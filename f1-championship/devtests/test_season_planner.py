"""Tests for the budgeted season planner (analysis/season_planner.py)."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK / "src"))
sys.path.insert(0, str(TASK / "analysis"))

import season_planner as sp  # noqa: E402
import track_a_solver as ts  # noqa: E402
from f1pitwall import coefficients as coef  # noqa: E402
from f1pitwall.championship import RaceEntry, new_championship_state  # noqa: E402
from f1pitwall.championship_transition import initial_inventory  # noqa: E402


def worn_short_season(races=2):
    archetypes = ("high_speed", "street", "mixed")
    calendar = [RaceEntry(name=f"T{i}", archetype=archetypes[i % 3], power_unit_stress=0.8 - 0.2 * (i % 2),
                          overtaking_difficulty=0.3 + 0.5 * (i % 2), tyre_degradation=0.5,
                          synthetic_placeholder=True) for i in range(races)]
    state = new_championship_state(calendar=calendar, resource_inventory=initial_inventory(coef.DEFAULT))
    for driver, wear in (("Apex A", 0.75), ("Apex B", 0.55)):
        for comp in state.power_units[driver].values():
            comp.wear = wear
    state.resource_inventory["Apex"]["component_spares"] = 2
    return state


class SeasonPlannerTests(unittest.TestCase):
    def test_horizon_one_is_greedy(self):
        state = worn_short_season(1)
        solver = ts.Solver()
        _, plan, _ = sp.search(sp.Evaluator(solver), state, 1, 100)
        self.assertEqual(sp.repair(state, plan[0], coef.DEFAULT), solver.choose(state, "greedy"))

    def test_search_finds_exact_optimum_on_two_race_season(self):
        state = worn_short_season(2)
        exact, _ = ts.Solver().optimal(state)
        value, _, info = sp.search(sp.Evaluator(ts.Solver()), state, 2, 1500)
        self.assertAlmostEqual(value, exact, places=6)
        self.assertLessEqual(info["evaluations"], 1500)

    def test_fixed_policy_path_value_matches_solver_evaluation(self):
        state = worn_short_season(3)
        solver = ts.Solver()
        for policy in ("always_use", "rival_rule", "greedy"):
            result = sp.run_season(copy.deepcopy(state), policy, solver=solver)
            self.assertAlmostEqual(result["expected_points"], solver.evaluate(state, policy), places=6)

    def test_planner_is_deterministic_and_seed_free(self):
        state = worn_short_season(3)
        first = sp.run_season(copy.deepcopy(state), "mpc:3", budget=400)
        second = sp.run_season(copy.deepcopy(state), "mpc:3", budget=400)
        self.assertEqual([s["option"] for s in first["path"]], [s["option"] for s in second["path"]])
        import inspect
        planning = [sp.search, sp.rollout, sp.run_season, sp.repair, sp._rule_plan, sp._block_candidates,
                    sp._neighbours, sp.Evaluator, sp._window]
        source = "\n".join(inspect.getsource(obj) for obj in planning)  # scoring helpers excluded
        self.assertNotIn("_seeded_race", source)
        self.assertNotIn("dnf_uniforms", source)
        self.assertNotIn("_event_schedule", source)

    def test_budget_is_respected(self):
        state = worn_short_season(3)
        _, _, info = sp.search(sp.Evaluator(ts.Solver()), state, 3, 50)
        self.assertLessEqual(info["evaluations"], 50)
        self.assertTrue(info["budget_exhausted"])

    def test_forced_prefix_is_executed(self):
        state = worn_short_season(2)
        forced = [tuple((d, c, "REPLACE" if d == "Apex B" else "USE") for d in ts.APEX for c in ts.COMPONENTS)]
        result = sp.run_season(copy.deepcopy(state), "greedy", forced_prefix=forced)
        self.assertEqual(result["path"][0]["option"], "B:ICE+B:turbo+B:energy_store")


if __name__ == "__main__":
    unittest.main()
