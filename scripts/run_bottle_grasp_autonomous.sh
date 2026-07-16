#!/usr/bin/env bash
set -euo pipefail

# 从头部相机开始的全自主流程：头部粗定位 → MoveIt自主规划到右腕观察位 →
# 腕部精定位 → 抓取。--autonomous-observation 会强制忽略 profile 里配置的
# 示教走廊，走真正的自主规划——用于验证"目标几何简单（如瓶子放桌角）时
# 能否不靠示教"。
#
# 安全提醒：MoveIt 自身的碰撞检查目前是坏的（见 docs/bottle_grasp_demo_runbook.md
# 第五节）。这条自主规划路径真正的安全网是电子围栏离线复核——MoveIt规划完的
# 每一条轨迹，执行前都会被独立的密集插值FK逐点校验（不依赖MoveIt的碰撞判断），
# 一旦违规直接安全中止、不会执行。但这层复核只挡得住"越过配置好的桌面禁入区/
# 工作空间"，挡不住"撞到没建模的东西"（比如显示器、其他物体）——这就是为什么
# 瓶子放桌角、周围清空能明显降低风险，但不是零风险。
#
# 用法（在 Mac 上执行，自动同步代码到机器人并远程运行）：
#   scripts/run_bottle_grasp_autonomous.sh plan     # 纯离线：头部定位+MoveIt规划，不动机器人
#   scripts/run_bottle_grasp_autonomous.sh observe  # 真机移动到观察位+腕部定位，不抓取
#   scripts/run_bottle_grasp_autonomous.sh grasp    # 真机抓取+抬升，保持
#   scripts/run_bottle_grasp_autonomous.sh cycle    # 真机抓取+抬升+放回+退开
#
# 建议顺序：先 plan 看MoveIt规划出的路径点数/耗时是否正常 → observe 看真机
# 移动到观察位、瓶子能不能被腕部相机稳定检测到 → 确认无误后再 grasp/cycle。

ROBOT_HOST="${ROBOT_HOST:-rm@192.168.3.68}"
REMOTE_DIR="${REMOTE_DIR:-/home/rm/Grabber}"
REMOTE_PY="${REMOTE_PY:-/home/rm/miniconda3/envs/tube_vision/bin/python}"
SAFETY_PROFILE="${SAFETY_PROFILE:-table_demo}"
PORT="${PORT:-8879}"

MODE="${1:-}"
case "${MODE}" in
  plan)    EXTRA_ARGS="--plan-only" ;;
  observe) EXTRA_ARGS="--execute --stop-after-observation" ;;
  grasp)   EXTRA_ARGS="--execute" ;;
  cycle)   EXTRA_ARGS="--execute --place-back" ;;
  *)
    echo "用法: $0 {plan|observe|grasp|cycle}"
    exit 1
    ;;
esac

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "== 同步 bottle_grasp 代码到机器人 =="
rsync -az "${SCRIPT_DIR}/../bottle_grasp/" "${ROBOT_HOST}:${REMOTE_DIR}/bottle_grasp/"
rsync -az "${SCRIPT_DIR}/bottle_grasp_demo.py" "${ROBOT_HOST}:${REMOTE_DIR}/scripts/bottle_grasp_demo.py"

if [[ "${MODE}" != "plan" ]]; then
  echo ""
  echo "!! 即将真机移动（自主MoveIt规划，非示教走廊）。确认瓶子放在桌角、"
  echo "   周围空旷，有人守硬件急停。按 Enter 继续，Ctrl+C 取消 !!"
  read -r
fi

echo "== 运行 (${MODE}, 自主观察位规划) =="
# shellcheck disable=SC2029
ssh -tt "${ROBOT_HOST}" \
  "cd '${REMOTE_DIR}' && '${REMOTE_PY}' scripts/bottle_grasp_demo.py \
     --autonomous-observation ${EXTRA_ARGS} \
     --safety-profile '${SAFETY_PROFILE}' --port '${PORT}' \
     2>&1 | tee outputs/bottle_grasp/latest.log | grep -v '丢弃'"
