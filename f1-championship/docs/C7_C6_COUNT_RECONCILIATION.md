# C6/C7 adaptive-rival count reconciliation

## Audited result

Both results use the same 431 generated rows: seeds 400–403, four common futures,
384 sampled pre-action states, unchanged engine mechanics, unchanged 0.5-point
near-tie threshold, and the same C6 `build_rows` implementation.

| Raw point-estimate relation | Uncertainty gate | Rows | Historical C6 label | Validated label |
|---|---|---:|---|---|
| Action changes | At least one lower bound ≤ 0.5 | 68 | Reversal | Near tie |
| Action changes | Both lower bounds > 0.5 | 1 | Reversal | Validated reversal |
| Action stable | At least one lower bound ≤ 0.5 | 221 | Near tie | Near tie |
| Action stable | Both lower bounds > 0.5 | 141 | No-change control | No-change control |
| **Total** | | **431** | **69 / 221 / 141** | **1 / 289 / 141** |

Thus the transformation is exact:

```text
historical raw reversals 69
- raw reversals failing uncertainty gate 68
= statistically separated reversals 1

historical near ties 221
+ near-tie raw reversals 68
= corrected near ties 289
```

The machine-readable cross-table is
`analysis/results/c7/reconciliation.json` (generation output SHA-256
`4f7a8bac96b60b238057c5def02325d00e7fb5fcf9b8471d5ce6c2b254527ba8`).

## Exact definitions

- **Raw action reversal:** the best point-estimate action in condition A differs
  from the best point-estimate action in condition B.
- **Reference gap:** for one condition, the lower 95% confidence bound of the
  paired best-minus-second-best expected team-points difference, clipped at zero.
- **Near tie:** either condition has `reference_gap <= 0.5` points.
- **Uncertainty-separated pair:** both conditions have `reference_gap > 0.5`.
- **Validated reversal:** raw action reversal and uncertainty-separated pair.
- **No-change control:** stable reference action and uncertainty-separated pair.

The boundary is intentionally strict: equality at 0.5 is a near tie, matching the
unchanged C6 classifier.

## Why the historical report differed

The C6 generator computed the C6 classifier correctly, but its summary and targeted
bucket expression used this reporting order:

```text
if reference_reversal: REVERSAL
elif classifier_result == NEAR_TIE: NEAR_TIE
else: NO_CHANGE_CONTROL
```

Consequently, a row with a changed point-estimate action and an uncertainty interval
crossing the near-tie threshold was counted as `REVERSAL` in the summary even though
the classifier returned `NEAR_TIE`. C7 applies the evidence gate first:

```text
if classifier_result == NEAR_TIE: NEAR_TIE
elif reference_reversal: VALIDATED_REVERSAL
else: NO_CHANGE_CONTROL
```

No engine rule, threshold, reference value, or classifier was changed.

## Duplicate and sampling-unit effect

C6's 431 count uses one **state × named rival-policy variant** as a row. Several
named policies produce the same baseline/altered public observations. There are 290
distinct ordered public-observation hash pairs overall.

| Class definition | Row count | Unique pairs within class |
|---|---:|---:|
| Historical raw reversal | 69 | 63 |
| Historical near tie | 221 | 164 |
| Historical no-change | 141 | 104 |
| Corrected near tie | 289 | 205 |
| Corrected no-change | 141 | 104 |
| Validated reversal | 1 | 1 |

Duplicate removal does **not** explain the 69→1 change: the uncertainty gate alone
removes 68 raw reversals. Duplicate removal is a separate issue for live-call sample
size because identical public prompts must not be presented as independent evidence.

Per-class unique counts sum above the 290 overall unique pairs because an identical
public-observation pair can be evaluated under different hidden continuation-policy
metadata and land in different reference classes. Such hidden metadata is not supplied
to Gemini and cannot justify duplicate live prompts.

## Reproduction and regression

```sh
cd f1-championship
PYTHONPATH=src:. scripts/py312 analysis/c7_reconcile_counts.py \
  --output analysis/results/c7/reconciliation.json
PYTHONPATH=src:. scripts/py312 -m unittest \
  devtests.test_c7_reconciliation devtests.test_c7_live_paired_probe \
  devtests.test_c6_evidence_pipeline -v
```

The regression explicitly asserts that a raw action change with either lower bound
at or below 0.5 cannot be reported as a validated reversal.
