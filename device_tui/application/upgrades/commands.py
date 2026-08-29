"""Compatibility imports for the relocated Huawei vendor adapter.

New code should import command profiles from
``infrastructure.vendor_adapters.huawei_vrp``.  This module remains so older
plugins and external integrations can migrate without a flag day.
"""

from device_tui.infrastructure.vendor_adapters.huawei_vrp.commands import (
    CommandPlan,
    HuaweiVrpCommandSet,
    HuaweiVrpDeviceCommandProfile,
)

__all__ = ["CommandPlan", "HuaweiVrpCommandSet", "HuaweiVrpDeviceCommandProfile"]
