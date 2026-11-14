"""B8 tests: opt-in FIA-2026-based PU rules (benchmark 2.1.0)."""

from __future__ import annotations

import json
import random
import sys
import unittest
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK / "src"))
sys.path.insert(0, str(TASK))

from f1pitwall import coefficients as coef  # noqa: E402
from f1pitwall import pu_rules  # noqa: E402
from f1pitwall.championship import TEAM_DRIVERS, new_championship_state  # noqa: E402
from f1pitwall.championship_transition import (available_component_actions, initial_inventory,  # noqa: E402
                                               prepare_race, replacement_cost)
from f1pitwall.integrated import config as C  # noqa: E402
from f1pitwall.integrated import policies as P  # noqa: E402
from f1pitwall.integrated import session as S  # noqa: E402
from f1pitwall.integrated import verify as V  # noqa: E402

FIA = pu_rules.with_fia_pu_rules(coef.DEFAULT)


def fia_state():
    return new_championship_state(resource_inventory=initial_inventory(FIA))


def decisions(state, replace=()):
    return [{"driver": d, "component": c, "action": "REPLACE" if (d, c) in replace else "USE"}
            for d, comps in state.power_units.items() for c in comps]


class RulesTests(unittest.TestCase):
    def test_default_rules_untouched(self):
        self.assertNotIn("pu_rules", coef.DEFAULT)
        state = new_championship_state(resource_inventory=initial_inventory(coef.DEFAULT))
        self.assertNotIn("stock:ICE", json.dumps(state.resource_inventory))
        self.assertEqual(replacement_cost(state, "Apex A", "ICE"), {"uses_free_unit": True, "grid_drop": 0})

    def test_fixture_matches_verified_text_and_declared_scaling(self):
        v = pu_rules.RULES["verified_rules_used"]
        self.assertEqual((v["first_additional_element_places"], v["subsequent_additional_element_places"],
                          v["back_of_grid_above_places"]), (10, 5, 15))
        self.assertEqual(pu_rules.scaled_places_check(), pu_rules.RULES["synthetic"]["field_size_scaling"]["places"])
        self.assertEqual(pu_rules.scaled_allocation_check(), pu_rules.RULES["synthetic"]["allocation_per_driver"])
        self.assertIn("SYNTHETIC", pu_rules.RULES["synthetic"]["label"])

    def test_penalty_sequence_per_type_and_cumulative(self):
        state = fia_state()
        self.assertEqual(pu_rules.element_penalty(2, "ICE"), 0)   # within allocation
        self.assertEqual(pu_rules.element_penalty(3, "ICE"), 4)   # first additional (FIA 10, scaled)
        self.assertEqual(pu_rules.element_penalty(4, "ICE"), 2)   # next additional (FIA 5, scaled)
        for comp in state.power_units["Apex A"].values():
            comp.replacements = 1
        self.assertEqual(pu_rules.penalty_for(state, "Apex A", ["ICE", "turbo", "energy_store"]), 12)
        prepare_race(state, decisions(state, {("Apex A", "ICE"), ("Apex A", "turbo")}), FIA)
        self.assertEqual(state.grid_penalties["Apex A"], 8)
        self.assertEqual(state.resource_inventory["Apex"]["stock:ICE"], 2)

    def test_stock_and_legality(self):
        state = fia_state()
        state.resource_inventory["Apex"]["stock:ICE"] = 0
        state.power_units["Apex A"]["ICE"].wear = 0.95
        self.assertEqual(available_component_actions(state, "Apex A", FIA)["ICE"], ["USE"])  # runs on, no stock
        self.assertEqual(available_component_actions(state, "Apex B", FIA)["ICE"], ["USE"])
        state.resource_inventory["Apex"]["stock:turbo"] = 1
        with self.assertRaises(ValueError):
            pu_rules.check_team_stock(state, "Apex", {"turbo": 2})
        with self.assertRaises(ValueError):
            prepare_race(state, decisions(state, {("Apex A", "turbo"), ("Apex B", "turbo")}), FIA)


class GridTests(unittest.TestCase):
    Q = ["A", "B", "C", "D", "E", "F", "G", "H"]

    def test_examples(self):
        self.assertEqual(pu_rules.fia_grid(self.Q, {}), self.Q)
        self.assertEqual(pu_rules.fia_grid(self.Q, {"A": 4}), ["B", "C", "D", "E", "A", "F", "G", "H"])
        # two drivers reach the same temporary slot: the slower one keeps it, the other goes ahead
        self.assertEqual(pu_rules.fia_grid(self.Q, {"A": 4, "C": 2}), ["B", "D", "E", "A", "C", "F", "G", "H"])
        # above the threshold: behind everyone, in qualifying order
        self.assertEqual(pu_rules.fia_grid(self.Q, {"B": 8, "A": 6, "H": 2}), ["C", "D", "E", "F", "G", "H", "A", "B"])
        # temporary slot beyond the field: moves up to fill the gap at the back
        self.assertEqual(pu_rules.fia_grid(self.Q, {"G": 4}), ["A", "B", "C", "D", "E", "F", "H", "G"])

    def test_random_grids_are_permutations_and_monotone(self):
        rng = random.Random(7)
        for _ in range(2000):
            pen = {d: rng.choice((0, 0, 0, 2, 4, 6, 8, 12)) for d in self.Q}
            grid = pu_rules.fia_grid(self.Q, pen)
            self.assertEqual(sorted(grid), sorted(self.Q))
            clean = [d for d in self.Q if pen[d] == 0]
            self.assertEqual([d for d in grid if pen[d] == 0], clean)  # unpenalised keep their order
            for d in self.Q:  # a penalised driver never ends ahead of an unpenalised one it qualified behind
                if 0 < pen[d] <= 5:
                    for c in clean:
                        if self.Q.index(c) < self.Q.index(d):
                            self.assertLess(grid.index(c), grid.index(d))
            backs = [d for d in self.Q if pen[d] > 5]
            self.assertEqual(grid[len(grid) - len(backs):], backs)


class SeasonTests(unittest.TestCase):
    def test_two_team_season_under_2_1_0(self):
        cfg = C.with_version(C.two_team(1), "2.1.0")
        self.assertNotEqual(cfg.config_hash(), C.two_team(1).config_hash())
        s = S.IntegratedSession(cfg, 31)
        pols = {"McLearn Racing": P.scripted("baseline"), "Red Bool Racing": P.scripted("event_aware")}
        replaced = {}
        while s.decision_type != S.CHAMPIONSHIP_COMPLETE:
            tick = s.tick_id
            for label in s.teams:
                obs = s.observation(label)
                self.assertEqual(obs["benchmark_version"], "2.1.0")
                text = json.dumps(obs)
                for forbidden in ('"seed"', '"events"', "dnf_uniform"):
                    self.assertNotIn(forbidden, text)
                action = pols[label](obs)
                if obs["decision_type"] == "COMPONENT_DECISION":  # replace the most worn element when legal
                    worst = max(((d, c, i["wear"]) for d, st in obs["controlled_drivers"].items()
                                 for c, i in st["components"].items() if "REPLACE" in i["legal_actions"]),
                                key=lambda x: x[2], default=None)
                    if worst and worst[2] > 0.5:
                        for item in action["decisions"]:
                            if (item["driver"], item["component"]) == worst[:2]:
                                item["action"] = "REPLACE"
                                replaced[(label, worst[1])] = replaced.get((label, worst[1]), 0) + 1
                s.submit(label, tick, action)
        state = s.state
        for team, drivers in TEAM_DRIVERS.items():  # inventory conservation
            for comp in ("ICE", "turbo", "energy_store"):
                used = sum(state.power_units[d][comp].replacements for d in drivers)
                self.assertEqual(state.resource_inventory[team][f"stock:{comp}"], 3 - used)
                self.assertGreaterEqual(state.resource_inventory[team][f"stock:{comp}"], 0)
        for team, drivers in TEAM_DRIVERS.items():  # driver/team point consistency
            self.assertEqual(state.team_points[team], sum(state.driver_points[d] for d in drivers))
        self.assertEqual(len(s.race_results), 8)
        out = V.replay(cfg, 31, s.journal)
        self.assertEqual(out["standings"], s.standings())
        self.assertTrue(replaced)

    def test_baseline_2_0_1_unchanged_by_hooks(self):
        cfg = C.two_team(1)
        a = S.IntegratedSession(cfg, 12)
        pols = {"McLearn Racing": P.scripted("baseline"), "Red Bool Racing": P.scripted("baseline")}
        while a.decision_type != S.CHAMPIONSHIP_COMPLETE:
            tick = a.tick_id
            for label in a.teams:
                obs = a.observation(label)
                self.assertEqual(obs["benchmark_version"], "2.0.1")
                self.assertNotIn("stock:", json.dumps(obs))
                a.submit(label, tick, pols[label](obs))
        V.replay(cfg, 12, a.journal)


if __name__ == "__main__":
    unittest.main()
