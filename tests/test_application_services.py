from __future__ import annotations

import asyncio
from dataclasses import asdict
from pathlib import Path

import pytest

from device_tui.application import (
    SIMULATED_DEVICE_ID,
    ResourceNotFoundError,
    UnsupportedOperationError,
    build_desktop_application,
    create_simulated_device,
)
from device_tui.interfaces.desktop_api.session_hub import SessionHub
from device_tui.device_sources.sample import SampleDeviceRepository


def _application():
    return build_desktop_application(SampleDeviceRepository(), SessionHub())


def test_device_inventory_is_credential_free_by_construction() -> None:
    inventory = _application().devices.list_inventory()

    assert inventory.devices
    encoded_keys = " ".join(asdict(inventory.devices[0])).lower()
    assert "password" not in encoded_keys
    assert "username" not in encoded_keys


def test_device_inventory_appends_one_canonical_simulated_terminal() -> None:
    class RepositoryWithDuplicateSimulator(SampleDeviceRepository):
        def fetch_devices(self):
            return [
                *super().fetch_devices(),
                create_simulated_device(),
                create_simulated_device(),
            ]

    application = build_desktop_application(
        RepositoryWithDuplicateSimulator(),
        SessionHub(),
    )
    inventory = application.devices.list_inventory()
    simulated = [
        device for device in inventory.devices if device.id == SIMULATED_DEVICE_ID
    ]

    assert len(inventory.devices) == 22
    assert len(simulated) == 1
    assert inventory.devices[-1] == simulated[0]
    assert simulated[0].row_id == "SIM-TERMINAL::0000"
    assert simulated[0].name == "模拟终端"
    assert simulated[0].domain == "测试"
    assert simulated[0].is_simulated is True
    assert simulated[0].ssh_endpoint is None
    assert simulated[0].telnet_endpoint is None
    assert simulated[0].serial_endpoint is None
    assert simulated[0].serial_display == ""
    assert simulated[0].can_connect_ssh is False
    assert simulated[0].can_connect_telnet is False
    assert simulated[0].can_connect_serial is False
    assert simulated[0].can_claim is False
    assert simulated[0].can_release is False
    assert simulated[0].can_power_off is False


def test_device_inventory_preserves_authoritative_unique_owned_device_ids() -> None:
    class RepositoryWithAuthoritativeOccupancy(SampleDeviceRepository):
        def fetch_owned_device_ids(self) -> set[str]:
            return {"MOCK-LAB-000", "XTN-NJ-018", SIMULATED_DEVICE_ID}

    application = build_desktop_application(
        RepositoryWithAuthoritativeOccupancy(),
        SessionHub(),
    )
    inventory = application.devices.list_inventory()
    mock = next(device for device in inventory.devices if device.id == "MOCK-LAB-000")
    frame_rows = [device for device in inventory.devices if device.id == "XTN-NJ-018"]

    assert inventory.owned_device_ids == ("MOCK-LAB-000", "XTN-NJ-018")
    assert mock.owner is None
    assert mock.can_release is True
    assert mock.can_claim is False
    assert all(device.can_release for device in frame_rows)
    assert SIMULATED_DEVICE_ID not in inventory.owned_device_ids


@pytest.mark.parametrize("action", ["claim", "release", "toggle", "power_off"])
def test_simulated_terminal_rejects_device_operations(action: str) -> None:
    application = _application()

    with pytest.raises(UnsupportedOperationError) as error:
        getattr(application.devices, action)(SIMULATED_DEVICE_ID)

    assert error.value.details == {
        "device_id": SIMULATED_DEVICE_ID,
        "action": action,
    }


def test_simulated_terminal_only_resolves_simulated_sessions() -> None:
    application = _application()

    target = application.credentials.resolve(SIMULATED_DEVICE_ID, "simulated")

    assert target.device_id == SIMULATED_DEVICE_ID
    assert target.protocol == "simulated"
    assert target.credentials == ()
    with pytest.raises(UnsupportedOperationError):
        application.credentials.resolve(SIMULATED_DEVICE_ID, "ssh")


def test_session_service_creates_dedicated_simulated_terminal() -> None:
    async def scenario() -> None:
        application = _application()
        session = await application.sessions.create(
            SIMULATED_DEVICE_ID,
            "simulated",
        )

        assert session.device_id == SIMULATED_DEVICE_ID
        assert session.kind == "simulated"
        await application.sessions.close_all()

    asyncio.run(scenario())


def test_session_service_validates_device_and_protocol() -> None:
    async def scenario() -> None:
        application = _application()
        device_id = application.devices.list_inventory().devices[0].id

        with pytest.raises(ResourceNotFoundError):
            await application.sessions.create("missing-device", "simulated")
        with pytest.raises(UnsupportedOperationError):
            await application.sessions.create(device_id, "invalid")
        await application.sessions.close_all()

    asyncio.run(scenario())


def test_session_lifecycle_publishes_versioned_events() -> None:
    async def scenario() -> None:
        application = _application()
        device_id = application.devices.list_inventory().devices[0].id
        queue, replay = application.events.subscribe()
        assert replay == []

        session = await application.sessions.create(device_id, "simulated")
        created = await asyncio.wait_for(queue.get(), timeout=1)
        assert created.type == "session.created"
        assert created.resource_id == session.id
        assert created.to_payload()["version"] == 1

        await application.sessions.close(session.id)
        closed = await asyncio.wait_for(queue.get(), timeout=1)
        assert closed.type == "session.closed"
        assert closed.sequence > created.sequence
        application.events.unsubscribe(queue)

    asyncio.run(scenario())


def test_credential_resolver_keeps_secret_out_of_repr() -> None:
    application = _application()
    device_id = application.devices.list_inventory().devices[0].id

    target = application.credentials.resolve(device_id, "ssh")

    assert target.host
    assert target.credentials
    assert target.credentials[0].password not in repr(target)
    assert "password" not in repr(target).lower()


def test_settings_store_copies_mutable_values() -> None:
    application = _application()
    value = {"tabs": ["one"]}
    application.settings.set("workspace", value)
    value["tabs"].append("two")

    assert application.settings.get("workspace") == {"tabs": ["one"]}


def test_application_layer_has_no_qt_dependency() -> None:
    application_root = (
        Path(__file__).resolve().parents[1] / "device_tui" / "application"
    )
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in application_root.rglob("*.py")
    ).casefold()

    assert "pyside6" not in source
    assert "device_tui.interfaces.desktop_api" not in source


def test_device_service_claim_and_release_return_updated_snapshot() -> None:
    application = _application()
    device = next(
        candidate
        for candidate in application.devices.list_inventory().devices
        if candidate.owner is None
        and ("idle" in candidate.status.casefold() or "空闲" in candidate.status)
    )

    claimed = application.devices.claim(device.id)
    released = application.devices.release(device.id)

    assert claimed.device.owner == application.devices.list_inventory().current_user
    assert claimed.inventory.current_user == application.devices.list_inventory().current_user
    assert claimed.action == "claim"
    assert released.device.owner is None
    assert released.action == "release"


def test_frame_occupancy_action_returns_all_updated_board_rows() -> None:
    application = _application()

    released = application.devices.release("XTN-NJ-018")
    released_boards = [
        device for device in released.inventory.devices if device.id == "XTN-NJ-018"
    ]
    claimed = application.devices.claim("XTN-NJ-018")
    claimed_boards = [
        device for device in claimed.inventory.devices if device.id == "XTN-NJ-018"
    ]

    assert len(released_boards) == 4
    assert all(device.owner is None and device.can_claim for device in released_boards)
    assert len(claimed_boards) == 4
    assert all(device.owner == claimed.inventory.current_user for device in claimed_boards)
    assert all(device.can_release for device in claimed_boards)
