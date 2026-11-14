# F1 Pit Wall — Harbor P0 vertical slice

A deterministic, judge-runnable Harbor task about one coupled pit-wall decision.
An agent chooses `PIT` or `STAY` for both Apex GP drivers. The choice changes
their remaining race times, finishing positions, and combined constructors'
points.

## What the agent must do

Inside the task container:

```bash
f1ctl observe
f1ctl rules
f1ctl preview '{"driver_a":"PIT","driver_b":"STAY"}'
f1ctl act '{"driver_a":"PIT","driver_b":"STAY"}'
```

The final command writes `/app/submission/action.json`. The trusted verifier
reads only those two choices and independently recomputes classification and
points. It never trusts a submitted score, a CLI result, or agent-visible engine
code.

This P0 slice intentionally contains no FastF1 data, weather, safety car, or
championship. Its purpose is to prove the Harbor lifecycle and trust boundary.

## Scoring and baselines

Official-style points for this eight-car field are `25, 18, 15, 12, 10, 8, 6,
4`. Reward is `Apex constructors' points / 28`, where 28 is the maximum for the
fixed scenario. Missing, malformed, incomplete, or extra-key submissions score
zero. `tests/test.sh` always writes one finite reward in `[0, 1]`.

| Policy | A | B | Points | Reward |
|---|---|---|---:|---:|
| Oracle | PIT | STAY | 28 | 1.00000000 |
| Do nothing | STAY | STAY | 20 | 0.71428571 |
| Stop early | — | — | 0 | 0.00000000 |

## Harbor 0.26.0

Prerequisites are Python 3.12+ and a working Docker installation. Install the
version used to scaffold and validate this task:

```bash
uv tool install 'harbor==0.26.0'
harbor --version
```

The repository follows `harbor task init` from 0.26.0: schema 1.4, an agent
environment, and a separate verifier image. Run:

```bash
python3 -m unittest discover -s tests -p 'test_local.py' -v
harbor lint .
harbor check .
harbor run -p . -a oracle
harbor run -p . -a nop
```

The missing-submission unit test is the explicit stop-early baseline. A real
OpenCode run requires the organizer-provided model identifier and credentials:

```bash
harbor run -p . -a opencode -m '<provider/model>'
```

Inspect each Harbor trial's verifier logs and `reward.txt`; documentation alone
is not evidence of a run.

## Optional MCP adapter

The task is CLI-first. `environment/f1pitwall/mcp_server.py` is a thin optional
FastMCP adapter over the same public engine. FastMCP is not installed in the
offline P0 image and the adapter is not registered in `task.toml`; it is an
extension point, not a second simulator or submission requirement.

## Sources and scope

- [Harbor quickstart](https://harborframework.com/docs/quickstart)
- [Harbor task creation guide](https://harborframework.com/docs/guides/creating-tasks)
- [Harbor repository](https://github.com/harbor-framework/harbor)
- [`docs/HANDOFF.md`](docs/HANDOFF.md) is background only; unverified claims
  were not treated as implementation facts.
