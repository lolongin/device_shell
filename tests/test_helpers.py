"""Tests for helpers module."""

from __future__ import annotations

from src._sample_data import STATUS_IDLE, STATUS_PIPELINE
from src.data import Device
from src.helpers import (
    build_search_text,
    html_badge,
    html_chip,
    html_device_summary,
    html_status_text,
    mask_password,
    status_color,
)


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
        device = Device(
            id="X",
            name="x",
            domain="x",
            device_type="x",
            cpu="x",
            status="x",
            owner=None,
            ssh_ip="",
            telnet_ip="",
            username="",
            password="",
            vendor="",
            model="",
            site="",
            rack="",
            version="",
            notes="",
        )
        build_search_text(device)


class TestMaskPassword:
    def test_returns_asterisks_for_non_empty(self) -> None:
        assert mask_password("secret123") == "******"

    def test_returns_empty_for_empty(self) -> None:
        assert mask_password("") == ""


class TestStatusColor:
    def test_known_status(self) -> None:
        assert status_color(STATUS_IDLE) == "#22c55e"

    def test_pipeline_status_uses_workspace_blue(self) -> None:
        assert status_color(STATUS_PIPELINE) == "#60a5fa"

    def test_unknown_status_returns_gray(self) -> None:
        assert status_color("unknown") == "#718096"


class TestHtmlBadge:
    def test_warning_badge_uses_workspace_tokens(self) -> None:
        badge = html_badge("临时连接", "仅本机", variant="warning", class_name="temporary-detail-badge")

        assert "temporary-detail-badge" in badge
        assert "#f8e7a1" in badge
        assert "rgba(251, 191, 36, 0.13)" in badge
        assert "rgba(251, 191, 36, 0.42)" in badge
        assert "<b>临时连接</b> · 仅本机" in badge

    def test_badge_escapes_text(self) -> None:
        badge = html_badge("<x>", "<script>", class_name="a'b")

        assert "&lt;x&gt;" in badge
        assert "&lt;script&gt;" in badge
        assert "a&#x27;b" in badge


class TestHtmlChip:
    def test_filter_chip_uses_workspace_tokens(self) -> None:
        chip = html_chip("CPU", "ARM", class_name="filter-chip")

        assert "filter-chip" in chip
        assert "#08101d" in chip
        assert "#243244" in chip
        assert "#a7b4c7" in chip
        assert "CPU: ARM" in chip

    def test_chip_escapes_text(self) -> None:
        chip = html_chip("<label>", "<value>", class_name="a'b")

        assert "&lt;label&gt;" in chip
        assert "&lt;value&gt;" in chip
        assert "a&#x27;b" in chip


class TestHtmlStatusText:
    def test_status_text_uses_color_and_class(self) -> None:
        text = html_status_text("运行中", "#22c55e", class_name="transfer-status-text")

        assert "transfer-status-text" in text
        assert "#22c55e" in text
        assert "font-weight:800" in text
        assert "运行中" in text

    def test_status_text_escapes_values(self) -> None:
        text = html_status_text("<ok>", "#22'bad", class_name="x<y")

        assert "&lt;ok&gt;" in text
        assert "#22&#x27;bad" in text
        assert "x&lt;y" in text


class TestHtmlDeviceSummary:
    def test_device_summary_uses_workspace_tokens_and_helpers(self) -> None:
        summary = html_device_summary(
            "Mock Device",
            "D-001",
            "测试",
            "空闲",
            "#22c55e",
            "未占用",
            owner_muted=True,
            detail_html="<div>detail</div>",
            class_name="device-summary",
        )

        assert "device-summary" in summary
        assert "#f8fafc" in summary
        assert "#a7b4c7" in summary
        assert "#22c55e" in summary
        assert "device-summary-status" in summary
        assert "<div>detail</div>" in summary

    def test_device_summary_escapes_values(self) -> None:
        summary = html_device_summary("<name>", "<id>", "<domain>", "<status>", "#22'bad", "<owner>")

        assert "&lt;name&gt;" in summary
        assert "&lt;id&gt;" in summary
        assert "&lt;domain&gt;" in summary
        assert "&lt;status&gt;" in summary
        assert "&lt;owner&gt;" in summary
        assert "#22&#x27;bad" in summary
