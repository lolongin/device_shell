"""Validation and terminal-plan helpers for App-managed file transfers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import os
from pathlib import Path, PurePosixPath
import re
import shlex
from typing import Any

from device_tui.infrastructure.vendor_adapters.huawei_vrp.parsers import PackageFileEntry, parse_dir_entries


MAX_TRANSFER_FILES = 1_000
MAX_TRANSFER_FILE_SCAN = 10_000
_DEVICE_STORAGE_RE = re.compile(
    r"^[A-Za-z0-9_.-]+(?:#[A-Za-z0-9_.-]+)?:/(?:[^/\\\x00-\x1f]+/)*[^/\\\x00-\x1f]+$"
)
TERMINAL_ENVIRONMENTS = frozenset({"auto", "linux", "vrp"})
_LINUX_MARKER_PREFIX = "__DEVICE_TUI_TRANSFER_"


@dataclass(frozen=True, slots=True)
class TransferInteractionProfile:
    """Device/client-specific terminal vocabulary for a managed transfer."""

    id: str = "generic-ftp"
    connect_template: str = "{protocol} {host} {port}"
    binary_command: str = "binary"
    download_template: str = "get {source} {destination}"
    upload_template: str = "put {source} {destination}"
    quit_command: str = "quit"
    host_key_prompt: str = "host_key_prompt"
    username_prompt: str = "username_prompt"
    password_prompt: str = "password_prompt"
    login_label: str = "本地自动登录文件服务"
    connect_timeout_code: str = "ftp_login_timeout"
    binary_timeout_code: str = "ftp_binary_prompt_timeout"
    transfer_timeout_code: str = "ftp_transfer_timeout"
    exit_timeout_code: str = "ftp_exit_timeout"


class ManagedTransferError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class SharedFileInfo:
    relative_path: str
    name: str
    size_bytes: int
    modified_at: str

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SharedFileCatalog:
    files: tuple[SharedFileInfo, ...]
    truncated: bool = False
    total: int = 0
    next_offset: int | None = None


def resolve_shared_root(root: Path) -> Path:
    try:
        resolved = root.expanduser().resolve(strict=True)
    except OSError as exc:
        raise ManagedTransferError(
            "transfer_root_unavailable",
            "文件传输共享目录不存在或不可访问。",
        ) from exc
    if not resolved.is_dir():
        raise ManagedTransferError(
            "transfer_root_unavailable",
            "文件传输共享路径不是目录。",
        )
    return resolved


def resolve_shared_file(root: Path, source_path: str) -> tuple[Path, SharedFileInfo]:
    resolved_root = resolve_shared_root(root)
    relative = _validate_relative_path(source_path, label="source_path")
    candidate = resolved_root.joinpath(*relative.parts)
    if candidate.is_symlink():
        raise ManagedTransferError(
            "transfer_source_outside_root",
            "源文件不能是符号链接。",
        )
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ManagedTransferError(
            "transfer_source_not_found",
            f"共享目录中不存在文件: {relative.as_posix()}",
        ) from exc
    if not resolved.is_relative_to(resolved_root):
        raise ManagedTransferError(
            "transfer_source_outside_root",
            "源文件超出文件传输共享目录。",
        )
    if not resolved.is_file():
        raise ManagedTransferError(
            "transfer_source_not_found",
            f"共享目录中的路径不是文件: {relative.as_posix()}",
        )
    try:
        stat = resolved.stat()
    except OSError as exc:
        raise ManagedTransferError(
            "transfer_source_not_found",
            f"无法读取源文件: {relative.as_posix()}",
        ) from exc
    return resolved, _file_info(relative, stat)


def list_shared_files(
    root: Path,
    *,
    relative_path: str = "",
    recursive: bool = True,
    limit: int = 200,
    query: str = "",
    sort: str = "name",
    order: str = "asc",
    offset: int = 0,
) -> SharedFileCatalog:
    resolved_root = resolve_shared_root(root)
    if not 1 <= limit <= MAX_TRANSFER_FILES:
        raise ManagedTransferError(
            "invalid_request",
            f"limit 必须在 1 到 {MAX_TRANSFER_FILES} 之间。",
        )
    relative = (
        _validate_relative_path(relative_path, label="path")
        if relative_path.strip()
        else PurePosixPath(".")
    )
    start = resolved_root.joinpath(*(() if relative == PurePosixPath(".") else relative.parts))
    try:
        resolved_start = start.resolve(strict=True)
    except OSError as exc:
        raise ManagedTransferError(
            "transfer_source_not_found",
            f"共享目录中不存在路径: {relative_path}",
        ) from exc
    if not resolved_start.is_relative_to(resolved_root) or start.is_symlink():
        raise ManagedTransferError(
            "transfer_source_outside_root",
            "枚举路径超出文件传输共享目录。",
        )
    if not resolved_start.is_dir():
        raise ManagedTransferError(
            "invalid_request",
            "枚举路径必须是共享目录中的子目录。",
        )

    normalized_query = query.strip().casefold()
    normalized_sort = sort.strip().casefold()
    normalized_order = order.strip().casefold()
    if normalized_sort not in {"name", "size", "modified"}:
        raise ManagedTransferError("invalid_request", "不支持的文件排序字段。")
    if normalized_order not in {"asc", "desc"}:
        raise ManagedTransferError("invalid_request", "文件排序方向必须是 asc 或 desc。")
    safe_offset = max(0, int(offset))
    files: list[SharedFileInfo] = []
    scan_truncated = False
    scanned = 0
    for directory, directory_names, file_names in os.walk(
        resolved_start,
        followlinks=False,
    ):
        directory_path = Path(directory)
        directory_names[:] = sorted(
            name
            for name in directory_names
            if not (directory_path / name).is_symlink()
        )
        for name in sorted(file_names):
            scanned += 1
            if scanned > MAX_TRANSFER_FILE_SCAN:
                scan_truncated = True
                break
            candidate = directory_path / name
            if candidate.is_symlink():
                continue
            try:
                resolved = candidate.resolve(strict=True)
                stat = resolved.stat()
            except OSError:
                continue
            if not resolved.is_file() or not resolved.is_relative_to(resolved_root):
                continue
            relative_file = PurePosixPath(resolved.relative_to(resolved_root).as_posix())
            info = _file_info(relative_file, stat)
            if normalized_query and normalized_query not in info.relative_path.casefold():
                continue
            files.append(info)
        if scan_truncated or not recursive:
            break
    key = {
        "name": lambda item: (item.name.casefold(), item.relative_path.casefold()),
        "size": lambda item: (item.size_bytes, item.relative_path.casefold()),
        "modified": lambda item: (item.modified_at, item.relative_path.casefold()),
    }[normalized_sort]
    files.sort(key=key, reverse=normalized_order == "desc")
    total = len(files)
    page = files[safe_offset : safe_offset + limit]
    next_offset = safe_offset + len(page) if safe_offset + len(page) < total else None
    return SharedFileCatalog(
        tuple(page),
        scan_truncated or next_offset is not None,
        total,
        next_offset,
    )


def validate_destination_path(destination_path: str) -> str:
    raw = destination_path.strip()
    if "\\" in raw:
        raise ManagedTransferError(
            "invalid_destination_path",
            "目标路径必须使用设备路径分隔符 /。",
        )
    normalized = raw
    if not normalized or not _DEVICE_STORAGE_RE.fullmatch(normalized):
        raise ManagedTransferError(
            "invalid_destination_path",
            "目标路径必须是包含文件名的设备绝对存储路径，例如 flash:/image.cc。",
        )
    tail = normalized.split(":/", 1)[1]
    if any(part in {"", ".", ".."} for part in tail.split("/")):
        raise ManagedTransferError(
            "invalid_destination_path",
            "目标路径不能包含空目录、. 或 ..。",
        )
    return normalized


def normalize_terminal_environment(value: str) -> str:
    normalized = value.strip().casefold() or "auto"
    if normalized not in TERMINAL_ENVIRONMENTS:
        raise ManagedTransferError(
            "invalid_terminal_environment",
            f"不支持的终端环境: {value}",
        )
    return normalized


def validate_linux_file_path(path: str) -> str:
    raw = path.strip()
    if not raw.startswith("/") or raw == "/":
        raise ManagedTransferError(
            "invalid_destination_path",
            "Linux 文件路径必须是包含文件名的绝对路径，例如 /tmp/image.cc。",
        )
    if any(ord(character) < 32 or character == "\x7f" for character in raw):
        raise ManagedTransferError(
            "invalid_destination_path",
            "Linux 文件路径不能包含控制字符。",
        )
    if any(part in {"", ".", ".."} for part in raw.split("/")[1:]):
        raise ManagedTransferError(
            "invalid_destination_path",
            "Linux 文件路径不能包含 . 或 ..。",
        )
    return PurePosixPath(raw).as_posix()


def validate_transfer_device_path(path: str, terminal_environment: str) -> str:
    environment = normalize_terminal_environment(terminal_environment)
    if environment == "vrp":
        return validate_destination_path(path)
    if environment == "linux":
        return validate_linux_file_path(path)
    try:
        return validate_destination_path(path)
    except ManagedTransferError:
        return validate_linux_file_path(path)


def infer_terminal_environment(path: str, *, session_kind: str = "") -> str:
    raw = path.strip()
    if _DEVICE_STORAGE_RE.fullmatch(raw):
        return "vrp"
    if raw.startswith("/"):
        return "linux"
    return "linux" if session_kind.strip().casefold() == "ssh" else "vrp"


def build_linux_inspection_command(path: str, protocol: str) -> str:
    normalized_path = validate_linux_file_path(path)
    normalized_protocol = protocol.strip().casefold()
    if normalized_protocol not in {"ftp", "sftp"}:
        raise ManagedTransferError(
            "invalid_request",
            f"不支持的文件传输协议: {protocol}",
        )
    quoted_path = shlex.quote(normalized_path)
    quoted_directory = shlex.quote(PurePosixPath(normalized_path).parent.as_posix())
    quoted_client = shlex.quote(normalized_protocol)
    prefix = _LINUX_MARKER_PREFIX
    return (
        f"if command -v {quoted_client} >/dev/null 2>&1; then printf '\\n{prefix}CLIENT__=1\\n'; "
        f"else printf '\\n{prefix}CLIENT__=0\\n'; fi; "
        f"if [ -f {quoted_path} ]; then printf '{prefix}SIZE__='; wc -c < {quoted_path}; "
        f"else printf '{prefix}MISSING__=1\\n'; fi; "
        f"if [ -d {quoted_directory} ]; then df -Pk {quoted_directory} 2>/dev/null | "
        f"awk 'END {{printf \"{prefix}FREE__=%.0f\\n\", $4 * 1024}}'; "
        f"else printf '{prefix}DIRECTORY__=0\\n'; fi"
    )


def linux_client_available(output: str) -> bool:
    return bool(re.search(rf"(?m)^{re.escape(_LINUX_MARKER_PREFIX)}CLIENT__=1\s*$", output))


def linux_file_size(output: str) -> int | None:
    match = re.search(
        rf"(?m)^{re.escape(_LINUX_MARKER_PREFIX)}SIZE__=(\d+)\s*$",
        output,
    )
    return int(match.group(1)) if match else None


def linux_free_space_bytes(output: str) -> int:
    match = re.search(
        rf"(?m)^{re.escape(_LINUX_MARKER_PREFIX)}FREE__=(\d+)\s*$",
        output,
    )
    return int(match.group(1)) if match else 0


def linux_directory_available(output: str) -> bool:
    return not bool(
        re.search(
            rf"(?m)^{re.escape(_LINUX_MARKER_PREFIX)}DIRECTORY__=0\s*$",
            output,
        )
    )


def destination_storage(destination_path: str) -> str:
    normalized = validate_destination_path(destination_path)
    return normalized.rsplit("/", 1)[0] + "/"


def destination_entry(
    output: str,
    destination_path: str,
) -> PackageFileEntry | None:
    normalized = validate_destination_path(destination_path)
    expected_name = PurePosixPath(normalized).name.casefold()
    for entry in parse_dir_entries(output, destination_storage(normalized)):
        if entry.name.casefold() == expected_name:
            return entry
    return None


def destination_matches(
    output: str,
    destination_path: str,
    expected_size: int,
) -> bool:
    entry = destination_entry(output, destination_path)
    return bool(entry is not None and entry.size_bytes == expected_size)


def source_fingerprint(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
    except OSError as exc:
        raise ManagedTransferError(
            "transfer_source_changed",
            "传输开始前源文件已不可访问。",
        ) from exc
    return stat.st_size, stat.st_mtime_ns


def quote_transfer_argument(value: str) -> str:
    if not any(character.isspace() or character in {'"', "'"} for character in value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _managed_transfer_connect_steps(
    protocol: str,
    host: str,
    port: int,
    responses: list[dict[str, Any]],
    timeout_seconds: int,
    terminal_environment: str = "vrp",
    connect_secret_ref: str = "",
    profile: TransferInteractionProfile | None = None,
    username_secret_ref: str = "",
    password_secret_ref: str = "",
) -> list[dict[str, Any]]:
    """Shared connect/login/binary-mode steps for App-managed FTP/SCP transfers."""
    normalized_protocol = protocol.strip().casefold()
    profile = profile or TransferInteractionProfile()
    prompt = "sftp_prompt" if normalized_protocol == "sftp" else "ftp_prompt"
    protocol_steps: list[dict[str, Any]] = []
    if normalized_protocol == "ftp":
        protocol_steps = [
            {"type": "send", "text": profile.binary_command, "label": "切换二进制模式"},
            {
                "type": "expect",
                "success": ["ftp_prompt"],
                "failures": ["500 ", "502 ", "Unknown FTP command", "Error:"],
                "timeout_seconds": 30,
                "label": "确认二进制模式",
                "timeout_code": profile.binary_timeout_code,
            },
        ]
    environment = normalize_terminal_environment(terminal_environment)
    if environment == "auto":
        environment = "vrp"
    if environment == "linux" and normalized_protocol == "sftp":
        if not connect_secret_ref:
            raise ManagedTransferError(
                "invalid_request",
                "Linux SFTP 连接缺少临时身份命令。",
            )
        connect_step: dict[str, Any] = {
            "type": "send",
            "secret_ref": connect_secret_ref,
            "secret_prefix": f"sftp -P {int(port)} ",
            "secret_suffix": f"@{shlex.quote(host)}",
            "label": "连接 SFTP 服务",
        }
    else:
        connect_step = {
            "type": "send",
            "text": profile.connect_template.format(protocol=normalized_protocol, host=host, port=int(port)),
            "label": f"连接 {normalized_protocol.upper()} 服务",
        }
    failures = [
        "Login incorrect",
        "Authentication failed",
        "Permission denied",
        "Host key verification failed",
        "530 ",
        "421 ",
    ]
    if normalized_protocol == "ftp" and username_secret_ref and password_secret_ref:
        # FTP login is deliberately modeled as separate protocol states. A
        # prompt is evidence that the device accepted the previous input;
        # output batching must not turn username and password into one
        # unordered response list.
        login_steps: list[dict[str, Any]] = [
            {
                "type": "expect",
                "success": [profile.username_prompt],
                "failures": failures,
                "timeout_seconds": timeout_seconds,
                "label": "等待 FTP 用户名提示",
                "timeout_code": f"{profile.connect_timeout_code}_username",
            },
            {
                "type": "send",
                "secret_ref": username_secret_ref,
                "label": "发送 FTP 用户名",
            },
            {
                "type": "expect",
                "success": [profile.password_prompt],
                "failures": failures,
                "timeout_seconds": timeout_seconds,
                "label": "等待 FTP 密码提示",
                "timeout_code": f"{profile.connect_timeout_code}_password",
            },
            {
                "type": "send",
                "secret_ref": password_secret_ref,
                "label": "发送 FTP 密码",
            },
            {
                "type": "expect",
                "success": [prompt, "ftp_prompt"],
                "failures": failures,
                "timeout_seconds": timeout_seconds,
                "label": profile.login_label,
                "timeout_code": profile.connect_timeout_code,
            },
        ]
    else:
        # SFTP may need a host-key response and different clients have
        # optional credential prompts, so retain its response-driven flow.
        login_steps = [
            {
                "type": "expect",
                "success": [prompt, "ftp_prompt"],
                "responses": responses,
                "failures": failures,
                "timeout_seconds": timeout_seconds,
                "label": profile.login_label,
                "timeout_code": profile.connect_timeout_code,
            }
        ]
    return [connect_step, *login_steps, *protocol_steps]


def _managed_transfer_login_responses(
    username_secret_ref: str = "file_transfer.username",
    password_secret_ref: str = "file_transfer.password",
    profile: TransferInteractionProfile | None = None,
) -> list[dict[str, Any]]:
    profile = profile or TransferInteractionProfile()
    return [
        {
            "match": profile.host_key_prompt,
            "text": "yes",
            "max_matches": 1,
        },
        {
            "match": profile.username_prompt,
            "secret_ref": username_secret_ref,
            "max_matches": 1,
        },
        {
            "match": profile.password_prompt,
            "secret_ref": password_secret_ref,
            "max_matches": 2,
        },
    ]


def build_managed_transfer_steps(
    *,
    protocol: str,
    host: str,
    port: int,
    source_path: str,
    destination_path: str,
    source_size: int,
    username_secret_ref: str = "file_transfer.username",
    password_secret_ref: str = "file_transfer.password",
    terminal_environment: str = "vrp",
    connect_secret_ref: str = "",
    profile: TransferInteractionProfile | None = None,
) -> tuple[list[dict[str, Any]], int]:
    normalized_protocol = protocol.strip().casefold()
    if normalized_protocol not in {"ftp", "sftp"}:
        raise ManagedTransferError(
            "invalid_request",
            f"不支持的文件传输协议: {protocol}",
        )
    transfer_timeout = min(
        3_500,
        max(120, int(source_size / (1024 * 1024)) * 2),
    )
    prompt = "sftp_prompt" if normalized_protocol == "sftp" else "ftp_prompt"
    source = quote_transfer_argument(source_path)
    destination = quote_transfer_argument(destination_path)
    profile = profile or TransferInteractionProfile()
    steps: list[dict[str, Any]] = [
        *_managed_transfer_connect_steps(
            normalized_protocol,
            host,
            port,
        _managed_transfer_login_responses(
            username_secret_ref,
            password_secret_ref,
            profile,
        ),
            timeout_seconds=45,
            terminal_environment=terminal_environment,
            connect_secret_ref=connect_secret_ref,
            profile=profile,
            username_secret_ref=username_secret_ref,
            password_secret_ref=password_secret_ref,
        ),
        {
            "type": "send",
            "text": profile.download_template.format(source=source, destination=destination),
            "label": f"下载 {source_path}",
        },
        {
            "type": "expect",
            "success": [prompt, "ftp_prompt"],
            "failures": [
                "Error:",
                "failed",
                "No such file",
                "not found",
                "timed out",
                "Connection closed",
                "500 ",
                "502 ",
                "550 ",
            ],
            "timeout_seconds": transfer_timeout,
            "label": "等待文件下载完成",
            "timeout_code": profile.transfer_timeout_code,
            "max_output_chars": 32_768,
        },
        {"type": "send", "text": profile.quit_command, "label": "退出文件客户端"},
        {
            "type": "expect",
            "success": ["device_prompt"],
            "failures": ["Error:", "500 ", "502 ", "550 "],
            "timeout_seconds": 30,
            "label": "返回设备命令行",
            "timeout_code": profile.exit_timeout_code,
        },
    ]
    return steps, min(3_600, transfer_timeout + 120)


def build_ftpget_command(
    *,
    username: str,
    password: str,
    host: str,
    source_path: str,
) -> str:
    """Build the one-shot device command used by simple ``ftpget`` clients."""
    normalized_host = host.strip()
    if not normalized_host:
        raise ManagedTransferError("service_endpoint_unavailable", "FTP 服务地址不能为空。")
    normalized_source = _validate_relative_path(
        source_path,
        label="source_path",
    ).as_posix()
    return " ".join((
        "ftpget",
        "-u",
        shlex.quote(username),
        "-p",
        shlex.quote(password),
        shlex.quote(normalized_host),
        shlex.quote(normalized_source),
    ))


def build_ftpget_transfer_steps(
    *,
    command_secret_ref: str,
    source_size: int,
) -> tuple[list[dict[str, Any]], int]:
    """Build a deterministic one-command FTP download plan for the device shell."""
    if not command_secret_ref.strip():
        raise ManagedTransferError("invalid_request", "ftpget 命令缺少受保护的运行时引用。")
    transfer_timeout = min(
        3_500,
        max(120, int(source_size / (1024 * 1024)) * 2),
    )
    steps: list[dict[str, Any]] = [
        {
            "type": "send",
            "secret_ref": command_secret_ref,
            "label": "发送 ftpget 单命令",
        },
        {
            "type": "expect",
            "success": ["device_prompt"],
            "failures": [
                "ftpget: usage:",
                "ftpget: Login incorrect",
                "ftpget: No such file",
                "Login incorrect",
                "Authentication failed",
                "Permission denied",
                "No such file",
                "not found",
                "timed out",
                "Connection refused",
                "Connection closed",
                "530 ",
                "550 ",
            ],
            "timeout_seconds": transfer_timeout,
            "label": "等待 ftpget 传输完成",
            "max_output_chars": 32_768,
        },
    ]
    return steps, min(3_600, transfer_timeout + 60)


def build_managed_transfer_download_steps(
    *,
    protocol: str,
    host: str,
    port: int,
    source_path: str,
    destination_path: str,
    source_size: int,
    username_secret_ref: str = "file_transfer.username",
    password_secret_ref: str = "file_transfer.password",
    terminal_environment: str = "vrp",
    connect_secret_ref: str = "",
    profile: TransferInteractionProfile | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Build FTP/SCP steps for a device->PC transfer (device 'put' to PC server)."""
    normalized_protocol = protocol.strip().casefold()
    if normalized_protocol not in {"ftp", "sftp"}:
        raise ManagedTransferError(
            "invalid_request",
            f"不支持的文件传输协议: {protocol}",
        )
    transfer_timeout = min(
        3_500,
        max(120, int(source_size / (1024 * 1024)) * 2),
    )
    prompt = "sftp_prompt" if normalized_protocol == "sftp" else "ftp_prompt"
    source = quote_transfer_argument(source_path)
    destination = quote_transfer_argument(destination_path)
    profile = profile or TransferInteractionProfile()
    steps: list[dict[str, Any]] = [
        *_managed_transfer_connect_steps(
            normalized_protocol,
            host,
            port,
            _managed_transfer_login_responses(
                username_secret_ref,
                password_secret_ref,
                profile,
            ),
            timeout_seconds=45,
            terminal_environment=terminal_environment,
            connect_secret_ref=connect_secret_ref,
            profile=profile,
        ),
        {
            "type": "send",
            "text": profile.upload_template.format(source=source, destination=destination),
            "label": f"上传 {source_path}",
        },
        {
            "type": "expect",
            "success": [prompt, "ftp_prompt"],
            "failures": [
                "Error:",
                "failed",
                "No such file",
                "not found",
                "timed out",
                "Connection closed",
                "500 ",
                "502 ",
                "550 ",
            ],
            "timeout_seconds": transfer_timeout,
            "label": "等待文件上传完成",
            "timeout_code": profile.transfer_timeout_code,
            "max_output_chars": 32_768,
        },
        {"type": "send", "text": profile.quit_command, "label": "退出文件客户端"},
        {
            "type": "expect",
            "success": ["device_prompt"],
            "failures": ["Error:", "500 ", "502 ", "550 "],
            "timeout_seconds": 30,
            "label": "返回设备命令行",
            "timeout_code": profile.exit_timeout_code,
        },
    ]
    return steps, min(3_600, transfer_timeout + 120)


def _validate_relative_path(value: str, *, label: str) -> PurePosixPath:
    normalized = value.strip().replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or normalized.startswith("./")
        or "/./" in normalized
        or normalized.endswith("/.")
        or path.is_absolute()
        or ":" in path.parts[0]
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ManagedTransferError(
            "transfer_source_outside_root",
            f"{label} 必须是共享目录内的相对路径。",
        )
    return path


def _file_info(relative: PurePosixPath, stat: os.stat_result) -> SharedFileInfo:
    modified_at = datetime.fromtimestamp(
        stat.st_mtime,
        tz=timezone.utc,
    ).isoformat()
    return SharedFileInfo(
        relative_path=relative.as_posix(),
        name=relative.name,
        size_bytes=stat.st_size,
        modified_at=modified_at,
    )
