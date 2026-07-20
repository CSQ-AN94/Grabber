#!/usr/bin/env bash
set -euo pipefail

robot_host="${ROBOT_HOST:-rm@192.168.3.68}"

if ! battery_output="$(
  ssh -o ConnectTimeout=5 "$robot_host" \
    'LD_LIBRARY_PATH=/home/rm/rmc_aida_l_atom/lib/linux /home/rm/agv_debug_tools/agv_battery' \
    2>&1
)"; then
  printf '%s\n' "$battery_output" >&2
  exit 1
fi

printf '%s\n' "$battery_output" | sed -n \
  -e '/^电量：/p' \
  -e '/^充电状态：/p' \
  -e '/^健康度：/p' \
  -e '/^充电循环：/p' \
  -e '/^额定循环寿命：/p' \
  -e '/^最高温度：/p'
