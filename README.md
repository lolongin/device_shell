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
The managed file-transfer workspace starts backend-owned FTP/SFTP services on
demand, browses and searches a user-selected shared directory, and queues
PC-to-device or device-to-PC terminal plans per session. It reports actual bytes,
speed, ETA, cancellation, retry, and persisted recent history while retaining
overwrite, space, source-change, and exact-byte verification gates. The service
supports auto-selected or explicit Linux Shell and Huawei VRP command adapters;
POSIX paths such as `/tmp/image.cc` select Linux semantics, while storage paths
such as `flash:/image.cc` select VRP semantics. The service stops after five idle
minutes. A wildcard listen address remains separate from the device-facing
address: by default Device TUI asks the operating-system route to the active
terminal's remote host for its source IPv4, with an explicit device-access IP
override for VPN and multi-adapter environments. The fixed manual-service password stays in the
operating-system credential vault; per-task credentials are memory-only and never
enter Vue or SQLite.
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

## Legacy PySide API Mode

The legacy `python src/desktop_app.py` entry point can still connect directly to
an HTTP backend. The Electron app does not register this compatibility adapter as
a selectable source; Electron website editions use `company-device-source`.

```powershell
$env:DEVICE_TUI_DATA_SOURCE = "api"
$env:DEVICE_TUI_API_BASE_URL = "http://127.0.0.1:8765"
$env:DEVICE_TUI_API_LOGIN_PATH = "/api/login"
$env:DEVICE_TUI_REFRESH_SECONDS = "30"
python src/desktop_app.py
```

Useful environment variables:

- `DEVICE_TUI_CURRENT_USER`: override current user in sample mode
- `DEVICE_TUI_DEFAULT_DATA_SOURCE`: legacy PySide default, either `sample` or `api`.
- `DEVICE_TUI_DATA_SOURCE`: force the legacy PySide startup source.
- `DEVICE_TUI_API_BASE_URL`: backend API base URL
- `DEVICE_TUI_API_TIMEOUT_SECONDS`: backend API timeout in seconds
- `DEVICE_TUI_API_LOGIN_PATH`: internal website login path, defaults to `/api/login`.
- `DEVICE_TUI_API_LOGOUT_PATH`: optional server-side logout path. The local cookie is
  always cleared when the user logs out.
- `DEVICE_TUI_API_LOGIN_USERNAME_FIELD`, `DEVICE_TUI_API_LOGIN_PASSWORD_FIELD`, and
  `DEVICE_TUI_API_LOGIN_CID_FIELD`: login JSON field names, defaulting to
  `username`, `password`, and `cid`.
- `DEVICE_TUI_API_LOGIN_FORMAT`: login body format, either `json` (default) or
  `form`. Both JSON and HTML login responses are accepted when a session cookie
  is returned.
- `DEVICE_TUI_REFRESH_SECONDS`: polling interval in API mode
- `DEVICE_TUI_SAMPLE_DEVICE_COUNT`: generated sample device count for GUI testing
- `DEVICE_TUI_TERMINAL_WIDGET`: terminal renderer, defaults to `xterm`.
  Use `canvas` for the previous PySide/pyte renderer or `legacy` for the
  previous `QPlainTextEdit` renderer.
- `DEVICE_TUI_AUTO_RESTORE_SESSIONS`: set to `1` to automatically reopen saved
  terminal sessions on startup.
- `DEVICE_TUI_XTERM_LOCAL_ECHO`: set to `1` only for endpoints which do not
  echo typed characters themselves. Leave it unset for normal SSH shells.

In an Electron website edition, the account entry opens an isolated login window.
The website plugin keeps the returned Cookie in memory and sends it with later
device requests. Username and CID are saved as form defaults; the password is only
persisted when **Remember login** is enabled, and then only in the operating-system
credential vault. The Cookie is never written to SQLite, renderer state, or logs.

## Device Data Sources and Batch Import

The Electron desktop uses exactly one active device source at a time: built-in
sample data, a website plugin, or an imported Excel/CSV snapshot. Records from
different sources are never merged. A product build fixes the user-facing workflow
through `desktop/resources/product-profile.json`: `web` exposes only website login,
`spreadsheet` exposes only table import, and `universal` keeps source switching and
plugin management for development. Existing terminal sessions must be closed before
switching a universal build or replacing an import so a session cannot silently
point at a different device row. `DEVICE_TUI_DATA_SOURCE` and
`DEVICE_TUI_DEFAULT_DATA_SOURCE` remain compatibility settings for the legacy
PySide entry point and unattended universal deployments.

Use **Device source > Excel / batch import > Import** in the device navigator. The
App supports `.xlsx`, `.csv`, and `.tsv` files up to 20 MB, 20,000 data rows, and
100 columns. UTF-8 (including BOM) and GB18030 CSV files are accepted. A device ID
or device name column is required; common Chinese and English headers for IP,
SSH/Telnet/serial ports, usernames, model, site, rack, version, and board ID are
mapped automatically. Legacy `.xls` files must first be saved as `.xlsx`.

Import is a two-step operation: the App first shows valid, skipped, and erroneous
row counts plus a safe preview, then requires explicit confirmation. A successful
commit replaces the previous imported snapshot in one SQLite transaction and makes
the imported source active. A failed parse or save leaves the previous snapshot
unchanged. Password-like columns are detected and ignored; imported passwords are
never stored in SQLite. Configure connection credentials when opening a terminal.

Company-specific device websites can be integrated without modifying the core App.
Copy `integration-templates/company-device-source` into the private repository and
register it through the `device_tui.device_sources` Entry Point group. It ships with
a complete demo website API and repository; later replace only
`binding.py::create_company_web_api()` with the proprietary API adapter. Universal
development builds expose installed sources under **Settings > Data sources and
plugins**; fixed product builds hide those developer controls. See
[Device Source Plugins](docs/device-source-plugins.md) for the contract and
PyInstaller packaging.

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
- `src/device_source_service.py`: product policy, active source, and plugin lifecycle
- `src/device_source_plugins.py`: built-in sources and Entry Point discovery
- `src/imported_devices.py`: spreadsheet-backed source and persistence boundary
- `src/product_profile.py`: developer-owned product source policy
- `src/repository.py`: sample and API-backed repositories
- `src/api_client.py`: HTTP client retained for legacy PySide API mode
- `src/telnet_session.py`: Huawei/device Telnet session
- `src/linux_session.py`: Linux SSH session
- `src/session_protocol.py`: shared session callback/protocol types

## Development Check

```bash
python -m py_compile src\*.py
```

## Product Data Source Profile

The packaged desktop app reads `desktop/resources/product-profile.json`. This
is a developer-owned product setting, so end users do not need to install,
choose, or configure data-source plugins.

Use one of these profiles before building the app:

```json
{ "mode": "web", "source": "internal-site" }
```

The web profile fixes the named website plugin, hides source switching and
plugin management, and leaves the account/CID login workflow visible.

```json
{ "mode": "spreadsheet", "source": "imported" }
```

The spreadsheet profile starts on the import workflow even before the first
file exists. The UI only offers selecting or updating an Excel, CSV, or TSV
device table.

```json
{ "mode": "universal", "source": "" }
```

Universal mode is intended for development and diagnostics. It keeps the
source selector and the plugin-management settings page. For local development,
`DEVICE_TUI_PRODUCT_MODE` and `DEVICE_TUI_PRODUCT_SOURCE` override the JSON
profile. A web build fails fast when its fixed plugin is missing, unavailable,
or does not implement the website-login workflow.

For a complete internal-website integration guide, including API field
mapping, Cookie/session ownership, reuse of an existing
`create_repository_from_env()` factory, tests, and release packaging, see
[`integration-templates/company-device-source/README.md`](integration-templates/company-device-source/README.md).
