from __future__ import annotations

import asyncio

from .session_protocol import SessionCallbacks


class SimulatedTerminalSession:
    """Local terminal simulator for testing startup prompts and auto responses."""

    LARGE_LOG_DEFAULT_LINES = 10000
    LARGE_LOG_CHUNK_LINES = 200

    def __init__(self, callbacks: SessionCallbacks) -> None:
        self.callbacks = callbacks
        self._connected = False
        self._boot_waiting = False
        self._admin_waiting = False
        self._boot_task: asyncio.Task[None] | None = None
        self._line_buffer = ""

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        if self.is_connected:
            await self.disconnect("Restarted simulated terminal.")
        self._connected = True
        self.callbacks.on_status("Connected")
        self.callbacks.on_output(
            "\n=== Simulated terminal connected ===\n"
            "Type 'help' for commands, 'reboot' to replay startup.\n\n"
        )
        self._start_boot_sequence()

    async def disconnect(self, message: str = "Disconnected.") -> None:
        self._connected = False
        self._boot_waiting = False
        self._admin_waiting = False
        if self._boot_task is not None:
            self._boot_task.cancel()
            try:
                await self._boot_task
            except asyncio.CancelledError:
                pass
            self._boot_task = None
        self.callbacks.on_status("Disconnected")
        if message:
            self.callbacks.on_output(f"\n=== {message} ===\n")

    async def send_command(self, command: str) -> None:
        await self.send_text(command.rstrip() + "\r")

    async def send_text(self, text: str) -> None:
        if not self.is_connected:
            return
        for char in text:
            if char == "\x01":
                self._enter_admin_menu()
                continue
            if char == "\x02":
                self._enter_boot_menu()
                continue
            if char in {"\r", "\n"}:
                command = self._line_buffer.strip()
                self._line_buffer = ""
                if command:
                    await self._handle_command(command)
                else:
                    self.callbacks.on_output("\n<sim> ")
                continue
            self._line_buffer += char
            self.callbacks.on_output(char)

    def _start_boot_sequence(self) -> None:
        if self._boot_task is not None:
            self._boot_task.cancel()
        self._boot_task = asyncio.create_task(self._boot_sequence())

    async def _boot_sequence(self) -> None:
        self._boot_waiting = False
        self.callbacks.on_output("Power on self-test...\n")
        await asyncio.sleep(0.4)
        self.callbacks.on_output("Memory test passed.\n")
        await asyncio.sleep(0.4)
        self._boot_waiting = True
        self.callbacks.on_output("Press Ctrl+B to enter BOOT menu: ")
        await asyncio.sleep(3.0)
        if not self._connected or not self._boot_waiting:
            return
        self._boot_waiting = False
        self.callbacks.on_output("\nAutoboot continuing...\n")
        await asyncio.sleep(0.4)
        self.callbacks.on_output("System ready.\n<sim> ")

    def _enter_boot_menu(self) -> None:
        if not self._boot_waiting:
            self.callbacks.on_output("^B\n<sim> Ctrl+B received outside boot window.\n<sim> ")
            return
        self._boot_waiting = False
        self._admin_waiting = False
        self.callbacks.on_output(
            "^B\n\n"
            "================ BOOT MENU ================\n"
            "1. Boot with default image\n"
            "2. Enter recovery shell\n"
            "3. Show startup configuration\n"
            "0. Continue autoboot\n"
            "Select option: "
        )

    def _enter_admin_menu(self) -> None:
        if not self._admin_waiting:
            self.callbacks.on_output("^A\n<sim> Ctrl+A received outside admin menu window.\n<sim> ")
            return
        self._admin_waiting = False
        self.callbacks.on_output(
            "^A\n\n"
            "=============== ADMIN MENU ===============\n"
            "1. Show diagnostics\n"
            "2. Reset counters\n"
            "3. Toggle verbose boot\n"
            "0. Exit admin menu\n"
            "Select option: "
        )

    async def _handle_command(self, command: str) -> None:
        lowered = command.lower()
        self.callbacks.on_output("\n")
        if lowered == "help":
            self.callbacks.on_output(
                "Commands: help, reboot, display version, menu, admin, biglog [lines], exit\n"
                "Use 'menu' to test Ctrl+B, 'admin' to test Ctrl+A.\n<sim> "
            )
            return
        if lowered == "reboot":
            self.callbacks.on_output("Rebooting simulated device...\n")
            self._start_boot_sequence()
            return
        if lowered == "display version":
            self.callbacks.on_output("SimOS V1.0 build 2026-05-29\n<sim> ")
            return
        if lowered == "menu":
            self._boot_waiting = True
            self.callbacks.on_output("Press Ctrl+B to enter BOOT menu: ")
            return
        if lowered in {"admin", "admin-menu", "ctrl-a"}:
            self._admin_waiting = True
            self.callbacks.on_output("Press Ctrl+A to enter ADMIN menu: ")
            return
        if lowered == "biglog" or lowered.startswith("biglog "):
            await self._emit_large_log(lowered)
            return
        if lowered in {"exit", "quit"}:
            await self.disconnect("Simulated terminal closed.")
            return
        if lowered in {"0", "1", "2", "3"}:
            self.callbacks.on_output(f"Selected menu option {lowered}.\n<sim> ")
            return
        self.callbacks.on_output(f"Unknown command: {command}\n<sim> ")

    async def _emit_large_log(self, command: str) -> None:
        parts = command.split()
        line_count = self.LARGE_LOG_DEFAULT_LINES
        if len(parts) >= 2:
            try:
                line_count = max(1, min(200000, int(parts[1])))
            except ValueError:
                self.callbacks.on_output("Usage: biglog [line_count]\n<sim> ")
                return

        self.callbacks.on_output(f"Generating {line_count} log lines...\n")
        emitted = 0
        while emitted < line_count and self.is_connected:
            chunk_size = min(self.LARGE_LOG_CHUNK_LINES, line_count - emitted)
            lines = []
            for offset in range(chunk_size):
                index = emitted + offset + 1
                lines.append(
                    f"{index:06d} 2026-05-31 17:00:{index % 60:02d}.000 "
                    f"slot={index % 16:02d} level=INFO cpu={index % 100:02d}% "
                    f"if=GE0/0/{index % 48:02d} event=simulated-throughput-test "
                    f"message=\"large terminal output rendering benchmark\"\n"
                )
            self.callbacks.on_output("".join(lines))
            emitted += chunk_size
            await asyncio.sleep(0)
        self.callbacks.on_output(f"Completed {emitted} log lines.\n<sim> ")
