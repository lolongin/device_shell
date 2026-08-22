"""Device inventory application service."""

from __future__ import annotations

from collections.abc import Callable, Set as AbstractSet
from dataclasses import dataclass, field
from datetime import datetime, timezone

from device_tui.domain.devices.models import Device
from device_tui.domain.devices.repository import (
    DeviceRepository,
    RepositoryConflictError,
    RepositoryError,
)
from device_tui.domain.devices.status import STATUS_OCCUPIED
from device_tui.domain.devices.temporary import is_temporary_device
from .errors import (
    ApplicationConflictError,
    ApplicationError,
    ResourceNotFoundError,
    UnsupportedOperationError,
)
from .simulator import (
    SIMULATED_DEVICE_ID,
    create_simulated_device,
    is_simulated_device,
)


def _endpoint(host: str, port: int) -> str | None:
    normalized = host.strip()
    return f"{normalized}:{port}" if normalized else None


def _parse_device_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        parsed = datetime.fromtimestamp(float(value), tz=timezone.utc)
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.isdigit():
            parsed = datetime.fromtimestamp(float(text), tz=timezone.utc)
        else:
            normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
            try:
                parsed = datetime.fromisoformat(normalized)
            except ValueError:
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
                    try:
                        parsed = datetime.strptime(text, fmt)
                        break
                    except ValueError:
                        parsed = None
                if parsed is None:
                    return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _occupancy_started_value(device: Device) -> datetime | None:
    for key in (
        "occupied_since",
        "occupied_at",
        "occupancy_started_at",
        "claimed_at",
        "claim_time",
        "owner_since",
        "since",
    ):
        parsed = _parse_device_datetime(device.extra.get(key))
        if parsed is not None:
            return parsed
    return None


def _occupancy_started_text(device: Device) -> str:
    value = _occupancy_started_value(device)
    if value is None:
        return ""
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _occupancy_duration_text(device: Device) -> str:
    if device.status != STATUS_OCCUPIED:
        return ""
    started_at = _occupancy_started_value(device)
    if started_at is None:
        return ""
    now = datetime.now(started_at.tzinfo or timezone.utc)
    seconds = max(0, int((now - started_at).total_seconds()))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _seconds = divmod(remainder, 60)
    if days:
        return f"{days}天{hours}小时"
    if hours:
        return f"{hours}小时{minutes}分"
    return f"{minutes}分"


def _status_text(device: Device) -> str:
    duration = _occupancy_duration_text(device)
    if duration and device.status == STATUS_OCCUPIED:
        return f"{device.status} {duration}"
    return device.status


def _presentation_tooltip(device: Device) -> str:
    parts = [
        f"设备: {device.name}",
        f"ID: {device.id}",
        f"板类型: {device.board_type or device.device_type or '-'}",
        f"CPU: {device.cpu or '-'}",
        f"Slot: {device.slot_id or '-'}",
        f"状态: {_status_text(device)}",
    ]
    if device.owner:
        parts.append(f"占用人: {device.owner}")
    started_text = _occupancy_started_text(device)
    if started_text:
        parts.append(f"开始时间: {started_text}")
    duration = _occupancy_duration_text(device)
    if duration:
        parts.append(f"占用时长: {duration}")
    return "\n".join(parts)


def _is_saved_server_device(device: Device) -> bool:
    return device.domain == "server"


def _is_my_occupied_device(
    device: Device,
    current_user: str,
    owned_device_ids: AbstractSet[str] | None = None,
) -> bool:
    if is_simulated_device(device) or is_temporary_device(device):
        return False
    if owned_device_ids is not None:
        return device.id in owned_device_ids
    return bool(current_user and device.owner == current_user)


def _can_view_serial_connection(
    device: Device,
    current_user: str,
    owned_device_ids: AbstractSet[str] | None = None,
) -> bool:
    if is_temporary_device(device):
        return bool(device.serial_ip.strip())
    return bool(
        device.serial_ip.strip()
        and _is_my_occupied_device(device, current_user, owned_device_ids)
    )


def _serial_display(
    device: Device,
    current_user: str,
    owned_device_ids: AbstractSet[str] | None = None,
) -> str:
    if is_simulated_device(device):
        return ""
    if _can_view_serial_connection(device, current_user, owned_device_ids):
        return f"{device.serial_ip.strip()}:{device.serial_port}"
    if is_temporary_device(device):
        return ""
    if (
        _is_my_occupied_device(device, current_user, owned_device_ids)
        and not device.serial_ip.strip()
    ):
        return "设备无串口 IP"
    return "占用后可见"


@dataclass(frozen=True, slots=True)
class DeviceSnapshot:
    """Credential-free device data safe for presentation adapters."""

    id: str
    row_id: str
    board_id: str
    name: str
    domain: str
    device_type: str
    cpu: str
    status: str
    owner: str | None
    vendor: str
    model: str
    site: str
    rack: str
    board_type: str
    slot: str
    status_text: str
    tooltip: str
    version: str
    ssh_endpoint: str | None
    telnet_endpoint: str | None
    serial_endpoint: str | None
    serial_display: str
    can_connect_telnet: bool
    can_connect_ssh: bool
    can_connect_serial: bool
    can_claim: bool
    can_release: bool
    can_power_off: bool
    is_simulated: bool
    is_temporary: bool
    is_saved_server: bool
    supports_power_off: bool
    source: str = "unknown"
    kind: str = "device"
    attributes: dict[str, object] = field(default_factory=dict)
    extensions: dict[str, object] = field(default_factory=dict)
    capabilities: dict[str, bool] = field(default_factory=dict)
    parent_id: str | None = None
    children: tuple[str, ...] = ()

    @classmethod
    def from_device(
        cls,
        device: Device,
        current_user: str = "",
        owned_device_ids: AbstractSet[str] | None = None,
    ) -> DeviceSnapshot:
        simulated = is_simulated_device(device)
        temporary = is_temporary_device(device)
        saved_server = _is_saved_server_device(device)
        telnet_endpoint = None if simulated else _endpoint(device.telnet_ip, device.telnet_port)
        ssh_endpoint = None if simulated else _endpoint(device.ssh_ip, device.ssh_port)
        serial_endpoint = None if simulated else _endpoint(device.serial_ip, device.serial_port)
        can_view_serial = _can_view_serial_connection(
            device,
            current_user,
            owned_device_ids,
        )
        if bool(device.extra.get("imported")):
            can_view_serial = bool(device.serial_ip.strip())
        occupied_by_me = _is_my_occupied_device(
            device,
            current_user,
            owned_device_ids,
        )
        supports_occupancy = bool(device.extra.get("supports_occupancy", True))
        board_id = device.board_id.strip()
        row_id = f"{device.id}::{board_id}" if board_id else device.id
        return cls(
            id=device.id,
            row_id=row_id,
            board_id=board_id,
            name=device.name,
            domain=device.domain,
            device_type=device.device_type,
            cpu=device.cpu,
            status=device.status,
            owner=device.owner,
            vendor=device.vendor,
            model=device.model,
            site=device.site,
            rack=device.rack,
            board_type=device.board_type or device.device_type,
            slot=device.slot_id,
            status_text=_status_text(device),
            tooltip=_presentation_tooltip(device),
            version=device.version,
            ssh_endpoint=ssh_endpoint,
            telnet_endpoint=telnet_endpoint,
            serial_endpoint=serial_endpoint,
            serial_display=_serial_display(device, current_user, owned_device_ids),
            can_connect_telnet=bool(telnet_endpoint and not simulated and not saved_server),
            can_connect_ssh=bool(ssh_endpoint and not simulated),
            can_connect_serial=bool(serial_endpoint and can_view_serial and not simulated and not saved_server),
            can_claim=bool(
                not simulated
                and not temporary
                and not saved_server
                and supports_occupancy
                and not occupied_by_me
                and device.owner is None
            ),
            can_release=bool(
                not simulated
                and not temporary
                and not saved_server
                and supports_occupancy
                and occupied_by_me
            ),
            can_power_off=bool(
                device.supports_power_off
                and occupied_by_me
                and not simulated
                and not temporary
                and supports_occupancy
            ),
            is_simulated=simulated,
            is_temporary=temporary,
            is_saved_server=saved_server,
            supports_power_off=device.supports_power_off,
            source=device.core_source,
            kind=device.core_kind,
            attributes=device.public_attributes,
            extensions=device.public_extensions(),
            capabilities={
                "claim": bool(
                    not simulated
                    and not temporary
                    and not saved_server
                    and supports_occupancy
                    and not occupied_by_me
                    and device.owner is None
                ),
                "release": bool(
                    not simulated
                    and not temporary
                    and not saved_server
                    and supports_occupancy
                    and occupied_by_me
                ),
                "power_off": bool(
                    device.supports_power_off
                    and occupied_by_me
                    and not simulated
                    and not temporary
                    and supports_occupancy
                ),
                "connect": bool(
                    ssh_endpoint or telnet_endpoint or serial_endpoint
                ),
            },
            parent_id=str(device.extra.get("parent_id") or "") or None,
            children=tuple(
                str(item).strip()
                for item in (device.extra.get("children") or ())
                if str(item).strip()
            ),
        )


@dataclass(frozen=True, slots=True)
class DeviceInventory:
    current_user: str
    owned_device_ids: tuple[str, ...]
    devices: tuple[DeviceSnapshot, ...]


@dataclass(frozen=True, slots=True)
class DeviceActionResult:
    device_id: str
    action: str
    message: str
    device: DeviceSnapshot
    inventory: DeviceInventory


class DeviceService:
    """Read device inventory without leaking repository credential fields."""

    def __init__(self, repository: DeviceRepository) -> None:
        self._repository = repository

    def list_inventory(self) -> DeviceInventory:
        fetched_devices = self._repository.fetch_devices()
        fetched_owned_device_ids = self._repository.fetch_owned_device_ids()
        current_user = self._repository.current_user()
        owned_device_ids = (
            {
                device.id
                for device in fetched_devices
                if current_user and device.owner == current_user
            }
            if fetched_owned_device_ids is None
            else set(fetched_owned_device_ids)
        )
        owned_device_ids.discard(SIMULATED_DEVICE_ID)
        # SIM-TERMINAL is an application-owned navigation item rather than a
        # repository record. Reserve its id, canonicalize it, and append it in
        # the stable final position expected by desktop navigation.
        repository_devices = [
            device
            for device in fetched_devices
            if device.id != SIMULATED_DEVICE_ID
        ]
        devices = [*repository_devices, create_simulated_device()]
        return DeviceInventory(
            current_user=current_user,
            owned_device_ids=tuple(sorted(owned_device_ids)),
            devices=tuple(
                DeviceSnapshot.from_device(device, current_user, owned_device_ids)
                for device in devices
            ),
        )

    def require_device(self, device_id: str) -> DeviceSnapshot:
        for device in self.list_inventory().devices:
            if device.id == device_id:
                return device
        raise ResourceNotFoundError(
            f"Unknown device: {device_id}",
            details={"resource": "device", "device_id": device_id},
        )

    def claim(self, device_id: str) -> DeviceActionResult:
        return self._run_action(device_id, "claim", self._repository.claim_device)

    def release(self, device_id: str) -> DeviceActionResult:
        return self._run_action(device_id, "release", self._repository.release_device)

    def toggle(self, device_id: str) -> DeviceActionResult:
        return self._run_action(device_id, "toggle", self._repository.toggle_device)

    def power_off(self, device_id: str) -> DeviceActionResult:
        return self._run_action(device_id, "power_off", self._repository.power_off_device)

    def _run_action(
        self,
        device_id: str,
        action: str,
        operation: Callable[[str, str], str],
    ) -> DeviceActionResult:
        device = self.require_device(device_id)
        if device.is_simulated:
            raise UnsupportedOperationError(
                "The simulated terminal does not support device operations.",
                details={"device_id": device_id, "action": action},
            )
        user = self._repository.current_user()
        if not user:
            raise ApplicationError("The current user is unavailable.")
        try:
            message = operation(device_id, user)
        except RepositoryConflictError as exc:
            raise ApplicationConflictError(
                str(exc),
                details={"device_id": device_id, "action": action},
            ) from exc
        except RepositoryError as exc:
            raise ApplicationError(
                str(exc),
                details={"device_id": device_id, "action": action},
            ) from exc
        inventory = self.list_inventory()
        updated_device = next(
            (device for device in inventory.devices if device.id == device_id),
            None,
        )
        if updated_device is None:
            raise ResourceNotFoundError(
                f"Unknown device after {action}: {device_id}",
                details={"resource": "device", "device_id": device_id},
            )
        return DeviceActionResult(
            device_id=device_id,
            action=action,
            message=str(message),
            device=updated_device,
            inventory=inventory,
        )
