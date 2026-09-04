"""Credential and connection-target boundary for session infrastructure."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from device_tui.domain.devices.models import Device
from device_tui.domain.devices.repository import DeviceRepository
from .errors import ResourceNotFoundError, UnsupportedOperationError
from .simulator import SIMULATED_DEVICE_ID


SessionProtocol = Literal["simulated", "ssh", "telnet", "serial"]


@dataclass(frozen=True, slots=True)
class SessionCredential:
    username: str
    password: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ConnectionTarget:
    device_id: str
    protocol: SessionProtocol
    host: str
    port: int
    credentials: tuple[SessionCredential, ...] = field(default_factory=tuple, repr=False)


class CredentialResolver(Protocol):
    def resolve(self, device_id: str, protocol: SessionProtocol) -> ConnectionTarget: ...


class RepositoryCredentialResolver:
    """Resolve repository credentials for backend-owned connection workflows."""

    def __init__(self, repository: DeviceRepository) -> None:
        self._repository = repository

    def resolve(self, device_id: str, protocol: SessionProtocol) -> ConnectionTarget:
        if device_id == SIMULATED_DEVICE_ID:
            if protocol != "simulated":
                raise UnsupportedOperationError(
                    f"The simulated terminal does not support {protocol} sessions.",
                    details={"device_id": device_id, "protocol": protocol},
                )
            return ConnectionTarget(
                device_id=SIMULATED_DEVICE_ID,
                protocol="simulated",
                host="",
                port=0,
            )
        device = self._find_device(device_id)
        if protocol == "simulated":
            return ConnectionTarget(device_id=device.id, protocol=protocol, host="", port=0)
        if protocol == "telnet":
            return self._target(
                device,
                protocol,
                device.telnet_ip,
                device.telnet_port,
                [(device.username, device.password)],
            )
        if protocol == "serial":
            return self._target(
                device,
                protocol,
                device.serial_ip,
                device.serial_port,
                [
                    (
                        device.serial_username or device.username,
                        device.serial_password or device.password,
                    )
                ],
            )
        if protocol == "ssh":
            username = device.ssh_username or device.username
            password = device.ssh_password or device.password
            candidates = [("root", "root"), ("root", "huawei"), (username, password)]
            return self._target(
                device,
                protocol,
                device.ssh_ip,
                device.ssh_port,
                candidates,
            )
        raise UnsupportedOperationError(
            f"Unsupported session protocol: {protocol}",
            details={"protocol": protocol},
        )

    def _find_device(self, device_id: str) -> Device:
        for device in self._repository.fetch_devices():
            if device.id == device_id:
                return device
        raise ResourceNotFoundError(
            f"Unknown device: {device_id}",
            details={"resource": "device", "device_id": device_id},
        )

    @staticmethod
    def _target(
        device: Device,
        protocol: SessionProtocol,
        host: str,
        port: int,
        candidates: list[tuple[str, str]],
    ) -> ConnectionTarget:
        normalized_host = host.strip()
        if not normalized_host:
            raise UnsupportedOperationError(
                f"Device has no {protocol} endpoint: {device.id}",
                details={"device_id": device.id, "protocol": protocol},
            )
        credentials: list[SessionCredential] = []
        for username, password in candidates:
            candidate = SessionCredential(username.strip(), password)
            username_required = protocol != "serial"
            if (
                (username_required and not candidate.username)
                or not candidate.password
                or candidate in credentials
            ):
                continue
            credentials.append(candidate)
        if not credentials:
            raise UnsupportedOperationError(
                f"Device has no usable {protocol} credentials: {device.id}",
                details={"device_id": device.id, "protocol": protocol},
            )
        return ConnectionTarget(
            device_id=device.id,
            protocol=protocol,
            host=normalized_host,
            port=port,
            credentials=tuple(credentials),
        )
