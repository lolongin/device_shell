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
