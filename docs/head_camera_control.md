# Head Camera Control 实时调头工具

这个工具用于在浏览器里实时查看头部/腕部摄像头画面，通过网页按钮微调头部上下左右角度，并按固定毫米步长控制机器人身体升降。

它不控制机械臂。身体升降通过独立升降控制器完成。

默认运行在 `shared` 模式：网页只读取其他机器人程序发布出来的最新 JPEG 帧，不直接打开 `/dev/video*` 或 RealSense pipeline，因此可以和夹水瓶 demo 同时运行。

注意：`shared` 模式本身不采图。只有夹水瓶 demo 或其他使用 `sensors.CameraThread` 的程序正在运行并发布共享帧时，网页画面才会实时刷新。如果共享帧超过 3 秒没有更新，网页会显示 `stale` 或等待提示图，而不是继续显示旧照片。

默认运行在 `shared` 模式：网页只读取其他机器人程序发布出来的最新 JPEG 帧，不直接打开 `/dev/video*` 或 RealSense pipeline，因此可以和夹水瓶 demo 同时运行。

注意：`shared` 模式本身不采图。只有夹水瓶 demo 或其他使用 `sensors.CameraThread` 的程序正在运行并发布共享帧时，网页画面才会实时刷新。如果共享帧超过 3 秒没有更新，网页会显示 `stale` 或等待提示图，而不是继续显示旧照片。

## 文件

- `test/head_camera_control.py`：网页服务和实时画面刷新，默认不占用相机设备
- `test/run_head_camera_control.sh`：启动脚本，默认使用 `head` 头部相机
- `test/run_head_camera_shared.sh`：强制 shared 模式启动
- `test/run_head_camera_direct.sh`：强制 direct 模式启动

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

## 两种启动模式

shared 模式不打开相机，只读 `/tmp/grabber_camera_frames`，适合和夹水瓶 demo 一起跑：

```bash
cd ~/Grabber/test
./run_head_camera_shared.sh
```

direct 模式会直接打开相机设备，适合单独调摆放、调头部角度。默认只开头部：

```bash
cd ~/Grabber/test
./run_head_camera_direct.sh head
```

也可以一次打开三路：

```bash
./run_head_camera_direct.sh all
```

等价写法：

```bash
FRAME_SOURCE=shared ./run_head_camera_control.sh head
FRAME_SOURCE=direct ./run_head_camera_control.sh head
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
./run_head_camera_direct.sh head
```

## 使用

网页打开后会显示：

- 实时画面，左上角有 `frame`、时间和当前 camera source，用来确认画面是否真的在刷新
- `↑ / ↓ / ← / →`：调整头部角度
- `●`：回中
- `Read Angles`：刷新角度读数
- `Mode`：在网页端切换 `Shared` / `Direct`
- `View`：可以同时勾选 `头部相机`、`右腕相机`、`左腕相机`
- `身体上升 / 身体下降`：先读取当前高度，再按网页中设置的步长移动，默认每次 50 mm
- `读取身体高度`：查询升降控制器并显示当前毫米高度

打开网页本身不会移动头部，只有点击方向按钮或回中按钮才会发控制指令。

打开网页时只会读取一次身体高度，不会自动移动。身体升降命令使用 `169.254.128.18:8080` 的 `get_lift_state` / `set_lift_height` 接口，速度固定为 30，服务端将目标高度强制限制在 `0–2600 mm`，单次步长最大 `200 mm`。同一时间只会执行一条升降命令，避免重复点击产生并发动作；控制器未使能或报告故障时也会拒绝移动。移动 API 只接受网页发出的带专用请求头的 `POST`，普通 `GET` 链接不会触发身体动作。操作前必须确认机器人上下方、双臂和线缆没有碰撞或拉扯风险。

网页切到 `Shared` 会释放 direct 打开的相机；网页切到 `Direct` 会打开 `View` 里勾选的相机。Direct 模式可以同时直连头部、右腕、左腕三路，但会占用这些相机设备，也更吃 USB 带宽。

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
| 右腕相机 | `right_wrist`，direct 默认 `/dev/video14`，共享帧 `right_wrist.jpg` |
| 左腕相机 | `left_wrist`，direct 默认 `/dev/video20`，共享帧 `left_wrist.jpg` |

只有在 `direct` 直连模式下，才会用到底层设备号。设备顺序变化时可以启动前用环境变量覆盖：

```bash
HEAD_CAMERA=/dev/video4 RIGHT_WRIST_CAMERA=/dev/video14 LEFT_WRIST_CAMERA=/dev/video20 FRAME_SOURCE=direct ./run_head_camera_control.sh
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

先看右侧 `Age` 或每个画面标题栏：

- `0.xs` / `1.xs`：共享帧正在更新，是实时画面
- `stale 10s` 之类：网页服务在跑，但共享帧已经过期；通常是夹水瓶 demo / `CameraThread` 没有运行，或对应相机没有被打开
- `waiting`：还没有对应相机的共享帧文件

默认 `shared` 模式不直接打开相机，所以单独启动网页服务时，如果没有其他程序发布共享帧，它不会凭空产生实时画面。

可以重启服务：

```bash
Ctrl+C
./run_head_camera_control.sh
```

如果只是单独测试摄像头画面、确认没有夹水瓶 demo 或其他视觉程序在用相机，可以临时使用直连模式：

```bash
./run_head_camera_direct.sh head
```

如果要三路一起看：

```bash
./run_head_camera_direct.sh all
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
