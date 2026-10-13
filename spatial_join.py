"""Attach GIS context to each station and build district summaries.

  point-in-polygon     station -> district (ADM2) and province (ADM1)
  raster sample        Copernicus GLO-90 elevation at the station, checked against
                       the elevation in the station metadata
  buffer + overlay     5 km buffer: terrain relief and ESA WorldCover 2021 class shares
  nearest feature      distance to the nearest major river (HydroRIVERS, upstream
                       area >= 1,000 km2)
  zonal statistics     mean district elevation
  coverage             share of Nepal's area within 25 km of a station

Distances and buffers are computed in UTM 45N (EPSG:32645). Nepal spans UTM zones 44
and 45; for the western stations this distorts distances by well under 1%.

Outputs
  data/stations_gis.csv      stations with every attached attribute
  data/district_summary.csv  one row per district that contains a station
  data/coverage.csv          monitored area and districts
  data/gis/*.gpkg            station points, buffers, clipped rivers, districts
"""
from pathlib import Path
import math
import os

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.mask import mask
from rasterio.windows import from_bounds
from shapely.geometry import box

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "3")

ROOT = Path(__file__).parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data"
GIS = OUT / "gis"
UTM = "EPSG:32645"
BUFFER_M = 5_000
COVERAGE_M = 25_000
MAJOR_RIVER_SKM = 1_000
ELEV_TOLERANCE_M = 100

DEM_URL = ("/vsicurl/https://copernicus-dem-90m.s3.amazonaws.com/"
           "Copernicus_DSM_COG_30_N{lat:02d}_00_E{lon:03d}_00_DEM/"
           "Copernicus_DSM_COG_30_N{lat:02d}_00_E{lon:03d}_00_DEM.tif")
WC_URL = ("/vsicurl/https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
          "ESA_WorldCover_10m_2021_v200_N{lat:02d}E{lon:03d}_Map.tif")
WORLDCOVER = {10: "tree_cover", 20: "shrubland", 30: "grassland", 40: "cropland",
              50: "built_up", 60: "bare_sparse", 70: "snow_ice", 80: "water",
              90: "wetland", 95: "mangrove", 100: "moss_lichen"}


def dem_tile(lon, lat):
    return DEM_URL.format(lat=math.floor(lat), lon=math.floor(lon))


def wc_tile(lon, lat):
    return WC_URL.format(lat=3 * math.floor(lat / 3), lon=3 * math.floor(lon / 3))


def read_clip(url, geom_ll, scale=1):
    """Pixels of `url` inside geom_ll (EPSG:4326), optionally decimated via overviews."""
    with rasterio.open(url) as src:
        w = from_bounds(*geom_ll.bounds, transform=src.transform).round_offsets().round_lengths()
        shape = (max(1, int(w.height // scale)), max(1, int(w.width // scale)))
        arr = src.read(1, window=w, out_shape=shape, boundless=True, fill_value=0)
        t = src.window_transform(w) * rasterio.Affine.scale(w.width / shape[1], w.height / shape[0])
    from rasterio.features import geometry_mask
    inside = ~geometry_mask([geom_ll], out_shape=arr.shape, transform=t)
    return arr[inside]


def sample_point(url, lon, lat):
    with rasterio.open(url) as src:
        return float(next(src.sample([(lon, lat)]))[0])


def clip_by_tiles(tile_fn, geom_ll, scale=1, step=1):
    """read_clip across however many 1-deg (or 3-deg) tiles the geometry touches."""
    minx, miny, maxx, maxy = geom_ll.bounds
    vals = []
    for lat in range(math.floor(miny / step) * step, math.floor(maxy / step) * step + 1, step):
        for lon in range(math.floor(minx / step) * step, math.floor(maxx / step) * step + 1, step):
            part = geom_ll.intersection(box(lon, lat, lon + step, lat + step))
            if not part.is_empty:
                vals.append(read_clip(tile_fn(lon + 1e-6, lat + 1e-6), part, scale))
    return np.concatenate(vals) if vals else np.array([])


# Districts that the airports and towns named in the station list actually lie in.
EXPECTED_DISTRICT = {"44434099999": "Kaski", "44438099999": "Rupandehi", "44449099999": "Bara",
                     "44454099999": "Kathmandu", "44478099999": "Morang"}


def validate_boundaries(label, layer, pts):
    """Attribute and topology checks on a district layer before anything is joined to it."""
    j = gpd.sjoin(pts[["station_id", "geometry"]], layer[["district", "geometry"]],
                  how="left", predicate="within")
    got = j.drop_duplicates("station_id").set_index("station_id").district
    wrong = [sid for sid, want in EXPECTED_DISTRICT.items()
             if pd.notna(got.get(sid)) and got[sid] != want]
    return dict(
        layer=label,
        features=len(layer),
        expected_features=77,
        duplicate_names=int(layer.district.duplicated().sum()),
        invalid_geometries=int((~layer.is_valid).sum()),
        stations_outside_every_district=int(j.district.isna().sum()),
        surveyed_stations_in_wrong_district=len(wrong),
        crs=str(layer.crs),
        verdict=("pass" if len(layer) == 77 and not layer.district.duplicated().any()
                 and j.district.notna().all() and not wrong else "reject"),
    )


def main():
    GIS.mkdir(parents=True, exist_ok=True)
    st = pd.read_csv(OUT / "stations.csv", dtype={"station_id": str})
    pts = gpd.GeoDataFrame(st, geometry=gpd.points_from_xy(st.lon, st.lat), crs="EPSG:4326")

    # Two candidate district layers are checked; the one that passes is used.
    gb = gpd.read_file(RAW / "npl_adm2.geojson").rename(columns={"shapeName": "district"})
    cod = gpd.read_file(RAW / "cod" / "npl_admin2.geojson").rename(
        columns={"adm2_name": "district", "adm2_pcode": "district_pcode"})
    checks = pd.DataFrame([validate_boundaries("geoBoundaries gbOpen ADM2", gb, pts),
                           validate_boundaries("OCHA COD-AB ADM2 (Survey Dept.)", cod, pts)])
    checks.to_csv(OUT / "boundary_check.csv", index=False)
    print(checks.T.to_string())

    adm2 = cod[["district", "district_pcode", "geometry"]]
    adm1 = gpd.read_file(RAW / "cod" / "npl_admin1.geojson")[["adm1_name", "geometry"]].rename(
        columns={"adm1_name": "province"})
    nepal = adm1.dissolve().geometry.iloc[0]

    # point in polygon
    pts = gpd.sjoin(pts, adm2, how="left", predicate="within").drop(columns="index_right")
    pts = gpd.sjoin(pts, adm1, how="left", predicate="within").drop(columns="index_right")
    pts["inside_nepal"] = pts.within(nepal)

    # elevation check: DEM at the station vs the metadata elevation
    pts["dem_elev_m"] = [round(sample_point(dem_tile(x, y), x, y), 1)
                         for x, y in zip(pts.lon, pts.lat)]
    pts["elev_diff_m"] = (pts.dem_elev_m - pts.elev_m).round(1)
    pts["elev_check"] = np.where(pts.elev_diff_m.abs() <= ELEV_TOLERANCE_M, "pass", "review")

    # 5 km buffer: terrain and land cover
    buf = pts[["station_id", "name", "geometry"]].to_crs(UTM)
    buf["geometry"] = buf.buffer(BUFFER_M)
    buf_ll = buf.to_crs("EPSG:4326")
    terrain, cover = [], []
    for sid, g in zip(buf_ll.station_id, buf_ll.geometry):
        z = clip_by_tiles(dem_tile, g)
        terrain.append(dict(station_id=sid, buf_elev_mean_m=round(float(z.mean()), 0),
                            buf_elev_min_m=round(float(z.min()), 0),
                            buf_elev_max_m=round(float(z.max()), 0),
                            buf_relief_m=round(float(z.max() - z.min()), 0)))
        lc = clip_by_tiles(wc_tile, g, step=3)
        lc = lc[lc > 0]
        shares = {f"lc_{WORLDCOVER[k]}_pct": 0.0 for k in WORLDCOVER}
        for k, n in zip(*np.unique(lc, return_counts=True)):
            shares[f"lc_{WORLDCOVER[int(k)]}_pct"] = round(100 * n / lc.size, 1)
        shares["station_id"] = sid
        cover.append(shares)
        print(f"  buffer done: {sid}")
    pts = pts.merge(pd.DataFrame(terrain), on="station_id").merge(pd.DataFrame(cover), on="station_id")
    lc_cols = [c for c in pts.columns if c.startswith("lc_") and pts[c].sum() > 0]
    pts = pts.drop(columns=[c for c in pts.columns if c.startswith("lc_") and c not in lc_cols])
    pts["dominant_land_cover"] = (pts[lc_cols].idxmax(axis=1)
                                  .str.removeprefix("lc_").str.removesuffix("_pct"))

    # nearest major river
    rivers = gpd.read_file(
        RAW / "hydrorivers" / "HydroRIVERS_v10_as_shp" / "HydroRIVERS_v10_as.shp",
        bbox=nepal.buffer(0.3).bounds)
    rivers = rivers[rivers.UPLAND_SKM >= MAJOR_RIVER_SKM]
    rivers = rivers[rivers.intersects(nepal.buffer(0.3))]
    rivers_utm = rivers.to_crs(UTM)
    pts_utm = pts.to_crs(UTM)
    near = gpd.sjoin_nearest(pts_utm[["station_id", "geometry"]],
                             rivers_utm[["UPLAND_SKM", "DIS_AV_CMS", "geometry"]],
                             distance_col="dist_m")
    near = near.sort_values("dist_m").drop_duplicates("station_id")
    near = near.rename(columns={"UPLAND_SKM": "river_upland_km2",
                                "DIS_AV_CMS": "river_mean_discharge_m3s"})
    near["dist_major_river_km"] = (near.dist_m / 1000).round(2)
    pts = pts.merge(near[["station_id", "dist_major_river_km", "river_upland_km2",
                          "river_mean_discharge_m3s"]], on="station_id")

    # station climate: calendar-month climatology from valid months only, then annual
    mon = pd.read_csv(OUT / "monthly.csv", dtype={"station_id": str})
    mon = mon[mon.status == "valid"].copy()
    mon["cal_month"] = mon.month.str[5:7].astype(int)
    clim = mon.groupby(["station_id", "variable", "cal_month"]).value.mean().unstack("cal_month")
    rows = []
    for sid in pts.station_id:
        r = dict(station_id=sid)
        for var, key, how in (("precipitation", "annual_precip_mm", "sum"),
                              ("temperature", "annual_tmean_c", "mean"),
                              ("relative_humidity", "annual_rh_pct", "mean")):
            c = clim.loc[(sid, var)] if (sid, var) in clim.index else pd.Series(dtype=float)
            r[f"{key.split('_')[1]}_months_covered"] = int(c.notna().sum())
            r[key] = round(float(getattr(c, how)()), 1) if c.notna().sum() == 12 else np.nan
        pr = clim.loc[(sid, "precipitation")] if (sid, "precipitation") in clim.index else None
        r["monsoon_jjas_precip_mm"] = (round(float(pr[[6, 7, 8, 9]].sum()), 0)
                                       if pr is not None and pr[[6, 7, 8, 9]].notna().all() else np.nan)
        rows.append(r)
    pts = pts.merge(pd.DataFrame(rows), on="station_id")

    # district summaries: districts that contain a station
    d = adm2[adm2.district.isin(pts.district)].copy()
    d = d.merge(adm2.to_crs(UTM).assign(area_km2=lambda x: (x.area / 1e6).round(0))
                [["district", "area_km2"]], on="district")
    d["mean_elev_m"] = [round(float(clip_by_tiles(dem_tile, g, scale=4).mean()), 0)
                        for g in d.geometry]
    keep = ["district", "province", "name", "station_id", "elev_m", "dominant_land_cover",
            "dist_major_river_km", "annual_precip_mm", "monsoon_jjas_precip_mm",
            "annual_tmean_c", "annual_rh_pct"]
    ds = d.drop(columns="geometry").merge(pts[keep], on="district").rename(
        columns={"name": "station", "elev_m": "station_elev_m"})
    ds = ds.sort_values("station_elev_m")
    ds.to_csv(OUT / "district_summary.csv", index=False)

    # coverage: how much of Nepal is within 25 km of a station
    nepal_utm = gpd.GeoSeries([nepal], crs="EPSG:4326").to_crs(UTM).iloc[0]
    reach = pts_utm.buffer(COVERAGE_M).union_all().intersection(nepal_utm)
    cent = adm2.to_crs(UTM)
    cent["near"] = cent.centroid.distance(pts_utm.union_all()) <= COVERAGE_M
    cov = pd.DataFrame([dict(
        stations=len(pts), districts_total=len(adm2),
        districts_with_station=int(pts.district.nunique()),
        districts_centroid_within_25km=int(cent.near.sum()),
        nepal_area_km2=round(nepal_utm.area / 1e6),
        area_within_25km_km2=round(reach.area / 1e6),
        area_within_25km_pct=round(100 * reach.area / nepal_utm.area, 1),
        stations_above_2000m=int((pts.elev_m > 2000).sum()),
        nepal_area_above_2000m_pct=np.nan,
    )])
    z = clip_by_tiles(dem_tile, nepal, scale=8)
    cov["nepal_area_above_2000m_pct"] = round(100 * float((z > 2000).mean()), 1)
    cov.to_csv(OUT / "coverage.csv", index=False)

    out = pd.DataFrame(pts.drop(columns="geometry"))
    out.to_csv(OUT / "stations_gis.csv", index=False)
    pts.to_file(GIS / "stations.gpkg", driver="GPKG")
    buf_ll.to_file(GIS / "station_buffers_5km.gpkg", driver="GPKG")
    rivers[["HYRIV_ID", "UPLAND_SKM", "DIS_AV_CMS", "ORD_STRA", "geometry"]].clip(
        nepal.buffer(0.05)).to_file(GIS / "major_rivers.gpkg", driver="GPKG")
    gpd.GeoDataFrame(ds.merge(d[["district", "geometry"]], on="district"),
                     crs="EPSG:4326").to_file(GIS / "districts_with_station.gpkg", driver="GPKG")

    print(out[["name", "district", "province", "elev_m", "dem_elev_m", "elev_check",
               "buf_relief_m", "dominant_land_cover", "dist_major_river_km"]].to_string())
    print(ds.to_string())
    print(cov.T)


if __name__ == "__main__":
    main()
