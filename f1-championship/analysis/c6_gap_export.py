#!/usr/bin/env python3
"""Export machine-readable and Markdown Frontier–Reference gap evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TASK / "src"), str(TASK)]

from track_c.gap_evidence import write_gap_outputs  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest")
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--markdown-output", required=True)
    args = parser.parse_args()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    report = write_gap_outputs(manifest, Path(args.json_output), Path(args.markdown_output))
    measured = sum(row["status"] == "MEASURED" for row in report["frontier_reference_gap"])
    print(json.dumps({"measured_groups": measured,
                      "competition_runs": len(report["gemini_deepseek_competition"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
