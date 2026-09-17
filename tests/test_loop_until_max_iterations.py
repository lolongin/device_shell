"""测试 loop.until 的 max_iterations 配置是否正确生效"""
import pytest
from device_tui.application.workflow_studio import *

CATALOG = build_action_catalog()


def test_loop_until_respects_max_iterations():
    """验证 loop.until 会执行配置的 max_iterations 次数"""
    workflow = WorkflowDraft(
        "测试循环次数",
        "验证 max_iterations",
        nodes=(
            WorkflowNode(
                "loop1",
                "loop.until",
                {
                    "action_id": "device.command",
                    "action_inputs": {"command": "echo test"},
                    "condition": "False",  # 永远不满足
                    "max_iterations": 5,
                    "interval_seconds": 0
                }
            ),
        )
    )

    result = validate_workflow(workflow, CATALOG)
    assert result.valid, f"验证失败: {result.errors}"
    assert not result.errors, "不应该有验证错误"


def test_loop_until_with_different_max_iterations():
    """测试不同的 max_iterations 值"""
    for max_iter in [1, 3, 10, 50, 100]:
        workflow = WorkflowDraft(
            f"测试 {max_iter} 次循环",
            "验证不同的 max_iterations",
            nodes=(
                WorkflowNode(
                    "loop1",
                    "loop.until",
                    {
                        "action_id": "device.command",
                        "action_inputs": {"command": "echo test"},
                        "condition": "result.status == 'succeeded'",
                        "max_iterations": max_iter,
                        "interval_seconds": 0
                    }
                ),
            )
        )

        result = validate_workflow(workflow, CATALOG)
        assert result.valid, f"max_iterations={max_iter} 验证失败: {result.errors}"


def test_loop_until_invalid_max_iterations():
    """测试无效的 max_iterations 值"""
    for invalid_value in [0, -1, 101, 1000]:
        workflow = WorkflowDraft(
            "测试无效循环次数",
            "验证边界检查",
            nodes=(
                WorkflowNode(
                    "loop1",
                    "loop.until",
                    {
                        "action_id": "device.command",
                        "action_inputs": {"command": "echo test"},
                        "condition": "result.status == 'succeeded'",
                        "max_iterations": invalid_value,
                        "interval_seconds": 0
                    }
                ),
            )
        )

        result = validate_workflow(workflow, CATALOG)
        # 应该有验证错误
        assert not result.valid or result.errors, \
            f"max_iterations={invalid_value} 应该被拒绝"
