# tests/test_ai_gateway_download.py
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from device_tui.infrastructure.transfers.managed_file_transfer import (
    ManagedTransferError,
    build_managed_transfer_download_steps,
)


def test_build_download_steps_uses_put() -> None:
    steps, total_timeout = build_managed_transfer_download_steps(
        protocol="ftp",
        host="10.0.1.1",
        port=2121,
        source_path="config/backup.cfg",
        destination_path="downloads/backup.cfg",
        source_size=1024 * 1024,
    )
    texts = [step.get("text", "") for step in steps]
    assert any(text.startswith("put ") for text in texts)
    assert any("get " in text for text in texts) is False
    assert total_timeout >= 120


def test_build_download_steps_validates_protocol() -> None:
    with pytest.raises(ManagedTransferError):
        build_managed_transfer_download_steps(
            protocol="unknown",
            host="h",
            port=1,
            source_path="a",
            destination_path="b",
            source_size=1,
        )
