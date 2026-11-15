#!/bin/bash
# Build the integrated SOLO_COORDINATION Harbor task (benchmark 2.0.1 by default, or 2.1.0) from the 1.1.0 task
# plus integrated_task/ overlay. The 1.1.0 task directory itself is never modified.
# Usage: scripts/make_integrated_task.sh <dest-dir> [engineer-condition] [benchmark-version: 2.0.1|2.1.0|2.2.0] [features: off|m2_m6_m7]
# 2.2.0 features default to the M2/M6/M7 integration candidate.
# F1_C5_WEEKEND=1 (requires 2.2.0, CHIEF_ONLY) adds the C5 practice/qualifying weekend; it composes with
# either feature setting. Without it every existing build is unchanged.
set -euo pipefail
TASK="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$1"
COND="${2:-MOCK_ENGINEERS}"
VERSION="${3:-2.0.1}"
DEFAULT_FEATURES="off"
if [ "$VERSION" = "2.2.0" ]; then
  DEFAULT_FEATURES="m2_m6_m7"
fi
FEATURES="${4:-$DEFAULT_FEATURES}"
if [ "$VERSION" != "2.2.0" ] && [ "$FEATURES" != "off" ]; then
  echo "M2/M6/M7 features require VERSION=2.2.0 (pass off for a legacy task)" >&2
  exit 2
fi
if [ "$FEATURES" != "off" ] && [ "$FEATURES" != "m2_m6_m7" ]; then
  echo "features must be off or m2_m6_m7" >&2
  exit 2
fi
rm -rf "$DEST"
mkdir -p "$DEST"
cp -R "$TASK/environment" "$TASK/tests" "$TASK/solution" "$DEST/"
cp "$TASK/task.toml" "$DEST/task.toml"
# Instruction. The submitted 2.1.0 CHIEF_ONLY task uses the standalone revision r2
# (integrated_task/instruction_2_1_0_chief_only.md). F1_INSTRUCTION_REVISION=r1 rebuilds the exact
# instruction the first 2.1.0 Harbor runs were evaluated on (integrated_task/evaluated/, sha256 f6697c53...).
# With C5 the instruction is the C5 section + r2 (+ the M2/M6/M7 addendum when those features are on).
REVISION="${F1_INSTRUCTION_REVISION:-r2}"
C5="${F1_C5_WEEKEND:-0}"
if [ "$C5" = "1" ] && { [ "$VERSION" != "2.2.0" ] || [ "$COND" != "CHIEF_ONLY" ]; }; then
  echo "F1_C5_WEEKEND=1 needs benchmark 2.2.0 and CHIEF_ONLY" >&2; exit 2
fi
if [ "$C5" = "1" ]; then
  cat "$TASK/integrated_task/instruction_2_2_0_c5.md" "$TASK/integrated_task/instruction_2_1_0_chief_only.md" > "$DEST/instruction.md"
  if [ "$FEATURES" = "m2_m6_m7" ]; then
    printf '\n' >> "$DEST/instruction.md"
    cat "$TASK/integrated_task/instruction_addendum_2_2_0.md" >> "$DEST/instruction.md"
  fi
elif [ "$VERSION" = "2.1.0" ] && [ "$COND" = "CHIEF_ONLY" ] && [ "$REVISION" = "r2" ]; then
  cp "$TASK/integrated_task/instruction_2_1_0_chief_only.md" "$DEST/instruction.md"
elif [ "$VERSION" = "2.1.0" ] && [ "$COND" = "CHIEF_ONLY" ] && [ "$REVISION" = "r1" ]; then
  cp "$TASK/integrated_task/evaluated/instruction_2_1_0_r1.md" "$DEST/instruction.md"
else
  cat "$TASK/instruction.md" "$TASK/integrated_task/instruction_addendum.md" > "$DEST/instruction.md"
  if [ "$VERSION" = "2.1.0" ]; then
    cat "$TASK/integrated_task/instruction_addendum_2_1_0.md" >> "$DEST/instruction.md"
  elif [ "$VERSION" = "2.2.0" ]; then
    cat "$TASK/integrated_task/instruction_addendum_2_2_0.md" >> "$DEST/instruction.md"
  fi
fi
O="$TASK/integrated_task"
cp "$O/sim/f1sim/"*.py "$DEST/environment/sim/f1sim/"
if [ "$C5" = "1" ]; then
  printf '{"mode": "SOLO_COORDINATION", "engineers": "%s", "benchmark_version": "%s", "c5_weekend": true}\n' "$COND" "$VERSION" > "$DEST/environment/sim/secret/mode.json"
else
  printf '{"mode": "SOLO_COORDINATION", "engineers": "%s", "benchmark_version": "%s"}\n' "$COND" "$VERSION" > "$DEST/environment/sim/secret/mode.json"
fi
cp "$DEST/environment/sim/secret/mode.json" "$DEST/tests/mode.json"
for target in "$DEST/environment/sim" "$DEST/tests"; do
  rm -rf "$target/track_c"; mkdir -p "$target/track_c"
  cp "$TASK/track_c/"*.py "$target/track_c/"; cp -R "$TASK/track_c/fixtures" "$target/track_c/"
  if [ "$VERSION" = "2.2.0" ]; then
    cp -R "$TASK/track_c/v22" "$target/track_c/"
  fi
  if [ "$C5" = "1" ]; then cp -R "$TASK/track_c/c5" "$target/track_c/"; fi
done
python3 - "$DEST" "$FEATURES" <<'PY'
import json
from pathlib import Path
import sys
root, features = Path(sys.argv[1]), sys.argv[2]
for name in ("environment/sim/secret/mode.json", "tests/mode.json"):
    path = root / name
    mode = json.loads(path.read_text())
    for key in ("m2_tendencies", "m6_compliance", "m7_weather"):
        mode[key] = features == "m2_m6_m7"
    path.write_text(json.dumps(mode, sort_keys=True) + "\n")
PY
cp "$O/tests/grade_integrated.py" "$O/tests/test.sh" "$DEST/tests/"
cp "$O/solution/play_integrated.py" "$O/solution/solve.sh" "$O/solution/reference_v21.py" "$DEST/solution/"
cp "$TASK/src/f1pitwall/integrated/policies.py" "$DEST/solution/policies.py"
if [ "$C5" = "1" ]; then  # no 2.2.0 reference exists yet: the oracle is the scripted coordinator + C5 smoke policy
  printf '#!/bin/bash\nset -euo pipefail\nexec python3 "$(cd "$(dirname "$0")" && pwd)/play_integrated.py"\n' > "$DEST/solution/solve.sh"
  chmod +x "$DEST/solution/solve.sh"
fi
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
