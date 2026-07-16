#!/usr/bin/env bash
set -euo pipefail

# One-click launcher for macOS. The repository is expected at REMOTE_DIR on the
# robot. Set EXECUTE=1 only after an observe-only run has passed.
ROBOT_HOST="${ROBOT_HOST:-rm@192.168.3.68}"
REMOTE_DIR="${REMOTE_DIR:-/home/rm/Grabber}"
REMOTE_PY="${REMOTE_PY:-/home/rm/miniconda3/envs/tube_vision/bin/python}"
LOCAL_PORT="${LOCAL_PORT:-8876}"
REMOTE_PORT="${REMOTE_PORT:-8876}"
SAFETY_PROFILE="${SAFETY_PROFILE:-table_demo}"
MODE=()
if [[ "${EXECUTE:-0}" == "1" ]]; then
  MODE=(--execute)
elif [[ "${PLAN_ONLY:-0}" == "1" ]]; then
  MODE=(--plan-only)
fi
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ "${EXECUTE:-0}" == "1" ]]; then
  MODE_LABEL="EXECUTE"
elif [[ "${PLAN_ONLY:-0}" == "1" ]]; then
  MODE_LABEL="PLAN-ONLY"
else
  MODE_LABEL="OBSERVE-ONLY"
fi
echo "Robot: ${ROBOT_HOST}  mode: ${MODE_LABEL}"
echo "Safety profile: ${SAFETY_PROFILE}"
echo "Dashboard: http://127.0.0.1:${LOCAL_PORT}"

# Sync only this demo package and its thin entrypoint. The robot's config,
# calibration, model, and unrelated working-tree files are left untouched.
if [[ "${SYNC_SCRIPT:-1}" == "1" ]]; then
  rsync -az "${SCRIPT_DIR}/../bottle_grasp/" "${ROBOT_HOST}:${REMOTE_DIR}/bottle_grasp/"
  rsync -az "${SCRIPT_DIR}/bottle_grasp_demo.py" "${ROBOT_HOST}:${REMOTE_DIR}/scripts/bottle_grasp_demo.py"
fi

ssh -tt -L "${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT}" "${ROBOT_HOST}" \
  "cd '${REMOTE_DIR}' && '${REMOTE_PY}' scripts/bottle_grasp_demo.py --port '${REMOTE_PORT}' --safety-profile '${SAFETY_PROFILE}' ${MODE[*]}" &
SSH_PID=$!
trap 'kill -INT "${SSH_PID}" 2>/dev/null || true; wait "${SSH_PID}" 2>/dev/null || true' INT TERM EXIT

for _ in {1..50}; do
  if curl -fsS "http://127.0.0.1:${LOCAL_PORT}/status.json" >/dev/null 2>&1; then
    open "http://127.0.0.1:${LOCAL_PORT}/"
    break
  fi
  sleep 0.2
done
wait "${SSH_PID}"
