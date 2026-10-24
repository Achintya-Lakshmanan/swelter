"""Fetch the real-data inputs that replace earlier assumptions. Stdlib only; raw files land in data/raw/.

    python3 scripts/fetch_real.py

City of Philadelphia (ArcGIS):  FEMA floodplain 2023, Heat Exposure Index 2023, warming/cooling sites
CDC PLACES 2024 release (tract): adult asthma + COPD prevalence, BRFSS 2022 (the 2025 release has no PA values)
EIA RECS 2020 microdata:        AC / heating / energy insecurity by income, Pennsylvania households
NOAA ISD hourly, PHL airport:   temperature, dew point, wind, precipitation 2010-2024 (event-day selection)
EPA AQS hourly PM2.5 2010-2025: Philadelphia County monitors (smoke event days)
NOAA GHCN-Daily:                daily highs for PHL, NYC, DC, Baltimore, Boston (ATUS hot-day behavior)
"""
import json
import pathlib
import time
import urllib.parse
import urllib.request

from fetch_osm import BBOX, DATA

RAW = DATA / "raw"
UA = {"User-Agent": "swelter-hackpsu/0.1"}
CITY = "https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services"
CITY_LAYERS = {
    "fema_floodplain_2023": "fld_zone,zone_subty,sfha_tf",
    "HeatExposure_2023": "HEI_Score",
    "heat_vulnerability_ct": "geoid10,hei_score,hsi_score,hvi_score,year",
    "Warming_Cooling_Sites_PUBLICVIEW": "site_name,site_type,site_address,site_hours,warming_site,cooling_site,site_status,capacity",
}
PLACES_URL = ("https://data.cdc.gov/resource/ai6z-tcin.json?$limit=5000&$where="
              + urllib.parse.quote("countyfips='42101' AND measureid in('CASTHMA','COPD')"))
RECS_URL = "https://www.eia.gov/consumption/residential/data/2020/csv/recs2020_public_v7.csv"
ISD_URL = "https://noaa-global-hourly-pds.s3.amazonaws.com/{year}/72408013739.csv"  # NCEI redirects here
AQS_URL = "https://aqs.epa.gov/aqsweb/airdata/hourly_88101_{year}.zip"
ISD_YEARS = range(2010, 2025)
AQS_YEARS = range(2010, 2026)  # 2026 is still partial
GHCN_URL = "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/{station}.csv"
# Airport/park stations for the I-95 metros whose ATUS diaries feed the hot-day behavior estimate (scripts/atus.py METROS)
GHCN_STATIONS = {"37980": "USW00013739", "35620": "USW00094728", "47900": "USW00013743", "12580": "USW00093721",
                 "14460": "USW00014739"}


def get(url, path, retries=3):
    if path.exists() and path.stat().st_size > 0:
        return path
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=600) as r:
                tmp = path.with_suffix(path.suffix + ".part")
                tmp.write_bytes(r.read())
                tmp.rename(path)
            print(f"  got {path.name} ({path.stat().st_size / 1e6:.1f} MB)")
            return path
        except Exception as e:
            print(f"  {url} failed ({e}), retry {i + 1}")
            time.sleep(3)
    raise RuntimeError(f"could not fetch {url}")


def city_layer(name, fields):
    """Page through an ArcGIS FeatureServer layer, clipped to the study area, as GeoJSON."""
    path = RAW / "city" / f"{name}.geojson"
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    s, w, n, e = map(float, BBOX.split(","))
    feats, offset = [], 0
    while True:
        q = urllib.parse.urlencode({
            "where": "1=1", "outFields": fields, "f": "geojson", "outSR": 4326, "geometryPrecision": 5,
            "geometry": f"{w - 0.01},{s - 0.01},{e + 0.01},{n + 0.01}", "geometryType": "esriGeometryEnvelope",
            "inSR": 4326, "spatialRel": "esriSpatialRelIntersects", "resultOffset": offset, "resultRecordCount": 500,
        })
        req = urllib.request.Request(f"{CITY}/{name}/FeatureServer/0/query?{q}", headers=UA)
        with urllib.request.urlopen(req, timeout=180) as r:
            page = json.load(r)
        got = page.get("features", [])
        feats += got
        # the server may cap pages below resultRecordCount, so advance by what actually came back
        if not got or not (page.get("exceededTransferLimit") or page.get("properties", {}).get("exceededTransferLimit")):
            break
        offset += len(got)
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    print(f"  {name}: {len(feats)} features")


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    print("City of Philadelphia layers...")
    for name, fields in CITY_LAYERS.items():
        city_layer(name, fields)
    print("CDC PLACES...")
    get(PLACES_URL, RAW / "places_cdc_philly.json")
    print("EIA RECS 2020...")
    get(RECS_URL, RAW / "recs2020_public_v7.csv")
    print("NOAA ISD hourly (PHL)...")
    (RAW / "isd").mkdir(exist_ok=True)
    for y in ISD_YEARS:
        get(ISD_URL.format(year=y), RAW / "isd" / f"72408013739_{y}.csv")
    print("NOAA GHCN-Daily (I-95 metros)...")
    for st in GHCN_STATIONS.values():
        get(GHCN_URL.format(station=st), RAW / f"{st}.csv")
    print("EPA AQS hourly PM2.5...")
    (RAW / "aqs").mkdir(exist_ok=True)
    for y in AQS_YEARS:
        get(AQS_URL.format(year=y), RAW / "aqs" / f"hourly_88101_{y}.zip")
    print("done")


if __name__ == "__main__":
    main()
