from __future__ import annotations

from pathlib import Path

from device_tui.interfaces.desktop_api.models import (
    DirectCredentialSessionRequest,
    InternalAuthLoginRequest,
    OneTimeCredentialSessionRequest,
    ProfileCredentialUpdateRequest,
    TransferPasswordResponse,
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
    assert "body: method === 'GET' ? undefined : body" in electron_main
    assert "credential:open-profile-session" in electron_main
    assert "credential:create-temporary-profile" in electron_main
    assert "profileId ? 'PUT' : 'POST'" in electron_main
    assert "encodeURIComponent(profileId)" in electron_main
    assert "payload.profile_type !== 'temporary'" in electron_main
    assert "Untrusted temporary-profile caller" in electron_main
    assert "ipcRenderer.invoke('credential:create-temporary-profile', request)" in preload


def test_ftp_password_save_and_command_copy_use_isolated_main_process_bridges() -> None:
    electron_main = (
        ROOT / "desktop" / "src" / "main" / "index.ts"
    ).read_text(encoding="utf-8")
    preload = (
        ROOT / "desktop" / "src" / "preload" / "index.ts"
    ).read_text(encoding="utf-8")
    transfer = (
        ROOT / "desktop" / "src" / "renderer" / "src" / "components"
        / "TransferWorkspace.vue"
    ).read_text(encoding="utf-8")

    assert "request.path === '/api/v1/file-transfer/password'" in electron_main
    assert "validateTransferSettingsSaveRequest(request)" in electron_main
    assert "ipcMain.handle(\n    'file-transfer:save-settings'" in electron_main
    assert "ipcMain.handle(\n    'file-transfer:copy-command'" in electron_main
    assert "ipcRenderer.invoke('file-transfer:save-settings', request)" in preload
    assert "ipcRenderer.invoke('file-transfer:copy-command', command)" in preload
    assert "{{file_transfer.password.shell}}" in transfer
    assert "workspace.transferSettings?.has_password" in transfer
    assert "window.desktopApi.copyTransferCommand(commandText.value)" in transfer


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


def test_device_import_path_is_owned_by_electron_main_process() -> None:
    electron_main = (ROOT / "desktop" / "src" / "main" / "index.ts").read_text(encoding="utf-8")
    preload = (ROOT / "desktop" / "src" / "preload" / "index.ts").read_text(encoding="utf-8")
    workspace_store = (
        ROOT / "desktop" / "src" / "renderer" / "src" / "stores" / "workspace.ts"
    ).read_text(encoding="utf-8")

    assert "request.path === '/api/v1/device-source/import/preview'" in electron_main
    assert "ipcMain.handle('device-source:choose-import'" in electron_main
    assert "Untrusted device-import caller" in electron_main
    assert "dialog.showOpenDialog(mainWindow" in electron_main
    assert "extensions: ['xlsx', 'csv', 'tsv']" in electron_main
    assert "JSON.stringify({ path: selectedPath })" in electron_main
    assert "ipcRenderer.invoke('device-source:choose-import')" in preload
    assert "window.desktopApi.chooseDeviceImport()" in workspace_store
    assert "chooseDeviceImport({" not in workspace_store


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
    internal = InternalAuthLoginRequest(
        username="operator",
        password="internal-one-time-secret",
        cid="CID-7",
    )
    transfer = TransferPasswordResponse(password="ftp-vault-secret")

    assert "vault-secret" not in repr(vault)
    assert "one-time-secret" not in repr(one_time)
    assert "direct-one-time-secret" not in repr(direct)
    assert "internal-one-time-secret" not in repr(internal)
    assert "ftp-vault-secret" not in repr(transfer)


def test_internal_login_password_stays_out_of_vue_renderer() -> None:
    electron_main = (ROOT / "desktop" / "src" / "main" / "index.ts").read_text(encoding="utf-8")
    preload = (ROOT / "desktop" / "src" / "preload" / "index.ts").read_text(encoding="utf-8")
    workspace_store = (
        ROOT / "desktop" / "src" / "renderer" / "src" / "stores" / "workspace.ts"
    ).read_text(encoding="utf-8")
    credential_dialog = (
        ROOT / "desktop" / "resources" / "credential-dialog.html"
    ).read_text(encoding="utf-8")

    assert "request.path === '/api/v1/internal-auth/login'" in electron_main
    assert "ipcMain.handle(\n    'internal-auth:login'" in electron_main
    assert "ipcRenderer.invoke('internal-auth:login', request)" in preload
    assert "window.desktopApi.loginInternalService" in workspace_store
    assert "username: internalAuthStatus.value.username" in workspace_store
    assert "cid: internalAuthStatus.value.cid" in workspace_store
    assert "sourceLabel: deviceSourceStatus.value.sources.find" in workspace_store
    assert "request.sourceLabel.length > 80" in electron_main
    assert 'id="cid" type="text"' in credential_dialog
    assert "登录 Cookie 只保留在本次 App 运行期间" in credential_dialog
    assert 'document.documentElement.dataset.theme' in electron_main
    assert "backgroundColor: credentialTheme === 'light' ? '#ffffff' : '#08101d'" in electron_main
    assert ':root[data-theme="light"]' in credential_dialog
    assert "theme: credentialTheme" in electron_main
    assert credential_dialog.index('id="username-row"') < credential_dialog.index('id="password"')
    assert credential_dialog.index('id="password"') < credential_dialog.index('id="cid-row"')
    assert 'id="password-toggle"' in credential_dialog
    assert "password.type = visible ? 'password' : 'text'" in credential_dialog
    assert 'id="auto-login" type="checkbox"' in credential_dialog
    assert "记住登录（密码保存到操作系统凭据库）" in credential_dialog
    assert "use_saved_password: !result.password && request.remembered" in electron_main
    assert "auto_login: result.autoLogin === true" in electron_main
    assert "function credentialDialogPath(): string" in electron_main
    assert "process.resourcesPath, 'credential-dialog.html'" in electron_main


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
