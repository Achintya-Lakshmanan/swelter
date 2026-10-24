"""The map side of the simulation: real OSM places, spatial lookups, and per-location hazard modifiers."""
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

# Ida-era flood hot spots that are not next to a mapped waterway (approximate segment endpoints).
# Source: Sept 2021 news/PennDOT reports of I-676 trench flooding.
FLOOD_SEGMENTS = [
    ("I-676 Vine St Expressway", (39.9580, -75.1745), (39.9567, -75.1520)),
]

# Opening hours (inclusive start, exclusive end) by place kind. Refuge sites override this.
HOURS_OPEN = {
    "library": (10, 18), "community_centre": (9, 17), "grocery": (7, 23), "shop": (8, 22),
    "food": (7, 23), "mall": (10, 21), "campus": (7, 23), "office": (7, 20), "health": (0, 24),
    "school": (7, 16), "worship": (7, 21), "leisure_indoor": (9, 22), "civic": (8, 17),
    "pool": (11, 19), "park": (0, 24), "bus_stop": (0, 24),
}


def dist_m(a_lat, a_lon, b_lat, b_lon):
    return math.hypot((a_lat - b_lat) * M_PER_DEG_LAT, (a_lon - b_lon) * M_PER_DEG_LON)


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
        self._delaware = sorted((c for w in self.water if w["name"] == "Delaware River" for c in w["coords"]))
        # Drop anything east of the Delaware (Camden, NJ) — outside Philadelphia.
        self.places = [p for p in places if not self._east_of(self._delaware, p["lat"], p["lon"])]
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

    def flood_prone(self, lat, lon):
        """True near rivers/creeks or at known flash-flood spots (proxy for FEMA flood zones)."""
        key = (round(lat, 4), round(lon, 4))
        if key not in self._flood_cache:
            hit = self.river_dist(lat, lon) < 220
            if not hit:
                hit = any(_seg_dist_m((lat, lon), a, b) < 120 for _, a, b in FLOOD_SEGMENTS)
            self._flood_cache[key] = hit
        return self._flood_cache[key]

    def heat_island(self, lat, lon):
        """°F added to heat index. Proxy for tree canopy / impervious surface: few parks nearby = hotter,
        riverside = cooler. Range roughly -3..+4. (Swap for Landsat land-surface temperature later.)"""
        key = (round(lat, 3), round(lon, 3))
        if key not in self._uhi_cache:
            parks = len(self.nearby(lat, lon, 450, {"park"}))
            mod = 4.0 - 1.0 * min(parks, 5)
            if self.river_dist(lat, lon) < 400:
                mod -= 2.0
            self._uhi_cache[key] = round(mod, 1)
        return self._uhi_cache[key]

    def wind_exposure(self, lat, lon):
        """°F subtracted from wind chill on open riverfront."""
        return 5.0 if self.river_dist(lat, lon) < 300 else 0.0
