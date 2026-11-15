#!/usr/bin/env python3
"""Bounded replay evidence for the isolated 2.2.0 M2/M6/M7 integration candidate.

No model calls, official submission promotion, new score calculation, or C5 integration.
"""

from __future__ import annotations

import argparse
import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import time

from devtests.test_v22_m6_integration import drive
from f1pitwall.integrated import config as C
from f1pitwall.integrated import verify as V

ROOT = Path(__file__).resolve().parents[1]


def sha_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cfg(name):
    return replace(C.with_version(C.two_team(1), "2.2.0"), **{
        "m2_tendencies": name in ("M2", "combined"),
        "m6_compliance": name in ("M6", "combined"),
        "m7_weather": name in ("M7", "combined"),
    })


def run(name, seed, started):
    config = cfg(name)
    driver = drive(config, seed)
    verified = V.replay(config, seed, copy.deepcopy(driver.journal), require_complete=True)
    return {
        "config": config.as_dict(),
        "config_sha256": config.config_hash(),
        "seed_id": seed,
        "complete_ticks": len(driver.journal),
        "races": len(driver.race_results),
        "points": driver.standings(),
        "head_hash": driver.journal[-1]["entry_hash"],
        "replay_complete": verified["complete"],
        "replay_matches_standings": verified["standings"] == driver.standings(),
        "seconds": round(time.monotonic() - started, 3),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        if not args.resume:
            raise SystemExit("refusing to overwrite evidence; pass --resume only if unchanged")
        existing = json.loads(args.output.read_text())
        assert all(row["replay_complete"] and row["replay_matches_standings"] for row in existing["runs"])
        print(json.dumps({"resume_verified_existing": True, "output_sha256": sha_file(args.output)}))
        return
    rows = []
    started = time.monotonic()
    for module in ("M2", "M6", "M7"):
        for seed in (11, 12):
            rows.append({"module": module, **run(module, seed, started)})
    rows.append({"module": "combined", **run("combined", 21, started)})
    payload = {
        "schema_version": 1,
        "model_calls": 0,
        "runs": rows,
        "all_replays_exact": all(row["replay_complete"] and row["replay_matches_standings"] for row in rows),
        "total_wall_seconds": round(time.monotonic() - started, 3),
        "fixtures": {
            "m2": sha_file(ROOT / "track_c" / "fixtures" / "v22_m2.json"),
            "m6": sha_file(ROOT / "track_c" / "fixtures" / "m6_compliance.json"),
            "m7": sha_file(ROOT / "track_c" / "fixtures" / "v22_m7.json"),
        },
        "limitations": [
            "M2 full M1/M3 S1 attack/proximity semantics are not integrated",
            "M7 neutralization multiplier remains an adapter, not a new SC/VSC rollout reference",
            "No live Engineer, adaptive LLM, Harbor, reward, or official reference result was evaluated",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"output": str(args.output), "runs": len(rows), "seconds": payload["total_wall_seconds"],
                      "all_replays_exact": payload["all_replays_exact"], "sha256": sha_file(args.output)}, sort_keys=True))


if __name__ == "__main__":
    main()
