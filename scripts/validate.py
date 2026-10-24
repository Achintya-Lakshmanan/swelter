"""Validation: does the simulation shift behavior on hot days the way Philadelphians actually do?

Real:  Google Community Mobility Reports, Philadelphia County, summer (Jun-Aug) weekdays 2020-2022, joined to
       NOAA GHCN-Daily max temperature at PHL airport. Effect = hot-day (Tmax >= 92°F) minus typical-day
       (Tmax 78-88°F) mobility, in percentage points, compared within the same month to absorb COVID-era trends.
Sim:   resident-hours in each category, moderate heatwave with no intervention vs. a normal summer day
       (same residents, same random draws), as % change.
Error: mean absolute difference (percentage points) across categories.

    python3 scripts/validate.py      # downloads ~100 MB once into data/raw/
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
# Earlier rule versions scored by this script (MAE, percentage points). v1 had every aware resident cancel optional
# outdoor plans; real Philadelphia hot-day park visits barely drop, so v2 lets most people shift or go anyway.
CALIBRATION_HISTORY = [{"version": "v1 · aware residents always cancel outdoor plans", "mae_pp": 5.6}]


def fetch(url, path):
    if not path.exists():
        print(f"downloading {url} ...")
        req = urllib.request.Request(url, headers={"User-Agent": "swelter-hackpsu/0.1"})
        with urllib.request.urlopen(req, timeout=600) as r:
            path.write_bytes(r.read())
    return path


def real_effects():
    RAW.mkdir(parents=True, exist_ok=True)
    z = zipfile.ZipFile(fetch(CMR_URL, RAW / "Region_Mobility_Report_CSVs.zip"))
    mob = {}
    for year in (2020, 2021, 2022):
        name = f"{year}_US_Region_Mobility_Report.csv"
        with z.open(name) as f:
            for row in csv.DictReader(io.TextIOWrapper(f, "utf-8")):
                if row["sub_region_1"] == "Pennsylvania" and row["sub_region_2"] == "Philadelphia County":
                    mob[row["date"]] = {k: float(row[c]) if row[c] else None for k, c in CATS.items()}
    tmax = {}
    with open(fetch(NOAA_URL, RAW / "USW00013739.csv"), newline="") as f:
        for row in csv.DictReader(f):
            if row.get("TMAX", "").strip():
                tmax[row["DATE"]] = float(row["TMAX"]) / 10 * 9 / 5 + 32  # tenths of °C -> °F

    by_month = defaultdict(lambda: {"hot": defaultdict(list), "typ": defaultdict(list), "n_hot": 0})
    n_hot = n_typ = 0
    for d, vals in mob.items():
        dt = date.fromisoformat(d)
        if dt.month not in (6, 7, 8) or dt.weekday() >= 5 or (dt.month, dt.day) in HOLIDAYS or d not in tmax:
            continue
        t = tmax[d]
        bucket = "hot" if t >= HOT_F else "typ" if TYPICAL_F[0] <= t <= TYPICAL_F[1] else None
        if not bucket:
            continue
        m = by_month[(dt.year, dt.month)]
        if bucket == "hot":
            m["n_hot"] += 1
            n_hot += 1
        else:
            n_typ += 1
        for k, v in vals.items():
            if v is not None:
                m[bucket][k].append(v)
    eff = {}
    for k in CATS:
        diffs, weights = [], []
        for m in by_month.values():
            if m["hot"][k] and m["typ"][k]:
                diffs.append(statistics.mean(m["hot"][k]) - statistics.mean(m["typ"][k]))
                weights.append(len(m["hot"][k]))
        eff[k] = sum(d * w for d, w in zip(diffs, weights)) / sum(weights) if weights else None
    return eff, n_hot, n_typ, sorted(mob)[0], sorted(mob)[-1]


def sim_hours(world, residents, intensity):
    """Resident-hours per category under a heat curve, no intervention."""
    rules = RulePlanner(world)
    sc = {"hazard": "heat", "level": "moderate", "intervention": "none", "site": None}
    tot = defaultdict(float)
    for r in residents:
        if r["role"] == "unhoused":
            continue
        slots = resolve_slots(world, r, sc)
        plan = rules.plan(r, sc, slots, intensity)
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


def main():
    real, n_hot, n_typ, d0, d1 = real_effects()
    world = World()
    residents = json.loads((DATA / "residents.json").read_text())
    normal = [round(80 + 6 * __import__("math").exp(-((h - 16) / 5) ** 2), 2) for h in H.HOURS]  # typical summer day HI
    base = sim_hours(world, residents, normal)
    hot = sim_hours(world, residents, H.intensity("heat", "moderate"))
    rows = []
    for k in CATS:
        if real[k] is None or not base[k]:
            continue
        sim = (hot[k] - base[k]) / base[k] * 100
        rows.append({"key": k, "label": LABELS[k], "real": round(real[k], 1), "sim": round(sim, 1)})
    mae = statistics.mean(abs(r["real"] - r["sim"]) for r in rows)
    out = {
        "title": "Hot-day behavior change, Philadelphia",
        "description": (f"Real: Google Community Mobility Reports for Philadelphia County, summer weekdays {d0[:4]}–{d1[:4]}, "
                        f"hot days (PHL Tmax ≥ {HOT_F}°F, n={n_hot}) vs typical days ({TYPICAL_F[0]}–{TYPICAL_F[1]}°F, n={n_typ}), "
                        "compared within the same month. Simulated: the same residents on a moderate heatwave vs a normal summer day."),
        "y_label": "Change on hot days (percentage points / %)",
        "rows": rows,
        "mae_pp": round(mae, 1),
        "error_label": f"Mean absolute error: {mae:.1f} percentage points across {len(rows)} activity categories",
        "calibration": CALIBRATION_HISTORY + [{"version": "v2 · current rules (cancel / shift / go anyway)", "mae_pp": round(mae, 1)}],
        "real_source_short": "Google mobility × NOAA",
        "notes": ("Caveats: mobility data are from the COVID era (2020–22) and measure visits relative to a Jan–Feb 2020 "
                  "baseline; the simulation measures resident-hours. The sim still over-predicts how much people avoid parks. "
                  "Next step: ATUS diaries × NOAA for time-use validation."),
    }
    (ROOT / "app" / "data" / "validation.json").write_text(json.dumps(out, indent=1))
    for r in rows:
        print(f"  {r['label']:13s} real {r['real']:+6.1f}  sim {r['sim']:+6.1f}")
    print(out["error_label"])


if __name__ == "__main__":
    main()
