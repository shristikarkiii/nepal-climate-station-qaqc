"""Download every public input the pipeline uses, into data/raw/.

  - NOAA ISD station history (station IDs, names, coordinates, periods of record)
  - NOAA GSOD daily summaries for Nepal stations active 2022-2024
  - OCHA COD-AB Nepal districts and provinces (Survey Department of Nepal)
  - geoBoundaries gbOpen Nepal districts, kept only to show why it was rejected
  - HydroRIVERS v1.0 Asia river network

The DEM (Copernicus GLO-90) and land cover (ESA WorldCover 2021) are cloud-optimised
GeoTIFFs read in place by spatial_join.py, so they are not downloaded here.
Files already present are not fetched again.
"""
from pathlib import Path
import csv
import zipfile

import requests

RAW = Path(__file__).parent / "data" / "raw"
YEARS = [2022, 2023, 2024]

ISD_HISTORY = "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv"
GSOD = "https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/{year}/{sid}.csv"
GB = "https://github.com/wmgeolab/geoBoundaries/raw/main/releaseData/gbOpen/NPL/{lvl}/geoBoundaries-NPL-{lvl}.geojson"
COD_AB = ("https://data.humdata.org/dataset/07db728a-4f0f-4e98-8eb0-8fa9df61f01c/resource/"
          "dea34e50-37d5-4e36-98ae-2b7b1b4c43de/download/npl_admin_boundaries.geojson.zip")
HYDRORIVERS = "https://data.hydrosheds.org/file/HydroRIVERS/HydroRIVERS_v10_as_shp.zip"


def get(url, dest):
    if dest.exists():
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(url, timeout=300, stream=True)
    if r.status_code != 200:
        print(f"  not available: {url}")
        return False
    with open(dest, "wb") as f:
        for chunk in r.iter_content(1 << 20):
            f.write(chunk)
    print(f"  {dest.relative_to(RAW)}")
    return True


def nepal_stations(path):
    """Stations in Nepal whose record runs into the analysis period."""
    with open(path, newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["CTRY"] == "NP"]
    return [r["USAF"] + r["WBAN"] for r in rows if r["END"] >= f"{YEARS[0]}0101"]


def main():
    get(ISD_HISTORY, RAW / "isd-history.csv")
    stations = nepal_stations(RAW / "isd-history.csv")
    print(f"{len(stations)} Nepal stations active since {YEARS[0]}")
    for year in YEARS:
        for sid in stations:
            get(GSOD.format(year=year, sid=sid), RAW / "gsod" / str(year) / f"{sid}.csv")
    get(GB.format(lvl="ADM2"), RAW / "npl_adm2.geojson")
    if get(COD_AB, RAW / "cod_npl.geojson.zip") and not (RAW / "cod").exists():
        with zipfile.ZipFile(RAW / "cod_npl.geojson.zip") as z:
            z.extractall(RAW / "cod", members=[m for m in z.namelist()
                                                if m in ("npl_admin1.geojson", "npl_admin2.geojson")])
    if get(HYDRORIVERS, RAW / "hydrorivers_as.zip") and not (RAW / "hydrorivers").exists():
        with zipfile.ZipFile(RAW / "hydrorivers_as.zip") as z:
            z.extractall(RAW / "hydrorivers")


if __name__ == "__main__":
    main()
