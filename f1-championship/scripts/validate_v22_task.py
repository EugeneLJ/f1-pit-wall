#!/usr/bin/env python3
"""Build and replay-validate a separate 2.2.0 integrated Harbor task in process.

This runs the scripted coordinator and trusted verifier only. It never calls a
model, Docker, Harbor, or any paid provider. It is not an actual Harbor evaluation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

TASK = Path(__file__).resolve().parents[1]
SOURCE_ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_report(output: Path, benchmark_version: str = "2.2.0") -> dict:
    report = json.loads((output / "oracle-report.json").read_text())
    if not report["completion"]["complete"] or not report["integrity"]["intact"]:
        raise SystemExit("generated candidate did not complete with intact replay")
    if report["benchmark_version"] != benchmark_version or not 0.0 <= report["reward"] <= 1.0:
        raise SystemExit("generated candidate has invalid benchmark version or reward")
    return report


def reject_private_keys(value: Any) -> None:
    forbidden = {"private_seed", "tendency_assignment", "bias_assignment", "rain_path", "hidden_draw"}
    if isinstance(value, dict):
        if forbidden & set(value):
            raise AssertionError(f"private key exposed in public rules: {forbidden & set(value)}")
        for child in value.values():
            reject_private_keys(child)
    elif isinstance(value, list):
        for child in value:
            reject_private_keys(child)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dest", type=Path, required=True, help="fresh directory for the generated task")
    parser.add_argument("--output", type=Path, required=True, help="fresh evidence directory")
    parser.add_argument("--resume", action="store_true", help="only validate an existing output report")
    args = parser.parse_args()
    if args.resume:
        report = checked_report(args.output)
        print(json.dumps({"resume_verified_existing": True, "report": str(args.output / "oracle-report.json"),
                          "output_sha256": sha256(args.output / "oracle-report.json")}, sort_keys=True))
        return
    if args.dest.exists() or args.output.exists():
        raise SystemExit("refusing to overwrite a task or evidence directory; resume explicitly if unchanged")

    args.dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(SOURCE_ROOT / "scripts" / "make_integrated_task.sh"), str(args.dest),
                    "MOCK_ENGINEERS", "2.2.0", "m2_m6_m7"], check=True)
    sys.path.insert(0, str(args.dest / "environment" / "sim"))
    sys.path.insert(0, str(SOURCE_ROOT / "src"))
    sys.path.insert(0, str(SOURCE_ROOT.parent))
    mode_path = args.dest / "environment" / "sim" / "secret" / "mode.json"
    os.environ["F1SIM_MODE_PATH"] = str(mode_path)
    from f1sim.integrated_server import task_config, public_rules
    from f1pitwall.integrated.session import IntegratedSession, CHAMPIONSHIP_COMPLETE
    from f1pitwall.integrated.policies import scripted
    from f1pitwall.integrated.engineers import EngineerBroker
    from f1sim.export_integrated import export_integrated
    mode = json.loads(mode_path.read_text())
    assert mode["benchmark_version"] == "2.2.0" and all(
        mode[key] for key in ("m2_tendencies", "m6_compliance", "m7_weather"))
    config = task_config(mode)
    assert all(getattr(config, key) for key in ("m2_tendencies", "m6_compliance", "m7_weather"))
    reject_private_keys(public_rules(config))
    seed = json.loads((args.dest / "tests" / "hidden_seed.json").read_text())["base_seed"]

    with tempfile.TemporaryDirectory(prefix="v22-task-state-") as workspace:
        state = Path(workspace)
        evidence = state / "evidence"
        driver = IntegratedSession(config, seed, engineer_broker=EngineerBroker(state / "engineers"), clock=lambda: 0.0)
        while driver.decision_type != CHAMPIONSHIP_COMPLETE:
            label = "Apex"
            observation = driver.observation(label)
            action = scripted("coordinator")(observation)
            report_names = {"private_seed", "tendency_assignment", "bias_assignment", "rain_path", "hidden_draw"}
            if any(key in json.dumps(observation) for key in report_names):
                raise AssertionError("private integration field leaked into public observation")
            if observation.get("engineer_reports"):
                action["consumed_reports"] = [r["record_hash"] for r in observation["engineer_reports"] if r["status"] == "VALID"]
            driver.submit(label, observation["tick_id"], action)
        state.mkdir(parents=True, exist_ok=True)
        os.chmod(state, 0o700)
        (state / "journal.jsonl").write_text(
            "".join(json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n" for entry in driver.journal),
            encoding="utf-8")
        manifest = export_integrated(state, evidence)
        env = os.environ.copy()
        env.update({
            "F1_EVIDENCE_DIR": str(evidence),
            "F1_SEED_PATH": str(args.dest / "tests" / "hidden_seed.json"),
            "F1_REWARD_PATH": str(state / "reward.txt"),
            "F1_REPORT_PATH": str(state / "report.json"),
            "F1_MODE_PATH": str(args.dest / "tests" / "mode.json"),
        })
        completed = subprocess.run([sys.executable, str(args.dest / "tests" / "grade_integrated.py")],
                                   env=env, text=True, capture_output=True)
        if completed.returncode:
            raise SystemExit(completed.stderr)
        report = json.loads((state / "report.json").read_text())
        assert report["benchmark_version"] == "2.2.0" and report["completion"]["complete"] and report["integrity"]["intact"]
        assert 0.0 <= report["reward"] <= 1.0

        args.output.mkdir(parents=True)
        shutil.copy2(state / "report.json", args.output / "oracle-report.json")
        shutil.copy2(evidence / "manifest.json", args.output / "oracle-manifest.json")
        report = checked_report(args.output)
        summary = {
            "schema_version": 1,
            "actual_harbor_run": False,
            "model_calls": 0,
            "completion": report["completion"],
            "integrity_intact": report["integrity"]["intact"],
            "benchmark_version": report["benchmark_version"],
            "reward": report["reward"],
            "journal_entries": manifest["journal_entries"],
            "engineer_record_files": manifest["engineer_record_files"],
            "oracle_report_sha256": sha256(args.output / "oracle-report.json"),
            "oracle_manifest_sha256": sha256(args.output / "oracle-manifest.json"),
            "summary_note": "generated coordinator replay through the independent v2 verifier; not live model or Harbor evaluation",
        }
        (args.output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
