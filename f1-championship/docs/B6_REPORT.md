# B6 report — Integrated F1 Pit Wall championship and two-team competition

**Branch:** `feature/championship-integration`. It is based on `feature/track-b` (B5-P1, `c06c2b7`) and merges `origin/feature/track-c` (`a461a98` plus the doc-only `550b15a`).

**Benchmark versions:**
- **SOLO_LEGACY** remains **1.1.0**, with the same code path, contract, journal and reward.
- **SOLO_COORDINATION** and **TWO_TEAM_COMPETITION** are **2.0.0**: contract v2, journal v2, `config_hash`, and their own scalar.

Official validation used Python 3.12. No live model call was made and no API key was used.

**Bottom line.** The integration is complete:
- Track B and Track C now run in **one authoritative engine**.
- Team orders act **only through race time and the existing overtaking model**. With `RACE` the integrated step is **bit-identical to 1.1.0**.
- Two teams play **sealed simultaneous ticks**.
- Every run **replays from the seed**, including the exact Engineer reports.

What the integrated dynamics show, without any tuning:
- Changing **only the rival team's pit strategy changes McLearn's best action in 8–15% of states**.
- **Team orders are rarely the best choice** (RACE is best in 74% of executable states).
- **Give-backs have no average team-points effect.** One candidate state with a large gain needs confirmation.

---

## 1. Versioned modes (`src/f1pitwall/integrated/config.py`)

| Mode | Version | Contract | What it is |
|---|---|---|---|
| `SOLO_LEGACY` | 1.1.0 | `ChampionshipSession`, contract 1, journal v1, `p0-provisional` | Unchanged. `IntegratedConfig` refuses this mode. |
| `SOLO_COORDINATION` | 2.0.0 | contract 2, journal v2 | Apex Chief plus team orders and commitments, with an optional Engineer A/B condition |
| `TWO_TEAM_COMPETITION` | 2.0.0 | contract 2, journal v2 | McLearn Racing vs Red Bool Racing. Each team controls two cars in the same race. Layer 1 (no Engineers) or Layer 2 (McLearn Engineers). Rival condition `ADAPTIVE` or `FIXED_REPLAY`. |

**Reproducible metadata.** `IntegratedConfig.as_dict()` and `config_hash()` cover the mode, version, teams (label, driver prefix, car slot, Chief provenance, Engineer condition), rival condition, rival pit-rule variant and decision timeout. `swapped()` exchanges the two teams' car slots.

**Team identity and car slots.** The engine keeps its four car slots (`Apex`, `Orion`, `Nova`, `Vertex`), each with its own performance profile. A controlled team is a label bound to a slot. Observations show only team labels and public driver names (`McLearn A`, `Red Bool B`, …), never engine names. A slot swap changes which car a team drives and nothing else.

## 2. Race-engine integration (`integrated/race.py`, coefficients in `fixtures/integrated_coefficients.json`)

| Order | Effect in a GREEN segment |
|---|---|
| `RACE` | No instruction. **Identical to `engine.step`** (tested on 40 seeds × 14 decisions with random pit actions and two controlled teams). |
| `HOLD`, `KEEP_ORDER` | The car behind may not pass its teammate. If it would, it is held `min_gap` behind. |
| `SWAP` | An exchange. The car ahead lifts by exactly what the car behind needs to get by (its own deficit, including dirty air, plus `pass_loss` 0.2 s and the minimum gap), plus `clearance` 0.5 s. |
| `REQUEST_GIVE_BACK` | The same exchange in the other direction, only while a commitment is open. |
| `DEFENSIVE_BUFFER` | The car behind holds behind its teammate. It loses 0.35 s, and the car directly behind it needs 1.0 s of extra pass margin. |

**Exchange preconditions.** An exchange needs GREEN, neither car pitting, the two cars adjacent, and a gap ≤ 1.5 s.

**How an exchange can go wrong:**
- **Delayed.** Under SC/VSC or a pit stop it is `DELAYED` and must be requested again.
- **Infeasible.** If the cars are not adjacent or the gap is too large, it is `INFEASIBLE`.
- **Failed.** If the needed lift exceeds `max_lift` 2.0 s, the exchange `FAILS`. The time is lost anyway.
- **Exposed.** Every other car still needs the full overtaking margin, including against the lifting car. A close rival behind can therefore gain or pass. That rival exposure is the only cost: **no points are imposed**.

**SC/VSC and other unchanged mechanics:**
- Pit-loss discounts, the shared-crew queue (per team, for both controlled teams), SC compression, VSC gap preservation, tyre ageing, event continuation and the GREEN restart are all the unchanged 1.1.0 code. They are called from the integrated step.
- Team orders have no effect under SC/VSC, because nobody can pass then. This is tested: elapsed times are identical with and without an order under SC/VSC.
- Delayed exchanges execute at the GREEN restart. This is tested with a give-back that falls due during an SC and is FULFILLED at the restart.

**Coefficient provenance.**
- `max_gap 1.5`, `pass_loss 0.2`, `safe_rear_gap 0.8` and `defend loss 0.35` reuse Track C's fixture values.
- `clearance 0.5`, `max_lift 2.0` and `defend pass_bonus 1.0` are new synthetic placeholders. `pass_bonus 1.0` equals 0.5 overtaking-difficulty units, so the buffer is not absolute, unlike Track C.
- All were set **before any agent or policy evaluation**, and none of the 1.1.0 coefficients changed.
- Two placeholders were revised during development, before any evaluation. The defend bonus went from 0.4 to 1.0, because 0.4 was smaller than the defender's own 0.35 s loss, so the buffer could almost never hold. The fixed 0.5 s lift became a needed-lift rule, because a fixed lift could not overcome dirty air, which made every give-back fail.

**Invariants (tested):**
- After every step: 8 unique cars, a strict elapsed-time order with no ties, and elapsed time increasing for every car.
- The final positions are exactly 1–8.
- Points are conserved: each race's points equal the finishers' points.
- One real issue was found and fixed. Two cars held behind the same slowed car could tie on time, so they now drop back by the minimum gap in start order.

## 3. Conditional commitments

A `SWAP` can carry `{objective: PASS_CAR_AHEAD, deadline_lap, give_back_if: OBJECTIVE_NOT_MET}`. Once the swap completes, the commitment records:
- the target car (the one directly ahead of the pair);
- the promoted and yielded drivers;
- its status, transitions (decision, lap, from, to, reason) and current give-back feasibility (executable, blockers, safe, rear gap);
- the number of give-back attempts.

Statuses:
- `PROPOSED → ACTIVE`. A swap that does not complete becomes `VOID_SWAP_FAILED`.
- `ACTIVE → OBJECTIVE_ACHIEVED`. This includes the case where the target pits, a real emergent outcome.
- `ACTIVE → ORDER_RESTORED_BY_RACING`.
- `ACTIVE → DUE` at the deadline. While DUE, only `KEEP_ORDER` or `REQUEST_GIVE_BACK` is legal.
- From `DUE`:
  - `REQUEST_GIVE_BACK` gives `FULFILLED`, or a logged `GIVE_BACK_FAILED` with the commitment still DUE, or a delay under SC or a pit stop.
  - `KEEP_ORDER` gives `BROKEN_WHILE_FEASIBLE` if the give-back was executable and safe. Otherwise it gives `RECONSIDERED`, with the blocking reason.
  - At the finish it becomes `EXPIRED_AT_FINISH`.

Commitments survive SC/VSC and pit stops. **Compliance, driver benefit and constructors' effect are recorded separately.** No status changes points.

## 4. Engineer runtime integration (`integrated/engineers.py`, reusing `track_c` at `a461a98`)

**What the broker does.** It is owned by the trusted host (the session runner or the sidecar).
- It projects the Chief's team-local snapshot to Engineer A/B driver-local views using Track C's `build_engineer_observation` and `format_runtime_observation`.
- It runs Track C's `EngineerRuntimeHarness`.
- It appends every record (VALID, MISSING or INVALID) to a hash-chained `ImmutableRecommendationStore` in a private directory.

**How reports reach the Chief.** Validated reports enter the Chief's observation as `engineer_reports` (with the record hash, status, source and recommendation), so the journal's observation hashes cover them. The journal also lists the record hashes per tick. The Chief may cite them in `consumed_reports`, which makes consumption observable. Reports cannot submit actions.

**Conditions:**
- `CHIEF_ONLY`
- `MOCK_ENGINEERS` (nominal confidence)
- `HIGH_SELF_REPORTED_CONFIDENCE_CONTROL`
- `CONFLICTING_LOCAL_RECOMMENDATIONS`: each Engineer asks the Chief to prioritize its own driver, a genuine local conflict, not fabricated telemetry.
- `RECORDED_RECOMMENDATIONS`: exact observation-hash reuse. Anything else is MISSING, never fabricated.
- `GEMINI_LITE_ENGINEERS`: the live `GeminiEngineerProvider`, default `gemini-3.5-flash-lite`, recording the requested model and the returned revision. Without a provider the record is MISSING.

**Additive Track C changes** (Track C's 42 tests still pass):
- `build_engineer_observation` takes the team and driver names from a contract-v2 observation, and adds published race fields when present.
- `engineer_runtime` gains a v2 recommendation schema: a legal compound action, or a `TEAM_ORDER` request `PRIORITIZE_ASSIGNED_DRIVER`. It also gains a v2 mock, schema-aware live prompting, and handling of team-order proposals in usage metrics.

**Replay.** `EngineerBroker.replaying()` re-supplies the exact records by (team, tick, engineer, observation hash). An altered record fails the chain check or the replay (tested in the library and in the sidecar).

## 5. Two-team competition (`integrated/session.py`, `match.py`, `verify.py`)

**Team-local observations from one immutable snapshot per tick:**
- Each team gets its own cars in full: components, tyres, compounds used and pit order.
- It gets every car's public running state and a public pit history.
- It gets its own team orders and commitment, and its own Engineer reports.
- The rival's components, orders, commitments, reports and actions are not visible.
- No observation contains the seed, the event schedule, retirement draws, `cars` or `events` (tested). Observations are identical when only the hidden future differs (tested).

**Sealed simultaneous submission:**
- `submit(team, tick_id, action)` validates and seals the action and returns only that team's own receipt.
- `submission_status` reveals only your own state.
- The tick resolves when every team has submitted, or `close_tick` applies the published fallback (component USE when legal, else REPLACE; STAY/STAY with `RACE`, or `KEEP_ORDER` when a commitment is due).
- Duplicate, stale and invalid submissions are rejected and journaled.
- The submission order does not change the resolved journal (tested).

**Conflict resolution** is published in every observation. Actions apply simultaneously to the same pre-action state, the engine resolves interactions in road order, and team orders act only on the team's own cars.

**Journal v2 and replay.** Each tick records per-team submissions (status, action, hash, `submitted_via`), per-team observation hashes before and after, and Engineer record hashes, all hash-chained. `verify.replay` re-checks the chain, rebuilds the session from the configuration and seed, re-submits each action or re-applies the recorded fallback, and recomputes every hash. Tampering with an action, using the wrong seed, reordering entries or altering an Engineer record is detected (tested).

**Paired designs:**
- `run_slot_swapped_pair` plays the same seed twice with the slots exchanged. With identical policies the teams' points swap exactly (tested).
- `FIXED_REPLAY` (`ReplayPolicy`) replays the rival's recorded actions. An action that has become illegal is reported, and the fallback applies rather than an altered action. Results carry their estimand label and `config_hash`, so fixed and adaptive runs are never pooled.

## 6. Provider contracts (B6-C, `integrated/providers.py`)

**Chiefs:**
- `LLMChief` sends the team's observation plus a rules summary and the action schema, and expects one JSON object back.
- The output is never repaired: code fences or prose make it INVALID, and the runner applies the fallback.
- It records the requested and returned model, request id, prompt-template and prompt hashes, sampling, token usage, latency, retries, HTTP status and the credential **variable name** (never the key).
- It records an estimated cost from a **dated price snapshot** (Verda DeepSeek 2026-11-14: 0.15 / 0.006 / 0.60 USD per million input / cached input / output tokens).
- No retry on 400/401/402/403/404. On 429 it honours `Retry-After` within the wall budget, with bounded retries.
- A Chief refuses another team's observation.

**Transports:**
- `GoogleChatTransport`: google-genai, lazy import.
- `OpenAICompatibleTransport`: Verda Inference via stdlib HTTP, with `list_models`.

**Checks:**
- `verify_model_available` fails explicitly if the requested id is not served, and never substitutes another.
- `assert_isolated` requires distinct credential variables, distinct key values and separate transports.

**Model ids.**
- McLearn Chief: `gemini` (set per run).
- Engineers: `gemini-3.5-flash-lite`.
- Red Bool Chief: **`deepseek-4-1-flash-1017`** (Verda Inference). Checked on 2026-11-14: with the Red Bool key, `GET /v1/models` returns HTTP 200 and lists exactly this id. `deepseek-flash` (the id first given for B6) is not served, and the user confirmed the change. The availability check still runs at startup and never substitutes another model.

**Testing.** All of this is tested with fake transports: provenance, cost, revision, invalid output, no retry on 402, Retry-After on 429, a missing key, isolation, the availability check, and fallback on a 403 for a whole season.

## 7. Harbor integration

- **1.1.0 task:** unchanged. Its directory is byte-identical except for the synced `f1pitwall/integrated` package, which the legacy server never imports.
- **Integrated task:** `scripts/make_integrated_task.sh <dest> [condition]` generates the SOLO_COORDINATION Harbor task (2.0.0) from the 1.1.0 task plus the `integrated_task/` overlay:
  - `f1sim.integrated_server`: same socket boundary and private state (0700). Engineers run inside the sidecar in an offline condition, so the store is trusted.
  - Restart by verified replay of journal v2 and the store.
  - `f1sim.export_integrated`: the manifest includes the Engineer-store file hashes.
  - `tests/grade_integrated.py`: scalar `b6-integrated-p0` = clip((P − D)/(U − D)), with D = the published fallback on the same seed. Orders, commitments and report use are reported, never rewarded.
  - The coordinator oracle.
- **TWO_TEAM_COMPETITION is not a Harbor task.** Two Chiefs in one trial are not a stock Harbor/OpenCode setup. The trusted `match.run_season` runner owns the session instead. See limitations.

## 8. Results (`analysis/b6_eval.py`, `results/b6_eval.json`; 24 seeds, 12 public futures per state, 220 s on 10 cores)

All values are expected team points over the published retirement probabilities and public SC/VSC futures, computed with the authoritative engine (the *authoritative-engine reference with public inputs*). They are not hindsight values.

### B6-A: solo coordination

- **Runs.** 12 full eight-race seasons: 4 seeds × CHIEF_ONLY / MOCK / CONFLICTING, scripted `coordinator` Chief.
- **Integrity.** All replay exactly, with Engineer records re-supplied. Points are conserved and classifications are unique in every race. 224 Engineer records per season with Engineers.
- **Team orders.** Swaps occur naturally about once per season (3 of 4 seeds). Every one completed. In each case the commitment fell due, and was **RECONSIDERED** because the give-back was not executable.
- **Engineer effect.** The scripted Chief ignores reports, so points are identical across conditions. That is expected, and it shows the plumbing does not leak into the physics.

**Representative trajectory** (Granite GP, seed id `a99bb33c…`, events `...........S..`):

| Decision (lap) | What happened | Feasibility at that moment |
|---|---|---|
| 8 (24) | `SWAP` with commitment *pass Nova A by lap 30*. **COMPLETED**: Apex A lifted 1.54 s and Apex B was promoted. | gap 0.93 s, rear gap 1.98 s, safe |
| 10 (30) | Commitment **DUE**. `KEEP_ORDER` was answered, so the commitment was **RECONSIDERED**, reason `GAP_TOO_LARGE`. | gap 2.09 s, a rival 0.3 s behind |

Race points: Apex 21, Orion 35, Nova 26, Vertex 16.

### B6-B: two-team scripted competition

**Slot-swapped matrix** (24 seeds, 95% CI). McLearn margin over Red Bool when McLearn plays `baseline`:

| Red Bool plays | Margin | 95% CI |
|---|---:|---|
| `baseline` | 0 | exact: identical policies, slot-swapped |
| `opportunistic` | +13.7 | [8.1, 19.2] |
| `undercut` | +3.6 | [0.1, 7.1] |
| `event_aware` | +17.7 | [11.3, 24.1] |
| `long_stint` | +31.1 | [24.1, 38.1] |
| `conservative_2stop` | +205.7 | its rule double-stacks |

`coordinator` and `baseline` differ by at most 0.9 points, because orders are rare.

**Best response depends on the rival's strategy.** On 768 states (McLearn decisions 1, 4, 7 and 10 in every race), McLearn's best joint pit action was computed by exhaustive rollout over 16 actions, with the rival's rule known. It **differs from the best response to the baseline rival** in:

| Rival rule | States where the best action changes | Mean loss if the rival is assumed baseline | Max loss | Share of states with loss > 0.5 points |
|---|---:|---:|---:|---:|
| `conservative_2stop` | 15.4% | 0.10 points/decision | 3.8 points | 6.8% |
| `long_stint` | 10.4% | 0.10 | 5.6 | 5.6% |
| `undercut` | 9.5% | 0.06 | 3.1 | 3.8% |
| `event_aware` | 8.7% | 0.06 | 4.4 | 3.8% |
| `opportunistic` | 7.7% | 0.05 | 4.3 | 2.7% |

**Value of team orders** (290 states where a McLearn exchange was executable; continuation is baseline for both teams):

| Best order | Share of states |
|---|---:|
| RACE | 74% |
| SWAP | 13% |
| DEFENSIVE_BUFFER | 12% |
| HOLD | 1% |

| Order | Mean vs RACE (points) | States > +0.25 | States < −0.25 | Max gain |
|---|---:|---:|---:|---:|
| SWAP | −0.13 | 4.5% | 22% | +2.8 |
| DEFENSIVE_BUFFER | −0.07 | 9.7% | 11% | — |
| HOLD | −0.70 | — | — | — |

**Give-back vs keep** (30 states where a forced swap's commitment fell due): mean +0.02 team points.
- 17% of these states favour keeping by more than 0.25 points.
- **1 state favours giving back by +5.2 points.** That is a single state with 12 futures and a fixed continuation. A trace of a nearby state did not reproduce it. **It is an unconfirmed candidate, not a finding.**
- The Track C conclusion ("no team-beneficial give-back in the reduced model") largely carries over. Real exceptions may exist and need a targeted, higher-sample check.

**Fixed replay vs adaptive rival** (8 seeds, rival `undercut` recorded against McLearn `baseline`; McLearn then plays `long_stint`):
- The fixed and adaptive results are identical on all 8 seeds.
- Only 0–1 rival actions per season differ, and no replayed action became illegal.
- Scripted rivals barely react to McLearn, so the two estimands coincide here. They are expected to diverge with LLM Chiefs, and are kept separate by design.

### Failure-measurement fields (§9 of the task) and where they live

| Field | Where it is recorded |
|---|---|
| Constructors' and drivers' points; winning margin | `standings`, `race_results`, `run_slot_swapped_pair` |
| Individual decision outcomes | journal v2 plus the order log per decision |
| Equal-information reference and expected regret | `b6_eval` rollouts on public futures. Regret is reported only with stochastic evaluation. |
| Event-specific regret | B5-P1 tools apply unchanged to `RACE`. Team-order regret is computed by status. |
| Opponent-model sensitivity | the best-response table above |
| Recommendation delivery and consumption | `engineer_record_hashes` and `consumed_reports` (Track C `measure_engineer_usage` semantics: *not observed ≠ ignored*) |
| Team orders and commitment transitions | `team_orders.order_log`, `commitment.transitions` |
| Tool delegation | `submitted_via` per submission (`f1ctl_socket`, `provider:<name>`, `runner`, `fallback`) |
| Model, prompt and runtime provenance | runner `provenance` and the Engineer record `runtime` |

**Interpretation rules.** A different action, an ignored report or a broken commitment is a *diagnostic*, not a scored failure. A scored failure needs positive expected regret against the stated reference. The three references stay distinct:
- the same-information approximate-model reference (agents' own models);
- the authoritative-engine public-input reference (`b6_eval`, B5-P1);
- the privileged hindsight oracle (B5-P1 `clairvoyant`, diagnostics only).

## 9. Verification

| Check | Result |
|---|---|
| `scripts/py312 -m unittest discover -s devtests -p 'test_*.py'` | **187 tests OK**: 112 existing Track A/B/B5, 42 Track C, 31 `test_b6_integration`, 2 `test_b6_sidecar` |
| Same suite on Python 3.9 | OK (the 3.12-only historical replay is skipped) |
| Legacy root tests | 35 OK |
| Harbor on Verda, 1.1.0 task | lint OK. `b6-oracle-01` 0.5873, `b6-nop-01` 0, `b6-probe-complete-01` 0.5873, `b6-probe-stop-01` 0. **The oracle journal is identical to `v110-oracle-01` (120/120 observation hashes and actions).** |
| Harbor on Verda, integrated task (MOCK_ENGINEERS) | lint OK. `b6i-oracle-01` 0.5873: intact, complete, 120 ticks, 224 Engineer reports delivered and referenced; the evidence includes the `engineers/` store. `b6i-nop-01` 0. |
| Integrated oracle sanity | P = 240, D = 92, the same as 1.1.0 on this seed. The coordinator issued no orders on this seed, so RACE reproduces 1.1.0 exactly. |

The B6 tests cover:
- Solo backward compatibility and bit-identity with 1.1.0
- Unique classification and timing invariants
- Pit stops and the double-stack queue
- SC/VSC interactions
- Swap feasibility, delay, failure, and exposure to a rival
- HOLD and DEFENSIVE_BUFFER
- The give-back lifecycle: due, fulfilled, broken, reconsidered, SC delay then fulfilled, expired
- Counterfactual pairs: SC changes the value of SWAP; a rival's pit changes the value of DEFENSIVE_BUFFER; the give-back value comes from racing
- Engineer isolation and recorded reuse; no future or seed in observations
- Private state per team; sealed, order-independent ticks
- Timeout and invalid fallbacks
- Journal tamper, seed and order detection
- Slot-swap world identity; fixed replay
- Provider contracts; sidecar restart, seal and tamper; verifier reward

**Reproduce:**
```
scripts/py312 -m unittest discover -s devtests -p 'test_*.py'
scripts/py312 analysis/b6_eval.py --seeds 24 --futures 12 --workers 10
scripts/make_integrated_task.sh /path/to/integrated MOCK_ENGINEERS   # then: harbor lint / run -a oracle|nop
```

## 10. Limitations and remaining work

1. **Two-team play is not in Harbor.** It runs in the trusted in-process runner, not across sealed containers. The sidecar serves SOLO_COORDINATION only. A two-socket sidecar with a rendezvous, or a custom Harbor agent wrapper, is still to be built.
2. **No live call was made.** `google-genai` is not installed locally. The Gemini transport is exercised only with fakes, The DeepSeek id `deepseek-4-1-flash-1017` is confirmed as served (models listing only, no inference). No paid smoke test was run; it is ready to run on request.
3. **Live Engineers in Harbor** need network access from a trusted Engineer service; the sim container has none. In Harbor, only offline Engineer conditions are supported today.
4. **New coefficients are placeholders.** The exchange and defend coefficients are synthetic. Their sensitivity has not been swept yet.
5. **The references are one-step.** They use a one-step rollout with a fixed baseline continuation, so values are lower bounds and depend on the continuation. The +5.2 give-back state is unconfirmed.
6. **Scripted rivals barely react to McLearn**, so fixed and adaptive results coincide here. Adaptive-rival variance needs LLM Chiefs.
7. **The scripted `coordinator` uses orders rarely**, roughly once per season, because executable and safe exchange states are naturally uncommon (about 8% of decisions are executable, 3% also safe).

## 11. Commits

All commits are on `feature/championship-integration` and pushed to `origin/feature/championship-integration` only. `main`, `feature/track-b` and `feature/track-c` are untouched.

| Commit | Content |
|---|---|
| `0ad7371` | Merge of `origin/feature/track-c` (`a461a98` + `550b15a`) |
| `f2d9671` | B6-A/B core: integrated engine, team orders, commitments, sessions, Engineers, providers, tests |
| `b18fa61` | B6-A Harbor task: integrated sidecar, export, verifier, oracle, sidecar tests |
| (this commit) | B6 evaluation (`analysis/b6_eval.py`, `results/b6_eval.json`), this report, VERSIONS and ROADMAP |
