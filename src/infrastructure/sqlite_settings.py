"""JSON settings persisted in the desktop SQLite metadata table."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Protocol

from ..application.settings import SettingValue


class MetadataStore(Protocol):
    def get_meta(self, key: str) -> str | None: ...

    def set_meta(self, key: str, value: str) -> None: ...

    def delete_meta(self, key: str) -> None: ...


class SQLiteSettingsStore:
    """Implement the presentation-neutral settings boundary using ``app_meta``."""

    PREFIX = "desktop.setting."

    def __init__(self, metadata: MetadataStore) -> None:
        self._metadata = metadata

    def get(self, key: str, default: SettingValue = None) -> SettingValue:
        raw = self._metadata.get_meta(self._key(key))
        if raw is None:
            return deepcopy(default)
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return deepcopy(default)

    def set(self, key: str, value: SettingValue) -> None:
        self._metadata.set_meta(
            self._key(key),
            json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        )

    def delete(self, key: str) -> None:
        self._metadata.delete_meta(self._key(key))

    @classmethod
    def _key(cls, key: str) -> str:
        return f"{cls.PREFIX}{key.strip()}"
