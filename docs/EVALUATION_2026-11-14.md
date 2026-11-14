# Phase 1–3 evaluation — 2026-11-14

This report records the first evaluation of the sequential, coupled race task.
It reports observed results only; the initial research hypothesis is not treated
as a finding.

## Configuration

- Task commit: `83cfe68` (`Add sequential coupled race strategy`)
- Harbor: `0.26.0`
- Frontier harness: OpenCode `1.19.5`
- Model: `gemini/gemini-3.8-flash`
- Seed: `20261114`
- Decision laps: 8, 12, 16
- Revealed event sequence: GREEN, GREEN, SC
- Reward anchors: 10 constructors' points = 0; 23 points = 1

The agent was restricted to the task CLI and the Gemini inference hostname.
The verifier independently replayed the transferred `actions.json`; it did not
trust simulator state or an agent-authored reward.

## Results

| Evaluation | Job or check | Actions | Points | Reward | Outcome |
|---|---|---|---:|---:|---|
| Planning reference | `f1-sequential-oracle-01` | A PIT/B STAY; both STAY; A STAY/B PIT | 23 | 1.00000000 | Valid |
| Frontier run 1 | `f1-sequential-opencode-gemini-01` | A PIT/B STAY; both STAY; A STAY/B PIT | 23 | 1.00000000 | Valid |
| Frontier run 2 | `f1-sequential-opencode-gemini-02` | A PIT/B STAY; both STAY; A STAY/B PIT | 23 | 1.00000000 | Valid |
| Frontier run 3 | `f1-sequential-opencode-gemini-03` | A PIT/B STAY; both STAY; A STAY/B PIT | 23 | 1.00000000 | Valid |
| Do nothing | local isolated-verifier test | both STAY three times | 16 | 0.46153846 | Valid, suboptimal |
| Pit spam | local isolated-verifier test | both PIT three times | 10 | 0.00000000 | Valid, low anchor |
| Stop early | `f1-sequential-nop-01` | no complete submission | — | 0.00000000 | Invalid/incomplete |
| Claimed reward field | local isolated-verifier test | oracle actions plus extra `reward` | — | 0.00000000 | Rejected |

All three frontier trials reproduced the planning reference exactly. No
planning, adaptation, or coordination failure was observed in this scenario.
This means the current fixed-seed instance is a valid integrity and mechanics
test, but it is not yet a demonstrated frontier-agent discriminator.

## Verification

The following checks passed:

- `python3 -m unittest discover -s tests -p 'test_local.py' -v` — 6/6
- exhaustive public/trusted-engine parity — all 64 legal action sequences
- finite bounded rewards — all 64 legal action sequences
- `bash -n tests/test.sh solution/solve.sh`
- Python bytecode compilation for environment and verifier modules
- `harbor lint .`
- Harbor oracle run — reward 1.0
- Harbor nop/stop-early run — reward 0.0
- three Harbor OpenCode/Gemini runs — reward 1.0 each

Raw Harbor job artifacts remain on the Verda instance under
`/root/f1-pit-wall-repo/jobs/<job-name>/`. They contain the action submission,
trajectory, verifier report, reward, seed, and configuration for each run.

## Next experiment

Before adding race engineers, make the planning task harder without hiding
legitimate rules: evaluate multiple held-out seeds, lengthen the horizon, add
event-conditioned action constraints, and score a policy across a seed suite
instead of one final editable action journal. This also closes the documented
hindsight-editing weakness. Engineer recommendations should then be added as a
separate controlled variable so any coordination failure can be attributed to
the recommendations rather than to a changed race model.
