#!/usr/bin/env python3
"""Offline regression tests for the Harbor demo UX (no Docker or paid API calls)."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "demo.py"
DEMO_SH = ROOT / "scripts" / "demo.sh"
RESULTS = ROOT / "f1-championship" / "analysis" / "results" / "rep_runs"
R0 = RESULTS / "r0"
R1 = RESULTS / "r1"
R2 = RESULTS / "r2"
ZERO_HASH = "0" * 64

SPEC = importlib.util.spec_from_file_location("f1_demo_ux", SCRIPT)
demo = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(demo)


class DemoWorkspace:
    def __init__(self, root: Path, source: Path = R1, with_evidence: bool = True, with_trace: bool = True):
        self.root = root
        self.run_dir = root / "run"
        self.trial = self.run_dir / "harbor-output" / "opencode" / "task" / "trial-0"
        self.verifier = self.trial / "verifier"
        self.evidence = self.trial / "artifacts" / "evidence" / "f1sim"
        self.verifier.mkdir(parents=True)
        self.evidence.mkdir(parents=True)
        report = json.loads((source / "verifier_report.json").read_text(encoding="utf-8"))
        (self.verifier / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        (self.verifier / "reward.txt").write_text(f"{report['reward']:.8f}\n", encoding="utf-8")
        if with_evidence:
            for name in ("journal.jsonl", "manifest.json"):
                shutil.copy2(source / "evidence" / name, self.evidence / name)
        if with_trace:
            analysis = self.trial / "analysis"
            analysis.mkdir()
            shutil.copy2(source / "trace_baseline_continuation.json", analysis / "trace_baseline_continuation.json")
        self.write_metadata()

    def write_metadata(self) -> None:
        metadata = {
            "schema_version": 1,
            "run_id": "offline-test",
            "agent": "opencode",
            "model": "gemini/test-model",
            "benchmark_path": str(ROOT / "f1-championship"),
            "harbor_version": "harbor 0.26.0-test",
            "harbor_log": "harbor.log",
            "started_at": "2026-11-15T00:00:00Z",
            "finished_at": "2026-11-15T00:01:00Z",
        }
        (self.run_dir / "run.json").write_text(json.dumps(metadata) + "\n", encoding="utf-8")

    def report(self) -> dict:
        return json.loads((self.verifier / "report.json").read_text(encoding="utf-8"))

    def save_report(self, report: dict) -> None:
        (self.verifier / "report.json").write_text(json.dumps(report) + "\n", encoding="utf-8")
        (self.verifier / "reward.txt").write_text(f"{report['reward']:.8f}\n", encoding="utf-8")


class DemoUxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="f1-demo-ux-")
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def finalize(self, workspace: DemoWorkspace, extra: list[str] | None = None, harbor_exit: int = 0):
        output = workspace.run_dir / "report.html"
        argv = [
            "finalize", "--run-dir", str(workspace.run_dir),
            "--benchmark-path", str(ROOT / "f1-championship"),
            "--harbor-exit-code", str(harbor_exit), "--output", str(output),
            "--tty", "never", "--replay-delay", "0",
        ] + (extra or [])
        parser = demo.build_parser()
        args = parser.parse_args(argv)
        real_read_json = demo.read_json

        def read_with_recorded_r1_seed(path):
            if Path(path) == ROOT / "f1-championship" / "tests" / "hidden_seed.json":
                # r1's published repeat seed. Production still reads the task's
                # own seed path; nothing is written or exposed in the report.
                return {"base_seed": 1750874342504930565}
            return real_read_json(path)

        # The container is Python 3.11. Exercise the replay code against real
        # evidence, without claiming that Python 3.11 is an official runtime.
        with mock.patch.object(demo, "require_replay_runtime", lambda: None), \
                mock.patch.object(demo, "read_json", side_effect=read_with_recorded_r1_seed):
            context, result = demo.inspect_and_render(args)
        return context, result, output.read_text(encoding="utf-8")

    def test_real_verified_artifacts_generate_canonical_race_summary(self) -> None:
        workspace = DemoWorkspace(self.root)
        context, result, page = self.finalize(workspace)
        self.assertTrue(result["verified"], result["errors"])
        self.assertEqual(result["demo_exit_code"], 0)
        self.assertEqual(result["apex_constructors_points"], 267)
        self.assertAlmostEqual(result["official_reward"], 0.7038461538461539)
        self.assertEqual(len(result["race_events"]), 8)
        self.assertIn("Harbor Grand Prix", page)
        self.assertIn("Finale Grand Prix", page)
        self.assertIn("0.70384615", page)
        self.assertIn("VERIFIED RUN", page)
        self.assertNotIn("<script", page)
        self.assertTrue((workspace.run_dir / "demo_artifacts" / "evidence" / "journal.jsonl").is_file())
        self.assertTrue((workspace.run_dir / "demo_artifacts" / "race_summary.json").is_file())
        self.assertEqual(context["report"]["performance"]["apex_constructors_points"], 267)
        self.assertEqual(context["race_summary"]["races"][0]["sc_vsc_decisions"], 1)

    def test_report_output_is_stable_for_identical_artifacts(self) -> None:
        workspace = DemoWorkspace(self.root)
        _, _, first = self.finalize(workspace)
        first_result = (workspace.run_dir / "demo_result.json").read_bytes()
        _, _, second = self.finalize(workspace)
        second_result = (workspace.run_dir / "demo_result.json").read_bytes()
        self.assertEqual(first, second)
        self.assertEqual(first_result, second_result)

    def test_malformed_sidecar_evidence_fails_and_never_advances_progress(self) -> None:
        workspace = DemoWorkspace(self.root, with_trace=False)
        with (workspace.evidence / "journal.jsonl").open("ab") as stream:
            stream.write(b"\n")
        context, result, page = self.finalize(workspace)
        self.assertFalse(result["verified"])
        self.assertEqual(result["demo_exit_code"], 3)
        self.assertTrue(any("digest differs" in error or "sealed manifest" in error for error in result["errors"]))
        self.assertIsNone(context["race_summary"])
        self.assertIn("RUN NOT VERIFIED", page)
        output = io.StringIO()
        demo.emit_progress(context["race_summary"], output, tty="never")
        self.assertIn("No verified race-completion events", output.getvalue())
        self.assertNotIn("RACE 1/8", output.getvalue())

    def test_missing_evidence_and_malformed_report_generate_failure_reports(self) -> None:
        missing = DemoWorkspace(self.root / "missing", with_evidence=False, with_trace=False)
        _, missing_result, missing_page = self.finalize(missing)
        self.assertEqual(missing_result["demo_exit_code"], 3)
        self.assertIn("journal.jsonl and manifest.json", missing_page)

        malformed = DemoWorkspace(self.root / "malformed", with_trace=False)
        (malformed.verifier / "report.json").write_text("{not-json", encoding="utf-8")
        _, malformed_result, malformed_page = self.finalize(malformed)
        self.assertEqual(malformed_result["demo_exit_code"], 3)
        self.assertIn("malformed report.json", malformed_page)
        self.assertIn("RUN NOT VERIFIED", malformed_page)

    def test_intact_but_incomplete_run_is_not_a_success(self) -> None:
        workspace = DemoWorkspace(self.root, with_trace=False)
        empty = b""
        digest = hashlib.sha256(empty).hexdigest()
        manifest = {
            "benchmark_version": "1.1.0",
            "journal_sha256": digest,
            "journal_entries": 0,
            "head_hash": ZERO_HASH,
        }
        (workspace.evidence / "journal.jsonl").write_bytes(empty)
        (workspace.evidence / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        report = {
            "benchmark_version": "1.1.0",
            "scalar_version": "p0-provisional",
            "completion": {"complete": False, "accepted_decisions": 0, "races_completed": 0, "races_total": 8},
            "integrity": {"intact": True, "error": None},
            "evidence": {"manifest": manifest, "journal_sha256": digest},
            "performance": {"apex_constructors_points": 0, "team_points": {"Apex": 0}},
            "normalization": {"formula": "official verifier formula"},
            "reward": 0.0,
        }
        workspace.save_report(report)
        context, result, page = self.finalize(workspace)
        self.assertTrue(result["integrity_intact"])
        self.assertTrue(result["artifact_ok"])
        self.assertFalse(result["complete"])
        self.assertFalse(result["verified"])
        self.assertEqual(result["demo_exit_code"], 3)
        self.assertEqual(result["race_events"], [])
        self.assertIn("INCOMPLETE", page)
        self.assertIsNotNone(context["race_summary"])
        self.assertEqual(context["race_summary"]["races"], [])

    def test_failed_harbor_exit_is_preserved_without_substituting_old_results(self) -> None:
        run_dir = self.root / "failed-run"
        run_dir.mkdir()
        (run_dir / "run.json").write_text(json.dumps({
            "run_id": "fresh-failed-run", "model": "gemini/new-run",
            "started_at": "2026-11-15T00:00:00Z", "finished_at": "2026-11-15T00:00:01Z",
        }), encoding="utf-8")
        parser = demo.build_parser()
        args = parser.parse_args([
            "finalize", "--run-dir", str(run_dir), "--benchmark-path", str(ROOT / "f1-championship"),
            "--harbor-exit-code", "17", "--output", str(run_dir / "report.html"),
        ])
        _, result = demo.inspect_and_render(args)
        page = (run_dir / "report.html").read_text(encoding="utf-8")
        self.assertEqual(result["demo_exit_code"], 17)
        self.assertFalse(result["verified"])
        self.assertIn("HARBOR RUN FAILED", page)
        self.assertIn("Harbor verifier report.json was not found", page)
        self.assertNotIn("0.70384615", page)

    def test_missing_and_invalid_matched_reference_never_produces_a_gap(self) -> None:
        workspace = DemoWorkspace(self.root)
        context, _, page = self.finalize(workspace)
        self.assertEqual(context["comparison"]["status"], "unavailable")
        self.assertIn("No valid matched reference was supplied", page)
        self.assertNotIn("Frontier − Reference</th>", page)

        reference = DemoWorkspace(self.root / "reference", source=R2)
        seed_a = self.root / "seed-a.json"
        seed_b = self.root / "seed-b.json"
        seed_a.write_text('{"base_seed": 1}\n', encoding="utf-8")
        seed_b.write_text('{"base_seed": 2}\n', encoding="utf-8")
        context, _, page = self.finalize(workspace, [
            "--reference-report", str(reference.verifier / "report.json"),
            "--reference-evidence", str(reference.evidence),
            "--reference-seed", str(seed_b), "--seed-path", str(seed_a),
        ])
        self.assertEqual(context["comparison"]["status"], "unavailable")
        self.assertIn("seed files do not match", page)

    def test_valid_matched_reference_displays_official_scores_and_gap(self) -> None:
        workspace = DemoWorkspace(self.root / "frontier")
        reference = DemoWorkspace(self.root / "reference", source=R2)
        current_seed = self.root / "current-seed.json"
        reference_seed = self.root / "reference-seed.json"
        current_seed.write_text('{"base_seed": 12345}\n', encoding="utf-8")
        shutil.copy2(current_seed, reference_seed)
        context, result, page = self.finalize(workspace, [
            "--reference-report", str(reference.verifier / "report.json"),
            "--reference-evidence", str(reference.evidence),
            "--reference-seed", str(reference_seed), "--seed-path", str(current_seed),
        ])
        self.assertTrue(result["verified"], result["errors"])
        comparison = context["comparison"]
        self.assertEqual(comparison["status"], "available")
        self.assertEqual(comparison["frontier_points"], 267)
        self.assertEqual(comparison["reference_points"], 248)
        self.assertEqual(comparison["points_gap"], 19)
        self.assertIn("Same benchmark/scalar version", page)
        self.assertIn("0.07307692", page)  # Difference of two displayed official rewards only.

    def test_confirmed_and_malformed_failure_evidence(self) -> None:
        confirmed = DemoWorkspace(self.root / "confirmed")
        shutil.copy2(
            R1 / "confirm_own_continuation.json",
            confirmed.trial / "confirm_own_continuation.json",
        )
        context, _, page = self.finalize(confirmed)
        self.assertEqual(context["failures"]["status"], "available")
        self.assertEqual(context["failures"]["confirmed_count"], 6)
        self.assertIn("STAY/PIT_HARD", page)
        self.assertIn("not verifier integrity failures", page)

        malformed = DemoWorkspace(self.root / "bad-failures")
        bad = self.root / "bad-failure.json"
        bad.write_text("{broken", encoding="utf-8")
        context, result, page = self.finalize(malformed, ["--failure-evidence", str(bad)])
        self.assertTrue(result["verified"])
        self.assertEqual(context["failures"]["status"], "unavailable")
        self.assertIn("Malformed failure evidence ignored", page)

    def test_progress_tty_non_tty_and_unverified_behavior(self) -> None:
        summary = {
            "replay_verified": True,
            "races_total": 8,
            "races": [{"race": race, "verified": True} for race in range(1, 9)],
        }
        plain = io.StringIO()
        demo.emit_progress(summary, plain, tty="never", delay=0)
        self.assertNotIn("\r", plain.getvalue())
        self.assertEqual(plain.getvalue().count("RACE "), 8)
        self.assertIn("RACE 1/8 [=o==o>-------]", plain.getvalue())
        self.assertIn("RACE 4/8 [------=o==o>-]", plain.getvalue())
        self.assertIn("RACE 8/8 [--------------=o==o>] FINISH", plain.getvalue())

        class TtyBuffer(io.StringIO):
            def isatty(self) -> bool:
                return True

        terminal = TtyBuffer()
        demo.emit_progress(summary, terminal, tty="auto", delay=0)
        self.assertIn("\r\x1b[2K", terminal.getvalue())
        self.assertEqual(terminal.getvalue().count("RACE "), 8)
        self.assertTrue(terminal.getvalue().endswith("FINISH\n"))
        demo.emit_progress(None, plain, tty="never", delay=0)
        self.assertIn("No verified race-completion events", plain.getvalue())

    def test_unbound_existing_trace_cannot_change_verified_race_details(self) -> None:
        workspace = DemoWorkspace(self.root)
        trace_path = workspace.trial / "analysis" / "trace_baseline_continuation.json"
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        trace["races"][0]["track"]["name"] = "UNBOUND FORGED TRACK"
        trace["races"][0]["apex_points"] = 999
        trace_path.write_text(json.dumps(trace), encoding="utf-8")
        context, result, page = self.finalize(workspace)
        self.assertTrue(result["verified"], result["errors"])
        self.assertEqual(context["race_summary"]["races"][0]["name"], "Harbor Grand Prix")
        self.assertEqual(context["race_summary"]["races"][0]["apex_points"], 35)
        self.assertNotIn("UNBOUND FORGED TRACK", page)

    def test_malformed_official_fields_and_reward_mismatch_fail_closed(self) -> None:
        malformed = DemoWorkspace(self.root / "schema", with_trace=False)
        report = malformed.report()
        report["performance"] = "not-an-object"
        malformed.save_report(report)
        context, result, page = self.finalize(malformed)
        self.assertFalse(result["verified"])
        self.assertEqual(result["demo_exit_code"], 3)
        self.assertIsNone(context["race_summary"])
        self.assertIn("official Apex constructors", page)

        mismatch = DemoWorkspace(self.root / "reward", with_trace=False)
        (mismatch.verifier / "reward.txt").write_text("0.00000000\n", encoding="utf-8")
        _, result, _ = self.finalize(mismatch)
        self.assertFalse(result["artifact_ok"])
        self.assertFalse(result["verified"])
        self.assertIn("reward.txt does not match", " ".join(result["errors"]))

        inconsistency = DemoWorkspace(self.root / "race-mismatch", with_trace=False)
        report = inconsistency.report()
        report["performance"]["apex_constructors_points"] = 266
        inconsistency.save_report(report)
        context, result, _ = self.finalize(inconsistency)
        self.assertFalse(result["verified"])
        self.assertEqual(result["demo_exit_code"], 3)
        self.assertIsNone(context["race_summary"])
        self.assertIn("Canonical replay/report mismatch", " ".join(result["errors"]))

    def test_replay_command_revalidates_summary_and_artifacts(self) -> None:
        workspace = DemoWorkspace(self.root)
        _, result, _ = self.finalize(workspace)
        self.assertTrue(result["demo_success"], result["errors"])
        args = demo.build_parser().parse_args(["replay", "--run-dir", str(workspace.run_dir), "--tty", "never"])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = demo.replay_command(args)
        self.assertEqual(status, 0)
        self.assertEqual(output.getvalue().count("RACE "), 8)
        self.assertIn("FINISH", output.getvalue())

        summary_path = workspace.run_dir / "demo_artifacts" / "race_summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["races"][0]["name"] = "TAMPERED"
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = demo.replay_command(args)
        self.assertEqual(status, 3)
        self.assertNotIn("RACE 1/8", output.getvalue())
        self.assertIn("No verified race-completion events", output.getvalue())

    def make_fake_harbor(self, mode: str = "success", exit_code: int = 0) -> Path:
        fake = self.root / f"fake-harbor-{mode}-{exit_code}"
        fake.write_text(r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import shutil
import sys

args = sys.argv[1:]
with Path(os.environ["FAKE_HARBOR_INVOCATIONS"]).open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(args) + "\n")
if args == ["--version"]:
    print("harbor 0.26.0-fake")
    raise SystemExit(0)
if args and args[0] == "lint":
    raise SystemExit(0)
if not args or args[0] != "run":
    raise SystemExit(64)
mode = os.environ.get("FAKE_HARBOR_MODE", "success")
if mode == "failed":
    raise SystemExit(int(os.environ.get("FAKE_HARBOR_EXIT", "23")))
def option(name):
    return args[args.index(name) + 1]
trial = Path(option("-o")) / option("--job-name") / "task" / "trial-0"
verifier = trial / "verifier"
evidence = trial / "artifacts" / "evidence" / "f1sim"
verifier.mkdir(parents=True)
evidence.mkdir(parents=True)
source = Path(os.environ["FAKE_HARBOR_FIXTURE"])
report = json.loads((source / "verifier_report.json").read_text(encoding="utf-8"))
(verifier / "report.json").write_text(json.dumps(report) + "\n", encoding="utf-8")
(verifier / "reward.txt").write_text(f"{report['reward']:.8f}\n", encoding="utf-8")
for name in ("journal.jsonl", "manifest.json"):
    shutil.copy2(source / "evidence" / name, evidence / name)
analysis = trial / "analysis"
analysis.mkdir()
shutil.copy2(source / "trace_baseline_continuation.json", analysis / "trace_baseline_continuation.json")
(trial / "result.json").write_text(json.dumps({"status": "completed"}) + "\n", encoding="utf-8")
''', encoding="utf-8")
        fake.chmod(0o755)
        return fake

    def run_fake_demo(
        self, mode: str = "success", exit_code: int = 23, auto_python: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        fake = self.make_fake_harbor(mode, exit_code)
        invocations = self.root / f"invocations-{mode}.jsonl"
        env = os.environ.copy()
        env.update({
            "F1_HARBOR_BIN": str(fake),
            "F1_OUTPUT_DIR": str(self.root / f"jobs-{mode}"),
            "F1_PYTHON": sys.executable,
            "F1_MODEL": "gemini/offline-test-model",
            "F1_PROGRESS": "never",
            "F1_REPLAY_DELAY": "0",
            "GEMINI_API_KEY": "offline-placeholder-not-a-credential",
            "FAKE_HARBOR_FIXTURE": str(R1),
            "FAKE_HARBOR_MODE": mode,
            "FAKE_HARBOR_EXIT": str(exit_code),
            "FAKE_HARBOR_INVOCATIONS": str(invocations),
        })
        env.pop("F1_ENV_FILE", None)
        if auto_python:
            env.pop("F1_PYTHON", None)
            env["FAKE_HARBOR_FIXTURE"] = str(R0)  # Matches the packaged task seed.
            binary_dir = self.root / "sterile-path"
            binary_dir.mkdir()
            for name in ("bash", "date", "dirname", "mkdir", "python3", "tee"):
                executable = shutil.which(name)
                self.assertIsNotNone(executable, name)
                (binary_dir / name).symlink_to(executable)
            env["PATH"] = str(binary_dir)
            env["HOME"] = str(self.root / "empty-home")
            Path(env["HOME"]).mkdir()
        completed = subprocess.run(
            [str(DEMO_SH)], cwd=ROOT, env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, check=False,
        )
        completed.invocations = invocations  # type: ignore[attr-defined]
        return completed

    def test_one_command_fake_harbor_success_and_exit_propagation(self) -> None:
        success = self.run_fake_demo("success")
        self.assertEqual(success.returncode, 0, success.stdout + success.stderr)
        self.assertIn("Report: ", success.stdout)
        # This forced-Python 3.11 harness must not promote the bundled trace to
        # verified progress. Canonical 3.12 replay is covered separately above.
        self.assertIn("No verified race-completion events", success.stdout)
        self.assertNotIn("\r", success.stdout)
        self.assertNotIn("RACE 1/8", success.stdout)
        invocation_lines = success.invocations.read_text(encoding="utf-8").splitlines()  # type: ignore[attr-defined]
        invocations = [json.loads(line) for line in invocation_lines]
        run = next(item for item in invocations if item and item[0] == "run")
        self.assertEqual(run[run.index("-a") + 1], "opencode")
        self.assertEqual(run[run.index("-m") + 1], "gemini/offline-test-model")
        self.assertEqual(run[run.index("--api-key-name") + 1], "GEMINI_API_KEY")
        self.assertNotIn("offline-placeholder-not-a-credential", json.dumps(invocations))

        failed = self.run_fake_demo("failed", 23)
        self.assertEqual(failed.returncode, 23, failed.stdout + failed.stderr)
        self.assertIn("Report: ", failed.stdout)
        reports = list((self.root / "jobs-failed").glob("demo-*/report.html"))
        self.assertEqual(len(reports), 1)
        page = reports[0].read_text(encoding="utf-8")
        self.assertIn("HARBOR RUN FAILED", page)
        self.assertNotIn("0.70384615", page)

    @unittest.skipIf(sys.version_info[:2] == (3, 12), "fallback probe is for a non-3.12 default interpreter")
    def test_unusable_py312_wrapper_falls_back_without_blocking_demo(self) -> None:
        completed = self.run_fake_demo("auto-fallback", auto_python=True)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("Report: ", completed.stdout)
        self.assertIn("Per-race canonical replay unavailable", completed.stderr)
        self.assertNotIn("Demo finalization failed", completed.stderr)
        reports = list((self.root / "jobs-auto-fallback").glob("demo-*/report.html"))
        self.assertEqual(len(reports), 1)


if __name__ == "__main__":
    unittest.main()
