#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
CAMERA=${1:-head}
HOST=${HOST:-0.0.0.0}
PORT=${PORT:-8765}
FRAME_SOURCE=${FRAME_SOURCE:-shared}

cd "$SCRIPT_DIR"

echo "Starting head camera control"
echo "  camera: $CAMERA"
echo "  source: $FRAME_SOURCE"
echo "  url   : http://192.168.3.68:$PORT"
echo ""

exec python3 head_camera_control.py --camera "$CAMERA" --frame-source "$FRAME_SOURCE" --host "$HOST" --port "$PORT"
