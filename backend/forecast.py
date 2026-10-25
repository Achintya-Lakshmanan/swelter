"""What the simulator adds to the live app: expected arrivals per cooling/warming site by hour, and where
dangerous exposure concentrates, for the stored run that best matches today (or a replayed record day)."""
import json
import math
import pathlib
import re
from functools import lru_cache

DATA = pathlib.Path(__file__).resolve().parent.parent / "app" / "data"


@lru_cache(maxsize=1)
def meta():
    return json.loads((DATA / "meta.json").read_text())


@lru_cache(maxsize=48)
def run(sid):
    if sid not in meta()["scenarios"]:
        raise KeyError(sid)
    return json.loads((DATA / "runs" / f"{sid}.json").read_text())


def norm(name):
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\(.*?\)", "", name.lower()))


@lru_cache(maxsize=1)
def refuge_index():
    """normalized site name → place index in the simulator."""
    return {norm(p[2]): i for i, p in enumerate(meta()["places"]) if p[1] == "refuge_site"}


def heat_index_f(t, rh):
    if t is None or rh is None or t < 80:
        return t
    return round(-42.379 + 2.04901523 * t + 10.14333127 * rh - .22475541 * t * rh - .00683783 * t * t
                 - .05481717 * rh * rh + .00122874 * t * t * rh + .00085282 * t * rh * rh - .00000199 * t * t * rh * rh)


def pick_scenario(hazard, today_peak):
    """Nearest of the three real days on record for this hazard, by peak intensity."""
    if hazard not in meta()["hazards"]:
        return None
    levels = meta()["hazards"][hazard]["levels"]
    if today_peak is None:
        return f"{hazard}_moderate"
    key = (lambda v: min(v)) if hazard == "cold" else (lambda v: max(v))
    best = min(levels, key=lambda lv: abs(key(levels[lv]["intensity"]) - today_peak))
    return f"{hazard}_{best}"


def site_forecast(scenario, site_name):
    """Simulated people at this site per hour (6 AM–10 PM) with the city's sites open, or None if outside the
    simulated area."""
    idx = refuge_index().get(norm(site_name))
    if idx is None or not scenario:
        return None
    rn = run(f"{scenario}_refuge")
    counts = [0] * len(meta()["hours"])
    for row in rn["steps"]:
        for h, s in enumerate(row):
            if s // 1000 == idx:
                counts[h] += 1
    return {"hours": meta()["hours"], "people": counts, "scenario": f"{scenario}_refuge",
            "real_day": meta()["hazards"][rn["hazard"]]["levels"][rn["level"]]["label"].split(" — ")[-1],
            "residents_simulated": len(meta()["residents"]), "source": "Swelter simulation (1,560 synthetic residents)"}


def risk_grid(scenario, hour, iv="none"):
    """Grid cells (~350 m) with how many simulated residents are at danger or worse at this hour."""
    m = meta()
    rn = run(f"{scenario}_{iv}")
    real_day = m["hazards"][rn["hazard"]]["levels"][rn["level"]]["label"].split(" — ")[-1]
    if not simulated(hour):  # no simulated residents overnight; say so rather than show another hour
        return {"scenario": f"{scenario}_{iv}", "hour": hour, "simulated": False, "step": m["grid"]["step"],
                "cells": [], "unit": m["hazards"][rn["hazard"]]["unit"], "real_day": real_day}
    h = hour - m["hours"][0]
    step, cells = m["grid"]["step"], {}
    for row, lv in zip(rn["steps"], rn["levels"]):
        p = m["places"][row[h] // 1000]
        key = (math.floor(p[3] / step), math.floor(p[4] / step))
        c = cells.setdefault(key, [0, 0])
        c[1] += 1
        if int(lv[h]) >= 2:
            c[0] += 1
    out = [{"lat": (k[0] + .5) * step, "lon": (k[1] + .5) * step, "danger": d, "people": n}
           for k, (d, n) in cells.items() if d]
    return {"scenario": f"{scenario}_{iv}", "hour": hour, "simulated": True, "step": step, "cells": out,
            "intensity": rn["intensity"][h], "unit": m["hazards"][rn["hazard"]]["unit"], "real_day": real_day}


@lru_cache(maxsize=1)
def replay_hours():
    """Every hour (0-23) of each record day as recorded (scripts/replay_hours.py); the simulation itself only
    covers 6 AM-10 PM."""
    f = DATA / "replay_hours.json"
    return json.loads(f.read_text()) if f.exists() else {}


def simulated(hour):
    """Whether the simulation has this clock hour (6 AM-10 PM)."""
    return hour in meta()["hours"]


def replay_conditions(scenario, hour):
    """The real recorded conditions of a replayed day at this clock hour."""
    m = meta()
    hz, lvl = scenario.split("_")
    L = m["hazards"][hz]["levels"][lvl]
    full = replay_hours().get(hz, {}).get(lvl, {}).get("values")
    if full:
        value, at = full[hour], hour
    else:  # older data without the full-day file: nearest simulated hour, labelled with that hour
        h = max(0, min(len(m["hours"]) - 1, hour - m["hours"][0]))
        value, at = L["intensity"][h], m["hours"][h]
    return {"hazard": hz, "label": m["hazards"][hz]["label"], "day": L["label"].split(" — ")[-1], "date": L.get("date"),
            "note": L["note"], "value": value, "unit": m["hazards"][hz]["unit"], "hour": at,
            "simulated": simulated(hour), "peak": (min if hz == "cold" else max)(full or L["intensity"]),
            "source": "NOAA ISD hourly at PHL" if hz != "smoke" else "EPA AQS hourly PM2.5 (NowCast AQI)"}


# The demo is told through one simulated resident on the record heat day: Kayla, 75+, Fairhill (tract 175), lives
# alone, no AC, never hears the warning, extreme danger at home 9 AM-10 PM. Her demo account's profile comes from
# that resident, so the person the audience sees on the simulator map is the one asking for help on the phone.
DEMO_RESIDENT = 1484


def demo_resident():
    m = meta()
    r = m["residents"][DEMO_RESIDENT]
    p = m["places"][r["home"]]
    flags = (["older"] if r["age"] in ("65-74", "75+") else []) + (["alone"] if r["alone"] else []) + \
        (["noac"] if not r["ac"] else []) + (["noheat"] if not r["heat"] else [])
    return {"name": r["name"], "home": {"name": p[2] or r["tract_name"], "lat": p[3], "lon": p[4]}, "flags": flags,
            "about": f"Simulated resident #{DEMO_RESIDENT}: {r['age']}, {r['role']}, {r['tract_name']}"}
