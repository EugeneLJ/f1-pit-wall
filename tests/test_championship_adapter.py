from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "environment"))

from f1pitwall.championship import TEAM_DRIVERS, new_championship_state  # noqa: E402
from f1pitwall.championship_adapter import (  # noqa: E402
    run_championship,
    run_championship_race,
    stay_race_policy,
)
from f1pitwall.championship_transition import (  # noqa: E402
    complete_race,
    default_component_decisions,
    prepare_race,
)


def use_components(state):
    return default_component_decisions(state)


def replace_component(decisions, driver, component):
    for decision in decisions:
        if decision["driver"] == driver and decision["component"] == component:
            decision["action"] = "REPLACE"
            return decisions
    raise AssertionError("component decision not found")


class ChampionshipAdapterTests(unittest.TestCase):
    def test_grid_penalty_produces_valid_permutation_and_changes_start(self):
        state = new_championship_state()
        state.power_units["Apex A"]["ICE"].replacements = 1
        decisions = replace_component(default_component_decisions(state), "Apex A", "ICE")
        result = run_championship_race(state, decisions, stay_race_policy(state), 20261114)
        self.assertEqual(len(result.starting_grid), 8)
        self.assertEqual(len(set(result.starting_grid)), 8)
        self.assertEqual(set(result.starting_grid), set(state.driver_points))
        self.assertEqual(result.starting_grid.index("Apex A"), 6)
        self.assertTrue(result.start_conditions.applied_to_grid)

    def test_unapplied_penalty_still_blocks_direct_completion(self):
        state = new_championship_state()
        state.power_units["Apex A"]["ICE"].replacements = 1
        decisions = replace_component(default_component_decisions(state), "Apex A", "ICE")
        prepare_race(state, decisions)
        with self.assertRaises(ValueError):
            complete_race(state, {driver: 0 for driver in state.driver_points})

    def test_engine_classification_updates_driver_and_team_points(self):
        state = new_championship_state()
        result = run_championship_race(
            state, default_component_decisions(state), stay_race_policy(state), 20261114)
        self.assertEqual(state.driver_points, result.awarded_points)
        for team, drivers in TEAM_DRIVERS.items():
            self.assertEqual(state.team_points[team], sum(result.awarded_points[d] for d in drivers))
        self.assertEqual(sum(result.awarded_points.values()), 98)

    def test_persistent_component_state_reaches_next_race(self):
        state = new_championship_state()
        decisions = replace_component(default_component_decisions(state), "Apex A", "ICE")
        run_championship_race(state, decisions, stay_race_policy(state), 20261114)
        self.assertEqual(state.race_index, 1)
        self.assertEqual(state.power_units["Apex A"]["ICE"].replacements, 1)
        self.assertGreater(state.power_units["Apex A"]["ICE"].wear, 0.0)
        self.assertEqual(state.resource_inventory["Apex"]["component_spares"], 1)
        self.assertFalse(state.race_prepared)
        self.assertFalse(state.grid_penalties_applied)
        self.assertTrue(all(value == 0 for value in state.grid_penalties.values()))

    def test_reproducible_for_same_state_seed_and_actions(self):
        first, second = new_championship_state(), new_championship_state()
        first_result = run_championship_race(
            first, default_component_decisions(first), stay_race_policy(first), 20261114)
        second_result = run_championship_race(
            second, default_component_decisions(second), stay_race_policy(second), 20261114)
        self.assertEqual(first_result, second_result)
        self.assertEqual(first, second)

    def test_two_race_smoke(self):
        state = new_championship_state()
        results = run_championship(state, use_components, stay_race_policy,
                                   base_seed=20261114, race_count=2)
        self.assertEqual(len(results), 2)
        self.assertEqual(state.race_index, 2)
        self.assertGreater(sum(state.team_points.values()), 0)
        self.assertGreater(state.power_units["Apex A"]["ICE"].wear, 0.0)

    def test_eight_race_smoke_and_final_standings(self):
        state = new_championship_state()
        results = run_championship(state, use_components, stay_race_policy, base_seed=20261114)
        self.assertEqual(len(results), 8)
        self.assertEqual(state.race_index, len(state.calendar))
        self.assertEqual(sum(state.team_points.values()), 8 * 98)
        standings = sorted(state.team_points.items(), key=lambda item: (-item[1], item[0]))
        self.assertEqual({team for team, _ in standings}, set(TEAM_DRIVERS))
        with self.assertRaises(ValueError):
            run_championship_race(
                state, default_component_decisions(state), stay_race_policy(state), 20261122)

    def test_replacement_penalty_changes_grid_and_race_outcome(self):
        baseline = new_championship_state()
        penalized = copy.deepcopy(baseline)
        penalized.power_units["Apex A"]["ICE"].replacements = 1
        fixed_actions = [
            {"driver_a": "PIT", "driver_b": "PIT"},
            {"driver_a": "PIT", "driver_b": "STAY"},
            {"driver_a": "PIT", "driver_b": "PIT"},
        ]
        baseline_result = run_championship_race(
            baseline, default_component_decisions(baseline), fixed_actions, 20261114)
        penalty_plan = replace_component(
            default_component_decisions(penalized), "Apex A", "ICE")
        penalty_result = run_championship_race(
            penalized, penalty_plan, fixed_actions, 20261114)
        self.assertNotEqual(baseline_result.starting_grid, penalty_result.starting_grid)
        self.assertNotEqual(baseline_result.awarded_points["Apex A"],
                            penalty_result.awarded_points["Apex A"])
        self.assertNotEqual(baseline.driver_points["Apex A"],
                            penalized.driver_points["Apex A"])


if __name__ == "__main__":
    unittest.main()
