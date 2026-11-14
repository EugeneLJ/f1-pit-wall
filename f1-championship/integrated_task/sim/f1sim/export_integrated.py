"""Collect hook (integrated mode): seal, then copy journal v2 and the Engineer record store
out of private state. Reads only the private state directory."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

from f1sim.export import EVIDENCE_DIR, STATE_DIR, _sha256, export


def export_integrated(state_dir: Path = STATE_DIR, evidence_dir: Path = EVIDENCE_DIR) -> dict:
    manifest = export(state_dir, evidence_dir)
    store = state_dir / "engineers"
    files = {}
    if store.exists():
        shutil.copytree(store, evidence_dir / "engineers")
        for path in sorted((evidence_dir / "engineers").rglob("*.jsonl")):
            files[path.relative_to(evidence_dir).as_posix()] = _sha256(path)
    from f1pitwall.integrated.config import INTEGRATED_VERSION
    manifest.update({"benchmark_version": INTEGRATED_VERSION, "server_version": INTEGRATED_VERSION,
                     "journal_version": 2, "engineer_record_files": files})
    (evidence_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    manifest = export_integrated()
    print(json.dumps({"exported_entries": manifest["journal_entries"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
