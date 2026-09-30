"""Public data contracts for managed file transfer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TransferSettings:
    protocol: str
    host: str
    advertised_host: str
    port: int
    root: str
    username: str
    writable: bool
    has_password: bool
    service_running: bool
    bound_port: int
    idle_stop_at: str = ""


@dataclass(frozen=True, slots=True)
class PreparedTransferSource:
    path: Path
    relative_path: str
    name: str
    size_bytes: int
    fingerprint: tuple[int, int]
    protocol: str = ""
    host: str = ""
    port: int = 0
