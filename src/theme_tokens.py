"""Workspace theme tokens shared by Python-rendered UI surfaces."""

from __future__ import annotations

WORKSPACE_BG = "#020617"
WORKSPACE_PANEL = "#0f172a"
WORKSPACE_PANEL_RAISED = "#111c2f"
WORKSPACE_INPUT = "#08101d"
WORKSPACE_LINE = "#243244"
WORKSPACE_LINE_STRONG = "#334155"
WORKSPACE_TEXT = "#f8fafc"
WORKSPACE_MUTED = "#a7b4c7"
WORKSPACE_SOFT = "#718096"
WORKSPACE_ACCENT = "#22c55e"
WORKSPACE_BLUE = "#60a5fa"
WORKSPACE_WARN = "#fbbf24"
WORKSPACE_DANGER = "#f87171"
WORKSPACE_SUCCESS_TEXT = "#d8fff0"
WORKSPACE_DANGER_TEXT = "#fecaca"
WORKSPACE_WARN_TEXT = "#f8e7a1"
WORKSPACE_SELECTED = "#24324a"
WORKSPACE_TEXT_SELECTION_BG = "#315f9f"
WORKSPACE_TEXT_SELECTION_FG = "#f8fafc"
WORKSPACE_SCROLL_HOVER = "#475569"

WORKSPACE_SUCCESS_SOFT = "rgba(34, 197, 94, 0.14)"
WORKSPACE_SUCCESS_LINE = "rgba(34, 197, 94, 0.42)"
WORKSPACE_WARNING_SOFT = "rgba(251, 191, 36, 0.13)"
WORKSPACE_WARNING_LINE = "rgba(251, 191, 36, 0.42)"
WORKSPACE_NEUTRAL_SOFT = "rgba(113, 128, 150, 0.14)"
WORKSPACE_NEUTRAL_LINE = "rgba(113, 128, 150, 0.36)"


def qwebengine_background_stylesheet(object_name: str) -> str:
    """Return the standard transparent-border WebEngine background rule."""
    return f"QWebEngineView#{object_name} {{ background: {WORKSPACE_BG}; border: 0; }}"
