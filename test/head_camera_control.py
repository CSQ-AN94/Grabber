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
import html
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
DEFAULT_SHARED_DIR = "/tmp/grabber_camera_frames"
SHARED_STALE_SECONDS = 3.0

CAMERA_SPECS = [
    {
        "id": "head",
        "label": "头部相机",
        "shared_name": "head",
        "env": "HEAD_CAMERA",
        "aliases": ["/dev/video4"],
        "candidates": [
            "/dev/video4",
            "/dev/v4l/by-path/platform-3610000.usb-usb-0:2:1.3-video-index0",
        ],
    },
    {
        "id": "right_wrist",
        "label": "右腕相机",
        "shared_name": "right_wrist",
        "env": "RIGHT_WRIST_CAMERA",
        "aliases": ["wrist_b", "/dev/video20"],
        "candidates": [
            "/dev/video20",
            "/dev/v4l/by-path/platform-3610000.usb-usb-0:3.2.4.3:1.3-video-index0",
        ],
    },
    {
        "id": "left_wrist",
        "label": "左腕相机",
        "shared_name": "left_wrist",
        "env": "LEFT_WRIST_CAMERA",
        "aliases": ["wrist_a", "/dev/video14"],
        "candidates": [
            "/dev/video14",
            "/dev/v4l/by-path/platform-3610000.usb-usb-0:3.2.4.4:1.3-video-index0",
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


def _env_camera_source(spec: dict[str, Any]) -> str:
    names = [spec["env"]]
    if spec["id"] == "right_wrist":
        names.append("WRIST_CAMERA_B")
    elif spec["id"] == "left_wrist":
        names.append("WRIST_CAMERA_A")
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def list_camera_options(shared: "SharedFrameStore | None" = None) -> list[dict[str, Any]]:
    options = []
    for spec in CAMERA_SPECS:
        env_source = _env_camera_source(spec)
        candidates = [env_source] if env_source else spec["candidates"]
        source = _first_existing(candidates)
        shared_info = shared.info(spec["id"]) if shared else {}
        options.append({
            "id": spec["id"],
            "label": spec["label"],
            "shared_name": spec["shared_name"],
            "source": source,
            "available": os.path.exists(source),
            "shared": shared_info,
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


def camera_id_for_value(value: str, options: list[dict[str, Any]]) -> str:
    if not value:
        return "head"
    for option, spec in zip(options, CAMERA_SPECS):
        names = {
            option["id"],
            option["label"],
            option["source"],
            option["shared_name"],
            *spec["aliases"],
        }
        if value in names:
            return option["id"]
    return "head"


def camera_ids_for_value(value: str, options: list[dict[str, Any]]) -> list[str]:
    if value in ("all", "multi", "*"):
        return [option["id"] for option in options]
    return [camera_id_for_value(value, options)]


class SharedFrameStore:
    def __init__(self, directory: str = DEFAULT_SHARED_DIR):
        self.directory = directory

    def _paths(self, camera_id: str) -> tuple[str, str]:
        safe_id = camera_id.replace("/", "_")
        return (
            os.path.join(self.directory, f"{safe_id}.jpg"),
            os.path.join(self.directory, f"{safe_id}.json"),
        )

    def read_jpeg(self, camera_id: str, require_fresh: bool = True) -> bytes | None:
        if require_fresh and not self.info(camera_id).get("fresh"):
            return None
        jpg_path, _ = self._paths(camera_id)
        try:
            with open(jpg_path, "rb") as fh:
                return fh.read()
        except OSError:
            return None

    def info(self, camera_id: str) -> dict[str, Any]:
        jpg_path, json_path = self._paths(camera_id)
        exists = os.path.exists(jpg_path)
        mtime = os.path.getmtime(jpg_path) if exists else 0.0
        age = time.time() - mtime if mtime else None
        meta: dict[str, Any] = {}
        try:
            with open(json_path, "r", encoding="utf-8") as fh:
                meta = json.load(fh)
        except (OSError, json.JSONDecodeError):
            pass
        return {
            "path": jpg_path,
            "exists": exists,
            "age_s": None if age is None else round(age, 3),
            "fresh": bool(exists and age is not None and age <= SHARED_STALE_SECONDS),
            **meta,
        }


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

    def join(self, timeout: float = 2.0) -> None:
        self._thread.join(timeout=timeout)

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
    .viewer { display:flex; align-items:stretch; justify-content:center; padding:14px; background:#07090d; }
    .streams { width:100%; display:grid; grid-template-columns:repeat(auto-fit, minmax(320px, 1fr)); gap:12px; align-content:start; }
    .tile { min-width:0; border:1px solid var(--line); background:#000; }
    .tile-head { display:flex; align-items:center; justify-content:space-between; gap:10px; min-height:34px; padding:7px 9px; background:#141922; border-bottom:1px solid var(--line); }
    .tile-title { font-size:13px; font-weight:650; }
    .tile-meta { font-size:12px; color:var(--muted); white-space:nowrap; }
    .tile img { display:block; width:100%; height:auto; max-height:calc(100vh - 138px); object-fit:contain; background:#000; }
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
    .mode-buttons { display:grid; grid-template-columns:1fr 1fr; gap:8px; width:100%; }
    .mode-buttons button { height:36px; font-size:13px; }
    .mode-buttons button[aria-pressed="true"] { border-color:var(--accent); color:#0b1712; background:var(--accent); }
    .camera-options { display:grid; gap:8px; }
    .camera-option { display:flex; align-items:center; gap:9px; min-height:34px; padding:7px 9px; border:1px solid var(--line); border-radius:6px; background:#10151d; font-size:13px; }
    .camera-option input { width:auto; min-height:0; }
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
      <div id="streams" class="streams"></div>
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
        <div class="row"><span class="label">Mode</span><div class="mode-buttons">
          <button id="modeShared" onclick="setMode('shared')" aria-pressed="false">Shared</button>
          <button id="modeDirect" onclick="setMode('direct')" aria-pressed="false">Direct</button>
        </div></div>
        <div class="row"><span class="label">View</span><span class="value">选择一路或多路画面</span></div>
        <div id="cameraChecks" class="camera-options"></div>
        <p class="small">Shared reads /tmp/grabber_camera_frames without opening cameras. Direct opens the checked camera devices.</p>
      </div>
    </aside>
  </main>
  <script>
    let lastCameraKey = '';
    let latestCameras = [];
    let latestStatus = null;

    function selectedCameraIds() {
      return Array.from(document.querySelectorAll('.camera-check:checked')).map(el => el.value);
    }

    function renderCameraChecks(cameras, activeIds = null) {
      const box = document.getElementById('cameraChecks');
      const key = cameras.map(c => c.id + ':' + c.label).join('|');
      if (key === lastCameraKey && box.children.length > 0) return;
      lastCameraKey = key;
      box.innerHTML = '';
      for (const camera of cameras) {
        const label = document.createElement('label');
        label.className = 'camera-option';
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.className = 'camera-check';
        input.value = camera.id;
        input.checked = activeIds ? activeIds.includes(camera.id) : camera.id === 'head';
        input.onchange = () => {
          renderStreamTiles(latestCameras);
          if (latestStatus && latestStatus.frame_source === 'direct') {
            setMode('direct');
          }
        };
        const text = document.createElement('span');
        text.textContent = camera.label;
        label.appendChild(input);
        label.appendChild(text);
        box.appendChild(label);
      }
    }

    function renderStreamTiles(cameras) {
      const ids = selectedCameraIds();
      const streams = document.getElementById('streams');
      const currentKey = streams.dataset.key || '';
      const nextKey = ids.join('|');
      if (currentKey === nextKey && streams.children.length > 0) return;
      streams.dataset.key = nextKey;
      streams.innerHTML = '';
      const byId = Object.fromEntries(cameras.map(c => [c.id, c]));
      for (const id of ids) {
        const camera = byId[id] || {id, label: id};
        const tile = document.createElement('div');
        tile.className = 'tile';
        tile.dataset.camera = id;
        tile.innerHTML = `<div class="tile-head"><span class="tile-title"></span><span class="tile-meta"></span></div><img alt="">`;
        tile.querySelector('.tile-title').textContent = camera.label;
        tile.querySelector('img').alt = camera.label;
        streams.appendChild(tile);
      }
    }

    function sharedStatusText(shared) {
      if (!shared) return 'waiting';
      if (shared.fresh) return `${shared.age_s}s`;
      if (shared.exists && shared.age_s != null) return `stale ${shared.age_s}s`;
      return 'waiting';
    }

    function cameraStatusText(camera, data) {
      const directById = Object.fromEntries((data.direct_cameras || []).map(item => [item.id, item]));
      const direct = directById[camera.id] || null;
      if (data.frame_source === 'direct' && direct) {
        return direct.frame_age_s != null ? `direct ${direct.frame_age_s}s` : 'direct';
      }
      return sharedStatusText(camera.shared);
    }

    function updateCameraStatus(cameras, data) {
      const selected = selectedCameraIds();
      const active = cameras.filter(c => selected.includes(c.id));
      const directCount = (data.direct_cameras || []).length;
      const ages = active.map(c => `${c.label}:${cameraStatusText(c, data)}`);
      document.getElementById('frameCount').textContent = directCount ? `${directCount} direct view(s)` : (active.length ? `${active.length} view(s)` : '-');
      document.getElementById('frameAge').textContent = ages.length ? ages.join(' | ') : '-';
      for (const camera of cameras) {
        const tile = document.querySelector(`.tile[data-camera="${camera.id}"]`);
        if (!tile) continue;
        tile.querySelector('.tile-meta').textContent = cameraStatusText(camera, data);
      }
    }

    function updateModeControls(data) {
      document.getElementById('modeShared').setAttribute('aria-pressed', data.frame_source === 'shared' ? 'true' : 'false');
      document.getElementById('modeDirect').setAttribute('aria-pressed', data.frame_source === 'direct' ? 'true' : 'false');
    }

    async function refreshStatus() {
      const res = await fetch('/api/status');
      const data = await res.json();
      latestStatus = data;
      latestCameras = data.cameras || [];
      document.getElementById('status').textContent = data.ok ? 'online' : 'offline';
      document.getElementById('cameraStatus').textContent = data.frame_source;
      const sourceEl = document.getElementById('cameraSource');
      const sourceText = (data.direct_cameras || []).length
        ? (data.direct_cameras || []).map(item => item.source).join(' | ')
        : data.shared_dir;
      sourceEl.textContent = sourceText || '-';
      sourceEl.title = sourceText || '';
      document.getElementById('angle1').textContent = data.angle ? data.angle.angle1 : '-';
      document.getElementById('angle2').textContent = data.angle ? data.angle.angle2 : '-';
      const directIds = (data.direct_cameras || []).map(item => item.id);
      renderCameraChecks(latestCameras, directIds.length ? directIds : null);
      renderStreamTiles(latestCameras);
      updateCameraStatus(latestCameras, data);
      updateModeControls(data);
    }

    async function setMode(mode) {
      const cameras = selectedCameraIds();
      const cameraParam = cameras.length ? cameras.join(',') : 'head';
      document.getElementById('status').textContent = 'switching';
      const res = await fetch(`/api/mode?source=${encodeURIComponent(mode)}&cameras=${encodeURIComponent(cameraParam)}`);
      const data = await res.json();
      if (!data.ok) {
        document.getElementById('status').textContent = data.error || 'error';
      }
      setTimeout(refreshStatus, 350);
    }

    async function act(action) {
      const repeat = document.getElementById('repeat').value;
      const interval = document.getElementById('interval').value;
      await fetch(`/api/action?action=${encodeURIComponent(action)}&repeat=${repeat}&interval=${interval}`);
      setTimeout(refreshStatus, 650);
    }
    let streamActive = true;
    let streamDelayMs = 180;

    function startSnapshotLoop() {
      function loadNext() {
        if (!streamActive) return;
        for (const img of document.querySelectorAll('.tile img')) {
          const camera = img.closest('.tile').dataset.camera;
          img.src = `/snapshot.jpg?camera=${encodeURIComponent(camera)}&t=${Date.now()}`;
        }
      }
      loadNext();
      setInterval(loadNext, streamDelayMs);
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
        if parsed.path == "/":
            self._send_html(HTML)
        elif parsed.path == "/stream.mjpg":
            self._stream_mjpeg(query)
        elif parsed.path == "/snapshot.jpg":
            self._send_snapshot(query)
        elif parsed.path == "/api/status":
            self._send_json(self.server.status_payload())
        elif parsed.path == "/api/action":
            self._handle_action(query)
        elif parsed.path == "/api/mode":
            self._handle_mode(query)
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

    def _send_snapshot(self, query: dict[str, list[str]]) -> None:
        camera_id = self.server.camera_id_from_query(query)
        jpeg = self.server.get_jpeg(camera_id)
        if jpeg:
            self._send_image(jpeg, "image/jpeg")
            return
        self._send_image(self.server.placeholder_svg(camera_id), "image/svg+xml; charset=utf-8")

    def _send_image(self, payload: bytes, content_type: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _stream_mjpeg(self, query: dict[str, list[str]]) -> None:
        camera_id = self.server.camera_id_from_query(query)
        self.send_response(HTTPStatus.OK)
        self.send_header("Age", "0")
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()

        while True:
            jpeg = self.server.get_jpeg(camera_id)
            if jpeg:
                try:
                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii"))
                    self.wfile.write(jpeg)
                    self.wfile.write(b"\r\n")
                except (BrokenPipeError, ConnectionResetError):
                    return
            time.sleep(1.0 / max(1, self.server.fps))

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

    def _handle_mode(self, query: dict[str, list[str]]) -> None:
        source = query.get("source", query.get("mode", [""]))[0]
        camera_values = query.get("cameras", [])
        camera_ids: list[str] = []
        for value in camera_values:
            camera_ids.extend(item for item in value.split(",") if item)
        if not camera_ids:
            camera_ids = query.get("camera", ["head"])
        try:
            result = self.server.set_frame_source(source, camera_ids)
        except Exception as exc:  # noqa: BLE001 - return the error to the web UI.
            self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json(result)

    def _handle_camera(self, query: dict[str, list[str]]) -> None:
        source = query.get("source", [""])[0]
        if not source:
            self._send_json({"ok": False, "error": "missing source"}, HTTPStatus.BAD_REQUEST)
            return
        camera_id = camera_id_for_value(source, self.server.camera_options)
        if self.server.frame_source != "direct":
            self._send_json(
                {"ok": False, "error": "direct camera is disabled in shared mode"},
                HTTPStatus.BAD_REQUEST,
            )
            return
        self._send_json(self.server.set_frame_source("direct", [camera_id]))


class HeadCameraServer(ThreadingHTTPServer):
    def __init__(self, addr: tuple[str, int], handler: type[BaseHTTPRequestHandler],
                 direct_cameras: dict[str, CameraStream], angles: AngleReceiver, head: HeadUdpController,
                 camera_options: list[dict[str, Any]], shared: SharedFrameStore,
                 frame_source: str, width: int, height: int, fps: int, quality: int):
        super().__init__(addr, handler)
        self.direct_cameras = direct_cameras
        self.angles = angles
        self.head = head
        self.shared = shared
        self.frame_source = frame_source
        self.width = width
        self.height = height
        self.fps = fps
        self.quality = quality
        self.camera_options = camera_options
        self.allowed_camera_sources = {item["source"] for item in camera_options}
        self._mode_lock = threading.Lock()

    def camera_label(self, source: str) -> str:
        return camera_label_for_source(source, self.camera_options)

    def camera_id_from_query(self, query: dict[str, list[str]]) -> str:
        value = query.get("camera", ["head"])[0]
        return camera_id_for_value(value, self.camera_options)

    def _source_for_camera_id(self, camera_id: str) -> str:
        self.camera_options = list_camera_options(self.shared)
        self.allowed_camera_sources = {item["source"] for item in self.camera_options}
        for option in self.camera_options:
            if option["id"] == camera_id:
                return option["source"]
        return choose_camera_source(camera_id, self.camera_options)

    def set_frame_source(self, frame_source: str, camera_ids: list[str] | str = "head") -> dict[str, Any]:
        if frame_source not in ("shared", "direct"):
            raise ValueError("source must be shared or direct")
        if isinstance(camera_ids, str):
            camera_ids = [camera_ids]
        camera_ids = camera_ids or ["head"]

        with self._mode_lock:
            if frame_source == "shared":
                old_cameras = self.direct_cameras
                self.direct_cameras = {}
                self.frame_source = "shared"
                for camera in old_cameras.values():
                    camera.stop()
                for camera in old_cameras.values():
                    camera.join()
                return {"ok": True, "frame_source": self.frame_source}

            targets: dict[str, str] = {}
            for camera_id in camera_ids:
                source = self._source_for_camera_id(camera_id)
                if source not in self.allowed_camera_sources:
                    raise ValueError(f"camera not allowed: {source}")
                targets[camera_id] = source

            for camera_id, camera in list(self.direct_cameras.items()):
                if camera_id not in targets:
                    camera.stop()
                    camera.join()
                    del self.direct_cameras[camera_id]

            for camera_id, source in targets.items():
                camera = self.direct_cameras.get(camera_id)
                if camera is None:
                    camera = CameraStream(source, self.width, self.height, self.fps, self.quality)
                    self.direct_cameras[camera_id] = camera
                    camera.start()
                elif camera.source != source:
                    camera.set_source(source)
            self.frame_source = "direct"
            return {
                "ok": True,
                "frame_source": self.frame_source,
                "cameras": [{"id": camera_id, "source": source} for camera_id, source in targets.items()],
            }

    def get_jpeg(self, camera_id: str) -> bytes | None:
        with self._mode_lock:
            frame_source = self.frame_source
            camera = self.direct_cameras.get(camera_id)

        if frame_source in ("shared", "auto"):
            jpeg = self.shared.read_jpeg(camera_id, require_fresh=True)
            if jpeg:
                return jpeg
        if frame_source in ("direct", "auto") and camera is not None:
            return camera.get_jpeg()
        return None

    def placeholder_svg(self, camera_id: str) -> bytes:
        info = self.shared.info(camera_id)
        label = camera_id
        for option in self.camera_options:
            if option["id"] == camera_id:
                label = option["label"]
                break

        if info.get("exists") and info.get("age_s") is not None:
            detail = f"last shared frame is {info['age_s']}s old"
        else:
            detail = "no shared frame file yet"
        mode = "shared mode waits for CameraThread frames" if self.frame_source == "shared" else "direct camera is not checked or has no frame"
        lines = [
            "Waiting for fresh camera frame",
            f"{label} ({camera_id})",
            detail,
            mode,
        ]
        escaped = [html.escape(str(line), quote=False) for line in lines]
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 480">
  <rect width="640" height="480" fill="#07090d"/>
  <rect x="34" y="34" width="572" height="412" rx="10" fill="#151922" stroke="#323946" stroke-width="2"/>
  <circle cx="82" cy="92" r="10" fill="#f5b85b"/>
  <text x="108" y="100" fill="#edf1f7" font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="25" font-weight="650">{escaped[0]}</text>
  <text x="56" y="168" fill="#edf1f7" font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="22">{escaped[1]}</text>
  <text x="56" y="214" fill="#f5b85b" font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="20">{escaped[2]}</text>
  <text x="56" y="260" fill="#98a2b3" font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="18">{escaped[3]}</text>
  <text x="56" y="306" fill="#98a2b3" font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="18">Run bottle demo/CameraThread, or use direct mode when cameras are free.</text>
</svg>
"""
        return svg.encode("utf-8")

    def status_payload(self) -> dict[str, Any]:
        self.camera_options = list_camera_options(self.shared)
        self.allowed_camera_sources = {item["source"] for item in self.camera_options}
        with self._mode_lock:
            frame_source = self.frame_source
            cameras = dict(self.direct_cameras)
        direct_cameras = []
        for camera_id, camera in cameras.items():
            direct = camera.snapshot()
            direct["label"] = self.camera_label(direct["source"])
            direct["id"] = camera_id
            direct_cameras.append(direct)
        direct_cameras.sort(key=lambda item: [spec["id"] for spec in CAMERA_SPECS].index(item["id"]))
        primary_direct = direct_cameras[0] if direct_cameras else None
        return {
            "ok": True,
            "frame_source": frame_source,
            "shared_dir": self.shared.directory,
            "direct_cameras": direct_cameras,
            "direct_camera": primary_direct,
            "camera": primary_direct or {
                "status": "shared",
                "source": self.shared.directory,
                "frame_count": None,
                "frame_age_s": None,
                "label": "shared frames",
            },
            "angle": self.angles.snapshot(),
            "cameras": self.camera_options,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--camera", default="head", help="head, right_wrist, left_wrist, wrist_a, wrist_b, or a configured device path")
    parser.add_argument(
        "--frame-source",
        choices=("shared", "direct"),
        default=os.environ.get("FRAME_SOURCE", os.environ.get("HEAD_CAMERA_FRAME_SOURCE", "shared")),
        help="shared reads /tmp/grabber_camera_frames without opening cameras; direct opens one camera device",
    )
    parser.add_argument(
        "--shared-dir",
        default=os.environ.get("CAMERA_SHARE_DIR", DEFAULT_SHARED_DIR),
        help="directory containing shared camera jpg/json files",
    )
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=int, default=15)
    parser.add_argument("--quality", type=int, default=80)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    angles = AngleReceiver()
    head = HeadUdpController(angles)
    shared = SharedFrameStore(args.shared_dir)
    camera_options = list_camera_options(shared)
    initial_camera_ids = camera_ids_for_value(args.camera, camera_options)
    direct_cameras: dict[str, CameraStream] = {}
    if args.frame_source == "direct":
        for camera_id in initial_camera_ids:
            camera_source = choose_camera_source(camera_id, camera_options)
            direct_cameras[camera_id] = CameraStream(camera_source, args.width, args.height, args.fps, args.quality)

    angles.start()
    for camera in direct_cameras.values():
        camera.start()
    try:
        server = HeadCameraServer(
            (args.host, args.port),
            AppHandler,
            direct_cameras,
            angles,
            head,
            camera_options,
            shared,
            args.frame_source,
            args.width,
            args.height,
            args.fps,
            args.quality,
        )
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
    print(f"Frame source: {args.frame_source}")
    if not direct_cameras:
        print(f"Shared frame dir: {shared.directory}")
    else:
        for camera_id, camera in direct_cameras.items():
            print(f"Camera source ({camera_id}): {camera.source}")
    print("Use Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for camera in list(server.direct_cameras.values()):
            camera.stop()
        for camera in list(server.direct_cameras.values()):
            camera.join()
        angles.stop()
        server.server_close()


if __name__ == "__main__":
    main()
