#!/usr/bin/env python3
"""判定 MoveIt 的碰撞检查是否真的在工作。

2026-07-16 现场确诊：move_group 对"目标深埋桌子内部"的规划照样瞬间成功、任意
状态 check_state_validity 恒为 valid——碰撞检查形同虚设，怀疑机器人碰撞几何
没加载。全自主大范围转移（垂下↔观察位自由规划）不修好这个绝不能用。

本脚本用两个探针给出确定结论，不依赖机械臂 SDK、不需要任何姿态先验：

  探针A（世界碰撞）：往场景里放一个把整台机器人都罩住的巨型盒子，再查一个
    普通关节状态。碰撞几何正常的话，机器人连杆必然和盒子相交 → invalid。
    若仍报 valid → 机器人碰撞几何没加载，这就是根因。
  探针B（基线）：撤掉盒子再查同一状态 → 应为 valid。

必须在 move_group 已经起来（bottle_grasp/moveit_headless.py）之后、同一个 ROS
图里运行：

  source /opt/ros/humble/setup.bash && source ~/ros2_ws/install/setup.bash
  python3 bottle_grasp/moveit_collision_selftest.py

退出码 0 = 碰撞检查工作正常（可以考虑放行 --autonomous-transit）；
退出码 2 = 碰撞检查失效（继续只用示教走廊转移）。
"""

from __future__ import annotations

import sys

import rclpy
from moveit_msgs.msg import (
    CollisionObject,
    PlanningScene,
    RobotState,
)
from moveit_msgs.srv import ApplyPlanningScene, GetStateValidity
from sensor_msgs.msg import JointState
from shape_msgs.msg import SolidPrimitive
from geometry_msgs.msg import Pose

PLANNING_FRAME = "platform_base_link"
GROUP = "right_arm"
RIGHT_JOINTS = [f"r_joint{i}" for i in range(1, 8)]
LEFT_JOINTS = [f"l_joint{i}" for i in range(1, 8)]
# 一个普通、可达的右臂查询姿态（度→稍后转弧度）；具体值不重要，探针A靠盒子
# 把整臂罩住，任何姿态都必然相交。
PROBE_RIGHT_DEG = [0.0, 90.0, 0.0, 90.0, 0.0, 0.0, 0.0]


def _wait(client, timeout=15.0):
    if not client.wait_for_service(timeout_sec=timeout):
        raise RuntimeError(f"服务不可用: {client.srv_name}")


def _probe_state(node, validity_client):
    from math import radians

    request = GetStateValidity.Request()
    request.group_name = GROUP
    state = RobotState()
    state.is_diff = True
    state.joint_state = JointState()
    state.joint_state.name = [*LEFT_JOINTS, *RIGHT_JOINTS]
    state.joint_state.position = [0.0] * 7 + [radians(v) for v in PROBE_RIGHT_DEG]
    request.robot_state = state
    future = validity_client.call_async(request)
    rclpy.spin_until_future_complete(node, future, timeout_sec=10)
    response = future.result()
    if response is None:
        raise RuntimeError("check_state_validity 超时")
    return bool(response.valid)


def _set_giant_box(node, apply_client, present: bool):
    scene = PlanningScene()
    scene.is_diff = True
    collision = CollisionObject()
    collision.header.frame_id = PLANNING_FRAME
    collision.id = "collision_selftest_box"
    if present:
        primitive = SolidPrimitive()
        primitive.type = SolidPrimitive.BOX
        primitive.dimensions = [4.0, 4.0, 4.0]  # 把整台机器人罩住
        pose = Pose()
        pose.orientation.w = 1.0
        collision.primitives = [primitive]
        collision.primitive_poses = [pose]
        collision.operation = CollisionObject.ADD
    else:
        collision.operation = CollisionObject.REMOVE
    scene.world.collision_objects.append(collision)
    request = ApplyPlanningScene.Request()
    request.scene = scene
    future = apply_client.call_async(request)
    rclpy.spin_until_future_complete(node, future, timeout_sec=15)
    if future.result() is None or not future.result().success:
        raise RuntimeError("apply_planning_scene 失败")


def main() -> int:
    rclpy.init()
    node = rclpy.create_node("moveit_collision_selftest")
    apply_client = node.create_client(ApplyPlanningScene, "/apply_planning_scene")
    validity_client = node.create_client(GetStateValidity, "/check_state_validity")
    try:
        _wait(apply_client)
        _wait(validity_client)

        baseline_valid = _probe_state(node, validity_client)
        _set_giant_box(node, apply_client, present=True)
        boxed_valid = _probe_state(node, validity_client)
        _set_giant_box(node, apply_client, present=False)
        cleared_valid = _probe_state(node, validity_client)

        print(f"探针B 基线（无盒子）: valid={baseline_valid}  期望 True")
        print(f"探针A 巨型盒子罩住整臂: valid={boxed_valid}  期望 False")
        print(f"撤盒子后恢复: valid={cleared_valid}  期望 True")

        collision_works = (not boxed_valid) and baseline_valid and cleared_valid
        if collision_works:
            print("\n结论：MoveIt 碰撞检查工作正常。")
            print("可以考虑放行全自主转移（--autonomous-transit，需另行接线）。")
            return 0
        print("\n结论：MoveIt 碰撞检查失效——巨型盒子罩住整臂仍报无碰撞，")
        print("几乎可以确定机器人碰撞几何没加载（检查 URDF collision 标签/网格）。")
        print("在修好之前，完整循环的转移段必须继续用示教走廊。")
        return 2
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
