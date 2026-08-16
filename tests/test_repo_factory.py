from __future__ import annotations

from src.repo_factory import create_repository_from_env
from src.repository import ApiDeviceRepository, SampleDeviceRepository


def test_legacy_factory_defaults_to_sample(monkeypatch) -> None:
    for name in (
        "DEVICE_TUI_DATA_SOURCE",
        "DEVICE_TUI_DEFAULT_DATA_SOURCE",
        "DEVICE_TUI_API_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)

    assert isinstance(create_repository_from_env(), SampleDeviceRepository)


def test_legacy_factory_keeps_explicit_api_mode(monkeypatch) -> None:
    monkeypatch.setenv("DEVICE_TUI_DATA_SOURCE", "api")
    monkeypatch.setenv("DEVICE_TUI_API_BASE_URL", "https://devices.example.test")

    assert isinstance(create_repository_from_env(), ApiDeviceRepository)
