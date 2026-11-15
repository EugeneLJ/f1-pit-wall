#!/usr/bin/env python3
"""Tamper regrade of a real 2.1.0 Harbor run with the unmodified 2.1.0 verifier. No model call.

Builds the 2.1.0 task (scripts/make_integrated_task.sh), then runs its tests/grade_integrated.py
on the committed evidence of a live run and on tampered copies:

  original            untouched evidence (exact bytes)            -> intact, reward as in Harbor
  edit_action         one submitted action changed, nothing else  -> manifest mismatch, reward 0
  edit_manifest_only  same edit, manifest re-hashed, chain stale  -> chain broken, reward 0
  forged_chain        same edit, chain + manifest recomputed      -> action hash mismatch, reward 0
  forged_action_hash  also the action hash recomputed (a forger   -> replay observation mismatch, reward 0
                      without the hidden seed)
  truncated           first half only, chain + manifest valid    -> intact but incomplete, reward 0
  wrong_version       manifest claims 2.0.1                      -> rejected, reward 0
  foreign_seed_run    a 1.1.0 journal (v1) under the 2.1.0 task  -> rejected, reward 0

Usage: scripts/py312 analysis/v21_tamper_regrade.py [--run v21-gemini-01]
Writes analysis/results/reference_runs/<run>/tamper_regrade.json
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
RUNS = HERE / "results" / "reference_runs"
sys.path[:0] = [str(TASK / "src")]
from f1pitwall.integrated.session import GENESIS_HASH  # noqa: E402
from f1pitwall.integrated import verify as V  # noqa: E402


def rechain(entries):
    prev = GENESIS_HASH
    out = []
    for number, entry in enumerate(entries, start=1):
        e = {k: v for k, v in entry.items() if k != "entry_hash"}
        e["seq"], e["prev_hash"] = number, prev
        e["entry_hash"] = V.sha256_text(prev + V.canonical(e))
        prev = e["entry_hash"]
        out.append(e)
    return out


def write(evidence, entries, manifest, rehash_manifest, raw=None):
    if raw is None:
        raw = "".join(json.dumps(e, sort_keys=True) + "\n" for e in entries).encode()
    (evidence / "journal.jsonl").write_bytes(raw)
    if rehash_manifest:
        manifest = {**manifest, "journal_sha256": hashlib.sha256(raw).hexdigest(),
                    "journal_entries": len(entries), "head_hash": entries[-1]["entry_hash"] if entries else GENESIS_HASH}
    (evidence / "manifest.json").write_text(json.dumps(manifest, sort_keys=True))


def grade(task, evidence, logs):
    logs.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "F1_EVIDENCE_DIR": str(evidence), "F1_SEED_PATH": str(task / "tests/hidden_seed.json"),
           "F1_MODE_PATH": str(task / "tests/mode.json"), "F1_REWARD_PATH": str(logs / "reward.txt"),
           "F1_REPORT_PATH": str(logs / "report.json")}
    subprocess.run([sys.executable, str(task / "tests/grade_integrated.py")], check=True, env=env,
                   capture_output=True)
    report = json.loads((logs / "report.json").read_text())
    return {"reward": report["reward"], "intact": report["integrity"]["intact"],
            "error": report["integrity"].get("error"), "complete": report.get("completion", {}).get("complete"),
            "points": (report.get("normalization") or {}).get("P"),
            "reward_txt": (logs / "reward.txt").read_text().strip()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="v21-gemini-01")
    args = parser.parse_args()
    run = RUNS / args.run
    raw_bytes = (run / "evidence" / "journal.jsonl").read_bytes()
    entries = [json.loads(x) for x in raw_bytes.decode().splitlines() if x]
    manifest = json.loads((run / "evidence" / "manifest.json").read_text())
    harbor = json.loads((run / "verifier_report.json").read_text())
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        task = tmp / "task"
        subprocess.run([str(TASK / "scripts/make_integrated_task.sh"), str(task), "CHIEF_ONLY", "2.1.0"],
                       check=True, capture_output=True)
        # pick the first race tick where driver_a stayed out; change it to a pit stop
        idx = next(i for i, e in enumerate(entries) if e["kind"] == "resolved"
                   and e["submissions"]["Apex"].get("action", {}).get("type") == "RACE_STRATEGY"
                   and e["submissions"]["Apex"]["action"]["driver_a"] == "STAY" and i > 20)
        edited = copy.deepcopy(entries)
        edited[idx]["submissions"]["Apex"]["action"]["driver_a"] = "PIT_SOFT"
        lines = raw_bytes.decode().splitlines(keepends=True)
        lines[idx] = json.dumps(edited[idx], sort_keys=True) + "\n"
        edited_raw = "".join(lines).encode()
        rehashed = copy.deepcopy(edited)
        sub = rehashed[idx]["submissions"]["Apex"]
        sub["action_sha256"] = V.sha256_text(V.canonical(sub["action"]))
        v1 = [json.loads(x) for x in (RUNS / "v110-gemini-01" / "evidence" / "journal.jsonl").read_text().splitlines() if x]
        cases = {
            "original": (entries, manifest, False, raw_bytes),
            "edit_action": (edited, manifest, False, edited_raw),
            "edit_manifest_only": (edited, manifest, True, edited_raw),
            "forged_chain": (rechain(edited), manifest, True),
            "forged_action_hash": (rechain(rehashed), manifest, True),
            "truncated": (rechain(entries[: len(entries) // 2]), manifest, True),
            "wrong_version": (entries, {**manifest, "benchmark_version": "2.0.1"}, False),
            "foreign_seed_run": (v1, {**manifest}, True),
        }
        results = {}
        for name, (journal, man, rehash, *raw) in cases.items():
            evidence = tmp / name / "evidence"
            evidence.mkdir(parents=True)
            write(evidence, journal, man, rehash, raw[0] if raw else None)
            results[name] = grade(task, evidence, tmp / name / "logs")
    expected_harbor = harbor["reward"]
    checks = {
        "original_matches_harbor": abs(results["original"]["reward"] - expected_harbor) < 1e-9 and results["original"]["intact"],
        "all_tampered_reward_zero": all(results[k]["reward"] == 0.0 for k in cases if k != "original"),
        "tampered_not_intact": all(not results[k]["intact"] for k in cases if k not in ("original", "truncated")),
        "truncated_incomplete": results["truncated"]["intact"] and not results["truncated"]["complete"],
    }
    out = {"schema_version": 1, "run": args.run, "benchmark_version": "2.1.0",
           "verifier": "unmodified integrated_task/tests/grade_integrated.py from a fresh make_integrated_task.sh build",
           "edited_tick": entries[idx]["tick_id"], "harbor_reward": harbor["reward"],
           "cases": results, "checks": checks, "all_checks_pass": all(checks.values())}
    (run / "tamper_regrade.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
    if not out["all_checks_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
