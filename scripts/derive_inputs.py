"""Derive the simulator's real-data inputs from the raw downloads (run scripts/fetch_real.py first).

    python3 scripts/derive_inputs.py

-> data/hazard_days.json   real hourly 6am-10pm series per hazard level, picked from the record (see pick_levels)
-> data/inputs.json        RECS 2020 Pennsylvania AC / heating rates, CDC PLACES tract asthma+COPD, city refuge sites,
                           hot-day behavior from ATUS diaries x NOAA daily highs (run scripts/atus.py first)
-> data/flood_zones.json   FEMA 2023 flood zones (City of Philadelphia), study area
-> data/heat_exposure.json City of Philadelphia Heat Exposure Index (2023 tracts, 2010 tracts where 2023 is blank)
"""
import csv
import io
import json
import math
import random
import re
import statistics
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fetch_osm import BBOX, DATA
from fetch_real import GHCN_STATIONS

RAW = DATA / "raw"
TZ = ZoneInfo("America/New_York")
HOURS = range(6, 23)
MID_INCOME = {1: 2500, 2: 6250, 3: 8750, 4: 11250, 5: 13750, 6: 17500, 7: 22500, 8: 27500, 9: 32500, 10: 37500,
              11: 45000, 12: 55000, 13: 67500, 14: 87500, 15: 125000, 16: 200000}  # RECS MONEYPY category midpoints


# --- weather -------------------------------------------------------------------------------------
def heat_index(t_f, rh):
    """NWS heat index (Rothfusz regression with NWS adjustments)."""
    hi = 0.5 * (t_f + 61 + (t_f - 68) * 1.2 + rh * 0.094)
    if (hi + t_f) / 2 < 80:
        return hi
    hi = (-42.379 + 2.04901523 * t_f + 10.14333127 * rh - 0.22475541 * t_f * rh - 0.00683783 * t_f ** 2
          - 0.05481717 * rh ** 2 + 0.00122874 * t_f ** 2 * rh + 0.00085282 * t_f * rh ** 2 - 0.00000199 * t_f ** 2 * rh ** 2)
    if rh < 13 and 80 <= t_f <= 112:
        hi -= (13 - rh) / 4 * math.sqrt((17 - abs(t_f - 95)) / 17)
    elif rh > 85 and 80 <= t_f <= 87:
        hi += (rh - 85) / 10 * (87 - t_f) / 5
    return hi


def wind_chill(t_f, mph):
    if t_f > 50 or mph < 3:
        return t_f
    return 35.74 + 0.6215 * t_f - 35.75 * mph ** 0.16 + 0.4275 * t_f * mph ** 0.16


def isd_hours():
    """{local date: {hour: {tmp_f, hi, wc, rain_in}}} from routine hourly METARs (FM-15) at PHL, 2010-2024."""
    days = defaultdict(dict)
    for path in sorted((RAW / "isd").glob("*.csv")):
        for row in csv.DictReader(open(path, newline="")):
            if row["REPORT_TYPE"].strip() != "FM-15":
                continue
            t, d = row["TMP"].split(","), row["DEW"].split(",")
            if t[0] in ("+9999", "") or d[0] in ("+9999", ""):
                continue
            tc, dc = int(t[0]) / 10, int(d[0]) / 10
            w = row["WND"].split(",")
            mph = int(w[3]) / 10 * 2.23694 if len(w) > 3 and w[3] != "9999" else 0
            rain = 0.0
            for k in ("AA1", "AA2"):
                a = row.get(k, "").split(",")
                if len(a) >= 2 and a[0] == "01" and a[1] != "9999":
                    rain = int(a[1]) / 10 / 25.4
            utc = datetime.fromisoformat(row["DATE"]).replace(tzinfo=timezone.utc)
            loc = (utc + timedelta(minutes=30)).astimezone(TZ)  # :54 obs -> the next top of the hour
            rh = 100 * math.exp(17.625 * dc / (243.04 + dc)) / math.exp(17.625 * tc / (243.04 + tc))
            tf = tc * 9 / 5 + 32
            days[loc.date()][loc.hour] = {"tmp": tf, "hi": heat_index(tf, rh), "wc": wind_chill(tf, mph), "rain": rain}
    return days


def series(day, key, prev=None):
    """17 hourly values 6..22, gaps of <= 2 hours interpolated; None if the day is too incomplete."""
    vals = [day.get(h, {}).get(key) for h in HOURS]
    if sum(v is None for v in vals) > 2 or vals[0] is None or vals[-1] is None:
        return None
    for i, v in enumerate(vals):
        if v is None:
            j = next(k for k in range(i + 1, len(vals)) if vals[k] is not None)
            vals[i] = vals[i - 1] + (vals[j] - vals[i - 1]) / (j - i + 1)
    return vals


def rain_3h(days, d):
    """Trailing 3-hour rainfall (in) at each hour 6..22 of day d."""
    yest = days.get(d - timedelta(days=1), {})
    hourly = {h - 24: yest.get(h, {}).get("rain", 0.0) for h in range(20, 24)}
    hourly.update({h: days[d].get(h, {}).get("rain", 0.0) for h in range(24)})
    return [sum(hourly.get(h - k, 0.0) for k in range(3)) for h in HOURS]


def pm25_aqi(c):
    bp = [(0, 9.0, 0, 50), (9.1, 35.4, 51, 100), (35.5, 55.4, 101, 150), (55.5, 125.4, 151, 200),
          (125.5, 225.4, 201, 300), (225.5, 325.4, 301, 500)]
    c = math.floor(c * 10) / 10
    for lo, hi, ilo, ihi in bp:
        if c <= hi:
            return ilo + (ihi - ilo) * (max(c, lo) - lo) / (hi - lo)
    return 500


def aqs_days():
    """{local date: [AQI x 17]} from EPA AQS hourly PM2.5 2023, mean of Philadelphia County monitors, NowCast."""
    by_hour = defaultdict(list)
    with zipfile.ZipFile(RAW / "hourly_88101_2023.zip") as z, z.open("hourly_88101_2023.csv") as f:
        for line in io.TextIOWrapper(f, "utf-8"):
            if not line.startswith('"42","101"'):
                continue
            row = next(csv.reader([line]))
            by_hour[datetime.fromisoformat(f"{row[9]}T{row[10]}")].append(float(row[13]))
    ts = sorted(by_hour)
    conc = {t: statistics.mean(by_hour[t]) for t in ts}
    out = defaultdict(dict)
    for t in ts:
        window = [conc.get(t - timedelta(hours=k)) for k in range(12)]
        recent = [c for c in window[:3] if c is not None]
        if len(recent) < 2:
            continue
        known = [(k, max(c, 0)) for k, c in enumerate(window) if c is not None]
        cs = [c for _, c in known]
        wgt = max(min(cs) / max(cs), 0.5) if max(cs) > 0 else 1
        nowcast = sum(c * wgt ** k for k, c in known) / sum(wgt ** k for k, _ in known)
        out[t.date()][t.hour] = {"aqi": pm25_aqi(nowcast)}
    return out


def pick_levels(cands, key_label):
    """cands: [(severity, date, values, extra)] for qualifying event days (higher severity = worse).
    moderate = the median event day, severe = 95th-percentile event day, extreme = worst day on record."""
    cands = sorted(cands, key=lambda c: c[0])
    n = len(cands)
    picks = {"moderate": cands[n // 2], "severe": cands[min(n - 2, int(0.95 * (n - 1)))] if n > 2 else cands[-1],
             "extreme": cands[-1]}
    return {lvl: {"date": c[1].isoformat(), "values": [round(v, 2) for v in c[2]], **c[3],
                  "rank_note": f"{['the median', 'top 5%', 'the worst'][i]} of {n} {key_label}"}
            for i, (lvl, c) in enumerate(picks.items())}


def hazard_days():
    print("NOAA ISD hourly (PHL) ...")
    days = isd_hours()
    heat, typical, cold, flood = [], [], [], []
    for d, day in days.items():
        if d.month in (6, 7, 8, 9):
            hi = series(day, "hi")
            tmax = max((v["tmp"] for v in day.values()), default=None)
            if hi and tmax is not None:
                if tmax >= 92:  # the validation's hot-day definition
                    heat.append((max(hi), d, hi, {"peak": round(max(hi)), "tmax": round(tmax)}))
                elif 78 <= tmax <= 88:
                    typical.append((max(hi), d, hi, {"peak": round(max(hi)), "tmax": round(tmax)}))
        if d.month in (12, 1, 2):
            wc = series(day, "wc")
            if wc and min(wc) <= 20:  # Philadelphia Code Blue threshold
                cold.append((-min(wc), d, wc, {"peak": round(min(wc))}))
        r3 = rain_3h(days, d)
        if max(r3) >= 1.0:
            flood.append((max(r3), d, r3, {"peak": round(max(r3), 2),
                                           "total": round(sum(v.get("rain", 0) for v in day.values()), 2)}))
    print("EPA AQS hourly PM2.5 2023 (Philadelphia County) ...")
    aqs = aqs_days()
    smoke = []
    for d, day in aqs.items():
        s = series(day, "aqi")
        if s and max(s) >= 151:  # EPA "Unhealthy" or worse
            smoke.append((max(s), d, s, {"peak": round(max(s))}))
    typ = sorted(typical, key=lambda c: c[0])[len(typical) // 2]
    out = {
        "heat": pick_levels(heat, "hot days (PHL high ≥ 92°F) since 2010"),
        "smoke": pick_levels(smoke, "smoke days in 2023 (AQI ≥ 151)"),
        "flood": pick_levels(flood, "downpours (≥ 1 in of rain in 3 h at PHL) since 2010"),
        "cold": pick_levels(cold, "Code Blue days (wind chill ≤ 20°F) since 2010"),
        "typical_summer": {"date": typ[1].isoformat(), "values": [round(v, 2) for v in typ[2]], **typ[3],
                           "rank_note": f"the median of {len(typical)} summer days with a PHL high of 78-88°F"},
    }
    for hz in ("heat", "smoke", "flood", "cold"):
        for lvl, v in out[hz].items():
            print(f"  {hz:6s} {lvl:9s} {v['date']}  peak {v['peak']}   ({v['rank_note']})")
    return out


# --- households, health, places ----------------------------------------------------------------
def recs():
    rows = [r for r in csv.DictReader(open(RAW / "recs2020_public_v7.csv", newline="")) if r["state_postal"] == "PA"]

    def below_poverty(r):  # 2020 HHS poverty guideline, 48 states
        return MID_INCOME[int(r["MONEYPY"])] < 12760 + 4480 * (int(r["NHSLDMEM"]) - 1)

    def share(sub, cond):
        w = sum(float(r["NWEIGHT"]) for r in sub)
        return round(sum(float(r["NWEIGHT"]) for r in sub if cond(r)) / w, 3)

    no_ac = lambda r: r["AIRCOND"] == "0"  # noqa: E731
    no_heat = lambda r: any(r[k] == "1" for k in ("NOHEATBROKE", "NOHEATEL", "NOHEATNG", "NOHEATBULK"))  # noqa: E731
    pov = [r for r in rows if below_poverty(r)]
    rest = [r for r in rows if not below_poverty(r)]
    return {
        "no_ac": {"poverty": share(pov, no_ac), "other": share(rest, no_ac)},
        "no_heat": {"poverty": share(pov, no_heat), "other": share(rest, no_heat)},
        "n": {"poverty": len(pov), "other": len(rest)},
        "source": ("EIA RECS 2020 microdata, Pennsylvania households (weighted). No AC = AIRCOND 0. No reliable heat = "
                   "unable to use main heating equipment at some point in the year (broken, unpaid bill, or no fuel)."),
    }


def places_resp():
    rows = json.loads((RAW / "places_cdc_philly.json").read_text())
    by = defaultdict(dict)
    for r in rows:
        by[r["locationname"]][r["measureid"]] = float(r["data_value"]) / 100
    return {g: round(1 - (1 - m.get("CASTHMA", 0)) * (1 - m.get("COPD", 0)), 3) for g, m in by.items()}


TIME = r"(\d{1,2})(?::(\d\d))?\s*([AaPp])\.?[Mm]?\.?"


def parse_hours(text):
    """Posted weekday hours -> (open, close) in whole hours; overnight sites close at midnight in this window."""
    t = (text or "").strip()
    if "24/7" in t:
        return 0, 24
    m = re.search(TIME + r"\s*-\s*" + TIME, t)
    if not m:
        return None

    def hr(h, mm, ap):
        h = int(h) % 12 + (12 if ap.lower() == "p" else 0)
        return h + (1 if mm and int(mm) >= 30 else 0)

    lo, hi = hr(*m.groups()[:3]), hr(*m.groups()[3:])
    return (lo, hi) if hi > lo else (lo, 24)


def refuges():
    s, w, n, e = map(float, BBOX.split(","))
    out = []
    feats = json.loads((RAW / "city" / "Warming_Cooling_Sites_PUBLICVIEW.geojson").read_text())["features"]
    seen = set()
    for i, f in enumerate(feats):
        p, g = f["properties"], f["geometry"]
        if not g or (p.get("site_status") or "").lower() != "open":
            continue
        lon, lat = g["coordinates"][:2]
        cooling, warming = (p.get("cooling_site") or "") == "yes", (p.get("warming_site") or "") == "yes"
        hours = parse_hours(p.get("site_hours"))
        name = (p.get("site_name") or "").strip()
        if not (cooling or warming) or not hours or not (s - 0.01 <= lat <= n + 0.01 and w - 0.01 <= lon <= e + 0.01) or name in seen:
            continue
        seen.add(name)
        out.append({"id": f"city{i}", "name": name, "type": (p.get("site_type") or "").strip().title(),
                    "lat": round(lat, 6), "lon": round(lon, 6), "hours": hours, "hours_text": p.get("site_hours"),
                    "cooling": cooling, "warming": warming, "address": p.get("site_address")})
    return out


def polygons(name, keep):
    """City GeoJSON -> [{props..., rings:[[[lon,lat],...]], bbox}] (MultiPolygons flattened)."""
    out = []
    for f in json.loads((RAW / "city" / f"{name}.geojson").read_text())["features"]:
        g, props = f["geometry"], keep(f["properties"])
        if not g or props is None:
            continue
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        for rings in polys:
            xs = [c[0] for c in rings[0]]
            ys = [c[1] for c in rings[0]]
            out.append({**props, "bbox": [min(xs), min(ys), max(xs), max(ys)],
                        "rings": [[[round(x, 5), round(y, 5)] for x, y in r] for r in rings]})
    return out


def flood_zone(p):
    if p["fld_zone"] == "AE":
        return {"zone": "floodway" if "FLOODWAY" in (p["zone_subty"] or "") else "1pct"}
    if "0.2 PCT" in (p["zone_subty"] or ""):
        return {"zone": "0.2pct"}
    return None


HOT_F, TYPICAL_F = 92, (78, 88)
AFTERNOON = range(11, 20)  # when hot-day heat index is dangerous
OUTDOOR_LEISURE = ("leisure_outdoor", "exercise_outdoor")


def behavior():
    """Hot-day change in afternoon outdoor leisure from real diaries: ATUS 2018-2024 summer weekday diaries in five I-95
    metros, each matched to that day's high at the metro's NOAA station, compared within calendar month, with a
    bootstrap 95% interval. (Evidence only: the interval is too wide to set the planner's parameters, which are fit
    to Philadelphia mobility data in scripts/validate.py.)"""
    tmax = {}
    for cbsa, st in GHCN_STATIONS.items():
        for row in csv.DictReader(open(RAW / f"{st}.csv", newline="")):
            if row.get("TMAX", "").strip() and row["DATE"] >= "2018":
                tmax[(cbsa, row["DATE"].replace("-", ""))] = float(row["TMAX"]) / 10 * 9 / 5 + 32
    doc = json.loads((DATA / "atus_diaries.json").read_text())
    acts = doc["activities"]
    rows = []
    for d in doc["diaries"]:
        month, t = int(d["date"][4:6]), tmax.get((d["cbsa"], d["date"]))
        if t is None or month not in (6, 7, 8, 9) or "20200401" <= d["date"] <= "20210630":
            continue
        bucket = "hot" if t >= HOT_F else "typ" if TYPICAL_F[0] <= t <= TYPICAL_F[1] else None
        if bucket:
            aft = sum(1 for i, c in enumerate(d["steps"]) if acts[c // 20] in OUTDOOR_LEISURE and 6 + i in AFTERNOON)
            rows.append((month, bucket, d["w"], aft))

    def rel_change(rs):
        cell = defaultdict(lambda: {"hot": [0.0, 0.0, 0], "typ": [0.0, 0.0, 0]})
        for m, b, w, a in rs:
            c = cell[m][b]
            c[0] += w; c[1] += w * a; c[2] += 1  # noqa: E702
        num = base = 0.0
        for c in cell.values():
            h, ty = c["hot"], c["typ"]
            if h[2] >= 5 and ty[2] >= 5:
                num += h[2] * (h[1] / h[0] - ty[1] / ty[0])
                base += h[2] * ty[1] / ty[0]
        return num / base

    rng = random.Random(1)
    boot = sorted(rel_change([rng.choice(rows) for _ in rows]) for _ in range(400))
    n_hot = sum(1 for r in rows if r[1] == "hot")
    return {
        "afternoon_outdoor_change": round(rel_change(rows), 3), "ci95": [round(boot[10], 3), round(boot[389], 3)],
        "n_hot": n_hot, "n_typical": len(rows) - n_hot,
        "source": (f"BLS ATUS 2018-2024 summer weekday diaries (Philadelphia, New York, Washington, Baltimore, Boston "
                   f"metros; lockdown months excluded) x NOAA GHCN-Daily highs. Hot = high >= {HOT_F}°F, typical = "
                   f"{TYPICAL_F[0]}-{TYPICAL_F[1]}°F; change in afternoon (11am-7pm) outdoor leisure, within month."),
    }


def main():
    (DATA / "hazard_days.json").write_text(json.dumps(hazard_days(), indent=1))
    ref = refuges()
    beh = behavior()
    print(f"hot-day behavior: {beh}")
    inputs = {"recs": recs(), "respiratory_by_tract": places_resp(), "refuges": ref, "behavior": beh,
              "respiratory_source": "CDC PLACES 2024 release (BRFSS 2022 model-based estimates): adult current asthma "
                                    "or COPD, combined as 1-(1-asthma)(1-COPD)"}
    (DATA / "inputs.json").write_text(json.dumps(inputs, indent=1))
    print(f"RECS PA: {inputs['recs']['no_ac']} no AC, {inputs['recs']['no_heat']} no reliable heat, n={inputs['recs']['n']}")
    print(f"PLACES: {len(inputs['respiratory_by_tract'])} tracts; refuges: {len(ref)} open sites "
          f"({sum(r['cooling'] for r in ref)} cooling, {sum(r['warming'] for r in ref)} warming)")
    fz = polygons("fema_floodplain_2023", flood_zone)
    (DATA / "flood_zones.json").write_text(json.dumps(fz, separators=(",", ":")))
    # 2023 tract scores first; tracts the 2023 layer leaves blank fall through to the same index on 2010 tracts
    hei = (polygons("HeatExposure_2023", lambda p: {"hei": round(float(p["HEI_Score"]), 3)} if p.get("HEI_Score") else None)
           + polygons("heat_vulnerability_ct", lambda p: {"hei": round(p["hei_score"], 3)} if p.get("hei_score") is not None else None))
    (DATA / "heat_exposure.json").write_text(json.dumps(hei, separators=(",", ":")))
    print(f"flood zone polygons: {len(fz)}; heat exposure polygons: {len(hei)}")


if __name__ == "__main__":
    main()
