"""Train two simulation-surrogate classifiers and rank real cooling/warming sites.

Run: .venv-ml/bin/python scripts/train_shelters.py
No observed health or shelter outcome labels are available. These models predict
the existing simulator's baseline danger labels, not real-world shelter benefit.
The coverage optimizer is deterministic; its weights are policy assumptions.
"""
import hashlib
import json
import math
import pathlib
import re
from datetime import datetime, timezone

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, brier_score_loss, recall_score
from sklearn.model_selection import GroupShuffleSplit

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = ROOT / "app" / "data"
OUT = ROOT / "models" / "shelters"
LEVELS = ("moderate", "severe", "extreme")
ROLES = ("office", "service", "healthcare", "outdoor", "student", "retired", "not_employed", "unhoused")
FLAGS = ("ac", "heat", "car", "alone", "respiratory", "poverty", "vulnerable")
FEATURES = ["hour", "intensity", "day_max", "day_min", "local_heat", "river_wind", "older"] + list(FLAGS)
FEATURES += ["role_" + r for r in ROLES]


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def distance(a, b):
    """Local planar distance in meters, never a road-network travel distance."""
    return math.hypot((a[0] - b[0]) * 111320, (a[1] - b[1]) * 85300)


def diary_group(r, hazard):
    season = "winter" if hazard == "cold" else "summer"
    trace = r["trace"].get("day_" + season, "")
    match = re.search(r"diary #(\d+)", trace)
    # Unhoused schedules are assumed, not ATUS. Group those by their home anchor.
    return "diary:" + match[1] if match else "anchor:" + str(r["home"])


def classifier():
    return RandomForestClassifier(n_estimators=64, max_depth=12,
                                  min_samples_leaf=12, max_features=0.8,
                                  random_state=20261025, n_jobs=2)


def positive_probability(model, x):
    if 1 not in model.classes_:
        return np.zeros(len(x))
    return model.predict_proba(x)[:, list(model.classes_).index(1)]


def build_examples(meta, hazard):
    activities = meta["activities"]
    feature_names = FEATURES + ["activity_" + a for a in activities] + ["at_home"]
    cells = meta["grid"]["cells"]
    local = {}
    rows, targets, groups, owners, levels = [], [], [], [], []
    runs = {}
    for level in LEVELS:
        rn = read(APP / "runs" / f"{hazard}_{level}_none.json")
        runs[level] = rn
        for i, r in enumerate(meta["residents"]):
            fixed = [int(r["age"] in ("65-74", "75+"))] + [int(r[k]) for k in FLAGS]
            fixed += [int(r["role"] == role) for role in ROLES]
            for h, hour in enumerate(meta["hours"]):
                code = rn["steps"][i][h]
                place_idx, activity = code // 1000, (code % 1000) // 40
                if place_idx not in local:
                    p = meta["places"][place_idx]
                    cell = min(cells, key=lambda c: distance((p[3], p[4]), c[:2]))
                    local[place_idx] = [cell[2], cell[4]]
                rows.append([hour, rn["intensity"][h], max(rn["intensity"]), min(rn["intensity"])]
                            + local[place_idx] + fixed
                            + [int(activity == j) for j in range(len(activities))]
                            + [int(place_idx == r["home"])])
                targets.append(int(rn["levels"][i][h]) >= 2)
                groups.append(diary_group(r, hazard))
                owners.append(f"{level}:{r['id']}")
                levels.append(level)
    return (np.asarray(rows, dtype=np.float32), np.asarray(targets, dtype=int),
            np.asarray(groups), np.asarray(owners), np.asarray(levels), feature_names, runs)


def evaluate(y, p, owners, prior):
    sums = {}
    for target, pred, owner in zip(y, p, owners):
        pair = sums.setdefault(owner, [0.0, 0.0])
        pair[0] += float(target)
        pair[1] += float(pred)
    return {"accuracy": round(float(accuracy_score(y, p >= .5)), 4),
            "danger_recall": round(float(recall_score(y, p >= .5, zero_division=0)), 4),
            "brier": round(float(brier_score_loss(y, p)), 5),
            "constant_baseline_brier": round(float(brier_score_loss(y, np.full(len(y), prior))), 5),
            "danger_prevalence": round(float(np.mean(y)), 4),
            "daily_hours_mae": round(float(np.mean([abs(a - b) for a, b in sums.values()])), 3),
            "rows": len(y), "resident_days": len(sums)}


def priority(r, hazard):
    # Explicit policy weights, not learned causal effects or population weights.
    vulnerable_home = not r["ac" if hazard == "heat" else "heat"]
    return 1 + vulnerable_home + (not r["car"]) + (r["role"] == "unhoused") + .5 * (r["age"] in ("65-74", "75+"))


def rank_sites(meta, hazard, run, risk):
    residents, hours = meta["residents"], meta["hours"]
    kind = "cooling" if hazard == "heat" else "warming"
    candidates = [s for s in meta["refuges"] if s[kind]]
    weights = np.asarray([priority(r, hazard) for r in residents])[:, None]
    matrices, distances = {}, {}
    for site in candidates:
        coverage = np.zeros_like(risk)
        dists = np.zeros_like(risk)
        for i, r in enumerate(residents):
            radius = 4000 if r["car"] else 2000 if r["role"] == "unhoused" else 700 if r["age"] in ("65-74", "75+") else 1000
            for h, hour in enumerate(hours):
                if not site["hours"][0] <= hour < site["hours"][1]:
                    continue
                p = meta["places"][run["steps"][i][h] // 1000]
                d = distance((p[3], p[4]), (site["lat"], site["lon"]))
                dists[i, h] = d
                if d <= radius:
                    coverage[i, h] = 1
        matrices[site["id"]] = coverage
        distances[site["id"]] = dists
    covered = np.zeros_like(risk)
    selected, summaries, masks = [], {}, {}
    pool = sorted(candidates, key=lambda s: s["id"])
    for rank in range(min(5, len(pool))):
        scored = []
        for site in pool:
            marginal = matrices[site["id"]] * (1 - covered)
            # Favor shorter trips among covered resident-hours, without calling this route time.
            proximity = 1 / (1 + distances[site["id"]] / 1000)
            score = float(np.sum(risk * weights * marginal * proximity))
            scored.append((score, site, marginal))
        score, site, marginal = max(scored, key=lambda item: item[0])
        if score <= 1e-9:
            break
        ids = np.flatnonzero(np.any((marginal > 0) & (risk >= .5), axis=1))
        reachable = float(np.sum(risk * marginal))
        weighted = marginal * risk
        avg_distance = float(np.sum(distances[site["id"]] * weighted) / np.sum(weighted)) if reachable else 0
        selected.append({"rank": rank + 1, "id": site["id"], "name": site["name"],
                         "lat": site["lat"], "lon": site["lon"], "address": site.get("address"),
                         "hours_text": site["hours_text"], "hours": site["hours"],
                         "priority_score": round(score, 2),
                         "additional_expected_risk_hours": round(reachable, 1),
                         "at_risk_residents": len(ids),
                         "no_car": sum(not residents[i]["car"] for i in ids),
                         "unhoused": sum(residents[i]["role"] == "unhoused" for i in ids),
                         "no_ac_or_heat": sum(not residents[i]["ac" if hazard == "heat" else "heat"] for i in ids),
                         "mean_straight_line_m": round(avg_distance)})
        covered = np.maximum(covered, matrices[site["id"]])
        masks[str(rank + 1)] = ["".join(str(int(value)) for value in row) for row in covered]
        pool = [s for s in pool if s["id"] != site["id"]]
        covered_hours = float(np.sum(risk * covered))
        total = float(np.sum(risk))
        summaries[str(rank + 1)] = {"expected_risk_hours_reachable": round(covered_hours, 1),
                                   "share_reachable": round(covered_hours / total, 4) if total else 0,
                                   "expected_risk_hours_outside_coverage": round(total - covered_hours, 1)}
    return {"candidate_count": len(candidates), "sites": selected, "coverage": summaries, "coverage_masks": masks,
            "risk_milli": np.rint(risk * 1000).astype(int).tolist(),
            "total_expected_risk_hours": round(float(np.sum(risk)), 1)}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    meta = read(APP / "meta.json")
    model_doc = {"version": 1, "generated": datetime.now(timezone.utc).isoformat(),
                 "scope": "Simulation-based planning estimates; not operational shelter guidance.",
                 "limitations": ["Labels are simulated exposure, not observed illness or shelter outcomes.",
                                 "Only three historical days per hazard; no claim of future-weather generalization.",
                                 "Residents are synthetic and unhoused residents are oversampled; counts are not population estimates.",
                                 "Straight-line distance, assumed reach limits; no road routing, capacity, accessibility or current facility verification.",
                                 "Scores measure reachable baseline risk, not hours prevented. Playback shows baseline routines; opening sites does not claim attendance or risk reduction."],
                 "sources": {"sites": "City of Philadelphia warming/cooling site records and posted hours",
                             "weather": "NOAA PHL historical hourly heat index / wind chill",
                             "residents": "Synthetic residents from ACS 2024, RECS 2020, CDC PLACES and ATUS 2018–2024",
                             "labels": "Existing baseline simulation levels >= 2"},
                 "policy": {"objective": "Greedy maximum coverage of predicted baseline danger probability, weighted by vulnerability and proximity; previously covered resident-hours are not counted twice.",
                            "weights": "1 + no AC/heat + no car + unhoused + 0.5 older (65+)",
                            "reach_m": "Car: 4000; unhoused on foot: 2000; other older adults on foot: 700; other car-free adults: 1000",
                            "proximity": "1 / (1 + straight-line distance in km)",
                            "hours": "Candidate must be open during the resident-hour."},
                 "models": {}}
    for hazard in ("heat", "cold"):
        x, y, groups, owners, levels, features, runs = build_examples(meta, hazard)
        train, test = next(GroupShuffleSplit(n_splits=1, test_size=.2, random_state=20261025).split(x, y, groups))
        assert not set(groups[train]) & set(groups[test])
        model = classifier().fit(x[train], y[train])
        metrics = evaluate(y[test], positive_probability(model, x[test]), owners[test], float(np.mean(y[train])))
        day_tests = {}
        for level in LEVELS:
            # Jointly hold out a weather day AND the test diary groups.
            fit = train[levels[train] != level]
            check = test[levels[test] == level]
            fold = classifier().fit(x[fit], y[fit])
            day_tests[level] = evaluate(y[check], positive_probability(fold, x[check]), owners[check], float(np.mean(y[fit])))
        if metrics["brier"] >= metrics["constant_baseline_brier"]:
            raise RuntimeError(f"{hazard}: model fails to beat constant-risk baseline; recommendations not published")
        split = {"method": "80/20 GroupShuffleSplit by sampled ATUS diary ID; assumed unhoused schedules grouped by home anchor",
                 "seed": 20261025, "train_rows": len(train), "test_rows": len(test),
                 "train_groups": len(set(groups[train])), "test_groups": len(set(groups[test])),
                 "overlap": 0, "train_group_ids": sorted(set(groups[train])), "test_group_ids": sorted(set(groups[test]))}
        # Final production artifact uses all data; evaluation above uses a separate held-out model.
        final = classifier().fit(x, y)
        joblib.dump(final, OUT / f"{hazard}.joblib", compress=3)
        risk = np.round(positive_probability(final, x), 3)
        n, h = len(meta["residents"]), len(meta["hours"])
        rankings = {level: rank_sites(meta, hazard, runs[level], risk[j*n*h:(j+1)*n*h].reshape(n, h))
                    for j, level in enumerate(LEVELS)}
        important = sorted(zip(features, final.feature_importances_), key=lambda item: -item[1])[:8]
        weaker_days = [level for level, metric in day_tests.items() if metric["brier"] >= metric["constant_baseline_brier"]]
        card = {"algorithm": "RandomForestClassifier", "parameters": {k: v for k, v in final.get_params().items() if k in ("n_estimators", "max_depth", "min_samples_leaf", "max_features", "random_state")},
                "target": "Probability of simulated dangerous exposure (baseline level >= 2) per resident-hour",
                "feature_names": features, "training_rows": len(y), "historical_days": 3,
                "metrics": metrics, "unseen_day_and_diary_metrics": day_tests,
                "weaker_unseen_days": weaker_days,
                "split": {k: v for k, v in split.items() if not k.endswith("group_ids")},
                "important_features": [{"name": name, "importance": round(float(value), 4)} for name, value in important],
                "artifact_sha256": digest(OUT / f"{hazard}.joblib"), "rankings": rankings}
        model_doc["models"][hazard] = card
        manifest = {"hazard": hazard, "scikit_learn": sklearn.__version__, "numpy": np.__version__,
                    "features": features, "split": split, "training_script_sha256": digest(pathlib.Path(__file__)),
                    "inputs": {"app/data/meta.json": digest(APP / "meta.json"), **{f"app/data/runs/{hazard}_{level}_none.json": digest(APP / "runs" / f"{hazard}_{level}_none.json") for level in LEVELS}},
                    "artifact_sha256": card["artifact_sha256"], "metrics": metrics,
                    "unseen_day_and_diary_metrics": day_tests}
        (OUT / f"{hazard}.manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        print(hazard, json.dumps(metrics), flush=True)
    (APP / "shelter_models.json").write_text(json.dumps(model_doc, separators=(",", ":")) + "\n")
    print("Wrote trained artifacts, manifests, and app/data/shelter_models.json", flush=True)


if __name__ == "__main__":
    main()
