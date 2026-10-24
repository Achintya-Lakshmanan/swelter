"""Synthetic residents drawn from real ACS tract statistics.

Each resident records which tract statistic set each attribute (`trace`), so every persona traces back
to the data pattern it came from. Residents collapse into persona *types* (the categorical
attributes that matter for behavior); the LLM planner works per type, the map shows residents.
"""
import random

from .world import HOME_KINDS, World, dist_m

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

# Assumptions not yet tied to a tract table (documented in the methods note).
ASSUMPTIONS = {
    "employment_rate": (0.62, "Philadelphia employment-population ratio, ACS (approx.)"),
    "no_ac_base": (0.08, "EIA RECS 2020: ~9 in 10 Mid-Atlantic homes use AC"),
    "no_ac_poverty_add": (0.22, "RECS 2020: AC access lower in low-income households (assumed gap)"),
    "no_heat_base": (0.03, "RECS 2020 energy insecurity (assumed)"),
    "no_heat_poverty_add": (0.12, "RECS 2020: unsafe indoor temps concentrated in low-income homes (assumed)"),
    "respiratory_base": (0.11, "CDC PLACES Philadelphia adult asthma prevalence (approx.)"),
}


def _a(key):
    return ASSUMPTIONS[key][0]


class PersonaBuilder:
    def __init__(self, world: World, seed=7):
        self.w = world
        self.rng = random.Random(seed)
        self.homes = [p for p in world.places if p["kind"] in HOME_KINDS]
        self.campuses = [p for p in world.places if p["kind"] in {"campus", "dorm"}]

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
        u = r.random()
        if u < t["share_65plus"]:
            age = "75+" if r.random() < 0.42 else "65-74"
            role = "retired" if r.random() < 0.85 else "office"
            trace["age"] = f"{t['share_65plus']:.0%} of tract is 65+"
        elif u < t["share_65plus"] + t["share_students"]:
            age, role = "18-24", "student"
            trace["age"] = f"{t['share_students']:.0%} of tract enrolled in college"
        else:
            age = r.choice(["25-44", "25-44", "45-64"])
            if r.random() < _a("employment_rate"):
                v = r.random()
                outdoor = min(0.45, t["share_outdoor_occ"])
                role = ("outdoor" if v < outdoor else "healthcare" if v < outdoor + 0.18
                        else "service" if v < outdoor + 0.43 else "office")
                trace["role"] = f"{t['share_outdoor_occ']:.0%} of tract workers in construction/transport jobs"
            else:
                role = "not_employed"
        older = age in ("65-74", "75+")
        if older:
            p_alone = max(0.2, min(0.6, 1.3 * t["share_hh_65alone"] / max(t["share_65plus"], 0.01)))
            trace["alone"] = f"{t['share_hh_65alone']:.0%} of tract households are a 65+ person alone"
        else:
            p_alone = 0.1 if role == "student" else 0.22
        alone = r.random() < p_alone
        poverty = r.random() < t["share_poverty"]
        trace["poverty"] = f"{t['share_poverty']:.0%} of tract below poverty line"
        p_nocar = min(0.95, t["share_hh_nocar"] + (0.3 if role == "student" else 0))
        car = r.random() >= p_nocar
        trace["car"] = f"{t['share_hh_nocar']:.0%} of tract households have no vehicle"
        ac = r.random() >= _a("no_ac_base") + (_a("no_ac_poverty_add") if poverty else 0) + (0.05 if age == "75+" else 0)
        heat = r.random() >= _a("no_heat_base") + (_a("no_heat_poverty_add") if poverty else 0)
        resp = r.random() < _a("respiratory_base") + (0.05 if poverty else 0) + (0.06 if older else 0)
        if home["kind"] == "dorm":
            role, age, ac, heat = "student", "18-24", True, True
        work = None
        if role in ("office", "service", "healthcare", "outdoor"):
            work = self._work_for(role, home)
        elif role == "student":
            hits = self.w.nearby(home["lat"], home["lon"], 4000, {"campus"})
            work = (r.choice(hits[:15])[1] if hits else None)
        return self._finish({
            "id": rid, "name": r.choice(FIRST_NAMES), "age": age, "role": role, "alone": alone,
            "car": car, "ac": ac, "heat": heat, "respiratory": resp, "poverty": poverty,
            "home": home["id"], "work": work["id"] if work else None,
            "tract": t["geoid"], "tract_name": t["name"], "source": t["source"], "trace": trace,
        })

    def _unhoused(self, rid, spot, hub):
        r = self.rng
        return self._finish({
            "id": rid, "name": r.choice(FIRST_NAMES), "age": r.choice(["25-44", "45-64", "45-64", "65-74"]),
            "role": "unhoused", "alone": True, "car": False, "ac": False, "heat": False,
            "respiratory": r.random() < 0.25, "poverty": True, "home": spot["id"], "work": None,
            "tract": self.w.nearest_tract(spot["lat"], spot["lon"])["geoid"], "tract_name": hub,
            "source": "Philadelphia Point-in-Time count: unsheltered residents concentrated in Kensington & Center City",
            "trace": {"role": f"sleeps outdoors near {hub}"},
        })

    def _finish(self, p):
        w = self.w
        home = w.by_id[p["home"]]
        p["flood_zone"] = w.flood_prone(home["lat"], home["lon"]) and p["role"] != "unhoused"
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
