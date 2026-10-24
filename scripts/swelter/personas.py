"""Synthetic residents drawn from real data: ACS tract statistics (age, work, occupation, poverty, cars, living alone),
EIA RECS 2020 (AC / heating by poverty), CDC PLACES (tract asthma + COPD), and a real ATUS diary for their weekday.

Each resident records which statistic set each attribute (`trace`), so every persona traces back to the data
pattern it came from. Residents collapse into persona *types* (the categorical
attributes that matter for behavior); the LLM planner works per type, the map shows residents.
"""
import json
import random

from .diaries import DiaryPool
from .world import DATA, HOME_KINDS, World, dist_m

FIRST_NAMES = [
    "Ana", "Andre", "Aisha", "Bea", "Bilal", "Carmen", "Chen", "Dani", "Darnell", "Deja", "Eli", "Elena",
    "Femi", "Gloria", "Hector", "Imani", "Isaiah", "Jae", "Jamal", "Jasmine", "Joe", "Kayla", "Keisha",
    "Kofi", "Lena", "Luis", "Mae", "Malik", "Maria", "Marcus", "Mei", "Nadia", "Nia", "Omar", "Priya",
    "Quinn", "Rosa", "Ruth", "Sam", "Shanice", "Tariq", "Teresa", "Tom", "Tyrell", "Vera", "Wen", "Xavier",
    "Yara", "Yusuf", "Zoe", "Frank", "Dolores", "Walt", "Irene", "Pat", "Rafael", "Minh", "Ibrahim",
]

# Unsheltered homelessness in Philadelphia is concentrated in Kensington and Center City
# (Philadelphia Office of Homeless Services, Point-in-Time counts).
UNHOUSED_HUBS = [((39.9965, -75.1340), 0.7, "Kensington Ave & Allegheny"), ((39.9526, -75.1636), 0.3, "Center City")]

INPUTS = json.loads((DATA / "inputs.json").read_text())
RECS = INPUTS["recs"]

# What still isn't measured per resident (shown in the methods note).
ASSUMPTIONS = {
    "alone_under_65": (0.22, "Share of adults under 65 living alone (only used for labels; not tract-specific)"),
    "unhoused_oversample": (60, "Unhoused residents simulated (oversampled vs the real ~0.1% of residents so the group has "
                                "enough people; group results are per-person averages)"),
}
SOURCES = {
    "no_ac": (RECS["no_ac"], f"EIA RECS 2020, Pennsylvania households: no air conditioning, by poverty (n={RECS['n']})"),
    "no_heat": (RECS["no_heat"], "EIA RECS 2020, Pennsylvania: couldn't use main heating equipment at some point in the year"),
    "respiratory": ("by tract", INPUTS["respiratory_source"]),
    "age_work_occupation": ("by tract", "ACS 2024 5-year: B01001 age, B23001 employment by age, C24010 occupation, "
                                        "B14001 college enrollment, B11007 65+ living alone, B17001 poverty, B08201 vehicles"),
    "weekday": ("by role", "BLS ATUS 2018-2024 weekday diaries, Philadelphia metro first (scripts/atus.py)"),
}


class PersonaBuilder:
    def __init__(self, world: World, seed=7):
        self.w = world
        self.rng = random.Random(seed)
        self.homes = [p for p in world.places if p["kind"] in HOME_KINDS]
        self.campuses = [p for p in world.places if p["kind"] in {"campus", "dorm"}]
        self.diaries = DiaryPool()

    def _home_near(self, lat, lon):
        hits = self.w.nearby(lat, lon, 700, HOME_KINDS) or self.w.nearby(lat, lon, 2000, HOME_KINDS)
        if not hits:
            return None
        return self.rng.choice(hits[:25])[1]

    def _work_for(self, role, home):
        r = self.rng
        kinds = {
            "office": {"office", "campus", "civic"},
            "service": {"shop", "food", "mall", "grocery"},
            "healthcare": {"health", "campus"},
            "outdoor": HOME_KINDS | {"park"},  # job sites: construction, landscaping, delivery routes
        }[role]
        radius = 2500 if role == "service" else 5000
        hits = [h for h in self.w.nearby(home["lat"], home["lon"], radius, kinds) if h[0] > 300]
        if not hits:
            return self.w.nearest(home["lat"], home["lon"], kinds)
        return r.choice(hits)[1]

    def build(self, n=1500, n_unhoused=60):
        r = self.rng
        tracts = [t for t in self.w.tracts if t["pop"] > 400]
        weights = [t["pop"] for t in tracts]
        residents = []
        while len(residents) < n:
            t = r.choices(tracts, weights)[0]
            home = self._home_near(t["lat"], t["lon"])
            if not home:
                continue
            residents.append(self._resident(len(residents), t, home))
        for _ in range(n_unhoused):
            (lat, lon), _, hub = r.choices(UNHOUSED_HUBS, [h[1] for h in UNHOUSED_HUBS])[0]
            lat += r.gauss(0, 0.004)
            lon += r.gauss(0, 0.004)
            spot = self.w.nearest(lat, lon, {"park", "bus_stop"})
            residents.append(self._unhoused(len(residents), spot, hub))
        return residents

    def _resident(self, rid, t, home):
        r = self.rng
        trace = {}
        ages = t["adult_age_shares"]
        age = r.choices(list(ages), list(ages.values()))[0]
        older = age in ("65-74", "75+")
        trace["age"] = f"{ages[age]:.0%} of tract adults are {age}"
        if age == "18-24" and r.random() < t["college_per_18_24"]:
            role = "student"
            trace["role"] = f"tract college enrollment ≈ {t['college_per_18_24']:.0%} of 18-24s"
        else:
            emp = t["emp_rate_65plus" if older else "emp_rate_20_64"]
            if r.random() < emp:
                occ, v = t["occ_shares"], r.random()
                role = ("healthcare" if v < occ["healthcare"] else "outdoor" if v < occ["healthcare"] + occ["outdoor"]
                        else "service" if v < occ["healthcare"] + occ["outdoor"] + occ["service"] else "office")
                trace["role"] = (f"{emp:.0%} of tract {'65+' if older else '20-64'} employed; workers: {occ['healthcare']:.0%} "
                                 f"healthcare, {occ['outdoor']:.0%} construction/transport/grounds, {occ['service']:.0%} service/sales")
            else:
                role = "retired" if older else "not_employed"
                trace["role"] = f"{1 - emp:.0%} of tract {'65+' if older else '20-64'} not employed"
        if older:
            p_alone = t["share_65plus_alone"]
            trace["alone"] = f"{p_alone:.0%} of tract 65+ residents live alone"
        else:
            p_alone = 0.1 if role == "student" else ASSUMPTIONS["alone_under_65"][0]
        alone = r.random() < p_alone
        poverty = r.random() < t["share_poverty"]
        trace["poverty"] = f"{t['share_poverty']:.0%} of tract below poverty line"
        car = r.random() >= t["share_hh_nocar"]
        trace["car"] = f"{t['share_hh_nocar']:.0%} of tract households have no vehicle"
        band = "poverty" if poverty else "other"
        ac = r.random() >= RECS["no_ac"][band]
        heat = r.random() >= RECS["no_heat"][band]
        trace["ac"] = (f"RECS 2020 PA: {RECS['no_ac'][band]:.0%} of {'low-income ' if poverty else ''}homes have no AC, "
                       f"{RECS['no_heat'][band]:.0%} lost heat")
        p_resp = INPUTS["respiratory_by_tract"].get(t["geoid"])
        if p_resp is None:
            p_resp = sorted(INPUTS["respiratory_by_tract"].values())[len(INPUTS["respiratory_by_tract"]) // 2]
        resp = r.random() < p_resp
        trace["respiratory"] = f"CDC PLACES: {p_resp:.0%} of tract adults have asthma or COPD"
        if home["kind"] == "dorm":
            role, age, ac, heat = "student", "18-24", True, True
            trace["role"] = "lives in a university dorm"
        work = None
        if role in ("office", "service", "healthcare", "outdoor"):
            work = self._work_for(role, home)
        elif role == "student":
            hits = self.w.nearby(home["lat"], home["lon"], 4000, {"campus"})
            work = (r.choice(hits[:15])[1] if hits else None)
        days = {}
        for season in ("summer", "winter"):
            d, tier, n = self.diaries.pick(role, age, season, r)
            days[season] = d["steps"]
            trace[f"day_{season}"] = self.diaries.describe(d, tier, n)
        return self._finish({
            "id": rid, "name": r.choice(FIRST_NAMES), "age": age, "role": role, "alone": alone,
            "car": car, "ac": ac, "heat": heat, "respiratory": resp, "poverty": poverty,
            "home": home["id"], "work": work["id"] if work else None, "days": days,
            "tract": t["geoid"], "tract_name": t["name"], "source": t["source"], "trace": trace,
        })

    def _unhoused(self, rid, spot, hub):
        r = self.rng
        return self._finish({
            "id": rid, "name": r.choice(FIRST_NAMES), "age": r.choice(["25-44", "45-64", "45-64", "65-74"]),
            "role": "unhoused", "alone": True, "car": False, "ac": False, "heat": False, "days": None,
            "respiratory": r.random() < 0.25, "poverty": True, "home": spot["id"], "work": None,
            "tract": self.w.nearest_tract(spot["lat"], spot["lon"])["geoid"], "tract_name": hub,
            "source": "Philadelphia Point-in-Time count: unsheltered residents concentrated in Kensington & Center City",
            "trace": {"role": f"sleeps outdoors near {hub}",
                      "day": "No survey covers unsheltered days (ATUS samples households): schedule built around meal programs and library hours"},
        })

    def _finish(self, p):
        w = self.w
        home = w.by_id[p["home"]]
        p["flood_zone"] = w.flood_prone(home["lat"], home["lon"]) and p["role"] != "unhoused"
        if p["flood_zone"]:
            zone = {"floodway": "floodway", "1pct": "1%-annual-chance", "0.2pct": "0.2%-annual-chance"}[w.flood_zone(home["lat"], home["lon"])]
            p["trace"]["flood"] = f"home is in FEMA's {zone} flood zone (2023 map)"
        if p["work"]:
            wk = w.by_id[p["work"]]
            p["commute_km"] = round(dist_m(home["lat"], home["lon"], wk["lat"], wk["lon"]) / 1000, 2)
        older = p["age"] in ("65-74", "75+")
        groups = []
        if older and p["alone"]:
            groups.append("older_alone")
        if p["role"] == "outdoor":
            groups.append("outdoor_worker")
        if not p["ac"] and p["role"] != "unhoused":
            groups.append("no_ac")
        if p["role"] == "student":
            groups.append("student")
        if p["role"] == "unhoused":
            groups.append("unhoused")
        if p["respiratory"]:
            groups.append("respiratory")
        if p["flood_zone"]:
            groups.append("flood_zone")
        if p["car"]:
            groups.append("driver")
        if not p["car"] and p["role"] != "unhoused":
            groups.append("no_car")
        if not p["heat"] and p["role"] != "unhoused":
            groups.append("no_heat")
        p["groups"] = groups
        p["vulnerable"] = older or p["respiratory"] or p["role"] == "unhoused"
        p["type"] = "|".join([
            p["role"], "older" if older else "adult", "alone" if p["alone"] else "hh",
            "car" if p["car"] else "nocar", "ac" if p["ac"] else "noac", "heat" if p["heat"] else "noheat",
            "resp" if p["respiratory"] else "-", "flood" if p["flood_zone"] else "-",
        ])
        return p
