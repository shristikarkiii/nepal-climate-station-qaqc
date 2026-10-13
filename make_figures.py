"""Maps, charts and summary tables for the technical note.

Reads the outputs of qaqc.py and spatial_join.py; writes figures/ and data/lapse_rate.csv.
"""
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

ROOT = Path(__file__).parent
DATA = ROOT / "data"
FIG = ROOT / "figures"
UTM = "EPSG:32645"

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
INK_3 = "#8a8983"
GRID = "#e4e3df"
BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
RIVER = "#6da7ec"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "font.family": "DejaVu Sans", "font.size": 9, "text.color": INK,
    "axes.edgecolor": INK_3, "axes.labelcolor": INK_2, "xtick.color": INK_2,
    "ytick.color": INK_2, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": False, "axes.titlesize": 10, "axes.titleweight": "bold",
    "axes.titlelocation": "left",
})

MONTHS = "J F M A M J J A S O N D".split()


def short(name):
    return (name.replace(" Intl", "").replace(" Airport", "").replace(" (Atariya)", "")
            .replace(" / Gautam Buddha", "").replace("Tribhuvan", "Kathmandu"))


def load():
    st = pd.read_csv(DATA / "stations_gis.csv", dtype={"station_id": str})
    st["label"] = st.name.map(short)
    mon = pd.read_csv(DATA / "monthly.csv", dtype={"station_id": str})
    return st, mon


def climatology(mon):
    v = mon[mon.status == "valid"].copy()
    v["cal_month"] = v.month.str[5:7].astype(int)
    return v.groupby(["station_id", "variable", "cal_month"]).value.mean().unstack("cal_month")


# ------------------------------------------------------------------------ fig 1

def fig_map(st):
    adm2 = gpd.read_file(DATA / "raw" / "cod" / "npl_admin2.geojson").to_crs(UTM)
    adm1 = gpd.read_file(DATA / "raw" / "cod" / "npl_admin1.geojson").to_crs(UTM)
    rivers = gpd.read_file(DATA / "gis" / "major_rivers.gpkg").to_crs(UTM)
    pts = gpd.GeoDataFrame(st, geometry=gpd.points_from_xy(st.lon, st.lat),
                           crs="EPSG:4326").to_crs(UTM)

    fig, ax = plt.subplots(figsize=(10, 5.6))
    monitored = adm2[adm2.adm2_name.isin(st.district)]
    adm2.plot(ax=ax, facecolor=SURFACE, edgecolor=GRID, linewidth=0.5)
    monitored.plot(ax=ax, facecolor="#f0efec", edgecolor=GRID, linewidth=0.5)
    pts.buffer(25_000).plot(ax=ax, facecolor="none", edgecolor=INK_3, linewidth=0.6,
                            linestyle=(0, (2, 2)))
    adm1.boundary.plot(ax=ax, color=INK_3, linewidth=0.9)
    lw = np.interp(np.log10(rivers.UPLAND_SKM), [3, 5.3], [0.4, 2.2])
    rivers.plot(ax=ax, color=RIVER, linewidth=lw)

    bins = [0, 600, 900, 1200, 1500, 2000, 3500]
    cmap = ListedColormap(BLUE[1:])
    norm = BoundaryNorm(bins, cmap.N)
    has = pts.monsoon_jjas_precip_mm.notna()
    ax.scatter(pts[has].geometry.x, pts[has].geometry.y, s=70, c=pts[has].monsoon_jjas_precip_mm,
               cmap=cmap, norm=norm, edgecolor=SURFACE, linewidth=2, zorder=5)
    ax.scatter(pts[~has].geometry.x, pts[~has].geometry.y, s=70, facecolor=SURFACE,
               edgecolor=INK_2, linewidth=1.2, zorder=5)
    # label offsets (dx, dy in m) chosen by eye so no two labels collide
    offset = {"Dadeldhura": (-12_000, 9_000, "right"), "Dipayal": (12_000, 9_000, "left"),
              "Dhankuta": (-12_000, 0, "right"), "Biratnagar": (0, -14_000, "center"),
              "Dang": (0, -14_000, "center"), "Bhairahawa": (0, -14_000, "center"),
              "Nepalgunj": (0, -14_000, "center")}
    for _, r in pts.iterrows():
        dx, dy, ha = offset.get(r.label, (0, 9_000, "center"))
        ax.annotate(r.label, (r.geometry.x + dx, r.geometry.y + dy), ha=ha,
                    va="top" if dy < 0 else ("bottom" if dy > 0 else "center"),
                    fontsize=7.5, color=INK, zorder=6)

    ax.set_axis_off()
    ax.set_title("Monitoring stations, monsoon rainfall (Jun-Sep) and 25 km coverage", pad=8)
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    cb = fig.colorbar(sm, ax=ax, orientation="horizontal", fraction=0.035, pad=0.02,
                      aspect=40, shrink=0.45, anchor=(0.05, 1))
    cb.set_label("Mean Jun-Sep precipitation, 2022-2024 (mm)", color=INK_2)
    cb.outline.set_visible(False)
    ax.legend(handles=[
        Line2D([], [], marker="o", ls="", mfc=SURFACE, mec=INK_2, ms=7,
               label="Station, monsoon months incomplete"),
        Line2D([], [], color=INK_3, lw=0.6, ls=(0, (2, 2)), label="25 km from a station"),
        Patch(facecolor="#f0efec", edgecolor=GRID, label="District with a station"),
        Line2D([], [], color=RIVER, lw=1.5, label="River, upstream area > 1,000 km²"),
        Line2D([], [], color=INK_3, lw=0.9, label="Province boundary"),
    ], loc="upper right", frameon=False, fontsize=7.5)
    fig.text(0.01, 0.01, "Stations: NOAA GSOD. Boundaries: OCHA COD-AB / Survey Department of "
             "Nepal. Rivers: HydroRIVERS v1.0. UTM 45N.", fontsize=7, color=INK_3)
    fig.savefig(FIG / "fig1_station_map.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------------------------------ fig 2

def fig_completeness(st, mon):
    order = st.sort_values("lon").station_id.tolist()
    labels = st.set_index("station_id").loc[order, "label"]
    code = {"no data": 0, "incomplete": 1, "valid": 2}
    fig, axes = plt.subplots(1, 3, figsize=(11, 4.2), sharey=True)
    cmap = ListedColormap(["#f0efec", BLUE[1], BLUE[5]])
    for ax, var in zip(axes, ["precipitation", "temperature", "relative_humidity"]):
        m = mon[mon.variable == var].pivot(index="station_id", columns="month", values="status")
        m = m.loc[order].replace(code).astype(int)
        ax.imshow(m.values, aspect="auto", cmap=cmap, vmin=0, vmax=2, interpolation="none")
        # 2 px surface gap between cells
        ax.set_xticks(np.arange(-0.5, m.shape[1]), minor=True)
        ax.set_yticks(np.arange(-0.5, m.shape[0]), minor=True)
        ax.grid(which="minor", color=SURFACE, linewidth=1.2)
        ax.tick_params(which="minor", length=0)
        ax.set_xticks([0, 12, 24], ["2022", "2023", "2024"])
        ax.set_yticks(range(len(order)), labels)
        valid = (mon[mon.variable == var].status == "valid").mean()
        ax.set_title(f"{var.replace('_', ' ').capitalize()}  ·  {valid:.0%} valid", fontsize=9)
        for s in ax.spines.values():
            s.set_visible(False)
    axes[0].set_ylabel("Station (west to east)")
    fig.legend(handles=[Patch(color=BLUE[5], label="Valid month"),
                        Patch(color=BLUE[1], label="Incomplete (fails completeness rule)"),
                        Patch(color="#f0efec", label="No data")],
               loc="lower center", ncol=3, frameon=False, bbox_to_anchor=(0.5, -0.04))
    fig.suptitle("Monthly completeness after QA/QC", x=0.01, ha="left", fontweight="bold",
                 fontsize=10)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(FIG / "fig2_completeness.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------------------------------ fig 3

def fig_climatology(st, mon):
    clim = climatology(mon)
    order = st.sort_values("elev_m").station_id.tolist()
    lab = st.set_index("station_id").label
    fig, axes = plt.subplots(3, 5, figsize=(11, 6), sharex=True, sharey=True)
    for ax, sid in zip(axes.flat, order):
        p = clim.loc[(sid, "precipitation")] if (sid, "precipitation") in clim.index else None
        x = np.arange(1, 13)
        vals = p.reindex(x).values if p is not None else np.full(12, np.nan)
        ax.bar(x, np.nan_to_num(vals), width=0.72, color=BLUE[4], linewidth=0)
        for xi in x[np.isnan(vals)]:
            ax.text(xi, 12, "–", ha="center", va="bottom", color=INK_3, fontsize=8)
        e = st.set_index("station_id").loc[sid, "elev_m"]
        ax.set_title(f"{lab[sid]}  {e:,.0f} m", fontsize=8.5, fontweight="normal")
        ax.set_xticks(x, MONTHS, fontsize=7)
        ax.yaxis.grid(True, color=GRID, linewidth=0.6)
        ax.set_axisbelow(True)
        ax.tick_params(length=0)
    for ax in axes[:, 0]:
        ax.set_ylabel("mm / month")
    fig.suptitle("Monthly precipitation, mean of valid months 2022-2024, stations by elevation"
                 "   (– = no valid month)", x=0.01, ha="left", fontweight="bold", fontsize=10)
    fig.tight_layout()
    fig.savefig(FIG / "fig3_precip_climatology.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------------------------------ fig 4

def lapse_rate(st, mon):
    """Temperature lapse rate from station means: per calendar month, and annual."""
    clim = climatology(mon)
    t = clim.xs("temperature", level="variable")
    elev = st.set_index("station_id").elev_m
    rows = []
    for m in range(1, 13):
        s = t[m].dropna()
        k, b = np.polyfit(elev[s.index] / 1000, s.values, 1)
        r = np.corrcoef(elev[s.index], s.values)[0, 1]
        rows.append(dict(period=MONTHS[m - 1] + f"{m:02d}", stations=len(s),
                         lapse_c_per_km=round(k, 2), intercept_c=round(b, 2), r2=round(r * r, 3)))
    full = t.dropna()
    ann = full.mean(axis=1)
    k, b = np.polyfit(elev[ann.index] / 1000, ann.values, 1)
    r = np.corrcoef(elev[ann.index], ann.values)[0, 1]
    rows.append(dict(period="annual", stations=len(ann), lapse_c_per_km=round(k, 2),
                     intercept_c=round(b, 2), r2=round(r * r, 3)))
    lr = pd.DataFrame(rows)
    lr.to_csv(DATA / "lapse_rate.csv", index=False)
    return lr, ann


def fig_temperature(st, mon):
    lr, ann = lapse_rate(st, mon)
    s = st.set_index("station_id")
    a = lr[lr.period == "annual"].iloc[0]
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(10.5, 4), gridspec_kw=dict(width_ratios=[1.3, 1]))
    x = s.loc[ann.index, "elev_m"]
    ax.scatter(x, ann, s=40, color=SERIES[0], edgecolor=SURFACE, linewidth=1.5, zorder=3)
    xx = np.array([0, 2500])
    ax.plot(xx, a.intercept_c + a.lapse_c_per_km * xx / 1000, color=INK_3, lw=1, zorder=2)
    # label the spread-out hill and mountain stations; the Terai cluster stays unlabelled
    for sid in ann.index[x[ann.index] > 800]:
        ax.annotate(s.loc[sid, "label"], (x[sid], ann[sid]), xytext=(5, 2),
                    textcoords="offset points", fontsize=7, color=INK_2)
    ax.annotate("Terai and valley stations below 800 m", (300, 25.6), fontsize=7, color=INK_2)
    ax.set_xlabel("Station elevation (m)")
    ax.set_ylabel("Mean temperature, (Tmax+Tmin)/2 (°C)")
    ax.set_title(f"Annual mean temperature falls {abs(a.lapse_c_per_km):.1f} °C per km "
                 f"(R² {a.r2:.2f}, {int(a.stations)} stations)")
    ax.yaxis.grid(True, color=GRID, lw=0.6)
    ax.set_axisbelow(True)

    m = lr[lr.period != "annual"]
    ax2.bar(range(12), -m.lapse_c_per_km, width=0.7, color=SERIES[0], linewidth=0)
    ax2.set_xticks(range(12), MONTHS)
    ax2.set_ylabel("Lapse rate (°C per km)")
    ax2.set_title("Steepest before the monsoon, shallowest in winter")
    ax2.yaxis.grid(True, color=GRID, lw=0.6)
    ax2.set_axisbelow(True)
    ax2.tick_params(length=0)
    fig.tight_layout()
    fig.savefig(FIG / "fig4_temperature_elevation.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    return lr


# ------------------------------------------------------------------------ fig 5

def fig_elevation_check(st):
    fig, ax = plt.subplots(figsize=(5.2, 4.6))
    lim = [0, 3000]
    ax.fill_between(lim, [lim[0] - 100, lim[1] - 100], [lim[0] + 100, lim[1] + 100],
                    color="#f0efec", linewidth=0)
    ax.plot(lim, lim, color=INK_3, lw=0.8)
    ok = st.elev_check == "pass"
    ax.scatter(st[ok].elev_m, st[ok].dem_elev_m, s=36, color=SERIES[0], edgecolor=SURFACE,
               linewidth=1.5, zorder=3, label="Within ±100 m")
    ax.scatter(st[~ok].elev_m, st[~ok].dem_elev_m, s=48, color=SERIES[1], marker="D",
               edgecolor=SURFACE, linewidth=1.5, zorder=3, label="Flagged for review")
    for _, r in st[~ok].iterrows():
        ax.annotate(f"{r.label}  {r.elev_diff_m:+.0f} m", (r.elev_m, r.dem_elev_m),
                    xytext=(-8, 6), textcoords="offset points", ha="right", fontsize=8)
    ax.set_xlim(lim)
    ax.set_ylim(lim)
    ax.set_xlabel("Elevation in station metadata (m)")
    ax.set_ylabel("Copernicus DEM at station coordinates (m)")
    ax.set_title("Coordinate check against the DEM")
    ax.legend(frameon=False, loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG / "fig5_elevation_check.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------------------------------ fig 6

def fig_landcover(st):
    groups = {
        "Tree cover": ["lc_tree_cover_pct"],
        "Cropland": ["lc_cropland_pct"],
        "Built-up": ["lc_built_up_pct"],
        "Grass & shrub": ["lc_grassland_pct", "lc_shrubland_pct"],
        "Other": ["lc_bare_sparse_pct", "lc_water_pct", "lc_snow_ice_pct", "lc_wetland_pct",
                  "lc_moss_lichen_pct"],
    }
    s = st.sort_values("elev_m", ascending=False).reset_index(drop=True)
    lc = pd.DataFrame({g: s[[c for c in cols if c in s]].sum(axis=1) for g, cols in groups.items()})
    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    left = np.zeros(len(s))
    for (g, col), color in zip(lc.items(), SERIES):
        ax.barh(range(len(s)), col, left=left, color=color, height=0.72,
                edgecolor=SURFACE, linewidth=1, label=g)
        for i, (l, w) in enumerate(zip(left, col)):
            if w >= 12:
                ax.text(l + w / 2, i, f"{w:.0f}", ha="center", va="center", fontsize=7,
                        color="white" if g in ("Tree cover", "Cropland") else INK)
        left += col.values
    ax.set_yticks(range(len(s)), [f"{l}  {e:,.0f} m" for l, e in zip(s.label, s.elev_m)])
    ax.set_xlim(0, 100)
    ax.set_xlabel("Share of 5 km buffer (%)")
    ax.set_title("Land cover around each station, ESA WorldCover 2021")
    ax.legend(ncol=5, frameon=False, loc="lower center", bbox_to_anchor=(0.4, -0.22), fontsize=8)
    ax.tick_params(length=0)
    ax.spines["left"].set_visible(False)
    fig.tight_layout()
    fig.savefig(FIG / "fig6_landcover.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def main():
    FIG.mkdir(exist_ok=True)
    st, mon = load()
    fig_map(st)
    fig_completeness(st, mon)
    fig_climatology(st, mon)
    lr = fig_temperature(st, mon)
    fig_elevation_check(st)
    fig_landcover(st)
    print(lr.to_string(index=False))


if __name__ == "__main__":
    main()
