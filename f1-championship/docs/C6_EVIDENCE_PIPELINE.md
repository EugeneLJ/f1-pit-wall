# C6 adaptive-rival and gap evidence pipeline

## Scope

C6 is analysis-only. It does not modify the authoritative engine, Harbor task,
reward, or verifier. It consumes benchmark 2.0.1 B7 artifacts and uses the existing
public-input rollout implementation for synthetic diagnostic probes. The probe
mechanics come from the frozen B8 integration baseline, but no opt-in 2.1.0 power-unit
rule is enabled.

The three estimands remain separate:

1. a matched Frontier–Reference season gap;
2. decision-level expected Constructors' points regret; and
3. Gemini-versus-DeepSeek two-team competition results.

The B7 competition scores are never reported as the official AfterQuery gap.

## Adaptive-rival evidence contract

`track_c/adaptive_rival_evaluation.py` first verifies the C4 bundle and its sealed
observation/action linkage. A rival action is eligible only after it appears in the
Chief observation's public classification or pit history. A policy name, future
continuation, hidden seed, or realized future event is not observable evidence.

A matched pair is classified as appropriate adaptation, failure to adapt,
incorrect adaptation, overreaction, no adaptation needed, near tie, inconclusive,
or insufficient evidence. A response label requires:

- a visible difference before both Chief decisions;
- identical mechanics and action constraints;
- separated equal-information reference preferences;
- paired Chief actions; and
- reference provenance that does not use the realized future as an observation.

B7 has 112 McLearn race decisions in each layer. The verified audit finds visible
Red Bool pit evidence, but only one adaptive trajectory per layer. It therefore
reports `INSUFFICIENT_EVIDENCE` for a Gemini adaptation failure rather than creating
a counterfactual Chief response.

Run the audit:

```sh
PYTHONPATH=src:. scripts/py312 analysis/c6_b7_audit.py analysis/results/b7 \
  --output analysis/results/c6_b7_evidence.json
```

## Deterministic paired probes

`analysis/c6_adaptive_probes.py` samples complete eight-race trajectories from
held-out seeds. At a sampled state it applies either the baseline or altered rival
action, then probes the next Chief decision, where that action is already public.
Both branches use common future draws and the existing authoritative public-input
rollout reference. Selection uses only reference reversal/control status and pair
ID; no model output is consulted.

The generated file reports the denominator for natural visible-pair frequency
separately from the small targeted diagnostic set. Reference reversal, stable
control, and near-tie pairs are separate. These are synthetic probes, not live
Gemini results and not FIA-calibrated frequencies.

```sh
PYTHONPATH=src:. scripts/py312 analysis/c6_adaptive_probes.py \
  --seeds 4 --offset 400 --futures 4 --per-bucket 2 \
  --output analysis/results/c6_adaptive_probes.json
```

## Gap evidence exporter

The input schema is `track_c/schemas/gap_evidence_manifest.schema.json` and semantic
validation is in `track_c/gap_evidence.py`. Runs are paired only by comparison group
and season seed. Confidence intervals use paired season differences; correlated
race decisions are never treated as independent samples. Missing or incomplete
Frontier/reference runs stay pending. Selected failure records require a SHA-256
observation hash and finite regret evidence with provenance.

```sh
PYTHONPATH=src:. scripts/py312 analysis/c6_gap_export.py \
  track_c/fixtures/c6_b7_gap_manifest.json \
  --json-output /tmp/c6-gap.json --markdown-output /tmp/c6-gap.md
```

The included manifest contains only the two real B7 competition records. It
intentionally produces no official Frontier–Reference measurement.

## Engineer evidence

The B7 C4 report contains 20 decisions that pass its positive-regret gate. The C6
audit exports a concise sample with exact observation hashes, regret intervals,
Engineer usage, and information-value classification. This supports individual
case studies. It does not support a causal Layer 1 versus Layer 2 claim because the
two live seasons are unmatched interventions and trajectories.

## Required inputs from Track B/Fable

An official gap report remains blocked until all of the following exist:

- completed Harbor Frontier season runs with benchmark/config/reward version, run
  ID, seed ID, model/provider/harness configuration, Constructors' points, and reward;
- reproducible strong-reference runs on the same season seeds, configuration,
  action constraints, and scenario distribution, with policy provenance;
- multiple independent matched season seeds for a defensible confidence interval;
- trusted observation/action journal artifacts plus public-input counterfactual
  values and uncertainty for selected decision failures;
- paired Gemini responses to matched visible-rival conditions for adaptive-response
  claims; and
- the exact reward normalization mapping and version.

Without these inputs C6 reports pending or insufficient evidence. It does not fill
gaps with B7 competition scores, a Chief's internal planner, or synthetic outcomes.

## Tests

```sh
PYTHONPATH=src:. scripts/py312 -m unittest devtests.test_c6_evidence_pipeline -v
PYTHONPATH=src:. scripts/py312 -m unittest devtests.test_c4_coordination_evaluation -v
PYTHONPATH=src:. scripts/py312 -m unittest discover -s devtests -v
```

No paid API call is required.
