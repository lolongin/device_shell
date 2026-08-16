"""Shared fixtures for testing."""
from __future__ import annotations

import pytest

from device_tui.domain.devices.models import Device
from device_tui.device_sources.sample import SampleDeviceRepository


@pytest.fixture
def sample_repo() -> SampleDeviceRepository:
    return SampleDeviceRepository()


@pytest.fixture
def sample_device() -> Device:
    return Device(
        id="TEST-001",
        name="Test-Device",
        domain="测试",
        device_type="Router",
        cpu="ARM-1",
        status="空闲",
        owner=None,
        ssh_ip="10.0.0.1",
        telnet_ip="10.0.0.1",
        username="admin",
        password="secret",
        vendor="TestCorp",
        model="T-1000",
        site="TestLab",
        rack="R01-U01",
        version="v1.0",
        notes="Test device",
    )
