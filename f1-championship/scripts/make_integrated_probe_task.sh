#!/bin/bash
# Build an adversarial copy of the integrated Harbor task whose "oracle" is the boundary probe.
# Usage: scripts/make_integrated_probe_task.sh <dest-dir> <complete|stop> [benchmark-version, default 2.1.0]
# Same construction as make_probe_task.sh (1.1.0): the probe runs as root to show the boundary does
# not rely on USER node. Sidecar, verifier and reward are the unmodified integrated task.
set -euo pipefail
TASK="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$1"
MODE="${2:-complete}"
VERSION="${3:-2.1.0}"
"$TASK/scripts/make_integrated_task.sh" "$DEST" CHIEF_ONLY "$VERSION" >/dev/null
rm -rf "$DEST/solution"
mkdir -p "$DEST/solution"
cp "$TASK/src/f1pitwall/integrated/policies.py" "$TASK/probes/probe_integrated.py" "$DEST/solution/"
cat > "$DEST/solution/solve.sh" <<SH
#!/bin/bash
set -euo pipefail
python3 /solution/probe_integrated.py $MODE
SH
chmod +x "$DEST/solution/solve.sh"
python3 - "$DEST/task.toml" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
text = path.read_text()
text = text.replace('[agent]\n', '[agent]\nuser = "root"\n', 1)
text = text.replace('name = "EugeneLJ/f1-championship-integrated"', 'name = "EugeneLJ/f1-championship-integrated-probe"', 1)
assert 'user = "root"' in text and "integrated-probe" in text
path.write_text(text)
PY
echo "integrated probe task ($MODE, $VERSION) at $DEST"
