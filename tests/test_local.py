from __future__ import annotations

import copy
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "environment"))
sys.path.insert(0, str(ROOT / "tests"))

from f1pitwall.engine import new_state, observation, run_episode, step  # noqa: E402
from trusted_engine import parse_submission, replay  # noqa: E402

ORACLE = [
    {"driver_a": "PIT", "driver_b": "STAY"},
    {"driver_a": "STAY", "driver_b": "STAY"},
    {"driver_a": "STAY", "driver_b": "PIT"},
]
STAY = [{"driver_a": "STAY", "driver_b": "STAY"}] * 3
PIT = [{"driver_a": "PIT", "driver_b": "PIT"}] * 3


class SequentialRaceTests(unittest.TestCase):
    def grade(self, payload: object | None) -> tuple[float, dict]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            submission, reward, report = root / "actions.json", root / "reward.txt", root / "report.json"
            if payload is not None:
                submission.write_text(json.dumps(payload), encoding="utf-8")
            env = os.environ | {"F1_SUBMISSION_PATH": str(submission),
                                "F1_REWARD_PATH": str(reward), "F1_REPORT_PATH": str(report)}
            subprocess.run([sys.executable, str(ROOT / "tests" / "grade.py")], env=env, check=False)
            return float(reward.read_text()), json.loads(report.read_text())

    def test_oracle(self):
        reward, report = self.grade({"version": 2, "actions": ORACLE})
        self.assertEqual(report["constructors_points"], 23)
        self.assertEqual(reward, 1.0)
        self.assertEqual(report["event_history"], ["GREEN", "GREEN", "SC"])

    def test_do_nothing_and_pit_spam_are_lower(self):
        stay_reward, stay_report = self.grade({"version": 2, "actions": STAY})
        pit_reward, pit_report = self.grade({"version": 2, "actions": PIT})
        self.assertEqual(stay_report["constructors_points"], 16)
        self.assertAlmostEqual(stay_reward, 6 / 13, places=7)
        self.assertEqual(pit_report["constructors_points"], 10)
        self.assertEqual(pit_reward, 0.0)

    def test_stop_early_and_extra_score_field_are_zero(self):
        for payload in (None, {"version": 2, "actions": ORACLE[:2]},
                        {"version": 2, "actions": ORACLE, "reward": 1.0}):
            reward, report = self.grade(payload)
            self.assertEqual(reward, 0.0)
            self.assertFalse(report["valid"])

    def test_state_persists_and_future_event_is_hidden(self):
        state = new_state()
        first = observation(state)
        self.assertEqual(first["lap"], 8)
        self.assertEqual(first["future_track_status"], "hidden")
        step(state, ORACLE[0])
        second = observation(state)
        self.assertEqual(second["lap"], 12)
        self.assertEqual(second["drivers"]["driver_a"]["compound"], "MEDIUM")
        self.assertEqual(second["drivers"]["driver_a"]["tyre_age"], 4)

    def test_public_and_trusted_engines_match_all_strategies(self):
        pairs = [{"driver_a": a, "driver_b": b}
                 for a, b in product(("PIT", "STAY"), repeat=2)]
        for sequence in product(pairs, repeat=3):
            actions = [copy.deepcopy(action) for action in sequence]
            public, trusted = run_episode(actions), replay(parse_submission({"version": 2, "actions": actions}))
            self.assertEqual(public["constructors_points"], trusted["constructors_points"])
            self.assertEqual(public["classification"], trusted["classification"])

    def test_all_rewards_are_finite_and_bounded(self):
        pairs = [{"driver_a": a, "driver_b": b}
                 for a, b in product(("PIT", "STAY"), repeat=2)]
        for sequence in product(pairs, repeat=3):
            reward, _ = self.grade({"version": 2, "actions": list(sequence)})
            self.assertTrue(math.isfinite(reward))
            self.assertGreaterEqual(reward, 0.0)
            self.assertLessEqual(reward, 1.0)


if __name__ == "__main__":
    unittest.main()
