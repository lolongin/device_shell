from __future__ import annotations

import json
from pathlib import Path

from device_tui.interfaces.mcp.gateway import McpGateway


class _FakeClient:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.closed = False

    def device_list(self) -> dict[str, object]:
        self.calls.append("device_list")
        return {"ok": True, "data": {"devices": []}}

    def close(self) -> None:
        self.closed = True


def _write_state(path: Path, *, port: int) -> None:
    path.write_text(
        json.dumps(
            {
                "pid": 1,
                "base_url": f"http://127.0.0.1:{port}",
                "token": "token",
            }
        ),
        encoding="utf-8",
    )


def test_gateway_caches_discovery_and_does_not_probe_health(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    state_path = tmp_path / "app-control.json"
    _write_state(state_path, port=1234)
    calls: list[str] = []
    clients: list[_FakeClient] = []

    def create_client(_path: Path) -> _FakeClient:
        client = _FakeClient(calls)
        clients.append(client)
        return client

    monkeypatch.setattr(
        "device_tui.interfaces.mcp.gateway.AppControlClient.from_state_file",
        create_client,
    )
    gateway = McpGateway(state_path)

    first = gateway.call("device_list")
    second = gateway.call("device_list")

    assert first["ok"] and second["ok"]
    assert calls == ["device_list", "device_list"]
    assert len(clients) == 1
    assert first["timing"]["gateway_ms"] >= 0


def test_gateway_reloads_client_when_control_state_changes(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    state_path = tmp_path / "app-control.json"
    _write_state(state_path, port=1234)
    clients: list[_FakeClient] = []

    def create_client(_path: Path) -> _FakeClient:
        client = _FakeClient([])
        clients.append(client)
        return client

    monkeypatch.setattr(
        "device_tui.interfaces.mcp.gateway.AppControlClient.from_state_file",
        create_client,
    )
    gateway = McpGateway(state_path)
    first = gateway.client()

    _write_state(state_path, port=12345)
    second = gateway.client()

    assert second is not first
    assert len(clients) == 2
    assert first.closed


def test_gateway_can_route_to_electron_backend_without_state_file(monkeypatch: object) -> None:
    class _DesktopClient:
        def __init__(self, url: str, token: str) -> None:
            assert url == "http://127.0.0.1:9999"
            assert token == "desktop-token"

        def ai_get_result(self, *, result_id: str, include_raw: bool = False) -> dict[str, object]:
            return {"ok": True, "result_id": result_id, "include_raw": include_raw}

        def close(self) -> None:
            return

    monkeypatch.setenv("DEVICE_TUI_MCP_BACKEND_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("DEVICE_TUI_MCP_BACKEND_TOKEN", "desktop-token")
    monkeypatch.setattr("device_tui.interfaces.mcp.gateway.DesktopApiClient", _DesktopClient)
    gateway = McpGateway(Path("unused-state.json"))

    response = gateway.call("ai_get_result", result_id="ai-1", include_raw=True)

    assert response["ok"] is True
    assert response["result_id"] == "ai-1"
    assert response["include_raw"] is True
    assert response["timing"]["gateway_ms"] >= 0
