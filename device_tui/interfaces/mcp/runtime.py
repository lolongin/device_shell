"""Runtime discovery and audit file locations."""

from __future__ import annotations

import os
from pathlib import Path


def default_runtime_directory() -> Path:
    root = os.getenv("LOCALAPPDATA")
    if root:
        return Path(root) / "OdyTerm"
    return Path.home() / ".odyterm"


def default_state_path() -> Path:
    override = os.getenv("DEVICE_TUI_CONTROL_STATE", "").strip()
    if override:
        return Path(override).expanduser()
    return default_runtime_directory() / "app-control.json"


def default_audit_path() -> Path:
    override = os.getenv("DEVICE_TUI_CONTROL_AUDIT", "").strip()
    if override:
        return Path(override).expanduser()
    return default_runtime_directory() / "app-control-audit.jsonl"
