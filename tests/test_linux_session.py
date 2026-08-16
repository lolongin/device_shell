from __future__ import annotations

import asyncio

import asyncssh

from device_tui.infrastructure.transports.linux_session import LinuxSshSession, RemoteOutputDecoder
from device_tui.infrastructure.transports.session_protocol import SessionCallbacks


class _BlockingReader:
    async def read(self, _size: int) -> bytes:
        await asyncio.Event().wait()
        return b""


class _FakeStdin:
    def __init__(self) -> None:
        self.writes: list[bytes] = []

    def write(self, text: bytes) -> None:
        self.writes.append(text)
        return

    async def drain(self) -> None:
        return

    def close(self) -> None:
        return


class _FakeProcess:
    def __init__(self) -> None:
        self.stdout = _BlockingReader()
        self.stderr = _BlockingReader()
        self.stdin = _FakeStdin()

    async def wait_closed(self) -> None:
        return


class _FakeConnection:
    def __init__(self) -> None:
        self.create_process_kwargs: dict[str, object] = {}

    async def create_process(self, **kwargs: object) -> _FakeProcess:
        self.create_process_kwargs = kwargs
        return _FakeProcess()

    def close(self) -> None:
        return

    async def wait_closed(self) -> None:
        return


def test_linux_ssh_session_reads_bytes_and_writes_utf8(monkeypatch) -> None:
    fake_connection = _FakeConnection()

    async def fake_connect(*_args: object, **_kwargs: object) -> _FakeConnection:
        return fake_connection

    monkeypatch.setattr(asyncssh, "connect", fake_connect)
    session = LinuxSshSession(SessionCallbacks(on_output=lambda _message: None, on_status=lambda _status: None))

    async def run() -> None:
        await session.connect("127.0.0.1", 22, "user", "password")
        await session.send_text("display version\r")
        assert session._process is not None
        assert session._process.stdin.writes == ["display version\r".encode("utf-8")]
        await session.disconnect("")

    asyncio.run(run())

    assert fake_connection.create_process_kwargs["encoding"] is None


def test_remote_output_decoder_preserves_split_utf8() -> None:
    decoder = RemoteOutputDecoder()
    payload = "中文日志".encode("utf-8")

    assert decoder.decode(payload[:2]) == ""
    assert decoder.decode(payload[2:]) == "中文日志"


def test_remote_output_decoder_falls_back_to_gb18030() -> None:
    decoder = RemoteOutputDecoder()
    payload = "中文日志正常".encode("gb18030")

    assert decoder.decode(payload) == "中文日志正常"
