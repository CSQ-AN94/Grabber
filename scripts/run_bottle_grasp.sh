#!/usr/bin/env bash
set -euo pipefail

# The only public real-robot bottle task launcher.
#
#   from-observation: right arm is already at a usable wrist observation pose;
#                     fresh head+wrist lock -> grasp -> lift -> place -> retreat
#   from-start:       fresh head lock -> MoveIt transfer to observation pose ->
#                     the same grasp/place tail -> return to configured home

ROBOT_HOST="${ROBOT_HOST:-rm@192.168.3.68}"
REMOTE_DIR="${REMOTE_DIR:-/home/rm/Grabber}"
REMOTE_PY="${REMOTE_PY:-/home/rm/miniconda3/envs/tube_vision/bin/python}"
SAFETY_PROFILE="${SAFETY_PROFILE:-table_demo}"
PORT="${PORT:-8879}"

usage() {
  echo "用法: $0 {from-observation|from-start}"
  echo "  from-observation  右臂已经在观察位，从本轮新鲜定位开始完整抓放"
  echo "  from-start        从固定头部定位开始完整抓放并返回初始姿态"
}

fail_config() {
  echo "启动参数无效: $1" >&2
  exit 1
}

if [[ "$#" -ne 1 ]]; then
  usage >&2
  exit 1
fi

# These values are later embedded in rsync/SSH destinations and a remote shell
# command.  Keep the supported override surface deliberately narrow instead of
# accepting whitespace, quotes or shell metacharacters.
if [[ ! "${ROBOT_HOST}" =~ ^([A-Za-z0-9][A-Za-z0-9._-]*@)?[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  fail_config "ROBOT_HOST 只允许 SSH 用户、主机名或 IPv4 地址"
fi
if [[ ! "${REMOTE_DIR}" =~ ^/[A-Za-z0-9._/-]+$ ]]; then
  fail_config "REMOTE_DIR 必须是不含空格/引号的绝对路径"
fi
if [[ ! "${REMOTE_PY}" =~ ^/[A-Za-z0-9._/-]+$ ]]; then
  fail_config "REMOTE_PY 必须是不含空格/引号的绝对路径"
fi
if [[ ! "${SAFETY_PROFILE}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  fail_config "SAFETY_PROFILE 只允许字母、数字、点、下划线和连字符"
fi
if [[ ! "${PORT}" =~ ^[0-9]+$ ]]; then
  fail_config "PORT 必须是 1-65535 的整数"
fi
if ((10#${PORT} < 1 || 10#${PORT} > 65535)); then
  fail_config "PORT 必须是 1-65535 的整数"
fi

MODE="$1"
case "${MODE}" in
  from-observation)
    MODE_NOTE="当前右臂观察位 -> 抓取 -> 抬升 -> 放回 -> 退开"
    ;;
  from-start)
    MODE_NOTE="头部定位 -> 避障到观察位 -> 抓取 -> 抬升 -> 放回 -> 返回初始姿态"
    ;;
  *)
    usage >&2
    exit 1
    ;;
esac

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SSH_OPTIONS=(
  -o ConnectTimeout=8
  -o ServerAliveInterval=10
  -o ServerAliveCountMax=3
)
RSYNC_SSH="ssh -o ConnectTimeout=8 -o ServerAliveInterval=10 -o ServerAliveCountMax=3"

echo "== 同步当前 bottle task 代码到机器人（不删除远端文件） =="
(
  cd "${SCRIPT_DIR}/.."
  rsync -azR --timeout=30 -e "${RSYNC_SSH}" \
    --exclude='__pycache__/' --exclude='*.pyc' \
    bottle_grasp/ \
    scripts/bottle_grasp_demo.py \
    scripts/run_bottle_grasp_autonomous.sh \
    scripts/run_bottle_grasp_resume.sh \
    scripts/start_bottle_demo.sh \
    sensors/camera_thread.py \
    "${ROBOT_HOST}:${REMOTE_DIR}/"
)

echo
echo "!! 即将执行真机任务: ${MODE_NOTE}"
echo "   确认桌面/瓶子布置正确、机械臂周围清空，并且有人手放在硬件急停上。"
echo "   按 Enter 启动；Ctrl+C 取消。"
read -r

echo "== 相机占用预检（头部 + 右腕） =="
# shellcheck disable=SC2029
ssh "${SSH_OPTIONS[@]}" -tt "${ROBOT_HOST}" \
  "cd '${REMOTE_DIR}' && \
   '${REMOTE_PY}' -m bottle_grasp.camera_access \
     --config config.yaml --camera head --camera right_wrist --no-probe"

echo "== 运行完整任务: ${MODE} =="
# Python already writes latest.log plus the immutable per-run evidence bundle;
# do not tee into latest.log a second time from the shell.
# shellcheck disable=SC2029
ssh "${SSH_OPTIONS[@]}" -tt "${ROBOT_HOST}" \
  "cd '${REMOTE_DIR}' && \
   '${REMOTE_PY}' scripts/bottle_grasp_demo.py \
     --execute --task-mode '${MODE}' \
     --safety-profile '${SAFETY_PROFILE}' --port '${PORT}'"
