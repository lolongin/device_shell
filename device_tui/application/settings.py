"""Presentation-neutral settings boundary."""

from __future__ import annotations

from copy import deepcopy
from threading import Lock
from typing import Protocol, TypeAlias


SettingScalar: TypeAlias = str | int | float | bool | None
SettingValue: TypeAlias = SettingScalar | list["SettingValue"] | dict[str, "SettingValue"]


class SettingsStore(Protocol):
    def get(self, key: str, default: SettingValue = None) -> SettingValue: ...

    def set(self, key: str, value: SettingValue) -> None: ...

    def delete(self, key: str) -> None: ...


class MemorySettingsStore:
    """Default store until the SQLite migration is introduced in Phase 4."""

    def __init__(self, initial: dict[str, SettingValue] | None = None) -> None:
        self._values = deepcopy(initial or {})
        self._lock = Lock()

    def get(self, key: str, default: SettingValue = None) -> SettingValue:
        with self._lock:
            return deepcopy(self._values.get(key, default))

    def set(self, key: str, value: SettingValue) -> None:
        with self._lock:
            self._values[key] = deepcopy(value)

    def delete(self, key: str) -> None:
        with self._lock:
            self._values.pop(key, None)
