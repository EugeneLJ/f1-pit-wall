import copy
import statistics
import unittest

from v22_helpers import assert_no_secrets
from track_c import v22
from track_c.v22 import weather as m7
from track_c.v22.common import reject_public_secrets


def forced_weather(state_name):
    model = m7.load_model()
    states = model["rain"]["states"]
    model["rain"]["initial_distribution"] = {kind: 1.0 if kind == state_name else 0.0 for kind in states}
    for kind in states:
        model["rain"]["transition"][kind] = [1.0 if target == state_name else 0.0 for target in states]
    return model


class WeatherProcessTests(unittest.TestCase):
    def test_seed_replay_and_action_independent_weather_paths(self):
        first = v22.weather_schedule(123, "race-0", 8)
        second = v22.weather_schedule(123, "race-0", 8)
        self.assertEqual(first, second)
        self.assertEqual(len(first["rain"]), 8)
        for wetness in first["wetness"]:
            self.assertGreaterEqual(wetness, 0.0)
            self.assertLessEqual(wetness, 1.0)
        one = m7.replay(123, ["STAY"] * 8)["state"]
        two = m7.replay(123, ["PIT_WET"] + ["STAY"] * 7)["state"]
        self.assertEqual(one["schedule"], two["schedule"])

    def test_forced_dry_drying_and_forced_wet_wetting_paths(self):
        dry = m7.weather_schedule(1, "dry", 8, forced_weather("DRY"))
        wet = m7.weather_schedule(1, "wet", 8, forced_weather("WET"))
        self.assertEqual(set(dry["rain"]), {"DRY"})
        self.assertEqual(dry["wetness"], [0.0] * 8)
        self.assertEqual(set(wet["rain"]), {"WET"})
        self.assertTrue(all(b > a for a, b in zip(wet["wetness"], wet["wetness"][1:])))

    def test_forecast_is_public_causal_and_report_noise_shrinks_with_lead(self):
        base = [0.5, 0.5]
        short = [m7._dirichlet(seed, base, 2, "forecast", "issue", 1) for seed in range(400)]
        long = [m7._dirichlet(seed, base, 6, "forecast", "issue", 1) for seed in range(400)]
        var_short = statistics.variance(row[0] for row in short)
        var_long = statistics.variance(row[0] for row in long)
        self.assertLess(var_long, var_short)
        schedule = m7.weather_schedule(91, "race-forecast", 8)
        first = m7.forecast(91, "race-forecast", schedule, 0)
        second = m7.forecast(91, "race-forecast", schedule, 0)
        self.assertEqual(first, second)
        for report in first["forecasts"].values():
            probabilities = report["rain_probabilities"]
            self.assertAlmostEqual(sum(probabilities.values()), 1.0)
            self.assertTrue(all(value >= 0 for value in probabilities.values()))
        assert_no_secrets(self, first)

    def test_future_alteration_does_not_change_current_public_forecast(self):
        state = m7.initial_state(404, "race-0")
        original = m7.public_observation(state)
        modified = copy.deepcopy(state)
        modified["schedule"]["rain"][-1] = "WET"
        modified["schedule"]["wetness"][-1] = 1.0
        self.assertEqual(original, m7.public_observation(modified))

    def test_public_projection_never_contains_hidden_fields(self):
        state = m7.initial_state(99)
        document = m7.public_observation(state)
        self.assertNotIn("schedule", document)
        self.assertNotIn("private_biases", document)
        self.assertNotIn("wetness", document["cars"]["Rival 1"])
        assert_no_secrets(self, document)
        with self.assertRaisesRegex(ValueError, "private"):
            reject_public_secrets({"rain_path": ["DRY", "WET"]})


class TyreAndLegalityTests(unittest.TestCase):
    def test_dry_coefficients_and_crossovers_are_public_and_coherent(self):
        self.assertEqual(v22.tyre_offset("SOFT", 0.0), -0.55)
        self.assertEqual(v22.tyre_offset("MEDIUM", 0.0), 0.0)
        self.assertEqual(v22.tyre_offset("HARD", 0.0), 0.28)
        self.assertEqual(v22.tyre_degradation("SOFT", 0.0), 0.35)
        self.assertEqual(v22.tyre_degradation("MEDIUM", 0.0), 0.14)
        self.assertEqual(v22.tyre_degradation("HARD", 0.0), 0.055)
        self.assertEqual(m7.incident_probabilities("SOFT", 0.0), (0.0, 0.0))
        self.assertLess(v22.tyre_offset("INTERMEDIATE", 0.4),
                        min(v22.tyre_offset(compound, 0.4) for compound in m7.DRY_COMPOUNDS))
        self.assertLess(v22.tyre_offset("WET", 1.0),
                        min(v22.tyre_offset(compound, 1.0) for compound in m7.DRY_COMPOUNDS))
        self.assertLess(v22.tyre_offset("WET", 0.85), v22.tyre_offset("INTERMEDIATE", 0.85))
        self.assertGreater(v22.tyre_degradation("WET", 0.0), v22.tyre_degradation("WET", 0.4))
        self.assertEqual(v22.m7_legal_actions(0.0), v22.m7_legal_actions(1.0))

    def test_two_dry_exemption_uses_actual_raced_compounds_only(self):
        self.assertEqual(v22.m7_finish_penalty(["MEDIUM"]), 20.0)
        self.assertEqual(v22.m7_finish_penalty(["MEDIUM", "HARD"]), 0.0)
        for compounds in (["INTERMEDIATE"], ["WET"], ["MEDIUM", "INTERMEDIATE"], ["SOFT", "MEDIUM", "WET"]):
            self.assertEqual(v22.m7_finish_penalty(compounds), 0.0)
        # A requested wet pit never raced gains no exemption.
        self.assertEqual(v22.m7_finish_penalty(["MEDIUM"]), 20.0)

    def test_neutralisation_adapter_preserves_simplex_and_configuration_is_opt_in(self):
        scaled = v22.neutralisation_multiplier("WET", {"SC": 0.5, "VSC": 0.4})
        self.assertAlmostEqual(sum(scaled.values()), 1.0)
        self.assertEqual(scaled["SC"] + scaled["VSC"], 1.0)
        default = v22.V22Config()
        self.assertFalse(default.m7_enabled)
        self.assertEqual(default.as_dict(), {"m2_enabled": False, "m7_enabled": False})


class MicroRaceAndReferenceTests(unittest.TestCase):
    def test_whole_replay_is_exact_and_safe_pit_changes_actual_outcomes(self):
        actions = ["PIT_WET", "STAY", "PIT_INTERMEDIATE", "STAY", "PIT_HARD", "PIT_INTERMEDIATE", "STAY", "PIT_WET"]
        raw_actions = copy.deepcopy(actions)
        first = m7.replay(987654321, actions)
        second = m7.replay(987654321, actions)
        self.assertEqual(first, second)
        self.assertEqual(actions, raw_actions)
        changed = m7.replay(987654321, ["STAY"] * 8)
        self.assertNotEqual(first["result"], changed["result"])
        self.assertEqual(len(first["observations"]), 8)
        for observation in first["observations"]:
            assert_no_secrets(self, observation)

    def test_forecast_only_pair_changes_legal_action_and_control_is_stable(self):
        dry_observation = m7.public_observation(m7.initial_state(7, "same-race", forced_weather("DRY")))
        wet_observation = m7.public_observation(m7.initial_state(7, "same-race", forced_weather("WET")))
        dry = v22.m7_action_values(dry_observation)
        wet = v22.m7_action_values(wet_observation)
        self.assertNotEqual(dry["chosen_action"], wet["chosen_action"])
        self.assertEqual(v22.m7_action_values(dry_observation), dry)
        self.assertEqual(dry["chosen_action"], v22.m7_action_values(dry_observation)["chosen_action"])
        self.assertNotIn("wetness", wet_observation["cars"]["Apex A"])

    def test_final_boundary_values_use_current_condition_without_future_leak(self):
        state = m7.initial_state(77)
        for _ in range(7):
            state = m7.step(state, "STAY")
        observation = m7.public_observation(state)
        self.assertEqual(observation["forecast"]["forecasts"], {})
        decision = m7.action_values(observation)
        self.assertIn("final-boundary", decision["value_basis"])
        self.assertIn(decision["chosen_action"], observation["legal_actions"])

    def test_rival_bias_can_change_visible_pit_action_without_weather_leak(self):
        state = m7.initial_state(8, "bias", forced_weather("WET"))
        first_pit = {}
        for bias in ("EARLY", "ON_TIME", "LATE"):
            candidate = copy.deepcopy(state)
            candidate["private_biases"]["Rival 1"] = bias
            for level in range(101):
                wetness = level / 100
                candidate["schedule"]["wetness"][0] = wetness
                if m7._next_rival_action(candidate, "Rival 1").startswith("PIT_"):
                    first_pit[bias] = wetness
                    break
        self.assertLess(first_pit["EARLY"], first_pit["ON_TIME"])
        self.assertLess(first_pit["ON_TIME"], first_pit["LATE"])

    def test_retired_controlled_car_has_only_stay_and_cannot_pit(self):
        state = m7.initial_state(88)
        state["cars"]["Apex A"]["retired"] = True
        observation = m7.public_observation(state)
        self.assertEqual(observation["legal_actions"], ["STAY"])
        self.assertEqual(m7.action_values(observation)["chosen_action"], "STAY")
        with self.assertRaisesRegex(ValueError, "cannot pit"):
            m7.step(state, "PIT_WET")
        result = m7.step(state, "STAY")
        self.assertTrue(result["cars"]["Apex A"]["retired"])

    def test_result_uses_existing_finish_penalty_plus_wet_exemption(self):
        violation = m7.replay(55, ["STAY"] * 8, model=forced_weather("DRY"))
        final = {row["car"]: row for row in violation["result"]["classification"]}
        self.assertEqual(final["Apex A"]["finish_penalty_sec"], 20.0)  # stayed on one dry compound
        self.assertEqual(final["Rival 1"]["finish_penalty_sec"], 0.0)
        wet = m7.replay(55, ["PIT_WET"] + ["STAY"] * 7, model=forced_weather("WET"))
        apex = next(row for row in wet["result"]["classification"] if row["car"] == "Apex A")
        self.assertTrue(apex["wet_exempt"])
        self.assertEqual(apex["finish_penalty_sec"], 0.0)


if __name__ == "__main__":
    unittest.main()
