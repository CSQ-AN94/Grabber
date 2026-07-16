#!/usr/bin/env bash
set -euo pipefail

# 完整循环一键脚本：垂下 → 观察位 → 抓取 → 抬升 → 放回 → 垂回垂下姿态。
# 转移段走一条【你录制的】示教走廊（人工示教、离线电子围栏逐点复核）。
#
# 明天上机的最短路径（每步都在下面有对应子命令）：
#   1) record   一次性录制『垂下→观察位』安全走廊（拖动示教，约5分钟，可复用）
#   2) plan     纯离线复核走廊+头部检测，不动机器人（先确认没报错）
#   3) cycle    真机跑完整一轮（有人守急停）
#
# 附带诊断（想上全自主转移时才需要）：
#   selftest    判定 MoveIt 碰撞检查是否已修好（决定能否用 --autonomous-transit）
#
# 用法：scripts/run_bottle_full_cycle.sh {record|plan|cycle|selftest}

ROBOT_HOST="${ROBOT_HOST:-rm@192.168.3.68}"
REMOTE_DIR="${REMOTE_DIR:-/home/rm/Grabber}"
REMOTE_PY="${REMOTE_PY:-/home/rm/miniconda3/envs/tube_vision/bin/python}"
SAFETY_PROFILE="${SAFETY_PROFILE:-table_demo}"
PORT="${PORT:-8879}"
# 示教走廊：首点=垂下起始姿态，末点=右腕观察位。record 会写到这里，plan/cycle 会读它。
CORRIDOR="${CORRIDOR:-outputs/bottle_grasp/guided_paths/hang_to_observe_right.json}"
ROS_PREFIX="source /opt/ros/humble/setup.bash && source /home/rm/ros2_ws/install/setup.bash &&"

MODE="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

sync_code() {
  echo "== 同步 bottle_grasp 代码到机器人 =="
  rsync -az "${SCRIPT_DIR}/../bottle_grasp/" "${ROBOT_HOST}:${REMOTE_DIR}/bottle_grasp/"
  rsync -az "${SCRIPT_DIR}/bottle_grasp_demo.py" "${ROBOT_HOST}:${REMOTE_DIR}/scripts/bottle_grasp_demo.py"
  rsync -az "${SCRIPT_DIR}/record_right_arm_guided_path.py" "${ROBOT_HOST}:${REMOTE_DIR}/scripts/record_right_arm_guided_path.py"
}

case "${MODE}" in
  record)
    sync_code
    echo ""
    echo "== 录制示教走廊 =="
    echo "步骤：先把右臂拖到【垂下起始姿态】，然后按住末端绿色按钮，"
    echo "     从垂下姿态缓慢、走安全路线（远离桌面）拖到【右腕观察位】"
    echo "     （腕部相机距瓶约30cm、瓶子完整居中入镜），到位后回到这里 Ctrl+C 停录。"
    echo "     录制是只读的，不会驱动机器人。"
    echo ""
    read -r -p "准备好开始录制按 Enter..."
    # shellcheck disable=SC2029
    ssh -tt "${ROBOT_HOST}" \
      "cd '${REMOTE_DIR}' && '${REMOTE_PY}' scripts/record_right_arm_guided_path.py --output '${CORRIDOR}'"
    echo "已保存走廊到 ${REMOTE_DIR}/${CORRIDOR}"
    ;;

  plan)
    sync_code
    echo "== 完整循环 plan-only（不动机器人，离线复核走廊+头部检测）=="
    # shellcheck disable=SC2029
    ssh -tt "${ROBOT_HOST}" \
      "cd '${REMOTE_DIR}' && '${REMOTE_PY}' scripts/bottle_grasp_demo.py \
         --plan-only --full-cycle --guided-path '${CORRIDOR}' \
         --safety-profile '${SAFETY_PROFILE}' --port '${PORT}' --observe-seconds 2 \
         2>&1 | tee outputs/bottle_grasp/latest.log | grep -v '丢弃'"
    ;;

  cycle)
    sync_code
    echo ""
    echo "!! 即将真机执行完整一轮（3% 低速）。确认：瓶子放稳、右臂在垂下起始姿态附近、"
    echo "   有人守硬件急停。按 Enter 继续，Ctrl+C 取消 !!"
    read -r
    # shellcheck disable=SC2029
    ssh -tt "${ROBOT_HOST}" \
      "cd '${REMOTE_DIR}' && '${REMOTE_PY}' scripts/bottle_grasp_demo.py \
         --execute --full-cycle --place-back --guided-path '${CORRIDOR}' \
         --safety-profile '${SAFETY_PROFILE}' --port '${PORT}' \
         2>&1 | tee outputs/bottle_grasp/latest.log | grep -v '丢弃'"
    ;;

  selftest)
    sync_code
    echo "== MoveIt 碰撞检查自检（需要 move_group 已在运行）=="
    echo "  若未运行 move_group，先在机器人另开一个终端："
    echo "    ${ROS_PREFIX} python3 bottle_grasp/moveit_headless.py"
    # shellcheck disable=SC2029
    ssh -tt "${ROBOT_HOST}" \
      "cd '${REMOTE_DIR}' && ${ROS_PREFIX} python3 bottle_grasp/moveit_collision_selftest.py"
    ;;

  *)
    echo "用法: $0 {record|plan|cycle|selftest}"
    echo "  record   = 录制『垂下→观察位』示教走廊（一次性，可复用）"
    echo "  plan     = 完整循环 plan-only 离线复核（不动机器人）"
    echo "  cycle    = 真机跑完整一轮（垂下→抓取→放回→垂回）"
    echo "  selftest = 判定 MoveIt 碰撞检查是否已修好"
    exit 1
    ;;
esac
