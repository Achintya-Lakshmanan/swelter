"""Live public data for the iPhone app: NWS alerts and observations, modeled air quality, and the city's
cooling/warming site layer (with its open/closed status). Every call is cached briefly so the app can poll."""
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")
UA = "ChillySOS/0.1 (HackPSU 2026; achucod03@gmail.com)"
CITY_HALL = (39.9526, -75.1652)
SITES_URL = ("https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services/"
             "Warming_Cooling_Sites_PUBLICVIEW/FeatureServer/0/query")
_cache = {}


def fetch_json(url, ttl=300):
    hit = _cache.get(url)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/geo+json, application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r)
    if isinstance(data, dict) and "error" in data:  # ArcGIS reports failures inside a 200; don't cache them
        raise OSError(f"{url.split('?')[0]}: {data['error']}")
    _cache[url] = (time.time(), data)
    return data


def c_to_f(v):
    return None if v is None else round(v * 9 / 5 + 32)


# NWS event names → the simulator's four hazards
HAZARD_OF = [
    (r"heat", "heat"), (r"air quality|smoke", "smoke"), (r"flood", "flood"),
    (r"winter|wind chill|extreme cold|snow|ice storm|blizzard", "cold")  # not frost/freeze: crop alerts,
]


def hazard_of(event):
    for pat, hz in HAZARD_OF:
        if re.search(pat, event, re.I):
            return hz
    return None


def alerts(lat=CITY_HALL[0], lon=CITY_HALL[1]):
    d = fetch_json(f"https://api.weather.gov/alerts/active?point={lat},{lon}", ttl=120)
    out = []
    for f in d.get("features", []):
        p = f["properties"]
        out.append({
            "event": p["event"], "headline": p.get("headline"), "severity": p.get("severity"),
            "urgency": p.get("urgency"), "ends": p.get("ends") or p.get("expires"),
            "description": (p.get("description") or "").strip(), "instruction": (p.get("instruction") or "").strip(),
            "hazard": hazard_of(p["event"]), "source": "National Weather Service",
        })
    return out


def conditions():
    obs = fetch_json("https://api.weather.gov/stations/KPHL/observations/latest", ttl=300)["properties"]
    aq = fetch_json("https://air-quality-api.open-meteo.com/v1/air-quality?latitude=39.99&longitude=-75.14"
                    "&current=us_aqi,pm2_5&timezone=America/New_York", ttl=600)["current"]
    return {
        "observed_at": obs["timestamp"], "station": "Philadelphia International Airport (KPHL)",
        "temp_f": c_to_f(obs["temperature"]["value"]), "heat_index_f": c_to_f(obs["heatIndex"]["value"]),
        "wind_chill_f": c_to_f(obs["windChill"]["value"]),
        "humidity": None if obs["relativeHumidity"]["value"] is None else round(obs["relativeHumidity"]["value"]),
        "summary": obs.get("textDescription"),
        "aqi": aq.get("us_aqi"), "pm2_5": aq.get("pm2_5"), "aqi_time": aq.get("time"),
        "aqi_source": "Open-Meteo air-quality model (CAMS), not an EPA monitor",
    }


def hourly_forecast(lat=39.99, lon=-75.14, hours=18):
    grid = fetch_json(f"https://api.weather.gov/points/{lat},{lon}", ttl=86400)["properties"]["forecastHourly"]
    periods = fetch_json(grid, ttl=900)["properties"]["periods"][:hours]
    return [{"time": p["startTime"], "temp_f": p["temperature"], "short": p["shortForecast"],
             "precip": (p.get("probabilityOfPrecipitation") or {}).get("value"),
             "humidity": (p.get("relativeHumidity") or {}).get("value")} for p in periods]


# ---------- the city's site layer ----------

TIME = r"(\d{1,2})(?::(\d\d))?\s*([ap])\.?m?\.?"
RANGE = re.compile(TIME + r"\s*-\s*" + TIME, re.I)
DAYS = [  # (pattern, weekdays Mon=0)
    (r"m\s*-\s*sun|daily", range(7)), (r"m\s*-\s*f\b|weekdays|m-f", range(5)), (r"weekends?", (5, 6)),
    (r"m\s*-\s*thu", range(4)), (r"sunday", (6,)), (r"saturday", (5,)),
]


def _mins(h, m, ap):
    h = int(h) % 12 + (12 if ap.lower() == "p" else 0)
    return h * 60 + int(m or 0)


def _days(text):
    for pat, days in DAYS:
        if re.search(pat, text, re.I):
            return set(days)
    return None


def parse_hours(text):
    """'4P-9P (Weekdays) 12P-5P (Weekends)' → [(days, start_min, end_min), ...]; None if unparseable."""
    if not text:
        return None
    if "24/7" in text:
        return [(set(range(7)), 0, 24 * 60)]
    matches = list(RANGE.finditer(text))
    if not matches:
        return None
    rules = []
    for i, m in enumerate(matches):
        after = text[m.end(): matches[i + 1].start() if i + 1 < len(matches) else len(text)]
        before = re.sub(r"^\s*\([^)]*\)", "", text[matches[i - 1].end() if i else 0: m.start()])
        paren = re.match(r"\s*\(([^)]*)\)", after)
        days = (_days(paren.group(1)) if paren else None) or _days(before) or set(range(7))
        rules.append((days, _mins(*m.group(1, 2, 3)), _mins(*m.group(4, 5, 6))))
    return rules


def open_at(rules, dt):
    if rules is None:
        return None
    t, wd = dt.hour * 60 + dt.minute, dt.weekday()
    for days, a, b in rules:
        if b > a and wd in days and a <= t < b:
            return True
        if b <= a and ((wd in days and t >= a) or ((wd - 1) % 7 in days and t < b)):  # overnight
            return True
    return False


def closes_at(rules, dt):
    """Minutes-of-day when today's open window ends, for 'open until 7 PM'."""
    if not rules:
        return None
    t, wd = dt.hour * 60 + dt.minute, dt.weekday()
    for days, a, b in rules:
        if b - a >= 24 * 60:
            return "24h"
        if b > a and wd in days and a <= t < b:
            return b
        if b <= a and wd in days and t >= a:
            return b + 24 * 60
        if b <= a and (wd - 1) % 7 in days and t < b:
            return b
    return None


def fmt_min(m):
    if m is None or m == "24h":
        return None if m is None else "open 24 hours"
    if m >= 24 * 60:
        m -= 24 * 60
    h, mm = divmod(m, 60)
    return f"{(h + 11) % 12 + 1}{':%02d' % mm if mm else ''} {'AM' if h < 12 else 'PM'}"


def yes(v):
    return None if v is None else str(v).strip().lower() in ("yes", "y", "true")


def sites(now=None):
    now = now or datetime.now(TZ)
    q = urllib.parse.urlencode({"where": "1=1", "outFields": "*", "outSR": 4326, "f": "json"})
    feats = fetch_json(f"{SITES_URL}?{q}", ttl=600)["features"]
    out = []
    for f in feats:
        a, g = f["attributes"], f.get("geometry") or {}
        if not g.get("x"):
            continue
        rules = parse_hours(a.get("site_hours"))
        status = (a.get("site_status") or "").strip().lower() or None
        within = open_at(rules, now)
        cap = a.get("capacity")
        out.append({
            "id": f"site{a['OBJECTID']}", "name": (a.get("site_name") or "").strip(),
            "type": (a.get("site_type") or "").strip().title().replace("Ppr", "Parks & Rec").replace("Pha", "PHA"),
            "address": (a.get("site_address") or "").strip(), "lat": g["y"], "lon": g["x"],
            "hours_text": a.get("site_hours"), "hours_parsed": rules is not None,
            "status": status, "cooling": yes(a.get("cooling_site")), "warming": yes(a.get("warming_site")),
            "open_now": status == "open" and bool(within), "closes": fmt_min(closes_at(rules, now)) if within else None,
            "capacity": int(cap) if cap and str(cap).isdigit() else None,
            "accessible": yes(a.get("handicap_accessible")), "water": yes(a.get("water_station")),
            "services": (a.get("services_offered") or "").strip() or None,
            "facilities": (a.get("facilities_include") or "").strip() or None,
            "source": "City of Philadelphia, Warming & Cooling Sites (live ArcGIS layer)",
        })
    return out
