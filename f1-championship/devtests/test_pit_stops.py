"""B2 level (a) tests: track pit loss, shared crew queue, out-lap warm-up."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK / "src"))

from f1pitwall import coefficients as coef  # noqa: E402
from f1pitwall import engine  # noqa: E402
from f1pitwall.championship import RaceEntry, new_championship_state  # noqa: E402
from f1pitwall.championship_adapter import race_config  # noqa: E402
from f1pitwall.championship_contract import ChampionshipSession  # noqa: E402
from f1pitwall.championship_transition import initial_inventory  # noqa: E402

STAY = {"driver_a": "STAY", "driver_b": "STAY"}


def race(coeffs=coef.DEFAULT, archetype="mixed", events=("GREEN", "GREEN", "GREEN"), grid=None):
    config = {"grid": grid or list(engine.LEGACY_CAR_NAMES), "pace": dict(engine.LEGACY_BASE_PACE),
              "overtaking": coeffs["track_performance"]["overtaking"], "overtaking_difficulty": 0.5,
              "tyres": coef.tyre_model(coeffs), "pit": coef.pit_model(archetype, coeffs), "events": list(events)}
    return engine.new_state(3, config)


def car(state, name):
    return next(c for c in state["cars"] if c["name"] == name)


def elapsed_after_first(state, action):
    engine.step(state, action)
    return {c["name"]: c["elapsed"] for c in state["cars"]}


class PitLossTests(unittest.TestCase):
    def test_pit_loss_depends_on_track_and_status(self):
        table = coef.DEFAULT["pit_stops"]["loss_green_sec_by_archetype"]
        street, fast = race(archetype="street"), race(archetype="high_speed")
        self.assertEqual(engine.pit_loss(street, "GREEN"), table["street"])
        self.assertGreater(engine.pit_loss(street, "GREEN"), engine.pit_loss(fast, "GREEN"))
        self.assertLess(engine.pit_loss(street, "SC"), engine.pit_loss(street, "VSC"))
        self.assertLess(engine.pit_loss(street, "VSC"), engine.pit_loss(street, "GREEN"))

    def test_track_ablation_equalizes_loss(self):
        flat = coef.ablate(coef.DEFAULT, "pit_loss_by_track")
        self.assertEqual(engine.pit_loss(race(flat, "street"), "GREEN"), engine.pit_loss(race(flat, "high_speed"), "GREEN"))

    def test_pit_costs_the_track_loss_on_the_road(self):
        stay = elapsed_after_first(race(archetype="street"), STAY)["Apex B"]
        pit = elapsed_after_first(race(archetype="street"), {"driver_a": "STAY", "driver_b": "PIT_HARD"})["Apex B"]
        # B pits from MEDIUM age 8 to a fresh HARD: lap gain is small, loss dominates
        self.assertGreater(pit - stay, engine.pit_loss(race(archetype="street"), "GREEN") - 3.0)


class SharedCrewTests(unittest.TestCase):
    def test_second_arrival_waits_regardless_of_driver_label(self):
        queue = coef.DEFAULT["pit_stops"]["double_stack_queue_sec"]
        # Default grid: Apex A ahead of Apex B -> B waits
        both = elapsed_after_first(race(), {"driver_a": "PIT_HARD", "driver_b": "PIT_HARD"})
        alone = elapsed_after_first(race(), {"driver_a": "STAY", "driver_b": "PIT_HARD"})
        self.assertAlmostEqual(both["Apex B"] - alone["Apex B"], queue, delta=0.8)
        # Swap grid slots so Apex B is ahead -> A waits
        grid = list(engine.LEGACY_CAR_NAMES)
        ia, ib = grid.index("Apex A"), grid.index("Apex B")
        grid[ia], grid[ib] = grid[ib], grid[ia]
        both = elapsed_after_first(race(grid=grid), {"driver_a": "PIT_HARD", "driver_b": "PIT_HARD"})
        alone = elapsed_after_first(race(grid=grid), {"driver_a": "PIT_HARD", "driver_b": "STAY"})
        self.assertAlmostEqual(both["Apex A"] - alone["Apex A"], queue, delta=0.8)

    def test_observation_says_who_is_serviced_first(self):
        self.assertEqual(engine.observation(race())["pit"]["if_both_pit_serviced_first"], "driver_a")

    def test_queue_ablation_and_rival_teams_queue_too(self):
        none = coef.ablate(coef.DEFAULT, "double_stack_queue")
        both = elapsed_after_first(race(none), {"driver_a": "PIT_HARD", "driver_b": "PIT_HARD"})
        alone = elapsed_after_first(race(none), {"driver_a": "STAY", "driver_b": "PIT_HARD"})
        self.assertAlmostEqual(both["Apex B"], alone["Apex B"], delta=0.8)
        # Rival team: both Nova cars (Rival 2 SOFT/8, Rival 4 MEDIUM/7) stop under SC; Rival 4 arrives second.
        queue = coef.DEFAULT["pit_stops"]["double_stack_queue_sec"]
        with_q = elapsed_after_first(race(events=("SC", "GREEN", "GREEN")), STAY)
        no_q = elapsed_after_first(race(none, events=("SC", "GREEN", "GREEN")), STAY)
        self.assertAlmostEqual(with_q["Rival 4"] - no_q["Rival 4"], queue, delta=0.8)
        self.assertAlmostEqual(with_q["Rival 2"], no_q["Rival 2"], delta=0.8)


class WarmupTests(unittest.TestCase):
    def test_harder_compounds_warm_up_slower_and_ablation_removes_it(self):
        warm = coef.DEFAULT["pit_stops"]["out_lap_warmup_sec"]
        self.assertLess(warm["SOFT"], warm["MEDIUM"])
        self.assertLess(warm["MEDIUM"], warm["HARD"])
        with_w = elapsed_after_first(race(), {"driver_a": "PIT_HARD", "driver_b": "STAY"})["Apex A"]
        without = elapsed_after_first(race(coef.ablate(coef.DEFAULT, "tyre_warmup")),
                                      {"driver_a": "PIT_HARD", "driver_b": "STAY"})["Apex A"]
        self.assertAlmostEqual(with_w - without, warm["HARD"], places=6)

    def test_warmup_applies_only_to_the_out_lap_segment(self):
        state = race()
        engine.step(state, {"driver_a": "PIT_HARD", "driver_b": "STAY"})
        self.assertNotIn("out_lap", car(state, "Apex A"))


class PublicPitInformationTests(unittest.TestCase):
    def test_calendar_and_race_observation_publish_pit_losses(self):
        session = ChampionshipSession(base_seed=5)
        obs = session.observation()
        self.assertIn("pit_loss_green_sec", obs["championship"]["remaining_calendar"][0])
        decisions = [{"driver": d, "component": c, "action": "USE"}
                     for d, s in obs["controlled_drivers"].items() for c in s["components"]]
        obs = session.submit({"type": "COMPONENT_DECISION", "decisions": decisions})
        self.assertIn("loss_sec", obs["race_progress"]["pit"])

    def test_race_config_carries_track_pit_model(self):
        entry = RaceEntry(name="S", archetype="street", power_unit_stress=0.4, overtaking_difficulty=0.9,
                          tyre_degradation=0.4, synthetic_placeholder=True)
        state = new_championship_state(calendar=[entry], resource_inventory=initial_inventory(coef.DEFAULT))
        self.assertEqual(race_config(state)["pit"]["loss_sec"]["GREEN"],
                         coef.DEFAULT["pit_stops"]["loss_green_sec_by_archetype"]["street"])


if __name__ == "__main__":
    unittest.main()
