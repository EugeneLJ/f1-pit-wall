#!/usr/bin/env python3
"""Policy-delegation timeline of a frontier run, from its OpenCode trajectory and sealed journal.

Reports which decisions the model submitted itself (an `f1ctl act <id>` call, or inline code
that names a decision id) versus decisions submitted by a script it wrote, when automation
started, every script the model wrote or edited (with the final source reconstructed), how
often each script was run, and whether it was run/tested before being trusted with the season.
Also scans the trajectory for credential-like strings.

Usage: python3 analysis/delegation.py <trajectory.json> <evidence_dir> <out_dir>
Writes <out_dir>/delegation.json and <out_dir>/scripts/<name> (final reconstructed sources).
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SECRET_PATTERNS = [re.compile(r"AIza[0-9A-Za-z_\-]{20,}"), re.compile(r"sk-[A-Za-z0-9]{20,}"),
                   re.compile(r"GEMINI_API_KEY\s*=\s*\S+"), re.compile(r"(?i)authorization:\s*bearer\s+\S+")]
ACT_ID = re.compile(r"\b[dt](\d{3})\b")  # journal v1 decision ids (d001) and v2 tick ids (t001)


def scan_secrets(text):
    return sorted({p.pattern for p in SECRET_PATTERNS if p.search(text)})


def main(trajectory_path, evidence_dir, out_dir):
    out_dir = Path(out_dir)
    (out_dir / "scripts").mkdir(parents=True, exist_ok=True)
    raw = Path(trajectory_path).read_text()
    trajectory = json.loads(raw)
    journal = [json.loads(line) for line in (Path(evidence_dir) / "journal.jsonl").read_text().splitlines() if line]
    accepted = [e for e in journal if e["kind"] == "accepted"]
    if not accepted and any(e["kind"] == "resolved" for e in journal):  # journal v2 (integrated tasks)
        accepted = [{**e, "decision_id": e["tick_id"],
                     "t_received": next(iter(e["submissions"].values()))["t_received"]}
                    for e in journal if e["kind"] == "resolved"]

    files, events = {}, []
    manual_ids = set()
    for step in trajectory["steps"]:
        ts = step.get("timestamp")
        for call in step.get("tool_calls") or []:
            name, args = call["function_name"], call["arguments"]
            text = json.dumps(args)
            if name == "write":
                path = args.get("filePath") or args.get("path")
                files.setdefault(path, []).append({"step": step["step_id"], "ts": ts, "op": "write",
                                                   "content": args.get("content", "")})
                events.append((ts, f"write {path}"))
            elif name == "edit":
                path = args.get("filePath") or args.get("path")
                files.setdefault(path, []).append({"step": step["step_id"], "ts": ts, "op": "edit",
                                                   "old": args.get("oldString", ""), "new": args.get("newString", ""),
                                                   "all": args.get("replaceAll", False)})
                events.append((ts, f"edit {path}"))
            elif name == "bash":
                cmd = args.get("command", "")
                # both `cat > f << EOF` and `cat << 'EOF' > f`
                heredoc = (re.search(r"cat\s*>\s*(?P<path>\S+)\s*<<\s*['\"]?(?P<tag>\w+)['\"]?\n(?P<body>.*?)\n(?P=tag)", cmd, re.S)
                           or re.search(r"cat\s*<<\s*['\"]?(?P<tag>\w+)['\"]?\s*>\s*(?P<path>\S+)\n(?P<body>.*?)\n(?P=tag)", cmd, re.S))
                if heredoc:
                    files.setdefault(heredoc.group("path"), []).append({"step": step["step_id"], "ts": ts, "op": "write",
                                                                         "content": heredoc.group("body")})
                    events.append((ts, f"heredoc {heredoc.group('path')}"))
                if "import " in cmd and any(Path(f).stem in cmd for f in files if f):
                    events.append((ts, "consult " + ",".join(Path(f).stem for f in files if f and Path(f).stem in cmd)))
                if "f1ctl act" in cmd or ('"act"' in cmd or "'act'" in cmd) and "decision_id" in cmd:
                    ids = {int(m) for m in ACT_ID.findall(cmd)}
                    if ids and "f1ctl act" in cmd:
                        manual_ids |= ids
                    events.append((ts, f"act {sorted(ids)[:3]}{'...' if len(ids) > 3 else ''}"))
                for path in files:
                    if path and (f"python3 {path}" in cmd or f"python {path}" in cmd or f"./{Path(path).name}" in cmd
                                 or f"python3 {Path(path).name}" in cmd):
                        events.append((ts, f"run {path}"))

    def to_epoch(ts):
        return datetime.fromisoformat(ts).astimezone(timezone.utc).timestamp() if ts else None

    scripts = {}
    for path, ops in files.items():
        content = ""
        for op in ops:
            if op["op"] == "write":
                content = op["content"]
            elif op["old"] in content:
                content = content.replace(op["old"], op["new"]) if op["all"] else content.replace(op["old"], op["new"], 1)
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", (path or "unnamed").strip("/"))
        (out_dir / "scripts" / (safe + ".txt")).write_text(content)
        runs = [e for e in events if e[1] == f"run {path}"]
        scripts[path] = {"versions": len(ops), "edits": sum(o["op"] == "edit" for o in ops),
                         "first_written": ops[0]["ts"], "runs": len(runs), "first_run": runs[0][0] if runs else None,
                         "saved_as": f"scripts/{safe}.txt", "lines": content.count("\n") + 1,
                         "acts_on_simulator": ('"act"' in content or "'act'" in content or "f1ctl" in content)}

    # decisions the model submitted itself right after asking one of its scripts for a recommendation
    consult_times = [to_epoch(ts) for ts, ev in events if ev.startswith("consult")]
    act_times = {}
    for ts, ev in events:
        if ev.startswith("act ["):
            for m in re.findall(r"\d+", ev.split("[", 1)[1]):
                act_times[int(m)] = to_epoch(ts)
    assisted = {i for i, t in act_times.items()
                if i in manual_ids and any(c is not None and t is not None and 0 <= t - c <= 120 for c in consult_times)}
    manual = [e for e in accepted if int(e["decision_id"][1:]) in manual_ids]
    automated = [e for e in accepted if int(e["decision_id"][1:]) not in manual_ids]
    first_auto = automated[0] if automated else None
    steps = [s for s in trajectory["steps"] if s.get("timestamp")]
    out = {
        "secrets_found": scan_secrets(raw),
        "agent_steps": len(steps),
        "accepted": len(accepted),
        "rejected": len(journal) - len(accepted),
        "manual_decisions": len(manual),
        "manual_decision_ids": [e["decision_id"] for e in manual],
        "script_assisted_manual_ids": [f"d{i:03d}" for i in sorted(assisted)],
        "automated_decisions": len(automated),
        "automation_started_at_decision": first_auto["decision_id"] if first_auto else None,
        "automation_started_unix": first_auto["t_received"] if first_auto else None,
        "first_step_unix": to_epoch(steps[0]["timestamp"]) if steps else None,
        "last_step_unix": to_epoch(steps[-1]["timestamp"]) if steps else None,
        "scripts": scripts,
        "timeline": events,
        "final_message": next((s.get("message") for s in reversed(trajectory["steps"]) if s.get("message")), None),
        "metrics": trajectory.get("final_metrics"),
    }
    (out_dir / "delegation.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps({k: out[k] for k in ("secrets_found", "agent_steps", "accepted", "rejected", "manual_decisions",
                                          "script_assisted_manual_ids", "automated_decisions",
                                          "automation_started_at_decision")}, indent=1))
    for path, info in scripts.items():
        print(path, info)


if __name__ == "__main__":
    main(*sys.argv[1:4])
