"""
RealMan RM75 右臂控制 Demo
- 关节控制：TCP JSON (169.254.128.19:8080)

运行条件：
  手臂周围无障碍物
"""
import socket, json, time, os, signal, subprocess

ARM_IP   = "169.254.128.19"
ARM_PORT = 8080
SPEED    = 35

JOINT_NAMES = ["j1 肩部旋转", "j2 肩部抬降", "j3 大臂扭转",
               "j4 肘关节",   "j5 小臂扭转", "j6 腕部俯仰", "j7 末端旋转"]
OFFSETS     = [20000, -20000, 20000, -35000, 30000, 25000, 40000]

def find_atom_pid():
    r = subprocess.run(["pgrep", "-x", "atom"], capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return int(r.stdout.strip().split()[0])
    return None

# ── TCP helpers ──────────────────────────────────────────────────────
def req(cmd, timeout=12.0):
    s = socket.socket()
    s.settimeout(timeout)
    s.connect((ARM_IP, ARM_PORT))
    s.sendall((json.dumps(cmd) + "\r\n").encode())
    buf = b""
    try:
        while True:
            c = s.recv(4096)
            if not c: break
            buf += c
            if b"\r\n" in buf: break
    except: pass
    s.close()
    for line in buf.split(b"\r\n"):
        if line.strip():
            try: return json.loads(line)
            except: pass
    return None

def get_joints():
    for _ in range(5):
        r = req({"command": "get_current_arm_state"})
        if r and "arm_state" in r:
            return r["arm_state"]["joint"]
        time.sleep(0.2)
    raise RuntimeError("get_joints failed")

def movej(joints, v=SPEED):
    req({"command": "movej", "joint": joints, "v": v, "r": 0, "connect": 0, "block": 1})

def wait_joint(idx, target, tol=800, timeout=8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        j = get_joints()
        if abs(j[idx] - target) <= tol:
            return j
        time.sleep(0.15)
    return get_joints()

def log(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg))

# ════════════════════════════════════════════════════════════════════
ATOM_PID = find_atom_pid()
log("=== RealMan 右臂控制 Demo ===")
log("atom PID: %s" % (ATOM_PID or "未找到"))

j0 = get_joints()
log("初始位置: %s" % [round(x/1000.0, 1) for x in j0])

if ATOM_PID:
    os.kill(ATOM_PID, signal.SIGSTOP)
time.sleep(0.3)
log("atom 已暂停\n")

try:
    log("--- 7 关节依次运动 ---\n")
    for i in range(7):
        offset = OFFSETS[i]
        target = list(j0)
        target[i] = j0[i] + offset

        log(">>> %s  %+d°" % (JOINT_NAMES[i], offset // 1000))
        movej(target)
        wait_joint(i, target[i])

        j_now = get_joints()
        actual = (j_now[i] - j0[i]) / 1000.0
        log("    到达 %.1f°  实际移动 %+.1f°" % (j_now[i]/1000.0, actual))
        time.sleep(2.0)

        movej(list(j0))
        wait_joint(i, j0[i])
        log("    归位完成\n")
        time.sleep(0.5)

except Exception as e:
    log("ERROR: %s" % e)
finally:
    if ATOM_PID:
        os.kill(ATOM_PID, signal.SIGCONT)
    req({"command": "set_arm_run_mode", "mode": 1})
    log("\natom 已恢复")
    log("=== Demo 结束 ===")
