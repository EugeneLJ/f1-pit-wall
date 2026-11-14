# Repeated frontier evaluation and policy-delegation analysis (Track B, after B4)

> **Benchmark version: 1.0.0.** These results were produced on benchmark 1.0.0 and are kept as historical results. Version 1.1.0 changes only how `f1ctl rules` names the published base paces (see `docs/VERSIONS.md`).

Date: 2026-11-14. Branch `feature/track-b`. **No environment, mechanics, reward or verifier change was made for this analysis.** Environment defects found during the analysis are listed as proposals in "Environment changes proposed" and kept separate from model/policy observations.

The report is split into:
- **Part 1:** what the B4 environment measures; this is the B4 result
- **Part 2:** the four frontier runs; these are the initial frontier result
- **Part 3:** what Track C and a two-team competition would need

## Part 1 — What B4 measures (recap, unchanged)

Full detail is in `docs/B4_REPORT.md`. In short:
- **SC/VSC process:** SC and VSC follow a seeded process with public start probabilities and durations. SC compresses the field; VSC slows everyone equally.
- **Value of replanning:** with the public-information rollout reference, replanning after a 2-segment SC is worth **+8.8 points per race** on average. 383/432 SC paths need replanning, and VSC paths include no-change controls.
- **Pitting under SC is not dominant:** an "always pit under SC" rule loses to no-replanning in 545/936 event paths.

## Part 2 — Four Gemini runs

### Setup and comparability

| Item | Value |
|---|---|
| Model / harness | `gemini/gemini-3.8-flash` via OpenCode 1.19.5, Harbor 0.26.0 on Verda; same flags for every run |
| Runs | r0 = first probe (task hidden seed); r1–r3 = repeats on three new seeds |
| Seed variants | Built with `scripts/make_seed_variant.sh`. Only `environment/sim/secret/seed.json` and `tests/hidden_seed.json` differ; instruction, client, Dockerfiles and rules are byte-identical (checked with `diff`); `harbor lint` is clean; the oracle ran on every variant (0.596 / 0.515 / 0.585) |
| Fresh workspace | Each run is a separate Harbor trial with new containers |
| Retries | None. All four runs are reported; none failed |
| Coding / automation | Allowed and not discouraged |

### 1. Outcome per run (same criteria for all four)

| Run | Constructors' points (rank) | Rival P2 | Reward | Complete / intact / rejected | Wall clock | Model-submitted decisions | Script decisions | Automation started | Tokens in (cached) / out | Cost (Harbor estimate) |
|---|---:|---|---:|---|---:|---:|---:|---|---:|---:|
| r0 | 268 (P1) | Orion 248 | 0.6984 | yes / yes / 0 | 541 s | 8 | 112 | d009 | 2.73M (2.55M) / 13.5k | $0.54 |
| r1 | 267 (P1) | Orion 205 | 0.7038 | yes / yes / 0 | 629 s | 3 | 117 | d004 | 4.04M (3.84M) / 25.2k | $0.70 |
| r2 | 248 (P1) | Orion 242 | 0.6308 | yes / yes / 0 | 628 s | 3 | 117 | d004 | 3.67M (3.48M) / 28.6k | $0.66 |
| r3 | 263 (P1) | Orion 232 | 0.6885 | yes / yes / 0 | 665 s | 8 (4 of them script-assisted) | 112 | d009 | 4.08M (3.86M) / 24.8k | $0.73 |
| **Across runs** | **261.5 ± 8.0** (248–268) | | **0.680 ± 0.029** | 4/4 complete | **616 ± 46 s** | 3–8 | 112–117 | | | **$2.62 total** |

The figures are population SD over the four runs. Each run is on a different seed, so the spread mixes agent variability with seed variability. The multi-seed policy evaluation below separates the two.

**Reward re-verification (item 9).**
- **Method:** I re-ran `tests/grade.py` locally on each run's sealed evidence with that run's seed, under **Python 3.12** (the same interpreter as the sim and verifier images).
- **Result:** it reproduces all four Harbor rewards exactly. For every run P/D/U is consistent and the reward is (P−D)/(U−D):

| Run | P | D | U | Reward |
|---|---:|---:|---:|---:|
| r0 | 268 | 92 | 344 | 0.69841270 |
| r1 | 267 | 84 | 344 | 0.70384615 |
| r2 | 248 | 84 | 344 | 0.63076923 |
| r3 | 263 | 84 | 344 | 0.68846154 |

- **Consistency:** the same `scalar_version` (`p0-provisional`), formula and aggregation apply to every run. D is the do-nothing policy on each run's own seed.
- **Interpreter caveat:** under Python 3.9 the r2 journal fails its hash check at entry 11 ("observation mismatch"). Python 3.12 changed float `sum()` to a compensated algorithm, so replays are only bit-exact on the interpreter the images use. The official reward is unaffected, because the sim and verifier share Python 3.12. The r2 decision analysis was rerun under 3.12 and gives identical candidates and confirmations.

### 2. Policy delegation (item 2 of the task)

| Run | Model-submitted decisions | Scripts (versions) | Pre-automation checks | Changed mid-season? | Uses current SC/VSC status | Uses the published SC/VSC model (`event_model`) |
|---|---|---|---|---|---|---|
| r0 | d001–d008 | `pitwall_bot.py` (1) | Inline simulations before each manual decision; the bot ran without a test | No | Yes (status-dependent thresholds) | **No** |
| r1 | d001–d003 | `test_strategy.py` (2, test only), `champion.py` (1) | Ran and edited `test_strategy.py` twice | No | Yes (current pit loss and tyre ageing) | **No** |
| r2 | d001–d003 | `/tmp/eval_d004.py`, `/tmp/test_forward.py`, `run_championship.py` (3) | Two test scripts in `/tmp` | No: the post-run edit removed a stray `EOF` line, and the second run found the season complete | Yes (compression approximated: all gaps set to 0.8 s) | **No** (future assumed GREEN) |
| r3 | d001–d004 own; d005–d008 submitted after printing `strategy_engine.py`'s recommendation | `strategy_engine.py` (1), `run_championship.py` (2) | Used `strategy_engine.py` as an advisor for 4 decisions, consulted `run_championship.py` v1 for 2 decisions, then rewrote it as v2 | Rewrote the policy before automating (v1 → v2 at d009) | Yes (compression modelled) | **No** |

- **Delegation in every run:** Gemini delegated **93–98% of decisions** to code it wrote, in **4/4 runs**.
- **No runtime revision:** no run changed its policy after seeing a race result. Every policy was fixed before the remaining races were played.
- **Script hygiene:**
  - No secrets were found in any trajectory (scanned for key patterns).
  - The raw trajectories stay out of the repository: they are in the session scratch area and on Verda under `jobs/`.
  - The agent-written sources needed for analysis are kept verbatim under `analysis/results/` (no credentials in them).

**Do the scripts use only public information? (item 3)**
- **Static audit:** none of the scripts reads `/opt/f1sim`, `/var/lib/f1sim`, `/evidence`, seeds or journals; imports simulator code; or sends any command besides `observe`/`act` (r2 calls `f1ctl`).
- **Server-side request statistics agree:** only `observe`, `rules`, `act` and `ping` were received in all runs; 0 rejected actions; 1 malformed request in r3 (no effect on state).
- **r0 environment probing:** during exploration r0 ran `ps`, read `/proc/*/cmdline` and walked the filesystem. It found nothing, and its scripts do not use any of it.
- **Constants:** the hard-coded constants match the published rules, with one exception. **r3 swaps the base pace of Orion B and Nova A** (89.75 ↔ 89.90).
  - The rules publish `published_base_pace` under the engine's internal names (`Rival 1`…`Rival 6`) without the mapping to the names in observations (`Orion A`, …).
  - r2 inferred the mapping correctly; r3 guessed wrong.
  - That is an **environment documentation defect** (see the proposals), not only an agent error.

### 3. Multi-seed evaluation of the written policies (item 5)

**Method.**
- **Same 100 seeds and same car conditions** for every policy (paired). The seeds were drawn fresh and never used in a Harbor run.
- **The calendar is the task's own.** The component plans were written for this calendar, so evaluating them on other calendars was not done.
- **Policy versions:** each policy is the agent's final script. r0's 8 hand-played decisions and r3's pre-automation decisions are not part of it.
- **Replay check:** replaying each script on its own run's hidden seed reproduces the Harbor points for r0 (268), r1 (267) and r2 (248), and gives 261 vs 263 for r3. The 2-point difference comes from r3's 8 non-scripted decisions.

| Policy | Mean pts | SD | 95% CI | Δ vs public baseline (95% CI) | Stops per season | Stops with ≤ 6 laps left |
|---|---:|---:|---|---|---:|---:|
| **r2 `run_championship.py`** | **254.9** | 13.0 | [252.4, 257.5] | **+23.3** [+21.0, +25.6] | 31.2 | 0.56 |
| r1 `champion.py` | 249.2 | 16.0 | [246.1, 252.4] | +17.6 [+15.2, +20.0] | 28.5 | 0.46 |
| r0 `pitwall_bot.py` | 245.7 | 16.1 | [242.6, 248.9] | +14.1 [+10.8, +17.4] | 30.2 | **4.57** |
| r3 `run_championship.py` | 243.7 | 17.2 | [240.3, 247.0] | +12.0 [+9.0, +15.0] | 33.0 | 0.95 |
| Public baseline | 231.6 | 14.9 | [228.7, 234.5] | — | 25.2 | 0.77 |

**Pairwise on the same seeds** (row − column, ± s.e.):

| | r1 | r2 | r3 |
|---|---:|---:|---:|
| r0 | −3.5 ± 1.5 | −9.2 ± 1.3 | +2.0 ± 1.4 |
| r1 | — | −5.7 ± 1.2 | +5.6 ± 1.5 |
| r2 | — | — | +11.3 ± 1.5 |

**Per-race means:**

| Race | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| r0 | 29.0 | 35.7 | 25.3 | 34.0 | 27.8 | 38.6 | 26.6 | 28.8 |
| r1 | 28.4 | 36.2 | 27.1 | 34.5 | 28.4 | 36.8 | 27.1 | 30.7 |
| r2 | 31.3 | 38.4 | 27.6 | 33.9 | **25.7** | 39.2 | 28.4 | 30.5 |
| r3 | 28.9 | 34.6 | 25.9 | 32.9 | 29.2 | 36.6 | 26.4 | 29.2 |
| Baseline | 29.3 | 38.3 | 26.7 | 28.8 | 27.3 | 34.5 | 19.2 | 27.4 |

**Attribution** (200 seeds; 100 for r1). Values are Δ vs the agent policy.

| | Same components, baseline race play | Baseline components, agent race play | Agent components + public rollout race reference | Agent policy with only the late-stop rule removed |
|---|---:|---:|---:|---:|
| r0 | +1.0 | −16.1 | +29.0 | **+16.0 ± 0.6** |
| r1 | −3.0 | −12.0 | +26.5 | +0.9 ± 0.3 |
| r2 | −9.7 | −11.5 | +20.6 | +0.6 ± 0.2 |
| r3 | +2.5 | −13.9 | +31.2 | +3.1 ± 0.3 |

**Reading the attribution.**
- **Component plans are identical.** All four agents chose the same Track A plan: replace ICE and turbo on both cars before race 5, using exactly the 4 free units, with no penalties. That plan is worth about +15 points over the baseline's plan and is the main source of the agents' advantage.
- **Race play differs by policy.** r2's race play is genuinely better than the baseline's (+9.7). r0's and r3's are about level with it or worse.
- **Large in-race headroom remains in every run:** +20.6 to +31.2 points with the public rollout reference.
- **r2's per-race weakness:** it is weaker than the baseline only in race 5 (25.7 vs 27.3). That's where its confirmed failures in the Harbor run sit too. The mechanism is not identified (see the candidates).

**Rival-policy sensitivity (item 6).** **Method.** 40 seeds, paired. The engine's rival pit rule is swapped inside the analysis process only; the environment is unchanged. Variants:
- **early stoppers:** pit 3 laps before tyre life; SC age ≥ 5, VSC age ≥ 8.
- **late stoppers:** run 2 laps past tyre life; SC age ≥ 9, VSC age ≥ 12.
- **SC opportunists:** stop under any SC/VSC at age ≥ 3 with ≥ 9 laps left.

r2's planner embeds the *public* rival rule, so these variants test it against rivals it mis-models. r1 was left out because of its per-call cost.

| Policy | Public rule | Early stoppers | Late stoppers | SC opportunists | Max shift |
|---|---:|---:|---:|---:|---:|
| r2 | 251.6 ± 2.0 | 257.6 ± 3.3 | 251.5 ± 2.4 | 254.2 ± 2.4 | 6.1 |
| r3 | 241.0 ± 3.1 | 252.9 ± 2.5 | 241.1 ± 2.5 | 242.1 ± 3.2 | 12.0 |
| r0 | 242.8 ± 2.5 | 250.6 ± 2.6 | 239.1 ± 3.0 | 243.8 ± 2.9 | 7.8 |
| Public baseline | 228.8 ± 2.2 | 223.0 ± 2.5 | 221.7 ± 2.1 | 225.6 ± 2.6 | 7.1 |

**Gap over the public baseline, by rival variant:**

| Policy | Public rule | Early stoppers | Late stoppers | SC opportunists |
|---|---:|---:|---:|---:|
| r2 | +22.8 ± 2.0 | +34.6 ± 2.6 | +29.9 ± 2.0 | +28.6 ± 2.2 |
| r3 | +12.2 ± 2.7 | +29.9 ± 2.2 | +19.4 ± 2.3 | +16.5 ± 2.7 |
| r0 | +14.0 ± 2.6 | +27.6 ± 2.4 | +17.4 ± 3.1 | +18.2 ± 2.9 |

**Reading.**
- **No loss from a mis-specified opponent model.** None of the agent policies loses points when rivals deviate from the rule r2 assumes. Their advantage over the baseline grows, and the ranking (r2 > r0 ≈ r3) is stable.
- **Opponent-model sensitivity is low** for the rival behaviours tried. That is evidence that the current rivals don't punish a wrong opponent model, not that the agents model opponents well.
- **Sample size:** 40 seeds; s.e. 2–3 points.

### 4. Decision-level failures (items 2, 4, 7)

**Method.**
- **Scoring:** each race decision on each run is scored with public information only. The agent's action, the best alternative and the baseline's action are each played now, then a fixed continuation plays the rest.
- **Futures:** 48 public futures for selection and an independent 48 for evaluation, conditioned only on what the agent had observed.
- **Candidates:** decisions where the loss exceeds 1 point and 2 s.e. under the **public baseline continuation**.
- **Confirmation:** a candidate is **confirmed** only if, re-estimated with the **agent's own written policy as the continuation** (independent futures, 24 samples), its loss again exceeds 1 point and 2 s.e.
- **Realized single-seed outcomes are never used** to classify a failure.

| Run | Race decisions | Candidates | Confirmed | Model-submitted confirmed | Script confirmed |
|---|---:|---:|---:|---:|---:|
| r0 | 112 | 22 | 7 | 0 | 7 |
| r1 | 112 | 16 | 6 | 0 | 6 |
| r2 | 112 | 12 | 5 | 0 | 5 |
| r3 | 112 | 22 | 8 | 1 | 7 |
| **Total** | 448 | 72 | **26** | 1 | 25 |

**Model-submitted vs script decisions (item 2).**
- **Samples:** the 18 "model-submitted" race decisions are every race decision the model sent itself (including r3's 4 script-assisted ones). They all fall in race 1, at decision positions 1–7 (r0, r3) or 1–2 (r1, r2). The 126 "script" decisions are the script decisions at the **same within-race decision positions** in races 2–8.
- **Result:** mean one-step loss under the baseline continuation is **0.97** (model-submitted) vs **0.69** (script).
- **Limits:**
  - The two groups were **not compared in the same decision states**. The model-submitted decisions all come from race 1 (one track); the script decisions come from seven other tracks with different car states.
  - The sample is small (n = 18).
  - So no difference can be claimed. The one confirmed model-submitted failure (r3 race 1 lap 3) has the same pattern as the script failures (type T1 below).

**Independent failure types after merging repeats (item 7):**

| Type | Instances (runs) | Pattern | Mechanism (checked how) | Category |
|---|---|---|---|---|
| **T1 Early SOFT stop never considered** | 9 (r0 ×1, r2 ×2, r3 ×6) | Apex A, which starts on SOFT, is left out at laps 3–6 when a stop for HARD is worth +1.4 to +5.3 points | Candidate pruning: r0 never pits a SOFT before age 9 (or anything before age 4); r2 skips GREEN stops below age 5; r3 only proposes stops when the tyre is near its life (SOFT ≥ 9). Forcing r3's own simulator to evaluate the pruned candidate shows that **its own model prefers PIT_HARD** (R4: 40 vs 33 pts; R7: 30 vs 27), in the same direction as the engine. The published tyre coefficients are applied correctly in r2 and r3 (age a, a+1, a+2; cliff; warm-up). r1, which enumerates every action, has no T1 failure. | **Long-horizon (in-race) planning failure: search-space pruning** |
| **T2 Late unnecessary stop (≤ 6 laps left)** | 4 (r0 ×3 incl. one under VSC; r2 ×1 under SC) | A stop with 6 laps to go costs 3–10.6 points | r0: its compound rule fits HARD with 30 laps left (life 24), so its own end-of-life rule forces a stop at lap 39 (removing it gains +16.0 ± 0.6 pts over 200 seeds). r2: its forward model assumes every future segment is GREEN, so the SC seems to end at once and a fresh SOFT looks worth having; the published SC duration model says otherwise. | r0: **long-horizon planning failure** (internally inconsistent plan). r2: **world-model mismatch** (event model ignored) |
| **T3 Missed or late mid-race stop** | 10 (r0 ×3, r1 ×4, r2 ×2, r3 ×1) | A car past its tyre life at laps 18–27 is left out | r1: its model scores each driver by **time only, one car at a time**, and prefers STAY by 4–6 s, while the engine says stopping gains +1.6 to +4.0 pts from track position, dirty air and rival stops. r0/r2/r3: threshold or model specifics, not separated further. | r1: **world-model / objective mismatch** (time as a proxy for points). Others: **action regret** (mechanism unconfirmed) |
| **T4 SC/VSC stop allocation** | 2 (r1 ×1, r3 ×1) | Wrong car stopped under VSC (r1); double stack under VSC (r3) | Not isolated | **Action regret** |
| **T5 Unnecessary early stop** | 1 (r1) | Fresh-tyre stop at lap 9 | Not isolated | **Action regret** |
| Tool execution errors | 0 affecting outcomes | — | 0 rejected actions in all runs; r2 left a stray `EOF` line in a script (harmless); r3 sent one malformed request (no effect) | **Tool execution error: none material** |

That gives **26 confirmed instances, which reduce to 5 independent failure types**. Three of them (T1–T3) recur across runs. Each run's Track A plan (the same in 4/4) shows no failure against the available comparators. A long-format Track A optimum doesn't exist yet (B5).

**T1 in detail (item 4).**
- **The trade-off:** under the published model SOFT degrades 0.35 s/lap per lap of age × the track multiplier. So 3–6 laps into the race, a SOFT is already losing ground to a HARD fitted now.
- **What the agents did:** two of four agents applied the coefficients correctly but wrote a candidate filter that never asks this question.
- **Model vs engine:** the planner's predictions are optimistic but not reversed (r3 predicts 40 pts for PIT_HARD where the engine's expectation is 37.2). The failure is in the search, not the world model.
- **Calibration caveat:** the size of T1 depends on the synthetic SOFT coefficient. With calibrated data it could shrink.

### 5. Information and compute: agent planners vs analysis reference (item 8)

| Planner | Information | World model | SC/VSC model | Search | Compute per decision |
|---|---|---|---|---|---|
| r0 bot | Public observation | Fixed thresholds | Current status only | None (rules) | ≪ 1 ms |
| r1 `champion.py` | Public observation; constants copied from rules | Per-driver tyre/pit time model; no rival interaction | Current status only; future assumed GREEN | Exhaustive over 0–2 future stops per driver | ≈ 0.18 s |
| r2 `run_championship.py` | Public observation; constants copied from rules (mapping correct) | Own whole-field forward simulator incl. rivals' public rule, dirty air, overtaking, approximate SC compression | Current status only; future assumed GREEN | Pruned joint candidates (no GREEN stop below age 5) | ≈ 0.01 s |
| r3 `run_championship.py` | Public observation; constants copied from rules (2 base paces swapped) | Own whole-field forward simulator | Current status; future GREEN | Pruned (stop only near tyre life) | ≈ 0.01 s |
| **Analysis reference (rollout)** | Public observation **plus the published SC/VSC model** (futures conditioned on observed statuses) | **The authoritative engine code**, which implements the published rules exactly | Sampled from the published model | One-step lookahead over all 16 joint actions, public baseline afterwards | ≈ 0.4 s (16 × 32 rollouts) |
| Analysis scorer (trace) | Same as the reference | Authoritative engine | Same | 16 actions × 48 + 48 futures, two continuations | ≈ 1 s |

The reference has no hidden seed or future events. But it does have an **exact executable world model**, which the agent had to rebuild from the rules. Part of the agent-vs-reference gap is therefore a world-model-building gap, which the benchmark legitimately measures. It should be reported as such, not as pure decision quality.

### 6. Answers to the final questions

1. **Does Gemini repeatedly automate its strategy?** Yes, in 4/4 runs. It submits 3–8 decisions itself, starts automating at d004 or d009, then hands 112–117 decisions to a script. 3/4 runs wrote test or advisor scripts before automating; 0/4 revised the policy after seeing race results.
2. **Do the written policies' flaws repeat?**
   - The specific rules differ by run, so the size of each flaw differs. r0's late stops cost 16 pts per season; the same flaw costs ≤ 3 in the others.
   - Two **mechanism families recur**: (a) candidate pruning and threshold rules that skip an early SOFT stop (3/4 policies, 9 confirmed instances), and (b) futures assumed GREEN, with the published SC/VSC model never used (4/4 policies).
   - The Track A plan is identical in 4/4.
3. **Do model-submitted and script decisions show different loss patterns?** No difference can be claimed: 0.97 vs 0.69 mean one-step loss at matched positions, n = 18 vs 126, confounded by track and state. The one confirmed model-submitted failure has the same pattern (T1) as the script failures.
4. **Is SC/VSC replanning actually measured?**
   - **Only indirectly.** The environment gives replanning real value (Part 1), and every policy reacts to the current status.
   - But no policy uses the published duration and start model, and none re-plans live. What gets measured is the quality of a pre-committed reactive rule, not the model's own reasoning after an event.
   - 3 of the 26 confirmed instances are SC/VSC-specific (T2-r2, T4).
5. **What should B5 prioritize for reference and evaluation?**
   1. A long-format full-season reference with a stated information and compute budget, so Track A and in-race gaps have a strong comparator (both are rule-bounded today).
   2. Multi-seed evaluation of written policies as a standard verifier-side report next to the single-run reward (needs a decision on the reward contract; not changed here).
   3. Per-decision provenance in the journal (model-submitted vs script) instead of inferring it from trajectories (environment change, versioned).
   4. Pinned analysis interpreter (Python 3.12, as in the images) plus the attribution tools used here (agent-policy continuation, forced-candidate check) as standard.
   5. The documentation fix below.

### Environment changes proposed (not applied; separate changeset)

Update: items 1 and 2 were applied as benchmark version 1.1.0; see `docs/VERSIONS.md`.


1. **Publish base paces under the observation names.** Keep `published_base_pace` keyed by `Orion A`, …, or publish the `Rival n → team driver` mapping. Today the mapping has to be inferred, and r3 got it wrong. This changes public information, so it needs a version bump, and earlier runs should be marked as pre-fix.
2. **Pin the Python used by `analysis/` to 3.12**, the same as the images, for bit-exact replays.
3. **Optional:** record `submitted_via` (`f1ctl` vs raw socket) per request in the journal, to make delegation directly observable.

None of these change the difficulty of the task.

## Part 3 — Integrating with Track C and a two-team competition

**Track C (Engineer A/B + Chief).**
- **Interface:** engineers should be exposed through the observation (an `engineer_reports` block per decision, journaled through the observation hash). Not a separate channel, so the verifier can replay it.
- **Hosting:** small models on the available A100 (e.g. vLLM). The Chief stays on the API.
- **Delegation interacts with Track C.** A Chief that writes a script after a few decisions will either ignore the engineers or hard-code a reaction to them. Options:
  - (a) Accept it and evaluate the script's handling of reports across seeds.
  - (b) Measure engineer-report use per decision and treat "script ignores reports" as its own outcome.
  - In both cases the report content must vary within a race (simulator-grounded per-driver advice), so a static script can't fake using it.
- **Ablation conditions** (none / aligned / conflicting / miscalibrated) should be seeded per decision, so that conditions are paired across runs.

**Two-team competition.**
- **Rival interface:** rival teams are currently a public deterministic rule inside the engine. A second agent team needs simultaneous actions per decision: the sidecar collects both teams' actions before stepping and times out to a default action.
  - Each team gets its own `decision_id` stream and its own visibility: its own private component wear; the other team sees only public usage, as rivals do now.
  - The journal and verifier must record and replay both action streams.
- **Harbor:** Harbor runs one agent per trial. A practical first step is a **frozen opponent pool** in the sidecar:
  - It holds policies written in earlier runs (e.g. r2's planner), loaded from the verifier-owned image and never visible to the agent.
  - Then a live second agent in its own container, if the harness allows.
  - The rival-sensitivity analysis above is the offline version of this.
- **Fairness:** swap sides on paired seeds; score head-to-head (constructors' margin) separately from absolute points; keep the hidden-seed and evidence boundary per team.
- **Reward:** a relative score (margin vs the opposing team) needs its own contract and anchors. Don't reuse the P0 provisional scalar.

## Reproducing

```bash
# Verda (Harbor 0.26.0)
f1-championship/scripts/make_seed_variant.sh seed-rN <seed> rN
harbor run -p seed-rN -a opencode -m gemini/gemini-3.8-flash --api-key-name GEMINI_API_KEY \
  --env-file <env file> --allow-agent-host generativelanguage.googleapis.com -o jobs --job-name rep-gemini-rN

# Mac, Python 3.12 for bit-exact replays
python analysis/delegation.py <trajectory.json> <evidence_dir> <out_dir>
python analysis/frontier_trace.py <evidence_dir> <trace.json> --seed <seed>
python analysis/confirm_candidates.py <evidence_dir> <trace.json> <script>:<race_fn> <seed> <confirm.json>
python analysis/written_policy_eval.py <script> --component-fn <fn> --race-fn <fn> --hidden-seed <seed>
python analysis/repeat_summary.py <runs.json> analysis/results/rep_summary.json
python analysis/rival_sensitivity.py <runs.json>
```

**Data files.**
- **Summaries:** `analysis/results/rep_summary.json`, `rep_policy_comparison.json`, `rep_r{1,2,3}_policy_eval.json`, `b4_written_policy_eval.json`, `rep_rival_sensitivity.json`.
- **Per-run analyses and scripts:** `analysis/results/rep_runs/`.
- **Raw trajectories:** not committed; kept on Verda `/root/f1-championship-p0/jobs/`.
