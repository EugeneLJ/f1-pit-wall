#!/bin/bash
# Build the integrated SOLO_COORDINATION Harbor task (benchmark 2.0.1 by default, or 2.1.0) from the 1.1.0 task
# plus integrated_task/ overlay. The 1.1.0 task directory itself is never modified.
# Usage: scripts/make_integrated_task.sh <dest-dir> [engineer-condition] [benchmark-version: 2.0.1|2.1.0]
set -euo pipefail
TASK="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$1"
COND="${2:-MOCK_ENGINEERS}"
VERSION="${3:-2.0.1}"
rm -rf "$DEST"
mkdir -p "$DEST"
cp -R "$TASK/environment" "$TASK/tests" "$TASK/solution" "$DEST/"
cp "$TASK/task.toml" "$DEST/task.toml"
# Instruction. The submitted 2.1.0 CHIEF_ONLY task uses the standalone revision r2
# (integrated_task/instruction_2_1_0_chief_only.md). F1_INSTRUCTION_REVISION=r1 rebuilds the exact
# instruction the first 2.1.0 Harbor runs were evaluated on (integrated_task/evaluated/, sha256 f6697c53...).
# Other versions and Engineer conditions keep the composed instruction unchanged.
REVISION="${F1_INSTRUCTION_REVISION:-r2}"
if [ "$VERSION" = "2.1.0" ] && [ "$COND" = "CHIEF_ONLY" ] && [ "$REVISION" = "r2" ]; then
  cp "$TASK/integrated_task/instruction_2_1_0_chief_only.md" "$DEST/instruction.md"
elif [ "$VERSION" = "2.1.0" ] && [ "$COND" = "CHIEF_ONLY" ] && [ "$REVISION" = "r1" ]; then
  cp "$TASK/integrated_task/evaluated/instruction_2_1_0_r1.md" "$DEST/instruction.md"
else
  cat "$TASK/instruction.md" "$TASK/integrated_task/instruction_addendum.md" > "$DEST/instruction.md"
  if [ "$VERSION" = "2.1.0" ]; then
    cat "$TASK/integrated_task/instruction_addendum_2_1_0.md" >> "$DEST/instruction.md"
  fi
fi
O="$TASK/integrated_task"
cp "$O/sim/f1sim/"*.py "$DEST/environment/sim/f1sim/"
printf '{"mode": "SOLO_COORDINATION", "engineers": "%s", "benchmark_version": "%s"}\n' "$COND" "$VERSION" > "$DEST/environment/sim/secret/mode.json"
cp "$DEST/environment/sim/secret/mode.json" "$DEST/tests/mode.json"
for target in "$DEST/environment/sim" "$DEST/tests"; do
  rm -rf "$target/track_c"; mkdir -p "$target/track_c"
  cp "$TASK/track_c/"*.py "$target/track_c/"; cp -R "$TASK/track_c/fixtures" "$target/track_c/"
done
cp "$O/tests/grade_integrated.py" "$O/tests/test.sh" "$DEST/tests/"
cp "$O/solution/play_integrated.py" "$O/solution/solve.sh" "$O/solution/reference_v21.py" "$DEST/solution/"
cp "$TASK/src/f1pitwall/integrated/policies.py" "$DEST/solution/policies.py"
python3 - "$DEST" "$VERSION" <<'PY'
import sys
from pathlib import Path
dest = Path(sys.argv[1])
docker = dest / "environment/sim/Dockerfile"
text = docker.read_text()
text = text.replace("COPY f1sim /opt/f1sim/f1sim\n", "COPY f1sim /opt/f1sim/f1sim\nCOPY track_c /opt/f1sim/track_c\n", 1)
text = text.replace("COPY secret/seed.json /opt/f1sim/secret/seed.json\n",
                    "COPY secret/seed.json /opt/f1sim/secret/seed.json\nCOPY secret/mode.json /opt/f1sim/secret/mode.json\n", 1)
text = text.replace("&& chmod 0600 /opt/f1sim/secret/seed.json", "&& chmod 0600 /opt/f1sim/secret/seed.json /opt/f1sim/secret/mode.json", 1)
text = text.replace('CMD ["python3", "-m", "f1sim.server"]', 'CMD ["python3", "-m", "f1sim.integrated_server"]', 1)
docker.write_text(text)
toml = dest / "task.toml"
text = toml.read_text()
text = text.replace('name = "EugeneLJ/f1-championship"', 'name = "EugeneLJ/f1-championship-integrated"', 1)
text = text.replace('version = "1.1.0"', f'version = "{sys.argv[2]}"', 1)
text = text.replace('command = "python3 -m f1sim.export"', 'command = "python3 -m f1sim.export_integrated"', 1)
toml.write_text(text)
for path, needle in ((docker, "f1sim.integrated_server"), (toml, sys.argv[2]), (toml, "export_integrated")):
    assert needle in path.read_text(), (path, needle)
PY
echo "integrated task ($COND, $VERSION) at $DEST"
