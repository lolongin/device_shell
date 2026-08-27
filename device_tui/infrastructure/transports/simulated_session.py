from __future__ import annotations

import asyncio
import shlex

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
        self._upgrade_require_startup_confirmation = False
        self._startup_confirmation_command = ""
        self._workflow_fail_next = False
        self._transfer_mode = ""
        self._transfer_phase = ""
        self._transfer_binary = False
        self._transfer_username = "device"
        self._transfer_password = "device"
        self._transfer_source_path = self._upgrade_package_name
        self._transfer_source_size = self._upgrade_package_size
        self._transfer_destination_path = ""
        self._transfer_size_mismatch = False
        self._transfer_input_timeout = 0.0
        self._transfer_timeout_task: asyncio.Task[None] | None = None
        # VRP emits FTP prompts as separate terminal packets. Keep a small
        # delay by default so automation is exercised against that timing.
        self._transfer_output_delay_seconds = 0.005
        self._transfer_password_delay_seconds = 0.01
        self._send_lock = asyncio.Lock()

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
        self._cancel_transfer_timeout()
        self.callbacks.on_status("Disconnected")
        if message:
            self.callbacks.on_output(f"\n=== {message} ===\n")

    async def send_command(self, command: str) -> None:
        await self.send_text(command.rstrip() + "\r")

    def configure_package_upgrade(
        self,
        package_name: str,
        package_size: int,
        username: str = "device",
        password: str = "device",
        require_startup_confirmation: bool = False,
    ) -> None:
        self._upgrade_package_name = package_name or self._upgrade_package_name
        self._upgrade_package_size = max(1, package_size)
        self._transfer_username = username
        self._transfer_password = password
        self._upgrade_require_startup_confirmation = bool(require_startup_confirmation)
        self._transfer_source_path = self._upgrade_package_name
        self._transfer_source_size = self._upgrade_package_size
        self._transfer_destination_path = ""
        self._transfer_size_mismatch = False

    def configure_managed_transfer(
        self,
        *,
        username: str,
        password: str,
        source_path: str,
        source_size: int,
        destination_path: str,
        size_mismatch: bool = False,
    ) -> None:
        self._transfer_username = username
        self._transfer_password = password
        self._transfer_source_path = source_path
        self._transfer_source_size = max(1, int(source_size))
        self._transfer_destination_path = destination_path
        self._transfer_size_mismatch = bool(size_mismatch)

    def configure_transfer_input_timeout(self, seconds: float) -> None:
        self._transfer_input_timeout = max(0.0, float(seconds))

    def configure_transfer_prompt_timing(
        self,
        *,
        output_delay_seconds: float | None = None,
        password_delay_seconds: float | None = None,
    ) -> None:
        """Configure simulated VRP FTP packet delays for deterministic tests."""
        if output_delay_seconds is not None:
            self._transfer_output_delay_seconds = max(0.0, float(output_delay_seconds))
        if password_delay_seconds is not None:
            self._transfer_password_delay_seconds = max(
                0.0, float(password_delay_seconds)
            )

    async def send_text(self, text: str) -> None:
        async with self._send_lock:
            await self._send_text(text)

    async def _send_text(self, text: str) -> None:
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
            # Real FTP clients do not echo password characters. Username and
            # regular command input remain visible as normal terminal echo.
            if not (
                self._transfer_mode and self._transfer_phase == "password"
            ):
                self.callbacks.on_output(char)

    def _start_boot_sequence(self) -> None:
        if self._boot_task is not None:
            self._boot_task.cancel()
        self._boot_task = asyncio.create_task(self._boot_sequence())

    async def _boot_sequence(self) -> None:
        self._boot_waiting = False
        self.callbacks.on_output("Power on self-test...\n")
        await asyncio.sleep(0.4)
        if not self._connected or self._transfer_mode:
            return
        self.callbacks.on_output("Memory test passed.\n")
        await asyncio.sleep(0.4)
        if not self._connected or self._transfer_mode:
            return
        self._boot_waiting = True
        self.callbacks.on_output("Press Ctrl+B to enter BOOT menu: ")
        await asyncio.sleep(3.0)
        if not self._connected or self._transfer_mode or not self._boot_waiting:
            return
        self._boot_waiting = False
        self.callbacks.on_output("\nAutoboot continuing...\n")
        await asyncio.sleep(0.4)
        if not self._connected or self._transfer_mode:
            return
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
        if self._startup_confirmation_command:
            pending = self._startup_confirmation_command
            self._startup_confirmation_command = ""
            if lowered in {"y", "yes"}:
                require_confirmation = self._upgrade_require_startup_confirmation
                self._upgrade_require_startup_confirmation = False
                try:
                    self._handle_startup_system_software(pending)
                finally:
                    self._upgrade_require_startup_confirmation = require_confirmation
            else:
                self.callbacks.on_output("Info: startup system-software cancelled.\n<sim> ")
            return
        if self._transfer_mode:
            await self._handle_transfer_command(command)
            return
        self.callbacks.on_output("\n")
        if lowered == "help":
            self.callbacks.on_output(
                "Commands: help, reboot, display version, display startup, dir flash:/, ftpget, "
                "menu, admin, biglog [lines], exit\n"
                "Upgrade toggles: sim upgrade fail-download|fail-space|fail-startup on|off\n"
                "Workflow test: sim workflow fail-next on|off\n"
                "Use 'menu' to test Ctrl+B, 'admin' to test Ctrl+A.\n<sim> "
            )
            return
        if lowered.startswith("sim upgrade "):
            self._handle_upgrade_toggle(lowered)
            return
        if lowered.startswith("sim workflow "):
            self._handle_workflow_toggle(lowered)
            return
        if self._workflow_fail_next:
            self._workflow_fail_next = False
            self.callbacks.on_output(f"Unknown command: {command}\n<sim> ")
            return
        if lowered == "screen-length 0 temporary":
            self.callbacks.on_output("Info: Screen length disabled temporarily.\n<sim> ")
            return
        if lowered == "display device":
            self.callbacks.on_output(
                "Slot  Role\n"
                "1     Master\n"
                "2     Standby\n"
                "<sim> "
            )
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
        if lowered.startswith("ftpget "):
            self._handle_ftpget(command)
            return
        if lowered.startswith("delete "):
            self._handle_delete(command)
            return
        if lowered.startswith("ftp ") or lowered.startswith("sftp "):
            self._transfer_mode = "sftp" if lowered.startswith("sftp ") else "ftp"
            self._transfer_phase = "username"
            self._transfer_binary = self._transfer_mode == "sftp"
            # Huawei VRP FTP clients expose the peer address and the current
            # local-user context in the username prompt. Keep this shape in
            # the simulator so transfer automation is tested against the
            # device prompt users actually see.
            await self._emit_transfer_chunks(
                "Connected to simulated transfer service.\r\r\n",
                "User(10.10.10.1):(none): ",
            )
            self._arm_transfer_timeout()
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

    def _handle_workflow_toggle(self, lowered: str) -> None:
        parts = lowered.split()
        if len(parts) != 4 or parts[2] != "fail-next" or parts[3] not in {"on", "off"}:
            self.callbacks.on_output("Usage: sim workflow fail-next on|off\n<sim> ")
            return
        self._workflow_fail_next = parts[3] == "on"
        state = "on" if self._workflow_fail_next else "off"
        self.callbacks.on_output(f"Simulated workflow fail-next is {state}.\n<sim> ")

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

    def _handle_ftpget(self, command: str) -> None:
        try:
            parts = shlex.split(command)
        except ValueError:
            parts = []
        if len(parts) != 7 or parts[1] != "-u" or parts[3] != "-p":
            self.callbacks.on_output(
                "ftpget: usage: ftpget -u USER -p PASSWORD HOST FILE\n<sim> "
            )
            return
        username, password, source_path = parts[2], parts[4], parts[6].replace("\\", "/")
        if username != self._transfer_username or password != self._transfer_password:
            self.callbacks.on_output("ftpget: Login incorrect\n<sim> ")
            return
        if source_path != self._transfer_source_path.replace("\\", "/"):
            self.callbacks.on_output(f"ftpget: No such file: {source_path}\n<sim> ")
            return
        local_name = self._basename(source_path)
        stored_size = self._transfer_source_size
        if self._transfer_size_mismatch:
            stored_size = max(1, stored_size - 1)
        self._files_by_storage.setdefault("flash:/", {})[local_name] = stored_size
        self.callbacks.on_output(
            f"ftpget: {source_path} transfer complete ({stored_size} bytes)\n<sim> "
        )

    async def _handle_transfer_command(self, command: str) -> None:
        lowered = command.lower()
        if self._transfer_phase == "username":
            self._cancel_transfer_timeout()
            if command != self._transfer_username:
                await self._emit_transfer_chunks(
                    "\r\r\n530 Login incorrect.\r\r\n",
                    "<sim> ",
                )
                self._reset_transfer_state()
                return
            self._transfer_phase = "password"
            await self._emit_transfer_chunks(
                "\r\r\n",
                "Password: ",
                delay_seconds=self._transfer_password_delay_seconds,
            )
            self._arm_transfer_timeout()
            return
        if self._transfer_phase == "password":
            self._cancel_transfer_timeout()
            if command != self._transfer_password:
                await self._emit_transfer_chunks(
                    "\r\r\n530 Login incorrect.\r\r\n",
                    "<sim> ",
                )
                self._reset_transfer_state()
                return
            self._transfer_phase = "ready"
            await self._emit_transfer_chunks(
                "\r\r\n230 User logged in.\r\r\n",
                f"{self._transfer_prompt()} ",
            )
            return
        if lowered == "binary":
            if self._transfer_mode != "ftp":
                await self._emit_transfer_chunks(
                    f"\r\r\n500 Unknown SFTP command: {command}\r\r\n",
                    f"{self._transfer_prompt()} ",
                )
                return
            self._transfer_binary = True
            await self._emit_transfer_chunks(
                "\r\r\n200 Type set to I.\r\r\n",
                f"{self._transfer_prompt()} ",
            )
            return
        if lowered.startswith("get "):
            if self._transfer_mode == "ftp" and not self._transfer_binary:
                await self._emit_transfer_chunks(
                    "\r\r\n503 Use binary mode before get.\r\r\n",
                    f"{self._transfer_prompt()} ",
                )
                return
            if self._upgrade_fail_download:
                await self._emit_transfer_chunks(
                    "\r\r\n550 Failed to download file from simulated server.\r\r\n",
                    f"{self._transfer_prompt()} ",
                )
                return
            try:
                parts = shlex.split(command)
            except ValueError:
                parts = []
            if len(parts) != 3:
                await self._emit_transfer_chunks(
                    "\r\r\n501 Usage: get source destination\r\r\n",
                    f"{self._transfer_prompt()} ",
                )
                return
            remote_name = parts[1].replace("\\", "/")
            local_path = parts[2].replace("\\", "/")
            if remote_name != self._transfer_source_path.replace("\\", "/"):
                await self._emit_transfer_chunks(
                    f"\r\r\n550 Source file not found: {remote_name}\r\r\n",
                    f"{self._transfer_prompt()} ",
                )
                return
            if (
                self._transfer_destination_path
                and local_path != self._transfer_destination_path
            ):
                await self._emit_transfer_chunks(
                    f"\r\r\n550 Unexpected destination: {local_path}\r\r\n",
                    f"{self._transfer_prompt()} ",
                )
                return
            storage = self._normalize_storage(local_path)
            local_name = self._basename(local_path) or self._basename(remote_name)
            stored_size = self._transfer_source_size
            if self._transfer_size_mismatch:
                stored_size = max(1, stored_size - 1)
            self._files_by_storage.setdefault(storage, {})[local_name] = stored_size
            await self._emit_transfer_chunks(
                f"\r\r\n226 Transfer complete. {local_name} saved to {storage}\r\r\n",
                f"{self._transfer_prompt()} ",
            )
            return
        if lowered in {"quit", "bye"}:
            self._cancel_transfer_timeout()
            await self._emit_transfer_chunks(
                "\r\r\n221 Goodbye.\r\r\n",
                "<sim> ",
            )
            self._reset_transfer_state()
            return
        if lowered.startswith("put "):
            await self._emit_transfer_chunks(
                "\r\r\n502 PUT is not supported by the simulated device client.\r\r\n",
                f"{self._transfer_prompt()} ",
            )
            return
        await self._emit_transfer_chunks(
            f"\r\r\n500 Unknown FTP command: {command}\r\r\n",
            f"{self._transfer_prompt()} ",
        )

    async def _emit_transfer_chunks(
        self,
        *chunks: str,
        delay_seconds: float | None = None,
    ) -> None:
        """Emit transfer output as ordered packets, like a real terminal."""
        delay = (
            self._transfer_output_delay_seconds
            if delay_seconds is None
            else max(0.0, float(delay_seconds))
        )
        for index, chunk in enumerate(chunks):
            if not self.is_connected:
                return
            if chunk:
                self.callbacks.on_output(chunk)
            if index + 1 < len(chunks) and delay > 0:
                await asyncio.sleep(delay)

    def _arm_transfer_timeout(self) -> None:
        self._cancel_transfer_timeout()
        if self._transfer_input_timeout <= 0:
            return
        phase = self._transfer_phase

        async def expire() -> None:
            await asyncio.sleep(self._transfer_input_timeout)
            if self._transfer_mode and self._transfer_phase == phase:
                self.callbacks.on_output("421 Login input timeout.\n<sim> ")
                self._reset_transfer_state()

        self._transfer_timeout_task = asyncio.create_task(expire())

    def _cancel_transfer_timeout(self) -> None:
        task = self._transfer_timeout_task
        self._transfer_timeout_task = None
        if task is not None:
            task.cancel()

    def _transfer_prompt(self) -> str:
        return "sftp>" if self._transfer_mode == "sftp" else "ftp>"

    def _reset_transfer_state(self) -> None:
        self._cancel_transfer_timeout()
        self._transfer_mode = ""
        self._transfer_phase = ""
        self._transfer_binary = False

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
        if self._upgrade_require_startup_confirmation:
            self._startup_confirmation_command = command
            self.callbacks.on_output(
                "Warning: this will change the next startup system software. Continue? [Y/N]: "
            )
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
