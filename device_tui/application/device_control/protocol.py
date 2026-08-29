"""Ports for device-protocol-specific command selection and parsing.

The device-control facade owns target and transport coordination, but it does
not own a vendor's CLI vocabulary.  Concrete profiles are supplied by the
composition root; the compatibility profile keeps older direct callers
working while they migrate to an explicit profile.
"""

from __future__ import annotations

from typing import Protocol


class DeviceCommandProfile(Protocol):
    """Vendor port used by application services that need CLI semantics."""

    def version_query(self) -> str: ...

    def startup_query(self) -> str: ...

    def storage_query(self, storage: str) -> str: ...

    def activation_command(self, destination_path: str) -> str: ...

    def startup_package_matches(self, output: str, package_name: str) -> bool: ...

    def reboot_steps(self) -> tuple[dict[str, object], ...]: ...


class CompatibilityDeviceCommandProfile:
    """Minimal command profile for callers that do not provide a vendor port."""

    def version_query(self) -> str:
        return "display version"

    def startup_query(self) -> str:
        return "display startup"

    def storage_query(self, storage: str) -> str:
        return f"dir {storage}"

    def activation_command(self, destination_path: str) -> str:
        return f"startup system-software {destination_path}".rstrip()

    def startup_package_matches(self, output: str, package_name: str) -> bool:
        target = self._basename(package_name)
        if not target:
            return False
        for line in output.splitlines():
            lowered = line.casefold()
            if "next startup system software" not in lowered:
                continue
            value = line.split(":", 1)[1].strip() if ":" in line else line.rsplit(None, 1)[-1]
            return self._basename(value) == target
        return False

    def reboot_steps(self) -> tuple[dict[str, object], ...]:
        return (
            {"type": "send", "text": "reboot", "label": "发送 reboot"},
            {
                "type": "expect",
                "success": ["device_prompt", "login_prompt", "username_prompt"],
                "failures": [],
                "responses": [{"match": "confirmation_prompt", "text": "y", "max_matches": 3}],
                "disconnect_is_success": True,
                "timeout_seconds": 180,
                "label": "等待设备重启完成",
                "max_output_chars": 32_768,
            },
        )

    @staticmethod
    def _basename(value: str) -> str:
        return str(value).strip().replace("\\", "/").rsplit("/", 1)[-1].casefold()


__all__ = ["CompatibilityDeviceCommandProfile", "DeviceCommandProfile"]
