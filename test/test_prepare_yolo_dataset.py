"""prepare_yolo_dataset.py's pure-Python assembly logic (no hardware, no
ultralytics/yaml training deps beyond PyYAML for data.yaml).

Covers the parts that are safe to get wrong silently: missing labels must
be refused rather than dropped, every class must appear in both train and
val even when small, and class_id order in data.yaml must be deterministic.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import prepare_yolo_dataset as dataset_mod  # noqa: E402


def _make_class(raw_root: Path, label: str, count: int, *, with_labels=True):
    class_dir = raw_root / label
    class_dir.mkdir(parents=True)
    for index in range(count):
        image = class_dir / f"{label}_{index:03d}.jpg"
        image.write_bytes(b"fake-jpeg")
        if with_labels:
            (class_dir / f"{label}_{index:03d}.txt").write_text("0 0.5 0.5 0.2 0.2\n")
    return class_dir


def test_discover_classes_sorted_and_rejects_empty(tmp_path):
    raw_root = tmp_path / "raw"
    _make_class(raw_root, "sprite_bottle", 3)
    _make_class(raw_root, "coke_bottle", 3)
    assert dataset_mod.discover_classes(raw_root) == ["coke_bottle", "sprite_bottle"]


def test_discover_classes_missing_root_raises():
    with pytest.raises(dataset_mod.DatasetPreparationError, match="不存在"):
        dataset_mod.discover_classes(Path("/nonexistent/raw/root"))


def test_collect_class_images_rejects_missing_labels(tmp_path):
    raw_root = tmp_path / "raw"
    class_dir = _make_class(raw_root, "coke_bottle", 3, with_labels=True)
    # Remove one label to simulate an unfinished annotation pass.
    (class_dir / "coke_bottle_001.txt").unlink()
    with pytest.raises(dataset_mod.DatasetPreparationError, match="缺少标注"):
        dataset_mod.collect_class_images(class_dir)


def test_collect_class_images_rejects_empty_directory(tmp_path):
    class_dir = tmp_path / "raw" / "empty_label"
    class_dir.mkdir(parents=True)
    with pytest.raises(dataset_mod.DatasetPreparationError, match="没有任何图片"):
        dataset_mod.collect_class_images(class_dir)


def test_split_train_val_keeps_every_class_in_both_splits():
    import random

    pairs = tuple((Path(f"{i}.jpg"), Path(f"{i}.txt")) for i in range(5))
    train, val = dataset_mod.split_train_val(
        pairs, val_fraction=0.15, rng=random.Random(0)
    )
    assert len(val) >= 1
    assert len(train) >= 1
    assert len(train) + len(val) == 5


def test_split_train_val_rejects_invalid_fraction():
    import random

    pairs = tuple((Path(f"{i}.jpg"), Path(f"{i}.txt")) for i in range(3))
    with pytest.raises(dataset_mod.DatasetPreparationError, match="val_fraction"):
        dataset_mod.split_train_val(pairs, val_fraction=1.5, rng=random.Random(0))


def test_build_dataset_end_to_end(tmp_path):
    raw_root = tmp_path / "raw"
    _make_class(raw_root, "coke_bottle", 10)
    _make_class(raw_root, "sprite_bottle", 10)
    output_root = tmp_path / "product_yolo"

    summary = dataset_mod.build_dataset(
        raw_root, output_root, val_fraction=0.2, seed=1
    )

    assert summary.classes == ("coke_bottle", "sprite_bottle")
    for label in summary.classes:
        assert summary.train_counts[label] + summary.val_counts[label] == 10
        assert summary.val_counts[label] >= 1
    assert len(list((output_root / "images" / "train").glob("*.jpg"))) == sum(
        summary.train_counts.values()
    )
    assert len(list((output_root / "images" / "val").glob("*.jpg"))) == sum(
        summary.val_counts.values()
    )
    # Every copied image has a matching label file alongside it.
    for split in ("train", "val"):
        images = {p.stem for p in (output_root / "images" / split).glob("*.jpg")}
        labels = {p.stem for p in (output_root / "labels" / split).glob("*.txt")}
        assert images == labels


def test_build_dataset_raises_on_missing_label_before_copying_anything(tmp_path):
    raw_root = tmp_path / "raw"
    class_dir = _make_class(raw_root, "coke_bottle", 5)
    (class_dir / "coke_bottle_000.txt").unlink()
    output_root = tmp_path / "product_yolo"

    with pytest.raises(dataset_mod.DatasetPreparationError):
        dataset_mod.build_dataset(raw_root, output_root)

    # Nothing should have been copied for a dataset that failed validation.
    assert not any((output_root / "images" / "train").glob("*.jpg"))


def test_data_yaml_has_deterministic_class_ids(tmp_path):
    output_root = tmp_path / "product_yolo"
    output_root.mkdir(parents=True)
    path = dataset_mod.write_data_yaml(output_root, ["coke_bottle", "sprite_bottle"])

    import yaml

    payload = yaml.safe_load(path.read_text())
    assert payload["names"] == {0: "coke_bottle", 1: "sprite_bottle"}
    assert payload["train"] == "images/train"
    assert payload["val"] == "images/val"
