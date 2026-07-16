#!/usr/bin/env bash
set -euo pipefail

# 复现 2026-07-16 首次成功抓取的标准流程（续抓模式，从观察位开始）。
#
# 前置条件（缺一不可）：
#   1. 右臂已处于观察位：腕部相机距瓶约 30cm，瓶子完整、居中出现在画面里
#      （用 scripts/wrist_camera_server.py 起直播，浏览器开 http://<robot>:8875 对照拖动）
#   2. 瓶子放稳、周围 15cm 无遮挡
#   3. 有人守在硬件急停旁
#   4. bottle_grasp/safety_profiles.json 的 table_demo 桌面禁入区与实际桌面一致
#      （桌子挪过就要重新量：头部深度实测桌面 z，改 keepout min/max）
#
# 用法（在 Mac 上执行，自动同步代码到机器人并远程运行）：
#   scripts/run_bottle_grasp_resume.sh check   # 第1步：无运动视觉确认（必须先跑）
#   scripts/run_bottle_grasp_resume.sh grasp   # 第2步：抓取+抬升5cm+保持
#   scripts/run_bottle_grasp_resume.sh cycle   # 第2步替代：抓取+抬升+放回+退开
#
# check 通过标准：日志出现 "共识帧 7/7" 且散布 < 5mm。
# 任何一步安全中止后：看日志最后的 ERROR 行，对照 docs/bottle_grasp_demo_runbook.md 排查表。

ROBOT_HOST="${ROBOT_HOST:-rm@192.168.3.68}"
REMOTE_DIR="${REMOTE_DIR:-/home/rm/Grabber}"
REMOTE_PY="${REMOTE_PY:-/home/rm/miniconda3/envs/tube_vision/bin/python}"
SAFETY_PROFILE="${SAFETY_PROFILE:-table_demo}"
PORT="${PORT:-8879}"

MODE="${1:-}"
case "${MODE}" in
  check) EXTRA_ARGS="--stop-after-observation --observe-seconds 2" ;;
  grasp) EXTRA_ARGS="" ;;
  cycle) EXTRA_ARGS="--place-back" ;;
  *)
    echo "用法: $0 {check|grasp|cycle}"
    echo "  check = 无运动视觉确认；grasp = 抓取并保持；cycle = 抓取后放回退开"
    exit 1
    ;;
esac

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "== 同步 bottle_grasp 代码到机器人 =="
rsync -az "${SCRIPT_DIR}/../bottle_grasp/" "${ROBOT_HOST}:${REMOTE_DIR}/bottle_grasp/"
rsync -az "${SCRIPT_DIR}/bottle_grasp_demo.py" "${ROBOT_HOST}:${REMOTE_DIR}/scripts/bottle_grasp_demo.py"

if [[ "${MODE}" != "check" ]]; then
  echo ""
  echo "!! 即将执行真机运动（3% 低速）。确认有人守在急停旁，按 Enter 继续，Ctrl+C 取消 !!"
  read -r
fi

echo "== 运行 (${MODE}) =="
# shellcheck disable=SC2029
ssh -tt "${ROBOT_HOST}" \
  "cd '${REMOTE_DIR}' && '${REMOTE_PY}' scripts/bottle_grasp_demo.py \
     --execute --resume-at-wrist ${EXTRA_ARGS} \
     --safety-profile '${SAFETY_PROFILE}' --port '${PORT}' \
     2>&1 | tee outputs/bottle_grasp/latest.log | grep -v '丢弃'"
