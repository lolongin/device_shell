from __future__ import annotations

import asyncio
from unittest.mock import patch

from device_tui.infrastructure.transports.telnet_session import (
    DO,
    IAC,
    NOP,
    SB,
    SE,
    TERMINAL_TYPE_IS,
    TERMINAL_TYPE_SEND,
    TERM_TYPE,
    WILL,
    HuaweiTelnetSession,
    OPTION_NAWS,
    OPTION_TERMINAL_TYPE,
)
import device_tui.infrastructure.transports.telnet_session as telnet_module


class _FakeWriter:
    def __init__(self) -> None:
        self.writes: list[bytes] = []

    def write(self, payload: bytes) -> None:
        self.writes.append(payload)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None

    async def wait_closed(self) -> None:
        return None


class _FailingWriter(_FakeWriter):
    async def drain(self) -> None:
        raise OSError("peer closed")


class _FakeReader:
    def __init__(self, *chunks: bytes) -> None:
        self._chunks = list(chunks)
        self._wait_for_more = asyncio.Event()

    async def read(self, _size: int) -> bytes:
        if self._chunks:
            return self._chunks.pop(0)
        await self._wait_for_more.wait()
        return b""


def test_huawei_telnet_negotiates_naws_with_current_terminal_size() -> None:
    writer = _FakeWriter()
    session = HuaweiTelnetSession(on_output=lambda _text: None, on_status=lambda _status: None)
    session._writer = writer
    session.set_terminal_size(132, 43)

    visible = session._process_bytes(bytes([IAC, DO, OPTION_NAWS]))

    assert visible == ""
    assert writer.writes == [
        bytes([IAC, WILL, OPTION_NAWS])
        + bytes([IAC, SB, OPTION_NAWS, 0, 132, 0, 43, IAC, SE])
    ]


def test_huawei_telnet_resize_sends_naws_update_after_negotiation() -> None:
    writer = _FakeWriter()
    session = HuaweiTelnetSession(on_output=lambda _text: None, on_status=lambda _status: None)
    session._writer = writer
    session._closed = False

    session._process_bytes(bytes([IAC, DO, OPTION_NAWS]))
    writer.writes.clear()

    asyncio.run(session.resize_terminal(180, 50))

    assert writer.writes == [bytes([IAC, SB, OPTION_NAWS, 0, 180, 0, 50, IAC, SE])]


def test_huawei_telnet_reports_xterm_terminal_type() -> None:
    writer = _FakeWriter()
    session = HuaweiTelnetSession(on_output=lambda _text: None, on_status=lambda _status: None)
    session._writer = writer

    session._process_bytes(bytes([IAC, DO, OPTION_TERMINAL_TYPE]))
    session._process_bytes(bytes([IAC, SB, OPTION_TERMINAL_TYPE, TERMINAL_TYPE_SEND, IAC, SE]))

    assert writer.writes == [
        bytes([IAC, WILL, OPTION_TERMINAL_TYPE]),
        bytes([IAC, SB, OPTION_TERMINAL_TYPE, TERMINAL_TYPE_IS])
        + TERM_TYPE.encode("ascii")
        + bytes([IAC, SE]),
    ]


def test_huawei_telnet_keeps_connection_open_after_authentication_failure() -> None:
    async def scenario() -> None:
        reader = _FakeReader(
            b"Username:",
            b"Password:",
            b"Authentication fail\r\nUsername:",
        )
        writer = _FakeWriter()
        statuses: list[str] = []
        session = HuaweiTelnetSession(
            on_output=lambda _text: None,
            on_status=statuses.append,
        )

        with patch(
            "device_tui.infrastructure.transports.telnet_session.asyncio.open_connection",
            return_value=(reader, writer),
        ):
            await session.connect("127.0.0.1", 23, "bad-user", "bad-password")

        assert session.is_connected
        assert writer.writes[:2] == [b"bad-user\r\n", b"bad-password\r\n"]
        assert statuses[-1] == "Connected"

        await session.send_text("retry-user\n")
        assert writer.writes[-1] == b"retry-user\r\n"
        await session.disconnect("")

    asyncio.run(scenario())


def test_huawei_telnet_keepalive_writes_nop(monkeypatch) -> None:
    async def scenario() -> None:
        writer = _FakeWriter()
        session = HuaweiTelnetSession(on_output=lambda _text: None, on_status=lambda _status: None)
        session._writer = writer
        session._closed = False
        monkeypatch.setattr(telnet_module, "TELNET_KEEPALIVE_INTERVAL_SECONDS", 0.01)
        monkeypatch.setattr(telnet_module, "TELNET_KEEPALIVE_TIMEOUT_SECONDS", 0.05)

        task = asyncio.create_task(session._keepalive_loop())
        await asyncio.sleep(0.03)
        await session.disconnect("")
        await task

        assert bytes([IAC, NOP]) in writer.writes

    asyncio.run(scenario())


def test_huawei_telnet_keepalive_failures_disconnect(monkeypatch) -> None:
    async def scenario() -> None:
        statuses: list[str] = []
        writer = _FailingWriter()
        session = HuaweiTelnetSession(on_output=lambda _text: None, on_status=statuses.append)
        session._writer = writer
        session._closed = False
        monkeypatch.setattr(telnet_module, "TELNET_KEEPALIVE_INTERVAL_SECONDS", 0.001)
        monkeypatch.setattr(telnet_module, "TELNET_KEEPALIVE_TIMEOUT_SECONDS", 0.01)
        monkeypatch.setattr(telnet_module, "TELNET_KEEPALIVE_FAILURE_LIMIT", 2)

        task = asyncio.create_task(session._keepalive_loop())
        await asyncio.wait_for(task, timeout=0.2)

        assert not session.is_connected
        assert statuses[-1] == "Disconnected"

    asyncio.run(scenario())
