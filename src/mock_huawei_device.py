from __future__ import annotations

import argparse
import asyncio
import contextlib
import os


IAC = 255
DO = 253
DONT = 254
WILL = 251
WONT = 252
SB = 250
SE = 240

SUPPRESS_GO_AHEAD = 3
ECHO = 1

NEGOTIATION_COMMANDS = {DO, DONT, WILL, WONT}

DEFAULT_USERNAME = os.getenv("MOCK_HUAWEI_USERNAME", "lon")
DEFAULT_PASSWORD = os.getenv("MOCK_HUAWEI_PASSWORD", "202188")
DEFAULT_HOSTNAME = os.getenv("MOCK_HUAWEI_HOSTNAME", "Lab-Huawei")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a mock Huawei Telnet device.")
    parser.add_argument("--host", default=os.getenv("MOCK_HUAWEI_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MOCK_HUAWEI_PORT", "2323")),
    )
    parser.add_argument("--username", default=DEFAULT_USERNAME)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--hostname", default=DEFAULT_HOSTNAME)
    return parser.parse_args()


class MockHuaweiCliSession:
    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        username: str,
        password: str,
        hostname: str,
    ) -> None:
        self.reader = reader
        self.writer = writer
        self.expected_username = username
        self.expected_password = password
        self.hostname = hostname
        self.system_view = False
        self.screen_length_disabled = False
        self.current_user = username
        self._iac_buffer = bytearray()
        self._closed = False

    async def run(self) -> None:
        try:
            await self._send_negotiation()
            username = await self._prompt("Username: ", echo=True)
            password = await self._prompt("Password: ", echo=False)
            if username != self.expected_username or password != self.expected_password:
                await self._write("\r\nError: Authentication failed.\r\n")
                return

            await self._write(
                "\r\nInfo: Login succeeded.\r\n"
                "Warning: Telnet is not a secure protocol.\r\n"
                "Use SSH in production environments.\r\n\r\n"
            )
            await self._show_prompt()
            while not self._closed:
                command = await self._read_command()
                if command is None:
                    break
                await self._handle_command(command)
        finally:
            self.writer.close()
            with contextlib.suppress(OSError):
                await self.writer.wait_closed()

    async def _send_negotiation(self) -> None:
        self.writer.write(bytes([IAC, WILL, SUPPRESS_GO_AHEAD, IAC, WILL, ECHO]))
        await self.writer.drain()

    async def _prompt(self, label: str, echo: bool) -> str:
        await self._write(label)
        value = await self._read_command(mask_input=not echo)
        if value is None:
            raise ConnectionError("Client disconnected during login.")
        return value

    async def _read_command(self, mask_input: bool = False) -> str | None:
        buffer = bytearray()
        while True:
            chunk = await self.reader.read(1024)
            if not chunk:
                return None
            incoming = self._strip_telnet_bytes(chunk)
            if not incoming:
                continue
            for byte in incoming:
                if byte in (10,):
                    continue
                if byte == 13:
                    if mask_input:
                        await self._write("\r\n")
                    else:
                        await self._write("\r\n")
                    return buffer.decode("utf-8", errors="ignore").strip()
                if byte in (8, 127):
                    if buffer:
                        buffer.pop()
                    continue
                buffer.append(byte)
                if not mask_input:
                    self.writer.write(bytes([byte]))
                    await self.writer.drain()

    async def _handle_command(self, command: str) -> None:
        if not command:
            await self._show_prompt()
            return

        lowered = command.lower()
        if lowered == "screen-length 0 temporary":
            self.screen_length_disabled = True
            await self._write(
                "Info: The configuration takes effect on the current user terminal interface only.\r\n"
            )
        elif lowered == "display version":
            await self._write(
                "Huawei Versatile Routing Platform Software\r\n"
                "VRP (R) software, Version 8.220 (Mock build)\r\n"
                f"Device name: {self.hostname}\r\n"
                "Patch Version: V200R013C10SPC500\r\n"
                "Uptime is 16 weeks, 2 days, 1 hour, 5 minutes\r\n"
            )
        elif lowered == "display current-configuration":
            await self._write(
                "sysname {hostname}\r\n"
                "stelnet server enable\r\n"
                "interface GigabitEthernet0/0/0\r\n"
                " ip address 192.168.10.1 255.255.255.0\r\n"
                "interface GigabitEthernet0/0/1\r\n"
                " undo shutdown\r\n"
                "ospf 1\r\n"
                " area 0.0.0.0\r\n"
                "  network 192.168.10.0 0.0.0.255\r\n".format(hostname=self.hostname)
            )
        elif lowered == "display ip interface brief":
            await self._write(
                "Interface                         IP Address/Mask      Physical   Protocol\r\n"
                "GigabitEthernet0/0/0             192.168.10.1/24      up         up\r\n"
                "GigabitEthernet0/0/1             unassigned           down       down\r\n"
                "LoopBack0                        10.255.255.1/32      up         up\r\n"
            )
        elif lowered == "system-view":
            self.system_view = True
            await self._write("Enter system view, return user view with Ctrl+Z.\r\n")
        elif lowered in {"quit", "return"}:
            if self.system_view:
                self.system_view = False
            else:
                await self._write("Info: Connection closed by foreign host.\r\n")
                self._closed = True
                return
        elif lowered in {"undo terminal monitor", "terminal monitor"}:
            await self._write("Info: Command accepted.\r\n")
        else:
            await self._write(f"Error: Unrecognized command found at '^' position: {command}\r\n")

        if not self._closed:
            await self._show_prompt()

    async def _show_prompt(self) -> None:
        prompt = f"[{self.hostname}]" if self.system_view else f"<{self.hostname}>"
        await self._write(prompt)

    async def _write(self, text: str) -> None:
        self.writer.write(text.encode("utf-8"))
        await self.writer.drain()

    def _strip_telnet_bytes(self, data: bytes) -> bytes:
        visible = bytearray()
        payload = self._iac_buffer + bytearray(data)
        self._iac_buffer.clear()
        index = 0
        while index < len(payload):
            byte = payload[index]
            if byte != IAC:
                if byte != 0:
                    visible.append(byte)
                index += 1
                continue

            if index + 1 >= len(payload):
                self._iac_buffer.extend(payload[index:])
                break

            command = payload[index + 1]
            if command == IAC:
                visible.append(IAC)
                index += 2
                continue

            if command in NEGOTIATION_COMMANDS:
                if index + 2 >= len(payload):
                    self._iac_buffer.extend(payload[index:])
                    break
                index += 3
                continue

            if command == SB:
                end_index = payload.find(bytes([IAC, SE]), index + 2)
                if end_index == -1:
                    self._iac_buffer.extend(payload[index:])
                    break
                index = end_index + 2
                continue

            index += 2

        return bytes(visible)


async def handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    username: str,
    password: str,
    hostname: str,
) -> None:
    peer = writer.get_extra_info("peername")
    session = MockHuaweiCliSession(reader, writer, username, password, hostname)
    print(f"Client connected: {peer}")
    try:
        await session.run()
    except ConnectionError:
        pass
    finally:
        print(f"Client disconnected: {peer}")


async def run_server(args: argparse.Namespace) -> None:
    server = await asyncio.start_server(
        lambda reader, writer: handle_client(reader, writer, args.username, args.password, args.hostname),
        host=args.host,
        port=args.port,
    )
    addresses = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
    print(f"Mock Huawei device listening on {addresses}")
    print(f"Username: {args.username}")
    print(f"Password: {args.password}")
    print(f"Hostname: {args.hostname}")
    async with server:
        await server.serve_forever()


def main() -> None:
    args = parse_args()
    try:
        asyncio.run(run_server(args))
    except KeyboardInterrupt:
        print("Mock Huawei device stopped.")


if __name__ == "__main__":
    main()
