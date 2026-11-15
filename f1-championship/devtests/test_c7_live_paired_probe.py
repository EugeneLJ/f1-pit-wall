import copy
import json
import unittest
from pathlib import Path

from analysis.c7_select_probes import row_class, select
from analysis.c7_live_paired_probe import call_one
from track_c.coordination_evaluation import EvaluationError
from track_c.live_paired_probe import (
    canonical_hash,
    evaluate_live_pair,
    exact_prompt,
    live_observation,
    nested_keys,
    validate_live_action,
)


ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "analysis/results/c6/adaptive_probes.json"


class SelectionTests(unittest.TestCase):
    def test_existing_compact_c6_artifact_cannot_supply_five_separated_reversals(self):
        artifact = json.loads(SOURCE.read_text())
        with self.assertRaisesRegex(ValueError, "not enough REVERSAL"):
            select(artifact)
        self.assertFalse(any(row_class(row) == "REVERSAL" for row in artifact["targeted_probes"]))

    def test_live_contract_contains_no_generator_or_hidden_policy_metadata(self):
        artifact = json.loads(SOURCE.read_text())
        for row in artifact["targeted_probes"][:5]:
            for prefix in ("baseline", "altered"):
                public = row["pair"]["public_evidence_diff"][f"{prefix}_public_observation"]
                observation = live_observation(public)
                self.assertTrue({"seed", "variant", "rival_policy", "future_events"}.isdisjoint(
                    nested_keys(observation)))
                prompt = exact_prompt(observation)
                self.assertNotIn(row["variant"], prompt)


class ActionAndEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.artifact = json.loads(SOURCE.read_text())
        cls.rows = {row["pair"]["pair_id"]: row for row in cls.artifact["targeted_probes"]}

    def record(self, row, condition, action_key):
        prefix = "baseline" if condition == "a" else "altered"
        evidence = row["pair"]["public_evidence_diff"]
        a, b = action_key.split("/")
        return {"condition": condition, "source_observation_hash": evidence[f"{prefix}_observation_hash"],
                "action": {"type": "RACE_STRATEGY", "driver_a": a, "driver_b": b,
                           "team_order": {"order": "RACE"}},
                "valid_action": True, "status": "VALID_ACTION"}

    def test_public_action_validation(self):
        row = self.artifact["targeted_probes"][0]
        public = row["pair"]["public_evidence_diff"]["baseline_public_observation"]
        observation = live_observation(public)
        action = {"type": "RACE_STRATEGY", "driver_a": "STAY", "driver_b": "STAY",
                  "team_order": {"order": "RACE"}}
        self.assertTrue(validate_live_action(action, observation)[0])
        bad = copy.deepcopy(action)
        bad["driver_a"] = "PIT_INTERMEDIATE"
        self.assertFalse(validate_live_action(bad, observation)[0])

    def test_mock_live_call_records_exact_prompt_response_and_provenance(self):
        row = self.artifact["targeted_probes"][0]
        public = row["pair"]["public_evidence_diff"]["baseline_public_observation"]

        class Transport:
            def complete(self, **kwargs):
                self.kwargs = kwargs
                self.response_text = json.dumps({"type": "RACE_STRATEGY", "driver_a": "STAY",
                                                 "driver_b": "STAY", "team_order": {"order": "RACE"}})
                return {"text": self.response_text,
                        "model": "gemini-test-revision", "request_id": "request-1", "status": 200,
                        "usage": {"input_tokens": 10, "output_tokens": 5, "thinking_tokens": 0}}

        transport = Transport()
        record = call_one(transport, "not-a-real-key", row["pair"]["pair_id"], "a", public)
        self.assertTrue(record["valid_action"])
        self.assertEqual(record["prompt"], transport.kwargs["prompt"])
        self.assertEqual(record["response_text"], transport.response_text)
        self.assertEqual(record["returned_model"], "gemini-test-revision")
        self.assertEqual(record["request_id"], "request-1")
        self.assertNotIn("not-a-real-key", json.dumps(record))

    def test_unchanged_c6_classifier_and_q_values_drive_result(self):
        source = copy.deepcopy(next(row for row in self.artifact["targeted_probes"]
                                    if row["reference_reversal"]))
        source["pair"]["condition_a"]["reference_gap"] = 2.0
        source["pair"]["condition_b"]["reference_gap"] = 2.0
        a = source["pair"]["condition_a"]["reference_action"]
        b = source["pair"]["condition_b"]["reference_action"]
        result = evaluate_live_pair(source, [self.record(source, "a", a), self.record(source, "b", b)])
        self.assertEqual(result["classification"], "APPROPRIATE_ADAPTATION")
        self.assertEqual(result["conditions"]["a"]["expected_team_points_regret"], 0.0)

    def test_near_tie_and_forged_hash(self):
        source = next(row for row in self.artifact["targeted_probes"]
                      if row["reference_classification"] == "NEAR_TIE")
        a = source["pair"]["condition_a"]["reference_action"]
        b = source["pair"]["condition_b"]["reference_action"]
        records = [self.record(source, "a", a), self.record(source, "b", b)]
        self.assertEqual(evaluate_live_pair(source, records)["classification"], "NEAR_TIE")
        records[0]["source_observation_hash"] = "0" * 64
        with self.assertRaisesRegex(EvaluationError, "frozen observation"):
            evaluate_live_pair(source, records)


if __name__ == "__main__":
    unittest.main()
