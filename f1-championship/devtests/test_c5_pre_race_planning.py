import copy
import json
import unittest
from pathlib import Path

from track_c.pre_race_evaluation import (
    paired_reversal,
    practice_test_information_value,
    qualifying_reference,
    setup_action_values,
)
from track_c.pre_race_planning import (
    COMPLETE,
    QUALIFYING,
    PreRaceConfig,
    PreRaceSession,
    trusted_replay,
)


class PracticeContractTests(unittest.TestCase):
    def test_seed_and_action_sequence_reproduce_trace(self):
        config = PreRaceConfig("BALANCED")
        actions = [
            {"type": "RUN_TEST", "test": "QUALIFYING_PACE_RUN"},
            {"type": "RUN_TEST", "test": "SETUP_COMPARISON", "driver": "driver_a"},
            {"type": "END_PRACTICE"},
            {"type": "SELECT_SETUPS", "driver_a": "BALANCED", "driver_b": "RACE_BIASED"},
        ]
        first = trusted_replay(config, 44, actions)
        second = trusted_replay(config, 44, actions)
        self.assertEqual(first.observation(), second.observation())
        self.assertEqual(first.replay_metadata(), second.replay_metadata())
        self.assertEqual(first.stage, COMPLETE)

    def test_unperformed_tests_and_latent_truth_are_not_observable(self):
        session = PreRaceSession(PreRaceConfig(), 1)
        before = session.observation()
        rendered = json.dumps(before, sort_keys=True)
        self.assertNotIn("potential_signals", rendered)
        self.assertNotIn('"truth"', rendered)
        self.assertNotIn("seed", rendered.lower())
        self.assertEqual(before["performed_tests"], [])
        session.submit({"type": "RUN_TEST", "test": "QUALIFYING_PACE_RUN"})
        after = session.observation()
        self.assertEqual(len(after["performed_tests"]), 1)
        self.assertNotIn("LONG_RUN_DEGRADATION", json.dumps(after["performed_tests"]))

    def test_budget_duplicate_and_action_validation(self):
        session = PreRaceSession(PreRaceConfig(practice_budget=2), 2)
        session.submit({"type": "RUN_TEST", "test": "LONG_RUN_DEGRADATION"})
        with self.assertRaisesRegex(ValueError, "already performed|insufficient"):
            session.submit({"type": "RUN_TEST", "test": "LONG_RUN_DEGRADATION"})
        with self.assertRaisesRegex(ValueError, "insufficient"):
            session.submit({"type": "RUN_TEST", "test": "QUALIFYING_PACE_RUN"})
        session.submit({"type": "END_PRACTICE"})
        self.assertEqual(session.stage, QUALIFYING)

    def test_information_value_is_public_and_includes_opportunity_cost(self):
        observation = PreRaceSession(PreRaceConfig("HIGH_DEGRADATION"), 3).observation()
        value = practice_test_information_value(observation, "LONG_RUN_DEGRADATION")
        self.assertFalse(value["uses_hidden_truth"])
        self.assertAlmostEqual(sum(value["signal_probabilities"].values()), 1.0)
        self.assertIn("net_cost", "expected_value_of_sample_information_net_cost")


class QualifyingContractTests(unittest.TestCase):
    def _qualify(self, track, setup_a, setup_b, seed=5):
        session = PreRaceSession(PreRaceConfig(track), seed)
        session.submit({"type": "END_PRACTICE"})
        return session.submit({"type": "SELECT_SETUPS", "driver_a": setup_a, "driver_b": setup_b})

    def test_grid_is_valid_and_modifier_is_explicitly_unapplied(self):
        result = self._qualify("BALANCED", "QUALIFYING_BIASED", "RACE_BIASED")
        self.assertEqual(len(result["provisional_grid"]), 8)
        self.assertEqual(len(set(result["provisional_grid"])), 8)
        modifier = result["race_setup_modifier"]
        self.assertTrue(modifier["parc_ferme_locked"])
        self.assertEqual(modifier["integration_status"], "NOT_APPLIED_TO_AUTHORITATIVE_ENGINE")
        self.assertIn("source_hash", modifier)

    def test_qualifying_and_race_setup_trade_off(self):
        qualifying = self._qualify("STREET", "QUALIFYING_BIASED", "QUALIFYING_BIASED")
        race = self._qualify("STREET", "RACE_BIASED", "RACE_BIASED")
        q_positions = [qualifying["provisional_grid"].index(name) for name in ("McLearn A", "McLearn B")]
        r_positions = [race["provisional_grid"].index(name) for name in ("McLearn A", "McLearn B")]
        self.assertLessEqual(sum(q_positions), sum(r_positions))
        q_pace = sum(v["pace_seconds_per_lap"] for v in
                     qualifying["race_setup_modifier"]["driver_modifiers"].values())
        r_pace = sum(v["pace_seconds_per_lap"] for v in
                     race["race_setup_modifier"]["driver_modifiers"].values())
        self.assertGreater(q_pace, r_pace)

    def test_reference_uses_only_public_beliefs_and_never_negative_regret(self):
        session = PreRaceSession(PreRaceConfig("BALANCED"), 9)
        session.submit({"type": "RUN_TEST", "test": "SETUP_COMPARISON", "driver": "driver_a"})
        session.submit({"type": "END_PRACTICE"})
        observation = session.observation()
        chosen = {"type": "SELECT_SETUPS", "driver_a": "QUALIFYING_BIASED", "driver_b": "BALANCED"}
        reference = qualifying_reference(observation, chosen)
        self.assertFalse(reference["uses_hidden_truth"])
        self.assertFalse(reference["uses_future_realization"])
        self.assertGreaterEqual(reference["expected_regret"], 0)
        self.assertEqual(len(setup_action_values(observation)), 9)

    def test_agent_independent_reversal_and_no_change_cases_exist(self):
        cases = [paired_reversal(PreRaceConfig("STREET"), seed,
                                 {"type": "RUN_TEST", "test": "LONG_RUN_DEGRADATION"})
                 for seed in range(30)]
        self.assertTrue(any(case["reversal"] for case in cases))
        self.assertTrue(any(not case["reversal"] for case in cases))
        self.assertTrue(all(not case["uses_agent_output_to_generate_case"] for case in cases))

    def test_representative_fixture_classifications_are_stable(self):
        path = Path(__file__).parents[1] / "track_c/fixtures/pre_race_scenarios.json"
        fixture = json.loads(path.read_text(encoding="utf-8"))
        for item in fixture["scenarios"]:
            result = paired_reversal(PreRaceConfig(item["track_archetype"]), item["trusted_seed"],
                                     item["test_action"])
            self.assertEqual(result["control_or_reversal"], item["expected_class"])

    def test_track_archetype_can_reverse_reference_setup(self):
        best = {}
        for track in ("STREET", "HIGH_DEGRADATION"):
            session = PreRaceSession(PreRaceConfig(track), 12)
            session.submit({"type": "END_PRACTICE"})
            values = setup_action_values(session.observation())
            best[track] = max(sorted(values), key=values.get)
        self.assertNotEqual(best["STREET"], best["HIGH_DEGRADATION"])


if __name__ == "__main__":
    unittest.main()
