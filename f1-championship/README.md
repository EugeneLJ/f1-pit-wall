# F1 Pit Wall — benchmark 2.1.0

**Submitted benchmark: 2.1.0**, Harbor mode `SOLO_COORDINATION`, Engineer condition `CHIEF_ONLY`
(history in [docs/VERSIONS.md](docs/VERSIONS.md)).

An agent runs Apex GP, a two-car team, through an eight-race constructors' championship. It plays
120 sequential decisions through a sealed simulator sidecar:
- per race, one power-unit decision under FIA-2026-based allocation, stock and grid-penalty rules;
- per race, 14 race decisions for both cars: stay out or pit onto SOFT / MEDIUM / HARD, plus a team
  order (`RACE`, `HOLD`, `SWAP` with an optional give-back commitment, or `DEFENSIVE_BUFFER`).

Safety cars, virtual safety cars and retirements are random. Rivals follow a published rule.

**In the Harbor task**
- pit and compound decisions;
- SC/VSC;
- the two-compound rule;
- PU allocation, stock and cumulative grid penalties;
- team orders and commitments.

**Not in the Harbor task**
- Engineers: the observation has no `engineer_reports` in this mode;
- an adaptive rival model;
- weather;
- practice and qualifying.

Those appear only in separately labelled diagnostic studies (below) or in plans.

## Results (2.1.0, Harbor, same hidden task seed)

| Run | Points | Reward | Artifact |
|---|---:|---:|---|
| Public-information reference (`-a oracle`) | **289** | **0.7817** | [`v21-oracle-01`](analysis/results/reference_runs/v21-oracle-01/) |
| Gemini 3.8 Flash, OpenCode 1.19.5, fresh run 1 | 279 | 0.7421 | [`v21-gemini-01`](analysis/results/reference_runs/v21-gemini-01/) |
| Gemini 3.8 Flash, fresh run 2 | 256 | 0.6508 | [`v21-gemini-02`](analysis/results/reference_runs/v21-gemini-02/) |
| Gemini 3.8 Flash, fresh run 3 | 276 | 0.7302 | [`v21-gemini-03`](analysis/results/reference_runs/v21-gemini-03/) |
| Do nothing (`-a nop`) | 0 | 0.0 | [`v21-nop-01`](analysis/results/reference_runs/v21-nop-01/) |
| Stop early after boundary attacks | 0 | 0.0 | [`v21-probe-stop-01`](analysis/results/reference_runs/v21-probe-stop-01/) |
| Boundary attacks, then the published baseline heuristic | 229 | 0.5437 | [`v21-probe-complete-01`](analysis/results/reference_runs/v21-probe-complete-01/) |

**The reference beats all three fresh Gemini runs on the task seed:** +10, +33 and +13 points
(mean +18.7, n = 3, no significance claim).

**Script replays** (not new model runs). Each Gemini run wrote its own strategy script. Replayed
on 20 paired seeds that no run had seen, the reference leads by +9.05 (15/20 seeds), +32.05
(20/20) and +8.55 (15/20).

**Where the gap comes from:**
- Almost entirely race decisions: +8.0 / +27.1 / +7.9 points when only the race policy differs.
- Not the power-unit rules: +0.55 in every run.

**Recurring failures, robust under three checks in all three runs:**
- the early SOFT stop is never taken;
- the cheap stop under the race-7 safety car (tick `t095`) is missed;
- mid-race stops are missed.

Method, attribution and limits: [docs/REFERENCE_2_1_0_REPORT.md](docs/REFERENCE_2_1_0_REPORT.md).
Decision-level analysis: `analysis/results/reference_runs/v21-gemini-0N/decisions.json`.

## Run (judges: start here)

Requirements: Harbor 0.26+, Docker with Compose, `python3` on the host. Run from the repository root.
Each command builds the 2.1.0 task from this checkout into `$TMPDIR/f1-pit-wall-2.1.0` (override
with `F1_BUILD_DIR`), then calls `harbor run`. Extra arguments go to `harbor run`.

```bash
# 1. Reference: public-information rollout player. Expected 289 points, reward 0.7817, about 2 min.
f1-championship/scripts/run_v21.sh oracle

# 2. Frontier run: OpenCode + gemini/gemini-3.8-flash, about 8–10 min. Repeat for more runs.
GEMINI_ENV_FILE=<file containing GEMINI_API_KEY=...> f1-championship/scripts/run_v21.sh opencode

# 3. Do-nothing baseline: the season is never finished, so reward 0.
f1-championship/scripts/run_v21.sh nop

# 4. Stop-early baseline: boundary attacks as root, two decisions, deletes the socket, quits. Reward 0.
f1-championship/scripts/run_v21.sh probe-stop

# 5. Exploit probe, then an honest finish with the published baseline heuristic.
#    Reward equals the heuristic's own score; every attack is refused.
f1-championship/scripts/run_v21.sh probe-complete
```

- **Output:** the reward is written to `/logs/verifier/reward.txt` (one number in [0, 1]) and the
  breakdown to `/logs/verifier/report.json` in the Harbor job directory.
- **Network:** only the frontier run needs it, to `generativelanguage.googleapis.com`. The sim
  container never has network.
- **Images are pinned:** `node:22.22.0-bookworm-slim` with `opencode-ai@1.19.5` for the agent,
  `python:3.12.12-slim-bookworm` for the sim and the verifier.

**Local checks** (no Docker; Python 3.12 through uv):

```bash
cd f1-championship
scripts/py312 -m unittest discover -s devtests                  # all devtests
scripts/py312 analysis/v21_tamper_regrade.py                    # tamper regrade of a real 2.1.0 run
scripts/py312 analysis/reference21_eval.py --stage inter20      # reference vs Gemini scripts, 20 seeds (cached)
```

**Another hidden seed.** `tests/hidden_seed.json` is public by design: the verifier needs it, and
the agent container cannot read it. To grade on a seed nobody has seen:
build the 2.1.0 task and replace its two seed files, as `scripts/make_seed_variant.sh` does for 1.1.0:

```bash
f1-championship/scripts/make_integrated_task.sh /tmp/v21-x CHIEF_ONLY 2.1.0
printf '{"schema_version": 1, "base_seed": %s}\n' <integer seed> | tee /tmp/v21-x/environment/sim/secret/seed.json > /tmp/v21-x/tests/hidden_seed.json
harbor run -p /tmp/v21-x -a oracle
```

## Scoring and integrity

```text
reward = 0                                  if the season is not complete or the evidence is not intact
reward = clip((P - D) / (U - D), 0, 1)      otherwise
P = Apex constructors' points; D = the published fallback policy (USE / STAY / RACE) on the same seed (92);
U = 43 x 8 races = 344, a true upper bound, not a reference score
```

- Points only accumulate, so stopping early cannot beat finishing.
- Team orders, commitments and report use are reported in `report.json`, never rewarded.

| Check (2.1.0) | Result | Evidence |
|---|---|---|
| Do nothing | reward 0 | `v21-nop-01` |
| Stop early after attacks | reward 0: 2 of 120 ticks resolved, evidence intact, 23 rejected requests logged | `v21-probe-stop-01` |
| Attacks then honest finish | 229 points, reward 0.5437, the same as the baseline heuristic on this seed. Refused: reset, rewind, seed, malformed or oversized requests, wrong-phase, future, stale and duplicate decisions (1 of 20 concurrent submissions accepted), acting after completion. Private paths and the simulator process are not visible. Files forged inside the agent container (`reward.txt`, evidence, manifest) are ignored by the verifier | `v21-probe-complete-01` (`agent_probe_results.json`) |
| Edited action, nothing else | reward 0, journal does not match sealed manifest | `v21-gemini-01/tamper_regrade.json` |
| Edited action, manifest re-hashed | reward 0, entry hash mismatch | same |
| Edited action, chain and manifest recomputed | reward 0, action hash mismatch | same |
| Same, action hash also recomputed (a forger without the seed) | reward 0, observation hash after the tick differs on replay | same |
| Truncated to half the season, chain and manifest valid | intact but incomplete, reward 0 | same |
| Evidence claims another version | reward 0, version rejected | same |
| Untouched evidence regraded | 279 points, reward 0.7421, identical to Harbor | same |

**Architecture**
- The agent container has `f1ctl` and OpenCode, but no engine, seed or state.
- The sim container (`f1sim.integrated_server`, no network) holds the seed, the live session and a
  hash-chained journal (v2), with an fsync per entry.
- After the agent stops, `f1sim.export_integrated` seals the journal and a manifest.
- The separate verifier container re-checks hashes and replays every tick from the hidden seed,
  recomputing every observation hash.
- Stale, future or duplicate decision ids are rejected and journaled. A restarted sidecar rebuilds
  state by verified replay.

**Disclosure.** The integrated instruction addendum (`integrated_task/instruction_addendum.md`) is
shared by all integrated modes. It still describes two race engineers and `engineer_reports`, and its
heading says 2.0.1, but this CHIEF_ONLY task delivers no reports. The three runs were evaluated on
exactly this instruction:
- the Gemini scripts read `engineer_reports` defensively (`obs.get(..., [])`);
- no action was rejected.

Changing the text would change the task, so it is left as run and disclosed here.

## Reference

`integrated_task/solution/reference_v21.py` (run by `-a oracle`) plays through `f1ctl` from public
observations only.
- **Race decisions:** a one-step rollout over the 16 joint pit actions, with futures from the
  published SC/VSC model conditioned on the observed history.
- **Components:** a season search under the published 2.1.0 power-unit rules.
- **Information:** it reads no seed, journal or sidecar file. Static and dynamic seed-blindness
  tests check this.
- **Model-access advantage:** it executes the published rules exactly, which a frontier agent must
  infer from `f1ctl rules`.
- **Cost:** budget-limited, not optimal. It takes 61–100 s per season against a 3600 s limit.

## Comparison version 1.1.0

1.1.0 is the race-and-legacy-components task in this directory (`harbor run -p ./f1-championship
-a oracle`). It is unchanged and still reproduces: oracle 286 / 0.7698, rerun during the 2.1.0 work
as `v21-v110-oracle-01`.

| 1.1.0 | Points | Reward |
|---|---:|---:|
| Reference, task seed (Harbor) | 286 | 0.770 |
| Gemini 3.8 Flash, task seed (Harbor, 3 fresh runs) | 282 / 279 / 286 | 0.754 / 0.742 / 0.770 |
| Scripts of those runs, 20 paired seeds (script replay) | reference ahead by +10.2 / +6.2 / +5.7 | — |

1.1.0 stop-early and exploit probes: `scripts/make_probe_task.sh`. Details are in
[docs/REFERENCE_GAP_REPORT.md](docs/REFERENCE_GAP_REPORT.md).

## Diagnostic studies (not part of the Frontier–Reference gap)

These run outside the Harbor task, through direct API runners. Each is preregistered or labelled,
and none changes the engine, reward or verifier.

| Study | What it shows | Report |
|---|---|---|
| B7: Gemini Chief vs DeepSeek Chief, two-team, 2.0.1 | one season per layer: 304 vs 143 without Engineers, 237 vs 175 with live Flash-Lite Engineers; DeepSeek's VSC double stacks were worse under all 12 assumptions | [docs/B7_P0_REPORT.md](docs/B7_P0_REPORT.md) |
| C7: adaptive-rival paired probes, 16 calls | 3 of 3 separated reversals were not followed, but Gemini stayed out in 15 of 16 calls, so this is not evidence of a rival-specific failure | [docs/C7_LIVE_EXPANSION_RESULTS.md](docs/C7_LIVE_EXPANSION_RESULTS.md) |
| C8: Engineer conflict, 40 fixed 2.1.0 states, 240 Chief calls | see the Gemini section below | [docs/C8_ENGINEER_CONFLICT_RESULTS.md](docs/C8_ENGINEER_CONFLICT_RESULTS.md) |

C6/C7 tooling and its count reconciliation: [docs/C6_EVIDENCE_PIPELINE.md](docs/C6_EVIDENCE_PIPELINE.md),
[docs/C7_C6_COUNT_RECONCILIATION.md](docs/C7_C6_COUNT_RECONCILIATION.md).

## Gemini API: Chief with two driver-local Engineers

**Architecture**
- A Gemini 3.8 Flash Chief and two Gemini 3.5 Flash-Lite Engineers.
- Each Engineer sees only its own driver and public rivals, and returns a schema-constrained
  recommendation bound to the hash of its observation.
- A trusted broker stores every record in a hash-chained store. The Chief cites the hashes it used
  (`consumed_reports`), and replay re-supplies the exact records.
- Every call records the requested and returned model, request id, prompt hash, token usage
  (including thinking) and a dated price snapshot. A model that is not served is refused, never
  substituted.
- Code: `src/f1pitwall/integrated/engineers.py`, `providers.py`, `track_c/engineer_runtime.py`.

**C8**, preregistered before any call (commit `0f5ba2d`): same state, only the Engineer reports differ.
- **Noise floor:** a Chief-only repeat changes its action in 7.5% of states.
- **Live Engineers:** mean regret +0.21 points per decision versus Chief-only, 95% bootstrap
  [−0.00, +0.49]. This is not separated from zero.
- **One robust harm (state `c8s28`):** the Chief kept its own correct pit decision but took the
  Engineer's compound (HARD → MEDIUM, confidence 0.85), losing 4.5–5.1 expected points under all
  three checks.
- **Pure priority claims** ("prioritise my driver") changed nothing.
- **Cost:** 240 Chief calls and 80 Engineer records, all valid, USD 2.04.

The Engineers are **not** part of the Harbor task above.

## Planned (not implemented in 2.1.0)

- **C5 practice and qualifying:** an isolated Track C module on `feature/c5-practice-qualifying`.
- **2.2.0 scenarios:** rival interaction, stewarding, intra-team rivalry, weather.
  Contract: [docs/V2_2_0_SCENARIO_CONTRACT.md](docs/V2_2_0_SCENARIO_CONTRACT.md).
- **Submission review and promotion gates:** [docs/SUBMISSION_READINESS_REVIEW.md](docs/SUBMISSION_READINESS_REVIEW.md).

## Development

- Edit the engine only in `src/f1pitwall/`, then run `scripts/sync_engine.py`. The sim image, the
  verifier image and the reference solution each need a copy, and devtests fail on drift.
- Analysis and replays run on Python 3.12, the same as the images (`scripts/py312`).
- All track and component coefficients are synthetic. Where a power-unit rule follows the FIA 2026
  Sporting Regulations (Section B, Issue 07), `f1ctl rules` says so and states the scaling.
