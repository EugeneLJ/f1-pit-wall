# C7 live paired-probe preflight report

> **P0 reconciliation:** this report's corrected census is backed by the row-level
> cross-table in `analysis/results/c7/reconciliation.json`. Historical C6 “69
> reversals” are 69 raw point-estimate action changes: 68 fail the unchanged
> uncertainty gate and 1 is a validated reversal. See
> `docs/C7_C6_COUNT_RECONCILIATION.md`.

## Outcome

The live experiment was stopped before any model call. The frozen C6 held-out
population cannot supply the requested five statistically separated reference
reversal pairs without duplicating public observations or relabelling near ties.

This is an evidence-coverage blocker, not a Gemini result. API calls, token usage,
and cost are all zero. No credential was written or copied into the repository.

## What the preflight found

C6 generated 431 eligible visible-action pairs from seeds 400–403 with four common
future samples. Its compact report counted any changed point-estimate reference
action as a reversal before checking whether the preference was separated. The C6
classifier itself correctly checks the near-tie threshold first.

C7 reran the unchanged C6 generator and classifier with mutually exclusive class
precedence:

1. `NEAR_TIE` when either reference preference is not separated;
2. `REVERSAL` only when both preferences are separated and their actions differ;
3. `NO_CHANGE_CONTROL` for a separated stable reference.

The corrected census is:

| Class | Generated rows | Unique public-observation pairs |
|---|---:|---:|
| Near tie | 289 | 205 |
| No-change control | 141 | 104 |
| Separated reversal | 1 | 1 |

The requested 5/5/3 selection therefore cannot be formed. Treating five near-tie
action changes as successful reversal probes would violate C6's evidence rules.
Repeating the same public pair under different hidden policy labels would not create
five legitimate observable conditions.

The machine-readable result is `analysis/results/c7/preflight.json`. It records
`live_calls_made: 0` and the exact blocker.

## Prepared runtime, not executed

C7 adds a resumable live runner and evaluator for use after a valid selection exists:

- exact prompt and response bytes plus SHA-256 hashes;
- requested and provider-returned model revision, request ID, token usage, latency,
  retry count, and dated estimated cost;
- environment-only credential loading and a pre-write credential leak check;
- validation against public legal actions;
- exact observation-hash linkage to the frozen pair;
- unchanged C6 classification; and
- point expected-regret calculation only where the frozen C6 `q_all` supports it.

The live observation excludes generator seed, rival policy/variant, future events,
and realized futures. The two conditions differ only through the public state and
consequences produced by the legitimate observable rival action.

## Reproduction

Reproduce the preflight. Exit status 2 is intentional:

```sh
cd f1-championship
PYTHONPATH=src:. scripts/py312 analysis/c7_build_candidates.py \
  --output analysis/results/c7/preflight.json
```

Tests:

```sh
PYTHONPATH=src:. scripts/py312 -m unittest \
  devtests.test_c7_live_paired_probe devtests.test_c6_evidence_pipeline -v
```

After a future valid selection is frozen, the intended smoke/full sequence is:

```sh
# Two calls; these count toward the final 26 because the runner resumes by pair/condition.
PYTHONPATH=src:. uv run --no-project --python 3.12 --with google-genai \
  python analysis/c7_live_paired_probe.py \
  --selection track_c/fixtures/c7_live_probe_selection.json \
  --source analysis/results/c7/frozen_candidates.json \
  --env-file /root/.config/f1-pit-wall.env \
  --output analysis/results/c7/live_records.jsonl \
  --max-pairs 1 --require-valid-smoke

# Resume the remaining calls with identical model/prompt/sampling settings.
PYTHONPATH=src:. uv run --no-project --python 3.12 --with google-genai \
  python analysis/c7_live_paired_probe.py \
  --selection track_c/fixtures/c7_live_probe_selection.json \
  --source analysis/results/c7/frozen_candidates.json \
  --env-file /root/.config/f1-pit-wall.env \
  --output analysis/results/c7/live_records.jsonl
```

## Safe next decision

The defensible next option is to extend the held-out seed population deterministically
while retaining the frozen engine, C6 classifier, near-tie threshold, prompt, action
schema, and common-future count. That is outside the request to select from the
existing C6 probes and should be approved explicitly. Lowering the threshold after
seeing the census or selecting on Gemini behavior would invalidate the experiment.
