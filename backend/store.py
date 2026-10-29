"""Storage for what phones send: site presence events, help requests, site-lead reports.

SQLite by default (data/swelter.db). Set DATABASE_URL to a Postgres URL (Tiger Data / Timescale Cloud) and the same
tables live there, with `presence` turned into a Timescale hypertable when the extension is available.
"""
import json
import os
import pathlib
import secrets
import sqlite3
import threading
import time

URL = os.environ.get("DATABASE_URL", "")
PG = URL.startswith("postgres")
DB_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "swelter.db"
_lock = threading.Lock()
# TCP keepalives so an idle connection isn't silently dropped by the network between requests.
PG_OPTS = dict(autocommit=True, keepalives=1, keepalives_idle=60, keepalives_interval=15, keepalives_count=4)

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS presence (
        ts BIGINT NOT NULL, site_id TEXT NOT NULL, event TEXT NOT NULL, token TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS requests (
        id TEXT PRIMARY KEY, created BIGINT NOT NULL, need TEXT NOT NULL, flags TEXT NOT NULL, people INTEGER,
        lat DOUBLE PRECISION NOT NULL, lon DOUBLE PRECISION NOT NULL, callback TEXT, note TEXT,
        status TEXT NOT NULL, secret TEXT NOT NULL, claimed_by TEXT, claimed_name TEXT, claimed_at BIGINT,
        closed_at BIGINT, outcome TEXT, user_sub TEXT, name TEXT)""",
    """CREATE TABLE IF NOT EXISTS site_reports (
        ts BIGINT NOT NULL, site_id TEXT NOT NULL, level TEXT NOT NULL, by_user TEXT)""",
    """CREATE TABLE IF NOT EXISTS users (
        sub TEXT PRIMARY KEY, name TEXT NOT NULL, home_name TEXT, lat DOUBLE PRECISION, lon DOUBLE PRECISION,
        flags TEXT NOT NULL, phone TEXT, updated BIGINT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS presence_site_ts ON presence (site_id, ts)",
    "CREATE INDEX IF NOT EXISTS requests_status ON requests (status, created)",
]


class DB:
    def __init__(self):
        if PG:
            import psycopg  # only needed for Tiger Data

            self.conn = psycopg.connect(URL, **PG_OPTS)
            self.kind = "timescale"
        else:
            DB_PATH.parent.mkdir(exist_ok=True)
            self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self.kind = "sqlite"
        for s in SCHEMA:
            self.run(s)
        for col in ("user_sub", "name"):  # databases created before sign-in
            try:
                self.run(f"ALTER TABLE requests ADD COLUMN {col} TEXT")
            except Exception:
                pass
        if PG:
            try:  # time-series storage for presence pings on Tiger Data
                self.run("CREATE EXTENSION IF NOT EXISTS timescaledb")
                self.run("SELECT create_hypertable('presence', by_range('ts', 86400000), if_not_exists => TRUE)")
                self.kind = "timescale (hypertable)"
            except Exception as e:
                print("Timescale hypertable not created:", e)

    def run(self, sql, args=()):
        if PG:
            sql = sql.replace("?", "%s")
        with _lock:
            if not PG:
                cur = self.conn.cursor()
                cur.execute(sql, args)
                self.conn.commit()
                return cur
            import psycopg

            for attempt in (0, 1):  # Tiger Data closes connections now and then: reconnect once and retry
                if self.conn.closed:
                    self.conn = psycopg.connect(URL, **PG_OPTS)
                try:
                    cur = self.conn.cursor()
                    cur.execute(sql, args)
                    return cur
                except psycopg.OperationalError:
                    if attempt or not self.conn.closed:
                        raise

    def rows(self, sql, args=()):
        cur = self.run(sql, args)
        if PG:
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
        return [dict(r) for r in cur.fetchall()]


_db = None


def db():
    global _db
    if _db is None:
        _db = DB()
    return _db


def now_ms():
    return int(time.time() * 1000)


# ---------- presence → crowd level ----------

BUCKET = 15 * 60 * 1000
WINDOW = 4 * 3600 * 1000
K_MIN = 5  # a site shows a phone-based level only when at least this many phones contributed


def add_presence(site_id, event, token):
    ts = now_ms() // BUCKET * BUCKET  # round to 15 minutes before storing
    db().run("INSERT INTO presence (ts, site_id, event, token) VALUES (?, ?, ?, ?)", (ts, site_id, event, token))


def presence_counts():
    """site_id → (phones inside now, distinct phones in the window)."""
    since = now_ms() - WINDOW
    rows = db().rows("SELECT site_id, token, event, ts FROM presence WHERE ts >= ? ORDER BY ts", (since,))
    last, seen = {}, {}
    for r in rows:
        last[(r["site_id"], r["token"])] = r["event"]
        seen.setdefault(r["site_id"], set()).add(r["token"])
    inside = {}
    for (site, _tok), ev in last.items():
        if ev == "enter":
            inside[site] = inside.get(site, 0) + 1
    return {s: (inside.get(s, 0), len(toks)) for s, toks in seen.items()}


def add_report(site_id, level, by_user):
    db().run("INSERT INTO site_reports (ts, site_id, level, by_user) VALUES (?, ?, ?, ?)",
             (now_ms(), site_id, level, by_user))


def latest_reports(max_age_ms=2 * 3600 * 1000):
    rows = db().rows("SELECT site_id, level, ts FROM site_reports WHERE ts >= ? ORDER BY ts", (now_ms() - max_age_ms,))
    return {r["site_id"]: r for r in rows}


# ---------- help requests ----------

NEEDS = {"ride", "water", "check", "stuck"}
FLAGS = {"older", "noac", "alone", "mobility", "medical", "pets", "noheat"}
OUTCOMES = {"moved", "water", "ok", "911", "not_found"}


def create_request(need, flags, people, lat, lon, callback=None, note=None, user_sub=None, name=None):
    """name: the signed-in resident's first name, which responders see."""
    rid, secret = secrets.token_urlsafe(8), secrets.token_urlsafe(16)
    db().run("""INSERT INTO requests (id, created, need, flags, people, lat, lon, callback, note, status, secret,
                                      user_sub, name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)""",
             (rid, now_ms(), need, json.dumps(sorted(flags)), people, lat, lon, callback, note, secret, user_sub, name))
    return rid, secret


def _decode(r):
    r["flags"] = json.loads(r["flags"])
    return r


def get_request(rid):
    r = db().rows("SELECT * FROM requests WHERE id = ?", (rid,))
    if not r:
        return None
    return _decode(r[0])


def open_requests(max_age_ms=12 * 3600 * 1000):
    rows = db().rows("SELECT * FROM requests WHERE status IN ('open', 'claimed') AND created >= ? ORDER BY created",
                     (now_ms() - max_age_ms,))
    return [_decode(r) for r in rows]


def claim(rid, user, name):
    cur = db().run("UPDATE requests SET status = 'claimed', claimed_by = ?, claimed_name = ?, claimed_at = ? "
                   "WHERE id = ? AND status = 'open'", (user, name, now_ms(), rid))
    return cur.rowcount == 1


def release(rid, user):
    cur = db().run("UPDATE requests SET status = 'open', claimed_by = NULL, claimed_name = NULL, claimed_at = NULL "
                   "WHERE id = ? AND status = 'claimed' AND claimed_by = ?", (rid, user))
    return cur.rowcount == 1


def close(rid, user, outcome):
    cur = db().run("UPDATE requests SET status = 'done', outcome = ?, closed_at = ? "
                   "WHERE id = ? AND status = 'claimed' AND claimed_by = ?", (outcome, now_ms(), rid, user))
    return cur.rowcount == 1


def cancel(rid, secret):
    cur = db().run("UPDATE requests SET status = 'cancelled', closed_at = ? WHERE id = ? AND secret = ? "
                   "AND status IN ('open', 'claimed')", (now_ms(), rid, secret))
    return cur.rowcount == 1


# ---------- signed-in people ----------

def get_user(sub):
    r = db().rows("SELECT * FROM users WHERE sub = ?", (sub,))
    if not r:
        return None
    u = r[0]
    return {"name": u["name"], "phone": u["phone"], "flags": json.loads(u["flags"]),
            "home": {"name": u["home_name"], "lat": u["lat"], "lon": u["lon"]} if u["lat"] is not None else None}


def save_user(sub, name, home=None, flags=(), phone=None):
    h = home or {}
    db().run("""INSERT INTO users (sub, name, home_name, lat, lon, flags, phone, updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (sub) DO UPDATE SET name = excluded.name, home_name = excluded.home_name,
                lat = excluded.lat, lon = excluded.lon, flags = excluded.flags, phone = excluded.phone,
                updated = excluded.updated""",
             (sub, name, h.get("name"), h.get("lat"), h.get("lon"), json.dumps(sorted(flags)), phone, now_ms()))
    return get_user(sub)
