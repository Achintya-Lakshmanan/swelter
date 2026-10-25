"""ChillySOS server: the web demo (static app + /api/why) and the iPhone app's API (backend/api.py).

    uv run server.py            # http://localhost:8000

/api/why explains one resident's simulated day. With ANTHROPIC_API_KEY set it asks Claude, grounded only in the
stored run (persona, hourly plan with reason codes, exposure levels, baseline comparison). Without a key it
returns a deterministic explanation built from the same facts, labelled as offline.
"""
import json
import os
import pathlib
from functools import lru_cache
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

from backend import api

ROOT = pathlib.Path(__file__).resolve().parent
APP = ROOT / "app"
DATA = APP / "data"
MODEL = os.environ.get("SWELTER_MODEL", "claude-opus-5-5")
PORT = int(os.environ.get("PORT", "8000"))
HOST = os.environ.get("HOST", "127.0.0.1")  # 0.0.0.0 in Docker / on Vultr
LEVEL_NAMES = ["safe", "caution", "danger", "extreme danger"]


@lru_cache(maxsize=1)
def meta():
    return json.loads((DATA / "meta.json").read_text())


@lru_cache(maxsize=96)
def run(sid):
    if "/" in sid or ".." in sid or sid not in meta()["scenarios"]:
        raise KeyError(sid)
    return json.loads((DATA / "runs" / f"{sid}.json").read_text())


def decode_day(m, rn, i):
    acts, reasons, places = m["activities"], list(m["reasons"]), m["places"]
    rows = []
    for h, (s, lvl) in enumerate(zip(rn["steps"][i], rn["levels"][i])):
        p = places[s // 1000]
        rows.append({
            "hour": m["hours"][h], "activity": acts[(s % 1000) // 40], "why": m["reasons"][reasons[s % 40]],
            "place": p[2] or p[1], "place_kind": p[1], "level": int(lvl), "hazard": rn["intensity"][h],
        })
    return rows


def facts(sid, rid):
    m, rn = meta(), run(sid)
    r = m["residents"][rid]
    hz = m["hazards"][rn["hazard"]]
    iv = hz["interventions"][rn["intervention"]]
    day = decode_day(m, rn, rid)
    base_sid = f"{rn['hazard']}_{rn['level']}_none"
    base = decode_day(m, run(base_sid), rid) if base_sid != sid else None
    flags = rn["flags"][rid]
    return {
        "resident": {k: r[k] for k in ("name", "age", "role", "alone", "car", "ac", "heat", "respiratory",
                                        "poverty", "flood_zone", "tract_name", "source")}
        | {"trace": {k: v for k, v in r["trace"].items() if k != ("day_summer" if rn["hazard"] == "cold" else "day_winter")}}
        | {"groups": [m["groups"][g] for g in r["groups"]]},
        "scenario": {"hazard": hz["label"], "level": hz["levels"][rn["level"]]["label"], "unit": hz["unit"],
                     "real_day": hz["levels"][rn["level"]]["label"].split(" — ")[-1],
                     "intervention": iv["label"], "intervention_detail": iv.get("desc", "")},
        "heard_warning": bool(flags & 1), "used_ac": bool(flags & 2), "wore_n95": bool(flags & 4),
        "heat_on": bool(flags & 8),
        "day": day,
        "danger_hours": sum(1 for d in day if d["level"] >= 2),
        "baseline_danger_hours": sum(1 for d in base if d["level"] >= 2) if base else None,
        "baseline_day": base,
    }


def offline_explanation(f):
    r, sc, day = f["resident"], f["scenario"], f["day"]
    cold = f["scenario"]["hazard"] == "Winter storm"
    worst = max(day, key=lambda d: (d["level"], -d["hazard"] if cold else d["hazard"]))
    diary = r["trace"].get("day_winter" if cold else "day_summer")
    whys = []
    for d in day:
        if d["why"] not in whys and d["why"] not in ("normal weekday routine", "travelling"):
            whys.append(d["why"])
    parts = [f"{r['name']} ({r['age']}, {r['role'].replace('_', ' ')}, {r['tract_name']}) "
             f"{'heard' if f['heard_warning'] else 'did not hear'} the warning."]
    if diary:
        parts.append(f"Their ordinary weekday comes from a real {diary.split(':')[0]}.")
    if whys:
        parts.append("Key choices: " + "; ".join(whys[:3]) + ".")
    if worst["level"] >= 2:
        parts.append(f"Worst hour: {worst['hour']}:00, {worst['activity'].replace('_', ' ')} at {worst['place']} "
                     f"({round(worst['hazard'], 1):g} {sc['unit']}) — {LEVEL_NAMES[worst['level']]}.")
    else:
        parts.append("They never reached a dangerous exposure level.")
    if f["baseline_danger_hours"] is not None:
        diff = f["baseline_danger_hours"] - f["danger_hours"]
        parts.append(f"With '{sc['intervention']}' they had {f['danger_hours']} dangerous hours vs "
                     f"{f['baseline_danger_hours']} if the city did nothing"
                     + (f" ({diff} fewer)." if diff > 0 else "." if diff == 0 else f" ({-diff} more — the trip there was exposed)."))
    return " ".join(parts)


SYSTEM = """You explain one synthetic resident's simulated day in a city disaster sandbox, for planners and judges.
Use ONLY the facts provided (persona, hourly plan with the planner's reason codes, exposure levels, baseline).
In 3-4 plain sentences: why they did what they did, which hours were dangerous and why (place, indoors/outdoors,
AC/heat/filtration, travel), and what the intervention changed for them versus doing nothing. Mention the data
pattern they came from in a few words (their routine is a real ATUS diary; the weather is a real day). No lists, no markdown, no speculation beyond the facts."""


def llm_explanation(f):
    import anthropic

    client = anthropic.Anthropic()
    slim = {**f, "baseline_day": [{k: d[k] for k in ("hour", "activity", "place", "level")} for d in f["baseline_day"]]
            if f["baseline_day"] else None}
    resp = client.beta.messages.create(
        model=MODEL,
        max_tokens=2000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low"},
        system=SYSTEM,
        messages=[{"role": "user", "content": json.dumps(slim)}],
    )
    if resp.stop_reason == "refusal":
        return None
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def has_key():
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(APP), **kw)

    def log_message(self, fmt, *args):
        if "/api/" in str(args[0] if args else ""):  # args[0] is an HTTPStatus when logging an error
            super().log_message(fmt, *args)

    def _json(self, code, obj, ctype="application/json"):
        body = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _api(self, method):
        url = urlsplit(self.path)
        try:
            body = {}
            if method in ("POST", "PUT"):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            code, out = api.handle(method, url.path, dict(parse_qsl(url.query)), self.headers, body)
        except api.HTTPError as e:
            code, out = e.code, {"error": str(e)}
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as e:
            code, out = 400, {"error": f"bad request: {e!r}"}
        except OSError as e:  # NWS / ArcGIS / sponsor API unreachable
            code, out = 502, {"error": f"upstream unavailable: {e}"}
        except Exception as e:  # never drop the connection; the app shows this message
            print("API error:", repr(e))
            code, out = 500, {"error": f"server error: {e}"}
        if isinstance(out, tuple):
            return self._json(code, *out)
        return self._json(code, out)

    def do_GET(self):
        if self.path == "/api/status":
            return self._json(200, {"llm": has_key(), "model": MODEL if has_key() else None})
        if self.path.startswith("/api/"):
            return self._api("GET")
        return super().do_GET()

    def do_PUT(self):
        return self._api("PUT")

    def do_POST(self):
        if self.path != "/api/why":
            return self._api("POST")
        try:  # the planner page is for government accounts (backend/auth.py)
            u = api.signed_in(self.headers)
            if u["role"] != "government":
                return self._json(403, {"error": "the planner page is for government accounts"})
        except api.HTTPError as e:
            return self._json(e.code, {"error": str(e)})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            f = facts(str(body["scenario"]), int(body["resident"]))
        except (KeyError, ValueError, IndexError, json.JSONDecodeError) as e:
            return self._json(400, {"error": f"bad request: {e}"})
        text, source = None, "offline"
        if has_key():
            try:
                text, source = llm_explanation(f), MODEL
            except Exception as e:  # never break the demo on an API hiccup
                print("LLM explain failed:", repr(e))
        if not text:
            text, source = offline_explanation(f), "offline"
        return self._json(200, {"text": text, "source": source})


if __name__ == "__main__":
    print(f"ChillySOS on http://{HOST}:{PORT}  (live LLM explainer: {'on, ' + MODEL if has_key() else 'off — set ANTHROPIC_API_KEY'})")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
