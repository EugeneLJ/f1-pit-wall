# B4 report — SC/VSC-driven adaptive replanning and an initial frontier probe

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

## Part B — Initial Gemini evaluation

Pending: added after the run.
