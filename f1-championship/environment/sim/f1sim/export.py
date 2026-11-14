"""Collect hook: seal the session and copy evidence out of private state.

Harbor runs this inside the sim service after the agent container is stopped.
It reads only the private state directory, never the shared socket volume.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

STATE_DIR = Path(os.environ.get("F1SIM_STATE_DIR", "/var/lib/f1sim"))
EVIDENCE_DIR = Path(os.environ.get("F1SIM_EVIDENCE_DIR", "/evidence/f1sim"))
SERVER_VERSION = "b4-1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def export(state_dir: Path = STATE_DIR, evidence_dir: Path = EVIDENCE_DIR) -> dict:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "SEALED").write_text(f"{time.time():.6f}\n", encoding="utf-8")
    journal = state_dir / "journal.jsonl"
    if not journal.exists():
        journal.write_text("", encoding="utf-8")
    stats_path = state_dir / "stats.json"
    stats = json.loads(stats_path.read_text(encoding="utf-8")) if stats_path.exists() else {}

    if evidence_dir.exists():
        shutil.rmtree(evidence_dir)
    evidence_dir.mkdir(parents=True)
    shutil.copyfile(journal, evidence_dir / "journal.jsonl")
    lines = [line for line in journal.read_text(encoding="utf-8").splitlines() if line]
    manifest = {
        "server_version": SERVER_VERSION,
        "sealed_at": round(time.time(), 6),
        "journal_sha256": _sha256(evidence_dir / "journal.jsonl"),
        "journal_entries": len(lines),
        "head_hash": json.loads(lines[-1])["entry_hash"] if lines else "0" * 64,
        "request_stats": stats,
    }
    (evidence_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                                                encoding="utf-8")
    return manifest


def main() -> int:
    manifest = export()
    print(json.dumps({"exported_entries": manifest["journal_entries"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
