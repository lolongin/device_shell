"""Tests for packaging configuration."""
from __future__ import annotations

import tomllib
from pathlib import Path


def test_setuptools_includes_refactored_subpackages() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    package_find = pyproject["tool"]["setuptools"]["packages"]["find"]

    assert "src*" in package_find["include"]
