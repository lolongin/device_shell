from __future__ import annotations

import asyncio

import pytest

from device_tui.application import build_desktop_application
from device_tui.application.errors import ApplicationError
from device_tui.application.tasking import (
    TaskCreate,
    TaskRecord,
    WorkflowDefinition,
    WorkflowStep,
    WorkflowTarget,
)
from device_tui.application.tasking import MemoryTaskStore
from device_tui.application.device_control import DeviceTarget
from device_tui.device_sources.sample import SampleDeviceRepository
from device_tui.framework import MemoryTaskRunStore
from device_tui.interfaces.desktop_api.session_hub import SessionHub


def _upgrade_request(application):
    workflow = application.workflows.build(
        "device_upgrade",
        WorkflowTarget(device_id="device-1"),
        {"package_path": "image.cc"},
    )
    return TaskCreate(
        workflow=workflow,
        target=DeviceTarget(device_id="device-1"),
        source="test",
    )


def test_production_compatibility_backend_is_not_a_framework_scheduler() -> None:
    application = build_desktop_application(SampleDeviceRepository(), SessionHub())
    backend = application.task_service._backend

    assert backend.__class__.__name__ == "TaskRecordCompatibilityBackend"
    assert not hasattr(backend, "_jobs")
    assert not hasattr(backend, "_allow_legacy_execution")

    asyncio.run(application.task_service.close())


def test_production_task_service_rejects_uncompiled_legacy_creation() -> None:
    application = build_desktop_application(SampleDeviceRepository(), SessionHub())
    request = TaskCreate(
        workflow=WorkflowDefinition(
            "legacy-workflow",
            (WorkflowStep("step", action="command"),),
        ),
        target=DeviceTarget(device_id="device-1"),
    )

    with pytest.raises(ApplicationError, match="Framework TaskPlan"):
        application.task_service.create(request)

    assert not hasattr(application.task_service._backend, "_jobs")
    asyncio.run(application.task_service.close())


def test_framework_creation_never_calls_legacy_backend_create(monkeypatch) -> None:
    application = build_desktop_application(SampleDeviceRepository(), SessionHub())
    backend = application.task_service._backend

    def fail_create(_request):
        raise AssertionError("Framework task creation entered the legacy backend")

    monkeypatch.setattr(backend, "create", fail_create)
    record = application.task_service.create(_upgrade_request(application))

    assert record.workflow_id == "device_upgrade"
    assert record.id in application.task_service._framework_requests
    asyncio.run(application.task_service.close())


def test_allowlisted_legacy_command_is_compiled_to_framework(monkeypatch) -> None:
    application = build_desktop_application(SampleDeviceRepository(), SessionHub())
    backend = application.task_service._backend

    def fail_create(_request):
        raise AssertionError("allow-listed legacy workflow entered the backend")

    monkeypatch.setattr(backend, "create", fail_create)
    request = TaskCreate(
        workflow=WorkflowDefinition(
            "health-check",
            (WorkflowStep(
                "health",
                action="command",
                params={"command": "display version", "device_id": "device-1"},
            ),),
        ),
        target=DeviceTarget(device_id="device-1"),
    )

    record = application.task_service.create(request)
    plan = application.task_service._framework_plans[record.id]
    assert plan.nodes[0].workflow_id == "terminal.command"
    assert plan.nodes[0].input_mapping["command"] == "display version"
    assert not hasattr(backend, "_jobs")
    asyncio.run(application.task_service.close())


def test_restart_adopts_persisted_framework_task_without_legacy_jobs() -> None:
    task_store = MemoryTaskStore()
    run_store = MemoryTaskRunStore()
    app1 = build_desktop_application(
        SampleDeviceRepository(),
        SessionHub(),
        task_store=task_store,
        framework_task_run_store=run_store,
    )
    record = app1.task_service.create(_upgrade_request(app1))

    app2 = build_desktop_application(
        SampleDeviceRepository(),
        SessionHub(),
        task_store=task_store,
        framework_task_run_store=run_store,
    )

    try:
        assert record.id in app2.task_service._framework_requests
        assert app2.task_service.get(record.id).id == record.id
        assert not hasattr(app2.task_service._backend, "_jobs")
    finally:
        asyncio.run(app2.task_service.close())
        asyncio.run(app1.task_service.close())
