"""Rule-based planner: ATUS-style day templates + hazard behavior rules.

This is the offline default (no API key needed) and the fallback when the LLM's plan fails verification.
RULES_TEXT is the same knowledge, written for the LLM planner. Each hour carries a reason code (`why`)
that the inspector and the live explainer use.

Common random numbers: a resident's random draws depend only on (resident, hazard), so the same person
makes the same baseline choices in every intervention — differences between runs come from the
intervention, not from noise.
"""
import random

from .hazards import HOURS
from .plan import refuge_place, travel
from .world import dist_m

# Of residents who hear a warning and had optional outdoor plans in dangerous hours: share who cancel,
# share who shift to a safer hour; the rest go anyway (vulnerable residents never "go anyway").
AVOID_CANCEL, AVOID_SHIFT = 0.35, 0.45

REASONS = {
    "routine": "normal weekday routine",
    "commute": "travelling",
    "unaware": "didn't hear the warning, kept their routine",
    "avoid_hazard": "heard the warning and stayed in instead of going out",
    "shift_early": "moved the activity to a safer hour of the day",
    "work_continues": "employer kept the outdoor shift going",
    "alert_shift": "employer shifted or paused outdoor work after the official alert",
    "self_break": "took an indoor break from outdoor work",
    "seek_refuge": "went to the official refuge (cooling / clean-air / warming center or shelter)",
    "too_far": "refuge was too far to reach without a car or transit",
    "informal_refuge": "spent hours in a nearby library or rec centre to escape conditions",
    "no_option": "had nowhere better to go, stayed put",
    "ac_cost": "has AC but kept it off to save on the electric bill",
    "evacuate": "left a flood-prone home for the shelter",
    "delay_trip": "waited out the storm before driving",
    "detour": "road closure forced a detour around flooded streets",
    "outreach": "outreach workers brought them indoors",
    "heat_restored": "utility shutoff moratorium restored their heat",
    "masked": "wore an N95 from the giveaway",
    "unsheltered": "no home to go to",
}

RULES_TEXT = """
Behavior knowledge (Philadelphia; cite as heat/smoke/flood/cold behavior literature + city programs):
GENERAL
- Only people who hear a warning change behavior. Baseline awareness ~55% (older adults living alone ~45%).
  An early official alert (Heatline, block captains, push alerts, Code Red/Blue) raises it to ~85-90%.
- Aware people with optional outdoor plans in dangerous hours: ~35% cancel, ~45% shift them to a safer hour, ~20% go
  anyway (vulnerable people don't). Philadelphia mobility data show only small hot-day drops in park visits. Unaware
  people keep their routine.
- Officially designated refuges only help people who can reach them: ~1 km on foot (0.7 km for older adults),
  ~4 km by SEPTA if they are willing (free fares raise willingness), any distance by car. Unhoused people walk up to ~2 km.
- Outdoor workers usually keep working unless the employer changes the shift; official alerts make employers
  shift work to dawn or pause it.
HEAT: dangerous from ~11am-7pm. Homes without AC stay hot into the evening (Philadelphia rowhomes trap heat).
  Some low-income older adults with AC keep it off to save money. Libraries are informal cooling spots.
SMOKE: indoor air with windows open (no AC) is ~75% as bad as outside; central AC ~45%; HEPA refuge ~15%.
  N95 masks cut outdoor dose ~70% if worn. People with asthma/COPD who are aware stay indoors.
FLOOD: rain peaks ~4-9pm. Most flood deaths are people driving into water. Ground-floor/basement homes near
  rivers flood. Aware drivers wait the storm out or leave early; road closures force detours.
COLD: unsheltered residents and homes without reliable heat are at risk all day. Code Blue outreach brings
  unhoused people indoors; utility shutoff moratoria restore heat to some homes.
"""


def _template(r, rng):
    """ATUS-style weekday templates. Returns 17 [activity, slot, why]."""
    role = r["role"]
    S = lambda a, s, w="routine": [a, s, w]  # noqa: E731
    home, sleep = S("home", "home"), S("sleep", "home")
    p = [home] * len(HOURS)

    def put(h, step):
        p[h - 6] = step

    if role in ("office", "service", "healthcare"):
        start, end = {"office": (9, 17), "service": (10, 18), "healthcare": (7, 19)}[role]
        put(6, sleep)
        put(start - 1, S("commute", "work", "commute"))
        for h in range(start, end):
            put(h, S("work_indoor", "work"))
        if role == "office" and rng.random() < 0.5:
            put(12, S("leisure_indoor", "food"))
        put(end, S("commute", "home", "commute"))
        if end + 1 <= 21 and rng.random() < 0.3:
            put(end + 1, S("errand", "grocery"))
        if role == "office" and rng.random() < 0.25:
            put(19, S("exercise_outdoor", "park"))
        put(22, sleep)
    elif role == "outdoor":
        put(6, S("commute", "work", "commute"))
        for h in range(7, 15):
            put(h, S("work_outdoor", "work"))
        put(15, S("commute", "home", "commute"))
        if rng.random() < 0.3:
            put(17, S("errand", "grocery"))
        if rng.random() < 0.35:
            put(18, S("leisure_outdoor", "park"))
        put(22, sleep)
    elif role == "student":
        for h in (6, 7, 8):
            put(h, sleep)
        put(9, S("commute", "campus", "commute"))
        for h in range(10, 15):
            put(h, S("class", "campus"))
        put(12, S("leisure_indoor", "food"))
        if rng.random() < 0.5:
            put(15, S("public_indoor", "library"))
            put(16, S("public_indoor", "library"))
        else:
            put(15, S("class", "campus"))
            put(16, S("commute", "home", "commute"))
        if rng.random() < 0.35:
            put(17, S("exercise_outdoor", "park"))
        if rng.random() < 0.4:
            put(19, S("leisure_outdoor", "park"))
        if rng.random() < 0.4:
            put(20, S("leisure_indoor", "food"))
    elif role in ("retired", "not_employed"):
        put(6, sleep)
        u = rng.random()
        if u < 0.45:
            put(10, S("errand", "grocery"))
        elif u < 0.7:
            put(9, S("exercise_outdoor", "park"))
        if rng.random() < 0.25:
            put(11, S("leisure_indoor", "community_centre"))
        if rng.random() < (0.3 if role == "retired" else 0.4):
            put(15, S("leisure_outdoor", "park"))
            put(16, S("leisure_outdoor", "park"))
        if rng.random() < 0.2:
            put(14, S("errand", "health"))
        if rng.random() < 0.1:
            put(18, S("leisure_indoor", "worship"))
        put(22, sleep)
    elif role == "unhoused":
        p = [S("outdoors_unsheltered", "home", "unsheltered")] * len(HOURS)
        if rng.random() < 0.5:
            p[9 - 6] = S("leisure_indoor", "community_centre")  # meal program
        if rng.random() < 0.4:
            p[17 - 6] = S("leisure_indoor", "worship")  # evening meal
        if rng.random() < 0.2:
            for h in (13, 14, 15):
                p[h - 6] = S("public_indoor", "library")
    return [list(s) for s in p]


class RulePlanner:
    name = "rules"

    def __init__(self, world):
        self.w = world

    def plan(self, r, scenario, slots, intensity, attempt=0):
        hz, iv = scenario["hazard"], scenario["intervention"]
        rng = random.Random(f"{r['id']}-{hz}-{attempt}")
        p = _template(r, rng)
        older = r["age"] in ("65-74", "75+")
        vuln = r["vulnerable"]

        # Awareness: one draw per resident, threshold raised by an early alert.
        base = 0.45 if (older and r["alone"]) else 0.55
        aware = rng.random() < (0.88 if iv == "alert" else base)
        u_refuge, u_ac, u_mask, u_misc = rng.random(), rng.random(), rng.random(), rng.random()
        extra = {"aware": aware, "ac_use": r["ac"], "mask": False, "heat_on": r["heat"]}

        refuge, rhours = refuge_place(self.w, r, scenario)
        home = slots["home"]
        reach = False
        if refuge is not None:
            d = dist_m(home["lat"], home["lon"], refuge["lat"], refuge["lon"]) / 1000
            walk_km = 2.0 if r["role"] == "unhoused" else 0.7 if older else 1.0
            transit_willing = 0.85 if (hz == "heat" and iv == "transit") else 0.45
            reach = d <= walk_km or r["car"] or (d <= 4.0 and u_refuge < transit_willing)

        I = dict(zip(HOURS, intensity))
        if hz == "heat":
            danger = {h for h in HOURS if I[h] >= (90 if vuln else 95)}
        elif hz == "smoke":
            danger = {h for h in HOURS if I[h] >= (150 if vuln else 200)}
        elif hz == "flood":
            danger = {h for h in HOURS if I[h] >= 0.6}
        else:
            danger = {h for h in HOURS if I[h] <= (25 if vuln else 15)}

        def set_(h, a, s, why):
            p[h - 6] = [a, s, why]

        def at(h):
            return p[h - 6]

        # 1) optional outdoor activities during dangerous hours. Aware people mostly *shift* to a safer hour rather
        # than cancel (calibrated against Philadelphia hot-day mobility, see scripts/validate.py); some go anyway.
        u_avoid = rng.random()
        style = "cancel" if u_avoid < AVOID_CANCEL else "shift" if u_avoid < AVOID_CANCEL + AVOID_SHIFT else "go"
        if vuln and style == "go":
            style = "cancel"
        for h in sorted(danger):
            a, s, _ = at(h)
            if a in ("leisure_outdoor", "exercise_outdoor") or (a == "errand" and hz in ("flood", "smoke")):
                if not aware or style == "go":
                    p[h - 6][2] = "unaware" if not aware else "routine"
                    continue
                set_(h, "home", "home", "avoid_hazard")
                if style == "shift":
                    free = [x for x in HOURS if x not in danger and 7 <= x <= 21 and at(x)[:2] == ["home", "home"]]
                    if free:
                        x = min(free, key=lambda x: abs(x - h))
                        set_(x, a, s, "shift_early")

        # 2) outdoor workers
        if r["role"] == "outdoor":
            work_hours = [h for h in HOURS if at(h)[0] == "work_outdoor"]
            if iv == "alert" and hz in ("heat", "smoke", "cold"):
                # Shift ends when the dangerous afternoon starts; dangerous morning hours move indoors.
                cutoff = min([h for h in work_hours if h in danger and h >= 11], default=None)
                for h in work_hours:
                    if cutoff is not None and h == cutoff:
                        set_(h, "commute", "home", "alert_shift")
                    elif cutoff is not None and h > cutoff:
                        set_(h, "home", "home", "alert_shift")
                    elif h in danger:
                        set_(h, "work_indoor", "work", "alert_shift")
                if cutoff is not None:
                    for h in HOURS:
                        if h > cutoff and at(h)[0] == "commute" and at(h)[1] == "home":
                            set_(h, "home", "home", "routine")
            else:
                for h in work_hours:
                    if h in danger:
                        p[h - 6][2] = "work_continues"
                if aware and hz == "heat" and 13 in danger and at(13)[0] == "work_outdoor":
                    set_(13, "work_indoor", "work", "self_break")
            if hz == "smoke" and iv == "n95" and u_mask < 0.75:
                extra["mask"] = True

        if hz == "smoke" and iv == "n95" and r["role"] in ("unhoused",) and u_mask < 0.6:
            extra["mask"] = True
        if hz == "smoke" and iv == "n95" and older and aware and u_mask < 0.5:
            extra["mask"] = True

        # 3) home conditions that drive refuge-seeking
        if hz == "heat" and r["ac"] and r["poverty"] and older and u_ac < 0.3:
            extra["ac_use"] = False
        if hz == "cold" and not r["heat"] and iv == "alert" and u_misc < 0.5:
            extra["heat_on"] = True
        home_bad = {
            "heat": not extra["ac_use"],
            "smoke": (not r["ac"]) or r["respiratory"],
            "flood": r["flood_zone"],
            "cold": not extra["heat_on"],
        }[hz] or r["role"] == "unhoused"

        if hz == "smoke" and r["respiratory"] and aware:
            for h in HOURS:
                if at(h)[0] in ("errand", "leisure_indoor", "leisure_outdoor", "exercise_outdoor") and h in danger:
                    set_(h, "home", "home", "avoid_hazard")

        # 4) refuge seeking
        free_hours = [h for h in HOURS if h in danger and at(h)[0] in ("home", "outdoors_unsheltered", "public_indoor", "leisure_indoor")]
        if hz == "flood":
            free_hours = [h for h in HOURS if h >= 15 and at(h)[0] in ("home", "outdoors_unsheltered")]
        if hz == "cold":
            free_hours = [h for h in HOURS if 7 <= h <= 22 and at(h)[0] in ("home", "outdoors_unsheltered", "public_indoor", "leisure_indoor")]

        wants = home_bad and (aware or (r["role"] == "unhoused" and iv in ("outreach", "alert")))
        if r["role"] == "unhoused" and iv == "outreach" and hz == "cold":
            wants = u_refuge < 0.8
        if wants and refuge is not None and reach:
            hrs = [h for h in free_hours if rhours[0] <= h < rhours[1]]
            if hrs:
                why = "evacuate" if hz == "flood" else "outreach" if iv == "outreach" else "seek_refuge"
                first = min(hrs)
                prev_place = slots[at(first - 1)[1]] if first > 6 else home
                mins, _ = travel(r, prev_place, refuge)
                if mins > 30:
                    set_(first, "commute", "refuge", "commute")
                    hrs = [h for h in hrs if h != first]
                for h in hrs:
                    set_(h, "refuge", "refuge", why)
                last = max(hrs + [first])
                if last + 1 <= 22 and hz != "flood" and not (hz == "cold" and r["role"] == "unhoused"):
                    back = "outdoors_unsheltered" if r["role"] == "unhoused" else "home"
                    set_(last + 1, back, "home", "routine")
        elif wants and refuge is not None and not reach:
            for h in free_hours:
                p[h - 6][2] = "too_far"
        # informal refuge: a nearby library/rec centre during its hours
        if home_bad and hz in ("heat", "smoke", "cold") and not any(s[0] == "refuge" for s in p):
            lib = slots["library"]
            near = lib and dist_m(home["lat"], home["lon"], lib["lat"], lib["lon"]) < (1500 if r["role"] == "unhoused" else 600)
            if near and (aware or r["role"] == "unhoused") and u_misc < (0.4 if r["role"] == "unhoused" else 0.3):
                for h in range(12, 17):
                    if h in danger or hz == "cold":
                        set_(h, "public_indoor", "library", "informal_refuge")
            else:
                for h in free_hours:
                    if p[h - 6][2] == "routine":
                        p[h - 6][2] = "no_option" if r["role"] != "unhoused" else "unsheltered"

        # 5) flood driving
        if hz == "flood" and r["car"]:
            h = HOURS[0]
            while h <= HOURS[-1]:
                a, s, _ = at(h)
                if a == "commute" and h in danger:
                    if aware and h > HOURS[0] and at(h - 1)[0] != "commute":
                        # wait it out where you are, drive after the peak
                        stay_a, stay_s, _ = at(h - 1)
                        later = next((x for x in HOURS if x > h and x not in danger), None)
                        for x in range(h, (later or HOURS[-1] + 1)):
                            set_(x, stay_a, stay_s, "delay_trip")
                        if later:
                            set_(later, "commute", s, "commute")
                        h = (later or HOURS[-1]) + 1
                        continue
                    elif iv == "closures":
                        p[h - 6][2] = "detour"
                    else:
                        p[h - 6][2] = "unaware"
                h += 1

        if not extra["ac_use"] and r["ac"] and hz == "heat":
            for h in HOURS:
                if at(h)[0] in ("home", "sleep") and h in danger and p[h - 6][2] in ("routine", "no_option"):
                    p[h - 6][2] = "ac_cost"
        if extra["heat_on"] and not r["heat"]:
            for h in HOURS:
                if at(h)[0] in ("home", "sleep") and p[h - 6][2] in ("routine", "no_option"):
                    p[h - 6][2] = "heat_restored"
        if extra["mask"]:
            for h in HOURS:
                if at(h)[0] in ("work_outdoor", "outdoors_unsheltered") and h in danger:
                    p[h - 6][2] = "masked"

        return {"hours": [{"activity": a, "place": s, "why": w} for a, s, w in p], **extra}
