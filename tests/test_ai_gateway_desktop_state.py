"""Desktop-state persistence of the AI gateway result-store config."""
from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from src.app.desktop_state import DESKTOP_STATE_VERSION
from src.app.main_window import DeviceDesktopApp


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _state_path(window: DeviceDesktopApp) -> Path:
    return Path(window.state_path)


def test_desktop_state_version_is_15() -> None:
    assert DESKTOP_STATE_VERSION == 15


def test_ai_gateway_defaults_applied(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    try:
        store = window.ai_gateway_service.result_store
        assert store.max_entries == 500
        assert store.ttl_seconds == 24 * 3600
    finally:
        window.close()


def test_ai_gateway_config_loads_and_clamps(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _ = app
    state_file = tmp_path / "desktop_state.json"
    monkeypatch.setattr(
        DeviceDesktopApp,
        "desktop_state_path",
        staticmethod(lambda: state_file),
    )
    state_file.write_text(
        json.dumps(
            {
                "version": DESKTOP_STATE_VERSION,
                "ai_gateway": {
                    "result_store": {"max_entries": 10000, "ttl_hours": 999},
                },
            }
        ),
        encoding="utf-8",
    )
    window = DeviceDesktopApp()
    try:
        store = window.ai_gateway_service.result_store
        assert store.max_entries == 5000  # clamped to upper bound
        assert store.ttl_seconds == 168 * 3600  # clamped to upper bound
    finally:
        window.close()


def test_ai_gateway_config_low_clamps(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _ = app
    state_file = tmp_path / "desktop_state.json"
    monkeypatch.setattr(
        DeviceDesktopApp,
        "desktop_state_path",
        staticmethod(lambda: state_file),
    )
    state_file.write_text(
        json.dumps(
            {
                "version": DESKTOP_STATE_VERSION,
                "ai_gateway": {
                    "result_store": {"max_entries": 1, "ttl_hours": 0},
                },
            }
        ),
        encoding="utf-8",
    )
    window = DeviceDesktopApp()
    try:
        store = window.ai_gateway_service.result_store
        assert store.max_entries == 50  # clamped to lower bound
        assert store.ttl_seconds == 3600  # 1h lower bound
    finally:
        window.close()


def test_ai_gateway_ignored_for_pre_v15_state(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _ = app
    state_file = tmp_path / "desktop_state.json"
    monkeypatch.setattr(
        DeviceDesktopApp,
        "desktop_state_path",
        staticmethod(lambda: state_file),
    )
    state_file.write_text(
        json.dumps(
            {
                "version": 14,
                "ai_gateway": {
                    "result_store": {"max_entries": 1234, "ttl_hours": 56},
                },
            }
        ),
        encoding="utf-8",
    )
    window = DeviceDesktopApp()
    try:
        store = window.ai_gateway_service.result_store
        assert store.max_entries == 500  # defaults, not the v14 values
        assert store.ttl_seconds == 24 * 3600
    finally:
        window.close()


def test_ai_gateway_config_round_trip(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _ = app
    state_file = tmp_path / "desktop_state.json"
    monkeypatch.setattr(
        DeviceDesktopApp,
        "desktop_state_path",
        staticmethod(lambda: state_file),
    )
    window = DeviceDesktopApp()
    try:
        window.ai_gateway_service.result_store.max_entries = 2000
        window.ai_gateway_service.result_store.ttl_seconds = 72 * 3600
        window.save_desktop_state()
    finally:
        window.close()

    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved["version"] == 15
    assert saved["ai_gateway"]["result_store"]["max_entries"] == 2000
    assert saved["ai_gateway"]["result_store"]["ttl_hours"] == 72
    # No result bodies are persisted (device output stays in memory).
    assert "results" not in saved["ai_gateway"]
    assert set(saved["ai_gateway"]["result_store"]) == {"max_entries", "ttl_hours"}
