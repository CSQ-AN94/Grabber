#!/usr/bin/env python3
"""Headless RealSense preview server for wrist-camera calibration.

Run this on the robot and view it through an SSH port forward.  It never opens
an OpenCV/desktop window on the robot.
"""

import argparse
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sensors.camera_thread import CameraThread


class PreviewHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            body = (
                "<!doctype html><meta charset='utf-8'><title>Right wrist camera</title>"
                "<style>body{margin:0;background:#111;color:#eee;font-family:sans-serif;text-align:center}"
                "img{max-width:100vw;max-height:92vh}h3{margin:8px}</style>"
                "<h3>右腕相机（机器人端无窗口）</h3><img src='/stream.mjpg'>"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/snapshot.jpg"):
            self._send_snapshot()
            return
        if self.path == "/stream.mjpg":
            self._send_stream()
            return
        if self.path == "/status.json":
            intrinsics = self.server.camera.get_camera_intrinsics()
            body = json.dumps({
                "serial": self.server.serial,
                "camera_matrix": intrinsics[0].tolist(),
                "dist_coeffs": intrinsics[1].reshape(-1).tolist(),
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def _jpeg(self):
        frame = self.server.camera.get_latest_frames()[0]
        if frame is None:
            return None
        ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
        return encoded.tobytes() if ok else None

    def _send_snapshot(self):
        jpeg = self._jpeg()
        if jpeg is None:
            self.send_error(503, "camera frame unavailable")
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(jpeg)))
        self.end_headers()
        self.wfile.write(jpeg)

    def _send_stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            while True:
                jpeg = self._jpeg()
                if jpeg is None:
                    time.sleep(0.05)
                    continue
                self.wfile.write(
                    b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                    + str(len(jpeg)).encode("ascii") + b"\r\n\r\n" + jpeg + b"\r\n"
                )
                time.sleep(1 / 20)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, fmt, *args):
        if not self.path.startswith("/snapshot.jpg"):
            super().log_message(fmt, *args)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", default="405622073249")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8875)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=int, default=30)
    args = parser.parse_args()

    camera = CameraThread(
        serial=args.serial, width=args.width, height=args.height,
        fps=args.fps, strict_serial=True,
    )
    if not camera.initialization_successful:
        raise SystemExit("[FATAL] wrist camera initialization failed")
    camera.start()
    time.sleep(2)
    if camera.get_latest_frames()[0] is None:
        camera.stop()
        camera.join(timeout=3)
        raise SystemExit("[FATAL] wrist camera returned no frames")

    server = ThreadingHTTPServer((args.host, args.port), PreviewHandler)
    server.camera = camera
    server.serial = args.serial
    print(f"Wrist preview: http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        camera.stop()
        camera.join(timeout=3)


if __name__ == "__main__":
    main()
