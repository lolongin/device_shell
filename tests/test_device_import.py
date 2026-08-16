from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from src.device_import import DeviceImportError, parse_device_import
from src.infrastructure.sqlite_desktop import SQLiteDesktopStore


def test_csv_import_maps_chinese_aliases_and_ignores_passwords(tmp_path: Path) -> None:
    source = tmp_path / "devices.csv"
    source.write_text(
        "设备编号,设备名称,管理IP,SSH端口,登录账号,密码,厂家\n"
        "R1,核心路由器,192.0.2.10,2222,admin,do-not-store,Acme\n",
        encoding="utf-8-sig",
    )

    parsed = parse_device_import(source)

    assert len(parsed.devices) == 1
    device = parsed.devices[0]
    assert (device.id, device.name, device.ssh_ip, device.telnet_ip) == (
        "R1",
        "核心路由器",
        "192.0.2.10",
        "192.0.2.10",
    )
    assert device.ssh_port == 2222
    assert device.password == device.ssh_password == device.serial_password == ""
    assert "密码列" in parsed.warnings[0]


def test_csv_import_supports_gb18030_and_reports_invalid_rows(tmp_path: Path) -> None:
    source = tmp_path / "legacy.csv"
    source.write_bytes(
        "设备ID,设备名称,IP,SSH端口\nA,设备甲,192.0.2.1,22\nB,设备乙,192.0.2.2,70000\n".encode(
            "gb18030"
        )
    )

    parsed = parse_device_import(source)

    assert [device.id for device in parsed.devices] == ["A"]
    assert parsed.total_rows == 2
    assert parsed.skipped_rows == 1
    assert parsed.errors[0].row == 3
    assert "1-65535" in parsed.errors[0].message


def test_xlsx_import_uses_first_visible_sheet(tmp_path: Path) -> None:
    source = tmp_path / "devices.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "设备清单"
    sheet.append(["ID", "名称", "SSH IP", "SSH 用户"])
    sheet.append(["SW-1", "交换机", "198.51.100.4", "ops"])
    workbook.save(source)

    parsed = parse_device_import(source)

    assert parsed.sheet_name == "设备清单"
    assert parsed.devices[0].ssh_username == "ops"


def test_duplicate_device_and_board_is_skipped(tmp_path: Path) -> None:
    source = tmp_path / "duplicate.csv"
    source.write_text("ID,名称,单板ID\nA,一号,B1\nA,重复,B1\n", encoding="utf-8")

    parsed = parse_device_import(source)

    assert len(parsed.devices) == 1
    assert parsed.skipped_rows == 1
    assert "重复" in parsed.errors[0].message


def test_unsupported_xls_has_conversion_guidance(tmp_path: Path) -> None:
    source = tmp_path / "old.xls"
    source.write_bytes(b"not-an-xls")

    with pytest.raises(DeviceImportError, match="另存为 .xlsx"):
        parse_device_import(source)


def test_sqlite_import_replacement_is_complete_persistent_and_secret_free(tmp_path: Path) -> None:
    first = tmp_path / "first.csv"
    first.write_text("ID,名称,IP,密码\nA,甲,192.0.2.1,secret\nB,乙,192.0.2.2,secret\n", encoding="utf-8")
    second = tmp_path / "second.csv"
    second.write_text("ID,名称,IP\nC,丙,192.0.2.3\n", encoding="utf-8")
    store = SQLiteDesktopStore(tmp_path / "desktop.sqlite3")
    one = parse_device_import(first)
    two = parse_device_import(second)

    store.replace_imported_devices(
        list(one.devices), source_name=first.name, sheet_name=one.sheet_name, imported_at="one"
    )
    metadata = store.replace_imported_devices(
        list(two.devices), source_name=second.name, sheet_name=two.sheet_name, imported_at="two"
    )
    reopened = SQLiteDesktopStore(tmp_path / "desktop.sqlite3")

    assert metadata.row_count == 1
    assert metadata.revision == 2
    assert [device.id for device in reopened.list_imported_devices()] == ["C"]
    assert reopened.list_imported_devices()[0].password == ""
    assert b"secret" not in (tmp_path / "desktop.sqlite3").read_bytes()
