"""Compatibility imports for the relocated workflow framework.

The implementation lives in :mod:`device_tui.framework`; shipped business
plugins remain under :mod:`device_tui.application.workflow_plugins`.
"""

from device_tui.framework import *  # noqa: F401,F403
from device_tui.framework import __all__ as _framework_all
from device_tui.application.workflow_plugins.builtins import (
    HuaweiVrpPackageUpgradeProvider,
    HuaweiVrpWorkflowAdapter,
    build_default_adapter_registry,
    build_default_activity_executor,
    build_default_workflow_registry,
)

__all__ = [
    *_framework_all,
    "HuaweiVrpPackageUpgradeProvider",
    "HuaweiVrpWorkflowAdapter",
    "build_default_adapter_registry",
    "build_default_activity_executor",
    "build_default_workflow_registry",
]
