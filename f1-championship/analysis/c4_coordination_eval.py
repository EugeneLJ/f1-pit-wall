#!/usr/bin/env python3
"""Validate and summarize C4 evaluation bundles without running a model or race."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TASK / "src"), str(TASK)]

from track_c.coordination_evaluation import compare_layers, summarize_bundle  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", help="one bundle, or matched Layer 1 then Layer 2 bundles")
    parser.add_argument("--output")
    args = parser.parse_args()
    bundles = [json.loads(Path(name).read_text(encoding="utf-8")) for name in args.inputs]
    if len(bundles) == 1:
        report = summarize_bundle(bundles[0])
    elif len(bundles) == 2:
        report = compare_layers(*bundles)
    else:
        parser.error("provide one bundle or exactly two matched bundles")
    rendered = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
