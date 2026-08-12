from __future__ import annotations

import asyncio
import time

from fastapi.testclient import TestClient

from src.desktop_backend.app import create_app
from src.desktop_backend.session_logging import FileSessionLogSink
from src.desktop_backend.session_hub import SessionHub
from src.repository import SampleDeviceRepository
from pathlib import Path


TOKEN = "desktop-test-token"


def _client() -> TestClient:
    app = create_app(
        token=TOKEN,
        repository=SampleDeviceRepository(),
        session_hub=SessionHub(),
    )
    return TestClient(app)


def test_health_does_not_require_token() -> None:
    with _client() as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "api_version": 1}


def test_device_api_excludes_credentials() -> None:
    with _client() as client:
        unauthorized = client.get("/api/v1/devices")
        response = client.get(
            "/api/v1/devices",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
    assert unauthorized.status_code == 401
    assert response.status_code == 200
    payload = response.json()
    assert payload["devices"]
    encoded = response.text.lower()
    assert "password" not in encoded
    assert "username" not in encoded


def test_device_api_includes_one_safe_simulated_terminal_row() -> None:
    with _client() as client:
        response = client.get(
            "/api/v1/devices",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

    assert response.status_code == 200
    devices = response.json()["devices"]
    owned_device_ids = response.json()["owned_device_ids"]
    simulated = [device for device in devices if device["id"] == "SIM-TERMINAL"]
    assert len(devices) == 21
    assert len(simulated) == 1
    assert devices[-1] == simulated[0]
    assert simulated[0]["row_id"] == "SIM-TERMINAL::0000"
    assert simulated[0]["name"] == "模拟终端"
    assert simulated[0]["is_simulated"] is True
    assert simulated[0]["ssh_endpoint"] is None
    assert simulated[0]["telnet_endpoint"] is None
    assert simulated[0]["serial_endpoint"] is None
    assert simulated[0]["can_connect_ssh"] is False
    assert simulated[0]["can_connect_telnet"] is False
    assert simulated[0]["can_connect_serial"] is False
    assert simulated[0]["can_claim"] is False
    assert simulated[0]["can_release"] is False
    assert simulated[0]["can_power_off"] is False
    assert len(owned_device_ids) == 4
    assert len(set(owned_device_ids)) == 4
    assert "XTN-NJ-018" in owned_device_ids
    assert "SIM-TERMINAL" not in owned_device_ids


def test_simulated_terminal_api_creates_only_simulated_sessions() -> None:
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with _client() as client:
        created = client.post(
            "/api/v1/sessions",
            headers=headers,
            json={"device_id": "SIM-TERMINAL", "kind": "simulated"},
        )
        ssh = client.post(
            "/api/v1/sessions",
            headers=headers,
            json={"device_id": "SIM-TERMINAL", "kind": "ssh"},
        )
        claim = client.post(
            "/api/v1/devices/SIM-TERMINAL/claim",
            headers=headers,
        )

    assert created.status_code == 200
    assert created.json()["device_id"] == "SIM-TERMINAL"
    assert created.json()["kind"] == "simulated"
    assert ssh.status_code == 400
    assert ssh.json()["error"]["code"] == "unsupported_operation"
    assert claim.status_code == 400
    assert claim.json()["error"]["code"] == "unsupported_operation"


def test_quick_send_crud_and_dispatch_are_python_backed() -> None:
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with _client() as client:
        session = client.post(
            "/api/v1/sessions",
            headers=headers,
            json={"device_id": "SIM-TERMINAL", "kind": "simulated"},
        ).json()
        workspace = client.get("/api/v1/automation/workspace", headers=headers)
        created = client.post(
            "/api/v1/automation/quick-send-buttons",
            headers=headers,
            json={
                "name": "查看版本",
                "response_text": "display version",
                "append_enter": True,
                "sensitive": False,
            },
        )
        button = created.json()["quick_send_buttons"][-1]
        sent = client.post(
            f"/api/v1/automation/quick-send-buttons/{button['id']}/send",
            headers=headers,
            json={"session_id": session["id"]},
        )
        deleted = client.delete(
            f"/api/v1/automation/quick-send-buttons/{button['id']}",
            headers=headers,
        )

    assert workspace.status_code == 200
    assert workspace.json()["quick_send_buttons"][0]["response_text"] == "Ctrl+B"
    assert created.status_code == 200
    assert sent.status_code == 200
    assert sent.json()["status"] == "sent"
    assert deleted.status_code == 204


def test_device_api_includes_legacy_table_presentation_fields() -> None:
    with _client() as client:
        response = client.get(
            "/api/v1/devices",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

    assert response.status_code == 200
    devices = response.json()["devices"]
    assert devices
    first = devices[0]
    for key in ("row_id", "board_id", "board_type", "slot", "status_text", "tooltip"):
        assert key in first
    assert len({device["row_id"] for device in devices}) == len(devices)
    assert first["board_type"]
    assert first["slot"]
    assert "设备:" in first["tooltip"]
    assert "Slot:" in first["tooltip"]

    frame_rows = [device for device in devices if device["id"] == "XTN-NJ-018"]
    assert len(frame_rows) > 1
    assert len({device["row_id"] for device in frame_rows}) == len(frame_rows)
    assert all(device["board_id"] for device in frame_rows)

    occupied = next(device for device in devices if device["status"] == "已被占用")
    assert occupied["status_text"].startswith("已被占用")
    assert "占用时长" in occupied["tooltip"]


def test_device_api_exposes_legacy_connection_action_rules() -> None:
    with _client() as client:
        response = client.get(
            "/api/v1/devices",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

    assert response.status_code == 200
    devices = response.json()["devices"]
    free_device = devices[0]
    assert free_device["can_connect_telnet"] is True
    assert free_device["can_connect_ssh"] is True
    assert free_device["can_connect_serial"] is False
    assert free_device["serial_display"] == "占用后可见"
    assert free_device["can_claim"] is True
    assert free_device["can_release"] is False
    assert free_device["can_power_off"] is False

    mine = next(device for device in devices if device["owner"] == "li.wei")
    assert mine["can_claim"] is False
    assert mine["can_release"] is True
    assert mine["can_power_off"] is mine["supports_power_off"]
    assert mine["serial_display"] in {"占用后可见", "设备无串口 IP"} or ":" in mine["serial_display"]


def test_simulated_terminal_websocket_supports_input_and_replay() -> None:
    with _client() as client:
        devices = client.get(
            "/api/v1/devices",
            headers={"Authorization": f"Bearer {TOKEN}"},
        ).json()["devices"]
        created = client.post(
            "/api/v1/sessions",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={"device_id": devices[0]["id"], "kind": "simulated"},
        )
        assert created.status_code == 200
        session_id = created.json()["id"]
        with client.websocket_connect(
            f"/ws/v1/terminals/{session_id}?access={TOKEN}"
        ) as websocket:
            initial = [websocket.receive_json(), websocket.receive_json()]
            assert {event["type"] for event in initial} == {
                "terminal.status",
                "terminal.output",
            }
            websocket.send_json({"type": "terminal.input", "data": "display version\r"})
            output = ""
            for _ in range(40):
                event = websocket.receive_json()
                output += str(event.get("data") or "")
                if "SimOS V1.0" in output:
                    break
            assert "SimOS V1.0" in output


def test_multi_session_simulated_load_sentinel(tmp_path: Path) -> None:
    app = create_app(
        token=TOKEN,
        repository=SampleDeviceRepository(),
        session_hub=SessionHub(log_sink=FileSessionLogSink(tmp_path / "logs")),
    )
    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        device_id = client.get("/api/v1/devices", headers=headers).json()["devices"][0]["id"]
        sessions = [
            client.post(
                "/api/v1/sessions",
                headers=headers,
                json={"device_id": device_id, "kind": "simulated", "title": f"load-{index}"},
            ).json()
            for index in range(12)
        ]

        listed = client.get("/api/v1/sessions", headers=headers).json()["sessions"]
        for session in sessions:
            sent = client.post(
                "/api/v1/commands/send",
                headers=headers,
                json={"session_id": session["id"], "command": "display version"},
            )
            assert sent.status_code == 200

        for session in sessions:
            log = ""
            for _ in range(60):
                log = client.get(
                    f"/api/v1/sessions/{session['id']}/log",
                    headers=headers,
                ).json()["content"]
                if "SimOS V1.0" in log:
                    break
                time.sleep(0.02)
            assert "SimOS V1.0" in log

        for session in sessions:
            closed = client.delete(f"/api/v1/sessions/{session['id']}", headers=headers)
            assert closed.status_code == 204

    assert {session["id"] for session in sessions}.issubset({session["id"] for session in listed})


def test_session_log_settings_move_active_log_and_manual_new_log(tmp_path: Path) -> None:
    initial_root = tmp_path / "initial-logs"
    moved_root = tmp_path / "moved-logs"
    sink = FileSessionLogSink(initial_root)
    app = create_app(
        token=TOKEN,
        repository=SampleDeviceRepository(),
        session_hub=SessionHub(log_sink=sink),
    )
    headers = {"Authorization": f"Bearer {TOKEN}"}

    with TestClient(app) as client:
        device_id = client.get("/api/v1/devices", headers=headers).json()["devices"][0]["id"]
        session = client.post(
            "/api/v1/sessions",
            headers=headers,
            json={"device_id": device_id, "kind": "simulated"},
        ).json()
        session_id = session["id"]
        client.post(
            "/api/v1/commands/send",
            headers=headers,
            json={"session_id": session_id, "command": "display version"},
        )
        for _ in range(60):
            content = client.get(
                f"/api/v1/sessions/{session_id}/log",
                headers=headers,
            ).json()["content"]
            if "SimOS V1.0" in content:
                break
            time.sleep(0.02)

        settings = client.put(
            "/api/v1/settings/session-logs",
            headers=headers,
            json={"directory": str(moved_root), "rotate_size_mb": 7},
        )
        assert settings.status_code == 200
        assert settings.json()["directory"] == str(moved_root.resolve())
        assert settings.json()["rotate_size_mb"] == 7
        assert settings.json()["moved_active_logs"] == 1

        location = client.get(
            f"/api/v1/sessions/{session_id}/log-path",
            headers=headers,
        )
        assert location.status_code == 200
        assert Path(location.json()["path"]).parent == moved_root.resolve()
        assert Path(location.json()["path"]).exists()

        fresh = client.post(
            f"/api/v1/sessions/{session_id}/log/new",
            headers=headers,
        )
        assert fresh.status_code == 200
        assert Path(fresh.json()["archived_path"]).exists()
        current = client.get(
            f"/api/v1/sessions/{session_id}/log",
            headers=headers,
        ).json()["content"]
        assert "New log created" in current
        assert "SimOS V1.0" not in current


def test_session_log_settings_reject_relative_root_and_missing_session(tmp_path: Path) -> None:
    app = create_app(
        token=TOKEN,
        repository=SampleDeviceRepository(),
        session_hub=SessionHub(log_sink=FileSessionLogSink(tmp_path / "logs")),
    )
    headers = {"Authorization": f"Bearer {TOKEN}"}

    with TestClient(app) as client:
        relative = client.put(
            "/api/v1/settings/session-logs",
            headers=headers,
            json={"directory": "relative/logs", "rotate_size_mb": 8},
        )
        missing_path = client.get(
            "/api/v1/sessions/missing/log-path",
            headers=headers,
        )
        missing_new = client.post(
            "/api/v1/sessions/missing/log/new",
            headers=headers,
        )

    assert relative.status_code == 422
    assert missing_path.status_code == 404
    assert missing_new.status_code == 404


def test_session_hub_keeps_session_after_subscriber_detaches() -> None:
    async def scenario() -> None:
        hub = SessionHub()
        created = await hub.create_simulated("DEVICE-1")
        queue, replay = hub.subscribe(created.id)
        assert replay
        hub.unsubscribe(created.id, queue)
        assert hub.get(created.id).session.is_connected
        await hub.close_all()

    asyncio.run(scenario())


def test_application_errors_use_versioned_envelope() -> None:
    with _client() as client:
        response = client.post(
            "/api/v1/sessions",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={"device_id": "missing-device", "kind": "simulated"},
        )

    assert response.status_code == 404
    assert response.json()["api_version"] == 1
    assert response.json()["error"]["code"] == "resource_not_found"


def test_session_lifecycle_is_available_on_application_event_socket() -> None:
    with _client() as client:
        device_id = client.get(
            "/api/v1/devices",
            headers={"Authorization": f"Bearer {TOKEN}"},
        ).json()["devices"][0]["id"]
        with client.websocket_connect(f"/ws/v1/events?access={TOKEN}") as websocket:
            created = client.post(
                "/api/v1/sessions",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={"device_id": device_id, "kind": "simulated"},
            )
            assert created.status_code == 200
            event = websocket.receive_json()

    assert event["version"] == 1
    assert event["type"] == "session.created"
    assert event["resourceId"] == created.json()["id"]


def test_ai_result_is_available_on_application_event_socket() -> None:
    with _client() as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        device_id = client.get("/api/v1/devices", headers=headers).json()["devices"][0]["id"]
        session_id = client.post(
            "/api/v1/sessions",
            headers=headers,
            json={"device_id": device_id, "kind": "simulated"},
        ).json()["id"]
        ticket = client.post(
            "/api/v1/ws-tickets",
            headers=headers,
            json={"scope": "events", "resource_id": ""},
        ).json()["ticket"]
        with client.websocket_connect(f"/ws/v1/events?ticket={ticket}") as websocket:
            response = client.post(
                "/api/v1/mcp/ai_execute_command",
                headers=headers,
                json={"session_id": session_id, "command": "display version"},
            )
            events = [websocket.receive_json() for _ in range(2)]

    assert response.status_code == 200
    event = next(item for item in events if item["type"] == "ai.result.created")
    assert event["data"]["kind"] == "command"


def test_session_can_disconnect_without_closing_and_read_log_contract() -> None:
    with _client() as client:
        device_id = client.get(
            "/api/v1/devices",
            headers={"Authorization": f"Bearer {TOKEN}"},
        ).json()["devices"][0]["id"]
        created = client.post(
            "/api/v1/sessions",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={"device_id": device_id, "kind": "simulated"},
        ).json()

        disconnected = client.post(
            f"/api/v1/sessions/{created['id']}/disconnect",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        sessions = client.get(
            "/api/v1/sessions",
            headers={"Authorization": f"Bearer {TOKEN}"},
        ).json()["sessions"]
        log_response = client.get(
            f"/api/v1/sessions/{created['id']}/log",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

    assert disconnected.status_code == 200
    assert disconnected.json()["status"] == "disconnected"
    assert created["id"] in {session["id"] for session in sessions}
    assert log_response.status_code == 200
    assert log_response.json() == {
        "api_version": 1,
        "session_id": created["id"],
        "content": "",
        "truncated": False,
    }


def test_terminal_websocket_accepts_one_time_scoped_ticket() -> None:
    with _client() as client:
        device_id = client.get(
            "/api/v1/devices",
            headers={"Authorization": f"Bearer {TOKEN}"},
        ).json()["devices"][0]["id"]
        session_id = client.post(
            "/api/v1/sessions",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={"device_id": device_id, "kind": "simulated"},
        ).json()["id"]
        ticket = client.post(
            "/api/v1/ws-tickets",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={"scope": "terminal", "resource_id": session_id},
        )
        assert ticket.status_code == 200

        with client.websocket_connect(
            f"/ws/v1/terminals/{session_id}?ticket={ticket.json()['ticket']}"
        ) as websocket:
            event = websocket.receive_json()

    assert event["sessionId"] == session_id


def test_device_claim_and_release_are_exposed_through_application_service() -> None:
    with _client() as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        inventory = client.get("/api/v1/devices", headers=headers).json()
        devices = inventory["devices"]
        device = next(
            candidate
            for candidate in devices
            if candidate["owner"] is None
            and ("idle" in candidate["status"].lower() or "空闲" in candidate["status"])
        )

        claimed = client.post(f"/api/v1/devices/{device['id']}/claim", headers=headers)
        released = client.post(f"/api/v1/devices/{device['id']}/release", headers=headers)

    assert claimed.status_code == 200
    assert claimed.json()["device"]["owner"] == inventory["current_user"]
    assert claimed.json()["action"] == "claim"
    assert released.status_code == 200
    assert released.json()["device"]["owner"] is None


def test_connection_profile_crud_never_returns_password_and_can_create_session() -> None:
    secret = "profile-api-secret"
    with _client() as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        created = client.post(
            "/api/v1/connection-profiles",
            headers=headers,
            json={
                "profile_type": "server",
                "name": "API server",
                "group": "Lab",
                "preferred_protocol": "ssh",
                "ssh": {"host": "127.0.0.1", "port": 9, "username": "root"},
                "ssh_password": secret,
            },
        )
        assert created.status_code == 200
        profile_id = created.json()["id"]
        listed = client.get("/api/v1/connection-profiles", headers=headers)
        session = client.post(
            "/api/v1/sessions",
            headers=headers,
            json={"device_id": profile_id, "kind": "ssh"},
        )
        deleted = client.delete(
            f"/api/v1/connection-profiles/{profile_id}",
            headers=headers,
        )

    assert created.json()["ssh"]["has_password"] is True
    assert secret not in created.text
    assert secret not in listed.text
    assert listed.json()["groups"] == ["Lab"]
    assert session.status_code == 200
    assert session.json()["device_id"] == profile_id
    assert deleted.status_code == 204


def test_connection_profile_group_can_be_created_before_its_servers() -> None:
    with _client() as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        created = client.post(
            "/api/v1/connection-profile-groups",
            headers=headers,
            json={"name": "Production"},
        )
        listed = client.get("/api/v1/connection-profiles", headers=headers)

    assert created.status_code == 200
    assert created.json()["groups"] == ["Production"]
    assert listed.json()["groups"] == ["Production"]


def test_connection_profile_routes_require_desktop_authorization() -> None:
    with _client() as client:
        listed = client.get("/api/v1/connection-profiles")
        group = client.post(
            "/api/v1/connection-profile-groups",
            json={"name": "Unauthorized"},
        )
        created = client.post(
            "/api/v1/connection-profiles",
            json={
                "profile_type": "server",
                "name": "Unauthorized",
                "ssh": {"host": "127.0.0.1", "port": 22, "username": "root"},
            },
        )

    assert listed.status_code == 401
    assert group.status_code == 401
    assert created.status_code == 401


def test_profile_credential_endpoints_support_vault_and_one_time_sessions() -> None:
    vault_secret = "vault-only-secret"
    one_time_secret = "one-time-only-secret"
    with _client() as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        profile = client.post(
            "/api/v1/connection-profiles",
            headers=headers,
            json={
                "profile_type": "server",
                "name": "Prompted server",
                "preferred_protocol": "ssh",
                "ssh": {"host": "127.0.0.1", "port": 9, "username": "root"},
            },
        ).json()
        profile_id = profile["id"]

        saved = client.put(
            f"/api/v1/connection-profiles/{profile_id}/credentials/ssh",
            headers=headers,
            json={"password": vault_secret},
        )
        removed = client.delete(
            f"/api/v1/connection-profiles/{profile_id}/credentials/ssh",
            headers=headers,
        )
        session = client.post(
            "/api/v1/sessions/with-credential",
            headers=headers,
            json={
                "profile_id": profile_id,
                "kind": "ssh",
                "password": one_time_secret,
            },
        )
        listed = client.get("/api/v1/connection-profiles", headers=headers)

    assert saved.status_code == 200
    assert saved.json()["ssh"]["has_password"] is True
    assert vault_secret not in saved.text
    assert removed.status_code == 200
    assert removed.json()["ssh"]["has_password"] is False
    assert session.status_code == 200
    assert one_time_secret not in session.text
    assert listed.json()["profiles"][0]["ssh"]["has_password"] is False


def test_temporary_profile_cannot_be_deleted_while_its_session_is_open() -> None:
    with _client() as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        profile = client.post(
            "/api/v1/connection-profiles",
            headers=headers,
            json={
                "profile_type": "temporary",
                "name": "Temporary session",
                "preferred_protocol": "ssh",
                "ssh": {"host": "127.0.0.1", "port": 9, "username": "root"},
                "ssh_password": "temporary-secret",
            },
        ).json()
        session = client.post(
            "/api/v1/sessions",
            headers=headers,
            json={"device_id": profile["id"], "kind": "ssh"},
        )
        blocked = client.delete(
            f"/api/v1/connection-profiles/{profile['id']}",
            headers=headers,
        )
        client.delete(
            f"/api/v1/sessions/{session.json()['id']}",
            headers=headers,
        )
        deleted = client.delete(
            f"/api/v1/connection-profiles/{profile['id']}",
            headers=headers,
        )

    assert session.status_code == 200
    assert blocked.status_code == 409
    assert deleted.status_code == 204


def test_command_workspace_crud_suggestions_and_terminal_dispatch() -> None:
    with _client() as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        initial = client.get("/api/v1/commands/workspace", headers=headers)
        created_group = client.post(
            "/api/v1/commands/groups",
            headers=headers,
            json={"name": "Operations"},
        )
        group_id = created_group.json()["current_group_id"]
        updated = client.put(
            f"/api/v1/commands/groups/{group_id}",
            headers=headers,
            json={"content": "display version\npassword api-secret"},
        )
        preferences = client.put(
            "/api/v1/commands/preferences",
            headers=headers,
            json={"current_group_id": group_id, "enter_sends": True},
        )
        suggestions = client.get(
            "/api/v1/commands/suggestions",
            headers=headers,
            params={"query": "dis"},
        )
        device_id = client.get("/api/v1/devices", headers=headers).json()["devices"][0]["id"]
        session = client.post(
            "/api/v1/sessions",
            headers=headers,
            json={"device_id": device_id, "kind": "simulated"},
        ).json()
        sent = client.post(
            "/api/v1/commands/send",
            headers=headers,
            json={"session_id": session["id"], "command": "password dispatch-secret"},
        )
        final_workspace = client.get("/api/v1/commands/workspace", headers=headers)
        removed = client.delete(
            f"/api/v1/commands/groups/{group_id}",
            headers=headers,
        )

    assert initial.status_code == 200
    assert initial.json()["groups"][0]["name"] == "终端"
    assert updated.status_code == 200
    assert "api-secret" not in updated.text
    assert "password [REDACTED]" in updated.text
    assert preferences.json()["enter_sends"] is True
    assert suggestions.json()["suggestions"][0] == "display version"
    assert sent.status_code == 200
    assert "dispatch-secret" not in sent.text
    assert sent.json()["session_ids"] == [session["id"]]
    assert final_workspace.json()["history"][0]["command"] == "password [REDACTED]"
    assert removed.status_code == 200
    assert len(removed.json()["groups"]) == 1


def test_command_workspace_routes_require_authorization() -> None:
    with _client() as client:
        workspace = client.get("/api/v1/commands/workspace")
        created = client.post("/api/v1/commands/groups", json={"name": "Unauthorized"})
        sent = client.post(
            "/api/v1/commands/send",
            json={"session_id": "missing", "command": "display version"},
        )

    assert workspace.status_code == 401
    assert created.status_code == 401
    assert sent.status_code == 401


def test_automation_rule_crud_manual_trigger_and_terminal_dispatch() -> None:
    with _client() as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        device_id = client.get("/api/v1/devices", headers=headers).json()["devices"][0]["id"]
        session = client.post(
            "/api/v1/sessions",
            headers=headers,
            json={"device_id": device_id, "kind": "simulated"},
        ).json()
        created = client.post(
            "/api/v1/automation/rules",
            headers=headers,
            json={
                "rule": {
                    "name": "Version probe",
                    "pattern": "",
                    "response": "display version\r",
                    "response_text": "display version",
                    "trigger_type": "manual",
                    "enabled": True,
                    "once": False,
                }
            },
        )
        rule_id = created.json()["rules"][0]["id"]
        triggered = client.post(
            f"/api/v1/automation/rules/{rule_id}/trigger",
            headers=headers,
            json={"session_id": session["id"]},
        )
        with client.websocket_connect(
            f"/ws/v1/terminals/{session['id']}?access={TOKEN}"
        ) as websocket:
            output = ""
            for _ in range(20):
                event = websocket.receive_json()
                output += str(event.get("data") or "")
                if "SimOS V1.0" in output:
                    break
        disabled = client.put(
            f"/api/v1/automation/rules/{rule_id}/enabled",
            headers=headers,
            json={"enabled": False},
        )
        removed = client.delete(
            f"/api/v1/automation/rules/{rule_id}",
            headers=headers,
        )

    assert created.status_code == 200
    assert created.json()["rules"][0]["rule"]["name"] == "Version probe"
    assert triggered.status_code == 200
    assert triggered.json()["status"] == "started"
    assert disabled.json()["rules"][0]["rule"]["enabled"] is False
    assert "SimOS V1.0" in output
    assert removed.status_code == 204


def test_automation_routes_require_authorization_and_reject_plaintext_secrets() -> None:
    unsafe_secret = "do-not-persist-this"
    with _client() as client:
        unauthorized = client.get("/api/v1/automation/workspace")
        rejected = client.post(
            "/api/v1/automation/rules",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={
                "rule": {
                    "name": "Unsafe login",
                    "pattern": "Password:",
                    "response": unsafe_secret,
                    "once": False,
                }
            },
        )
        workspace = client.get(
            "/api/v1/automation/workspace",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

    assert unauthorized.status_code == 401
    assert rejected.status_code == 400
    assert unsafe_secret not in rejected.text
    assert workspace.json()["rules"] == []
