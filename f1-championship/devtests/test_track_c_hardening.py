import unittest

from track_c.benchmark_hardening import (
    SequentialCoordinationEpisode,
    build_failure_record,
    decision_sensitivity,
    generate_design_grid,
    summarize_generated_scenarios,
)
from track_c.scenario_evaluation import (
    follow_up_action,
    initial_action,
    load_coordination_scenarios,
)


class GeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        payload = load_coordination_scenarios()
        cls.mechanics = payload["mechanics"]
        cls.fixtures = {item["id"]: item for item in payload["scenarios"]}

    def test_declared_grid_is_generated_before_outcome_classification(self):
        scenarios = generate_design_grid()
        self.assertEqual(len(scenarios), 5832)
        self.assertEqual(len({item["id"] for item in scenarios}), 5832)
        self.assertTrue(
            all(item["pair_id"] == "generated_design_grid" for item in scenarios)
        )

    def test_full_grid_distribution_is_reproducible_and_not_real_prevalence(self):
        summary = summarize_generated_scenarios(generate_design_grid(), self.mechanics)
        self.assertTrue(summary["not_real_world_prevalence"])
        self.assertEqual(
            summary["reference_action_counts"],
            {"DEFENSIVE_BUFFER": 1133, "HOLD": 3529, "SWAP": 1170},
        )
        self.assertEqual(summary["category_counts"]["NEAR_TIE"], 3692)
        self.assertEqual(summary["category_counts"]["GIVE_BACK_TEAM_BENEFICIAL"], 0)
        self.assertEqual(
            summary["category_counts"]["GIVE_BACK_DRIVER_BENEFICIAL_TEAM_NEUTRAL"],
            2113,
        )
        self.assertEqual(
            summary["deterministic_regret_distribution"],
            {"minimum": 1, "median": 2, "p95": 3, "maximum": 3},
        )
        self.assertIsNone(summary["expected_regret_distribution"])

    def test_failure_record_separates_observation_reference_regret_and_hypothesis(self):
        scenario = self.fixtures["safe_release_attack"]
        action = initial_action("HOLD")
        unexplained = build_failure_record(scenario, self.mechanics, action)
        attributed = build_failure_record(
            scenario, self.mechanics, action, followed_local_recommendation=True
        )
        self.assertEqual(unexplained["observed_action"], action)
        self.assertEqual(
            unexplained["equal_information_reference_action"]["order"], "SWAP"
        )
        self.assertEqual(unexplained["deterministic_points_regret"], 3)
        self.assertIsNone(unexplained["expected_points_regret"])
        self.assertEqual(
            unexplained["diagnostic_hypothesis"], "unexplained_team_suboptimal_decision"
        )
        self.assertEqual(
            attributed["diagnostic_hypothesis"],
            "possible_partial_evidence_integration_failure",
        )
        self.assertTrue(attributed["evidence_supporting_hypothesis"])

    def test_sensitivity_is_counterfactual_and_deterministic(self):
        scenario = self.fixtures["release_under_rival_pressure"]
        first = decision_sensitivity(scenario, self.mechanics)
        second = decision_sensitivity(scenario, self.mechanics)
        self.assertEqual(first, second)
        self.assertEqual(first["perturbations_tested"], 12)
        self.assertGreaterEqual(first["reversal_rate"], 0.0)
        self.assertLessEqual(first["reversal_rate"], 1.0)


class SequentialCommitmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        payload = load_coordination_scenarios()
        cls.mechanics = payload["mechanics"]
        cls.fixtures = {item["id"]: item for item in payload["scenarios"]}

    def test_observation_has_current_state_but_no_future_event_or_seed(self):
        episode = SequentialCoordinationEpisode(
            self.fixtures["failed_attack_safe_give_back"], self.mechanics
        )
        observation = episode.observe()
        self.assertNotIn("future_events", observation)
        self.assertNotIn("seed", observation)
        self.assertIsNone(observation["commitment"])

    def test_failed_before_deadline_then_deadline_expired_and_fulfilled(self):
        episode = SequentialCoordinationEpisode(
            self.fixtures["failed_attack_safe_give_back"], self.mechanics
        )
        episode.submit_initial(initial_action("SWAP", deadline_lap=46))
        first = episode.advance_one_lap()
        self.assertEqual(
            first["commitment"]["status"], "OBJECTIVE_FAILED_BEFORE_DEADLINE"
        )
        for _ in range(3):
            final = episode.advance_one_lap()
        self.assertEqual(final["commitment"]["status"], "DEADLINE_EXPIRED")
        self.assertEqual(final["commitment"]["feasibility"], "FEASIBLE")
        self.assertEqual(
            final["commitment"]["benefit_scope"],
            "driver_a_order_restoration_team_points_unproven",
        )
        resolved = episode.resolve_commitment(follow_up_action("REQUEST_GIVE_BACK"))
        self.assertEqual(resolved["commitment"]["status"], "COMMITMENT_FULFILLED")

    def test_feasible_commitment_can_be_violated(self):
        episode = SequentialCoordinationEpisode(
            self.fixtures["failed_attack_safe_give_back"], self.mechanics
        )
        episode.submit_initial(initial_action("SWAP", deadline_lap=46))
        for _ in range(4):
            episode.advance_one_lap()
        result = episode.resolve_commitment(follow_up_action("KEEP_ORDER"))
        self.assertEqual(
            result["commitment"]["status"],
            "COMMITMENT_VIOLATED_WHILE_BENEFICIAL_AND_FEASIBLE",
        )

    def test_unsafe_commitment_is_rationally_reconsidered_with_reason(self):
        episode = SequentialCoordinationEpisode(
            self.fixtures["failed_attack_unsafe_give_back"], self.mechanics
        )
        episode.submit_initial(initial_action("SWAP", deadline_lap=46))
        for _ in range(4):
            episode.advance_one_lap()
        result = episode.resolve_commitment(follow_up_action("REQUEST_GIVE_BACK"))
        self.assertEqual(result["commitment"]["status"], "RATIONALLY_RECONSIDERED")
        self.assertEqual(result["commitment"]["reconsideration_reason"], "rival_proximity")

    def test_objective_achievement_lapses_give_back_condition(self):
        episode = SequentialCoordinationEpisode(
            self.fixtures["safe_release_attack"], self.mechanics
        )
        episode.submit_initial(initial_action("SWAP", deadline_lap=35))
        for _ in range(5):
            observation = episode.advance_one_lap()
        self.assertEqual(observation["commitment"]["status"], "OBJECTIVE_ACHIEVED")
        resolved = episode.resolve_commitment(follow_up_action("REQUEST_GIVE_BACK"))
        self.assertEqual(resolved["commitment"]["status"], "CONDITION_LAPSED")


if __name__ == "__main__":
    unittest.main()
