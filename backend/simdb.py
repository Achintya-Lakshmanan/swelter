"""The simulation as SQL tables, for the dashboard's "Ask" chat (backend/ask.py).

Loads what the dashboard shows (heat and cold, three real days each: synthetic residents, their hour-by-hour
baseline day, the trained models' danger probability per resident-hour, the city's real sites and the model's site
rankings) into Tiger Data when DATABASE_URL is a Postgres URL, else into a local SQLite file (data/simulation.db).
On Tiger Data the tables live in schema `sim` and resident_hours is a TimescaleDB hypertable on ts.

    uv run --env-file .env --extra tiger scripts/load_sql.py     # (re)load; the server also loads on first ask

Questions run read-only: one SELECT, a row cap and a time limit (query()).
"""
import json
import os
import pathlib
import re
import sqlite3
import threading
import time
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "app" / "data"
SQLITE = ROOT / "data" / "simulation.db"
URL = os.environ.get("DATABASE_URL", "")
PG = URL.startswith("postgres")
HAZARDS = ("heat", "cold")
LEVELS = ("moderate", "severe", "extreme")
OUTDOOR = {"work_outdoor", "leisure_outdoor", "exercise_outdoor", "outdoors_unsheltered"}
MAX_ROWS = 500
TIMEOUT_S = 8
_lock = threading.Lock()

TABLES = {
    "scenarios": """scenario_id TEXT PRIMARY KEY, hazard TEXT NOT NULL, level TEXT NOT NULL, day DATE NOT NULL,
        label TEXT NOT NULL, note TEXT, unit TEXT NOT NULL, total_risk_hours DOUBLE PRECISION""",
    "weather": """scenario_id TEXT NOT NULL, hour INTEGER NOT NULL, ts TIMESTAMP NOT NULL, value DOUBLE PRECISION NOT NULL""",
    "residents": """resident_id INTEGER PRIMARY KEY, name TEXT, age_group TEXT, role TEXT, lives_alone BOOLEAN,
        has_car BOOLEAN, has_ac BOOLEAN, has_heat BOOLEAN, respiratory BOOLEAN, poverty BOOLEAN, flood_zone BOOLEAN,
        vulnerable BOOLEAN, tract TEXT, tract_name TEXT, home_lat DOUBLE PRECISION, home_lon DOUBLE PRECISION,
        commute_km DOUBLE PRECISION""",
    "groups": "group_id TEXT PRIMARY KEY, label TEXT NOT NULL",
    "resident_groups": "resident_id INTEGER NOT NULL, group_id TEXT NOT NULL",
    "places": "place_id INTEGER PRIMARY KEY, kind TEXT, name TEXT, lat DOUBLE PRECISION, lon DOUBLE PRECISION",
    "resident_hours": """ts TIMESTAMP NOT NULL, scenario_id TEXT NOT NULL, resident_id INTEGER NOT NULL,
        hour INTEGER NOT NULL, activity TEXT NOT NULL, setting TEXT NOT NULL, place_id INTEGER NOT NULL,
        reason TEXT NOT NULL, risk DOUBLE PRECISION NOT NULL, sim_level INTEGER NOT NULL""",
    "sites": """site_id TEXT PRIMARY KEY, name TEXT, address TEXT, kind TEXT, cooling BOOLEAN, warming BOOLEAN,
        open_hour INTEGER, close_hour INTEGER, hours_text TEXT, lat DOUBLE PRECISION, lon DOUBLE PRECISION""",
    "site_rankings": """scenario_id TEXT NOT NULL, rank INTEGER NOT NULL, site_id TEXT NOT NULL,
        priority_score DOUBLE PRECISION, additional_risk_hours DOUBLE PRECISION, at_risk_residents INTEGER,
        no_car INTEGER, unhoused INTEGER, no_ac_or_heat INTEGER, mean_distance_m INTEGER""",
    "coverage": """scenario_id TEXT NOT NULL, sites_opened INTEGER NOT NULL, risk_hours_reachable DOUBLE PRECISION,
        share_reachable DOUBLE PRECISION, risk_hours_outside DOUBLE PRECISION""",
}
INDEXES = ["CREATE INDEX IF NOT EXISTS rh_scenario ON resident_hours (scenario_id, resident_id, hour)",
           "CREATE INDEX IF NOT EXISTS rg_group ON resident_groups (group_id, resident_id)"]


def engine():
    return "Tiger Data (TimescaleDB)" if PG else "SQLite (local)"


def dialect():
    return "PostgreSQL 16 (TimescaleDB)" if PG else "SQLite 3"


# ---------- building the tables from app/data ----------

def rows_from_app_data():
    """→ {table: [tuple, ...]} in TABLES column order."""
    meta = json.loads((APP / "meta.json").read_text())
    models = json.loads((APP / "shelter_models.json").read_text())["models"]
    hours, acts, reason_ids, places = meta["hours"], meta["activities"], list(meta["reasons"]), meta["places"]
    out = {t: [] for t in TABLES}
    out["groups"] = [(g, label) for g, label in meta["groups"].items()]
    out["places"] = [(i, p[1], p[2], p[3], p[4]) for i, p in enumerate(places)]
    for r in meta["residents"]:
        home = places[r["home"]]
        out["residents"].append((r["id"], r["name"], r["age"], r["role"], r["alone"], r["car"], r["ac"], r["heat"],
                                 r["respiratory"], r["poverty"], r["flood_zone"], r["vulnerable"], r["tract"],
                                 r["tract_name"], home[3], home[4], r.get("commute_km")))
        out["resident_groups"] += [(r["id"], g) for g in r["groups"]]
    out["sites"] = [(s["id"], s["name"], s.get("address"), s.get("type"), s.get("cooling", False),
                     s.get("warming", False), s["hours"][0], s["hours"][1], s.get("hours_text"), s["lat"], s["lon"])
                    for s in meta["refuges"]]
    for hz in HAZARDS:
        H = meta["hazards"][hz]
        for lv in LEVELS:
            sid, L = f"{hz}_{lv}", H["levels"][lv]
            day = date.fromisoformat(L["date"])
            rk = models[hz]["rankings"][lv]
            run = json.loads((APP / "runs" / f"{sid}_none.json").read_text())
            out["scenarios"].append((sid, hz, lv, day, L["label"], L.get("note"), H["unit"], rk["total_expected_risk_hours"]))
            ts = [f"{day} {h:02d}:00:00" for h in hours]
            out["weather"] += [(sid, h, ts[k], run["intensity"][k]) for k, h in enumerate(hours)]
            for i, (steps, levels) in enumerate(zip(run["steps"], run["levels"])):
                risk = rk["risk_milli"][i]
                for k, s in enumerate(steps):
                    act = acts[(s % 1000) // 40]
                    out["resident_hours"].append((
                        ts[k], sid, i, hours[k], act,
                        "outdoors" if act in OUTDOOR else "travelling" if act == "commute" else "indoors",
                        s // 1000, reason_ids[s % 40], risk[k] / 1000, int(levels[k])))
            out["site_rankings"] += [(sid, s["rank"], s["id"], s["priority_score"], s["additional_expected_risk_hours"],
                                      s["at_risk_residents"], s["no_car"], s["unhoused"], s["no_ac_or_heat"],
                                      s["mean_straight_line_m"]) for s in rk["sites"]]
            out["coverage"] += [(sid, int(b), c["expected_risk_hours_reachable"], c["share_reachable"],
                                 c["expected_risk_hours_outside_coverage"]) for b, c in rk["coverage"].items()]
    return out


def _columns(table):
    return [c.split()[0] for c in re.split(r",\s*", " ".join(TABLES[table].split()))]


def build():
    """(Re)create every table and load it. Returns {table: row count}."""
    data, t0 = rows_from_app_data(), time.time()
    if PG:
        import psycopg

        with psycopg.connect(URL, autocommit=True) as c:
            c.execute("CREATE SCHEMA IF NOT EXISTS sim")
            for t, cols in TABLES.items():
                c.execute(f"DROP TABLE IF EXISTS sim.{t}")
                c.execute(f"CREATE TABLE sim.{t} ({cols})")
            try:
                c.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
                c.execute("SELECT create_hypertable('sim.resident_hours', by_range('ts', INTERVAL '1 day'))")
            except Exception as e:
                print("resident_hours stays a plain table (no TimescaleDB):", e)
            for t, rows in data.items():
                with c.cursor().copy(f"COPY sim.{t} ({', '.join(_columns(t))}) FROM STDIN") as cp:
                    for r in rows:
                        cp.write_row(r)
            for s in INDEXES:
                c.execute(s.replace(" ON ", " ON sim."))
            c.execute("ANALYZE")
    else:
        SQLITE.parent.mkdir(exist_ok=True)
        tmp = SQLITE.with_suffix(".tmp")
        tmp.unlink(missing_ok=True)
        c = sqlite3.connect(tmp)
        for t, cols in TABLES.items():
            c.execute(f"CREATE TABLE {t} ({cols})")
            c.executemany(f"INSERT INTO {t} VALUES ({', '.join('?' * len(_columns(t)))})",
                          [tuple(str(v) if isinstance(v, date) else v for v in r) for r in data[t]])
        for s in INDEXES:
            c.execute(s)
        c.commit()
        c.close()
        tmp.replace(SQLITE)
    _conn.cache = None
    print(f"loaded {sum(map(len, data.values())):,} rows into {engine()} in {time.time() - t0:.1f}s")
    return {t: len(r) for t, r in data.items()}


def loaded():
    if PG:
        try:
            return _conn().execute("SELECT to_regclass('sim.resident_hours') IS NOT NULL").fetchone()[0]
        except Exception:
            return False
    return SQLITE.exists() and SQLITE.stat().st_mtime >= (APP / "shelter_models.json").stat().st_mtime


def ensure():
    with _lock:
        if not loaded():
            build()


# ---------- read-only questions ----------

def _conn():
    if getattr(_conn, "cache", None) is None:
        if PG:
            import psycopg

            _conn.cache = psycopg.connect(URL, autocommit=True)
        else:
            c = sqlite3.connect(f"file:{SQLITE}?mode=ro", uri=True, check_same_thread=False)
            c.execute("PRAGMA query_only = ON")
            _conn.cache = c
    return _conn.cache


_conn.cache = None
FORBIDDEN = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|grant|revoke|truncate|copy|attach|detach|pragma|vacuum|"
    r"analyze|reindex|call|do|execute|prepare|listen|notify|set|reset|lock|refresh|into|load|"
    r"pg_\w+|information_schema|sqlite_\w+|dblink\w*|lo_\w+|public|users|requests|presence|site_reports)\b", re.I)


def check(sql):
    """One SELECT (or WITH … SELECT) over the simulation tables, or ValueError saying why not."""
    s = sql.strip().rstrip(";").strip()
    if not re.match(r"(?is)^(select|with)\b", s):
        raise ValueError("only SELECT queries can run")
    if ";" in s or "--" in s or "/*" in s:
        raise ValueError("one statement, no comments")
    bad = FORBIDDEN.search(re.sub(r"'(?:[^']|'')*'", "''", s))  # string literals can say anything
    if bad:
        raise ValueError(f"'{bad[0]}' isn't allowed in a question query")
    return s


def query(sql):
    """→ (columns, rows) for a checked SELECT, at most MAX_ROWS rows, within TIMEOUT_S seconds."""
    s = check(sql)
    wrapped = f"SELECT * FROM ({s}) AS q LIMIT {MAX_ROWS + 1}"
    with _lock:
        c = _conn()
        if PG:
            with c.transaction():
                c.execute("SET TRANSACTION READ ONLY")
                c.execute(f"SET LOCAL statement_timeout = '{TIMEOUT_S}s'")
                c.execute("SET LOCAL search_path TO sim")
                cur = c.execute(wrapped)
                cols, rows = [d.name for d in cur.description], cur.fetchall()
        else:
            deadline = time.time() + TIMEOUT_S
            c.set_progress_handler(lambda: int(time.time() > deadline), 10000)
            try:
                cur = c.execute(wrapped)
                cols, rows = [d[0] for d in cur.description], cur.fetchall()
            finally:
                c.set_progress_handler(None, 0)
    return cols, [[_plain(v) for v in r] for r in rows]


def _plain(v):
    if isinstance(v, float):
        return round(v, 4)
    if hasattr(v, "isoformat"):
        return v.isoformat(sep=" ") if hasattr(v, "hour") else v.isoformat()
    if v is not None and not isinstance(v, (int, str, bool)):
        return float(v)  # Decimal from Postgres
    return v
