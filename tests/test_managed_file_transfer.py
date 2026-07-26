"""Tests for managed file-transfer validation and plan construction."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.managed_file_transfer import (
    ManagedTransferError,
    build_managed_transfer_steps,
    destination_matches,
    list_shared_files,
    resolve_shared_file,
    validate_destination_path,
)


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
