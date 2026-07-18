# 抓水瓶Demo — 现状交接（更新于 2026-07-17）

分支 `dual-arm-sdk`。这份文档是给"换个窗口继续写代码"用的，目标是让你不用
重新翻聊天记录就能接上上下文。

## ⚠️ 现在最需要知道的两件事

1. **所有这些改动都还没提交**：`git log` 停在 `a6c5aa0`，工作区里 43 个文件
   改动/新增（`git diff --stat` 是 +1772/-1088 行），一次提交都没有。这不是
   小改动堆积——是整整一轮"清理示教走廊 + 重写安全规划层 + 重写相机/夹爪/
   头部健壮性"的工作全部悬在工作区里。换会话/换电脑之前**先确认这些文件还在**
   （`git status --short`），别用 `git checkout .`/`git clean` 之类的命令。
2. **没有任何一次确认"从头到尾完整跑通一次真机抓取"是在这一整轮新代码之上
   做到的**——下面"验证状态"一节按功能点列出了哪些真机跑过、跑到哪一步、
   哪些完全没上过真机。不要假设"测试全过=能跑"，这批测试全部是 mock，
   不连真机/不连 ROS。

## 一句话现状

**2026-07-16凌晨首次真机完整抓取成功**（视觉定位→接近→力控夹取→抬升→放回→
退开全部走通，但那次用的是**清理之前**的旧代码：示教走廊+蠕动式接近+写死
夹爪阈值）。**2026-07-17 做了一轮大清理**：示教走廊/完整循环整体移除、夹取
点估计改成确定性偏低取点、腕部接近段去掉逐段MoveIt重规划、夹爪空夹判定改成
每轮实测基线。同一天又修正了旧 MoveIt selftest 的错误基线，真机验证世界碰撞
链正常，并新增 `SafeMotionPlanner`：围栏拒绝后自动换路线/观察端点，最终轨迹
同时经过 MoveIt 全臂后验复核和独立电子围栏复核。

同日又完成相机/启动健壮性修复：launcher 按 RealSense 序列号解析全部 V4L2
节点，自动释放已知预览程序、报告但不终止未知占用者；pipeline 启动无帧时有一次
完整重建，两次无帧后才对目标相机做一次硬件重启。`resume check` 已拆成真正的
只读路径。真机实测 `check`：右腕 7/7 帧、散布 2.0mm、退出码0。运动前对唯一的
瞬态 `0xF000` 关节通信丢帧允许一次官方清错并连续两次复核，其他故障仍一律中止。

**净效果**：单个环节（空夹标定、头部校正、MoveIt碰撞链、相机重连、夹爪
`dof_state`误判）都各自在真机上验证过一次，但自从这轮清理开始，**没有一次
串起来的完整真机抓取成功记录**——旧的"2026-07-16成功"是用被这轮清理整体
替换掉的代码做到的，不能当成现在这版代码已经跑通的证据。

## 2026-07-17 清理内容（部分已开始真机验证）

1. **示教走廊/完整循环移除**：`--full-cycle`/`--guided-path`/
   `--autonomous-observation` 标志、`record_right_arm_guided_path.py`、
   `run_bottle_full_cycle.sh`、走廊JSON、safety profile 里的 guided 字段全删。
   理由：用户确认示教这条路已没用（跟货架无人部署目标冲突）。观察位转移
   现在只有 MoveIt 自主规划一条路（原 `--autonomous-observation` 行为成为默认）。
   selftest 子命令移到了 `run_bottle_grasp_autonomous.sh selftest`。
2. **夹取点估计改成确定性偏低取点**：原来 (u,v) 取"深度接近瓶身的像素的中位
   数"，v 随每帧有效深度像素分布漂移，导致每轮抓取高度不一样、偏高时近距腕部
   相机丢目标。现在 u 仍取中位数（横向鲁棒），v 固定取检测框
   `grasp_height_fraction=0.66` 处（瓶身下部）。透明瓶深度回退路径同样用这个
   比例（原来是 0.48）。
3. **腕部接近段去掉逐段MoveIt重规划**（原"蠕动式执行"）：原
   `_move_to_pregrasp_with_active_replanning` 每前进4.5cm就向MoveIt重规划一次。
   近距阶段逐段调用全局规划器只带来走走停停。现在 `_approach_pregrasp`
   一次规划直线路径，防线与最后接近段一致：电子围栏逐点校验 + plan_ik
   连续性/限位/奇异检查 + 点云通道检查 + 锁定目标视觉守卫。目标在起步前已用
   7帧锁定；运动守卫把锁定3D点投影到当前腕部画面，与原始 bottle 检测框关联，
   不再复用初始化的长宽比门禁。腕部确实关联不到时，段间暂停并切固定头部相机
   独立采3帧确认，偏移>5cm令当前路径作废，随后恢复右腕。路径本身还会验证
   TCP距锁定目标从观察距离收敛到8.5cm悬停位。到达预抓取位后仍必须重新检测
   到瓶子，复检失败就不会进入最后接近。
   MoveIt 只负责"到观察位"的大范围关节空间转移。`_refresh_wrist_scene`
   （腕部体素建图，只喂给已删的逐段重规划）一并移除。
4. **夹爪空夹判定改成动态基线**：抓取前在观察位自由空间闭合一次实测今天的
   空夹基线（`RobotSession.calibrate_empty_close`）。2026-07-17 真机确认空夹能
   闭到 `pos=0`，所以动态标定不再由历史静态值394仲裁，只要求本轮闭合位比本轮
   张开位至少小100（夹爪确实完成了明显闭合）；余量从35降到6。2026-07-15 被
   误判的窄金属瓶（pos=402，仅比当时基线高8）按新逻辑会判成功。判定失败的
   报错里带 pos/current，方便下次现场核对。新增
   `test/bottle_grasp/test_gripper_judgment.py` 覆盖。

## 2026-07-17 同一天后续追加（真机试跑 `finish` 后暴露+修的三个问题）

第一次真机跑 `run_bottle_grasp_autonomous.sh finish`（夹爪还抓着水瓶，从当前
姿态收尾）暴露了两个问题，顺带补了一个用户主动要求的安全项：

1. **新增"返回初始姿态"**（`_return_home`，`--return-home`，`cycle`/`finish`
   默认带上）：放回后用 MoveIt 规划一段回到 `safety_profiles.json` 里
   `home_joints_deg` 配置的关节角，跟去程转移到观察位同一套机制（MoveIt规划+
   电子围栏密集插值复核），风险等级一致。`table_demo` 的 `home_joints_deg` 是
   从**已删除**的示教走廊文件的 git 历史（`git show HEAD:...`）恢复的
   2026-07-15 垂下起始姿态，**没有现场重新验证过**，桌子/机械臂摆位变过要
   重新确认。新增 `--finish-from-current` + launcher `finish` 子命令：跳过
   定位和抓取，假设夹爪已抓着水瓶，直接放回+返回初始姿态。
2. **真机实测发现并修的bug：`_place_back()`/抬升没有奇异区规避**——机械臂
   当前姿态本身就能落在 J4≈0° 奇异带（不用动都在带内），`_place_back()`的
   下降/退开、`_grasp_and_lift()`的抬升，都是从当前姿态直接求逆解，没有
   `candidate_path()`那种"逆解失败就绕接近轴转个角度重试"的机制，第一次
   真机跑 `finish` 时在放回的下降步直接安全中止（规划阶段拦下，**没有任何
   实际运动**，瓶子安全）。新增 `_plan_ik_avoiding_singularity()`统一给这
   三段接上跟 `candidate_path()` 同款的绕轴重试（8°/15°/25°，正负都试）。
   新增 `test/bottle_grasp/test_singularity_avoidance.py`。
   **2026-07-18 补根治（未真机验证）**：绕接近轴 roll 几何上改不了 |J4|
   ——肘角大小由肩-腕距离唯一决定，绕工具 z 轴不移动腕心，所以"起点已在
   奇异带内"的场景 roll 重试注定全灭。新增 `robot.escape_j4_singularity()`：
   起点 |J4|<8° 时先做纯关节空间弯肘（J4→±14°，先同号后反号，逃逸路径
   逐 1.5° 做 FK+电子围栏校验后 movej 执行；关节运动不经过病态雅可比，
   穿越奇异带安全，危险的只是带内笛卡尔直线）。抬升/下降/退开三段改走
   `_plan_local_leg()`：先逃逸、**逃逸后重建路径**（逃逸会移动 TCP 约
   数厘米，旧路径起点已失效）、再 roll 重试。`plan_ik` 的奇异拒绝消息
   现在区分"起点在带内（应弯肘逃逸）"和"路径中途入带（目标接近最大
   伸展，需调整目标/移动底盘）"。正常抓取循环里逃逸不会触发（抓取姿态
   都过了 |J4|≥8° 检查），只有 finish/续抓这类"从未校验姿态出发"的入口
   会用到。
3. **新增"头部基准角度强制校正"**（用户主动要求，`bottle_grasp/head_lock.py`）：
   `initialize()`最开始（早于安全profile加载、早于建立机械臂SDK连接）强制
   把头部舵机拉回标定基准角度（俯仰最低`angle1=398`、左右居中`angle2=516`，
   2026-07-08标定会话实测值）——头部相机的手眼标定`T_base_right_to_camera_head`
   只在这个角度下有效，头部可能被人工调试工具摆过、也可能被SDK初始化的
   未知副作用带偏（旧`ArmController`有实测坑，`RobotSession`是否也有未排除，
   见`teleop_sdk_coexist`记忆）。`--execute`时才真的驱动舵机，`--plan-only`
   只警告不移动。协议原来在`scripts/head_position_lock.py`里，已经把可复用
   逻辑搬进`bottle_grasp/head_lock.py`，那个脚本改成薄命令行封装（人工诊断
   用）。新增`test/bottle_grasp/test_head_lock.py`。头部基准校正已经在后续
   `cycle` 中成功运行；但这三条改动仍没有跑通过一次完整真机流程。

4. **夹爪动态标定后的重新张开单帧误判**：真机已确认动态基线正常接受
   `open=903 → empty close=0`，随后重新张开到 `pos=728`、仍以 `speed=74`
   运动时，反馈了一帧 `dof_state=6`，但 `sys_state=0`、`dof_err=0`。旧代码把
   单帧立刻判成故障并退出。现在 `sys_state`/`dof_err` 真错误仍立即中止；只有
   `dof_state=5/6` 时，运动中继续观察，停住后连续3帧仍为5/6才中止，总动作仍受
   5秒超时保护。真实反馈回放和持续故障两个方向都有回归测试。

5. **2026-07-18（用户主动要求）：转移前自动收拢张开的夹爪**——`_preflight()`
   读到夹爪状态后，如果 `pos` 超过 `gripper_pretransit_open_threshold`
   （=100，远高于闭合基线抖动、远低于张开位），先用 `close_empty_gripper`
   （无抓取判定的收拢语义，不是 `close_gripper`）收拢再继续。原因：张开的
   手指是比 `tool_guard` 固定防撞盒更宽、更不可预测的碰撞形状，长距离
   MoveIt 转移途中也更容易勾挂到东西。**`--finish-from-current` 显式跳过**
   （那个模式假设夹爪已抓着水瓶，绝不能在这里被强行合上）——由
   `_preflight()` 内部按 `finish_from_current` 参数判断，不依赖调用方
   记得传。未真机验证。

## 验证状态（逐功能点，别笼统地说"验证过"）

| 功能点 | 状态 | 证据 |
|---|---|---|
| 头部基准角度强制校正 | **真机 `--execute` 跑通过**（舵机真的转动回中） | `observe`/`cycle` 日志里出现过"头部基准位已校正" |
| MoveIt 世界碰撞检查本身 | **真机验证正常**（selftest 三态） | `moveit_collision_selftest.py` 用安全 home 探针跑出 valid→invalid→valid |
| `SafeMotionPlanner` 候选/换路/双重复核 | **真机 plan-only 跑过两次**，没有 `--execute` 过 | obstacle_avoidance.md 3.4 节的两次候选数/轨迹点数记录 |
| 相机自愈（重建/硬件重启） | 逻辑写好+单测覆盖，**具体触发路径未见真机日志证实** | 待确认下次真机遇到无帧场景时是否按预期恢复 |
| 夹爪动态空夹标定 | **真机 `--execute` 跑过，行为符合预期**（`open=903→close=0`） | 本轮会话里用户贴的真机日志 |
| 夹爪 `dof_state=5/6` 容忍逻辑 | **真机触发过一次并按预期未误中止** | 张开到 `pos=728` 时的单帧 `state=6` 被正确容忍 |
| `_plan_ik_avoiding_singularity`（放回/抬升绕轴重试） | **代码写好，尚未验证实际执行成功**——只确认了修复前会在规划阶段正确拦截，没见过它真的转过角度后成功执行 | 上一版代码在 `finish` 时于放回下降步安全中止；重试逻辑之后没有对应的成功日志 |
| `_return_home` | **完全没有真机运行记录**（plan-only 或 execute 都没有） | — |
| `LockedTargetGuard`/`ProjectedTargetAssociation`（视觉运动守卫） | **完全没有真机运行记录** | — |
| `camera_access.py` 的相机所有权释放/交接 | **部分验证**：见过启动阶段正常跑过，没见过它真的抢救回一次"被未知/已知程序占用"的场景 | — |
| 完整一轮（头定位→观察位→抓→放回→回初始姿态） | **没有任何一次在当前代码上跑完** | 本轮会话三次真机尝试全部在不同阶段中止（夹爪空夹标定异常 / 围栏拒绝观察位轨迹 / J4奇异区） |

## 踩过的坑，别再踩

这些是本轮清理里已经实际发生过、被现场日志证实的坑，不是猜测：

1. **写死的历史常量会反过来坑动态标定**：`gripper_empty_closed_position=394`
   本来只是防呆参考值，早期实现却拿它当仲裁标准——真机某次空夹直接闭到
   `pos=0`（跟环境/夹爪状态强相关，不是异常），被硬拿 394 一比就被误判成
   "标定异常"直接中止。**教训**：既然引入动态标定就是不信历史常量，就不要
   在校验逻辑里悄悄把常量请回来当门槛；改成"闭合位比本轮实测张开位至少小
   100"这种只依赖本轮数据的判据。
2. **给规划器的碰撞盒余量太小，会让 MoveIt 的路径采样分辨率"跳过"薄的安全区**：
   `table_top` 禁入盒给 MoveIt 用的碰撞几何四面都做了外扩（`moveit_
   collision_boxes()`一直是这样写的，**这一点昨天的诊断记错了**，不是"只扩了
   顶面"），但最初只多扩 `clearance_m+1cm`——这个宽度比 MoveIt 内部路径碰撞
   检测的采样分辨率还窄，于是出现"MoveIt说没碰、独立围栏用更密的插值一查发现
   已经穿进去1~1.7cm"的情况，本轮会话两次真机 `observe` 都在这个问题上耗尽
   全部候选中止。**教训**：给规划器看的安全余量不是"只要非零就行"，得比
   规划器自己的碰撞检测粒度更宽，否则规划和复核两层标准不一致，复核会在
   边界附近反复打回；余量应该按实测偏差量级选，不能拍脑袋定一个像1cm这样
   的小数字。
3. **奇异区不是"运动中才会撞上"，静止姿态本身就可能已经在里面**：机械臂
   放回水瓶前的静止姿态，J4 逆解就已经落在 ±8° 的奇异带内——不需要真的移动，
   对**同一姿态**求逆解都会被拒绝。任何"从当前姿态出发的纯平移"（抬升/
   下降/退开）如果直接对当前姿态求解、不做绕轴重试，在这类起始姿态下一定
   会在第一步就中止。**教训**：凡是"从当前姿态求逆解"的代码路径都需要同一
   套绕接近轴重试，不能假设只有"运动方向"会有奇异区问题。
4. **诊断脚本自己的探针姿态也可能有 bug，别急着信"碰撞检测坏了"这个结论**：
   旧 `moveit_collision_selftest.py` 用了一个会让 `r_hand`/`r_link7` 直接撞
   底盘/车身的固定探针姿态，"无盒子基线"永远是 `invalid`，脚本却把这个现象
   误读成"巨型盒子加了也没变化→碰撞几何没加载"。改用真机示教过的安全垂下
   姿态做探针后，三态测试立刻恢复正常（`valid→invalid→valid`）。**教训**：
   遇到"底层安全机制看起来完全失效"这种大结论前，先怀疑诊断工具本身的输入
   （尤其是硬编码的探针姿态/坐标），不要跳过这一步直接开始绕过或重写整个
   子系统。
5. **`pkill -f` 自我误杀**（历史坑，仍然适用）：用一整段包含目标进程名的
   shell/python 字符串通过 SSH 执行 `pkill -f <substring>`，会把执行这条命令
   本身的父进程也匹配上杀掉，看起来像"SSH 莫名断开"。`camera_access.py` 的
   `release_known_preview_owners()` 已经改成按精确 PID 调用 `os.kill`，不是
   字符串子串匹配，规避了这个坑，但如果以后又要写清场脚本，这条还是要记住。
6. **交接文档自己也会写错，别当成真理直接往下推理**：这份文档昨天把"table_top
   只在顶面外扩"写成了确定结论，今天回来重新读代码才发现四面早就在扩、真正
   问题是扩的量不够——两次诊断的表面症状（规划贴边界飞、被复核打回）一样，
   根因不一样。**教训**：交接文档描述的"某处代码现在是什么样"只是写文档那
   一刻的快照，改代码前先重新读一遍相关源码确认现状，尤其是在"这是我昨天
   自己下的结论"这种看起来不需要复核的地方。

## 还需要留意但还不算"坑"的判断调用

- **`table_top` 禁入盒的具体数值是"选出来的"，不是纯测量值**：顶面 z=-0.20
  和前沿 y=0.36 是在"最靠近的可见桌面像素（y=0.49，被画面下边界切掉）"和
  "示教走廊验证过无碰撞的通道（y=0.329, z=-0.49）"之间取的一个折中值，写在
  profile 的 `description` 字段里。桌子/相机布置一旦变化，这个数字不会自动
  更新，需要人工重新走一遍第四节的测量流程。
- **`bottle_grasp/demo.py` 里的 `_select_observation_flange()` 目前看起来没
  有调用方**（`_plan_observation()`/`SafeMotionPlanner` 走的是
  `_observation_flange_candidates()` 生成候选列表这条路）。不确定是刻意保留
  的兼容函数还是清理时漏删的死代码，下次动 `demo.py` 时顺手确认一下，不要
  假设它还在被用。

## 两套运行流程，怎么选

| 场景 | 用哪个脚本 | 转移方式 |
|---|---|---|
| 右臂已经在观察位，只测抓取 | `scripts/run_bottle_grasp_resume.sh` | 无（已在位） |
| 从头部定位开始完整跑 | `scripts/run_bottle_grasp_autonomous.sh` | MoveIt自主规划（默认，唯一） |

具体命令、参数含义看 [demos_overview.md](demos_overview.md) 第三节，那里列得
很全，这里不重复。

**2026-07-18 追加 `watch` 子命令**（`run_bottle_grasp_autonomous.sh watch`）：
在同一次运行里完成"到观察位确认+抓取"，不用像之前那样跑完 `observe`
再切到 `run_bottle_grasp_resume.sh cycle`——那种拼接走的是完全不同的
代码路径（resume 跳过头部相机/抓取预检），2026-07-18 当天就是这么拼出
了"观察位选得到但抓取脱节"的问题。`watch` 到观察位并检出瓶子后在终端
暂停，操作者确认真实姿态没问题、按 Enter 再继续，走的是跟 `grasp`/
`cycle` 完全同一条 `_finish_grasp_from_wrist` 路径，且不重启进程（省约
30-40秒的相机/YOLO/MoveIt 初始化）。Ctrl+C/STOP 在等待期间仍然立即生效
（轮询 `stop_event`，不是裸 `input()` 阻塞）。未真机验证。

## 抓取核心逻辑（两套流程共用，别重复造）

`bottle_grasp/demo.py` 的 `_grasp_and_lift()`：空夹基线标定→直线分段接近
（`_approach_pregrasp`）→最后低速直线接近→力控夹取（`RobotSession.
close_gripper`，RM Plus原生协议+实测基线抓空判定）→抬升5cm。`_place_back()`：
放低→松爪→沿接近轴反向退开。**改抓取逻辑只用改一处**。

## 已知问题清单（按影响排序）

1. **MoveIt 世界碰撞链已验证，自动重规划已接通**——旧 selftest 使用的固定姿态
   本身撞底盘，却被误诊成“碰撞几何没加载”。安全 home 探针真机结果为
   `valid → invalid(巨盒 contacts) → valid`。全局转移现在走
   `SafeMotionPlanner`：最多8端点×2路线，围栏违规点反馈给 MoveIt，最终轨迹做
   MoveIt密集状态复核+独立围栏复核。详见 [obstacle_avoidance.md](obstacle_avoidance.md)。
2. **`table_top` 围栏盒给 MoveIt 的余量不够，已在本地改大，但没有真机验证**
   （2026-07-17 晚追加诊断）：`moveit_collision_boxes()` 其实**早就四面都在
   外扩**（不是之前以为的"只扩了顶面"——那条诊断是错的，已在本节和"踩过的坑"
   里改正），本轮会话第二次真机 `observe` 还是在这个问题上连续失败8个候选、
   16次尝试：MoveIt 认为路径没碰垫大的盒子（按它自己的路径采样分辨率），但
   独立围栏用更密的插值复核，发现实际路径已经比垫大后的盒子边界还深入
   1~1.7cm——**真正的根因是 MoveIt 的路径碰撞采样分辨率比余量本身还粗**，
   不是"没垫"。已把 `bottle_grasp/safety.py` 的 padding 从 `clearance_m+1cm`
   加到 `clearance_m+5cm`（本地修改，SSH 连不上机器人时做的，**还没有同步到
   机器人、没有真机验证过**，下次能连机器人时优先跑 `observe` 确认这个改动
   有没有解决问题）。
   **2026-07-18 追加治本修复（同样未真机验证）**：根因（MoveIt 路径碰撞采样
   分辨率过粗）已直接用 OMPL `longest_valid_segment_fraction=0.0025` 收紧
   （`bottle_grasp/ompl_config.py`）；同轮把 helper 场景同步改为无状态（每次
   `/get_planning_scene` 查现存物体按前缀全删重建，
   `scene_ids.py`/`moveit_scene_helpers.py`），体素合并为单个 `rgbd_voxels`
   物体。**同日晚些时候 padding 又从 `clearance_m+5cm` 回调到 `+2cm`**
   （总余量4.5cm，对旧实测最大偏差1.7cm仍有2.6倍系数，对lvsf修复后的理论
   预期偏差~0.4cm有约10倍系数，但只是推算），是这三项里风险最高、最该
   优先真机复测的一项——如果又出现贴桌路径零星拒绝，先把 padding 临时
   改回 `+0.05` 定位问题，别急着怀疑 lvsf。真机复测清单见
   [obstacle_avoidance.md](obstacle_avoidance.md) 第四节第2条。
3. **货架部署仍需实测建模**——货架板件尺寸和允许区域必须写入并现场验证
   `shelf_template`；碰撞链正常不代表未知障碍物会自动进入场景。
4. **本轮清理之后没有一次串起来的完整真机成功**——具体哪些功能点验证到什么
   程度看上面"验证状态"表，不要笼统地说"2026-07-17的改动没验证"，各功能点
   进度差异很大。第一次上机要低速有人守观察。
5. **透明瓶深度双峰**：前壁/后壁深度相差约一个瓶径（4.5cm），带标签的不透明
   瓶没有这个问题、检测置信度也高很多（0.85 vs 0.09）。首次成功demo用的
   是不透明瓶。
6. **头部相机自训模型（`8_17.pt`）对瓶子朝向敏感**：标签背对相机时置信度
   从0.85掉到0.09，导致头部定位直接检测不到。已加yolo11n通用模型兜底
   （`bottle_grasp/perception.py` 的 `fallback_model`），但根子问题（自训
   模型泛化差）没解决，长期应该补训练数据。
7. **遥操不会自动恢复**：`RobotSession`构造时会停掉`atom`/`zhixing_ctrl`，
   demo结束不自动重启（避免意外抢串口），需要手动跑官方`upstart_all.sh`，
   或者跑demo时加`--restore-teleop`（结束保持、收到STOP后自动恢复）。

## 代码结构导览

```
bottle_grasp/
  core.py          — 共享数据类型（DemoParams参数表、Localization、SafetyAbort及子类
                      CameraFrameUnavailable/BottleDetectionLost）、位姿插值/关节插值/
                      坐标变换的几何工具函数
  head_lock.py      — 头部舵机基准角度强制校正协议，initialize()最先执行
  camera_access.py  — 按V4L2节点判定相机真实占用者、释放已知预览程序、探测/硬件
                      重启RealSense；也是独立CLI（launcher在demo启动前先单独调用）
  target_guard.py   — LockedTargetGuard（腕部丢失时最多一次头部补充确认）+
                      ProjectedTargetAssociation（锁定3D点投影关联检测框，取代
                      形状门禁）
  perception.py     — YOLO检测 + 稳健深度估计（robust_near_cluster处理透明瓶噪声）
  robot.py          — RobotSession：真实TCP/SDK连接、正逆解、movej/movel执行、
                      力控夹爪（RM Plus原生协议+空夹基线标定）、J7=0xF000瞬态
                      清错、dof_state=5/6容忍、motion失败诊断快照
  planner.py        — MoveItPlanner：子进程桥接ROS2，发规划/校验请求；
                      `_run_json_helper`统一处理超时/坏JSON/无输出
  safe_planner.py   — SafeMotionPlanner：候选排序、围栏反馈、有限换路、双重后验复核
  moveit_headless.py — 起一个只规划、不执行的move_group（ROS2节点）
  moveit_plan_once.py — 单次规划请求helper（被planner.py调用的子进程脚本）
  moveit_validate_path.py — 逐点碰撞校验helper
  moveit_collision_selftest.py — 独立诊断工具，用真机示教安全姿态做三态碰撞探针
  safety.py         — 电子围栏：FenceBox/SafetyProfile，笛卡尔空间硬校验
  safety_profiles.json — 围栏配置数据（table_demo已启用verified，shelf_template
                      是禁用的模板）
  scene.py          — RGB-D点云→体素化障碍物（喂给MoveIt）
  collision.py      — 最后接近前的点云通道检查 + selftest三态分类器
  dashboard.py       — 本地Web dashboard（实时看阶段/检测画面）
  demo.py           — BottleDemo状态机主体，run() 单一主流程（1300+行，见下方
                      "验证状态"表逐功能点核对，不要通读代码就当成已验证）

scripts/
  bottle_grasp_demo.py       — 入口，argparse
  run_bottle_grasp_resume.sh — 续抓模式launcher；先单独调camera_access CLI释放
                      相机所有权，再跑demo
  run_bottle_grasp_autonomous.sh — 全自主流程launcher（plan/observe/grasp/cycle/finish/selftest）
  start_bottle_demo.sh       — 最早的launcher（带dashboard，无新参数）
  head_position_lock.py      — bottle_grasp/head_lock.py的人工诊断命令行封装（check/restore）

test/bottle_grasp/（共69个测试，纯逻辑+mock，不连真机/ROS，全部通过不代表真机能跑）
  test_algorithms.py            — 感知/围栏算法单测（含夹取点确定性）14个
  test_camera_access.py         — 相机所有权释放/重建/硬件重启触发时机 6个
  test_gripper_judgment.py      — 空夹判定（实测基线/静态回退/夹持力） 9个
  test_head_lock.py             — 头部基准角度强制校正编排 8个
  test_motion_failures.py       — 0xF000清错、原生围栏拒绝、隐藏关节故障、rc=-6诊断 7个
  test_observation_planning.py  — run() 观察位规划编排（mock机械臂） 2个
  test_planner_adapter.py       — planner.py的_run_json_helper超时/坏JSON处理 2个
  test_pregrasp_visibility.py   — 视觉运动守卫瞬时丢失容忍/断流仍中止/投影关联 4个
  test_return_home.py           — 返回初始姿态 + finish-from-current 编排 6个
  test_safe_planner.py          — SafeMotionPlanner围栏反馈/候选降级/有限换路 4个
  test_singularity_avoidance.py — 绕接近轴避奇异重试 + J4 弯肘逃逸 10个
  test_target_guard.py          — LockedTargetGuard一次性头部确认逻辑 4个
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
- `6a6ccc3` 完整循环（示教走廊转移，**2026-07-17 已移除**）
- `5abb201` `--autonomous-observation`（**2026-07-17 已成为默认并删除标志**）

## 下一步优先级

1. **先把当前工作区提交掉**——43个文件的改动一次commit都没有，是目前最大的
   单点风险（误操作/换机器/换分支都可能丢），跟功能验证同等优先级，甚至应该
   排在前面。
2. **按"验证状态"表逐项补真机记录**，不要跳过表里标"完全没有真机运行记录"的
   项直接当成能用：`_return_home`、`LockedTargetGuard`/头部补充确认路径、
   `_plan_ik_avoiding_singularity`真正执行成功一次。低速、有人守。
3. **能连上机器人后第一件事：同步代码跑一次 `observe`，验证 narrow-band
   拒绝循环是否真的解决了**（这条已经不是"改了没测过"的悬案：根因——
   MoveIt 路径采样分辨率过粗——已经在仓库里通过 `bottle_grasp/ompl_config.py`
   直接改 `longest_valid_segment_fraction=0.0025` 从源头收紧，`moveit_headless.py`
   加载时对每个规划组生效，不再需要登录机器人改本地 `ompl_planning.yaml`；
   同时 `safety.py` 的 padding 从 `+5cm` 回调到了 `+2cm`。这两个改动组合
   起来还没有真机测过——如果又反复被拒，先把 padding 临时改回 `+0.05`
   看是否是余量问题）。
4. **完整跑通一次"头定位→观察位→抓→放回→回初始姿态"**，产出这一版代码下
   第一次成功的完整记录，不要拿2026-07-16那次（旧代码）的成功背书新代码。
5. 为货架测量并建模所有板件/立柱，启用前跑 selftest、plan、observe 分级验证
6. 多验证几次现有流程的稳定性（不同瓶子摆位、不同光照），积累"能不能复现"
   的证据，而不是只信一次成功
7. 货架部署：量出货架真实尺寸，填 `safety_profiles.json` 的 `shelf_template`，
   现场验证后把 `verified_for_execution` 改 `true`
