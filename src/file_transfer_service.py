"""Local FTP/SFTP transfer service helpers."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


LogCallback = Callable[[str], None]


@dataclass(slots=True)
class TransferServiceConfig:
    protocol: str
    host: str
    port: int
    root: Path
    username: str
    password: str
    writable: bool = True


class TransferServiceController:
    """Owns one local FTP or SFTP service instance."""

    def __init__(self, on_log: LogCallback) -> None:
        self._on_log = on_log
        self._protocol = ""
        self._ftp_server = None
        self._sftp_loop: asyncio.AbstractEventLoop | None = None
        self._sftp_acceptor = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._bound_port = 0

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def protocol(self) -> str:
        return self._protocol

    @property
    def bound_port(self) -> int:
        return self._bound_port

    def start(self, config: TransferServiceConfig) -> None:
        with self._lock:
            if self.is_running:
                raise RuntimeError("文件传输服务已经在运行。")
            config.root = config.root.expanduser().resolve()
            if not config.root.exists() or not config.root.is_dir():
                raise RuntimeError(f"共享目录不存在: {config.root}")
            protocol = config.protocol.lower()
            if protocol == "ftp":
                self._start_ftp(config)
            elif protocol == "sftp":
                self._start_sftp(config)
            else:
                raise RuntimeError(f"不支持的传输协议: {config.protocol}")
            self._protocol = protocol

    def stop(self) -> None:
        with self._lock:
            if self._protocol == "ftp" and self._ftp_server is not None:
                self._ftp_server.close_all()
            if self._protocol == "sftp" and self._sftp_loop is not None:
                loop = self._sftp_loop
                acceptor = self._sftp_acceptor

                async def close_acceptor() -> None:
                    if acceptor is not None:
                        acceptor.close()
                        await acceptor.wait_closed()

                try:
                    asyncio.run_coroutine_threadsafe(close_acceptor(), loop).result(timeout=2)
                except Exception as exc:
                    self._on_log(f"SFTP 停止时出现异常: {exc}")
                loop.call_soon_threadsafe(loop.stop)

            thread = self._thread
            self._ftp_server = None
            self._sftp_loop = None
            self._sftp_acceptor = None
            self._protocol = ""
            self._bound_port = 0

        if thread is not None:
            thread.join(timeout=3)
        self._thread = None
        self._on_log("文件传输服务已停止。")

    def _start_ftp(self, config: TransferServiceConfig) -> None:
        try:
            from pyftpdlib.authorizers import DummyAuthorizer
            from pyftpdlib.handlers import FTPHandler
            from pyftpdlib.servers import FTPServer
        except ModuleNotFoundError as exc:
            raise RuntimeError("FTP 服务需要安装 pyftpdlib。请运行: python -m pip install pyftpdlib") from exc

        permissions = "elradfmwMT" if config.writable else "elr"
        authorizer = DummyAuthorizer()
        authorizer.add_user(config.username, config.password, str(config.root), perm=permissions)
        on_log = self._on_log

        class LoggingFTPHandler(FTPHandler):
            def on_connect(self) -> None:
                on_log(f"FTP 连接: {self.remote_ip}:{self.remote_port}")

            def on_disconnect(self) -> None:
                on_log(f"FTP 断开: {self.remote_ip}:{self.remote_port}")

            def on_login(self, username: str) -> None:
                on_log(f"FTP 登录: {username}")

            def on_file_sent(self, file: str) -> None:
                on_log(f"FTP 下载: {file}")

            def on_file_received(self, file: str) -> None:
                on_log(f"FTP 上传: {file}")

        LoggingFTPHandler.authorizer = authorizer
        try:
            server = FTPServer((config.host, config.port), LoggingFTPHandler)
        except OSError as exc:
            raise RuntimeError(self._bind_error_message("FTP", config, exc)) from exc
        self._ftp_server = server
        self._bound_port = int(server.socket.getsockname()[1])

        def run() -> None:
            self._on_log(f"FTP 服务已启动: {config.host}:{self._bound_port} -> {config.root}")
            try:
                server.serve_forever(timeout=0.5, blocking=True)
            except Exception as exc:
                self._on_log(f"FTP 服务异常: {exc}")

        self._thread = threading.Thread(target=run, daemon=True, name="device-tui-ftp-server")
        self._thread.start()

    def _start_sftp(self, config: TransferServiceConfig) -> None:
        try:
            import asyncssh
        except ModuleNotFoundError as exc:
            raise RuntimeError("SFTP 服务需要安装 asyncssh。") from exc

        on_log = self._on_log

        class PasswordSFTPServer(asyncssh.SSHServer):
            def connection_made(self, conn) -> None:
                peer = conn.get_extra_info("peername")
                on_log(f"SFTP 连接: {peer}")

            def connection_lost(self, exc) -> None:
                if exc:
                    on_log(f"SFTP 断开: {exc}")
                else:
                    on_log("SFTP 断开。")

            def begin_auth(self, username: str) -> bool:
                return True

            def password_auth_supported(self) -> bool:
                return True

            def validate_password(self, username: str, password: str) -> bool:
                ok = username == config.username and password == config.password
                on_log(f"SFTP {'登录成功' if ok else '登录失败'}: {username}")
                return ok

        class SharedDirectorySFTPServer(asyncssh.SFTPServer):
            def _ensure_writable(self) -> None:
                if not config.writable:
                    raise asyncssh.SFTPPermissionDenied("共享目录为只读")

            def open(self, path, pflags, attrs):
                write_flags = (
                    asyncssh.FXF_WRITE
                    | asyncssh.FXF_APPEND
                    | asyncssh.FXF_CREAT
                    | asyncssh.FXF_TRUNC
                    | asyncssh.FXF_EXCL
                )
                if pflags & write_flags:
                    self._ensure_writable()
                return super().open(path, pflags, attrs)

            def open56(self, path, desired_access, flags, attrs):
                write_access = (
                    asyncssh.ACE4_WRITE_DATA
                    | asyncssh.ACE4_APPEND_DATA
                    | asyncssh.ACE4_WRITE_ATTRIBUTES
                )
                disposition = flags & asyncssh.FXF_ACCESS_DISPOSITION
                if (
                    desired_access & write_access
                    or flags & asyncssh.FXF_APPEND_DATA
                    or disposition != asyncssh.FXF_OPEN_EXISTING
                ):
                    self._ensure_writable()
                return super().open56(path, desired_access, flags, attrs)

            def write(self, file_obj, offset, data):
                self._ensure_writable()
                return super().write(file_obj, offset, data)

            def setstat(self, path, attrs):
                self._ensure_writable()
                return super().setstat(path, attrs)

            def lsetstat(self, path, attrs):
                self._ensure_writable()
                return super().lsetstat(path, attrs)

            def fsetstat(self, file_obj, attrs):
                self._ensure_writable()
                return super().fsetstat(file_obj, attrs)

            def remove(self, path):
                self._ensure_writable()
                return super().remove(path)

            def mkdir(self, path, attrs):
                self._ensure_writable()
                return super().mkdir(path, attrs)

            def rmdir(self, path):
                self._ensure_writable()
                return super().rmdir(path)

            def rename(self, oldpath, newpath):
                self._ensure_writable()
                return super().rename(oldpath, newpath)

            def posix_rename(self, oldpath, newpath):
                self._ensure_writable()
                return super().posix_rename(oldpath, newpath)

            def symlink(self, oldpath, newpath):
                self._ensure_writable()
                return super().symlink(oldpath, newpath)

            def link(self, oldpath, newpath):
                self._ensure_writable()
                return super().link(oldpath, newpath)

        async def run_server() -> object:
            host_key = asyncssh.generate_private_key("ssh-rsa")
            chroot = str(config.root).encode()
            return await asyncssh.create_server(
                PasswordSFTPServer,
                config.host,
                config.port,
                server_host_keys=[host_key],
                sftp_factory=lambda chan: SharedDirectorySFTPServer(chan, chroot=chroot),
            )

        loop = asyncio.new_event_loop()
        ready: threading.Event = threading.Event()
        failure: list[BaseException] = []

        def run() -> None:
            asyncio.set_event_loop(loop)
            try:
                self._sftp_acceptor = loop.run_until_complete(run_server())
                self._sftp_loop = loop
                self._bound_port = int(self._sftp_acceptor.get_port())
                self._on_log(f"SFTP 服务已启动: {config.host}:{self._bound_port} -> {config.root}")
                ready.set()
                loop.run_forever()
            except BaseException as exc:
                failure.append(exc)
                ready.set()
            finally:
                loop.close()

        self._thread = threading.Thread(target=run, daemon=True, name="device-tui-sftp-server")
        self._thread.start()
        if not ready.wait(timeout=5):
            loop.call_soon_threadsafe(loop.stop)
            self._thread = None
            raise RuntimeError("SFTP 服务启动超时。")
        if failure:
            self._bound_port = 0
            self._thread = None
            if isinstance(failure[0], OSError):
                raise RuntimeError(self._bind_error_message("SFTP", config, failure[0])) from failure[0]
            raise RuntimeError(f"SFTP 服务启动失败: {failure[0]}")

    @staticmethod
    def _bind_error_message(protocol: str, config: TransferServiceConfig, exc: OSError) -> str:
        message = f"{protocol} 服务启动失败: {exc}"
        if getattr(exc, "winerror", None) in {10013, 10048} or getattr(exc, "errno", None) in {13, 48, 98, 10013, 10048}:
            fallback_port = 2121 if protocol == "FTP" else 2222
            message = (
                f"{message}\n"
                f"可能是 {config.host}:{config.port} 已被占用，或当前用户没有监听该端口的权限。"
                f"建议改用 {fallback_port}，或以管理员身份启动。"
            )
        return message
