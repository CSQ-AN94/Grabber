# 底盘 ROS2 控制说明

配合 [chassis_diagnostic_report.md](chassis_diagnostic_report.md) 使用，记录如何通过 ROS2 控制这台 Woosh AGV 底盘，以及目前的测试结论。

## 1. 安装

官方提供 ROS2 Humble/Jazzy 版本的机器人代理程序，来自客服提供的资料包 `产品二次开发资料/软件二次开发接口/应用层ROS2接口/`。机器人电脑（`192.168.3.68`）装的是 ROS2 Humble，用的是：

```
ros-humble-woosh-robot-agent_0.0.6-0jammy_arm64.run
```

安装（需要 sudo，会用 dpkg 装几个包并写 `/etc/ld.so.conf.d/woosh.conf`）：

```bash
chmod +x ros-humble-woosh-robot-agent_0.0.6-0jammy_arm64.run
sudo ./ros-humble-woosh-robot-agent_0.0.6-0jammy_arm64.run
```

装完会有一个可执行文件：`/opt/ros/humble/lib/woosh_robot_agent/agent`。这个程序本质是把 Woosh 网络 SDK（`169.254.128.2:5410`）包了一层 ROS2 服务/话题壳，**不是**独立的控制通道。

## 2. 启动 agent

```bash
source /opt/ros/humble/setup.bash
/opt/ros/humble/lib/woosh_robot_agent/agent
```

启动后会自动连底盘，注册一堆 `/robot/*` 话题和服务。查看：

```bash
ros2 topic list      # 状态类：/robot/PoseSpeed /robot/Mode /robot/RobotState /robot/HardwareState ...
ros2 service list    # 控制类：/robot/Twist /robot/SwitchControlMode /robot/InitRobot /robot/ActionOrder ...
```

**注意**：这个版本的 agent 只暴露了和 SDK 一一对应的服务（`/robot/Twist` 对应 SDK 的 `twistReq`），**没有**暴露官方 ROS 接口文档里提到的 `/base_cmd_vel`、`/cmd_vel_control` 这类"绕过状态限制"的话题——那两个话题可能属于另一个更完整的应用层节点（本资料包里没有对应安装包），不是这个 `agent` 提供的。

## 3. 测试脚本

`agv_debug_tools/ros_chassis_turn_test.sh`（在机器人上，`/home/rm/agv_debug_tools/` 目录）：

```bash
./ros_chassis_turn_test.sh [角速度rad/s，默认0.12] [持续秒数，默认15]
```

流程：确保 agent 在跑 → 切换到自动模式（`SwitchControlMode`）→ 初始化（`InitRobot`）→ 查询转动前位姿 → 循环发送转动指令 → 停止 → 查询转动后位姿。

**执行前必须确认现场安全**（周围无人/无障碍物、有人看护），这是会真实发送速度指令的测试。

## 4. 已验证结论（2026-07-06）

用这个脚本走了一遍完整流程：切自动模式成功、初始化成功（`kUninit→kIdle`）、转动指令连续发送约 15 秒（角速度 0.12 rad/s）全部返回成功。但转动前后 `theta` 只变化约 0.014 rad（约 0.8°），和之前用原始 C++ SDK 程序测试时看到的"噪声级别漂移"（0.01~0.02 rad）完全一致——**不是真实物理转动**。

**结论：ROS 和原始 SDK 走的是同一条底层协议，结果完全一样零响应。** 这排除了"之前的 C++ 测试代码写得有问题"这种可能性，进一步支持 [chassis_diagnostic_report.md](chassis_diagnostic_report.md) 第12节的判断——真正的阻塞点大概率在物理旋钮/硬件使能层面，不是客户端用什么语言、什么协议调用的问题。

下一步仍然是：现场把物理「自动/手动/维护」旋钮真正转到「自动」档（会导致随车电脑断电），配合官方 APP 或其他不依赖这台电脑的方式测试底盘是否响应；或者带着"SDK + ROS 两种方式结果一致"这个证据去问 Woosh 客服。
