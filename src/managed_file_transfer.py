"""Validation and terminal-plan helpers for App-managed file transfers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any

from .package_upgrade import PackageFileEntry, parse_dir_entries


MAX_TRANSFER_FILES = 1_000
_DEVICE_STORAGE_RE = re.compile(
    r"^[A-Za-z0-9_.-]+(?:#[A-Za-z0-9_.-]+)?:/(?:[^/\\\x00-\x1f]+/)*[^/\\\x00-\x1f]+$"
)


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

    files: list[SharedFileInfo] = []
    truncated = False
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
            files.append(_file_info(relative_file, stat))
            if len(files) > limit:
                truncated = True
                break
        if truncated or not recursive:
            break
    files.sort(key=lambda item: item.relative_path.casefold())
    return SharedFileCatalog(tuple(files[:limit]), truncated)


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
) -> list[dict[str, Any]]:
    """Shared connect/login/binary-mode steps for App-managed FTP/SCP transfers."""
    normalized_protocol = protocol.strip().casefold()
    prompt = "sftp_prompt" if normalized_protocol == "sftp" else "ftp_prompt"
    protocol_steps: list[dict[str, Any]] = []
    if normalized_protocol == "ftp":
        protocol_steps = [
            {"type": "send", "text": "binary", "label": "切换二进制模式"},
            {
                "type": "expect",
                "success": ["ftp_prompt"],
                "failures": ["500 ", "502 ", "Unknown FTP command", "Error:"],
                "timeout_seconds": 30,
                "label": "确认二进制模式",
            },
        ]
    return [
        {
            "type": "send",
            "text": f"{normalized_protocol} {host} {port}",
            "label": f"连接 {normalized_protocol.upper()} 服务",
        },
        {
            "type": "expect",
            "success": [prompt, "ftp_prompt"],
            "responses": responses,
            "failures": [
                "Login incorrect",
                "Authentication failed",
                "Permission denied",
                "Host key verification failed",
                "530 ",
                "421 ",
            ],
            "timeout_seconds": timeout_seconds,
            "label": "本地自动登录文件服务",
        },
        *protocol_steps,
    ]


def _managed_transfer_login_responses() -> list[dict[str, Any]]:
    return [
        {
            "match": "host_key_prompt",
            "text": "yes",
            "max_matches": 1,
        },
        {
            "match": "username_prompt",
            "secret_ref": "file_transfer.username",
            "max_matches": 1,
        },
        {
            "match": "password_prompt",
            "secret_ref": "file_transfer.password",
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
    steps: list[dict[str, Any]] = [
        *_managed_transfer_connect_steps(
            normalized_protocol,
            host,
            port,
            _managed_transfer_login_responses(),
            timeout_seconds=45,
        ),
        {
            "type": "send",
            "text": f"get {source} {destination}",
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
            "max_output_chars": 32_768,
        },
        {"type": "send", "text": "quit", "label": "退出文件客户端"},
        {
            "type": "expect",
            "success": ["device_prompt"],
            "failures": ["Error:", "500 ", "502 ", "550 "],
            "timeout_seconds": 30,
            "label": "返回设备命令行",
        },
    ]
    return steps, min(3_600, transfer_timeout + 120)


def build_managed_transfer_download_steps(
    *,
    protocol: str,
    host: str,
    port: int,
    source_path: str,
    destination_path: str,
    source_size: int,
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
    steps: list[dict[str, Any]] = [
        *_managed_transfer_connect_steps(
            normalized_protocol,
            host,
            port,
            _managed_transfer_login_responses(),
            timeout_seconds=45,
        ),
        {
            "type": "send",
            "text": f"put {source} {destination}",
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
            "max_output_chars": 32_768,
        },
        {"type": "send", "text": "quit", "label": "退出文件客户端"},
        {
            "type": "expect",
            "success": ["device_prompt"],
            "failures": ["Error:", "500 ", "502 ", "550 "],
            "timeout_seconds": 30,
            "label": "返回设备命令行",
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
