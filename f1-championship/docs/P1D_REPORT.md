# P1-D report — does Track A need a long planning horizon over 8 races?

Date: 2026-11-14. No new mechanics, no compound choice, no frontier/OpenCode runs.
The legacy task, the P0 Harbor boundary, the verifier and the reward contract are unchanged.
Raw data: `analysis/results/track_a_p1d.json`. Tables: `python3 analysis/summarize_track_a_season.py`.

## Setup

- **Scenarios:** the same 24 generated calendars as P1-C (generator seed 20261114). Each season starts fresh: all parts new, 4 shared free units. Every scenario is reported.
- **Season-aware fair reference:** `analysis/season_planner.py`, a receding-horizon planner.
  - At each race it searches component plans for the next H races and executes only the first decision.
  - A plan's value is the sum of exact expected race values from the P1-B solver (reused). There is no terminal value beyond the window.
  - Search is local search with block moves (all 64 options for one race), single-part moves, and seeded random restarts.
  - **Compute budget, identical for every H:** 1500 race evaluations and 6000 plan rollouts per decision.
  - Information: public state, the public rival rule, published probabilities and formulas. No seeds, future SC/VSC, retirement draws or internal state (a unit test checks the planning code).
  - **It is not proven optimal:** with twice the budget, H=8 gains +1.2 points on average (max +3.3, 6 scenarios), and H=5 beats it in 5/24 scenarios.
- **Exact evaluation:** component decisions never depend on race outcomes, so each policy's executed season path is deterministic. Its season score is therefore an exact expectation (in-race PIT/STAY uses the public baseline policy). Realized points on 40 shared seeds give the spread.
- **Privileged hindsight:** a separate diagnostic. It knows a seed's realized SC/VSC and retirement draws, runs a budgeted open-loop search warm-started from the reference plan, and is reported as a lower bound on the true hindsight optimum.

## Results

### Horizon ablation (expected season points; regret against the H=8 reference)

| Policy | Mean pts | Regret mean / median / max | Regret > 1 pt | Beats reference | Race evals per decision | s / season |
|---|---:|---:|---:|---:|---:|---:|
| Always USE | 186.23 | 18.26 / 18.16 / 27.81 | 24/24 | 0/24 | 0 | 0.0 |
| Replacement rule (wear ≥ 0.65) | 199.13 | 5.37 / 4.86 / 16.23 | 20/24 | 0/24 | 0 | 0.0 |
| Greedy (H=1) | 197.04 | 7.45 / 9.45 / 12.79 | 23/24 | 0/24 | 64 per race (exhaustive) | 1.5 |
| Planner H=2 | 198.15 | 6.35 / 6.87 / 10.28 | 24/24 | 0/24 | 333 | 21 |
| Planner H=3 | 201.27 | 3.23 / 2.69 / 7.50 | 18/24 | 1/24 | 705 | 37 |
| Exact 3-race DP, receding | 202.27 | 2.23 / 1.37 / 7.44 | 14/24 | 1/24 | 3694 | 303 |
| Planner H=5 | 203.64 | 0.86 / 0.27 / 5.70 | 8/24 | 5/24 | 983 | 44 |
| Planner H=8 (reference) | 204.49 | — | — | — | 990 | 45 |

**Search quality at H=3.** The exact receding 3-race DP beats the budgeted H=3 search by 1.0 points on average (max 7.1, min −3.7), at 5× the compute. So budgeted results carry a search error of roughly that size. Differences under about 1 point between planners should not be read as meaningful.

### Early vs late season, relative to the reference

| Policy | Races 1–4 Δ mean (median) | Races 5–8 Δ mean (median) | Ahead early but behind overall |
|---|---:|---:|---:|
| Greedy (H=1) | +0.26 (+0.21) | −7.72 (−9.76) | 20/24 |
| Planner H=2 | +0.24 (+0.20) | −6.58 (−7.29) | 18/24 |
| Planner H=3 | +0.17 (+0.21) | −3.40 (−2.97) | 18/24 |
| Planner H=5 | +0.09 (+0.00) | −0.94 (−0.29) | 5/24 |
| Replacement rule | −2.17 (−0.56) | −3.20 (−2.38) | 0/24 |
| Always USE | −2.17 (−0.56) | −16.09 (−16.28) | 0/24 |

### Allocation and timing (means)

| Policy | Replacements | First replacement race | In races 1–4 | Races with a grid drop | Grid places | A / B |
|---|---:|---:|---:|---:|---:|---:|
| Greedy | 6.12 | 2.54 | 3.79 | 1.33 | 5.33 | 3.12 / 3.00 |
| Planner H=3 | 6.71 | 2.25 | 3.67 | 1.67 | 6.58 | 3.42 / 3.29 |
| Planner H=5 | 6.25 | 2.58 | 2.21 | 1.25 | 4.92 | 3.38 / 2.88 |
| Reference H=8 | 5.75 | 2.92 | 1.62 | 1.04 | 3.50 | 3.12 / 2.62 |
| Replacement rule | 4.17 | 6.50 | 0.00 | 0.17 | 0.67 | 2.08 / 2.08 |

### Seed spread (40 shared seeds × 24 scenarios = 960 paired seasons)

| Policy | Mean realized | Paired diff vs reference (sd across seeds) | Seeds where it beats the reference |
|---|---:|---:|---:|
| Always USE | 179.29 | −17.72 (6.83) | 3/960 |
| Replacement rule | 191.57 | −5.44 (4.92) | 111/960 |
| Greedy | 189.63 | −7.38 (4.34) | 39/960 |
| Planner H=3 | 193.74 | −3.27 (3.59) | 100/960 |
| Planner H=5 | 196.18 | −0.84 (2.13) | 150/960 |
| Reference H=8 | 197.02 | — | — |

Per-scenario regrets are in the summarizer output. Greedy's regret ranges from 0.02 (S13) to 12.79 (S23).

### Do races 6–8 change races 1–3? (12 scenarios; same races 1–5, races 6–8 swapped)

| Test | Reference's race 1–3 decisions differ | Loss from playing the other world's race 1–3 decisions (mean / median / max) |
|---|---:|---:|
| Decision pair (late high-speed ×3 vs late street ×3), high-speed world | 5/12 | 0.51 / 0.05 / 2.90 |
| Same pairs, street world | — | −0.17 / 0.00 / 3.02 |
| Control (races 6–8 jittered by ±0.03) | 11/12 | 0.11 / 0.23 / 2.22 |
| Greedy regret inside the pair worlds | — | 8.64 / 9.47 / 16.16 |

### Privileged hindsight (same seeds as the reference; 4 runs)

| Scenario / seed | Reference realized | Hindsight PIT/STAY on the reference's component plan | Full hindsight (lower bound) | Greedy realized | Replacement rule realized |
|---|---:|---:|---:|---:|---:|
| S00 / 701 | 203 | 212 | 215 | 189 | 205 |
| S01 / 701 | 173 | 189 | 189 | 170 | 176 |
| S02 / 702 | 199 | 206 | 208 | 190 | 190 |
| S03 / 702 | 177 | 183 | 187 | 170 | 177 |

Of the 9–16 point hindsight gap, about 77% (6–16 points) is recovered by hindsight PIT/STAY alone, with the reference's component plan unchanged.
A first hindsight search without the warm start used too little compute (about 450 plans) and fell below the fair reference in one case. It was discarded as uninformative.

### Representative failure trace — median greedy-regret scenario S10 (regret 9.49)

| Race | Track | Greedy replaces (drops) | Greedy E[pts] | Reference replaces (drops) | Reference E[pts] |
|---:|---|---|---:|---|---:|
| 1 | wet_prone | — | 21.57 | — | 21.57 |
| 2 | wet_prone | A:turbo, A:ES, B:ICE, B:turbo, B:ES (B −2) | **21.89** | — | 21.68 |
| 3 | street | — | 33.85 | — | 33.85 |
| 4 | high_speed | — | 22.36 | A:ICE | 22.36 |
| 5 | wet_prone | A:turbo (A −2) | 22.10 | B:ICE, B:ES | 22.67 |
| 6 | mixed | A:ES, B:ES (A −2, B −2) | 23.44 | A:ICE, A:turbo, B:turbo (A −2, B −2) | 24.15 |
| 7 | mixed | — | 22.38 | — | 24.85 |
| 8 | high_speed | A:ICE (A −4) | **15.33** | — | 21.28 |
| | **Total** | | **182.92** | | **192.41** |

- **Race 2:** greedy uses all four free units plus a penalty, for +0.21 expected points. Every later replacement then costs grid places.
- **Race 8:** greedy ends up with a forced ICE replacement and a 4-place drop at a high-speed track.
- **The reference** spreads replacements over races 4–6 and gives up 0.21 points early to save about 9.7 later.
- **The worst case, S23** (regret 12.79), follows the same pattern: early B:ICE/ES/turbo, then three penalised replacements for A in races 6–8.

## Answers

**1. How does the 3-race mean gap of 1.47 points change over 8 races?**
- **Greedy regret** grows to a mean of **7.45**, median 9.45 and max 12.79. That is about 3.6% of the reference's points, and greedy is worse than the reference in 23/24 scenarios.
- **On realized points** greedy beats the reference on only 39 of 960 paired seeds. The paired difference is −7.38 (sd 4.34).
- **Why it grows:** P1-C started from mid-season states. A full season gives greedy time to spend its free units early (3.79 replacements in races 1–4 vs 1.62 for the reference) and then pay for them later.

**2. Is the 8-race planner meaningfully better than greedy and short horizons?**
- **Against greedy and H ≤ 3: yes.** H=1/2/3 regrets are 7.45 / 6.35 / 3.23, all larger than the search error (about 1 point). The receding exact 3-race DP still loses 2.23.
- **H=5 vs H=8:** only 0.86 apart, and H=5 beats H=8 in 5/24 scenarios. That difference is within search error and budget sensitivity (+1.2 with 2× budget). **The benefit of horizon flattens out around 5 races.**
- **The reference is not proven optimal.** A simple rule, "replace at wear ≥ 0.65", gets within 5.37 and beats greedy and H=2.

**3. Does information about races 6–8 actually affect race 1–2 decisions?**
- **Not measurably in the current model.**
- **Race 1 is never a decision:** every part is new, so USE is the only sensible choice.
- **Races 1–3 decisions:** they differ in 5/12 decision pairs, but in 11/12 control pairs as well. Playing the other world's race 1–3 decisions costs a median of about 0 (mean 0.51 / −0.17, max about 3). That is within the planner's search noise.
- **What creates the long-horizon cost** is the general scarcity of free units across the whole season, not the specific character of the late tracks. Long-horizon planning is needed in the sense that **you must not spend units early**. It is not needed in the sense that **you must read the late calendar to decide early**.

**4. Is Track A alone enough to be worth evaluating frontier agents on?**
- **Worth a frontier probe, not enough on its own as the main benchmark.**
- **For:**
  - There is a robust gap between myopic and season-aware play: 7.5 points, 23/24 scenarios, consistent across seeds.
  - Doing nothing is heavily penalised (−18).
  - The failure pattern is easy to recognise in a trace: spending free units early and taking penalties late.
- **Against:**
  - (a) A one-line threshold rule recovers most of the gap (regret 5.37), so an agent with ordinary "replace worn parts" sense may land between greedy and the reference without real planning.
  - (b) The only lesson needed is "units are scarce, don't burn them early", which a frontier model may infer from the instruction.
  - (c) Early decisions don't depend on reading the late calendar.
  - (d) There are only 8 component decisions per season.

**5. What justifies adding compound choice or Track B dynamic events?**
- **Most of the remaining headroom is in-race.** Of the 9–16 point hindsight gap per season, about 77% is recovered by optimizing in-race PIT/STAY alone, with the component plan unchanged. Only 0–4 points come from replanning components.
- **Caveats:** this is a hindsight bound on 4 seeds and uses future knowledge, so it overstates what fair play can reach. Even so, in-race decisions put more points at stake than component allocation does.
- **Track A's long-horizon value levels off by H≈5**, and late-track characteristics barely move early decisions.
- **What Track B would add:** more decisions per race and real information revealed during the race (SC/VSC timing now; forecasts and compound choice later). That would test contingent replanning, which Track A lacks.
- **Recommendation for the next step:** add compound choice and more decision points (Track B), keeping Track A's season-level resource coupling as-is. Then check whether the combined task makes greedy or a simple rule fall further behind a fair planner. Coefficients would stay untouched.

## Limits

- **Budget-limited reference and search noise.** The reference is a budgeted search and the H=8 budget is not converged (+1.2 with 2× budget). The H=3 search is up to 7 points below the exact DP in single scenarios.
- **Fixed race policy.** In-race play is the same public baseline policy for every planner, so planners only differ in component decisions.
- **Small samples.** 24 scenarios; pairs on 12; hindsight on 4 seeds.
- **Synthetic coefficients.** All coefficients are synthetic placeholders.
