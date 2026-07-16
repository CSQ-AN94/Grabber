# Electronic fence profiles

The grasp state machine is environment-independent. Static geometry and allowed
TCP corridors live in `safety_profiles.json`; RGB-D contributes only temporary
obstacle voxels.

Each profile uses the calibrated/controller frame `right_controller_base`.
The fixed `T_moveit_from_profile` bridge converts it to MoveIt's
`platform_base_link` frame. A profile contains:

- `tcp_workspace`: the outer software envelope.
- `allowed_tcp_zones`: a union of safe home, transit, and task volumes.
- `keepout_boxes`: solid fixtures such as a table, shelf panels, shelf boards,
  walls, or the robot body.
- `clearance_m`: the extra distance applied during offline TCP checks.
- `verified_for_execution`: must remain `false` until every boundary has been
  measured and checked on the real robot.

For a shelf, copy `shelf_template`, measure the shelf bottom/top/left/right/back
panels as keepout boxes, then define one home corridor and one or more bin
approach volumes. Select it with:

```bash
SAFETY_PROFILE=my_shelf PLAN_ONLY=1 scripts/start_bottle_demo.sh
```

Only after plan-only validation and a low-speed supervised dry run should the
profile be marked `verified_for_execution: true`.

When a good route has already been demonstrated by teleoperation, record the
whole route instead of guessing a new global path:

```bash
python scripts/record_right_arm_guided_path.py
```

The recorder is read-only. The sampled joint/TCP path can be checked against
the same profile, reduced to safe gateway waypoints, and reused as the
environment-specific transit corridor. For shelves, keep a guided corridor per
bin or per row while retaining the same grasp state machine.

The RealMan SDK's named electronic-fence API is not used as a real-hardware
guard because its current documentation says that feature only takes effect in
controller simulation mode. On hardware, this demo uses MoveIt collision
objects plus SDK forward-kinematics validation of every dense trajectory point.
The hardware emergency stop remains required.
