"""Stable contracts for external system-package builder plugins.

Package builders are deliberately narrower than device-source plugins.  A
builder prepares a controlled local process invocation; the application owns
task lifecycle, cancellation, logging, and artifact verification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Protocol


class PackageBuilderPluginError(RuntimeError):
    """Raised when a package-builder plugin violates its public contract."""


@dataclass(frozen=True, slots=True)
class PackageBuilderDescriptor:
    id: str
    label: str
    version: str = "1.0.0"
    publisher: str = ""
    package_types: tuple[str, ...] = ("system",)
    plugin_api_version: int = 1

    def __post_init__(self) -> None:
        plugin_id = self.id.strip().lower()
        label = self.label.strip()
        version = self.version.strip()
        if not plugin_id or len(plugin_id) > 64:
            raise PackageBuilderPluginError("Package-builder ids must contain 1-64 characters.")
        if not label or len(label) > 100:
            raise PackageBuilderPluginError("Package-builder labels must contain 1-100 characters.")
        if not version or len(version) > 40:
            raise PackageBuilderPluginError("Package-builder versions must contain 1-40 characters.")
        if self.plugin_api_version != 1:
            raise PackageBuilderPluginError("Unsupported package-builder plugin API version.")
        package_types = tuple(item.strip().lower() for item in self.package_types if item.strip())
        if not package_types:
            raise PackageBuilderPluginError("At least one package type is required.")
        object.__setattr__(self, "id", plugin_id)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "publisher", self.publisher.strip())
        object.__setattr__(self, "package_types", package_types)


@dataclass(frozen=True, slots=True)
class VrpBuildRequest:
    mrid: str
    package_type: str
    model: str = ""
    vrp_version: str = ""
    source_revision: str = ""
    output_name: str = ""
    options: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("mrid", "package_type"):
            value = str(getattr(self, name)).strip()
            if not value:
                raise ValueError(f"{name} is required")
            object.__setattr__(self, name, value)
        for name in ("model", "vrp_version", "source_revision", "output_name"):
            object.__setattr__(self, name, str(getattr(self, name) or "").strip())


@dataclass(frozen=True, slots=True)
class PackageBuilderContext:
    config: Mapping[str, object] = field(default_factory=dict)
    secrets: Mapping[str, str] = field(default_factory=dict)
    work_dir: Path = Path(".")
    output_dir: Path = Path(".")
    executable: str = ""


@dataclass(frozen=True, slots=True)
class PreparedBuild:
    argv: tuple[str, ...]
    cwd: str
    output_path: str
    env: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: float = 3_600
    request_path: str = ""

    def __post_init__(self) -> None:
        if not self.argv or not str(self.argv[0]).strip():
            raise PackageBuilderPluginError("Prepared build argv is required.")
        if not str(self.output_path).strip():
            raise PackageBuilderPluginError("Prepared build output_path is required.")


class PackageBuilderPlugin(Protocol):
    @property
    def descriptor(self) -> PackageBuilderDescriptor: ...

    def prepare_build(
        self,
        request: VrpBuildRequest,
        context: PackageBuilderContext,
    ) -> PreparedBuild: ...
