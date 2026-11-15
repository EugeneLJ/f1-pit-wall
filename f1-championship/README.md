# F1 Pit Wall — benchmark 2.1.0

## 1. The task

The agent is the Chief Strategist of **Apex GP**, a two-car team in an eight-race constructors'
championship. Its goal is to **maximise the team's season points**. It plays 120 sequential
decisions through a sealed simulator:
- **Before each race:** USE or REPLACE for each power-unit element of both cars.
- **During each race, 14 times:** for each car, stay out or pit onto SOFT / MEDIUM / HARD, plus a
  team order (`RACE`, `HOLD`, `SWAP` with an optional give-back commitment, or `DEFENSIVE_BUFFER`).

**Supported mode (the only one submitted):**

| Setting | Value |
|---|---|
| Benchmark version | `2.1.0` |
| Mode | `SOLO_COORDINATION`, Engineer condition `CHIEF_ONLY` |
| Agent | one agent controls Apex |
| Rivals | six cars on fixed published rules; not a model, and they do not adapt to the agent |
| Instruction | revision **r2** (`integrated_task/instruction_2_1_0_chief_only.md`). The first three Gemini runs used **r1** (`integrated_task/evaluated/instruction_2_1_0_r1.md`, rebuilt with `F1_INSTRUCTION_REVISION=r1`). r1 and r2 tasks differ only in `instruction.md`: same simulator, actions, observations, seed and verifier. |
| Not in this task | Engineer reports, an adaptive rival model, weather, practice and qualifying |

## 2. Why it is hard

The decisions trade off against each other over different horizons:
- **Tyres:** they degrade and fall off a cliff after their published life, and each car must use
  two compounds.
- **SC/VSC:** periods are random but follow a published model. A stop under them is cheaper, but
  it still costs track position.
- **Pit crew:** one crew means a double stop queues the second car.
- **Power units:** wear carries across races, and units beyond each driver's allocation cost grid
  places (FIA-2026-based rules, scaled to 8 races and 8 cars).
- **Team orders:** they cost race time and can fail.

Nothing needed is hidden except the future random draws. All formulas, distributions and rival
rules are in `f1ctl rules`.

**What the agent can use.** Shell access in its own container, plus one tool:
- `f1ctl rules` (all public rules);
- `f1ctl observe` (the current state and legal actions);
- `f1ctl act <decision_id> '<json>'`.

It has no seed, reset, rewind or preview. The simulator, seed and journal live in a separate
container with no network.

## 3. Reproduce (judges: start here)

**Prerequisites** (verified on a clean Ubuntu 26.04 host, `docs/REPRODUCTION_LOG.md`):
- Docker with the Compose plugin;
- `git` and `python3`;
- Harbor 0.26.0, installed with:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh        # installs uv (provides `uv tool`)
uv tool install harbor==0.26.0
git clone --branch submission/2.1.0 https://github.com/EugeneLJ/f1-pit-wall.git && cd f1-pit-wall
```

Each command below builds the 2.1.0 task from the checkout into `$TMPDIR/f1-pit-wall-2.1.0`
(override with `F1_BUILD_DIR`) and runs `harbor run`. Extra arguments go to `harbor run`, for
example `-o jobs --job-name x`.

```bash
f1-championship/scripts/run_v21.sh oracle          # reference: expected 289 points, reward 0.7817 (~2 min)
f1-championship/scripts/run_v21.sh nop             # do nothing: reward 0
f1-championship/scripts/run_v21.sh probe-stop      # boundary attacks as root, 2 decisions, quit: reward 0
f1-championship/scripts/run_v21.sh probe-complete  # same attacks, then the published baseline heuristic: 229 points, 0.5437
GEMINI_ENV_FILE=<file containing GEMINI_API_KEY=...> f1-championship/scripts/run_v21.sh opencode
                                                   # frontier run: OpenCode 1.19.5 + gemini/gemini-3.8-flash (~10 min)
```

- **Output:** each run writes `<jobs>/<job>/<trial>/verifier/reward.txt` (a number in [0, 1]) and
  `verifier/report.json` (completion, integrity, normalisation, points). The sealed evidence is in
  `artifacts/evidence/f1sim/{journal.jsonl,manifest.json}`.
- **Network:** only `opencode` needs it, and only to `generativelanguage.googleapis.com`.
- **Images are pinned:** `node:22.22.0-bookworm-slim` with `opencode-ai@1.19.5` for the agent,
  `python:3.12.12-slim-bookworm` for the sim and the verifier.

**Local checks**, no Docker (uv provides Python 3.12):

```bash
cd f1-championship
scripts/py312 -m unittest discover -s devtests              # 234 tests
scripts/py312 analysis/v21_tamper_regrade.py                # regrade a real run, plus 6 forgeries
scripts/py312 analysis/reference21_eval.py --stage inter20  # reference vs the Gemini scripts on 20 seeds (cached)
```

**Another seed.** `tests/hidden_seed.json` is public by design (the verifier needs it; the agent
container cannot read it). To grade on an unseen seed, replace both seed files of a built task:

```bash
f1-championship/scripts/make_integrated_task.sh /tmp/v21-x CHIEF_ONLY 2.1.0
printf '{"schema_version": 1, "base_seed": %s}\n' <integer seed> | tee /tmp/v21-x/environment/sim/secret/seed.json > /tmp/v21-x/tests/hidden_seed.json
harbor run -p /tmp/v21-x -a oracle
```

## 4. Verified Frontier–Reference results (2.1.0)

**Scope of every row:**
- benchmark 2.1.0, SOLO_COORDINATION / CHIEF_ONLY;
- the same hidden task seed (`tests/hidden_seed.json`);
- reward from the isolated Harbor verifier (`b6-integrated-p0`).

Artifacts are in `analysis/results/reference_runs/<dir>/`.

| Run | Type | Model / agent | Instruction | Points | Reward | Dir |
|---|---|---|---|---:|---:|---|
| Reference | Harbor run | `-a oracle` (public-information rollout) | r1 (r2 on the clean host: identical journal) | **289** | **0.7817** | `v21-oracle-01` |
| Gemini 1 | Harbor run, fresh | OpenCode 1.19.5, gemini/gemini-3.8-flash | r1 | 279 | 0.7421 | `v21-gemini-01` |
| Gemini 2 | Harbor run, fresh | same | r1 | 256 | 0.6508 | `v21-gemini-02` |
| Gemini 3 | Harbor run, fresh | same | r1 | 276 | 0.7302 | `v21-gemini-03` |
| Gemini smoke on r2 | Harbor run, fresh | same | **r2** | 279 | 0.7421 | `v21r2-gemini-01` |

**What this supports**
- On the task seed the reference beats each of the three r1 Gemini runs, by +10, +33 and +13
  points (mean +18.7).
- On instruction r2 (the submitted text), one fresh smoke run scored 279 (0.7421), 10 points below the reference; 110 of its 120 actions equal run 1's. The instruction correction did not materially change Gemini's play (10 of 120 actions differ), so no further repeats were run. r1 and r2 are reported as separate conditions and the +18.7 mean uses the three r1 runs only.

**What this does not support**
- n = 3 runs on one seed, so no significance claim.
- **Script replays are not model runs.** Each Gemini run wrote a strategy script. Replayed on 20
  unseen paired seeds, the reference leads by +9.05 (15/20 seeds), +32.05 (20/20) and +8.55
  (15/20) (`analysis/results/reference21_2.1.0_inter20*.json`). That measures the scripts, not
  fresh agent behaviour.
- **Advantage is disclosed:** the reference has a model-access advantage, because it executes the
  published rules exactly.

**Where Gemini loses** (counterfactual analysis: the authoritative engine rolled out on public
inputs, `v21-gemini-0N/decisions.json`):
- **Race decisions:** +8.0 / +27.1 / +7.9 points.
- **Power-unit choices:** +0.55 in every run.
- **Robust in all three runs:** the early SOFT stop is never taken, and the cheap stop under the
  race-7 safety car (`t095`) is missed. Mid-race stops are also missed.

Full method: [docs/REFERENCE_2_1_0_REPORT.md](docs/REFERENCE_2_1_0_REPORT.md).

## 5. Reward and integrity

```text
reward = 0                              if the season is incomplete or the evidence is not intact
reward = clip((P - D) / (U - D), 0, 1)  otherwise
P = Apex points; D = 92, the published fallback (USE / STAY / RACE) on the same seed; U = 43 x 8 = 344
```

- Orders, commitments and report use are reported, never rewarded.
- The verifier re-checks the manifest and hash chain, then replays every tick from the hidden seed,
  recomputing every observation hash.

| Check (2.1.0, Harbor unless noted) | Result | Dir |
|---|---|---|
| Do nothing | reward 0 | `v21-nop-01` |
| Stop early after boundary attacks | reward 0 (2 of 120 ticks, evidence intact) | `v21-probe-stop-01` |
| Boundary attacks, then the baseline heuristic | 229 points, 0.5437, the heuristic's own score | `v21-probe-complete-01` |
| Attacks attempted as root | all refused or ignored (see below) | `agent_probe_results.json` |
| Tamper regrade (local, unmodified verifier) | six forgeries give reward 0; untouched evidence regrades to 279 / 0.7421 | `v21-gemini-01/tamper_regrade.json` |
| Clean-host rerun of oracle, nop and probes | all four reproduce exactly (289 / 0.7817, 0, 0, 229 / 0.5437); the oracle journal matches `v21-oracle-01` tick by tick | `docs/REPRODUCTION_LOG.md` |

**Attacks attempted as root:**
- reset, rewind and seed commands;
- malformed and oversized requests;
- wrong-phase actions;
- future, stale, duplicate and concurrent decisions: 1 of 20 concurrent submissions is accepted;
- acting after completion;
- reading private paths, or spotting the simulator process;
- forging `reward.txt`, evidence and manifest files in the agent container. These are ignored
  because the verifier reads only the sealed sidecar export.

**The six forgeries:**
1. an action edited, nothing else;
2. the manifest re-hashed;
3. the chain recomputed;
4. the action hash also recomputed;
5. a truncated season;
6. a wrong version.

## 6. Diagnostic extensions (not part of the Frontier–Reference gap)

These run outside the Harbor task, through direct API runners, on the same engine.

| Study | Configuration | Finding (descriptive) | Report |
|---|---|---|---|
| **C8 Engineer conflict** | 2.1.0 states; Gemini 3.8 Flash Chief plus two Gemini 3.5 Flash-Lite Engineers, each with a driver-local view; preregistered | Live Engineers: +0.21 regret [−0.00, +0.49] vs Chief-only, not separated from zero. One robust harm, `c8s28`: the Chief adopted the Engineer's MEDIUM over its own HARD and lost 4.5–5.1 points. Pure priority claims had no effect. | [docs/C8_ENGINEER_CONFLICT_RESULTS.md](docs/C8_ENGINEER_CONFLICT_RESULTS.md) |
| **B7 two-team** | 2.0.1; Gemini Chief vs DeepSeek (Verda) Chief | One season per layer. DeepSeek's VSC double stacks were worse under all 12 assumptions. | [docs/B7_P0_REPORT.md](docs/B7_P0_REPORT.md) |
| **C7 adaptive-rival probes** | 2.0.1 two-team states; 16 Gemini calls | 3 of 3 reversals not followed, but Gemini stayed out in 15 of 16 calls, so this is not evidence of a rival-specific failure | [docs/C7_LIVE_EXPANSION_RESULTS.md](docs/C7_LIVE_EXPANSION_RESULTS.md) |

**Engineer architecture:**
- schema-constrained reports, each bound to the hash of its observation;
- a trusted hash-chained broker, with exact replay;
- per-call provenance: requested and returned model, usage, dated prices;
- a model that is not served is refused, never substituted.

Code: `src/f1pitwall/integrated/engineers.py`, `providers.py`, `track_c/engineer_runtime.py`.

## 7. Comparison version 1.1.0 and history

1.1.0 is the race-and-legacy-components task in this directory (`harbor run -p ./f1-championship -a oracle`).
It is unchanged: oracle 286 / 0.7698, Gemini 282 / 279 / 286. Its stop-early and exploit probes
are built with `scripts/make_probe_task.sh`.

Its numbers are a separate benchmark and are never pooled with 2.1.0. Details:
[docs/REFERENCE_GAP_REPORT.md](docs/REFERENCE_GAP_REPORT.md), [docs/VERSIONS.md](docs/VERSIONS.md).

**Planned, not part of this task:**
- C5 practice and qualifying;
- the 2.2.0 scenarios ([docs/V2_2_0_SCENARIO_CONTRACT.md](docs/V2_2_0_SCENARIO_CONTRACT.md)).

Submission evidence index: [docs/SUBMISSION_CHECKLIST.md](docs/SUBMISSION_CHECKLIST.md).

## Development

- Edit the engine only in `src/f1pitwall/`, then run `scripts/sync_engine.py`. Devtests fail on
  drift between the copies.
- All coefficients are synthetic. `f1ctl rules` marks which power-unit rules follow the FIA 2026
  Sporting Regulations (Section B, Issue 07) and how they are scaled.
