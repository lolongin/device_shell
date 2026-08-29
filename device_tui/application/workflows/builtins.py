"""Backward-compatible domain registry imports.

New composition roots should import these builders from
``application.workflow_plugins`` so the framework remains vendor-neutral.
"""

from device_tui.application.workflow_plugins.builtins import (
    HuaweiVrpPackageUpgradeProvider,
    HuaweiVrpWorkflowAdapter,
    build_default_adapter_registry,
    build_default_workflow_registry,
)

__all__ = [
    "HuaweiVrpPackageUpgradeProvider",
    "HuaweiVrpWorkflowAdapter",
    "build_default_adapter_registry",
    "build_default_workflow_registry",
]
