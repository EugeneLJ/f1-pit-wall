from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "environment"))

from f1pitwall.championship import (  # noqa: E402
    CALENDAR_FIXTURE,
    TRACK_ARCHETYPES,
    ChampionshipState,
    load_calendar_fixture,
    new_championship_state,
)


class ChampionshipSchemaTests(unittest.TestCase):
    def test_default_state_has_eight_races_and_persistent_fields(self):
        state = new_championship_state()
        self.assertEqual(state.race_index, 0)
        self.assertEqual(len(state.calendar), 8)
        self.assertEqual(len(state.driver_points), 8)
        self.assertEqual(len(state.team_points), 4)
        self.assertEqual(set(state.power_units), set(state.driver_points))
        self.assertEqual(set(state.grid_penalties), set(state.driver_points))
        self.assertEqual(set(state.resource_inventory), set(state.team_points))

    def test_calendar_fixture_loads_synthetic_track_characteristics(self):
        calendar = load_calendar_fixture(CALENDAR_FIXTURE)
        self.assertEqual(len(calendar), 8)
        self.assertEqual({race.archetype for race in calendar}, TRACK_ARCHETYPES)
        for race in calendar:
            self.assertTrue(race.synthetic_placeholder)
            self.assertGreaterEqual(race.power_unit_stress, 0.0)
            self.assertLessEqual(race.power_unit_stress, 1.0)
            self.assertGreaterEqual(race.overtaking_difficulty, 0.0)
            self.assertLessEqual(race.overtaking_difficulty, 1.0)
            self.assertGreaterEqual(race.tyre_degradation, 0.0)
            self.assertLessEqual(race.tyre_degradation, 1.0)

    def test_json_round_trip_preserves_state(self):
        state = new_championship_state()
        state.race_index = 3
        state.driver_points["Apex A"] = 42
        state.team_points["Apex"] = 71
        state.power_units["Apex A"]["ICE"].wear = 0.375
        state.power_units["Apex A"]["ICE"].replacements = 1
        state.grid_penalties["Apex A"] = 5
        state.resource_inventory["Apex"]["component_spares"] = 1
        restored = ChampionshipState.from_json(state.to_json())
        self.assertEqual(restored, state)

    def test_validation_rejects_invalid_state(self):
        valid = new_championship_state().to_dict()
        invalid_cases = []
        bad_index = copy.deepcopy(valid)
        bad_index["race_index"] = 9
        invalid_cases.append(bad_index)
        bad_wear = copy.deepcopy(valid)
        bad_wear["power_units"]["Apex A"]["ICE"]["wear"] = 1.01
        invalid_cases.append(bad_wear)
        bad_driver = copy.deepcopy(valid)
        del bad_driver["driver_points"]["Apex B"]
        invalid_cases.append(bad_driver)
        unknown_field = copy.deepcopy(valid)
        unknown_field["future_result"] = 25
        invalid_cases.append(unknown_field)

        for payload in invalid_cases:
            with self.assertRaises(ValueError):
                ChampionshipState.from_json(json.dumps(payload))

    def test_calendar_validation_rejects_unmarked_or_out_of_range_values(self):
        valid = json.loads(CALENDAR_FIXTURE.read_text(encoding="utf-8"))
        cases = []
        unmarked = copy.deepcopy(valid)
        unmarked["races"][0]["synthetic_placeholder"] = False
        cases.append(unmarked)
        out_of_range = copy.deepcopy(valid)
        out_of_range["races"][0]["power_unit_stress"] = 1.1
        cases.append(out_of_range)
        wrong_count = copy.deepcopy(valid)
        wrong_count["races"].pop()
        cases.append(wrong_count)

        for index, payload in enumerate(cases):
            path = Path(self.id().replace(".", "_") + f"_{index}.json")
            try:
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_calendar_fixture(path)
            finally:
                path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
