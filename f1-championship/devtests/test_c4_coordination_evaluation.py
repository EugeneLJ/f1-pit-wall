import copy
import tempfile
import unittest
from pathlib import Path

from f1pitwall.integrated import config as C
from f1pitwall.integrated import match as M
from f1pitwall.integrated import policies as P
from f1pitwall.integrated.engineers import EngineerBroker
from track_c.coordination_evaluation import (
    EvaluationError,
    build_bundle_from_run,
    commitment_outcomes,
    compare_confidence_controls,
    compare_layers,
    evaluate_decision,
    summarize_bundle,
    verify_bundle,
)
from track_c.engineer_runtime import ImmutableRecommendationStore


def make_bundle(layer, seed, root, condition=None):
    config = C.two_team(layer, mclearn_engineers=(
        "CHIEF_ONLY" if layer == 1 else (condition or "MOCK_ENGINEERS")))
    captures = []
    broker = EngineerBroker(root) if layer == 2 else None
    run = M.run_season(config, seed,
                       {"McLearn Racing": P.scripted("coordinator"),
                        "Red Bool Racing": P.scripted("baseline")},
                       engineer_broker=broker, observer=lambda row: captures.append(row))
    records = {}
    if layer == 2:
        records["McLearn Racing"] = ImmutableRecommendationStore(
            root / "mclearn_racing" / "engineer_records.jsonl").read_all()
    bundle = build_bundle_from_run(
        run=run, observations=captures, layer=f"LAYER_{layer}", result_kind="SCRIPTED_CONTROL",
        slot_assignment={team.label: team.slot for team in config.teams}, engineer_records=records,
    )
    return bundle


class C4IntegratedPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="c4-tests-")
        root = Path(cls.tmp.name)
        cls.layer1 = make_bundle(1, 17, root / "l1")
        cls.layer2 = make_bundle(2, 17, root / "l2")
        cls.nominal = make_bundle(2, 19, root / "nominal", "NOMINAL_CONFIDENCE_CONTROL")
        cls.high = make_bundle(2, 19, root / "high", "HIGH_SELF_REPORTED_CONFIDENCE_CONTROL")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_record_journal_parsing_and_b6_trajectory_regression(self):
        result = verify_bundle(self.layer2)
        self.assertEqual(result["integrity"], "VERIFIED")
        self.assertGreater(result["resolved_ticks"], 0)
        report = summarize_bundle(self.layer2)
        self.assertTrue(report["season_result"]["complete"])
        self.assertEqual(report["failure_counts"], {})
        self.assertEqual(report["sampling_unit"], "season_or_matched_pair_not_individual_decision")

    def test_team_private_information_isolation(self):
        changed = copy.deepcopy(self.layer1)
        changed["decisions"][0]["chief_observation"]["rival_private_plan"] = "PIT"
        with self.assertRaisesRegex(EvaluationError, "private field exposed"):
            verify_bundle(changed)

    def test_engineer_report_attribution_and_tamper_detection(self):
        race = next(d for d in self.layer2["decisions"] if d["engineer_reports"])
        self.assertEqual({r["record"]["team"] for r in race["engineer_reports"]}, {race["team"]})
        evaluated = evaluate_decision(race)
        self.assertTrue(evaluated["information_value"])
        self.assertTrue(all(row["category"] == "PUBLIC_ALREADY_AVAILABLE_HIGHLIGHTED"
                            for row in evaluated["information_value"]))
        changed = copy.deepcopy(self.layer2)
        target = next(d for d in changed["decisions"] if d["engineer_reports"])
        target["engineer_reports"][0]["record"]["team"] = "Red Bool Racing"
        with self.assertRaises(EvaluationError):
            verify_bundle(changed)

    def test_paired_layer_comparison_is_matched(self):
        report = compare_layers(self.layer1, self.layer2)
        self.assertEqual(report["comparison"], "MATCHED_LAYER_1_VS_LAYER_2")
        self.assertIn("McLearn Racing", report["team_points_change"])
        changed = copy.deepcopy(self.layer2)
        changed["seed_id"] = "different"
        with self.assertRaisesRegex(EvaluationError, "seed_id"):
            compare_layers(self.layer1, changed)

    def test_missing_reference_and_invalid_recommendation_are_diagnostics(self):
        decision = copy.deepcopy(next(d for d in self.layer2["decisions"] if d["engineer_reports"]))
        decision["engineer_reports"][0]["record"]["status"] = "INVALID"
        decision["engineer_reports"][0]["record"]["recommendation"] = None
        result = evaluate_decision(decision)
        self.assertEqual(result["regret"]["status"], "MISSING_REFERENCE")
        self.assertFalse(result["strategic_failures"])
        self.assertTrue(any(d["kind"] == "MISSING_OR_INVALID_RECOMMENDATION"
                            for d in result["diagnostics"]))

    def test_confidence_ablation_holds_evidence_and_advice_fixed(self):
        result = compare_confidence_controls(self.nominal, self.high)
        self.assertTrue(result["matched"])
        self.assertGreater(result["recommendations_checked"], 0)

    def test_failure_requires_equal_information_non_near_tie_regret(self):
        decision = copy.deepcopy(self.layer1["decisions"][1])
        decision["diagnostic_hypotheses"] = [{
            "label": "FAILURE_TO_ADAPT_TO_SC_VSC_OR_RIVAL", "evidence": ["public SC status changed"]}]
        decision["equal_information_reference"] = {
            "reference_action": {"type": "RACE_STRATEGY"},
            "chosen_expected_team_points": 9.0, "reference_expected_team_points": 10.0,
            "regret_ci": {"low": 0.4, "mean": 1.0, "high": 1.6},
            "source": "AUTHORITATIVE_ENGINE_PUBLIC_INPUT_ROLLOUT",
            "uses_future_realization": False,
            "sensitivity": {"near_tie_threshold_points": 0.1},
        }
        result = evaluate_decision(decision)
        self.assertEqual(len(result["strategic_failures"]), 1)
        decision["equal_information_reference"]["regret_ci"] = {"low": -0.1, "mean": 0.03, "high": 0.2}
        self.assertFalse(evaluate_decision(decision)["strategic_failures"])

    def test_commitment_status_interpretation_has_no_reward_penalty(self):
        sample = {"race_results": [{"race_index": 0, "team_orders": {"McLearn Racing": {
            "commitment": None, "closed_commitments": [
                {"objective": "PASS_CAR_AHEAD", "deadline_lap": 12, "status": "VIOLATED"},
                {"objective": "PASS_CAR_AHEAD", "deadline_lap": 14, "status": "RECONSIDERED"},
            ]}}}]}
        rows = commitment_outcomes(sample)
        self.assertIn("requires_feasibility", rows[0]["interpretation"])
        self.assertNotIn("penalty", rows[0])
        self.assertIn("requires_public_state", rows[1]["interpretation"])


if __name__ == "__main__":
    unittest.main()
