#!/bin/bash
# Build an adversarial copy of the task whose "oracle" is the boundary probe.
# Usage: scripts/make_probe_task.sh <dest-dir> <complete|stop>
# The probe agent runs as root to show the boundary does not rely on USER node.
set -euo pipefail
TASK="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$1"
MODE="${2:-complete}"
rm -rf "$DEST"
mkdir -p "$DEST"
cp -R "$TASK/instruction.md" "$TASK/task.toml" "$TASK/environment" "$TASK/tests" "$DEST/"
mkdir -p "$DEST/solution"
cp "$TASK/solution/play.py" "$TASK/probes/probe.py" "$DEST/solution/"
cat > "$DEST/solution/solve.sh" <<EOF
#!/bin/bash
set -euo pipefail
python3 /solution/probe.py $MODE
EOF
chmod +x "$DEST/solution/solve.sh"
python3 - "$DEST/task.toml" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
text = path.read_text()
text = text.replace('[agent]\n', '[agent]\nuser = "root"\n', 1)
text = text.replace('name = "EugeneLJ/f1-championship"', 'name = "EugeneLJ/f1-championship-probe"', 1)
path.write_text(text)
PY
echo "probe task ($MODE) at $DEST"
