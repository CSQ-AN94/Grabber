#!/usr/bin/env python3
"""Validate every state of an exact demonstrated joint path in MoveIt."""

from __future__ import annotations

import json
import math
import sys

import rclpy
from geometry_msgs.msg import Pose
from moveit_msgs.msg import (
    AttachedCollisionObject,
    CollisionObject,
    PlanningScene,
    RobotState,
)
from moveit_msgs.srv import ApplyPlanningScene, GetStateValidity
from sensor_msgs.msg import JointState
from shape_msgs.msg import SolidPrimitive


def wait(client, timeout=20.0):
    if not client.wait_for_service(timeout_sec=timeout):
        raise RuntimeError(f"service unavailable: {client.srv_name}")


def add_box(scene, frame_id, object_id, center, size):
    collision = CollisionObject()
    collision.header.frame_id = frame_id
    collision.id = object_id
    primitive = SolidPrimitive()
    primitive.type = SolidPrimitive.BOX
    primitive.dimensions = list(map(float, size))
    pose = Pose()
    pose.position.x, pose.position.y, pose.position.z = map(float, center)
    pose.orientation.w = 1.0
    collision.primitives = [primitive]
    collision.primitive_poses = [pose]
    collision.operation = CollisionObject.ADD
    scene.world.collision_objects.append(collision)


def main():
    request_path, output_path = sys.argv[1:3]
    with open(request_path, "r", encoding="utf-8") as stream:
        data = json.load(stream)
    rclpy.init()
    node = rclpy.create_node("bottle_moveit_validate_path")
    apply_client = node.create_client(
        ApplyPlanningScene, "/apply_planning_scene"
    )
    validity_client = node.create_client(
        GetStateValidity, "/check_state_validity"
    )
    try:
        wait(apply_client)
        wait(validity_client)
        frame_id = data["planning_frame"]
        scene = PlanningScene()
        scene.is_diff = True
        for index, center in enumerate(data.get("obstacles", [])):
            add_box(
                scene,
                frame_id,
                f"rgbd_{index}",
                center,
                [data["voxel_size"]] * 3,
            )
        for item in data.get("boxes", []):
            add_box(
                scene,
                frame_id,
                str(item["id"]),
                item["center"],
                item["size"],
            )
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
        apply_request = ApplyPlanningScene.Request()
        apply_request.scene = scene
        future = apply_client.call_async(apply_request)
        rclpy.spin_until_future_complete(node, future, timeout_sec=20)
        if future.result() is None or not future.result().success:
            raise RuntimeError("failed to apply validation scene")

        right_names = [f"r_joint{i}" for i in range(1, 8)]
        left_names = [f"l_joint{i}" for i in range(1, 8)]
        left_positions = [
            math.radians(value)
            for value in data["start_left_joints_deg"]
        ]
        invalid = []
        for index, right_values in enumerate(data["points_deg"]):
            request = GetStateValidity.Request()
            request.group_name = "right_arm"
            state = RobotState()
            # 同 moveit_plan_once.py：非diff状态会把附着的工具防撞体清掉，
            # 校验时夹爪没有碰撞体积，等于没校验。
            state.is_diff = True
            state.joint_state = JointState()
            state.joint_state.name = [*left_names, *right_names]
            state.joint_state.position = [
                *left_positions,
                *[math.radians(value) for value in right_values],
            ]
            request.robot_state = state
            future = validity_client.call_async(request)
            rclpy.spin_until_future_complete(node, future, timeout_sec=5)
            response = future.result()
            if response is None:
                raise RuntimeError(f"state validity timeout at {index}")
            if not response.valid:
                invalid.append(
                    {
                        "index": index,
                        "contacts": [
                            [item.contact_body_1, item.contact_body_2]
                            for item in response.contacts[:12]
                        ],
                    }
                )
                break
        output = {
            "success": not invalid,
            "checked_states": (
                len(data["points_deg"])
                if not invalid
                else invalid[0]["index"] + 1
            ),
            "invalid": invalid,
        }
        with open(output_path, "w", encoding="utf-8") as stream:
            json.dump(output, stream, indent=2)
        return 0 if output["success"] else 2
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
