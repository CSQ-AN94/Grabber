#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON=/home/rm/miniconda3/bin/python

if [ ! -x "$PYTHON" ]; then
  echo "ERROR: $PYTHON not found or not executable" >&2
  exit 1
fi

exec "$PYTHON" "$SCRIPT_DIR/test_head_servo.py"
