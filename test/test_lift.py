"""
升降机构测试脚本
运行环境：机器人内网（或 SSH 进机器人后运行）
目标：169.254.128.18:8080  （与左臂同一控制器）

测试流程：
  1. 查询当前高度
  2. 下降到 (当前 - 100) mm
  3. 等待到位
  4. 上升到 (下降后 + 50) mm
  5. 恢复回最初高度
  6. 再次查询确认
"""

import socket
import json
import time

LIFT_IP = "169.254.128.18"
LIFT_PORT = 8080
TIMEOUT = 10  # 单次命令超时秒数


def send_cmd(sock: socket.socket, cmd: dict) -> dict:
    payload = json.dumps(cmd) + "\r\n"
    sock.sendall(payload.encode())

    buf = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break

        buf += chunk

        try:
            return json.loads(buf.decode().strip())
        except json.JSONDecodeError:
            continue

    raise RuntimeError(f"连接断开，未收到完整响应。已收: {buf!r}")


def main():
    print(f"连接升降控制器 {LIFT_IP}:{LIFT_PORT} ...")

    with socket.create_connection((LIFT_IP, LIFT_PORT), timeout=TIMEOUT) as s:
        s.settimeout(TIMEOUT)

        # 1. 查询当前状态
        state = send_cmd(s, {"command": "get_lift_state"})
        print(f"当前状态: {state}")

        current_h = state.get("height", None)
        if current_h is None:
            print("ERROR: 未获取到高度，退出")
            return

        # 安全限制
        target_down = max(current_h - 100, 0)      # 下降 10 cm
        target_up = min(target_down + 50, 2600)   # 再上升 5 cm

        print(f"\n当前高度: {current_h} mm")
        print(f"目标下降 10 cm: {target_down} mm")
        print(f"之后上升 5 cm: {target_up} mm")
        print(f"最后恢复原高度: {current_h} mm")

        input("\n按 Enter 开始下降 10 cm（Ctrl+C 取消）...")

        # 2. 下降 10 cm
        resp_down = send_cmd(s, {
            "command": "set_lift_height",
            "speed": 30,
            "height": target_down,
            "block": 1
        })
        print(f"下降指令响应: {resp_down}")

        time.sleep(0.5)
        state_down = send_cmd(s, {"command": "get_lift_state"})
        print(f"下降后状态: {state_down}")

        input("\n按 Enter 开始上升 5 cm（Ctrl+C 取消）...")

        # 3. 上升 5 cm
        resp_up = send_cmd(s, {
            "command": "set_lift_height",
            "speed": 30,
            "height": target_up,
            "block": 1
        })
        print(f"上升指令响应: {resp_up}")

        time.sleep(0.5)
        state_up = send_cmd(s, {"command": "get_lift_state"})
        print(f"上升后状态: {state_up}")

        input(f"\n按 Enter 恢复原高度 {current_h} mm（Ctrl+C 取消）...")

        # 4. 恢复最初高度
        resp_restore = send_cmd(s, {
            "command": "set_lift_height",
            "speed": 30,
            "height": current_h,
            "block": 1
        })
        print(f"恢复指令响应: {resp_restore}")

        time.sleep(0.5)
        state_final = send_cmd(s, {"command": "get_lift_state"})
        print(f"最终状态: {state_final}")

    print("\n测试完成。")


if __name__ == "__main__":
    main()