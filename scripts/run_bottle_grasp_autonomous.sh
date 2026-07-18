#!/usr/bin/env bash
set -euo pipefail

# 从头部相机开始的全自主流程（当前唯一的完整流程，示教走廊已移除）：
# 头部粗定位 → MoveIt 自主规划到右腕观察位 → 腕部精定位 → 夹爪空夹基线
# 标定 → 直线分段接近 → 力控夹取 → 抬升 → 放回+退开 → MoveIt 规划返回初始
# 姿态（cycle 模式）。
#
# 安全链：MoveIt 全臂碰撞规划 → MoveIt 密集状态后验复核 → 独立电子围栏密集
# TCP 复核。围栏拒绝会反馈成临时碰撞盒并自动换路线/观察端点，所有候选都失败
# 才中止。2026-07-17 巨型盒子 selftest 已实测 MoveIt 世界碰撞检查工作正常。
# 这些检查仍然只能避开已建模的物体；显示器、杂物等未进入场景时无法自动避让，
# 所以运行前仍须清空周围并由人守急停。
#
# 2026-07-18：头部定位阶段（plan/observe/grasp/cycle，不含 finish）现在
# 每轮从头部点云实测桌面并在 ±12cm 内自适应 table_top 电子围栏（跟着底盘
# 停靠位置走），超出容差会直接拒跑并提示重新测量——不再需要底盘小幅挪动
# 就手动改 safety_profiles.json。日志里找"桌面围栏自适应"这条 stage 确认
# 生效。run_bottle_grasp_resume.sh（跳过头部相机的续抓模式）不受益于这项，
# 它仍按原来的方式依赖静态围栏配置。
#
# 用法（在 Mac 上执行，自动同步代码到机器人并远程运行）：
#   scripts/run_bottle_grasp_autonomous.sh plan     # 纯离线：头部定位+MoveIt规划，不动机器人
#   scripts/run_bottle_grasp_autonomous.sh observe  # 真机移动到观察位+腕部定位，不抓取
#   scripts/run_bottle_grasp_autonomous.sh grasp    # 真机抓取+抬升，保持
#   scripts/run_bottle_grasp_autonomous.sh cycle    # 真机抓取+抬升+放回+退开+返回初始姿态
#   scripts/run_bottle_grasp_autonomous.sh finish   # 夹爪已抓着水瓶（上一轮遗留）：跳过定位/抓取，直接放回+返回初始姿态
#   scripts/run_bottle_grasp_autonomous.sh selftest # 判定 MoveIt 碰撞检查是否已修好
#
# 建议顺序：先 plan 看MoveIt规划出的路径点数/耗时是否正常 → observe 看真机
# 移动到观察位、瓶子能不能被腕部相机稳定检测到 → 确认无误后再 grasp/cycle。

ROBOT_HOST="${ROBOT_HOST:-rm@192.168.3.68}"
REMOTE_DIR="${REMOTE_DIR:-/home/rm/Grabber}"
REMOTE_PY="${REMOTE_PY:-/home/rm/miniconda3/envs/tube_vision/bin/python}"
SAFETY_PROFILE="${SAFETY_PROFILE:-table_demo}"
PORT="${PORT:-8879}"
ROS_PREFIX="source /opt/ros/humble/setup.bash && source /home/rm/ros2_ws/install/setup.bash &&"

MODE="${1:-}"
case "${MODE}" in
  plan)     EXTRA_ARGS="--plan-only"; CAMERA_ARGS="--camera head" ;;
  observe)  EXTRA_ARGS="--execute --stop-after-observation"; CAMERA_ARGS="--camera head --camera right_wrist" ;;
  grasp)    EXTRA_ARGS="--execute"; CAMERA_ARGS="--camera head --camera right_wrist" ;;
  cycle)    EXTRA_ARGS="--execute --place-back --return-home"; CAMERA_ARGS="--camera head --camera right_wrist" ;;
  finish)   EXTRA_ARGS="--execute --finish-from-current --place-back --return-home"; CAMERA_ARGS="--camera right_wrist" ;;
  selftest) EXTRA_ARGS="" ;;
  *)
    echo "用法: $0 {plan|observe|grasp|cycle|finish|selftest}"
    exit 1
    ;;
esac

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "== 同步 bottle_grasp 代码到机器人 =="
(
  cd "${SCRIPT_DIR}/.."
  rsync -azR --exclude='__pycache__/' --exclude='*.pyc' \
    bottle_grasp/ scripts/bottle_grasp_demo.py sensors/camera_thread.py \
    "${ROBOT_HOST}:${REMOTE_DIR}/"
)

if [[ "${MODE}" == "selftest" ]]; then
  echo "== MoveIt 碰撞检查自检（自动启动/清理只规划 move_group）=="
  # shellcheck disable=SC2029
  ssh -tt "${ROBOT_HOST}" \
    "cd '${REMOTE_DIR}' && ${ROS_PREFIX} python3 bottle_grasp/moveit_collision_selftest.py"
  exit 0
fi

if [[ "${MODE}" != "plan" ]]; then
  echo ""
  echo "!! 即将真机移动（自主MoveIt规划）。确认瓶子放在桌角、周围空旷，"
  echo "   有人守硬件急停。按 Enter 继续，Ctrl+C 取消 !!"
  read -r
fi

echo "== 运行 (${MODE}, 自主观察位规划) =="
# shellcheck disable=SC2029
ssh -tt "${ROBOT_HOST}" \
  "set -o pipefail; cd '${REMOTE_DIR}' && \
   '${REMOTE_PY}' -m bottle_grasp.camera_access \
     --config config.yaml ${CAMERA_ARGS} --no-probe && \
   '${REMOTE_PY}' scripts/bottle_grasp_demo.py \
     ${EXTRA_ARGS} \
     --safety-profile '${SAFETY_PROFILE}' --port '${PORT}' \
     2>&1 | tee outputs/bottle_grasp/latest.log | grep -v '丢弃'"
