#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BRIDGE_PYTHON="${FLY_BRIDGE_PYTHON:-$REPO_ROOT/.venv-bridge/bin/python}"
BRAIN_PYTHON="${FLY_BRAIN_PYTHON:-}"
CONVERSATION_MODE="mock"
KEY_FILE=""
LAUNCH_BRAIN=1

usage() {
    cat <<'EOF'
Usage: tools/Start-MacLocal.sh [options]

Starts the Mac-local MaleCNS Brain and Flylingual Bridge in the foreground.

Options:
  --conversation MODE  off, mock (default), or live
  --live               shorthand for --conversation live
  --key-file PATH      single-line OpenAI key file for live mode
  --brain-python PATH  Python executable for the Brain runtime
  --bridge-only        connect to an already-running local Brain; do not launch one
  -h, --help           show this help

Environment:
  FLY_BRIDGE_PYTHON    override the Bridge virtualenv Python
  FLY_BRAIN_PYTHON     override the Brain runtime Python
EOF
}

while (($# > 0)); do
    case "$1" in
        --conversation)
            if (($# < 2)); then
                echo "error: --conversation requires off, mock, or live" >&2
                exit 2
            fi
            CONVERSATION_MODE="$2"
            shift 2
            ;;
        --live)
            CONVERSATION_MODE="live"
            shift
            ;;
        --key-file)
            if (($# < 2)); then
                echo "error: --key-file requires a path" >&2
                exit 2
            fi
            KEY_FILE="$2"
            shift 2
            ;;
        --brain-python)
            if (($# < 2)); then
                echo "error: --brain-python requires a path" >&2
                exit 2
            fi
            BRAIN_PYTHON="$2"
            shift 2
            ;;
        --bridge-only)
            LAUNCH_BRAIN=0
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "error: unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

case "$CONVERSATION_MODE" in
    off|mock|live) ;;
    *)
        echo "error: conversation must be off, mock, or live" >&2
        exit 2
        ;;
esac

if [[ ! -x "$BRIDGE_PYTHON" ]]; then
    cat >&2 <<EOF
error: Bridge Python was not found: $BRIDGE_PYTHON
Run the one-time setup from Docs/mac/Mac-Startup-Handoff.md, or set FLY_BRIDGE_PYTHON.
EOF
    exit 2
fi

if [[ -z "$BRAIN_PYTHON" ]]; then
    for candidate in \
        "$REPO_ROOT/.venv-brain/bin/python" \
        "${HOME}/miniforge3/envs/flybrain-malecns/bin/python" \
        "${HOME}/miniforge3/envs/brian2/bin/python"; do
        if [[ -x "$candidate" ]]; then
            BRAIN_PYTHON="$candidate"
            break
        fi
    done
fi

if [[ "$LAUNCH_BRAIN" -eq 1 ]]; then
    if [[ -z "$BRAIN_PYTHON" || ! -x "$BRAIN_PYTHON" ]]; then
        cat >&2 <<EOF
error: Brain Python was not found.
Install Brain/MaleCNS/requirements-runtime.txt into a Python 3.10 environment,
then set FLY_BRAIN_PYTHON or pass --brain-python PATH.
EOF
        exit 2
    fi
    "$BRAIN_PYTHON" - <<'PY'
import importlib.util
import sys

missing = [name for name in ("numpy", "numba", "llvmlite", "psutil")
           if importlib.util.find_spec(name) is None]
if missing:
    print("error: Brain Python is missing: " + ", ".join(missing), file=sys.stderr)
    raise SystemExit(2)
PY
fi

doctor_args=(
    doctor
    --profile mac-local
    --conversation "$CONVERSATION_MODE"
    --brain-python "${BRAIN_PYTHON:-$BRIDGE_PYTHON}"
)
if [[ -n "$KEY_FILE" ]]; then
    doctor_args+=(--key-file "$KEY_FILE")
fi

echo "[Flylingual] Mac-local doctor: profile=mac-local conversation=$CONVERSATION_MODE"
"$BRIDGE_PYTHON" "$REPO_ROOT/tools/dev.py" "${doctor_args[@]}" >/dev/null

up_args=(
    up
    --profile mac-local
    --conversation "$CONVERSATION_MODE"
    --brain-python "${BRAIN_PYTHON:-$BRIDGE_PYTHON}"
)
if [[ "$LAUNCH_BRAIN" -eq 1 ]]; then
    up_args+=(--launch-brain)
fi
if [[ -n "$KEY_FILE" ]]; then
    up_args+=(--key-file "$KEY_FILE")
fi

cat <<EOF
[Flylingual] Mac-local starting
  profile:       mac-local
  conversation:  $CONVERSATION_MODE
  Brain:         $([[ "$LAUNCH_BRAIN" -eq 1 ]] && echo launch-owned || echo bridge-only)
  Brain TCP:     127.0.0.1:8766
  Bridge TCP:    127.0.0.1:8770
  Bridge UI:     http://127.0.0.1:8771/
  Stop:          Ctrl-C (only this launcher's own Brain is stopped)
EOF

cd "$REPO_ROOT"
exec "$BRIDGE_PYTHON" "$REPO_ROOT/tools/dev.py" "${up_args[@]}"
