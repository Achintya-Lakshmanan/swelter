"""Meaningful checks for learned artifacts, leakage, and the siting objective.

Run: .venv-ml/bin/python -m unittest discover -s tests -v
"""
import importlib.util
import json
import pathlib
import unittest

import joblib
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("train_shelters", ROOT / "scripts" / "train_shelters.py")
training = importlib.util.module_from_spec(spec)
spec.loader.exec_module(training)


class CoverageTests(unittest.TestCase):
    def fixture(self):
        r = {"age": "65-74", "car": False, "role": "retired", "ac": False, "heat": False}
        a = {"id": "a", "name": "A", "lat": 40, "lon": -75, "hours": [9, 17], "hours_text": "9–17", "cooling": True, "warming": True}
        b = {**a, "id": "b", "name": "B"}
        meta = {"residents": [r], "hours": [8, 12], "places": [["p", "home", "Home", 40, -75]], "refuges": [a, b]}
        return meta, {"steps": [[0, 0]]}, np.asarray([[1., 1.]])

    def test_closed_hours_and_duplicate_sites_cannot_inflate_coverage(self):
        meta, run, risk = self.fixture()
        result = training.rank_sites(meta, "heat", run, risk)
        self.assertEqual(len(result["sites"]), 1)
        self.assertEqual(result["coverage"]["1"]["expected_risk_hours_reachable"], 1)
        self.assertEqual(result["coverage"]["1"]["expected_risk_hours_outside_coverage"], 1)

    def test_far_site_not_reachable_by_older_car_free_resident(self):
        meta, run, risk = self.fixture()
        for site in meta["refuges"]:
            site["lat"] += .02
        self.assertEqual(training.rank_sites(meta, "heat", run, risk)["sites"], [])

    def test_hazard_designation_is_required(self):
        meta, run, risk = self.fixture()
        for site in meta["refuges"]:
            site["warming"] = False
        result = training.rank_sites(meta, "cold", run, risk)
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["sites"], [])

    def test_policy_prioritizes_lack_of_heating_for_cold(self):
        resident = {"age": "25-44", "car": True, "role": "office", "ac": True, "heat": False}
        self.assertGreater(training.priority(resident, "cold"), training.priority(resident, "heat"))


class ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = training.read(training.APP / "shelter_models.json")

    def test_only_requested_models_exist(self):
        self.assertEqual(set(self.document["models"]), {"heat", "cold"})

    def test_inputs_artifacts_and_group_splits_are_traceable(self):
        for hazard in ("heat", "cold"):
            with self.subTest(hazard=hazard):
                manifest = training.read(training.OUT / f"{hazard}.manifest.json")
                split = manifest["split"]
                self.assertFalse(set(split["train_group_ids"]) & set(split["test_group_ids"]))
                self.assertGreater(split["test_groups"], 0)
                for path, checksum in manifest["inputs"].items():
                    self.assertEqual(training.digest(ROOT / path), checksum)
                self.assertEqual(training.digest(training.OUT / f"{hazard}.joblib"), manifest["artifact_sha256"])
                self.assertEqual(training.digest(ROOT / "scripts" / "train_shelters.py"), manifest["training_script_sha256"])
                model = joblib.load(training.OUT / f"{hazard}.joblib")
                self.assertEqual(model.n_features_in_, len(manifest["features"]))
                metrics = manifest["metrics"]
                self.assertLess(metrics["brier"], metrics["constant_baseline_brier"])

    def test_published_rankings_obey_hours_designations_and_monotonic_coverage(self):
        meta = training.read(training.APP / "meta.json")
        sites = {s["id"]: s for s in meta["refuges"]}
        for hazard, model in self.document["models"].items():
            for level, result in model["rankings"].items():
                with self.subTest(hazard=hazard, level=level):
                    last = 0
                    ids = []
                    for count, selected in enumerate(result["sites"], 1):
                        site = sites[selected["id"]]
                        self.assertTrue(site["cooling" if hazard == "heat" else "warming"])
                        self.assertEqual(selected["hours"], site["hours"])
                        ids.append(site["id"])
                        covered = result["coverage"][str(count)]["expected_risk_hours_reachable"]
                        self.assertGreaterEqual(covered, last)
                        self.assertLessEqual(covered, result["total_expected_risk_hours"] + .1)
                        last = covered
                    self.assertEqual(len(ids), len(set(ids)))

    def test_weaker_unseen_day_results_are_disclosed(self):
        for model in self.document["models"].values():
            expected = [level for level, m in model["unseen_day_and_diary_metrics"].items()
                        if m["brier"] >= m["constant_baseline_brier"]]
            self.assertEqual(model["weaker_unseen_days"], expected)

    def test_published_predictions_and_masks_reproduce_coverage_metrics(self):
        meta = training.read(training.APP / "meta.json")
        expected_shape = (len(meta["residents"]), len(meta["hours"]))
        for hazard, model in self.document["models"].items():
            for level, result in model["rankings"].items():
                with self.subTest(hazard=hazard, level=level):
                    risk = np.asarray(result["risk_milli"]) / 1000
                    self.assertEqual(risk.shape, expected_shape)
                    self.assertTrue(np.all((risk >= 0) & (risk <= 1)))
                    self.assertAlmostEqual(float(risk.sum()), result["total_expected_risk_hours"], delta=.1)
                    previous = np.zeros(expected_shape)
                    for count, rows in result["coverage_masks"].items():
                        mask = np.asarray([[int(c) for c in row] for row in rows])
                        self.assertEqual(mask.shape, expected_shape)
                        self.assertTrue(np.all(mask >= previous))
                        self.assertAlmostEqual(float(np.sum(risk * mask)), result["coverage"][count]["expected_risk_hours_reachable"], delta=.1)
                        previous = mask


if __name__ == "__main__":
    unittest.main()
