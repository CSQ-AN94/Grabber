# 抓水瓶Demo — 现状交接（2026-07-16）

分支 `dual-arm-sdk`，git HEAD 在 `5abb201`（本文档写于此提交之后）。这份文档
是给"换个窗口继续写代码"用的，目标是让你不用重新翻聊天记录就能接上上下文。

## 一句话现状

**2026-07-16凌晨首次真机完整抓取成功**（视觉定位→接近→力控夹取→抬升→放回→
退开全部走通），之后又做了两轮扩展：**完整循环**（垂下→观察→抓→放回→垂回，
转移段用示教走廊）和**全自主观察位规划**（跳过示教，验证简单几何场景）。
当前最大的遗留问题是 **MoveIt2 的碰撞检测端到端失效**，详见
[obstacle_avoidance.md](obstacle_avoidance.md) 第三节——这个问题没解决之前，
所有"大范围自由移动"都要么靠示教走廊、要么局限在几何简单（周围空旷）的场景。

## 三套运行流程，怎么选

| 场景 | 用哪个脚本 | 转移方式 |
|---|---|---|
| 右臂已经在观察位，只测抓取 | `scripts/run_bottle_grasp_resume.sh` | 无（已在位） |
| 要完整跑一轮（垂下开始） | `scripts/run_bottle_full_cycle.sh` | 示教走廊（人工录一次，可复用） |
| 瓶子放桌角/简单几何，测免示教 | `scripts/run_bottle_grasp_autonomous.sh` | MoveIt自主规划（`--autonomous-observation`） |

具体命令、参数含义看 [demos_overview.md](demos_overview.md) 第三节，那里列得
很全，这里不重复。

## 抓取核心逻辑（三套流程共用，别重复造）

`bottle_grasp/demo.py` 的 `_grasp_and_lift()`：视觉闭环分段接近→最后低速直线
接近→力控夹取（`RobotSession.close_gripper`，RM Plus原生协议+抓空判定）→
抬升5cm。`_place_back()`：放低→松爪→沿接近轴反向退开。这两个方法被
`run()`（原有流程）、`run_full_cycle()`（完整循环）共用，**改抓取逻辑只用改
一处**。

## 已知问题清单（按影响排序）

1. **夹爪"空夹"判定阈值不准，会把真实抓取成功误判成失败**（2026-07-15晚
   实测确认，高优先级）——`bottle_grasp/robot.py` 的 `close_gripper()` 靠位置
   阈值判断是否抓到东西：`gripper_empty_closed_position=394`（空夹时的闭合
   终止位置）+ `gripper_object_margin=35`（要求的余量），闭合位置必须
   `>429` 才判定"抓到了"。实测：桌角那个金属瓶状容器（比之前用的塑料瓶窄/
   硬）抓取时实际已经抓稳（人工现场确认"还夹着"），但闭合终止位置只有
   `pos=402`（只比空夹基线394高8），远低于429门槛，被误判成"空夹"，直接
   安全中止、没有抬升——**这不是没抓到，是判定逻辑对这个物体不适用**。
   建议修法：①改成动态标定（每次抓取前先测一次当前环境下的"空夹闭合位置"，
   不用写死的394常量，环境/物体一变常量就可能失准）；②或者用夹爪状态里的
   `current_force`（力反馈）代替/辅助纯位置判断，力信号对"有没有真的夹住东西"
   更直接；③如果暂时不改代码，至少要意识到"夹爪闭合位置等同空夹"这个中止
   消息**不能直接当成真的抓空**，尤其是抓较窄/较硬的物体时。
2. **MoveIt2碰撞检测端到端失效**（架构级最高优先级）——目标在障碍盒内部10cm
   都判无碰撞。诊断细节、已排除的可能性、还没跑完的实验、下一步排查方向，
   全部写在 [obstacle_avoidance.md](obstacle_avoidance.md)。**下次开机第一
   件事**：跑 `scripts/run_bottle_full_cycle.sh selftest`。
3. **货架部署不能靠示教**——用户明确提出：后续没有遥操/无人值守，"每个新
   货位人工示教一次"这条路走不通。示教走廊只是问题2解决前的临时方案，不是
   长期架构。问题2修好后，货架部署应该走：感知定位→MoveIt自主规划→电子
   围栏复核（纯代码，不靠人）→执行，货架配置退化成"量一次尺寸写进
   `safety_profiles.json`"，不需要操作机器人。
4. **透明瓶深度双峰**：前壁/后壁深度相差约一个瓶径（4.5cm），带标签的不透明
   瓶没有这个问题、检测置信度也高很多（0.85 vs 0.09）。昨晚最终成功demo用的
   是不透明瓶。
5. **头部相机自训模型（`8_17.pt`）对瓶子朝向敏感**：标签背对相机时置信度
   从0.85掉到0.09，导致头部定位直接检测不到。已加yolo11n通用模型兜底
   （`bottle_grasp/perception.py` 的 `fallback_model`），但根子问题（自训
   模型泛化差）没解决，长期应该补训练数据。
6. **蠕动式执行**：密集关节点逐条`rm_movej`+段间MoveIt重规划，走走停停不好看，
   但这是安全优先的设计选择，不是bug。想优化可以改成SDK的连续轨迹透传模式，
   但要重新验证安全性。
7. **遥操不会自动恢复**：`RobotSession`构造时会停掉`atom`/`zhixing_ctrl`，
   demo结束不自动重启（避免意外抢串口），需要手动跑官方`upstart_all.sh`，
   或者跑demo时加`--restore-teleop`。

## 代码结构导览

```
bottle_grasp/
  core.py          — 共享数据类型（DemoParams参数表、Localization、SafetyAbort）、
                      位姿插值/坐标变换的几何工具函数
  perception.py     — YOLO检测 + 稳健深度估计（robust_near_cluster处理透明瓶噪声）
  robot.py          — RobotSession：真实TCP/SDK连接、正逆解、movej/movel执行、
                      力控夹爪（RM Plus原生协议）
  planner.py        — MoveItPlanner：子进程桥接ROS2，发规划/校验请求
  moveit_headless.py — 起一个只规划、不执行的move_group（ROS2节点）
  moveit_plan_once.py — 单次规划请求helper（被planner.py调用的子进程脚本）
  moveit_validate_path.py — 逐点碰撞校验helper（示教路径复核用）
  moveit_collision_selftest.py — 独立诊断工具，判定MoveIt碰撞检测是否工作
  safety.py         — 电子围栏：FenceBox/SafetyProfile，笛卡尔空间硬校验
  safety_profiles.json — 围栏配置数据（table_demo已启用verified，shelf_template
                      是禁用的模板）
  scene.py          — RGB-D点云→体素化障碍物（喂给MoveIt）
  collision.py      — 最后接近前的点云通道检查
  dashboard.py       — 本地Web dashboard（实时看阶段/检测画面）
  demo.py           — BottleDemo状态机主体，run()/run_full_cycle()两条主流程
  guided_paths/table_demo_right.json — 已录制的示教走廊（首次成功用的那条）

scripts/
  bottle_grasp_demo.py       — 入口，argparse
  run_bottle_grasp_resume.sh — 续抓模式launcher
  run_bottle_full_cycle.sh   — 完整循环launcher（record/plan/cycle/selftest）
  run_bottle_grasp_autonomous.sh — 全自主观察位launcher
  start_bottle_demo.sh       — 最早的launcher（带dashboard，无新参数）
  record_right_arm_guided_path.py — 示教走廊录制工具

test/bottle_grasp/
  test_algorithms.py         — 感知/围栏算法单测（8个）
  test_full_cycle.py         — run_full_cycle()编排逻辑测试（3个，mock机械臂）
  test_autonomous_observation.py — --autonomous-observation分支选择测试（3个）
  当前共14个测试，全部通过（不需要真机/ROS，纯逻辑+mock）
```

## 跟旧代码栈的关系

`bottle_grasp/` 是**完全独立的新SDK控制栈**，不碰旧的 `controllers/arm_controller.py`
（`ArmController`，被 `direct_grab.py`/`main_agent.py`/标定脚本用）。两套并存、
互不干扰，见 [demos_overview.md](demos_overview.md) 里的对比表。这是有意的
架构决定：抓取要的东西（真实TCP、力控夹取、MoveIt桥接、只读规划模式）旧
ArmController都没有，硬塞会把那套也搞乱。

## 相关git提交（时间顺序）

- `c40b49a` 四轮手眼标定全套（头部+双腕，含可分享标定包）
- `4fd4fff` 抓水瓶demo首次真机成功（核心状态机+安全层）
- `b12af5f` 清理死路径（删掉回放绝对坐标的脆弱方案）
- `6a6ccc3` 完整循环（垂下→观察→抓→放回→垂回，示教走廊转移）
- `5abb201` `--autonomous-observation`（跳过示教，验证简单几何场景）

## 下一步优先级

1. **MoveIt碰撞检测排查**（见obstacle_avoidance.md第三节的具体步骤）——这是
   解锁"货架部署不靠示教"的前提，应该优先于其它一切新功能
2. 多验证几次现有流程的稳定性（不同瓶子摆位、不同光照），积累"能不能复现"
   的证据，而不是只信一次成功
3. MoveIt碰撞修好后：接线 `--autonomous-transit`（`run_full_cycle`里的转移段
   换成自由规划，去掉示教依赖）
4. 货架部署：量出货架真实尺寸，填 `safety_profiles.json` 的 `shelf_template`，
   现场验证后把 `verified_for_execution` 改 `true`
