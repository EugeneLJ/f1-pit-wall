# B1 report — tyre compound choice and tyre model (Track B, step 1)

Branch `feature/track-b`. The baseline is tag `track-a-v1` (5b0e7f7).
No new decision points yet (still 3 per race; that's B3). No frontier runs.

## What changed

| Item | Rule (coefficients in `track_a_coefficients.json` → `tyres`, synthetic) |
|---|---|
| Race action | Per driver `STAY`, `PIT_SOFT`, `PIT_MEDIUM`, `PIT_HARD`. A bare `PIT` is rejected in championship races; the legacy engine path still accepts `PIT`/`STAY` unchanged. `legal_actions` is in every race observation. |
| Compounds | Legacy offsets and linear degradation (SOFT −0.55 s, 0.35 s/lap; MEDIUM 0, 0.14; HARD +0.28, 0.055), scaled by the track degradation multiplier |
| Tyre life / cliff | Life 10 / 16 / 24 laps. Beyond its life a tyre adds `0.25 · deg_multiplier · (age − life)` s/lap |
| Two-compound rule | Each car must race on two compounds (the starting one counts); otherwise +20 s at the finish |
| Rival compounds | Public rule. When pitting, rivals take SOFT if ≤ 6 laps remain, MEDIUM if ≤ 14, else HARD, switching if that would break the two-compound rule. A rival on one compound pits at the last decision. Rivals pit at the end of tyre life rather than at legacy age limits. |
| Observation | `laps_remaining`; compounds used per Apex car and per classified car; penalty and compounds in the race result |
| Baseline heuristic (`solution/play.py`) | Same stop timing as before. Compound from laps remaining; a stop at the last decision if needed for the rule; no double-stacking unless both cars need the rule |
| Ablations | `compound_choice` (MEDIUM only), `tyre_cliff` (linear only), `two_compound_rule` (no rule) |

**Bugs found and fixed while adding this.**
- **Shared list across copies.** The solver's race-copy shared the new per-car `compounds_used` list between event-tree branches.
- **Penalty missing from expectations.** The exact expected-points function ignored the finish penalty. It now uses a shared `engine.finish_penalty`, with a regression test against `engine.result`.

## Level (a) — `devtests/test_tyres.py` (12 tests)

- **Actions:** compound fitting and recording; the bare `PIT` is rejected in configured races but still accepted on the legacy path; the medium-only ablation; double-stacking with compound stops.
- **Tyre model:** soft is faster when fresh and degrades faster; the cliff scales with track degradation and switches off cleanly.
- **Two-compound rule:** the penalty applies, its ablation removes it, and the solver's expectation includes it.
- **Rivals:** they follow the public compound rule and meet the two-compound rule in a full race.

## Levels (b) and (c) — in-race value of the tyre mechanics

`analysis/race_expectimax.py` runs an exact expectimax for one race. It covers every SC/VSC/GREEN path (with the status observed before each decision), all 16 joint Apex actions, and exact retirement expectations. It reads no seeds.

The sample is 24 generated calendars × races 1, 4 and 7, with public-rule history: 72 races. Values are exact expected Apex points per race.

| Comparison | Mean | Median | Max | Races > 0.5 pt |
|---|---:|---:|---:|---:|
| Value of compound choice: optimal − compound-blind with optimal timing* | 1.32 | 1.12 | 3.31 | 50/72 |
| Compound-blind with optimal timing − baseline heuristic | 1.68 | 1.43 | 4.67 | 61/72 |
| Fair optimum − baseline heuristic | 3.00 | 2.64 | 7.37 | 68/72 |
| Baseline heuristic − always STAY | 18.24 | 16.05 | 28.88 | 72/72 |
| Fair optimum − baseline, tyre cliff off | 3.08 | 2.77 | 7.62 | 68/72 |
| Fair optimum − baseline, two-compound rule off | 4.00 | 3.34 | 8.86 | 72/72 |

\* Compound-blind: a stop fits MEDIUM, or HARD when MEDIUM is the car's only compound so far, so the rule can always be met. The timing of stops is still optimized. A plain medium-only restriction would make the rule impossible for a car that started on MEDIUM and would overstate the value of choice, so it isn't used.

**Level (c): changes to the optimal first decision.**
- **Two-compound rule:** switching it off changes the optimal first decision in **65/72** races. The rule shapes when the car must stop.
- **Tyre cliff:** switching it off changes the optimal first decision in **1/72** races. With 12 laps left at the first decision and lives of 10–24 laps, good play rarely reaches the cliff. It mostly punishes bad play, so it counts as realism rather than a source of difficulty at the current decision density.
- **Optimal first decisions across all statuses:**
  - PIT_HARD/STAY: 78
  - PIT_HARD/PIT_HARD: 73
  - PIT_MEDIUM/STAY: 55
  - PIT_MEDIUM/PIT_HARD: 10
- **SOFT** is never optimal at the first decision (12 laps remaining). Its role should be checked at later decisions and in B3's longer races.

## Reading

- **Compound choice adds real in-race value.** It averages 1.3 points per race (about 10 per season). The fair-optimum vs baseline gap is 3.0 points per race (about 24 per season, upper estimate). That gap is larger than Track A's 7.45-point greedy season regret.
- **This matches P1-D's hindsight split,** where most of the headroom was in-race.
- **Doing nothing is now punished hard** (−18 points per race), which strengthens reward integrity.
- **The tyre cliff is weak** at three decisions per race. It needs B3's longer races to matter.

## Verification

- **Tests:** `devtests` passes 66/66; the legacy tests pass 35/35, and the legacy files are untouched.
- **Harbor 0.26.0 on Verda:**
  - `harbor lint` is clean.
  - `b1-oracle-01` reward 0.5198.
  - `b1-nop-01` reward 0.
  - `b1-probe-complete-01` (root): no private paths visible; only `sim.sock` on the shared volume; duplicates rejected; 1 of 20 concurrent submissions accepted; reward identical to the oracle.
- **The oracle reward rose** from 0.2548 to 0.5198. The provisional P0 formula is unchanged. The do-nothing baseline D on the same seed fell from 136 to 92 points because it now breaks the two-compound rule, and the heuristic plays better.

## Effect on Track A results

- **P1-C and P1-D numbers are tied to `track-a-v1`** and are not re-measured here.
- **The in-race baseline policy changed.** It now chooses compounds, so the absolute season points of every component policy will change.
- **Re-measuring** the horizon ablation under the B1 engine belongs in B5, where Track A and Track B difficulty are compared.
