"""Short-lived device leases used to fence task-owned write operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import threading
from uuid import uuid4

from device_tui.application.errors import ApplicationConflictError, ResourceNotFoundError


@dataclass(frozen=True, slots=True)
class DeviceLease:
    device_id: str
    owner_id: str
    token: str
    expires_at: str


class DeviceLeaseService:
    """In-process fencing leases for task-owned device mutations.

    The lease is deliberately independent of the device repository.  A task can
    therefore reserve a device before opening a session, while stale leases are
    naturally invalidated after a process restart or timeout.
    """

    def __init__(self, *, ttl_seconds: int = 900, clock=None) -> None:
        self._ttl_seconds = max(30, min(int(ttl_seconds), 86_400))
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._leases: dict[str, DeviceLease] = {}
        self._lock = threading.RLock()

    def acquire(self, device_id: str, owner_id: str) -> DeviceLease:
        device_id = str(device_id).strip()
        owner_id = str(owner_id).strip()
        if not device_id or not owner_id:
            raise ValueError("device_id and owner_id are required")
        with self._lock:
            self._expire_locked()
            current = self._leases.get(device_id)
            if current is not None and current.owner_id != owner_id:
                raise ApplicationConflictError(
                    "设备正在被另一个任务占用。",
                    details={"device_id": device_id, "owner_id": current.owner_id},
                )
            token = current.token if current is not None else str(uuid4())
            lease = DeviceLease(device_id, owner_id, token, self._expires_at())
            self._leases[device_id] = lease
            return lease

    def renew(self, device_id: str, token: str) -> DeviceLease:
        with self._lock:
            lease = self._require_locked(device_id, token)
            renewed = DeviceLease(lease.device_id, lease.owner_id, lease.token, self._expires_at())
            self._leases[device_id] = renewed
            return renewed

    def validate(self, device_id: str, token: str) -> DeviceLease:
        with self._lock:
            return self._require_locked(device_id, token)

    def release(self, device_id: str, token: str) -> bool:
        with self._lock:
            lease = self._leases.get(str(device_id).strip())
            if lease is None or lease.token != str(token):
                return False
            self._leases.pop(lease.device_id, None)
            return True

    def get(self, device_id: str) -> DeviceLease | None:
        with self._lock:
            self._expire_locked()
            return self._leases.get(str(device_id).strip())

    def _require_locked(self, device_id: str, token: str) -> DeviceLease:
        self._expire_locked()
        lease = self._leases.get(str(device_id).strip())
        if lease is None or lease.token != str(token):
            raise ResourceNotFoundError(
                "设备租约不存在或已过期。",
                details={"device_id": str(device_id), "lease_token": "invalid"},
            )
        return lease

    def _expire_locked(self) -> None:
        now = self._clock()
        expired = [device_id for device_id, lease in self._leases.items() if _parse(lease.expires_at) <= now]
        for device_id in expired:
            self._leases.pop(device_id, None)

    def _expires_at(self) -> str:
        return (self._clock() + timedelta(seconds=self._ttl_seconds)).isoformat()


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)
