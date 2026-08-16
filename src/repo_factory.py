"""Legacy PySide repository factory; Electron uses DeviceSourceService."""

from __future__ import annotations

import os

from device_tui.plugin_api import DEVICE_SOURCE_ID_PATTERN

from ._sample_data import CURRENT_USER
from .api_client import create_http_client_from_env
from .repository import ApiDeviceRepository, DeviceRepository, SampleDeviceRepository


def _configured_source_id(variable: str) -> str:
    source = os.getenv(variable, "").strip().lower()
    return source if DEVICE_SOURCE_ID_PATTERN.fullmatch(source) else ""


def create_repository_from_env() -> DeviceRepository:
    forced = _configured_source_id("DEVICE_TUI_DATA_SOURCE")
    preferred = _configured_source_id("DEVICE_TUI_DEFAULT_DATA_SOURCE")
    if not preferred and os.getenv("DEVICE_TUI_API_BASE_URL", "").strip():
        preferred = "api"
    source = forced or preferred or "sample"
    if source == "api" and os.getenv("DEVICE_TUI_API_BASE_URL", "").strip():
        try:
            refresh_seconds = float(os.getenv("DEVICE_TUI_REFRESH_SECONDS", "30"))
        except ValueError:
            refresh_seconds = 30.0
        return ApiDeviceRepository(
            create_http_client_from_env(),
            refresh_interval_seconds=refresh_seconds,
        )
    try:
        sample_count = int(os.getenv("DEVICE_TUI_SAMPLE_DEVICE_COUNT", "0") or "0")
    except ValueError:
        sample_count = 0
    return SampleDeviceRepository(
        current_user=os.getenv("DEVICE_TUI_CURRENT_USER", CURRENT_USER),
        device_count=sample_count,
    )
