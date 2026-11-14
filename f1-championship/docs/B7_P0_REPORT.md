# B7-P0 report — Live McLearn vs Red Bool pilot

> **Benchmark version: integrated 2.0.1.** It differs from 2.0.0 only in the action-schema wording (§1). 1.1.0, 2.0.0 and all earlier results are untouched.
>
> **Scope:** two seasons, one per layer, on the same seed and slots. **This is a pilot. Nothing here says which model is stronger.** One season per condition, fixed car slots, and the two trajectories diverge from tick t003 onwards.

**Branch and data.** Branch `feature/championship-integration`. The runs were made on Verda on 2026-11-15. Raw data is in `analysis/results/b7/` (frozen; see §9).

## 1. Setup, live-integration fixes and contract parity

**Models.** All three were verified by free model listings and logged with the returned model on every call. Nothing was substituted.

| Role | Model | Returned model |
|---|---|---|
| McLearn Chief | `gemini-3.8-flash` | `gemini-3.8-flash` (120/120 in each layer) |
| McLearn Engineer A/B (Layer 2) | `gemini-3.5-flash-lite` | — |
| Red Bool Chief | `deepseek-4-1-flash-1017` (Verda) | `deepseek-4-1-flash-1017` (120/120) |

**Fixed settings, identical for both Chiefs:**
- prompt template `chief-v1`, sha256 `e7f0abc8ad35…`, which is the same in all 480 Chief calls;
- temperature 0.0, `max_output_tokens` 8192, timeout 120 s, at most 1 retry (429/5xx/network);
- no tools, direct API.

**Seed and slots.** Seed 20261115 (fresh; seed id `da8723e6b2d39810`). McLearn is in slot Apex and Red Bool in slot Orion.

**Cost ceiling.** USD 5 per layer, charged at a conservative price ceiling (Gemini 3.8 Flash at the 2027 standard price of 1.50/7.50 per M tokens). Neither layer came close.

**Live-integration gap found and fixed (benchmark 2.0.1).** In the first probe on 2.0.0, the Gemini Chief misread our `action_schema` text. It sent component decisions as a dict, and it nested `consumed_reports` under the literal `optional` key we had published. Direct-API Chiefs never see `instruction.md`'s examples. 2.0.1 states the list format and the top-level field, and adds one format example per phase, identical for both teams.
- Mechanics, legal actions and scoring are unchanged.
- The re-probe was legal for both Chiefs in both phases. All four Engineer A/B reports were VALID, with observation hashes matching (the `dc76415` fix works live).
- Both probe files are kept: `probe_v2.0.0.json`, about USD 0.015, and `probe.json`, about USD 0.016.

**Contract parity, checked in every observation:**
- all 480 team observations are 2.0.1;
- there are exactly two action-schema shapes (component and race), shared by both teams;
- each carries the format example;
- both Chiefs used the same prompt template.

## 2. Layer 1 — Head-to-head (no Engineers)

**Integrity.** Complete (8 races, 120 ticks). Journal v2 replays exactly: every team observation hash and the standings match, and there are no rejected entries. C4 `verify_bundle` reports VERIFIED.

| | McLearn (Gemini) | Red Bool (DeepSeek) |
|---|---:|---:|
| Constructors' points | **304** | 143 |
| Drivers | A 171 / B 133 | A 115 / B 28 |
| Margin | +161 | |
| Pit stops (compounds) | 27 (HARD 19, MEDIUM 8) | 39 (SOFT 18, HARD 14, MEDIUM 7) |
| Double stacks | 0 | 11 |
| Stops in the 8 SC/VSC decisions | 6 | 10 |
| Team orders | HOLD ×5, SWAP ×2 (both COMPLETED) | HOLD ×6 |
| Commitments | none created | none |

Per race (McLearn–Red Bool), with the events of each race:

| Race | Events | McLearn | Red Bool |
|---|---|---:|---:|
| 1 | `..............` | 30 | 29 |
| 2 | — | 40 | 22 |
| 3 | `.V.......VV...` | 40 | 10 |
| 4 | — | 40 | 14 |
| 5 | — | 28 | 29 |
| 6 | `........VV....` | 43 | 10 |
| 7 | `..V......VV...` | 40 | 10 |
| 8 | — | 43 | 19 |

## 3. Layer 2 — Coordination (McLearn Chief + Gemini Lite Engineer A/B)

**Integrity.** Same seed and slots as Layer 1. Complete and exact replay, with the Engineer records re-supplied from their hash chain. C4 reports VERIFIED.

**Divergence.** The trajectories diverge at **t003** (race 1, decision 2):
- Layer 1: McLearn `STAY/STAY`.
- Layer 2: McLearn `PIT_MEDIUM/STAY`; Engineer A had proposed `PIT_MEDIUM`.

Everything after t003 is a different state, so Layer 1 vs Layer 2 differences are **not** a paired per-decision effect.

| | McLearn | Red Bool |
|---|---:|---:|
| Constructors' points | **237** | 175 |
| Margin | +62 | |
| Change vs Layer 1 | −67 | +32 |
| Pit stops | 33 (MEDIUM 16, HARD 17) | 41 (SOFT 19, HARD 14, MEDIUM 8) |
| Double stacks | 0 | 10 |
| Team orders | HOLD ×5, SWAP ×1 (COMPLETED) | HOLD ×5 |

The Red Bool rival adapted naturally: it is the same model and prompt as in Layer 1, facing a different McLearn.

**Interpretation limit.** That McLearn scored 67 points fewer with Engineers is a **single-season, divergent-trajectory** observation. It is not an Engineer effect estimate. It needs matched seeds and slot-swapped pairs.

## 4. Engineers (Layer 2)

| | Engineer A | Engineer B |
|---|---:|---:|
| Records | 112 | 112 |
| VALID | 108 | 111 |
| INVALID | 4 (evidence did not quote an existing field exactly) | 1 (illegal proposed action) |

- **Invalid reports.** These are recorded as Engineer API failures and **never repaired**. They were delivered to the Chief as INVALID.
- **Proposals:** STAY 93, PIT_MEDIUM 51, PIT_SOFT 39, PIT_HARD 36. No team-order requests.
- **Confidence:** self-reported values 0.75–0.95, not calibrated.
- **Delivery and consumption.** All records were delivered. The Chief cited reports (`consumed_reports`) in **108 of 112** race decisions: 84 of A's reports and 96 of B's.
- **Agreement.** The Chief's pit choice for the driver matched the Engineer's proposal 56 / 108 times for A and 67 / 111 times for B. Disagreement is **not** treated as a failure.
- **Information value (C4).** All 591 cited evidence items are `PUBLIC_ALREADY_AVAILABLE_HIGHLIGHTED`. The Engineers saw nothing the Chief did not already have, so any effect is from emphasis or recommendation, not new information.
- **Regret, descriptive only.** McLearn's mean regret per decision is 0.60 points when its action differed from at least one Engineer (77 decisions) and 1.03 when it agreed with both (35). For the whole layer it is 0.74, against 0.46 in Layer 1, on different trajectories.

## 5. Candidate strategic failures

**Reference: authoritative-engine public-input rollouts (it has a model-access advantage: it executes the exact engine).**
- Every joint pit action is evaluated, plus the Chief's own action.
- 12 public SC/VSC futures are drawn from the published model, conditioned on the observed history.
- Afterwards both teams continue with the published baseline rule, and the rival's same-tick action is also the baseline rule.
- A **candidate** needs regret > 1.0 point and > 2 SE.
- **C4** additionally requires a regret-CI lower bound above 1.0 point plus concrete evidence for a named hypothesis.

Candidates are hypotheses about decision quality, **not confirmed causal mechanisms**.

| | Layer 1 candidates | Layer 1 C4-confirmed | Layer 2 candidates | Layer 2 C4-confirmed |
|---|---:|---:|---:|---:|
| McLearn | 13 (mean regret/decision 0.46) | 3 adapt-to-SC/VSC-or-rival | 18 (0.74) | 10 excessive reliance on Engineer, 5 adapt, 1 unjustified rejection (labels overlap) |
| Red Bool | 23 (1.44) | 6 adapt | 18 (1.19) | 9 adapt |

All candidates have a replay-reproduced observation; full replays are exact. Per decision, `analysis.json` records the observation, legal actions and team orders, the chosen action, the reference action, the regret ± SE, and context tags (event, double stack, team-order context, rival within 2 s, Engineer disagreement, fallback). The tags are context, not causes.

### Red Bool's VSC double stacks onto SOFT (`deep.json`)

**Recurrence.** Layer 1: 5 times in 3 races. Layer 2: 4 times. Separately, Red Bool double-stacked onto HARD 6 times (Layer 1) and 5 times (Layer 2) under GREEN.

**Robustness.** For each of the 5 Layer 1 VSC cases, all 16 pit/compound combinations were evaluated under:
- 3 future-event assumptions: the published model with 24 futures, "VSC ends now", and "continues one more segment";
- 4 rival-continuation assumptions: baseline, `event_aware`, `long_stint`, `opportunistic`.

**Result.** In all 5 × 12 combinations the chosen action ranks **12th–16th of 16**, with **regret ≥ 4.5 points**. Under the published model the regret is 7.3–11.4 points with SE ≤ 1.4. Usually STAY/STAY, or a single HARD stop, is best.

**Mechanism (one-segment decomposition):**
- A VSC stop still costs 10.5–12.1 s (55% of the GREEN loss), plus a 6 s shared-crew queue for the second car.
- SOFT (10-lap life) was fitted with 15–39 laps left, so another stop is forced. Several stops came on tyres only 6–9 laps old.
- Positions are lost immediately: for example P1 and P3 became P7 and P8 in one segment.

**McLearn's zero double stacks: selective, not over-restrictive.**
- A double stack was never the reference-best action for McLearn (0 / 112 in each layer).
- It was clearly better than McLearn's choice in only 1 / 112 decisions per layer.
- For Red Bool, a double stack was reference-best 3 times per layer, and its own double stacks had positive regret 10 / 11 (Layer 1) and 8 / 10 (Layer 2).
- So Red Bool's problem is **which** double stacks it chooses, not double-stacking itself. This is consistent with B5-P1: a double stack under SC/VSC can be optimal.

## 6. Team orders and commitments

- **Gemini (Layer 1): HOLD ×5, SWAP ×2.**
  - All five HOLDs were applied with the teammates not contesting position; value vs the same pit action with RACE is 0.0.
  - SWAP at race 4, lap 15: COMPLETED, value −1.92 ± 0.39 points vs RACE. It is a candidate. The exchange cost time and the promoted car did not gain.
  - SWAP at race 6, lap 39: COMPLETED, value 0.0.
- **Gemini (Layer 2):** HOLD ×5 (value 0.0) and SWAP ×1 at race 8, lap 39 (COMPLETED, value 0.0).
- **DeepSeek:** HOLD ×6 (Layer 1) and ×5 (Layer 2), all value 0.0. Most were issued when the teammates were not adjacent or the gap was too large (`NOT_ADJACENT`, `GAP_TOO_LARGE`), so they had no effect.
- **Commitments:** **no Chief created a commitment in either layer.** Fulfilment, reconsideration and give-back could not be observed in this pilot. This is a coverage gap, not a result.

## 7. Operational metrics (separate from strategy)

| | L1 McLearn | L1 Red Bool | L2 McLearn | L2 Red Bool | L2 Engineers A/B |
|---|---:|---:|---:|---:|---:|
| Calls | 120 | 120 | 120 | 120 | 112 / 112 |
| Invalid output (fallback applied) | 0 | 0 | 0 | **1** | 4 / 1 invalid reports |
| Retries / timeouts | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| Latency mean / p95 / max (s) | 12.8 / 26.9 / 43.8 | 0.55 / 1.2 / 4.2 | 15.6 / 36.3 / 63.6 | 3.7 / 4.9 / 7.9 | — |
| Input / output / thinking tokens | 432k / 8.1k / 156k | 421k / 5.2k / 0 | 536k / 19.7k / 197k | 422k / 5.1k / 0 | 115k+118k in / 49k+50k out |
| Estimated cost (USD) | 0.94 | 0.04 | 1.21 | 0.04 | ≈0.32 |
| Wall time | 26.7 min | | 38.5 min | | |

**Total pilot cost:** about **USD 2.58**, including the probes (about USD 0.03). These are estimates from dated price snapshots; the provider billing pages are authoritative. Tool or script delegation does not apply, because these are direct-API Chiefs with no tools (`submitted_via=provider:*`).

## 8. Harbor and security limitations

- **Not in Harbor.** Both seasons ran in the trusted host runner (`integrated.match`) on Verda, not in sealed Harbor containers. Harbor supports only the 1.1.0 task and the SOLO_COORDINATION task, which has offline Engineers only.
- **Credentials.** Keys were read only from `/root/.config/f1-pit-wall.env` (0600) into the runner process. No key appears in any output (scanned).
- **Engineer store.** The Engineer record store lives in the run directory on the host; it is trusted ownership, but it is not container-isolated.

## 9. Frozen artifacts and integrity

| Layer | `journal.jsonl` sha256 | Journal head hash |
|---|---|---|
| Layer 1 | `e8391273222b8a97aad10530d298ba3a7c95a10a35fc616517f7b0b8eb9d1ea7` | `4695e2db70a8bd9cf5c52c809a6b8d7dab8f289f9d66c135877734334732e47a` |
| Layer 2 | `a060baca4bcc28a13b56d050289a146852723b99b9f05b85b72a994001befa06` | `5a5251c36d8a1dc911d8c251aaf0a77c81b58a0f23d59dd935339c2e4350b9d5` |

**Files** (`analysis/results/b7/`):
- `layer1/`, `layer2/`: `summary.json`, `journal.jsonl`, `ticks.jsonl`, `analysis.json`, `c4_bundle.json`; Layer 2 also has `engineers/`;
- `deep.json`, `c4_report.json`, `models.json`, `probe*.json`.

**Reproduce (no model calls):**
```
scripts/py312 analysis/b7_analysis.py analysis/results/b7/layer1 --futures 12
scripts/py312 analysis/b7_analysis.py analysis/results/b7/layer2 --futures 12
scripts/py312 analysis/b7_deep.py analysis/results/b7 --futures 24
scripts/py312 analysis/b7_c4.py analysis/results/b7
```

**Live runs (paid; on Verda):** `analysis/b7_pilot.py --verify|--probe|--layer 1|--layer 2`.

## 10. What not to conclude, and next steps

**Do not conclude:**
- any model ranking (one season, fixed slots, divergent trajectories);
- an Engineer effect (−67 is not an estimate);
- a commitment behaviour (none was created).

**Next (each needs a separate decision):**
- same-seed slot-swapped pairs over several seeds;
- a FIXED_REPLAY condition to isolate the Engineer effect against a recorded rival;
- an Engineer `RECORDED_RECOMMENDATIONS` ablation.
