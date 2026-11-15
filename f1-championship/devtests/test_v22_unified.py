"""Unified 2.2.0 candidate: C5 + M2 + M6 + M7 together, the runtime axes, and the all-off identity."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TASK / "src"), str(TASK)]

from f1pitwall import weather  # noqa: E402
from f1pitwall.integrated import config as C  # noqa: E402
from f1pitwall.integrated import runtime as R  # noqa: E402
from f1pitwall.integrated import session as S  # noqa: E402
from f1pitwall.integrated import verify as V  # noqa: E402
from f1pitwall.integrated.policies import scripted  # noqa: E402

SEED = json.loads((TASK / "tests" / "hidden_seed.json").read_text())["base_seed"]
BASE = C.solo_coordination(engineers="CHIEF_ONLY", chief={"provider": "harbor_agent"})
ALL = {"m2_tendencies": True, "m6_compliance": True, "m7_weather": True}
UNIFIED = C.with_c5_weekend(C.with_features(C.with_version(BASE, "2.2.0"), ALL))
RACE = scripted("coordinator")
PRACTICE = {"type": "PRACTICE", "driver_a": {"program": "QUALI_SIM", "setup_id": "low_drag", "laps": 6},
            "driver_b": {"program": "LONG_RUN", "setup_id": "high_downforce", "laps": 6}}
QUALI = {"type": "QUALIFYING", "driver_a": {"setup_id": "high_downforce", "run_plan": "TWO_RUN"},
         "driver_b": {"setup_id": "low_drag", "run_plan": "ONE_RUN"}}


def play(cfg, seed=SEED, until=None):
    s = S.IntegratedSession(cfg, seed, clock=lambda: 0.0)
    while s.decision_type != S.CHAMPIONSHIP_COMPLETE and (until is None or not until(s)):
        obs = s.observation("Apex")
        action = PRACTICE if s.decision_type == S.PRACTICE else QUALI if s.decision_type == S.QUALIFYING else RACE(obs)
        s.submit("Apex", s.tick_id, action)
    return s


class Unified(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.season = play(UNIFIED)

    def test_config_keeps_all_four_flags(self):
        d = UNIFIED.as_dict()
        self.assertEqual({k: d.get(k) for k in ("m2_tendencies", "m6_compliance", "m7_weather", "c5_weekend")},
                         {"m2_tendencies": True, "m6_compliance": True, "m7_weather": True, "c5_weekend": True})
        self.assertEqual(C.IntegratedConfig.from_dict(d).as_dict(), d)
        # order of application does not matter
        other = C.with_features(C.with_c5_weekend(C.with_version(BASE, "2.2.0")), ALL)
        self.assertEqual(other.as_dict(), d)

    def test_full_season_phases_deterministic_and_replayable(self):
        types = [e["decision_type"] for e in self.season.journal]
        self.assertEqual(len(types), 144)
        self.assertEqual(types[:5], ["COMPONENT_DECISION", "PRACTICE", "PRACTICE", "QUALIFYING", "RACE_STRATEGY"])
        again = play(UNIFIED)
        self.assertEqual([e["entry_hash"] for e in again.journal], [e["entry_hash"] for e in self.season.journal])
        self.assertEqual(V.replay(UNIFIED, SEED, self.season.journal)["standings"], self.season.standings())

    def test_every_extension_is_live_in_the_unified_season(self):
        s = play(UNIFIED, until=lambda s: s.decision_type == S.RACE_STRATEGY)
        obs = s.observation("Apex")
        self.assertIn("weather", obs["race_progress"])                         # M7
        self.assertIn("m6_driver_objectives", obs["championship"])            # M6
        self.assertIsNotNone(s._m2_tendency_map)                              # M2 (hidden; not in obs)
        self.assertNotIn("tendenc", json.dumps(obs).lower().replace("m2_tendencies", ""))
        self.assertIn("weekend_result", obs)                                  # C5
        self.assertEqual(s._active.starting_grid, s._weekend.qualifying_result["order"])
        self.assertTrue(any("deg_factor" in c for c in s.race_state["cars"]))

    def test_c5_degradation_factor_applies_under_m7_dry_timing(self):
        s = play(UNIFIED, until=lambda s: s.decision_type == S.RACE_STRATEGY)
        state = s.race_state
        car = dict(next(c for c in state["cars"] if c["team"] == "Apex" and c["compound"] in weather.DRY_COMPOUNDS))
        tyres = state["config"]["tyres"]
        ctx_backup = json.dumps(state["config"][weather.WEATHER_KEY])
        if weather._current(state)[2] != 0.0:
            self.skipTest("first segment is wet on this seed")
        a = weather._segment(state, {**car, "deg_factor": 1.0, "tyre_age": 10}, 3, 1.0, 0.0, tyres, 3)
        state["config"][weather.WEATHER_KEY] = json.loads(ctx_backup)
        b = weather._segment(state, {**car, "deg_factor": 1.5, "tyre_age": 10}, 3, 1.0, 0.0, tyres, 3)
        self.assertGreater(b, a)

    def test_all_extensions_off_plays_exactly_like_2_1_0(self):
        a = play(C.with_version(BASE, "2.1.0"))
        off = C.with_features(C.with_version(BASE, "2.2.0"), {})
        b = play(off)
        self.assertEqual(a.standings(), b.standings())
        self.assertEqual([e["submissions"] for e in a.journal], [e["submissions"] for e in b.journal])

    def test_runtime_spec_composes_all_features_with_both_axes(self):
        for rival, replay in (("SCRIPTED", None), ("ADAPTIVE_LLM", None), ("FIXED_REPLAY", "x")):
            for eng in R.ENGINEER_AXIS:
                spec = R.RuntimeSpec(eng, rival, c5_weekend=True, replay_journal=replay, **ALL)
                cfg = R.build_config(spec)
                self.assertTrue(cfg.c5_weekend and cfg.m2_tendencies and cfg.m6_compliance and cfg.m7_weather)
                self.assertEqual(spec.label().split("|")[-4:], ["C5", "M2", "M6", "M7"])

    def test_harbor_build_and_sidecar_verifier_see_all_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "task"
            subprocess.run([str(TASK / "scripts" / "make_integrated_task.sh"), str(dest), "CHIEF_ONLY", "2.2.0", "m2_m6_m7"],
                           check=True, capture_output=True, env={**os.environ, "F1_C5_WEEKEND": "1"})
            mode = json.loads((dest / "tests" / "mode.json").read_text())
            self.assertEqual(mode, json.loads((dest / "environment/sim/secret/mode.json").read_text()))
            self.assertTrue(all(mode[k] for k in ("c5_weekend", "m2_tendencies", "m6_compliance", "m7_weather")))
            self.assertTrue((dest / "environment/sim/track_c/c5").is_dir() and (dest / "environment/sim/track_c/v22").is_dir())
            text = (dest / "instruction.md").read_text()
            self.assertIn("C5 practice and qualifying", text)
            self.assertIn("Additional 2.2.0 rules", text)
            code = ("import sys,json; sys.path[:0]=[sys.argv[1]]\n"
                    "from f1sim.integrated_server import load_mode, task_config, public_rules\n"
                    "cfg=task_config(load_mode(__import__('pathlib').Path(sys.argv[2])))\n"
                    "r=public_rules(cfg); print(json.dumps([cfg.as_dict(), sorted(k for k in r if k in "
                    "('weekend','m2_tendencies','m6_driver_objectives','m7_weather','power_unit_rules'))]))")
            out = subprocess.run([sys.executable, "-c", code, str(dest / "environment/sim"), str(dest / "tests/mode.json")],
                                 check=True, capture_output=True, text=True)
            cfg, rules = json.loads(out.stdout.strip().splitlines()[-1])
            self.assertEqual(cfg, UNIFIED.as_dict())
            self.assertEqual(rules, ["m2_tendencies", "m6_driver_objectives", "m7_weather", "power_unit_rules", "weekend"])


if __name__ == "__main__":
    unittest.main()
