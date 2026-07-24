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
        self._upgrade_package_name = "target.cc"
        self._upgrade_package_size = 640_000_000
        self._current_system = "flash:/current.cc"
        self._next_system = "flash:/current.cc"
        self._files_by_storage: dict[str, dict[str, int]] = {
            "flash:/": {
                "current.cc": 500_000_000,
                "old.cc": 500_000_000,
            },
            "slave#flash:/": {
                "current.cc": 500_000_000,
                "old-slave.cc": 500_000_000,
            },
        }
        self._upgrade_fail_download = False
        self._upgrade_fail_space = False
        self._upgrade_fail_startup = False
        self._transfer_mode = ""
        self._transfer_phase = ""

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

    def configure_package_upgrade(self, package_name: str, package_size: int) -> None:
        self._upgrade_package_name = package_name or self._upgrade_package_name
        self._upgrade_package_size = max(1, package_size)

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
        if self._transfer_mode:
            await self._handle_transfer_command(command)
            return
        if lowered == "help":
            self.callbacks.on_output(
                "Commands: help, reboot, display version, display startup, dir flash:/, "
                "menu, admin, biglog [lines], exit\n"
                "Upgrade toggles: sim upgrade fail-download|fail-space|fail-startup on|off\n"
                "Use 'menu' to test Ctrl+B, 'admin' to test Ctrl+A.\n<sim> "
            )
            return
        if lowered.startswith("sim upgrade "):
            self._handle_upgrade_toggle(lowered)
            return
        if lowered == "screen-length 0 temporary":
            self.callbacks.on_output("Info: Screen length disabled temporarily.\n<sim> ")
            return
        if lowered == "display startup":
            self.callbacks.on_output(
                "MainBoard:\n"
                f"  Current startup system software: {self._current_system}\n"
                f"  Next startup system software: {self._next_system}\n"
                "<sim> "
            )
            return
        if lowered == "reboot":
            self.callbacks.on_output("Rebooting simulated device...\n")
            self._start_boot_sequence()
            return
        if lowered == "display version":
            self.callbacks.on_output("SimOS V1.0 build 2026-05-29\n<sim> ")
            return
        if lowered.startswith("dir "):
            self._handle_dir(command)
            return
        if lowered.startswith("delete "):
            self._handle_delete(command)
            return
        if lowered.startswith("ftp ") or lowered.startswith("sftp "):
            self._transfer_mode = "sftp" if lowered.startswith("sftp ") else "ftp"
            self._transfer_phase = "username"
            self.callbacks.on_output("Connected to simulated transfer service.\nUser: ")
            return
        if lowered.startswith("copy "):
            self._handle_copy(command)
            return
        if lowered.startswith("startup system-software "):
            self._handle_startup_system_software(command)
            return
        if lowered.startswith("verify /md5 "):
            self.callbacks.on_output("Info: The file verified successfully.\n<sim> ")
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

    def _handle_upgrade_toggle(self, lowered: str) -> None:
        parts = lowered.split()
        if (
            len(parts) != 4
            or parts[2] not in {"fail-download", "fail-space", "fail-startup"}
            or parts[3] not in {"on", "off"}
        ):
            self.callbacks.on_output(
                "Usage: sim upgrade fail-download|fail-space|fail-startup on|off\n<sim> "
            )
            return
        enabled = parts[3] == "on"
        if parts[2] == "fail-download":
            self._upgrade_fail_download = enabled
        elif parts[2] == "fail-space":
            self._upgrade_fail_space = enabled
        elif parts[2] == "fail-startup":
            self._upgrade_fail_startup = enabled
        state = "on" if enabled else "off"
        self.callbacks.on_output(f"Simulated upgrade {parts[2]} is {state}.\n<sim> ")

    @staticmethod
    def _normalize_storage(value: str) -> str:
        storage = value.strip()
        if not storage:
            return "flash:/"
        if storage.endswith("/"):
            return storage
        if storage.endswith(":"):
            return f"{storage}/"
        if "/" in storage:
            return storage.rsplit("/", 1)[0] + "/"
        return storage

    @staticmethod
    def _basename(value: str) -> str:
        return value.strip().replace("\\", "/").rsplit("/", 1)[-1]

    def _handle_dir(self, command: str) -> None:
        target = command.split(maxsplit=1)[1].strip() if len(command.split(maxsplit=1)) > 1 else "flash:/"
        storage = self._normalize_storage(target)
        requested_name = self._basename(target) if target.lower().endswith(".cc") else ""
        files = dict(self._files_by_storage.get(storage, {}))
        if self._upgrade_fail_space:
            current_name = self._basename(self._current_system)
            files = {name: size for name, size in files.items() if name == current_name}
        total_bytes = 1_500_000_000
        used_bytes = sum(files.values())
        free_bytes = 1_024 if self._upgrade_fail_space else max(128_000_000, total_bytes - used_bytes)
        lines = [f"Directory of {storage}\n\n", "  Idx  Attr     Size(Byte)  Date        Time       FileName\n"]
        index = 0
        for name, size in sorted(files.items()):
            if requested_name and name.casefold() != requested_name.casefold():
                continue
            lines.append(f"  {index:3d}  -rw-    {size:,}  Jan 01 2026 10:00:00  {name}\n")
            index += 1
        lines.append(f"\n1,464,844 KB total ({free_bytes // 1024:,} KB free)\n<sim> ")
        self.callbacks.on_output("".join(lines))

    def _handle_delete(self, command: str) -> None:
        path = command.split()[-1]
        storage = self._normalize_storage(path)
        name = self._basename(path)
        files = self._files_by_storage.setdefault(storage, {})
        if name in files:
            del files[name]
            self.callbacks.on_output(f"Delete {path} OK.\n<sim> ")
            return
        self.callbacks.on_output(f"Warning: {path} does not exist.\n<sim> ")

    async def _handle_transfer_command(self, command: str) -> None:
        lowered = command.lower()
        if self._transfer_phase == "username":
            self._transfer_phase = "password"
            self.callbacks.on_output("Password: ")
            return
        if self._transfer_phase == "password":
            self._transfer_phase = "ready"
            self.callbacks.on_output("230 User logged in.\nftp> ")
            return
        if lowered == "binary":
            self.callbacks.on_output("200 Type set to I.\nftp> ")
            return
        if lowered.startswith("get "):
            if self._upgrade_fail_download:
                self.callbacks.on_output("Error: failed to download package from simulated server.\nftp> ")
                return
            parts = command.split()
            remote_name = parts[1] if len(parts) >= 2 else self._upgrade_package_name
            local_path = parts[2] if len(parts) >= 3 else f"flash:/{remote_name}"
            storage = self._normalize_storage(local_path)
            local_name = self._basename(local_path) or self._basename(remote_name)
            self._files_by_storage.setdefault(storage, {})[local_name] = self._upgrade_package_size
            self.callbacks.on_output(
                f"226 Transfer complete. {local_name} saved to {storage}\nftp> "
            )
            return
        if lowered in {"quit", "bye"}:
            self._transfer_mode = ""
            self._transfer_phase = ""
            self.callbacks.on_output("221 Goodbye.\n<sim> ")
            return
        self.callbacks.on_output("200 OK.\nftp> ")

    def _handle_copy(self, command: str) -> None:
        parts = command.split()
        if len(parts) < 3:
            self.callbacks.on_output("Error: invalid copy command.\n<sim> ")
            return
        source = parts[1]
        target = parts[2]
        source_storage = self._normalize_storage(source)
        source_name = self._basename(source)
        target_storage = self._normalize_storage(target)
        target_name = self._basename(target)
        source_size = self._files_by_storage.get(source_storage, {}).get(source_name)
        if source_size is None:
            self.callbacks.on_output(f"Error: source file {source} not found.\n<sim> ")
            return
        self._files_by_storage.setdefault(target_storage, {})[target_name] = source_size
        self.callbacks.on_output(f"Copy {source} to {target} OK.\n<sim> ")

    def _handle_startup_system_software(self, command: str) -> None:
        if self._upgrade_fail_startup:
            self.callbacks.on_output("Error: startup system-software rejected by simulated device.\n<sim> ")
            return
        parts = command.split()
        if len(parts) < 3:
            self.callbacks.on_output("Error: invalid startup command.\n<sim> ")
            return
        package_path = parts[2]
        storage = self._normalize_storage(package_path)
        name = self._basename(package_path)
        if name not in self._files_by_storage.get(storage, {}):
            self.callbacks.on_output(f"Error: system software {package_path} not found.\n<sim> ")
            return
        self._next_system = package_path
        self.callbacks.on_output(f"Info: Succeeded in setting next startup software to {package_path}.\n<sim> ")

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
