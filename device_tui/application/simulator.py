"""Canonical definition for the local simulated terminal device."""

from __future__ import annotations

from device_tui.domain.devices.models import Device


SIMULATED_DEVICE_ID = "SIM-TERMINAL"


def create_simulated_device() -> Device:
    """Return the UI-independent device model used by every desktop client."""

    return Device(
        id=SIMULATED_DEVICE_ID,
        name="模拟终端",
        board_id="0000",
        domain="测试",
        device_type="本地终端",
        cpu="ARM",
        status="空闲",
        owner=None,
        ssh_ip="localhost",
        telnet_ip="localhost",
        username="sim",
        password="",
        vendor="本地",
        model="终端",
        site="本机",
        rack="-",
        version="V1.0",
        notes="本机终端，用于验证自动响应规则。",
    )


def is_simulated_device(device: Device) -> bool:
    return device.id == SIMULATED_DEVICE_ID
