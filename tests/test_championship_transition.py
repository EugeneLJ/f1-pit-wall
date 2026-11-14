from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "environment"))

from f1pitwall.championship import new_championship_state  # noqa: E402
from f1pitwall.championship_transition import (  # noqa: E402
    available_component_actions,
    complete_race,
    default_component_decisions,
    mark_grid_penalties_applied,
    prepare_race,
)


def zero_points(state):
    return {driver: 0 for driver in state.driver_points}


def replace(decisions, driver, component):
    for decision in decisions:
        if decision["driver"] == driver and decision["component"] == component:
            decision["action"] = "REPLACE"
            return
    raise AssertionError("decision not found")


class ChampionshipTransitionTests(unittest.TestCase):
    def test_race_completion_carries_points_wear_and_inventory(self):
        state = new_championship_state()
        decisions = default_component_decisions(state)
        replace(decisions, "Apex A", "ICE")
        start = prepare_race(state, decisions)
        self.assertTrue(start.applied_to_grid)
        points = zero_points(state)
        points["Apex A"], points["Apex B"] = 25, 18
        complete_race(state, points)
        self.assertEqual(state.race_index, 1)
        self.assertEqual(state.driver_points["Apex A"], 25)
        self.assertEqual(state.team_points["Apex"], 43)
        self.assertEqual(state.resource_inventory["Apex"]["component_spares"], 1)
        self.assertGreater(state.power_units["Apex A"]["ICE"].wear, 0.0)

    def test_excess_replacement_exposes_unapplied_grid_penalty(self):
        state = new_championship_state()
        state.power_units["Apex A"]["ICE"].replacements = 1
        decisions = default_component_decisions(state)
        replace(decisions, "Apex A", "ICE")
        start = prepare_race(state, decisions)
        self.assertEqual(start.grid_drop_positions["Apex A"], 5)
        self.assertFalse(start.applied_to_grid)
        with self.assertRaises(ValueError):
            complete_race(state, zero_points(state))
        marked = mark_grid_penalties_applied(state)
        self.assertTrue(marked.applied_to_grid)
        complete_race(state, zero_points(state))
        self.assertEqual(state.grid_penalties["Apex A"], 0)

    def test_different_component_strategies_change_future_options(self):
        use_state = new_championship_state()
        use_state.power_units["Apex A"]["ICE"].wear = 0.80
        replace_state = copy.deepcopy(use_state)

        prepare_race(use_state, default_component_decisions(use_state))
        complete_race(use_state, zero_points(use_state))
        replacement_plan = default_component_decisions(replace_state)
        replace(replacement_plan, "Apex A", "ICE")
        prepare_race(replace_state, replacement_plan)
        complete_race(replace_state, zero_points(replace_state))

        self.assertNotIn("USE", available_component_actions(use_state, "Apex A")["ICE"])
        self.assertIn("USE", available_component_actions(replace_state, "Apex A")["ICE"])
        self.assertGreater(use_state.power_units["Apex A"]["ICE"].wear,
                           replace_state.power_units["Apex A"]["ICE"].wear)
        self.assertGreater(use_state.resource_inventory["Apex"]["component_spares"],
                           replace_state.resource_inventory["Apex"]["component_spares"])

    def test_invalid_and_duplicate_decisions_are_atomic(self):
        state = new_championship_state()
        original = copy.deepcopy(state)
        duplicate = default_component_decisions(state)
        duplicate.append(dict(duplicate[0]))
        with self.assertRaises(ValueError):
            prepare_race(state, duplicate)
        self.assertEqual(state, original)

        invalid = default_component_decisions(state)
        invalid[0]["action"] = "REFURBISH"
        with self.assertRaises(ValueError):
            prepare_race(state, invalid)
        self.assertEqual(state, original)

        no_spares = copy.deepcopy(state)
        no_spares.resource_inventory["Apex"]["component_spares"] = 0
        unavailable = default_component_decisions(no_spares)
        replace(unavailable, "Apex A", "ICE")
        before = copy.deepcopy(no_spares)
        with self.assertRaises(ValueError):
            prepare_race(no_spares, unavailable)
        self.assertEqual(no_spares, before)

    def test_same_race_cannot_be_prepared_twice(self):
        state = new_championship_state()
        prepare_race(state, default_component_decisions(state))
        with self.assertRaises(ValueError):
            prepare_race(state, default_component_decisions(state))


if __name__ == "__main__":
    unittest.main()
