"""Fetch the non-OSM-places inputs: waterways (flood proximity) and Census ACS tract stats.

Writes data/waterways.json and data/tracts.json. Stdlib only.
    python3 scripts/fetch_extra.py
"""
import json
import urllib.request

from fetch_osm import BBOX, DATA, overpass

WATER_Q = f"""
[out:json][timeout:90];
way["waterway"~"^(river|stream|canal)$"]({BBOX});
out geom tags;
"""

# ACS 5-year tract tables for Philadelphia County via Census Reporter (the Census API now needs a key).
CR_URL = "https://api.censusreporter.org/1.0/data/show/latest?table_ids={tables}&geo_ids=140|05000US42101"
CR_TABLES = ["B01001", "B08201", "B11007", "B17001", "B14001", "B08301", "B19013", "C24010"]
GAZ_URL = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_gaz_tracts_42.txt"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "swelter-hackpsu/0.1"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read().decode("utf-8", "replace")


def fetch_waterways():
    print("fetching waterways...")
    raw = overpass(WATER_Q)
    water = [
        {
            "name": el.get("tags", {}).get("name", ""),
            "kind": el.get("tags", {}).get("waterway"),
            "coords": [[round(g["lat"], 5), round(g["lon"], 5)] for g in el["geometry"]],
        }
        for el in raw["elements"] if el.get("geometry")
    ]
    (DATA / "waterways.json").write_text(json.dumps(water))
    print(f"  {len(water)} waterway segments")


def main():
    if not (DATA / "waterways.json").exists():
        fetch_waterways()

    print("fetching ACS tract stats (Census Reporter)...")
    acs = json.loads(get(CR_URL.format(tables=",".join(CR_TABLES))))
    release = acs["release"]["name"]

    print("fetching tract centroids (Census gazetteer)...")
    gaz = get(GAZ_URL).splitlines()
    gh = [h.strip() for h in gaz[0].split("\t")]
    cent = {}
    for line in gaz[1:]:
        f = dict(zip(gh, [x.strip() for x in line.split("\t")]))
        cent[f["GEOID"]] = (float(f["INTPTLAT"]), float(f["INTPTLONG"]))

    s, w, n, e = map(float, BBOX.split(","))
    tracts = []
    for cr_id, tables in acs["data"].items():
        geoid = cr_id.split("US")[1]
        if geoid not in cent:
            continue
        lat, lon = cent[geoid]
        if not (s - 0.01 <= lat <= n + 0.01 and w - 0.01 <= lon <= e + 0.01):
            continue

        def v(col):
            return tables[col[:6]]["estimate"].get(col) or 0

        pop = v("B01001001")
        if pop < 200:
            continue
        p65 = sum(v(f"B01001{i:03d}") for i in [*range(20, 26), *range(44, 50)])
        hh = max(v("B08201001"), 1)
        workers = max(v("B08301001"), 1)
        employed = max(v("C24010001"), 1)
        income = v("B19013001")
        tracts.append({
            "geoid": geoid,
            "name": acs["geography"][cr_id]["name"].split(",")[0],
            "lat": lat, "lon": lon,
            "pop": int(pop),
            "share_65plus": round(p65 / pop, 3),
            "share_hh_nocar": round(v("B08201002") / hh, 3),
            "share_hh_65alone": round(v("B11007003") / hh, 3),
            "share_poverty": round(v("B17001002") / max(v("B17001001"), 1), 3),
            "share_students": round((v("B14001008") + v("B14001009")) / pop, 3),
            "share_commute_transit": round(v("B08301010") / workers, 3),
            "share_commute_walk": round(v("B08301019") / workers, 3),
            # construction/maintenance + transport/material moving: the outdoor-heavy occupations
            "share_outdoor_occ": round((v("C24010030") + v("C24010066") + v("C24010034") + v("C24010070")) / employed, 3),
            "median_income": int(income) if income and income > 0 else None,
            "source": f"{release}, tract {geoid}",
        })
    (DATA / "tracts.json").write_text(json.dumps(tracts))
    print(f"  {len(tracts)} tracts in study area")


if __name__ == "__main__":
    main()
