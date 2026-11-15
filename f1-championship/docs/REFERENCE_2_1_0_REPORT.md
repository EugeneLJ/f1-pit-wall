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
| **`v21-gemini-02` (live, same task build and flags)** | **256 points, reward 0.651.** Complete, intact, 0 rejected, about 10 min. 118 / 120 decisions by its `strategy.py` (whole-field segment simulator; 7 DEFENSIVE_BUFFER orders). |
| **`v21-gemini-03` (live, same task build and flags)** | **276 points, reward 0.730.** Complete, intact, 0 rejected, about 8 min. 119 / 120 decisions by `/tmp/run_season.py` (one completed SWAP). |
| **Mean of the 3 live runs** | **270.3 points, reward 0.708. The reference leads by +18.7 on the task seed (+10, +33, +13).** |

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

### All three live runs' scripts on the same 20 paired seeds

| Script (replay; each reproduces its Harbor score exactly on the task seed) | Mean pts | Reference − script | SE | Reference ahead |
|---|---:|---:|---:|---:|
| `v21-gemini-01` | 267.3 | +9.05 | 2.2 | 15 / 20 |
| `v21-gemini-02` | 244.3 | **+32.05** | 2.4 | 20 / 20 |
| `v21-gemini-03` | 267.8 | +8.55 | 1.8 | 15 / 20 |
| **Mean of the three** | **259.8** | **+16.6** (median +9.05) | | |

- No script submitted an illegal action on these 20 seeds.
- All three use the same component behaviour: they never exceed allocation, and leave 3 stock units unused on every seed.

### Where the gap comes from (attribution, 20 paired seeds)

| Policy | Mean pts | Reference − policy |
|---|---:|---:|
| reference, both phases | 276.3 | — |
| reference components + Gemini race policy | 268.3 | **+8.0** (SE 2.2) |
| Gemini components + reference race policy | 275.8 | **+0.6** (SE 1.2) |
| Gemini script, both phases | 267.3 | +9.05 |

**Runs 02 and 03, same design:**

| Run | Reference components + that run's race policy | That run's components + reference race policy |
|---|---:|---:|
| 02 | +27.1 (SE 2.3) | +0.55 (SE 1.2) |
| 03 | +7.9 (SE 1.9) | +0.55 (SE 1.2) |

The three runs' component rules produce identical plans, hence the identical +0.55.

- **Almost all of the gap is in race decisions.**
- Gemini's penalty-averse component rule costs about 0.6 points, a near tie, even though it leaves stock unused.
- So the richer 2.1.0 component rules do **not** currently separate the reference from the frontier. That agrees with B8: natural replacement choices are mostly near ties.

## 5. Comparison with 1.1.0

| | 1.1.0 | 2.1.0 |
|---|---|---|
| Reference on the task seed (Harbor) | 286, 0.770 | 289, 0.782 |
| Live Gemini runs on the task seed | 282 / 279 / 286; reference − Gemini **+3.7** mean (0 to +7) | 279 / 256 / 276; reference − Gemini **+18.7** mean (+10 to +33) |
| Script replays, 20 paired seeds | +10.2 / +6.2 / +5.7 (mean +7.4) | +9.05 / +32.05 / +8.55 (mean +16.6, median +9.05) |
| Published baseline gap (20 seeds) | +38.0 | +55.1 |
| Reference runtime per season | 36–60 s | 61–100 s |
| Main source of Gemini's loss | race decisions | race decisions (component part +0.55 in all three runs) |

**Reading.**
- On 2.1.0 the reference leads all three live runs and all three scripts. The average gap is larger than on 1.1.0, but it is driven by one run (02). Two of three runs are within the 1.1.0 range (+9 vs +6 to +10).
- **The larger 2.1.0 average is not attributed to the 2.1.0 power-unit mechanics.** Their measured contribution is +0.55 in every run. Plausible but untested explanations are run-to-run variance in the strategy Gemini writes, and the longer 2.1.0 instruction. Neither is a finding.
- The 20-seed tiers use different seed sets in the two versions, so the cross-version numbers are descriptive.
- n = 3 live runs per version; no significance claim is made.

## 6. Decision-level analysis of the live 2.1.0 runs (`analysis/b21_decisions.py --run v21-gemini-0N`)

### Across the three runs

| | Run 01 | Run 02 | Run 03 |
|---|---|---|---|
| Same action as reference | 73% | 52% | 74% |
| Candidates / robust | 15 / 7 | 25 / 18 | 13 / 7 |
| **Early SOFT stop never taken (lap 3–6), robust** | races 5, 8 | races 4, 5, 8 | races 5, 8 |
| **Missed stop under SC, race 7 lap 12 (t095), robust** | +3.9 | +1.6 | +3.9 |
| Mid-race missed stops, robust decisions | 5 | 10 | 4 |
| Other robust | — | 4 unneeded stops, incl. MEDIUM→MEDIUM at lap 15 (+7.0, +10.2) | VSC double stack onto MEDIUM at lap 36 (+2.9) |

**Two failures recur robustly in all three runs:**
- the early SOFT stop is never taken (1.1.0's T1);
- the cheap stop under the race-7 SC is missed (T4).

Mid-race missed stops (T3) recur in all three runs. Run 03's VSC double stack onto a short-life tyre is the same pattern Red Bool (DeepSeek) showed in B7. No robust candidate in any run involves components.

### Run 01 in detail

**Method.**
- The live journal v2 replays exactly from the task seed.
- At each of the 112 race decisions, all 16 joint pit actions (team order RACE) plus Gemini's own action were rolled out over 16 public SC/VSC futures, with baseline continuation. This is the authoritative-engine public-input reference, and it has a **model-access advantage**.
- **Candidate:** regret > 1 point and > 2 SE.
- **Robust:** the candidate stays a candidate with 3× futures **and** with two other continuation rules (`event_aware`, `long_stint`).
- Data: `analysis/results/reference_runs/v21-gemini-01/decisions.json`.

**Overall.**
- 73% of Gemini's decisions equal the reference, and 78% are near ties (|regret| < 0.25 points).
- 15 candidates, 7 robust. **All 7 robust candidates are missed stops.**
- Regret by race is concentrated in races 2, 4 and 7 (11.6, 10.1 and 15.8). Decision regrets within a stint are not additive.

Consecutive candidates in one stint are one missed opportunity that persists, so they are grouped into **episodes**:

| Episode | Decisions | Gemini | Reference (regret) | Robust | Same type as on 1.1.0 |
|---|---|---|---|---|---|
| Early SOFT stop not taken: Apex A on SOFT at lap 3, races 5 / 7 / 8 | t062, t092, t107 | STAY | PIT_HARD (+1.5, +2.0, +2.4) | 2 / 3 | **T1** (early-stint SOFT stop never a candidate) |
| Race 7: Apex A P8 on HARD, never stops, laps 12–24, **including under SC at lap 12** | t095, t097, t098, t099 | STAY ×4 | PIT_HARD (+3.9 under SC; +2.6, +2.9, +3.9) | 3 / 4 | **T3** (missed mid-race stop), **T4** (SC opportunity) |
| Race 2: Apex A P5 on HARD, laps 18–21 | t022, t023 | STAY | PIT_HARD (+3.1, +2.2) | 1 / 2 | T3 |
| Race 1: Apex B on MEDIUM age 15 (life 16), lap 15 | t006 | STAY | PIT_HARD (+2.5) | yes | T3 |
| Race 4: mid-race and VSC stop timing; stops the other car | t049, t052–t054 | mixed | other car or other timing | 0 / 4 | — |
| Race 2: SOFT/HARD stop under VSC at lap 36 | t028 | PIT_HARD | STAY (+2.7) | no | (T2-like late stop) |

**Reading.**
- The robust losses are the same failure types found in the four 1.0.0 runs: the early SOFT stop is never taken, and mid-race stops are missed, including a cheap stop under SC.
- They recur on 2.1.0 with a different script. That suggests they are stable behaviours of Gemini-written strategies, not artefacts of one version.
- **No robust candidate involves components.** That matches the phase attribution (§4: components +0.6, race +8.0).
- Gemini's penalty-averse component rule, which leaves 3 stock units unused, is a strategic choice with a near-tie cost, not a scored failure.
- **Operational, not strategic:** the script submitted an illegal SWAP commitment once on a replayed dev seed, never live. The single DEFENSIVE_BUFFER (live) was applied; it is not among the candidates.

## 7. Limitations and next steps

- **Evidence volume.** One live 2.1.0 run. More runs (about $0.7 each) need a decision.
- **Model-access advantage.** The reference executes the exact rules, which an agent must build itself.
- **Synthetic scaling.** The 2.1.0 allocation, places and stock are synthetic scalings of the FIA rule structure. CHIEF_ONLY (no Engineers) was used for the gap task.
- **Team orders.** The reference uses team order RACE only. B6/B8 show orders are rarely best.
- **Race-side strengthening.** That is where the gap is; the bounded 1.1.0 study found no cheap gain.
- **Next.** More live runs, only if decided, to see whether the T1/T3 patterns recur across runs, which would support a stable gap claim. Possibly a reference that mirrors these specific decisions as a targeted check.
