from __future__ import annotations

import copy
from dataclasses import replace
import unittest
from unittest import mock

from devtests.test_b6_integration import act, scene
from devtests.test_v22_m6_integration import drive
from devtests.v22_helpers import assert_no_secrets as secret_guard
from f1pitwall import engine
from f1pitwall.integrated import config as C
from f1pitwall.integrated import race as ir
from f1pitwall.integrated import session as S
from f1pitwall.integrated import verify as V
from f1pitwall.integrated import match
from f1pitwall import weather as owner_weather
from track_c.v22 import weather as micro


def no_secrets(test, value):
    class Wrapper:
        def assertNotIn(self, *args, **kwargs):
            pass
    secret_guard(Wrapper(), value)


def forced_model(condition):
    model = micro.load_model()
    states = model["rain"]["states"]
    model["rain"]["initial_distribution"] = {
        kind: 1.0 if kind == condition else 0.0 for kind in states}
    for kind in states:
        model["rain"]["transition"][kind] = [
            1.0 if target == condition else 0.0 for target in states]
    return model


def enable(state, condition):
    context = owner_weather.create(state["seed"], f"m7-test-{condition}", 14)
    context["schedule"] = micro.weather_schedule(
        state["seed"], f"m7-test-{condition}", 14, forced_model(condition))
    context["model"] = forced_model(condition)
    state["config"][owner_weather.WEATHER_KEY] = context
    owner_weather.adopt_tyre_model(state)
    return state


def elapses(state):
    return [(car["name"], car["elapsed"], car["tyre_age"], car["compound"], car.get("weather_retired"))
            for car in state["cars"]]


class M7IntegrationTests(unittest.TestCase):
    def test_forced_dry_first_step_matches_legacy_and_green_sc_vsc(self):
        for condition in ("GREEN", "SC", "VSC"):
            baseline, changed = scene(events=(condition,)), scene(events=(condition,))
            ir.step(baseline, act())
            enable(changed, "DRY")
            ir.step(changed, act())
            self.assertEqual(elapses(baseline), elapses(changed))
            self.assertEqual(baseline["cars"][0]["base_pace"], changed["cars"][0]["base_pace"])

    def test_wet_pit_acts_fresh_tyre_and_preserves_warmup_and_risk(self):
        baseline, wet = scene(), scene()
        ir.step(baseline, act())
        enable(wet, "WET")
        ir.step(wet, act(a="PIT_INTERMEDIATE"))
        changed = next(car for car in wet["cars"] if car["name"] == "Apex A")
        old = next(car for car in baseline["cars"] if car["name"] == "Apex A")
        self.assertNotEqual(changed["elapsed"], old["elapsed"])
        self.assertEqual(changed["compound"], "INTERMEDIATE")
        self.assertEqual(changed["tyre_age"], 3)
        self.assertEqual(changed["weather_raced"], ["INTERMEDIATE"])
        self.assertEqual(engine.finish_penalty(wet, changed), 0.0)
        view = S.team_race_view(wet, "Apex", lambda name: name,
                                {name: name for name in ("Apex", "Orion", "Nova", "Vertex")}, "race")
        self.assertIn("PIT_INTERMEDIATE", view["weather"]["legal_actions"])
        self.assertIn("PIT_WET", view["weather"]["legal_actions"])
        self.assertEqual(view["weather"]["compounds_used"]["Apex A"], ["INTERMEDIATE"])

    def test_public_forecasts_are_deterministic_and_future_private_fields_do_not_leak(self):
        state = enable(scene(), "WET")
        before = copy.deepcopy(state)
        first = owner_weather.weather_observation(state)
        second = owner_weather.weather_observation(state)
        self.assertEqual(first, second)
        self.assertEqual(state, before)
        modified = copy.deepcopy(state)
        modified["config"][owner_weather.WEATHER_KEY]["schedule"]["rain"][-1] = "DRY"
        modified["config"][owner_weather.WEATHER_KEY]["schedule"]["wetness"][-1] = 0.0
        self.assertEqual(first, owner_weather.weather_observation(modified))
        no_secrets(self, first)
        for key in ctx_privacy("_"):
            self.assertNotIn(key, str(first))

    def test_retirement_stops_pits_movement_team_geometry_and_finalizes_dnf(self):
        state = enable(scene(), "WET")
        retired_name = "Apex B"
        next(car for car in state["cars"] if car["name"] == retired_name)["weather_retired"] = True
        self.assertTrue(owner_weather.retired_context(state, retired_name))
        self.assertEqual(owner_weather.rival_action(state, next(car for car in state["cars"] if car["name"] == retired_name),
                                                  "GREEN", 0, 14, engine._tyres(state), 39), "STAY")
        order_view = ir.public_order_view(state, "Apex")
        self.assertEqual(order_view["exchange_feasibility_if_no_pit"]["blocking_reasons"], ["RETIRED_DRIVER"])
        self.assertIsNone(order_view["exchange_feasibility_if_no_pit"]["gap_sec"])
        ir.update_commitments(state)
        ir.step(state, act(a="PIT_WET", b="STAY"))
        state["complete"] = True
        result = engine.result(state)
        self.assertTrue(result["complete"])
        dnf = next(row for row in result["classification"] if row["driver"] == retired_name)
        self.assertEqual(dnf["status"], "DNF")
        self.assertEqual(dnf["points"], 0)

    def test_incident_stream_is_keyed_and_retiree_is_not_reinserted_by_later_steps(self):
        state = enable(scene(), "WET")
        with mock.patch("track_c.v22.common.uniform", return_value=0.0):
            a = copy.deepcopy(state)
            b = copy.deepcopy(state)
            ir.step(a, act())
            ir.step(b, act())
            self.assertEqual(elapses(a), elapses(b))
            self.assertTrue(any(car.get("weather_retired") for car in a["cars"]))
            view = ir.public_order_view(a, "Apex")
            self.assertIn("RETIRED_DRIVER", view["exchange_feasibility_if_no_pit"]["blocking_reasons"])
            ir.step(a, act(a="PIT_WET", b="PIT_INTERMEDIATE"))
            self.assertTrue(any(car.get("weather_retired") for car in a["cars"]))

    def test_wet_context_supports_public_neutralization_multiplier_and_typed_return(self):
        state = enable(scene(events=("SC",)), "WET")
        multiplier = micro.neutralisation_multiplier("WET", {"SC": 0.5, "VSC": 0.4})
        self.assertAlmostEqual(sum(multiplier.values()), 1.0)
        self.assertGreaterEqual(multiplier["GREEN"], 0.0)
        current = owner_weather.weather_observation(state)
        self.assertIsInstance(current["forecast"]["forecasts"]["1"]["lead_segments"], int)

    def test_full_m2_m6_weather_seasons_replay_and_no_false_m6_events(self):
        config = replace(C.with_version(C.two_team(1), "2.2.0"), m6_compliance=False, m2_tendencies=False, m7_weather=True)
        for seed in (11, 12):
            driver = drive(config, seed)
            self.assertEqual(len(driver.journal), 120)
            replayed = V.replay(config, seed, copy.deepcopy(driver.journal), require_complete=True)
            self.assertTrue(replayed["complete"])
            self.assertEqual(replayed["standings"], driver.standings())
            self.assertTrue(all("order_events" not in entry for entry in driver.journal))

    def test_combined_m2_m6_weather_replays_and_preserves_constructors_fields(self):
        config = replace(C.with_version(C.two_team(1), "2.2.0"),
                         m2_tendencies=True, m6_compliance=True, m7_weather=True)
        driver = drive(config, 21)
        self.assertEqual(len(driver.race_results), 8)
        replayed = V.replay(config, 21, copy.deepcopy(driver.journal), require_complete=True)
        self.assertTrue(replayed["complete"])
        self.assertEqual(replayed["standings"], driver.standings())
        for result in driver.race_results:
            self.assertEqual(sum(result["driver_points"].values()), sum(result["team_points"].values()))


class ModeAndConfigTests(unittest.TestCase):
    def test_legacy_config_serialization_has_no_false_flags_and_opt_in_is_explicit(self):
        before = C.two_team(1)
        after = replace(before, m2_tendencies=False, m6_compliance=False, m7_weather=False)
        self.assertEqual(before.as_dict(), after.as_dict())
        self.assertEqual(before.config_hash(), after.config_hash())
        with self.assertRaisesRegex(ValueError, "opt-in benchmark 2.2.0"):
            replace(before, m7_weather=True).validate()

    def test_fixed_replay_reuses_actions_without_model_or_future_access(self):
        action = {"type": "COMPONENT_DECISION", "decisions": []}
        journal = [{"kind": "resolved", "tick_id": "t001",
                    "submissions": {"Apex": {"action": action}}}]
        policy = match.ReplayPolicy(journal, "Apex")
        returned, metadata = policy({"tick_id": "t001"})
        self.assertEqual(returned, action)
        self.assertEqual(metadata, {"source": "FIXED_REPLAY"})
        self.assertIsNot(returned, action)
        with self.assertRaises(KeyError):
            policy({"tick_id": "t002"})


def ctx_privacy(_):
    return ("private_seed", "rain_path", "tendency_assignment", "bias_assignment", "hidden_draw")


if __name__ == "__main__":
    unittest.main()
