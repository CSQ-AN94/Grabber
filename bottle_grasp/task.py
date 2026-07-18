"""The two supported real-robot bottle pick/place workflows.

The public task interface is deliberately smaller than the legacy demo CLI:
one operation, two valid starting conditions, and one shared grasp/place tail.
Historical run artefacts are evidence only; neither workflow resumes from
saved localizations or trajectories.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np

from .core import SafetyAbort
from .environment_guard import LeftArmStabilityGuard


class StartMode(str, Enum):
    """The only two supported task entry conditions."""

    FROM_OBSERVATION = "from-observation"
    FROM_START = "from-start"


class TaskPhase(str, Enum):
    START = "start"
    PREFLIGHT = "preflight"
    HEAD_LOCK = "head_lock"
    SCENE_SYNC = "scene_sync"
    MOVE_TO_OBSERVATION = "move_to_observation"
    WRIST_LOCK = "wrist_lock"
    GRASP_AND_LIFT = "grasp_and_lift"
    GRASP_VERIFIED = "grasp_verified"
    PLACE_AND_RETREAT = "place_and_retreat"
    RELEASE_VERIFIED = "release_verified"
    RETURN_HOME = "return_home"
    DONE = "done"
    ABORTED = "aborted"


class ObjectState(str, Enum):
    EMPTY = "empty"
    UNKNOWN = "unknown"
    HELD = "held"


class RunStatus(str, Enum):
    RUNNING = "running"
    DONE = "done"
    SAFE_ABORT = "safe_abort"
    FAULT = "fault"


@dataclass(frozen=True)
class RunResult:
    run_id: str
    mode: str
    status: str
    phase: str
    object_state: str
    evidence_dir: str
    error: str | None = None


class BottlePickPlaceTask:
    """Run one fresh, bounded pick/place transaction.

    ``demo`` is the hardware composition root.  This module owns legal task
    ordering and object-state semantics; camera, robot and planner details stay
    behind the existing adapters used by ``BottleDemo``.
    """

    def __init__(self, demo: Any):
        self.demo = demo
        self.run_id = str(uuid4())
        self.phase = TaskPhase.START
        self.object_state = ObjectState.EMPTY
        self.status = RunStatus.RUNNING
        self.error: str | None = None
        self._sequence = 0

    @property
    def _run_dir(self) -> Path:
        return Path(self.demo.run_dir)

    def _snapshot(self) -> RunResult:
        return RunResult(
            run_id=self.run_id,
            mode=str(self.demo.args.task_mode),
            status=self.status.value,
            phase=self.phase.value,
            object_state=self.object_state.value,
            evidence_dir=str(self._run_dir),
            error=self.error,
        )

    def _write_json_atomic(self, name: str, payload: dict) -> None:
        path = self._run_dir / name
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(temporary, path)

    def _record(self, phase: TaskPhase, message: str) -> None:
        self.phase = phase
        self._sequence += 1
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sequence": self._sequence,
            "run_id": self.run_id,
            "mode": str(self.demo.args.task_mode),
            "phase": phase.value,
            "object_state": self.object_state.value,
            "message": message,
        }
        journal = self._run_dir / "task_journal.jsonl"
        with journal.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        self.demo.stage(f"任务/{phase.value}", message)

    def _finish(self) -> RunResult:
        result = self._snapshot()
        self._write_json_atomic("task_result.json", asdict(result))
        return result

    def run(self, mode: StartMode) -> RunResult:
        """Execute the selected prefix followed by the shared pick/place tail."""

        if StartMode(self.demo.args.task_mode) is not mode:
            raise SafetyAbort(
                "任务模式在解析后发生变化，拒绝启动不一致的实机流程"
            )
        environment_guard: LeftArmStabilityGuard | None = None
        try:
            self.demo.initialize()
            self._record(TaskPhase.PREFLIGHT, "执行硬件、夹爪和安全配置预检")
            self.demo._preflight()
            if self.demo.left_robot is None:
                raise SafetyAbort(
                    "完整实机任务必须读取并监控左臂碰撞快照"
                )
            environment_guard = LeftArmStabilityGuard(
                left_reader=self.demo.left_robot,
                stop_event=self.demo.stop_event,
                tolerance_deg=self.demo.params.planned_start_tolerance_deg,
            )
            self.demo.task_left_reference_joints_deg = (
                environment_guard.start()
            )

            self._record(TaskPhase.HEAD_LOCK, "本轮重新采集固定头部目标")
            head_target = self.demo._fresh_head_target()

            self._record(TaskPhase.SCENE_SYNC, "用本轮头部 RGB-D 重建场景与桌面")
            self.demo._build_head_scene(head_target)

            if mode is StartMode.FROM_START:
                self._record(
                    TaskPhase.MOVE_TO_OBSERVATION,
                    "规划、复核并执行到右腕观察位",
                )
                observation_plan = self.demo._plan_observation(
                    np.asarray(head_target.point_base, dtype=float)
                )
                # A complete candidate/planner search may legitimately use
                # most of its 120-second budget.  Never execute that answer
                # against the old camera snapshot: reacquire the world and
                # revalidate the exact chosen trajectory first.
                self.demo._refresh_and_revalidate_plan(
                    name="moveit_observation",
                    plan=observation_plan,
                    locked_target=head_target,
                )
                self.demo._execute_plan(
                    "避障移动到右腕观察位", observation_plan
                )

            self._record(
                TaskPhase.WRIST_LOCK,
                (
                    "验证当前右腕观察位并建立新鲜目标锁"
                    if mode is StartMode.FROM_OBSERVATION
                    else "到位后建立新鲜右腕目标锁"
                ),
            )
            wrist_target = self.demo._fresh_wrist_target(head_target)
            self.demo._verify_wrist_observation_start(wrist_target)

            # Entering a grasp command makes the physical object state
            # conservative UNKNOWN until gripper feedback and lift both pass.
            self.object_state = ObjectState.UNKNOWN
            self._record(
                TaskPhase.GRASP_AND_LIFT,
                "执行共享接近、夹取反馈判定和抬升",
            )
            self.demo._grasp_and_lift(wrist_target)
            self.object_state = ObjectState.HELD
            self._record(
                TaskPhase.GRASP_VERIFIED,
                "夹爪反馈通过且瓶子已完成抬升，物体状态记为 held",
            )

            # Release may happen before a later retreat/vision failure, so do
            # not claim HELD or EMPTY while this compound action is in flight.
            self.object_state = ObjectState.UNKNOWN
            self._record(
                TaskPhase.PLACE_AND_RETREAT,
                "放回锁定位置、松开夹爪、安全退开后由固定头部确认释放",
            )
            self.demo._place_back(wrist_target)
            self.object_state = ObjectState.EMPTY
            self._record(
                TaskPhase.RELEASE_VERIFIED,
                "夹爪打开、瓶子在锁定放置点得到视觉确认且机械臂已退开",
            )

            if mode is StartMode.FROM_START:
                self._record(
                    TaskPhase.RETURN_HOME,
                    "重新采集头部障碍场景，再用同一安全规划链返回配置的初始姿态",
                )
                self.demo._refresh_head_scene_for_global_motion(wrist_target)
                self.demo._return_home()

            environment_guard.close()
            environment_guard = None

            self.status = RunStatus.DONE
            self._record(
                TaskPhase.DONE,
                "抓取、抬升、放回、释放确认和退开均已完成；任务正常退出",
            )
            return self._finish()
        except Exception as exc:
            if environment_guard is not None:
                try:
                    environment_guard.close()
                except Exception:
                    # Preserve the first physical/safety failure.  The guard
                    # already set stop_event if it was the source.
                    pass
            self.status = (
                RunStatus.SAFE_ABORT
                if isinstance(exc, SafetyAbort)
                else RunStatus.FAULT
            )
            self.error = f"{type(exc).__name__}: {exc}"
            try:
                self._record(TaskPhase.ABORTED, self.error)
                self._finish()
            except Exception:
                # Evidence I/O must never hide the original hardware/safety
                # failure that determines the process exit code.
                pass
            raise
