from __future__ import annotations

import pytest

from device_tui.application.workflow_runtime.value_extraction import extract_value


def test_extracts_first_full_match() -> None:
    assert extract_value("flash:/cc\nflash:/other", {"pattern": r"flash:/\S+"}) == ("flash:/cc", True)


def test_extracts_capture_group() -> None:
    assert extract_value("Version: 8.220", {"pattern": r"Version:\s*([0-9.]+)", "group": 1}) == ("8.220", True)


def test_can_save_the_matching_line() -> None:
    assert extract_value("ok\nfound flash:/cc\nend", {"pattern": r"flash:/\S+", "mode": "line"}) == ("found flash:/cc", True)


def test_no_match_returns_empty_value() -> None:
    assert extract_value("nothing", {"pattern": "cc"}) == ("", False)


def test_invalid_pattern_is_rejected() -> None:
    with pytest.raises(ValueError, match="invalid extraction pattern"):
        extract_value("text", {"pattern": "["})
