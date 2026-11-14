from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "environment"))

from f1pitwall.championship_contract import (  # noqa: E402
    CHAMPIONSHIP_COMPLETE,
    COMPONENT_DECISION,
    RACE_STRATEGY,
    ChampionshipSession,
)


def component_use_action(observation):
    decisions = []
    for driver, driver_state in observation["controlled_drivers"].items():
        for component in driver_state["components"]:
            decisions.append({"driver": driver, "component": component, "action": "USE"})
    return {"type": COMPONENT_DECISION, "decisions": decisions}


def stay_action():
    return {"type": RACE_STRATEGY, "driver_a": "STAY", "driver_b": "STAY"}


def run_races(session, count):
    for _ in range(count):
        session.submit(component_use_action(session.observation()))
        for _ in range(3):
            session.submit(stay_action())


def assert_no_keys(test, value, forbidden):
    if isinstance(value, dict):
        test.assertTrue(set(value).isdisjoint(forbidden))
        for child in value.values():
            assert_no_keys(test, child, forbidden)
    elif isinstance(value, list):
        for child in value:
            assert_no_keys(test, child, forbidden)


class ChampionshipContractTests(unittest.TestCase):
    def test_component_observation_contains_public_championship_state(self):
        observation = ChampionshipSession().observation()
        self.assertEqual(observation["decision_type"], COMPONENT_DECISION)
        self.assertEqual(len(observation["championship"]["remaining_calendar"]), 8)
        self.assertEqual(len(observation["championship"]["team_standings"]), 4)
        self.assertEqual(set(observation["controlled_drivers"]), {"Apex A", "Apex B"})
        self.assertIn("power_unit_stress", observation["current_track"])
        self.assertIn("component_spares", observation["resource_inventory"])
        assert_no_keys(self, observation, {"seed", "events", "event_history", "cars"})

    def test_race_strategy_is_sequential_and_shows_only_current_event(self):
        session = ChampionshipSession()
        observation = session.submit(component_use_action(session.observation()))
        self.assertEqual(observation["decision_type"], RACE_STRATEGY)
        self.assertEqual(observation["race_progress"]["decision_index"], 1)
        self.assertIn("track_status", observation["race_progress"])
        self.assertNotIn("future_track_status", observation["race_progress"])
        next_observation = session.submit(stay_action())
        self.assertEqual(next_observation["race_progress"]["decision_index"], 2)

    def test_illegal_duplicate_and_out_of_order_actions_are_rejected(self):
        session = ChampionshipSession()
        with self.assertRaises(ValueError):
            session.submit(stay_action())
        self.assertEqual(session.state.race_index, 0)
        self.assertFalse(session.state.race_prepared)

        action = component_use_action(session.observation())
        action["decisions"].append(dict(action["decisions"][0]))
        with self.assertRaises(ValueError):
            session.submit(action)
        self.assertFalse(session.state.race_prepared)
        self.assertFalse(session.trace()[-1]["validation"]["valid"])

        session.submit(component_use_action(session.observation()))
        with self.assertRaises(ValueError):
            session.submit(component_use_action(session.observation()))

    def test_same_actions_produce_identical_state_and_trace(self):
        first, second = ChampionshipSession(), ChampionshipSession()
        run_races(first, 2)
        run_races(second, 2)
        self.assertEqual(first.state, second.state)
        self.assertEqual(first.trace(), second.trace())
        assert_no_keys(self, first.trace(), {"seed", "events", "event_history", "cars"})

    def test_two_race_end_to_end(self):
        session = ChampionshipSession()
        run_races(session, 2)
        observation = session.observation()
        self.assertEqual(session.state.race_index, 2)
        self.assertEqual(observation["decision_type"], COMPONENT_DECISION)
        self.assertEqual(len(observation["championship"]["remaining_calendar"]), 6)
        self.assertEqual(len(session.trace()), 8)
        self.assertGreater(sum(session.state.team_points.values()), 0)

    def test_eight_race_end_to_end_and_completed_race_rejected(self):
        session = ChampionshipSession()
        run_races(session, 8)
        observation = session.observation()
        self.assertEqual(session.state.race_index, 8)
        self.assertEqual(observation["decision_type"], CHAMPIONSHIP_COMPLETE)
        self.assertIsNone(observation["action_schema"])
        self.assertEqual(len(session.trace()), 32)
        with self.assertRaises(ValueError):
            session.submit(stay_action())
        self.assertEqual(session.state.race_index, 8)

    def test_trace_is_json_serializable_and_records_final_transition(self):
        session = ChampionshipSession()
        run_races(session, 1)
        trace = session.trace()
        json.dumps(trace, sort_keys=True)
        final = trace[-1]["state_transition"]
        self.assertEqual(final["race_index_before"], 0)
        self.assertEqual(final["race_index_after"], 1)
        self.assertIn("awarded_points", final)
        self.assertEqual(len(final["classification"]), 8)


if __name__ == "__main__":
    unittest.main()
