# AGV 底盘调试小工具（本地留档 + 详细操作步骤）

> 这份文档是远端机器人（`192.168.3.68:/home/rm/agv_debug_tools/README.md`）的本地镜像，方便本地查看和以后照着操作。工具本身（`.cpp`/编译好的可执行文件/`.sh` 脚本）只在机器人上，这个仓库里没有。

一次性调试用，不是项目正式代码。全部通过 Woosh SDK / ROS2（本质是同一套协议）操作底盘 `robot_id 10001`（底盘自己的网络地址 `169.254.128.2:5410`）。

## 0. 怎么连上去、东西在哪

```bash
ssh rm@192.168.3.68        # 密码 rm
cd ~/agv_debug_tools        # 所有工具都在这个目录下
ls
```

会看到一堆 `.cpp` 源码、同名的已编译可执行文件（没有后缀名的那些）、一个 `.sh` 脚本。**直接跑可执行文件就行，不需要重新编译。**

如果哪天需要改参数重新编译（比如改转动角度），编译命令是：

```bash
g++ -std=c++17 -O2 <name>.cpp \
  -I ~/rmc_aida_l_atom/include \
  -L ~/rmc_aida_l_atom/lib/linux \
  ~/rmc_aida_l_atom/lib/linux/libwoosh_robot.so.1.1 \
  ~/rmc_aida_l_atom/lib/linux/libprotobuf.so.32 \
  -lpthread -Wl,-rpath,~/rmc_aida_l_atom/lib/linux \
  -o <name>
```

---

## 文件速查表（全部 .cpp / 脚本一览）

| 文件 | 类型 | 一句话说明 | 会不会动 |
|---|---|---|---|
| `agv_diag.cpp` | 只读 | 打印状态/模式/硬件自检/告警/位姿全部信息，排查问题第一步 | 不会 |
| `agv_pose_query.cpp` | 只读 | 只查一次位姿+速度，比 `agv_diag` 更快更简单 | 不会 |
| `agv_mode_init.cpp` | 模式切换 | 切到自动模式(`kAuto`)+初始化(`kUninit→kIdle`)，是后面运动测试的前提步骤 | 不会 |
| `agv_set_deploy.cpp` | 模式切换 | 把工作模式切到"维护模式"(`kDeployMode`) | 不会 |
| `agv_restore_mode.cpp` | 模式切换 | 把控制模式改回最初的 `kManual + kTaskMode`，测试完收尾还原用 | 不会 |
| `agv_release_control_test.cpp` | 模式切换+运动测试 | 在 `kAuto+kIdle` 状态下重新调用 `release-control`，验证一个假设(结论：假设不成立)，之后顺带做 30° 转动测试 | **会**(转动部分) |
| `agv_manual_turn.cpp` | 运动测试 | 手动模式下原地转动测试，正转→停3秒→反转→停，参数 30°/0.12rad/s(源码和编译好的二进制已经统一，不再有 v2 版本) | **会** |
| `agv_auto_turn.cpp` | 运动测试 | 在已初始化的自动模式下做转动测试，跟 `agv_manual_turn` 类似，只是过程中不会中途切回手动模式 | **会** |
| `agv_step_rotate.cpp` | 运动测试 | 用另一种控制接口(`StepControl` 离散步进动作，而非连续速度指令)测试转动 | **会** |
| `agv_forward_test.cpp` | 运动测试 | 前进 5cm→停3秒→倒退 5cm→停，打印前后坐标，是目前最干净的"零响应"反证 | **会** |
| `ros_chassis_turn_test.sh` | 运动测试(ROS2版) | 用官方 ROS2 接口走一遍"切自动+初始化+转动+停止+查位姿"，用来验证不是 C++ 代码写错 | **会** |

"会不会动"指的是**理论上会真实发送运动指令**，不代表底盘实际会物理移动——目前的结论是这些"会动"的测试指令全部返回成功，但底盘没有真实物理响应(详见第7节)。凡是标"会"的，执行前必须确认周围安全。

---

## 1. `agv_diag` —— 排查问题第一步，只读，随时能跑，不会动

**是什么**：一次性把底盘所有能查到的状态打印出来，不发任何运动指令，安全。

**什么时候用**：任何时候想看看底盘现在是什么情况（电量、有没有报警、控制模式、位置），都先跑这个。

**怎么跑**：
```bash
cd ~/agv_debug_tools
./agv_diag
```

**输出里要看哪几行**：
- `[RobotState] ... state: kUninit` —— 底盘是否已初始化。`kUninit`=未初始化，`kIdle`=已初始化待命，`kFault`=故障。
- `[Mode] ... ctrl: kManual  work: kTaskMode` —— 当前控制模式（`kManual`手动/`kAuto`自动/`kMaintain`维护）和工作模式。
- `[HardwareState] ...` —— 一长串 `motor/lidar/camera/sonar/lift/roller: kNormal`，只要都是 `kNormal` 就说明硬件自检没问题。
- `[AbnormalCodes] ...` —— 当前**未恢复**的告警列表，空的就是没有告警。
- `[PoseSpeed] ... pose { x y theta } twist { linear angular }` —— 当前位置和速度，`twist` 是空的/都是0说明底盘静止。

---

## 2. `agv_mode_init` —— 把底盘从"未初始化"切到"待命"状态

**是什么**：底盘刚连上或者重连之后经常是 `kUninit`（未初始化）状态，这个程序负责把它切到 `kAuto`（自动模式）并初始化成 `kIdle`（待命），这是后面能发运动指令的**前提步骤**。这一步本身不会让底盘动。

**什么时候用**：想测试转动/平移之前，先跑这个把底盘准备好。

**怎么跑**：
```bash
cd ~/agv_debug_tools
./agv_mode_init
```

**它内部做了什么（会在终端一条条打印出来）**：
1. 查询当前模式/状态（这时通常是 `kManual` + `kUninit`）
2. 尝试取消任务/释放控制权（这一步在没切自动模式前必然失败，是正常现象，不用管）
3. 调用 `switchControlModeReq` 切换到 `kAuto`（自动模式）—— 看到 `switch-ctrl-auto ok=true` 说明切换成功
4. 调用初始化 —— 看到 `init-record-true ok=true` 说明初始化成功
5. 再查一次状态确认，最后发一个停止指令收尾

**跑完之后确认**：输出最后应该有 `state-after-init ... state: kIdle`，看到 `kIdle` 就说明这一步做对了，可以接着跑下面的运动测试了。

---

## 3. `agv_manual_turn` —— 转动测试（30°，正转再转回来）

**⚠️ 这个会真实发送运动指令，执行前必须确认：周围没人、没有障碍物/线缆，急停在手边。**

**是什么**：让底盘原地正转约 30°，停住 3 秒钟给你看，再反向转回来，最后停止，并且会打印转动前后的坐标位置方便对比。

**前提**：先跑过 `agv_mode_init` 把底盘切到 `kAuto`+`kIdle`（这个程序本身也会自己切一次 `kManual`，但底盘要提前初始化过才有效）。

**怎么跑**：
```bash
cd ~/agv_debug_tools
./agv_manual_turn
```

**跑完看什么**：
- 终端里一长串 `turn-left ok=true` / `turn-right ok=true`，这只是说明指令被底盘"接收"了，不代表真的转动了。
- 关键看 `pose-before-turn`（转动前坐标）和 `pose-after-return`（转回来之后的坐标）里的 `theta`（朝向角度，单位弧度）。
  - 如果底盘真的转了一圈又转回来，`theta` 前后应该几乎一样（正反抵消）。
  - **同时你的眼睛要盯着底盘看它有没有真的转** —— 目前我们测试下来，指令全部显示成功，但底盘肉眼观察没有任何转动，`theta` 变化也只在噪声级别（0.01 rad 左右），这就是我们卡住的地方。

**如果想改角度/速度**，改 `agv_manual_turn.cpp` 开头的 `kAngularSpeedRadPerSec`、`kTurnAngleRad` 两个常量，重新编译（编译命令见文件开头第0节）。

---

## 4. `agv_forward_test` —— 前进后退测试（5cm，目前最干净的反证）

**⚠️ 这个是前后平移，会真实改变底盘位置，风险比原地转动更高（周围有其他设备/机械臂要特别小心），执行前必须确认正前方半米内没有人/障碍物。**

**是什么**：底盘前进 5cm（很慢，0.02 m/s，走2.5秒左右），停3秒，再倒退回来，最后停止，打印前后坐标。

**怎么跑**：
```bash
cd ~/agv_debug_tools
./agv_forward_test
```

**跑完看什么**：
- 输出里 `pose-after-forward` 和 `pose-after-return` 的 `x` `y` 坐标。
- 我们实测的结果是：前进后退整个过程 `x`/`y` 坐标**完全没有变化，分毫不差**——说明指令虽然返回成功，但驱动轮完全没有物理输出。这是目前证明"底盘收到指令但不动"最干净的一次测试。

---

## 5. `ros_chassis_turn_test.sh` —— ROS2 版本的转动测试（一条命令走完整流程）

**⚠️ 同样会真实发送运动指令，执行前确认安全。**

**是什么**：跟上面的 C++ 程序做的事情一样（切自动模式→初始化→转动→停止→查位姿），只不过是用官方 ROS2 接口（`woosh_robot_agent`）走的，用来验证"是不是我们自己写的 C++ 代码有问题"（结论：不是，ROS 和 C++ SDK 结果一模一样）。

**前提**：机器人上要先装好 ROS2 Humble 版的官方代理程序 `ros-humble-woosh-robot-agent`（已经装过了，装在 `/opt/ros/humble/lib/woosh_robot_agent/agent`，一般不需要重装）。

**怎么跑**：
```bash
cd ~/agv_debug_tools
./ros_chassis_turn_test.sh              # 用默认参数：角速度0.12 rad/s，转15秒
./ros_chassis_turn_test.sh 0.2 10        # 自定义：角速度0.2 rad/s，转10秒
```

**它自动做的事情**（脚本会打印每一步的 `[info]` 提示）：
1. 检查 ROS2 的 `agent` 进程有没有在跑，没有的话自动用 `nohup` 启动
2. 调用 ROS2 服务把控制模式切到自动（`SwitchControlMode`）
3. 调用 `InitRobot` 初始化
4. 打印转动前的位姿（`ros2 topic echo /robot/PoseSpeed --once`）
5. 循环发送转动指令，持续你指定的秒数
6. 发停止指令
7. 打印转动后的位姿

**跑完看什么**：和上面 C++ 版本一样，对比转动前后 `theta` 的变化。我们实测下来跟 C++ 版本一样是"噪声级别的微小变化，肉眼看不到底盘转动"。

---

## 6. 其他工具（用得少，了解一下就行，详细说明见上面"文件速查表"）

- `agv_pose_query` —— 只查一次位姿速度，比 `agv_diag` 更快更简单，只读安全。
- `agv_set_deploy` —— 把工作模式切到"维护模式"，只是切模式，不产生运动。
- `agv_restore_mode` —— 把控制模式改回最初的 `kManual + kTaskMode`，用来测试完收尾还原现场。
- `agv_auto_turn` —— 在已经初始化好的自动模式下做转动测试，跟 `agv_manual_turn` 类似，只是不会中途切回手动模式。
- `agv_step_rotate` —— 用另一种控制接口（`StepControl` 离散步进动作，而不是连续速度指令）测试转动，结果同样是零响应。
- `agv_release_control_test` —— 验证过的一个假设用的测试程序（结论是这个假设不成立，已经排除，具体见下面"已验证结论"）。

**已清理**（2026-07-06）：早期的 `agv_turn_test`/`agv_turn_hold_test`（功能已被 `agv_manual_turn` 完全覆盖）、临时日志 `agent.log`、已经装完的 ROS2 安装包 `ros-humble-woosh-robot-agent_0.0.6-0jammy_arm64.run`（系统里已经 `dpkg` 装好，删掉安装包不影响已装的程序，只是以后要重装得重新从客服资料包传一份）都已从远端删除。

---

## 7. 已验证结论（截至 2026-07-06）

**核心结论：底盘收到运动指令后 SDK 层全部返回"成功"，但驱动轮没有任何物理响应。** 已经系统性排除的可能性：

- 不是控制模式问题：手动/自动/维护三种模式都测过。
- 不是接口选择问题：连续速度指令（`twistReq`）和离散步进动作（`StepControl`）都测过。
- 不是转动/平移的区别：原地转动和直线平移都测过（平移是最干净的反证，坐标分毫不变）。
- 不是漏了某个初始化步骤：`kAuto`+`kIdle` 状态下重新调用 `release-control` 也测过，结果证伪（后来查官方文档确认这个调用本来就要求"任务中"状态，跟驱动解锁无关）。
- 不是我们自己代码写错：换成官方 ROS2 接口重新测了一遍，结果完全一样。

**目前最可能的方向**：查过官方 SDK 文档发现，切换控制模式的 API 明确写着"仅调试可用，正常作业请使用车体物理旋钮"——而我们测试期间物理旋钮几乎全程停在"手动"档。怀疑真正的驱动使能是由物理旋钮位置决定的，软件层的模式切换只是覆盖了"上报状态"，没有打开硬件层面的驱动权限。

详细的排查过程、时间线和给客服的问题简报，见仓库内 [chassis_diagnostic_report.md](chassis_diagnostic_report.md)；ROS2 部分的安装和原理见 [chassis_ros_control.md](chassis_ros_control.md)。
