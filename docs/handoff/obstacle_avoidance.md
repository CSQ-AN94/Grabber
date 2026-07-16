# 机械臂避障/运动规划 — 领域介绍 + 本项目的具体应用

写这份文档的目的：让你（或者你带去问的另一个AI）能快速理解"避障"在机械臂
控制里到底是什么、有哪几层、以及本项目现在具体卡在哪一层的哪个问题上。

## 一、这个领域在解决什么问题

核心问题一句话：**给定机械臂的运动学模型和环境里障碍物的位置，找一条从起点
到终点、机械臂任何部位都不会撞的路径**。

### 1.1 构型空间（Configuration Space, C-space）

机械臂有几个关节就有几维自由度——本项目的RM75是7自由度，对应一个7维空间，
每个点代表"7个关节各转到多少度"这一个具体姿态。这个抽象空间叫**构型空间**，
跟"手在三维世界里的哪个位置"（任务空间/笛卡尔空间）是两回事：任务空间三维，
构型空间七维，两者之间的映射就是正解/逆解（forward/inverse kinematics）。

避障规划的本质是：**在这个7维构型空间里搜一条路径，使得路径上每一点对应的
机械臂姿态，在三维世界里都不跟障碍物相交**。之所以要转到构型空间讨论，是
因为"任务空间里两点连直线"不代表"关节空间里对应的路径不穿过障碍"——机械臂
中间那几节连杆的位置不是任务空间目标点决定的，要看具体走的是哪条关节路径。

### 1.2 碰撞检测：规划器怎么知道"撞没撞"

规划器每验证一个候选姿态，都要做一次**碰撞检测**：这个姿态下，机械臂的每个
连杆（以及末端工具）跟环境障碍物、跟自己的其它连杆，有没有几何相交。

- 机械臂自身的碰撞几何来自URDF里的`<collision>`标签（跟渲染用的`<visual>`
  网格是分开定义的两套，`<collision>`通常用更简单的几何体，检测更快）
- 环境障碍物通常表示成简单几何体（长方体/圆柱/球），不会直接拿原始点云做碰撞
  检测（太慢）——所以第一步永远是"把感知数据（点云）转换成简化的障碍物几何"
- 自碰撞（self-collision）额外需要一张"允许碰撞矩阵"（Allowed Collision
  Matrix, ACM）：相邻连杆天生贴在一起，必须显式声明"这两个允许碰"，否则会
  一直误报"自己撞自己"

### 1.3 规划算法：采样式规划（Sampling-Based Planning）

7维空间穷举搜索不现实，主流做法是**采样式规划**：随机在构型空间里撒点，
检查每个点是否无碰撞，把无碰撞的点两两尝试连线（同样要做碰撞检测），逐步长出
一棵树或一张图，直到连通起点和终点。代表算法：

- **RRT / RRT-Connect**：从起点（和终点）各长一棵随机树，尝试让两棵树握手
- **PRM**（Probabilistic Roadmap）：先在自由空间随机撒一堆点建图，之后复用

这些算法都在 **OMPL**（Open Motion Planning Library）这个库里实现好了，
**MoveIt2 通过 OMPL 插件调用它们**——这就是为什么 `bottle_grasp/moveit_headless.py`
里配置的是 `"planning_plugin": "ompl_interface/OMPLPlanner"`。具体用哪个采样
算法（RRTConnect是大多数MoveIt配置的默认值）由机器人那边安装的
`dual_rm_75b_moveit_config` 包里的 `ompl_planning.yaml` 决定，这个仓库里
没有这份文件（它是ROS包自带的，装在机器人系统里，不在这个git仓库管理范围）。

### 1.4 纵深防御：为什么不能只信规划器

工业界的标准做法是**纵深防御（defense in depth）**：规划器/碰撞检测这套链路
环节很多（URDF加载→碰撞几何解析→规划场景同步→采样规划→碰撞检测插件），
任何一环出问题都可能让"避障"变成"以为在避障、其实完全没避"——而且很可能是
**静默失效**（不报错，只是永远说"没有碰撞"），本项目现在遇到的正是这种情况。

所以正确做法是加一层**跟规划器逻辑完全独立、简单到不太可能出错**的硬限制：
通常是笛卡尔空间里的长方体禁区（业内叫 geofence / 电子围栏），执行前逐点做
纯几何校验，不依赖"规划器说没碰撞"这句话。

## 二、本项目具体怎么落地这套东西

对着代码看：

| 层 | 作用 | 代码位置 | 现状 |
|---|---|---|---|
| 感知→障碍物 | RGB-D点云体素化 | `bottle_grasp/scene.py` | 正常工作 |
| ROS2/MoveIt2桥接 | 起规划服务、发规划请求 | `bottle_grasp/planner.py`、`moveit_headless.py`、`moveit_plan_once.py`、`moveit_validate_path.py` | 服务能起来、能返回"规划成功"，但碰撞检测本身失效（见下） |
| 采样规划算法 | OMPL在7维构型空间搜路径 | 机器人上的ROS包，本仓库不管理 | 未知（依赖碰撞检测，检测坏了规划质量无法评估） |
| **电子围栏（真正在工作的防线）** | 执行前笛卡尔空间硬校验 | `bottle_grasp/safety.py` + `safety_profiles.json` | **正常工作，2026-07-16晚两次正确拦截了违规路径** |
| 执行时关节安全 | 关节限位余量、J4奇异区、单步跳变 | `bottle_grasp/robot.py` 的 `plan_ik` | 正常工作 |

**关键认知**：MoveIt负责"聪明地绕障碍"，电子围栏负责"绝不越线"。当前MoveIt
这层的碰撞检测坏了，但因为电子围栏这层独立存在，系统整体还是fail-closed的
（规划器出的坏路径会被拦下、安全中止，而不是被执行）——只是牺牲了"自主绕开
复杂障碍"的能力，退化成"人工划好安全区域、规划器只能在区域内活动"。

## 三、当前诊断：MoveIt碰撞检测失效（未完全查明根因）

### 3.1 已确认的现象

2026-07-16凌晨，用真实机械臂位姿做了几组独立验证：

1. 构造一个关节配置，使TCP笛卡尔位置落在已配置的桌面禁入盒**内部约3cm**处，
   直接调用ROS2服务 `/check_state_validity` 查询——返回 `valid=True, contacts=[]`
2. 把同一个方向再往深处推到**内部约10cm**（IK仍有解、机械臂姿态合理）——
   仍然 `valid=True`
3. 反过来验证：调用 `/get_planning_scene` 确认碰撞物确实在场景里
   （`fence_table_top` 长方体存在、尺寸合理）、末端工具防撞体
   （`bottle_tool_guard`）已正确附着在 `r_link7` 上、ACM里有34个连杆条目
   （看起来是正常的自碰撞豁免表）——**场景数据本身看起来是对的**，但
   `check_state_validity` 就是不认它

4. 独立用MoveIt的规划服务 `/plan_kinematic_path` 请求一条"终点在桌子内部
   15cm"的轨迹——**规划直接成功**，返回轨迹，说明规划采样阶段全程没有触发
   任何碰撞拒绝

这四点合起来结论很明确：**MoveIt的碰撞检测这一步，无论是单点查询
（check_state_validity）还是规划过程中的内部调用，都没有真正生效**。

### 3.2 已经排除/修过但不是根因的

- `RobotState.is_diff` 没设为 `True`：这是个真实的bug（非diff状态会把附着的
  工具防撞体从场景里替换掉），已在 `moveit_plan_once.py` 和
  `moveit_validate_path.py` 里修了，但修完之后碰撞检测**依然**对上面的测试
  配置返回 `valid=True`——说明这不是（唯一）根因

### 3.3 尚未查明、留下的可疑线索

`bottle_grasp/moveit_headless.py` 启动 `move_group` 时的日志里有这一行没深挖：

```
[moveit_ros.planning_scene_monitor.planning_scene_monitor]: Failed to fetch current robot state.
```

这条警告值得怀疑，原因：`moveit_headless.py` 里故意把
`joint_state_topic` 配成了 `"/unused_joint_states"`（因为这套架构不用TF/实时
关节状态驱动规划场景，而是每次请求里显式带 `start_state`）——但如果
planning_scene_monitor **从来没拿到过一次初始机器人状态**，它内部维护的
"当前监控场景"里的机器人状态可能是某种未初始化/默认值。当请求带
`is_diff=True` 的部分RobotState进来做合并时，合并逻辑如果依赖这个从未正确
初始化的基准状态，行为可能不可预测——这跟"碰撞检测对任何输入都说没碰撞"这个
现象方向上是吻合的，但**没有实证，只是最可疑的一条线索**，需要下次实际验证。

### 3.4 还没跑完的实验

- **自碰撞探针**：构造两个"肘部严重折叠、大概率自己撞自己"的关节配置
  （`[0,100,0,150,0,0,0]` 和 `[0,0,0,170,0,0,0]`），准备验证自碰撞检测是否
  也失效（跟世界碰撞失效是不是同一个根因）——**命令已经写好但机器人在这一步
  掉线了，没有跑出结果**
- **巨型盒子世界碰撞探针**（`bottle_grasp/moveit_collision_selftest.py`）：
  往场景里放一个4m³的巨型盒子把整台机器人罩住，任何可达姿态理论上都必然相交，
  如果还报`valid=True`几乎能实锤"机器人自身碰撞几何没加载"这个方向。**这个
  脚本写完后同样因为机器人掉线，从没有实际跑过一次**，下次开机的第一件事
  应该是跑它（`scripts/run_bottle_full_cycle.sh selftest`）

### 3.5 建议的排查方向（按怀疑程度排序）

1. **先跑 `moveit_collision_selftest.py`**：如果巨型盒子都测不出碰撞，几乎
   可以确定是"机器人自身碰撞几何没被加载进regulatory scene"这个方向，重点
   查 `dual_rm_75b_moveit_config` 包里的URDF `<collision>` 标签/网格路径是否
   正确、`robot_state_publisher` 是否真的把完整模型发布出去了
2. **追查"Failed to fetch current robot state"**：看这条警告具体在
   `planning_scene_monitor` 源码的哪个分支触发，以及它是否真的导致内部碰撞
   世界跟"机器人当前状态"没有正确关联
3. **跑自碰撞探针**：如果自碰撞也失效但世界碰撞（盒子测试）正常，说明问题
   窄化在"世界障碍物没被真正注册进碰撞矩阵"这一侧，而不是机器人自身几何
4. 对照一份**已知能正常工作的MoveIt2最小示例**（比如MoveIt2官方教程里的
   panda机械臂demo）逐项diff配置差异，缩小范围

## 四、参考资料

- **MoveIt2官方教程**（moveit.picknik.ai）——直接搜 "MoveIt2 Planning Scene
  tutorial"、"MoveIt2 collision objects"，这两个概念直接对应本项目现在的坑
- **OMPL官方文档**（ompl.kavrakilab.org）——想搞懂RRT这类采样规划算法怎么工作
- **Steven LaValle《Planning Algorithms》**——这个领域最经典的教材，作者主页
  有免费全文PDF，偏理论但把C-space/采样规划的本质讲透了
- 带着诊断细节去问AI时可以用的关键词：`MoveIt2 check_state_validity always
  returns valid`、`MoveIt2 collision geometry not loading from URDF`、
  `planning_scene_monitor Failed to fetch current robot state`、
  `moveit RobotState is_diff attached collision object`
