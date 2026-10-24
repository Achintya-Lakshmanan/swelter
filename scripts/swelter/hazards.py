"""Hazard definitions: real hourly days, interventions, groups, and danger thresholds.

Every hazard level replays a real day from the record (scripts/derive_inputs.py -> data/hazard_days.json):
the median event day, the 95th-percentile event day, and the worst day on record. Heat index and wind chill come from
NOAA hourly observations at PHL airport (2010-2024), rainfall is the trailing 3-hour total at PHL, and smoke is the
EPA PM2.5 NowCast AQI averaged over Philadelphia County monitors (2010-2025, satellite-confirmed smoke days). The
planner decides behavior; exposure.py uses these series and thresholds to score it.
"""
import json
from datetime import date

from .world import DATA

HOURS = list(range(6, 23))  # 6am .. 10pm, one slot per hour (17 slots)
DAYS = json.loads((DATA / "hazard_days.json").read_text())
REFUGES = json.loads((DATA / "inputs.json").read_text())["refuges"]
N_COOL = sum(r["cooling"] for r in REFUGES)
N_WARM = sum(r["warming"] for r in REFUGES)
LEVEL_WORDS = {"moderate": "Typical", "severe": "Severe", "extreme": "Record"}


def _level(hz, lvl):
    d = DAYS[hz][lvl]
    dt = date.fromisoformat(d["date"])
    return {"label": f"{LEVEL_WORDS[lvl]} \u2014 {dt:%b} {dt.day}, {dt.year}", "date": d["date"],
            "note": d["rank_note"], "values": d["values"]}


HAZARDS = {
    "heat": {
        "label": "Heatwave",
        "unit": "°F heat index",
        "history": "July 1993 Philadelphia heat wave (100+ heat deaths) led to the city's Heat Health Emergency program and Heatline.",
        "levels": {k: _level("heat", k) for k in LEVEL_WORDS},
        "interventions": {
            "none": {"label": "Do nothing"},
            "refuge": {"label": "Open cooling sites",
                       "desc": f"The city's {N_COOL} designated cooling sites (libraries, PHA and rec centers, community partners) open at their posted hours."},
            "transit": {"label": "Free SEPTA to cooling",
                        "desc": "Cooling sites open, plus free fares to the nearest one, so more people are willing to make the trip."},
            "alert": {"label": "Early heat alert",
                      "desc": "Heat Health Emergency declared a day early: Heatline, block-captain checks, outdoor work shifted to dawn."},
        },
        "groups": ["older_alone", "outdoor_worker", "no_ac", "student", "unhoused"],
    },
    "smoke": {
        "label": "Wildfire smoke",
        "unit": "AQI (PM2.5)",
        "history": "June 2023 Canadian wildfire smoke pushed Philadelphia's AQI into the hazardous range and triggered a Code Red.",
        "levels": {k: _level("smoke", k) for k in LEVEL_WORDS},
        "interventions": {
            "none": {"label": "Do nothing"},
            "refuge": {"label": "Clean-air rooms",
                       "desc": f"The city's {N_COOL} cooling sites run as HEPA-filtered clean-air rooms at their posted hours."},
            "n95": {"label": "N95 giveaway",
                    "desc": "Free N95s at libraries, rec centers and outreach vans; masks cut outdoor PM2.5 dose ~70%."},
            "alert": {"label": "Code Red air alert",
                      "desc": "Early air-quality alert: outdoor events cancelled, outdoor work paused above AQI 200."},
        },
        "groups": ["respiratory", "outdoor_worker", "older_alone", "no_ac", "unhoused"],
    },
    "flood": {
        "label": "Flash flood",
        "unit": "in of rain in past 3 h",
        "history": "The record day (July 28, 2013) is PHL's heaviest 3-hour rainfall since 2010. Ida (Sept 2021) flooded the Schuylkill and I-676 mostly from upstream rain, which this rainfall-only model does not capture.",
        "levels": {k: _level("flood", k) for k in LEVEL_WORDS},
        "interventions": {
            "none": {"label": "Do nothing"},
            "refuge": {"label": "Emergency shelters",
                       "desc": "City sites outside the FEMA flood zone open as shelters from 3pm; flood-zone residents told to evacuate."},
            "closures": {"label": "Pre-emptive road closures",
                         "desc": "Flood-prone roads (Kelly/MLK Dr, I-676, riverside) closed before the storm; trips rerouted."},
            "alert": {"label": "Early flood warning",
                      "desc": "Flash-flood warning pushed 3 hours earlier with 'don't drive' guidance."},
        },
        "groups": ["flood_zone", "driver", "no_car", "older_alone", "unhoused"],
    },
    "cold": {
        "label": "Winter storm",
        "unit": "°F wind chill",
        "history": "Philadelphia Code Blue: declared when temperature or wind chill drops to 20°F or below; unsheltered residents at highest risk.",
        "levels": {k: _level("cold", k) for k in LEVEL_WORDS},
        "interventions": {
            "none": {"label": "Do nothing"},
            "refuge": {"label": "Open warming sites",
                       "desc": f"The city's {N_WARM} Code Blue warming sites open at their posted hours."},
            "outreach": {"label": "Outreach to 24-hour sites",
                         "desc": "Homeless outreach vans bring unsheltered residents to the nearest 24-hour warming site."},
            "alert": {"label": "Early Code Blue",
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
FLOOD_DEPTH_BANDS = [(0.5, 1), (1.0, 2), (2.0, 3)]  # inches of rain in 3 h, scaled by FEMA zone (assumed bands)


def scenario_ids():
    """Every precomputed run id: hazard_level_intervention."""
    return [f"{hz}_{lvl}_{iv}" for hz, h in HAZARDS.items() for lvl in h["levels"] for iv in h["interventions"]]


def parse_scenario(sid):
    hz, lvl, iv = sid.split("_")
    return {"hazard": hz, "level": lvl, "intervention": iv}


def intensity(hazard, level):
    return list(HAZARDS[hazard]["levels"][level]["values"])


def meta():
    """JSON-safe view of the config for the frontend."""
    return {
        "hours": HOURS,
        "refuges": REFUGES,
        "groups": GROUP_LABELS,
        "typical_summer": DAYS["typical_summer"],
        "hazards": {
            hz: {
                "label": h["label"], "unit": h["unit"], "history": h["history"], "groups": h["groups"],
                "levels": {k: {"label": v["label"], "date": v["date"], "note": v["note"], "intensity": v["values"]}
                           for k, v in h["levels"].items()},
                "interventions": {k: dict(v) for k, v in h["interventions"].items()},
            }
            for hz, h in HAZARDS.items()
        },
    }
