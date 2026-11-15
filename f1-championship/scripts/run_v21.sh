#!/bin/bash
# One command for the submitted benchmark 2.1.0 (SOLO_COORDINATION, CHIEF_ONLY):
# builds the Harbor task from this checkout, then runs it.
#
#   f1-championship/scripts/run_v21.sh oracle          # public-information reference (expected 289 pts, reward 0.7817)
#   f1-championship/scripts/run_v21.sh nop             # do-nothing baseline (season unfinished -> reward 0)
#   f1-championship/scripts/run_v21.sh probe-stop      # boundary attacks as root, two decisions, quits -> reward 0
#   f1-championship/scripts/run_v21.sh probe-complete  # same attacks, then finishes with the published baseline heuristic
#   GEMINI_ENV_FILE=<file with GEMINI_API_KEY=...> f1-championship/scripts/run_v21.sh opencode
#                                                      # frontier run: OpenCode + gemini/gemini-3.8-flash
#
# Extra arguments after the mode are passed to `harbor run` unchanged (e.g. --job-name x).
# Requirements: Harbor 0.26+, Docker with Compose, python3 on the host. Only `opencode` needs network
# access (to generativelanguage.googleapis.com) and an API key; the sim container never has network.
set -euo pipefail
TASK="$(cd "$(dirname "$0")/.." && pwd)"
MODE="${1:-}"
shift || true
BUILD="${F1_BUILD_DIR:-${TMPDIR:-/tmp}/f1-pit-wall-2.1.0}"
HARBOR="${F1_HARBOR_BIN:-harbor}"

case "$MODE" in
  oracle|nop|opencode)
    "$TASK/scripts/make_integrated_task.sh" "$BUILD/task" CHIEF_ONLY 2.1.0
    DIR="$BUILD/task" ;;
  probe-stop|probe-complete)
    "$TASK/scripts/make_integrated_probe_task.sh" "$BUILD/$MODE" "${MODE#probe-}" 2.1.0
    DIR="$BUILD/$MODE" ;;
  *)
    sed -n '2,15p' "$0" >&2
    exit 2 ;;
esac

case "$MODE" in
  oracle|probe-stop|probe-complete)
    exec "$HARBOR" run -p "$DIR" -a oracle "$@" ;;
  nop)
    exec "$HARBOR" run -p "$DIR" -a nop "$@" ;;
  opencode)
    if [ -z "${GEMINI_ENV_FILE:-}" ]; then
      echo "set GEMINI_ENV_FILE to a file containing GEMINI_API_KEY=..." >&2
      exit 2
    fi
    exec "$HARBOR" run -p "$DIR" -a opencode -m "${F1_MODEL:-gemini/gemini-3.8-flash}" \
      --api-key-name GEMINI_API_KEY --env-file "$GEMINI_ENV_FILE" \
      --allow-agent-host generativelanguage.googleapis.com "$@" ;;
esac
