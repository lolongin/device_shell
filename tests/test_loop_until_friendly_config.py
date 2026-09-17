"""Test that loop.until friendly UI configuration generates valid conditions."""

import pytest
from device_tui.application.workflow_studio import *


CATALOG = build_action_catalog()


def test_output_contains_condition_is_valid():
    """Test that 'output contains text' mode generates a valid condition."""
    workflow = WorkflowDraft(
        "w1",
        "Loop until READY appears",
        nodes=(
            WorkflowNode(
                "loop_1",
                "loop.until",
                {
                    "action_id": "device.command",
                    "action_inputs": {"command": "display version"},
                    "condition": "'READY' in result.output",
                    "max_iterations": 10,
                    "interval_seconds": 2,
                },
            ),
        ),
    )

    result = validate_workflow(workflow, CATALOG)
    assert not result.errors, f"Expected no errors, got {result.errors}"


def test_output_regex_condition_is_valid():
    """Test that 'output matches regex' mode generates a valid condition."""
    workflow = WorkflowDraft(
        "w2",
        "Loop until version pattern matches",
        nodes=(
            WorkflowNode(
                "loop_1",
                "loop.until",
                {
                    "action_id": "device.command",
                    "action_inputs": {"command": "display version"},
                    "condition": "'V\\\\d+R\\\\d+' in result.output",
                    "max_iterations": 10,
                    "interval_seconds": 2,
                },
            ),
        ),
    )

    result = validate_workflow(workflow, CATALOG)
    assert not result.errors, f"Expected no errors, got {result.errors}"


def test_command_success_condition_is_valid():
    """Test that 'command success' mode generates a valid condition."""
    workflow = WorkflowDraft(
        "w3",
        "Loop until command succeeds",
        nodes=(
            WorkflowNode(
                "loop_1",
                "loop.until",
                {
                    "action_id": "device.command",
                    "action_inputs": {"command": "ping 8.8.8.8"},
                    "condition": "result.status == 'succeeded'",
                    "max_iterations": 5,
                    "interval_seconds": 3,
                },
            ),
        ),
    )

    result = validate_workflow(workflow, CATALOG)
    assert not result.errors, f"Expected no errors, got {result.errors}"


def test_command_failure_condition_is_valid():
    """Test that 'command failure' mode generates a valid condition."""
    workflow = WorkflowDraft(
        "w4",
        "Loop until command fails",
        nodes=(
            WorkflowNode(
                "loop_1",
                "loop.until",
                {
                    "action_id": "device.command",
                    "action_inputs": {"command": "test -f /tmp/lock"},
                    "condition": "result.status == 'failed'",
                    "max_iterations": 20,
                    "interval_seconds": 1,
                },
            ),
        ),
    )

    result = validate_workflow(workflow, CATALOG)
    assert not result.errors, f"Expected no errors, got {result.errors}"


def test_empty_pattern_is_still_valid():
    """Test that empty pattern in 'output contains' still validates (will match empty string)."""
    workflow = WorkflowDraft(
        "w5",
        "Loop with empty pattern",
        nodes=(
            WorkflowNode(
                "loop_1",
                "loop.until",
                {
                    "action_id": "device.command",
                    "action_inputs": {"command": "display version"},
                    "condition": "'' in result.output",
                    "max_iterations": 10,
                    "interval_seconds": 2,
                },
            ),
        ),
    )

    result = validate_workflow(workflow, CATALOG)
    assert not result.errors, f"Expected no errors, got {result.errors}"

