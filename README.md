# Network Device Desktop

Electron + Vue desktop application for device inventory, terminal sessions,
occupancy management, managed file transfer, package upgrades, and MCP-driven
automation. Python runs as a headless local backend; Electron is the only desktop
UI.

## Architecture

```text
Electron Main
  ├─ Vue renderer
  └─ supervised Python backend (loopback only)
       ├─ FastAPI + WebSocket API
       ├─ DeviceSourceService
       │    └─ sample / imported table / company website plugin
       ├─ application services
       └─ SSH / Telnet / simulated session hub
```

The renderer never connects directly to devices or company websites. Credentials,
cookies, backend bearer tokens, terminal sessions, and transfer services stay in
Electron Main or Python backend boundaries.

## Features

- Device search, filters, details, occupancy, and power actions
- Embedded xterm.js SSH, Telnet, serial-over-Telnet, and simulated terminals
- Saved servers, temporary connections, multi-session navigation, logs, and replay
- Command history and terminal automation with variables, loops, conditions, and dry runs
- Backend-managed FTP transfer and guarded package upgrade workflows
- Product-specific device sources: website-only, spreadsheet-only, or universal
- Local MCP tools for device, session, terminal, transfer, and upgrade operations

## Requirements

- Python 3.10+
- Node.js 20+
- Windows for installer packaging and the current release scripts

## Development Setup

Install the Python backend and desktop dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
Set-Location desktop
npm install
```

Run the desktop application:

```powershell
$env:DEVICE_TUI_PROJECT_ROOT = (Resolve-Path ..)
npm run dev
```

The Python backend can also be started independently for diagnostics:

```powershell
python -m device_tui.interfaces.desktop_api.main
```

## Build and Package

From `desktop/`:

```powershell
npm run build
npm run dist
```

`npm run dist` builds the Vue renderer, bundles the Python backend, and creates the
Windows installer. Release checks are available as:

```powershell
npm run smoke:release
npm run smoke:clean-runtime
npm run smoke:soak
npm run smoke:app-soak
```

For an overnight packaged-app soak:

```powershell
npm run soak:app
```

## Device Data Sources

Exactly one device source is active at a time. Records from different sources are
never merged. Product behavior is fixed by
`desktop/resources/product-profile.json`:

```json
{ "mode": "web", "source": "internal-site" }
```

The `web` profile exposes the website account/CID login flow and hides source
switching. The named plugin must be installed in the packaged backend.

```json
{ "mode": "spreadsheet", "source": "imported" }
```

The `spreadsheet` profile exposes Excel/CSV/TSV import and hides website login.

```json
{ "mode": "universal", "source": "" }
```

`universal` is intended for development and diagnostics. It exposes source
selection and plugin status. For local development,
`DEVICE_TUI_PRODUCT_MODE` and `DEVICE_TUI_PRODUCT_SOURCE` override the JSON file.

### Spreadsheet Import

The App accepts `.xlsx`, `.csv`, and `.tsv` files up to 20 MB, 20,000 data rows,
and 100 columns. UTF-8 (including BOM) and GB18030 CSV files are supported. A
device ID or device name column is required; common Chinese and English headers
are mapped automatically. Password-like columns are ignored and never stored.

Import first produces a validation preview. Confirmation replaces the previous
imported snapshot in one SQLite transaction. Parse or persistence failures leave
the existing snapshot unchanged. Existing terminal sessions must be closed before
replacing the active source.

### Company Website Integration

Company-specific integration is an external Python package registered through the
`device_tui.device_sources` entry-point group. End users do not install or select a
plugin in fixed product builds; developers include the implementation when building
the product.

Start with `integration-templates/company-device-source`. Its demo implementation
is runnable as-is; normally only
`binding.py::create_company_web_api()` is replaced with the proprietary website API
adapter. Login cookies remain in backend memory. Username and CID may be saved as
form defaults, while remembered passwords use the operating-system credential
vault.

Plugins import descriptors from `device_tui.plugin_api` and repository contracts
from `device_tui.plugin_api.repository`; internal package paths are not part of the
plugin contract.

See [Device Source Plugins](docs/device-source-plugins.md) and
[Company Device Source Template](integration-templates/company-device-source/README.md).

## Managed File Transfer

The transfer workspace starts a backend-owned FTP service on demand and lets
the user browse a selected shared directory. PC-to-device and device-to-PC plans
are generated per terminal session for Linux Shell or Huawei VRP syntax. The
service reports bytes, speed, ETA, cancellation, retry, and recent history.

The wildcard listen address is separate from the device-facing address. By
default, the backend selects the local IPv4 route used to reach the active device;
an explicit device-access IP can be configured for VPN and multi-adapter hosts.
Fixed service passwords use the operating-system credential vault. Per-task
credentials are memory-only.

## MCP and Automation

The desktop starts a loopback-only control API and writes runtime connection data
under `%LOCALAPPDATA%\DeviceTUI`. Install the Python package and configure the MCP
client to run:

```text
device-tui-mcp
```

The source-checkout equivalent is:

```powershell
python -m device_tui.interfaces.mcp.server
```

Common tools include `device_list`, `device_get`, `session_open`, `terminal_run`,
`terminal_interact`, `file_transfer_start`, `package_upgrade_start`,
`operation_wait`, and `operation_cancel`. Prefer `terminal_run` for ordinary
commands and `terminal_interact` for prompt-driven flows. Use the dedicated
transfer and upgrade tools so credentials and guarded operations stay inside the
backend.

## Security

- The backend listens only on loopback and uses an Electron-owned bearer token.
- Terminal WebSockets use short-lived one-time tickets.
- Saved secrets use the operating-system credential vault.
- Website cookies and one-time credentials do not enter Vue, Pinia, SQLite, or logs.
- Do not commit real device credentials; sample values are for local development.

## Project Layout

- `desktop/src/main/`: Electron lifecycle, backend supervision, and secure IPC
- `desktop/src/preload/`: narrow renderer bridge
- `desktop/src/renderer/`: Vue application and xterm.js workspace
- `device_tui/domain/`: device models and repository contracts
- `device_tui/application/`: UI-independent application services
- `device_tui/device_sources/`: active-source policy, imports, and plugin discovery
- `device_tui/infrastructure/`: persistence, transports, transfer servers, and audit logs
- `device_tui/interfaces/desktop_api/`: FastAPI and WebSocket desktop backend
- `device_tui/interfaces/mcp/`: MCP server, tools, and gateway
- `device_tui/plugin_api/`: stable public API for external device-source plugins

## Development Checks

```powershell
python -m pytest
python -m compileall -q src
Set-Location desktop
npm run typecheck
npm run build
```

The repository intentionally contains no PySide/PyQt desktop entry point. New UI
work belongs in the Electron/Vue application; reusable behavior belongs in the
Python application or backend layers.
