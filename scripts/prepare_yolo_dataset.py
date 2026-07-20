#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把人工打框标注好的原始图片整理成 ultralytics 训练要的目录结构。

输入：`intelligence/data/raw/<label>/*.jpg` + LabelImg（或 CVAT 导出成
YOLO 格式）产出的同名 `.txt` 标注，每个 `<label>` 子目录就是一个类别。

输出：`images/{train,val}/`、`labels/{train,val}/`（复制，不移动，原始
采集数据保持不动）+ `data.yaml`（ultralytics `YOLO(...).train(data=...)`
直接吃这个文件）。

校验规则跟这个仓库其它地方一致：缺标注的图片列出来直接报错拒绝整理，
不静默跳过——训练集里悄悄漏掉一部分数据比明确报错更难发现。
"""

from __future__ import annotations

import argparse
import random
import shutil
from dataclasses import dataclass
from pathlib import Path

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png")


class DatasetPreparationError(RuntimeError):
    """Raised when the raw data directory is not ready to be assembled."""


@dataclass(frozen=True)
class ClassImages:
    label: str
    pairs: tuple[tuple[Path, Path], ...]  # (image_path, label_txt_path)


def discover_classes(raw_root: Path) -> list[str]:
    """Class names = subdirectory names of raw_root, sorted for a
    reproducible class_id assignment."""
    if not raw_root.is_dir():
        raise DatasetPreparationError(f"原始数据目录不存在: {raw_root}")
    classes = sorted(
        entry.name for entry in raw_root.iterdir() if entry.is_dir()
    )
    if not classes:
        raise DatasetPreparationError(f"{raw_root} 下没有任何类别子目录")
    return classes


def collect_class_images(class_dir: Path) -> ClassImages:
    """Pair every image in class_dir with its same-stem .txt label.

    Raises if any image is missing its label — a dataset with silently
    unlabeled images would train on nothing for those samples without any
    visible sign something is wrong.
    """
    images = sorted(
        p for p in class_dir.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES
    )
    if not images:
        raise DatasetPreparationError(f"{class_dir} 下没有任何图片")
    missing = [p for p in images if not p.with_suffix(".txt").exists()]
    if missing:
        names = ", ".join(p.name for p in missing[:10])
        more = f" 等共 {len(missing)} 张" if len(missing) > 10 else ""
        raise DatasetPreparationError(
            f"{class_dir} 下有图片缺少标注文件: {names}{more}——"
            "先在 LabelImg/CVAT 里补完标注再重新整理"
        )
    pairs = tuple((image, image.with_suffix(".txt")) for image in images)
    return ClassImages(label=class_dir.name, pairs=pairs)


def split_train_val(
    pairs: tuple[tuple[Path, Path], ...],
    *,
    val_fraction: float,
    rng: random.Random,
) -> tuple[list[tuple[Path, Path]], list[tuple[Path, Path]]]:
    """Stratified split for one class: shuffle, then cut by val_fraction.

    Splitting per class (not across the whole pooled dataset) guarantees
    every class appears in both train and val even with an uneven class
    count — pooling first and cutting once could starve a small class of
    validation examples entirely.
    """
    if not 0.0 < val_fraction < 1.0:
        raise DatasetPreparationError("val_fraction 必须在 (0, 1) 之间")
    shuffled = list(pairs)
    rng.shuffle(shuffled)
    val_count = max(1, round(len(shuffled) * val_fraction))
    val_count = min(val_count, len(shuffled) - 1) if len(shuffled) > 1 else 0
    return shuffled[val_count:], shuffled[:val_count]


@dataclass(frozen=True)
class DatasetSummary:
    classes: tuple[str, ...]
    train_counts: dict
    val_counts: dict
    data_yaml_path: Path


MIN_RECOMMENDED_IMAGES = 150


def build_dataset(
    raw_root: Path,
    output_root: Path,
    *,
    val_fraction: float = 0.15,
    seed: int = 0,
) -> DatasetSummary:
    classes = discover_classes(raw_root)
    rng = random.Random(seed)

    images_train = output_root / "images" / "train"
    images_val = output_root / "images" / "val"
    labels_train = output_root / "labels" / "train"
    labels_val = output_root / "labels" / "val"
    for directory in (images_train, images_val, labels_train, labels_val):
        directory.mkdir(parents=True, exist_ok=True)

    train_counts: dict = {}
    val_counts: dict = {}
    for label in classes:
        class_images = collect_class_images(raw_root / label)
        train_pairs, val_pairs = split_train_val(
            class_images.pairs, val_fraction=val_fraction, rng=rng
        )
        for image_path, label_path in train_pairs:
            shutil.copy2(image_path, images_train / image_path.name)
            shutil.copy2(label_path, labels_train / label_path.name)
        for image_path, label_path in val_pairs:
            shutil.copy2(image_path, images_val / image_path.name)
            shutil.copy2(label_path, labels_val / label_path.name)
        train_counts[label] = len(train_pairs)
        val_counts[label] = len(val_pairs)

    data_yaml_path = write_data_yaml(output_root, classes)
    return DatasetSummary(
        classes=tuple(classes),
        train_counts=train_counts,
        val_counts=val_counts,
        data_yaml_path=data_yaml_path,
    )


def write_data_yaml(output_root: Path, classes: list[str]) -> Path:
    import yaml

    payload = {
        "path": str(output_root.resolve()),
        "train": "images/train",
        "val": "images/val",
        "names": {index: name for index, name in enumerate(classes)},
    }
    path = output_root / "data.yaml"
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", default="intelligence/data/raw")
    parser.add_argument(
        "--output-root", default="intelligence/data/product_yolo"
    )
    parser.add_argument("--val-fraction", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    try:
        summary = build_dataset(
            Path(args.raw_root),
            Path(args.output_root),
            val_fraction=args.val_fraction,
            seed=args.seed,
        )
    except DatasetPreparationError as exc:
        print(f"错误: {exc}")
        return 1

    print(f"类别（class_id 顺序）: {list(summary.classes)}")
    for label in summary.classes:
        train_n = summary.train_counts[label]
        val_n = summary.val_counts[label]
        total = train_n + val_n
        warn = (
            f"  ⚠ 建议至少 {MIN_RECOMMENDED_IMAGES} 张，当前偏少"
            if total < MIN_RECOMMENDED_IMAGES
            else ""
        )
        print(f"  {label}: train={train_n} val={val_n} total={total}{warn}")
    print(f"data.yaml 已写入: {summary.data_yaml_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
