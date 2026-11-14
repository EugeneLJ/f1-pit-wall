# B4 report — SC/VSC-driven adaptive replanning and an initial frontier probe

> **Benchmark version: 1.0.0.** These results were produced on benchmark 1.0.0 and are kept as historical results. Version 1.1.0 changes only how `f1ctl rules` names the published base paces (see `docs/VERSIONS.md`).

Branch `feature/track-b`. Part A is the implementation and validation. Part B is the exploratory Gemini run and is added after the run.

## Part A — B4 implementation

### SC/VSC state model

Coefficients are synthetic placeholders in `track_a_coefficients.json` under `neutralization`.

**Before B4**, the status was drawn independently at each decision (B3: 4% SC, 4% VSC). It only lowered pit loss. It had no duration, no effect on gaps, and no slow laps.

**B4 process** (long format):
- **Starts:** at a GREEN decision, an SC starts with probability 0.035 and a VSC with 0.035.
- **Duration:** drawn from public distributions. SC lasts 1/2/3 segments with probability 0.35/0.50/0.15 (3 laps per segment). VSC lasts 1/2 segments with 0.70/0.30.
- **Cooldown:** at least 1 GREEN segment follows every neutralization.
- **Seeding:** the process is seeded per race and independent of all actions. The schedule is fixed when the race is created.

**Effects of each status:**

| Status | Gaps | Overtaking | Tyre ageing per 3-lap segment | Pit loss |
|---|---|---|---:|---:|
| GREEN | race pace; dirty air; overtaking threshold | yes | 3 laps | × 1.00 |
| SC | everyone runs slow laps, then the field closes to 0.8 s gaps (order kept) | no | 1 lap | × 0.30 |
| VSC | everyone slows equally; gaps kept | no | 2 laps | × 0.55 |

A car that stops under SC loses no time to the field's slow laps, but it rejoins at the back of the compressed train. So it loses track position to every car that was within the pit loss behind it. This is why "SC means pit" is not automatically right.

**Public vs hidden.**
- **Public:** the current status, how many segments it has lasted so far, and the full start/duration model (`event_model` in every race observation and in `f1ctl rules`).
- **Hidden:** the remaining duration, future events and the seed.
- **Planners:** they sample futures from the published model conditioned only on statuses already observed (`engine.sample_future_statuses`).

**Main files changed:** `src/f1pitwall/engine.py`, `coefficients.py`, `fixtures/track_a_coefficients.json`, `analysis/track_a_solver.py` (public conditional sampling), `environment/sim/f1sim/server.py` (rules text) and `instruction.md`. The legacy engine path and the short format are unchanged. The `neutralization_dynamics` ablation restores B3's independent events.

### Event frequency and duration (`devtests/test_neutralization.py`, 6000 seeded races)

- **Start rate per eligible GREEN decision:** matches 0.035 for both SC and VSC (±0.004).
- **Duration distributions:** match the model within ±0.04, counting only episodes that end before the race does.
- **Cooldown:** always respected.
- **Per-race counts:** both SC and VSC average between 0.25 and 0.7 per race.
- **Conditional futures:** after one SC segment, the continuation probability matches P(D ≥ 2) = 0.65. Two different true schedules with the same observed history give identical planner futures, so planners can't see the true future.

The test file has 13 tests in total. Effect tests cover SC compression and order, VSC gap preservation, reduced tyre ageing, the pit-loss ordering SC < VSC < GREEN, position loss for a stop under SC, the ablation, and the observation, which exposes status and segments so far but no remaining duration and no events.

### Counterfactual pairs (`analysis/b4_counterfactual.py`)

**Fair in-race reference ("replan").**
- At every decision it scores all 16 joint actions by playing each now and the public baseline afterwards.
- This is done over 32 public futures conditioned on what has been observed so far.
- It's one-step lookahead, so it's approximate rather than optimal.

**Setup.**
- **Races:** 24 calendars × races 1, 4, 7 (72 races).
- **Paths per race:**
  - a no-event path
  - an SC lasting 2 segments starting at decision 2, 4, 6, 8, 10 or 12
  - a 1-segment VSC at the same decisions
  - 4 representative paths drawn from the public model

**Policies compared on each fixed path** (exact retirement expectation at the finish):
- **no_replan:** the reference's own no-event plan replayed open-loop.
- **always-pit-under-SC:** that plan, but both cars stop at the first SC/VSC decision, with a rule-aware compound.
- **baseline:** the public heuristic.

| Path type | Paths | Replan − no-replan: mean / median / max | Replanning required (> 0.5 pt) | No-change controls (plan unchanged after the event) | Share of post-event decisions where the reference changes its plan |
|---|---:|---:|---:|---:|---:|
| SC (2 segments) at a fixed decision | 432 | 8.79 / 8.71 / 29.01 | 383 | 3 | 0.31 |
| VSC (1 segment) at a fixed decision | 432 | 1.46 / 0.00 / 12.56 | 164 | 93 | 0.24 |
| Representative public paths with ≥ 1 event | 72 | 13.17 / 11.72 / 21.32 | 72 | 0 | 0.30 |
| No event | 72 | 0 | 0 | — | 0 |

**Replan − no-replan by event timing (mean / median; number of paths at most 0.5 pt):**

| Event | Decision 2 | 4 | 6 | 8 | 10 | 12 |
|---|---|---|---|---|---|---|
| SC | 7.3 / 7.8; 14 | 11.2 / 10.7; 0 | 8.6 / 7.7; 0 | 14.8 / 10.7; 0 | 7.4 / 10.6; 16 | 3.4 / 3.9; 19 |
| VSC | 0.6 / 0.0; 52 | 1.2 / 0.0; 52 | 1.8 / 0.0; 40 | 2.6 / 2.9; 30 | 2.1 / 2.0; 31 | 0.4 / 0.0; 63 |

| Regret measure (event paths) | n | mean / median / max |
|---|---:|---:|
| Failing to respond: replan − no-replan, replanning-required paths | 619 | 8.90 / 7.76 / 29.01 |
| Unnecessary change: replan − always-pit-under-SC, no-change paths | 317 | 8.72 / 8.66 / 28.12 |
| Always-pit-under-SC − no-replan, all event paths | 936 | −3.69 / −2.88 / +15.45 |
| Always-pit-under-SC worse than no-replan | 545/936 | — |
| Replan − public baseline, all paths | 1224 | 3.66 / 2.93 / 18.38 |

**Gate-8 example: an event-driven change that changes the outcome.**
- **Race:** S00 race 1, SC at decisions 6–7 (laps 18–24).
- **No replanning:** the no-event plan replayed open-loop scores 19.97 expected points.
- **Replanning:** 34.46. The reference pits Apex A under the first SC segment and Apex B under the second. Staggering the stops avoids the shared-crew queue, and both cars use the cheap pit window.
- **Always-pit-under-SC:** 19.97.
- **VSC at decision 10** in the same race: replanning 42.28 vs 36.44, with one extra stop for Apex B under the VSC.

### Meaningful decisions: B4 vs B3 (`analysis/decision_points.py`)

Same method as B3: one-step lookahead with the baseline playing afterwards; the best action is selected on one set of 48 futures and scored on an independent set. 72 races × 4 public trajectories.

| Format | Decisions per race | Meaningful (stakes > 0.5) per race | Baseline-improvable (gain > 0.25) per race | Mean gain per decision |
|---|---:|---:|---:|---:|
| B3 (independent events, no SC dynamics) | 14 | 6.16 (median 6) | 4.70 (median 4) | 0.78 |
| **B4** | 14 | 5.85 (median 5) | **5.12** (median 4) | 0.81 |

| Status at the decision (B4) | Decisions | Mean gain | Improvable share |
|---|---:|---:|---:|
| GREEN | 3816 | 0.76 | 0.36 |
| VSC | 72 | 0.41 | 0.36 |
| SC | 144 | **2.41** | **0.62** |

- **The last two decisions** (laps 39 and 42) are still never meaningful (stakes and gain 0), so this is re-verified.
- **SC decisions carry about 3× the value** of GREEN decisions, and the baseline gets 62% of them wrong.
- **The count of meaningful decisions per race barely changes.** B4 makes them event-dependent rather than more numerous.
- **No extra decision points were added.** The status is revealed at each 3-lap decision, which already lets a strategy respond within one segment of an SC starting. The value lost to that granularity wasn't measured.

### Validation gates before the frontier run

| # | Gate | Result |
|---:|---|---|
| 1 | B4 mechanics and counterfactual tests | Pass (13 new in `test_neutralization.py`; `devtests` 96/96) |
| 2 | Earlier B3 tests and legacy regression | Pass (all 83 earlier `devtests`; legacy 35/35) |
| 3 | 8-race championship completes | Pass: `b4-oracle-01`, 120 accepted decisions, complete |
| 4 | P0 sidecar boundary | Pass: root probe sees no private paths, no seed or journal files, no simulator process; only `sim.sock` shared |
| 5 | Hidden seed and future events not exposed | Pass: observation tests plus the probe; planners use only conditioned public futures |
| 6 | Action validation and deterministic trace | Pass: duplicates rejected, 1/20 concurrent accepted, journal replays intact |
| 7 | Harbor oracle / nop / root probes | Pass: oracle 0.5873; nop 0; probe-complete 0.5873; probe-stop 0 (incomplete, intact) |
| 8 | An event-driven change affects the outcome | Pass (S00 example above; 619 replanning-required paths) |

Harbor 0.26.0 on Verda; `harbor lint` is clean. The oracle's 120 decisions took 5.1 s of play.

Raw results: `analysis/results/b4_counterfactual.json` and `analysis/results/b4_decision_points.json`.

## Part B — Initial Gemini evaluation (exploratory probe, one run)

This is a single run on a single hidden seed. It's an exploratory probe for failure modes, not a benchmark result.

### Run configuration

| Item | Value |
|---|---|
| Harness | Harbor 0.26.0 on Verda, `-a opencode` (OpenCode 1.19.5), job `b4-gemini-01` |
| Model | `gemini/gemini-3.8-flash` (OpenCode ran `google/gemini-3.8-flash`, thinking on) |
| Task | `f1-championship` at `ebbabce`: full 8-race season, 120 decisions, agent limit 3600 s |
| Network | Agent egress limited to `generativelanguage.googleapis.com`; sim sidecar `network_mode: none` |
| Credentials | `--api-key-name GEMINI_API_KEY --env-file` (permission-restricted file on Verda); no key appears in any downloaded log |

### Outcome

| Item | Value |
|---|---|
| Completion | **Complete**: 120/120 decisions accepted, 0 rejected, 0 protocol errors, journal intact |
| Apex constructors' points | **268**: championship winner (Orion 248, Nova 154, Vertex 100) |
| Reward (provisional P0 scale) | **0.6984** (D = 92 do-nothing on this seed, U = 344) |
| Wall clock | Trial 9 min 01 s (16:59:02 → 17:08:03 UTC); decision span 363 s; 45 agent steps; step gap mean 11.0 s, median 7.1 s, max 58 s |
| Tokens / cost (Harbor) | 2,729,672 input (2,548,658 cached), 13,488 output, about 42k reasoning; **$0.536** |
| Context growth | Prompt grew from 9k to 136k tokens per step |

**How Gemini played.**
1. **Explored** the environment: `f1ctl rules` and `observe`, then read the `f1ctl` source and ran `ps aux`, a glob of `/`, a listing of `/run/f1sim`, a dump of every `/proc/*/cmdline`, and an `os.walk` for files named like "f1" or "sim".
   - It found only its own container. It used only legal commands; the server recorded `observe`, `rules` and `act`, and never `reset` or `seed`.
   - The P0 boundary held.
2. **Played decisions d001–d008 by hand** (race 1 to lap 21), writing small simulations of tyre, pit and wear trade-offs before each move.
3. **Wrote `/app/pitwall_bot.py`** (saved as `analysis/results/b4_gemini_pitwall_bot.py.txt`), a fixed-threshold rule policy over public observations. It played the remaining **112 decisions** (from race 1 lap 24 to the end of the season) in about 7 s.
   - So most of the season measures the quality of a policy the agent wrote, not per-decision reasoning.

### Results per race

| Race | Track | Events (per decision: `.` GREEN) | Apex A / B finish | Points | Replacements |
|---:|---|---|---|---:|---|
| 1 | mixed | `......SS.....V` | P1 / P2 | 43 | — |
| 2 | street | `...S.......VV.` | P6 / P1 | 33 | — |
| 3 | high_speed | `..........VV..` | P3 / P4 | 27 | — |
| 4 | high_degradation | `....V..V......` | P2 / P3 | 33 | — |
| 5 | wet_prone | `..............` | P2 / P6 | 26 | A ICE + turbo, B ICE + turbo (all free, no drops) |
| 6 | street | `..............` | P1 / P3 | 40 | — |
| 7 | high_speed | `..SS..........` | P2 / P3 | 33 | — |
| 8 | mixed | `............V.` | P2 / P3 | 33 | — |
| | | | | **268** | No grid penalties, no retirements, no two-compound penalties |

### Comparison on the same hidden seed (`analysis/seed_baselines.py`) and in expectation

| Policy | Points on this seed | Reward on the P0 scale |
|---|---:|---:|
| Do nothing (always USE, always STAY) | 92 | 0 |
| Public baseline (= Harbor oracle) | 240 | 0.587 |
| Replacement rule + baseline race play | 247 | 0.615 |
| Greedy components + baseline race play | 248 | 0.619 |
| **Gemini** | **268** | **0.698** |
| Replacement rule + B4 in-race rollout reference | 285 | 0.766 |

**Track A in expectation** (component plan with baseline race play; 96 public CRN paths per race):

| Component plan | Expected points |
|---|---:|
| **Gemini** | **247.9** |
| Replacement rule | 245.7 |
| Greedy | 241.2 |
| Always USE | 230.6 |

**Limits of these references.**
- **No full-season reference for the long format.** The P1-D season planner is too slow to run on it (that's B5), so there is no Track A optimum to compare against.
- **The rollout reference** is public-information one-step lookahead (baseline afterwards), combined with replacement-rule components. It handles B4's events, but it is not optimal.
- **Single-seed numbers** (the 17-point gap to 285, or the 20-point lead over the greedy plan) are realized outcomes on one seed. They are not optimality gaps.

### Failure-mode analysis

**Method.**
- **Each race decision is scored with public information only.** The agent's action, the best alternative and the baseline's action are each played now, then a fixed continuation plays the rest of the race. Values are averaged over 48 public futures conditioned only on what the agent had observed. The best action is selected on one future set and every value is re-estimated on an independent set, with a paired standard error.
- **Two continuations are used:** the public baseline, and **Gemini's own bot**.
- **"Confirmed"** means a loss of more than 1 point and more than 2 standard errors under both continuations.
- **"Candidate"** means it holds under only one continuation and needs more checks.
- **Single-seed outcomes are not used** to call anything a failure.

| Category | Decisions | Mean one-step loss vs best (baseline / bot continuation) | Confirmed | Candidates |
|---|---:|---:|---:|---:|
| In-race (GREEN, not right after an SC/VSC) | 91 | 0.63 / 0.49 | 5 | about 13 |
| Replanning (SC/VSC, or the first GREEN after one) | 21 | 0.89 / 0.69 | 1 | 3 |
| Track A (component decisions) | 8 | (season-level comparison above) | 0 | 0 |

**A. Long-horizon resource allocation — no failure observed.**
- **Plan:** Gemini kept every part until race 5, then replaced ICE and turbo on both cars at once, using exactly the 4 free units.
- **Outcome:** zero grid penalties, maximum wear about 0.6, and retirement risk at most about 2.3%. These were its own stated calculations in the bot comments.
- **Reasoning:** it reasoned explicitly about the shared free units and the cost of penalties. It shows no greedy pattern (no early burning of units).
- **Expected value:** its plan scores above the rule and greedy plans.
- **Caveat:** whether it's near-optimal is unknown until B5.

**B. In-race strategy — confirmed failures.**

| Race / decision / lap | Status | Gemini | Best public alternative | Loss (baseline / bot continuation) | Pattern |
|---|---|---|---|---:|---|
| R5 d13 lap 39 | GREEN | Apex B `PIT_SOFT` (HARD at age 24, P2) | STAY | 6.69 / 6.69 | Stops at end of tyre life with 6 laps left. The bot rule "age ≥ life → pit if > 3 laps left" ignores that the cliff over 6 laps costs less than a green stop. |
| R6 d13 lap 39 | GREEN | Apex B `PIT_SOFT` (HARD at age 24, P1) | STAY | 2.89 / 2.89 | Same rule |
| R2 d8 lap 24 | GREEN | STAY (Apex A HARD at age 13, P6) | Apex A `PIT_HARD` | 2.74 / 1.96 | Missed a second stop for the trailing car |
| R2 d9 lap 27 | GREEN | STAY (Apex A HARD at age 16, P5) | Apex A `PIT_HARD` | 1.61 / 2.84 | Same |
| R7 d2 lap 6 | GREEN | STAY (Apex A SOFT at age 6, P2) | Apex A `PIT_HARD` | 2.37 / 1.90 | Missed early undercut off the soft |

**C. Adaptive replanning.**

Confirmed overreaction:

| Race / decision / lap | Status | Gemini | Best public alternative | Loss (baseline / bot continuation) |
|---|---|---|---|---:|
| R2 d13 lap 39 | VSC | Apex A `PIT_SOFT` (MEDIUM at age 8, P3, already three compounds) | STAY | **10.62 / 10.62** |

- **Pattern:** the bot's SC/VSC rule ("stop if past a wear threshold and at least 6 laps left") fires with 6 laps to go. The time lost then cannot be recovered. The public baseline would have made the same move, so this is a shared rule-level flaw.

Candidates (need more checks):

| Race / decision / lap | Status | Gemini | Loss (baseline / bot continuation) | Note |
|---|---|---|---:|---|
| R2 d4 lap 12 | SC | single stop for Apex B | 0.68 / 3.91 | Possible missed double-stack under SC |
| R2 d12 lap 36 | VSC | Apex B `PIT_MEDIUM` | 3.32 / 0.00 | Possible overreaction |
| R7 d3 lap 9 | SC | double-stack | 1.21 / 0.00 | Not clearly a failure |

Other events:
- **R1 SC at laps 21–24:** handled correctly. Gemini pitted Apex A under the SC (manual decision), and that matches the best alternative.
- **R4's VSC stops:** also match the best alternative.

### What this probe shows (and does not)

- **Gemini did not fail at the season level.** It completed the season, won the championship on this seed, beat every rule baseline on the same seed, and had the best component plan among the available comparators. Its losses are concentrated in a few fixed-threshold rules of the bot it wrote: stops at the end of tyre life or under VSC late in the race, and missed second stops for the trailing car.
- **The dominant behaviour is writing a policy, not making each call.** After 8 hand-played decisions, Gemini handed 112 of the 120 decisions to its own script. Per-decision reasoning about SC/VSC timing was replaced by thresholds chosen early in race 1, so the replanning ability this environment is meant to test was mostly not exercised by the model itself.
- **Environment probing.** Gemini actively looked for simulator internals (process list, `/proc` command lines, filesystem search). Isolating the simulator in a sidecar is what kept this from being an exploit path.
- **Not shown:** one run on one seed shows no repeatable gap. The rollout reference scores higher on this seed (285 vs 268), but it is not optimal and this is a single seed.

### Priorities for B5 / Track C (proposed; not implemented)

1. **Repeat with ≥ 3 runs and several hidden seeds** before claiming any gap. Report expected values, using the verifier-side trace tool to score decisions, as well as realized outcomes.
2. **Decide what the benchmark measures when an agent writes a policy.**
   - **Option 1:** accept it (the policy is the agent's decision) and evaluate the written policy across many seeds, which is cheap and more robust.
   - **Option 2:** make per-decision judgement necessary or the measured unit, for example by recording when decisions are delegated to a script.
   - This is a design choice for the team, not something to change silently.
3. **B5 reference:** a long-format full-season planner (component plan plus in-race rollout) so that Track A and in-race gaps can be stated against something stronger than rules. Compute is the limiting factor (B3 cost note); a vectorized rollout engine on the available A100 is an option.
4. **Track C:** the dominant failures are rule-level and late-race (end-of-life and VSC stops with 6 laps left). Engineer reports that flag "remaining laps vs. pit loss" could be tested as the aligned/conflicting variable.

Raw data:
- `analysis/results/b4_gemini_trace.json` (baseline continuation)
- `analysis/results/b4_gemini_trace_botcont.json` (bot continuation)
- `analysis/results/b4_seed_baselines.json`
- `analysis/results/b4_gemini_pitwall_bot.py.txt`

The Harbor job artifacts stay on Verda under `/root/f1-championship-p0/jobs/b4-gemini-01/`.
