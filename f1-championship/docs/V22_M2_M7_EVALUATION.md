# M2/M7 reproducible evaluation report

Branch base: scenario contract `4dc5d4b`. Work is isolated under `track_c/v22`,
fixtures, analysis, devtests, and documentation. **No API/model/Harbor calls, no
paid cost, no C5 merge, and no official 2.2.0 activation.**

## What was built

- **M2:** independently keyed per-race `DEFENDER`/`OPPORTUNIST`/`CONSERVATIVE`
  assignments; literal legal reaction table; observable lap/reaction evidence;
  joint-likelihood public posterior; posterior-mixture legal-value evaluation with
  explicit near-tie and uncertainty classes. Actual assignments, seeds, draws and
  policy identifiers are absent from projections.
- **M7:** hidden seeded DRY/DAMP/WET Markov weather with continuous wetness;
  causal Dirichlet forecast reports; five tyre compounds with published crossover
  curves, wear, warmup, spin and retirement; legal action checks; early/on-time/late
  rival switching; an eight-boundary two-car micro-race with exact replay and wet-use
  exemption. Neutralisation is limited to a hazard-simplex adapter.
- **Configuration:** `V22Config(m2_enabled=False, m7_enabled=False)` default-off,
  plus `disabled_m2_projection()` and guarded public projections.
- **Evidence:** unit/replay/leakage tests, bounded seeded generation and a resume
  check. Full integration details and unresolved gaps are in
  [V22_M2_M7_INTEGRATION.md](V22_M2_M7_INTEGRATION.md).

## Exact bounded execution

From `f1-championship`, using the isolated Python 3.12.12 binary:

```bash
PYTHONPATH=src:. PYTHONDONTWRITEBYTECODE=1 \
/tmp/opencode/python-3.12.12/python/bin/python3.12 \
  analysis/v22_m2_m7_eval.py --phase smoke \
  --output analysis/results/v22/smoke.json

PYTHONPATH=src:. PYTHONDONTWRITEBYTECODE=1 \
/tmp/opencode/python-3.12.12/python/bin/python3.12 \
  analysis/v22_m2_m7_eval.py --phase dev \
  --output analysis/results/v22/development.json

# Valid resume of an unchanged complete artifact (no recompute/overwrite).
PYTHONPATH=src:. PYTHONDONTWRITEBYTECODE=1 \
/tmp/opencode/python-3.12.12/python/bin/python3.12 \
  analysis/v22_m2_m7_eval.py --phase smoke \
  --output analysis/results/v22/smoke.json --resume

# Tests shown after the final code/test changes.
PYTHONPATH=src:. PYTHONDONTWRITEBYTECODE=1 \
/tmp/opencode/python-3.12.12/python/bin/python3.12 \
  -m unittest discover -s devtests -p 'test_v22_*.py' -v
```

No additional seed was chosen for a preferred result. Temporary failures during
implementation (final-horizon reference valuation and a harness race-ID mismatch)
were fixed before these artifacts. No partial failed artifact was promoted.

Inputs are the two public fixture files, not actual future rivals/weather:

| Artifact | SHA-256 |
|---|---|
| `track_c/fixtures/v22_m2.json` | `3f2bb4f6df1eddbce3fa611f879988a783062f371a866c32dfcd10bd120cc4a3` |
| `track_c/fixtures/v22_m7.json` | `af671dfa920d41064aa5336947ab8f1d90b779b85c316097a615565dabea7706` |

## Smoke and development results

| Phase | Preregistered seeds | Generation seconds | Output SHA-256 |
|---|---|---:|---|
| Smoke (two) | 11, 12 | 0.020759 | `65ac179e8fab00527e1faa3b939a98e6afd39193a4acc5048439d6809a75725e` |
| Development (five) | 101, 102, 103, 104, 105 | 0.051908 | `1e56b1742ef7dd36526b7654f2ae1ac1f66717503902169ad8ce4cb95aefe666` |

Canonical row-list hashes are
`c44580ca76367c3efb8f0ddac298b30719669bb97f119bdb88d8501421b87f99`
and `e3ee92e3202e523113b00b7ae35bd8c0ab59ed7d659525cd1fc1fa983c1165e5`.
Pre-fix artifacts are preserved under `analysis/results/v22/archive/` and are not
valid current evidence. The corrected M2 sensor consumes the published observation
confusion model; no coefficient or seed changed.
Generation times exclude interpreter startup/imports; source files include exact
per-seed durations too, and therefore are not reproduction hash targets.

| Measure | Smoke 11,12 | Development 101–105 |
|---|---:|---:|
| M2 public-value `NEAR_TIE` | 1 | 4 |
| M2 public-value `UNCERTAIN` | 1 | 1 |
| M2 confirmed/separated action reversal | **0** | **0** |
| M7 public-value separated rows | 15/16 | 39/40 |
| M7 near-tie rows | 1/16 | 1/40 |
| M7 pit actions | 1 | 3 |
| Replay failures | **0** | **0** |
| Model calls / matched model runs / official gap | **0 / 0 / none** | **0 / 0 / none** |

The M7 separated rows are the reduced public **seconds/cost heuristic** graded
against its synthetic near-tie threshold; they are not model performance or an
official F1-point/reference gap. High separation is not presented as universal
strategic difficulty. Bounded M2 development values mainly remain near ties, exactly
where the evaluator must not upgrade a point-estimate change to a confirmed reversal.

### Distinguishing natural and synthetic evidence

- "Naturally seeded" means a predeclared seed generated a Markov/customer path, not
  a natural F1 event. M2 public posterior and M7 forecasts remain partial evidence.
- The M2 flip case in unit tests intentionally supplies type-dominant public legal
  values, demonstrating decision-value sensitivity instead of mere behavior
  changes. These explicit synthetic values are not authoritative engine outcomes.
- M7 forced-DRY/WET pairs change only the observed process/forecast input consumed
  by `action_values`; duplicate observations are controls. A final-boundary control
  uses current condition because no next forecast exists.
- Real-time incident actions alter micro-race outcomes: stopping can change fitted
  compound, elapsed time, tyre age and weather incident realization. Underlying rain
  and incident keys stay fixed across action branches.

## Unit/replay/secrecy tests

`devtests/test_v22_m2.py`, `test_v22_m7.py`, and `test_v22_evaluation.py` cover:

- exact per-race type draws/replays, baseline reaction priorities and equality;
- joint Bayes history, prefix behavior, duplicate evidence, no private assignments;
- actual type-dependent public behavior plus changing legal-value optima;
- near-tie-first, uncertainty reversals muted, no-change controls and illegal values;
- weather exact replay/action independence, wetness bounds, forecast reproducibility
  and report variance shrinkage over 400 independent keys per concentration;
- no hidden schedule/bias/path/seed in observations, including altered future input;
- dry coefficient identity nodes, tyre crossovers, legal all-weather compounds,
  incidents and wet-use rules using actually raced compounds only;
- paired forecast-versus-control choices, last-horizon legality, early/late rival
  switches, whole-replay exactness, pit versus stay outcomes and finish penalties;
- preregistered seed/output counts, zero replay failures, source hashes, aggregate
  recomputation and a non-mutating resume path.

Final totals: **25 targeted tests OK (0.148s)**, **259 development tests OK
(102.659s)**, and **35 legacy tests OK (1.807s)**. No final test failed. No result is
inferred from the original C6/C7 or live Gemini reports.

## Limitations and unresolved items

1. M2's full S1 value needs M1/M3, which are deliberately not implemented. Its
   genuine engine outcomes require owner-resolved defence/attack, proximity and legal
   action values; partial behavior evidence alone is insufficient difficulty proof.
2. Forecasts are explicitly noisy Dirichlet reports whose concentration grows with
   lead. They are not declared calibrated true-weather posteriors. An owner choosing
   a sampling reference must state its conditioning/rollout model.
3. Exact hidden wetness remains private; public state includes observed conditions,
   probabilistic reports, lap/action facts and fitted/current tyres only.
4. The contract's DQ/30-second clause conflicts with the documented normal-finish
   +20-second two-dry rule. The micro-race preserves the +20 behavior and adds only
   wet exemption. No suspension/red-flag or invented 30-second model exists.
5. Coefficients and scenario values are synthetic; no Gemini behavior is targeted or
   tuned. No reward, official reference policy, verifier, official engine override,
   M1/M3/M4/M5/M6, or C5 mechanic is included.
6. This study is a mechanics/replay check and bounded frequency report, not proof of
   a Frontier–Reference gap. Such a claim requires actual matched model runs,
   common undisclosed futures, uncertainty estimates and an official versioned task.
