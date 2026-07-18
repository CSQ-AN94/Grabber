# 项目里所有的 Demo/脚本 — 一览与运行方法

> **2026-07-18 当前入口：** 水瓶实机任务只允许
> `scripts/run_bottle_grasp.sh from-observation` 和
> `scripts/run_bottle_grasp.sh from-start`。旧 launcher/阶段子命令均已禁用，
> **禁止复制历史命令执行真机**；对应 launcher 现在会退出 2。现场操作只以
> `docs/bottle_grasp_demo_runbook.md` 为准。

这份文档盘点项目里**能直接跑起来的入口脚本**，按"这是干什么用的"分类。标定
类脚本（`scripts/run_eye_*_calibration*.py`、`collect_calibration_poses.py` 等）
不在这里详细展开，那部分看 `docs/hand_eye_calibration_status.md` 和
`exports/dual_arm_handeye_calibration_20260715/README.md`。

## 速查表

| 脚本 | 一句话 | 运行位置 |
|---|---|---|
| `sdk_demo.py` | 双臂关节+夹爪硬件冒烟测试 | 机器人上 |
| `tcp_demo.py` | 最原始的TCP JSON关节控制 | 机器人上 |
| `pose_reader.py` | 遥操时只读打印末端位姿（记点用） | 机器人上 |
| `grasp_demo.py` / `grasp_demo_left.py` | 单次抓取，硬编码固定位姿 | 机器人上 |
| `direct_grab.py` | 视觉扫描+按名字/序号抓取，不经过大模型 | 机器人上 |
| `main_agent.py` | 完整Agent主程序（Gemini+语音+工具调用） | 机器人上 |
| `scripts/bottle_grasp_demo.py` + 3个launcher | 抓水瓶demo（本次主要工作） | Mac一键/机器人上 |

---

## 一、底层SDK/硬件验证类

### `sdk_demo.py` — 双臂关节+夹爪冒烟测试
```bash
python3 sdk_demo.py           # 双臂都测
python3 sdk_demo.py left      # 仅左臂
python3 sdk_demo.py right     # 仅右臂
```
流程：整段SIGSTOP住`atom`遥操 → 依次测每个关节J1-J7小范围往返 → 测夹爪
（右臂，SIGSTOP `zhixing_ctrl`）→ SIGCONT恢复。**这是这个仓库最早期的架构**
（遥操靠SIGSTOP插队），后来在标定/抓水瓶那批工作里证明这个架构不安全（SIGCONT
后从臂高跟随会瞬间跳回主臂位置），已经改用"彻底停遥操→纯SDK控制→官方脚本
重启遥操"的模式（`grasp_demo.py`、`bottle_grasp/robot.py` 都是后者）。跑这个
脚本前要清楚它还是老架构。

### `tcp_demo.py` — 最原始的关节控制
```bash
python3 tcp_demo.py
```
直接拼JSON走TCP socket给控制器（不经过Python SDK包装），每个关节从当前位置
按 `OFFSETS` 里的角度转一下再转回来。纯验证TCP协议通不通，不做任何安全检查，
运行前必须确认周围无障碍物。

### `pose_reader.py` — 遥操时的只读位姿打印
```bash
python3 pose_reader.py               # 默认右臂 169.254.128.19
python3 pose_reader.py 169.254.128.18  # 左臂
```
用遥控手柄/拖动示教正常操作机械臂，这个脚本只读连接、持续打印末端笛卡尔位姿，
不发送任何指令、不影响遥操。用途：把手臂摆到想要的位置，读出坐标，抄进
`grasp_demo.py` 这类硬编码位姿的脚本里。

---

## 二、传统抓取Demo（硬编码位姿/无视觉闭环）

### `grasp_demo.py` / `grasp_demo_left.py` — 单次固定位姿抓取
```bash
python3 grasp_demo.py                      # 右臂，默认IP
python3 grasp_demo.py 169.254.128.19 8080  # 显式指定IP/端口
python3 grasp_demo_left.py                 # 左臂版，用前必须先标定
```
架构：停遥操（`pkill atom` + `pkill zhixing_ctrl.py`）→ 纯SDK连接+夹爪初始化 →
按硬编码的 `HOME_JOINTS`/`GRASP_POSE` 走一遍"回home→预抓取→下探→合爪→抬起→
回home" → SDK断开 → 官方脚本带校准重启遥操。**这是"停遥操→SDK→重启"这套安全
架构最早成型的地方**，后来 `bottle_grasp/robot.py` 的 `RobotSession` 沿用了
同样的思路（但换成了更完整的力控夹爪协议+MoveIt桥接）。左臂版本用前必须先用
`pose_reader.py 169.254.128.18` 量出左臂专属的HOME/GRASP位姿，改
`LEFT_POSES_VERIFIED = True` 才会真正执行，否则只打印不动。

### `direct_grab.py` — 视觉扫描+指定抓取（无大模型）
```bash
python3 direct_grab.py scan              # 只扫描当前视野商品，打印列表
python3 direct_grab.py grab 红牛          # 直接抓取指定商品
python3 direct_grab.py                   # 交互模式：输入商品名/序号
python3 direct_grab.py --no-initial-scan # 交互模式启动不自动扫描
```
走 `intelligence.robot_tools` 那套（YOLO视觉+旧的抓取流程），跳过Gemini/语音，
是"main_agent.py 去掉AI对话层"的简化版，适合只想验证硬件抓取链路时用。

### `main_agent.py` — 完整Agent主程序
```bash
python3 main_agent.py
```
交互式启动：先问模式（1=纯对话/2=启用工具调用）、再问是否用真实硬件、再问
语音还是文本交互。这是项目最初设想的"最终形态"入口——Gemini对话驱动、可选
语音、工具调用去操作机械臂/视觉。**跟 `bottle_grasp/` 那套是两条独立的技术栈**
（这个走 `controllers/arm_controller.py` 的 `ArmController`，`bottle_grasp/`
走自己的 `RobotSession`），互不影响，见 `bottle_grasp_status.md` 里的对比。

---

## 三、抓水瓶 Demo（当前操作面）

现场只有一个 Mac 端 launcher、两个完整任务：

```bash
scripts/run_bottle_grasp.sh from-observation
scripts/run_bottle_grasp.sh from-start
```

- `from-observation`：右臂已在合格腕部观察位；本轮重新做头部/腕部锁定，然后完成
  抓取、抬升、放回、退开与固定头部释放确认。
- `from-start`：从固定头部定位开始，用 MoveIt 转移到腕部观察位，走相同抓放尾段，
  最后返回 profile 的 home。

`run_bottle_grasp_resume.sh`、`run_bottle_grasp_autonomous.sh` 和
`start_bottle_demo.sh` 都是退役迁移 stub：只打印对应新命令并退出 2。机器人端
`scripts/bottle_grasp_demo.py` 默认也拒绝 legacy 阶段参数；开发诊断不得伪装成
现场任务。完整前置条件、部署变量、终点与“尚未完成本版实机 DONE 验收”的边界见
[当前实机运行手册](../bottle_grasp_demo_runbook.md)。

`bottle_grasp/moveit_collision_selftest.py` 等单项工具只属于开发诊断，不是第三个
任务入口。其历史探针结果和使用背景见 [避障交接](obstacle_avoidance.md)，不能替代
两个完整流程的现场验收。
