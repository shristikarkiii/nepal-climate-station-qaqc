# Data dictionary

One entry per dataset: source, coverage, coordinate reference system, variables,
processing and known limitations. Inputs first, then outputs.

---

## Inputs

### NOAA GSOD daily summaries

| | |
| --- | --- |
| Source | NOAA NCEI, Global Surface Summary of the Day, `ncei.noaa.gov/data/global-summary-of-the-day/access/{year}/{station}.csv` |
| Coverage | 15 Nepal stations, 1 Jan 2022 – 31 Dec 2024; 12,338 of 16,440 possible station-days present |
| CRS | Geographic coordinates, WGS 84 (EPSG:4326) |
| Variables used | `TEMP`, `DEWP`, `MAX`, `MIN` (°F), `PRCP` (inches), their attribute flags, `LATITUDE`, `LONGITUDE`, `ELEVATION` |
| Missing codes | 9999.9 for temperatures, 99.99 for precipitation |
| Processing | `qaqc.py` |
| Limitations | Only stations that transmit WMO synoptic messages; most send 4–5 reports a day; precipitation assembled from those messages |

### NOAA ISD station history

| | |
| --- | --- |
| Source | `ncei.noaa.gov/pub/data/noaa/isd-history.csv` |
| Coverage | All ISD stations; filtered to country `NP` with a record ending on or after 1 Jan 2022 |
| CRS | EPSG:4326 |
| Variables used | `USAF`, `WBAN`, `STATION NAME`, `ICAO`, `LAT`, `LON`, `ELEV(M)`, `BEGIN`, `END` |
| Use | Reference list for station-ID validation and the coordinate cross-check |

### OCHA COD-AB Nepal administrative boundaries

| | |
| --- | --- |
| Source | OCHA / Survey Department of Nepal, via HDX (`cod-ab-npl`), version v02, valid from 14 Mar 2024 |
| Coverage | 7 provinces (`npl_admin1`), 77 districts (`npl_admin2`) |
| CRS | EPSG:4326 |
| Variables used | `adm2_name`, `adm2_pcode`, `adm1_name` |
| Use | District and province for each station; district area and mean elevation |
| License | CC BY-IGO |

### geoBoundaries gbOpen NPL ADM2

| | |
| --- | --- |
| Source | `github.com/wmgeolab/geoBoundaries`, gbOpen release |
| Use | **Evaluated and rejected** — 75 districts (pre-2017 set), 2 duplicate names, 1 station outside every polygon, Pokhara placed in Syangja. See `data/boundary_check.csv` |

### Copernicus DEM GLO-90

| | |
| --- | --- |
| Source | `copernicus-dem-90m.s3.amazonaws.com`, 1° cloud-optimised GeoTIFF tiles, read in place |
| Resolution | 3 arc-seconds (~90 m) |
| CRS | EPSG:4326, heights relative to EGM2008 |
| Use | Elevation at each station (coordinate check); mean, min, max and relief in 5 km buffers; district mean elevation (read at 4× decimation, ~360 m); share of Nepal above 2,000 m (8× decimation) |

### ESA WorldCover 2021 v200

| | |
| --- | --- |
| Source | `esa-worldcover.s3.eu-central-1.amazonaws.com`, 3° tiles, read in place |
| Resolution | 10 m |
| CRS | EPSG:4326 |
| Classes | 10 tree cover, 20 shrubland, 30 grassland, 40 cropland, 50 built-up, 60 bare/sparse, 70 snow/ice, 80 water, 90 wetland, 95 mangrove, 100 moss/lichen |
| Use | Class shares within each station's 5 km buffer |
| Limitations | Single year (2021); 76.7% global overall accuracy per the product validation report |

### HydroRIVERS v1.0 (Asia)

| | |
| --- | --- |
| Source | `data.hydrosheds.org`, HydroRIVERS_v10_as_shp |
| CRS | EPSG:4326 |
| Variables used | `UPLAND_SKM` (upstream area, km²), `DIS_AV_CMS` (modelled long-term mean discharge, m³/s), `ORD_STRA` |
| Use | Reaches with upstream area ≥ 1,000 km² within 0.3° of Nepal; nearest-reach distance for each station |
| Limitations | Derived from 15 arc-second hydrography; discharge is modelled, not gauged |

---

## Outputs

### `data/stations.csv`

Station metadata after ID and coordinate validation. One row per station.

| Column | Description |
| --- | --- |
| `station_id` | 11-character USAF + WBAN identifier |
| `name`, `icao` | Station name from ISD history; ICAO code for airports |
| `lat`, `lon` | Decimal degrees, WGS 84, as given in the GSOD files |
| `elev_m` | Station elevation from the GSOD files, m |
| `history_offset_km` | Distance between GSOD-file and ISD-history coordinates |
| `coord_precision` | `whole arc-minute` (rounded, up to ~1 km off) or `surveyed` |
| `record_begins`, `record_ends` | Period of record in ISD history, YYYYMMDD |

### `data/daily_clean.csv`

One row per station-day present in GSOD, after QA.

| Column | Unit | Description |
| --- | --- | --- |
| `station_id`, `date` | | |
| `tmax_c`, `tmin_c` | °C | Daily extremes; blank where NOAA derived them from fewer than 20 reports |
| `tobs_c` | °C | Mean of that day's reports (kept for comparison only) |
| `tmean_c` | °C | (Tmax + Tmin) / 2 — the value used downstream |
| `dewp_c` | °C | Mean dew point |
| `rh_pct` | % | Relative humidity from `tobs_c` and `dewp_c`, Magnus formula, capped at 100 |
| `prcp_mm` | mm | 24-hour precipitation; blank where the station sent no report (flag `I`) |
| `n_obs_temp` | count | Reports used for the day's mean temperature |

### `data/monthly.csv`

One row per station × month × variable: 15 × 36 × 3 = 1,620.

| Column | Description |
| --- | --- |
| `variable`, `unit` | `precipitation` (mm, monthly total), `temperature` (°C, mean), `relative_humidity` (%, mean) |
| `value` | Blank unless `status` is `valid` |
| `days_in_month`, `days_observed` | Denominator and numerator of completeness |
| `longest_gap_days` | Longest run of consecutive missing days |
| `status` | `valid`, `incomplete`, or `no data` |
| `rule` | The completeness rule applied |

### `data/qa_log.csv` and `data/qa_summary.csv`

`qa_log.csv` has one row per affected value: `check`, `station_id`, `date`, `field`, the
original `value`, and the `action` (`set missing`, `dropped`, or `kept, review`).
`qa_summary.csv` counts rows by check and action.

### `data/stations_gis.csv`

`stations.csv` plus:

| Column | Description |
| --- | --- |
| `district`, `district_pcode`, `province` | From COD-AB, point-in-polygon |
| `dem_elev_m`, `elev_diff_m`, `elev_check` | DEM elevation at the station; DEM minus metadata; `pass` within ±100 m, else `review` |
| `buf_elev_mean_m`, `buf_elev_min_m`, `buf_elev_max_m`, `buf_relief_m` | DEM statistics in the 5 km buffer |
| `lc_*_pct`, `dominant_land_cover` | WorldCover class shares in the 5 km buffer (classes absent from every buffer are dropped) |
| `dist_major_river_km`, `river_upland_km2`, `river_mean_discharge_m3s` | Nearest HydroRIVERS reach with ≥ 1,000 km² upstream area |
| `precip_months_covered`, `tmean_months_covered`, `rh_months_covered` | Calendar months (of 12) with at least one valid month |
| `annual_precip_mm`, `annual_tmean_c`, `annual_rh_pct` | Only where all 12 calendar months are covered |
| `monsoon_jjas_precip_mm` | Sum of June–September calendar-month means, where all four are covered |

### `data/district_summary.csv`

The 15 districts that contain a station: `district`, `district_pcode`, `province`,
`area_km2` (UTM 45N), `mean_elev_m` (DEM), and the station's name, elevation, dominant land
cover, distance to a major river and climate fields.

### `data/boundary_check.csv`, `data/coverage.csv`, `data/lapse_rate.csv`

Boundary-layer validation; network coverage (districts with a station, area within 25 km,
share of Nepal above 2,000 m); temperature lapse rate by calendar month and annual
(slope in °C/km, intercept, R², station count).

### `data/gis/`

| File | Geometry | CRS |
| --- | --- | --- |
| `stations.gpkg` | Points, all `stations_gis.csv` attributes | EPSG:4326 |
| `station_buffers_5km.gpkg` | 5 km buffers built in EPSG:32645 | EPSG:4326 |
| `major_rivers.gpkg` | HydroRIVERS reaches ≥ 1,000 km², clipped to Nepal | EPSG:4326 |
| `districts_with_station.gpkg` | COD-AB polygons with `district_summary.csv` attributes | EPSG:4326 |

Distances, areas and buffers are computed in UTM zone 45N (EPSG:32645). Western Nepal lies
in zone 44; the scale error there is under 1%.
