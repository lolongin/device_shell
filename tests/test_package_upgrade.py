from pathlib import Path

from src.package_upgrade import (
    STANDBY_STORAGE_ABSENT,
    STANDBY_STORAGE_AVAILABLE,
    STANDBY_STORAGE_INDETERMINATE,
    PackageFileEntry,
    PackageUpgradeConfig,
    StartupInfo,
    build_cleanup_plan,
    classify_standby_storage,
    dir_contains_package,
    find_upgrade_failure,
    generate_huawei_upgrade_plan,
    parse_dir_entries,
    parse_display_startup,
    parse_free_space_bytes,
    startup_uses_package,
)


def test_classify_standby_storage_detects_readable_directory() -> None:
    output = """
    Directory of slave#flash:/
    1,048,576 KB total (256,000 KB free)
    """

    assert classify_standby_storage(output) == STANDBY_STORAGE_AVAILABLE


def test_classify_standby_storage_detects_absent_controller() -> None:
    assert (
        classify_standby_storage("Error: The storage device does not exist.")
        == STANDBY_STORAGE_ABSENT
    )


def test_classify_standby_storage_does_not_hide_permission_errors() -> None:
    assert (
        classify_standby_storage("Error: Permission denied.")
        == STANDBY_STORAGE_INDETERMINATE
    )


def test_parse_display_startup_extracts_current_and_next_system() -> None:
    output = """
      Current startup system software: flash:/S5735-V200R021C00.cc
      Next startup system software: flash:/S5735-V200R022C00.cc
    """

    startup = parse_display_startup(output)

    assert startup.current_system == "flash:/S5735-V200R021C00.cc"
    assert startup.next_system == "flash:/S5735-V200R022C00.cc"


def test_parse_dir_entries_and_free_space_from_vrp_output() -> None:
    output = """
    Directory of flash:/

      Idx  Attr     Size(Byte)  Date        Time       FileName
        0  -rw-    512,000,000  Jan 01 2026 10:00:00  old.cc
        1  -rw-    640,000,000  Jan 02 2026 10:00:00  current.cc

    1,048,576 KB total (256,000 KB free)
    """

    entries = parse_dir_entries(output, "flash:/")

    assert parse_free_space_bytes(output) == 256_000 * 1024
    assert [entry.name for entry in entries] == ["old.cc", "current.cc"]
    assert entries[0].path == "flash:/old.cc"
    assert entries[0].size_bytes == 512_000_000


def test_upgrade_output_helpers_confirm_package_and_startup() -> None:
    dir_output = """
    Directory of flash:/
      0  -rw-    640,000,000  Jan 02 2026 10:00:00  target.cc
    1,048,576 KB total (300,000 KB free)
    """
    startup_output = """
      Current startup system software: flash:/current.cc
      Next startup system software: flash:/target.cc
    """

    assert dir_contains_package(
        dir_output,
        storage="flash:/",
        package_name="target.cc",
        expected_size=640_000_000,
    )
    assert startup_uses_package(startup_output, "target.cc")
    assert find_upgrade_failure("Error: insufficient space.") == "error"


def test_dir_contains_package_rejects_wrong_size() -> None:
    dir_output = """
    Directory of flash:/
      0  -rw-    640,000,000  Jan 02 2026 10:00:00  target.cc
    """

    assert not dir_contains_package(
        dir_output,
        storage="flash:/",
        package_name="target.cc",
        expected_size=700_000_000,
    )


def test_cleanup_plan_deletes_only_unprotected_old_cc_packages() -> None:
    startup = StartupInfo(
        current_system="flash:/current.cc",
        next_system="flash:/next.cc",
    )
    entries = [
        PackageFileEntry("flash:/current.cc", "current.cc", 500_000_000),
        PackageFileEntry("flash:/next.cc", "next.cc", 500_000_000),
        PackageFileEntry("flash:/old-large.cc", "old-large.cc", 700_000_000),
        PackageFileEntry("flash:/notes.txt", "notes.txt", 900_000_000),
        PackageFileEntry("flash:/target.cc", "target.cc", 600_000_000),
    ]

    plan = build_cleanup_plan(
        storage="flash:/",
        free_bytes=100_000_000,
        target_bytes=600_000_000,
        entries=entries,
        startup=startup,
        target_package_name="target.cc",
        reserve_bytes=0,
    )

    assert plan.has_enough_space
    assert [entry.path for entry in plan.delete_entries] == ["flash:/old-large.cc"]


def test_cleanup_plan_reports_not_enough_space_when_only_protected_packages_exist() -> None:
    startup = StartupInfo(
        current_system="flash:/current.cc",
        next_system="flash:/next.cc",
    )
    entries = [
        PackageFileEntry("flash:/current.cc", "current.cc", 500_000_000),
        PackageFileEntry("flash:/next.cc", "next.cc", 500_000_000),
    ]

    plan = build_cleanup_plan(
        storage="flash:/",
        free_bytes=100_000_000,
        target_bytes=600_000_000,
        entries=entries,
        startup=startup,
        target_package_name="target.cc",
        reserve_bytes=0,
    )

    assert not plan.has_enough_space
    assert plan.delete_entries == []


def test_huawei_upgrade_plan_includes_dual_controller_steps_and_cleanup() -> None:
    config = PackageUpgradeConfig(
        package_path=Path("S5735-V200R023C00.cc"),
        server_host="192.0.2.10",
        protocol="ftp",
        port=2121,
        username="u",
        password="p",
        include_slave=True,
        cleanup_entries=[
            PackageFileEntry("flash:/old.cc", "old.cc", 500_000_000),
            PackageFileEntry("slave#flash:/old.cc", "old.cc", 500_000_000, storage="slave#flash:/"),
        ],
    )

    plan = generate_huawei_upgrade_plan(config)
    script = "\n".join(plan.commands)

    assert "delete /unreserved /quiet flash:/old.cc" in script
    assert "delete /unreserved /quiet slave#flash:/old.cc" in script
    assert "ftp 192.0.2.10 2121" in script
    assert "copy flash:/S5735-V200R023C00.cc slave#flash:/S5735-V200R023C00.cc" in script
    assert "startup system-software flash:/S5735-V200R023C00.cc all" in script


def test_huawei_upgrade_plan_omits_standby_steps_for_single_controller() -> None:
    config = PackageUpgradeConfig(
        package_path=Path("S5735-V200R023C00.cc"),
        server_host="192.0.2.10",
        include_slave=False,
    )

    script = "\n".join(generate_huawei_upgrade_plan(config).commands)

    assert "slave#flash:/" not in script
    assert " all" not in script
    assert "slave-board" not in script
    assert "startup system-software flash:/S5735-V200R023C00.cc" in script
