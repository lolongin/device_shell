"""Infrastructure adapters for the UI-independent application services."""
from .persistence import SQLiteConnectionProfileStore, SQLiteDesktopStore

__all__ = ["SQLiteConnectionProfileStore", "SQLiteDesktopStore"]
