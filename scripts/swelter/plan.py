"""The behavior schema every planner (rules or LLM) must emit, slot resolution, travel, and the verifier.

A day plan is 17 hourly slots (6am..10pm). Each slot = (activity, place_slot). Activities come from a fixed
list; place slots are symbolic ("library", "refuge") and resolve to real OSM places per resident. Nothing
free-text reaches the map.
"""
from .hazards import HOURS, SITES
from .world import HOURS_OPEN, World, dist_m

ACTIVITIES = {
    # name: (outdoors?, description)
    "sleep": (False, "asleep at home"),
    "home": (False, "at home"),
    "commute": (False, "travelling to the slot's place (mode depends on car access/distance)"),
    "work_indoor": (False, "working indoors"),
    "work_outdoor": (True, "working outdoors (construction, delivery, landscaping)"),
    "class": (False, "in class / on campus"),
    "errand": (False, "shopping, pharmacy, appointments"),
    "leisure_indoor": (False, "indoor leisure: eating out, gym, community centre, worship"),
    "leisure_outdoor": (True, "outdoor leisure: park, stoop, playground"),
    "exercise_outdoor": (True, "walking, running, sports outdoors"),
    "public_indoor": (False, "spending time in a public building (library, rec centre) to escape conditions"),
    "refuge": (False, "at the official cooling / clean-air / warming center or shelter"),
    "outdoors_unsheltered": (True, "outdoors without shelter (sleeping rough, staying on the street)"),
}
ACTIVITY_LIST = list(ACTIVITIES)

SLOTS = {
    "home": None, "work": None, "campus": {"campus"}, "grocery": {"grocery", "shop"}, "food": {"food"},
    "park": {"park"}, "library": {"library"}, "community_centre": {"community_centre", "leisure_indoor"},
    "worship": {"worship"}, "health": {"health"}, "pool": {"pool"}, "refuge": None,
}
SLOT_LIST = list(SLOTS)

WALK_KMH, OLDER_WALK_KMH, TRANSIT_KMH, CAR_KMH = 4.5, 3.2, 13.0, 25.0


def refuge_place(world: World, resident, scenario):
    """The official refuge for this scenario, if any, and its open hours."""
    hz, iv, site = scenario["hazard"], scenario["intervention"], scenario["site"]
    if iv == "refuge":
        hours = {"heat": (9, 20), "smoke": (9, 20), "flood": (15, 24), "cold": (0, 24)}[hz]
        return world.by_id[SITES[site]["place_id"]], hours
    if hz == "heat" and iv == "transit":
        # Free SEPTA to the city's existing library cooling sites (regular library hours).
        home = world.by_id[resident["home"]]
        return world.nearest(home["lat"], home["lon"], {"library"}), HOURS_OPEN["library"]
    if hz == "cold" and iv == "outreach":
        home = world.by_id[resident["home"]]
        return world.nearest(home["lat"], home["lon"], {"community_centre"}), (0, 24)
    return None, None


def resolve_slots(world: World, resident, scenario):
    """slot name -> place dict (or None when the slot does not exist for this resident)."""
    home = world.by_id[resident["home"]]
    out = {"home": home, "work": world.by_id.get(resident["work"]) if resident["work"] else None}
    anchor_work = out["work"] or home
    for slot, kinds in SLOTS.items():
        if kinds is None:
            continue
        # Lunch food is near work; everything else near home.
        a = anchor_work if slot == "food" and out["work"] else home
        out[slot] = world.nearest(a["lat"], a["lon"], kinds)
    if resident["role"] == "student" and out["work"]:
        out["campus"] = out["work"]
    out["refuge"], _ = refuge_place(world, resident, scenario)
    return out


def travel(resident, a, b):
    """(minutes, mode) for a trip a -> b."""
    if a is None or b is None or a["id"] == b["id"]:
        return 0.0, "none"
    d = dist_m(a["lat"], a["lon"], b["lat"], b["lon"]) / 1000
    older = resident["age"] in ("65-74", "75+")
    if d < 1.2:
        return 60 * d / (OLDER_WALK_KMH if older else WALK_KMH), "walk"
    if resident["car"]:
        return 60 * d / CAR_KMH + 4, "car"
    return 60 * d / TRANSIT_KMH + 8, "transit"


def is_open(place, slot, hour, refuge_hours):
    if slot in ("home", "work", "campus", "park"):
        return True
    if slot == "refuge":
        return refuge_hours is not None and refuge_hours[0] <= hour < refuge_hours[1]
    lo, hi = HOURS_OPEN.get(place["kind"], (0, 24))
    return lo <= hour < hi


def verify(world: World, resident, scenario, plan, slots=None):
    """Return a list of human-readable violations (empty = plausible day)."""
    v = []
    hours = plan.get("hours", [])
    if len(hours) != len(HOURS):
        return [f"expected {len(HOURS)} hourly slots, got {len(hours)}"]
    slots = slots or resolve_slots(world, resident, scenario)
    _, refuge_hours = refuge_place(world, resident, scenario)
    unhoused = resident["role"] == "unhoused"
    prev = slots["home"]
    for i, step in enumerate(hours):
        h = HOURS[i]
        act, slot = step.get("activity"), step.get("place")
        if act not in ACTIVITIES:
            v.append(f"{h}:00 unknown activity '{act}'")
            continue
        if slot not in SLOTS:
            v.append(f"{h}:00 unknown place '{slot}'")
            continue
        place = slots.get(slot)
        if place is None:
            v.append(f"{h}:00 '{slot}' does not exist for this resident/scenario")
            continue
        if unhoused and act in ("home", "sleep"):
            v.append(f"{h}:00 unhoused resident cannot be 'at home'")
        if not unhoused and act == "outdoors_unsheltered":
            v.append(f"{h}:00 housed resident marked unsheltered")
        if act in ("home", "sleep") and slot != "home":
            v.append(f"{h}:00 '{act}' must be at home")
        if act == "refuge" and slot != "refuge":
            v.append(f"{h}:00 'refuge' activity must use the refuge place")
        if act in ("work_indoor", "work_outdoor") and slot != "work":
            v.append(f"{h}:00 work happens at the work place")
        if not is_open(place, slot, h, refuge_hours) and act != "commute":
            v.append(f"{h}:00 {place['name'] or slot} is closed")
        mins, mode = travel(resident, prev, place)
        if mins > 60:
            v.append(f"{h}:00 {mins:.0f}-min {mode} trip cannot fit in one hour")
        elif mins > 30 and act != "commute" and (i == 0 or hours[i - 1].get("activity") != "commute"):
            v.append(f"{h}:00 {mins:.0f}-min {mode} trip with no travel slot")
        prev = place
    return v


def repair(plan, violations_by_hour):
    """Last-resort fix: replace each violating hour with the resident's previous valid step (or home)."""
    hours = [dict(s) for s in plan["hours"]]
    for i in sorted(violations_by_hour):
        hours[i] = dict(hours[i - 1]) if i > 0 else {"activity": "home", "place": "home"}
        if hours[i].get("activity") == "commute":
            hours[i]["activity"] = "home" if hours[i]["place"] == "home" else "public_indoor"
    return {**plan, "hours": hours}


def bad_hours(violations):
    out = set()
    for msg in violations:
        head = msg.split(":")[0]
        if head.isdigit():
            out.add(int(head) - HOURS[0])
    return out
