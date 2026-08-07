from __future__ import annotations

import re

from src.styles import APP_STYLE, APP_STYLE_LIGHT
from src.theme_tokens import DARK_TO_LIGHT


def test_dark_to_light_covers_all_app_style_hex_colors() -> None:
    """Every 6-digit hex in APP_STYLE must have a light mapping, or the light
    stylesheet would keep stray dark literals."""
    hexes = set(re.findall(r"#[0-9a-fA-F]{6}", APP_STYLE))
    unmapped = {h for h in hexes if h.lower() not in {k.lower() for k in DARK_TO_LIGHT}}
    assert not unmapped, f"Unmapped APP_STYLE colors: {sorted(unmapped)}"


def test_dark_to_light_has_no_identity_mapping() -> None:
    for dark, light in DARK_TO_LIGHT.items():
        assert dark != light, f"Identity mapping for {dark}"


def test_app_style_unchanged() -> None:
    """APP_STYLE must remain the dark original (tests guard its values)."""
    assert "#020617" in APP_STYLE
    assert "background: #15803d" in APP_STYLE  # primary button dark green


def test_app_style_light_has_light_base_and_no_dark_base() -> None:
    assert "#f2f4f6" in APP_STYLE_LIGHT  # light bg
    assert "#020617" not in APP_STYLE_LIGHT  # dark bg gone


def test_app_style_light_has_light_primary_button() -> None:
    assert "background: #15803d" not in APP_STYLE_LIGHT


def test_app_style_light_panels_stay_white() -> None:
    """Panels (#0f172a) must map to white and must NOT be clobbered back to
    near-black by the later #ffffff→#1c2128 rule (single-pass replacement)."""
    assert "background: #ffffff" in APP_STYLE_LIGHT
    # No residual dark panels: count #1c2128 occurrences should be reasonable
    # (it's the mapped text color), but the dark panel #0f172a is gone.
    assert "#0f172a" not in APP_STYLE_LIGHT
