"""Entry Point discovery and registry for package-builder plugins."""

from __future__ import annotations

from importlib import metadata
from typing import Iterable

from .api import PackageBuilderPlugin, PackageBuilderPluginError
from .builtin import InternalVrpCliBuilder

PACKAGE_BUILDER_ENTRY_POINT_GROUP = "device_tui.package_builders"


class PackageBuilderRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, PackageBuilderPlugin] = {}
        self._warnings: list[str] = []

    def register(self, plugin: PackageBuilderPlugin, *, strict: bool = True) -> None:
        try:
            descriptor = plugin.descriptor
            plugin_id = descriptor.id
            if not callable(getattr(plugin, "prepare_build", None)):
                raise PackageBuilderPluginError("Plugin must implement prepare_build().")
            if plugin_id in self._plugins:
                raise PackageBuilderPluginError(f"Duplicate package-builder id: {plugin_id}")
            self._plugins[plugin_id] = plugin
        except Exception as exc:
            if strict:
                raise
            self._warnings.append(str(exc))

    def get(self, builder_id: str) -> PackageBuilderPlugin:
        try:
            return self._plugins[str(builder_id).strip().lower()]
        except KeyError as exc:
            raise KeyError(f"Unknown package builder: {builder_id}") from exc

    def list(self) -> tuple[PackageBuilderPlugin, ...]:
        return tuple(self._plugins[key] for key in sorted(self._plugins))

    def warnings(self) -> tuple[str, ...]:
        return tuple(self._warnings)


def discover_package_builder_plugins() -> tuple[list[PackageBuilderPlugin], list[str]]:
    plugins: list[PackageBuilderPlugin] = []
    warnings: list[str] = []
    try:
        entries = metadata.entry_points()
        selected = entries.select(group=PACKAGE_BUILDER_ENTRY_POINT_GROUP)
        for entry in selected:
            try:
                candidate = entry.load()
                plugin = candidate() if callable(candidate) else candidate
                plugins.append(plugin)
            except Exception as exc:
                warnings.append(f"无法加载编包插件 {entry.name}：{exc}")
    except Exception as exc:
        warnings.append(f"无法发现编包插件：{exc}")
    return plugins, warnings


def build_package_builder_registry(
    plugins: Iterable[PackageBuilderPlugin] = (),
    *,
    discover: bool = True,
) -> PackageBuilderRegistry:
    registry = PackageBuilderRegistry()
    registry.register(InternalVrpCliBuilder())
    if discover:
        discovered, warnings = discover_package_builder_plugins()
        registry._warnings.extend(warnings)
        for plugin in discovered:
            registry.register(plugin, strict=False)
    for plugin in plugins:
        registry.register(plugin)
    return registry


__all__ = [
    "PACKAGE_BUILDER_ENTRY_POINT_GROUP",
    "PackageBuilderRegistry",
    "build_package_builder_registry",
    "discover_package_builder_plugins",
]
