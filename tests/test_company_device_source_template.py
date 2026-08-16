from __future__ import annotations

import importlib
import sys
from pathlib import Path
import tomllib

import pytest
from fastapi.testclient import TestClient

from device_tui.plugin_api import DeviceSourceContext
from device_tui.repository_api import RepositoryError, STATUS_IDLE, STATUS_OCCUPIED
from src.desktop_backend.app import create_app
from src.desktop_backend.session_hub import SessionHub
from src.imported_devices import MemoryImportedDeviceStore


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "integration-templates" / "company-device-source"


def _provider(monkeypatch):
    monkeypatch.syspath_prepend(str(TEMPLATE / "src"))
    for name in tuple(sys.modules):
        if name == "company_device_source" or name.startswith("company_device_source."):
            sys.modules.pop(name, None)
    return importlib.import_module("company_device_source.provider")


def test_company_template_is_an_independent_entry_point_package() -> None:
    configuration = tomllib.loads(
        (TEMPLATE / "pyproject.toml").read_text(encoding="utf-8")
    )
    package_root = TEMPLATE / "src" / "company_device_source"

    assert configuration["project"]["dependencies"] == ["device-tui>=0.1,<1"]
    assert configuration["project"]["entry-points"]["device_tui.device_sources"] == {
        "company": "company_device_source.provider:create_plugin"
    }
    for path in package_root.glob("*.py"):
        assert "from src." not in path.read_text(encoding="utf-8")


def test_company_template_is_directly_usable_end_to_end(monkeypatch) -> None:
    provider = _provider(monkeypatch)
    repository = provider.create_plugin().create_repository(DeviceSourceContext())

    assert repository.internal_auth_status().configured is True
    with pytest.raises(RepositoryError, match="请先登录"):
        repository.fetch_devices()

    status = repository.login_internal("internal-user", "password", "CID-001")
    devices = repository.fetch_devices()
    claimed = repository.claim_device("INTERNAL-DEMO-01", "internal-user")
    occupied = repository.fetch_devices()[0]
    released = repository.release_device("INTERNAL-DEMO-01", "internal-user")

    assert status.authenticated is True
    assert len(devices) == 2
    assert devices[0].status == STATUS_IDLE
    assert "已占用" in claimed
    assert occupied.status == STATUS_OCCUPIED
    assert occupied.owner == "internal-user"
    assert "已释放" in released


def test_company_template_replaces_only_web_api_binding(monkeypatch) -> None:
    provider = _provider(monkeypatch)
    binding = importlib.import_module("company_device_source.binding")
    demo_api = importlib.import_module("company_device_source.demo_api")
    expected = demo_api.DemoCompanyWebApi()
    received: list[DeviceSourceContext] = []

    def create_api(context: DeviceSourceContext):
        received.append(context)
        return expected

    monkeypatch.setattr(binding, "create_company_web_api", create_api)
    context = DeviceSourceContext(config={"refresh_seconds": 60})

    repository = provider.create_plugin().create_repository(context)

    assert repository._api is expected
    assert repository.refresh_interval_seconds == 60
    assert received == [context]


def test_company_template_works_through_desktop_backend(monkeypatch) -> None:
    monkeypatch.setenv("DEVICE_TUI_DATA_SOURCE", "sample")
    provider = _provider(monkeypatch)
    app = create_app(
        token="company-template-test",
        session_hub=SessionHub(),
        imported_device_store=MemoryImportedDeviceStore(),
        device_source_plugins=[provider.create_plugin()],
        discover_source_plugins=False,
    )
    headers = {"Authorization": "Bearer company-template-test"}

    with TestClient(app) as client:
        plugins = client.get("/api/v1/device-source/plugins", headers=headers)
        switched = client.put(
            "/api/v1/device-source",
            headers=headers,
            json={"source": "internal-site"},
        )
        before_login = client.get("/api/v1/devices", headers=headers)
        login = client.post(
            "/api/v1/internal-auth/login",
            headers=headers,
            json={
                "username": "backend-user",
                "password": "backend-password",
                "cid": "CID-BACKEND",
            },
        )
        devices = client.get("/api/v1/devices", headers=headers)
        claimed = client.post(
            "/api/v1/devices/INTERNAL-DEMO-01/claim",
            headers=headers,
        )

    assert plugins.status_code == 200
    company = next(item for item in plugins.json()["plugins"] if item["id"] == "internal-site")
    assert company["available"] is True
    assert len(company["config_fields"]) == 3
    assert switched.status_code == 200
    assert before_login.status_code == 200
    assert before_login.json()["devices"] == []
    assert login.status_code == 200
    assert login.json()["authenticated"] is True
    assert devices.status_code == 200
    assert {
        "INTERNAL-DEMO-01",
        "INTERNAL-DEMO-02",
    }.issubset({item["id"] for item in devices.json()["devices"]})
    assert claimed.status_code == 200
    assert claimed.json()["device"]["owner"] == "backend-user"
