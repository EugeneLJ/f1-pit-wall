from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "environment"))

from f1pitwall.engine import DECISION_LAPS, SEED, SEGMENT_LENGTH, new_state, observation, step  # noqa: E402


class LegacyP0RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT / "configs" / "legacy_p0.json"
        cls.fixture = json.loads(path.read_text(encoding="utf-8"))

    def grade(self, payload: object | None) -> tuple[float, dict]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            submission = root / "actions.json"
            reward = root / "reward.txt"
            report = root / "report.json"
            if payload is not None:
                submission.write_text(json.dumps(payload), encoding="utf-8")
            env = os.environ | {"F1_SUBMISSION_PATH": str(submission),
                                "F1_REWARD_PATH": str(reward),
                                "F1_REPORT_PATH": str(report)}
            subprocess.run([sys.executable, str(ROOT / "tests" / "grade.py")],
                           env=env, check=False)
            return float(reward.read_text()), json.loads(report.read_text())

    def test_fixture_matches_legacy_engine_contract(self):
        self.assertEqual(self.fixture["configuration"], "legacy_p0")
        self.assertEqual(self.fixture["seed"], SEED)
        self.assertEqual(self.fixture["decision_laps"], list(DECISION_LAPS))
        self.assertEqual(self.fixture["segment_length"], SEGMENT_LENGTH)

    def test_oracle_result_and_major_state_transition(self):
        oracle = self.fixture["oracle"]
        state = new_state(self.fixture["seed"])
        self.assertEqual(observation(state)["track_status"], oracle["event_history"][0])
        step(state, oracle["actions"][0])
        next_observation = observation(state)
        self.assertEqual(next_observation["lap"], 12)
        self.assertEqual(next_observation["drivers"]["driver_a"]["compound"], "MEDIUM")
        self.assertEqual(next_observation["drivers"]["driver_a"]["tyre_age"], 4)

        reward, report = self.grade({"version": 2, "actions": oracle["actions"]})
        self.assertEqual(report["event_history"], oracle["event_history"])
        self.assertEqual(report["constructors_points"], oracle["constructors_points"])
        self.assertEqual(reward, oracle["reward"])

    def test_recorded_baselines_remain_fixed(self):
        stay = [{"driver_a": "STAY", "driver_b": "STAY"}] * 3
        pit = [{"driver_a": "PIT", "driver_b": "PIT"}] * 3
        for name, actions in (("do_nothing", stay), ("pit_spam", pit)):
            expected = self.fixture["baselines"][name]
            reward, report = self.grade({"version": 2, "actions": actions})
            self.assertEqual(report["constructors_points"], expected["constructors_points"])
            self.assertAlmostEqual(reward, expected["reward"], places=8)

    def test_invalid_legacy_submissions_still_score_zero(self):
        actions = self.fixture["oracle"]["actions"]
        cases = [
            {"version": 2, "actions": actions[:2]},
            {"version": 2, "actions": actions, "reward": 1.0},
        ]
        for payload in cases:
            reward, report = self.grade(payload)
            self.assertEqual(reward, 0.0)
            self.assertFalse(report["valid"])


if __name__ == "__main__":
    unittest.main()
