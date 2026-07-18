# Head Camera Control 实时调头工具

这个工具用于在浏览器里实时查看头部/腕部摄像头画面，并通过网页按钮微调头部上下左右角度。

它只控制头部摄像头云台，不控制机械臂，也不控制升降。

默认运行在 `shared` 模式：网页只读取其他机器人程序发布出来的最新 JPEG 帧，不直接打开 `/dev/video*` 或 RealSense pipeline，因此可以和夹水瓶 demo 同时运行。

## 文件

- `test/head_camera_control.py`：网页服务和实时画面刷新，默认不占用相机设备
- `test/run_head_camera_control.sh`：启动脚本，默认使用 `head` 头部相机

## 运行位置

服务端程序要在机器人上运行。电脑端只需要打开浏览器访问网页。

```bash
ssh rm@192.168.3.68
cd ~/Grabber/test
./run_head_camera_control.sh
```

如果还没有把 Grabber 拉到机器人上，也可以先在当前测试目录运行：

```bash
cd ~/test
./run_head_camera_control.sh
```

启动后，在电脑浏览器打开：

```text
http://192.168.3.68:8765
```

## 手动启动

不用启动脚本也可以直接运行：

```bash
python3 head_camera_control.py --camera head --host 0.0.0.0 --port 8765
```

参数说明：

- `--camera head`：默认勾选头部摄像头。网页里也可以同时勾选右腕/左腕
- `--frame-source shared`：默认值，只读共享帧，不直接占用相机
- `--host 0.0.0.0`：允许局域网电脑访问
- `--port 8765`：网页端口。不要用 `87` 这种小于 1024 的端口，否则普通用户会报 `Permission denied`

手动启动头部相机：

```bash
python3 head_camera_control.py --camera head --host 0.0.0.0 --port 8765
```

如果只是独立测试网页、没有其他程序发布共享帧，可以显式开启直连相机模式。注意这个模式会直接打开相机设备，可能和夹水瓶 demo 冲突：

```bash
FRAME_SOURCE=direct ./run_head_camera_control.sh head
```

## 使用

网页打开后会显示：

- 实时画面，左上角有 `frame`、时间和当前 camera source，用来确认画面是否真的在刷新
- `↑ / ↓ / ← / →`：调整头部角度
- `●`：回中
- `Read Angles`：刷新角度读数
- `View`：可以同时勾选 `头部相机`、`右腕相机`、`左腕相机`

打开网页本身不会移动头部，只有点击方向按钮或回中按钮才会发控制指令。

## 控制方式

这个网页程序不直接打开 `/dev/rmUSB3` 串口。它通过 UDP 发送和遥控按钮一致的控制帧，由机器人上已经运行的 `head_servo_ctrl.py` 接收并控制舵机。

默认 `shared` 模式也不直接打开任何相机。相机数据来自：

```text
/tmp/grabber_camera_frames/head.jpg
/tmp/grabber_camera_frames/right_wrist.jpg
/tmp/grabber_camera_frames/left_wrist.jpg
```

这些文件由 `sensors.CameraThread` 在夹水瓶 demo 或其他视觉程序采图时自动更新。

所以：

- 画面能显示，但按钮没反应：优先检查 `head_servo_ctrl.py` 是否在运行
- 角度读数一直是 `-`：说明没有收到 `head_servo_ctrl.py` 的角度广播
- 串口被占用不会由这个网页程序造成，因为网页程序不占串口
- 夹水瓶程序运行时，网页不会额外抢相机；如果画面显示 `waiting`，说明当前还没有程序发布对应相机的共享帧

## 相机列表

网页里只保留三路相机：

| 名称 | 默认设备 |
| --- | --- |
| 头部相机 | `head`，共享帧 `head.jpg` |
| 右腕相机 | `right_wrist`，共享帧 `right_wrist.jpg` |
| 左腕相机 | `left_wrist`，共享帧 `left_wrist.jpg` |

只有在 `FRAME_SOURCE=direct` 直连模式下，才会用到底层设备号。设备顺序变化时可以启动前用环境变量覆盖：

```bash
HEAD_CAMERA=/dev/video4 RIGHT_WRIST_CAMERA=/dev/video20 LEFT_WRIST_CAMERA=/dev/video14 FRAME_SOURCE=direct ./run_head_camera_control.sh
```

## 常见问题

### `PermissionError: [Errno 13] Permission denied`

通常是用了小于 1024 的端口，例如 `--port 87`。改用默认端口：

```bash
python3 head_camera_control.py --camera head --host 0.0.0.0 --port 8765
```

### 打开的不是头部摄像头

头部摄像头默认是：

```text
/dev/video4
```

如果网页显示 `waiting`，先确认正在运行的视觉程序已经接入新版 `CameraThread`，并在发布共享帧：

```bash
ls -lh /tmp/grabber_camera_frames/
```

### 画面看起来没有刷新

看画面左上角的 `frame` 数字和时间。如果它们不变，说明服务端没有读到新帧。

可以重启服务：

```bash
Ctrl+C
./run_head_camera_control.sh
```

### 网页打不开

确认服务是在机器人上启动的，并且终端里打印了类似：

```text
Head camera control: http://0.0.0.0:8765
```

然后在电脑浏览器打开：

```text
http://192.168.3.68:8765
```

### 按钮没有控制效果

检查头部控制服务是否在运行：

```bash
ps -ef | grep head_servo_ctrl.py | grep -v grep
```

如果没有运行，需要先启动机器人原来的头部控制服务，或者重新打开开机自启动那套程序。
