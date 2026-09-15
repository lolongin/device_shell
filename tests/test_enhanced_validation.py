"""测试增强的验证错误信息"""
import pytest
from device_tui.application.workflow_studio import (
    WorkflowDraft,
    WorkflowNode,
    WorkflowEdge,
    validate_workflow,
    build_action_catalog,
    ValidationIssue,
)

CATALOG = build_action_catalog()


def test_enhanced_validation_issue_has_fix_suggestion():
    """验证错误包含修复建议"""
    draft = WorkflowDraft(
        "test-workflow",
        "Test",
        nodes=(WorkflowNode("cmd1", "device.command", {"command": ""}),),
    )

    result = validate_workflow(draft, CATALOG)

    assert len(result.errors) > 0
    issue = result.errors[0]
    assert issue.code == "missing_required_config"
    assert issue.fix_suggestion is not None
    assert "display version" in issue.fix_suggestion or "命令" in issue.fix_suggestion


def test_enhanced_validation_issue_has_doc_link():
    """验证错误包含文档链接"""
    draft = WorkflowDraft(
        "test-workflow",
        "Test",
        nodes=(WorkflowNode("cmd1", "device.command", {"command": ""}),),
    )

    result = validate_workflow(draft, CATALOG)

    issue = result.errors[0]
    assert issue.doc_link is not None
    assert "/docs/nodes/" in issue.doc_link


def test_unknown_action_provides_helpful_message():
    """未知操作提供有用的错误信息"""
    draft = WorkflowDraft(
        "test-workflow",
        "Test",
        nodes=(WorkflowNode("node1", "unknown.action", {}),),
    )

    result = validate_workflow(draft, CATALOG)

    issue = next((e for e in result.errors if e.code == "unknown_action"), None)
    assert issue is not None
    assert issue.fix_suggestion is not None
    assert "节点库" in issue.fix_suggestion or "valid" in issue.fix_suggestion.lower()


def test_validation_issue_to_dict():
    """测试 ValidationIssue 转换为字典"""
    issue = ValidationIssue(
        code="test_error",
        message="Test error message",
        node_id="node1",
        severity="error",
        fix_suggestion="Try this fix",
        doc_link="/docs/test",
        affected_nodes=("node2", "node3"),
    )

    result = issue.to_dict()

    assert result["code"] == "test_error"
    assert result["message"] == "Test error message"
    assert result["node_id"] == "node1"
    assert result["severity"] == "error"
    assert result["fix_suggestion"] == "Try this fix"
    assert result["doc_link"] == "/docs/test"
    assert result["affected_nodes"] == ["node2", "node3"]


def test_different_action_types_have_specific_suggestions():
    """不同操作类型有特定的建议"""
    # device.command
    draft1 = WorkflowDraft("w1", "Test", nodes=(WorkflowNode("n1", "device.command", {}),))
    result1 = validate_workflow(draft1, CATALOG)
    issue1 = result1.errors[0]
    assert "display" in issue1.fix_suggestion.lower() or "命令" in issue1.fix_suggestion

    # utility.wait
    draft2 = WorkflowDraft("w2", "Test", nodes=(WorkflowNode("n2", "utility.wait", {}),))
    result2 = validate_workflow(draft2, CATALOG)
    issue2 = result2.errors[0]
    assert "秒" in issue2.fix_suggestion or "second" in issue2.fix_suggestion.lower()

    # loop.for_each
    draft3 = WorkflowDraft("w3", "Test", nodes=(WorkflowNode("n3", "loop.for_each", {}),))
    result3 = validate_workflow(draft3, CATALOG)
    # 找到 items 或 action_id 的错误
    items_issue = next((e for e in result3.errors if "items" in e.message), None)
    if items_issue:
        assert "列表" in items_issue.fix_suggestion or "list" in items_issue.fix_suggestion.lower()


def test_validation_result_maintains_backward_compatibility():
    """确保增强的验证结果向后兼容"""
    draft = WorkflowDraft(
        "test-workflow",
        "Test",
        nodes=(
            WorkflowNode("cmd1", "device.command", {"command": ""}),
            WorkflowNode("cmd2", "device.command", {"command": ""}),
        ),
        edges=(WorkflowEdge("cmd1", "cmd1"),),  # 自循环
    )

    result = validate_workflow(draft, CATALOG)

    # 应该有错误
    assert not result.valid
    assert not result.is_valid
    assert len(result.errors) > 0

    # 所有错误应该是 ValidationIssue 类型
    for error in result.errors:
        assert isinstance(error, ValidationIssue)
        assert hasattr(error, "code")
        assert hasattr(error, "message")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
