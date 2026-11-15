#!/usr/bin/env python3
"""Offline tests for the 2.1.0 submission demo (no Docker, no API calls).

Run: f1-championship/scripts/py312 -m unittest tests.test_demo_ux -v   (from the repository root)
All inputs are committed genuine 2.1.0 Harbor runs; tampered/incomplete cases are copies of them.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "f1-championship" / "analysis" / "results" / "reference_runs"
SPEC = importlib.util.spec_from_file_location("f1_demo", ROOT / "scripts" / "demo.py")
demo = importlib.util.module_from_spec(SPEC)
sys.modules["f1_demo"] = demo
SPEC.loader.exec_module(demo)


def run_demo(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = demo.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def live_layout(tmp: Path, run: str) -> Path:
    """Copy a committed run into Harbor's live job layout under <run_dir>/harbor-output."""
    run_dir = tmp / "run"
    trial = run_dir / "harbor-output" / "live" / "task__abc"
    (trial / "verifier").mkdir(parents=True)
    (trial / "artifacts" / "evidence" / "f1sim").mkdir(parents=True)
    src = RUNS / run
    shutil.copy2(src / "verifier_report.json", trial / "verifier" / "report.json")
    shutil.copy2(src / "reward.txt", trial / "verifier" / "reward.txt")
    shutil.copy2(src / "harbor_result.json", trial / "result.json")
    for f in (src / "evidence").iterdir():
        shutil.copy2(f, trial / "artifacts" / "evidence" / "f1sim" / f.name)
    return run_dir


def edit_action(run: Path) -> Path:
    journal = run / "evidence" / "journal.jsonl"
    lines = journal.read_text().splitlines()
    idx = next(i for i, line in enumerate(lines) if '"driver_a":"STAY"' in line and i > 20)
    lines[idx] = lines[idx].replace('"driver_a":"STAY"', '"driver_a":"PIT_SOFT"', 1)
    journal.write_text("\n".join(lines) + "\n")
    return journal


class DemoV21(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.task = demo.build_task(Path(cls.tmp.name) / "task", "r2")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def tmpdir(self) -> Path:
        return Path(tempfile.mkdtemp(dir=self.tmp.name))

    # ---------------------------------------------------------- parsing / verification
    def test_recorded_genuine_run_verifies_against_journal_v2(self):
        result = demo.verify(demo.recorded_source("v21-gemini-01"), self.task)
        self.assertTrue(result["verified"], result["errors"])
        self.assertEqual(result["points"], 279)
        replay = result["replay"]
        self.assertEqual(replay["resolved_ticks"], 120)
        self.assertEqual(len(replay["race_results"]), 8)
        self.assertIn("tests/f1pitwall/integrated/verify.py", replay["replay_module"])  # verifier package, not src
        journal_points = [e["race_result"]["team_points"] for e in result["entries"] if "race_result" in e]
        self.assertEqual(journal_points, [r["team_points"] for r in replay["race_results"]])
        rows = demo.race_rows(result)
        self.assertEqual(rows[-1]["cumulative"]["Apex"], 279)
        self.assertEqual(sum(r["apex"] for r in rows), 279)

    def test_reference_and_all_committed_runs_verify(self):
        expected = {"v21-oracle-01": 289, "v21-gemini-01": 279, "v21-gemini-02": 256, "v21-gemini-03": 276, "v21r2-gemini-01": 279}
        for run, points in expected.items():
            result = demo.verify(demo.recorded_source(run), self.task)
            self.assertTrue(result["verified"], (run, result["errors"]))
            self.assertEqual(result["points"], points, run)

    def test_incomplete_intact_run_is_not_verified(self):
        result = demo.verify(demo.recorded_source("v21-probe-stop-01"), self.task)
        self.assertFalse(result["verified"])
        self.assertTrue(result["intact"])
        self.assertTrue(any("season complete" in e for e in result["errors"]))

    def test_tampered_journal_fails(self):
        run = self.tmpdir() / "tampered"
        shutil.copytree(RUNS / "v21-gemini-01", run)
        edit_action(run)
        result = demo.verify(demo.recorded_source(run), self.task)
        self.assertFalse(result["verified"])
        self.assertTrue(any("SHA-256" in e for e in result["errors"]))

    def test_forged_manifest_still_fails_replay(self):
        """Re-hash the manifest after editing an action: the authoritative replay must reject it."""
        run = self.tmpdir() / "forged"
        shutil.copytree(RUNS / "v21-gemini-01", run)
        journal = edit_action(run)
        manifest = json.loads((run / "evidence" / "manifest.json").read_text())
        manifest["journal_sha256"] = hashlib.sha256(journal.read_bytes()).hexdigest()
        (run / "evidence" / "manifest.json").write_text(json.dumps(manifest))
        result = demo.verify(demo.recorded_source(run), self.task)
        self.assertFalse(result["verified"])
        self.assertTrue(any("Authoritative replay" in e for e in result["errors"]))

    def test_reward_mismatch_fails_in_live_layout(self):
        run_dir = live_layout(self.tmpdir(), "v21-oracle-01")
        (run_dir / "harbor-output" / "live" / "task__abc" / "verifier" / "reward.txt").write_text("1.00000000\n")
        result = demo.verify(demo.live_source(run_dir), self.task)
        self.assertFalse(result["verified"])
        self.assertTrue(any("reward.txt" in e for e in result["errors"]))

    def test_inflated_report_points_fail(self):
        run = self.tmpdir() / "inflated"
        shutil.copytree(RUNS / "v21-gemini-01", run)
        report = json.loads((run / "verifier_report.json").read_text())
        report["normalization"]["P"] = 300
        report["performance"]["apex_constructors_points"] = 300
        report["reward"] = (300 - 92) / (344 - 92)
        (run / "verifier_report.json").write_text(json.dumps(report))
        result = demo.verify(demo.recorded_source(run), self.task)
        self.assertFalse(result["verified"])
        self.assertTrue(any("Authoritative replay" in e for e in result["errors"]))

    def test_wrong_version_fails(self):
        run = self.tmpdir() / "version"
        shutil.copytree(RUNS / "v21-gemini-01", run)
        report = json.loads((run / "verifier_report.json").read_text())
        report["benchmark_version"] = "1.1.0"
        (run / "verifier_report.json").write_text(json.dumps(report))
        self.assertFalse(demo.verify(demo.recorded_source(run), self.task)["verified"])

    # ---------------------------------------------------------- end-to-end finalize
    def test_recorded_finalize_renders_verified_report(self):
        run_dir = self.tmpdir() / "out"
        code, out, err = run_demo("finalize", "--mode", "recorded", "--run", "v21-gemini-01", "--run-dir", str(run_dir))
        self.assertEqual(code, 0, err)
        page = (run_dir / "report.html").read_text()
        for needle in ("F1 Championship Strategist", "A Long-Horizon AI Strategy Benchmark", "Recorded replay",
                       "Championship progression", "Eight-race timeline", "Race 7 Safety Car", "PIT_HARD/STAY",
                       "Verified evidence", ">279<", ">289<", "+10"):
            self.assertIn(needle, page)
        self.assertNotIn("Live · fresh Harbor trial", page)
        self.assertNotIn("No verified championship result", page)
        result = json.loads((run_dir / "demo_result.json").read_text())
        self.assertTrue(result["verified"])
        key = [e for e in result["examples"] if e["tick_id"] == "t095"][0]
        committed = [r for r in json.loads((RUNS / "v21-gemini-01" / "decisions.json").read_text())["rows"] if r["tick_id"] == "t095"][0]
        self.assertAlmostEqual(key["regret"], committed["regret"], places=4)  # same counterfactual as the committed analysis
        self.assertEqual(key["reference_run_action"], "PIT_HARD/STAY")

    def test_page_is_self_contained(self):
        run_dir = self.tmpdir() / "out"
        run_demo("finalize", "--mode", "recorded", "--run", "v21-gemini-03", "--run-dir", str(run_dir))
        page = (run_dir / "report.html").read_text()
        for bad in ("<script src", "<link ", "http://", "https://", "@import"):
            self.assertNotIn(bad, page)

    def test_live_success_layout(self):
        run_dir = live_layout(self.tmpdir(), "v21-oracle-01")
        code, out, err = run_demo("finalize", "--mode", "live", "--run-dir", str(run_dir), "--task", str(self.task),
                                  "--harbor-exit-code", "0")
        self.assertEqual(code, 0, err)
        page = (run_dir / "report.html").read_text()
        self.assertIn("Live · fresh Harbor trial", page)
        self.assertTrue((run_dir / "demo_artifacts" / "evidence" / "journal.jsonl").exists())

    def test_live_failure_never_looks_successful(self):
        run_dir = self.tmpdir() / "empty"
        code, out, err = run_demo("finalize", "--mode", "live", "--run-dir", str(run_dir), "--task", str(self.task),
                                  "--harbor-exit-code", "1")
        self.assertEqual(code, 1)
        page = (run_dir / "report.html").read_text()
        self.assertIn("No verified championship result", page)
        self.assertIn("Not verified", page)
        self.assertIn("Harbor trial failed or incomplete", page)
        self.assertNotIn("Live · fresh Harbor trial", page)
        for absent in ("Championship progression", "Eight-race timeline", ">289<", ">279<"):
            self.assertNotIn(absent, page)
        self.assertFalse(json.loads((run_dir / "demo_result.json").read_text())["verified"])

    def test_nonzero_harbor_exit_with_valid_artifacts_is_not_success(self):
        run_dir = live_layout(self.tmpdir(), "v21-oracle-01")
        code, out, err = run_demo("finalize", "--mode", "live", "--run-dir", str(run_dir), "--task", str(self.task),
                                  "--harbor-exit-code", "137")
        self.assertEqual(code, 137)
        self.assertIn("No verified championship result", (run_dir / "report.html").read_text())

    def test_incomplete_recorded_run_renders_failure(self):
        run_dir = self.tmpdir() / "out"
        code, out, err = run_demo("finalize", "--mode", "recorded", "--run", "v21-nop-01", "--run-dir", str(run_dir))
        self.assertEqual(code, demo.EXIT_UNVERIFIED)
        self.assertIn("No verified championship result", (run_dir / "report.html").read_text())

    def test_mismatched_reference_shows_no_gap(self):
        run_dir = self.tmpdir() / "out"
        code, out, err = run_demo("finalize", "--mode", "recorded", "--run", "v21-gemini-01", "--run-dir", str(run_dir),
                                  "--reference", "v21-nop-01")
        self.assertEqual(code, 0, err)
        page = (run_dir / "report.html").read_text()
        self.assertNotIn("Reference − Gemini", page)
        self.assertNotIn("Apex · Reference", page)

    def test_demo_sh_recorded_and_bad_mode(self):
        out = self.tmpdir()
        proc = subprocess.run([str(ROOT / "scripts" / "demo.sh"), "recorded", "v21-gemini-01"], capture_output=True, text=True,
                              env={**os.environ, "F1_OUTPUT_DIR": str(out), "F1_OPEN": "0"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Recorded replay of committed Harbor run", proc.stdout)
        self.assertEqual(len(list(out.glob("demo-recorded-*/report.html"))), 1)
        bad = subprocess.run([str(ROOT / "scripts" / "demo.sh"), "nonsense"], capture_output=True, text=True)
        self.assertEqual(bad.returncode, 2)


if __name__ == "__main__":
    unittest.main()
