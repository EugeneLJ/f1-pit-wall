import copy
import unittest

from track_c.scenario_evaluation import (
    assess_decision,
    assess_shared_resource_allocation,
    evaluate_policy,
    fair_reference,
    follow_up_action,
    initial_action,
    load_coordination_scenarios,
    load_shared_resource_scenarios,
    recommendation_information_ablation,
    recommendation_value_ablation,
    shared_resource_action,
    validate_coordination_action,
)


class ResearchScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        payload = load_coordination_scenarios()
        cls.mechanics = payload["mechanics"]
        cls.scenarios = {item["id"]: item for item in payload["scenarios"]}

    def test_fixture_is_synthetic_and_uses_valid_eight_car_orders(self):
        payload = load_coordination_scenarios()
        self.assertEqual(payload["data_status"], "synthetic_placeholder")
        for scenario in payload["scenarios"]:
            classification = scenario["public_state"]["classification"]
            self.assertEqual(len(classification), 8)
            self.assertEqual(len(set(classification)), 8)

    def test_swap_outcome_depends_on_gap_pace_tyre_and_rival_pressure(self):
        safe = self.scenarios["safe_release_attack"]
        pressured = self.scenarios["release_under_rival_pressure"]
        deadline = 35
        action = initial_action("SWAP", deadline_lap=deadline)
        follow_up = follow_up_action("KEEP_ORDER")

        safe_result = evaluate_policy(safe, self.mechanics, action, follow_up)
        pressured_result = evaluate_policy(pressured, self.mechanics, action, follow_up)
        self.assertTrue(safe_result["swap_feasible"])
        self.assertTrue(safe_result["objective_met"])
        self.assertFalse(pressured_result["objective_met"])
        self.assertGreater(pressured_result["swap_time_loss"], safe_result["swap_time_loss"])
        self.assertGreater(safe_result["constructors_points"], pressured_result["constructors_points"])

        remote = copy.deepcopy(safe)
        remote["id"] = "remote_swap_control"
        remote["public_state"]["teammate_gap"] = self.mechanics["max_swap_gap"] + 0.01
        remote_result = evaluate_policy(remote, self.mechanics, action, follow_up)
        self.assertFalse(remote_result["swap_feasible"])
        self.assertEqual(remote_result["swap_time_loss"], 0.0)

    def test_counterfactual_pair_reverses_reference_action(self):
        safe_reference = fair_reference(self.scenarios["safe_release_attack"], self.mechanics)
        pressure_reference = fair_reference(
            self.scenarios["release_under_rival_pressure"], self.mechanics
        )
        self.assertEqual(safe_reference["actions"][0]["order"], "SWAP")
        self.assertEqual(pressure_reference["actions"][0]["order"], "DEFENSIVE_BUFFER")
        self.assertEqual(safe_reference["reference_kind"], "exact_public_deterministic_enumeration")
        self.assertEqual(safe_reference["candidate_count"], 4)

    def test_team_points_regret_not_action_difference_defines_failure(self):
        safe = self.scenarios["safe_release_attack"]
        wrong = assess_decision(safe, self.mechanics, initial_action("HOLD"))
        self.assertTrue(wrong["scored_failure"])
        self.assertEqual(wrong["expected_team_points_cost"], 3)

        safe_give_back = self.scenarios["failed_attack_safe_give_back"]
        deadline = 46
        broken = assess_decision(
            safe_give_back,
            self.mechanics,
            initial_action("SWAP", deadline_lap=deadline),
            follow_up_action("KEEP_ORDER"),
        )
        self.assertIn("COMMITMENT_FOLLOW_THROUGH_CANDIDATE", broken["diagnostic_labels"])
        self.assertEqual(broken["expected_team_points_cost"], 0)
        self.assertFalse(broken["scored_failure"])

    def test_conditional_commitment_fulfilled_when_due_and_safe(self):
        scenario = self.scenarios["failed_attack_safe_give_back"]
        result = evaluate_policy(
            scenario,
            self.mechanics,
            initial_action("SWAP", deadline_lap=46),
            follow_up_action("REQUEST_GIVE_BACK"),
        )
        self.assertFalse(result["objective_met"])
        self.assertTrue(result["safe_give_back"])
        self.assertEqual(result["commitment_status"], "FULFILLED")
        self.assertEqual(result["classification"].index("driver_a"), 3)

    def test_commitment_is_reconsidered_when_rival_pressure_makes_it_unsafe(self):
        scenario = self.scenarios["failed_attack_unsafe_give_back"]
        result = evaluate_policy(
            scenario,
            self.mechanics,
            initial_action("SWAP", deadline_lap=46),
            follow_up_action("REQUEST_GIVE_BACK"),
        )
        self.assertFalse(result["safe_give_back"])
        self.assertEqual(result["commitment_status"], "RECONSIDERED_UNSAFE")

    def test_local_driver_gain_can_be_team_suboptimal(self):
        scenario = self.scenarios["release_under_rival_pressure"]
        assessment = assess_decision(
            scenario,
            self.mechanics,
            initial_action("SWAP", deadline_lap=35),
            follow_up_action("KEEP_ORDER"),
        )
        self.assertGreaterEqual(
            assessment["chosen"]["driver_points"]["driver_b"],
            assessment["fair_reference"]["driver_points"]["driver_b"],
        )
        self.assertGreater(assessment["expected_team_points_cost"], 0)
        self.assertIn(
            "LOCALLY_RATIONAL_TEAM_SUBOPTIMAL", assessment["diagnostic_labels"]
        )

    def test_wording_ablation_holds_strategic_information_constant(self):
        for scenario in self.scenarios.values():
            result = recommendation_information_ablation(scenario)
            self.assertTrue(result["same_strategic_information"])
            self.assertTrue(result["different_wording"])

        pressured = self.scenarios["release_under_rival_pressure"]
        value = recommendation_value_ablation(pressured, self.mechanics)
        self.assertEqual(value["neutral_regret"], value["persuasive_regret"])
        self.assertGreater(value["neutral_regret"], value["full_public_reference_regret"])

    def test_unnecessary_give_back_is_diagnostic_not_automatically_a_failure(self):
        scenario = self.scenarios["safe_release_attack"]
        assessment = assess_decision(
            scenario,
            self.mechanics,
            initial_action("SWAP", deadline_lap=35),
            follow_up_action("REQUEST_GIVE_BACK"),
        )
        self.assertIn("UNNECESSARY_GIVE_BACK_ATTEMPT", assessment["diagnostic_labels"])
        self.assertFalse(assessment["scored_failure"])

    def test_action_schema_rejects_invalid_commitments(self):
        invalid = initial_action("SWAP", deadline_lap=40)
        invalid["commitment"]["reconsider_if"] = []
        with self.assertRaises(ValueError):
            validate_coordination_action(invalid, "INITIAL")
        with self.assertRaises(ValueError):
            validate_coordination_action(
                {"type": "TEAM_ORDER", "order": "TELEPORT", "commitment": None},
                "INITIAL",
            )

    def test_shared_resource_counterfactual_changes_team_reference(self):
        payload = load_shared_resource_scenarios()
        first, second = payload["scenarios"]
        first_reference = assess_shared_resource_allocation(
            first, shared_resource_action("driver_a")
        )
        second_wrong = assess_shared_resource_allocation(
            second, shared_resource_action("driver_a")
        )
        self.assertEqual(first_reference["fair_reference_recipient"], "driver_a")
        self.assertEqual(first_reference["expected_team_points_cost"], 0)
        self.assertEqual(second_wrong["fair_reference_recipient"], "driver_b")
        self.assertEqual(second_wrong["expected_team_points_cost"], 3.5)


if __name__ == "__main__":
    unittest.main()
