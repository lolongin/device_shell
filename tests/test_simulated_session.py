"""Tests for the local simulated terminal session."""

from __future__ import annotations

import asyncio

from src.session_protocol import SessionCallbacks
from src.simulated_session import SimulatedTerminalSession


def test_simulated_session_enters_boot_menu_with_ctrl_b() -> None:
    output: list[str] = []
    statuses: list[str] = []
    session = SimulatedTerminalSession(
        SessionCallbacks(
            on_output=output.append,
            on_status=statuses.append,
        )
    )

    async def run() -> None:
        await session.connect()
        await asyncio.sleep(0.9)
        await session.send_text("\x02")
        await session.disconnect("")

    asyncio.run(run())

    text = "".join(output)
    assert "Press Ctrl+B to enter BOOT menu" in text
    assert "BOOT MENU" in text
    assert "Connected" in statuses


def test_simulated_session_enters_admin_menu_with_ctrl_a() -> None:
    output: list[str] = []
    session = SimulatedTerminalSession(
        SessionCallbacks(
            on_output=output.append,
            on_status=lambda _status: None,
        )
    )

    async def run() -> None:
        await session.connect()
        await session.send_command("admin")
        await session.send_text("\x01")
        await session.disconnect("")

    asyncio.run(run())

    text = "".join(output)
    assert "Press Ctrl+A to enter ADMIN menu" in text
    assert "ADMIN MENU" in text


def test_simulated_session_biglog_emits_requested_lines() -> None:
    output: list[str] = []
    session = SimulatedTerminalSession(
        SessionCallbacks(
            on_output=output.append,
            on_status=lambda _status: None,
        )
    )

    async def run() -> None:
        await session.connect()
        await session.send_command("biglog 3")
        await session.disconnect("")

    asyncio.run(run())

    text = "".join(output)
    assert "Generating 3 log lines" in text
    assert "000001" in text
    assert "000003" in text
    assert "Completed 3 log lines" in text


def test_simulated_session_supports_package_upgrade_success_path() -> None:
    output: list[str] = []
    session = SimulatedTerminalSession(
        SessionCallbacks(
            on_output=output.append,
            on_status=lambda _status: None,
        )
    )
    session.configure_package_upgrade("target.cc", 123_456)

    async def run() -> None:
        await session.connect()
        await session.send_command("display startup")
        await session.send_command("dir flash:/")
        await session.send_command("ftp 192.0.2.10 2121")
        await session.send_command("user")
        await session.send_command("password")
        await session.send_command("binary")
        await session.send_command("get target.cc flash:/target.cc")
        await session.send_command("quit")
        await session.send_command("dir flash:/target.cc")
        await session.send_command("copy flash:/target.cc slave#flash:/target.cc")
        await session.send_command("dir slave#flash:/target.cc")
        await session.send_command("startup system-software flash:/target.cc all")
        await session.send_command("display startup")
        await session.disconnect("")

    asyncio.run(run())

    text = "".join(output)
    assert "Current startup system software: flash:/current.cc" in text
    assert "target.cc" in text
    assert "123,456" in text
    assert "Copy flash:/target.cc to slave#flash:/target.cc OK" in text
    assert "Next startup system software: flash:/target.cc" in text


def test_simulated_session_can_inject_upgrade_failures() -> None:
    output: list[str] = []
    session = SimulatedTerminalSession(
        SessionCallbacks(
            on_output=output.append,
            on_status=lambda _status: None,
        )
    )

    async def run() -> None:
        await session.connect()
        await session.send_command("sim upgrade fail-download on")
        await session.send_command("ftp 192.0.2.10 2121")
        await session.send_command("user")
        await session.send_command("password")
        await session.send_command("get target.cc flash:/target.cc")
        await session.send_command("quit")
        await session.send_command("sim upgrade fail-space on")
        await session.send_command("dir flash:/")
        await session.disconnect("")

    asyncio.run(run())

    text = "".join(output)
    assert "failed to download package" in text
    assert "1 KB free" in text
    assert "old.cc" not in text[text.rfind("Directory of flash:/") :]
