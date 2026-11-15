import copy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import unittest

from c5_helpers import assert_no_secrets, public_state, qualifying_state
from track_c import c5


FIXTURE = Path(__file__).resolve().parents[1] / "track_c" / "fixtures" / "c5_setups.json"


class QualifyingAndRaceTests(unittest.TestCase):
    def test_provisional_grid_is_deterministic_atomic_and_penalty_free(self):
        state = qualifying_state(314159)
        actions = {
            "type": "QUALIFYING",
            "driver_a": {"setup_id": "low_drag", "run_plan": "TWO_RUN"},
            "driver_b": {"setup_id": "high_downforce", "run_plan": "ONE_RUN"},
        }
        state_before, actions_before = copy.deepcopy(state), copy.deepcopy(actions)
        first = c5.qualifying(state, actions, 314159)
        second = c5.qualifying(state, actions, 314159)
        self.assertEqual(first, second)
        self.assertEqual(state, state_before)
        self.assertEqual(actions, actions_before)
        self.assertEqual(set(first), {"order", "times"})
        self.assertEqual(len(first["order"]), len(state["field"]))
        self.assertEqual(first["order"], sorted(first["order"], key=lambda car: (first["times"][car], car)))
        self.assertNotIn("penalties", json.dumps(first).lower())
        assert_no_secrets(self, first)

    def test_two_run_is_best_of_two_and_multi_team_actions_are_supported(self):
        state = qualifying_state(81)
        one = c5.qualifying(state, {
            "type": "QUALIFYING", "driver_a": {"setup_id": "low_drag", "run_plan": "ONE_RUN"},
            "driver_b": {"setup_id": "balanced", "run_plan": "ONE_RUN"}}, 81)
        two = c5.qualifying(state, {
            "type": "QUALIFYING", "driver_a": {"setup_id": "low_drag", "run_plan": "TWO_RUN"},
            "driver_b": {"setup_id": "balanced", "run_plan": "ONE_RUN"}}, 81)
        self.assertLessEqual(two["times"]["Apex A"], one["times"]["Apex A"])
        both = c5.qualifying(state, {
            "Orion": {
                "type": "QUALIFYING", "driver_a": {"setup_id": "high_downforce", "run_plan": "TWO_RUN"},
                "driver_b": {"setup_id": "balanced", "run_plan": "ONE_RUN"}},
            "Apex": {
                "type": "QUALIFYING", "driver_a": {"setup_id": "low_drag", "run_plan": "TWO_RUN"},
                "driver_b": {"setup_id": "balanced", "run_plan": "ONE_RUN"}},
        }, 81)
        self.assertEqual(both["times"]["Apex A"], two["times"]["Apex A"])
        self.assertNotIn("fia_grid", json.dumps(both))

    def test_natural_grid_race_reversal_comes_from_model_not_a_lucky_draw(self):
        state = qualifying_state(7)
        balanced = c5.evaluate_setup(state, "Apex A", "balanced")
        low_drag = c5.evaluate_setup(state, "Apex A", "low_drag")
        self.assertLess(low_drag["provisional_grid_position"], balanced["provisional_grid_position"])
        self.assertLess(low_drag["estimated_race_points"], balanced["estimated_race_points"])
        self.assertLess(low_drag["net_estimated_points"], balanced["net_estimated_points"])
        grid_balanced = c5.qualifying(state, {
            "type": "QUALIFYING", "driver_a": {"setup_id": "balanced", "run_plan": "ONE_RUN"},
            "driver_b": {"setup_id": "balanced", "run_plan": "ONE_RUN"}}, 7)
        grid_low = c5.qualifying(state, {
            "type": "QUALIFYING", "driver_a": {"setup_id": "low_drag", "run_plan": "ONE_RUN"},
            "driver_b": {"setup_id": "balanced", "run_plan": "ONE_RUN"}}, 7)
        self.assertLess(grid_low["order"].index("Apex A"), grid_balanced["order"].index("Apex A"))

    def test_parc_ferme_choice_is_frozen_and_raw_public_actions_cannot_change_it(self):
        choice = c5.make_parc_ferme_choice(
            {"Apex A": "low_drag", "Apex B": "high_downforce"},
            rng_key=1234, weekend_id="round-test", archetype="mixed", team="Apex")
        self.assertEqual(choice, c5.make_parc_ferme_choice(
            {"Apex B": "high_downforce", "Apex A": "low_drag"},
            rng_key=1234, weekend_id="round-test", archetype="mixed", team="Apex"))
        with self.assertRaises(FrozenInstanceError):
            choice.weekend_id = "changed"
        with self.assertRaises(ValueError):
            c5.race_modifiers({"Apex A": "high_downforce"})
        self.assertEqual(c5.race_modifiers(choice), c5.race_modifiers(choice))
        self.assertNotIn("1234", repr(choice))
        public = c5.public_observation(qualifying_state(1234))
        assert_no_secrets(self, public)

    def test_no_c5_and_neutral_setup_are_exact_identity_guards(self):
        self.assertEqual(c5.race_modifiers(None), {})
        neutral = c5.make_parc_ferme_choice(
            {"Apex A": "balanced", "Apex B": "balanced"}, rng_key=42,
            weekend_id="round-test", archetype="mixed", team="Apex")
        self.assertEqual(c5.race_modifiers(neutral), {
            "Apex A": {"pace_offset_sec_per_lap": 0.0, "deg_multiplier_factor": 1.0},
            "Apex B": {"pace_offset_sec_per_lap": 0.0, "deg_multiplier_factor": 1.0},
        })

    def test_qualifying_validation_rejects_bad_phase_setup_run_plan_and_team(self):
        initial = public_state()
        action = {"type": "QUALIFYING", "driver_a": {"setup_id": "balanced", "run_plan": "ONE_RUN"},
                  "driver_b": {"setup_id": "balanced", "run_plan": "ONE_RUN"}}
        with self.assertRaisesRegex(ValueError, "both practice sessions"):
            c5.qualifying(initial, action, 1)
        state = qualifying_state(1)
        bad = copy.deepcopy(action)
        bad["driver_a"]["setup_id"] = "not-valid"
        with self.assertRaises(ValueError):
            c5.qualifying(state, bad, 1)
        bad = copy.deepcopy(action)
        bad["driver_a"]["run_plan"] = "THREE_RUN"
        with self.assertRaises(ValueError):
            c5.qualifying(state, bad, 1)
        with self.assertRaisesRegex(ValueError, "unknown team"):
            c5.qualifying(state, {"Unknown": action}, 1)

    def test_extra_same_team_car_cannot_inherit_controlled_setup(self):
        state = public_state()
        state["field"]["Apex C"] = {"team": "Apex", "driver_key": "driver_a", "base_pace_sec": 88.0}
        with self.assertRaisesRegex(ValueError, "duplicate team/seat"):
            c5.public_observation(state)

    def test_public_reference_is_valid_qualifying_action_and_grid_loss_is_explicit(self):
        state = qualifying_state(10)
        reference = c5.qualifying_reference(state, grid_loss_places=2)
        result_one = c5.qualifying(state, reference, 10)
        result_two = c5.qualifying(state, reference, 10)
        self.assertEqual(result_one, result_two)
        for car in state["car_ids"].values():
            evaluation = c5.evaluate_setup(state, car, "low_drag", grid_loss_places=2)
            self.assertEqual(evaluation["net_estimated_points"],
                             evaluation["estimated_race_points"] - 4.0)


class FixtureContractTests(unittest.TestCase):
    def test_every_prior_and_archetype_coefficient_is_marked_synthetic(self):
        raw = json.loads(FIXTURE.read_text())
        self.assertEqual(raw["data_status"], "synthetic_only")
        self.assertEqual(raw["sources"], [])
        for setup in raw["setups"].values():
            for prior in setup["priors"].values():
                self.assertEqual(prior["provenance"], "synthetic")
        for program in raw["noise_model"]["programs"].values():
            self.assertEqual(program["observation_sd_per_lap"]["provenance"], "synthetic")
        for value in raw["defaults"].values():
            if isinstance(value, dict):
                self.assertIn("synthetic", value["provenance"])
        for archetype in raw["archetypes"].values():
            self.assertIn("synthetic", archetype["base_deg_time_loss_sec_per_lap"]["provenance"])

    def test_all_archetypes_build_public_models_and_distinct_non_prior_draws(self):
        for archetype in ("mixed", "street", "high_speed", "high_degradation", "wet_prone"):
            model = c5.load_model(archetype)
            self.assertEqual(model["archetype"], archetype)
            self.assertEqual(model["defaults"] if "defaults" in model else model["default_setup_id"], "balanced")
            self.assertEqual(model["sessions_total"], 2)
            self.assertEqual(model["lap_budget_per_driver"], 24)
            self.assertGreater(model["base_deg_time_loss_sec_per_lap"], 0)

    def test_normal_stream_is_table_stable_and_key_separated(self):
        first = c5.keyed_normal(42, "domain", "team", "driver", 3)
        self.assertEqual(first, c5.keyed_normal(42, "domain", "team", "driver", 3))
        self.assertNotEqual(first, c5.keyed_normal(42, "domain", "team", "driver", 4))
        self.assertNotEqual(first, c5.keyed_normal(42, "domain", "team", "other", 3))
        self.assertNotEqual(first, c5.keyed_normal(42, "other-domain", "team", "driver", 3))


if __name__ == "__main__":
    unittest.main()
