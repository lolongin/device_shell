from __future__ import annotations

import sys
from pathlib import Path
import tomllib

import pytest

from device_tui.plugin_api import DeviceSourceContext
from device_tui.plugin_api.repository import RepositoryError, STATUS_IDLE, STATUS_OCCUPIED


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from company_device_source import binding  # noqa: E402
from company_device_source.demo_api import DemoCompanyWebApi  # noqa: E402
from company_device_source.provider import create_plugin  # noqa: E402


def test_package_registers_entry_point() -> None:
    configuration = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert configuration["project"]["entry-points"]["device_tui.device_sources"] == {
        "company": "company_device_source.provider:create_plugin"
    }


def test_default_plugin_is_immediately_configured_but_requires_login() -> None:
    repository = create_plugin().create_repository(DeviceSourceContext())

    assert repository.internal_auth_status().configured is True
    assert repository.internal_auth_status().authenticated is False
    with pytest.raises(RepositoryError, match="请先登录"):
        repository.fetch_devices()


def test_demo_login_inventory_and_occupancy_work_end_to_end() -> None:
    repository = create_plugin().create_repository(DeviceSourceContext())

    status = repository.login_internal("demo-user", "demo-password", "CID-DEMO")
    before = repository.fetch_devices()
    revision = repository.current_revision()
    claimed = repository.claim_device("INTERNAL-DEMO-01", "demo-user")
    after_claim = repository.fetch_devices()
    owned_after_claim = repository.fetch_owned_device_ids()
    released = repository.release_device("INTERNAL-DEMO-01", "demo-user")
    after_release = repository.fetch_devices()

    assert status.authenticated is True
    assert status.username == "demo-user"
    assert len(before) == 2
    assert before[0].status == STATUS_IDLE
    assert "已占用" in claimed
    assert after_claim[0].status == STATUS_OCCUPIED
    assert after_claim[0].owner == "demo-user"
    assert owned_after_claim == {"INTERNAL-DEMO-01"}
    assert "已释放" in released
    assert after_release[0].status == STATUS_IDLE
    assert repository.current_revision() > revision


def test_only_binding_factory_needs_replacement(monkeypatch) -> None:
    expected_api = DemoCompanyWebApi()
    received: list[DeviceSourceContext] = []

    def create_api(context: DeviceSourceContext):
        received.append(context)
        return expected_api

    monkeypatch.setattr(binding, "create_company_web_api", create_api)
    context = DeviceSourceContext(config={"refresh_seconds": 45})

    repository = create_plugin().create_repository(context)

    assert repository._api is expected_api
    assert repository.refresh_interval_seconds == 45
    assert received == [context]
