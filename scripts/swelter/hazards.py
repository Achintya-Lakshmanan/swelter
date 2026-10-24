"""Hazard definitions: hourly intensity curves, interventions, groups, and danger thresholds.

Everything here is deterministic config. The planner (rules or LLM) decides behavior; exposure.py
uses these curves and thresholds to score it.
"""
import math

HOURS = list(range(6, 23))  # 6am .. 10pm, one slot per hour (17 slots)

# Candidate refuge sites (real OSM places). Used by cooling / clean-air / warming / flood-shelter runs.
SITES = {
    "parkway": {"place_id": "w32122450", "label": "Parkway Central Library (Center City)"},
    "huntingpark": {"place_id": "w1240008921", "label": "Hunting Park NAC (Hunting Park)"},
    "marrero": {"place_id": "w601325283", "label": "Lillian Marrero Library (Fairhill)"},
}


def _diurnal(h, lo, hi, peak_hour=16, width=5.0):
    """Smooth bump peaking at peak_hour; lo at the far tails."""
    return lo + (hi - lo) * math.exp(-((h - peak_hour) / width) ** 2)


def _trough(h, day_hi, night_lo, warm_hour=14):
    """Cold curve: warmest mid-afternoon, coldest at 6am and late evening."""
    return night_lo + (day_hi - night_lo) * math.exp(-((h - warm_hour) / 5.0) ** 2)


HAZARDS = {
    "heat": {
        "label": "Heatwave",
        "unit": "°F heat index",
        "history": "July 1993 Philadelphia heat wave (100+ heat deaths) led to the city's Heat Health Emergency program and Heatline.",
        "levels": {
            "moderate": {"label": "Moderate", "curve": lambda h: _diurnal(h, 82, 96)},
            "severe": {"label": "Severe", "curve": lambda h: _diurnal(h, 86, 105)},
            "extreme": {"label": "Extreme", "curve": lambda h: _diurnal(h, 90, 114)},
        },
        "interventions": {
            "none": {"label": "Do nothing"},
            "refuge": {"label": "Cooling center", "site": True,
                       "desc": "Air-conditioned cooling center open 9am–8pm at the chosen site."},
            "transit": {"label": "Free SEPTA to cooling", "site": False,
                        "desc": "Free fares + extended hours on routes to the city's existing library cooling sites."},
            "alert": {"label": "Early heat alert", "site": False,
                      "desc": "Heat Health Emergency declared a day early: Heatline, block-captain checks, outdoor work shifted to dawn."},
        },
        "groups": ["older_alone", "outdoor_worker", "no_ac", "student", "unhoused"],
    },
    "smoke": {
        "label": "Wildfire smoke",
        "unit": "AQI (PM2.5)",
        "history": "June 2023 Canadian wildfire smoke pushed Philadelphia's AQI into the hazardous range and triggered a Code Red.",
        "levels": {
            "moderate": {"label": "Unhealthy", "curve": lambda h: _diurnal(h, 110, 165, peak_hour=14, width=6)},
            "severe": {"label": "Very unhealthy", "curve": lambda h: _diurnal(h, 150, 260, peak_hour=14, width=6)},
            "extreme": {"label": "Hazardous", "curve": lambda h: _diurnal(h, 220, 420, peak_hour=14, width=6)},
        },
        "interventions": {
            "none": {"label": "Do nothing"},
            "refuge": {"label": "Clean-air center", "site": True,
                       "desc": "HEPA-filtered clean-air center open 9am–8pm at the chosen site."},
            "n95": {"label": "N95 giveaway", "site": False,
                    "desc": "Free N95s at libraries, rec centers and outreach vans; masks cut outdoor PM2.5 dose ~70%."},
            "alert": {"label": "Code Red air alert", "site": False,
                      "desc": "Early air-quality alert: outdoor events cancelled, outdoor work paused above AQI 200."},
        },
        "groups": ["respiratory", "outdoor_worker", "older_alone", "no_ac", "unhoused"],
    },
    "flood": {
        "label": "Flash flood",
        "unit": "in/hr rainfall",
        "history": "Hurricane Ida remnants, Sept 2021: the Schuylkill posted its highest crest in over a century and I-676 (Vine St Expressway) flooded.",
        "levels": {
            "moderate": {"label": "Heavy storm", "curve": lambda h: _diurnal(h, 0.0, 1.0, peak_hour=18, width=2.2)},
            "severe": {"label": "Flash flood", "curve": lambda h: _diurnal(h, 0.0, 2.0, peak_hour=18, width=2.4)},
            "extreme": {"label": "Ida-scale", "curve": lambda h: _diurnal(h, 0.05, 3.2, peak_hour=18, width=2.8)},
        },
        "interventions": {
            "none": {"label": "Do nothing"},
            "refuge": {"label": "Emergency shelter", "site": True,
                       "desc": "Shelter opened at the chosen site from 3pm; flood-zone residents told to evacuate there."},
            "closures": {"label": "Pre-emptive road closures", "site": False,
                         "desc": "Flood-prone roads (Kelly/MLK Dr, I-676, riverside) closed before the storm; trips rerouted."},
            "alert": {"label": "Early flood warning", "site": False,
                      "desc": "Flash-flood warning pushed 3 hours earlier with 'don't drive' guidance."},
        },
        "groups": ["flood_zone", "driver", "no_car", "older_alone", "unhoused"],
    },
    "cold": {
        "label": "Winter storm",
        "unit": "°F wind chill",
        "history": "Philadelphia Code Blue: declared when temperature or wind chill drops to 20°F or below; unsheltered residents at highest risk.",
        "levels": {
            "moderate": {"label": "Cold snap", "curve": lambda h: _trough(h, 28, 15)},
            "severe": {"label": "Arctic blast", "curve": lambda h: _trough(h, 14, 0)},
            "extreme": {"label": "Polar vortex", "curve": lambda h: _trough(h, 0, -15)},
        },
        "interventions": {
            "none": {"label": "Do nothing"},
            "refuge": {"label": "Warming center", "site": True,
                       "desc": "24-hour Code Blue warming center at the chosen site."},
            "outreach": {"label": "Outreach + open stations", "site": False,
                         "desc": "Homeless outreach vans and SEPTA concourses kept open overnight as refuge."},
            "alert": {"label": "Early Code Blue", "site": False,
                      "desc": "Code Blue declared early with utility shutoff moratorium; heat restored for many shut-off homes."},
        },
        "groups": ["older_alone", "no_heat", "unhoused", "outdoor_worker", "no_car"],
    },
}

GROUP_LABELS = {
    "older_alone": "Older adults living alone",
    "outdoor_worker": "Outdoor workers",
    "no_ac": "No-AC households",
    "student": "Students",
    "unhoused": "Unhoused residents",
    "respiratory": "Asthma / COPD",
    "flood_zone": "Live in flood-prone area",
    "driver": "Drivers",
    "no_car": "Car-free households",
    "no_heat": "No reliable heat",
}

# Danger levels per hour: 0 safe, 1 caution, 2 danger, 3 extreme. "Dangerous-exposure hours" = level >= 2.
# Thresholds are tightened for vulnerable residents (older adults, respiratory conditions, unhoused).
HEAT_BANDS = [(90, 1), (103, 2), (115, 3)]          # NWS heat index categories
HEAT_BANDS_VULN = [(85, 1), (95, 2), (105, 3)]
AQI_BANDS = [(101, 1), (201, 2), (301, 3)]          # EPA AQI categories
AQI_BANDS_VULN = [(51, 1), (151, 2), (201, 3)]
CHILL_BANDS = [(32, 1), (10, 2), (-10, 3)]          # colder is worse (<=)
CHILL_BANDS_VULN = [(40, 1), (20, 2), (0, 3)]
FLOOD_DEPTH_BANDS = [(0.4, 1), (1.0, 2), (2.0, 3)]  # in/hr while in a flood-prone spot


def scenario_ids():
    """Every precomputed run id: hazard_level_intervention[_site]."""
    out = []
    for hz, h in HAZARDS.items():
        for lvl in h["levels"]:
            for iv, ivd in h["interventions"].items():
                if ivd.get("site"):
                    out += [f"{hz}_{lvl}_{iv}_{s}" for s in SITES]
                else:
                    out.append(f"{hz}_{lvl}_{iv}")
    return out


def parse_scenario(sid):
    parts = sid.split("_")
    return {"hazard": parts[0], "level": parts[1], "intervention": parts[2],
            "site": parts[3] if len(parts) > 3 else None}


def intensity(hazard, level):
    curve = HAZARDS[hazard]["levels"][level]["curve"]
    return [round(curve(h), 2) for h in HOURS]


def meta():
    """JSON-safe view of the config for the frontend."""
    return {
        "hours": HOURS,
        "sites": SITES,
        "groups": GROUP_LABELS,
        "hazards": {
            hz: {
                "label": h["label"], "unit": h["unit"], "history": h["history"], "groups": h["groups"],
                "levels": {k: {"label": v["label"], "intensity": intensity(hz, k)} for k, v in h["levels"].items()},
                "interventions": {k: {kk: vv for kk, vv in v.items()} for k, v in h["interventions"].items()},
            }
            for hz, h in HAZARDS.items()
        },
    }
