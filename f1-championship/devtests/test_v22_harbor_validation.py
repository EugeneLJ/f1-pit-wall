import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
HELPER = ROOT / "scripts" / "validate_v22_task.py"


class V22TaskValidationTests(unittest.TestCase):
    def test_generated_task_verifies_and_resume_does_not_recompute(self):
        expected_reward = 0.40562248995983935
        with tempfile.TemporaryDirectory(prefix="v22-validation-") as tmp:
            root = Path(tmp)
            task = root / "task"
            evidence = root / "evidence"
            completed = subprocess.run([
                sys.executable, str(HELPER), "--dest", str(task), "--output", str(evidence)],
                text=True, capture_output=True, check=False, timeout=120)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads((evidence / "oracle-report.json").read_text())
            self.assertEqual(report["benchmark_version"], "2.2.0")
            self.assertTrue(report["completion"]["complete"])
            self.assertTrue(report["integrity"]["intact"])
            self.assertEqual(report["completion"]["resolved_ticks"], 120)
            self.assertAlmostEqual(report["reward"], expected_reward)
            manifest = json.loads((evidence / "oracle-manifest.json").read_text())
            self.assertEqual(manifest["journal_entries"], 120)
            self.assertEqual(manifest["journal_version"], 2)
            self.assertTrue(manifest["engineer_record_files"])
            first_bytes = (evidence / "oracle-report.json").read_bytes()
            completed = subprocess.run([
                sys.executable, str(HELPER), "--dest", str(task), "--output", str(evidence), "--resume"],
                text=True, capture_output=True, check=False, timeout=120)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("resume_verified_existing", completed.stdout)
            self.assertEqual((evidence / "oracle-report.json").read_bytes(), first_bytes)
            self.assertEqual(json.loads(completed.stdout)["output_sha256"],
                             hashlib.sha256(first_bytes).hexdigest())

    def test_legacy_default_generation_does_not_enable_extensions(self):
        with tempfile.TemporaryDirectory(prefix="v22-legacy-default-") as tmp:
            destination = Path(tmp) / "legacy-task"
            completed = subprocess.run([
                str(ROOT / "scripts" / "make_integrated_task.sh"), str(destination)],
                text=True, capture_output=True, check=False, timeout=120)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            mode = json.loads((destination / "tests" / "mode.json").read_text())
            self.assertEqual(mode["benchmark_version"], "2.0.1")
            for key in ("m2_tendencies", "m6_compliance", "m7_weather"):
                self.assertFalse(mode[key])


if __name__ == "__main__":
    unittest.main()
