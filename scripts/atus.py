"""Turn real American Time Use Survey diaries into hourly day plans in the simulator's schema.

    python3 scripts/atus.py          # reads data/raw/atus/*.zip  ->  data/atus_diaries.json

Inputs (BLS, https://www.bls.gov/tus/data.htm):
  atusact-0324.zip    activity episodes 2003-2024 (TRCODEP activity code, TEWHERE location, start/duration)
  atusrost-0324.zip   household roster (respondent age, sex)
  atusresp-YYYY.zip   respondent file per year 2018-2024 (labor force, occupation, school, diary date, weight)
  atuscps-YYYY.zip    CPS file per year 2018-2024 (metro area GTCBSA, region)
BLS's multi-year respondent/CPS zips are corrupt on the server (identical bad bytes on every download), and per-year
files only exist from 2018, so the pool is 2018-2024.

Every weekday, non-holiday diary of an adult becomes 17 hourly steps (6am-10pm). Each hour takes the activity/place
that filled most of its minutes. Travel episodes take the place of the episode they lead to.
"""
import csv
import io
import json
import pathlib
import sys
import zipfile
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from swelter.hazards import HOURS  # noqa: E402
from swelter.plan import ACTIVITY_LIST, SLOT_LIST  # noqa: E402
from swelter.world import DATA  # noqa: E402

RAW = DATA / "raw" / "atus"
YEARS = range(2018, 2025)
PHILLY = "37980"
# I-95 corridor metros with a long NOAA airport record: used for the hot-day behavior estimate.
METROS = {"37980": "Philadelphia", "35620": "New York", "47900": "Washington", "12580": "Baltimore", "14460": "Boston"}

# TEWHERE (from the BLS .do label file) -> place slot
WHERE_SLOT = {1: "home", 2: "work", 3: "home", 4: "food", 5: "worship", 6: "grocery", 7: "grocery", 8: "campus",
              9: "park", 10: "library", 11: "community_centre", 30: "grocery", 31: "community_centre", 32: "grocery",
              89: "home", -1: "home"}
# TRDTOCC1 detailed occupation groups -> simulator role (for employed respondents)
OCC_ROLE = {10: "healthcare", 11: "healthcare",
            14: "outdoor", 18: "outdoor", 19: "outdoor", 20: "outdoor", 22: "outdoor",  # grounds, construction, repair, transport
            12: "service", 13: "service", 15: "service", 16: "service", 21: "service"}


def classify(code, where):
    """(activity, slot) for one ATUS episode; slot None = travel, resolved to the next episode's place."""
    major, sub = code[:2], code[:4]
    slot = WHERE_SLOT.get(where, "community_centre")
    at_home = slot == "home"
    if sub == "0101":
        return "sleep", "home"
    if major == "18":
        return "commute", None
    if major == "05":
        return ("home", "home") if at_home else ("work_outdoor", "work") if where == 9 else ("work_indoor", "work")
    if major == "06":
        return ("home", "home") if at_home else ("class", "campus")
    if sub in ("0203", "0205"):  # exterior maintenance, lawn & garden: outdoors at home (yard, stoop)
        return "leisure_outdoor", "home"
    if sub == "0804":
        return "errand", "health"
    if at_home:
        return "home", "home"
    if where == 9:
        return ("exercise_outdoor" if major == "13" else "leisure_outdoor"), "park"
    if slot == "work":
        return "work_indoor", "work"
    if major in ("07", "08", "09", "10"):
        return "errand", slot if slot in ("grocery", "health", "library", "community_centre") else "grocery"
    if major == "14":
        return "leisure_indoor", "worship"
    if slot == "library":
        return "public_indoor", "library"
    if slot == "campus":
        return "class", "campus"
    return "leisure_indoor", slot if slot in ("food", "worship", "community_centre") else "community_centre"


def role_of(p):
    age, lfs = p["age"], p["TELFS"]
    if age >= 18 and age <= 29 and p["TESCHENR"] == 1 and p["TESCHLVL"] == 2:
        return "student"
    if lfs in (1, 2):
        return OCC_ROLE.get(p["TRDTOCC1"], "office")
    return "retired" if age >= 65 else "not_employed"


def age_group(a):
    return "18-24" if a < 25 else "25-44" if a < 45 else "45-64" if a < 65 else "65-74" if a < 75 else "75+"


def read_dat(zpath, prefix):
    z = zipfile.ZipFile(zpath)
    name = next(n for n in z.namelist() if n.startswith(prefix) and n.endswith(".dat"))
    with z.open(name) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, "utf-8"))


def respondents():
    people = {}
    for y in YEARS:
        geo = {}
        for row in read_dat(RAW / f"atuscps-{y}.zip", "atuscps"):
            if row["TULINENO"] == "1":
                geo[row["TUCASEID"]] = (row["GTCBSA"], row["GEREG"], row["GTMETSTA"])
        for row in read_dat(RAW / f"atusresp-{y}.zip", "atusresp"):
            day, hol = int(row["TUDIARYDAY"]), int(row["TRHOLIDAY"])
            if day in (1, 7) or hol == 1:
                continue
            cid = row["TUCASEID"]
            # final weight: TUFINLWGT before 2020, TUFNWGTP after, TU20FWGT for 2020
            wt = next((float(row[k]) for k in ("TUFNWGTP", "TUFINLWGT", "TU20FWGT") if float(row.get(k) or -1) > 0), 0.0)
            cbsa, reg, met = geo.get(cid, ("0", "0", "0"))
            people[cid] = {k: int(row.get(k) or -1) for k in ("TELFS", "TESCHENR", "TESCHLVL", "TRDTOCC1")} | {
                "date": row["TUDIARYDATE"], "dow": day, "w": wt, "cbsa": cbsa, "region": int(reg), "metro": met == "1"}
    for row in read_dat(RAW / "atusrost-0324.zip", "atusrost"):
        p = people.get(row["TUCASEID"])
        if p and row["TULINENO"] == "1":
            p["age"], p["sex"] = int(row["TEAGE"]), "F" if row["TESEX"] == "2" else "M"
    return {c: p for c, p in people.items() if p.get("age", 0) >= 18}


def episodes(people):
    eps = defaultdict(list)
    for row in read_dat(RAW / "atusact-0324.zip", "atusact"):
        cid = row["TUCASEID"]
        if cid in people:
            end = int(row["TUCUMDUR24"])
            dur = int(row["TUACTDUR24"])
            eps[cid].append((end - dur, end, row["TRCODEP"].zfill(6), int(row["TEWHERE"])))
    return eps


def hourly(ep):
    """17 (activity, slot) steps, the minute each move started, and minute totals for the hot-day analysis.

    dep[i] = minutes after 6am when the respondent set off for hour i's place (the start of the travel episode that
    led there, within an hour either side), or -1 when hour i's place is the same as hour i-1's or no trip was found."""
    ep.sort()
    cls = [classify(code, where) for _, _, code, where in ep]
    nxt = "home"
    for i in range(len(cls) - 1, -1, -1):  # travel takes the place of the episode it leads to
        if cls[i][1] is None:
            cls[i] = ("commute", nxt)
        else:
            nxt = cls[i][1]
    steps, mins = [], defaultdict(int)
    for (s, e, _, _), (a, sl) in zip(ep, cls):
        if 2 * 60 <= s < 18 * 60 or 2 * 60 < e <= 18 * 60:  # 6am-10pm window for the totals
            m = max(0, min(e, 18 * 60) - max(s, 2 * 60))
            outdoors = a in ("leisure_outdoor", "exercise_outdoor", "work_outdoor")
            mins["outdoor_leisure" if outdoors and a != "work_outdoor" else "outdoor_work" if outdoors
                 else "home" if a in ("home", "sleep") else "travel" if a == "commute" else "away"] += m
    for h in HOURS:
        lo, hi = (h - 4) * 60, (h - 3) * 60  # diary minutes start at 4am
        share = defaultdict(int)
        for (s, e, _, _), c in zip(ep, cls):
            o = min(e, hi) - max(s, lo)
            if o > 0:
                share[c] += o
        a, sl = max(share.items(), key=lambda kv: (kv[1], kv[0][1] != "home"))[0] if share else ("home", "home")
        steps.append(ACTIVITY_LIST.index(a) * 20 + SLOT_LIST.index(sl))
    moves, here = [], None  # (start minute, destination slot) for every trip or change of place
    for (s, _, _, _), (a, sl) in zip(ep, cls):
        if a == "commute" or (here is not None and sl != here):
            moves.append((s, sl))
        if a != "commute":
            here = sl
    dep = [-1]
    for i in range(1, len(HOURS)):
        sl = steps[i] % 20
        if sl == steps[i - 1] % 20:
            dep.append(-1)
            continue
        lo = (HOURS[i] - 4) * 60
        cands = [s for s, d in moves if SLOT_LIST.index(d) == sl and lo - 60 <= s < lo + 60]
        dep.append(min(cands, key=lambda s: abs(s - lo)) - 120 if cands else -1)
    return steps, dep, dict(mins)


def main():
    print("respondents 2018-2024 ...")
    people = respondents()
    print(f"  {len(people):,} weekday adult diaries; reading activity episodes ...")
    eps = episodes(people)
    out = []
    for cid, p in people.items():
        if cid not in eps:
            continue
        steps, dep, mins = hourly(eps[cid])
        out.append({
            "id": cid, "date": p["date"], "dow": p["dow"], "w": round(p["w"]), "age": p["age"], "sex": p["sex"],
            "role": role_of(p), "age_group": age_group(p["age"]), "cbsa": p["cbsa"], "region": p["region"],
            "metro": p["metro"], "steps": steps, "dep": dep, "mins": mins,
        })
    phl = [d for d in out if d["cbsa"] == PHILLY]
    by_role = defaultdict(int)
    for d in phl:
        by_role[d["role"]] += 1
    doc = {
        "source": "BLS American Time Use Survey 2018-2024 (weekday, non-holiday diaries of adults)",
        "encoding": ("steps[i] = activity_index*20 + slot_index for hours 6..22, indices into plan.ACTIVITY_LIST / SLOT_LIST; "
                     "dep[i] = minutes after 6am the move into hour i's place started, -1 if none"),
        "activities": ACTIVITY_LIST, "slots": SLOT_LIST, "metros": METROS, "diaries": out,
    }
    (DATA / "atus_diaries.json").write_text(json.dumps(doc, separators=(",", ":")))
    print(f"  wrote {len(out):,} diaries ({len(phl)} Philadelphia metro) -> data/atus_diaries.json")
    print("  Philadelphia by role:", dict(sorted(by_role.items())))


if __name__ == "__main__":
    main()
