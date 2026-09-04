"""Public package-builder plugin contracts and discovery."""

from .api import (
    PackageBuilderContext,
    PackageBuilderDescriptor,
    PackageBuilderPlugin,
    PackageBuilderPluginError,
    PreparedBuild,
    VrpBuildRequest,
)
from .builtin import InternalVrpCliBuilder
from .registry import PackageBuilderRegistry, build_package_builder_registry

__all__ = [
    "InternalVrpCliBuilder",
    "PackageBuilderContext",
    "PackageBuilderDescriptor",
    "PackageBuilderPlugin",
    "PackageBuilderPluginError",
    "PackageBuilderRegistry",
    "PreparedBuild",
    "VrpBuildRequest",
    "build_package_builder_registry",
]
