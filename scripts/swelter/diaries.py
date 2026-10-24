"""Real ATUS diaries as each resident's baseline day (built by scripts/atus.py).

A resident gets one summer and one winter weekday diary of a respondent with the same role (and age group when
there are enough), preferring Philadelphia-metro respondents, then Northeast metro areas, then any US metro area.
Picks are weighted by the ATUS final weight and recorded in the resident's trace.
"""
import json
from collections import defaultdict
from datetime import date

from .world import DATA

PHILLY = "37980"
SEASON_MONTHS = {"summer": {5, 6, 7, 8, 9}, "winter": {11, 12, 1, 2, 3}}
HAZARD_SEASON = {"heat": "summer", "smoke": "summer", "flood": "summer", "cold": "winter"}
COVID = ("20200401", "20210630")  # lockdown / remote-school months: not a normal weekday
MIN_POOL, MIN_AGE_POOL = 20, 8
TIERS = [
    ("Philadelphia metro", lambda d: d["cbsa"] == PHILLY),
    ("Northeast metro area", lambda d: d["region"] == 1 and d["metro"]),
    ("US metro area", lambda d: d["metro"]),
]
DOW = ["", "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
ROLE_WORDS = {"office": "office/professional worker", "service": "service worker", "healthcare": "healthcare worker",
              "outdoor": "construction/transport/grounds worker", "student": "college student", "retired": "retiree",
              "not_employed": "adult not in paid work"}


class DiaryPool:
    def __init__(self):
        doc = json.loads((DATA / "atus_diaries.json").read_text())
        self.activities, self.slots = doc["activities"], doc["slots"]
        self.by_id = {}
        self.index = defaultdict(list)  # (tier, role, season) -> diaries
        for d in doc["diaries"]:
            if COVID[0] <= d["date"] <= COVID[1]:
                continue
            self.by_id[d["id"]] = d
            month = int(d["date"][4:6])
            for season, months in SEASON_MONTHS.items():
                if month in months:
                    for t, (_, ok) in enumerate(TIERS):
                        if ok(d):
                            self.index[(t, d["role"], season)].append(d)

    def pick(self, role, age_group, season, rng):
        for t, (label, _) in enumerate(TIERS):
            pool = self.index[(t, role, season)]
            if len(pool) >= MIN_POOL or t == len(TIERS) - 1:
                same_age = [d for d in pool if d["age_group"] == age_group]
                if len(same_age) >= MIN_AGE_POOL:
                    pool = same_age
                d = rng.choices(pool, [x["w"] for x in pool])[0]
                return d, label, len(pool)
        raise LookupError(role)

    def describe(self, d, tier, n):
        dt = date(int(d["date"][:4]), int(d["date"][4:6]), int(d["date"][6:]))
        who = f"{d['age']}-year-old {'woman' if d['sex'] == 'F' else 'man'}, {ROLE_WORDS[d['role']]}"
        return (f"ATUS {dt.year} diary #{d['id']}: {DOW[d['dow']]} {dt:%b} {dt.day}, {who} ({tier}; "
                f"drawn from {n} matching diaries)")

    def decode(self, steps):
        return [[self.activities[s // 20], self.slots[s % 20]] for s in steps]
