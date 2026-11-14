# B3 report — more decision points per race (Track B, step 3)

Branch `feature/track-b`, on top of B1–B2. No frontier runs.

## What changed

| Item | Rule (`track_a_coefficients.json` → `race_format`, synthetic) |
|---|---|
| Race format (default `long`) | 45 laps; a `RACE_STRATEGY` decision every 3 laps from lap 3 to lap 42, so **14 decisions per race** and **120 per season** (8 × (1 component + 14)), up from 32 |
| Start | Grid gaps scaled to a lap-3 spread (× 0.4 of the legacy lap-8 gaps); every car on 3-lap-old starting tyres |
| Event odds | Per decision: GREEN 0.92, VSC 0.04, SC 0.04, i.e. about 0.56 SC and 0.56 VSC per race. The legacy odds (0.25/0.15) would give more than 2 SCs per race. Events are still independent per decision; SC/VSC duration is B4. |
| Short format | The `long_race_format` ablation restores the 3-decision format (laps 8/12/16, 4-lap segments, legacy odds). The B1/B2 exact single-race analyses run in this format and stay reproducible. |
| Engine | Segment length, decision laps, grid spacing, starting tyre age and event odds come from the race configuration. The legacy path is unchanged and still matches the frozen engine on all 64 action sequences. |
| Observation | Adds per-decision event odds, segment length and the tyre-life table (`decision_count`, `lap` and `laps_remaining` were already there) |
| Agent time limit | Raised from 1800 s to 3600 s for 120 decisions |

**Solver changes.**
- An exact event tree over 14 decisions would need 3^14 ≈ 4.8M paths. Up to 4 remaining decisions the exact tree is kept.
- Longer races use the mean over **96 fixed public event paths**: drawn from the published odds with a seed derived only from the race format, never the hidden seed, and shared by every compared option. Retirements stay exact.
- Exhaustive hindsight is refused for long races (`NotImplementedError`) rather than silently attempted.

**Baseline heuristic (`solution/play.py`), adapted to long races.**
- It stops once a tyre reaches its published life, but only if at least 3 segments remain.
- A first version stopped one segment before the end of life even late in the race. That made its own late moves worse than doing nothing by up to 5.6 points. The analysis exposed this and it was corrected before the final measurements.

## Level (a) — `devtests/test_race_format.py` (6 tests)

- **Format:** 14 decisions over 45 laps in 3-lap segments.
- **Start:** grid spread and starting tyre age as configured.
- **Event schedule:** matches the published odds over 4000 seeded races (about 0.3–0.9 SC per race).
- **Short format:** reproduces the legacy decision laps, segment length and odds.
- **Observation:** publishes the odds, the tyre-life table and race progress.
- **Season:** a full season has 120 decisions.

Other tests were made format-aware:
- **Decision counts and race events:** the boundary and wear tests now derive them from the format.
- **Exact-tree and planner-logic tests:** these pin the short format, where exact enumeration is possible.
- **Monte Carlo path:** a new test checks that the long-format expectation is the deterministic mean over the public paths.

## Are the extra decision points meaningful? (`analysis/decision_points.py`)

**Method.**
- 24 calendars × races 1, 4 and 7, each played by the baseline along 4 fixed public event paths.
- At every decision, all 16 joint actions are scored by playing them now and then letting the baseline continue, over 48 shared public futures.
- The best action is **selected on one set of 48 futures and scored on an independent set**, so the maximum over actions is not biased upward.
- **Meaningful:** the best action beats STAY/STAY by more than 0.5 points.
- **Baseline-improvable:** the best action beats the baseline's own choice by more than 0.25 points.
- This is one-step lookahead with the baseline continuing afterwards, so it is a lower bound on what full replanning can gain.

| Format | Decisions per race | Meaningful per race (mean, median) | Baseline-improvable per race (mean, median) | Mean one-step gain per decision | Max |
|---|---:|---:|---:|---:|---:|
| Short (3 decisions) | 3 | 2.44 (2) | 1.26 (1) | 0.82 | 8.39 |
| **Long (14 decisions)** | 14 | **5.80 (5)** | **4.14 (4)** | 0.70 | 6.71 |

| Decision | Lap | Mean stakes | Mean gain | Meaningful share | Improvable share |
|---:|---:|---:|---:|---:|---:|
| 1 | 3 | 2.17 | 2.17 | 0.57 | 0.57 |
| 2 | 6 | 2.09 | 2.09 | 0.74 | 0.78 |
| 3 | 9 | 1.83 | 1.83 | 0.74 | 0.82 |
| 4 | 12 | 4.77 | 0.11 | 1.00 | 0.06 |
| 5 | 15 | 0.16 | 0.16 | 0.16 | 0.18 |
| 6 | 18 | 3.29 | 0.07 | 0.91 | 0.06 |
| 7 | 21 | 0.37 | 0.37 | 0.18 | 0.20 |
| 8 | 24 | 0.82 | 0.40 | 0.32 | 0.24 |
| 9 | 27 | 0.41 | 0.42 | 0.23 | 0.23 |
| 10 | 30 | 0.71 | 0.71 | 0.30 | 0.36 |
| 11 | 33 | 2.51 | 0.87 | 0.53 | 0.34 |
| 12 | 36 | 0.28 | 0.66 | 0.12 | 0.31 |
| 13 | 39 | 0.00 | 0.00 | 0.00 | 0.00 |
| 14 | 42 | 0.00 | 0.00 | 0.00 | 0.00 |

| Status at the decision | Decisions | Mean gain | Improvable share |
|---|---:|---:|---:|
| GREEN | 3816 | 0.73 | 0.30 |
| VSC | 144 | 0.10 | 0.15 |
| SC | 72 | 0.59 | 0.24 |

## Reading

- **More meaningful decisions, but not all 14.**
  - The long format gives about **5.8 meaningful decisions per race** (2.4× the short format) and about **46 per season**, of which about 33 leave value on the table for the baseline.
  - Decisions 13–14 (laps 39–42) are never meaningful, because no stop pays off with 6 or fewer laps left.
  - Decisions 5, 7, 9 and 12 are rarely meaningful.
  - The 13–18 target counts decision *points*. The *meaningful* count under the current mechanics is about 6 per race.
- **Where the baseline loses most:**
  - **Early race (laps 3–9):** the start-tyre and first-stop strategy, mean gain about 2 points per decision. The baseline is too passive here.
  - **Around lap 33:** the second stop.
  - At laps 12 and 18 the stakes are high (a stop is clearly needed), but the baseline already does the right thing.
- **SC/VSC decisions are rare.**
  - Only 216 of 4032 decisions happen under SC or VSC, because events are independent per decision at 4% each.
  - Event-driven replanning (Track B's dynamic-events goal) needs B4: SC/VSC duration, field compression and forecasts. Not just more decision points.
- **Track A interaction.** The overtaking effect on grid-penalty cost is now larger for Apex B: 1.84 points at difficulty 0.1 vs 5.04 at 0.9. It's small for Apex A (2.82 vs 3.02).

## Verification

- **Tests:** `devtests` passes 83/83 and the legacy tests pass 35/35, with legacy files untouched.
- **Harbor 0.26.0 on Verda:**
  - `harbor lint` is clean.
  - `b3-oracle-01`: reward 0.5556; 120 accepted decisions; complete and intact.
  - `b3-nop-01`: reward 0.
  - `b3-probe-complete-01` (root): no private paths visible; only `sim.sock` on the shared volume; duplicates rejected; 1 of 20 concurrent submissions accepted; reward identical to the oracle.
- **Timing (oracle):**
  - The 120 decisions take 5.3 s of play.
  - Mean gap between decisions 0.025 s; worst server latency 44 ms.
  - The Harbor trial takes about 50 s.
  - Frontier agent time hasn't been measured. 120 LLM turns at a few seconds each should fit the 3600 s limit.
- **Raw results:** `analysis/results/b3_decision_points.json`.

## Cost note for B5

- **Race evaluation.** A long-format race value costs about 96 × 14 engine steps, versus about 39 for the short-format exact tree.
- **The P1-D season planner** (1500 race evaluations per decision) would be roughly 25–35× slower on the long format.
- **B5** therefore needs fewer public paths, a cheaper in-race surrogate for component planning, or more compute (more cores).
