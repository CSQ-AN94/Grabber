#!/usr/bin/env python3
"""Thin robot-side entrypoint for the right-wrist bottle grasp demo."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bottle_grasp.core import SafetyAbort
from bottle_grasp.demo import BottleDemo
from utils.config import load_config

LOG = logging.getLogger("bottle_demo")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Right wrist RGB-D bottle grasp demo"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="execute the collision-checked plan on the real right arm",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="run head localization and MoveIt planning, but never move hardware",
    )
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument(
        "--safety-config",
        default=str(ROOT / "bottle_grasp" / "safety_profiles.json"),
        help="configuration-driven electronic fence profiles",
    )
    parser.add_argument(
        "--safety-profile",
        default="table_demo",
        help="electronic fence profile name",
    )
    parser.add_argument(
        "--stop-after-observation",
        action="store_true",
        help="execute only through wrist observation and localization",
    )
    parser.add_argument(
        "--place-back",
        action="store_true",
        help="抓取抬升后把瓶子放回桌面并退开（不加则保持抓着不动）",
    )
    parser.add_argument(
        "--autonomous-observation",
        action="store_true",
        help=(
            "头部定位后强制用 MoveIt 自主规划移动到右腕观察位，"
            "忽略 profile 里配置的示教走廊（测试简单几何场景，如瓶子放桌角）"
        ),
    )
    parser.add_argument(
        "--full-cycle",
        action="store_true",
        help=(
            "完整一轮：垂下→观察位→抓取→抬升→放回→垂回。"
            "转移段走示教走廊（--guided-path 或 profile 的 guided_path）"
        ),
    )
    parser.add_argument(
        "--guided-path",
        default=None,
        help="覆盖示教转移走廊 JSON（grabber_guided_path_v1，首点=垂下姿态）",
    )
    parser.add_argument(
        "--restore-teleop",
        action="store_true",
        help="完整循环结束后自动运行官方 upstart_all.sh 恢复遥操",
    )
    parser.add_argument(
        "--resume-at-wrist",
        action="store_true",
        help="keep the current right-arm pose and resume wrist visual grasping",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8876)
    parser.add_argument(
        "--output-dir", default=str(ROOT / "outputs" / "bottle_grasp")
    )
    parser.add_argument("--observe-seconds", type=float, default=10.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.execute and args.plan_only:
        raise SystemExit("--execute and --plan-only are mutually exclusive")
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(Path(args.output_dir) / "latest.log"),
        ],
    )
    demo = BottleDemo(args, load_config(args.config))

    def request_stop(signum=None, frame=None):
        LOG.warning("收到停止请求：缓停并保持，不自动后退")
        demo.stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    try:
        demo.run()
        return 0
    except SafetyAbort as exc:
        LOG.error("安全中止: %s", exc)
        demo.state.update(stage="安全中止", message=str(exc))
        return 2
    except Exception:
        LOG.exception("未处理异常，停止并保持")
        demo.state.update(stage="程序错误", message="查看日志")
        return 1
    finally:
        demo.close()


if __name__ == "__main__":
    raise SystemExit(main())
