# Desktop Architecture

## Status

Implemented. Electron + Vue is the only desktop presentation layer. Python is a
headless backend and contains no Qt UI dependency.

## Process Model

```text
┌──────────────── Electron application ────────────────┐
│ Electron Main                                         │
│  - starts/stops Python                                │
│  - owns backend token                                 │
│  - owns privileged IPC and credential windows        │
│       │ narrow preload bridge                         │
│       ▼                                               │
│ Vue renderer + Pinia + xterm.js                       │
└───────────────────┬───────────────────────────────────┘
                    │ authenticated loopback HTTP/WS
                    ▼
┌──────────────── Python backend ───────────────────────┐
│ FastAPI routes / WebSocket tickets                    │
│ Application services                                  │
│ DeviceSourceService / Session Hub / Operations        │
│ Persistence / credential vault / network transports  │
└────────────────────────────────────────────────────────┘
```

Electron supervises the backend on a random loopback port. The renderer does not
receive the backend bearer token. Terminal connections use one-time WebSocket
tickets issued through the authenticated API.

## Layer Boundaries

The Python package has one root and explicit inward-facing layers:

```text
device_tui/
  domain/                  device models and repository contracts
  application/             use cases and orchestration
  device_sources/          source selection, imports, and plugins
  infrastructure/          persistence, transports, transfers, audit
  interfaces/desktop_api/  Electron-facing FastAPI/WebSocket adapter
  interfaces/mcp/          MCP adapter
  plugin_api/              stable external integration contract
```

The former `src` package root and compatibility facades are not part of the
runtime or distribution.

### Renderer

The renderer owns visual state, layout, filtering, dialogs, and xterm.js display.
It must not own device sockets, long-running operations, secrets, website cookies,
or authoritative persistence.

### Electron Main and Preload

Electron Main owns backend lifecycle, application windows, native dialogs, and
privileged IPC. Preload exposes a small typed surface; it must not proxy arbitrary
filesystem, process, or network access.

### Desktop Backend

The backend exposes application capabilities over loopback HTTP and WebSocket. It
normalizes errors, authorizes operations, publishes versioned events, and manages
startup/shutdown cleanup.

### Application Layer

Application services are UI-independent. They coordinate devices, credentials,
sessions, commands, automation, transfers, upgrades, events, and operations. They
must remain importable in test and service processes without Electron.

### Infrastructure

Infrastructure adapters implement SQLite persistence, credential-vault access,
entry-point discovery, filesystem boundaries, and network transports.

## Device Sources

`DeviceSourceService` is the sole active-source boundary:

```text
ProductProfile
  -> DeviceSourceService
       -> DeviceSourceRegistry
            -> sample
            -> imported spreadsheet snapshot
            -> external company website plugin
```

One source is active at a time; data is never merged. Fixed `web` and
`spreadsheet` products hide developer source controls. `universal` mode exists for
development and diagnostics. Website adapters are separate packages registered in
the `device_tui.device_sources` Entry Point group.

## Session and Terminal Flow

The backend resolves credentials and creates SSH, Telnet, serial-over-Telnet, or
simulated sessions in the Session Hub. Output is buffered for replay and forwarded
over WebSocket. The renderer owns xterm.js instances and sends input through the
same session API. Reconnect and close actions remain backend-authoritative.

## Long-running Operations

Transfers, upgrades, automation, and AI-driven terminal execution are represented
as backend operations with IDs, status, events, cancellation, and audit metadata.
The UI observes operation state instead of holding transport objects.

## Security Invariants

- Bind control APIs only to loopback.
- Keep bearer tokens in Electron Main.
- Use short-lived, single-use terminal tickets.
- Store remembered secrets in the operating-system credential vault.
- Keep website cookies and one-time credentials in backend memory.
- Exclude secrets from Vue/Pinia, SQLite, logs, replay, events, and MCP results.
- Validate all renderer-supplied paths and operation parameters at backend boundaries.

## Packaging

`desktop/package.json` is the desktop build authority. `npm run dist` builds the
renderer, bundles the Python backend, and creates the installer. Python console
scripts expose backend and MCP services only; there is no Python desktop entry
point.
