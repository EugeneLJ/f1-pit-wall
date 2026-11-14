from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .engine import RULES, SEED, new_state, observation, result, step, validate_action

STATE = Path("/app/.f1pitwall/state.json")
SUBMISSION = Path("/app/submission/actions.json")


def _json_argument(value: str) -> dict[str, str]:
    try:
        return validate_action(json.loads(value))
    except (json.JSONDecodeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    state = new_state(SEED)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
    return state


def _save(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
    SUBMISSION.parent.mkdir(parents=True, exist_ok=True)
    SUBMISSION.write_text(json.dumps({"version": 2, "actions": state["actions"]}, sort_keys=True) + "\n",
                          encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="f1ctl")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("observe")
    subparsers.add_parser("rules")
    act = subparsers.add_parser("act")
    act.add_argument("action", type=_json_argument)
    args = parser.parse_args(argv)
    if args.command == "rules":
        output = RULES
    elif args.command == "observe":
        output = observation(_load_state())
    else:
        state = _load_state()
        step(state, args.action)
        _save(state)
        output = result(state) if state["complete"] else observation(state)
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
