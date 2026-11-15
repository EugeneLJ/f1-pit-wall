from __future__ import annotations

import copy
from dataclasses import replace
import unittest

from devtests.test_b6_integration import act, scene
from devtests.test_v22_m6_integration import drive
from f1pitwall.integrated import config as C
from f1pitwall.integrated import race as ir
from f1pitwall.integrated import session as S
from f1pitwall.integrated import verify as V


class M2IntegrationTests(unittest.TestCase):
    def test_defender_incurs_actual_existing_buffer_effect_and_replays(self):
        base, defended = scene(), scene()
        assignment = {"Orion": {"driver_b": "DEFENDER"}}
        ir.step(base, act())
        ir.step(defended, act(), tendency_map=assignment)
        baseline = next(car for car in base["cars"] if car["name"] == "Rival 3")["elapsed"]
        changed = next(car for car in defended["cars"] if car["name"] == "Rival 3")["elapsed"]
        self.assertAlmostEqual(changed - baseline, 0.35, places=6)
        repeated = scene()
        ir.step(repeated, act(), tendency_map=assignment)
        self.assertEqual([
            (car["name"], car["elapsed"], car["compound"], car["tyre_age"])
            for car in defended["cars"]], [
            (car["name"], car["elapsed"], car["compound"], car["tyre_age"])
            for car in repeated["cars"]])

    def test_conservative_suppresses_actual_pass_without_teleporting_result(self):
        base, guarded = scene(), scene()
        for race in (base, guarded):
            for car in race["cars"]:
                if car["name"] == "Rival 3":
                    car["base_pace"] = 50.0
                elif car["name"] == "Apex B":
                    car["base_pace"] = 90.0
        ir.step(base, act())
        ir.step(guarded, act(), tendency_map={"Orion": {"driver_b": "CONSERVATIVE"}})
        base_order = [car["name"] for car in sorted(base["cars"], key=lambda value: value["elapsed"])]
        guarded_order = [car["name"] for car in sorted(guarded["cars"], key=lambda value: value["elapsed"])]
        self.assertLess(base_order.index("Rival 3"), base_order.index("Apex B"))
        self.assertGreater(guarded_order.index("Rival 3"), guarded_order.index("Apex B"))
        self.assertGreater(next(c["elapsed"] for c in guarded["cars"] if c["name"] == "Rival 3"), 0.0)

    def test_opportunist_without_m3_does_not_fabricate_an_attack_bonus(self):
        baseline, opportunist = scene(), scene()
        ir.step(baseline, act())
        ir.step(opportunist, act(), tendency_map={"Orion": {"driver_b": "OPPORTUNIST"}})
        self.assertEqual([car["elapsed"] for car in baseline["cars"]],
                         [car["elapsed"] for car in opportunist["cars"]])

    def test_initialization_is_private_stable_and_absent_when_disabled(self):
        cfg = replace(C.with_version(C.two_team(1), "2.2.0"), m2_tendencies=True)
        session = S.IntegratedSession(cfg, 42, clock=lambda: 0.0)
        for label in session.teams:
            obs = session.observation(label)
            decisions = [{"driver": driver, "component": name, "action": "USE"}
                         for driver, info in obs["controlled_drivers"].items() for name in info["components"]]
            session.submit(label, session.tick_id, {"type": "COMPONENT_DECISION", "decisions": decisions})
        session._m2_tendency_map = session._initialize_m2()
        first = copy.deepcopy(session._m2_tendency_map)
        second = session._initialize_m2()
        self.assertEqual(first, second)
        self.assertNotIn("m2_tendency_map", session.race_state["integrated"])
        serialized = str(session.observation("McLearn Racing"))
        for kind in ("DEFENDER", "OPPORTUNIST", "CONSERVATIVE"):
            self.assertNotIn(kind, serialized)
        self.assertIsNone(S.IntegratedSession(C.two_team(1), 42)._initialize_m2())
        for flag in cfg.as_dict():
            self.assertNotIn("secret", flag.lower())

    def test_two_full_seasons_replay_exactly_with_m2_enabled(self):
        cfg = replace(C.with_version(C.two_team(1), "2.2.0"), m2_tendencies=True)
        for seed in (1, 2):
            driver = drive(cfg, seed)
            result = V.replay(cfg, seed, copy.deepcopy(driver.journal), require_complete=True)
            self.assertTrue(result["complete"])
            self.assertEqual(result["standings"], driver.standings())


if __name__ == "__main__":
    unittest.main()
