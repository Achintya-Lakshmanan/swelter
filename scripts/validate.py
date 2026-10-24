"""Fit and validate hot-day behavior against how Philadelphians actually moved.

Real:  Google Community Mobility Reports, Philadelphia County, summer (Jun-Aug) weekdays, joined to NOAA GHCN-Daily
       max temperature at PHL airport. Effect = hot-day (Tmax >= 92°F) minus typical-day (Tmax 78-88°F) mobility,
       in percentage points, compared within the same month to absorb COVID-era trends.
Sim:   resident-hours in each category on the real median hot day (heat "moderate") vs the real median typical
       summer day, no intervention, same residents and random draws, as % change.
Fit:   the planner's free behavior parameters (share of warned residents who cancel / shift optional outdoor plans, and
       whether warned vulnerable residents always stay in) are grid-searched on 2020-2021 and scored on 2022, which
       the fit never sees.

    python3 scripts/validate.py      # writes data/behavior_fit.json (used by simulate.py) and app/data/validation.json
"""
import csv
import io
import json
import pathlib
import statistics
import sys
import urllib.request
import zipfile
from collections import defaultdict
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from swelter import hazards as H  # noqa: E402
from swelter.plan import resolve_slots  # noqa: E402
from swelter.rules import RulePlanner  # noqa: E402
from swelter.world import DATA, ROOT, World  # noqa: E402

RAW = DATA / "raw"
CMR_URL = "https://www.gstatic.com/covid19/mobility/Region_Mobility_Report_CSVs.zip"
NOAA_URL = "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00013739.csv"
CATS = {
    "parks": "parks_percent_change_from_baseline",
    "residential": "residential_percent_change_from_baseline",
    "retail_rec": "retail_and_recreation_percent_change_from_baseline",
    "grocery": "grocery_and_pharmacy_percent_change_from_baseline",
    "workplaces": "workplaces_percent_change_from_baseline",
    "transit": "transit_stations_percent_change_from_baseline",
}
LABELS = {"parks": "Parks", "residential": "Home", "retail_rec": "Retail & rec", "grocery": "Grocery",
          "workplaces": "Work", "transit": "Transit"}
HOT_F, TYPICAL_F = 92, (78, 88)
HOLIDAYS = {(7, 4), (7, 5), (7, 3)}
TRAIN, TEST = (2020, 2021), (2022,)
GRID = [(c, s, v) for c in (0.0, 0.05, 0.1, 0.2, 0.3, 0.4) for s in (0.0, 0.1, 0.2, 0.3, 0.45, 0.6) for v in (True, False)
        if c + s <= 1]
# Scores of the earlier prototype (synthetic hazard curves, hand-written routines), kept for the record.
PROTOTYPE_HISTORY = [
    {"version": "prototype v1 · synthetic day, everyone warned cancels outdoor plans", "mae_pp": 5.6},
    {"version": "prototype v2 · synthetic day, hand-tuned cancel / shift / go", "mae_pp": 2.0},
]


def fetch(url, path):
    if not path.exists():
        print(f"downloading {url} ...")
        req = urllib.request.Request(url, headers={"User-Agent": "swelter-hackpsu/0.1"})
        with urllib.request.urlopen(req, timeout=600) as r:
            path.write_bytes(r.read())
    return path


def load_real():
    RAW.mkdir(parents=True, exist_ok=True)
    z = zipfile.ZipFile(fetch(CMR_URL, RAW / "Region_Mobility_Report_CSVs.zip"))
    mob = {}
    for year in (2020, 2021, 2022):
        with z.open(f"{year}_US_Region_Mobility_Report.csv") as f:
            for row in csv.DictReader(io.TextIOWrapper(f, "utf-8")):
                if row["sub_region_1"] == "Pennsylvania" and row["sub_region_2"] == "Philadelphia County":
                    mob[row["date"]] = {k: float(row[c]) if row[c] else None for k, c in CATS.items()}
    tmax = {}
    with open(fetch(NOAA_URL, RAW / "USW00013739.csv"), newline="") as f:
        for row in csv.DictReader(f):
            if row.get("TMAX", "").strip():
                tmax[row["DATE"]] = float(row["TMAX"]) / 10 * 9 / 5 + 32  # tenths of °C -> °F
    return mob, tmax


def real_effects(mob, tmax, years):
    by_month = defaultdict(lambda: {"hot": defaultdict(list), "typ": defaultdict(list)})
    n_hot = n_typ = 0
    for d, vals in mob.items():
        dt = date.fromisoformat(d)
        if dt.year not in years or dt.month not in (6, 7, 8) or dt.weekday() >= 5 or (dt.month, dt.day) in HOLIDAYS:
            continue
        t = tmax.get(d)
        bucket = None if t is None else "hot" if t >= HOT_F else "typ" if TYPICAL_F[0] <= t <= TYPICAL_F[1] else None
        if not bucket:
            continue
        n_hot += bucket == "hot"
        n_typ += bucket == "typ"
        for k, v in vals.items():
            if v is not None:
                by_month[(dt.year, dt.month)][bucket][k].append(v)
    eff = {}
    for k in CATS:
        diffs, weights = [], []
        for m in by_month.values():
            if m["hot"][k] and m["typ"][k]:
                diffs.append(statistics.mean(m["hot"][k]) - statistics.mean(m["typ"][k]))
                weights.append(len(m["hot"][k]))
        eff[k] = sum(d * w for d, w in zip(diffs, weights)) / sum(weights) if weights else None
    return eff, n_hot, n_typ


def sim_hours(world, residents, intensity, avoid=None):
    """Resident-hours per category on one day, no intervention."""
    rules = RulePlanner(world, avoid)
    sc = {"hazard": "heat", "level": "moderate", "intervention": "none"}
    tot = defaultdict(float)
    for r in residents:
        if r["role"] == "unhoused":
            continue
        plan = rules.plan(r, sc, resolve_slots(world, r, sc), intensity)
        for s in plan["hours"]:
            a, p = s["activity"], s["place"]
            if a in ("home", "sleep"):
                tot["residential"] += 1
            elif p == "park":
                tot["parks"] += 1
            elif a in ("work_indoor", "work_outdoor"):
                tot["workplaces"] += 1
            elif a == "errand" and p == "grocery":
                tot["grocery"] += 1
            elif a in ("leisure_indoor", "errand") and p in ("food", "community_centre", "worship", "health"):
                tot["retail_rec"] += 1
            elif a == "commute" and not r["car"]:
                tot["transit"] += 1
    return tot


def compare(real, base, hot):
    rows = []
    for k in CATS:
        if real[k] is None or not base[k]:
            continue
        rows.append({"key": k, "label": LABELS[k], "real": round(real[k], 1),
                     "sim": round((hot[k] - base[k]) / base[k] * 100, 1)})
    return rows, statistics.mean(abs(r["real"] - r["sim"]) for r in rows)


def main():
    mob, tmax = load_real()
    train, n_hot_tr, n_typ_tr = real_effects(mob, tmax, TRAIN)
    test, n_hot_te, n_typ_te = real_effects(mob, tmax, TEST)
    world = World()
    residents = json.loads((DATA / "residents.json").read_text())
    typical = H.DAYS["typical_summer"]
    hot_day = H.HAZARDS["heat"]["levels"]["moderate"]
    base = sim_hours(world, residents, typical["values"])  # no dangerous hours on a typical day: avoid params unused

    print(f"fitting behavior on {TRAIN} ({n_hot_tr} hot days) ...")
    fits = []
    for c, s, v in GRID:
        _, mae = compare(train, base, sim_hours(world, residents, hot_day["values"], (c, s, v)))
        fits.append((round(mae, 3), c, s, v))
    train_mae, c, s, v = min(fits, key=lambda f: (f[0], f[1] + f[2]))  # ties: the smaller behavior change
    print(f"  best cancel={c} shift={s} vuln_stay={v} (train MAE {train_mae:.2f} pp)")
    (DATA / "behavior_fit.json").write_text(json.dumps({
        "cancel": c, "shift": s, "vuln_stay": v, "train_years": list(TRAIN), "train_mae_pp": round(train_mae, 2),
        "grid": [{"cancel": cc, "shift": ss, "vuln_stay": vv, "mae_pp": m} for m, cc, ss, vv in fits]}, indent=1))

    rows, mae = compare(test, base, sim_hours(world, residents, hot_day["values"], (c, s, v)))
    out = {
        "title": "Hot-day behavior change, Philadelphia (held-out 2022)",
        "description": (f"Real: Google Community Mobility Reports, Philadelphia County, summer weekdays of 2022, hot days "
                        f"(PHL high ≥ {HOT_F}°F, n={n_hot_te}) vs typical days ({TYPICAL_F[0]}–{TYPICAL_F[1]}°F, "
                        f"n={n_typ_te}), compared within month. Simulated: the same residents on the real median hot day "
                        f"({hot_day['date']}) vs the real median typical summer day ({typical['date']}). The three behavior "
                        f"parameters were fit on 2020–21 only."),
        "y_label": "Change on hot days (percentage points / %)",
        "rows": rows,
        "mae_pp": round(mae, 1),
        "error_label": f"Held-out (2022) mean absolute error: {mae:.1f} percentage points across {len(rows)} categories",
        "fit": {"cancel": c, "shift": s, "vuln_stay": v, "train_years": "2020–21", "train_mae_pp": round(train_mae, 1),
                "n_hot_train": n_hot_tr},
        "calibration": PROTOTYPE_HISTORY + [
            {"version": f"real data · fit on 2020–21 (cancel {c:.0%}, shift {s:.0%}, vulnerable "
                        f"{'always stay in' if v else 'decide like others'}), train", "mae_pp": round(train_mae, 1)},
            {"version": "real data · same fit, held-out 2022", "mae_pp": round(mae, 1)}],
        "real_source_short": "Google mobility × NOAA",
        "notes": ("Caveats: mobility data are from the COVID era (2020–22) and measure visits relative to a Jan–Feb 2020 "
                  "baseline; the simulation measures resident-hours. ATUS diaries from five I-95 metros could not pin down "
                  "the hot-day change on their own (95% interval spans a 55% drop to a 160% rise in afternoon outdoor "
                  "leisure), so they set the routines but not the hot-day parameters."),
    }
    (ROOT / "app" / "data" / "validation.json").write_text(json.dumps(out, indent=1))
    for r in rows:
        print(f"  {r['label']:13s} real {r['real']:+6.1f}  sim {r['sim']:+6.1f}")
    print(out["error_label"])


if __name__ == "__main__":
    main()
