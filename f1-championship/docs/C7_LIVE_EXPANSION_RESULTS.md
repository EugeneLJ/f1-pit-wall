# C7 live paired-probe results (adaptive expansion, seeds 404–413)

**Diagnostic only.** This is not part of the official Frontier–Reference gap
(`official_frontier_reference_gap: false`). It uses benchmark 2.0.1 two-team states outside Harbor.
No engine, reward, observation contract, classifier or threshold was changed.

## What ran

| Item | Value |
|---|---|
| Selection | `analysis/results/c7/live_selection_expansion.json`, all 8 preregistered expansion candidates in file order (3 reversal, 3 no-change control, 2 near tie), frozen before any call |
| Source | `analysis/results/c7/adaptive_expansion_candidates.json`, sha256 `061794dd…1f31` (checked by the evaluator) |
| Model | `gemini-3.8-flash` requested, `gemini-3.8-flash` returned on all 16 calls |
| Sampling | temperature 0.0, max_output_tokens 8192, identical across all conditions |
| Calls | 16 of the 16 allowed (smoke pair 2 calls included), 16 valid legal actions, 0 retries needed |
| Tokens | 29,062 input, 895 output, 21,895 thinking |
| Estimated cost | USD 0.107 (2026-11-14 price snapshot) |
| Latency | mean 14.1 s, p95 30.6 s |

Raw records with prompt and response hashes: `analysis/results/c7/live_records_expansion.jsonl`
(secret scan clean). Evaluation: `analysis/results/c7/live_evaluation_expansion.json`.

## Results (unchanged C6 classifier)

| Pair | Reference class | Ref. action a → b | Gemini a → b | Regret a / b | Classification |
|---|---|---|---|---|---|
| s409-r2-d4 | reversal | PIT_HARD/STAY → STAY/STAY | STAY/STAY → STAY/STAY | 1.92 / 0 | FAILURE_TO_ADAPT |
| s409-r0-d9 | reversal | STAY/STAY → PIT_MEDIUM/STAY | STAY/STAY → STAY/STAY | 0 / 1.48 | FAILURE_TO_ADAPT |
| s407-r2-d8 | reversal | STAY/PIT_HARD → STAY/STAY | STAY/STAY → STAY/STAY | 3.90 / 0 | FAILURE_TO_ADAPT |
| s404-r4-d8 | control | PIT_HARD/STAY (both) | STAY/STAY (both) | 4.12 / 3.40 | INCONCLUSIVE* |
| s410-r3-d12 | control | STAY/STAY (both) | STAY/STAY (both) | 0 / 0 | NO_ADAPTATION_NEEDED |
| s406-r6-d6 | control | STAY/STAY (both) | STAY/STAY (both) | 0 / 0 | NO_ADAPTATION_NEEDED |
| s413-r4-d8 | near tie | PIT_HARD/STAY (both) | PIT_HARD/STAY → STAY/STAY | 0 / 2.40 | NEAR_TIE |
| s408-r3-d7 | near tie | STAY/STAY (both) | STAY/STAY (both) | 0 / 0 | NEAR_TIE |

Regret is the C6 point-estimate expected-team-points difference; it has no CI of its own.
\*The C6 classifier has no label for "stable reference, Chief wrong in both conditions", so this
pair falls through to INCONCLUSIVE. The classifier was left unchanged as preregistered.

## Reading

- **3 of 3 separated reversals were not followed.** In every reversal pair Gemini chose the same
  action in both conditions.
- **This is not evidence of a rival-specific adaptation failure.** Gemini chose STAY/STAY in
  15 of 16 calls. Its single pit (s413, condition a) is in a near-tie pair. In every reversal it
  stayed in both conditions, so it was "right" in exactly the condition where the reference also
  stays. The control s404 shows the same pattern with no rival change at all: the reference pits
  in both conditions, Gemini stays in both. The probes therefore cannot tell "ignores the rival's
  change" apart from a general reluctance to pit. That reluctance matches the missed-stop failures
  in the three live 2.1.0 Harbor runs (`docs/REFERENCE_2_1_0_REPORT.md`).
- With 3 reversal pairs, one model, temperature 0 and one call per condition, this result is
  descriptive. No significance or generality claim is made. The preregistration does not allow
  more seeds or calls, so the adaptive-rival live pilot stops here.

## Caveats

- The reference has a model-access advantage (it executes the authoritative engine on public
  inputs); its preferences on the reversal pairs are separated under four common futures only.
- Prompts are the C7 single-decision probe prompts, not a full Harbor season, so the live Chief
  lacks the season history it would have in a real run.
- Selection was independent of model output. No result was used to change any rule or threshold.
