# Grabber项目外部API使用规范与最佳实践

**版本: 1.0**
**文档目的:** 本文档旨在澄清 `RM_API2` (睿尔曼机械臂) 和 `pyorbbecsdk` (奥比中光相机) 的核心使用问题，统一项目内的开发标准，解决坐标系、单位和数据格式的混乱问题，并为后续开发提供可靠的指导。

---

## 第一部分: RM_API2 (机械臂) 使用规范

### 1.1. 核心问题：获取末端位姿 (Pose)

**问题描述:**
之前我们依赖手动正运动学（FK）解算来获取机械臂末端位姿，这不仅可能存在错误，而且与机械臂控制器的内置模型不一致，导致笛卡尔空间运动不可靠。

**解决方案：废除手动解算，使用原生API**

`RM_API2` 提供了直接从控制器获取当前状态的权威接口。我们**必须**使用此接口作为获取末端位姿的唯一真实来源。

- **关键函数:** `rm_get_current_arm_state()`
- **返回值:** 该函数返回一个包含丰富状态的字典，其中 `pose` 字段就是我们需要的末端位姿。

**优化点 (`arm_controller.py`):**
我们现有的 `get_base_to_end_pose_matrix()` 方法已经在使用此函数，但���内部实现存在单位转换硬编码和不清晰的问题。我们将对其进行优化。

**分析 `rm_get_current_arm_state()` 的 `pose` 输出:**
通过分析 `rm_robot_interface.py` 中 `rm_current_arm_state_t` 的结构，我们确认其 `pose` 字段是一个包含6个元素的数组，其单位为：
- **位置 (前3个元素):** `0.001mm` (0.001毫米)
- **姿态 (后3个元素, 欧拉角):** `0.001rad` (0.001弧度)

### 1.2. 标准：统一项目单位

**问题描述:**
API的输入输出单位（度/弧度，米/毫米）与我们项目内部（期望使用SI单位：米、弧度）以及其他库（如OpenCV）的需求不一致，导致代码中散落着各种转换，难以维护。

**解决方案：建立“接口隔离层”原则**

所有单位转换**必须**在 `arm_controller.py` 的函数边界处完成。该控制器对项目其他部分暴露的接口，其单位**必须**是标准SI单位。

#### **RM_API2 单位速查表**

| 函数 (部分) | 参数 | API要求单位 | 项目内部单位 (SI) | `arm_controller` 职责 |
| :--- | :--- | :--- | :--- | :--- |
| `rm_movej` | `joint_angles` | **度 (degree)** | 弧度 (rad) | 内部将弧度转为度 |
| `rm_movej_p` | `pose` | **米 (m), 弧度 (rad)** | 米 (m), 弧度 (rad) | **直接使用** |
| `rm_get_joint_degree` | `return` | **度 (degree)** | 弧度 (rad) | 将返回的度转为弧度 |
| `rm_get_current_arm_state` | `pose` (位置) | **0.001 毫米** | 米 (m) | `val / 1000000.0` |
| `rm_get_current_arm_state` | `pose` (姿态) | **0.001 弧度** | 弧度 (rad) | `val / 1000.0` |

### 1.3. 优化与重构建议 (`arm_controller.py`)

#### **`get_base_to_end_pose_matrix()` 重构**

这是解决坐标系问题的核心。

```python
# 建议在 arm_controller.py 中重构

def get_base_to_end_pose_matrix(self) -> Optional[np.ndarray]:
    """
    获取机械臂末端在基坐标系下的4x4位姿矩阵。
    该方法是获取真实世界位姿的唯一可信来源。
    
    Returns:
        np.ndarray: 4x4的齐次变换矩阵 (T_base_to_end)。
                    位置单位为米(m)，姿态为旋转矩阵。
                    如果获取失败，返回 None。
    """
    with self.lock:
        ret_code, state_dict = self.arm.rm_get_current_arm_state()
        if ret_code != 0:
            print(f"获取机械臂状态失败，错误码: {ret_code}")
            return None
        
        pose_raw = state_dict.get('pose')
        if pose_raw is None:
            print("无法从机械臂状态中获取末端位姿'pose'")
            return None
            
        # --- 单位转换层 (清晰、明确) ---
        # 原始单位: 0.001mm -> 目标单位: m
        x_m = pose_raw[0] / 1000000.0
        y_m = pose_raw[1] / 1000000.0
        z_m = pose_raw[2] / 1000000.0
        
        # 原始单位: 0.001rad -> 目标单位: rad
        rx_rad = pose_raw[3] / 1000.0
        ry_rad = pose_raw[4] / 1000.0
        rz_rad = pose_raw[5] / 1000.0
        
        # --- 矩阵构造 ---
        T = np.eye(4)
        try:
            # 使用scipy将欧拉角转换为旋转矩阵
            rotation_matrix = Rotation.from_euler('xyz', [rx_rad, ry_rad, rz_rad], degrees=False).as_matrix()
            T[:3, :3] = rotation_matrix
            T[:3, 3] = [x_m, y_m, z_m]
            return T
        except Exception as e:
            print(f"从欧拉角构造位姿矩阵失败: {e}")
            return None
```

#### **其他函数单位澄清**

- **`get_current_joint_angles()`:** 当前实现是正确的，它明确将API返回的**度**转换为**弧度**。应保留并添加清晰注释。
- **`move_to_joints()`:** 当前实现接收的是**度**。应修改为接收**弧度**，在函数内部转换为度再调用API，以符合接口隔离原则。
- **`move_to_cartesian_pose()`:** `rm_movej_p` 的文档明确指出其单位是**米**和**弧度**。我们当前的实现传递的是毫米和度，这是**错误**的，必须修正。

---

## 第二部分: pyorbbecsdk (相机) 使用规范

### 2.1. 核心问题：图像格式 (RGB vs BGR)

**问题描述:**
相机SDK、OpenCV和YOLO模型对图像通道顺序（RGB/BGR）有不同要求，导致混乱。

**解决方案：确立项目唯一的图像标准：BGR**

- **事实:** `pyorbbecsdk` 的 `frame_to_bgr_image` 辅助函数，无论从相机接收到的是 `OBFormat.RGB` 还是 `OBFormat.BGR`，最终都会统一输出 **BGR** 格式的 `numpy` 数组。这是因为 `cv2.imshow` 和大多数OpenCV操作都默认使用BGR。
- **分析:** 我们在 `camera_thread.py` 中已经使用了 `frame_to_bgr_image`。这意味着，`camera_thread` 已经为整个项目提供了一个统一的、**BGR格式**的图像源。
- **项目规范:**
    1. `camera_thread.py` 是唯一需要关心相机原始格式的地方。
    2. `camera_thread.py` 对外提供的图像 (`shared_state.update_frames`) **必须**是 BGR 格式。
    3. 项目中所有其他模块（如 `vision.py`）在处理图像时，都**必须**假设输入是 BGR 格式。如果需要（例如，YOLOv8推理时），则在函数内部自行完成 `BGR -> RGB` 的转换。

### 2.2. 核心问题：深度数据单位

**问题描述:**
深度图的原始数据是 `uint16`，需要转换为有物理意义的单位。

**解决方案：确认并固化转换流程**

- **事实:** `depth.py` 和 `hw_d2c_align.py` 示例都展示了标准转换流程。
- **流程:**
    1. 从 `depth_frame` 获取原始 `uint16` 数据。
    2. 获取 `depth_frame.get_depth_scale()`，这是一个缩放因子。
    3. 最终深度（毫米） = `depth_data.astype(np.float32) * scale`。
    4. 最终深度（米） = `(depth_data.astype(np.float32) * scale) / 1000.0`。
- **分析:** 我们在 `camera_thread.py` 中的实现完全正确，最终输出的是以**米**为单位的深度图。
- **项目规范:** `camera_thread.py` 对外提供的深度图 (`shared_state.update_frames`) **必须**是以**米 (m)** 为单位的 `float32` `numpy` 数组。

### 2.3. 优化与高级功能

#### **硬件对齐 (Hardware D2C)**
我们当前在 `camera_thread.py` 中使用的 `OBAlignMode.HW_MODE` 是**最佳选择**。它利用相机内置硬件处理深度图到彩色图的对齐，相比软件对齐（`SW_MODE`），极大地降低了CPU负载，并减少了延迟。应继续保持此配置。

#### **坐标变换 (`transformation` 模块)**
`coordinate_transform.py` 示例展示了SDK内置的坐标变换函数。但对于我们的手眼标定场景，这些函数过于底层。我们的 `utils/calibration.py` 中 `transform_pixel_to_world` 的实现思路是正确的：
1.  使用相机内参将 `(u, v)` 像��坐标和深度值 `Z` 反投影为相机坐标系下的 `(X, Y, Z)` 点。
2.  使用 `T_base_to_end` (来自机械臂API) 和 `T_end_to_camera` (来自手眼标定) 将相机坐标系下的点变换到世界坐标系。

这个流程是正确的，只要我们确保输入给它的 `T_base_to_end` 是通过 `rm_get_current_arm_state()` 获得的准确位姿，整个坐标变换链条就是可靠的。

---

## 总结与行动项

1.  **[首要任务] 修正 `arm_controller.py`:**
    -   **重构 `get_base_to_end_pose_matrix`**，明确内部的单位转换，并添加详细注释，使其成为获取位姿的唯一可信来源。
    -   **修正 `move_to_cartesian_pose`**，确保传递给 `rm_movej_p` 的单位是**米**和**弧度**。
    -   **修改 `move_to_joints`**，使其接收**弧度**，在内部转换为度。

2.  **[规范] 统一代码注释:**
    -   在 `arm_controller.py` 和 `camera_thread.py` 的所有对外接口函数中，使用docstring明确标注输入/输出的**单位**和**格式**。例如 `(BGR, np.ndarray)` 或 `(radians, list[float])`。

3.  **[确认] `vision.py`:**
    -   确认YOLOv8的推理代码，确保在需要时进行了 `cv2.cvtColor(image, cv2.COLOR_BGR2RGB)` 的转换。