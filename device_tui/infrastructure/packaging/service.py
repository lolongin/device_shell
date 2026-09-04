"""Long-running package build service backed by external CLI processes."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Mapping

from device_tui.application.events import EventBus
from device_tui.application.operations import OperationManager, OperationRecord
from device_tui.infrastructure.processes import LocalProcessAdapter
from device_tui.package_builders import (
    PackageBuilderContext,
    PackageBuilderPluginError,
    PackageBuilderRegistry,
    VrpBuildRequest,
)


class PackageBuildService:
    """Run package-builder plugins as cancellable desktop operations."""

    KIND = "vrp_package_build"

    def __init__(
        self,
        operations: OperationManager,
        events: EventBus,
        registry: PackageBuilderRegistry,
        *,
        data_root: Path,
        output_root: Path | None = None,
        process_adapter: LocalProcessAdapter | None = None,
    ) -> None:
        self._operations = operations
        self._events = events
        self._registry = registry
        self._data_root = Path(data_root).resolve()
        self._output_root = Path(output_root).resolve() if output_root is not None else self._data_root / "transfers"
        self._processes = process_adapter or LocalProcessAdapter()
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def builders(self) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "id": plugin.descriptor.id,
                "label": plugin.descriptor.label,
                "version": plugin.descriptor.version,
                "publisher": plugin.descriptor.publisher,
                "package_types": list(plugin.descriptor.package_types),
            }
            for plugin in self._registry.list()
        )

    def start(
        self,
        request: VrpBuildRequest,
        *,
        builder_id: str = "internal-vrp",
        config: Mapping[str, object] | None = None,
    ) -> OperationRecord:
        operation = self._operations.create(
            kind=self.KIND,
            direction="build",
            device_id="",
            session_id="",
            stage="queued",
            message="编包任务已排队。",
            data={"builder_id": builder_id, "mrid": request.mrid, "package_type": request.package_type},
        )
        task = asyncio.create_task(
            self._run(operation.id, request, builder_id, dict(config or {})),
            name=f"package-build-{operation.id}",
        )
        self._tasks[operation.id] = task
        self._operations.register_canceller(operation.id, lambda oid=operation.id: self._cancel(oid))
        task.add_done_callback(lambda _task, oid=operation.id: self._tasks.pop(oid, None))
        return operation

    def get(self, operation_id: str) -> OperationRecord:
        return self._operations.get(operation_id)

    def cancel(self, operation_id: str) -> OperationRecord:
        return self._operations.cancel(operation_id)

    async def close(self) -> None:
        for task in tuple(self._tasks.values()):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

    async def _run(
        self,
        operation_id: str,
        request: VrpBuildRequest,
        builder_id: str,
        config: dict[str, object],
    ) -> None:
        work_dir = self._data_root / "package-builds" / operation_id
        output_dir = self._output_root
        try:
            plugin = self._registry.get(builder_id)
            prepared = plugin.prepare_build(
                request,
                PackageBuilderContext(
                    config=config,
                    work_dir=work_dir,
                    output_dir=output_dir,
                    executable=str(config.get("executable") or os.getenv("DEVICE_TUI_VRP_BUILDER", "")),
                ),
            )
            self._operations.update(
                operation_id,
                status="running",
                stage="building",
                message="正在编译 VRP 系统包。",
            )
            buffer = ""

            def on_output(chunk: str) -> None:
                nonlocal buffer
                buffer += chunk
                lines = buffer.splitlines(keepends=True)
                buffer = "" if not lines or lines[-1].endswith(("\n", "\r")) else lines.pop()
                for line in lines:
                    self._handle_output(operation_id, line.strip())

            result = await self._processes.run(
                operation_id,
                prepared.argv,
                cwd=prepared.cwd,
                env=(dict(os.environ) | dict(prepared.env)) if prepared.env else None,
                timeout_seconds=prepared.timeout_seconds,
                on_output=on_output,
            )
            if result.status == "cancelled":
                return
            if result.status != "succeeded":
                self._operations.update(
                    operation_id,
                    status="failed" if result.status == "failed" else "interrupted",
                    stage="failed",
                    message="VRP 编包失败。",
                    error_code="package_builder_failed" if result.status == "failed" else "package_builder_timeout",
                    data={"returncode": result.returncode},
                )
                return
            artifact = Path(prepared.output_path).resolve()
            try:
                artifact.relative_to(output_dir)
            except ValueError as exc:
                raise PackageBuilderPluginError("编包产物必须位于受控输出目录内。") from exc
            if not artifact.is_file() or artifact.stat().st_size <= 0:
                raise PackageBuilderPluginError(f"编包完成但产物不存在或为空：{artifact.name}")
            digest = hashlib.sha256()
            with artifact.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            self._operations.update(
                operation_id,
                status="completed",
                stage="completed",
                progress_percent=100,
                message="VRP 系统包编译完成。",
                data={
                    "artifact_name": artifact.name,
                    "artifact_relative_path": artifact.relative_to(output_dir).as_posix(),
                    "size_bytes": artifact.stat().st_size,
                    "sha256": digest.hexdigest(),
                },
            )
        except asyncio.CancelledError:
            self._operations.update(
                operation_id,
                status="cancelled",
                stage="cancelled",
                message="编包任务已取消。",
                error_code="operation_cancelled",
            )
        except Exception as exc:
            self._operations.update(
                operation_id,
                status="failed",
                stage="failed",
                message=str(exc),
                error_code="package_builder_error",
            )

    def _handle_output(self, operation_id: str, line: str) -> None:
        if not line:
            return
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            self._operations.update(operation_id, message=line[-2_000:])
            return
        if not isinstance(payload, dict):
            return
        progress = payload.get("progress")
        progress_percent = int(progress) if isinstance(progress, (int, float)) else None
        stage = str(payload.get("name") or payload.get("stage") or "building")
        message = str(payload.get("message") or payload.get("event") or stage)
        self._operations.update(
            operation_id,
            stage=stage,
            message=message,
            progress_percent=progress_percent,
        )

    def _cancel(self, operation_id: str) -> None:
        task = self._tasks.get(operation_id)
        if task is not None:
            task.cancel()
        asyncio.create_task(self._processes.cancel(operation_id))


__all__ = ["PackageBuildService"]
