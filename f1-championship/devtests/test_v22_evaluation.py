import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from analysis.v22_m2_m7_eval import DEV_SEEDS, SMOKE_SEEDS, aggregate


ROOT = Path(__file__).parents[1]
ARTIFACTS = ROOT / "analysis" / "results" / "v22"


class EvaluationArtifactTests(unittest.TestCase):
    def check_artifact(self, path, seeds):
        data = json.loads(path.read_text())
        self.assertEqual(data["preregistered_seeds"], list(seeds))
        self.assertEqual([row["seed"] for row in data["rows"]], list(seeds))
        self.assertEqual(data["aggregate"], aggregate(data["rows"]))
        self.assertEqual(data["aggregate"]["replay_failures"], [])
        self.assertEqual(data["api_calls"], 0)
        self.assertFalse(data["actual_model_results"])
        self.assertIsNone(data["official_frontier_reference_gap"])
        self.assertTrue(all("schedule" not in row and "private_type" not in row for row in data["rows"]))
        for row in data["rows"]:
            self.assertNotIn("schedule", row["m2"])
            self.assertNotIn("schedule", row["m7"])
            self.assertNotIn("tendency_assignment", row["m2"]["public_event"])
        self.assertEqual(data["fixture_sha256"]["m2"], "3f2bb4f6df1eddbce3fa611f879988a783062f371a866c32dfcd10bd120cc4a3")
        self.assertEqual(data["fixture_sha256"]["m7"], "af671dfa920d41064aa5336947ab8f1d90b779b85c316097a615565dabea7706")
        return data

    def test_preregistered_seeds_and_outputs_are_disjoint_and_replay_proven(self):
        self.assertEqual(SMOKE_SEEDS, (11, 12))
        self.assertEqual(DEV_SEEDS, (101, 102, 103, 104, 105))
        self.assertFalse(set(SMOKE_SEEDS) & set(DEV_SEEDS))
        smoke = self.check_artifact(ARTIFACTS / "smoke.json", SMOKE_SEEDS)
        dev = self.check_artifact(ARTIFACTS / "development.json", DEV_SEEDS)
        self.assertEqual(smoke["aggregate"]["m7_pit_actions"], 1)
        self.assertEqual(dev["aggregate"]["m7_pit_actions"], 3)
        self.assertEqual(smoke["aggregate"]["m2_public_value_classes"], {"NEAR_TIE": 1, "UNCERTAIN": 1})
        self.assertEqual(dev["aggregate"]["m2_public_value_classes"], {"NEAR_TIE": 4, "UNCERTAIN": 1})

    def test_resume_verifies_original_instead_of_recomputing_or_overwriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "smoke.json"
            original = (ARTIFACTS / "smoke.json").read_bytes()
            destination.write_bytes(original)
            completed = subprocess.run([
                sys.executable, str(ROOT / "analysis" / "v22_m2_m7_eval.py"),
                "--phase", "smoke", "--output", str(destination), "--resume",
            ], cwd=ROOT, capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            summary = json.loads(completed.stdout)
            self.assertTrue(summary["resumed_verified_existing"])
            self.assertEqual(destination.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
