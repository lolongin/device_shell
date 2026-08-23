from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from device_tui.application.tasking import (
    PlanStep,
    WorkflowCatalog,
    WorkflowCatalogError,
    WorkflowDescriptor,
    WorkflowParameter,
    WorkflowPlan,
    WorkflowPlanCompiler,
    WorkflowTarget,
    build_default_workflow_catalog,
)
from device_tui.application.tasking.models import WorkflowDefinition, WorkflowStep
from device_tui.device_sources.sample import SampleDeviceRepository
from device_tui.interfaces.desktop_api.app import create_app
from device_tui.interfaces.desktop_api.session_hub import SessionHub


class HealthWorkflowProvider:
    descriptor = WorkflowDescriptor(
        id="device.health_check",
        version="1",
        name="设备健康检查",
        description="执行健康检查命令。",
        parameters=(WorkflowParameter("command", required=True),),
        capability="device.health_check",
        capability_action="device_health_check",
    )

    def build(self, target: WorkflowTarget, parameters: dict[str, object]) -> WorkflowDefinition:
        return WorkflowDefinition(
            id=self.descriptor.id,
            name=self.descriptor.name,
            steps=(WorkflowStep("health", action="command", params={"command": parameters["command"], "device_id": target.device_id}),),
        )

    def migrate_legacy(self, parameters, steps):
        return dict(parameters)


def test_catalog_registers_provider_and_builds_without_api_changes() -> None:
    catalog = build_default_workflow_catalog()
    catalog.register(HealthWorkflowProvider())
    assert {item.id for item in catalog.list()} == {"device_upgrade", "device.health_check"}
    workflow = catalog.build("device.health_check", WorkflowTarget("d1"), {"command": "display health"})
    assert workflow.id == "device.health_check"
    assert workflow.steps[0].params["device_id"] == "d1"


def test_catalog_rejects_unknown_and_invalid_parameters() -> None:
    catalog = build_default_workflow_catalog()
    with pytest.raises(WorkflowCatalogError, match="unknown workflow"):
        catalog.descriptor("does_not_exist")
    with pytest.raises(WorkflowCatalogError, match="must be one of"):
        catalog.build(
            "device_upgrade",
            WorkflowTarget("d1"),
            {"package_path": "target.cc", "activation_policy": "invalid"},
        )


def test_plan_compiler_uses_injected_catalog_for_named_workflow() -> None:
    catalog = build_default_workflow_catalog()
    catalog.register(HealthWorkflowProvider())
    compiler = WorkflowPlanCompiler(catalog=catalog)
    result = compiler.validate(
        WorkflowPlan(
            "plan-health",
            "check device health",
            {"device_id": "d1"},
            (PlanStep("health", "device.health_check", {"command": "display health"}),),
        )
    )
    assert result.status == "validated"
    assert result.workflow is not None
    assert result.workflow.steps[0].id == "health.health"


def test_desktop_api_lists_and_builds_injected_provider() -> None:
    catalog = build_default_workflow_catalog()
    catalog.register(HealthWorkflowProvider())
    app = create_app(
        token="catalog-token",
        repository=SampleDeviceRepository(),
        session_hub=SessionHub(),
        workflow_catalog=catalog,
    )
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer catalog-token"}
        workflows = client.get("/api/v1/workflows", headers=headers)
        device_id = client.get("/api/v1/devices", headers=headers).json()["devices"][0]["id"]
        task = client.post(
            "/api/v1/tasks",
            headers=headers,
            json={
                "workflow_id": "device.health_check",
                "device_id": device_id,
                "parameters": {"command": "display version"},
                "source": "desktop",
            },
        )
    assert workflows.status_code == 200
    assert "device.health_check" in {item["id"] for item in workflows.json()["workflows"]}
    assert task.status_code == 200, task.text
    assert task.json()["task"]["workflow_id"] == "device.health_check"
