#!/usr/bin/env python3
"""Apply voxel obstacles and request one collision-aware RM75 plan."""

from __future__ import annotations

import json
import math
import sys

import rclpy
from geometry_msgs.msg import Pose
from moveit_msgs.msg import (
    AttachedCollisionObject,
    CollisionObject,
    Constraints,
    JointConstraint,
    OrientationConstraint,
    PlanningScene,
    PositionConstraint,
    RobotState,
)
from moveit_msgs.srv import ApplyPlanningScene, GetMotionPlan
from sensor_msgs.msg import JointState
from shape_msgs.msg import SolidPrimitive


def quaternion_from_matrix(matrix):
    trace = matrix[0][0] + matrix[1][1] + matrix[2][2]
    if trace > 0:
        scale = math.sqrt(trace + 1.0) * 2
        return [
            (matrix[2][1] - matrix[1][2]) / scale,
            (matrix[0][2] - matrix[2][0]) / scale,
            (matrix[1][0] - matrix[0][1]) / scale,
            0.25 * scale,
        ]
    index = max(range(3), key=lambda i: matrix[i][i])
    if index == 0:
        scale = math.sqrt(1 + matrix[0][0] - matrix[1][1] - matrix[2][2]) * 2
        return [
            0.25 * scale,
            (matrix[0][1] + matrix[1][0]) / scale,
            (matrix[0][2] + matrix[2][0]) / scale,
            (matrix[2][1] - matrix[1][2]) / scale,
        ]
    if index == 1:
        scale = math.sqrt(1 + matrix[1][1] - matrix[0][0] - matrix[2][2]) * 2
        return [
            (matrix[0][1] + matrix[1][0]) / scale,
            0.25 * scale,
            (matrix[1][2] + matrix[2][1]) / scale,
            (matrix[0][2] - matrix[2][0]) / scale,
        ]
    scale = math.sqrt(1 + matrix[2][2] - matrix[0][0] - matrix[1][1]) * 2
    return [
        (matrix[0][2] + matrix[2][0]) / scale,
        (matrix[1][2] + matrix[2][1]) / scale,
        0.25 * scale,
        (matrix[1][0] - matrix[0][1]) / scale,
    ]


def wait(client, timeout=20.0):
    if not client.wait_for_service(timeout_sec=timeout):
        raise RuntimeError(f"service unavailable: {client.srv_name}")


def main():
    request_path, output_path = sys.argv[1:3]
    with open(request_path, "r", encoding="utf-8") as stream:
        data = json.load(stream)
    rclpy.init()
    node = rclpy.create_node("bottle_moveit_plan_once")
    apply_client = node.create_client(ApplyPlanningScene, "/apply_planning_scene")
    plan_client = node.create_client(GetMotionPlan, "/plan_kinematic_path")
    try:
        wait(apply_client)
        wait(plan_client)
        scene_request = ApplyPlanningScene.Request()
        scene = PlanningScene()
        scene.is_diff = True
        planning_frame = data["planning_frame"]
        for object_id in data.get("clear_ids", []):
            collision = CollisionObject()
            collision.header.frame_id = planning_frame
            collision.id = object_id
            collision.operation = CollisionObject.REMOVE
            scene.world.collision_objects.append(collision)
        for index, center in enumerate(data.get("obstacles", [])):
            collision = CollisionObject()
            collision.header.frame_id = planning_frame
            collision.id = f"rgbd_{index}"
            primitive = SolidPrimitive()
            primitive.type = SolidPrimitive.BOX
            primitive.dimensions = [data["voxel_size"]] * 3
            pose = Pose()
            pose.position.x, pose.position.y, pose.position.z = center
            pose.orientation.w = 1.0
            collision.primitives = [primitive]
            collision.primitive_poses = [pose]
            collision.operation = CollisionObject.ADD
            scene.world.collision_objects.append(collision)
        for item in data.get("boxes", []):
            collision = CollisionObject()
            collision.header.frame_id = planning_frame
            collision.id = str(item["id"])
            primitive = SolidPrimitive()
            primitive.type = SolidPrimitive.BOX
            primitive.dimensions = list(map(float, item["size"]))
            pose = Pose()
            pose.position.x, pose.position.y, pose.position.z = map(
                float, item["center"]
            )
            pose.orientation.w = 1.0
            collision.primitives = [primitive]
            collision.primitive_poses = [pose]
            collision.operation = CollisionObject.ADD
            scene.world.collision_objects.append(collision)
        guard = data.get("tool_guard")
        if guard:
            attached = AttachedCollisionObject()
            attached.link_name = "r_link7"
            attached.touch_links = ["r_link6", "r_link7", "r_hand"]
            attached.object.header.frame_id = "r_link7"
            attached.object.id = "bottle_tool_guard"
            primitive = SolidPrimitive()
            primitive.type = SolidPrimitive.BOX
            primitive.dimensions = [
                float(guard["xy"]),
                float(guard["xy"]),
                float(guard["length"]),
            ]
            pose = Pose()
            pose.position.z = float(guard["center_z"])
            pose.orientation.w = 1.0
            attached.object.primitives = [primitive]
            attached.object.primitive_poses = [pose]
            attached.object.operation = CollisionObject.ADD
            scene.robot_state.is_diff = True
            scene.robot_state.attached_collision_objects = [attached]
        scene_request.scene = scene
        future = apply_client.call_async(scene_request)
        rclpy.spin_until_future_complete(node, future, timeout_sec=20)
        if future.result() is None or not future.result().success:
            raise RuntimeError("failed to apply planning scene")

        request = GetMotionPlan.Request()
        motion = request.motion_plan_request
        motion.group_name = "right_arm"
        motion.num_planning_attempts = 8
        motion.allowed_planning_time = 8.0
        motion.max_velocity_scaling_factor = 0.08
        motion.max_acceleration_scaling_factor = 0.08
        motion.workspace_parameters.header.frame_id = planning_frame
        workspace = data["workspace"]
        (
            motion.workspace_parameters.min_corner.x,
            motion.workspace_parameters.min_corner.y,
            motion.workspace_parameters.min_corner.z,
        ) = map(float, workspace["min"])
        (
            motion.workspace_parameters.max_corner.x,
            motion.workspace_parameters.max_corner.y,
            motion.workspace_parameters.max_corner.z,
        ) = map(float, workspace["max"])
        state = RobotState()
        # 关键：必须是diff状态。非diff的start_state会整体替换场景里的机器人
        # 状态，把上面刚附着的bottle_tool_guard防撞体清掉，规划时夹爪等于
        # 没有碰撞体积——2026-07-16实测规划出TCP距桌面2.7cm的擦桌路径。
        state.is_diff = True
        state.joint_state = JointState()
        right_names = [f"r_joint{i}" for i in range(1, 8)]
        right_positions = [
            math.radians(value) for value in data["start_joints_deg"]
        ]
        left_values = data.get("start_left_joints_deg")
        if left_values is None:
            state.joint_state.name = right_names
            state.joint_state.position = right_positions
        else:
            state.joint_state.name = [
                *[f"l_joint{i}" for i in range(1, 8)],
                *right_names,
            ]
            state.joint_state.position = [
                *[math.radians(value) for value in left_values],
                *right_positions,
            ]
        motion.start_state = state

        constraint = Constraints()
        goal_joints = data.get("goal_joints_deg")
        if goal_joints is not None:
            for name, value in zip(right_names, goal_joints):
                joint_constraint = JointConstraint()
                joint_constraint.joint_name = name
                joint_constraint.position = math.radians(value)
                joint_constraint.tolerance_above = math.radians(0.2)
                joint_constraint.tolerance_below = math.radians(0.2)
                joint_constraint.weight = 1.0
                constraint.joint_constraints.append(joint_constraint)
        else:
            target = data["target_flange"]
            rotation = target[:3]
            position = [row[3] for row in target[:3]]
            quaternion = quaternion_from_matrix(rotation)
            position_constraint = PositionConstraint()
            position_constraint.header.frame_id = planning_frame
            position_constraint.link_name = "r_link7"
            box = SolidPrimitive()
            box.type = SolidPrimitive.BOX
            box.dimensions = [0.008, 0.008, 0.008]
            region_pose = Pose()
            (
                region_pose.position.x,
                region_pose.position.y,
                region_pose.position.z,
            ) = position
            region_pose.orientation.w = 1.0
            position_constraint.constraint_region.primitives = [box]
            position_constraint.constraint_region.primitive_poses = [region_pose]
            position_constraint.weight = 1.0
            orientation_constraint = OrientationConstraint()
            orientation_constraint.header.frame_id = planning_frame
            orientation_constraint.link_name = "r_link7"
            (
                orientation_constraint.orientation.x,
                orientation_constraint.orientation.y,
                orientation_constraint.orientation.z,
                orientation_constraint.orientation.w,
            ) = quaternion
            orientation_constraint.absolute_x_axis_tolerance = 0.035
            orientation_constraint.absolute_y_axis_tolerance = 0.035
            orientation_constraint.absolute_z_axis_tolerance = 0.035
            orientation_constraint.weight = 1.0
            constraint.position_constraints = [position_constraint]
            constraint.orientation_constraints = [orientation_constraint]
        motion.goal_constraints = [constraint]

        future = plan_client.call_async(request)
        rclpy.spin_until_future_complete(node, future, timeout_sec=20)
        response = future.result()
        if response is None:
            raise RuntimeError("MoveIt planning service timed out")
        result = response.motion_plan_response
        error_code = int(result.error_code.val)
        trajectory = result.trajectory.joint_trajectory
        output = {
            "success": error_code == 1 and bool(trajectory.points),
            "error_code": error_code,
            "planning_time": float(result.planning_time),
            "joint_names": list(trajectory.joint_names),
            "points_deg": [
                [math.degrees(value) for value in point.positions]
                for point in trajectory.points
            ],
        }
        with open(output_path, "w", encoding="utf-8") as stream:
            json.dump(output, stream, indent=2)
        return 0 if output["success"] else 2
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
