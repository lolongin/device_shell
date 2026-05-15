"""Repository factory — selects implementation based on environment."""

from __future__ import annotations

import os

from ._sample_data import CURRENT_USER
from .api_client import create_http_client_from_env
from .repository import ApiDeviceRepository, DeviceRepository, SampleDeviceRepository


def create_repository_from_env() -> DeviceRepository:
    source = os.getenv("DEVICE_TUI_DATA_SOURCE", "sample").strip().lower()
    current_user = os.getenv("DEVICE_TUI_CURRENT_USER", CURRENT_USER)
    if source == "api":
        refresh_seconds = float(os.getenv("DEVICE_TUI_REFRESH_SECONDS", "30"))
        return ApiDeviceRepository(
            create_http_client_from_env(),
            refresh_interval_seconds=refresh_seconds,
        )
    try:
        sample_count = int(os.getenv("DEVICE_TUI_SAMPLE_DEVICE_COUNT", "0") or "0")
    except ValueError:
        sample_count = 0
    return SampleDeviceRepository(current_user=current_user, device_count=sample_count)
