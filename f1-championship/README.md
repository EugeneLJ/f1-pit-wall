# F1 Pit Wall — Championship task

**Benchmark version 1.1.0** (`f1pitwall.version`; history in [docs/VERSIONS.md](docs/VERSIONS.md)). Analysis and replays run on Python 3.12, the same as the images (`scripts/py312`).

Harbor task in which an agent runs Apex GP through an eight-race constructors'
championship. **Status: Track B through B4 (benchmark 1.1.0).** The sealed evaluation boundary (P0) is verified
on Harbor 0.26.0. Track A long-horizon mechanics (component wear, reliability,
shared free units, grid penalties, track-dependent performance) are implemented
and analysed with an exact reduced-season solver. See
[docs/P0_REPORT.md](docs/P0_REPORT.md), [docs/P1_REPORT.md](docs/P1_REPORT.md)
and the full target scope in [docs/ROADMAP.md](docs/ROADMAP.md). The legacy single-race task at the
repository root is unchanged and remains the regression baseline.

## What the agent does

Uses `f1ctl observe | rules | act <decision_id> '<json>'` to make 32 sequential
decisions per season (32 before Track B, 120 from B3): per race, one component decision (USE/REPLACE per power-unit
component) and, since Track B, 14 STAY/PIT_<compound> decisions per race for both cars. See `instruction.md`.

## Architecture

```text
 main (agent) container            sim container (network: none)
 ┌─────────────────────┐           ┌──────────────────────────────────┐
 │ OpenCode / oracle   │           │ f1sim.server  (authoritative)    │
 │ /usr/local/bin/f1ctl│──socket──▶│ /opt/f1sim/secret/seed.json 0600 │
 │ no engine, no seed  │  volume   │ /var/lib/f1sim/journal.jsonl 0700│
 └─────────────────────┘ f1sock:   │ (hash-chained, fsync per entry)  │
                         /run/f1sim└──────────────┬───────────────────┘
                         (socket only)            │ [[verifier.collect]]
                                                  │ f1sim.export (main stopped,
                                                  ▼ session sealed)
                                   /evidence/f1sim/{journal.jsonl,manifest.json}
                                                  │ [[artifacts]] service="sim"
                                                  ▼
                                   verifier container (tests/Dockerfile)
                                   grade.py: chain check + full replay from
                                   hidden seed → /logs/verifier/reward.txt
```

- The shared volume holds only the Unix socket. Seed, live state and journal
  never leave the sim container's private filesystem.
- Every `act` must echo the current `decision_id`; stale ids are rejected as
  duplicates, future ids as out of order, and phase/action validation runs on a
  copy of the session, so rejected requests never change state. There is no
  reset/rewind/preview/seed command. A restarted server rebuilds state from its
  journal and refuses to start if the journal does not replay.
- The verifier reads only sidecar evidence plus its own copy of the hidden
  seed, re-verifies the hash chain and manifest, and replays every entry,
  recomputing each observation hash. Rejected `invalid_action` entries must
  also fail under replay.

## Scoring (P0, provisional)

The report (`/logs/verifier/report.json`) separates `completion`, `integrity`,
`performance` (raw Apex points, driver points, rank, margin) and `timing`.

```text
reward = 0                                  if not complete or not intact
reward = clip((P - D) / (U - D), 0, 1)      otherwise
P = Apex points, D = do-nothing policy on the same hidden seed,
U = 43 x races (P1+P2 every race; a true upper bound, not a reference score)
```

Points only accumulate, so stopping early cannot beat finishing. `U` is a bound, not a
reference score: the reference below reaches about 0.72 on average.

## Reference and measured gap

`solution/reference.py` (run by `-a oracle`) plays through `f1ctl` from public observations only, using a
model of the published rules: one-step rollout over all 16 joint race actions with futures sampled from
the published SC/VSC model, plus a search over season replacement plans. It is budget-limited, not optimal.

| | Points | Reward |
|---|---:|---:|
| Reference, task seed (Harbor) | 286 | 0.770 |
| Gemini 3.8 Flash, task seed, benchmark 1.0.0 (Harbor) | 268 | 0.698 |
| Gemini 3.8 Flash, task seed, benchmark 1.1.0 (Harbor, 3 runs on the same seed) | 282 / 279 / 286 | 0.754 / 0.742 / 0.770 |
| Reference, mean of 100 seeds | 271.8 | 0.724 |
| Scripts written by the four 1.0.0 Gemini runs, same 100 seeds | 243.7–254.9 | 0.617–0.660 |
| Scripts written by the three 1.1.0 Gemini runs, 20 paired seeds (reference 266.8 on these) | 256.6–261.1 | — |
| Simple public heuristic (`F1_SOLUTION=baseline`) | 231.6 | 0.571 |

Details, limits and open items: [docs/REFERENCE_GAP_REPORT.md](docs/REFERENCE_GAP_REPORT.md).

**Benchmark 2.1.0 (integrated, FIA-2026-based power-unit rules).** Generate the task with `scripts/make_integrated_task.sh f1-championship-2.1.0 CHIEF_ONLY 2.1.0`, then run `harbor run -p f1-championship-2.1.0 -a oracle`.

| 2.1.0 | Points | Reward |
|---|---:|---:|
| Reference, task seed (Harbor) | 289 | 0.782 |
| Gemini 3.8 Flash, task seed (Harbor, 1 run) | 279 | 0.742 |
| Reference, mean of 20 seeds | 276.3 | — |
| Gemini script replayed on the same 20 seeds | 267.3 | — |

Details: [docs/REFERENCE_2_1_0_REPORT.md](docs/REFERENCE_2_1_0_REPORT.md).

## Run (judges: start here)

Requirements: Harbor 0.26+, local Docker with Compose. Run from the repository root.

```bash
# 1. Reference run (public-information rollout player, about 90 s including image start)
harbor run -p ./f1-championship -a oracle

# 2. Frontier run (the documented model; repeat for more runs)
harbor run -p ./f1-championship -a opencode -m gemini/gemini-3.8-flash \
  --api-key-name GEMINI_API_KEY --env-file <file with GEMINI_API_KEY=...> \
  --allow-agent-host generativelanguage.googleapis.com

# 3. Do-nothing baseline (agent does nothing; season unfinished -> reward 0)
harbor run -p ./f1-championship -a nop

# 4. Stop-early baseline (tries 20+ boundary attacks, plays two decisions, quits -> reward 0)
f1-championship/scripts/make_probe_task.sh /tmp/probe-stop stop && harbor run -p /tmp/probe-stop -a oracle

# 5. Exploit probe that then finishes honestly with the simple public heuristic (reward 0.587, evidence intact)
f1-championship/scripts/make_probe_task.sh /tmp/probe-complete complete && harbor run -p /tmp/probe-complete -a oracle

# Same task on another hidden seed (only the two seed files change)
f1-championship/scripts/make_seed_variant.sh /tmp/seed-x <integer seed> x && harbor run -p /tmp/seed-x -a oracle

# Local tests and the matched-seed comparison (no Docker; Python 3.12 through uv)
cd f1-championship
scripts/py312 -m unittest discover -s devtests
scripts/py312 analysis/reference_eval.py --seeds 100       # reference vs the four recorded Gemini policies
scripts/py312 analysis/reference_eval.py --harbor-seeds    # the four seeds of the recorded Harbor runs
```

The reward is written to `/logs/verifier/reward.txt` (one number in [0, 1]); the full breakdown is in
`/logs/verifier/report.json`. A "play every decision but do nothing" policy (USE, STAY) is the reward's
zero point `D`, so it also scores 0.

Edit the engine only in `src/f1pitwall/`, then run `scripts/sync_engine.py`
(the sim image, the verifier image and the reference solution each need a copy; `devtests` fails on drift).
All track and component coefficients are synthetic placeholders.
