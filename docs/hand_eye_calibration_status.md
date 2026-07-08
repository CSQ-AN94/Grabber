# 多相机 + 双臂手眼标定 — 进度与说明（2026-07-08）

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

从 ChArUco 板换成了普通黑白棋盘格（用户反馈"ChArUco质感不如棋盘格"）：
- **7×10格（短边7、长边10），内角点 6×9，方格边长实测 24mm**
- 检测代码在 `HandEyeCalibrator._find_chessboard()`，优先用 `cv2.findChessboardCornersSB`（比经典 `findChessboardCorners` 鲁棒很多，实拍图片经典算法检测失败、SB算法能成功）

## 当前状态：卡在第1轮，标定数值不可信

**第1轮（右臂+头部相机）13组姿态全部成功检测到棋盘格，但自洽性验证不通过。**

自洽性验证原理（`HandEyeCalibrator._print_consistency_check()`）：标定板刚性固定在末端上，理论上每组姿态反推出的"标定板相对末端位姿"应该是同一个常数。实测反推出的13组结果彼此分散：平移最大相差 **322.7mm**，旋转最大相差 **154.85度**——远超可接受范围（好的标定应该平移<1cm、旋转<2度）。

**诊断（较大把握，未100%确认）**：普通棋盘格没有ArUco标记辅助定向，OpenCV在角度差异很大的两张图之间可能把角点顺序识别反（比如180°转向搞反），单张图检测和PnP解算都不会报错，但汇总起来做手眼标定就全乱套。这是ChArUco（带ArUco标记，每个角点有唯一身份）能避免、纯棋盘格容易踩的已知坑。

支持这个诊断的证据：两组几乎完全相同姿态（关节角只差0.01度）算出来的棋盘格位姿高度一致（说明单帧检测和PnP本身没问题），问题应该出在角度差异大的姿态两两之间。

**待用户决定的下一步（两个方向）**：
1. 换回 ChArUco 标定板（如果还在），复用已经验证过的 `HandEyeCalibrator.__init__(board_type="charuco", ...)` 路径，不会有这个歧义问题
2. 给棋盘格检测加一层"角点顺序纠偏"逻辑（跟已有数据比对，自动尝试180°/90°重新排列角点顺序，挑一个跟其他姿态一致的），工作量更大且不保证100%可靠

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
- `scripts/run_eye_in_hand_calibration_right.py` / `_left.py` — 第3/4轮驱动脚本（还没开始）
- `scripts/compose_dual_arm_transform.py` — 组合第1/2轮结果得到左右臂坐标系变换（还没到这一步）
- `config.yaml` — 新增 `calibration.T_base_right_to_camera_head`（第1轮结果，标定通过自洽性验证前不要当作可信数据使用）
