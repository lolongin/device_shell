from __future__ import annotations

from src._sample_data import STATUS_IDLE, sample_devices
from src.repository import SampleDeviceRepository


def test_sample_data_includes_frame_device_boards() -> None:
    boards = [device for device in sample_devices() if device.id == "XTN-NJ-018"]

    assert len(boards) == 4
    assert {board.slot_id for board in boards} == {"1", "2", "5", "8"}
    assert {board.board_role for board in boards} == {"MPU", "SFU", "LPU", "PIU"}
    assert {board.board_type for board in boards} == {"XTN960"}
    assert {board.subdomain for board in boards} == {"SDK"}
    assert {board.hardware_platform for board in boards} == {"云杉"}
    assert {board.serial_server for board in boards} == {"172.18.200.18"}
    assert {board.name for board in boards} == {"XTN-Hub-NJ18"}
    assert all(board.board_id.startswith("XTN-NJ-018-") for board in boards)


def test_sample_repository_updates_frame_device_as_one_unit() -> None:
    repository = SampleDeviceRepository()

    repository.release_device("XTN-NJ-018", "li.wei")
    released_boards = [device for device in repository.fetch_devices() if device.id == "XTN-NJ-018"]

    assert released_boards
    assert all(board.owner is None for board in released_boards)
    assert all(board.status == STATUS_IDLE for board in released_boards)

    repository.claim_device("XTN-NJ-018", "li.wei")
    claimed_boards = [device for device in repository.fetch_devices() if device.id == "XTN-NJ-018"]

    assert all(board.owner == "li.wei" for board in claimed_boards)
