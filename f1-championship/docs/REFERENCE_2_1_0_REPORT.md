# 2.1.0 reference port and first frontier comparison

**Branch.** `feature/reference-2.1.0`, from `feature/strategic-scenarios-b8` (`2d30e84`) plus a merge of `feature/afterquery-reference` (`0012b95`). Both source branches are unchanged.

**What stays the same.**
- 1.1.0 is reproducible and unchanged: its Harbor oracle is still 0.7698 (286), and 35 legacy + 213 devtests pass.
- B7/B8 mechanics changed only where §2 states a correctness bug. The frozen B7 journals replay exactly.
- C5 and C7 are not integrated.

## 1. What was built

| Item | Where |
|---|---|
| 2.1.0 reference (public information only) | `integrated_task/solution/reference_v21.py` |
| Versioned Harbor task | `scripts/make_integrated_task.sh <dest> CHIEF_ONLY 2.1.0` (`EugeneLJ/f1-championship-integrated`, version 2.1.0) |
| Sidecar / verifier versioning | `mode.json` carries `benchmark_version`; `task_config()` is shared by sidecar and verifier; `f1ctl rules` publishes `power_unit_rules` and marks the legacy pool superseded; 2.1.0 instruction addendum; the verifier rejects evidence of another version |
| Staged, cached evaluation | `analysis/reference21_eval.py`, cache `analysis/results/cache/2.1.0/` |
| Live run evidence | `analysis/results/reference_runs/v21-gemini-01/` (verifier report, Harbor result, journal v2, extracted scripts, adapter) |

**Reference design.**
- **Model.** An `IntegratedSession` of the 2.1.0 rules with seed 0. It is checked against every observation (components, rivals' public usage, inventory, tyres, elapsed times). The observed track status is copied in. The model's own future events and retirement draws are never read.
- **Race decisions.** A one-step rollout over the 16 joint pit actions with team order RACE, reusing the 1.1.0 functions unchanged. With RACE the integrated race step equals the 1.1.0 step bit for bit.
- **Component plans.** A season search under the 2.1.0 rules: per-driver allocation, team stock, cumulative penalties and back of grid. It uses the rivals' published stock-aware rule, with per-driver bundle seeds and bundle-move operators added.
- **Information.** It uses no seed, journal, sidecar file or rival internals. A static test checks this, and so does a dynamic one: two seeds give identical actions while their observations agree.

**Port assumptions that did not hold, and were fixed:**
1. **Rival rule.** The planner's rival rule ignored stock. The session's stock-aware rule is now one shared, published function, `published_rule_decisions`; its behaviour is unchanged and the B7 replays are exact.
2. **Joint stock.** `_repair` checked stock per element. It now enforces the team's stock across both drivers.

## 2. 2.1.0 correctness fixes (not tuning)

1. **No-legal-action state.**
   - Two drivers over the wear limit with one unit of that type left had no legal joint action: REPLACE for both exceeds the stock, and USE was "too worn".
   - Even the published fallback failed there.
   - Fix: under 2.1.0, a worn element may keep running with the published pace and reliability cost, and REPLACE needs stock.
2. **Misleading free units.** 2.1.0 observations showed `free_units_available: 4` from the legacy pool, which does not exist in 2.1.0. That pool is now 0.

No agent had been evaluated on 2.1.0 before these fixes. B8's evaluation never reached the affected state, so its results stand. The reward formula is unchanged: `b6-integrated-p0`, clip((P − D)/(U − D)), with D the published fallback in the same version.

## 3. Harbor (Verda)

| Run | Result |
|---|---|
| `harbor lint` (2.1.0 task, 1.1.0 task) | OK, OK |
| `v21-oracle-01` (2.1.0 reference) | **289 points, reward 0.782.** Complete, intact, 120 ticks, 0 fallbacks, 0 resyncs. 61 s of play, 113 s wall. |
| `v21-nop-01` | 0.0 |
| `v21-v110-oracle-01` (1.1.0 task) | 0.7698 (286), unchanged |
| **`v21-gemini-01` (live Gemini 3.8 Flash, OpenCode, same flags as the 1.1.0 runs)** | **279 points, reward 0.742.** Complete, intact, 0 rejected, about 10 min wall. |

**Reproduce:** `scripts/make_integrated_task.sh f1-championship-2.1.0 CHIEF_ONLY 2.1.0`, then `harbor run -p f1-championship-2.1.0 -a oracle`.

**How Gemini played** (`delegation.json`): 119 of 120 decisions were made by its own `run_championship.py`, from the first race decision on.
- **Race decisions:** a per-car stint-time search; one DEFENSIVE_BUFFER order.
- **Components:** "replace only if it costs 0 grid places". It never took a penalty, kept 3 stock units unused, and replaced ICE and turbo before race 5.

## 4. Staged evaluation (replays of public policies and of Gemini's script; seeds disjoint from all other sets)

| Tier | Reference | Gemini script (replay) | Published baseline | Reference − Gemini, mean (per seed) |
|---|---:|---:|---:|---|
| Task seed (Harbor live) | 289 | 279 (live run) | 229 | +10 |
| Smoke, 2 seeds | 246, 284 | — | 211, 222 | — |
| Dev, 5 seeds | 269.4 | 265.8 | 209.2 | +3.6 (−7, +7, +13, −7, +12) |
| Inter, 10 seeds | 277.3 | 272.7 | 225.0 | +4.6, SE 2.5 |
| **Inter, 20 seeds** | **276.3** | **267.3** | **221.3** | **+9.05, SE 2.2; reference ahead in 15 / 20** |

Per-seed values are in `analysis/results/reference21_2.1.0_inter20.json`.

**Script replay vs the live run.** The script replays to its Harbor 279 exactly on the task seed. On one dev seed it submitted an illegal action (a SWAP commitment with no car ahead). The sidecar would reject it, and the replay applies the published fallback for that tick: an approximation, because the live agent's reaction cannot be replayed. **These replays measure the script Gemini wrote. They are not independent model runs.** The only live 2.1.0 model run is `v21-gemini-01`.

**The reference in every evaluated season:** 0 fallbacks, 0 resyncs. It always used all 9 stock units (Apex A 6, Apex B 3), bundling Apex A's three elements before race 7 on the task seed. It runs in 61–100 s per season, against a 3600 s limit.

### Where the gap comes from (attribution, 20 paired seeds)

| Policy | Mean pts | Reference − policy |
|---|---:|---:|
| reference, both phases | 276.3 | — |
| reference components + Gemini race policy | 268.3 | **+8.0** (SE 2.2) |
| Gemini components + reference race policy | 275.8 | **+0.6** (SE 1.2) |
| Gemini script, both phases | 267.3 | +9.05 |

- **Almost all of the gap is in race decisions.**
- Gemini's penalty-averse component rule costs about 0.6 points, a near tie, even though it leaves stock unused.
- So the richer 2.1.0 component rules do **not** currently separate the reference from the frontier. That agrees with B8: natural replacement choices are mostly near ties.

## 5. Comparison with 1.1.0

| | 1.1.0 | 2.1.0 |
|---|---|---|
| Reference on the task seed (Harbor) | 286, 0.770 | 289, 0.782 |
| Live Gemini runs on the task seed | 282 / 279 / 286 (3 runs), mean gap +3.7 | 279 (1 run), gap +10 |
| Script replays, 20 paired seeds | gaps +10.2 / +6.2 / +5.7 (3 scripts) | gap +9.05 (1 script) |
| Published baseline gap (20 seeds) | +38.0 | +55.1 |
| Reference runtime per season | 36–60 s | 61–100 s |
| Main source of Gemini's loss | race decisions (search, event model, objective; §4 of `REFERENCE_GAP_REPORT.md`) | race decisions (+8.0 of +9.05) |

**Reading.**
- On 2.1.0 the reference leads by a similar, modest margin. A single 2.1.0 run cannot show a larger gap than on 1.1.0: the 1.1.0 single-seed gaps ranged 0 to +7, and the 20-seed script gaps overlap.
- The published baseline falls further behind under 2.1.0, because it never replaces and races on worn elements.
- **No significance claim is made.** There is one live run, and the replays come from one script.

## 6. Observed strategic behaviour and candidate failures (Gemini 2.1.0)

| Behaviour | Evidence | Status |
|---|---|---|
| Race-strategy losses | +8.0 points per season attributable to the race policy (20 seeds) | **Main candidate.** Decision-level analysis, as in B7's `b7_analysis`, is not yet run on 2.1.0 |
| Penalty aversion (never exceeds allocation, 3 stock units unused) | 20 / 20 seeds | **Not a scored failure:** its cost is +0.6 ± 1.2 points (near tie) |
| Illegal SWAP commitment (no car ahead) | 1 of 25 replayed seasons | Script bug; an operational, not strategic, failure; never occurred live |
| DEFENSIVE_BUFFER ×1 (live run) | journal | Not evaluated |

## 7. Limitations and next steps

- **Evidence volume.** One live 2.1.0 run. More runs (about $0.7 each) need a decision.
- **Model-access advantage.** The reference executes the exact rules, which an agent must build itself.
- **Synthetic scaling.** The 2.1.0 allocation, places and stock are synthetic scalings of the FIA rule structure. CHIEF_ONLY (no Engineers) was used for the gap task.
- **Team orders.** The reference uses team order RACE only. B6/B8 show orders are rarely best.
- **Race-side strengthening.** That is where the gap is; the bounded 1.1.0 study found no cheap gain.
- **Next.** A decision-level analysis of the live 2.1.0 run (reuse `b7_analysis` with the 2.1.0 config). Then more live runs only if the user decides.
