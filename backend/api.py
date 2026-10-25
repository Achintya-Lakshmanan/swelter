"""JSON API for the Swelter iPhone app. Live city/NWS data, what phones report, and the simulator's forecast.

Public:
  GET  /api/config                      Auth0 settings, demo accounts, which sponsor features are switched on
  GET  /api/live[?lang=es][&replay=heat_extreme&hour=15]
  GET  /api/sites[?replay=…&hour=…]     city sites + crowd level (site lead > phones, k≥5 > Swelter forecast)
  POST /api/presence                    {site_id, event: enter|exit, token}
  POST /api/requests                    {need, flags[], people, lat, lon, callback?, note?} → {id, secret}
                                        (signed in: responders see the resident's first name)
  GET  /api/requests/<id>?secret=…
  POST /api/requests/<id>/cancel        {secret}
  POST /api/speak                       {text} → audio/mpeg (ElevenLabs)
Signed in (Auth0 bearer token, or X-Demo-Account with SWELTER_DEV_LOGIN=1):
  GET  /api/me                          {sub, role: resident|responder, demo, profile|null}
  PUT  /api/me                          {name, home?: {name, lat, lon}, flags[], phone?}
Responders (role responder):
  GET  /api/responder/requests
  POST /api/responder/requests/<id>/claim | release | done {outcome}
  POST /api/responder/sites/<id>/report {level: quiet|busy|full}
  GET  /api/responder/risk[?hour=…&replay=…]
"""
import hmac
import re
from datetime import date, datetime

from . import auth, forecast, live, store, translate, voice

PHILLY = (39.86, 40.14, -75.29, -74.95)  # lat min, lat max, lon min, lon max — requests outside are refused
SNAP = 0.002  # ~200 m: what an unclaimed request shows of its location
LEVELS = ("quiet", "busy", "full")


class HTTPError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


def need(cond, msg, code=400):
    if not cond:
        raise HTTPError(code, msg)


def now():
    return datetime.now(live.TZ)


# ---------- today's situation ----------

def situation(q):
    """Which hazard applies right now, which stored run best matches it, and whether this is a replay."""
    rep = q.get("replay")
    if rep:
        hz, _, lvl = rep.partition("_")
        need(hz in forecast.meta()["hazards"] and lvl in forecast.meta()["hazards"][hz]["levels"], "unknown replay day")
        hour = min(max(int(q.get("hour") or now().hour), 0), 23)
        # The replay is presented as this year's date of the record day (e.g. Jul 22, 2011 → Wed, Jul 22 this
        # year), so site hours follow that weekday; the weather stays the recorded day's.
        rec = date.fromisoformat(forecast.meta()["hazards"][hz]["levels"][lvl]["date"])
        sim = date(now().year, rec.month, rec.day)
        return {"replay": True, "hazard": hz, "scenario": rep, "hour": hour, "sim_date": sim,
                "sim_now": datetime(sim.year, sim.month, sim.day, hour, now().minute, tzinfo=live.TZ),
                "mode": "warming" if hz == "cold" else "cooling"}
    cond, al = live.conditions(), live.alerts()
    hz = next((a["hazard"] for a in al if a["hazard"]), None)
    if not hz:  # no NWS alert: fall back to what the thermometer and air model say
        hi, wc, aqi = cond["heat_index_f"] or cond["temp_f"], cond["wind_chill_f"] or cond["temp_f"], cond["aqi"]
        hz = ("heat" if hi and hi >= 90 else "smoke" if aqi and aqi >= 101 else
              "cold" if wc is not None and wc <= 32 else None)
    peak = None
    if hz in ("heat", "cold"):
        fc = live.hourly_forecast(hours=24)
        vals = [forecast.heat_index_f(p["temp_f"], p["humidity"]) if hz == "heat" else p["temp_f"] for p in fc]
        vals = [v for v in vals if v is not None]
        peak = (max if hz == "heat" else min)(vals) if vals else None
    elif hz == "smoke":
        peak = cond["aqi"]
    month = now().month
    mode = ("warming" if hz == "cold" else "cooling" if hz else "cooling" if 5 <= month <= 9 else "warming")
    return {"replay": False, "hazard": hz, "scenario": forecast.pick_scenario(hz, peak) if hz else None,
            "peak": peak, "hour": now().hour, "mode": mode, "conditions": cond, "alerts": al}


def get_live(q):
    s = situation(q)
    out = {"mode": s["mode"], "hazard": s["hazard"], "replay": s["replay"], "matched_day": None}
    if s["scenario"]:
        r = forecast.replay_conditions(s["scenario"], s["hour"])
        out["matched_day"] = {"scenario": s["scenario"], "day": r["day"], "date": r["date"], "peak": r["peak"],
                              "unit": r["unit"], "source": r["source"]}
    if s["replay"]:
        d = s["sim_date"]
        out |= {"conditions": forecast.replay_conditions(s["scenario"], s["hour"]), "alerts": [], "forecast": [],
                "simulated": {"date": d.isoformat(), "label": f"{d:%a, %b} {d.day}, {d.year}"},
                "note": "Replaying a real recorded day. Not today's weather."}
        return out
    out |= {"conditions": s["conditions"], "alerts": s["alerts"], "forecast": live.hourly_forecast()}
    if q.get("lang") == "es" and translate.enabled():
        for a in out["alerts"]:
            try:
                a["headline_es"] = translate.to_spanish(a["headline"])
                a["instruction_es"] = translate.to_spanish(a["instruction"])
                a["translated_by"] = f"Gemini ({translate.MODEL}), machine translation"
            except Exception as e:
                print("translate failed:", repr(e))
    return out


# ---------- sites and crowd levels ----------

def crowd(site, reports, presence, sc, hour):
    r = reports.get(site["id"])
    if r:
        return {"level": r["level"], "source": "site lead", "minutes_ago": (store.now_ms() - r["ts"]) // 60000}
    inside, phones = presence.get(site["id"], (0, 0))
    if phones >= store.K_MIN:
        lvl = None
        if site["capacity"]:
            ratio = inside / site["capacity"]
            lvl = "quiet" if ratio < .5 else "busy" if ratio < .85 else "full"
        return {"level": lvl, "source": "phones", "phones_inside": inside, "phones_4h": phones}
    f = forecast.site_forecast(sc, site["name"]) if sc else None
    if f:
        lvl = None  # the simulation has no one at sites outside 6 AM-10 PM, so no level then
        if hour in f["hours"]:
            rel = f["people"][f["hours"].index(hour)] / max(max(f["people"]), 1)
            lvl = "quiet" if rel < .4 else "busy" if rel < .75 else "full"
        return {"level": lvl, "source": "swelter forecast",
                "busiest_hour": f["hours"][f["people"].index(max(f["people"]))], "by_hour": f["people"],
                "hours": f["hours"], "real_day": f["real_day"],
                "note": "Simulated from a real day on record, relative to this site's own busiest hour."}
    return {"level": None, "source": "no data"}


def get_sites(q):
    s = situation(q)
    sites = live.sites(s["sim_now"] if s["replay"] else None)
    reports, presence = store.latest_reports(), store.presence_counts()
    for x in sites:
        x["crowd"] = crowd(x, reports, presence, s["scenario"], s["hour"])
    return {"mode": s["mode"], "scenario": s["scenario"], "replay": s["replay"], "k_min": store.K_MIN,
            "sites": sites, "counts": {"total": len(sites), "open_now": sum(x["open_now"] for x in sites)}}


# ---------- help requests ----------

def public_request(r):
    return {k: r[k] for k in ("id", "created", "need", "flags", "people", "status", "claimed_name", "claimed_at",
                              "closed_at", "outcome")}


def responder_view(r, user):
    mine = r["claimed_by"] == user
    out = public_request(r) | {"mine": mine, "minutes_waiting": (store.now_ms() - r["created"]) // 60000,
                               "name": r.get("name")}
    if mine:
        out |= {"lat": r["lat"], "lon": r["lon"], "callback": r["callback"], "note": r["note"], "exact": True}
    else:  # approximate until claimed, so the queue doesn't publish where vulnerable people are
        out |= {"lat": round(r["lat"] / SNAP) * SNAP, "lon": round(r["lon"] / SNAP) * SNAP, "exact": False}
    return out


def post_request(b, u):
    nd, flags = b.get("need"), set(b.get("flags") or [])
    need(nd in store.NEEDS, f"need must be one of {sorted(store.NEEDS)}")
    need(flags <= store.FLAGS, f"flags must be from {sorted(store.FLAGS)}")
    lat, lon = float(b["lat"]), float(b["lon"])
    need(PHILLY[0] <= lat <= PHILLY[1] and PHILLY[2] <= lon <= PHILLY[3], "Swelter only covers Philadelphia")
    people = max(1, min(20, int(b.get("people") or 1)))
    cb = (b.get("callback") or "").strip()[:32] or None
    note = (b.get("note") or "").strip()[:280] or None
    prof = u and store.get_user(u["sub"])
    first = prof["name"].split()[0] if prof else None
    rid, secret = store.create_request(nd, flags, people, lat, lon, cb, note, u and u["sub"], first)
    return {"id": rid, "secret": secret}


# ---------- routing ----------

def handle(method, path, q, headers, body):
    """→ (status, payload); payload is a dict (JSON) or (bytes, content type)."""
    p = path.rstrip("/")
    if method == "GET" and p == "/api/config":
        return 200, {"auth0": auth.config(), "voice": voice.enabled(), "translate": translate.enabled(),
                     "db": store.db().kind, "k_min": store.K_MIN,
                     "replay_days": {sid: forecast.meta()["hazards"][sid.split("_")[0]]["levels"][sid.split("_")[1]]["label"]
                                     for sid in sorted({s.rsplit("_", 1)[0] for s in forecast.meta()["scenarios"]})}}
    if method == "GET" and p == "/api/live":
        return 200, get_live(q)
    if method == "GET" and p == "/api/sites":
        return 200, get_sites(q)
    if method == "POST" and p == "/api/presence":
        sid, ev, tok = body.get("site_id", ""), body.get("event"), body.get("token", "")
        need(re.fullmatch(r"site\d+", sid) and ev in ("enter", "exit") and 8 <= len(tok) <= 64, "bad presence event")
        store.add_presence(sid, ev, tok)
        return 200, {"ok": True}
    if method == "POST" and p == "/api/requests":
        return 200, post_request(body, signed_in(headers, required=False))
    if p == "/api/me":
        u = signed_in(headers)
        if method == "PUT":
            return 200, me(u, save_profile(u, body))
        return 200, me(u, store.get_user(u["sub"]) or demo_profile(u))
    m = re.fullmatch(r"/api/requests/([\w-]+)(/cancel)?", p)
    if m:
        r = store.get_request(m[1])
        secret = body.get("secret") if m[2] else q.get("secret")
        need(r and secret and secrets_eq(r["secret"], secret), "not found", 404)
        if m[2] and method == "POST":
            store.cancel(m[1], secret)
            r = store.get_request(m[1])
        return 200, public_request(r)
    if method == "POST" and p == "/api/speak":
        need(voice.enabled(), "voice is off (set ELEVENLABS_API_KEY)", 503)
        text = (body.get("text") or "").strip()
        need(text, "no text")
        return 200, (voice.speak(text), "audio/mpeg")
    if p.startswith("/api/responder/"):
        u = signed_in(headers)
        need(u["role"] == "responder", "this account isn't a responder yet: an organiser grants the role in Auth0", 403)
        prof = store.get_user(u["sub"])
        return responder(method, p, q, body, u["sub"], prof["name"] if prof else u["name"] or "Responder")
    raise HTTPError(404, "not found")


# ---------- accounts ----------

def signed_in(headers, required=True):
    try:
        return auth.required(headers) if required else auth.user(headers)
    except auth.AuthError as e:
        raise HTTPError(401, str(e))


def me(u, profile):
    return {"sub": u["sub"], "role": u["role"], "demo": u["demo"], "profile": profile}


def demo_profile(u):
    """Demo accounts start with a profile: Kayla's is the simulator's resident #1484, Marisol's just a name."""
    if not u["demo"]:
        return None
    if u["sub"] == "demo|kayla":
        d = forecast.demo_resident()
        return store.save_user(u["sub"], d["name"], d["home"], d["flags"])
    return store.save_user(u["sub"], u["name"])


def save_profile(u, b):
    name = (b.get("name") or "").strip()[:60]
    need(name, "name is required")
    flags = set(b.get("flags") or [])
    need(flags <= store.FLAGS, f"flags must be from {sorted(store.FLAGS)}")
    home = b.get("home")
    if home:
        home = {"name": str(home.get("name") or "")[:120], "lat": float(home["lat"]), "lon": float(home["lon"])}
        need(PHILLY[0] <= home["lat"] <= PHILLY[1] and PHILLY[2] <= home["lon"] <= PHILLY[3],
             "Swelter only covers Philadelphia")
    phone = (b.get("phone") or "").strip()[:32] or None
    return store.save_user(u["sub"], name, home, flags, phone)


def secrets_eq(a, b):
    return hmac.compare_digest(str(a), str(b))


def responder(method, p, q, body, user, name):
    if method == "GET" and p == "/api/responder/requests":
        return 200, {"requests": [responder_view(r, user) for r in store.open_requests()], "you": name}
    m = re.fullmatch(r"/api/responder/requests/([\w-]+)/(claim|release|done)", p)
    if m and method == "POST":
        rid, act = m[1], m[2]
        if act == "claim":
            ok = store.claim(rid, user, name)
        elif act == "release":
            ok = store.release(rid, user)
        else:
            need(body.get("outcome") in store.OUTCOMES, f"outcome must be one of {sorted(store.OUTCOMES)}")
            ok = store.close(rid, user, body["outcome"])
        need(ok, "someone else has this request, or it is no longer open", 409)
        return 200, responder_view(store.get_request(rid), user)
    m = re.fullmatch(r"/api/responder/sites/(site\d+)/report", p)
    if m and method == "POST":
        need(body.get("level") in LEVELS, f"level must be one of {LEVELS}")
        store.add_report(m[1], body["level"], user)
        return 200, {"ok": True}
    if method == "GET" and p == "/api/responder/risk":
        s = situation(q)
        if not s["scenario"]:
            return 200, {"cells": [], "note": "No heat, smoke or cold hazard today, so there is no risk forecast."}
        hour = int(q.get("hour") or s["hour"])
        g = forecast.risk_grid(s["scenario"], hour, q.get("iv", "refuge"))
        note = ("Swelter simulation of the closest real day on record. Synthetic residents, not real people."
                if g["simulated"] else "Swelter simulates 6 AM to 10 PM, so there is no risk layer at this hour.")
        return 200, g | {"note": note, "replay": s["replay"]}
    raise HTTPError(404, "not found")

