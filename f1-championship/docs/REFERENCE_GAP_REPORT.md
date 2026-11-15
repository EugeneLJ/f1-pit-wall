# Frontier–reference gap and submission readiness (benchmark 1.1.0)

Date: 2026-11-15. Branch `feature/afterquery-reference` (from `feature/strategic-scenarios-b8`, `2d30e84`).
**No mechanics, coefficient, seed, reward, verifier, instruction or agent-image change.** The changes are
the reference player in `solution/`, its tests, an evaluation script, and documentation.

**Bottom line.**
- **Submit `f1-championship/` at benchmark 1.1.0.** It is the only version with a Harbor task, recorded frontier runs and a stronger reference.
- **The reference is now executable in Harbor.** `harbor run -p ./f1-championship -a oracle` plays the season through `f1ctl` from public observations and scores **286 points, reward 0.770** on the task seed (84 s). Before this change the Harbor oracle was the simple heuristic (240 points, 0.587), which Gemini beat.
- **The gap is established on 1.0.0 and still open on 1.1.0.** On the four seeds of the recorded Gemini 3.8 Flash runs (benchmark 1.0.0) it is ahead 4 of 4, by +13.8 ± 2.0 points (reward 0.734 vs 0.680). Against those runs' own scripts on 100 fresh seeds it is ahead by +16.9 to +28.2 points and wins 92–100% of seasons. **But the first fresh Gemini run on 1.1.0 scored 282 (0.754) on the task seed, 4 points behind the reference.** Two more fresh runs were still in progress when this was written, and the new script has not been replayed on the 100 seeds. Until that is done, the gap on the submitted version is not established.

## 1. Reference inventory

Every implementation in the repository that could serve as a reference, read from the code.

| # | Reference | Entry point | Versions | Plays a full 8-race season | Information | Runs in Harbor | Recorded evidence | Cost |
|---|---|---|---|---|---|---|---|---|
| 1 | Public baseline heuristic | `solution/play.py` | 1.0.0–1.1.0 | Yes, through `f1ctl` | Public observation only | Yes (was the oracle until this branch) | 240 pts / 0.587 on the task seed; 231.6 mean on 100 seeds | < 1 s |
| 2 | Public-information rollout, analysis form | `analysis/b4_counterfactual.py::rollout_action`, driven by `analysis/written_policy_eval.py` | 1.0.0–1.1.0 | Race decisions only; components were borrowed from the agent under test | Public futures, but it was handed the session's internal race state object | No | 272–273 mean on 30–60 seeds with Gemini's component plan | 0.2–0.4 s per decision |
| 3 | SC/VSC-model planner family (`green_only` … `full`, plus `clairvoyant`) | `analysis/event_policies.py` | 1.1.0 | No (single-race counterfactuals) | `full` is fair; `clairvoyant` is hindsight | No | B5 event evaluation | as 2 |
| 4 | Exact race expectimax | `analysis/race_expectimax.py` | short 3-decision format only | No | Fair | No | B1/B2 | infeasible for 14 decisions |
| 5 | Season component planner H=1…8 | `analysis/season_planner.py`, `analysis/track_a_solver.py` | 1.x | Components only; races valued with the baseline | Fair | No | P1-D: 24 calendars | 5–12 min per season in the 45-lap format (measured here: H=3 318 s, H=5 613 s, H=8 733 s) |
| 6 | Hindsight oracle | `track_a_solver.Solver.hindsight` | short format | — | **Privileged** (true events and retirement draws) | No | diagnostic only | — |
| 7 | Integrated scripted Chiefs | `integrated/policies.py`, `integrated_task/solution/play_integrated.py` | 2.0.x / 2.1.0 | Yes | Public | Generated task only | 0.587 (same as 1) | < 1 s |
| 8 | **Executable rollout reference (this branch)** | **`solution/reference.py`** (`solution/solve.sh`) | **1.1.0** | **Yes, through `f1ctl`** | **Public observations and published rules only** | **Yes: `-a oracle`** | §3 | 36 s per season in the agent container |

What was missing: references 2 and 5 were the only ones stronger than the frontier, and neither could be run by a judge. Reference 2 read `session._active_race.race_state` (the simulator's own object, whose event list contains the hidden future, although the rollout overwrote it before use) and had no component policy of its own.

## 2. The selected reference: `solution/reference.py`

It is reference 2 made executable, with nothing privileged.

| Aspect | What it does |
|---|---|
| Interface | `f1ctl rules`, `f1ctl observe`, `f1ctl act` — the agent's interface. 120 accepted decisions, 0 rejected. |
| Model | `solution/lib/f1pitwall`: the published rules as code (a synced copy of `src/f1pitwall`). It is started with seed 0 and has no access to the sidecar. |
| Synchronisation | At every race decision the observed track status is written into the model, and the model's tyres and elapsed times are checked against the observation (tolerance 0.002 s, the observation's rounding). Wear, grids and race dynamics are deterministic given public information, so the model reproduces the public state exactly: **0 repairs and 0 fallbacks in every season run so far.** |
| Race policy | One-step lookahead over the 16 joint actions. Each is played now and the public heuristic afterwards, over 32 futures sampled from the published SC/VSC model conditioned on the statuses seen so far. Value = exact expected Apex points over the published retirement probabilities. |
| Component policy | Search over season replacement plans, valued with the same model (public heuristic race play, 48 public event paths per race). Starting plans, then up to 4 sweeps of single-replacement moves. About 420 race evaluations, 11 s. |
| Safety | Any inconsistency or exception switches to the public heuristic for the rest of the season, so the season always completes. |
| Not used | Hidden seed, future statuses, retirement draws, journal, sidecar files. `devtests/test_reference.py` checks this statically and checks that two different seeds give identical actions while their observations agree. |

**What it has that an agent does not.** The agent gets the same rules as JSON and text and must write the model itself; the reference ships that model as tested code. It has no extra information. This is a modelling advantage and is reported as such. Compute is small: 36 s for the season, against a 3600 s agent limit.

**It is not optimal.** One-step lookahead with a heuristic continuation; 96 futures instead of 32 did not help (269.1 vs 270.6 on 40 seeds, within noise). It is a demonstrated stronger player, not the reward's upper bound `U` (344).

## 3. Matched frontier–reference results

### 3.1 Harbor, same seeds as the four recorded Gemini runs

Gemini: `gemini/gemini-3.8-flash`, OpenCode 1.19.5, Harbor 0.26.0, benchmark 1.0.0 (`docs/FRONTIER_REPEAT_REPORT.md`). Reference: this branch, benchmark 1.1.0. The two versions differ only in how `f1ctl rules` names the base paces; mechanics and seeds are identical, so points are comparable. The season is the independent unit: n = 4.

| Seed | Gemini run: points / reward | Reference: points / reward | Difference (points / reward) |
|---|---:|---:|---:|
| task seed (r0) | 268 / 0.698 | 286 / 0.770 | +18 / +0.071 |
| r1 | 267 / 0.704 | 279 / 0.750 | +12 / +0.046 |
| r2 | 248 / 0.631 | 264 / 0.692 | +16 / +0.062 |
| r3 | 263 / 0.688 | 272 / 0.723 | +9 / +0.035 |
| **Mean** | **261.5 / 0.680** | **275.2 / 0.734** | **+13.8 ± 2.0 s.e. / +0.053** |

The reference is ahead in 4 of 4 matched seasons. The task-seed reference figure is a real Harbor run (`ref-oracle-01`); the other three are the same player run locally on the recorded seeds (the task-seed local run gives the same 286).

### 3.1b Fresh Gemini runs on benchmark 1.1.0 (task seed, same flags)

| Run | Points / reward | Reference on the same seed | Difference |
|---|---:|---:|---:|
| `v110-gemini-01` | 282 / 0.754 | 286 / 0.770 | +4 / +0.016 |
| `v110-gemini-02` | in progress when written | 286 / 0.770 | — |
| `v110-gemini-03` | queued when written | 286 / 0.770 | — |

`v110-gemini-01`: complete, evidence intact, 120 accepted / 0 rejected, 118 decisions by its own script (`strategy_agent.py`, a whole-field simulator with enumerated stop plans, future segments assumed GREEN), about 13 min, $0.67. Evidence, verifier report and the script are in `analysis/results/reference_runs/v110-gemini-01/`.

**This run is 14 points above the 1.0.0 run on the same seed (268).** One season cannot separate a better policy from seed luck. A possible cause is the 1.1.0 rules fix (base paces are now keyed by the observation names; one 1.0.0 run mis-mapped them), but that is a hypothesis, not a finding. The check is to replay this script on the 100 seeds (`analysis/results/reference_runs/v110-gemini-01/policy.py` adapts it for `analysis/reference_eval.py`; not yet run).

### 3.2 100 fresh seeds, the agents' own final scripts

Each Gemini run delegated 93–98% of its decisions to a script it wrote. Those four scripts, the reference and the baselines play the same 100 seeds (none used in a Harbor run). `scripts/py312 analysis/reference_eval.py --seeds 100`; data in `analysis/results/reference_eval.json`.

| Policy | Mean pts | SD | Mean reward | Reference − policy, pts (± s.e.) | Reward gap (± s.e.) | Ref better / tie / worse |
|---|---:|---:|---:|---:|---:|---:|
| reference | 271.8 | 13.4 | 0.724 | +0.0 ± 0.0 | +0.000 ± 0.000 | 0 / 100 / 0 |
| gemini_r0 | 245.7 | 16.1 | 0.625 | +26.1 ± 1.4 | +0.100 ± 0.005 | 98 / 1 / 1 |
| gemini_r1 | 249.2 | 16.1 | 0.638 | +22.6 ± 1.2 | +0.086 ± 0.004 | 95 / 1 / 4 |
| gemini_r2 | 254.9 | 13.0 | 0.660 | +16.9 ± 1.1 | +0.065 ± 0.004 | 92 / 0 / 8 |
| gemini_r3 | 243.7 | 17.3 | 0.617 | +28.2 ± 1.2 | +0.108 ± 0.004 | 100 / 0 / 0 |
| baseline | 231.6 | 14.9 | 0.571 | +40.2 ± 1.2 | +0.154 ± 0.004 | 100 / 0 / 0 |
| stop_early | 123.2 | 10.2 | 0.000 | +148.7 ± 1.2 | +0.724 ± 0.005 | 100 / 0 / 0 |
| do_nothing | 82.4 | 4.8 | 0.000 | +189.4 ± 1.2 | +0.724 ± 0.005 | 100 / 0 / 0 |

Stop-early here means walking away after 60 of 120 decisions: points are banked but the season is unfinished, so the reward is 0.

**What this supports.** The reference beats every recorded frontier policy on average, with paired standard errors of 1–1.5 points. **What it does not support:** a large gap. The reference wins most seasons, not all, and the best Gemini policy (r2) is within about 15 points.

## 4. Why the frontier lost points

All three examples are from `docs/FRONTIER_REPEAT_REPORT.md` §4 and `analysis/results/rep_runs/*/confirm_own_continuation.json`. A loss counts only if it exceeds 1 point and 2 s.e. with the agent's own script as the continuation; realized single-seed outcomes are not used. In every case the information needed was in the observation or the rules.

1. **A useful action was never a candidate (r0, r2, r3; 9 confirmed instances).** Apex A starts on SOFT. With the published SOFT degradation, stopping for HARD at lap 3–6 is worth +2.1 to +5.3 points (r2 race 5 lap 3: +5.3 ± 1.3; r3 race 4 lap 3: +4.5 ± 0.7). The scripts only propose a stop when the tyre is near its published life. r3's own simulator prefers the stop when forced to evaluate it (40 vs 33 points). r1, which enumerates every action, has no such loss. The reference enumerates all 16 joint actions.
2. **The published SC/VSC model was not used (4 of 4 scripts).** Every script assumes all future segments are GREEN. r2 stopped Apex B for SOFT at lap 39 under SC (−4.3 ± 0.5): with the published duration law the SC is likely to continue, so the new tyre gains nothing and the stop costs position in a compressed field. r0 stopped under VSC at lap 39 for −10.6. The reference samples futures from the published start and duration model.
3. **Time used as a proxy for points (r1; 4 confirmed instances).** r1 scores each car alone by race time and keeps a MEDIUM out past its life at lap 18 (−2.7 to −4.0 points, three races). The time model prefers staying by 4–6 s; the points model prefers stopping because of track position, dirty air and rival stops. The reference scores whole-field finishing order.

These are decisions inside scripts the model wrote (25 of the 26 confirmed instances), so they are evidence about the strategy the agent built, not 26 separate reasoning errors.

## 5. Submission readiness

| Check | Result |
|---|---|
| Harbor layout | `instruction.md`, `task.toml`, `environment/Dockerfile` + `docker-compose.yaml`, `tests/`, `solution/` in `f1-championship/` |
| Reference in Harbor | `ref-oracle-01`: 286 points, reward 0.76984127, complete, intact, 120 accepted / 0 rejected, 0 fallbacks, 84 s wall |
| Do-nothing (`-a nop`) | `ref-nop-01`: reward 0.0, 0 decisions, evidence intact |
| Stop-early with attacks | `ref-probe-stop-01`: reward 0.0 (2 decisions accepted, 23 rejected requests logged) |
| Attacks then honest play | `ref-probe-complete-01`: reward 0.58730159 = the plain heuristic's score; evidence intact; 24 rejected requests logged. The attacks gained nothing. |
| Frontier through OpenCode | `v110-gemini-01`: 282 points, reward 0.75396825, complete, intact, 0 rejected. Runs 02 and 03 were not finished when this was written. |
| Reward range | `tests/test.sh` writes 0 first and rewrites anything outside [0, 1] or non-finite as 0 |
| Replay | Verifier replays the hash-chained journal from its own seed copy and recomputes every observation hash |
| Leakage | Seed exists only in the sim image and the verifier image; the agent image build context excludes `sim/`; the reference and client contain no seed (tested) |
| Timeout | Agent 3600 s; Gemini runs took 9–11 min, the reference 36 s |
| Local tests | `scripts/py312 -m unittest discover -s devtests`: 208 tests, OK (78 s). One earlier run of the same suite, started while two other evaluations were using every core, reported 1 failure; the failing test was not captured and it did not recur. |

**Exploit routes reviewed (no environment change made).**

| Route | Outcome |
|---|---|
| Read seed, journal or state from the agent container | Not mounted; only the socket is shared (probe: paths absent, also as root) |
| Reset, rewind, preview, unknown commands, oversized or malformed requests | Rejected; state unchanged; rejected requests are journaled and must also fail under replay |
| Duplicate or out-of-order `decision_id`, concurrent `act` | One lock, one accepted action per id |
| Write `/logs/verifier/reward.txt` or fake evidence from the agent | The verifier is a separate container and reads only evidence collected from the sim service |
| Finish early or skip races | Unfinished season → 0 |
| Play every decision trivially | USE + STAY is the zero point `D` |
| Flood rejections | At most 2000 are journaled; the rest are counted |

**Residual risks, stated plainly.**
- **The seed is in the public repository.** Someone with the repository (not the sandboxed agent) could precompute a hindsight action list. A fresh seed takes one command (`scripts/make_seed_variant.sh`).
- **One seed per task.** A single run has a seed-to-seed SD of about 13 points (0.05 reward).

## 6. Version recommendation

| Candidate | Gap (30) | Meaningful difficulty (30) | Reward integrity (25) | Craft (15) | Verdict |
|---|---|---|---|---|---|
| **1.1.0 Solo (`f1-championship/`)** | Measured: 4 Harbor frontier runs, executable reference, 100-seed paired comparison | Failures traced to search, event model and objective, with public information | Sealed sidecar, replay, probes re-run on this branch | One-command runs; README updated | **Submit** |
| 2.0.1 SOLO_COORDINATION | No frontier run in Harbor; its oracle is the 0.587 heuristic; no stronger reference | Team orders are rarely the best action (RACE best in 74% of states), give-back shows no benefit | Same boundary, but the task is generated by a script and live Engineers cannot run in Harbor | Extra build step | Demo material for the Gemini challenge |
| 2.1.0 (B8 rules) | No frontier run, no reference | Most natural replacement choices are near ties | Not exposed as a Harbor task | — | Do not submit |
| B8 + C5 | Not integrated; C5 scores are proxy values, not points | — | — | — | Do not start |

## 7. Critical blockers

Only items that could cost judging points.

1. **Gap size.** About 0.05–0.10 reward (14–28 points) against the 1.0.0 runs, and possibly much less on 1.1.0 (see 2). A stronger model than Gemini 3.8 Flash that writes a faithful simulator and enumerates all actions could close most of it. Document Gemini 3.8 Flash as the judged model.
2. **Frontier runs on 1.1.0.** **Open, and the most important item.** Only one fresh run is in, and it is within 4 points of the reference. The 1.0.0 evidence supports a gap; the 1.1.0 evidence so far does not. Collect runs 02 and 03, replay the new scripts on the 100 seeds, and only then state the gap.
3. **Early SOFT stop looks odd.** The largest recurring loss is "stop a SOFT at lap 3". It follows from the published coefficients, and it is in the rules, but a judge may read it as an unrealistic tyre model. Have the one-line explanation ready (SOFT loses 0.35 s per lap of age × track multiplier).
4. **Root of the repository is a different, older task.** The root README now points to `f1-championship/` first; the demo must use that path.
5. **Branches are not merged.** The submission branch must be pushed and named in the README/video; `main` does not contain the championship task's later work.

## 8. Patch made (smallest that closes the reference gap)

| File | Change |
|---|---|
| `solution/reference.py` | New: the executable reference |
| `solution/lib/f1pitwall/` | Synced copy of `src/f1pitwall` for the reference's model |
| `solution/solve.sh` | Runs the reference; `F1_SOLUTION=baseline` runs the old heuristic |
| `scripts/sync_engine.py`, `devtests/test_boundary.py` | Third sync target; drift and seed checks cover the new files |
| `devtests/test_reference.py` | Information and consistency tests for the reference |
| `analysis/reference_eval.py`, `analysis/results/reference_eval*.json` | Matched-seed comparison and its data |
| `README.md` (root and task), this report | Judge commands and results |

Agent-visible files (`instruction.md`, `environment/`), the simulator, the verifier and the reward are byte-identical to `2d30e84`.

## 9. Gemini API challenge (20%)

What is true and can be shown:
- **Gemini is the agent under test and builds its own strategy system.** In 4 of 4 runs it read the rules, wrote a simulator and a policy, tested it, and delegated 93–98% of the season to it. That is a real, inspectable use of the API through OpenCode, with every decision replayable from sealed evidence.
- **Chief + Engineer hierarchy (B7).** Gemini 3.8 Flash Chief with Gemini 3.5 Flash-Lite Driver Engineers: 219 of 224 Engineer records valid, exact replay verified.

What must not be claimed: that Engineers improve results (Layer 2 scored below Layer 1, without a matched design), or that beating DeepSeek is the benchmark's gap.
