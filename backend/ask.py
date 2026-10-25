"""The dashboard's Ask chat: a conversation with Gemini about the simulation. Gemini answers from the conversation
when it can and calls one tool, run_sql, when it needs numbers: a read-only SELECT over the simulation tables
(backend/simdb.py). Every query it ran comes back with its rows so a judge can check the answer. Government accounts
only (backend/api.py).

Env: GEMINI_API_KEY, optional GEMINI_SQL_MODEL (default gemini-3.5-flash)."""
import json
import os
import urllib.error
import urllib.request
from functools import lru_cache

from . import simdb

KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = os.environ.get("GEMINI_SQL_MODEL", "gemini-3.5-flash")
# Flash, quick; Flash-Lite only if Flash is busy, slow or rate-limited.
MODELS = [MODEL, "gemini-3.5-flash-lite"]
ROWS_TO_MODEL = 80
MAX_QUERIES = 4  # per reply


def enabled():
    return bool(KEY)


@lru_cache(maxsize=1)
def schema_notes():
    lab = lambda sql: ", ".join(f"{r[0]} ({r[1]})" for r in simdb.query(sql)[1])
    return f"""Database: {simdb.dialect()}. Tables (Philadelphia disaster simulator, synthetic residents):

scenarios(scenario_id, hazard, level, day, label, note, unit, total_risk_hours)
  One real historical day per hazard and level: {lab("SELECT scenario_id, label || ', ' || unit FROM scenarios ORDER BY scenario_id")}.
  hazard is 'heat' or 'cold'; level is 'moderate' (typical day), 'severe', 'extreme' (worst on record).
weather(scenario_id, hour, ts, value)  Hourly NOAA reading at PHL airport for that day: heat index °F for heat,
  wind chill °F for cold (lower is worse).
residents(resident_id, name, age_group, role, lives_alone, has_car, has_ac, has_heat, respiratory, poverty,
  flood_zone, vulnerable, tract, tract_name, home_lat, home_lon, commute_km)
  Synthetic people built from Census ACS 2024 tracts, RECS 2020, CDC PLACES. age_group in '18-24','25-44','45-64',
  '65-74','75+' (older adults = '65-74' or '75+'). role in 'office','not_employed','retired','student','service',
  'healthcare','outdoor','unhoused'. Unhoused residents are oversampled (60) so their group has enough people.
groups(group_id, label) / resident_groups(resident_id, group_id)
  Groups: {lab("SELECT group_id, label FROM groups ORDER BY group_id")}.
places(place_id, kind, name, lat, lon)  Real OpenStreetMap places.
resident_hours(ts, scenario_id, resident_id, hour, activity, setting, place_id, reason, risk, sim_level)
  One row per resident per hour 6..22 (6 AM to 10 PM) of each scenario: their baseline routine from a real ATUS
  time-use diary. activity in {", ".join(r[0] for r in simdb.query("SELECT DISTINCT activity FROM resident_hours ORDER BY 1")[1])}.
  setting in 'indoors','outdoors','travelling'. risk = trained random-forest probability (0..1) that this
  resident-hour is dangerous exposure. SUM(risk) = expected dangerous hours ("risk-hours"). The map marks an hour
  dangerous when risk >= 0.5, so "dangerous hours" = COUNT of rows with risk >= 0.5. sim_level = the rule-based
  simulator's exposure level (0 safe, 1 caution, 2 danger, 3 extreme danger) that the models were trained on.
sites(site_id, name, address, kind, cooling, warming, open_hour, close_hour, hours_text, lat, lon)
  The city's real cooling/warming sites with posted hours (open_hour..close_hour, 24-hour clock).
site_rankings(scenario_id, rank, site_id, priority_score, additional_risk_hours, at_risk_residents, no_car,
  unhoused, no_ac_or_heat, mean_distance_m)  The model's greedy pick order of sites to open (rank 1 first);
  additional_risk_hours = predicted risk-hours newly within reach when that site is added.
coverage(scenario_id, sites_opened, risk_hours_reachable, share_reachable, risk_hours_outside)
  Cumulative reach if the top N ranked sites open (N = sites_opened, 1..5).

Rules: one read-only SELECT (CTEs allowed), no semicolon, no comments. Use only these tables and columns. Round
decimals to 1-2 places. Count people with COUNT(DISTINCT resident_id) and hours with COUNT(*); name columns so
the difference is clear (e.g. residents_in_danger vs dangerous_hours). When comparing groups, roles or tracts of
different sizes, include the number of residents and a per-person rate (e.g. dangerous hours per person), and order
by the rate. A resident is "in danger" in a scenario if they have at least one hour with risk >= 0.5. hour is the
24-hour clock. Prefer aggregated results under 50 rows; ORDER BY the main measure. Use readable column
aliases. Booleans are {"true/false" if simdb.PG else "stored as 1/0"}. Distances between lat/lon can use
111000 * sqrt(power(lat1 - lat2, 2) + power((lon1 - lon2) * 0.77, 2)) metres."""


def gemini(contents, system, tools=None, final=False, models=None):
    """→ (the model's content, model that answered). final=True forbids tool calls so the model has to answer."""
    cfg = {"temperature": 0.3, "thinkingConfig": {"thinkingLevel": "low"}}
    req_body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents, "generationConfig": cfg}
    if tools:
        req_body |= {"tools": tools, "toolConfig": {"functionCallingConfig": {"mode": "NONE" if final else "AUTO"}}}
    body = json.dumps(req_body).encode()
    err = None
    for model in models or MODELS:
        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            data=body, headers={"Content-Type": "application/json", "x-goog-api-key": KEY})
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                out = json.load(r)
        except urllib.error.HTTPError as e:
            err = f"Gemini {e.code} ({model}): {e.read()[:200].decode(errors='replace')}"
            if e.code in (404, 429, 500, 503):
                continue
            raise RuntimeError(err)
        except TimeoutError:
            err = f"Gemini ({model}) took over 25 s"
            continue
        cand = (out.get("candidates") or [{}])[0]
        return cand.get("content") or {"role": "model", "parts": []}, model
    raise RuntimeError(err)


TOOLS = [{"functionDeclarations": [{
    "name": "run_sql",
    "description": "Run one read-only SELECT over the simulation tables and get the rows back. Use it whenever the "
                   "answer needs numbers, names or comparisons from the data; you may call it again to refine.",
    "parameters": {"type": "OBJECT", "properties": {
        "sql": {"type": "STRING", "description": "One SELECT (CTEs allowed), no semicolon, no comments"},
        "purpose": {"type": "STRING", "description": "A few words on what this query checks"}},
        "required": ["sql"]}}]}]


def context_line(sc):
    if not sc:
        return ""
    sid = f"{sc.get('hazard')}_{sc.get('level')}"
    return (f"\n\nThe planner is looking at scenario_id '{sid}' on the dashboard"
            + (f" with the top {sc.get('budget')} sites opened" if sc.get("iv") == "refuge" else "")
            + ". 'This scenario', 'here' or 'today' means that one.")


def system_prompt(scenario):
    return f"""You are Swelter's analyst, chatting with a city emergency planner about a simulation of synthetic
Philadelphia residents living through real historical heat and winter-storm days. Hold a normal conversation: greet,
explain what the simulation and its models are, clarify, and follow up on earlier answers from what is already in the
conversation. Greetings, what-can-you-do, how the models work and the list of scenarios need no query (the notes
below already list the scenarios and groups). When the answer needs data you don't already have, call run_sql (several times if it helps: e.g. a
total, then a breakdown). Never guess or invent numbers; every figure you state must come from a query result in this
conversation. If the tables can't answer something, say what they can show instead.

Answer style: lead with the direct answer and the key numbers, then the inference a planner would act on (who is
most exposed, when, where, what an extra site buys). 2-6 sentences; short plain paragraphs, no markdown, no tables.
Name places, groups and hours concretely; write hours as clock times (hour 18 = 6 PM). Keep people and
resident-hours apart. Say "synthetic" or "simulated" where it matters: counts are not population estimates. Don't
mention SQL, tables or column names unless the planner asks how you got a number.{context_line(scenario)}

{schema_notes()}"""


def _jsonable(v):
    return json.loads(json.dumps(v, default=str))


def run_tool(args):
    """→ (what the model sees, what the page shows)."""
    sql = (args.get("sql") or "").strip()
    try:
        cols, rows = simdb.query(sql)
    except Exception as e:
        msg = str(e)[:300]
        return {"error": msg, "hint": "Fix the query and call run_sql again."}, {"sql": sql, "error": msg}
    truncated = len(rows) > simdb.MAX_ROWS
    rows = rows[:simdb.MAX_ROWS]
    shown = [dict(zip(cols, r)) for r in rows[:ROWS_TO_MODEL]]
    seen = {"row_count": len(rows), "truncated": truncated, "rows": _jsonable(shown)}
    if len(rows) > ROWS_TO_MODEL:
        seen["note"] = f"first {ROWS_TO_MODEL} of {len(rows)} rows shown; aggregate further if you need all of them"
    return seen, {"sql": sql, "purpose": args.get("purpose", ""), "columns": cols, "rows": _jsonable(rows[:100]),
                  "row_count": len(rows), "truncated": truncated}


def past_turns(history):
    """Earlier turns as plain text; each answer notes the queries behind it so follow-ups can build on them."""
    contents = []
    for h in history[-8:]:
        if not isinstance(h, dict) or not h.get("question"):
            continue
        text = str(h.get("answer") or "")[:1500]
        sqls = [q for q in (h.get("sql") or []) if isinstance(q, str) and q][:MAX_QUERIES]
        if sqls:
            text += "\n\n[Queries behind this answer:\n" + "\n".join(sqls) + "]"
        contents += [{"role": "user", "parts": [{"text": str(h["question"])[:500]}]},
                     {"role": "model", "parts": [{"text": text or "(no answer)"}]}]
    return contents


def answer(question, history=(), scenario=None):
    if not KEY:
        return {"error": "Ask is off: set GEMINI_API_KEY in .env and restart the server."}
    simdb.ensure()
    system = system_prompt(scenario)
    contents = past_turns(history) + [{"role": "user", "parts": [{"text": question}]}]
    queries, models, model = [], None, MODEL
    text = lambda c: "".join(p.get("text", "") for p in c.get("parts", []) if not p.get("thought")).strip()
    for round_ in range(MAX_QUERIES + 1):
        content, model = gemini(contents, system, TOOLS, final=round_ == MAX_QUERIES, models=models)
        # Stay on the model that started this reply: its thought signatures are in the contents from here on.
        models = MODELS[MODELS.index(model):]
        calls = [p["functionCall"] for p in content.get("parts", []) if "functionCall" in p]
        if not calls:
            reply = text(content)
            if not reply and queries:  # tools done but no words: ask once more for the answer itself
                contents.append({"role": "user", "parts": [{"text": "Answer my question now from those results."}]})
                content, model = gemini(contents, system, TOOLS, final=True, models=models)
                reply = text(content)
            return {"answer": reply or "I couldn't put an answer together for that. Try rephrasing.",
                    "queries": queries, "model": model, "engine": simdb.engine()}
        contents.append(content)  # verbatim, with Gemini's thought signatures
        replies = []
        for call in calls:
            seen, shown = run_tool(call.get("args") or {}) if call.get("name") == "run_sql" else \
                ({"error": "unknown tool"}, None)
            if shown:
                queries.append(shown)
            reply = {"name": call.get("name"), "response": seen}
            if call.get("id"):
                reply["id"] = call["id"]
            replies.append({"functionResponse": reply})
        contents.append({"role": "user", "parts": replies})
