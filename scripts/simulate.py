"""Batch-generate every scenario run. The app replays these files; only the "why" explainer is live.

    python3 scripts/simulate.py                       # rule planner, all 48 runs
    python3 scripts/simulate.py --planner llm --only heat_severe   # Claude plans persona types (needs API key)

Writes app/data/meta.json (places, residents, hazard config) and app/data/runs/<scenario>.json.
"""
import argparse
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # swelter package + fetch_osm

from swelter import hazards as H  # noqa: E402
from swelter.exposure import score, summarize  # noqa: E402
from swelter.personas import ASSUMPTIONS, SOURCES, PersonaBuilder  # noqa: E402
from swelter.plan import ACTIVITY_LIST, bad_hours, repair, resolve_slots, verify  # noqa: E402
from swelter.rules import REASONS, RulePlanner  # noqa: E402
from swelter.world import DATA, ROOT, World  # noqa: E402

OUT = ROOT / "app" / "data"
REASON_LIST = list(REASONS)


def hazard_grid(world, step=0.0035):
    """Overlay cells: [lat, lon, heat-exposure °F, FEMA flood weight 0..1, riverfront wind °F]."""
    from fetch_osm import BBOX
    s, w, n, e = map(float, BBOX.split(","))
    cells = []
    lat = s + step / 2
    while lat < n:
        lon = w + step / 2
        while lon < e:
            if not world._east_of(world._delaware, lat, lon):
                sub = [(lat + dy, lon + dx) for dy in (-step / 4, step / 4) for dx in (-step / 4, step / 4)]
                flood = round(sum(world.flood_weight(a, b) for a, b in sub) / 4, 2)
                cells.append([round(lat, 5), round(lon, 5), world.heat_island(lat, lon), flood,
                              world.wind_exposure(lat, lon)])
            lon += step
        lat += step
    return {"step": step, "cells": cells}


def export_layers():
    """Slim copies of roads/waterways ([lon, lat] paths) for the map."""
    for name in ("roads", "waterways"):
        d = json.loads((DATA / f"{name}.json").read_text())
        slim = [{"c": x.get("class") or x.get("kind"), "p": [[round(lo, 4), round(la, 4)] for la, lo in x["coords"]]}
                for x in d]
        (OUT / f"{name}.json").write_text(json.dumps(slim, separators=(",", ":")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--planner", choices=["rules", "llm"], default="rules")
    ap.add_argument("--only", default="", help="substring filter on scenario ids")
    ap.add_argument("--residents", type=int, default=1500)
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    t0 = time.time()
    world = World()
    res_path = DATA / "residents.json"
    if res_path.exists():
        residents = json.loads(res_path.read_text())
    else:
        residents = PersonaBuilder(world).build(n=args.residents)
        res_path.write_text(json.dumps(residents))
    print(f"world: {len(world.places)} places, {len(world.tracts)} tracts; {len(residents)} residents, "
          f"{len({r['type'] for r in residents})} persona types")

    rules = RulePlanner(world)
    llm = None
    if args.planner == "llm":
        from swelter.llm import MODEL, LLMPlanner, type_key
        llm = LLMPlanner(world, model=args.model or MODEL)

    (OUT / "runs").mkdir(parents=True, exist_ok=True)
    # Stable place index (world order) so runs generated separately share one place table.
    places_out = [[p["id"], p["kind"], p["name"], p["lat"], p["lon"]] for p in world.places]
    place_index = {p["id"]: i for i, p in enumerate(world.places)}

    def pidx(p):
        return place_index[p["id"]]

    sids = [s for s in H.scenario_ids() if args.only in s]
    for sid in sids:
        sc = H.parse_scenario(sid)
        inten = H.intensity(sc["hazard"], sc["level"])
        slots_by_id = {r["id"]: resolve_slots(world, r, sc) for r in residents}
        llm_plans = {}
        if llm:
            reps = {}
            for r in residents:
                reps.setdefault(type_key(world, r, sc), r)
            llm_plans = llm.plan_types(
                sc, reps, slots_by_id, inten,
                verify=lambda rr, p: verify(world, rr, sc, p, slots_by_id[rr["id"]]))
        stats = {"drafts": 0, "rejected": 0, "repaired": 0, "llm_used": 0, "llm_fallback": 0}
        examples = []
        steps_out, levels_out, flags_out, levels_by = [], [], [], {}
        for r in residents:
            slots = slots_by_id[r["id"]]
            plan = None
            if llm:
                cand = llm_plans.get(type_key(world, r, sc))
                if cand:
                    stats["drafts"] += 1
                    bad = verify(world, r, sc, cand, slots)
                    if bad:
                        stats["rejected"] += 1
                        stats["llm_fallback"] += 1
                    else:
                        plan = cand
                        stats["llm_used"] += 1
                else:
                    stats["llm_fallback"] += 1
            attempt = 0
            while plan is None:
                cand = rules.plan(r, sc, slots, inten, attempt)
                stats["drafts"] += 1
                bad = verify(world, r, sc, cand, slots)
                if not bad:
                    plan = cand
                elif attempt >= 2:
                    stats["rejected"] += 1
                    stats["repaired"] += 1
                    plan = repair(cand, bad_hours(bad))
                    still = verify(world, r, sc, plan, slots)
                    if still:  # give up on the day's optional parts: stay home / at their spot
                        keep = "outdoors_unsheltered" if r["role"] == "unhoused" else "home"
                        plan["hours"] = [s if i not in bad_hours(still) else {"activity": keep, "place": "home", "why": "no_option"}
                                         for i, s in enumerate(plan["hours"])]
                else:
                    stats["rejected"] += 1
                    if len(examples) < 5:
                        examples.append({"resident": r["id"], "violations": bad[:3]})
                attempt += 1
            levels, values = score(world, r, sc, plan, slots, inten)
            levels_by[r["id"]] = levels
            levels_out.append("".join(map(str, levels)))
            steps_out.append([
                pidx(slots[s["place"]]) * 1000 + ACTIVITY_LIST.index(s["activity"]) * 40 + REASON_LIST.index(s["why"])
                for s in plan["hours"]
            ])
            flags_out.append(int(plan.get("aware", False)) | int(plan.get("ac_use", False)) << 1
                             | int(plan.get("mask", False)) << 2 | int(plan.get("heat_on", False)) << 3)
        summary = summarize(residents, levels_by, H.HAZARDS[sc["hazard"]]["groups"])
        run = {"id": sid, **sc, "planner": "llm+rules" if llm else "rules", "intensity": inten,
               "steps": steps_out, "levels": levels_out, "flags": flags_out, "summary": summary,
               "verifier": {**stats, "examples": examples}}
        (OUT / "runs" / f"{sid}.json").write_text(json.dumps(run, separators=(",", ":")))
        a = summary["all"]["all"]
        print(f"  {sid:32s} danger-h/person {a['danger_hours']:5.2f}  any-danger {a['share_any_danger']:.0%}  "
              f"verifier rejected {stats['rejected']}/{stats['drafts']} drafts")

    meta = {
        **H.meta(),
        "activities": ACTIVITY_LIST,
        "reasons": REASONS,
        "assumptions": {k: {"value": v[0], "source": v[1]} for k, v in ASSUMPTIONS.items()},
        "sources": {k: {"value": v[0], "source": v[1]} for k, v in SOURCES.items()},
        "places": places_out,
        "residents": [{k: r[k] for k in ("id", "name", "age", "role", "alone", "car", "ac", "heat", "respiratory",
                                          "poverty", "flood_zone", "groups", "type", "tract", "tract_name",
                                          "source", "trace", "vulnerable")}
                      | {"home": place_index[r["home"]], "commute_km": r.get("commute_km")} for r in residents],
        "scenarios": sids if not args.only else sorted(p.stem for p in (OUT / "runs").glob("*.json")),
        "grid": hazard_grid(world),
        "generated": time.strftime("%Y-%m-%d %H:%M"),
    }
    (OUT / "meta.json").write_text(json.dumps(meta, separators=(",", ":")))
    export_layers()
    if llm:
        print("LLM usage:", llm.usage)
    print(f"done: {len(sids)} runs in {time.time() - t0:.0f}s -> {OUT}")


if __name__ == "__main__":
    main()
