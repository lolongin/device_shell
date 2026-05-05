from __future__ import annotations

import argparse
import asyncio
import os
import shlex
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePosixPath

import asyncssh

try:
    from .mock_terminal import AnsiKeyParser, InputToken, TerminalLineEditor
except ImportError:
    from mock_terminal import AnsiKeyParser, InputToken, TerminalLineEditor


DEFAULT_HOST = os.getenv("MOCK_LINUX_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("MOCK_LINUX_PORT", "2200"))
DEFAULT_USERNAME = os.getenv("MOCK_LINUX_USERNAME", "ops")
DEFAULT_PASSWORD = os.getenv("MOCK_LINUX_PASSWORD", "ops123")
DEFAULT_HOSTNAME = os.getenv("MOCK_LINUX_HOSTNAME", "mock-linux")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a mock Linux SSH server.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--username", default=DEFAULT_USERNAME)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--hostname", default=DEFAULT_HOSTNAME)
    return parser.parse_args()


@dataclass(slots=True)
class MockLinuxState:
    hostname: str
    files: dict[str, str] = field(default_factory=dict)
    directories: set[str] = field(
        default_factory=lambda: {"/", "/tmp", "/home", "/tmp/huawei_logs"}
    )

    def ensure_home(self, username: str) -> str:
        home = f"/home/{username}"
        self.directories.add(home)
        return home

    def normalize_path(self, path: str, cwd: str) -> str:
        candidate = PurePosixPath(path)
        if not candidate.is_absolute():
            candidate = PurePosixPath(cwd) / candidate
        normalized = str(candidate)
        return normalized or "/"

    def list_entries(self, path: str) -> list[str]:
        base = path.rstrip("/") or "/"
        prefix = "/" if base == "/" else f"{base}/"
        entries: set[str] = set()
        for directory in self.directories:
            if directory == base:
                continue
            if directory.startswith(prefix):
                remainder = directory[len(prefix) :]
                if remainder and "/" not in remainder:
                    entries.add(remainder)
        for filename in self.files:
            if filename.startswith(prefix):
                remainder = filename[len(prefix) :]
                if remainder and "/" not in remainder:
                    entries.add(remainder)
        return sorted(entries)


class MockLinuxSshServer(asyncssh.SSHServer):
    def __init__(self, username: str, password: str) -> None:
        self.expected_username = username
        self.expected_password = password

    def connection_made(self, conn: asyncssh.SSHServerConnection) -> None:
        peer = conn.get_extra_info("peername")
        print(f"SSH client connected: {peer}")

    def connection_lost(self, exc: Exception | None) -> None:
        if exc:
            print(f"SSH client disconnected with error: {exc}")
        else:
            print("SSH client disconnected")

    def begin_auth(self, username: str) -> bool:
        return True

    def password_auth_supported(self) -> bool:
        return True

    def validate_password(self, username: str, password: str) -> bool:
        return username == self.expected_username and password == self.expected_password


class MockLinuxCommandProcessor:
    def __init__(self, state: MockLinuxState, username: str) -> None:
        self.state = state
        self.username = username
        self.cwd = state.ensure_home(username)
        self._input_parser = AnsiKeyParser()

    async def handle_process(self, process: asyncssh.SSHServerProcess[str]) -> None:
        if process.command is None:
            await self._run_shell(process)
            return

        stdout, stderr, exit_status = self._execute(process.command)
        if stdout:
            process.stdout.write(stdout)
        if stderr:
            process.stderr.write(stderr)
        process.exit(exit_status)

    async def _run_shell(self, process: asyncssh.SSHServerProcess[str]) -> None:
        process.stdout.write(
            f"Welcome to {self.state.hostname} mock Linux shell.\r\n"
            "Use this for workflow testing only.\r\n"
        )
        while not process.stdout.is_closing():
            process.stdout.write(self._prompt())
            command = await self._read_command(process)
            if command is None:
                break
            if not command:
                continue
            if command in {"exit", "quit", "logout"}:
                break
            stdout, stderr, _ = self._execute(command)
            if stdout:
                process.stdout.write(stdout)
            if stderr:
                process.stderr.write(stderr)

        process.exit(0)

    async def _read_command(self, process: asyncssh.SSHServerProcess[str]) -> str | None:
        editor = TerminalLineEditor()
        while not process.stdout.is_closing():
            chunk = await process.stdin.read(1)
            if not chunk:
                return None
            for token in self._input_parser.feed(chunk):
                command = await self._handle_input_token(process, editor, token)
                if command is not None:
                    return command
        return None

    async def _handle_input_token(
        self,
        process: asyncssh.SSHServerProcess[str],
        editor: TerminalLineEditor,
        token: InputToken,
    ) -> str | None:
        if token.kind == "char":
            redraw = editor.insert(token.value, echo=True)
            if redraw:
                process.stdout.write(redraw)
            return None

        if token.kind == "backspace":
            redraw = editor.backspace(echo=True)
            if redraw:
                process.stdout.write(redraw)
            return None

        if token.kind == "delete":
            redraw = editor.delete(echo=True)
            if redraw:
                process.stdout.write(redraw)
            return None

        if token.kind == "left":
            redraw = editor.move_left()
            if redraw:
                process.stdout.write(redraw)
            return None

        if token.kind == "right":
            redraw = editor.move_right()
            if redraw:
                process.stdout.write(redraw)
            return None

        if token.kind == "home":
            redraw = editor.move_home()
            if redraw:
                process.stdout.write(redraw)
            return None

        if token.kind == "end":
            redraw = editor.move_end()
            if redraw:
                process.stdout.write(redraw)
            return None

        if token.kind == "enter":
            process.stdout.write("\r\n")
            return editor.submit().strip()

        if token.kind == "interrupt":
            editor.clear()
            process.stdout.write("^C\r\n")
            return ""

        if token.kind == "eof":
            return None

        return None

    def _prompt(self) -> str:
        return f"{self.username}@{self.state.hostname}:{self.cwd}$ "

    def _execute(self, command: str) -> tuple[str, str, int]:
        stripped = command.strip()
        if not stripped:
            return "", "", 0

        try:
            tokens = shlex.split(stripped)
        except ValueError as exc:
            return "", f"bash: parse error: {exc}\n", 2

        if not tokens:
            return "", "", 0

        if tokens[0] == "mkdir" and len(tokens) >= 3 and tokens[1] == "-p":
            for raw_path in tokens[2:]:
                path = self.state.normalize_path(raw_path, self.cwd)
                self.state.directories.add(path)
            return "", "", 0

        if tokens[0] == "pwd":
            return f"{self.cwd}\n", "", 0

        if tokens[0] == "whoami":
            return f"{self.username}\n", "", 0

        if tokens[0] == "hostname":
            return f"{self.state.hostname}\n", "", 0

        if tokens[0] == "uname":
            return (
                f"Linux {self.state.hostname} 5.10.0-mock #1 SMP PREEMPT_DYNAMIC "
                "Mock-Ubuntu x86_64 GNU/Linux\n",
                "",
                0,
            )

        if tokens[0] == "date":
            return f"{datetime.now().strftime('%a %b %d %H:%M:%S %Y')}\n", "", 0

        if tokens[0] == "cd":
            path = tokens[1] if len(tokens) > 1 else self.state.ensure_home(self.username)
            normalized = self.state.normalize_path(path, self.cwd)
            self.state.directories.add(normalized)
            self.cwd = normalized
            return "", "", 0

        if tokens[0] == "ls":
            target = tokens[-1] if len(tokens) > 1 and not tokens[-1].startswith("-") else self.cwd
            path = self.state.normalize_path(target, self.cwd)
            if path not in self.state.directories:
                return "", f"ls: cannot access '{target}': No such file or directory\n", 2
            entries = self.state.list_entries(path)
            return ("\n".join(entries) + "\n") if entries else "", "", 0

        if tokens[0] == "cat" and len(tokens) == 2:
            path = self.state.normalize_path(tokens[1], self.cwd)
            if path not in self.state.files:
                return "", f"cat: {tokens[1]}: No such file or directory\n", 1
            return self.state.files[path], "", 0

        if tokens[0] == "touch" and len(tokens) >= 2:
            for raw_path in tokens[1:]:
                path = self.state.normalize_path(raw_path, self.cwd)
                parent = str(PurePosixPath(path).parent) or "/"
                self.state.directories.add(parent)
                self.state.files.setdefault(path, "")
            return "", "", 0

        if tokens[0] == "echo":
            return self._handle_echo(tokens)

        if stripped == "find /tmp/huawei_logs":
            entries = [
                path
                for path in sorted(self.state.files)
                if path.startswith("/tmp/huawei_logs")
            ]
            return ("\n".join(entries) + "\n") if entries else "", "", 0

        return "", f"bash: {tokens[0]}: command not found\n", 127

    def _handle_echo(self, tokens: list[str]) -> tuple[str, str, int]:
        if ">" in tokens or ">>" in tokens:
            redirect = ">>" if ">>" in tokens else ">"
            index = tokens.index(redirect)
            if index == len(tokens) - 1:
                return "", "bash: syntax error near unexpected token `newline'\n", 2
            text = " ".join(tokens[1:index])
            target = self.state.normalize_path(tokens[index + 1], self.cwd)
            parent = str(PurePosixPath(target).parent) or "/"
            self.state.directories.add(parent)
            content = text + "\n"
            if redirect == ">>":
                self.state.files[target] = self.state.files.get(target, "") + content
            else:
                self.state.files[target] = content
            return "", "", 0

        return " ".join(tokens[1:]) + "\n", "", 0


async def run_server(args: argparse.Namespace) -> None:
    state = MockLinuxState(hostname=args.hostname)
    host_key = asyncssh.generate_private_key("ssh-rsa")

    async def process_factory(process: asyncssh.SSHServerProcess[str]) -> None:
        connection = process.channel.get_connection()
        username = connection.get_extra_info("username") or args.username
        processor = MockLinuxCommandProcessor(state, username)
        await processor.handle_process(process)

    server = await asyncssh.listen(
        args.host,
        args.port,
        server_factory=lambda: MockLinuxSshServer(args.username, args.password),
        server_host_keys=[host_key],
        process_factory=process_factory,
        encoding="utf-8",
    )

    addresses = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
    print(f"Mock Linux SSH listening on {addresses}")
    print(f"Username: {args.username}")
    print(f"Password: {args.password}")
    print(f"Hostname: {args.hostname}")
    print("Suggested workflow check: /collect_log")

    try:
        await server.wait_closed()
    finally:
        server.close()


def main() -> None:
    args = parse_args()
    try:
        asyncio.run(run_server(args))
    except KeyboardInterrupt:
        print("Mock Linux SSH stopped.")


if __name__ == "__main__":
    main()
