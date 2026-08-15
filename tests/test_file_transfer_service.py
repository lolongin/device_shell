"""Tests for local FTP/SFTP service helpers."""

from __future__ import annotations

import asyncio
import ftplib
import io
from pathlib import Path

import asyncssh
import pytest

from src.file_transfer_service import TransferServiceConfig, TransferServiceController


def test_ftp_service_starts_on_ephemeral_port_and_honors_read_only(tmp_path: Path) -> None:
    share_root = tmp_path / "share"
    share_root.mkdir()
    (share_root / "hello.txt").write_text("hello", encoding="utf-8")
    logs: list[str] = []
    controller = TransferServiceController(logs.append)

    controller.start(
        TransferServiceConfig(
            protocol="ftp",
            host="127.0.0.1",
            port=0,
            root=share_root,
            username="device",
            password="device",
            writable=False,
        )
    )

    try:
        assert controller.is_running
        assert controller.bound_port > 0
        with ftplib.FTP(timeout=3) as ftp:
            ftp.connect("127.0.0.1", controller.bound_port)
            ftp.login("device", "device")
            assert "hello.txt" in ftp.nlst()
            with pytest.raises(ftplib.error_perm):
                ftp.storbinary("STOR upload.txt", io.BytesIO(b"blocked"))
    finally:
        controller.stop()

    assert not controller.is_running
    assert any("FTP 服务已启动" in entry for entry in logs)


def test_sftp_service_starts_on_ephemeral_port_and_honors_read_only(tmp_path: Path) -> None:
    share_root = tmp_path / "share"
    share_root.mkdir()
    (share_root / "hello.txt").write_text("hello", encoding="utf-8")
    local_upload = tmp_path / "upload.txt"
    local_upload.write_text("blocked", encoding="utf-8")
    logs: list[str] = []
    controller = TransferServiceController(logs.append)

    controller.start(
        TransferServiceConfig(
            protocol="sftp",
            host="127.0.0.1",
            port=0,
            root=share_root,
            username="device",
            password="device",
            writable=False,
        )
    )

    async def exercise_client() -> None:
        conn = await asyncssh.connect(
            "127.0.0.1",
            port=controller.bound_port,
            username="device",
            password="device",
            known_hosts=None,
        )
        try:
            sftp = await conn.start_sftp_client()
            try:
                assert "hello.txt" in await sftp.listdir(".")
                with pytest.raises(asyncssh.SFTPError):
                    await sftp.put(local_upload, "upload.txt")
            finally:
                sftp.exit()
                await sftp.wait_closed()
        finally:
            conn.close()
            await conn.wait_closed()

    try:
        assert controller.is_running
        assert controller.bound_port > 0
        asyncio.run(exercise_client())
    finally:
        controller.stop()

    assert not controller.is_running
    assert any("SFTP 服务已启动" in entry for entry in logs)


@pytest.mark.parametrize("protocol", ["ftp", "sftp"])
def test_managed_transfer_identity_reports_exact_read_progress(
    tmp_path: Path,
    protocol: str,
) -> None:
    share_root = tmp_path / "share"
    share_root.mkdir()
    payload = b"managed-progress" * 8_192
    (share_root / "payload.bin").write_bytes(payload)
    logs: list[str] = []
    progress: list[int] = []
    controller = TransferServiceController(logs.append)
    controller.start(
        TransferServiceConfig(
            protocol=protocol,
            host="127.0.0.1",
            port=0,
            root=share_root,
            username="device",
            password="device",
            writable=True,
        )
    )
    username, password = controller.register_managed_transfer(
        "12345678-1234-1234-1234-123456789abc",
        total_bytes=len(payload),
        on_progress=lambda _operation_id, transferred: progress.append(transferred),
    )

    async def sftp_download() -> bytes:
        connection = await asyncssh.connect(
            "127.0.0.1",
            port=controller.bound_port,
            username=username,
            password=password,
            known_hosts=None,
        )
        try:
            client = await connection.start_sftp_client()
            try:
                async with client.open("payload.bin", "rb") as remote_file:
                    return await remote_file.read()
            finally:
                client.exit()
                await client.wait_closed()
        finally:
            connection.close()
            await connection.wait_closed()

    async def sftp_upload() -> None:
        connection = await asyncssh.connect(
            "127.0.0.1",
            port=controller.bound_port,
            username=username,
            password=password,
            known_hosts=None,
        )
        try:
            client = await connection.start_sftp_client()
            try:
                async with client.open("uploaded.bin", "wb") as remote_file:
                    await remote_file.write(payload)
            finally:
                client.exit()
                await client.wait_closed()
        finally:
            connection.close()
            await connection.wait_closed()

    try:
        if protocol == "ftp":
            received = bytearray()
            with ftplib.FTP(timeout=3) as ftp:
                ftp.connect("127.0.0.1", controller.bound_port)
                ftp.login(username, password)
                ftp.retrbinary("RETR payload.bin", received.extend)
            assert bytes(received) == payload
        else:
            assert asyncio.run(sftp_download()) == payload
        assert progress
        assert progress == sorted(progress)
        assert progress[-1] == len(payload)

        controller.unregister_managed_transfer(username)
        progress.clear()
        username, password = controller.register_managed_transfer(
            "abcdef12-1234-1234-1234-123456789abc",
            total_bytes=len(payload),
            on_progress=lambda _operation_id, transferred: progress.append(transferred),
        )
        if protocol == "ftp":
            with ftplib.FTP(timeout=3) as ftp:
                ftp.connect("127.0.0.1", controller.bound_port)
                ftp.login(username, password)
                ftp.storbinary("STOR uploaded.bin", io.BytesIO(payload))
        else:
            asyncio.run(sftp_upload())
        assert (share_root / "uploaded.bin").read_bytes() == payload
    finally:
        controller.unregister_managed_transfer(username)
        controller.stop()

    assert progress
    assert progress == sorted(progress)
    assert progress[-1] == len(payload)
    assert username not in "\n".join(logs)
