# 多相机 + 双臂手眼标定 — 进度与说明（更新于 2026-07-15）

## 目标

把机器人上3个相机（头部 `base_0` + 左右腕部 `left_wrist_0`/`right_wrist_0`）和左右两条手臂的坐标系全部打通，让任意相机检测到的目标都能换算成任意一条手臂可以直接用来抓取的坐标。

用于"从架子上用视觉抓一瓶水"这个demo的手眼标定工作，`docs/demo_operation_guide.md` 是主抓取流程的说明，本文档只覆盖标定这部分。

## 硬件事实（已确认，勿重新猜测）

- 3个相机型号完全一样（Intel RealSense D435），角色不同：
  - `153122071777` = 头部相机 `base_0`（`config.yaml` 的 `camera.head_serial`），俯视工作台，广角，现有 `scan_shelf` 检测流程用这个
  - `405622073249` = 右腕相机 `right_wrist_0`（实测确认：转动右臂j7关节，这个相机画面明显变化）
  - `335522072194` = 左腕相机 `left_wrist_0`（排除法确认）
- 右臂 IP `169.254.128.19`，左臂 IP `169.254.128.18`，端口都是 `8080`
- 头部有俯仰(`angle1`)/偏航(`angle2`)两个舵机，走独立UDP通道（`head_servo_ctrl.py`），跟手臂SDK是两套完全独立的系统
- 头部相机是固定平台（不像手臂末端会动），头部舵机角度必须在整个"头部相机"相关的标定轮次之间保持不变

## 整体方案：4轮标定 + 1次组合

| 轮次 | 方法 | 标定板怎么放 | 移动哪条臂 | 解出什么 | 驱动脚本 |
|---|---|---|---|---|---|
| 1 | eye-to-hand | 绑**右臂**夹爪上（相机不动，板子跟手臂动） | 右臂 | 头部相机 相对 右臂基座 | `scripts/run_eye_to_hand_calibration.py` |
| 2 | eye-to-hand | 绑**左臂**夹爪上（头部角度必须跟第1轮完全一致） | 左臂 | 头部相机 相对 左臂基座 | `scripts/run_eye_to_hand_calibration_left.py` |
| 3 | eye-in-hand | 固定在桌面/支架上不动（相机跟手臂动，板子不动） | 右臂 | 右腕相机 相对 右臂末端 | `scripts/run_eye_in_hand_calibration_right.py` |
| 4 | eye-in-hand | 同一摆位，不用重新放 | 左臂 | 左腕相机 相对 左臂末端 | `scripts/run_eye_in_hand_calibration_left.py` |

第1、2轮的结果用 `scripts/compose_dual_arm_transform.py` 组合，反解出左右臂基座坐标系的相对变换 `T_base_right_to_base_left`，从而把两条手臂串到同一个坐标系里。第3、4轮各自独立，只跟各自那条手臂相关，不需要跟另一条臂组合。

数学原理见 `utils/handeye_calibrator.py` 里 `run_calibration_process()`（eye-in-hand）和 `run_eye_to_hand_calibration()`（eye-to-hand）的docstring和内联注释——已经用合成数据（已知真值反推模拟测量值）在机器人实际环境验证过公式正确性，用的是 `cv2.CALIB_HAND_EYE_PARK`（不是TSAI，实测TSAI在理想合成数据下都有系统性误差，PARK能精确恢复到机器精度）。

## 标定板

- eye-to-hand 使用普通黑白棋盘格：**7×10格、6×9内角点、24mm方格**。
- eye-in-hand 使用固定在桌面的 ChArUco：**12×9格、30mm方格、22.5mm marker、DICT_5X5_250**。
- 两类标定互相独立，可以使用不同标定板。

## 当前统一结果（2026-07-15）

四轮标定均已完成，全部矩阵写入 `config.yaml.calibration`，统一约定
`p_A = T_A_to_B @ p_B`。运行时可通过 `CalibrationConfig.camera_to_arm_base()`
把头部、左腕或右腕相机坐标组合到任意一条手臂基座。

| 外参 | 质量 |
|---|---|
| 头部 → 右臂基座 | 良好：9.3mm / 1.09deg max |
| 头部 → 左臂基座 | 中等：12.8mm / 1.09deg max |
| 右腕 → 右末端 | 中等：22.8mm / 2.84deg max |
| 左腕 → 左末端 | 中等：19.6mm / 3.44deg max |

由两套头部外参组合得到的左右基座安装间距约 `0.1211m`；正反矩阵闭环数值误差
小于 `1e-12`。腕部两套结果应先用于低速粗定位验证，尚不建议直接用于精细抓取。

## 历史记录

> 2026-07-10 更新：进一步检查发现 `ArmController.get_base_to_end_pose_matrix()`
> 曾错误地把 `[rx, ry, rz]` 传给 SciPy 的 `ZYX` 轴序列。真机用 Realman SDK
> `rm_algo_pos2matrix()` 对照后确认应使用 `xyz`；旧写法与 SDK 矩阵的最大元素误差
> 接近 1。第1轮当时保存结果的旋转部分 `det(R)≈-1`，不是合法刚体旋转，必须丢弃。
> **这才是最初那次"自洽性验证不通过"（平移最大322.7mm/旋转最大154.85度）的
> 首要根因**——下面之前记录的"棋盘格角点顺序歧义"诊断经核实是次要因素，
> 并非主因，特此更正。

> 2026-07-14 更新：Euler角度bug修复后，第1轮（右臂+头部相机）用同一块棋盘格
> 重新标定，**13/13姿态成功检测，自洽性验证通过**（平移两两差异 max=9.3mm /
> mean=4.7mm，旋转两两差异 max=1.09deg / mean=0.47deg，达到"良好"标准）。
> 结果已写入 `config.yaml` 的 `calibration.T_base_right_to_camera_head`。
> 原始数据（每帧图片 + 位姿 + 重投影误差）存档在机器人
> `~/Grabber/outputs/eye_to_hand_right_calibration/`。
>
> 过程中棋盘格从右臂夹爪上物理脱落了两次（胶带固定不够牢靠，一次"打到墙上"），
> 每次重装后跟原有姿态列表对应的视角就对不上（同一批姿态重装后一度只有2/13能
> 检测到板子）——**这提醒了一件更值得注意的事：标定板物理位置漂移是比棋盘格
> 方向歧义更常见、更直接的错误来源，标定前务必做"晃动测试"确认板子和末端之间
> 没有任何相对位移**，且需要用双面胶+扎带等更牢固的方式二次固定，不能只靠胶带。

**标定板依然是普通棋盘格（7×10格/6×9内角点/24mm方格），没有换成ChArUco**——
Euler角度bug修复后棋盘格本身工作正常，暂时没有再触发方向歧义问题，
但这不代表方向歧义完全不存在，大角度姿态之间仍建议谨慎，`_print_transform_consistency`
自洽性检查是防线，标定后必须确认输出的是"良好"而不是被直接拒绝。

**下一步**：
1. 第2轮（左臂+头部相机）：棋盘格挪到左臂夹爪（务必扎带二次固定），
   头部角度不能再动，用 `scripts/collect_calibration_poses.py 169.254.128.18`
   采集新姿态，跑 `scripts/run_eye_to_hand_calibration_left.py`
2. 第3/4轮（左右腕部+ChArUco，固定在桌面）：脚本已经支持严格相机序列号校验、
   重投影误差过滤、SE(3)合法性检查、自洽性验证、原始数据落盘，
   仍需现场用 `collect_calibration_poses.py --camera-serial ... --board-type charuco`
   采集左右腕安全姿态
3. 全部4轮完成后跑 `scripts/compose_dual_arm_transform.py` 组合出左右臂坐标系变换

## 本次会话过程中发现并修复的额外问题（供参考）

1. **`arm_controller.py` 曾用已验证危险的 SIGSTOP 遥操共存架构**——已改成一次性 `pkill` 全部遥操进程 + SDK全程控制 + `close()`时官方脚本重启，真机验证通过
2. **重启遥操时忘杀 `head_servo_ctrl.py` 会导致新旧进程抢占同一串口**——已在 `arm_controller.py` 里补上
3. **机器人上 cv2==4.5.4 是旧版aruco API**，新版写法（`DetectorParameters()`/`GridBoard()`无参构造）会直接崩溃，已改成 `*_create` 系列旧式调用
4. **eye-to-hand标定公式曾多算一次矩阵求逆**——用合成数据反复验证后发现并修正
5. **`ArmController.__init__` 过程中 `head_servo_ctrl.py` 有时会意外消失**（具体机制未100%查清，孤立测试证明"只杀atom不会带死head_servo"，但完整初始化流程会），不追查根因，直接在标定脚本里加 `ensure_head_fixed()`：构造完 `ArmController` 后自动检查+必要时手动拉起 `head_servo_ctrl.py`，再强制把头部角度调回基准值，标定采集姿态前保证头部一定归位
6. **`pkill -f <substring>` 自我误杀陷阱**：一整段shell/python命令字符串里如果同时包含"用-f去杀某进程"和"该进程名字符串本身"，会把执行这条命令的父进程自己也杀掉，表现为"SSH连接莫名中断"。规避：把pkill命令写成独立脚本文件再调用，不要在同一条内联命令里既提到目标进程名又用`-f`杀它

## 相关文件清单

- `controllers/arm_controller.py` — 机械臂SDK控制器，遥操停止/恢复架构
- `utils/calibration.py` — 像素坐标→基座3D点转换（`get_point_base`=eye-in-hand用，`get_point_base_fixed_camera`=eye-to-hand用）
- `utils/handeye_calibrator.py` — 手眼标定核心算法类 `HandEyeCalibrator`
- `scripts/head_position_lock.py` — 头部角度锁定/校验/恢复（`check`/`restore`）
- `scripts/capture_calibration_pose.py` — 单次读关节角+拍照确认（只读，不碰遥操）
- `scripts/collect_calibration_poses.py` — 交互式批量采集标定姿态（现场操作，命令行内自助完成，不用来回问答），需要配合 `head_camera_control.py`（`/home/rm/test/`目录，机器人自带的网页取景工具，提供 `/snapshot.jpg` 接口）实时看画面
- `scripts/run_eye_to_hand_calibration.py` / `_left.py` — 第1/2轮驱动脚本
- `scripts/run_eye_in_hand_calibration_right.py` / `_left.py` — 第3/4轮驱动脚本（均已完成）
- `scripts/compose_dual_arm_transform.py` — 从统一配置复算并检查左右臂基座变换闭环
- `config.yaml` — 四套基础外参和两套左右基座互变矩阵的唯一配置来源
- `test/test_handeye_math.py` — 单元测试：合成数据验证 `_solve_handeye`/`_is_valid_rigid_transform`，以及ChArUco检测+重投影过滤的基本行为
