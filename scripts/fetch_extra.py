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
CR_TABLES = ["B01001", "B08201", "B11007", "B17001", "B14001", "B08301", "B19013", "C24010", "B23001"]
# C24010 occupation columns (male, female) grouped like the ATUS roles in scripts/atus.py
OCC = {
    "healthcare": [16, 20, 52, 56],
    "outdoor": [25, 31, 32, 33, 36, 37, 61, 67, 68, 69, 72, 73],  # grounds, farming, construction, repair, transport
    "service": [21, 24, 26, 28, 35, 57, 60, 62, 64, 71],  # protective, food, personal care, sales, production
}
# B23001 age-group blocks: first column of each block (total), employed is first + 4
WORKING_AGE = [*range(10, 67, 7), *range(96, 153, 7)]  # 20-64, both sexes (16-19 excluded: residents are adults)
OLDER = [73, 78, 83, 159, 164, 169]  # 65-69, 70-74, 75+
AGE_BANDS = {"18-24": [7, 8, 9, 10], "25-44": [11, 12, 13, 14], "45-64": [15, 16, 17, 18, 19],
             "65-74": [20, 21, 22], "75+": [23, 24, 25]}  # B01001 male columns; female = +24
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
        ages = {k: sum(v(f"B01001{i:03d}") + v(f"B01001{i + 24:03d}") for i in cols) for k, cols in AGE_BANDS.items()}
        adults = max(sum(ages.values()), 1)
        p65 = ages["65-74"] + ages["75+"]
        hh = max(v("B08201001"), 1)
        workers = max(v("B08301001"), 1)
        employed = max(v("C24010001"), 1)
        income = v("B19013001")
        occ = {k: sum(v(f"C24010{c:03d}") for c in cols) / employed for k, cols in OCC.items()}

        def emp_rate(blocks):
            tot = sum(v(f"B23001{b:03d}") for b in blocks)
            return sum(v(f"B23001{b + (2 if b in OLDER else 4):03d}") for b in blocks) / tot if tot else 0
        tracts.append({
            "geoid": geoid,
            "name": acs["geography"][cr_id]["name"].split(",")[0],
            "lat": lat, "lon": lon,
            "pop": int(pop),
            "share_65plus": round(p65 / pop, 3),
            "adult_age_shares": {k: round(x / adults, 3) for k, x in ages.items()},
            "share_65plus_alone": round(min(1, v("B11007003") / max(p65, 1)), 3),
            "emp_rate_20_64": round(emp_rate(WORKING_AGE), 3),
            "emp_rate_65plus": round(emp_rate(OLDER), 3),
            "occ_shares": {k: round(x, 3) for k, x in occ.items()},
            "college_per_18_24": round(min(1, (v("B14001008") + v("B14001009")) / max(ages["18-24"], 1)), 3),
            "share_hh_nocar": round(v("B08201002") / hh, 3),
            "share_hh_65alone": round(v("B11007003") / hh, 3),
            "share_poverty": round(v("B17001002") / max(v("B17001001"), 1), 3),
            "share_students": round((v("B14001008") + v("B14001009")) / pop, 3),
            "share_commute_transit": round(v("B08301010") / workers, 3),
            "share_commute_walk": round(v("B08301019") / workers, 3),
            "share_outdoor_occ": round(occ["outdoor"], 3),
            "median_income": int(income) if income and income > 0 else None,
            "source": f"{release}, tract {geoid}",
        })
    (DATA / "tracts.json").write_text(json.dumps(tracts))
    print(f"  {len(tracts)} tracts in study area")


if __name__ == "__main__":
    main()
