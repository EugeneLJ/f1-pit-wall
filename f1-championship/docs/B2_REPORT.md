# B2 report — pit-stop strategy and shared pit crew (Track B, step 2)

Branch `feature/track-b`, on top of B1. Still 3 decisions per race (B3 expands that). No frontier runs.

## What changed

All values live in `track_a_coefficients.json` under `pit_stops` and are synthetic placeholders.

| Item | Rule |
|---|---|
| Pit-lane loss by track | GREEN loss by archetype: street 22 s, wet_prone 21, high_degradation 20, mixed 20, high_speed 19 |
| Pit loss under VSC/SC | × 0.55 under VSC, × 0.30 under SC (legacy was a flat 18 / 10 / 5 s) |
| Shared crew, all teams | When two cars of one team pit at the same decision, the car that arrives second on the road waits 6 s. Before B2 only Apex B ever waited, and rivals never queued. |
| Out-lap warm-up | The first segment on new tyres adds SOFT 0.3 s, MEDIUM 0.6 s, HARD 1.0 s. This sets how strong an undercut is. |
| Observation | The race view shows this track's pit losses per status, the queue time, warm-up per compound, and which Apex car would be serviced first if both pit. Each calendar entry shows its GREEN pit loss. |
| Ablations | `pit_loss_by_track` (20 s everywhere), `double_stack_queue` (no queue), `tyre_warmup` (none) |

The legacy engine path is unchanged: it still uses flat losses and Apex-B-only queueing, and it matches the frozen root engine on all 64 action sequences.

**Deliberately not added: random slow stops.** A seeded slow-stop draw for every car at every stop would make the solver's exact in-race expectation enumerate 2^(cars pitting) outcomes at each decision. It's recorded as a candidate for later, if B4/B5 move to sampled evaluation.

## Level (a) — `devtests/test_pit_stops.py` (10 tests)

- **Pit loss:** varies by track and by status; the ablation makes it equal; a pit stop costs about the track loss on the road.
- **Queue:** the second car to arrive waits whichever driver it is (checked by swapping grid slots); the observation names who is serviced first; the queue ablation removes the wait; rival teams queue too (both Nova cars under SC).
- **Warm-up:** harder compounds warm up slower; the warm-up applies only to the out-lap segment; its ablation removes it.
- **Public information:** pit data appears in the calendar and in race observations; the race configuration carries the track's pit model.

## Levels (b) and (c) — exact in-race expectimax

`analysis/race_expectimax.py`, 72 races (24 generated calendars × races 1, 4, 7), public-rule history. Values are exact expected Apex points per race. No seeds are read.

| Comparison | Mean | Median | Max | Races > 0.5 pt |
|---|---:|---:|---:|---:|
| Fair optimum − baseline heuristic | 2.93 | 2.41 | 6.73 | 72/72 |
| Value of compound choice (vs compound-blind with optimal timing) | 1.17 | 0.85 | 2.83 | 52/72 |
| Compound-blind with optimal timing − baseline | 1.77 | 1.68 | 4.08 | 64/72 |
| Baseline − always STAY | 18.60 | 17.51 | 27.05 | 72/72 |

| Mechanic off | (b) Fair optimum − baseline | (c) Optimal first decision changes | (c) Real-world loss of the decision that is optimal with it off: mean / max |
|---|---:|---:|---:|
| double_stack_queue | 3.94 | 56/72 | **0.32 / 2.50** |
| two_compound_rule | 4.38 | 64/72 | 0.46 / 1.49 |
| tyre_warmup | 3.30 | 36/72 | 0.07 / 0.62 |
| pit_loss_by_track | 2.85 | 21/72 | 0.01 / 0.43 |
| tyre_cliff | 2.93 | 0/72 | 0.00 / 0.00 |

**Is the optimal first decision a double stack?**

| Status | Races where the optimal first decision double-stacks |
|---|---:|
| GREEN | 0/72 |
| VSC | 28/72 |
| SC | 57/72 |

## Reading

- **The shared-crew queue creates a real decision.**
  - A double stack is never optimal under GREEN, but it is optimal under SC in most races, even after paying the 6 s queue.
  - Ignoring the queue costs up to 2.5 points in a race.
  - The baseline heuristic never double-stacks unless the two-compound rule forces it. That accounts for part of the 2.9-point gap between the optimum and the baseline.
- **Track pit loss and warm-up mostly change near-ties.**
  - They change the optimal first decision often (21/72 and 36/72).
  - But the real-world cost of ignoring them is tiny (0.01 and 0.07 mean).
  - They count as realism, not as sources of difficulty, at the current decision density.
- **The tyre cliff has no effect on first decisions** (0/72) now that warm-up and track losses push good play towards harder compounds and earlier stops.
- **The two-compound rule** remains the strongest single shaper of when to stop.
- **The fair in-race gap** (2.93 per race) is about the same as in B1 (3.00). B2 changed which decisions matter (double-stack timing) more than how much in total.

## Verification

- **Tests:** `devtests` passes 76/76 and the legacy tests pass 35/35, with legacy files untouched.
- **Harbor 0.26.0 on Verda:**
  - `harbor lint` is clean.
  - `b2-oracle-01` reward 0.5388.
  - `b2-nop-01` reward 0.
  - `b2-probe-complete-01` (root): no private paths visible; only `sim.sock` on the shared volume; duplicates rejected; 1 of 20 concurrent submissions accepted; reward identical to the oracle.
  - The do-nothing baseline D on the same seed is now 99 points.
- **Raw results:** `analysis/results/b2_race_value.json`.

## Effect on earlier results

- **B1's table** (`b1_compound_value.json`) was measured before B2. The B2 table above supersedes it for the current engine.
- **Track A season results** (P1-C/D, tag `track-a-v1`) still need re-measuring under the Track B engine. That's planned for B5.
