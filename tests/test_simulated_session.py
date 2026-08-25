"""Tests for the local simulated terminal session."""

from __future__ import annotations

import asyncio

from device_tui.infrastructure.transports.session_protocol import SessionCallbacks
from device_tui.infrastructure.transports.simulated_session import SimulatedTerminalSession


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
        await session.send_command("device")
        await session.send_command("device")
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
    assert "User(10.10.10.1):(none):" in text
    assert "Current startup system software: flash:/current.cc" in text
    assert "target.cc" in text
    assert "123,456" in text
    assert "Copy flash:/target.cc to slave#flash:/target.cc OK" in text
    assert "Next startup system software: flash:/target.cc" in text


def test_simulated_session_can_require_startup_confirmation() -> None:
    output: list[str] = []
    session = SimulatedTerminalSession(
        SessionCallbacks(on_output=output.append, on_status=lambda _status: None)
    )
    session.configure_package_upgrade(
        "target.cc",
        123_456,
        require_startup_confirmation=True,
    )

    async def run() -> None:
        await session.connect()
        await session.send_command("startup system-software flash:/current.cc")
        await session.send_command("y")
        await session.disconnect("")

    asyncio.run(run())

    text = "".join(output)
    assert "Continue? [Y/N]:" in text
    assert "Succeeded in setting next startup software to flash:/current.cc" in text


def test_simulated_ftp_emits_vrp_prompts_as_ordered_packets() -> None:
    output: list[str] = []
    session = SimulatedTerminalSession(
        SessionCallbacks(
            on_output=output.append,
            on_status=lambda _status: None,
        )
    )
    session.configure_transfer_prompt_timing(
        output_delay_seconds=0.001,
        password_delay_seconds=0.001,
    )

    async def run() -> None:
        await session.connect()
        output.clear()

        await session.send_command("ftp 192.0.2.10 2121")
        assert [
            item
            for item in output
            if item.startswith("Connected to")
            or item.startswith("User(10.10.10.1)")
        ] == [
            "Connected to simulated transfer service.\r\r\n",
            "User(10.10.10.1):(none): ",
        ]

        output.clear()
        await session.send_command("device")
        assert output[-2:] == ["\r\r\n", "Password: "]

        output.clear()
        await session.send_command("device")
        assert output == ["\r\r\n230 User logged in.\r\r\n", "ftp> "]
        await session.disconnect("")

    asyncio.run(run())


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
        await session.send_command("device")
        await session.send_command("device")
        await session.send_command("binary")
        await session.send_command("get target.cc flash:/target.cc")
        await session.send_command("quit")
        await session.send_command("sim upgrade fail-space on")
        await session.send_command("dir flash:/")
        await session.disconnect("")

    asyncio.run(run())

    text = "".join(output)
    assert "Failed to download file" in text
    assert "1 KB free" in text
    assert "old.cc" not in text[text.rfind("Directory of flash:/") :]


def test_simulated_session_can_inject_one_workflow_command_failure() -> None:
    output: list[str] = []
    session = SimulatedTerminalSession(
        SessionCallbacks(
            on_output=output.append,
            on_status=lambda _status: None,
        )
    )

    async def run() -> None:
        await session.connect()
        await session.send_command("sim workflow fail-next on")
        await session.send_command("display version")
        await session.send_command("display version")
        await session.disconnect("")

    asyncio.run(run())

    text = "".join(output)
    assert "Simulated workflow fail-next is on." in text
    assert "Unknown command: display version" in text
    assert text.count("SimOS V1.0 build 2026-05-29") == 1


def test_simulated_transfer_login_can_expire_while_waiting_for_input() -> None:
    output: list[str] = []
    session = SimulatedTerminalSession(
        SessionCallbacks(
            on_output=output.append,
            on_status=lambda _status: None,
        )
    )
    session.configure_transfer_input_timeout(0.01)

    async def run() -> None:
        await session.connect()
        await session.send_command("ftp 192.0.2.10 2121")
        await asyncio.sleep(0.03)
        await session.disconnect("")

    asyncio.run(run())

    assert "421 Login input timeout." in "".join(output)


def test_simulated_transfer_rejects_wrong_credentials() -> None:
    output: list[str] = []
    session = SimulatedTerminalSession(
        SessionCallbacks(
            on_output=output.append,
            on_status=lambda _status: None,
        )
    )

    async def run() -> None:
        await session.connect()
        await session.send_command("ftp 192.0.2.10 2121")
        await session.send_command("ftp 192.0.2.10")
        await session.send_command("quit")
        await session.disconnect("")

    asyncio.run(run())

    text = "".join(output)
    assert "530 Login incorrect." in text
    assert "230 User logged in." not in text
    assert "200 OK." not in text


def test_simulated_transfer_rejects_invalid_ftp_commands_without_creating_file() -> None:
    output: list[str] = []
    session = SimulatedTerminalSession(
        SessionCallbacks(
            on_output=output.append,
            on_status=lambda _status: None,
        )
    )
    session.configure_managed_transfer(
        username="admin",
        password="secret",
        source_path="large.bin",
        source_size=2_048,
        destination_path="flash:/large.bin",
    )

    async def run() -> None:
        await session.connect()
        await session.send_command("ftp 192.0.2.10 2121")
        await session.send_command("admin")
        await session.send_command("secret")
        await session.send_command("bin")
        await session.send_command("put large.bin flash:/large.bin")
        await session.send_command("dir flash:/")
        await session.send_command("q")
        await session.send_command("quit")
        await session.send_command("dir flash:/large.bin")
        await session.disconnect("")

    asyncio.run(run())

    text = "".join(output)
    assert "500 Unknown FTP command: bin" in text
    assert "502 PUT is not supported" in text
    assert "500 Unknown FTP command: dir flash:/" in text
    assert "500 Unknown FTP command: q" in text
    assert "large.bin" not in text[text.rfind("Directory of flash:/") :]
    assert "200 OK." not in text


def test_simulated_ftpget_accepts_single_command_and_saves_same_named_file() -> None:
    output: list[str] = []
    session = SimulatedTerminalSession(
        SessionCallbacks(
            on_output=output.append,
            on_status=lambda _status: None,
        )
    )
    session.configure_managed_transfer(
        username="managed-user",
        password="managed-password",
        source_path="target.cc",
        source_size=4_096,
        destination_path="target.cc",
    )

    async def run() -> None:
        await session.connect()
        await session.send_command(
            "ftpget -u managed-user -p managed-password 192.0.2.10 target.cc"
        )
        await session.send_command("dir flash:/target.cc")
        await session.disconnect("")

    asyncio.run(run())

    text = "".join(output)
    assert "ftpget: target.cc transfer complete (4096 bytes)" in text
    assert "target.cc" in text[text.rfind("Directory of flash:/") :]
