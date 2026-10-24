"""Fetch Philadelphia (Center City / University City / North Philly) places, roads and bus stops from OpenStreetMap (Overpass API).

Writes data/places.json and data/roads.json. Stdlib only.
    python3 scripts/fetch_osm.py
"""
import json
import pathlib
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
BBOX = "39.935,-75.215,40.030,-75.120"  # Center City, University City, North Philly incl. Hunting Park
ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

PLACES_Q = f"""
[out:json][timeout:90];
(
 nwr["amenity"~"^(library|community_centre|hospital|clinic|cinema|social_facility|townhall|pharmacy|cafe|restaurant|fast_food|place_of_worship|school|college|university)$"]({BBOX});
 nwr["shop"~"^(supermarket|mall|department_store|convenience)$"]({BBOX});
 nwr["leisure"~"^(park|sports_centre|swimming_pool|stadium|playground)$"]({BBOX});
 nwr["building"~"^(apartments|dormitory|retail|commercial|office|university)$"]({BBOX});
 nwr["landuse"~"^(residential|commercial|retail)$"]({BBOX});
 node["highway"="bus_stop"]({BBOX});
);
out center tags;
"""

ROADS_Q = f"""
[out:json][timeout:90];
way["highway"~"^(primary|secondary|tertiary|trunk)$"]({BBOX});
out geom tags;
"""


def overpass(query):
    body = urllib.parse.urlencode({"data": query}).encode()
    last = None
    for url in ENDPOINTS:
        for attempt in range(2):
            try:
                req = urllib.request.Request(url, data=body, headers={"User-Agent": "swelter-hackpsu/0.1"})
                with urllib.request.urlopen(req, timeout=120) as r:
                    return json.load(r)
            except Exception as e:  # rate limits / timeouts: try next mirror
                last = e
                print(f"  {url} failed ({e}); retrying")
                time.sleep(3)
    raise RuntimeError(f"all Overpass endpoints failed: {last}")


# Map raw OSM tags to the small set of place kinds the simulator understands.
# ac: share of the time a resident at this kind of place is in air conditioning.
KIND_RULES = [
    ("amenity", "library", "library", 1.0),
    ("amenity", "community_centre", "community_centre", 1.0),
    ("amenity", "social_facility", "community_centre", 1.0),
    ("amenity", "townhall", "civic", 1.0),
    ("amenity", "hospital", "health", 1.0),
    ("amenity", "clinic", "health", 1.0),
    ("amenity", "pharmacy", "shop", 1.0),
    ("amenity", "cinema", "leisure_indoor", 1.0),
    ("amenity", "cafe", "food", 0.9),
    ("amenity", "restaurant", "food", 0.9),
    ("amenity", "fast_food", "food", 0.9),
    ("amenity", "place_of_worship", "worship", 0.6),
    ("amenity", "school", "school", 0.7),
    ("amenity", "college", "campus", 0.85),
    ("amenity", "university", "campus", 0.85),
    ("shop", "mall", "mall", 1.0),
    ("shop", "department_store", "mall", 1.0),
    ("shop", "supermarket", "grocery", 1.0),
    ("shop", "convenience", "shop", 1.0),
    ("leisure", "park", "park", 0.0),
    ("leisure", "playground", "park", 0.0),
    ("leisure", "stadium", "park", 0.0),
    ("leisure", "swimming_pool", "pool", 0.0),
    ("leisure", "sports_centre", "leisure_indoor", 0.8),
    ("building", "dormitory", "dorm", 0.9),
    ("building", "apartments", "apartment", None),
    ("building", "university", "campus", 0.85),
    ("building", "office", "office", 1.0),
    ("building", "commercial", "office", 0.95),
    ("building", "retail", "shop", 1.0),
    ("landuse", "residential", "residential", None),
    ("landuse", "commercial", "office", 0.95),
    ("landuse", "retail", "shop", 1.0),
    ("highway", "bus_stop", "bus_stop", 0.0),
]


def classify(tags):
    for key, val, kind, ac in KIND_RULES:
        if tags.get(key) == val:
            return kind, ac
    return None, None


def main():
    DATA.mkdir(exist_ok=True)
    print("fetching places...")
    raw = overpass(PLACES_Q)
    places = []
    for el in raw["elements"]:
        tags = el.get("tags", {})
        kind, ac = classify(tags)
        if not kind:
            continue
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        if lat is None:
            continue
        name = tags.get("name") or tags.get("addr:street") or ""
        places.append({
            "id": f"{el['type'][0]}{el['id']}",
            "kind": kind,
            "name": name,
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "ac": ac,  # None = depends on the household (homes)
        })
    (DATA / "places.json").write_text(json.dumps(places))
    counts = {}
    for p in places:
        counts[p["kind"]] = counts.get(p["kind"], 0) + 1
    print(f"  {len(places)} places:", dict(sorted(counts.items(), key=lambda kv: -kv[1])))

    print("fetching roads...")
    raw = overpass(ROADS_Q)
    roads = []
    for el in raw["elements"]:
        geom = el.get("geometry")
        if not geom:
            continue
        roads.append({
            "id": el["id"],
            "class": el.get("tags", {}).get("highway"),
            "name": el.get("tags", {}).get("name", ""),
            "coords": [[round(g["lat"], 5), round(g["lon"], 5)] for g in geom],
        })
    (DATA / "roads.json").write_text(json.dumps(roads))
    print(f"  {len(roads)} road segments")


if __name__ == "__main__":
    main()
