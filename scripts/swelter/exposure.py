"""Deterministic exposure scoring. No LLM here.

For each hour: hazard intensity at the resident's location x share of the hour outdoors x the indoor
environment where they are (AC / heat / filtration / flood-prone ground floor). Output is a danger
level 0 safe, 1 caution, 2 danger, 3 extreme. "Dangerous-exposure hours" = hours at level >= 2.
"""
from . import hazards as H
from .plan import ACTIVITIES, travel
from .world import World


def _band(value, bands, colder_is_worse=False):
    lvl = 0
    for thr, l in bands:
        if (value <= thr) if colder_is_worse else (value >= thr):
            lvl = l
    return lvl


def _route_flood(world: World, a, b):
    """Does a straight-line trip a->b pass a flood-prone spot? (5 samples)"""
    for t in (0.1, 0.3, 0.5, 0.7, 0.9):
        if world.flood_prone(a["lat"] + t * (b["lat"] - a["lat"]), a["lon"] + t * (b["lon"] - a["lon"])):
            return True
    return False


def score(world: World, r, scenario, plan, slots, intensity):
    hz, iv = scenario["hazard"], scenario["intervention"]
    vuln = r["vulnerable"]
    peak = max(intensity) if hz != "cold" else min(intensity)
    levels, values = [], []
    prev = slots["home"]
    for i, step in enumerate(plan["hours"]):
        act, slot = step["activity"], step["place"]
        place = slots[slot]
        I = intensity[i]
        mins, mode = travel(r, prev, place)
        outdoor = 1.0 if ACTIVITIES[act][0] else 0.0
        if mode in ("walk", "transit"):
            outdoor = max(outdoor, min(1.0, mins / 60 + (0.15 if mode == "transit" else 0)))
        at_home = slot == "home" and r["role"] != "unhoused"
        refuge = act == "refuge"
        loc = place

        if hz == "heat":
            out_v = I + world.heat_island(loc["lat"], loc["lon"])
            noac = 0.75 * out_v + 0.25 * (peak + world.heat_island(loc["lat"], loc["lon"]))
            if refuge:
                in_v = 76
            elif at_home:
                in_v = 77 if plan.get("ac_use") else noac
            else:
                a = loc.get("ac") if loc.get("ac") is not None else 0.8
                in_v = a * 76 + (1 - a) * noac
            bands = H.HEAT_BANDS_VULN if vuln else H.HEAT_BANDS
            lo, li = _band(out_v, bands), _band(in_v, bands)
            v = outdoor * out_v + (1 - outdoor) * in_v
        elif hz == "smoke":
            out_v = I * (0.3 if plan.get("mask") else 1.0)
            if refuge:
                f = 0.15
            elif at_home:
                f = 0.45 if r["ac"] else 0.75
            else:
                f = 0.5
            in_v = I * f
            bands = H.AQI_BANDS_VULN if vuln else H.AQI_BANDS
            lo, li = _band(out_v, bands), _band(in_v, bands)
            v = outdoor * out_v + (1 - outdoor) * in_v
        elif hz == "flood":
            prone = world.flood_prone(loc["lat"], loc["lon"])
            out_v = I * (1.0 if prone else 0.3)
            in_v = I * 0.8 if (prone and (at_home or r["role"] == "unhoused")) and not refuge else 0.0
            if mode == "car" and mins > 0 and _route_flood(world, prev, place):
                closed = iv == "closures" and step.get("why") != "unaware"
                out_v = max(out_v, 0 if closed else I * 1.5)
                outdoor = 1.0
            lo, li = _band(out_v, H.FLOOD_DEPTH_BANDS), _band(in_v, H.FLOOD_DEPTH_BANDS)
            v = max(outdoor * out_v, in_v)
        else:  # cold
            out_v = I - world.wind_exposure(loc["lat"], loc["lon"])
            if refuge:
                in_v = 68
            elif at_home:
                in_v = 68 if plan.get("heat_on") else 50 + (4 if I > 20 else 0)
            else:
                in_v = 66
            bands = H.CHILL_BANDS_VULN if vuln else H.CHILL_BANDS
            lo = _band(out_v, bands, colder_is_worse=True)
            li = 0
            if in_v <= 60:
                li = (3 if in_v <= 48 else 2 if in_v <= 55 else 1) if vuln else (2 if in_v <= 48 else 1 if in_v <= 55 else 0)
            v = outdoor * out_v + (1 - outdoor) * in_v

        if outdoor >= 0.25:
            lvl = max(lo, li if outdoor < 1 else 0)
        elif outdoor > 0:
            lvl = max(lo - 1, li)
        else:
            lvl = li
        levels.append(int(max(0, lvl)))
        values.append(round(v, 1))
        prev = place
    return levels, values


def summarize(residents, levels_by_res, groups):
    """Mean dangerous-exposure hours per person, by group, plus city-wide counts."""
    out = {"groups": {}, "all": {}}
    for g in ["all"] + groups:
        members = [r["id"] for r in residents if g == "all" or g in r["groups"]]
        if not members:
            continue
        dh = [sum(1 for l in levels_by_res[m] if l >= 2) for m in members]
        out["groups" if g != "all" else "all"][g] = {
            "n": len(members),
            "danger_hours": round(sum(dh) / len(dh), 2),
            "share_any_danger": round(sum(1 for x in dh if x) / len(dh), 3),
        }
    hourly = [[0, 0, 0, 0] for _ in H.HOURS]
    for lv in levels_by_res.values():
        for i, l in enumerate(lv):
            hourly[i][l] += 1
    out["hourly_levels"] = hourly
    return out
