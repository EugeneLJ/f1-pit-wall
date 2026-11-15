#!/usr/bin/env python3
"""Bounded, resumable-by-do-not-overwrite M2/M7 offline evaluation.

No paid/model calls, no existing engine integration, no hidden schedules/types in
public output. Smoke: 11,12. Development: 101..105, emitted separately.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import time
from pathlib import Path

from track_c.v22 import rival_tendencies as m2
from track_c.v22 import weather as m7

SMOKE_SEEDS = (11, 12)
DEV_SEEDS = (101, 102, 103, 104, 105)
HERE = Path(__file__).resolve().parent
TASK = HERE.parent


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def m2_record(seed):
    model = m2.load_model()
    private_type = m2.draw_tendency(seed, "bounded-m2", "Rival 1", model)
    context = {"car": "Rival 1", "m3_active": True, "defence_applicable": False,
               "attack_legal": True, "gap_ahead": None, "lap_index": seed % 3}
    event = m2.observable_lap(seed, "bounded-m2", private_type, context, model)
    prior = {kind: model["prior"][kind]["value"] for kind in model["types"]}
    public = m2.public_projection(prior, [event], model)
    stay = {kind: 6.0 for kind in prior}
    pit = dict(stay)
    pit["OPPORTUNIST"] = 7.0
    pit["CONSERVATIVE"] = 5.9
    decision = m2.expected_values(public["posterior"], {"STAY": {
        kind: {"mean": value, "se": 0.2} for kind, value in stay.items()}, "PIT_HARD": {
        kind: {"mean": value, "se": 0.2} for kind, value in pit.items()}})
    return {
        "source": "SEED_GENERATED_PUBLIC_EVENT_PLUS_DECLARED_SYNTHETIC_ACTION_VALUES",
        "public_event": event,
        "public_posterior": public["posterior"],
        "value_model_provenance": "synthetic counterfactual only, not an official engine outcome or fitted policy model",
        "decision": decision,
        "duplicate_replay_equal": m2.public_projection(prior, [event], model) == public,
    }


def m7_record(seed):
    state = m7.initial_state(seed, f"bounded-m7-{seed}")
    actions, choices = [], []
    while not state["complete"]:
        observation = m7.public_observation(state)
        decision = m7.action_values(observation)
        actions.append(decision["chosen_action"])
        choices.append({"boundary": observation["boundary"], "classification": decision["classification"],
                        "chosen_action": decision["chosen_action"],
                        "estimated_margin_sec": decision["estimated_margin_sec"],
                        "observed_weather": observation["observed_weather"]})
        state = m7.step(state, actions[-1])
    replay_equal = m7.replay(seed, actions, race_id=state["race_id"])["state"] == state
    if not replay_equal:
        raise RuntimeError(f"M7 replay mismatch for seed {seed}; no evidence emitted")
    return {
        "source": "naturally seeded public Markov trace, never retried for preferred outcome",
        "actions": actions,
        "choices": choices,
        "result": m7.classification(state),
        "replay_equal": replay_equal,
    }


def run(seed):
    started = time.monotonic()
    value = {"seed": seed, "m2": m2_record(seed), "m7": m7_record(seed)}
    value["seed_generation_seconds"] = round(time.monotonic() - started, 6)
    return value


def aggregate(rows):
    m2_classes = {}
    m7_classes = {}
    m7_pits = 0
    replay_failures = []
    for row in rows:
        classification = row["m2"]["decision"]["classification"]
        m2_classes[classification] = m2_classes.get(classification, 0) + 1
        m7_pits += sum(action.startswith("PIT_") for action in row["m7"]["actions"])
        for choice in row["m7"]["choices"]:
            kind = choice["classification"]
            m7_classes[kind] = m7_classes.get(kind, 0) + 1
        if not row["m2"]["duplicate_replay_equal"] or not row["m7"]["replay_equal"]:
            replay_failures.append(row["seed"])
    return {
        "m2_public_value_classes": m2_classes,
        "m7_public_value_classes": m7_classes,
        "m7_pit_actions": m7_pits,
        "m7_segments_evaluated": sum(len(row["m7"]["choices"]) for row in rows),
        "replay_failures": replay_failures,
        "interpretation": "bounded counts only; no model failure, matched reference gap, or natural-model-difficulty claim",
    }


def write_new(path, output):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(output, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
    return file_hash(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("smoke", "dev"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    seeds = SMOKE_SEEDS if args.phase == "smoke" else DEV_SEEDS
    if args.output.exists():
        if not args.resume:
            raise SystemExit(f"refusing to overwrite evidence: {args.output}")
        existing = json.loads(args.output.read_text())
        if existing["preregistered_seeds"] != list(seeds):
            raise SystemExit("resume seed contract mismatch")
        rows_by_seed = {row["seed"]: row for row in existing["rows"]}
        if not set(seeds) <= set(rows_by_seed):
            raise SystemExit("partial resume requires a new, explicit partial artifact")
        print(json.dumps({"resumed_verified_existing": True, "seeds": list(seeds),
                          "sha256": file_hash(args.output), "aggregate": existing["aggregate"]}, sort_keys=True))
        return
    started = time.monotonic()
    rows = [run(seed) for seed in seeds]
    output = {
        "schema_version": 1,
        "preregistered_seeds": list(seeds),
        "seed_budget": "two smoke rows or five development rows; no additional seed searches",
        "fixture_sha256": {
            "m2": file_hash(TASK / "track_c" / "fixtures" / "v22_m2.json"),
            "m7": file_hash(TASK / "track_c" / "fixtures" / "v22_m7.json"),
        },
        "rows": rows,
        "rows_sha256": digest(rows),
        "aggregate": aggregate(rows),
        "main_generation_seconds": round(time.monotonic() - started, 6),
        "api_calls": 0,
        "actual_model_results": False,
        "official_frontier_reference_gap": None,
        "synthetic_vs_natural": {
            "natural": "seeded Markov weather rival behavior and M2 draw classes only",
            "synthetic": "declared decision-value objects and micro-race, not official engine results",
        },
    }
    sha = write_new(args.output, output)
    print(json.dumps({"output": str(args.output), "sha256": sha,
                      "aggregate": output["aggregate"], "seconds": output["main_generation_seconds"]}, sort_keys=True))


if __name__ == "__main__":
    main()
