"""Tests for managed file-transfer validation and plan construction."""

from __future__ import annotations

from pathlib import Path

import pytest

from device_tui.infrastructure.transfers.managed_file_transfer import (
    ManagedTransferError,
    build_ftpget_command,
    build_ftpget_transfer_steps,
    build_linux_inspection_command,
    build_managed_transfer_steps,
    destination_matches,
    infer_terminal_environment,
    list_shared_files,
    linux_client_available,
    linux_directory_available,
    linux_file_size,
    linux_free_space_bytes,
    resolve_shared_file,
    validate_linux_file_path,
    validate_destination_path,
    validate_transfer_device_path,
)
from device_tui.application.terminal.orchestration import parse_terminal_plan


def test_shared_file_catalog_returns_only_relative_metadata(tmp_path: Path) -> None:
    nested = tmp_path / "packages"
    nested.mkdir()
    package = nested / "target.cc"
    package.write_bytes(b"package")

    catalog = list_shared_files(tmp_path)

    assert [item.relative_path for item in catalog.files] == ["packages/target.cc"]
    assert catalog.files[0].name == "target.cc"
    assert catalog.files[0].size_bytes == 7
    assert str(tmp_path) not in str(catalog.files[0].public_dict())


@pytest.mark.parametrize(
    "source_path",
    ["../secret.cc", "/absolute.cc", "C:/secret.cc", "./target.cc"],
)
def test_shared_file_resolution_rejects_paths_outside_root(
    tmp_path: Path,
    source_path: str,
) -> None:
    with pytest.raises(ManagedTransferError) as error:
        resolve_shared_file(tmp_path, source_path)

    assert error.value.code == "transfer_source_outside_root"


def test_shared_file_catalog_supports_subdirectory_and_limit(tmp_path: Path) -> None:
    packages = tmp_path / "packages"
    packages.mkdir()
    (packages / "a.cc").write_bytes(b"a")
    (packages / "b.cc").write_bytes(b"bb")
    (tmp_path / "ignored.txt").write_text("ignored", encoding="utf-8")

    catalog = list_shared_files(
        tmp_path,
        relative_path="packages",
        recursive=False,
        limit=1,
    )

    assert [item.relative_path for item in catalog.files] == ["packages/a.cc"]
    assert catalog.truncated


def test_shared_file_catalog_does_not_mark_exact_limit_as_truncated(
    tmp_path: Path,
) -> None:
    (tmp_path / "only.cc").write_bytes(b"x")

    catalog = list_shared_files(tmp_path, limit=1)

    assert len(catalog.files) == 1
    assert not catalog.truncated


def test_shared_file_catalog_search_sort_and_pagination(tmp_path: Path) -> None:
    (tmp_path / "alpha.cfg").write_bytes(b"a")
    (tmp_path / "beta.cfg").write_bytes(b"bbb")
    (tmp_path / "ignore.txt").write_bytes(b"xx")

    first = list_shared_files(
        tmp_path,
        query=".cfg",
        sort="size",
        order="desc",
        limit=1,
    )
    second = list_shared_files(
        tmp_path,
        query=".cfg",
        sort="size",
        order="desc",
        offset=first.next_offset or 0,
        limit=1,
    )

    assert first.total == 2
    assert first.truncated
    assert first.next_offset == 1
    assert [item.name for item in first.files] == ["beta.cfg"]
    assert [item.name for item in second.files] == ["alpha.cfg"]
    assert second.next_offset is None


@pytest.mark.parametrize(
    "destination",
    ["target.cc", "flash:/", "flash:/../target.cc", "/flash/target.cc", "flash:\\target.cc"],
)
def test_destination_path_requires_device_absolute_file_path(
    destination: str,
) -> None:
    with pytest.raises(ManagedTransferError) as error:
        validate_destination_path(destination)

    assert error.value.code == "invalid_destination_path"


def test_destination_verification_requires_exact_size() -> None:
    output = """
Directory of flash:/

    0  -rw-    1,024  Jan 01 2026 10:00:00  target.cc

1,464,844 KB total (100,000 KB free)
<sim>
"""

    assert destination_matches(output, "flash:/target.cc", 1_024)
    assert not destination_matches(output, "flash:/target.cc", 1_023)


def test_managed_plan_uses_local_secrets_and_device_side_get() -> None:
    steps, timeout = build_managed_transfer_steps(
        protocol="ftp",
        host="192.0.2.10",
        port=2121,
        source_path="packages/target.cc",
        destination_path="flash:/target.cc",
        source_size=1_024,
    )
    text = str(steps)

    assert "file_transfer.username" in text
    assert "file_transfer.password" in text
    assert "get packages/target.cc flash:/target.cc" in text
    assert "put " not in text
    assert "binary" in text
    assert timeout >= 120


def test_managed_ftp_plan_keeps_credential_prompts_in_protocol_order() -> None:
    steps, _ = build_managed_transfer_steps(
        protocol="ftp",
        host="192.0.2.10",
        port=2121,
        source_path="packages/target.cc",
        destination_path="flash:/target.cc",
        source_size=1_024,
    )

    labels = [step.get("label") for step in steps]
    assert labels[:5] == [
        "连接 FTP 服务",
        "等待 FTP 用户名提示",
        "发送 FTP 用户名",
        "等待 FTP 密码提示",
        "发送 FTP 密码",
    ]
    assert steps[1]["success"] == ["username_prompt"]
    assert steps[3]["success"] == ["password_prompt"]
    assert "responses" not in steps[1]
    assert "responses" not in steps[3]


def test_ftpget_plan_uses_exact_one_command_contract_and_protected_reference() -> None:
    command = build_ftpget_command(
        username="transfer-user",
        password="transfer-secret",
        host="192.0.2.10",
        source_path="target.cc",
    )
    steps, timeout = build_ftpget_transfer_steps(
        command_secret_ref="managed_transfer.12345678-1234-1234-1234-123456789abc.command",
        source_size=2 * 1024 * 1024,
    )

    assert command == "ftpget -u transfer-user -p transfer-secret 192.0.2.10 target.cc"
    assert steps[0]["secret_ref"].endswith(".command")
    assert steps[1]["success"] == ["device_prompt"]
    assert timeout >= 120
    parsed = parse_terminal_plan(steps)
    assert parsed.steps[0].secret_ref.endswith(".command")

    quoted = build_ftpget_command(
        username="transfer-user",
        password="transfer-secret",
        host="192.0.2.10",
        source_path="images/target image;1.cc",
    )
    assert quoted.endswith("'images/target image;1.cc'")


@pytest.mark.parametrize(
    "path",
    ["tmp/image.cc", "/", "/tmp/../image.cc", "/tmp/./image.cc", "/tmp//image.cc"],
)
def test_linux_transfer_path_requires_clean_absolute_file_path(path: str) -> None:
    with pytest.raises(ManagedTransferError) as error:
        validate_linux_file_path(path)

    assert error.value.code == "invalid_destination_path"


def test_auto_terminal_environment_accepts_vrp_and_linux_paths() -> None:
    assert validate_transfer_device_path("flash:/image.cc", "auto") == "flash:/image.cc"
    assert validate_transfer_device_path("/tmp/image.cc", "auto") == "/tmp/image.cc"
    assert infer_terminal_environment("flash:/image.cc", session_kind="ssh") == "vrp"
    assert infer_terminal_environment("/tmp/image.cc", session_kind="telnet") == "linux"
    assert infer_terminal_environment("relative.bin", session_kind="ssh") == "linux"


def test_linux_inspection_command_and_markers_cover_client_file_and_space() -> None:
    command = build_linux_inspection_command("/tmp/target image.cc", "ftp")
    output = """
__DEVICE_TUI_TRANSFER_CLIENT__=1
__DEVICE_TUI_TRANSFER_SIZE__=1024
__DEVICE_TUI_TRANSFER_FREE__=4096
"""

    assert "command -v ftp" in command
    assert "'/tmp/target image.cc'" in command
    assert linux_client_available(output)
    assert linux_directory_available(output)
    assert linux_file_size(output) == 1024
    assert linux_free_space_bytes(output) == 4096
    assert not linux_directory_available("__DEVICE_TUI_TRANSFER_DIRECTORY__=0\n")


def test_linux_ftp_plan_uses_standard_interactive_client_and_posix_path() -> None:
    steps, _ = build_managed_transfer_steps(
        protocol="ftp",
        host="192.0.2.10",
        port=2121,
        source_path="packages/target.cc",
        destination_path="/tmp/target.cc",
        source_size=1024,
        terminal_environment="linux",
    )

    assert steps[0]["text"] == "ftp 192.0.2.10 2121"
    assert any(step.get("text") == "get packages/target.cc /tmp/target.cc" for step in steps)
    assert any(step.get("text") == "binary" for step in steps)


def test_linux_sftp_plan_keeps_connect_identity_in_runtime_secret() -> None:
    reference = "managed_transfer.12345678-1234-1234-1234-123456789abc.username"
    steps, _ = build_managed_transfer_steps(
        protocol="sftp",
        host="192.0.2.10",
        port=2222,
        source_path="packages/target.cc",
        destination_path="/tmp/target.cc",
        source_size=1024,
        terminal_environment="linux",
        connect_secret_ref=reference,
    )

    assert steps[0] == {
        "type": "send",
        "secret_ref": reference,
        "secret_prefix": "sftp -P 2222 ",
        "secret_suffix": "@192.0.2.10",
        "label": "连接 SFTP 服务",
    }
    assert parse_terminal_plan(steps).steps[0].secret_ref == reference
