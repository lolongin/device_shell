from device_tui.application.workflow_studio.conditions import evaluate_rules


def test_evaluate_rules_supports_business_operators_and_and_or() -> None:
    values = {"software_version": "8.100", "status": "ready", "name": "router-a"}
    assert evaluate_rules([{"field": "software_version", "operator": "小于", "value": "8.200"}], values)
    assert evaluate_rules([
        {"field": "software_version", "operator": "小于", "value": "8.200"},
        {"field": "status", "operator": "等于", "value": "ready"},
    ], values, logical_operator="AND")
    assert not evaluate_rules([
        {"field": "software_version", "operator": "大于", "value": "8.200"},
        {"field": "name", "operator": "包含", "value": "router"},
    ], values, logical_operator="AND")
    assert evaluate_rules([
        {"field": "software_version", "operator": "大于", "value": "8.200"},
        {"field": "name", "operator": "包含", "value": "router"},
    ], values, logical_operator="OR")


def test_evaluate_rules_handles_empty_and_missing_fields() -> None:
    assert evaluate_rules([{"field": "missing", "operator": "是否为空", "value": ""}], {})
    assert not evaluate_rules([{"field": "status", "operator": "等于", "value": "ready"}], {})
    assert evaluate_rules([{"field": "name", "operator": "不包含", "value": "switch"}], {"name": "router-a"})
