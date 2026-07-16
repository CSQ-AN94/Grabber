#!/usr/bin/env python3
"""Record a teleoperated right-arm path without issuing motion commands."""

from __future__ import annotations

import argparse
import json
import signal
import time
from datetime import datetime
from pathlib import Path

import numpy as np


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only recorder for a demonstrated safe right-arm path"
    )
    parser.add_argument("--ip", default="169.254.128.19")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--rate", type=float, default=10.0)
    parser.add_argument("--min-joint-change-deg", type=float, default=0.15)
    parser.add_argument("--max-idle-s", type=float, default=0.5)
    parser.add_argument(
        "--output",
        default=(
            "outputs/bottle_grasp/guided_paths/"
            + datetime.now().strftime("%Y%m%d_%H%M%S")
            + "_right_arm.json"
        ),
    )
    args = parser.parse_args()

    from Robotic_Arm.rm_robot_interface import RoboticArm, rm_thread_mode_e

    stop = False

    def request_stop(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    arm = RoboticArm(rm_thread_mode_e.RM_TRIPLE_MODE_E)
    handle = arm.rm_create_robot_arm(args.ip, args.port)
    if handle.id == -1:
        raise SystemExit("right-arm SDK read-only connection failed")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    samples = []
    previous = None
    last_saved = 0.0
    start = time.monotonic()
    print(f"Recording read-only right-arm path to {output}")
    print("Teleoperate normally; press Ctrl+C here when the demonstrated path ends.")
    try:
        while not stop:
            rc_q, joints = arm.rm_get_joint_degree()
            rc_state, state = arm.rm_get_current_arm_state()
            now = time.monotonic()
            if rc_q == 0 and rc_state == 0 and state.get("pose"):
                joints_array = np.asarray(joints, dtype=float)
                changed = (
                    previous is None
                    or np.max(np.abs(joints_array - previous))
                    >= args.min_joint_change_deg
                    or now - last_saved >= args.max_idle_s
                )
                if changed:
                    samples.append(
                        {
                            "t_s": round(now - start, 4),
                            "joints_deg": joints_array.tolist(),
                            "controller_pose": list(
                                map(float, state["pose"])
                            ),
                        }
                    )
                    previous = joints_array
                    last_saved = now
                    print(
                        f"\rrecorded {len(samples)} samples",
                        end="",
                        flush=True,
                    )
            time.sleep(max(0.01, 1.0 / args.rate))
    finally:
        arm.rm_delete_robot_arm()
        payload = {
            "format": "grabber_guided_path_v1",
            "arm": "right",
            "ip": args.ip,
            "sample_rate_hz": args.rate,
            "recorded_at": datetime.now().isoformat(timespec="seconds"),
            "samples": samples,
        }
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(output)
        print(f"\nSaved {len(samples)} samples to {output}")
    return 0 if len(samples) >= 2 else 2


if __name__ == "__main__":
    raise SystemExit(main())
