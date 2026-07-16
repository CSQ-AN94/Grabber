# 双臂三相机手眼标定结果

标定日期：2026-07-15

本包用于共享同一台双臂机器人已经完成的手眼标定结果。只要相机、机械臂和相机支架没有拆装或发生相对位移，使用者无需重复标定。

## 文件

- `handeye_calibration.json`：四套手眼外参、两套双臂基座变换、相机序列号和质量指标。
- `handeye_transform.py`：独立的坐标转换辅助函数。
- `verify_calibration.py`：检查矩阵合法性和左右基座正反变换闭环。

## 坐标约定

所有距离单位均为米。

`T_A_to_B` 表示把坐标系 B 中的点变换到坐标系 A：

```text
p_A = T_A_to_B @ p_B
```

三维点需扩展为齐次坐标 `[x, y, z, 1]`。

## 硬件对应关系

- 头部 RealSense D435：`153122071777`
- 右腕 RealSense D435：`405622073249`
- 左腕 RealSense D435：`335522072194`
- 右臂：`169.254.128.19:8080`
- 左臂：`169.254.128.18:8080`

头部相机外参只有在头部舵机处于以下标定位置时有效：

```text
angle1 = 398
angle2 = 516
```

## Python 使用示例

依赖：

```bash
pip install numpy
```

头部相机三维点转换到右臂基座：

```python
import numpy as np

from handeye_transform import (
    camera_to_arm_base,
    load_calibration,
    transform_point,
)

calibration = load_calibration("handeye_calibration.json")
T_base_right_to_camera_head = camera_to_arm_base(
    calibration,
    camera="head",
    target_arm="right",
)

p_camera = np.array([0.10, 0.02, 0.50])
p_base_right = transform_point(T_base_right_to_camera_head, p_camera)
print(p_base_right)
```

右腕相机三维点转换到右臂基座：

```python
T_base_right_to_end_right = ...  # 从机器人实时读取的 4×4 末端位姿

T_base_right_to_camera_rightwrist = camera_to_arm_base(
    calibration,
    camera="right_wrist",
    target_arm="right",
    T_base_to_end=T_base_right_to_end_right,
)

p_base_right = transform_point(
    T_base_right_to_camera_rightwrist,
    p_camera,
)
```

右腕相机三维点也可以直接转换给左臂：

```python
T_base_left_to_camera_rightwrist = camera_to_arm_base(
    calibration,
    camera="right_wrist",
    target_arm="left",
    T_base_to_end=T_base_right_to_end_right,
)
```

## 运行自检

```bash
python verify_calibration.py
```

看到 `Calibration verification passed.` 表示文件内容和矩阵闭环正常。

## 精度说明

- 头部相机 → 右臂基座：良好，平移一致性最大误差 9.3 mm，旋转最大误差 1.09°。
- 头部相机 → 左臂基座：中等，平移一致性最大误差 12.8 mm，旋转最大误差 1.09°。
- 右腕相机 → 右臂末端：中等，平移一致性最大误差 22.8 mm，旋转最大误差 2.84°。
- 左腕相机 → 左臂末端：中等，平移一致性最大误差 19.6 mm，旋转最大误差 3.44°。

腕部结果应按厘米级误差设计安全余量，并使用 RGB-D 闭环修正，不应按毫米级精度使用。

