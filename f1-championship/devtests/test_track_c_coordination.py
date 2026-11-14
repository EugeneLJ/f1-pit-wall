import copy
import json
import unittest
from pathlib import Path

from track_c.coordination import (
    ALIGNED,
    CONFLICTING,
    MISCALIBRATED_CONFIDENCE,
    NO_ENGINEER,
    CoordinationRound,
    DeterministicMockEngineer,
    RecommendationReplay,
    build_coordination_observation,
    build_engineer_observation,
    load_team_order_scenarios,
    validate_recommendation,
    validate_team_order_action,
)


def public_chief_observation():
    return {
        "schema_version": 1,
        "decision_type": "RACE_STRATEGY",
        "current_track": {
            "track_id": "synthetic_round_03",
            "name": "Synthetic Round 3",
            "power_unit_stress": 0.72,
            "overtaking_difficulty": 0.64,
            "tyre_degradation": 0.81,
        },
        "race_progress": {
            "lap": 12,
            "laps_total": 20,
            "decision_index": 2,
            "decision_count": 3,
            "track_status": "GREEN",
            "drivers": {
                "driver_a": {
                    "position": 2,
                    "compound": "SOFT",
                    "tyre_age": 12,
                    "elapsed": 721.125,
                },
                "driver_b": {
                    "position": 4,
                    "compound": "MEDIUM",
                    "tyre_age": 8,
                    "elapsed": 724.875,
                },
            },
            "classification": [
                {"position": 1, "driver": "Orion A", "team": "Orion", "gap": 0.0},
                {"position": 2, "driver": "Apex A", "team": "Apex", "gap": 1.2},
                {"position": 3, "driver": "Vela A", "team": "Vela", "gap": 2.1},
                {"position": 4, "driver": "Apex B", "team": "Apex", "gap": 3.7},
            ],
            "legal_actions": ["PIT", "STAY"],
        },
        "championship": {
            "race_index": 2,
            "driver_points": {"driver_a": 34, "driver_b": 27},
            "constructor_points": {"Apex": 61},
        },
    }


class EngineerObservationTests(unittest.TestCase):
    def test_observations_are_driver_local_and_exclude_teammate(self):
        chief = public_chief_observation()
        observation_a = build_engineer_observation(chief, "engineer_a")
        observation_b = build_engineer_observation(chief, "engineer_b")

        self.assertEqual(observation_a["assigned_driver"]["key"], "driver_a")
        self.assertEqual(observation_b["assigned_driver"]["key"], "driver_b")
        self.assertEqual(observation_a["race_context"]["assigned_driver_state"]["elapsed"], 721.125)
        self.assertEqual(observation_b["race_context"]["assigned_driver_state"]["elapsed"], 724.875)

        serialized_a = json.dumps(observation_a, sort_keys=True)
        serialized_b = json.dumps(observation_b, sort_keys=True)
        self.assertNotIn("Apex B", serialized_a)
        self.assertNotIn("Apex A", serialized_b)
        self.assertNotIn("724.875", serialized_a)
        self.assertNotIn("721.125", serialized_b)
        self.assertIn("Orion A", serialized_a)
        self.assertIn("Vela A", serialized_b)
        self.assertFalse(observation_a["information_boundary"]["future_events_visible"])

    def test_hidden_state_is_rejected_even_when_nested(self):
        for key, value in (
            ("seed", 91),
            ("events", [{"lap": 14, "type": "SC"}]),
            ("future_track_status", "SC"),
        ):
            with self.subTest(key=key):
                chief = public_chief_observation()
                chief["race_progress"][key] = value
                with self.assertRaisesRegex(ValueError, "hidden fields are not allowed"):
                    build_engineer_observation(chief, "engineer_a")


class RecommendationTests(unittest.TestCase):
    def setUp(self):
        chief = public_chief_observation()
        self.observation_a = build_engineer_observation(chief, "engineer_a")

    def test_mock_recommendation_schema_and_validation(self):
        recommendation = DeterministicMockEngineer("engineer_a").recommend(self.observation_a, ALIGNED)
        validate_recommendation(recommendation, self.observation_a)
        self.assertEqual(recommendation["proposed_action"]["type"], "RACE_STRATEGY")
        self.assertTrue(recommendation["evidence"])
        self.assertGreater(recommendation["expected_benefit"]["value"], 0)

    def test_invalid_confidence_and_extra_fields_are_rejected(self):
        recommendation = DeterministicMockEngineer("engineer_a").recommend(self.observation_a, ALIGNED)
        invalid_confidence = copy.deepcopy(recommendation)
        invalid_confidence["confidence"] = 1.01
        with self.assertRaises(ValueError):
            validate_recommendation(invalid_confidence, self.observation_a)

        extra_field = copy.deepcopy(recommendation)
        extra_field["hidden_score"] = 100
        with self.assertRaises(ValueError):
            validate_recommendation(extra_field, self.observation_a)

    def test_coordination_conditions_are_explicit(self):
        chief = public_chief_observation()
        no_engineer = build_coordination_observation(chief, NO_ENGINEER)
        aligned = build_coordination_observation(chief, ALIGNED)
        conflicting = build_coordination_observation(chief, CONFLICTING)
        miscalibrated = build_coordination_observation(chief, MISCALIBRATED_CONFIDENCE)

        self.assertEqual(no_engineer["recommendations"], [])
        self.assertEqual(
            {item["proposed_action"]["choice"] for item in aligned["recommendations"]},
            {"STAY"},
        )
        self.assertEqual(
            [item["proposed_action"]["choice"] for item in conflicting["recommendations"]],
            ["PIT", "STAY"],
        )
        self.assertTrue(all(item["confidence"] == 0.99 for item in miscalibrated["recommendations"]))
        self.assertTrue(
            all(
                item["calibration"] == "intentionally_overconfident_fixture"
                for item in miscalibrated["recommendations"]
            )
        )

    def test_exact_observation_replay_is_deterministic(self):
        provider = DeterministicMockEngineer("engineer_a")
        replay = RecommendationReplay("engineer_a")
        recommendation = provider.recommend(self.observation_a, CONFLICTING)
        replay.record(self.observation_a, recommendation)

        first = replay.recommend(self.observation_a, CONFLICTING)
        second = replay.recommend(copy.deepcopy(self.observation_a), ALIGNED)
        self.assertEqual(first, recommendation)
        self.assertEqual(first, second)
        self.assertIsNot(first, second)

        changed = copy.deepcopy(self.observation_a)
        changed["race_context"]["assigned_driver_state"]["tyre_age"] += 1
        with self.assertRaises(ValueError):
            replay.recommend(changed, CONFLICTING)


class ChiefAuthorityTests(unittest.TestCase):
    def test_conflicting_recommendations_can_be_accepted_or_rejected(self):
        bundle = build_coordination_observation(public_chief_observation(), CONFLICTING)
        coordination = CoordinationRound(bundle)
        decision = coordination.chief_decide(
            {"type": "RACE_STRATEGY", "driver_a": "PIT", "driver_b": "PIT"},
            "Accept A's pit case and reject B's local stay recommendation.",
        )
        outcomes = decision["recommendation_accepted"]
        self.assertEqual(outcomes, {"engineer_a": True, "engineer_b": False})

    def test_only_chief_decision_can_reach_execution_callback(self):
        bundle = build_coordination_observation(public_chief_observation(), ALIGNED)
        coordination = CoordinationRound(bundle)
        submitted = []

        with self.assertRaises(PermissionError):
            coordination.execute(submitted.append)
        self.assertEqual(submitted, [])

        action = {"type": "RACE_STRATEGY", "driver_a": "STAY", "driver_b": "STAY"}
        coordination.chief_decide(action, "Both local recommendations align with the team action.")
        coordination.execute(submitted.append)
        self.assertEqual(submitted, [action])
        with self.assertRaises(ValueError):
            coordination.execute(submitted.append)

    def test_recommendations_do_not_mutate_public_race_state(self):
        chief = public_chief_observation()
        before = copy.deepcopy(chief)
        build_coordination_observation(chief, CONFLICTING)
        self.assertEqual(chief, before)


class FutureTeamOrderSchemaTests(unittest.TestCase):
    def test_position_swap_and_conditional_give_back_fixtures_validate(self):
        fixture_path = Path(__file__).parents[1] / "track_c" / "fixtures" / "team_order_scenarios.json"
        scenarios = load_team_order_scenarios(fixture_path)
        self.assertEqual(len(scenarios), 2)
        for scenario in scenarios:
            validate_team_order_action(scenario["proposed_action"])
        self.assertEqual(scenarios[0]["proposed_action"]["order"], "SWAP")
        self.assertEqual(
            scenarios[1]["proposed_action"]["give_back"]["condition"],
            "IF_NO_POSITION_GAIN",
        )


if __name__ == "__main__":
    unittest.main()
