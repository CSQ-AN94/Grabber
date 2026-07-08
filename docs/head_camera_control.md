# Head Camera Control 实时调头工具

这个工具用于在浏览器里实时查看头部摄像头画面，并通过网页按钮微调头部上下左右角度。

它只控制头部摄像头云台，不控制机械臂，也不控制升降。

## 文件

- `test/head_camera_control.py`：网页服务和实时画面刷新
- `test/run_head_camera_control.sh`：启动脚本，默认使用头部摄像头 `/dev/video4`

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
python3 head_camera_control.py --camera /dev/video4 --host 0.0.0.0 --port 8765
```

参数说明：

- `--camera /dev/video4`：头部摄像头。已确认头部是 `/dev/video4`
- `--host 0.0.0.0`：允许局域网电脑访问
- `--port 8765`：网页端口。不要用 `87` 这种小于 1024 的端口，否则普通用户会报 `Permission denied`

启动脚本也支持临时换摄像头：

```bash
./run_head_camera_control.sh /dev/video5
```

## 使用

网页打开后会显示：

- 实时画面，左上角有 `frame`、时间和当前 camera source，用来确认画面是否真的在刷新
- `↑ / ↓ / ← / →`：调整头部角度
- `●`：回中
- `Read Angles`：刷新角度读数
- `Switch`：切换 `/dev/video*` 摄像头

打开网页本身不会移动头部，只有点击方向按钮或回中按钮才会发控制指令。

## 控制方式

这个网页程序不直接打开 `/dev/rmUSB3` 串口。它通过 UDP 发送和遥控按钮一致的控制帧，由机器人上已经运行的 `head_servo_ctrl.py` 接收并控制舵机。

所以：

- 画面能显示，但按钮没反应：优先检查 `head_servo_ctrl.py` 是否在运行
- 角度读数一直是 `-`：说明没有收到 `head_servo_ctrl.py` 的角度广播
- 串口被占用不会由这个网页程序造成，因为网页程序不占串口

## 常见问题

### `PermissionError: [Errno 13] Permission denied`

通常是用了小于 1024 的端口，例如 `--port 87`。改用默认端口：

```bash
python3 head_camera_control.py --camera /dev/video4 --host 0.0.0.0 --port 8765
```

### 打开的不是头部摄像头

头部摄像头默认是：

```text
/dev/video4
```

如果重启后设备顺序变化，可以在网页右侧 `Switch` 下拉框切换，或者启动时指定：

```bash
./run_head_camera_control.sh /dev/video4
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
