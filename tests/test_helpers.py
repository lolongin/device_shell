"""Tests for helpers module."""
from __future__ import annotations

from src.data import Device
from src.helpers import build_search_text, mask_password, status_color


class TestBuildSearchText:
    def test_joins_all_device_fields(self, sample_device: Device) -> None:
        result = build_search_text(sample_device)
        assert "test-001" in result
        assert "test-device" in result
        assert "router" in result

    def test_lowercase(self, sample_device: Device) -> None:
        result = build_search_text(sample_device)
        assert result == result.lower()

    def test_empty_owner_does_not_crash(self) -> None:
        d = Device(
            id="X", name="x", domain="x", device_type="x",
            cpu="x", status="x", owner=None,
            ssh_ip="", telnet_ip="", username="", password="",
            vendor="", model="", site="", rack="", version="", notes="",
        )
        build_search_text(d)  # should not raise


class TestMaskPassword:
    def test_returns_asterisks_for_non_empty(self) -> None:
        assert mask_password("secret123") == "******"

    def test_returns_empty_for_empty(self) -> None:
        assert mask_password("") == ""


class TestStatusColor:
    def test_known_status(self) -> None:
        assert status_color("空闲") == "#3cc98e"

    def test_unknown_status_returns_gray(self) -> None:
        assert status_color("未知") == "#808080"
