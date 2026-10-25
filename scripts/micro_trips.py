"""Short trips the hourly plans drop, for the map only.

Each resident's hour is whatever filled most of it in their ATUS diary, so a 20-minute grocery run or a lunch out
never shows. This re-reads each diary to the minute, finds those out-and-back trips, and writes them per run as
app/data/micro/<run>.json. A trip is kept only in hours the run left as the diary had them (same activity and place
every hour it touches), and an outdoor trip is dropped in an hour the run marks as unsafe. Exposure, risk and the
models never see these trips; the map draws them.

    uv run scripts/micro_trips.py
"""
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from atus import classify, episodes, hourly  # noqa: E402
from swelter.diaries import HAZARD_SEASON  # noqa: E402
from swelter.plan import SLOTS, SLOT_LIST  # noqa: E402

APP = pathlib.Path(__file__).resolve().parent.parent / "app" / "data"
DIARY = re.compile(r"diary #(\d+)")


def excursions(ep):
    """(depart, back, slot) in minutes after 6am for each stay away from the hour's place that the hourly plan drops."""
    steps, _, _ = hourly(ep)
    cls = [classify(code, where) for _, _, code, where in ep]
    nxt = "home"
    for i in range(len(cls) - 1, -1, -1):  # travel belongs to where it leads, as in hourly()
        if cls[i][1] is None:
            cls[i] = ("commute", nxt)
        else:
            nxt = cls[i][1]
    segs = []  # (start, end, slot): time at one place, counting the trip there
    for (s, e, _, _), (_, sl) in zip(ep, cls):
        if segs and segs[-1][2] == sl:
            segs[-1][1] = e
        else:
            segs.append([s, e, sl])
    out = []
    for s, e, sl in segs:
        s, e = s - 120, e - 120  # diary minutes start at 4am
        if s < 0 or e > 16 * 60 or e - s < 10:
            continue
        hours = range(s // 60, (e - 1) // 60 + 1)
        base = {SLOT_LIST[steps[h] % 20] for h in hours}
        if len(base) == 1 and sl not in base:
            out.append((s, e, sl, list(hours)))
    return out


def main():
    meta = json.loads((APP / "meta.json").read_text())
    places, residents, H = meta["places"], meta["residents"], len(meta["hours"])
    acts = meta["activities"]
    by_kind = {}
    for k, p in enumerate(places):
        by_kind.setdefault(p[1], []).append(k)

    def near(at, slot, i):
        """One of the three places of the slot's kinds nearest `at` (which one varies by resident)."""
        a = places[at]
        cands = [k for kind in SLOTS[slot] for k in by_kind.get(kind, [])]
        cands.sort(key=lambda k: (places[k][3] - a[3]) ** 2 + ((places[k][4] - a[4]) * 0.766) ** 2)
        return cands[i % 3] if len(cands) >= 3 else cands[0] if cands else None

    ids = {}
    for r in residents:
        for season in ("summer", "winter"):
            m = DIARY.search(r["trace"].get(f"day_{season}", ""))
            if m:
                ids[(r["id"], season)] = m.group(1)
    eps = episodes(set(ids.values()))
    trips = {key: excursions(eps[cid]) for key, cid in ids.items() if eps.get(cid)}
    print(f"{len(trips)} diaries, {sum(map(len, trips.values()))} short trips "
          f"({sum(bool(t) for t in trips.values())} diaries with at least one)")

    diary_act = {}
    for r in json.loads((APP.parent.parent / "data" / "residents.json").read_text()):
        for s, d in (r["days"] or {}).items():
            diary_act[(int(r["id"]), s)] = [acts[x // 20] for x in d]

    (APP / "micro").mkdir(exist_ok=True)
    for path in sorted((APP / "runs").glob("*.json")):
        run = json.loads(path.read_text())
        season = HAZARD_SEASON[run["hazard"]]
        flat, kept, total = [], 0, 0
        for i, st in enumerate(run["steps"]):
            ex, da = trips.get((i, season)), diary_act.get((i, season))
            if not ex or not da:
                continue
            place = [x // 1000 for x in st]
            act = [acts[(x % 1000) // 40] for x in st]
            work = next((place[h] for h in range(H) if act[h] in ("work_indoor", "work_outdoor")), None)
            for s, e, slot, hours in ex:
                total += 1
                if any(act[h] != da[h] for h in hours) or len({place[h] for h in hours}) > 1:
                    continue  # the hazard rules changed these hours
                if slot == "park" and any(run["levels"][i][h] != "0" for h in hours):
                    continue  # outdoors while it's unsafe: the rules would have called it off
                at = place[hours[0]]
                to = (residents[i]["home"] if slot == "home" else work if slot == "work"
                      else None if slot == "refuge" else near(at, slot, i))
                if to is None or to == at:
                    continue
                flat += [i, s, e, to]
                kept += 1
        (APP / "micro" / path.name).write_text(json.dumps({"run": run["id"], "trips": flat}, separators=(",", ":")))
        print(f"{run['id']}: {kept}/{total} short trips kept ({kept / len(run['steps']):.2f} per resident)")


if __name__ == "__main__":
    main()
