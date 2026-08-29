"""Resource coordination for Task and Workflow execution.

The coordinator is deliberately transport agnostic.  A device lease service
can back device resources while the same contract can later coordinate
sessions, subprocesses, and transfer operations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import threading
from typing import Protocol
from uuid import uuid4

from device_tui.application.errors import ApplicationConflictError


@dataclass(frozen=True, slots=True)
class ResourceRequest:
    kind: str
    resource_id: str
    owner_id: str
    ttl_seconds: int = 900

    def __post_init__(self) -> None:
        if not str(self.kind).strip() or not str(self.resource_id).strip() or not str(self.owner_id).strip():
            raise ValueError("resource kind, resource_id, and owner_id are required")
        if self.ttl_seconds < 1:
            raise ValueError("resource ttl_seconds must be positive")


@dataclass(frozen=True, slots=True)
class ResourceLease:
    kind: str
    resource_id: str
    owner_id: str
    token: str
    expires_at: str


class ResourceCoordinator(Protocol):
    def acquire(self, request: ResourceRequest) -> ResourceLease: ...

    def renew(self, lease: ResourceLease) -> ResourceLease: ...

    def release(self, lease: ResourceLease) -> bool: ...

    def release_owner(self, owner_id: str) -> int: ...


class LeaseResourceCoordinator:
    """Coordinate resource claims with optional device-lease persistence.

    Acquisition by the same owner is re-entrant.  Reference counting is
    important when a Task owns a device and each child Workflow acquires the
    same device through the runtime.
    """

    def __init__(self, *, device_leases=None, default_ttl_seconds: int = 900, clock=None) -> None:
        self._device_leases = device_leases
        self._default_ttl_seconds = max(1, int(default_ttl_seconds))
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._claims: dict[tuple[str, str], ResourceLease] = {}
        self._refs: dict[tuple[str, str, str], int] = {}
        self._lock = threading.RLock()

    def acquire(self, request: ResourceRequest) -> ResourceLease:
        kind = str(request.kind).strip()
        resource_id = str(request.resource_id).strip()
        owner_id = str(request.owner_id).strip()
        key = (kind, resource_id)
        owner_key = (kind, resource_id, owner_id)
        with self._lock:
            self._expire_locked()
            current = self._claims.get(key)
            if current is not None and current.owner_id != owner_id:
                raise ApplicationConflictError(
                    "资源正在被另一个任务占用。",
                    details={
                        "resource_kind": kind,
                        "resource_id": resource_id,
                        "owner_id": current.owner_id,
                    },
                )
            token = current.token if current is not None else str(uuid4())
            if kind == "device" and self._device_leases is not None:
                backend = self._device_leases.acquire(resource_id, owner_id)
                token = str(getattr(backend, "token", token))
                expires_at = str(getattr(backend, "expires_at", self._expires_at(request.ttl_seconds)))
            else:
                expires_at = self._expires_at(request.ttl_seconds)
            lease = ResourceLease(kind, resource_id, owner_id, token, expires_at)
            self._claims[key] = lease
            self._refs[owner_key] = self._refs.get(owner_key, 0) + 1
            return lease

    def renew(self, lease: ResourceLease) -> ResourceLease:
        key = (lease.kind, lease.resource_id)
        with self._lock:
            self._expire_locked()
            current = self._claims.get(key)
            if current is None or current.token != lease.token or current.owner_id != lease.owner_id:
                raise ValueError("resource lease is no longer valid")
            if lease.kind == "device" and self._device_leases is not None:
                backend = self._device_leases.renew(lease.resource_id, lease.token)
                renewed = ResourceLease(
                    lease.kind,
                    lease.resource_id,
                    lease.owner_id,
                    lease.token,
                    str(getattr(backend, "expires_at", self._expires_at(self._default_ttl_seconds))),
                )
            else:
                renewed = ResourceLease(
                    lease.kind,
                    lease.resource_id,
                    lease.owner_id,
                    lease.token,
                    self._expires_at(self._default_ttl_seconds),
                )
            self._claims[key] = renewed
            return renewed

    def release(self, lease: ResourceLease) -> bool:
        key = (lease.kind, lease.resource_id)
        owner_key = (lease.kind, lease.resource_id, lease.owner_id)
        with self._lock:
            current = self._claims.get(key)
            if current is None or current.token != lease.token or current.owner_id != lease.owner_id:
                return False
            refs = self._refs.get(owner_key, 0)
            if refs > 1:
                self._refs[owner_key] = refs - 1
                return True
            self._refs.pop(owner_key, None)
            self._claims.pop(key, None)
            if lease.kind == "device" and self._device_leases is not None:
                return bool(self._device_leases.release(lease.resource_id, lease.token))
            return True

    def release_owner(self, owner_id: str) -> int:
        owner_id = str(owner_id).strip()
        released = 0
        with self._lock:
            leases = [lease for lease in self._claims.values() if lease.owner_id == owner_id]
        for lease in leases:
            while self.release(lease):
                released += 1
                with self._lock:
                    if (lease.kind, lease.resource_id, lease.owner_id) not in self._refs:
                        break
        return released

    def _expire_locked(self) -> None:
        now = self._clock()
        expired: list[tuple[str, str]] = []
        for key, lease in self._claims.items():
            expired_at = _parse_time(lease.expires_at)
            backend_get = getattr(self._device_leases, "get", None)
            backend_missing = (
                lease.kind == "device"
                and callable(backend_get)
                and backend_get(lease.resource_id) is None
            )
            if expired_at <= now or backend_missing:
                expired.append(key)
        for key in expired:
            lease = self._claims.pop(key)
            self._refs.pop((lease.kind, lease.resource_id, lease.owner_id), None)

    def _expires_at(self, ttl_seconds: int) -> str:
        return (self._clock() + timedelta(seconds=max(1, int(ttl_seconds)))).isoformat()


__all__ = ["LeaseResourceCoordinator", "ResourceCoordinator", "ResourceLease", "ResourceRequest"]


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
