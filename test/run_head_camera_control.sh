#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
CAMERA=${1:-/dev/video4}
HOST=${HOST:-0.0.0.0}
PORT=${PORT:-8765}

cd "$SCRIPT_DIR"

echo "Starting head camera control"
echo "  camera: $CAMERA"
echo "  url   : http://192.168.3.68:$PORT"
echo ""

exec python3 head_camera_control.py --camera "$CAMERA" --host "$HOST" --port "$PORT"
