#!/bin/bash
# Build a copy of the task that differs ONLY in its hidden evaluation seed.
# Usage: scripts/make_seed_variant.sh <dest-dir> <base_seed> <task-name-suffix>
# The seed goes into the sim image (environment/sim/secret/seed.json) and the verifier
# image (tests/hidden_seed.json); rules, instruction, tools and Harbor config are unchanged.
set -euo pipefail
TASK="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$1"
SEED="$2"
SUFFIX="$3"
rm -rf "$DEST"
mkdir -p "$DEST"
cp -R "$TASK/instruction.md" "$TASK/task.toml" "$TASK/environment" "$TASK/tests" "$TASK/solution" "$DEST/"
printf '{"schema_version": 1, "base_seed": %s}\n' "$SEED" > "$DEST/environment/sim/secret/seed.json"
cp "$DEST/environment/sim/secret/seed.json" "$DEST/tests/hidden_seed.json"
python3 - "$DEST/task.toml" "$SUFFIX" <<'PY'
import sys
from pathlib import Path
path, suffix = Path(sys.argv[1]), sys.argv[2]
text = path.read_text()
text = text.replace('name = "EugeneLJ/f1-championship"', f'name = "EugeneLJ/f1-championship-{suffix}"', 1)
path.write_text(text)
PY
diff -rq "$TASK/instruction.md" "$DEST/instruction.md"
echo "seed variant $SUFFIX at $DEST"
