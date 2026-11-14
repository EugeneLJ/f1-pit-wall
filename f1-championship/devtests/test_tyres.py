"""B1 level (a) tests: compound choice, tyre cliff, two-compound rule, rival compound rule."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK / "src"))

from f1pitwall import coefficients as coef  # noqa: E402
from f1pitwall import engine  # noqa: E402


def race(coeffs=coef.DEFAULT, events=("GREEN", "GREEN", "GREEN"), deg=1.0):
    config = {"grid": list(engine.LEGACY_CAR_NAMES), "pace": dict(engine.LEGACY_BASE_PACE),
              "deg_multiplier": deg, "overtaking": coeffs["track_performance"]["overtaking"],
              "overtaking_difficulty": 0.5, "tyres": coef.tyre_model(coeffs), "events": list(events)}
    return engine.new_state(3, config)


def car(state, name):
    return next(c for c in state["cars"] if c["name"] == name)


STAY = {"driver_a": "STAY", "driver_b": "STAY"}


class CompoundActionTests(unittest.TestCase):
    def test_pit_fits_the_named_compound_and_records_it(self):
        state = race()
        engine.step(state, {"driver_a": "PIT_HARD", "driver_b": "PIT_SOFT"})
        self.assertEqual((car(state, "Apex A")["compound"], car(state, "Apex A")["tyre_age"]), ("HARD", 4))
        self.assertEqual(car(state, "Apex B")["compound"], "SOFT")
        self.assertEqual(car(state, "Apex A")["compounds_used"], ["SOFT", "HARD"])

    def test_bare_pit_is_rejected_in_configured_races_but_legacy_accepts_it(self):
        with self.assertRaises(ValueError):
            engine.step(race(), {"driver_a": "PIT", "driver_b": "STAY"})
        legacy = engine.new_state(3)
        engine.step(legacy, {"driver_a": "PIT", "driver_b": "STAY"})
        self.assertEqual(car(legacy, "Apex A")["compound"], "MEDIUM")

    def test_observation_lists_legal_actions_and_laps_remaining(self):
        obs = engine.observation(race())
        self.assertEqual(obs["legal_actions"], list(engine.COMPOUND_ACTIONS))
        self.assertEqual(obs["laps_remaining"], 12)
        self.assertEqual(obs["drivers"]["driver_a"]["compounds_used"], ["SOFT"])

    def test_compound_choice_ablation_allows_medium_only(self):
        ablated = coef.ablate(coef.DEFAULT, "compound_choice")
        state = race(ablated)
        self.assertEqual(engine.legal_actions(state), ["STAY", "PIT_MEDIUM"])
        with self.assertRaises(ValueError):
            engine.step(state, {"driver_a": "PIT_SOFT", "driver_b": "STAY"})

    def test_double_stack_applies_to_compound_stops(self):
        both, alone = race(), race()
        engine.step(both, {"driver_a": "PIT_HARD", "driver_b": "PIT_HARD"})
        engine.step(alone, {"driver_a": "STAY", "driver_b": "PIT_HARD"})
        pit_b = lambda s: car(s, "Apex B")["elapsed"]  # noqa: E731
        self.assertAlmostEqual(pit_b(both) - pit_b(alone), engine.DOUBLE_STACK_DELAY, delta=1.0)


class TyreModelTests(unittest.TestCase):
    def setUp(self):
        self.tyres = coef.tyre_model(coef.DEFAULT)

    def seg(self, compound, age, deg=1.0, tyres=None):
        return engine._segment_time({"compound": compound, "tyre_age": age, "base_pace": 90.0}, 1, deg,
                                    0.0, tyres or self.tyres)

    def test_softer_is_faster_fresh_and_degrades_faster(self):
        self.assertLess(self.seg("SOFT", 0), self.seg("MEDIUM", 0))
        self.assertLess(self.seg("MEDIUM", 0), self.seg("HARD", 0))
        self.assertGreater(self.seg("SOFT", 8) - self.seg("SOFT", 0), self.seg("HARD", 8) - self.seg("HARD", 0))

    def test_cliff_beyond_life_scales_with_track_degradation_and_can_be_ablated(self):
        life = self.tyres["compounds"]["SOFT"]["life_laps"]
        linear_step = 4 * 4 * self.tyres["compounds"]["SOFT"]["degradation"]
        before = self.seg("SOFT", life - 4) - self.seg("SOFT", life - 8)
        after = self.seg("SOFT", life + 4) - self.seg("SOFT", life)
        self.assertAlmostEqual(before, linear_step, places=9)
        self.assertGreater(after, linear_step + 1.0)
        self.assertGreater(self.seg("SOFT", life + 4, 1.4) - self.seg("SOFT", life + 4, 1.4, coef.tyre_model(
            coef.ablate(coef.DEFAULT, "tyre_cliff"))), self.seg("SOFT", life + 4) - self.seg(
            "SOFT", life + 4, 1.0, coef.tyre_model(coef.ablate(coef.DEFAULT, "tyre_cliff"))))
        flat = coef.tyre_model(coef.ablate(coef.DEFAULT, "tyre_cliff"))
        self.assertAlmostEqual(self.seg("SOFT", life + 4, 1.0, flat) - self.seg("SOFT", life, 1.0, flat),
                               linear_step, places=9)


class TwoCompoundRuleTests(unittest.TestCase):
    def test_solver_expectation_accounts_for_the_penalty(self):
        sys.path.insert(0, str(TASK / "analysis"))
        import track_a_solver as ts
        stayed, changed = race(), race()
        for state, action in ((stayed, "STAY"), (changed, "PIT_MEDIUM")):
            engine.step(state, {"driver_a": action, "driver_b": "PIT_HARD"})
            engine.step(state, STAY)
            engine.step(state, STAY)
            state["config"]["dnf_prob"] = {name: 0.0 for name in state["config"]["dnf_prob"]}
        self.assertEqual(ts.expected_apex_points_at_finish(stayed), engine.result(stayed)["constructors_points"])
        self.assertEqual(ts.expected_apex_points_at_finish(changed), engine.result(changed)["constructors_points"])

    def finish(self, coeffs, a_action):
        state = race(coeffs)
        engine.step(state, {"driver_a": a_action, "driver_b": "PIT_HARD"})
        engine.step(state, STAY)
        engine.step(state, STAY)
        return next(e for e in engine.result(state)["classification"] if e["driver"] == "Apex A")

    def test_one_compound_race_is_penalised(self):
        stayed = self.finish(coef.DEFAULT, "STAY")
        self.assertEqual(stayed["penalty_sec"], coef.DEFAULT["tyres"]["two_compound_rule"]["penalty_sec"])
        same = self.finish(coef.DEFAULT, "PIT_SOFT")  # Apex A started on SOFT
        self.assertGreater(same["penalty_sec"], 0)
        changed = self.finish(coef.DEFAULT, "PIT_MEDIUM")
        self.assertEqual(changed["penalty_sec"], 0.0)

    def test_rule_ablation_removes_the_penalty(self):
        self.assertEqual(self.finish(coef.ablate(coef.DEFAULT, "two_compound_rule"), "STAY")["penalty_sec"], 0.0)


class RivalCompoundTests(unittest.TestCase):
    def test_rival_rule_by_laps_remaining_and_two_compound_compliance(self):
        tyres = coef.tyre_model(coef.DEFAULT)
        rival = {"compound": "MEDIUM", "tyre_age": 2, "compounds_used": ["MEDIUM"]}
        self.assertEqual(engine.rival_compound(rival, 4, tyres), "SOFT")
        self.assertEqual(engine.rival_compound(rival, 20, tyres), "HARD")
        self.assertEqual(engine.rival_compound(rival, 12, tyres), "HARD")  # MEDIUM would break the rule
        self.assertEqual(engine._rival_action(rival, "GREEN", 2, 3, tyres, 4), "PIT_SOFT")
        self.assertEqual(engine._rival_action(rival, "GREEN", 1, 3, tyres, 8), "STAY")

    def test_rivals_meet_the_rule_in_a_full_race(self):
        state = race()
        for _ in range(3):
            engine.step(state, {"driver_a": "PIT_MEDIUM", "driver_b": "PIT_HARD"}
                        if state["step"] == 0 else STAY)
        for entry in engine.result(state)["classification"]:
            self.assertEqual(entry["penalty_sec"], 0.0, entry["driver"])


if __name__ == "__main__":
    unittest.main()
