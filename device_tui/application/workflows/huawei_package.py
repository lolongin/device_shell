"""Backward-compatible import for the Huawei workflow plugin."""

from device_tui.application.workflow_plugins.huawei_package import (
    HuaweiVrpPackageUpgradeProvider,
    HuaweiVrpWorkflowAdapter,
)

__all__ = ["HuaweiVrpPackageUpgradeProvider", "HuaweiVrpWorkflowAdapter"]
