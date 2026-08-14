# Network Device Desktop

PySide6 desktop GUI for device inventory, occupancy management, and embedded
terminal sessions.

## Features

- Device list with keyword, domain, status, CPU, and "my occupancy" filters
- Device detail panel with Telnet, SSH, serial, asset, and owner information
- Web-rendered home dashboard, compact terminal device navigation, and shared OLED workspace theme
- Embedded xterm.js terminal sessions through PySide6 WebEngine
- Embedded Telnet, Linux SSH, and serial Telnet sessions
- Multi-session device tabs, split terminal panes, reconnect, disconnect, and logs
- Command note panel with persisted command tabs
- Optional API-backed repository for integration with an external website/backend

## Design System

The workspace uses a Web-style OLED design system shared by Qt style sheets,
embedded Web pages, xterm.js, canvas terminal rendering, and generated HTML
snippets. The source of truth is `design-system/MASTER.md`.

Key invariants:

- Home is the full device pool dashboard; the left device pool stays hidden on home.
- Terminal mode shows the left device pool only as compact session navigation.
- Web pages link `src/web/assets/workspace-theme.css` instead of redefining local root tokens.
- Native context menus go through the workspace menu factory so right-click actions stay consistent.

## Install

```bash
pip install -e .
```

or install the runtime dependencies directly:

```bash
pip install PySide6 PySide6-WebEngine asyncssh "telnetlib3>=4.0,<5" pyte
```

## Run

```bash
python src/desktop_app.py
```

or after editable install:

```bash
device-tui
```

## Electron + Vue Desktop Preview

The next-generation desktop client is developed alongside the existing PySide6
application. It starts a headless Python API on a random loopback port, loads the
real device repository, and keeps terminal sessions in a backend-owned Session Hub.

Install the Python backend dependency and desktop packages:

```powershell
python -m pip install "fastapi>=0.135,<1" "uvicorn>=0.46,<1" "websockets>=15,<17" "keyring>=25,<26"
Set-Location desktop
npm install
```

Run the new desktop client during development:

```powershell
$env:DEVICE_TUI_PROJECT_ROOT = (Resolve-Path ..)
npm run dev
```

Build and preview the production renderer:

```powershell
npm run build
npm run preview
```

Build the Windows installer with the bundled Python backend and run the local
release smoke:

```powershell
npm run dist
npm run smoke:release
npm run smoke:clean-runtime
npm run smoke:soak
npm run smoke:app-soak
```

For an overnight packaged-app soak, run:

```powershell
npm run soak:app
```

To exercise a real upgrade and rollback path, pass an older installer to the
validation script:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/validate-release.ps1 -PreviousInstaller C:\path\to\old\DeviceTUISetup.exe
```

The current migration milestone includes device inventory/details and filters,
occupancy and power actions, temporary connections, saved servers and groups,
Electron supervision of the Python process, backend-owned simulated/SSH/Telnet/
serial-over-Telnet sessions, replay and reconnect, terminal logs/search/font
preferences, and multi-session navigation. Connection metadata is stored in SQLite;
saved passwords use the operating-system credential vault. One-time passwords are
entered in an isolated Electron credential window and do not enter Vue/Pinia,
SQLite, or logs. The backend bearer token also remains outside the Vue renderer,
and terminal WebSockets use short-lived one-time tickets. The Electron workspace now
also includes persisted command tabs/history and a Python-owned terminal automation
editor with output matching, manual/connection/delayed triggers, multi-step and
action-flow execution, target routing, loops, cancellation, and manual-input
precedence. Action flows support scoped variables, controlled assignment/add/subtract/
multiply operations, safe expressions such as `{{base + loop.index0 * step}}`,
array/object access, read-only session/device context, and templates such as
`{{counter}}`, `{{loop.index}}`, `{{loop.count}}`, `{{loop.first}}`, and
`{{loop.last}}`. A backend dry-run preview expands actions and variable changes with
optional simulated terminal output without waiting or writing to a terminal.
Credential-like legacy automation responses are moved to the operating-
system vault; echoed values are redacted before WebSocket replay and logging.
The managed file-transfer workspace starts backend-owned FTP/SFTP services, browses
a user-selected shared directory, runs PC-to-device or device-to-PC terminal plans,
and exposes progress/cancellation with overwrite, space, source-change, and exact-
byte verification gates. Its generated service password stays in the operating-
system credential vault and never enters Vue or SQLite.
Existing PySide6 state is imported once without modifying its source file. The
legacy `device-tui` entry point remains unchanged.

## Large Local Dataset

For local GUI performance testing, set `DEVICE_TUI_SAMPLE_DEVICE_COUNT` before
launching the desktop app. The built-in sample devices are kept first, and
generated devices are appended until the requested count is reached.

PowerShell example:

```powershell
$env:DEVICE_TUI_SAMPLE_DEVICE_COUNT = "1200"
python src/desktop_app.py
```

## API Mode

By default, the GUI uses the in-memory sample repository. To connect it to your
own backend service:

```powershell
$env:DEVICE_TUI_DATA_SOURCE = "api"
$env:DEVICE_TUI_API_BASE_URL = "http://127.0.0.1:8765"
$env:DEVICE_TUI_REFRESH_SECONDS = "30"
python src/desktop_app.py
```

Useful environment variables:

- `DEVICE_TUI_CURRENT_USER`: override current user in sample mode
- `DEVICE_TUI_API_BASE_URL`: backend API base URL
- `DEVICE_TUI_API_TIMEOUT_SECONDS`: backend API timeout in seconds
- `DEVICE_TUI_REFRESH_SECONDS`: polling interval in API mode
- `DEVICE_TUI_SAMPLE_DEVICE_COUNT`: generated sample device count for GUI testing
- `DEVICE_TUI_TERMINAL_WIDGET`: terminal renderer, defaults to `xterm`.
  Use `canvas` for the previous PySide/pyte renderer or `legacy` for the
  previous `QPlainTextEdit` renderer.
- `DEVICE_TUI_AUTO_RESTORE_SESSIONS`: set to `1` to automatically reopen saved
  terminal sessions on startup.
- `DEVICE_TUI_XTERM_LOCAL_ECHO`: set to `1` only for endpoints which do not
  echo typed characters themselves. Leave it unset for normal SSH shells.

## xterm.js Terminal

The default terminal widget is `PySide6 + QWebEngineView + xterm.js`, bridged
to the existing Python session layer with `QtWebChannel`.

Runtime layout:

```text
QWebEngineView xterm.js -> QtWebChannel -> AsyncSSH/Telnet session
```

The bundled HTML first tries to load xterm assets from `src/web/assets/`:

- `xterm.js`
- `xterm.css`
- `addon-fit.js`

If those files are not present, it falls back to the jsDelivr CDN. For offline
deployments, copy the matching xterm.js build artifacts into `src/web/assets/`.

## Session Logs

Session logs are grouped under the configured log root by device ID and name:

```text
logs/
  MOCK-LAB-000_Mock-Huawei-Lab/
    20260607-120000_Mock-Huawei-Lab_telnet_Telnet-1.log
```

Each log rolls over automatically at 10 MB by default. Use the terminal
toolbar's `日志 > 设置日志分卷大小...` action to choose a value from
1 MB to 1024 MB. The log root and rollover size are saved in desktop state.

## AI Tool Calling and MCP

The desktop app starts a local-only control API on a random `127.0.0.1` port.
It writes connection details to:

```text
%LOCALAPPDATA%\DeviceTUI\app-control.json
```

Install the project, start the desktop app, and configure an MCP client to run:

```text
device-tui-mcp
```

The equivalent source checkout command is:

```powershell
python -m src.mcp_server
```

The MCP server exposes these tools:

- `system_status`
- `device_list`
- `device_get`
- `device_select`
- `session_list`
- `session_manage`
- `session_open`
- `terminal_run`
- `terminal_execute`
- `terminal_execute_batch`
- `terminal_interact`
- `file_transfer_list`
- `file_transfer_start`
- `terminal_send_command`
- `terminal_read`
- `execution_get`
- `execution_cancel`
- `package_upgrade_start`
- `approval_get`
- `operation_get`
- `operation_wait`
- `operation_cancel`

For reliable daily commands, prefer `terminal_run`. It accepts one or more
commands, reuses or prepares a session in the same call, and returns only the
output produced by those commands. Known prompts complete through terminal
output events instead of service polling. The older session and terminal
tools remain available for compatibility.

```text
terminal_run(
  device_id="SIM-TERMINAL",
  commands=["display version", "dir flash:/"]
)
```

Use `terminal_execute_batch` for several ordinary commands. Device TUI sends
the next command as soon as the previous device prompt appears, so the whole
list needs only one MCP call.

Use `terminal_interact` for prompt-driven work. A plan can send text, wait for
prompt aliases, respond to intermediate prompts, and wait for connection
state. The approved local references `transfer.username` and
`transfer.password` resolve inside Device TUI; their values are not returned
to the MCP client or written to command results. Long plans return an
`execution_id` for `execution_get` and `execution_cancel`.

For package upgrades, call `package_upgrade_start` instead of manually
entering FTP or SFTP commands. The App holds the session for the full upgrade
and performs transfer login locally from the package-upgrade configuration.
Use `operation_wait` with the returned operation ID to wait for a change or
completion without repeated model-paced `operation_get` polling.

For transfer-only requests, call `file_transfer_list` and then
`file_transfer_start`. The source is a relative path returned from the App's
file-transfer share, and the caller supplies the device destination path.
Device TUI keeps the local root and credentials private, performs FTP/SFTP
locally, and reports success only after the destination file's exact byte size
matches. Existing destinations are refused unless `overwrite=true`. This
workflow does not select startup software or reboot; use
`package_upgrade_start` only for a complete package replacement.

Device TUI executes external tool calls immediately by default, including
configuration, reboot, file-changing, and package-upgrade actions. Risk
classification, audit logging, authorization, and the guarded package-upgrade
state machine remain active. Approval configured by the MCP client or Codex is
not changed by this setting.

Set `DEVICE_TUI_APPROVAL_MODE=required` before starting Device TUI to restore
the legacy in-app approval list and `批准` / `拒绝` buttons. In that mode,
guarded calls return `approval_required`; poll `approval_get` and retry the
original tool with the returned single-use `approval_token`.

The control server never listens on the LAN. Set
`DEVICE_TUI_APP_CONTROL=0` to disable it. Override the runtime and audit paths
with `DEVICE_TUI_CONTROL_STATE` and `DEVICE_TUI_CONTROL_AUDIT`.

## Project Layout

- `src/desktop_app.py`: PySide6 desktop GUI
- `src/device_mcp/server.py`: FastMCP entry point and tool registration
- `src/device_mcp/tools/`: domain-oriented MCP tools
- `src/device_mcp/gateway.py`: cached MCP-to-App gateway
- `src/device_mcp/client.py`: keep-alive App Control client
- `src/device_mcp/http_server.py`: local App Control HTTP server
- `src/device_mcp/service.py`: application-control coordinator
- `src/mcp_server.py` and `src/app_control*.py`: compatibility entry points
- `src/data.py`: device model and sample/generated data
- `src/repository.py`: sample and API-backed repositories
- `src/api_client.py`: HTTP API client used by GUI API mode
- `src/telnet_session.py`: Huawei/device Telnet session
- `src/linux_session.py`: Linux SSH session
- `src/session_protocol.py`: shared session callback/protocol types

## Development Check

```bash
python -m py_compile src\*.py
```
