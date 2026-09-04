"""Built-in adapter for the independently packaged internal VRP CLI."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .api import (
    PackageBuilderContext,
    PackageBuilderDescriptor,
    PackageBuilderPluginError,
    PreparedBuild,
    VrpBuildRequest,
)


class InternalVrpCliBuilder:
    """Prepare invocations for ``vrp-builder build --request ...``.

    The executable is intentionally external to the backend.  The adapter
    writes only non-secret request data and never places credentials in argv.
    """

    descriptor = PackageBuilderDescriptor(
        id="internal-vrp",
        label="内部 VRP 编包器",
        publisher="Internal",
        package_types=("system", "patch"),
    )

    def prepare_build(
        self,
        request: VrpBuildRequest,
        context: PackageBuilderContext,
    ) -> PreparedBuild:
        executable = str(context.executable or context.config.get("executable") or "").strip()
        if not executable:
            executable = os.getenv("DEVICE_TUI_VRP_BUILDER", "").strip()
        if not executable:
            raise PackageBuilderPluginError(
                "VRP 编包器未配置，请设置 DEVICE_TUI_VRP_BUILDER 或插件 executable 配置。"
            )
        if request.package_type.casefold() not in self.descriptor.package_types:
            raise PackageBuilderPluginError(
                f"Unsupported package type: {request.package_type}"
            )

        work_dir = Path(context.work_dir).resolve()
        output_dir = Path(context.output_dir).resolve()
        work_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_name = request.output_name or f"{request.model or 'vrp'}-{request.vrp_version or request.mrid}.cc"
        if any(separator in output_name for separator in ("/", "\\")):
            raise PackageBuilderPluginError("output_name must be a file name, not a path.")
        output_path = (output_dir / Path(output_name).name).resolve()
        if output_path.parent != output_dir:
            raise PackageBuilderPluginError("output_name must be a file name, not a path.")
        request_path = work_dir / "request.json"
        payload = {
            "mrid": request.mrid,
            "package_type": request.package_type,
            "model": request.model,
            "vrp_version": request.vrp_version,
            "source_revision": request.source_revision,
            "output_name": output_path.name,
            "options": dict(request.options),
        }
        request_path.write_text(
            json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        return PreparedBuild(
            argv=(
                executable,
                "build",
                "--request",
                str(request_path),
                "--output",
                str(output_path),
                "--json-lines",
            ),
            cwd=str(work_dir),
            output_path=str(output_path),
            env={str(key): str(value) for key, value in context.config.items() if str(key).startswith("VRP_BUILDER_")},
            timeout_seconds=float(context.config.get("timeout_seconds") or 3_600),
            request_path=str(request_path),
        )


__all__ = ["InternalVrpCliBuilder"]
