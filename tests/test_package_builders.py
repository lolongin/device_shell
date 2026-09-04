from __future__ import annotations

import asyncio
from pathlib import Path

from device_tui.application.events import EventBus
from device_tui.application.operations import MemoryOperationStore, OperationManager
from device_tui.infrastructure.packaging import PackageBuildService
from device_tui.package_builders import (
    InternalVrpCliBuilder,
    PackageBuilderContext,
    PackageBuilderPluginError,
    VrpBuildRequest,
    build_package_builder_registry,
)
from device_tui.infrastructure.processes.local import ProcessExecutionResult


def test_internal_builder_writes_request_and_uses_external_executable(tmp_path: Path) -> None:
    prepared = InternalVrpCliBuilder().prepare_build(
        VrpBuildRequest("mrid-1", "system", model="S5735", vrp_version="V1", output_name="image.cc"),
        PackageBuilderContext(
            executable="vrp-builder.exe",
            work_dir=tmp_path / "work",
            output_dir=tmp_path / "out",
        ),
    )

    assert prepared.argv[0] == "vrp-builder.exe"
    assert prepared.argv[-1] == "--json-lines"
    assert Path(prepared.output_path).name == "image.cc"
    payload = Path(prepared.request_path).read_text(encoding="utf-8")
    assert '"mrid": "mrid-1"' in payload
    assert '"package_type": "system"' in payload


def test_internal_builder_rejects_output_path_escape(tmp_path: Path) -> None:
    try:
        InternalVrpCliBuilder().prepare_build(
            VrpBuildRequest("mrid-1", "system", output_name="..\\outside.cc"),
            PackageBuilderContext(
                executable="vrp-builder.exe",
                work_dir=tmp_path / "work",
                output_dir=tmp_path / "out",
            ),
        )
    except PackageBuilderPluginError as exc:
        assert "output_name" in str(exc)
    else:
        raise AssertionError("output path escape was accepted")


class _FakeProcess:
    def __init__(self, output_path: str) -> None:
        self.output_path = Path(output_path)
        self.cancelled = False

    async def run(self, invocation_id, argv, **kwargs):
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_bytes(b"vrp-package")
        on_output = kwargs.get("on_output")
        if on_output:
            on_output('{"event":"phase","name":"compile","progress":50}\n')
            on_output('{"event":"result","progress":100}\n')
        return ProcessExecutionResult("succeeded", 0, "ok")

    async def cancel(self, invocation_id):
        self.cancelled = True


def test_package_build_service_completes_and_records_checksum(tmp_path: Path) -> None:
    registry = build_package_builder_registry(discover=False)
    operations = OperationManager(EventBus(), MemoryOperationStore(), persistent_kinds={PackageBuildService.KIND})
    output = tmp_path / "transfers" / "image.cc"
    fake = _FakeProcess(str(output))
    service = PackageBuildService(
        operations,
        EventBus(),
        registry,
        data_root=tmp_path,
        process_adapter=fake,
    )

    async def run() -> None:
        operation = service.start(
            VrpBuildRequest("mrid-1", "system", output_name="image.cc"),
            config={"executable": "vrp-builder.exe"},
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        latest = service.get(operation.id)
        assert latest.status == "completed"
        assert latest.progress_percent == 100
        assert latest.data["artifact_name"] == "image.cc"
        assert latest.data["size_bytes"] == len(b"vrp-package")
        await service.close()

    asyncio.run(run())
