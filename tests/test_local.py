from __future__ import annotations
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "environment"))
from f1pitwall.engine import evaluate_action  # noqa: E402


class VerticalSliceTests(unittest.TestCase):
    def grade(self, payload: object | None) -> tuple[float, dict]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            submission, reward, report = root / "action.json", root / "reward.txt", root / "report.json"
            if payload is not None:
                submission.write_text(json.dumps(payload), encoding="utf-8")
            env = os.environ | {"F1_SUBMISSION_PATH": str(submission),
                                "F1_REWARD_PATH": str(reward), "F1_REPORT_PATH": str(report)}
            subprocess.run([sys.executable, str(ROOT / "tests" / "grade.py")], env=env, check=False)
            return float(reward.read_text()), json.loads(report.read_text())

    def test_oracle(self):
        reward, report = self.grade({"driver_a": "PIT", "driver_b": "STAY"})
        self.assertEqual(report["constructors_points"], 28)
        self.assertEqual(reward, 1.0)

    def test_do_nothing_is_lower(self):
        reward, report = self.grade({"driver_a": "STAY", "driver_b": "STAY"})
        self.assertEqual(report["constructors_points"], 20)
        self.assertAlmostEqual(reward, 20 / 28, places=7)

    def test_stop_early_missing_submission(self):
        reward, report = self.grade(None)
        self.assertEqual(reward, 0.0)
        self.assertFalse(report["valid"])

    def test_invalid_and_agent_score_are_ignored(self):
        reward, report = self.grade({"driver_a": "PIT", "driver_b": "FLY", "reward": 1})
        self.assertEqual(reward, 0.0)
        self.assertFalse(report["valid"])

    def test_actions_change_real_points(self):
        scores = {(a, b): evaluate_action({"driver_a": a, "driver_b": b})["constructors_points"]
                  for a in ("PIT", "STAY") for b in ("PIT", "STAY")}
        self.assertEqual(scores[("PIT", "STAY")], 28)
        self.assertGreater(len(set(scores.values())), 1)

    def test_all_rewards_are_finite_and_bounded(self):
        for a in ("PIT", "STAY"):
            for b in ("PIT", "STAY"):
                reward, _ = self.grade({"driver_a": a, "driver_b": b})
                self.assertTrue(math.isfinite(reward))
                self.assertGreaterEqual(reward, 0.0)
                self.assertLessEqual(reward, 1.0)


if __name__ == "__main__":
    unittest.main()
