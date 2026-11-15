import copy
import gzip
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from track_c.adaptive_rival_evaluation import (
    audit_bundle_visibility,
    classify_adaptation,
    load_verified_bundle,
    public_rival_evidence,
)
from track_c.coordination_evaluation import EvaluationError
from track_c.gap_evidence import export_gap_evidence, markdown_report


ROOT = Path(__file__).parents[1]


def canonical_hash(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def nested_keys(value):
    if isinstance(value, dict):
        return set(value).union(*(nested_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(nested_keys(item) for item in value)) if value else set()
    return set()


def pair(reference_a="STAY/STAY", reference_b="PIT_HARD/STAY", gap_a=2.0, gap_b=2.0,
         chief_a=None, chief_b=None, visible=True):
    return {
        "pair_id": "p1", "public_evidence_diff": {"visible_before_chief_decision": visible},
        "condition_a": {"reference_action": reference_a, "reference_gap": gap_a, "chief_action": chief_a},
        "condition_b": {"reference_action": reference_b, "reference_gap": gap_b, "chief_action": chief_b},
        "reference_provenance": {"future_info": False}, "uses_hidden_policy_as_observation": False,
    }


class AdaptiveRivalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.layer1_path = ROOT / "analysis/results/b7/layer1/c4_bundle.json.gz"

    def test_frozen_b7_bundle_verifies_and_links_visibility(self):
        bundle = load_verified_bundle(self.layer1_path)
        report = audit_bundle_visibility(bundle, "McLearn Racing", "Red Bool Racing")
        self.assertGreater(report["race_decisions"], 0)
        self.assertGreater(report["new_visible_rival_stops"], 0)

    def test_forged_observation_is_rejected(self):
        with gzip.open(self.layer1_path, "rt") as handle:
            bundle = json.load(handle)
        bundle["decisions"][0]["chief_observation"]["team"] = "forged"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "forged.json"
            path.write_text(json.dumps(bundle), encoding="utf-8")
            with self.assertRaises(EvaluationError):
                load_verified_bundle(path)

    def test_public_evidence_does_not_infer_hidden_policy(self):
        observation = {
            "race_progress": {
                "track_status": "GREEN", "decision_index": 3,
                "drivers": {"driver_a": {"name": "McLearn A"}, "driver_b": {"name": "McLearn B"}},
                "classification": [{"driver": "Red Bool A", "team": "Red Bool Racing", "position": 1}],
                "public_pit_history": [{"decision": 2, "stops": [
                    {"driver": "McLearn A", "compound": "HARD"},
                    {"driver": "Red Bool A", "compound": "SOFT"}]}],
            }}
        evidence = public_rival_evidence(observation, "McLearn Racing", "Red Bool Racing")
        self.assertEqual(len(evidence["visible_rival_pit_history"][0]["stops"]), 1)
        self.assertFalse(evidence["hidden_policy_identity_visible"])

    def test_adaptation_labels_require_visibility_pairing_and_separation(self):
        hidden = pair()
        hidden["uses_hidden_policy_as_observation"] = True
        self.assertEqual(classify_adaptation(hidden)["classification"], "INSUFFICIENT_EVIDENCE")
        leaked = pair()
        leaked["reference_provenance"]["future_info"] = True
        self.assertEqual(classify_adaptation(leaked)["classification"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(classify_adaptation(pair(visible=False))["classification"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(classify_adaptation(pair(gap_b=0.1))["classification"], "NEAR_TIE")
        self.assertEqual(classify_adaptation(pair())["classification"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(classify_adaptation(pair(chief_a="STAY/STAY", chief_b="STAY/STAY"))["classification"],
                         "FAILURE_TO_ADAPT")
        self.assertEqual(classify_adaptation(pair(chief_a="STAY/STAY", chief_b="PIT_HARD/STAY"))["classification"],
                         "APPROPRIATE_ADAPTATION")
        stable = pair(reference_b="STAY/STAY", chief_a="STAY/STAY", chief_b="PIT_HARD/STAY")
        self.assertEqual(classify_adaptation(stable)["classification"], "OVERREACTION")


class GapExporterTests(unittest.TestCase):
    def manifest(self):
        return {"schema_version": 1,
                "benchmark": {"version": "2.0.1", "config_hash": "abc", "reward_version": "constructors-v1"},
                "runs": [
                    {"run_id": "f1", "role": "FRONTIER", "seed_id": "s1", "comparison_group": "harbor",
                     "complete": True, "constructors_points": 20, "normalized_reward": 0.4,
                     "model": "gemini", "selected_decision_failures": []},
                    {"run_id": "r1", "role": "REFERENCE", "seed_id": "s1", "comparison_group": "harbor",
                     "complete": True, "constructors_points": 25, "normalized_reward": 0.6,
                     "policy_provenance": {"kind": "public planner"}},
                    {"run_id": "f2", "role": "FRONTIER", "seed_id": "s2", "comparison_group": "harbor",
                     "complete": True, "constructors_points": 22, "normalized_reward": 0.45},
                    {"run_id": "r2", "role": "REFERENCE", "seed_id": "s2", "comparison_group": "harbor",
                     "complete": True, "constructors_points": 30, "normalized_reward": 0.7},
                    {"run_id": "b7-gemini", "role": "COMPETITION", "seed_id": "b7", "comparison_group": "b7",
                     "complete": True, "constructors_points": 304, "normalized_reward": None},
                ]}

    def test_gap_is_paired_by_season_and_competition_is_separate(self):
        report = export_gap_evidence(self.manifest())
        harbor = next(row for row in report["frontier_reference_gap"] if row["comparison_group"] == "harbor")
        self.assertEqual(harbor["season_level_gap"]["n_seasons"], 2)
        self.assertEqual(harbor["season_level_gap"]["mean_points"], 6.5)
        self.assertEqual(len(report["gemini_deepseek_competition"]), 1)
        self.assertIn("not the official Frontier–Reference gap", markdown_report(report))

    def test_mismatched_seed_remains_pending(self):
        manifest = self.manifest()
        manifest["runs"][1]["seed_id"] = "different"
        report = export_gap_evidence(manifest)
        harbor = next(row for row in report["frontier_reference_gap"] if row["comparison_group"] == "harbor")
        self.assertEqual(harbor["season_level_gap"]["n_seasons"], 1)
        self.assertTrue(harbor["unmatched_or_pending"])

    def test_forged_failure_without_hash_or_regret_is_rejected(self):
        manifest = self.manifest()
        manifest["runs"][0]["selected_decision_failures"] = [{"label": "failure"}]
        with self.assertRaisesRegex(EvaluationError, "observation hash"):
            export_gap_evidence(manifest)

    def test_forged_regret_and_out_of_range_reward_are_rejected(self):
        manifest = self.manifest()
        manifest["runs"][0]["selected_decision_failures"] = [{
            "observation_hash": "a" * 64,
            "regret_evidence": {"source": "claimed", "expected_points_regret": float("nan")},
        }]
        with self.assertRaisesRegex(EvaluationError, "invalid regret"):
            export_gap_evidence(manifest)
        manifest = self.manifest()
        manifest["runs"][0]["normalized_reward"] = 1.01
        with self.assertRaisesRegex(EvaluationError, "within"):
            export_gap_evidence(manifest)


class GeneratedProbeTests(unittest.TestCase):
    def test_targeted_probes_link_exact_public_observations_without_hidden_inputs(self):
        artifact = json.loads((ROOT / "analysis/results/c6/adaptive_probes.json").read_text())
        self.assertFalse(artifact["actual_model_results"])
        self.assertEqual(artifact["candidate_state_variant_pairs"],
                         artifact["natural_sampled_pre_action_states"] * 5)
        forbidden = {"hidden_seed", "future_events", "realized_future", "rival_policy"}
        for row in artifact["targeted_probes"]:
            evidence = row["pair"]["public_evidence_diff"]
            for prefix in ("baseline", "altered"):
                observation = evidence[f"{prefix}_public_observation"]
                self.assertEqual(evidence[f"{prefix}_observation_hash"], canonical_hash(observation))
                self.assertTrue(forbidden.isdisjoint(nested_keys(observation)))
            self.assertFalse(row["pair"]["uses_hidden_policy_as_observation"])


if __name__ == "__main__":
    unittest.main()
