# Demo handoff (submission 2.1.0)

**Status (2026-11-15): implemented** on `submission/2.1.0` as `scripts/demo.sh`, `scripts/demo.py` and `scripts/demo_v21_replay.py`, following this contract. Usage is in the README "Demo" section. The rest of this file remains the contract that any further demo work must keep.

**Scope.** This file says what the demo must read and how it must label results. It does not
implement the demo: `feature/demo-ux` stays with its owner. Do not merge development branches
into `submission/2.1.0`; deliver demo changes as their own branch for review.

## 1. Harbor task

| Item | Value |
|---|---|
| Build command | `f1-championship/scripts/run_v21.sh <oracle\|nop\|opencode\|probe-stop\|probe-complete> [harbor args]` |
| Builder underneath | `f1-championship/scripts/make_integrated_task.sh <dest> CHIEF_ONLY 2.1.0` |
| Built task path | `$F1_BUILD_DIR/task`; default `${TMPDIR:-/tmp}/f1-pit-wall-2.1.0/task`. Probe tasks go to `$F1_BUILD_DIR/probe-stop` and `probe-complete`. |
| Harbor task name / version | `EugeneLJ/f1-championship-integrated` / `2.1.0` (probe tasks: `…-integrated-probe`) |
| Mode labels | `benchmark_version` `2.1.0`, `mode` `SOLO_COORDINATION`, `engineers` `CHIEF_ONLY`, rivals fixed published rules |
| Instruction revision | **r2** by default (`integrated_task/instruction_2_1_0_chief_only.md`, sha256 `5ad46b10…`). **r1** is the instruction the first three Gemini runs saw (`integrated_task/evaluated/instruction_2_1_0_r1.md`, sha256 `f6697c53…`); rebuild it with `F1_INSTRUCTION_REVISION=r1`. r1 and r2 builds differ only in `instruction.md`. |

## 2. Where Harbor writes results

The job root is `harbor run -o <dir>` (default `./jobs`), then `<job-name>/<trial>/`:

| File | Content |
|---|---|
| `verifier/report.json` | official breakdown: `benchmark_version`, `scalar_version` `b6-integrated-p0`, `completion` (`complete`, `races_completed`, `resolved_ticks`), `integrity` (`intact`, `error`, `rejected_requests_logged`), `normalization` (`P`, `D_fallback_same_seed` = 92, `U` = 344), `performance`, `reward` |
| `verifier/reward.txt` | one number with 8 decimals; must equal `report.json.reward` |
| `artifacts/evidence/f1sim/journal.jsonl` | sealed journal v2 (§3) |
| `artifacts/evidence/f1sim/manifest.json` | `benchmark_version`, `journal_sha256`, `journal_entries`, `head_hash`, `journal_version` 2, `request_stats`, `server_version`, `sealed_at`, `engineer_record_files` (empty here) |
| `result.json` | Harbor trial record: `config.agent.name`, `config.agent.model_name`, `task_checksum`, timestamps |
| `agent/` | agent log. **Never publish `trajectory.json`** (it is not committed anywhere). |

## 3. Journal v2 (one JSON object per line)

Common fields:
- `journal_version: 2`;
- `seq`, 1-based;
- `prev_hash` (genesis is 64 zeros);
- `entry_hash = sha256(prev_hash + canonical(entry without entry_hash))`;
- `kind`.

**`kind: "resolved"`** has these fields:
- `tick_id` (`t001`…`t120`);
- `decision_type` (`COMPONENT_DECISION` or `RACE_STRATEGY`);
- `submissions.Apex` with `status` (`SUBMITTED`, or the fallback reason), `action` (the
  validated action), `action_sha256`, `submitted_via` and `t_received`;
- `engineer_record_hashes` (`{}` here);
- `obs_before_sha256.Apex` and `obs_after_sha256.Apex`;
- `t_done`;
- **`race_result`** on the last tick of each race: `{race_index, team_points: {Apex, Orion, Nova, Vertex}}`.
  This is the easiest source for a per-race points chart.

**`kind: "rejected"`** has these fields:
- `tick_id`;
- `team`;
- `action_sha256`;
- `error` (stale or unknown tick, already sealed, or a validation error).

**Authoritative replay.** Do not write your own simulator.
- Function: `f1pitwall.integrated.verify.replay(config, base_seed, entries, require_complete=False)`.
- Config: `C.with_version(C.solo_coordination(engineers="CHIEF_ONLY", chief={"provider": "harbor_agent"}), "2.1.0")`.
- It checks the chain, rebuilds the session from the seed, re-applies every action and recomputes
  every observation hash. It raises `ReplayError` on any mismatch.
- The verifier itself is `integrated_task/tests/grade_integrated.py`; run it with the
  `F1_EVIDENCE_DIR`, `F1_SEED_PATH`, `F1_MODE_PATH`, `F1_REWARD_PATH` and `F1_REPORT_PATH`
  variables, as `analysis/v21_tamper_regrade.py` does.
- The seed is `tests/hidden_seed.json` inside the built task.
- The demo-ux parser expects journal v1 (`kind: "accepted"`, `completion.accepted_decisions`).
  That does not exist in v2: use `resolved` and `resolved_ticks`.

## 4. Verified artifacts (committed, `f1-championship/analysis/results/reference_runs/`)

| Dir | Label to show | Points / reward |
|---|---|---|
| `v21-oracle-01` | 2.1.0 · CHIEF_ONLY · Harbor run · public-information reference (`-a oracle`) · instruction r1 | 289 / 0.7817 |
| `v21-gemini-01`, `-02`, `-03` | 2.1.0 · CHIEF_ONLY · Harbor run · OpenCode 1.19.5 · gemini/gemini-3.8-flash · instruction r1 | 279 / 0.7421, 256 / 0.6508, 276 / 0.7302 |
| `v21r2-gemini-01` | 2.1.0 · CHIEF_ONLY · Harbor run · same model · **instruction r2** (a separate condition; do not pool with r1 runs without saying so) | 279 / 0.7421 |
| `v21-nop-01` | 2.1.0 · Harbor run · `-a nop` | 0 / 0 |
| `v21-probe-stop-01` | 2.1.0 · Harbor run · adversarial probe, stop early | 0 / 0 |
| `v21-probe-complete-01` | 2.1.0 · Harbor run · adversarial probe, then the published baseline heuristic | 229 / 0.5437 |
| `v21-gemini-01/tamper_regrade.json` | local regrade with the unmodified verifier | 6 forgeries → 0; untouched → 279 / 0.7421 |
| `v21-gemini-0N/decisions.json` | **counterfactual analysis**, not a run: regret per decision computed by the engine on public inputs | — |
| `analysis/results/reference21_2.1.0_inter20*.json` | **script replay**, not model runs | reference vs scripts on 20 seeds |

**Every run uses the same hidden task seed:** `tests/hidden_seed.json`, sha256 of the file in the
built task. Diagnostic studies (B7, C7, C8) are outside Harbor and must carry a "diagnostic —
not the Frontier–Reference gap" label.

## 5. Demo entry-point contract (expected)

- **Command:** one command, for example `scripts/demo.sh`, that takes `F1_MODE=oracle|opencode`
  (plus the existing `F1_*` variables). It calls `f1-championship/scripts/run_v21.sh`, so the
  task is built exactly as for judges. It must not build its own copy.
- **Writes** a fresh run directory and never reuses old results on failure:
  - `run.json`: model, agent, job path, Harbor version, instruction revision, start and end time;
    no credentials or seed;
  - `report.html`.
- **Status rule:** show "verified" only when all of these hold:
  - `report.json.integrity.intact` and `completion.complete` are true;
  - `reward.txt` equals `report.json.reward`;
  - `manifest.journal_sha256` equals the sha256 of `journal.jsonl`;
  - the entry count matches;
  - a run of `verify.replay` on the captured journal reproduces `normalization.P`.
- **Comparison rule:** show a gap only between a Frontier run and the reference on the same
  `benchmark_version`, `scalar_version` and seed file. Otherwise say "no matched reference".
- **Labels on every number:** benchmark version, mode, Harbor run vs replay, model, instruction
  revision, seed provenance.
- **Recorded mode** (`--replay <job dir>`): renders an existing job and must title the page
  "Recorded run" with the job's timestamps.

## 6. Video segments that can use committed artifacts directly

- **Per-race points:** `race_result` entries of `v21-oracle-01` against `v21-gemini-02`.
- **Failure t095** (race 7, safety car): `v21-gemini-0N/decisions.json` row `t095`.
  - Gemini's action and the reference action, regret +3.9 / +1.6 / +3.9.
  - Label it "counterfactual: engine rollout on public inputs".
- **Integrity:** `v21-nop-01`, `v21-probe-stop-01`, `v21-probe-complete-01/agent_probe_results.json`,
  `tamper_regrade.json`.
