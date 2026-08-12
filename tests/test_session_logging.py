from __future__ import annotations

from pathlib import Path

from src.desktop_backend.session_logging import FileSessionLogSink


def test_file_session_log_sink_writes_plain_redacted_records(tmp_path: Path) -> None:
    sink = FileSessionLogSink(tmp_path)
    path = sink.path_for("session/unsafe", "device:unsafe")

    sink.record("session/unsafe", "device:unsafe", "OUT", "\x1b[32mready\x1b[0m\r\n")
    sink.record("session/unsafe", "device:unsafe", "OUT", "password=***\r\n")
    tail, truncated = sink.read_tail("session/unsafe", "device:unsafe", 10_000)
    sink.close_session("session/unsafe")
    sink.shutdown()

    content = path.read_text(encoding="utf-8")
    assert tail == content
    assert not truncated
    assert "ready" in content
    assert "\x1b[32m" not in content
    assert "password=***" in content
    assert "session/unsafe" not in path.name


def test_file_session_log_sink_rotates_large_logs(tmp_path: Path) -> None:
    sink = FileSessionLogSink(tmp_path, max_bytes=64 * 1024, backup_count=2)
    path = sink.path_for("session-1", "device-1")

    sink.record("session-1", "device-1", "OUT", "A" * 60_000)
    sink.record("session-1", "device-1", "OUT", "B" * 60_000)
    tail, truncated = sink.read_tail("session-1", "device-1", 200_000)
    sink.shutdown()

    rotated = path.with_name(f"{path.name}.1")
    assert rotated.exists()
    assert "A" * 1_000 in rotated.read_text(encoding="utf-8")
    assert "Log rotated automatically" in tail
    assert "B" * 1_000 in tail
    assert not truncated


def test_file_session_log_sink_reconfigures_and_moves_active_logs(tmp_path: Path) -> None:
    original_root = tmp_path / "original"
    new_root = tmp_path / "moved"
    sink = FileSessionLogSink(original_root, max_bytes=2 * 1024 * 1024, backup_count=2)
    original_path = sink.path_for("session-1", "device-1")

    sink.record("session-1", "device-1", "OUT", "before move\n")
    sink.read_tail("session-1", "device-1", 10_000)
    result = sink.reconfigure(
        new_root,
        max_bytes=3 * 1024 * 1024,
        backup_count=4,
    )
    sink.record("session-1", "device-1", "OUT", "after move\n")
    tail, truncated = sink.read_tail("session-1", "device-1", 10_000)
    moved_path = sink.path_for("session-1", "device-1")
    sink.shutdown()

    assert result["moved_count"] == 1
    assert result["root"] == str(new_root.resolve())
    assert result["max_bytes"] == 3 * 1024 * 1024
    assert result["backup_count"] == 4
    assert not original_path.exists()
    assert moved_path.parent == new_root.resolve()
    assert "before move" in tail
    assert "after move" in tail
    assert "Log location changed" in tail
    assert truncated is False


def test_file_session_log_sink_starts_fresh_manual_log(tmp_path: Path) -> None:
    sink = FileSessionLogSink(tmp_path)
    path = sink.path_for("session-1", "device-1")
    sink.record("session-1", "device-1", "OUT", "old content\n")
    sink.read_tail("session-1", "device-1", 10_000)

    archived = Path(sink.start_new_log("session-1", "device-1"))
    sink.record("session-1", "device-1", "OUT", "new content\n")
    tail, _ = sink.read_tail("session-1", "device-1", 10_000)
    sink.shutdown()

    assert archived.exists()
    assert archived.read_text(encoding="utf-8").find("old content") >= 0
    assert path.exists()
    assert "old content" not in tail
    assert "New log created" in tail
    assert "new content" in tail


def test_file_session_log_sink_preserves_destination_collision_on_move(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    sink = FileSessionLogSink(source_root)
    sink.record("session-1", "device-1", "OUT", "active source\n")
    sink.read_tail("session-1", "device-1", 10_000)

    destination_path = destination_root / sink.path_for("session-1", "device-1").name
    destination_path.parent.mkdir(parents=True)
    destination_path.write_text("older destination\n", encoding="utf-8")
    sink.reconfigure(destination_root, max_bytes=1024 * 1024)
    tail, _ = sink.read_tail("session-1", "device-1", 10_000)
    sink.shutdown()

    archives = list(destination_root.glob(f"{destination_path.name}.before-move-*"))
    assert len(archives) == 1
    assert archives[0].read_text(encoding="utf-8") == "older destination\n"
    assert "active source" in tail
