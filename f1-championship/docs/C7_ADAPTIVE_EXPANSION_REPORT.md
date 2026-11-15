# C7 bounded adaptive-rival expansion

The preregistration was committed as `3a28b96` before generating results. Exactly
the ten registered seeds 404–413 were evaluated with four common futures and the
unchanged C6 classifier and 0.5-point near-tie threshold.

## Result

| Validated class | Rows | Unique public-observation pairs |
|---|---:|---:|
| Validated reversal | 3 | 3 |
| No-change control | 343 | 186 |
| Near tie | 639 | 297 |

- Eligible state×policy rows: 985
- Unique public-observation pairs overall: 439
- Pairs whose class varies with hidden continuation metadata: 47
- Runtime: 254.989 seconds
- GO/NO-GO: **GO** under the preregistered minimum of three unique reversals
- Live model calls: **0**

Eight disjoint-prompt candidates were frozen: three validated reversals, three
no-change controls, and two near ties. The experiment stopped before live Gemini
calls to conserve the remaining evaluation budget; no C8 paid experiment began.

Artifacts:

- `analysis/results/c7/adaptive_expansion.json`, SHA-256
  `d6d1e5d0475469f5519f3959d4b1f74e37883c3f111993b5a15a706bd2d5e2f9`
- `analysis/results/c7/adaptive_expansion_candidates.json`, SHA-256
  `061794dd39dafbcb96169479625aaffc6bd012f4bda2f81058ed786fd1906f31`

Reproduce:

```sh
PYTHONPATH=src:. scripts/py312 analysis/c7_adaptive_expansion.py \
  --prereg track_c/fixtures/c7_adaptive_expansion_prereg.json \
  --output analysis/results/c7/adaptive_expansion.json \
  --candidates-output analysis/results/c7/adaptive_expansion_candidates.json
```

The next live step is bounded by the preregistration to 16 calls including smoke.
C8 Engineer-conflict work remains unstarted and must use a separate branch.
