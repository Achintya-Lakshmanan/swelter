"""The dashboard's Ask chat: a planner's question → Gemini writes one SQL query over the simulation tables
(backend/simdb.py) → the server runs it read-only → Gemini answers from the rows. The answer comes back with the SQL
and the rows so a judge can check it. Government accounts only (backend/api.py).

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


def gemini(contents, system, schema=None, temperature=0.1):
    """→ (parsed reply, model that answered)."""
    cfg = {"temperature": temperature, "thinkingConfig": {"thinkingLevel": "low"}}
    if schema:
        cfg |= {"responseMimeType": "application/json", "responseSchema": schema}
    body = json.dumps({"systemInstruction": {"parts": [{"text": system}]}, "contents": contents,
                       "generationConfig": cfg}).encode()
    err = None
    for model in MODELS:
        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            data=body, headers={"Content-Type": "application/json", "x-goog-api-key": KEY})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                out = json.load(r)
        except urllib.error.HTTPError as e:
            err = f"Gemini {e.code} ({model}): {e.read()[:200].decode(errors='replace')}"
            if e.code in (404, 429, 500, 503):
                continue
            raise RuntimeError(err)
        except TimeoutError:
            err = f"Gemini ({model}) took over 20 s"
            continue
        text = "".join(p.get("text", "") for p in out["candidates"][0]["content"].get("parts", [])).strip()
        return (json.loads(text) if schema else text), model
    raise RuntimeError(err)


SQL_SCHEMA = {"type": "OBJECT", "properties": {
    "sql": {"type": "STRING", "description": "The query, or empty if the data can't answer the question"},
    "reason": {"type": "STRING", "description": "If sql is empty: why the tables can't answer it"}},
    "required": ["sql"]}


def context_line(sc):
    if not sc:
        return ""
    sid = f"{sc.get('hazard')}_{sc.get('level')}"
    return (f"\nThe planner is looking at scenario_id '{sid}' on the dashboard"
            + (f" with the top {sc.get('budget')} sites opened" if sc.get("iv") == "refuge" else "")
            + ". 'This scenario' or 'today' means that one.")


def write_sql(question, history, scenario, error=None):
    contents = []
    for h in history[-3:]:
        contents += [{"role": "user", "parts": [{"text": h["question"]}]},
                     {"role": "model", "parts": [{"text": json.dumps({"sql": h.get("sql", "")})}]}]
    text = question + context_line(scenario)
    if error:
        text += f"\n\nYour previous query failed:\n{error['sql']}\nError: {error['message']}\nWrite a corrected query."
    contents.append({"role": "user", "parts": [{"text": text}]})
    system = ("You turn a city emergency planner's question into one SQL query over a disaster simulation "
              "database.\n\n" + schema_notes())
    return gemini(contents, system, SQL_SCHEMA)[0]


ANSWER_SYSTEM = """You answer a city emergency planner's question from the result of a SQL query over a simulation
of synthetic Philadelphia residents on real historical weather days. Use only the rows given. 2-4 plain sentences,
lead with the direct answer and the key numbers; name places, groups and hours concretely. Say "synthetic residents"
or "simulated" where it matters (counts are not population estimates). If rows are empty, say no residents matched.
Keep people and resident-hours apart as the column names say. Write hours as clock times (hour 18 = 6 PM).
No markdown, no lists, don't mention SQL or column names."""


def answer(question, history=(), scenario=None):
    if not KEY:
        return {"error": "Ask is off: set GEMINI_API_KEY in .env and restart the server."}
    simdb.ensure()
    history = [h for h in history if isinstance(h, dict) and h.get("question")]
    plan, error = write_sql(question, history, scenario), None
    sql = (plan.get("sql") or "").strip()
    if not sql:
        return {"answer": plan.get("reason") or "The simulation data can't answer that.", "sql": "", "columns": [],
                "rows": [], "model": MODEL, "engine": simdb.engine()}
    for attempt in range(2):
        try:
            cols, rows = simdb.query(sql)
            break
        except Exception as e:
            if attempt:
                return {"answer": f"I couldn't build a working query for that ({e}). Try rephrasing.", "sql": sql,
                        "columns": [], "rows": [], "model": MODEL, "engine": simdb.engine()}
            error = {"sql": sql, "message": str(e)[:300]}
            sql = (write_sql(question, history, scenario, error).get("sql") or "").strip()
    truncated = len(rows) > simdb.MAX_ROWS
    rows = rows[:simdb.MAX_ROWS]
    shown = [dict(zip(cols, r)) for r in rows[:ROWS_TO_MODEL]]
    prompt = (f"Question: {question}\nQuery result ({len(rows)} rows"
              + (f", first {ROWS_TO_MODEL} shown" if len(rows) > ROWS_TO_MODEL else "") + f"):\n{json.dumps(shown)}")
    text, model = gemini([{"role": "user", "parts": [{"text": prompt}]}], ANSWER_SYSTEM, temperature=0.2)
    return {"answer": text, "sql": sql, "columns": cols, "rows": rows[:100], "row_count": len(rows),
            "truncated": truncated, "model": model, "engine": simdb.engine()}
