# CLAUDE.md

Repository guidance for coding agents working on Device TUI.

## Build and Test

```powershell
python -m pip install -e .
python -m pytest
python -m compileall -q src
Set-Location desktop
npm install
npm run typecheck
npm run build
```

## Architecture

Electron + Vue is the sole desktop presentation layer. Electron Main supervises a
loopback-only FastAPI process and exposes a narrow preload API to the renderer.
Python owns device data, sessions, credentials, automation, transfers, upgrades,
persistence, and MCP integration.

```text
Vue renderer
  -> preload IPC
    -> Electron Main
      -> authenticated loopback HTTP/WebSocket
        -> device_tui/interfaces/desktop_api
          -> device_tui/application
            -> repositories, session hub, transfers, automation
```

Do not add PySide/PyQt desktop code or move privileged behavior into Vue.

### Device sources

`DeviceSourceService` is the single source boundary. `DeviceSourceRegistry`
provides built-in `sample` and `imported` sources and discovers external packages
through the `device_tui.device_sources` Entry Point group. A product profile fixes
website or spreadsheet behavior; universal mode is for development diagnostics.
Sources never merge.

### Session layer

`device_tui/application/sessions.py` coordinates the backend-owned Session Hub.
`HuaweiTelnetSession`, `LinuxSshSession`, and the simulated session implement the
transport behavior. The Vue renderer receives output through authenticated,
short-lived WebSocket tickets and renders it with xterm.js.

### Security boundary

Passwords use the operating-system credential vault. Website cookies and one-time
credentials stay in backend memory. Backend tokens stay in Electron Main. Never
put secrets in renderer state, SQLite, logs, terminal replay, or MCP results.

### Automation and transfers

Automation rules and execution live in Python application services. Managed
FTP/SFTP servers, device command generation, transfer verification, and package
upgrade gates also remain backend-owned. UI components should call the existing
API rather than reimplement these workflows.

### Persistence

Desktop workspace state and non-secret metadata are stored through the
infrastructure persistence layer. Keep schema migrations backward compatible and
test restart behavior.

## Key Files

- `desktop/src/main/`: Electron process and backend supervision
- `desktop/src/preload/`: renderer bridge
- `desktop/src/renderer/`: Vue workspace
- `device_tui/domain/`: device models and contracts
- `device_tui/application/`: application services
- `device_tui/device_sources/`: active source orchestration and plugin discovery
- `device_tui/infrastructure/`: persistence, transports, transfers, and audit adapters
- `device_tui/interfaces/desktop_api/`: HTTP/WebSocket routes and lifecycle
- `device_tui/interfaces/mcp/`: MCP integration
- `device_tui/plugin_api/`: external device-source contract

## Change Rules

- Put visual behavior in Vue/CSS and reusable domain behavior in Python services.
- Keep renderer IPC narrow, typed, and free of secrets.
- Add or update pytest coverage for backend changes and run desktop typecheck/build
  for renderer or Electron changes.
- Preserve unrelated working-tree changes.
