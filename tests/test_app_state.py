"""Tests for app_state module."""
from __future__ import annotations

from src.app_state import RepositorySnapshot


class TestRepositorySnapshot:
    def test_create_snapshot(self, sample_device) -> None:
        snapshot = RepositorySnapshot(
            current_user="test.user",
            devices=[sample_device],
            owned_device_ids={"TEST-001"},
        )
        assert snapshot.current_user == "test.user"
        assert len(snapshot.devices) == 1
        assert "TEST-001" in snapshot.owned_device_ids
