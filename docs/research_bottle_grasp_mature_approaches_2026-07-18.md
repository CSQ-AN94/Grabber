# 瓶子抓取实机可靠性：成熟方案调研与落地取舍

日期：2026-07-18  
范围：RealMan 双臂、ROS 2 Humble、MoveIt 2、眼在手上的 RealSense、现有 Python 抓取流程。  
目标：解决当前避障/路径执行名存实亡、腕部相机只看到部分瓶子时定位漂移、流程无法可靠恢复这三类实机问题。本文只做调研和架构决策，不改运行代码。

## 结论先行

当前最该做的不是再增加规划候选、碰撞 padding 或重试次数，而是建立三条不可绕过的实机不变量：

1. **同一关节状态在 MoveIt 与 RealMan SDK 中必须表示同一个末端和同一套碰撞几何。** 这条不成立时，“MoveIt 规划成功但本地 TCP 围栏拒绝”是必然结果，继续调安全距离只会掩盖问题。
2. **截断检测框不得直接更新瓶子三维抓取位姿。** 当前抓取高度来自“检测框内部固定比例”，看到半个瓶子时输入定义已经变了；这不是多做几帧平均能修好的噪声问题。
3. **规划、带时间参数的轨迹、控制器执行和执行中场景复核必须是一条闭环。** 当前 MoveIt 只生成离散关节路径，随后由 SDK 逐点 `movej`；MoveIt 不知道真实执行进度，也无法在场景变化时停止剩余轨迹。

成熟且适配当前项目的方向是：

- 用常驻 `PlanningSceneMonitor` 管理静态桌面、实时 OctoMap 和目标物生命周期；
- 优先审计并逐步接入 RealMan 官方 ROS 2 `ros2_control` + `FollowJointTrajectory` 链路，让 MoveIt `planAndExecute` 真正负责执行；
- 对直立瓶子采用“桌面平面 + 竖直圆柱 + 有界主动换视角”的轻量几何方案，不引入新的重训练模型；
- 用明确的 Python 状态机承载用户真正需要的两个入口，并为每个状态定义成功条件、有限重试和物理恢复动作。

## 当前实机失败证据与代码原因

| 现象 | 运行证据 / 当前实现 | 判断 |
|---|---|---|
| MoveIt 说可行，本地安全检查说碰桌 | 2026-07-18 日志中候选 9、45 多次规划成功，但 SDK-FK 的 TCP 在桌面禁入带被拒；候选 18、30、36 则返回 MoveIt 99999 | **高度怀疑** MoveIt URDF/link、工具变换、坐标系或 SDK-FK 至少一项不一致。日志不能单独证明是哪一项，因此必须先做同关节状态对照实验 |
| “碰撞测试通过”仍不能证明实机可靠 | 现有大盒子自测只能证明 PlanningScene 中的世界物体进入了 FCL；它没有验证 MoveIt 末端与 SDK TCP 重合，也没有验证实际工具包络 | 测试覆盖了一个局部机制，不是端到端安全证据 |
| 规划与执行脱节 | `moveit_plan_once.py` 只保留 `points_deg`，丢弃 `time_from_start`、速度和加速度；`robot.py` 再把路径加密为约 1.5° 的点并逐点调用阻塞式 SDK `rm_movej` | 这是“先规划、后盲执行”，不是 MoveIt 的受监控轨迹执行 |
| 场景是一次性近似快照 | `scene.py` 将深度点云稀疏成 6.5 cm 体素盒，最多 550 个；每次帮助进程重建场景 | 场景没有持续时间语义，规划后的环境变化无法触发剩余轨迹复核 |
| 目标附近人为挖出大洞 | 当前场景删除整个检测框邻域，并清除距目标 14 cm 内的场景点 | 会同时删除瓶子附近的真实障碍证据；该洞与抓取阶段/接触许可没有对象语义 |
| 半瓶检测被当成完整瓶子 | 日志中腕部框为 `(344, 165, 467, 479)`，下边正好触及 480 高图像边界；仍被判为稳定目标，并令基座三维目标相对旧锁漂移 147.3 mm | 这是确定性的截断偏差，不是随机深度噪声 |
| 抓取高度依赖可见框高度 | `perception.py` 用 `v = y1 + 0.66 * (y2 - y1)` 选抓取像素；各语义区也都是检测框的固定百分比 | 框被裁掉上半或下半后，“66%”不再对应同一物理高度 |
| 深度单位有隐含假设 | 相机做了 `rs.align`，但用固定 `/1000` 转米，没有从深度传感器查询 `get_depth_scale()` | 多数设备可能恰好是 0.001 m/单位，但不应把设备属性当成算法常量 |
| 流程恢复依赖“上次应该做到哪” | `demo.py` 是长过程加分支；resume 会加载最近定位并推断接下来该做什么 | 重启后不能可靠回答“物体是否还在手中、场景是否仍有效、应退还是应继续” |

## 1. 让避障与路径规划真正约束实机

### 1.1 P0：先建立同一关节状态不变量

在继续改规划参数前，从真实工作区采集一组右臂关节状态，至少覆盖观察位、预抓取、桌边、放置位和回撤位。对每个状态同时计算：

- MoveIt 中 `r_link7` 的位姿；
- MoveIt 中实际夹具 TCP 的位姿，包含固定工具变换；
- RealMan SDK FK 返回的 TCP 位姿；
- 夹具碰撞模型最低点相对已标定桌面的有符号距离。

建议把平移不一致不超过 5 mm、姿态不一致不超过 0.5° 作为首轮工程门槛；这是本项目的建议验收值，不是上游文档给出的通用保证。若达不到，按以下顺序修正：

1. 关节名称、顺序、弧度/角度单位和零位；
2. `base_link`、机器人安装基座与桌面标定坐标；
3. `r_link7` 到 SDK TCP 的固定变换；
4. 夹具/相机/防护罩碰撞网格的原点、尺度和方向；
5. MoveIt 当前关节状态的时间戳与真实控制器状态是否对应同一时刻。

只有这项通过后，桌面 padding、TCP 围栏和 MoveIt 碰撞结果才有共同物理含义。现有“巨型障碍物必定失败”测试可以保留，但应增加多个已标定的小障碍：分别贴近前臂、腕部、夹具侧面和桌面上方，确认碰撞 link、接触点和距离都符合预期。

### 1.2 P1：把场景改成一个常驻、可追溯的事实源

MoveIt 的 [`PlanningSceneMonitor`](https://moveit.picknik.ai/humble/doc/concepts/planning_scene_monitor.html) 本来就是用于持续合并机器人状态、TF 和世界几何的组件；深度或点云更新器生成的占据栅格会进入 FCL 碰撞检测。官方 [Perception Pipeline 教程](https://moveit.picknik.ai/humble/doc/examples/perception_pipeline/perception_pipeline_tutorial.html) 给出了 `PointCloudOctomapUpdater` 的点云话题、范围、子采样、padding 和更新频率配置，并包含机器人自过滤。

建议场景分三层：

| 层 | 表示 | 原因 |
|---|---|---|
| 标定的固定环境 | 桌面、桌沿、底座等解析 `CollisionObject` | 桌面是安全基准面，不应依赖稀疏深度是否恰好看到 |
| 未知/移动障碍 | 头部深度点云生成的 OctoMap，带 TF、时间戳、自过滤和最大时效 | 保留环境证据，并能持续更新 |
| 任务对象 | 有 ID 的瓶子解析圆柱或保守包络 | 允许按抓取阶段改变接触关系、附着和放下后的世界位置 |

不要继续使用“删除目标框 + 清掉目标周围 14 cm 所有点”的全局洞。应采用 MoveIt 官方 PlanningScene 对象生命周期：

1. 瓶子最初是世界碰撞对象；
2. 只有在最终接触阶段，才在 Allowed Collision Matrix 中允许瓶子与指定手指/手掌 link 接触；
3. 抓取验证成功后，将瓶子从世界对象转为 attached object；
4. 搬运期间，瓶子随机器人作为碰撞几何参与规划；
5. 释放验证成功后 detach，并以实际放置位重新加入世界。

MoveIt 的 [Planning Scene ROS API 教程](https://moveit.picknik.ai/humble/doc/examples/planning_scene_ros_api/planning_scene_ros_api_tutorial.html) 展示了同步 `ApplyPlanningScene`、添加/移除以及 attach/detach；[Planning Scene 教程](https://moveit.picknik.ai/humble/doc/examples/planning_scene/planning_scene_tutorial.html) 说明 ACM 会忽略被允许的特定碰撞。因此 `touch_links` 必须尽量窄，只包含真实会接触瓶子的手指/手掌，不要全局放开目标周边碰撞。

每次规划都应保存可复现的“场景证据包”：关节状态及时间戳、TF 时间戳、场景版本、对象 ID、OctoMap 时间戳/哈希、规划请求、碰撞接触/最小距离和最终带时间参数轨迹。这样一次实机失败才能在离线重放时回答“当时规划器看到了什么”。

### 1.3 P1/P2：让 MoveIt 的轨迹成为控制器真正执行的轨迹

MoveIt 的规划结果经过时间参数化后才是满足速度和加速度约束的轨迹；官方 [Motion Planning 概念文档](https://moveit.picknik.ai/humble/doc/concepts/motion_planning.html) 明确区分了几何路径和时间化轨迹。当前项目只提取位置点，再由 SDK 逐点运动，丢失了这层约束。

更可靠的目标链路是：

```text
PlanningSceneMonitor
        ↓
MoveGroup planAndExecute
        ↓
带 time_from_start / velocity / acceleration 的 JointTrajectory
        ↓
FollowJointTrajectory action
        ↓
RealMan ros2_control 控制器 + 高频关节反馈
```

这不是从零造桥。RealMan 官方 [`ros2_rm_robot` Humble 分支](https://github.com/RealManRobot/ros2_rm_robot/tree/humble/rm_moveit2_config) 已提供控制真实机械臂的 MoveIt 2 配置；其 [MoveIt 控制器配置](https://github.com/RealManRobot/ros2_rm_robot/blob/humble/rm_moveit2_config/rm_75_config/config/moveit_controllers.yaml) 使用 `FollowJointTrajectory`，对应的 [`ros2_controllers.yaml`](https://github.com/RealManRobot/ros2_rm_robot/blob/humble/rm_moveit2_config/rm_75_config/config/ros2_controllers.yaml) 配置了 7 关节的 `JointTrajectoryController` 和 100 Hz 更新率。应先在单右臂隔离环境核对具体机型、固件、关节命名和双臂 namespace，再移植，不能直接把官方单臂 launch 当成当前双臂系统的无条件替换。

ROS 2 [`JointTrajectoryController`](https://control.ros.org/humble/doc/ros2_controllers/joint_trajectory_controller/doc/userdoc.html) 以 `FollowJointTrajectory` action 作为带执行监控的主要接口，并支持 path/goal tolerance；超差时可中止并保持。MoveIt Humble 上游的 [`PlanExecution`](https://github.com/moveit/moveit2/blob/humble/moveit_ros/planning/plan_execution/src/plan_execution.cpp) 会在场景更新后复查剩余轨迹，若剩余路径失效则停止执行；[`MoveActionCapability`](https://github.com/moveit/moveit2/blob/humble/moveit_ros/move_group/src/default_capabilities/move_action_capability.cpp) 的 plan-and-execute 路径正是调用这一机制。起点一致性还应使用 TrajectoryExecutionManager 的 [`allowed_start_tolerance`](https://github.com/moveit/moveit2/blob/humble/moveit_ros/planning/trajectory_execution_manager/src/trajectory_execution_manager.cpp) 和控制器跟踪容差。

在官方控制桥尚未验证前，可以暂时保留 SDK 执行，但必须明确它只是过渡方案，并至少增加：

- 每段执行前检查真实关节与轨迹起点；
- 检查场景新鲜度，场景过期不得启动；
- 每段后比较期望与实际关节/TCP，超差即停止，不自动进入下一段；
- 场景变化后重新验证剩余路径；
- 保存一条已验证的回撤路径，但不能在新障碍出现后盲目反向播放。

这些措施仍不等价于 `planAndExecute` + `FollowJointTrajectory` 的统一执行监控。

## 2. 半瓶视野下的可靠抓取定位

### 2.1 必须先把“看不完整”变成显式状态

检测框距任意图像边缘小于 3–5 px，或小于图像尺寸约 1%–2%，就应标记为 `TRUNCATED`。阈值是工程起点，应由相机畸变、检测抖动和保存帧回放校准。2026-07-18 日志中的 `y2 = 479`、图像高度 480 是无歧义的下边缘截断，不能继续走完整目标定位分支。

截断状态下的硬规则：

- 禁止使用检测框高度推导瓶身抓取高度；
- 禁止让单次截断测量覆盖完整视野建立的三维目标锁；
- 可以将可见 RGB-D 数据用于横向中心的小幅修正，但只有在模型残差和多帧不确定度都下降时才接受；
- 证据不足就主动换视角，不能用“上一次深度 + 这一次框比例”拼出一个看似完整的三维位姿。

### 2.2 推荐的轻量几何估计器

对当前“桌上直立瓶子”这一受限任务，优先使用可解释的几何约束：

1. 使用 RealSense 的彩深对齐，并从设备查询真实 `depth_scale`。Intel 的官方 [Python 对齐示例](https://github.com/IntelRealSense/librealsense/blob/master/wrappers/python/examples/align-depth2color.py) 同时执行 `rs.align` 和 `get_depth_scale()`。
2. 在目标邻域拟合桌面平面 `\(\mathbf n^\top \mathbf p + d = 0\)`；平面法向应与标定的基座竖直方向一致。
3. 去除平面点，在剩余支持点上拟合轴线接近桌面法向的圆柱，半径限制来自实际瓶型范围。
4. 用圆柱轴/横截面中心估计水平位置；抓取高度取“桌面平面以上的已配置安全夹持带”，而不是检测框内部比例。
5. 输出的不只是位姿，还包括有效深度点数、圆柱内点率、残差、可见圆弧覆盖、多帧漂移和桌面拟合质量。

PCL 官方 [圆柱分割教程](https://pointclouds.org/documentation/tutorials/cylinder_segmentation.html) 给出了“距离裁剪 → 法向估计 → RANSAC 平面分割 → 基于法向的圆柱模型和半径限制”的成熟流程，其 [`SACSegmentationFromNormals`](https://pointclouds.org/documentation/classpcl_1_1_s_a_c_segmentation_from_normals.html) 是参考实现。当前仓库已有 NumPy/SciPy，首版可以复用同样的受约束 RANSAC/最小二乘思想而不必立刻引入整个 PCL 运行时。

透明、反光或仅有极少可见弧段时，深度圆柱也可能不可辨识。正确行为是返回“不可观测”，不是强行补全。完整头部视角建立的目标锁可以作为先验，但必须带协方差/置信区间；腕部截断观测只有在通过关联门限且降低不确定度时才更新它。

### 2.3 有界主动换视角，而不是重训练一个补全网络

当前最小可用策略是为腕部观察定义一个质量窗口：目标框四边均有边距、中心接近期望像素、尺度在合理范围、深度有效率和模型残差达标。若不满足：

1. 从当前安全位后退少量，避免近距离放大导致再次截断；
2. 生成最多 2–3 个小幅、碰撞检查过的观察候选，让目标回到质量窗口；
3. 每次移动后重新采集，不复用移动前的像素/深度；
4. 达到重试上限仍不可观测则安全终止，不进入预抓取。

这可以复用现有观察位候选思想，但评价函数必须同时考虑图像质量、几何可观测性、运动代价和抓取可达性。ICRA 2024 的 [ActPerMoMa 原论文](https://arxiv.org/abs/2310.00433) 使用滚动时域采样路径，并在效用中权衡信息增益、运动代价和抓取可达性，且展示了实机迁移。当前项目只应借鉴其“有界下一最佳视角”思想，不应照搬完整移动操作、TSDF 和抓取网络栈。

MoveIt [`Servo`](https://moveit.picknik.ai/humble/doc/examples/realtime_servo/realtime_servo_tutorial.html) 可以接收笛卡尔或关节增量命令，并处理碰撞、奇异位形和关节限制，适合后续视觉伺服居中。不过它要求控制器能高频接收位置/速度命令并提供快速、准确的关节反馈。当前阻塞式 SDK 逐点执行不满足这个前提，因此：

- P0：使用低速、有限步数、每步完整规划的换视角动作；
- P2：官方 100 Hz `ros2_control` 执行链通过验证后，再使用 Servo 做最后的小范围图像居中/位姿精修。

## 3. 两个入口、一个共享的可恢复抓放状态机

用户需要的不是十几个可自由组合的内部模式，而是两个稳定入口：

```text
完整流程：HEAD_START → 头部定位/建场景 → 右臂观察位 → 共享抓放流程
观察位流程：WRIST_START → 确认右臂确在观察位 → 共享抓放流程
```

共享流程建议显式拆为：

```text
PREFLIGHT
→ TARGET_LOCKED
→ SCENE_VALID
→ WRIST_OBSERVE
→ REFRAME_IF_NEEDED
→ PREGRASP
→ FINAL_APPROACH
→ GRASP_VERIFY
→ ATTACH_OBJECT
→ LIFT_VERIFY
→ PLACE
→ RELEASE_VERIFY
→ DETACH_OBJECT
→ RETREAT
→ HOME
→ DONE
```

每个状态必须拥有五项定义：进入前置条件、唯一动作、可测量的成功后置条件、有限次数恢复动作、失败后的安全状态。关键恢复规则如下：

| 失败位置 | 允许恢复 | 禁止行为 |
|---|---|---|
| 接触前感知失败 | 有界换视角后重新观测；用尽次数则停在已验证安全位 | 继续使用过期目标锁进入预抓取 |
| 规划失败 | 刷新场景，换下一个有限候选 | 无上限地改 padding、扩大 ACM 或重试同一请求 |
| 执行偏差或场景过期 | 减速停/保持，重新同步关节和场景 | 自动执行旧回撤轨迹 |
| 闭夹后抓取验证失败 | 仅在反向路径仍有效时打开、回撤、重观测；最多一次重新抓取 | 在未知接触状态下直接回观察位 |
| 抬升后确认物体在手 | 保持 attached 几何；优先安全放置或原地保持等待人工 | 按“空手”路径回 HOME |
| 释放未确认 | 保持 attached 状态并停止 | 先 detach 再假定瓶子已经放稳 |

检查点应以原子方式写入小型 journal，至少包含：`run_id`、状态、关节状态/时间、目标估计及不确定度、场景版本、夹爪/抓取证据、对象是否 attached、最后一条经过验证的回撤轨迹。重启时先重新感知和读取关节/夹爪，协调“记录状态”与“物理状态”；不能根据最新一份定位文件直接猜测继续点。

MoveIt Task Constructor 的 [Pick and Place 教程](https://moveit.picknik.ai/humble/doc/tutorials/pick_and_place_with_moveit_task_constructor/pick_and_place_with_moveit_task_constructor.html) 已把连接、抓取、允许局部接触、attach、放置、detach 和回家建模为可诊断 stage，值得借鉴其对象生命周期与阶段失败语义。但当前主流程是 Python，且只需要两个入口，P0 没必要先重写成 MTC。

同样，[BehaviorTree.CPP 基础](https://www.behaviortree.dev/docs/learn-the-basics/BT_basics/) 的 Sequence/Fallback、[Decorator](https://www.behaviortree.dev/docs/nodes-library/DecoratorNode/) 的有限重试/超时和 Nav2 的 [RecoveryNode](https://docs.nav2.org/configuration/packages/bt-plugins/controls/RecoveryNode.html) 都是成熟恢复语义；但它们主要是 C++/ROS 2 生态。现在应先用 Python `Enum` + 转移表实现同样的有界语义，等运动执行全面迁入 ROS 2 后再评估 BT.CPP/MTC，避免一次性引入新的跨语言运行栈。

## 4. 分阶段落地顺序与实机验收

| 优先级 | 必须交付 | 未通过时不得做什么 |
|---|---|---|
| P0-A | MoveIt FK/工具几何与 SDK FK 的同状态对照；桌面有符号距离一致 | 不得继续通过改 padding“调到能走” |
| P0-B | 截断门控；完整框/截断框走不同分支；截断观测不能覆盖抓取高度 | 不得从触边框直接进入预抓取 |
| P0-C | 两入口显式状态机；每状态后置条件、有限重试、物体在手恢复规则 | 不得继续用隐式 resume 猜测物理状态 |
| P1-A | 常驻 PlanningSceneMonitor；静态桌面 + 实时 OctoMap + 瓶子对象生命周期 | 不得依赖 14 cm 目标洞作为接近策略 |
| P1-B | 桌面 + 圆柱几何估计和 2–3 次有界换视角 | 不得用更多帧平均掩盖结构性截断偏差 |
| P1-C | 审计并接入 RealMan 官方 `FollowJointTrajectory` 控制链；保留完整时间轨迹 | 不得把 MoveIt 位置点拆成 SDK 盲走点后宣称“MoveIt 执行” |
| P2 | `planAndExecute` 场景更新停机、控制器容差、可选 MoveIt Servo 精修 | 不得在阻塞式低频 SDK 链上直接启用 Servo |

本地单元测试仍然有价值，但只能证明局部函数。上线门禁应分四层：

1. **确定性回放**：保存彩色图、对齐深度、检测框、TF、关节和场景；重放本次 `y2=479` 案例以及对完整图像人工裁边的合成案例，确保输出 `TRUNCATED` 且目标高度不更新。
2. **几何一致性台架**：用实机关节记录验证 MoveIt/SDK FK；在已知位置放泡沫障碍，检查正确 link/contact，而不只测巨型盒子。
3. **无抓取低速执行**：低速运行观察位、预抓取和回撤；记录期望/实际轨迹与最小碰撞距离；执行中插入新的安全软障碍，确认会停止而不是走完旧路径。
4. **分层实机任务**：先固定无遮挡瓶，再做轻微截断需换视角，再做场景中有软障碍；分别验证“完成任务”和“无法保证时安全终止”。

最终验收报告应同时给出任务成功率、安全终止率、失败状态分布、轨迹跟踪最大误差、场景年龄和感知不确定度。只有“测试全部通过”而没有这些实机证据，不能代表系统可用。

## 5. Adopt / Do not adopt

| 方案 | 决策 | 原因 |
|---|---|---|
| MoveIt PlanningSceneMonitor + OctoMap + 解析桌面 | Adopt | 与 Humble/现有 MoveIt 兼容，解决场景持续性和未知障碍表示 |
| 瓶子 world/attached 生命周期 + 阶段局部 ACM | Adopt | 用对象语义替代目标周围大洞，搬运时瓶子也参与碰撞 |
| RealMan 官方 ros2_control + FollowJointTrajectory | 先隔离审计，再 Adopt | 上游已有真实机械臂链路；需适配当前双臂 namespace、机型和固件 |
| 桌面平面 + 竖直圆柱 + 不确定度 | Adopt | 任务先验强、可解释、无需训练；证据不足时能明确拒绝 |
| 有界下一最佳视角 | Adopt 精简版 | 直接解决眼在手上近距离截断；只需少量规划候选 |
| MoveIt Servo | Later | 需先有高频控制/反馈和经过验证的碰撞模型 |
| Python 显式 FSM | Adopt | 两个入口足够，能立即定义恢复和 checkpoint |
| 全量 MTC / BT.CPP 重写 | Not now | 会扩大改动面；先借用 stage/retry 语义即可 |
| cuRobo / Isaac / GPU 规划栈 | Do not adopt | 当前瓶颈是几何/坐标/执行闭环不一致，不是求解速度；会引入第二套碰撞世界 |
| ClearGrasp、TransCG、NeRF 或新抓取网络 | Do not adopt now | 当前失败是可复现的边界截断和任务几何问题；训练、域偏移和部署成本不能修复执行链 |
| 完整 ActPerMoMa/TSDF 移动操作栈 | Do not adopt | 对固定双臂桌面任务过重；只借鉴效用与滚动换视角 |
| 全局放开目标碰撞 / 继续扩大场景洞 | Do not adopt | 会删除真实障碍和非手指接触，安全风险不可接受 |
| 在 FK 不一致前继续调 padding/重试 | Do not adopt | 参数会补偿另一个坐标系的错误，换姿态后仍会失效 |

## 一手资料索引

- MoveIt 2 Humble: [Planning Scene Monitor](https://moveit.picknik.ai/humble/doc/concepts/planning_scene_monitor.html)、[Perception Pipeline](https://moveit.picknik.ai/humble/doc/examples/perception_pipeline/perception_pipeline_tutorial.html)、[Planning Scene ROS API](https://moveit.picknik.ai/humble/doc/examples/planning_scene_ros_api/planning_scene_ros_api_tutorial.html)、[Planning Scene / ACM](https://moveit.picknik.ai/humble/doc/examples/planning_scene/planning_scene_tutorial.html)、[MoveIt Task Constructor Pick and Place](https://moveit.picknik.ai/humble/doc/tutorials/pick_and_place_with_moveit_task_constructor/pick_and_place_with_moveit_task_constructor.html)、[MoveIt Servo](https://moveit.picknik.ai/humble/doc/examples/realtime_servo/realtime_servo_tutorial.html)。
- MoveIt 2 Humble 上游实现: [`plan_execution.cpp`](https://github.com/moveit/moveit2/blob/humble/moveit_ros/planning/plan_execution/src/plan_execution.cpp)、[`trajectory_execution_manager.cpp`](https://github.com/moveit/moveit2/blob/humble/moveit_ros/planning/trajectory_execution_manager/src/trajectory_execution_manager.cpp)、[`move_action_capability.cpp`](https://github.com/moveit/moveit2/blob/humble/moveit_ros/move_group/src/default_capabilities/move_action_capability.cpp)。
- RealMan 官方 ROS 2: [`ros2_rm_robot` Humble](https://github.com/RealManRobot/ros2_rm_robot/tree/humble)、[`rm_moveit2_config`](https://github.com/RealManRobot/ros2_rm_robot/tree/humble/rm_moveit2_config)、[官方 ROS 2 Driver 文档](https://aa.realman-robotics.com/robot/ros2/driver/)。
- ROS 2 Control: [`JointTrajectoryController` Humble 文档](https://control.ros.org/humble/doc/ros2_controllers/joint_trajectory_controller/doc/userdoc.html)。
- Intel RealSense: [`align-depth2color.py`](https://github.com/IntelRealSense/librealsense/blob/master/wrappers/python/examples/align-depth2color.py)。
- PCL: [Cylinder segmentation tutorial](https://pointclouds.org/documentation/tutorials/cylinder_segmentation.html)、[`SACSegmentationFromNormals`](https://pointclouds.org/documentation/classpcl_1_1_s_a_c_segmentation_from_normals.html)。
- 原论文: Jauhri, Lueth, Chalvatzaki, [Active-Perceptive Motion Generation for Mobile Manipulation (ActPerMoMa), ICRA 2024](https://arxiv.org/abs/2310.00433)。
- 恢复语义: [BehaviorTree.CPP Basics](https://www.behaviortree.dev/docs/learn-the-basics/BT_basics/)、[Decorator Nodes](https://www.behaviortree.dev/docs/nodes-library/DecoratorNode/)、[Nav2 RecoveryNode](https://docs.nav2.org/configuration/packages/bt-plugins/controls/RecoveryNode.html)。

## 结论边界

上游资料证明了这些组件具备相应机制，但不证明它们在本机器人的当前 URDF、标定、双臂 namespace 和厂商固件上已经正确集成。本文把“MoveIt/SDK 几何不一致”列为日志支持的高概率推断，而非既成事实；P0 同状态对照实验就是用来确认或否定它。任何方案只有通过上述分层实机门禁，才能从“架构上合理”升级为“当前机器人可用”。
