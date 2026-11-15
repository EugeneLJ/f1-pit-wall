import copy
import json
import math
import unittest

from c5_helpers import action, assert_no_secrets, public_state, qualifying_state, zero_action
from track_c import c5


class PracticeDeterminismTests(unittest.TestCase):
    def test_replay_is_exact_and_does_not_mutate_inputs_or_share_output_aliases(self):
        state = public_state()
        decision = action()
        original_state = copy.deepcopy(state)
        original_action = copy.deepcopy(decision)
        first = c5.simulate_practice(state, decision, 987654321)
        second = c5.simulate_practice(state, decision, 987654321)
        self.assertEqual(first, second)
        self.assertEqual(state, original_state)
        self.assertEqual(decision, original_action)
        self.assertIsNot(first["state"], second["state"])
        first["state"]["practice"]["laps_budget_remaining"]["driver_a"] = -1
        self.assertNotEqual(first["state"]["practice"], second["state"]["practice"])

    def test_driver_and_other_team_noise_streams_are_action_independent(self):
        state = public_state()
        base = c5.simulate_practice(state, action(), 24680)
        changed_teammate = c5.simulate_practice(
            state, action(program_b="LONG_RUN", setup_b="low_drag", laps_b=12), 24680)
        other = public_state(team="Other")
        c5.simulate_practice(other, action(setup_a="balanced", setup_b="balanced"), 24680)
        c5.keyed_normal(1, "many unrelated calls")
        replay = c5.simulate_practice(state, action(), 24680)
        self.assertEqual(base["measurements"][0], changed_teammate["measurements"][0])
        self.assertEqual(base, replay)
        self.assertNotEqual(base["measurements"][0], changed_teammate["measurements"][1])

    def test_absolute_lap_stream_continues_across_sessions(self):
        state = public_state()
        first = c5.simulate_practice(state, action(laps_a=4, laps_b=0), 1122)
        second = c5.simulate_practice(first["state"], action(laps_a=4, laps_b=0), 1122)
        self.assertEqual(first["measurements"][0]["lap_index_start"], 0)
        self.assertEqual(second["measurements"][0]["lap_index_start"], 4)
        self.assertNotEqual(first["measurements"][0]["sample_mean"], second["measurements"][0]["sample_mean"])

    def test_qualifying_run_noise_does_not_change_with_action_iteration_order(self):
        state = qualifying_state(2024)
        actions = {
            "Orion": {
                "type": "QUALIFYING",
                "driver_a": {"setup_id": "balanced", "run_plan": "ONE_RUN"},
                "driver_b": {"setup_id": "high_downforce", "run_plan": "TWO_RUN"},
            },
            "Apex": {
                "type": "QUALIFYING",
                "driver_a": {"setup_id": "low_drag", "run_plan": "ONE_RUN"},
                "driver_b": {"setup_id": "high_downforce", "run_plan": "TWO_RUN"},
            },
        }
        forward = c5.qualifying(state, actions, 2024)
        reverse = c5.qualifying(state, dict(reversed(list(actions.items()))), 2024)
        self.assertEqual(forward, reverse)
        self.assertEqual(len(forward["order"]), len(set(forward["order"])))
        self.assertEqual(set(forward["order"]), set(state["field"]))


class PracticeInformationTests(unittest.TestCase):
    def test_more_laps_narrow_ci_over_many_keys(self):
        for key in range(64):
            state = public_state()
            initial = state["practice"]["known_setup_estimates"]["low_drag"][
                "long_run_pace_offset_sec_per_lap"]["ci95"]
            first = c5.simulate_practice(state, action(laps_a=4, laps_b=0), key)
            four = first["state"]["practice"]["known_setup_estimates"]["low_drag"][
                "long_run_pace_offset_sec_per_lap"]
            second = c5.simulate_practice(first["state"], action(laps_a=8, laps_b=0), key)
            twelve = second["state"]["practice"]["known_setup_estimates"]["low_drag"][
                "long_run_pace_offset_sec_per_lap"]
            self.assertEqual(four["laps_observed"], 4)
            self.assertEqual(twelve["laps_observed"], 12)
            self.assertLess(twelve["ci95"], four["ci95"])
            self.assertLess(four["ci95"], initial)

    def test_long_run_only_updates_tyre_information_and_preserves_tradeoff(self):
        state = public_state()
        before = copy.deepcopy(state["practice"]["known_setup_estimates"])
        result = c5.simulate_practice(
            state, action(program_a="LONG_RUN", program_b="LONG_RUN", laps_a=6, laps_b=6), 400)
        self.assertEqual(result["state"]["practice"]["known_setup_estimates"], before)
        self.assertEqual(result["state"]["practice"]["tyre_wear_estimates"]["low_drag"]["laps_observed"], 6)
        self.assertEqual(result["state"]["practice"]["tyre_wear_estimates"]["high_downforce"]["laps_observed"], 6)
        self.assertEqual(result["state"]["practice"]["laps_budget_remaining"],
                         {"driver_a": 18, "driver_b": 18})

    def test_sample_error_and_posterior_ci_follow_published_precision(self):
        result = c5.simulate_practice(
            public_state(), action(laps_a=16, laps_b=0, program_a="QUALI_SIM"), 99)
        row = result["measurements"][0]
        self.assertEqual(row["observation_sd_per_lap"], 0.08)
        self.assertEqual(row["sample_standard_error"], 0.02)
        self.assertEqual(row["lap_index_start"], 0)
        self.assertEqual(row["laps"], 16)

    def test_exact_budget_and_zero_laps_never_go_negative(self):
        first = c5.simulate_practice(public_state(), action(laps_a=24, laps_b=24), 17)
        second = c5.simulate_practice(first["state"], zero_action(), 17)
        self.assertEqual(second["state"]["practice"]["laps_budget_remaining"],
                         {"driver_a": 0, "driver_b": 0})
        self.assertEqual(second["measurements"], [])
        self.assertEqual(second["state"]["phase"], "QUALIFYING")


class PublicObservationAndValidationTests(unittest.TestCase):
    def test_public_observation_has_estimates_noise_and_no_private_content(self):
        state = public_state()
        result = c5.simulate_practice(state, action(), 111)
        phase = c5.public_observation(result["state"])
        self.assertEqual(phase["type"], "PRACTICE")
        practice = phase["practice"]
        self.assertEqual(practice["laps_budget_remaining"], {"driver_a": 20, "driver_b": 20})
        self.assertIn("noise_model", practice)
        self.assertIn("mean", practice["known_setup_estimates"]["low_drag"]["long_run_pace_offset_sec_per_lap"])
        self.assertIn("ci95", practice["tyre_wear_estimates"]["low_drag"])
        for document in (state, result, phase, qualifying_state(111), c5.public_observation(qualifying_state(111))):
            assert_no_secrets(self, document)
            self.assertNotIn("987654321012345678901234567890", json.dumps(document))

    def test_injected_private_state_is_rejected(self):
        for key in ("hidden_true_effects", "rng_key", "future_draws"):
            state = public_state()
            state[key] = {"low_drag": 123}
            with self.assertRaisesRegex(ValueError, "private field"):
                c5.public_observation(state)

    def test_illegal_program_setup_laps_and_action_shape_are_atomic(self):
        state = public_state()
        original = copy.deepcopy(state)
        bad = [
            action(program_a="SPRINT"),
            action(setup_a="not-an-option"),
            action(laps_a=-1),
            action(laps_a=True),
            action(laps_a=1.5),
            action(laps_a=25),
            {"type": "PRACTICE", "driver_a": {}},
            {"type": "PRACTICE", "driver_a": {"program": "SETUP_TEST", "setup_id": "low_drag", "laps": 1},
             "driver_b": {"program": "SETUP_TEST", "setup_id": "low_drag", "laps": 1, "extra": 1}},
        ]
        for decision in bad:
            with self.subTest(decision=decision):
                with self.assertRaises(ValueError):
                    c5.simulate_practice(state, decision, 1)
                self.assertEqual(state, original)

    def test_budget_and_history_tampering_is_rejected(self):
        state = public_state()
        state["practice"]["laps_budget_remaining"]["driver_a"] -= 1
        with self.assertRaisesRegex(ValueError, "inconsistent with history"):
            c5.public_observation(state)
        result = c5.simulate_practice(public_state(), action(), 1)
        broken = copy.deepcopy(result["state"])
        broken["practice"]["history"][0]["actions"][0]["laps"] += 1
        with self.assertRaises(ValueError):
            c5.public_observation(broken)

    def test_duplicate_measurement_cannot_replace_teammate_evidence(self):
        result = c5.simulate_practice(public_state(), action(), 1)
        broken = copy.deepcopy(result["state"])
        broken["practice"]["history"][0]["measurements"][1] = \
            copy.deepcopy(broken["practice"]["history"][0]["measurements"][0])
        with self.assertRaisesRegex(ValueError, "exactly one measurement"):
            c5.public_observation(broken)

    def test_third_session_and_bad_rng_keys_are_rejected(self):
        complete = qualifying_state(77)
        with self.assertRaisesRegex(ValueError, "PRACTICE phase"):
            c5.simulate_practice(complete, zero_action(), 77)
        for key in (True, -1, 2**256, "not-a-number"):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    c5.simulate_practice(public_state(), zero_action(), key)

    def test_reference_actions_validate_and_never_exceed_batch_or_budget(self):
        state = public_state()
        action_one = c5.practice_reference(state)
        first = c5.simulate_practice(state, action_one, 1)
        action_two = c5.practice_reference(first["state"])
        second = c5.simulate_practice(first["state"], action_two, 1)
        self.assertEqual(second["state"]["phase"], "QUALIFYING")
        self.assertLessEqual(action_one["driver_a"]["laps"], 6)
        self.assertLessEqual(action_two["driver_a"]["laps"], 6)
        for remaining in second["state"]["practice"]["laps_budget_remaining"].values():
            self.assertGreaterEqual(remaining, 0)


if __name__ == "__main__":
    unittest.main()
