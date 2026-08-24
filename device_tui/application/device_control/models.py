"""Transport-neutral requests and results for device control."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True, slots=True)
class DeviceTarget:
    """A stable device reference; session_id takes precedence when present."""

    device_id: str = ""
    session_id: str = ""
    protocol: str = "auto"


@dataclass(frozen=True, slots=True)
class ControlContext:
    source: str = "unknown"
    request_id: str = ""
    idempotency_key: str = ""
    actor: str = ""
    approval_token: str = ""
    lease_token: str = ""
    task_id: str = ""
    step_id: str = ""
    operation_callback: Callable[[str, str], None] | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class SessionView:
    session_id: str
    device_id: str
    protocol: str
    status: str
    title: str = ""
    sequence: int = 0
    generation: int = 0
    reused: bool = False


@dataclass(frozen=True, slots=True)
class CommandRequest:
    commands: tuple[str, ...] = ()
    mode: str = "batch"
    timeout_seconds: int = 30
    total_timeout_seconds: float | None = None
    max_output_chars: int = 16_384
    steps: tuple[dict[str, object], ...] = ()
    require_confirmation: bool = False


@dataclass(frozen=True, slots=True)
class SendResult:
    session_id: str
    device_id: str
    sent: bool


@dataclass(frozen=True, slots=True)
class BroadcastResult:
    session_ids: tuple[str, ...]
    command: str


@dataclass(frozen=True, slots=True)
class CommandResult:
    operation_id: str
    execution_id: str
    session_id: str
    device_id: str
    status: str
    output: str = ""
    error_code: str = ""
    steps: tuple[dict[str, object], ...] = ()
    duration_ms: float = 0
    data: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TransferRequest:
    direction: str
    source_path: str
    destination_path: str
    overwrite: bool = False
    terminal_environment: str = "auto"
    command_mode: str = "vrp"


@dataclass(frozen=True, slots=True)
class PackageUpgradeRequest:
    package_path: str
    package_source: str = "local"
    include_slave: bool = True
    standby_required: bool = False
    auto_delete_old_packages: bool = True
    reboot_after_setting: bool = False
    master_storage: str = ""
    slave_storage: str = ""
    driver_id: str = "auto"


@dataclass(frozen=True, slots=True)
class OperationView:
    operation_id: str
    kind: str
    device_id: str
    session_id: str
    status: str
    stage: str
    message: str
    progress_percent: int = 0
    direction: str = ""
    bytes_transferred: int = 0
    total_bytes: int = 0
    bytes_per_second: int = 0
    eta_seconds: int | None = None
    queue_position: int | None = None
    retry_of: str | None = None
    cancellable: bool = True
    revision: int = 0
    created_at: str = ""
    updated_at: str = ""
    error_code: str = ""
    data: dict[str, object] = field(default_factory=dict)
