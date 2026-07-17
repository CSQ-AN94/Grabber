#!/usr/bin/env python3
"""
Web control panel for the head camera and head servos.

Run on the robot, then open http://192.168.3.68:8765 from a browser.

This program does not open /dev/rmUSB3. It controls the head by sending the
same UDP button frames consumed by head_servo_ctrl.py, so that service must be
running for head movement and angle feedback.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import select
import socket
import threading
import time
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import cv2


BROADCAST_IP = "169.254.128.255"
CONTROL_PORT = 19999
ANGLE_PORT = 9996

HEAD_CTRL_IO = 5
UP_IO = 6
DOWN_IO = 7
LEFT_IO = 8
RIGHT_IO = 9

ACTIONS = {
    "u": UP_IO,
    "d": DOWN_IO,
    "l": LEFT_IO,
    "r": RIGHT_IO,
}

CENTER_ANGLE = 500
CENTER_TOLERANCE = 25

CAMERA_SPECS = [
    {
        "id": "head",
        "label": "头部相机",
        "env": "HEAD_CAMERA",
        "aliases": ["/dev/video4"],
        "candidates": [
            "/dev/video4",
            "/dev/v4l/by-path/platform-3610000.usb-usb-0:2:1.3-video-index0",
        ],
    },
    {
        "id": "wrist_a",
        "label": "腕部相机 A",
        "env": "WRIST_CAMERA_A",
        "aliases": ["/dev/video14"],
        "candidates": [
            "/dev/video14",
            "/dev/v4l/by-path/platform-3610000.usb-usb-0:3.2.4.4:1.3-video-index0",
        ],
    },
    {
        "id": "wrist_b",
        "label": "腕部相机 B",
        "env": "WRIST_CAMERA_B",
        "aliases": ["/dev/video20"],
        "candidates": [
            "/dev/video20",
            "/dev/v4l/by-path/platform-3610000.usb-usb-0:3.2.4.3:1.3-video-index0",
        ],
    },
]


def json_bytes(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def _first_existing(candidates: list[str]) -> str:
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return candidates[0]


def list_camera_options() -> list[dict[str, Any]]:
    options = []
    for spec in CAMERA_SPECS:
        env_source = os.environ.get(spec["env"], "").strip()
        candidates = [env_source] if env_source else spec["candidates"]
        source = _first_existing(candidates)
        options.append({
            "id": spec["id"],
            "label": spec["label"],
            "source": source,
            "available": os.path.exists(source),
        })
    return options


def choose_camera_source(camera_arg: str, options: list[dict[str, Any]]) -> str:
    for option, spec in zip(options, CAMERA_SPECS):
        names = {option["id"], option["label"], option["source"], *spec["aliases"]}
        if camera_arg in names:
            return option["source"]

    for option in options:
        if option["available"]:
            return option["source"]

    return options[0]["source"]


def camera_label_for_source(source: str, options: list[dict[str, Any]]) -> str:
    for option in options:
        if option["source"] == source:
            return option["label"]
    return "自定义相机"


class AngleReceiver:
    def __init__(self, port: int = ANGLE_PORT):
        self.port = port
        self.latest: dict[str, Any] | None = None
        self.last_rx_time = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def snapshot(self) -> dict[str, Any] | None:
        with self._lock:
            if self.latest is None:
                return None
            data = dict(self.latest)
            data["age_s"] = round(time.time() - self.last_rx_time, 3)
            return data

    def _run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", self.port))
        sock.setblocking(False)
        while not self._stop.is_set():
            ready, _, _ = select.select([sock], [], [], 0.2)
            if not ready:
                continue
            try:
                data, _ = sock.recvfrom(2048)
                obj = json.loads(data.decode("utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            with self._lock:
                self.latest = obj
                self.last_rx_time = time.time()
        sock.close()


class HeadUdpController:
    def __init__(self, angle_receiver: AngleReceiver):
        self.angle_receiver = angle_receiver

    def make_io_frame(self, *pressed_ios: int) -> bytes:
        frame = bytearray(34)
        frame[0] = 0x01
        frame[1] = 0x04
        frame[2] = 0x20
        for io_num in pressed_ios:
            frame[2 + io_num * 2] = 1
        return bytes(frame)

    def send_action(self, action: str, repeat: int = 6, interval: float = 0.05) -> dict[str, Any]:
        if action not in ACTIONS:
            raise ValueError(f"unknown action: {action}")

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        press = self.make_io_frame(HEAD_CTRL_IO, ACTIONS[action])
        release = self.make_io_frame()
        for _ in range(max(1, repeat)):
            sock.sendto(press, (BROADCAST_IP, CONTROL_PORT))
            time.sleep(max(0.01, interval))
        sock.sendto(release, (BROADCAST_IP, CONTROL_PORT))
        sock.close()
        return {"ok": True, "action": action, "repeat": repeat, "interval": interval}

    def center(self, repeat: int = 6, interval: float = 0.05, max_steps: int = 12,
               target: int = CENTER_ANGLE, tolerance: int = CENTER_TOLERANCE) -> dict[str, Any]:
        steps = []
        for step in range(1, max_steps + 1):
            current = self.angle_receiver.snapshot()
            if not current:
                return {"ok": False, "error": "no angle broadcast", "steps": steps}

            actions = []
            a1 = current.get("angle1")
            a2 = current.get("angle2")
            if isinstance(a1, int):
                if a1 < target - tolerance:
                    actions.append("u")
                elif a1 > target + tolerance:
                    actions.append("d")
            if isinstance(a2, int):
                if a2 < target - tolerance:
                    actions.append("l")
                elif a2 > target + tolerance:
                    actions.append("r")

            steps.append({"step": step, "angle": current, "actions": actions})
            if not actions:
                return {"ok": True, "done": True, "steps": steps}

            for action in actions:
                self.send_action(action, repeat=repeat, interval=interval)
                time.sleep(0.5)

        return {"ok": True, "done": False, "error": "max_steps reached", "steps": steps}


class CameraStream:
    def __init__(self, source: str, width: int, height: int, fps: int, quality: int):
        self.source = source
        self.width = width
        self.height = height
        self.fps = fps
        self.quality = quality
        self.latest_jpeg: bytes | None = None
        self.status = "starting"
        self.frame_count = 0
        self.last_frame_time = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._reopen = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def set_source(self, source: str) -> None:
        with self._lock:
            self.source = source
            self.status = "switching"
            self.latest_jpeg = None
        self._reopen.set()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            age = None if not self.last_frame_time else round(time.time() - self.last_frame_time, 3)
            return {
                "source": self.source,
                "status": self.status,
                "frame_count": self.frame_count,
                "frame_age_s": age,
                "width": self.width,
                "height": self.height,
                "fps": self.fps,
            }

    def get_jpeg(self) -> bytes | None:
        with self._lock:
            return self.latest_jpeg

    def _open_capture(self, source: str) -> cv2.VideoCapture:
        cap = cv2.VideoCapture(source, cv2.CAP_V4L2)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            cap.set(cv2.CAP_PROP_FPS, self.fps)
        return cap

    def _run(self) -> None:
        cap: cv2.VideoCapture | None = None
        current_source = None
        frame_interval = 1.0 / max(1, self.fps)

        while not self._stop.is_set():
            with self._lock:
                desired_source = self.source
            if cap is None or current_source != desired_source or self._reopen.is_set():
                self._reopen.clear()
                if cap is not None:
                    cap.release()
                current_source = desired_source
                cap = self._open_capture(current_source)
                with self._lock:
                    self.status = "open" if cap.isOpened() else f"failed to open {current_source}"

            if cap is None or not cap.isOpened():
                time.sleep(0.5)
                continue

            ok, frame = cap.read()
            if not ok or frame is None:
                with self._lock:
                    self.status = "no frame"
                time.sleep(0.2)
                continue

            with self._lock:
                next_frame_count = self.frame_count + 1
            display = frame.copy()
            stamp = time.strftime("%H:%M:%S")
            overlay = f"frame {next_frame_count}  {stamp}  {current_source}"
            cv2.rectangle(display, (0, 0), (640, 34), (0, 0, 0), -1)
            cv2.putText(display, overlay[:70], (8, 24), cv2.FONT_HERSHEY_SIMPLEX,
                        0.62, (0, 255, 255), 2, cv2.LINE_AA)

            ok, encoded = cv2.imencode(".jpg", display, [int(cv2.IMWRITE_JPEG_QUALITY), self.quality])
            if ok:
                with self._lock:
                    self.latest_jpeg = encoded.tobytes()
                    self.status = "streaming"
                    self.frame_count += 1
                    self.last_frame_time = time.time()
            time.sleep(frame_interval)

        if cap is not None:
            cap.release()


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Head Camera Control</title>
  <style>
    :root { color-scheme: dark; --bg:#101216; --panel:#1b2028; --line:#323946; --text:#edf1f7; --muted:#98a2b3; --accent:#5dd39e; --warn:#f5b85b; --bad:#ff6b6b; }
    * { box-sizing: border-box; }
    body { margin:0; background:var(--bg); color:var(--text); font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    header { height:56px; display:flex; align-items:center; justify-content:space-between; padding:0 18px; border-bottom:1px solid var(--line); background:#151922; }
    h1 { font-size:17px; margin:0; font-weight:650; }
    main { display:grid; grid-template-columns:minmax(320px, 1fr) 340px; min-height:calc(100vh - 56px); }
    .viewer { display:flex; align-items:center; justify-content:center; padding:14px; background:#07090d; }
    .viewer img { max-width:100%; max-height:calc(100vh - 86px); object-fit:contain; border:1px solid var(--line); background:#000; }
    .side { border-left:1px solid var(--line); background:var(--panel); padding:16px; overflow:auto; }
    .row { display:flex; gap:8px; align-items:center; margin-bottom:10px; }
    .label { color:var(--muted); font-size:13px; min-width:72px; }
    .value { font-variant-numeric: tabular-nums; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .pill { display:inline-flex; align-items:center; min-height:26px; padding:3px 8px; border:1px solid var(--line); border-radius:6px; font-size:12px; color:var(--muted); }
    .controls { display:grid; grid-template-columns:72px 72px 72px; gap:8px; justify-content:center; margin:18px 0; }
    button { height:44px; border:1px solid var(--line); border-radius:7px; background:#252b35; color:var(--text); font-size:18px; cursor:pointer; }
    button:hover { border-color:var(--accent); }
    button:active { transform:translateY(1px); }
    .wide { grid-column:1 / span 3; font-size:14px; }
    input, select { width:100%; min-height:36px; color:var(--text); background:#10151d; border:1px solid var(--line); border-radius:6px; padding:0 9px; }
    .small { font-size:12px; color:var(--muted); line-height:1.5; }
    .section { border-top:1px solid var(--line); padding-top:14px; margin-top:14px; }
    @media (max-width: 860px) { main { grid-template-columns:1fr; } .side { border-left:0; border-top:1px solid var(--line); } .viewer img { max-height:58vh; } }
  </style>
</head>
<body>
  <header>
    <h1>Head Camera Control</h1>
    <span class="pill" id="status">connecting</span>
  </header>
  <main>
    <section class="viewer">
      <img id="stream" src="/snapshot.jpg" alt="camera stream">
    </section>
    <aside class="side">
      <div class="row"><span class="label">Camera</span><span class="value" id="cameraStatus">-</span></div>
      <div class="row"><span class="label">Source</span><span class="value" id="cameraSource">-</span></div>
      <div class="row"><span class="label">Frame</span><span class="value" id="frameCount">-</span></div>
      <div class="row"><span class="label">Age</span><span class="value" id="frameAge">-</span></div>
      <div class="row"><span class="label">Angle 1</span><span class="value" id="angle1">-</span></div>
      <div class="row"><span class="label">Angle 2</span><span class="value" id="angle2">-</span></div>

      <div class="controls">
        <span></span><button onclick="act('u')" title="Up">↑</button><span></span>
        <button onclick="act('l')" title="Left">←</button>
        <button onclick="act('center')" title="Center">●</button>
        <button onclick="act('r')" title="Right">→</button>
        <span></span><button onclick="act('d')" title="Down">↓</button><span></span>
        <button class="wide" onclick="refreshStatus()">Read Angles</button>
      </div>

      <div class="section">
        <div class="row"><span class="label">Repeat</span><input id="repeat" type="number" min="1" max="20" value="6"></div>
        <div class="row"><span class="label">Interval</span><input id="interval" type="number" min="0.01" max="0.5" step="0.01" value="0.05"></div>
      </div>

      <div class="section">
        <div class="row"><span class="label">Switch</span><select id="cameraSelect"></select></div>
        <button class="wide" onclick="setCamera()">Apply Camera</button>
        <p class="small">Only the head camera and two wrist cameras are shown here. Device paths are hidden from the menu to avoid picking the wrong /dev/video node.</p>
      </div>
    </aside>
  </main>
  <script>
    async function refreshStatus() {
      const res = await fetch('/api/status');
      const data = await res.json();
      document.getElementById('status').textContent = data.ok ? 'online' : 'offline';
      document.getElementById('cameraStatus').textContent = data.camera.status;
      const sourceEl = document.getElementById('cameraSource');
      sourceEl.textContent = data.camera.label || data.camera.source;
      sourceEl.title = data.camera.source;
      document.getElementById('frameCount').textContent = data.camera.frame_count;
      document.getElementById('frameAge').textContent = data.camera.frame_age_s + ' s';
      document.getElementById('angle1').textContent = data.angle ? data.angle.angle1 : '-';
      document.getElementById('angle2').textContent = data.angle ? data.angle.angle2 : '-';
      const select = document.getElementById('cameraSelect');
      if (select.children.length === 0) {
        for (const item of data.cameras) {
          const source = typeof item === 'string' ? item : item.source;
          const label = typeof item === 'string' ? item : item.label;
          const available = typeof item === 'string' ? true : item.available;
          const opt = document.createElement('option');
          opt.value = source;
          opt.textContent = available ? label : `${label} (missing)`;
          opt.title = source;
          if (source === data.camera.source) opt.selected = true;
          select.appendChild(opt);
        }
      }
    }
    async function act(action) {
      const repeat = document.getElementById('repeat').value;
      const interval = document.getElementById('interval').value;
      await fetch(`/api/action?action=${encodeURIComponent(action)}&repeat=${repeat}&interval=${interval}`);
      setTimeout(refreshStatus, 650);
    }
    let streamActive = true;
    let streamDelayMs = 125;

    function startSnapshotLoop() {
      const img = document.getElementById('stream');
      function loadNext() {
        if (!streamActive) return;
        img.src = '/snapshot.jpg?t=' + Date.now();
      }
      loadNext();
      setInterval(loadNext, streamDelayMs);
    }

    async function setCamera() {
      const source = document.getElementById('cameraSelect').value;
      await fetch(`/api/camera?source=${encodeURIComponent(source)}`);
      document.getElementById('stream').src = '/snapshot.jpg?t=' + Date.now();
      setTimeout(refreshStatus, 500);
    }
    refreshStatus();
    setInterval(refreshStatus, 1000);
    startSnapshotLoop();
  </script>
</body>
</html>
"""


class AppHandler(BaseHTTPRequestHandler):
    server: "HeadCameraServer"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.client_address[0]} - {fmt % args}")

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        camera_state = self.server.camera.snapshot()
        camera_state["label"] = self.server.camera_label(camera_state["source"])
        if parsed.path == "/":
            self._send_html(HTML)
        elif parsed.path == "/stream.mjpg":
            self._stream_mjpeg()
        elif parsed.path == "/snapshot.jpg":
            self._send_snapshot()
        elif parsed.path == "/api/status":
            self._send_json({
                "ok": True,
                "camera": camera_state,
                "angle": self.server.angles.snapshot(),
                "cameras": self.server.camera_options,
            })
        elif parsed.path == "/api/action":
            self._handle_action(query)
        elif parsed.path == "/api/camera":
            self._handle_camera(query)
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def _send_html(self, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, data: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json_bytes(data)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_snapshot(self) -> None:
        jpeg = self.server.camera.get_jpeg()
        if not jpeg:
            self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, "no camera frame")
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(jpeg)))
        self.end_headers()
        self.wfile.write(jpeg)

    def _stream_mjpeg(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Age", "0")
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()

        while True:
            jpeg = self.server.camera.get_jpeg()
            if jpeg:
                try:
                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii"))
                    self.wfile.write(jpeg)
                    self.wfile.write(b"\r\n")
                except (BrokenPipeError, ConnectionResetError):
                    return
            time.sleep(1.0 / max(1, self.server.camera.fps))

    def _handle_action(self, query: dict[str, list[str]]) -> None:
        action = query.get("action", [""])[0]
        repeat = int(float(query.get("repeat", ["6"])[0]))
        interval = float(query.get("interval", ["0.05"])[0])
        try:
            if action in ("c", "center"):
                result = self.server.head.center(repeat=repeat, interval=interval)
            else:
                result = self.server.head.send_action(action, repeat=repeat, interval=interval)
        except Exception as exc:  # noqa: BLE001 - return the error to the web UI.
            self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json(result)

    def _handle_camera(self, query: dict[str, list[str]]) -> None:
        source = query.get("source", [""])[0]
        if not source:
            self._send_json({"ok": False, "error": "missing source"}, HTTPStatus.BAD_REQUEST)
            return
        if source not in self.server.allowed_camera_sources:
            self._send_json({"ok": False, "error": f"camera not allowed: {source}"}, HTTPStatus.BAD_REQUEST)
            return
        self.server.camera.set_source(source)
        self._send_json({"ok": True, "source": source})


class HeadCameraServer(ThreadingHTTPServer):
    def __init__(self, addr: tuple[str, int], handler: type[BaseHTTPRequestHandler],
                 camera: CameraStream, angles: AngleReceiver, head: HeadUdpController,
                 camera_options: list[dict[str, Any]]):
        super().__init__(addr, handler)
        self.camera = camera
        self.angles = angles
        self.head = head
        self.camera_options = camera_options
        self.allowed_camera_sources = {item["source"] for item in camera_options}

    def camera_label(self, source: str) -> str:
        return camera_label_for_source(source, self.camera_options)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--camera", default="head", help="head, wrist_a, wrist_b, or one of their configured device paths")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=int, default=15)
    parser.add_argument("--quality", type=int, default=80)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    angles = AngleReceiver()
    head = HeadUdpController(angles)
    camera_options = list_camera_options()
    camera_source = choose_camera_source(args.camera, camera_options)
    camera = CameraStream(camera_source, args.width, args.height, args.fps, args.quality)

    angles.start()
    camera.start()
    try:
        server = HeadCameraServer((args.host, args.port), AppHandler, camera, angles, head, camera_options)
    except PermissionError as exc:
        if exc.errno == errno.EACCES and args.port < 1024:
            print(f"ERROR: port {args.port} is a privileged port on Linux.")
            print("Use a port >= 1024, for example:")
            print(f"  python3 head_camera_control.py --camera head --host {args.host} --port 8765")
            return
        raise
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            print(f"ERROR: port {args.port} is already in use.")
            print("If the web control panel is already running, open:")
            print(f"  http://192.168.3.68:{args.port}")
            print("Or choose another port, for example --port 8766.")
            return
        raise
    print(f"Head camera control: http://{args.host}:{args.port}")
    print(f"Camera source: {camera_source}")
    print("Use Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        camera.stop()
        angles.stop()
        server.server_close()


if __name__ == "__main__":
    main()
