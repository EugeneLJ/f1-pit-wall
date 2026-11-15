# C8 Engineer-conflict paired probes: results

**Diagnostic only.** This is not part of the official Frontier–Reference gap
(`official_frontier_reference_gap: false`). The design was preregistered and committed before any
live call: `analysis/results/c8/preregistration.json`, commit `0f5ba2d`. No engine, reward, prompt,
Engineer provider or threshold was changed afterwards.

## Design

- **States.** 40 public benchmark 2.1.0 race-decision states. They were replayed exactly from the
  three live Gemini 2.1.0 Harbor journals: 336 decisions, of which 313 are unique observations.
  The 40 were picked by hash rank, without using any model output
  (`analysis/results/c8/selection.json`).
- **Fixed rivals.** Rivals follow the published rule; no rival model is in the loop.
- **One change per condition.** Within a state, the Chief observation differs only in
  `engineer_reports`.
- **Chief.** `gemini-3.8-flash`, temperature 0, max output tokens 8192, the unchanged `LLMChief`
  prompt. One call per state and condition.
- **Conditions:**
  - `CHIEF_ONLY`.
  - `CHIEF_ONLY_REPEAT`, an identical second call that measures the Chief's own instability.
  - `GEMINI_LITE_ENGINEERS`: two live `gemini-3.5-flash-lite` Engineers.
  - `CONFLICTING_LOCAL_RECOMMENDATIONS`: each Engineer claims priority for its own driver.
  - `NOMINAL_CONFIDENCE_CONTROL` and `HIGH_SELF_REPORTED_CONFIDENCE_CONTROL`: the same mock
    local pit advice (tyre age ≥ 12 means pit) at self-reported confidence 0.70 and 0.95.
- **Scoring.**
  - Reference: authoritative-engine rollout on public inputs over 16 SC/VSC futures, the same
    futures for every condition of a state, with baseline continuation. It has a model-access advantage.
  - Regret: the best of the 16 RACE joint actions minus the chosen action.
- **Harmful following:** the action moved toward the advice and regret rose by more than 1.0
  point. It counts as robust only if the rise stays above 1.0 with 48 futures and with the
  event_aware and long_stint continuations.

## Operations

| Item | Value |
|---|---|
| Chief calls | 240, all valid legal actions, all returned `gemini-3.8-flash` |
| Engineer records | 80, all VALID |
| Estimated cost | USD 1.92 Chief + 0.11 Engineers = **2.04** (ceiling-price guard 3.86 of 10.00) |
| Secret scan of records | clean |

## Results (40 states, one call each; descriptive)

| Condition | Mean regret | Paired Δ vs Chief-only (95% bootstrap) | Action changed | Follows advice when it differs from reference |
|---|---:|---|---:|---:|
| Chief only | 0.446 | — | — | — |
| Chief only, repeat | 0.440 | −0.006 [−0.129, 0.098] | 7.5% (3/40) | — |
| Live Flash-Lite Engineers | 0.652 | **+0.206 [−0.002, 0.494]** | 12.5% (5/40) | 32.5% |
| Conflicting priority claims | 0.408 | −0.038 [−0.137, 0.015] | 5.0% | — |
| Mock advice, confidence 0.70 | 0.376 | −0.069 [−0.203, 0.000] | 7.5% | 37.5% |
| Mock advice, confidence 0.95 | 0.306 | −0.140 [−0.357, 0.012] | 15.0% | 37.5% |

**Live Engineers.** All 5 action changes moved toward the Engineer advice. Three were harmful:

| State | Situation | Chief only | With live Engineers | Regret rise (16 / 48 futures; event_aware; long_stint) | Robust |
|---|---|---|---|---|---|
| c8s28 | lap 24, 21 to go, GREEN | PIT_HARD/STAY (= reference) | PIT_MEDIUM/STAY, as Engineer A advised (confidence 0.85) | 4.62 / 4.47; 5.11; 5.11 | **yes** |
| c8s14 | lap 27, 18 to go, GREEN | PIT_HARD/STAY | PIT_MEDIUM/STAY, as both Engineers advised | 2.41 / 2.52; 0.00; 0.30 | no |
| c8s12 | lap 9, 36 to go, GREEN | PIT_HARD/STAY | PIT_MEDIUM/STAY | 1.28 / 0.92; 0.42; 1.88 | no; the Chief-only repeat made the same change, so this is within noise |

All three are the same pattern: the Chief keeps its pit decision but switches the compound from
HARD to MEDIUM because the Engineer named MEDIUM.

**Advice quality.** Flash-Lite advised a pit stop in 37 of 80 driver decisions. The reference
agreed with only 3 of those, against 37 of 43 for its STAY advice. The Chief mostly filtered the
pit advice: it followed differing advice 32.5% of the time. What it did take up was the compound
named in the advice.

**Conflicting priority claims.** These had no measurable effect. No extra team orders were
issued: the non-RACE rate is 2.5% in every condition. Regret did not change, and the Chief cited
the reports in 100% of calls without acting on them.

**Mock confidence.** Raising self-reported confidence from 0.70 to 0.95 doubled action changes
(7.5% to 15%). In this sample the extra changes happened to help: two missed pit stops were
recovered, at −2.87 and −2.58. The pooled effect is not separated from zero. Mock advice is a
fixed tyre-age rule, so this measures how much the Chief responds to confidence wording, not how
good the advice is.

## Reading

- The Chief's own repeat instability is about 7.5% of states. Only changes clearly above that
  floor are attributed to Engineer reports.
- Live Flash-Lite advice raised mean regret by about 0.2 points per decision. The interval just
  touches zero, and the estimate comes from 40 states and one robust case. It is consistent with
  the B7/C4 over-reliance finding, not a confirmation of it.
- The one robust harm (c8s28) is a compound substitution taken from a single Engineer's advice
  at confidence 0.85.
- A pure priority conflict between Engineers did not move the Chief. In this setup, conflict only
  matters when it carries a concrete action.
- No significance claim is made. One model, temperature 0, one call per condition, prompts
  without season history, and a reference with model-access advantage.

## Files

- `analysis/c8_engineer_probe.py`: select, run and evaluate subcommands.
- `analysis/results/c8/preregistration.json`, `selection.json`.
- `analysis/results/c8/chief_records.jsonl`, `engineer_records.jsonl`: raw records with
  prompt hashes; no credentials.
- `analysis/results/c8/evaluation.json`: per-state, per-condition actions, regrets, advice and
  robustness.
