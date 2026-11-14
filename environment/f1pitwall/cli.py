from __future__ import annotations
import argparse
import json
from pathlib import Path
from typing import Sequence
from .engine import OBSERVATION, RULES, evaluate_action, validate_action

SUBMISSION = Path("/app/submission/action.json")


def _json_argument(value: str) -> dict[str, str]:
    try:
        return validate_action(json.loads(value))
    except (json.JSONDecodeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="f1ctl")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("observe")
    subparsers.add_parser("rules")
    for name in ("preview", "act"):
        command = subparsers.add_parser(name)
        command.add_argument("action", type=_json_argument)
    args = parser.parse_args(argv)
    if args.command == "observe":
        output = OBSERVATION
    elif args.command == "rules":
        output = RULES
    elif args.command == "preview":
        output = evaluate_action(args.action)
    else:
        SUBMISSION.parent.mkdir(parents=True, exist_ok=True)
        SUBMISSION.write_text(json.dumps(args.action, sort_keys=True) + "\n", encoding="utf-8")
        output = {"submitted": True, "action": args.action}
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
