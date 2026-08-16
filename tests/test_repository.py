"""Tests for SampleDeviceRepository."""

from __future__ import annotations

import copy

import pytest

from src.repository import RepositoryConflictError, RepositoryError


class TestFetchDevices:
    def test_returns_copies(self, sample_repo):
        """Mutating a returned device does not affect the repository state."""
        devices_before = sample_repo.fetch_devices()
        assert len(devices_before) > 0

        # Mutate the first returned device
        mutated = devices_before[0]
        mutated.status = "mutated"
        mutated.owner = "hacker"

        # Fetch again -- original repo data must be unchanged
        devices_after = sample_repo.fetch_devices()
        after = next(d for d in devices_after if d.id == mutated.id)
        assert after.status != "mutated"
        assert after.owner != "hacker"


class TestFetchOwnedDeviceIds:
    def test_returns_set(self, sample_repo):
        """fetch_owned_device_ids returns a set of strings."""
        ids = sample_repo.fetch_owned_device_ids()
        assert isinstance(ids, set)
        # With default data and current_user="li.wei"
        assert "RTN-BJ-001" in ids
        assert "RTN-SZ-009" in ids
        assert "JQ-HZ-011" in ids
        assert "XTN-NJ-018" in ids

    def test_result_is_independent(self, sample_repo):
        """Mutating the set does not affect subsequent calls."""
        ids_first = sample_repo.fetch_owned_device_ids()
        ids_first.clear()
        ids_second = sample_repo.fetch_owned_device_ids()
        assert len(ids_second) > 0


class TestClaimDevice:
    def test_claim_idle_succeeds(self, sample_repo):
        """Claiming an idle device succeeds and changes its state."""
        result = sample_repo.claim_device("MOCK-LAB-000", "li.wei")
        assert "Claimed" in result

        devices = sample_repo.fetch_devices()
        claimed = next(d for d in devices if d.id == "MOCK-LAB-000")
        assert claimed.owner == "li.wei"
        assert claimed.status == "已被占用"

    def test_claim_occupied_raises_conflict(self, sample_repo):
        """Claiming an already-occupied device raises RepositoryConflictError."""
        with pytest.raises(RepositoryConflictError):
            sample_repo.claim_device("RTN-BJ-001", "some.other")

    def test_claim_pipeline_raises_conflict(self, sample_repo):
        """Claiming a pipeline-occupied device raises RepositoryConflictError."""
        with pytest.raises(RepositoryConflictError):
            sample_repo.claim_device("RTR-GZ-006", "li.wei")

    def test_claim_unknown_id_raises(self, sample_repo):
        """Claiming a non-existent device raises RepositoryError."""
        with pytest.raises(RepositoryError, match="Unknown device id"):
            sample_repo.claim_device("DOES-NOT-EXIST", "li.wei")


class TestReleaseDevice:
    def test_release_owned_succeeds(self, sample_repo):
        """Releasing a device owned by the caller succeeds."""
        result = sample_repo.release_device("RTN-BJ-001", "li.wei")
        assert "Released" in result

        devices = sample_repo.fetch_devices()
        released = next(d for d in devices if d.id == "RTN-BJ-001")
        assert released.owner is None
        assert released.status == "空闲"

    def test_release_not_owned_raises(self, sample_repo):
        """Releasing a device not owned by the caller raises RepositoryConflictError."""
        with pytest.raises(RepositoryConflictError):
            sample_repo.release_device("RTR-GZ-006", "li.wei")

    def test_release_idle_no_owner_raises(self, sample_repo):
        """Releasing a device with no owner raises RepositoryConflictError."""
        with pytest.raises(RepositoryConflictError):
            sample_repo.release_device("JQ-SH-003", "li.wei")


class TestToggleDevice:
    def test_toggle_claim_and_release_cycle(self, sample_repo):
        """toggle claims an idle device, then toggling again releases it."""
        # First toggle claims the idle device
        result1 = sample_repo.toggle_device("XTN-CD-002", "li.wei")
        assert "Claimed" in result1

        devices = sample_repo.fetch_devices()
        claimed = next(d for d in devices if d.id == "XTN-CD-002")
        assert claimed.owner == "li.wei"
        assert claimed.status == "已被占用"

        # Second toggle releases it
        result2 = sample_repo.toggle_device("XTN-CD-002", "li.wei")
        assert "Released" in result2

        devices = sample_repo.fetch_devices()
        released = next(d for d in devices if d.id == "XTN-CD-002")
        assert released.owner is None
        assert released.status == "空闲"

    def test_toggle_on_occupied_by_other_raises(self, sample_repo):
        """Toggling a device occupied by another user raises RepositoryConflictError."""
        with pytest.raises(RepositoryConflictError):
            sample_repo.toggle_device("RTN-BJ-001", "some.other")


class TestPowerOffDevice:
    def test_power_off_on_supporting_device_succeeds(self, sample_repo):
        """Power off succeeds on a device that supports it (after claiming it)."""
        sample_repo.claim_device("MOCK-LAB-000", "li.wei")
        result = sample_repo.power_off_device("MOCK-LAB-000", "li.wei")
        assert "Powered off" in result

    def test_power_off_on_non_supporting_device_raises(self, sample_repo):
        """Power off raises on a device that does not support it."""
        sample_repo.claim_device("JQ-SH-003", "li.wei")
        with pytest.raises(RepositoryConflictError, match="does not support power off"):
            sample_repo.power_off_device("JQ-SH-003", "li.wei")

    def test_power_off_not_owned_raises(self, sample_repo):
        """Power off raises when caller does not own the device."""
        with pytest.raises(RepositoryConflictError):
            sample_repo.power_off_device("RTN-BJ-001", "some.other")

    def test_power_off_on_released_device_raises(self, sample_repo):
        """Power off raises after device has been released."""
        sample_repo.claim_device("MOCK-LAB-000", "li.wei")
        sample_repo.release_device("MOCK-LAB-000", "li.wei")
        with pytest.raises(RepositoryConflictError):
            sample_repo.power_off_device("MOCK-LAB-000", "li.wei")


def test_sample_repository_reports_internal_login_unavailable(sample_repo) -> None:
    status = sample_repo.internal_auth_status()

    assert status.available is False
    assert status.authenticated is False
    with pytest.raises(RepositoryError, match="未配置内部网站登录"):
        sample_repo.login_internal("operator", "secret", "CID-7")
