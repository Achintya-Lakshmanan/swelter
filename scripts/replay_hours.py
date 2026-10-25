"""Full-day (midnight to 11 PM) recorded conditions for the 12 replay days, for the iPhone app.

The simulation only runs 6 AM-10 PM (data/hazard_days.json). The app replays a record day on the real clock, so at
any hour it needs that hour's real reading: heat index / wind chill / trailing 3-hour rain from NOAA ISD at PHL, and
PM2.5 NowCast AQI from EPA AQS (Philadelphia County monitors). Same sources and formulas as derive_inputs.py.

    python3 scripts/replay_hours.py   ->  app/data/replay_hours.json
"""
import json
from datetime import date, timedelta

from derive_inputs import DATA, aqs_days, isd_hours

KEY = {"heat": "hi", "cold": "wc", "smoke": "aqi"}


def fill(vals):
    """Interpolate gaps between readings; carry the nearest reading into gaps at either end. None if no data."""
    known = [i for i, v in enumerate(vals) if v is not None]
    if not known:
        return None
    out = list(vals)
    for i in range(24):
        if out[i] is None:
            lo = max((k for k in known if k < i), default=None)
            hi = min((k for k in known if k > i), default=None)
            if lo is None or hi is None:
                out[i] = vals[lo if hi is None else hi]
            else:
                out[i] = vals[lo] + (vals[hi] - vals[lo]) * (i - lo) / (hi - lo)
    return [round(v, 2) for v in out], 24 - len(known)


def main():
    picked = json.loads((DATA / "hazard_days.json").read_text())
    days, aqs = isd_hours(), aqs_days()
    out = {}
    for hz in ("heat", "smoke", "flood", "cold"):
        out[hz] = {}
        for lvl, v in picked[hz].items():
            d = date.fromisoformat(v["date"])
            if hz == "flood":  # trailing 3-hour rain, as in derive_inputs.rain_3h, for every hour
                yest = days.get(d - timedelta(days=1), {})
                rain = {h - 24: yest.get(h, {}).get("rain", 0.0) for h in range(21, 24)}
                rain.update({h: days.get(d, {}).get(h, {}).get("rain", 0.0) for h in range(24)})
                vals, gaps = [round(sum(rain.get(h - k, 0.0) for k in range(3)), 2) for h in range(24)], 0
            else:
                src = (aqs if hz == "smoke" else days).get(d, {})
                vals, gaps = fill([src.get(h, {}).get(KEY[hz]) for h in range(24)])
            check = max(abs(a - b) for a, b in zip(vals[6:23], v["values"]))
            out[hz][lvl] = {"date": v["date"], "values": vals, "interpolated_hours": gaps}
            print(f"  {hz:6s} {lvl:9s} {v['date']}  {gaps} gap hours, max diff vs sim series 6-22: {check:.2f}")
    out["source"] = ("NOAA ISD hourly at PHL (heat index, wind chill, trailing 3-h rain); EPA AQS hourly PM2.5 NowCast "
                     "AQI, Philadelphia County. Missing hours interpolated.")
    (DATA.parent / "app" / "data" / "replay_hours.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
