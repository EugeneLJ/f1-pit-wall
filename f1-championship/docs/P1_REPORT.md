# P1-A to P1-C report — Track A long-horizon mechanics

Date: 2026-11-14. Scope: P1-A (mechanics plus level-a tests), P1-B (exact reduced-season
solver, fair reference, hindsight oracle), P1-C (counterfactual and control pairs,
representative scenarios, policy gaps). No frontier or API run was performed. P1-D
(compound choice and other race mechanics, the 8-race reference, the first frontier
probe) is pending review.

All coefficients are synthetic placeholders and live only in
`src/f1pitwall/fixtures/track_a_coefficients.json`.

## P1-A: what changed in the simulator

| Mechanic | Rule | Track-A role |
|---|---|---|
| Wear → pace | `Σ k_c · stress · wear_c²` s/lap (k = 0.30 / 0.20 / 0.15) | Old parts cost more at high-stress tracks |
| Wear → reliability | `p_dnf = 0.02 + Σ r_c · stress · max(0, wear_c − 0.5)²`, cap 0.6 | Running worn parts is a risk, not just a slowdown |
| Wear accrual | `wear += stress · rate_c` after each race (0.22 / 0.18 / 0.14), independent of race events | Deterministic, plannable state |
| Use limit | USE illegal above 0.90 wear; REPLACE always legal | Replacement eventually becomes forced |
| Shared free units | 4 per team, shared by both drivers | Which driver gets the scarce unit, and when |
| Grid penalty | No free unit → ICE 4 places, turbo/ES 2 places | Using a unit early has a later cost |
| Team track profiles | Published pace offset per archetype; each team's offsets average to zero | Track order changes who is competitive; no team gains on average (Orion not weakened) |
| Overtaking | Pass only if margin ≥ 0.2 + 2.0·difficulty s per 4-lap segment; gap-based dirty air (0.15 s/lap within 1.0 s) replaces the legacy positional traffic term in configured races | Grid-drop cost depends on the track |
| Tyre degradation | Degradation × (0.5 + track tyre_degradation) | Track-dependent race behaviour |
| Qualifying | Grid ordered by published pace incl. wear, then drops | Wear and penalties act through the grid |
| Rivals | Public rule: replace any part with wear ≥ 0.65 | Rival state is inferable from public history |

Information exposed to the agent (identical for the fair planner):
- Full completed and remaining calendar with track parameters.
- Apex wear, legal actions, the cost of a replacement, free units, and projected pace loss and retirement probability.
- Rivals' public component usage, team free units, grid drops, and a published pace estimate.
- All formulas and coefficients via `f1ctl rules`.

Not exposed:
- Seeds, future SC/VSC, retirement draws.
- Rivals' raw wear numbers. They can be inferred from the public rule plus history.

The legacy path is unchanged. The unconfigured engine matches the frozen root engine
on every one of the 64 action sequences × 2 seeds (unit test). The P0 Harbor boundary
was re-verified on Verda with the P1 mechanics:
- `p1-oracle-01`: reward 0.2548
- `p1-nop-01`: reward 0
- `p1-probe-complete-01`, run as root: secrets not visible, duplicates rejected, 1 of 20 concurrent submissions accepted, reward unchanged at 0.2548

**A model flaw found and fixed along the way.** With the legacy positional traffic term
(0.1 s/lap per position behind P1), the cost of a grid drop did not depend on
overtaking difficulty. Position itself made a car slower, which swamped the
overtaking effect. Replacing it with gap-based dirty air in configured races fixed
this. The direction of the effect is measured, not imposed (see the penalty-cost table).

## P1-B: solver, fair reference, hindsight oracle (`analysis/track_a_solver.py`)

- **Reduced season.** The final three races (indices 5–7) of an 8-race championship. The state at race 5 comes from public-rule history.
- **Fair optimum.** An exact dynamic program over Apex component decisions:
  - Each race's expected points are computed exactly: over all 27 SC/VSC/GREEN paths with the published probabilities, and exactly over retirements (each car retires independently with its published probability).
  - Wear never depends on race events, so the season transition is deterministic and expectations add across races.
  - In-race PIT/STAY uses the same public baseline policy for every compared component policy, so the comparison isolates Track A decisions.
  - It uses only information the agent can see or infer.
- **Hindsight oracle (diagnostic only).** Knows the seed's realized SC/VSC schedule and retirement draws, and optimizes component and PIT/STAY decisions. Retirement depends on wear, so every candidate plan is replayed against the same action-independent draws.
- **Correctness checks:**
  - Unit tests: the retirement expectation and the event-tree expectation match brute-force enumeration, and greedy equals optimal in a final race.
  - The solver's realized path matches a live `ChampionshipSession` point for point.
  - Monte Carlo, with 300 seeds through the real engine: exact 77.08 vs MC 77.10 ± 0.43; 74.32 vs 74.29 ± 0.43; 88.96 vs 89.12 ± 0.59; 87.83 vs 87.82 ± 0.58.
- **Cost:** about 40 s per scenario for the fair DP (≈6k race evaluations) and about 220 s per seed for the hindsight oracle.

## P1-C: results on 24 generated scenarios (`analysis/run_track_a.py`, generator seed 20261114)

**Scenario generator.** Each scenario gets a random 8-race calendar: each round's archetype is drawn uniformly, and its parameters are drawn from that archetype's synthetic ranges. History (races 1–5) comes from public rules. Apex's early habit is either the rival rule or always-USE. Every one of the 24 scenarios is reported; none were selected.
Raw data: `analysis/results/track_a_p1.json` and `analysis/results/track_a_p1_cross.json`.

### Policy gaps (exact expected Apex points over the final 3 races)

| Policy | Mean expected pts | Mean regret vs fair optimum | Regret > 1 pt | Max regret |
|---|---:|---:|---:|---:|
| Fair optimum (DP) | 77.13 | — | — | — |
| Greedy (best for the current race only) | 75.66 | 1.47 | 12/24 | 5.56 |
| Rival rule (replace at wear ≥ 0.65) | 74.51 | 2.62 | 18/24 | 10.03 |
| Always USE (replace only when forced) | 61.61 | 15.52 | 24/24 | 25.04 |

- **Greedy, the locally rational choice, loses value across the season.** Its first decision alone, followed by optimal play, costs a mean of 0.89 pts (10/24 scenarios > 0.5 pt). Typically it spends free units on a part, or a driver, that gains most in the current race, and later replacements then cost grid places.
- **The gap is real but modest under the current coefficients:** about 1.9% of the season's points on average, up to 5.6 pts. I have not tuned coefficients to enlarge it.
- **Doing nothing is clearly punished.** Always-USE loses 15.5 pts, which supports reward integrity: a do-nothing policy is not close to good play.

### Mechanic verification: levels (a), (b), (c)

Level (a) — every mechanic changes state or outcomes. Unit tests in `devtests/test_track_a_mechanics.py`.

Levels (b) and (c): each row switches one mechanic off and re-solves all 24 scenarios. "Decision loss" is the expected cost in the real world of acting on the first decision that would be optimal with that mechanic switched off. This measures how much the mechanic changes the best first decision, rather than merely whether it changes it.

| Mechanic off | (b) Δ optimum | (b) Greedy regret on → off | (b) Always-USE regret on → off | (c) Decision loss, mean (scenarios > 0.5 pt) |
|---|---:|---:|---:|---:|
| allocation_limit (unlimited free units) | +0.75 | 1.47 → 0.02 | 15.52 → 16.77 | 2.52 (17/24) |
| grid_penalty (no penalty) | +0.75 | 1.47 → 0.02 | 15.52 → 16.77 | 2.52 (17/24) |
| wear_pace | −2.15 | 1.47 → 0.01 | 15.52 → 3.64 | 0.54 (8/24) |
| team_profiles | −4.03 | 1.47 → 0.50 | 15.52 → 11.25 | 0.91 (11/24) |
| shared_pool (split 2 + 2 per driver) | +0.03 | 1.47 → 1.32 | 15.52 → 15.55 | 0.43 (4/24, max 4.80) |
| overtaking (same difficulty everywhere) | +0.16 | 1.47 → 1.91 | 15.52 → 15.86 | 0.22 (4/24) |
| tyre_degradation (same everywhere) | −0.58 | 1.47 → 1.34 | 15.52 → 15.88 | 0.13 (1/24) |
| reliability | +0.01 | 1.47 → 2.64 | 15.52 → 12.95 | 0.09 (2/24) |

**Reading the table:**
- **Scarcity is what causes greedy's loss.** With unlimited free units, or with no grid penalty, greedy regret falls to 0.02. Those two ablations give identical numbers because both make every replacement free.
- **Wear-driven pace loss creates the reason to replace.** Without it, greedy regret is about 0 and always-USE regret drops from 15.5 to 3.6.
- **Strong at levels (b) and (c):** the free-unit limit, grid penalties, wear→pace and team profiles.
- **Shared pool:** matters in a few scenarios (max 4.8 pts) but is small on average.
- **Weak at level (c):** overtaking, tyre degradation and reliability. They affect outcomes (level a), and reliability affects policy values (b): without it, greedy gets worse and always-USE better. But they rarely change the best first component decision. They are kept as realism, not as sources of difficulty.
- **The penalty-cost table below** shows that overtaking difficulty changes the cost of a grid drop, but not in one consistent direction. That direction is a modelling result, not an imposed property.

### Counterfactual and control pairs

Each pair has the same history and the same race 6; only races 7–8 differ.

- **Decision pair:** a late high-speed double-header vs a late street double-header. This is natural because real calendars cluster similar venues, and power-unit stress and overtaking difficulty move in opposite directions between these two archetypes.
- **Control pair:** the original late races vs the same archetypes with every parameter jittered by at most ±0.03, a statistically indistinguishable calendar.

| Pair | Optimal race-6 decision differs | Cost of using the other variant's optimal decision |
|---|---:|---:|
| Decision: street-optimal decision used in the high-speed world | 21/24 | mean 0.52 (11/24 > 0.5 pt), max 1.52 |
| Decision: high-speed-optimal decision used in the street world | 21/24 | mean 2.15 (16/24 > 0.5 pt), max 4.01 |
| Control: decisions swapped between the original and jittered calendars | 5/24 | all 5 are near-ties: ≤ 0.28 pt in either world |

- **Greedy ignores the calendar by construction.** It picks the same race-6 decision in both decision-pair variants. That costs 0.87 pts (13/24 > 0.5) in the high-speed world and 2.38 pts (15/24 > 0.5) in the street world.
- **This is the observable Track A failure pattern:** a policy that doesn't look at the remaining calendar can't tell these worlds apart.
- **Diagnostics only.** These pairs aren't part of any score.
- **Close calls.** The best and second-best first decisions are often within 0.1 pt (median 0.08). Changed-decision counts should therefore always be read alongside the cost of the decision.

### Hindsight diagnostic (realized points, 6 scenarios × 2 seeds)

Mean hindsight gap of the fair optimum: **6.75 pts**. This includes in-race PIT/STAY improvements, because the fair optimum uses the baseline race policy, as well as knowledge of retirements and SC timing. On fixed seeds:
- The realized fair optimum is ≥ greedy in 10/12 runs. The exceptions are single-seed luck: S03/101 and S04/202.
- It is ≥ always-USE in 12/12.

This is why the report keeps expected regret (exact) separate from single-seed realized outcomes.

### Expected cost of a 4-place ICE grid drop (pts, stress 0.5, all other parts fresh)

| Archetype | Driver | d=0.1 | 0.3 | 0.5 | 0.7 | 0.9 |
|---|---|---:|---:|---:|---:|---:|
| high_degradation | Apex A | 4.24 | 4.25 | 2.99 | 3.26 | 3.60 |
| high_degradation | Apex B | 6.81 | 7.14 | 7.51 | 7.42 | 6.64 |
| high_speed | Apex A | 2.79 | 2.92 | 3.48 | 3.49 | 3.13 |
| high_speed | Apex B | 5.55 | 5.86 | 5.62 | 5.62 | 6.30 |
| mixed | Apex A | 2.72 | 3.00 | 2.94 | 2.79 | 3.18 |
| mixed | Apex B | 4.91 | 5.15 | 5.78 | 5.58 | 6.59 |
| street | Apex A | 4.67 | 4.56 | 3.83 | 3.95 | 3.87 |
| street | Apex B | 8.94 | 9.10 | 8.16 | 8.13 | 7.83 |
| wet_prone | Apex A | 3.69 | 3.64 | 3.08 | 3.16 | 3.15 |
| wet_prone | Apex B | 5.66 | 5.57 | 5.04 | 5.48 | 6.53 |

A penalty consistently costs Apex B more than Apex A. Apex B qualifies just inside the points, so it loses more positions that score. That makes "which driver takes the penalty" a real choice. The effect of difficulty is small and not consistent in direction.

## Conclusions

1. The structure we're looking for exists: **reasonable moves in the current race (greedy component use) are inefficient across the season**. The cause is the scarcity of free units and grid penalties, interacting with wear-driven pace loss and track-dependent team performance. The cost of ignoring the remaining calendar is measurable: up to 6 pts in the pair worlds.
2. Under the current synthetic coefficients the effect is **modest on average** (1.5 pts mean regret for greedy; 0.9 pts for its first decision alone). Whether the full 8-race horizon amplifies it is untested; I would test that before touching any coefficient.
3. Reliability, overtaking and tyre degradation rarely change the best component decision. They don't create Track A difficulty.

## Gap table: current implementation vs final requirements

| Area | Requirement | Status | Gap |
|---|---|---|---|
| A | 8-race championship | Harbor task runs 8 races with Track A rules; budgeted 8-race fair reference (P1-D) | Reference not proven optimal; not yet exposed as `solution/solve.sh` |
| A | Persistent wear, replacement, spare allocation | Implemented (synthetic) | Coefficients uncalibrated |
| A | Grid penalties and track-dependent opportunity cost | Implemented | Penalty cost vs overtaking difficulty is weak and not monotonic |
| A | Constructors' optimization | Objective = Apex points; rank and margin reported | No rival-relative objective in the scalar |
| A | Season-level driver prioritization | Only via which driver gets free units/penalties | Team orders not implemented (Track C) |
| B | 13–18 decision points per race | B3: 14 per race (45 laps), about 5.8 meaningful; solver uses public CRN paths | Last 2 decisions never meaningful; SC/VSC decisions rare; frontier time unmeasured |
| B | Compound choice and degradation | B1: compound choice, tyre life cliff, two-compound rule | Cliff rarely binding at 3 decisions per race |
| B | SC/VSC responses | B4: seeded SC/VSC process with public durations, SC compression, VSC slow-down, reduced tyre ageing | Status granularity is one 3-lap segment |
| B | Weather and forecasts | — | Not started |
| B | Rival pit strategy, undercut/overcut | Rule-based rival pits | No explicit in/out-lap model |
| B | Shared pit crew / double stack | B2: one crew per team, second arrival queues (all teams); track pit loss; out-lap warm-up | No random slow stops |
| C | Engineer A/B, Chief, simulator-grounded feedback | — | Not started; the decision-type phase machine and journal are generic |
| C | Conflicting advice, confidence, ablations | — | Not started |
| Eval | Fair reference playing through `f1ctl` | — | `solution/solve.sh` is still the P0 heuristic |
| Eval | Reward fields: raw points, fair-reference regret, hindsight gap, completion/integrity | Raw points and completion/integrity in the Harbor verifier; regret and hindsight only offline | Denominator undecided (provisional P0 formula unchanged) |
| Eval | Reskin ablation | — | Not started |
| Eng | Scale | — | Server deep-copies the session per action; solver 40 s per scenario; hindsight about 220 s per seed |

## Reproduce

```bash
python3 -m unittest discover -s devtests -v          # 48 tests (P0 boundary + Track A)
python3 analysis/run_track_a.py --scenarios 24 --workers 10   # ~41 min on 10 cores
python3 analysis/cross_eval_track_a.py                # ~5 min
python3 analysis/summarize_track_a.py
```
