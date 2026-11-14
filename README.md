# F1 Pit Wall — sequential Harbor race strategy

A judge-runnable Harbor task for coupled, sequential F1 strategy decisions. An
agent controls both Apex GP drivers at laps 8, 12 and 16 of a 20-lap synthetic
race. Tyres, elapsed time, track position and pit consequences persist.

This version implements the minimal Phases 1–3 research environment: sequential
decisions, shared-pit-crew coupling, and seeded GREEN/VSC/SC events. It does not
yet include weather, engineer recommendations, a championship, or FastF1 data.

## Agent contract

Inside the task container:

```bash
f1ctl rules
f1ctl observe
f1ctl act '{"driver_a":"PIT","driver_b":"STAY"}'
```

Each `act` advances four laps and returns the next causally available
observation. Repeat until three actions are submitted. There is deliberately no
future-outcome preview command. The CLI writes `/app/submission/actions.json`.

The agent sees the complete tyre, traffic, pit-loss, double-stack and rival
policy rules. It sees only the current track status; later seeded events remain
hidden until their decision points.

## Mechanics

- Eight cars: two Apex cars and six deterministic rivals.
- Actions: `PIT` or `STAY` independently for both Apex drivers.
- A pit stop installs a new MEDIUM tyre.
- Pit loss: GREEN 18s, VSC 10s, SC 5s.
- If both Apex cars pit together, Driver B waits an additional 6s.
- Lap time combines driver base pace, compound offset, age-dependent
  degradation and a bounded traffic penalty.
- Event generation uses a fixed seed and probabilities GREEN 0.60, VSC 0.25,
  SC 0.15 at each decision.
- Objective: combined official-style constructors' points, not either driver's
  individual position.

For seed `20261114`, the observed event history is GREEN, GREEN, SC. It is
reported only after completion.

## Trusted scoring

Harbor transfers only `/app/submission/actions.json` to the isolated verifier.
The verifier does not import agent-visible code or trust a claimed score. It
validates exactly three actions and independently replays the race using
`tests/trusted_engine.py`.

Official-style points for the eight-car field are `25, 18, 15, 12, 10, 8, 6,
4`. Reward uses fixed, documented anchors:

```text
clip((constructors_points - 10) / (23 - 10), 0, 1)
```

The low anchor is the validated every-decision double-stack policy. The high
anchor is the best score found by exhaustive enumeration of all 64 legal action
sequences. Invalid or incomplete submissions score zero.

| Policy | Action summary | Points | Reward |
|---|---|---:|---:|
| Oracle | A pits early; B stays, then pits under SC | 23 | 1.00000000 |
| Do nothing | both stay at all three decisions | 16 | 0.46153846 |
| Pit spam | both pit at all three decisions | 10 | 0.00000000 |
| Stop early | fewer than three decisions | — | 0.00000000 |

`tests/test.sh` initializes `/logs/verifier/reward.txt` to zero and always
normalizes it to one finite scalar in `[0, 1]`.

## Run

Prerequisites are Python 3.12+, Docker, and Harbor 0.26.0:

```bash
uv tool install 'harbor==0.26.0'
python3 -m unittest discover -s tests -p 'test_local.py' -v
harbor lint .
harbor run -p . -a oracle
harbor run -p . -a nop
```

The agent image pins Node 22 and OpenCode `1.19.5` so installation remains
compatible with the offline task policy. A Gemini run uses a host-side env file
and permits only the inference hostname during the agent phase:

```bash
harbor run -p . -a opencode -m gemini/gemini-3.8-flash \
  --api-key-name GEMINI_API_KEY \
  --env-file /secure/path/f1-pit-wall.env \
  --allow-agent-host generativelanguage.googleapis.com
```

## Validation and limitations

The local suite exhaustively checks all 64 legal strategies for parity between
the public simulator and isolated verifier. It also checks state persistence,
hidden future observations, oracle, do-nothing, pit-spam, invalid, extra-field
and stop-early paths.

The current action journal is a minimal Harbor interaction contract, not a
cryptographic append-only protocol. The verifier ignores mutable state and
replays only the final action sequence, but a deliberately adversarial agent
could edit its sequence after observing later events. A policy-on-held-out-seed
contract or authenticated sidecar is required before claiming strong hindsight
resistance.

The first three frontier-agent trials matched the planning reference and did
not expose a failure. See [`docs/EVALUATION_2026-11-14.md`](docs/EVALUATION_2026-11-14.md)
for the exact jobs, traces, scores, and proposed next experiment.

## Optional MCP adapter

The task is CLI-first. `environment/f1pitwall/mcp_server.py` is an optional
FastMCP extension over the public rules and initial observation. It is not
installed or registered for evaluation.

## Sources and scope

- [Harbor quickstart](https://harborframework.com/docs/quickstart)
- [Harbor task creation guide](https://harborframework.com/docs/guides/creating-tasks)
- [Harbor repository](https://github.com/harbor-framework/harbor)
- [`docs/HANDOFF.md`](docs/HANDOFF.md) is research background, not proof of an
  implemented feature or measured frontier-agent gap.
