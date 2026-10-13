"""Validate, standardise and aggregate the GSOD daily records to station-months.

Every check writes one row per affected value to data/qa_log.csv, so each value that
was changed or removed can be traced back to the rule that removed it.

Outputs
  data/stations.csv      station metadata after ID and coordinate validation
  data/daily_clean.csv   daily values in SI units, after QA
  data/monthly.csv       one row per station x month x variable, with completeness
  data/qa_log.csv        every flagged value and the action taken
  data/qa_summary.csv    counts by check
"""
from pathlib import Path
import math

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data"
YEARS = [2022, 2023, 2024]

MISSING = {"TEMP": 9999.9, "DEWP": 9999.9, "MAX": 9999.9, "MIN": 9999.9, "PRCP": 99.99}

# Monthly completeness rules
TEMP_MAX_MISSING = 10        # WMO: a monthly mean is invalid with 11+ missing days ...
TEMP_MAX_CONSEC = 4          # ... or 5+ consecutive missing days
PRCP_MIN_FRACTION = 0.90     # a monthly total needs >= 90% of days observed
MIN_OBS_FOR_DERIVED_EXTREME = 20   # reports/day before a derived Tmax/Tmin is trusted

log = []


def flag(check, station, date, field, value, action):
    log.append(dict(check=check, station_id=station, date=date, field=field,
                    value=value, action=action))


def f_to_c(f):
    return (f - 32.0) * 5.0 / 9.0


def rh_magnus(t, td):
    """Relative humidity (%) from air and dew-point temperature (degC), Magnus form."""
    a, b = 17.625, 243.04
    return 100.0 * np.exp(a * td / (b + td)) / np.exp(a * t / (b + t))


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


# --------------------------------------------------------------------------- load

def load_history():
    h = pd.read_csv(RAW / "isd-history.csv", dtype=str)
    h["station_id"] = h["USAF"] + h["WBAN"]
    return h.set_index("station_id")


def load_raw():
    frames = []
    for year in YEARS:
        for path in sorted((RAW / "gsod" / str(year)).glob("*.csv")):
            df = pd.read_csv(path, dtype={"STATION": str}, keep_default_na=False)
            df["source_file"] = f"{year}/{path.name}"
            df["file_station"] = path.stem
            df["file_year"] = year
            frames.append(df)
    return pd.concat(frames, ignore_index=True)


# ------------------------------------------------------------------ record checks

def check_station_ids(d, hist):
    bad = d["STATION"] != d["file_station"]
    for _, r in d[bad].iterrows():
        flag("station_id_mismatch", r.file_station, r.DATE, "STATION", r.STATION, "dropped")
    d = d[~bad]
    unknown = ~d["STATION"].isin(hist.index)
    for sid in d.loc[unknown, "STATION"].unique():
        flag("station_id_unknown", sid, "", "STATION", sid, "dropped")
    return d[~unknown]


def check_dates(d):
    d = d.copy()
    d["date"] = pd.to_datetime(d["DATE"], format="%Y-%m-%d", errors="coerce")
    bad = d["date"].isna() | (d["date"].dt.year != d["file_year"])
    for _, r in d[bad].iterrows():
        flag("date_invalid_or_outside_file_year", r.STATION, r.DATE, "DATE", r.DATE, "dropped")
    return d[~bad]


def check_duplicates(d):
    dup = d.duplicated(["STATION", "date"], keep="first")
    for _, r in d[dup].iterrows():
        flag("duplicate_station_date", r.STATION, r.DATE, "", "", "dropped (kept first)")
    return d[~dup]


def station_metadata(d, hist):
    """One row per station; compare the coordinates in the data files to the station
    history and record any station whose position is inconsistent across files."""
    rows = []
    for sid, g in d.groupby("STATION"):
        h = hist.loc[sid]
        lat = pd.to_numeric(g["LATITUDE"]).round(6)
        lon = pd.to_numeric(g["LONGITUDE"]).round(6)
        elev = pd.to_numeric(g["ELEVATION"])
        if lat.nunique() > 1 or lon.nunique() > 1:
            flag("coordinates_vary_between_files", sid, "", "LATITUDE/LONGITUDE",
                 f"{lat.nunique()} lat, {lon.nunique()} lon values", "used most frequent")
        lat0, lon0, elev0 = lat.mode()[0], lon.mode()[0], elev.mode()[0]
        offset = haversine_km(lat0, lon0, float(h.LAT), float(h.LON))
        if offset > 1.0:
            flag("coordinates_differ_from_station_history", sid, "", "LATITUDE/LONGITUDE",
                 f"{offset:.2f} km", "kept data-file position")
        whole_minutes = all(abs(v * 60 - round(v * 60)) < 1e-3 for v in (lat0, lon0))
        rows.append(dict(
            station_id=sid,
            name=h["STATION NAME"].title(),
            icao=h.ICAO if isinstance(h.ICAO, str) else "",
            lat=lat0, lon=lon0, elev_m=elev0,
            history_offset_km=round(offset, 3),
            coord_precision=("whole arc-minute (up to ~1 km off)" if whole_minutes
                             else "surveyed (sub-arc-second)"),
            record_begins=h.BEGIN, record_ends=h.END,
        ))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------- value checks

def standardise(d):
    """Replace sentinel codes with NaN, convert to SI units, apply physical checks."""
    d = d.copy()
    for col, code in MISSING.items():
        raw = pd.to_numeric(d[col].astype(str).str.strip(), errors="coerce")
        miss = raw.isna() | np.isclose(raw, code)
        for _, r in d[miss].iterrows():
            flag("missing_value_code", r.STATION, r.DATE, col, r[col], "set missing")
        d[col] = raw.where(~miss)
        d[f"{col}_missing_code"] = miss

    # GSOD precipitation flag I: the station sent no precipitation report that day,
    # so a 0.00 there is not an observed zero.
    pflag = d["PRCP_ATTRIBUTES"].astype(str).str.strip()
    no_report = (pflag == "I") & d["PRCP"].notna()
    for _, r in d[no_report].iterrows():
        flag("precip_flag_I_no_report", r.STATION, r.DATE, "PRCP", r.PRCP, "set missing")
    d.loc[no_report, "PRCP"] = np.nan

    out = pd.DataFrame({
        "station_id": d["STATION"].values,
        "date": d["date"].values,
        "tmax_c": f_to_c(d["MAX"]).round(2).values,
        "tmin_c": f_to_c(d["MIN"]).round(2).values,
        "tobs_c": f_to_c(d["TEMP"]).round(2).values,
        "dewp_c": f_to_c(d["DEWP"]).round(2).values,
        "prcp_mm": (d["PRCP"] * 25.4).round(1).values,
        "n_obs_temp": pd.to_numeric(d["TEMP_ATTRIBUTES"], errors="coerce").values,
        "tmax_from_hourly": (d["MAX_ATTRIBUTES"].astype(str).str.strip() == "*").values,
        "tmin_from_hourly": (d["MIN_ATTRIBUTES"].astype(str).str.strip() == "*").values,
    })

    def drop(mask, check, fields):
        for _, r in out[mask].iterrows():
            for fld in fields:
                flag(check, r.station_id, r.date.date().isoformat(), fld, r[fld], "set missing")
        out.loc[mask, fields] = np.nan

    # Tmax/Tmin flagged '*' were derived by NOAA from the station's own reports rather
    # than read from its max/min thermometers. With hourly reports (Tribhuvan) that is a
    # fair estimate; with the 4-5 synoptic reports a day most stations send, the true
    # extreme is usually missed, so those are not used.
    sparse = out.n_obs_temp < MIN_OBS_FOR_DERIVED_EXTREME
    drop(out.tmax_from_hourly & sparse & out.tmax_c.notna(),
         "tmax_derived_from_too_few_reports", ["tmax_c"])
    drop(out.tmin_from_hourly & sparse & out.tmin_c.notna(),
         "tmin_derived_from_too_few_reports", ["tmin_c"])

    drop((out.tmax_c < -40) | (out.tmax_c > 50), "tmax_out_of_range", ["tmax_c"])
    drop((out.tmin_c < -40) | (out.tmin_c > 40), "tmin_out_of_range", ["tmin_c"])
    drop(out.tmin_c > out.tmax_c, "tmin_exceeds_tmax", ["tmax_c", "tmin_c"])
    drop(out.dewp_c > out.tobs_c + 0.5, "dewpoint_exceeds_air_temperature", ["dewp_c"])
    drop(out.prcp_mm < 0, "precip_negative", ["prcp_mm"])

    # Day-to-day jumps are flagged for review but kept: a 15 degC swing can be real
    # at a mountain station during a western disturbance.
    out = out.sort_values(["station_id", "date"])
    for col in ("tmax_c", "tmin_c"):
        jump = out.groupby("station_id")[col].diff().abs() > 15
        for _, r in out[jump].iterrows():
            flag(f"{col}_day_to_day_jump_gt_15C", r.station_id, r.date.date().isoformat(),
                 col, r[col], "kept, review")
    heavy = out.prcp_mm > 300
    for _, r in out[heavy].iterrows():
        flag("precip_gt_300mm_day", r.station_id, r.date.date().isoformat(),
             "prcp_mm", r.prcp_mm, "kept, review")

    out["tmean_c"] = ((out.tmax_c + out.tmin_c) / 2).round(2)
    out["rh_pct"] = rh_magnus(out.tobs_c, out.dewp_c).clip(upper=100).round(1)
    return out


# --------------------------------------------------------------------- monthly

def longest_gap(present):
    run = best = 0
    for p in present:
        run = 0 if p else run + 1
        best = max(best, run)
    return best


def monthly(daily, stations):
    months = pd.period_range(f"{YEARS[0]}-01", f"{YEARS[-1]}-12", freq="M")
    rows = []
    for sid in stations.station_id:
        g = daily[daily.station_id == sid].set_index("date")
        for m in months:
            days = pd.date_range(m.start_time, m.end_time.normalize(), freq="D")
            s = g.reindex(days)
            for var, col, how in (("precipitation", "prcp_mm", "sum"),
                                  ("temperature", "tmean_c", "mean"),
                                  ("relative_humidity", "rh_pct", "mean")):
                present = s[col].notna().values
                n, gap = int(present.sum()), longest_gap(present)
                if how == "sum":
                    ok = n >= PRCP_MIN_FRACTION * len(days)
                    rule = f"needs >= {math.ceil(PRCP_MIN_FRACTION * len(days))} of {len(days)} days"
                else:
                    ok = (len(days) - n) <= TEMP_MAX_MISSING and gap <= TEMP_MAX_CONSEC
                    rule = "WMO: <= 10 missing days and <= 4 consecutive"
                value = getattr(s[col], how)() if n else np.nan
                rows.append(dict(
                    station_id=sid, month=str(m), variable=var,
                    unit={"precipitation": "mm", "temperature": "degC",
                          "relative_humidity": "%"}[var],
                    value=round(float(value), 2) if ok else np.nan,
                    days_in_month=len(days), days_observed=n, longest_gap_days=gap,
                    status="valid" if ok else ("no data" if n == 0 else "incomplete"),
                    rule=rule,
                ))
    return pd.DataFrame(rows)


def main():
    hist = load_history()
    raw = load_raw()
    n_raw = len(raw)
    d = check_station_ids(raw, hist)
    d = check_dates(d)
    d = check_duplicates(d)
    stations = station_metadata(d, hist)
    daily = standardise(d)
    mon = monthly(daily, stations)

    stations.to_csv(OUT / "stations.csv", index=False)
    daily.drop(columns=["tmax_from_hourly", "tmin_from_hourly"]).to_csv(
        OUT / "daily_clean.csv", index=False, date_format="%Y-%m-%d")
    mon.to_csv(OUT / "monthly.csv", index=False)
    qa = pd.DataFrame(log)
    qa.to_csv(OUT / "qa_log.csv", index=False)
    summary = (qa.groupby(["check", "action"]).size().rename("values_affected")
               .reset_index().sort_values("values_affected", ascending=False))
    summary.to_csv(OUT / "qa_summary.csv", index=False)

    possible = len(stations) * len(YEARS) * 365 + len(stations)  # 2024 is a leap year
    print(f"{n_raw} daily rows read from {raw.source_file.nunique()} files "
          f"({n_raw / possible:.1%} of {possible} possible station-days)")
    print(f"{len(stations)} stations, {len(mon)} station-month-variable records, "
          f"{(mon.status == 'valid').sum()} valid")
    print(mon.groupby(["variable", "status"]).size().unstack(fill_value=0))
    print(summary.to_string(index=False))
    # How far is the mean of the synoptic reports from the (Tmax+Tmin)/2 daily mean?
    bias = (daily.tobs_c - daily.tmean_c).dropna()
    print(f"mean of synoptic reports minus (Tmax+Tmin)/2: {bias.mean():+.2f} degC "
          f"(n={len(bias)})")


if __name__ == "__main__":
    main()
