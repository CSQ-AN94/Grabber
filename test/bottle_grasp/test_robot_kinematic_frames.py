"""Regression tests for RealMan SDK tool-frame semantics."""

from types import SimpleNamespace

import numpy as np

from bottle_grasp.core import DemoParams
from bottle_grasp.robot import RobotSession


class _Algo:
    def rm_algo_forward_kinematics(self, _joints, _flag):
        return [0.0] * 6

    def rm_algo_inverse_kinematics(self, _params):
        return 0, [0.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0]

    def rm_algo_set_joint_min_limit(self, _limits):
        return None

    def rm_algo_set_joint_max_limit(self, _limits):
        return None


class _Arm:
    def rm_get_joint_min_pos(self):
        return 0, [-180.0] * 7

    def rm_get_joint_max_pos(self):
        return 0, [180.0] * 7


def _session():
    session = RobotSession.__new__(RobotSession)
    session.tcp_z_m = 0.151
    session.model_flange_offset_m = 0.0172
    session.algo = _Algo()
    session.arm = _Arm()
    session.joints_deg = lambda: [0.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0]
    session.ik_params = lambda *args: args
    session._tool_offsets = []
    session._set_algo_tool_z = session._tool_offsets.append
    return session


def test_sdk_fk_uses_zero_tool_for_controller_flange_and_tcp_only_for_tcp():
    session = _session()

    session.controller_flange_from_joints([0.0] * 7)
    session.tcp_from_joints([0.0] * 7)

    assert session._tool_offsets == [0.0, session.tcp_z_m]


def test_sdk_ik_does_not_add_moveit_link7_offset_to_flange_or_tcp_targets():
    session = _session()

    session.solve_flange_ik(np.eye(4), DemoParams())
    session.plan_ik([[0.0] * 6], DemoParams())

    assert session._tool_offsets == [0.0, session.tcp_z_m]
