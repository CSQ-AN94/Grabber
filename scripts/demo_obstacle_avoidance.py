#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hardware-free obstacle-avoidance gate demo.

This demo uses mock detector boxes to show how a shelf-picking target can be
accepted or rejected before any robot motion is issued.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from html import escape
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from utils.safety_region import ImageSafetyConfig, evaluate_image_space_safety, expand_box


CASES: Dict[str, List[dict]] = {
    "blocked": [
        {"name": "red_bull", "confidence": 0.94, "box": [280, 245, 360, 385], "center_depth_m": 0.82},
        {"name": "chips", "confidence": 0.88, "box": [226, 155, 312, 318], "center_depth_m": 0.81},
        {"name": "water", "confidence": 0.86, "box": [425, 175, 500, 340], "center_depth_m": 0.83},
    ],
    "clear": [
        {"name": "red_bull", "confidence": 0.94, "box": [280, 245, 360, 385], "center_depth_m": 0.82},
        {"name": "chips", "confidence": 0.88, "box": [130, 160, 215, 320], "center_depth_m": 0.82},
        {"name": "water", "confidence": 0.86, "box": [430, 175, 505, 340], "center_depth_m": 0.83},
    ],
}


def _svg_rect(x1: int, y1: int, x2: int, y2: int, stroke: str, fill: str = "none", opacity: float = 1.0) -> str:
    width = max(0, x2 - x1)
    height = max(0, y2 - y1)
    return (
        f'<rect x="{x1}" y="{y1}" width="{width}" height="{height}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="2" opacity="{opacity:.2f}" />'
    )


def _svg_label(text: str, x: int, y: int, color: str, size: int = 16) -> str:
    y = max(size, y)
    return (
        f'<text x="{x}" y="{y}" fill="{color}" font-family="Arial, sans-serif" '
        f'font-size="{size}" font-weight="600">{escape(text)}</text>'
    )


def render_case_svg(case_name: str, detections: List[dict], result: dict, config: ImageSafetyConfig) -> str:
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{config.image_width}" height="{config.image_height}" '
        f'viewBox="0 0 {config.image_width} {config.image_height}">',
        '<rect x="0" y="0" width="100%" height="100%" fill="#f5f5f5" />',
        f'<line x1="0" y1="210" x2="{config.image_width}" y2="210" stroke="#d2d2d2" />',
        f'<line x1="0" y1="400" x2="{config.image_width}" y2="400" stroke="#d2d2d2" />',
    ]

    corridor = result.get("corridor")
    if corridor:
        x1, y1, x2, y2 = corridor
        color = "#3cb44b" if result["safe"] else "#e02f2f"
        parts.append(_svg_rect(x1, y1, x2, y2, color, color, opacity=0.18))
        parts.append(_svg_rect(x1, y1, x2, y2, color))
        parts.append(_svg_label("approach corridor", x1 + 4, y1 + 22, color, size=15))

    blockers = set(id(det) for det in result.get("blockers", []))
    target = result.get("target")
    target_id = id(target) if target else None

    for det in detections:
        box = expand_box(det["box"], 0, config.image_width, config.image_height)
        x1, y1, x2, y2 = box
        if id(det) == target_id:
            color = "#3cb44b"
        elif id(det) in blockers:
            color = "#e02f2f"
        else:
            color = "#2878b5"
        parts.append(_svg_rect(x1, y1, x2, y2, color))
        label = f"{det['name']} {det.get('center_depth_m', 0):.2f}m"
        parts.append(_svg_label(label, x1, y1 - 8, color, size=15))

    status = "SAFE" if result["safe"] else "BLOCKED"
    status_color = "#3cb44b" if result["safe"] else "#e02f2f"
    parts.append(_svg_label(f"{case_name}: {status}", 20, 32, status_color, size=20))
    parts.append("</svg>")
    return "\n".join(parts)


def run_case(case_name: str, output_dir: Path, config: ImageSafetyConfig, target_name: str) -> None:
    detections = CASES[case_name]
    result = evaluate_image_space_safety(target_name, detections, config)
    output_dir.mkdir(parents=True, exist_ok=True)
    svg = render_case_svg(case_name, detections, result, config)
    output_path = output_dir / f"{case_name}.svg"
    output_path.write_text(svg, encoding="utf-8")

    print(f"[{case_name}] {result['message']}")
    print(f"[{case_name}] debug image: {output_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a hardware-free image-space obstacle avoidance demo.")
    parser.add_argument("--case", choices=("blocked", "clear", "both"), default="both")
    parser.add_argument("--target", default="red_bull")
    parser.add_argument("--corridor-width", type=int, default=120)
    parser.add_argument("--output-dir", default="outputs/obstacle_avoidance")
    args = parser.parse_args()

    config = ImageSafetyConfig(corridor_width_px=args.corridor_width)
    output_dir = PROJECT_ROOT / args.output_dir
    case_names = ("blocked", "clear") if args.case == "both" else (args.case,)

    print("Demo type: image-space safety gate; no arm, no camera, no hand-eye calibration.")
    for case_name in case_names:
        run_case(case_name, output_dir, config, args.target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
