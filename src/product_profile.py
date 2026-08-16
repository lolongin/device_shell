"""Developer-owned product policy for device-source presentation and access."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Literal


ProductMode = Literal["universal", "web", "spreadsheet"]
PRODUCT_MODES: tuple[ProductMode, ...] = ("universal", "web", "spreadsheet")
_SOURCE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9._-]*$")


@dataclass(frozen=True, slots=True)
class ProductProfile:
    """Controls which source workflow is exposed by a particular product build."""

    mode: ProductMode = "universal"
    source_id: str = ""

    @classmethod
    def from_environment(
        cls,
        *,
        mode: str | None = None,
        source_id: str | None = None,
    ) -> "ProductProfile":
        raw_mode = (
            mode if mode is not None else os.getenv("DEVICE_TUI_PRODUCT_MODE", "universal")
        )
        normalized_mode = str(raw_mode or "universal").strip().lower()
        if normalized_mode not in PRODUCT_MODES:
            choices = ", ".join(PRODUCT_MODES)
            raise ValueError(
                f"DEVICE_TUI_PRODUCT_MODE must be one of: {choices}; got {normalized_mode!r}."
            )
        raw_source = (
            source_id
            if source_id is not None
            else os.getenv("DEVICE_TUI_PRODUCT_SOURCE", "")
        )
        normalized_source = str(raw_source or "").strip().lower()
        if normalized_source and not _SOURCE_ID_PATTERN.fullmatch(normalized_source):
            raise ValueError(
                "DEVICE_TUI_PRODUCT_SOURCE must be a valid device-source id."
            )
        if normalized_mode == "web" and not normalized_source:
            raise ValueError(
                "DEVICE_TUI_PRODUCT_SOURCE is required when DEVICE_TUI_PRODUCT_MODE=web."
            )
        return cls(
            mode=normalized_mode,  # type: ignore[arg-type]
            source_id=normalized_source,
        )

    @property
    def source_locked(self) -> bool:
        return self.mode != "universal"

    @property
    def allow_source_switch(self) -> bool:
        return self.mode == "universal"

    @property
    def allow_plugin_management(self) -> bool:
        return self.mode == "universal"

    @property
    def allow_import(self) -> bool:
        return self.mode in {"universal", "spreadsheet"}
