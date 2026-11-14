# F1 Pit Wall — Championship task (P0: sealed evaluation boundary)

Harbor task in which an agent runs Apex GP through an eight-race constructors'
championship. **Status: P0.** The evaluation boundary is implemented and
verified on Harbor 0.26.0; the race mechanics are still the legacy single-race
engine repeated per round, so this is *not yet* a strategy benchmark (see
[docs/P0_REPORT.md](docs/P0_REPORT.md)). The legacy single-race task at the
repository root is unchanged and remains the regression baseline.

## What the agent does

Uses `f1ctl observe | rules | act <decision_id> '<json>'` to make 32 sequential
decisions: per race, one component decision (USE/REPLACE per power-unit
component) and three PIT/STAY decisions for both cars. See `instruction.md`.

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

Points only accumulate, so stopping early cannot beat finishing. P2 will add
a reference planner and reference-relative regret as a separate report field.

## Run

```bash
harbor run -p ./f1-championship -a oracle    # P0 heuristic oracle
harbor run -p ./f1-championship -a nop       # stop-early / do-nothing
scripts/make_probe_task.sh /tmp/probe complete && harbor run -p /tmp/probe -a oracle
python3 -m unittest discover -s devtests -v  # local boundary tests (no Docker)
```

Edit the engine only in `src/f1pitwall/`, then run `scripts/sync_engine.py`
(the sim and verifier images each need a copy; `devtests` fails on drift).
All track and component coefficients are synthetic placeholders.
