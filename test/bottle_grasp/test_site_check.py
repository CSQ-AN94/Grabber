"""Site-check runner semantics (no hardware).

真实检查项只能在板房跑——这里只锁三件框架层的事：失败必须被隔离而不是
中断整个体检、依赖未通过必须显式 SKIP 而不是装作通过、任何非全绿都必须
是 NO-GO。这些语义错了，体检报告会给出假 GO，比没有体检更危险。
"""

import json
from types import SimpleNamespace

import pytest

from bottle_grasp.core import SafetyAbort
from bottle_grasp.site_check import (
    Check,
    SiteCheckRunner,
    build_site_checks,
    render_table,
    verdict,
    write_report,
)


def _ok(_context):
    return "fine"


def _boom(_context):
    raise SafetyAbort("硬件不在状态")


def test_failure_is_isolated_and_dependents_skip():
    runner = SiteCheckRunner(
        [
            Check("a", "A", _boom),
            Check("b", "B", _ok),  # independent of a — must still run
            Check("c", "C", _ok, requires=("a",)),  # must SKIP, not pass
        ]
    )
    results = {result.name: result for result in runner.run()}
    assert results["a"].status == "fail"
    assert "硬件不在状态" in results["a"].detail
    assert results["b"].status == "pass"
    assert results["c"].status == "skip"
    assert "a" in results["c"].detail


def test_unexpected_exception_is_reported_not_raised():
    def crash(_context):
        raise RuntimeError("driver segfault-ish")

    results = SiteCheckRunner([Check("x", "X", crash)]).run()
    assert results[0].status == "fail"
    assert "RuntimeError" in results[0].detail


def test_context_flows_between_checks():
    def produce(context):
        context["value"] = 41
        return "produced"

    def consume(context):
        assert context["value"] == 41
        return "consumed"

    results = SiteCheckRunner(
        [
            Check("p", "P", produce),
            Check("q", "Q", consume, requires=("p",)),
        ]
    ).run()
    assert [result.status for result in results] == ["pass", "pass"]


def test_verdict_is_go_only_when_everything_passed():
    all_pass = SiteCheckRunner([Check("a", "A", _ok)]).run()
    assert verdict(all_pass) == "GO"
    with_fail = SiteCheckRunner(
        [Check("a", "A", _boom), Check("b", "B", _ok, requires=("a",))]
    ).run()
    # 一项失败 + 一项 SKIP：SKIP 是"没测到"，绝不能算 GO
    assert verdict(with_fail) == "NO-GO"
    assert verdict([]) == "NO-GO"


def test_registry_rejects_duplicate_or_forward_requires():
    with pytest.raises(ValueError, match="duplicate"):
        SiteCheckRunner([Check("a", "A", _ok), Check("a", "A2", _ok)])
    with pytest.raises(ValueError, match="requires"):
        SiteCheckRunner([Check("a", "A", _ok, requires=("later",))])


def test_real_check_sequence_covers_the_chain_in_order():
    """冻结体检覆盖面：少一环，体检的 GO 就不再意味着"链路都验过"。"""
    checks = build_site_checks(SimpleNamespace(project_root="/tmp"))
    names = [check.name for check in checks]
    assert names == [
        "clock",
        "head_servo",
        "collision_probe",
        "init_stack",
        "arm",
        "gripper",
        "head_stream",
        "head_localization",
        "scene_table",
        "plan_rehearsal",
        "wrist_stream",
    ]
    by_name = {check.name: check for check in checks}
    # 彩排必须同时依赖真实场景和真实手臂状态；定位必须依赖舵机在基准位
    assert set(by_name["plan_rehearsal"].requires) == {"scene_table", "arm"}
    assert "head_servo" in by_name["head_localization"].requires
    # 探针自带 move_group，必须先于 demo 的 MoveIt 栈
    assert names.index("collision_probe") < names.index("init_stack")


def test_report_written_and_renderable(tmp_path):
    results = SiteCheckRunner(
        [Check("a", "A", _ok), Check("b", "B", _boom)]
    ).run()
    path = write_report(tmp_path, results)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["verdict"] == "NO-GO"
    assert len(payload["results"]) == 2
    table = render_table(results)
    assert "A" in table and "B" in table
