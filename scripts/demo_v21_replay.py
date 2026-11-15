#!/usr/bin/env python3
"""Authoritative replay of one 2.1.0 journal with the BUILT task's own verifier package.

Run in a fresh interpreter: python3 -I demo_v21_replay.py <task_dir> <journal.jsonl> [<states.pickle>]
Only <task_dir>/tests is put on sys.path, so `f1pitwall` is the verifier image's copy, not the
repository's. Prints one JSON object: the recomputed standings and per-race results from
`f1pitwall.integrated.verify.replay`, plus the public pre-decision race states at SC/VSC decisions
(for the demo's counterfactual examples). The race states go to <states.pickle> (plain dicts;
JSON would turn integer keys into strings). Any mismatch raises and exits non-zero.
"""

import copy
import json
import pickle
import sys
from pathlib import Path


def main() -> int:
    task, journal_path = Path(sys.argv[1]), Path(sys.argv[2])
    sys.path.insert(0, str(task / "tests"))
    from f1pitwall.integrated import config as C
    from f1pitwall.integrated import session as S
    from f1pitwall.integrated import verify as V

    mode = json.loads((task / "tests" / "mode.json").read_text())
    config = C.with_version(C.solo_coordination(engineers=mode["engineers"], chief={"provider": "harbor_agent"}),
                            mode["benchmark_version"])
    seed = json.loads((task / "tests" / "hidden_seed.json").read_text())["base_seed"]
    entries = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines() if line]

    result = V.replay(config, seed, entries, require_complete=False)
    session = result["session"]
    calendar = [{"name": r.name, "archetype": r.archetype} for r in session.state.calendar]

    # Second pass: step a fresh session along the journal, checking every observation hash,
    # and keep the public race state at SC/VSC decisions (input for the counterfactual examples).
    probe = S.IntegratedSession(config, seed, clock=lambda: 0.0)
    neutralised = []
    for entry in entries:
        if entry["kind"] != "resolved":
            continue
        if probe._obs_hash != entry["obs_before_sha256"]:
            raise V.ReplayError(f"{entry['tick_id']}: observation differs from the journal")
        if probe.decision_type == S.RACE_STRATEGY:
            obs = probe.observation("Apex")
            status = obs["race_progress"]["track_status"]
            if status != "GREEN":
                neutralised.append({
                    "tick_id": entry["tick_id"], "race_index": probe.state.race_index,
                    "race_name": probe.state.calendar[probe.state.race_index].name,
                    "lap": obs["race_progress"]["lap"], "status": status,
                    "laps_remaining": obs["race_progress"]["laps_remaining"],
                    "cars": {k: {kk: v.get(kk) for kk in ("position", "compound", "tyre_age")}
                             for k, v in obs["race_progress"]["drivers"].items()},
                    "action": entry["submissions"]["Apex"]["action"],
                    "race": copy.deepcopy(probe.race_state),
                })
        sub = entry["submissions"]["Apex"]
        if sub["status"] == S.SUBMITTED:
            probe.submit("Apex", probe.tick_id, sub["action"])
        else:
            probe.close_tick(probe.tick_id, reason=sub["status"])

    if len(sys.argv) > 3:
        Path(sys.argv[3]).write_bytes(pickle.dumps({n["tick_id"]: n["race"] for n in neutralised}))
    for n in neutralised:
        del n["race"]
    out = {
        "replay_module": str(Path(V.__file__).resolve()),
        "benchmark_version": config.benchmark_version,
        "mode": mode,
        "resolved_ticks": result["resolved_ticks"],
        "complete": result["complete"],
        "team_points": result["standings"]["team_points"],
        "calendar": calendar,
        "race_results": [{"race_index": r["race_index"], "race_name": r["race_name"],
                          "team_points": r["team_points"], "events": r["events"],
                          "classification": [{k: c.get(k) for k in ("position", "driver", "team", "status", "points")}
                                             for c in r["classification"]]}
                         for r in result["race_results"]],
        "neutralised_decisions": neutralised,
    }
    print(json.dumps(out, default=list))
    return 0


if __name__ == "__main__":
    sys.exit(main())
