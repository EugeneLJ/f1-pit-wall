"""C5 practice/qualifying weekend integrated into the session (opt-in 2.2.0, c5_weekend)."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TASK / "src"), str(TASK)]

from f1pitwall import engine  # noqa: E402
from f1pitwall.integrated import config as C  # noqa: E402
from f1pitwall.integrated import session as S  # noqa: E402
from f1pitwall.integrated import verify as V  # noqa: E402
from f1pitwall.integrated import weekend as W  # noqa: E402
from f1pitwall.integrated.policies import scripted  # noqa: E402
from track_c import c5  # noqa: E402

SEED = json.loads((TASK / "tests" / "hidden_seed.json").read_text())["base_seed"]
RUNS = TASK / "analysis" / "results" / "reference_runs"
BASE = C.solo_coordination(engineers="CHIEF_ONLY", chief={"provider": "harbor_agent"})
C5CFG = C.with_c5_weekend(BASE)
RACE = scripted("baseline")


def practice(a=("QUALI_SIM", "low_drag", 6), b=("LONG_RUN", "high_downforce", 6)):
    return {"type": "PRACTICE", "driver_a": dict(zip(("program", "setup_id", "laps"), a)),
            "driver_b": dict(zip(("program", "setup_id", "laps"), b))}


def qualifying(a="low_drag", b="high_downforce", plan_a="TWO_RUN", plan_b="ONE_RUN"):
    return {"type": "QUALIFYING", "driver_a": {"setup_id": a, "run_plan": plan_a},
            "driver_b": {"setup_id": b, "run_plan": plan_b}}


def play(cfg, prac=practice, qual=qualifying, seed=SEED, until=None):
    s = S.IntegratedSession(cfg, seed, clock=lambda: 0.0)
    while s.decision_type != S.CHAMPIONSHIP_COMPLETE and (until is None or not until(s)):
        obs = s.observation("Apex")
        if s.decision_type == S.PRACTICE:
            action = prac()
        elif s.decision_type == S.QUALIFYING:
            action = qual()
        else:
            action = RACE(obs)
        s.submit("Apex", s.tick_id, action)
    return s


class Config(unittest.TestCase):
    def test_flag_requires_2_2_0_and_is_off_by_default(self):
        self.assertFalse(BASE.c5_weekend)
        with self.assertRaises(ValueError):
            C.IntegratedConfig(BASE.mode, list(BASE.teams), benchmark_version="2.1.0", c5_weekend=True).validate()
        self.assertEqual(C5CFG.benchmark_version, "2.2.0")
        self.assertNotIn("c5_weekend", C.with_version(BASE, "2.1.0").as_dict())  # existing config hashes unchanged
        self.assertEqual(C.IntegratedConfig.from_dict(C5CFG.as_dict()).c5_weekend, True)


class Disabled(unittest.TestCase):
    def test_committed_2_1_0_harbor_journals_still_replay_exactly(self):
        cfg = C.with_version(BASE, "2.1.0")
        for run, points in (("v21-oracle-01", 289), ("v21-gemini-01", 279)):
            journal = [json.loads(x) for x in (RUNS / run / "evidence" / "journal.jsonl").read_text().splitlines() if x]
            self.assertEqual(V.replay(cfg, SEED, journal)["standings"]["team_points"]["Apex"], points, run)

    def test_2_2_0_without_c5_plays_exactly_like_2_1_0(self):
        a = play(C.with_version(BASE, "2.1.0"))
        b = play(C.with_version(BASE, "2.2.0"))
        self.assertEqual(a.standings(), b.standings())
        self.assertEqual([e["submissions"] for e in a.journal], [e["submissions"] for e in b.journal])
        self.assertEqual([r["classification"] for r in a.race_results], [r["classification"] for r in b.race_results])

    def test_engine_without_car_deg_factor_is_unchanged(self):
        state = engine.new_state(7, {"grid": [c["name"] for c in engine._legacy_cars()],
                                     "pace": engine.LEGACY_BASE_PACE})
        self.assertFalse(any("deg_factor" in car for car in state["cars"]))


class Weekend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = play(C5CFG)

    def test_phase_machine_and_tick_count(self):
        types = [e["decision_type"] for e in self.session.journal]
        self.assertEqual(len(types), 8 * (1 + 2 + 1 + 14))
        self.assertEqual(types[:5], ["COMPONENT_DECISION", "PRACTICE", "PRACTICE", "QUALIFYING", "RACE_STRATEGY"])

    def test_deterministic_and_exactly_replayable(self):
        again = play(C5CFG)
        self.assertEqual([e["entry_hash"] for e in again.journal], [e["entry_hash"] for e in self.session.journal])
        result = V.replay(C5CFG, SEED, self.session.journal)
        self.assertEqual(result["standings"], self.session.standings())

    def test_tampered_practice_or_qualifying_action_fails_replay(self):
        for kind, field, value in (("PRACTICE", "laps", 7), ("QUALIFYING", "setup_id", "balanced")):
            journal = copy.deepcopy(self.session.journal)
            entry = next(e for e in journal if e["decision_type"] == kind)
            entry["submissions"]["Apex"]["action"]["driver_a"][field] = value
            with self.assertRaises(V.ReplayError):
                V.replay(C5CFG, SEED, journal)

    def test_qualifying_order_is_the_race_grid_and_setups_set_race_pace(self):
        s = play(C5CFG, until=lambda s: s.decision_type == S.RACE_STRATEGY)
        wk = s._weekend
        order = wk.qualifying_result["order"]
        self.assertEqual(s._active.starting_grid, order)  # race 1 has no grid penalties
        published = s.race_state["config"]["pace"]
        mods = {}
        for label, slot in s.slot_of.items():
            choice = {d: wk.setups[label][W._seat(d)] for d in ("Apex A", "Apex B")}
            sealed = c5.make_parc_ferme_choice(choice, rng_key=wk._key, weekend_id=wk.weekend_id,
                                               archetype=wk.archetype, team=slot)
            mods = c5.race_modifiers(sealed)
        cars = {c["name"]: c for c in s.race_state["cars"]}
        from f1pitwall.championship_adapter import CHAMPIONSHIP_TO_ENGINE_DRIVER, car_performance
        for driver, mod in mods.items():
            name = CHAMPIONSHIP_TO_ENGINE_DRIVER[driver]
            base = car_performance(s.state, driver, s.coeffs)["pace"]
            self.assertAlmostEqual(published[name], base + mod["pace_offset_sec_per_lap"], places=9)
            self.assertAlmostEqual(cars[name]["deg_factor"], mod["deg_multiplier_factor"], places=12)
        rivals = [c for c in s.race_state["cars"] if c["team"] != "Apex"]
        self.assertFalse(any("deg_factor" in c for c in rivals))  # rivals keep the neutral default setup

    def test_neutral_weekend_has_no_race_effect(self):
        neutral = lambda: practice(("SETUP_TEST", "balanced", 0), ("SETUP_TEST", "balanced", 0))  # noqa: E731
        s = play(C5CFG, neutral, lambda: qualifying("balanced", "balanced", "ONE_RUN", "ONE_RUN"),
                 until=lambda s: s.decision_type == S.RACE_STRATEGY)
        for car in s.race_state["cars"]:
            self.assertEqual(car.get("deg_factor", 1.0), 1.0)
        from f1pitwall.championship_adapter import ENGINE_TO_CHAMPIONSHIP_DRIVER, car_performance
        for name, pace in s.race_state["config"]["pace"].items():
            self.assertEqual(pace, car_performance(s.state, ENGINE_TO_CHAMPIONSHIP_DRIVER[name], s.coeffs)["pace"])

    def test_hidden_information_never_in_observations(self):
        s = S.IntegratedSession(C5CFG, SEED, clock=lambda: 0.0)
        key = W.weekend_key(SEED, 0)
        texts = []
        while s.decision_type != S.CHAMPIONSHIP_COMPLETE and len(texts) < 40:
            obs = s.observation("Apex")
            texts.append(json.dumps(obs))
            if s.decision_type in (S.PRACTICE, S.QUALIFYING):
                s.submit("Apex", s.tick_id, practice() if s.decision_type == S.PRACTICE else qualifying())
            else:
                s.submit("Apex", s.tick_id, RACE(obs))
        wk = s._weekend
        truths = [c5.core._true_effect(key, wk.weekend_id, "Apex", setup, metric, c5.load_model(wk.archetype))
                  for setup in ("low_drag", "high_downforce")
                  for metric in ("qualifying_pace_offset_sec", "long_run_pace_offset_sec_per_lap", "deg_multiplier_factor")]
        blob = "\n".join(texts)
        self.assertNotIn(str(key), blob)
        for value in truths:
            self.assertNotIn(repr(round(value, 12)), blob)
        for word in ("rng_key", "true_effect", "seed", "deg_factor"):
            self.assertNotIn(f'"{word}"', blob)

    def test_practice_observation_carries_public_information(self):
        s = play(C5CFG, until=lambda s: s.decision_type == S.QUALIFYING)
        obs = s.observation("Apex")
        est = obs["weekend"]["qualifying"]["setup_options"]["low_drag"]
        self.assertGreater(est["qualifying_pace_offset_sec"]["laps_observed"], 0)  # QUALI_SIM laps were run
        self.assertEqual(len(obs["weekend"]["practice_history"]), 2)
        self.assertIn("parc_ferme", obs["action_schema"])

    def test_invalid_weekend_actions_are_rejected_without_state_change(self):
        s = play(C5CFG, until=lambda s: s.decision_type == S.PRACTICE)
        before = s._obs_hash
        for bad in (practice(("QUALI_SIM", "low_drag", 25)), practice(("QUALI_SIM", "rocket", 2)),
                    {"type": "PRACTICE", "driver_a": {}}, qualifying()):
            with self.assertRaises(S.TickError):
                s.submit("Apex", s.tick_id, bad)
        self.assertEqual(s._obs_hash, before)
        self.assertEqual(s.journal[-1]["kind"], "rejected")

    def test_timeout_uses_published_fallback_and_replays(self):
        s = S.IntegratedSession(C5CFG, SEED, clock=lambda: 0.0)
        while s.decision_type != S.CHAMPIONSHIP_COMPLETE:
            s.close_tick(s.tick_id)
        self.assertEqual(V.replay(C5CFG, SEED, s.journal)["standings"], s.standings())
        prac = next(e for e in s.journal if e["decision_type"] == "PRACTICE")["submissions"]["Apex"]
        self.assertEqual(prac["action"]["driver_a"]["laps"], 0)

    def test_two_team_weekend_is_sealed_and_replayable(self):
        cfg = C.with_c5_weekend(C.two_team(2))
        s = S.IntegratedSession(cfg, SEED, clock=lambda: 0.0)
        labels = list(s.teams)
        while s.decision_type != S.CHAMPIONSHIP_COMPLETE:
            for label in labels:
                if s.decision_type == S.PRACTICE:
                    s.submit(label, s.tick_id, practice())
                elif s.decision_type == S.QUALIFYING:
                    s.submit(label, s.tick_id, qualifying())
                else:
                    s.submit(label, s.tick_id, s.fallback_action(label))
        self.assertEqual(V.replay(cfg, SEED, s.journal)["standings"], s.standings())
        obs = S.IntegratedSession(cfg, SEED, clock=lambda: 0.0)
        obs.close_tick(obs.tick_id)
        own = obs.observation(labels[0])["weekend"]
        self.assertEqual(own["team"], obs.slot_of[labels[0]])


if __name__ == "__main__":
    unittest.main()
