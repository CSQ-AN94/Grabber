#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
CAMERA=${1:-head}

exec env FRAME_SOURCE=shared "$SCRIPT_DIR/run_head_camera_control.sh" "$CAMERA"
