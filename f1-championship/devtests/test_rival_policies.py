"""B5-P1 tests: opt-in rival strategy variants and event-aware planner information boundary."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK / "src"))
sys.path.insert(0, str(TASK / "analysis"))

from f1pitwall import coefficients as coef  # noqa: E402
from f1pitwall import engine  # noqa: E402
from f1pitwall.championship_adapter import race_config  # noqa: E402
from f1pitwall.championship import new_championship_state  # noqa: E402
from f1pitwall.championship_transition import initial_inventory  # noqa: E402
from f1pitwall.rival_policies import VARIANTS  # noqa: E402

FMT = coef.race_format(coef.DEFAULT)
N = len(FMT["decision_laps"])
STAY = {"driver_a": "STAY", "driver_b": "STAY"}


def race(seed, variant=None):
    config = {"grid": list(engine.LEGACY_CAR_NAMES), "pace": dict(engine.LEGACY_BASE_PACE),
              "overtaking": coef.DEFAULT["track_performance"]["overtaking"], "overtaking_difficulty": 0.5,
              "tyres": coef.tyre_model(coef.DEFAULT), "pit": coef.pit_model("mixed", coef.DEFAULT), **FMT,
              "events": engine.neutralization_schedule(seed, N, FMT["neutralization"])}
    if variant is not None:
        config["rival_policy"] = variant
    return engine.new_state(seed, config)


def run(state):
    stops = {}
    while not state["complete"]:
        before = {c["name"]: len(c["compounds_used"]) for c in state["cars"]}
        engine.step(state, STAY)
        for c in state["cars"]:
            if len(c["compounds_used"]) > before[c["name"]]:
                stops.setdefault(c["name"], []).append(state["step"])
    return stops


class RivalVariantTests(unittest.TestCase):
    def test_default_state_and_rules_unchanged(self):
        self.assertNotIn("rival_policy", race(3)["config"])
        self.assertNotIn("rival_policy", race(3, "public")["config"])
        self.assertNotIn("rival_policy_variant", coef.DEFAULT)
        state = new_championship_state(resource_inventory=initial_inventory(coef.DEFAULT))
        self.assertNotIn("rival_policy", race_config(state, coef.DEFAULT, []))
        self.assertEqual(race_config(state, coef.with_rival_policy(coef.DEFAULT, "undercut"), [])["rival_policy"],
                         "undercut")

    def test_explicit_public_equals_default(self):
        for seed in range(10):
            a, b = race(seed), race(seed, "public")
            run(a), run(b)
            self.assertEqual(engine.result(a), engine.result(b))

    def test_variants_are_distinct_compliant_and_hidden(self):
        for variant in VARIANTS[1:]:
            differs = False
            for seed in range(12):
                default, alt = race(seed), race(seed, variant)
                self.assertEqual(engine.observation(default).keys(), engine.observation(alt).keys())
                self.assertNotIn(variant, json.dumps(engine.observation(alt)))
                s1, s2 = run(default), run(alt)
                differs |= s1 != s2
                for car in (c for c in alt["cars"] if c["team"] != "Apex"):
                    self.assertEqual(engine.finish_penalty(alt, car), 0.0, (variant, seed, car["name"]))
            self.assertTrue(differs, variant)

    def test_unknown_variant_rejected(self):
        with self.assertRaises(ValueError):
            coef.with_rival_policy(coef.DEFAULT, "teleport")
        state = race(1, "teleport")
        with self.assertRaises(ValueError):
            engine.step(state, STAY)


class PlannerInformationTests(unittest.TestCase):
    def test_planner_futures_ignore_true_future(self):
        import event_policies as ep
        base = race(5)
        base["events"] = ["GREEN"] * N
        for _ in range(4):
            engine.step(base, STAY)
        other = dict(base, events=list(base["events"]))
        other["events"][5:] = ["SC"] * (N - 5)
        for mode in ep.FAIR_MODES + ("full_long",):
            self.assertEqual(ep.planner_futures(base, mode), ep.planner_futures(other, mode), mode)
            self.assertEqual(ep.plan_action(base, mode, samples=4), ep.plan_action(other, mode, samples=4), mode)

    def test_mode_assumptions(self):
        import event_policies as ep
        import random
        model = FMT["neutralization"]
        hist = ["GREEN", "SC"]
        self.assertTrue(all(s == "GREEN" for s in ep.generate(random.Random(1), hist, N, model, "green_only")))
        for k in range(30):
            reactive = ep.generate(random.Random(k), hist, N, model, "reactive")
            self.assertNotIn("VSC", reactive)
            self.assertTrue(all(s == "GREEN" for s in reactive[2:]))
            self.assertEqual(ep.generate(random.Random(k), hist, N, model, "full_long")[:3], ["SC", "SC", "GREEN"])


if __name__ == "__main__":
    unittest.main()
