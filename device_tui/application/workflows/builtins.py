"""Default framework plugin registries."""

from .huawei_package import HuaweiVrpPackageUpgradeProvider, HuaweiVrpWorkflowAdapter
from .plugins import AdapterRegistry, WorkflowRegistry


def build_default_workflow_registry() -> WorkflowRegistry:
    registry = WorkflowRegistry()
    registry.register(HuaweiVrpPackageUpgradeProvider())
    return registry


def build_default_adapter_registry() -> AdapterRegistry:
    registry = AdapterRegistry()
    registry.register(HuaweiVrpWorkflowAdapter())
    return registry


__all__ = [
    "HuaweiVrpPackageUpgradeProvider",
    "HuaweiVrpWorkflowAdapter",
    "build_default_adapter_registry",
    "build_default_workflow_registry",
]
