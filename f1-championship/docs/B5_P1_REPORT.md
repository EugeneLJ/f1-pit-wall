# B5-P1 report — SC/VSC-aware planning, counterfactual evaluation and rival-strategy sensitivity

> **Benchmark version: 1.1.0 (unchanged).** B5-P1 adds analysis code and an **opt-in** rival-strategy hook.
> The published model, the mechanics, the event probabilities, the action space, scoring, the rules text and
> the agent observation are unchanged. The default race state is identical byte for byte. A Harbor oracle run
> reproduces the 1.1.0 journal exactly (120/120 entries with identical observation hashes and actions).
> The four Gemini runs (r0–r3) remain historical 1.0.0 results. Their policies are replayed here unchanged.

Branch `feature/track-b`. All numbers come from Python 3.12 (`scripts/py312`).
Re-run them with:

```
scripts/py312 analysis/b5_event_audit.py
scripts/py312 analysis/b5_event_eval.py --scenarios 24 --natural 4 --event 4 --workers 10
scripts/py312 analysis/b5_reversals.py --workers 10
scripts/py312 analysis/b5_rival_eval.py --scenarios 24 --paths 2 --workers 10
scripts/py312 analysis/b5_summarize.py            # -> analysis/results/b5_summary.json
```

**Bottom line.**
- **We can now measure the decision-quality gap between SC/VSC-blind and SC/VSC-aware strategies, reproducibly.** The aggregate value is real but small. Most of it lives in a few event decisions. Per decision it is large.
- **SC/VSC-specific failures of the Gemini policies are measurable and distinct from the 26 earlier failures.**
  - The dominant one is **over-reaction**: pitting both cars, or the wrong car, under an SC/VSC.
  - It is not a failure to anticipate events. It is not optimism about when an SC ends.

---

## 1. SC/VSC mechanics audit (from code)

Source: `src/f1pitwall/engine.py` (`neutralization_schedule`, `_continue_schedule`, `step`, `_neutralized_segment`, `observation`) and the `neutralization` block of `fixtures/track_a_coefficients.json`.

| Item | What the code does |
|---|---|
| Generation | `random.Random(f"neutral:{seed}")`. The whole schedule (14 statuses) is drawn **when the race is created**. It is independent of every action, so a pit decision cannot change future events. |
| Start probability | At a GREEN decision that is not in cooldown: SC 0.035, VSC 0.035. Otherwise GREEN. |
| Duration | Drawn at the start. SC 1/2/3 segments with 0.35/0.50/0.15. VSC 1/2 with 0.70/0.30. Each segment is 3 laps. A duration may run past the last decision; it is truncated. |
| Return to GREEN | After the drawn duration. Then at least `cooldown` = 1 GREEN segment before another start. |
| Observe/act order | The status of decision *k* is **revealed in the observation before the action at k**, and it applies to the segment that follows. "SC just started" therefore means the agent can pit in the first SC segment. |
| Pit loss | Applied first, at the status of the decision: base × 0.30 (SC) or × 0.55 (VSC). The shared-crew queue (6 s, second car of the team in road order) and the warm-up flag are set the same way. |
| Segment effect | All cars run slow laps (factor 1.4 SC / 1.3 VSC × mean legacy pace × laps). No overtaking. Tyres age 1 lap (SC) / 2 laps (VSC) per segment. The warm-up is cleared. |
| Gap compression | SC only, after the slow laps: each car's gap to the car ahead becomes `min(gap, 0.8 s)`, with order kept. So a car that pits under SC rejoins at the back of the compressed train. VSC keeps the gaps. |
| Observation | `track_status`, `neutralization{status, segments_so_far}` and the full `event_model` (start probabilities, duration law, cooldown). Remaining duration, future statuses and the seed are hidden (`future_track_status: "hidden"`). |
| Future-model exposure | The exact generating law is public (`event_model`, `f1ctl rules`). A planner can condition on `segments_so_far` to get the exact continuation probability. |

**Distribution check** (`analysis/b5_event_audit.py`, `results/b5_event_audit.json`): 100 000 simulated races against an exact dynamic-programming solution of the same Markov process.

| Quantity | Exact | Simulated (95% CI) |
|---|---:|---:|
| SC starts per race | 0.4464 | 0.4463 |
| VSC starts per race | 0.4464 | 0.4461 |
| Races with ≥ 1 SC / ≥ 1 VSC | — | 0.379 / 0.376 |
| SC duration 1/2/3 (uncensored, n = 35 199) | 0.35/0.50/0.15 | 0.349/0.504/0.147 (all inside CI) |
| VSC duration 1/2 (n = 38 436) | 0.70/0.30 | 0.696/0.304 (inside CI) |
| P(SC continues after 1 segment) | 0.650 | 0.652 [0.648, 0.657] |
| P(SC continues after 2 segments) | 0.231 | 0.227 [0.222, 0.233] |
| P(VSC continues after 1 segment) | 0.300 | 0.304 [0.299, 0.308] |
| Occupancy per decision and status (28 cells) | DP | 26/28 inside the 95% CI. Max \|z\| = 2.08, which is consistent with chance at 28 tests. |
| Cooldown | ≥ 1 GREEN | Respected in every race. |

The durations are measured only on episodes that start early enough to finish before the race ends. Naive counting under-reports long SCs because of right-censoring. Conclusion: the implementation matches the published law. No mechanic was changed.

## 2. Four event-aware references (`analysis/event_policies.py`)

Every planner has the same pieces:
- the 16 joint actions;
- the same public baseline continuation;
- the same exact engine for rollouts;
- the same 24-future budget per decision (deterministic modes need one);
- statuses only up to the current decision.

They differ **only in their model of future SC/VSC**:

| Reference | New events | Current event | Duration law |
|---|---|---|---|
| `green_only` | none | ends now | — |
| `reactive` | none | continues per published law, conditioned on `segments_so_far` | public |
| `prob_aware` | published start probabilities | ends now | every event lasts 1 segment |
| `full` (fair reference) | published | conditioned continuation | public |
| `full_long` *(diagnostic)* | published | as full | every event lasts its maximum |
| `clairvoyant` *(diagnostic, unfair)* | true remaining path | — | — |

**Information boundary** (tested in `devtests/test_rival_policies.py::PlannerInformationTests`):
- Planner futures are seeded from `(mode, step, observed history)` only.
- Changing the true future after the current decision changes neither the futures nor the chosen action, in any fair mode.
- `clairvoyant` is the only mode that reads the true path. It is reported as a diagnostic bound.

**Model-access difference (important).** These references roll out the authoritative engine: the published rules, executed exactly. The agent-written policies had to build their own approximate model from the rules text. Part of the agent–reference gap is therefore a *model-construction* gap. That gap is legitimate to measure (everything needed is public), but it is not pure decision quality. The sections below separate the two where possible.

**Evaluation design** (`analysis/b5_event_eval.py`):
- **States.** 24 generated calendars × races 1, 4 and 7 = **72 race-start states**. Each is built through the real `ChampionshipSession`, so agent policies receive the exact agent-visible observation.
- **Paths.** For each state, 4 **natural** paths come from the true published process, plus 4 **event** paths conditioned on at least one SC/VSC (by rejection).
- **Seed separation.** Evaluation seeds (`b5-eval|…`), planner sampling (`plan|…`) and decision re-valuation (`evaluate|…`, 48 futures) are separate streams. This avoids winner's-curse bias.
- **Uncertainty.** The unit is the state: paired differences are averaged over its paths, and t-intervals are taken across the 72 states.
- **Cost.** 659 s wall time on 10 local cores.

### Mean Apex points per race (natural paths = the published event process)

| Policy | Natural (72 states, 288 paths) | Event-conditioned |
|---|---:|---:|
| `clairvoyant` (diagnostic) | 33.48 | 33.90 |
| **`prob_aware`** | **33.39** | **33.57** |
| **`full`** | **33.26** | **33.41** |
| `reactive` | 33.24 | 32.88 |
| `green_only` | 32.99 | 32.79 |
| `full_long` (diagnostic) | 32.58 | 31.70 |
| public baseline heuristic | 29.98 | 29.73 |
| Gemini r2 / r1 / r0 / r3 | 30.49 / 30.16 / 29.67 / 29.50 | 30.24 / 31.66 / 31.19 / 29.68 |

### Value of event information (paired, mean [95% CI], points per race)

| Contrast | Natural | Event-conditioned |
|---|---:|---:|
| Anticipation: `prob_aware` − `green_only` | **+0.40 [0.09, 0.71]** | **+0.78 [0.28, 1.27]** |
| Persistence/replanning: `reactive` − `green_only` | **+0.25 [0.06, 0.44]** | +0.09 [−0.18, 0.35] |
| `full` − `green_only` | +0.26 [−0.15, 0.68] | **+0.61 [0.09, 1.14]** |
| `full` − `reactive` | +0.01 [−0.39, 0.42] | **+0.53 [0.05, 1.00]** |
| Duration law: `full` − `prob_aware` | −0.13 [−0.44, 0.18] | −0.16 [−0.64, 0.32] |
| Duration misspecification: `full` − `full_long` | **+0.67 [0.34, 1.01]** | **+1.71 [1.22, 2.20]** |
| Hindsight gap: `clairvoyant` − `full` | +0.23 [−0.14, 0.60] | **+0.50 [0.20, 0.79]** |
| `full` − public baseline | +3.28 [2.71, 3.85] | +3.68 [2.95, 4.41] |
| `full` − Gemini r0 / r1 / r2 / r3 | +3.59 / +3.10 / +2.76 / +3.76 | +2.21 / +1.74 / +3.17 / +3.73 |

**Reading.**
1. **Event awareness has measurable value.**
   - Anticipating new events with the published start probabilities is worth +0.4 points per race on the published process and +0.8 when an event happens. Both intervals exclude 0.
   - Modelling persistence is worth +0.25 points per race.
   - Over-estimating durations is clearly harmful: `full_long` loses 0.7 points per race, and 1.7 when events happen.
   - Full SC/VSC awareness (`full`) beats GREEN-only by +0.61 [0.09, 1.14] when events happen. On the natural mix the difference is +0.26, and that interval includes 0, because about 40% of races have no event.
2. **The full duration law adds nothing over a 1-segment assumption** (`full` ≈ `prob_aware`, −0.13 ± 0.3). The reason: a car that waits one more SC segment keeps the cheap pit loss, so assuming "it ends now" makes the planner pit at once. Pitting at once is near-optimal anyway. This is a property of the current coefficients, and it is reported rather than tuned away.
3. **The hindsight bound is close** (+0.23 natural). Knowing the future is worth little beyond the public model, so the fair reference is near the information limit. The remaining gap to the agents (~3 points per race) is not about SC/VSC information.
4. **Per-race regret relative to `full`** (natural paths):

   | Policy | Paths with regret > 1 point | Median regret | p90 regret |
   |---|---:|---:|---:|
   | `prob_aware` | 11.8% | 0 | — |
   | `reactive` | 19.4% | 0 | — |
   | `green_only` | 23.6% | 0 | — |
   | baseline | 63.9% | 2.9 | 7.8 |
   | Gemini r0–r3 | 45–73% | — | 9.6–10.6 |

   Regret is lumpy: one swapped finishing position is worth about 1–3 points. That is why paired intervals across states are used throughout.

### Decision-level view (re-valued on 48 independent futures)

Decisions analysed: every SC/VSC decision, every decision within 2 decisions after an event, and a 15% sample of the remaining GREEN decisions. That is about 2 900 per policy, 978 of them under SC/VSC.

**How often does event awareness change the best action?** On the states each policy actually visits, `full` and `green_only` pick different actions in **31–34% of SC/VSC decisions** and **10–13% of GREEN decisions**. The split by current status (on the `green_only` trajectories):

| Current status | n | `full` ≠ `green_only` | Mean loss of `green_only` (points) |
|---|---:|---:|---:|
| SC, 1st segment | 304 | 49% | **1.35** |
| SC, 2nd segment | 212 | 28% | 0.41 |
| VSC, 1st segment | 316 | 17% | 0.11 |
| VSC, 2nd segment | 92 | 33% | 0.23 |

The value is concentrated in the **first segment of an SC**.

**Near-tie and meaningful decisions.**
- "Near tie" means |loss| < 0.25 points.
- "Significant" means loss > 1.0 point **and** > 2 standard errors.

| Policy | Same action as `full` | Near ties | Significant losses | Mean loss (all / SC-VSC) |
|---|---:|---:|---:|---:|
| `prob_aware` | 90% | 93% | 2.3% | 0.07 / 0.20 |
| `reactive` | 85% | 89% | 3.2% | 0.07 / 0.11 |
| `green_only` | 81% | 85% | 7.5% | 0.23 / 0.58 |
| `full_long` | 84% | 87% | 6.6% | 0.21 / 0.65 |
| baseline | 62% | 66% | 25.4% | 0.89 / 1.76 |
| Gemini r0 | 65% | 70% | 21.5% | 0.70 / 1.28 |
| Gemini r1 | 68% | 73% | 19.0% | 0.60 / 0.86 |
| Gemini r2 | 72% | 77% | 15.4% | 0.63 / 1.23 |
| Gemini r3 | 66% | 70% | 21.3% | 0.94 / 1.90 |

## 3. Event-driven counterfactual reversals (`analysis/b5_reversals.py`)

**Method.**
- Take decision states visited by `full` on the evaluation paths: all SC/VSC decisions, half of the decisions from lap 33 on, and 12% of the other GREEN decisions. That gives **2 750 naturally generated states**. None was constructed or selected to fail.
- Evaluate all 16 joint actions under explicitly constructed future classes.
- These classes are evaluation-only. The policy only ever chooses under the public mixture.

| Required scenario | Natural states | Finding |
|---|---:|---|
| GREEN: pitting now is good | 189 / 1 772 GREEN states have a best action that pits | Example: race 1, lap 3, `PIT_HARD/STAY` is worth +4.4 ± 0.5 points over STAY/STAY. |
| GREEN: STAY is good **because** an SC may come | 8 / 1 772 (all at lap 24, the same state family) | All are near ties (regret 0.01–0.96, SE ≈ 0.65). **This class is essentially absent under the current coefficients.** The anticipation value in §2 comes from compound and timing choices, not from clean "wait for the SC" reversals. |
| If an SC were certain next, the best GREEN action would change | 289 / 1 772 (16%) | This is a value of *hindsight*, not obtainable from public information. It is bounded by the +0.23 clairvoyant gap. |
| SC just started: PIT is good | 272 / 304 first-segment SC states pit at least one car | Example: lap 21, double stop on HARD, +14.1 ± 0.7 points. A double stack under SC can be right. |
| SC just started: STAY is good | 32 / 304 | Late race (e.g. lap 42) or fresh tyres. |
| Best choice depends on SC duration (d = 1/2/3 segments) | **228 / 304** change the exact action; **189 / 304** change the number of stops | The most common patterns are "1 stop if d = 1, else 0" (39), "2 stops if d = 1, else 1" (39) and "1 if d = 1, then 2" (17). Example: lap 9, `STAY/PIT_MEDIUM` if d = 1, `STAY/STAY` if longer. Waiting keeps the cheap pit loss for one more segment while the tyres age only 1 lap per SC segment. |
| SC ends earlier than expected (replanning) | — | Measured as policy value: assuming the maximum duration (`full_long`) costs **0.67 [0.34, 1.01]** (natural) and **1.71 [1.22, 2.20]** (event) points per race. |
| VSC vs SC call for different strategies | **540 / 978** neutralized states change their best action when the status type is flipped | Example: lap 15, VSC → STAY/STAY, but SC → PIT_HARD/STAY. |
| Late race (lap ≥ 33): pitting good vs bad | 109 / 1 430 pit; 79 with a gain > 1 point | Example: lap 36, `STAY/PIT_MEDIUM`, +5.0 ± 0.4 points. In the other 92% STAY is best or tied. |

## 4. Gemini r0–r3 attribution on SC/VSC scenarios

**Setup.**
- The four agent-written race policies are loaded unchanged from `analysis/results/rep_runs/rX/scripts/`.
- They play every path above, from the same 72 states, and receive the exact session observation.
- The component (Track A) part is not used: these are in-race replays.
- **This scenario set is new. These counts are not added to the 26 confirmed failures of the repeat report.** Those were found on each run's own season. These are per-decision diagnoses on a shared, representative set. Decisions inside one path are correlated, so the counts describe *where* loss comes from, not independent events.

**Classifier** (`b5_event_eval.classify`, applied in this order, to significant losses only):
1. `candidate_pruning`: the reference stops a car that the agent's own hard-coded filter (transcribed from its source) could never propose in that state.
2. `model_based:optimistic_event_end`: under SC/VSC, the agent picked exactly the GREEN-only planner's action while the full reference differs.
3. `replanning:no_adaptation_to_event`: the agent would take the same action if the status were GREEN, so the event changed nothing.
4. `replanning:over_or_mis_reaction`: the event changed the agent's action, but in the wrong direction.
5. `model_based:no_anticipation`: under GREEN, the agent equals `green_only` while `full` differs.
6. `action_regret`: everything else.

**Significant losses by category** (EV = at an SC/VSC decision; GREEN = elsewhere, including decisions just after an event):

| Run | Significant | Pruning EV / GREEN | Over/mis-reaction (EV) | No adaptation (EV) | Optimistic end (EV) | No anticipation | Action regret |
|---|---:|---:|---:|---:|---:|---:|---:|
| r0 | 635 | 224 / 226 | 144 | 2 | 6 | 0 | 33 |
| r1 | 547 | 0 / 0 | 138 | 103 | 21 | 5 | 280 |
| r2 | 452 | 0 / 57 | **225** | 31 | 22 | 5 | 112 |
| r3 | 614 | 113 / 213 | **249** | 4 | 1 | 0 | 34 |

**What goes wrong in an over-reaction** (agent action vs `full`):

| Run | n | Pits both cars (double stack) | Extra single stop | Fewer stops | Wrong car | Wrong compound | Mean loss |
|---|---:|---:|---:|---:|---:|---:|---:|
| r0 | 144 | 25 | 69 | 6 | 16 | 28 | 3.2 points |
| r1 | 138 | 25 | 52 | 44 | 16 | 1 | 3.3 points |
| r2 | 225 | **105** | 50 | 22 | 16 | 32 | 4.2 points |
| r3 | 249 | **164** | 42 | 1 | 14 | 28 | 5.1 points |

**Interpretation.**
- **Ignoring SC/VSC probabilities** (`no_anticipation`): ≤ 5 per run. No policy reads `event_model`, but in this model that costs little (§3: the "STAY because SC may come" class is almost empty).
- **Optimistic SC end** (`optimistic_event_end`): 1–22 per run, small. r2's explicit "neutralization ends after this segment" assumption equals `prob_aware`'s assumption, and that assumption is near-optimal here (§2).
- **Sticking to the plan** (`no_adaptation_to_event`): this matters for **r1** (103). Its scorer barely changes with the status.
- **Over-reaction** is the main SC/VSC-specific failure. Its share of the significant SC/VSC losses is 64% (r2) and 68% (r3). It is mostly **"SC/VSC means pit both cars"**: the double stack pays the shared-crew queue and both cars rejoin at the back of the compressed train. The reference double-stacks only when it is worth it.
  - This matches B4's finding that "always pit under SC" is worse than not replanning in 545/936 cases.
- **Candidate pruning (general)**: dominant for r0 and r3, including at SC/VSC decisions (r0 224, r3 113). Their filters forbid stops on young tyres even when an SC makes them cheap. **This is the same mechanism as earlier type T1/T3 (early-stint SOFT pruning). It is not a new SC failure.**

**Separating the four requested causes:**

| Cause | Where it shows up |
|---|---|
| Model-based planning failure | `no_anticipation`, `optimistic_event_end`. Small. |
| Candidate-pruning failure | Structural (filter) losses. Large for r0/r3, absent for r1. |
| Genuine replanning failure | `no_adaptation_to_event` (r1) plus `over_or_mis_reaction` (all runs, largest for r2/r3). |
| Pure action regret | Residual. Large for r1, where the candidate set is complete but the scorer is wrong. |

## 5. Rival pit-strategy sensitivity (`src/f1pitwall/rival_policies.py`, `analysis/b5_rival_eval.py`)

Opt-in variants (default = `public`, the published `engine._rival_action`):
- They are enabled only through `coefficients.with_rival_policy(coeffs, name)`, which sets the race config key `rival_policy`.
- They use only public pit-wall information: own tyres, laps left, status, running order and gaps, and visible tyre ages.
- None reads the seed, future events or retirement draws.
- All satisfy the two-compound rule (0 penalties in tests).
- When the default is used, the key is **absent** from the race state. State hashes and observations are therefore unchanged (tested; Harbor oracle journal identical to 1.1.0).

Behaviour (60 seeds, rival cars):

| Variant | Rule | Stops/race | Mean first stop (lap) | Share of stops under SC/VSC |
|---|---|---:|---:|---:|
| `public` (default) | published rule | 1.57 | 17.8 | 0.45 |
| `conservative_2stop` | targets laps 15/30; earlier only if neutralized within 3 laps | 2.00 | 14.8 | 0.14 |
| `opportunistic` | tyre life, or any SC/VSC with tyres ≥ 4 laps old | 1.59 | 16.1 | 0.51 |
| `undercut` | tyre life, or within 2 s of an older-tyred car ahead near life, or SC with tyres ≥ 7 laps | 1.48 | 18.8 | 0.32 |
| `long_stint` | life + 3 laps, HARD preferred, SC only at age ≥ 12 | 1.20 | 21.5 | 0.36 |
| `event_aware` | SC with tyres ≥ 4, VSC with tyres ≥ 7, GREEN stints stretched by 2 laps to keep an SC window open | 1.49 | 16.7 | 0.50 |

**Evaluation design.**
- The same 72 race-start states, with 2 natural + 2 event paths each and the same true event paths for every variant.
- `full_known` is the full planner whose rollouts use the actual rival variant.
- `full_assumes_public` is the same planner with rollouts assuming the published rival rule: a misspecified opponent model.
- Gemini r0–r3 and the baseline play unchanged.
- The 95% intervals are across states. Cost: 685 s wall time on 10 cores.

**Mean Apex points per race, and regret vs `full_known` (mean [95% CI]):**

| Rival variant | `full_known` | `full_assumes_public` regret | Baseline regret | r0 | r1 | r2 | r3 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `public` (default) | 33.64 | — | +3.52 [2.80, 4.23] | +3.24 | +2.44 | +3.37 | +4.13 |
| `conservative_2stop` | 36.28 | +0.55 [0.20, 0.91] | +3.28 | +2.04 | +0.81 | +1.53 | +2.17 |
| `opportunistic` | 32.98 | +0.55 [0.16, 0.93] | +4.31 | +3.65 | +2.45 | +3.05 | +3.98 |
| `undercut` | 33.39 | +0.41 [0.04, 0.78] | +3.70 | +4.01 | +3.23 | +3.79 | +4.61 |
| `long_stint` | 34.13 | +0.99 [0.58, 1.41] | +3.94 | +4.04 | +2.20 | +2.91 | +4.44 |
| `event_aware` | 33.18 | **+1.01 [0.53, 1.50]** | **+5.00** | **+4.23** | +3.08 | +3.64 | **+4.94** |

All Gemini regret intervals exclude 0 (their half-widths are 0.5–1.1 points).

**Does the value of PIT/STAY and compound choices change with the rivals?** Yes. On 1 355 fixed decision states (all SC/VSC decisions plus 25% of GREEN decisions, taken from `full_known` trajectories under the default rivals), the best joint action differs from the default-rival best action in:

| Variant | All states | SC/VSC states |
|---|---:|---:|
| `conservative_2stop` | 24.9% | 28.0% |
| `long_stint` | 17.7% | 26.3% |
| `event_aware` | 10.8% | 18.0% |
| `opportunistic` | 10.1% | 18.0% |
| `undercut` | 7.4% | 9.2% |

**Reading.**
- **The variants differ in substance, not just in name.** Both the stop counts and timing (table above) and the Apex best responses change.
- **Opponents who also use SC windows make the race harder.** These are `event_aware` and `opportunistic`, and they cost Apex 0.46–0.66 points per race relative to the default. The predictable `conservative_2stop` gives back 2.6 points.
- **A wrong opponent model costs 0.4–1.0 points per race.** That is the same order as the whole SC/VSC information value in §2. It is largest against `long_stint` and `event_aware`, which stay out longer than the published rule assumes.
- **Gemini regret is highest against `event_aware` and `undercut` rivals.** r1 has the lowest regret against every variant.
  - Against `conservative_2stop`, everyone's regret shrinks. With predictable rivals, simple rules are close to optimal.
  - The ordering of the four runs is stable (r1 best; r3/r0 worst), so the earlier rival-robustness conclusion holds.
- **Fairness.**
  - No variant gets information Apex lacks. All are stateless rules over public fields.
  - None is tuned against Apex or against the Gemini policies.
  - The default is unchanged.
- **Recommendation.** Keep `public` as the default. If a robustness split is wanted later, `event_aware` is the most informative opt-in variant: it has the largest misspecification regret and the largest Gemini regret. Changing the default would be a benchmark version change (1.2.0) and is not done here.

## 6. Two-team interface (design only; DeepSeek not run)

Target matchups:
- **McLearn Racing** (Chief = Gemini) vs **Red Bool Racing** (Chief = DeepSeek 4.1 Flash 1017).
- **Layer 1:** Chief vs Chief.
- **Layer 2:** Gemini Chief + Engineer A/B vs DeepSeek Chief.

**What the current code already provides:** an action-independent seeded world, a hash-chained journal, verifier replay, and the rival-policy hook. Through that hook a second controlled team can replace a rule-based rival.

**Required design:**

| Requirement | Design |
|---|---|
| Independent observations and action authority | One sidecar holds the authoritative state. Each team gets its own Unix socket (`/run/f1sim/<team>.sock`, separate volumes) and its own `f1ctl` token. An observation is rendered **per team**: own cars in full (tyres, components, `compounds_used`), rivals only through public fields (position, gap, visible compound, tyre age, pit history). A team can submit only `driver_a/driver_b` of its own cars. |
| Simultaneous submission | Each decision `d###` waits for both teams. Actions are committed as a pair, using the hash of each sealed action, and the step executes once both have arrived. Neither team can see the other's action for the same decision. A per-decision timeout applies the published default (STAY / USE) and journals it as a timeout. |
| Private/public isolation | Engineer briefings and private car data go only to the owning team. The journal records per-team observation hashes. The verifier checks that no team's observation contains the other team's private fields (a schema allow-list). |
| Rival adaptation | Each team sees the other's realised stops, compounds and gaps after each segment. No other channel exists. Adaptation is therefore measurable as a response to public history. |
| Journal/replay/verifier | Each entry becomes `{decision_id, actions:{team:…}, obs_sha256:{team:…}, timeouts}`. Replay reproduces both teams' observations from the hidden seed. The reward is computed per team. The existing single-team entries stay valid; this is a new `decision_type` schema entry, as the roadmap's extension points intend. |
| Same seed, paired runs, side swap | Each matchup runs on seed *s* twice, with the teams swapped between the two car slots and archetypes. The team effect is estimated from the paired difference, which removes car and grid advantage. Seeds are drawn from the representative generator and never selected. |
| Fair tools and inference budget | Same container image, same tools, same `f1ctl` surface, same wall-clock and decision timeouts. Each team's token and inference budget is logged per decision. Budget-matched comparisons are reported next to the raw ones. Scripts are allowed for both teams, and delegation is measured with the existing `delegation.py`. |
| Layer 2 (Engineer A/B) | Engineers are extra agents inside the McLearn container. They have read-only observation access and post messages to the Chief, who alone submits actions. Engineer messages are journaled as observation content. The DeepSeek team receives an equal-budget "no engineer" control. |

**Remaining integration blockers:**
1. Multi-socket sidecar and per-team observation rendering. Today only Apex is controllable.
2. A synchronised two-party decision barrier with timeout semantics.
3. Journal schema v2 and verifier per-team replay.
4. Harbor: two agents in one trial is not a stock OpenCode configuration. It needs either a custom agent wrapper that runs both models as subprocesses, or the sidecar opened to two separate Harbor trials with a rendezvous.
5. DeepSeek API host allow-listing and key handling on Verda, following TEAM_HANDOFF rules.
6. Reward definition for head-to-head play (points share vs margin).

## 7. Statistical uncertainty and limitations

- **Sample sizes.** 72 race-start states with 8 paths each (288 natural, 288 event-conditioned). The 95% intervals are across states.
  - The event-information effects are small (+0.25 to +0.8 points per race) compared with per-race noise (one position ≈ 1–3 points), so several intervals only just exclude 0.
  - `full` − `green_only` on natural paths does **not** exclude 0.
- **MC noise.** Planner Q-values use 24 futures per decision. Decision re-valuation uses 48 independent futures, with paired standard errors per decision. Significance requires > 1 point and > 2 SE.
- **Reference strength.** All references are one-step lookahead with the public baseline continuation, not a full tree search. Their values are lower bounds on what public information allows. `prob_aware` ≥ `full` is within noise and partly reflects this continuation.
- **Model access.** As stated in §2, the references use the true engine. Gemini's gap includes model construction.
- **Synthetic coefficients.** SC compression, pit-loss factors and duration law are placeholders. The near-absence of "STAY because SC may come" is a property of these values. It is reported, not tuned (the task forbids tuning).
- **Classifier.** Categories depend on transcribed candidate filters and on a status-flip counterfactual. Decisions inside one path are not independent.
- **Rivals.** The variants are hand-written public-information rules. They are not adaptive learners, and they do not respond to Apex.

## 8. Files changed

**Engine (opt-in only), synced to `environment/sim/f1pitwall/` and `tests/f1pitwall/` by `scripts/sync_engine.py`:**
- `src/f1pitwall/engine.py`. The `rival_policy` config key is kept only when it is set and is not "public". `step()` dispatches rival actions to `rival_policies.decide` when the key is set.
- `src/f1pitwall/rival_policies.py` (new). Five public-information rival variants.
- `src/f1pitwall/coefficients.py`. Adds `with_rival_policy(coeffs, name)`.
- `src/f1pitwall/championship_adapter.py`. `race_config` passes `rival_policy` only when `rival_policy_variant` is set.

**Analysis (new):** `analysis/b5_event_audit.py`, `event_policies.py`, `b5_event_eval.py`, `b5_reversals.py`, `b5_rival_eval.py`, `b5_summarize.py`.

**Results (new):** `analysis/results/b5_event_audit.json` and `b5_summary.json`. The raw per-path and per-decision outputs are gzipped: `b5_event_eval.json.gz`, `b5_reversals.json.gz`, `b5_rival_eval.json.gz`. Re-running a script writes plain `.json`, and readers prefer plain over `.gz`.

**Tests:** `devtests/test_rival_policies.py` (new):
- the default state and rules are unchanged;
- explicit `public` equals the default;
- every variant is distinct, compliant and hidden from the observation;
- unknown variants are rejected;
- planner futures ignore the true future;
- each mode's assumptions hold.

**Docs:** `docs/B5_P1_REPORT.md` (this file), `docs/ROADMAP.md` (phase row).

Not changed: the published coefficients, `instruction.md`, the server rules text, the verifier, the reward, the legacy root task, the Gemini results, main, and feature/track-c.

## 9. Verification

| Check | Result |
|---|---|
| `scripts/py312 -m unittest discover -s devtests -p 'test_*.py'` | 112 tests OK. This includes the 1.0.0 historical replay test, which needs 3.12. |
| Legacy root tests (`python3 -m unittest discover -s tests`) | 35 OK |
| Harbor lint (Verda) | OK |
| Oracle (`b5-oracle-01`) | reward 0.5873, same as 1.1.0 |
| Journal check | **Identical observation hashes and actions to `v110-oracle-01` for all 120 entries** |
| nop (`b5-nop-01`) | 0.0 |
| Probes: complete / stop | 0.5873 / 0.0 |

## 10. Commits

On `feature/track-b`, pushed to `origin/feature/track-b` only. `main` and `feature/track-c` are untouched.
1. **Opt-in rival strategy variants.** Engine hook, `rival_policies.py`, `with_rival_policy`, synced copies, `devtests/test_rival_policies.py`.
2. **SC/VSC-aware references, counterfactual and rival evaluation.** Analysis scripts, results, this report and the roadmap row.
