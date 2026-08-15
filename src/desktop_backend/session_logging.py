"""Non-blocking terminal log sinks owned by the Python backend."""

from __future__ import annotations

import queue
import re
import shutil
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, TextIO

from ..terminal_execution import strip_terminal_ansi


LOG_FLUSH_BATCH_RECORDS = 64


class SessionLogSink(Protocol):
    def record(
        self,
        session_id: str,
        device_id: str,
        channel: str,
        text: str,
    ) -> None: ...

    def close_session(self, session_id: str) -> None: ...

    def read_tail(
        self,
        session_id: str,
        device_id: str,
        max_chars: int,
    ) -> tuple[str, bool]: ...

    def shutdown(self) -> None: ...


class NullSessionLogSink:
    def record(
        self,
        session_id: str,
        device_id: str,
        channel: str,
        text: str,
    ) -> None:
        del session_id, device_id, channel, text

    def close_session(self, session_id: str) -> None:
        del session_id

    def read_tail(
        self,
        session_id: str,
        device_id: str,
        max_chars: int,
    ) -> tuple[str, bool]:
        del session_id, device_id, max_chars
        return "", False

    def shutdown(self) -> None:
        return


@dataclass(frozen=True, slots=True)
class _LogCommand:
    kind: str
    session_id: str = ""
    device_id: str = ""
    channel: str = ""
    text: str = ""
    completion: threading.Event | None = None
    root: Path | None = None
    max_bytes: int = 0
    backup_count: int = 0
    result: dict[str, object] | None = None


class FileSessionLogSink:
    """Write terminal records on one background thread with bounded buffering."""

    def __init__(
        self,
        root: Path,
        *,
        queue_size: int = 20_000,
        max_bytes: int = 24 * 1024 * 1024,
        backup_count: int = 5,
    ) -> None:
        self._config_lock = threading.Lock()
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._max_bytes = max(64 * 1024, int(max_bytes))
        self._backup_count = max(1, int(backup_count))
        self._queue: queue.Queue[_LogCommand] = queue.Queue(maxsize=max(100, queue_size))
        self._dropped = 0
        self._drop_lock = threading.Lock()
        self._closed = False
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="device-tui-session-log",
        )
        self._thread.start()

    @property
    def root(self) -> Path:
        with self._config_lock:
            return self._root

    @property
    def max_bytes(self) -> int:
        with self._config_lock:
            return self._max_bytes

    @property
    def backup_count(self) -> int:
        with self._config_lock:
            return self._backup_count

    def configuration(self) -> dict[str, object]:
        with self._config_lock:
            return {
                "root": str(self._root),
                "max_bytes": self._max_bytes,
                "backup_count": self._backup_count,
            }

    def reconfigure(
        self,
        root: Path,
        *,
        max_bytes: int,
        backup_count: int | None = None,
    ) -> dict[str, object]:
        """Atomically move active logs and apply the new runtime policy."""

        new_root = root.expanduser().resolve()
        new_root.mkdir(parents=True, exist_ok=True)
        completion = threading.Event()
        result: dict[str, object] = {}
        self._put_control(
            _LogCommand(
                kind="reconfigure",
                root=new_root,
                max_bytes=max(64 * 1024, int(max_bytes)),
                backup_count=max(1, int(backup_count or self.backup_count)),
                completion=completion,
                result=result,
            )
        )
        if not completion.wait(timeout=10.0):
            raise TimeoutError("Timed out while reconfiguring session logging.")
        error = result.get("error")
        if error:
            raise OSError(str(error))
        return self.configuration() | {"moved_count": int(result.get("moved_count", 0))}

    def start_new_log(self, session_id: str, device_id: str) -> str:
        """Archive the current session log and continue with a fresh file."""

        completion = threading.Event()
        result: dict[str, object] = {}
        self._put_control(
            _LogCommand(
                kind="new_log",
                session_id=session_id,
                device_id=device_id,
                completion=completion,
                result=result,
            )
        )
        if not completion.wait(timeout=5.0):
            raise TimeoutError("Timed out while creating a new session log.")
        error = result.get("error")
        if error:
            raise OSError(str(error))
        return str(result.get("archived_path", ""))

    def record(
        self,
        session_id: str,
        device_id: str,
        channel: str,
        text: str,
    ) -> None:
        if self._closed or not text:
            return
        command = _LogCommand(
            kind="record",
            session_id=session_id,
            device_id=device_id,
            channel=channel,
            text=text,
        )
        try:
            self._queue.put_nowait(command)
        except queue.Full:
            with self._drop_lock:
                self._dropped += 1

    def close_session(self, session_id: str) -> None:
        self._put_control(_LogCommand(kind="close", session_id=session_id))

    def read_tail(
        self,
        session_id: str,
        device_id: str,
        max_chars: int,
    ) -> tuple[str, bool]:
        completion = threading.Event()
        self._put_control(
            _LogCommand(kind="flush", session_id=session_id, completion=completion)
        )
        completion.wait(timeout=2.0)
        path = self.path_for(session_id, device_id)
        if not path.exists():
            return "", False
        limit = max(1_024, min(2_000_000, int(max_chars)))
        size = path.stat().st_size
        read_size = min(size, limit * 4 + 4)
        with path.open("rb") as handle:
            if read_size < size:
                handle.seek(-read_size, 2)
            content = handle.read(read_size).decode("utf-8", errors="replace")
        truncated = read_size < size or len(content) > limit
        return (content[-limit:] if truncated else content), truncated

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._put_control(_LogCommand(kind="shutdown"))
        self._thread.join(timeout=3.0)

    def path_for(self, session_id: str, device_id: str) -> Path:
        return self._path_for_root(self.root, session_id, device_id)

    def _path_for_root(self, root: Path, session_id: str, device_id: str) -> Path:
        safe_device = self._safe_component(device_id, "device")
        safe_session = self._safe_component(session_id, "session")
        return root / f"{safe_device}-{safe_session}.log"

    def _put_control(self, command: _LogCommand) -> None:
        while self._thread.is_alive():
            try:
                self._queue.put(command, timeout=0.2)
                return
            except queue.Full:
                continue

    def _run(self) -> None:
        handles: dict[str, TextIO] = {}
        session_devices: dict[str, str] = {}
        unflushed_records: dict[str, int] = {}
        try:
            while True:
                command = self._queue.get()
                if command.kind == "shutdown":
                    return
                if command.kind == "close":
                    handle = handles.pop(command.session_id, None)
                    if handle is not None:
                        handle.flush()
                        handle.close()
                    session_devices.pop(command.session_id, None)
                    unflushed_records.pop(command.session_id, None)
                    continue
                if command.kind == "flush":
                    handle = handles.get(command.session_id)
                    if handle is not None:
                        handle.flush()
                    unflushed_records[command.session_id] = 0
                    if command.completion is not None:
                        command.completion.set()
                    continue
                if command.kind == "reconfigure":
                    try:
                        moved_count = self._reconfigure_handles(
                            handles,
                            session_devices,
                            command.root or self.root,
                            command.max_bytes,
                            command.backup_count,
                        )
                        if command.result is not None:
                            command.result["moved_count"] = moved_count
                        unflushed_records.clear()
                    except (OSError, shutil.Error) as exc:
                        if command.result is not None:
                            command.result["error"] = str(exc)
                    finally:
                        if command.completion is not None:
                            command.completion.set()
                    continue
                if command.kind == "new_log":
                    try:
                        archived_path = self._start_new_log(
                            handles,
                            session_devices,
                            command.session_id,
                            command.device_id,
                        )
                        if command.result is not None:
                            command.result["archived_path"] = str(archived_path or "")
                        unflushed_records[command.session_id] = 0
                    except OSError as exc:
                        if command.result is not None:
                            command.result["error"] = str(exc)
                    finally:
                        if command.completion is not None:
                            command.completion.set()
                    continue
                session_devices[command.session_id] = command.device_id
                handle = handles.get(command.session_id)
                if handle is None:
                    path = self.path_for(command.session_id, command.device_id)
                    handle = path.open("a", encoding="utf-8", newline="")
                    handles[command.session_id] = handle
                dropped = self._take_dropped()
                if dropped:
                    self._write_record(handle, "SYS", f"Dropped {dropped} buffered log records.\n")
                handle = self._rotate_if_needed(
                    handles,
                    command.session_id,
                    command.device_id,
                    len(strip_terminal_ansi(command.text).encode("utf-8")),
                )
                self._write_record(handle, command.channel, command.text)
                unflushed_records[command.session_id] = unflushed_records.get(command.session_id, 0) + 1
                if (
                    unflushed_records[command.session_id] >= LOG_FLUSH_BATCH_RECORDS
                    or self._queue.empty()
                ):
                    handle.flush()
                    unflushed_records[command.session_id] = 0
        finally:
            for handle in handles.values():
                handle.flush()
                handle.close()

    def _take_dropped(self) -> int:
        with self._drop_lock:
            dropped = self._dropped
            self._dropped = 0
        return dropped

    def _reconfigure_handles(
        self,
        handles: dict[str, TextIO],
        session_devices: dict[str, str],
        new_root: Path,
        max_bytes: int,
        backup_count: int,
    ) -> int:
        old_root = self.root
        new_root.mkdir(parents=True, exist_ok=True)
        for handle in handles.values():
            handle.flush()
            handle.close()
        handles.clear()

        moved: list[tuple[Path, Path]] = []
        displaced: list[tuple[Path, Path]] = []
        try:
            if old_root != new_root:
                for session_id, device_id in session_devices.items():
                    source = self._path_for_root(old_root, session_id, device_id)
                    if not source.exists():
                        continue
                    target = self._path_for_root(new_root, session_id, device_id)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists():
                        archive = self._unique_archive_path(target, "before-move")
                        target.replace(archive)
                        displaced.append((archive, target))
                    shutil.move(str(source), str(target))
                    moved.append((target, source))
        except (OSError, shutil.Error):
            for target, source in reversed(moved):
                if target.exists():
                    source.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(target), str(source))
            for archive, target in reversed(displaced):
                if archive.exists():
                    archive.replace(target)
            self._reopen_handles(handles, session_devices, old_root)
            raise

        with self._config_lock:
            self._root = new_root
            self._max_bytes = max(64 * 1024, int(max_bytes))
            self._backup_count = max(1, int(backup_count))
        self._reopen_handles(handles, session_devices, new_root)
        if old_root != new_root:
            for handle in handles.values():
                self._write_record(handle, "SYS", f"Log location changed from {old_root}\n")
                handle.flush()
        return len(moved)

    def _reopen_handles(
        self,
        handles: dict[str, TextIO],
        session_devices: dict[str, str],
        root: Path,
    ) -> None:
        for session_id, device_id in session_devices.items():
            path = self._path_for_root(root, session_id, device_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            handles[session_id] = path.open("a", encoding="utf-8", newline="")

    def _start_new_log(
        self,
        handles: dict[str, TextIO],
        session_devices: dict[str, str],
        session_id: str,
        device_id: str,
    ) -> Path | None:
        session_devices[session_id] = device_id
        handle = handles.pop(session_id, None)
        if handle is not None:
            handle.flush()
            handle.close()
        path = self.path_for(session_id, device_id)
        archived: Path | None = None
        if path.exists() and path.stat().st_size > 0:
            archived = self._unique_archive_path(path, "manual")
            path.replace(archived)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a", encoding="utf-8", newline="")
        handles[session_id] = handle
        previous = archived.name if archived is not None else "empty log"
        self._write_record(handle, "SYS", f"New log created; previous log: {previous}\n")
        handle.flush()
        return archived

    @staticmethod
    def _unique_archive_path(path: Path, label: str) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        candidate = path.with_name(f"{path.name}.{label}-{stamp}")
        counter = 2
        while candidate.exists():
            candidate = path.with_name(f"{path.name}.{label}-{stamp}-{counter}")
            counter += 1
        return candidate

    def _rotate_if_needed(
        self,
        handles: dict[str, TextIO],
        session_id: str,
        device_id: str,
        incoming_bytes: int,
    ) -> TextIO:
        handle = handles[session_id]
        path = self.path_for(session_id, device_id)
        try:
            current_size = path.stat().st_size
        except OSError:
            return handle
        max_bytes = self.max_bytes
        backup_count = self.backup_count
        if current_size + incoming_bytes <= max_bytes:
            return handle
        handle.flush()
        handle.close()
        for index in range(backup_count, 0, -1):
            source = path.with_name(f"{path.name}.{index}")
            target = path.with_name(f"{path.name}.{index + 1}")
            if index == backup_count:
                source.unlink(missing_ok=True)
            elif source.exists():
                source.replace(target)
        if path.exists():
            path.replace(path.with_name(f"{path.name}.1"))
        new_handle = path.open("a", encoding="utf-8", newline="")
        self._write_record(new_handle, "SYS", f"Log rotated automatically; previous log: {path.name}.1\n")
        handles[session_id] = new_handle
        return new_handle

    @staticmethod
    def _write_record(handle: TextIO, channel: str, text: str) -> None:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        normalized = strip_terminal_ansi(text).replace("\r\n", "\n").replace("\r", "\n")
        handle.write(f"[{timestamp}] [{channel}] {normalized}")
        if not normalized.endswith("\n"):
            handle.write("\n")

    @staticmethod
    def _safe_component(value: str, fallback: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._")
        return normalized[:96] or fallback
