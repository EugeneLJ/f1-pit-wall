#!/usr/bin/env python3
"""F1 Championship Strategist — 2.1.0 submission demo: verification and static HTML report.

Presentation code only. Official completion, integrity, points and reward come from the isolated
Harbor verifier. This file re-checks the captured artifacts, replays the sealed journal with the
built task's own verifier package (scripts/demo_v21_replay.py), and renders one self-contained page.

  finalize  --mode live      a fresh Harbor run directory written by scripts/demo.sh
  finalize  --mode recorded  a committed 2.1.0 Harbor run (f1-championship/analysis/results/reference_runs/<run>)
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import pickle
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TASK_SRC = ROOT / "f1-championship"
RUNS = TASK_SRC / "analysis" / "results" / "reference_runs"
REPLAY_HELPER = Path(__file__).resolve().parent / "demo_v21_replay.py"
CAPTURE_DIR = "demo_artifacts"
EXIT_INVALID = 2
EXIT_UNVERIFIED = 3
GENESIS = "0" * 64

EXPECTED = {"benchmark_version": "2.1.0", "scalar_version": "b6-integrated-p0",
            "mode": "SOLO_COORDINATION", "engineers": "CHIEF_ONLY"}
RACES, TICKS = 8, 120
# Instruction revision, identified from the built instruction or from Harbor's task checksum.
INSTRUCTION_SHA = {"f6697c53b1e0e0a35d6ca29a29deeab4b9f203917b15fa1548e43f63ad0e6591": "r1",
                   "5ad46b1044c088d0fcf0ab74ad17376a17108a14f36fffc2dfaa5e32f40b6c23": "r2"}
TASK_CHECKSUM = {"e94d82c1287f5be73f1671a19f7e085c8b6a87e9bb6f8b8a22c9f9ddccc801bf": "r1",
                 "a008cb00ad4344436fc58e69df828b809f85e5498e068bdf8a9a203425d03a48": "r2"}
DEFAULT_REFERENCE = "v21-oracle-01"
OTHER_RUNS = ("v21-gemini-01", "v21-gemini-02", "v21-gemini-03", "v21r2-gemini-01")
TEAMS = ("Apex", "Orion", "Nova", "Vertex")
KEY_TICK = "t095"  # race 7 Safety Car, the recurring failure in the committed analysis
CF_FUTURES = 16


# ------------------------------------------------------------------ small helpers
def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"missing {Path(path).name}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"malformed {Path(path).name}: {type(exc).__name__}: {exc}") from exc


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n", encoding="utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


# ------------------------------------------------------------------ run sources
@dataclass
class Source:
    """Where one Harbor run's official files are, in either layout."""
    label: str
    kind: str  # "live" or "recorded"
    report: Path | None
    reward: Path | None
    evidence: Path | None
    harbor_result: Path | None
    errors: list[str] = field(default_factory=list)


def live_source(run_dir: Path) -> Source:
    """Fresh Harbor job under <run_dir>/harbor-output: exactly one trial with a verifier mount."""
    out = run_dir / "harbor-output"
    reports = sorted(p for p in out.glob("*/*/verifier/report.json") if p.is_file()) if out.is_dir() else []
    if len(reports) != 1:
        msg = "no Harbor verifier report.json was produced" if not reports else "more than one Harbor trial found"
        return Source("live", "live", None, None, None, None, [msg])
    trial = reports[0].parent.parent
    return Source("live", "live", reports[0], trial / "verifier" / "reward.txt",
                  trial / "artifacts" / "evidence" / "f1sim", trial / "result.json")


def recorded_source(run: str | Path) -> Source:
    path = Path(run)
    if not path.is_dir():
        path = RUNS / str(run)
    if not path.is_dir():
        return Source(str(run), "recorded", None, None, None, None, [f"recorded run not found: {run}"])
    return Source(path.name, "recorded", path / "verifier_report.json", path / "reward.txt",
                  path / "evidence", path / "harbor_result.json")


# ------------------------------------------------------------------ verification
def verify(source: Source, task: Path, states_out: Path | None = None) -> dict[str, Any]:
    """Every check the demo relies on. `verified` is True only if all pass."""
    checks: list[tuple[str, bool, str]] = []
    out: dict[str, Any] = {"source": source.label, "kind": source.kind, "checks": checks, "verified": False,
                           "errors": []}

    def check(name: str, ok: bool | None, detail: str) -> bool:
        """ok=None means not applicable (shown as N/A, does not affect `verified`)."""
        checks.append((name, None if ok is None else bool(ok), detail))
        if ok is False:
            out["errors"].append(f"{name}: {detail}")
        return ok is not False

    if source.errors or source.report is None:
        check("Harbor verifier output", False, "; ".join(source.errors) or "missing")
        return out
    try:
        report = read_json(source.report)
        if not isinstance(report, dict):
            raise ValueError("report.json is not an object")
    except ValueError as exc:
        check("Harbor verifier output", False, str(exc))
        return out
    out["report"] = report
    out["report_path"] = str(source.report)
    completion = report.get("completion") if isinstance(report.get("completion"), dict) else {}
    integrity = report.get("integrity") if isinstance(report.get("integrity"), dict) else {}
    norm = report.get("normalization") if isinstance(report.get("normalization"), dict) else {}
    perf = report.get("performance") if isinstance(report.get("performance"), dict) else {}
    out.update({"points": norm.get("P"), "reward": report.get("reward"),
                "complete": completion.get("complete") is True, "intact": integrity.get("intact") is True})

    check("Benchmark and scalar version",
          report.get("benchmark_version") == EXPECTED["benchmark_version"] and report.get("scalar_version") == EXPECTED["scalar_version"],
          f"{report.get('benchmark_version')} / {report.get('scalar_version')}")
    check("Verifier: season complete", completion.get("complete") is True and completion.get("resolved_ticks") == TICKS
          and completion.get("races_completed") == RACES,
          f"complete={completion.get('complete')}, {completion.get('resolved_ticks')} of {TICKS} ticks, "
          f"{completion.get('races_completed')} of {RACES} races")
    check("Verifier: sealed replay intact", integrity.get("intact") is True,
          integrity.get("error") or "hash chain, manifest and full replay accepted by the isolated verifier")
    reward = report.get("reward")
    p, d, u = norm.get("P"), norm.get("D_fallback_same_seed"), norm.get("U")
    consistent = all(is_number(v) for v in (p, d, u, reward)) and u > d and perf.get("apex_constructors_points") == p
    if consistent and out["complete"] and out["intact"]:
        consistent = abs(min(1.0, max(0.0, (p - d) / (u - d))) - reward) < 1e-9
    elif consistent:
        consistent = reward == 0.0
    check("Reward matches the published formula", consistent,
          f"P={p}, D={d}, U={u}, reward={reward}")
    if source.kind == "recorded" and not Path(source.reward or "").is_file():
        check("reward.txt equals report.json", None, "not part of this run's committed evidence; report.json reward used")
    else:
      try:
        text = Path(source.reward).read_text(encoding="utf-8").strip()
        check("reward.txt equals report.json", is_number(reward) and abs(float(text) - float(reward)) < 1e-8, f"reward.txt = {text}")
      except (OSError, ValueError, TypeError) as exc:
        check("reward.txt equals report.json", False, f"unreadable: {exc}")

    journal_path, manifest_path = Path(source.evidence or "") / "journal.jsonl", Path(source.evidence or "") / "manifest.json"
    try:
        raw = journal_path.read_bytes()
        manifest = read_json(manifest_path)
        entries = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line]
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        check("Sealed evidence present", False, str(exc))
        return out
    digest = sha256_bytes(raw)
    out["journal_sha256"], out["entries"] = digest, entries
    check("Journal SHA-256 matches manifest", manifest.get("journal_sha256") == digest, digest)
    check("Manifest entry count and head hash",
          manifest.get("journal_entries") == len(entries) and manifest.get("head_hash") == (entries[-1]["entry_hash"] if entries else GENESIS),
          f"{len(entries)} entries")
    check("Journal v2 for benchmark 2.1.0",
          manifest.get("benchmark_version") == "2.1.0" and manifest.get("journal_version") == 2
          and all(e.get("journal_version") == 2 for e in entries), f"manifest {manifest.get('benchmark_version')}, journal v{manifest.get('journal_version')}")
    resolved = [e for e in entries if e.get("kind") == "resolved"]
    check("Resolved ticks match the verifier", len(resolved) == completion.get("resolved_ticks"),
          f"{len(resolved)} resolved entries")

    # Authoritative replay with the verifier package of the built task.
    with tempfile.TemporaryDirectory() as tmp:
        states_path = Path(tmp) / "states.pickle"
        proc = subprocess.run([sys.executable, "-I", str(REPLAY_HELPER), str(task), str(journal_path), str(states_path)],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            check("Authoritative replay (verifier package)", False, (proc.stderr.strip().splitlines() or ["failed"])[-1][:300])
            return out
        replay = json.loads(proc.stdout)
        if states_out is not None and states_path.exists():
            shutil.copy2(states_path, states_out)
    out["replay"] = replay
    journal_results = [e["race_result"] for e in resolved if "race_result" in e]
    same_races = [r["team_points"] for r in replay["race_results"]] == [r["team_points"] for r in journal_results]
    check("Authoritative replay (verifier package)",
          replay["resolved_ticks"] == len(resolved) and replay["team_points"].get("Apex") == p and same_races,
          f"{replay['resolved_ticks']} ticks replayed; Apex {replay['team_points'].get('Apex')} pts; "
          f"{len(replay['race_results'])} race results equal the journal's race_result entries"
          if same_races else "per-race results differ from the journal")
    out["verified"] = all(ok is not False for _, ok, _ in checks)
    return out


def provenance(source: Source, task: Path | None, metadata: dict[str, Any]) -> dict[str, Any]:
    info: dict[str, Any] = {"model": metadata.get("model"), "agent": metadata.get("agent")}
    try:
        harbor = read_json(source.harbor_result) if source.harbor_result else {}
    except ValueError:
        harbor = {}
    agent = (harbor.get("config") or {}).get("agent") or {}
    info["agent"] = agent.get("name") or info["agent"]
    info["model"] = agent.get("model_name") or info["model"] or ("—" if agent.get("name") in ("oracle", "nop") else None)
    info["trial"] = harbor.get("trial_name")
    info["started_at"] = harbor.get("started_at")
    info["finished_at"] = harbor.get("finished_at")
    info["task_checksum"] = harbor.get("task_checksum")
    revision = TASK_CHECKSUM.get(harbor.get("task_checksum") or "")
    if revision is None and task is not None and source.kind == "live":
        revision = INSTRUCTION_SHA.get(sha256_bytes((task / "instruction.md").read_bytes()))
    info["instruction"] = revision or "unknown"
    return info


# ------------------------------------------------------------------ analysis (labelled counterfactual)
def _counterfactual(jobs):
    """Sequential (about 0.2 s per decision). Uses the repository engine through the committed analysis
    code (analysis/b21_decisions.py); devtests keep it identical to the image copies."""
    if str(TASK_SRC / "analysis") not in sys.path:
        sys.path.insert(0, str(TASK_SRC / "analysis"))
    import b21_decisions as B
    return {tick: B.evaluate({"tick_id": tick, "race": race, "action": action}, CF_FUTURES) for tick, race, action in jobs}


def decision_examples(verified_run: dict[str, Any], states_file: Path, reference: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Counterfactual check of every SC/VSC decision; returns the race-7 SC decision and the largest other loss."""
    items = verified_run["replay"]["neutralised_decisions"]
    states = pickle.loads(states_file.read_bytes())
    jobs = [(n["tick_id"], states[n["tick_id"]], n["action"]) for n in items if n["tick_id"] in states]
    evals = _counterfactual(jobs)
    ref_actions = {}
    if reference and reference.get("verified"):
        ref_actions = {e["tick_id"]: e["submissions"]["Apex"]["action"] for e in reference["entries"] if e.get("kind") == "resolved"}
    rows = []
    for n in items:
        ev = evals.get(n["tick_id"])
        if not ev:
            continue
        ra = ref_actions.get(n["tick_id"])
        rows.append({**n, "regret": ev["regret"], "se": ev["se"], "best": ev["reference"].split("|")[0],
                     "chosen": ev["chosen"].split("|")[0],
                     "reference_run_action": f"{ra['driver_a']}/{ra['driver_b']}" if ra else None})
    chosen = [r for r in rows if r["tick_id"] == KEY_TICK]
    others = sorted((r for r in rows if r["tick_id"] != KEY_TICK and r["regret"] > 1.0 and r["regret"] > 2 * r["se"]),
                    key=lambda r: -r["regret"])
    return (chosen + others)[:2] if chosen else others[:2]


# ------------------------------------------------------------------ view model
def race_rows(run: dict[str, Any]) -> list[dict[str, Any]]:
    replay = run["replay"]
    resolved = [e for e in run["entries"] if e.get("kind") == "resolved"]
    stops: dict[int, list[str]] = {}
    race_index = 0
    for e in resolved:
        action = e["submissions"]["Apex"].get("action") or {}
        if e["decision_type"] == "RACE_STRATEGY":
            for car, key in (("A", "driver_a"), ("B", "driver_b")):
                if str(action.get(key, "")).startswith("PIT_"):
                    stops.setdefault(race_index, []).append(f"{car}→{action[key][4]}")
        if "race_result" in e:
            race_index += 1
    rows, cumulative = [], {t: 0 for t in TEAMS}
    for i, r in enumerate(replay["race_results"]):
        for t in TEAMS:
            cumulative[t] += r["team_points"].get(t, 0)
        cls = {c["driver"]: c for c in r["classification"]}
        def place(driver):
            c = cls.get(driver) or {}
            return f"P{c['position']}" if c.get("status") == "FINISHED" else (c.get("status") or "?")
        neutral = [(k, s) for k, s in enumerate(r["events"]) if s != "GREEN"]
        rows.append({"race": i + 1, "name": r["race_name"].replace(" Grand Prix", ""),
                     "archetype": replay["calendar"][i]["archetype"].replace("_", " "),
                     "events": [f"{s} L{3 * (k + 1)}" for k, s in neutral],
                     "apex": r["team_points"].get("Apex", 0), "team_points": r["team_points"],
                     "cumulative": dict(cumulative), "places": (place("Apex A"), place("Apex B")),
                     "stops": stops.get(i, [])})
    return rows


# ------------------------------------------------------------------ HTML
CSS = """
.viz-root{color-scheme:light;--surface:#fcfcfb;--page:#f3f3f1;--line:#e3e2dd;--grid:#ecebe7;--text:#0b0b0b;--text2:#52514e;--muted:#7a7974;
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--ok:#0c7a3a;--bad:#c0332f;--warn:#a86a00;--accent:#d4212c}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])) .viz-root{color-scheme:dark;--surface:#1a1a19;--page:#111110;--line:#33322f;--grid:#262624;
--text:#f0efec;--text2:#c3c2b7;--muted:#8f8e86;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--ok:#3fbf73;--bad:#ff6b66;--warn:#e3a53a;--accent:#ff5a60}}
:root[data-theme="dark"] .viz-root{color-scheme:dark;--surface:#1a1a19;--page:#111110;--line:#33322f;--grid:#262624;
--text:#f0efec;--text2:#c3c2b7;--muted:#8f8e86;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--ok:#3fbf73;--bad:#ff6b66;--warn:#e3a53a;--accent:#ff5a60}
*{box-sizing:border-box}html,body{margin:0}body{background:var(--page)}
.viz-root{background:var(--page);color:var(--text);font:15px/1.5 Inter,system-ui,-apple-system,"Segoe UI",sans-serif;min-height:100vh}
main{max-width:1160px;margin:0 auto;padding:28px 24px 40px}
header{border-top:6px solid var(--accent);padding-top:18px;display:flex;flex-wrap:wrap;gap:12px 24px;align-items:flex-end;justify-content:space-between}
h1{font-size:2.1rem;line-height:1.1;margin:0;letter-spacing:-.01em}.sub{color:var(--text2);margin:4px 0 0;font-size:1.05rem}
.badges{display:flex;flex-wrap:wrap;gap:8px}.badge{font-size:.78rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;padding:5px 10px;border-radius:999px;border:1px solid var(--line);color:var(--text2);background:var(--surface)}
.badge.ok{color:var(--ok);border-color:var(--ok)}.badge.bad{color:var(--bad);border-color:var(--bad)}.badge.rec{color:var(--warn);border-color:var(--warn)}
.config{color:var(--muted);font-size:.86rem;margin:10px 0 0}
section{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:20px 22px;margin:18px 0}
h2{font-size:1.05rem;margin:0 0 4px}.note{color:var(--muted);font-size:.84rem;margin:2px 0 12px}
.hero{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px}
.tile{border-left:3px solid var(--line);padding:4px 14px}.tile.gem{border-color:var(--s1)}.tile.ref{border-color:var(--text2)}
.tile .k{color:var(--text2);font-size:.82rem}.tile .v{font-size:2.2rem;font-weight:750;font-variant-numeric:tabular-nums;line-height:1.15}.tile .r{color:var(--muted);font-size:.84rem;font-variant-numeric:tabular-nums}
.runs{color:var(--muted);font-size:.84rem;margin-top:12px}
.chart{position:relative}.chart svg{width:100%;height:auto;display:block}.chart text{font-family:inherit;fill:var(--text2);font-size:12px}
.chart .end{font-size:12.5px;font-weight:650;fill:var(--text)}.chart .axis{stroke:var(--line)}.chart .grid{stroke:var(--grid)}
.legend{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:.85rem;color:var(--text2);margin:0 0 6px}.legend i{display:inline-block;width:18px;height:0;border-top:3px solid;vertical-align:middle;margin-right:6px}
.legend i.dash{border-top-style:dashed}
.tip{position:absolute;pointer-events:none;background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:8px 10px;font-size:.82rem;box-shadow:0 4px 14px rgba(0,0,0,.12);display:none;min-width:170px;font-variant-numeric:tabular-nums}
.tip b{display:block;margin-bottom:4px}.tip div{display:flex;justify-content:space-between;gap:14px}
.timeline{display:grid;grid-template-columns:repeat(8,minmax(0,1fr));gap:10px}
.race{border:1px solid var(--line);border-radius:10px;padding:10px 10px 12px;min-width:0;position:relative}
.race .n{color:var(--muted);font-size:.74rem;font-weight:700;letter-spacing:.06em}.race .t{font-weight:700;font-size:.95rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.race .a{color:var(--muted);font-size:.74rem;margin-bottom:6px}.race .pts{font-size:1.5rem;font-weight:750;font-variant-numeric:tabular-nums}.race .pts small{font-size:.72rem;color:var(--muted);font-weight:500}
.race .ref{color:var(--muted);font-size:.76rem;font-variant-numeric:tabular-nums}.race .pl{font-size:.8rem;color:var(--text2);margin-top:4px}
.chips{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px;min-height:20px}.chip{font-size:.68rem;font-weight:700;border-radius:4px;padding:1px 5px;border:1px solid var(--warn);color:var(--warn)}
.chip.sc{background:var(--warn);color:var(--surface);border-color:var(--warn)}.stops{font-size:.72rem;color:var(--muted);margin-top:4px}
.race.key{outline:2px solid var(--accent);outline-offset:-1px}
.cases{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px}
.case{border:1px solid var(--line);border-radius:10px;padding:14px 16px}.case h3{margin:0 0 2px;font-size:.98rem}.case .ctx{color:var(--muted);font-size:.82rem;margin-bottom:10px}
.case table{width:100%;border-collapse:collapse;font-size:.86rem}.case td{padding:4px 0;border-bottom:1px solid var(--grid)}.case td:last-child{text-align:right;font-weight:650;font-variant-numeric:tabular-nums}
.loss{color:var(--bad)}
table.data{width:100%;border-collapse:collapse;font-size:.86rem;font-variant-numeric:tabular-nums}table.data th,table.data td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--grid)}
table.data th{color:var(--muted);font-weight:600;font-size:.76rem;text-transform:uppercase;letter-spacing:.04em}
.checks{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:4px 22px;font-size:.84rem}
.checks div{display:flex;gap:8px;align-items:baseline;border-bottom:1px solid var(--grid);padding:4px 0}.checks .s{font-weight:750;min-width:40px}.checks .s.ok{color:var(--ok)}.checks .s.bad{color:var(--bad)}
.checks .d{color:var(--muted);overflow-wrap:anywhere}
.prov{font-size:.8rem;color:var(--muted);overflow-wrap:anywhere}.prov code{font-size:.78rem}
.failbox{border:2px solid var(--bad);border-radius:12px;padding:18px 22px;background:var(--surface);margin:18px 0}.failbox h2{color:var(--bad)}
details summary{cursor:pointer;color:var(--text2);font-size:.86rem}
@media(max-width:900px){.timeline{grid-template-columns:repeat(4,minmax(0,1fr))}}
@media(max-width:560px){main{padding:18px 16px}.timeline{grid-template-columns:repeat(2,minmax(0,1fr))}h1{font-size:1.6rem}}
"""

JS = """
(function(){var c=document.querySelector('.chart');if(!c)return;var d=JSON.parse(c.dataset.series),svg=c.querySelector('svg'),tip=c.querySelector('.tip'),hair=svg.querySelector('.hair');
function show(i){var x=d.x[i];hair.setAttribute('x1',x);hair.setAttribute('x2',x);hair.style.display='';tip.textContent='';var b=document.createElement('b');b.textContent=d.labels[i];tip.appendChild(b);
d.series.forEach(function(s){var r=document.createElement('div'),n=document.createElement('span'),v=document.createElement('strong');n.textContent=s.name;v.textContent=s.values[i];r.appendChild(n);r.appendChild(v);tip.appendChild(r);});
var box=svg.getBoundingClientRect(),sx=box.width/svg.viewBox.baseVal.width;tip.style.display='block';var left=x*sx+14;if(left+tip.offsetWidth>box.width)left=x*sx-tip.offsetWidth-14;tip.style.left=left+'px';tip.style.top='8px';}
function hide(){tip.style.display='none';hair.style.display='none';}
svg.addEventListener('pointermove',function(e){var box=svg.getBoundingClientRect(),px=(e.clientX-box.left)*svg.viewBox.baseVal.width/box.width,best=0;d.x.forEach(function(x,i){if(Math.abs(x-px)<Math.abs(d.x[best]-px))best=i;});show(best);});
svg.addEventListener('pointerleave',hide);svg.addEventListener('focus',function(){show(d.x.length-1)});svg.addEventListener('blur',hide);})();
"""


def points_chart(rows: list[dict[str, Any]], ref_rows: list[dict[str, Any]] | None, frontier_label: str) -> str:
    W, H, L, R, T, B = 980, 380, 52, 150, 16, 40
    n = len(rows)
    xs = [L + (W - L - R) * i / RACES for i in range(RACES + 1)]
    series = [(f"Apex · {frontier_label}", "var(--s1)", False, [0] + [r["cumulative"]["Apex"] for r in rows])]
    if ref_rows:
        series.append(("Apex · Reference", "var(--s1)", True, [0] + [r["cumulative"]["Apex"] for r in ref_rows]))
    for team, color in (("Orion", "var(--s2)"), ("Nova", "var(--s3)"), ("Vertex", "var(--s4)")):
        series.append((team, color, False, [0] + [r["cumulative"][team] for r in rows]))
    top = max(max(v) for *_, v in series) or 1
    step = 50 if top > 150 else 25
    ymax = math.ceil(top / step) * step
    y = lambda v: T + (H - T - B) * (1 - v / ymax)
    parts = [f'<line class="axis" x1="{L}" y1="{y(0):.1f}" x2="{W - R}" y2="{y(0):.1f}"/>']
    for v in range(0, ymax + 1, step):
        if v:
            parts.append(f'<line class="grid" x1="{L}" y1="{y(v):.1f}" x2="{W - R}" y2="{y(v):.1f}"/>')
        parts.append(f'<text x="{L - 8}" y="{y(v) + 4:.1f}" text-anchor="end">{v}</text>')
    for i in range(RACES + 1):
        label = "Start" if i == 0 else f"R{i}"
        parts.append(f'<text x="{xs[i]:.1f}" y="{H - B + 20}" text-anchor="middle">{label}</text>')
    # draw rivals first, Apex last (on top); 2px lines, 8px markers with a surface ring
    ends = []
    for name, color, dashed, values in reversed(series):
        pts = " ".join(f"{xs[i]:.1f},{y(v):.1f}" for i, v in enumerate(values[: n + 1]))
        width = 3 if name.startswith("Apex") else 2
        dash = ' stroke-dasharray="7 5"' if dashed else ""
        parts.append(f'<polyline fill="none" stroke="{color}" stroke-width="{width}" stroke-linejoin="round" stroke-linecap="round"{dash} points="{pts}"/>')
        if name.startswith("Apex") and not dashed:
            for i, v in enumerate(values[1: n + 1], start=1):
                parts.append(f'<circle cx="{xs[i]:.1f}" cy="{y(v):.1f}" r="4" fill="{color}" stroke="var(--surface)" stroke-width="2"/>')
        ends.append([y(values[n]), name, values[n], color])
    ends.sort(key=lambda e: e[0])
    for i in range(1, len(ends)):  # keep end labels at least 15px apart
        ends[i][0] = max(ends[i][0], ends[i - 1][0] + 15)
    for ly, name, value, color in ends:
        parts.append(f'<text class="end" x="{xs[n] + 10:.1f}" y="{ly + 4:.1f}">{esc(value)} {esc(name)}</text>')
    parts.append(f'<line class="hair" x1="0" y1="{T}" x2="0" y2="{H - B}" stroke="var(--muted)" stroke-width="1" style="display:none"/>')
    data = {"x": [round(x, 1) for x in xs[: n + 1]], "labels": ["Start"] + [f"Race {r['race']} · {r['name']}" for r in rows],
            "series": [{"name": s[0], "values": s[3][: n + 1]} for s in series]}
    legend = "".join(f'<span><i style="border-color:{c}"{" class=dash" if d else ""}></i>{esc(nm)}</span>' for nm, c, d, _ in series)
    return (f'<div class="legend">{legend}</div><div class="chart" data-series="{esc(json.dumps(data))}">'
            f'<svg viewBox="0 0 {W} {H}" role="img" tabindex="0" aria-label="Cumulative constructors\' points by race">{"".join(parts)}</svg>'
            f'<div class="tip" role="status"></div></div>')


def timeline(rows: list[dict[str, Any]], ref_rows: list[dict[str, Any]] | None, key_race: int | None) -> str:
    cards = []
    for i, r in enumerate(rows):
        chips = "".join(f'<span class="chip{" sc" if e.startswith("SC") else ""}">{esc(e)}</span>' for e in r["events"]) or '<span class="note" style="margin:0">green race</span>'
        ref = f'<div class="ref">Reference {ref_rows[i]["apex"]}</div>' if ref_rows and i < len(ref_rows) else ""
        stops = ", ".join(r["stops"]) if r["stops"] else "no stop"
        cards.append(f'<div class="race{" key" if key_race == r["race"] else ""}"><div class="n">RACE {r["race"]}</div><div class="t" title="{esc(r["name"])}">{esc(r["name"])}</div>'
                     f'<div class="a">{esc(r["archetype"])}</div><div class="pts">{r["apex"]} <small>pts</small></div>{ref}'
                     f'<div class="pl">{esc(r["places"][0])} · {esc(r["places"][1])}</div><div class="chips">{chips}</div><div class="stops">Stops: {esc(stops)}</div></div>')
    return f'<div class="timeline">{"".join(cards)}</div>'


def case_cards(examples: list[dict[str, Any]], frontier_label: str) -> str:
    out = []
    for ex in examples:
        cars = ex["cars"]
        ctx = (f'Race {ex["race_index"] + 1} · {esc(ex["race_name"])} · lap {ex["lap"]} · {esc(ex["status"])} · {ex["laps_remaining"]} laps to go. '
               f'Car A P{cars["driver_a"]["position"]} on {cars["driver_a"]["compound"]} ({cars["driver_a"]["tyre_age"]} laps), '
               f'car B P{cars["driver_b"]["position"]} on {cars["driver_b"]["compound"]} ({cars["driver_b"]["tyre_age"]} laps).')
        rows = [(f"{frontier_label} chose", esc(ex["chosen"])),
                ("Best by engine rollout on public inputs", esc(ex["best"])),
                ("Expected points given up", f'<span class="loss">{ex["regret"]:.1f} ± {ex["se"]:.1f}</span>' if ex["regret"] > 0.05 else "≈ 0")]
        if ex.get("reference_run_action"):
            rows.append(("The Reference run at this same Safety Car tick" if ex["status"] == "SC" else "The Reference run at this tick", esc(ex["reference_run_action"])))
        title = "Race 7 Safety Car: the cheap stop" if ex["tick_id"] == KEY_TICK else f'{ex["status"]} decision, race {ex["race_index"] + 1}'
        out.append(f'<div class="case"><h3>{esc(title)}</h3><div class="ctx">{ctx}</div><table>'
                   + "".join(f"<tr><td>{a}</td><td>{b}</td></tr>" for a, b in rows) + "</table></div>")
    return f'<div class="cases">{"".join(out)}</div>'


def checks_html(run: dict[str, Any], title: str) -> str:
    rows = "".join(f'<div><span class="s {"ok" if ok else ("" if ok is None else "bad")}">{"PASS" if ok else ("N/A" if ok is None else "FAIL")}</span><span>{esc(n)}<br><span class="d">{esc(d)}</span></span></div>'
                   for n, ok, d in run["checks"])
    return f'<h3 style="font-size:.9rem;margin:10px 0 4px">{esc(title)}</h3><div class="checks">{rows}</div>'


def render(ctx: dict[str, Any]) -> str:
    run, ref, meta, prov = ctx["run"], ctx.get("reference"), ctx["metadata"], ctx["provenance"]
    mode = ctx["mode"]
    verified = run["verified"] and ctx["harbor_exit_code"] == 0
    frontier = "Gemini" if "gemini" in str(prov.get("model") or "") else (prov.get("agent") or "Agent")
    if mode == "live":
        mode_badge = ('<span class="badge ok">Live · fresh Harbor trial</span>' if verified
                      else '<span class="badge">Live · Harbor trial failed or incomplete</span>')
    else:
        mode_badge = f'<span class="badge rec">Recorded replay · Harbor run of {esc((prov.get("finished_at") or "?")[:16].replace("T", " "))} UTC</span>'
    status_badge = '<span class="badge ok">Verified</span>' if verified else '<span class="badge bad">Not verified</span>'
    config = (f'Benchmark {EXPECTED["benchmark_version"]} · {EXPECTED["mode"]} · {EXPECTED["engineers"]} · rivals on fixed published rules · '
              f'instruction {esc(prov.get("instruction"))} · {esc(prov.get("agent"))} · {esc(prov.get("model") or "model unknown")} · task seed')
    head = (f'<header><div><h1>F1 Championship Strategist</h1><p class="sub">A Long-Horizon AI Strategy Benchmark</p></div>'
            f'<div class="badges">{mode_badge}{status_badge}</div></header><p class="config">{config}</p>')
    body = []
    if not verified:
        reasons = "".join(f"<li>{esc(e)}</li>" for e in (run["errors"] or [f"Harbor exited with code {ctx['harbor_exit_code']}"]))
        if ctx["harbor_exit_code"]:
            reasons = f"<li>Harbor exited with code {ctx['harbor_exit_code']}</li>" + reasons
        body.append(f'<div class="failbox"><h2>No verified championship result</h2><p>This run is not shown as a result. '
                    f'Nothing recorded was substituted.</p><ul>{reasons}</ul></div>')
        body.append(f'<section><h2>Verification</h2>{checks_html(run, "This run")}</section>')
    else:
        rows, ref_rows = ctx["rows"], ctx.get("ref_rows")
        p, rw = run["points"], run["reward"]
        tiles = [f'<div class="tile gem"><div class="k">{esc(frontier)} · constructors\' points</div><div class="v">{p}</div><div class="r">reward {rw:.4f}</div></div>']
        if ref and ref.get("verified"):
            gap = ref["points"] - p
            tiles.append(f'<div class="tile ref"><div class="k">Reference · constructors\' points</div><div class="v">{ref["points"]}</div><div class="r">reward {ref["reward"]:.4f}</div></div>')
            tiles.append(f'<div class="tile"><div class="k">Reference − {esc(frontier)}</div><div class="v">{gap:+d}</div><div class="r">same benchmark, mode and seed</div></div>')
        standings = sorted(run["replay"]["team_points"].items(), key=lambda kv: -kv[1])
        rank = [t for t, _ in standings].index("Apex") + 1
        tiles.append(f'<div class="tile"><div class="k">Apex championship position</div><div class="v">P{rank}</div><div class="r">of 4 constructors</div></div>')
        others = ctx.get("others") or []
        strip = ""
        if others:
            strip = '<div class="runs">All committed Gemini Harbor runs on this seed (each re-verified here): ' + " · ".join(
                f'{esc(o["source"])} {o["points"]} ({esc(o["instruction"])})' for o in others) + ". Reference " + (f'{ref["points"]}' if ref else "—") + ".</div>"
        body.append(f'<section><div class="hero">{"".join(tiles)}</div>{strip}</section>')
        body.append(f'<section><h2>Championship progression</h2><p class="note">Cumulative constructors\' points after each race, from the authoritative replay of the sealed journal. '
                    f'Rivals are from this run; the dashed line is Apex in the Reference run on the same seed.</p>{points_chart(rows, ref_rows, frontier)}</section>')
        key_race = next((ex["race_index"] + 1 for ex in ctx.get("examples", []) if ex["tick_id"] == KEY_TICK), None)
        body.append(f'<section><h2>Eight-race timeline</h2><p class="note">Apex points per race ({esc(frontier)} run; Reference below), finishing positions of cars A and B, '
                    f'Safety Car / Virtual Safety Car periods (decision lap) and the pit stops this run made (car → compound).</p>{timeline(rows, ref_rows, key_race)}</section>')
        if ctx.get("examples"):
            body.append(f'<section><h2>Strategic decisions under neutralisation</h2><p class="note">Counterfactual analysis, not a race result: the authoritative engine rolled out every legal pit '
                        f'choice over {CF_FUTURES} SC/VSC futures drawn from the published model, conditioned on what had happened so far (public inputs only; the reference has a model-access advantage). '
                        f'Values are expected constructors\' points for the rest of the race.</p>{case_cards(ctx["examples"], frontier)}</section>')
        table_rows = "".join(f'<tr><td>R{r["race"]} {esc(r["name"])}</td>' + "".join(f'<td>{r["team_points"].get(t, 0)}</td>' for t in TEAMS)
                             + (f'<td>{ref_rows[i]["apex"]}</td>' if ref_rows else "") + f'<td>{r["cumulative"]["Apex"]}</td></tr>' for i, r in enumerate(rows))
        n = run["report"]["normalization"]
        body.append(f'<section><h2>Final result</h2><p class="note">Official values from the isolated Harbor verifier; reward = clip((P − D) / (U − D)), '
                    f'P = Apex points {n["P"]}, D = published fallback on the same seed {n["D_fallback_same_seed"]}, U = 43 × 8 = {n["U"]} → <strong>{rw:.4f}</strong>.</p>'
                    f'<details><summary>Race-by-race table</summary><div style="overflow-x:auto"><table class="data"><thead><tr><th>Race</th>' + "".join(f"<th>{t}</th>" for t in TEAMS)
                    + ("<th>Apex · Reference</th>" if ref_rows else "") + f'<th>Apex cumulative</th></tr></thead><tbody>{table_rows}</tbody></table></div></details></section>')
        checks = checks_html(run, f"This run ({run['source']})") + (checks_html(ref, f"Reference ({ref['source']})") if ref else "")
        body.append(f'<section><h2>Verified evidence</h2>{checks}</section>')
    prov_rows = [("Run", run["source"]), ("Harbor trial", prov.get("trial")), ("Started / finished (UTC)", f'{prov.get("started_at")} / {prov.get("finished_at")}'),
                 ("Harbor task checksum", prov.get("task_checksum")), ("Journal SHA-256", run.get("journal_sha256")),
                 ("Verifier report", run.get("report_path")), ("Replay module", (run.get("replay") or {}).get("replay_module")),
                 ("Reference", f'{ref["source"]} · {ref.get("report_path")}' if ref else "none"),
                 ("Report generated", meta.get("generated_at"))]
    body.append('<section class="prov"><h2>Provenance</h2>' + "<br>".join(f"{esc(k)}: <code>{esc(v)}</code>" for k, v in prov_rows) + "</section>")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>F1 Championship Strategist</title><style>{CSS}</style></head><body><div class="viz-root"><main>{head}{"".join(body)}</main></div>'
            f'<script>{JS}</script></body></html>')


# ------------------------------------------------------------------ commands
def build_task(dest: Path, revision: str) -> Path:
    env = {**os.environ, "F1_INSTRUCTION_REVISION": revision}
    subprocess.run([str(TASK_SRC / "scripts" / "make_integrated_task.sh"), str(dest), "CHIEF_ONLY", "2.1.0"],
                   check=True, capture_output=True, env=env)
    return dest


def capture(run_dir: Path, source: Source) -> None:
    dest = run_dir / CAPTURE_DIR
    for path, name in ((source.report, "verifier/report.json"), (source.reward, "verifier/reward.txt"),
                       (source.harbor_result, "harbor/result.json")):
        if path and Path(path).is_file():
            (dest / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest / name)
    if source.evidence and Path(source.evidence).is_dir():
        (dest / "evidence").mkdir(parents=True, exist_ok=True)
        for f in Path(source.evidence).iterdir():
            if f.is_file():
                shutil.copy2(f, dest / "evidence" / f.name)


def finalize(args: argparse.Namespace) -> int:
    run_dir = args.run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    try:
        metadata = read_json(run_dir / "run.json")
    except ValueError:
        metadata = {}
    metadata.update({"mode": args.mode, "generated_at": utc_now()})
    if args.mode == "live":
        task = Path(args.task).resolve()
        source = live_source(run_dir)
        harbor_exit = args.harbor_exit_code
    else:
        source = recorded_source(args.run)
        harbor_exit = 0
        try:
            harbor = read_json(source.harbor_result) if source.harbor_result else {}
        except ValueError:
            harbor = {}
        revision = TASK_CHECKSUM.get(harbor.get("task_checksum") or "", "r2")
        task = build_task(run_dir / "task", revision)
    states = run_dir / "neutralised_states.pickle"
    run = verify(source, task, states)
    prov = provenance(source, task, metadata)
    reference = None
    if args.reference != "none":
        reference = verify(recorded_source(args.reference), task)
    seed_ok = (task / "tests" / "hidden_seed.json").read_bytes() == (TASK_SRC / "tests" / "hidden_seed.json").read_bytes()
    if reference is not None:
        reference["checks"].append(("Same seed as this run", seed_ok, "built task seed = the task seed the committed runs used"))
        reference["verified"] = reference["verified"] and seed_ok
    ctx: dict[str, Any] = {"mode": args.mode, "run": run, "reference": reference, "metadata": metadata, "provenance": prov,
                           "harbor_exit_code": harbor_exit}
    if run["verified"] and harbor_exit == 0:
        ctx["rows"] = race_rows(run)
        if reference and reference["verified"]:
            ctx["ref_rows"] = race_rows(reference)
        try:
            ctx["examples"] = decision_examples(run, states, reference)
        except Exception as exc:  # analysis is optional; never blocks the verified result
            run.setdefault("notes", []).append(f"counterfactual examples unavailable: {type(exc).__name__}: {exc}")
        others = []
        for name in OTHER_RUNS:
            o = verify(recorded_source(name), task)
            if o["verified"]:
                others.append({"source": name, "points": o["points"],
                               "instruction": provenance(recorded_source(name), None, {})["instruction"]})
        ctx["others"] = others
    capture(run_dir, source)
    states.unlink(missing_ok=True)
    out = args.output or run_dir / "report.html"
    out.write_text(render(ctx), encoding="utf-8")
    success = run["verified"] and harbor_exit == 0
    result = {"schema_version": 2, "mode": args.mode, "source": run["source"], "verified": success,
              "harbor_exit_code": harbor_exit, "points": run.get("points"), "reward": run.get("reward"),
              "journal_sha256": run.get("journal_sha256"), "provenance": prov,
              "reference": {"source": reference["source"], "verified": reference["verified"], "points": reference.get("points"),
                            "reward": reference.get("reward")} if reference else None,
              "checks": [{"name": n, "pass": ok, "detail": d} for n, ok, d in run["checks"]],  # pass None = N/A
              "examples": [{k: v for k, v in ex.items() if k != "cars"} for ex in ctx.get("examples", [])],
              "errors": run["errors"], "report_html": str(out)}
    write_json(run_dir / "demo_result.json", result)
    print(f"Verification: {'PASS' if success else 'FAIL'}" + (f"; points {run.get('points')}, reward {run.get('reward')}" if success else ""))
    for error in run["errors"]:
        print(f"  - {error}", file=sys.stderr)
    print(f"Report: {out}")
    if harbor_exit:
        return harbor_exit
    return 0 if success else EXIT_UNVERIFIED


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("finalize")
    f.add_argument("--mode", choices=("live", "recorded"), required=True)
    f.add_argument("--run-dir", type=Path, required=True, help="output directory for this demo run")
    f.add_argument("--task", type=Path, help="live: the built task directory used for the Harbor run")
    f.add_argument("--harbor-exit-code", type=int, default=0)
    f.add_argument("--run", default="v21-gemini-01", help="recorded: a committed run name or directory")
    f.add_argument("--reference", default=DEFAULT_REFERENCE, help="committed reference run, or 'none'")
    f.add_argument("--output", type=Path)
    f.set_defaults(func=finalize)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.mode == "live" and not args.task:
        print("--task is required in live mode", file=sys.stderr)
        return EXIT_INVALID
    try:
        return args.func(args)
    except subprocess.CalledProcessError as exc:
        print(f"Demo failed: {exc}", file=sys.stderr)
        return EXIT_INVALID


if __name__ == "__main__":
    sys.exit(main())
