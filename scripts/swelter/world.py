"""The map side of the simulation: real OSM places, spatial lookups, and per-location hazard modifiers.

Flood zones are FEMA's 2023 flood map and heat is the city's 2023 Heat Exposure Index (both City of Philadelphia
open data, prepared by scripts/derive_inputs.py). City cooling/warming sites are added as places.
"""
import json
import math
import pathlib
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

M_PER_DEG_LAT = 111_320
M_PER_DEG_LON = 111_320 * math.cos(math.radians(39.98))

HOME_KINDS = {"apartment", "residential", "dorm"}
WORK_INDOOR_KINDS = {"office", "campus", "health", "shop", "food", "mall", "grocery", "school", "civic"}

# FEMA zone -> share of the hazard felt there: 1% annual chance (incl. floodway) vs 0.2% annual chance (assumed weights)
FLOOD_WEIGHT = {"floodway": 1.0, "1pct": 1.0, "0.2pct": 0.6}
# Heat Exposure Index is a standardized score (about -5..+5 across the city); 1 unit is taken as 1°F of heat index.
HEI_F_PER_UNIT, HEI_CAP_F = 1.0, 4.0

# Opening hours (inclusive start, exclusive end) by place kind. Refuge sites use their posted hours instead.
HOURS_OPEN = {
    "library": (10, 18), "community_centre": (9, 17), "grocery": (7, 23), "shop": (8, 22),
    "food": (7, 23), "mall": (10, 21), "campus": (7, 23), "office": (7, 20), "health": (0, 24),
    "school": (7, 16), "worship": (7, 21), "leisure_indoor": (9, 22), "civic": (8, 17),
    "pool": (11, 19), "park": (0, 24), "bus_stop": (0, 24),
}


def dist_m(a_lat, a_lon, b_lat, b_lon):
    return math.hypot((a_lat - b_lat) * M_PER_DEG_LAT, (a_lon - b_lon) * M_PER_DEG_LON)


def _in_rings(lon, lat, rings):
    """Even-odd point-in-polygon over all rings (outer + holes)."""
    inside = False
    for ring in rings:
        j = len(ring) - 1
        for i in range(len(ring)):
            xi, yi = ring[i]
            xj, yj = ring[j]
            if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
                inside = not inside
            j = i
    return inside


def _polygon_value(polys, lat, lon, key):
    for p in polys:
        b = p["bbox"]
        if b[0] <= lon <= b[2] and b[1] <= lat <= b[3] and _in_rings(lon, lat, p["rings"]):
            return p[key]
    return None


def _seg_dist_m(p, a, b):
    """Distance from point p to segment ab, all (lat, lon)."""
    px, py = p[1] * M_PER_DEG_LON, p[0] * M_PER_DEG_LAT
    ax, ay = a[1] * M_PER_DEG_LON, a[0] * M_PER_DEG_LAT
    bx, by = b[1] * M_PER_DEG_LON, b[0] * M_PER_DEG_LAT
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


class World:
    CELL = 0.004  # ~400 m grid buckets

    def __init__(self):
        places = json.loads((DATA / "places.json").read_text())
        self.water = json.loads((DATA / "waterways.json").read_text())
        self.tracts = json.loads((DATA / "tracts.json").read_text())
        self.flood_zones = json.loads((DATA / "flood_zones.json").read_text())
        self.heat_polys = json.loads((DATA / "heat_exposure.json").read_text())
        self.refuges = json.loads((DATA / "inputs.json").read_text())["refuges"]
        self._delaware = sorted((c for w in self.water if w["name"] == "Delaware River" for c in w["coords"]))
        # Drop anything east of the Delaware (Camden, NJ) — outside Philadelphia.
        self.places = [p for p in places if not self._east_of(self._delaware, p["lat"], p["lon"])]
        self.places += [{"id": r["id"], "kind": "refuge_site", "name": r["name"], "lat": r["lat"], "lon": r["lon"], "ac": 1.0}
                        for r in self.refuges]
        self.by_id = {p["id"]: p for p in self.places}
        self.grid = defaultdict(list)
        for p in self.places:
            self.grid[self._cell(p["lat"], p["lon"])].append(p)
        self._water_segs = [(w["kind"], w["coords"][i], w["coords"][i + 1])
                            for w in self.water for i in range(len(w["coords"]) - 1)]
        self._flood_cache, self._uhi_cache, self._river_cache = {}, {}, {}

    @staticmethod
    def _east_of(river, lat, lon):
        if not river:
            return False
        near = min(river, key=lambda c: abs(c[0] - lat))
        return abs(near[0] - lat) < 0.01 and lon > near[1]

    def _cell(self, lat, lon):
        return (int(lat / self.CELL), int(lon / self.CELL))

    def nearby(self, lat, lon, radius_m, kinds=None):
        r = int(radius_m / 400) + 1
        ci, cj = self._cell(lat, lon)
        out = []
        for i in range(ci - r, ci + r + 1):
            for j in range(cj - r, cj + r + 1):
                for p in self.grid.get((i, j), ()):
                    if kinds and p["kind"] not in kinds:
                        continue
                    d = dist_m(lat, lon, p["lat"], p["lon"])
                    if d <= radius_m:
                        out.append((d, p))
        out.sort(key=lambda x: x[0])
        return out

    def nearest(self, lat, lon, kinds, max_m=6000):
        for radius in (500, 1500, 3000, max_m):
            hits = self.nearby(lat, lon, radius, kinds)
            if hits:
                return hits[0][1]
        return None

    def nearest_tract(self, lat, lon):
        return min(self.tracts, key=lambda t: dist_m(lat, lon, t["lat"], t["lon"]))

    # --- hazard modifiers ------------------------------------------------------------------------
    def river_dist(self, lat, lon):
        key = (round(lat, 4), round(lon, 4))
        if key not in self._river_cache:
            best = 1e9
            for kind, a, b in self._water_segs:
                if abs(a[0] - lat) > 0.02 and abs(b[0] - lat) > 0.02:
                    continue
                d = _seg_dist_m((lat, lon), a, b)
                if kind == "stream":
                    d *= 1.8  # small creeks flood a narrower band than the Schuylkill
                best = min(best, d)
            self._river_cache[key] = best
        return self._river_cache[key]

    def flood_zone(self, lat, lon):
        """FEMA 2023 zone at this point: 'floodway', '1pct', '0.2pct' or None."""
        key = (round(lat, 4), round(lon, 4))
        if key not in self._flood_cache:
            self._flood_cache[key] = _polygon_value(self.flood_zones, lat, lon, "zone")
        return self._flood_cache[key]

    def flood_weight(self, lat, lon):
        return FLOOD_WEIGHT.get(self.flood_zone(lat, lon), 0.0)

    def flood_prone(self, lat, lon):
        return self.flood_zone(lat, lon) is not None

    def heat_island(self, lat, lon):
        """°F added to the airport heat index here, from the city's Heat Exposure Index (0 outside its polygons)."""
        key = (round(lat, 3), round(lon, 3))
        if key not in self._uhi_cache:
            hei = _polygon_value(self.heat_polys, lat, lon, "hei")
            if hei is None:  # outside every scored tract: use the nearest one
                hei = min(self.heat_polys, key=lambda q: dist_m(lat, lon, (q["bbox"][1] + q["bbox"][3]) / 2,
                                                                 (q["bbox"][0] + q["bbox"][2]) / 2))["hei"]
            self._uhi_cache[key] = round(max(-HEI_CAP_F, min(HEI_CAP_F, HEI_F_PER_UNIT * hei)), 1)
        return self._uhi_cache[key]

    def wind_exposure(self, lat, lon):
        """°F subtracted from wind chill on open riverfront (assumed)."""
        return 5.0 if self.river_dist(lat, lon) < 300 else 0.0
