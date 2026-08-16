"""Tests for local temporary device helpers."""

from __future__ import annotations

from device_tui.domain.devices.temporary import (
    TEMPORARY_DEVICE_DOMAIN,
    deserialize_temporary_device,
    is_temporary_device,
    make_temporary_device,
    next_temporary_device_id,
    serialize_temporary_device,
)


def test_make_temporary_device_sets_local_marker() -> None:
    device = make_temporary_device(
        device_id="TEMP-10-0-0-1",
        name="Temp Router",
        telnet_ip="10.0.0.1",
        telnet_port=23,
        ssh_ip="10.0.0.1",
        ssh_port=22,
        telnet_username="admin",
        telnet_password="secret",
        ssh_username="linux",
        ssh_password="linux-secret",
    )

    assert device.domain == TEMPORARY_DEVICE_DOMAIN
    assert device.supports_power_off is False
    assert is_temporary_device(device)


def test_next_temporary_device_id_deduplicates_by_suffix() -> None:
    existing = {"TEMP-10-0-0-1", "TEMP-10-0-0-1-2"}

    assert next_temporary_device_id(existing, "10.0.0.1") == "TEMP-10-0-0-1-3"


def test_temporary_device_round_trips_desktop_state_payload() -> None:
    device = make_temporary_device(
        device_id="TEMP-SSH",
        name="Temp SSH",
        telnet_ip="",
        telnet_port=23,
        ssh_ip="192.0.2.10",
        ssh_port=2222,
        serial_ip="192.0.2.11",
        serial_port=2023,
        serial_password="serial-secret",
        telnet_username="ops",
        telnet_password="secret",
        ssh_username="linux.ops",
        ssh_password="ssh-secret",
        notes="one-off access",
        created_at="2026-05-16T00:00:00+00:00",
        preferred_kind="linux",
    )

    restored = deserialize_temporary_device(serialize_temporary_device(device))

    assert restored is not None
    assert restored.id == device.id
    assert restored.ssh_ip == "192.0.2.10"
    assert restored.ssh_port == 2222
    assert restored.serial_ip == "192.0.2.11"
    assert restored.serial_port == 2023
    assert restored.serial_username == ""
    assert restored.serial_password == "serial-secret"
    assert restored.username == "ops"
    assert restored.password == "secret"
    assert restored.ssh_username == "linux.ops"
    assert restored.ssh_password == "ssh-secret"
    assert restored.extra["created_at"] == "2026-05-16T00:00:00+00:00"
    assert restored.extra["preferred_kind"] == "linux"


def test_deserialize_rejects_missing_id() -> None:
    assert deserialize_temporary_device({"name": "No id"}) is None
