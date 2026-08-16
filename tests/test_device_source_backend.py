from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from src.desktop_backend.app import create_app
from src.desktop_backend.session_hub import SessionHub
from src.device_source_plugins import (
    DeviceSourceContext,
    DeviceSourceDescriptor,
    PluginCheckResult,
    PluginConfigField,
)
from src.application.secrets import MemorySecretStore
from src.imported_devices import MemoryImportedDeviceStore
from src.repository import SampleDeviceRepository


TOKEN = "device-source-test"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


class _ManagedPlugin:
    descriptor = DeviceSourceDescriptor(
        id="managed-source",
        label="托管插件",
        description="由设置页面管理的外部插件。",
        version="1.4.0",
        publisher="Example Team",
        default_priority=80,
    )
    config_fields = (
        PluginConfigField("base_url", "平台地址", kind="url", required=True),
        PluginConfigField("api_token", "API Token", kind="secret", required=True),
    )

    def create_repository(self, context: DeviceSourceContext) -> SampleDeviceRepository:
        if not context.config.get("base_url") or not context.secrets.get("api_token"):
            raise RuntimeError("插件配置不完整")
        return SampleDeviceRepository(current_user="plugin-user")

    def test_connection(self, context: DeviceSourceContext) -> PluginCheckResult:
        return PluginCheckResult(
            bool(context.config.get("base_url") and context.secrets.get("api_token")),
            "插件连接配置有效",
        )


class _WebsitePlugin:
    descriptor = DeviceSourceDescriptor(
        id="website-source",
        label="项目设备平台",
        description="项目固定的网站后端。",
        requires_login=True,
    )
    config_fields = ()

    def create_repository(self, context: DeviceSourceContext) -> SampleDeviceRepository:
        return SampleDeviceRepository(current_user="website-user")


def _app(store: MemoryImportedDeviceStore | None = None):
    return create_app(
        token=TOKEN,
        repository=SampleDeviceRepository(),
        session_hub=SessionHub(),
        imported_device_store=store or MemoryImportedDeviceStore(),
    )


def _preview(client: TestClient, path: Path) -> dict[str, object]:
    response = client.post(
        "/api/v1/device-source/import/preview",
        headers=HEADERS,
        json={"path": str(path)},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_import_preview_commit_and_exclusive_switch(tmp_path: Path) -> None:
    source = tmp_path / "inventory.csv"
    source.write_text(
        "ID,名称,IP,串口地址,串口端口,密码\n"
        "A,设备甲,192.0.2.10,198.51.100.10,2001,secret\n"
        "B,设备乙,192.0.2.11,,,secret\n",
        encoding="utf-8",
    )
    store = MemoryImportedDeviceStore()

    with TestClient(_app(store)) as client:
        before = client.get("/api/v1/device-source", headers=HEADERS).json()
        unavailable = client.put(
            "/api/v1/device-source", headers=HEADERS, json={"source": "imported"}
        )
        preview = _preview(client, source)
        committed = client.post(
            "/api/v1/device-source/import/commit",
            headers=HEADERS,
            json={"token": preview["token"]},
        )
        devices = client.get("/api/v1/devices", headers=HEADERS).json()["devices"]
        switched = client.put(
            "/api/v1/device-source", headers=HEADERS, json={"source": "sample"}
        )

    assert before["active_source"] == "sample"
    assert unavailable.status_code == 409
    assert preview["file_name"] == "inventory.csv"
    assert str(tmp_path) not in str(preview)
    assert preview["valid_rows"] == 2
    assert committed.status_code == 200
    assert committed.json()["source"]["active_source"] == "imported"
    imported = [device for device in devices if not device["is_simulated"]]
    assert {device["id"] for device in imported} == {"A", "B"}
    assert imported[0]["can_claim"] is False
    assert next(device for device in imported if device["id"] == "A")["can_connect_serial"] is True
    assert switched.status_code == 200
    assert switched.json()["active_source"] == "sample"
    assert all(device.password == "" for device in store.list_imported_devices())


def test_sessions_block_source_switch_and_import_replacement(tmp_path: Path) -> None:
    first = tmp_path / "first.csv"
    first.write_text("ID,名称,IP\nA,设备甲,192.0.2.10\n", encoding="utf-8")
    second = tmp_path / "second.csv"
    second.write_text("ID,名称,IP\nB,设备乙,192.0.2.11\n", encoding="utf-8")

    with TestClient(_app()) as client:
        first_preview = _preview(client, first)
        assert client.post(
            "/api/v1/device-source/import/commit",
            headers=HEADERS,
            json={"token": first_preview["token"]},
        ).status_code == 200
        created = client.post(
            "/api/v1/sessions",
            headers=HEADERS,
            json={"device_id": "A", "kind": "simulated"},
        )
        second_preview = _preview(client, second)
        switch = client.put(
            "/api/v1/device-source", headers=HEADERS, json={"source": "sample"}
        )
        replacement = client.post(
            "/api/v1/device-source/import/commit",
            headers=HEADERS,
            json={"token": second_preview["token"]},
        )

    assert created.status_code == 200
    assert switch.status_code == 409
    assert replacement.status_code == 409


def test_electron_registry_does_not_expose_legacy_api_source() -> None:
    app = create_app(
        token=TOKEN,
        repository=SampleDeviceRepository(),
        session_hub=SessionHub(),
        imported_device_store=MemoryImportedDeviceStore(),
        discover_source_plugins=False,
    )

    with TestClient(app) as client:
        status = client.get("/api/v1/device-source", headers=HEADERS)

    assert status.status_code == 200
    assert {item["id"] for item in status.json()["sources"]} == {
        "sample",
        "imported",
    }


def test_web_product_fixes_website_source_and_blocks_user_management(tmp_path: Path) -> None:
    app = create_app(
        token=TOKEN,
        repository=SampleDeviceRepository(),
        session_hub=SessionHub(),
        imported_device_store=MemoryImportedDeviceStore(),
        device_source_plugins=[_WebsitePlugin()],
        discover_source_plugins=False,
        product_mode="web",
        product_source="website-source",
    )

    with TestClient(app) as client:
        status = client.get("/api/v1/device-source", headers=HEADERS)
        switch = client.put(
            "/api/v1/device-source",
            headers=HEADERS,
            json={"source": "sample"},
        )
        plugin_update = client.put(
            "/api/v1/device-source/plugins/website-source",
            headers=HEADERS,
            json={"enabled": False},
        )
        import_preview = client.post(
            "/api/v1/device-source/import/preview",
            headers=HEADERS,
            json={"path": str(tmp_path / "devices.xlsx")},
        )

    payload = status.json()
    assert payload["product_mode"] == "web"
    assert payload["allow_source_switch"] is False
    assert payload["allow_plugin_management"] is False
    assert payload["allow_import"] is False
    assert payload["active_source"] == "website-source"
    assert [source["id"] for source in payload["sources"]] == ["website-source"]
    assert switch.status_code == 409
    assert plugin_update.status_code == 409
    assert import_preview.status_code == 409


def test_spreadsheet_product_starts_empty_import_source_and_blocks_switch() -> None:
    app = create_app(
        token=TOKEN,
        repository=SampleDeviceRepository(),
        session_hub=SessionHub(),
        imported_device_store=MemoryImportedDeviceStore(),
        discover_source_plugins=False,
        product_mode="spreadsheet",
    )

    with TestClient(app) as client:
        status = client.get("/api/v1/device-source", headers=HEADERS)
        switch = client.put(
            "/api/v1/device-source",
            headers=HEADERS,
            json={"source": "sample"},
        )

    payload = status.json()
    assert payload["product_mode"] == "spreadsheet"
    assert payload["active_source"] == "imported"
    assert payload["default_source"] == "imported"
    assert payload["allow_import"] is True
    assert len(payload["sources"]) == 1
    assert payload["sources"][0]["id"] == "imported"
    assert payload["sources"][0]["available"] is True
    assert payload["sources"][0]["supports_import"] is True
    assert switch.status_code == 409


def test_web_product_requires_explicit_website_source() -> None:
    with pytest.raises(ValueError, match="DEVICE_TUI_PRODUCT_SOURCE is required"):
        create_app(
            token=TOKEN,
            repository=SampleDeviceRepository(),
            session_hub=SessionHub(),
            imported_device_store=MemoryImportedDeviceStore(),
            discover_source_plugins=False,
            product_mode="web",
            product_source="",
        )


def test_plugin_management_api_configures_tests_and_disables_external_source() -> None:
    secrets = MemorySecretStore()
    app = create_app(
        token=TOKEN,
        repository=SampleDeviceRepository(),
        session_hub=SessionHub(),
        imported_device_store=MemoryImportedDeviceStore(),
        secret_store=secrets,
        device_source_plugins=[_ManagedPlugin()],
        discover_source_plugins=False,
    )

    with TestClient(app) as client:
        before = client.get("/api/v1/device-source/plugins", headers=HEADERS)
        configured = client.put(
            "/api/v1/device-source/plugins/managed-source",
            headers=HEADERS,
            json={
                "enabled": True,
                "config": {"base_url": "https://devices.example.test"},
                "secrets": {"api_token": "not-returned-to-ui"},
            },
        )
        tested = client.post(
            "/api/v1/device-source/plugins/managed-source/test",
            headers=HEADERS,
        )
        switched = client.put(
            "/api/v1/device-source",
            headers=HEADERS,
            json={"source": "managed-source"},
        )
        active_disable = client.put(
            "/api/v1/device-source/plugins/managed-source",
            headers=HEADERS,
            json={"enabled": False},
        )
        client.put(
            "/api/v1/device-source",
            headers=HEADERS,
            json={"source": "sample"},
        )
        disabled = client.put(
            "/api/v1/device-source/plugins/managed-source",
            headers=HEADERS,
            json={"enabled": False},
        )

    assert before.status_code == 200
    before_plugin = next(
        item for item in before.json()["plugins"] if item["id"] == "managed-source"
    )
    assert before_plugin["built_in"] is False
    assert before_plugin["version"] == "1.4.0"
    assert before_plugin["available"] is False
    assert configured.status_code == 200
    configured_plugin = next(
        item for item in configured.json()["plugins"] if item["id"] == "managed-source"
    )
    token_field = next(
        item for item in configured_plugin["config_fields"] if item["key"] == "api_token"
    )
    assert configured_plugin["available"] is True
    assert token_field["value"] is None
    assert token_field["secret_configured"] is True
    assert "not-returned-to-ui" not in configured.text
    assert secrets.get("device-source-plugin/managed-source/api_token") == "not-returned-to-ui"
    assert tested.status_code == 200
    assert tested.json()["success"] is True
    assert switched.status_code == 200
    assert active_disable.status_code == 409
    assert disabled.status_code == 200
    disabled_plugin = next(
        item for item in disabled.json()["plugins"] if item["id"] == "managed-source"
    )
    assert disabled_plugin["enabled"] is False
    assert disabled_plugin["available"] is False
