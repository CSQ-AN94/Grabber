# 项目里所有的 Demo/脚本 — 一览与运行方法

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

## 三、抓水瓶Demo家族（本次主要工作，2026-07-16）

代码在 `bottle_grasp/`，入口是 `scripts/bottle_grasp_demo.py`，配套3个一键
launcher脚本（Mac上跑，自动同步代码到机器人+SSH远程执行）。
**示教走廊已于 2026-07-17 移除**（`--full-cycle`/`--guided-path`/录制脚本/
走廊JSON），观察位转移只剩 MoveIt 自主规划一条路。**完整背景、架构、
已知问题看 [bottle_grasp_status.md](bottle_grasp_status.md)**，这里只列怎么跑。

### `scripts/run_bottle_grasp_resume.sh` — 续抓模式（从观察位开始）
```bash
scripts/run_bottle_grasp_resume.sh check   # 无运动视觉确认（先跑这个）
scripts/run_bottle_grasp_resume.sh grasp   # 抓取+抬升，保持
scripts/run_bottle_grasp_resume.sh cycle   # 抓取+抬升+放回+退开
```
前提：右臂已经在观察位（腕部相机距瓶~30cm、瓶子完整入镜）。这是2026-07-16
凌晨首次真机抓取成功用的模式。`check` 是严格只读路径：不接管机械臂、不启动
MoveIt/夹爪/工具坐标设置；启动器会自动释放占用目标相机的已知预览程序，并拒绝
终止未知占用者。

### `scripts/run_bottle_grasp_autonomous.sh` — 全自主流程（默认且唯一的完整流程）
```bash
scripts/run_bottle_grasp_autonomous.sh plan     # 离线：头部定位+MoveIt规划
scripts/run_bottle_grasp_autonomous.sh observe  # 真机移动到观察位，不抓取
scripts/run_bottle_grasp_autonomous.sh grasp    # 抓取+抬升
scripts/run_bottle_grasp_autonomous.sh cycle    # 抓取+抬升+放回+退开+返回初始姿态
scripts/run_bottle_grasp_autonomous.sh finish   # 夹爪已抓着水瓶（上一轮遗留）：跳过定位/抓取，直接放回+返回初始姿态
scripts/run_bottle_grasp_autonomous.sh selftest # 判定MoveIt碰撞检查是否正常
```
头部定位→**MoveIt自主规划**到观察位→腕部精定位→空夹基线标定→直线接近→
抓取。适合目标几何简单的场景（比如瓶子放桌角、周围空旷）。**注意**：截至
2026-07-17，这条完整链路在当前这版代码上还没有一次真机完整跑通的记录，
细节看 [bottle_grasp_status.md](bottle_grasp_status.md) 的"验证状态"表。

### `scripts/start_bottle_demo.sh` — 最早的完整流程launcher（带Web Dashboard）
```bash
PLAN_ONLY=1 scripts/start_bottle_demo.sh   # 纯规划
EXECUTE=1 scripts/start_bottle_demo.sh     # 真机执行
SAFETY_PROFILE=table_demo scripts/start_bottle_demo.sh
```
自动开一个本地网页dashboard（`http://127.0.0.1:8876`）实时看当前阶段/检测画面。
跟上面两个脚本比，这个是最原始的"从头开始、无参数定制"版本，直接调用
`bottle_grasp_demo.py` 不带 `--resume-at-wrist`，走同样的自主观察位规划。

### `bottle_grasp/moveit_collision_selftest.py` — MoveIt碰撞检查自检
```bash
# 需要先在机器人上另开终端起 move_group：
source /opt/ros/humble/setup.bash && source ~/ros2_ws/install/setup.bash
python3 bottle_grasp/moveit_headless.py
# 另一个终端：
python3 bottle_grasp/moveit_collision_selftest.py
```
`run_bottle_grasp_autonomous.sh selftest` 会自动跑这个。用真机示教过的安全垂下
姿态做探针，几秒内判定MoveIt的碰撞检查到底工不工作。**2026-07-17 修正**：旧版
探针姿态自身就会撞底盘，导致误诊成"碰撞检测坏了"；换成安全姿态后真机验证
碰撞检测本身工作正常（三态 valid→invalid→valid），详见 `obstacle_avoidance.md`。

### 直接调用 `bottle_grasp_demo.py`（不走launcher脚本时的完整参数）
```bash
python3 scripts/bottle_grasp_demo.py \
  --execute                        # 真机执行；不加则只能配合--plan-only
  --plan-only                      # 只规划不执行（与--execute互斥）
  --resume-at-wrist                # 跳过头部定位，从当前腕部姿态续抓
  --finish-from-current            # 跳过定位与抓取，假设夹爪已抓着水瓶，直接放回/返回初始姿态
  --place-back                     # 抓取抬升后放回桌面并退开
  --return-home                    # 放回后额外规划返回profile里home_joints_deg配置的初始姿态
  --restore-teleop                 # 结束后自动跑官方upstart_all.sh恢复遥操
  --stop-after-observation         # 只做到腕部定位，不抓取
  --safety-profile table_demo      # 电子围栏profile名（safety_profiles.json）
  --output-dir outputs/bottle_grasp
```
