#!/usr/bin/env python3
"""Thin robot-side entrypoint for the right-wrist bottle grasp demo."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bottle_grasp import console
from bottle_grasp.core import SafetyAbort
from bottle_grasp.demo import BottleDemo
from utils.config import load_config

LOG = logging.getLogger("bottle_demo")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Right wrist RGB-D bottle grasp demo"
    )
    parser.add_argument(
        "--task-mode",
        choices=("from-observation", "from-start"),
        help=(
            "run one supported real-robot transaction: start at the verified "
            "right-wrist observation pose, or start with head localization"
        ),
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
        "--confirm-before-grasp",
        action="store_true",
        help=(
            "到达观察位、检测到水瓶后暂停等待终端 Enter 再继续抓取；"
            "同一进程内暂停，不重启相机/YOLO/MoveIt。与 --stop-after-observation"
            "互斥（后者直接不抓取退出）"
        ),
    )
    parser.add_argument(
        "--place-back",
        action="store_true",
        help="抓取抬升后把瓶子放回桌面并退开（不加则保持抓着不动）",
    )
    parser.add_argument(
        "--return-home",
        action="store_true",
        help=(
            "放回后额外用 MoveIt 规划返回 profile 里的 home_joints_deg"
            "（跟去程一样只受电子围栏保护，需要该 profile 配置了 home_joints_deg）"
        ),
    )
    parser.add_argument(
        "--dispense",
        action="store_true",
        help=(
            "抓取抬升后送到 profile 里的 output_joints_deg 出货口（真实出货），"
            "而不是放回原货架位置；只能跟 --task-mode 一起用，需要目标 "
            "electronic-fence profile 配置了 output_joints_deg"
        ),
    )
    parser.add_argument(
        "--target-product",
        default=None,
        help=(
            "按商品类别选择要抓的目标（YOLO 类别名，可用逗号分隔多个别名）；"
            "不给则保持现状——detector 内置的通用瓶子类别"
        ),
    )
    parser.add_argument(
        "--restore-teleop",
        action="store_true",
        help="demo 结束（STOP/Ctrl+C 退出保持）后自动运行官方 upstart_all.sh 恢复遥操",
    )
    parser.add_argument(
        "--resume-at-wrist",
        action="store_true",
        help="keep the current right-arm pose and resume wrist visual grasping",
    )
    parser.add_argument(
        "--finish-from-current",
        action="store_true",
        help=(
            "跳过定位与抓取，假设夹爪已经抓着水瓶（上一轮运行遗留在原地），"
            "从当前姿态直接按 --place-back/--return-home 收尾"
        ),
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
    if (
        not args.task_mode
        and os.environ.get("BOTTLE_GRASP_ALLOW_LEGACY") != "1"
    ):
        raise SystemExit(
            "legacy phase flags are disabled; use --execute --task-mode "
            "{from-observation|from-start}. Developers may set "
            "BOTTLE_GRASP_ALLOW_LEGACY=1 for isolated diagnostics only."
        )
    if args.execute and args.plan_only:
        raise SystemExit("--execute and --plan-only are mutually exclusive")
    if args.confirm_before_grasp and args.stop_after_observation:
        raise SystemExit(
            "--confirm-before-grasp and --stop-after-observation are "
            "mutually exclusive"
        )
    if args.task_mode and not args.execute:
        raise SystemExit("--task-mode requires --execute")
    if args.dispense and not args.task_mode:
        raise SystemExit("--dispense requires --task-mode")
    if args.task_mode and any(
        (
            args.plan_only,
            args.stop_after_observation,
            args.confirm_before_grasp,
            args.place_back,
            args.return_home,
            args.resume_at_wrist,
            args.finish_from_current,
        )
    ):
        raise SystemExit(
            "--task-mode owns the complete workflow and cannot be combined "
            "with legacy phase flags"
        )
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, handlers=[])
    demo = BottleDemo(args, load_config(args.config))
    # Full detail keeps going to latest.log and the per-run run.log; the
    # terminal gets phase structure, live progress and timing instead.
    demo.timeline = console.install(
        latest_log=Path(args.output_dir) / "latest.log"
    )

    def request_stop(signum=None, frame=None):
        LOG.warning(
            "收到停止请求：后台监控线程正请求控制器缓停；不自动后退。"
            "硬件急停仍是最终保护"
        )
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
        # Where the wall clock actually went.  Printed on success and on
        # failure alike: a slow run and an aborted run are both worth
        # attributing to a phase.
        if demo.timeline is not None:
            summary = demo.timeline.render()
            if summary:
                print(summary)


if __name__ == "__main__":
    raise SystemExit(main())
