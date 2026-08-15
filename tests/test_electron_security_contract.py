from __future__ import annotations

from pathlib import Path

from src.desktop_backend.models import (
    DirectCredentialSessionRequest,
    OneTimeCredentialSessionRequest,
    ProfileCredentialUpdateRequest,
)


ROOT = Path(__file__).resolve().parents[1]


def test_temporary_profile_create_and_edit_accept_passwords_without_exposing_saved_values() -> None:
    profile_dialog = (
        ROOT / "desktop" / "src" / "renderer" / "src" / "components"
        / "ConnectionProfileDialog.vue"
    ).read_text(encoding="utf-8")
    workspace_store = (
        ROOT / "desktop" / "src" / "renderer" / "src" / "stores" / "workspace.ts"
    ).read_text(encoding="utf-8")
    renderer_types = (
        ROOT / "desktop" / "src" / "renderer" / "src" / "types.ts"
    ).read_text(encoding="utf-8")

    assert profile_dialog.count('type="password"') == 3
    assert 'data-testid="temporary-telnet-password"' in profile_dialog
    assert 'data-testid="temporary-ssh-password"' in profile_dialog
    assert 'data-testid="temporary-serial-password"' in profile_dialog
    assert "props.profileType === 'temporary'" in profile_dialog
    assert "留空保留原密码；输入新密码将替换" in profile_dialog
    assert "编辑时留空保留原密码" in profile_dialog
    assert 'autocomplete="new-password"' in profile_dialog
    assert "profile?.ssh.has_password" in profile_dialog
    assert ".password" not in workspace_store.casefold()
    assert "telnet_password" not in renderer_types.casefold()
    assert "ssh_password" not in renderer_types.casefold()
    assert "serial_password" not in renderer_types.casefold()


def test_generic_renderer_bridge_rejects_sensitive_body_keys() -> None:
    electron_main = (
        ROOT / "desktop" / "src" / "main" / "index.ts"
    ).read_text(encoding="utf-8")
    preload = (
        ROOT / "desktop" / "src" / "preload" / "index.ts"
    ).read_text(encoding="utf-8")

    assert "hasSensitiveKey(JSON.parse(request.body))" in electron_main
    assert "Sensitive values are not allowed through the renderer API bridge" in electron_main
    assert "credential:open-profile-session" in electron_main
    assert "credential:create-temporary-profile" in electron_main
    assert "profileId ? 'PUT' : 'POST'" in electron_main
    assert "encodeURIComponent(profileId)" in electron_main
    assert "payload.profile_type !== 'temporary'" in electron_main
    assert "Untrusted temporary-profile caller" in electron_main
    assert "ipcRenderer.invoke('credential:create-temporary-profile', request)" in preload


def test_session_log_export_bridge_is_bounded_and_main_owned() -> None:
    electron_main = (
        ROOT / "desktop" / "src" / "main" / "index.ts"
    ).read_text(encoding="utf-8")
    preload = (
        ROOT / "desktop" / "src" / "preload" / "index.ts"
    ).read_text(encoding="utf-8")

    assert "Untrusted session-log export caller" in electron_main
    assert "request.content.length > 2_000_000" in electron_main
    assert "dialog.showSaveDialog" in electron_main
    assert "logs:open-directory" in electron_main
    assert "logs:choose-directory" in electron_main
    assert "logs:open-session" in electron_main
    assert "logs:save-copy" in electron_main
    assert "fetchBackend(backend.config, '/api/v1/settings/session-logs')" in electron_main
    assert "Backend returned an invalid session-log directory" in electron_main
    assert "ipcRenderer.invoke('logs:save-copy', request)" in preload
    assert "ipcRenderer.invoke('logs:choose-directory')" in preload
    assert "ipcRenderer.invoke('logs:open-session', sessionId)" in preload


def test_terminal_clipboard_bridge_is_bounded_and_main_owned() -> None:
    electron_main = (
        ROOT / "desktop" / "src" / "main" / "index.ts"
    ).read_text(encoding="utf-8")
    preload = (
        ROOT / "desktop" / "src" / "preload" / "index.ts"
    ).read_text(encoding="utf-8")

    assert "Untrusted clipboard caller" in electron_main
    assert "value.length > 2_000_000" in electron_main
    assert "clipboard.readText()" in electron_main
    assert "clipboard.writeText(value)" in electron_main
    assert "ipcRenderer.invoke('clipboard:read-text')" in preload
    assert "ipcRenderer.invoke('clipboard:write-text', value)" in preload


def test_sensitive_backend_models_hide_password_from_repr() -> None:
    vault = ProfileCredentialUpdateRequest(password="vault-secret")
    one_time = OneTimeCredentialSessionRequest(
        profile_id="SERVER-1",
        kind="ssh",
        password="one-time-secret",
    )
    direct = DirectCredentialSessionRequest(
        device_id="DEVICE-1",
        kind="ssh",
        host="127.0.0.1",
        port=22,
        username="operator",
        password="direct-one-time-secret",
    )

    assert "vault-secret" not in repr(vault)
    assert "one-time-secret" not in repr(one_time)
    assert "direct-one-time-secret" not in repr(direct)


def test_custom_device_connection_uses_isolated_credential_bridge() -> None:
    electron_main = (ROOT / "desktop" / "src" / "main" / "index.ts").read_text(encoding="utf-8")
    preload = (ROOT / "desktop" / "src" / "preload" / "index.ts").read_text(encoding="utf-8")
    workspace_store = (
        ROOT / "desktop" / "src" / "renderer" / "src" / "stores" / "workspace.ts"
    ).read_text(encoding="utf-8")
    credential_dialog = (
        ROOT / "desktop" / "resources" / "credential-dialog.html"
    ).read_text(encoding="utf-8")

    assert "credential:open-device-session" in electron_main
    assert "request.path === '/api/v1/sessions/direct'" in electron_main
    assert "ipcRenderer.invoke('credential:open-device-session', request)" in preload
    assert "window.desktopApi.openDeviceSession" in workspace_store
    assert 'type="password"' not in workspace_store
    assert 'id="host"' in credential_dialog
    assert 'id="port"' in credential_dialog
    assert 'id="username"' in credential_dialog
    assert 'id="password" type="password"' in credential_dialog
