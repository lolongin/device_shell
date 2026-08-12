# Device TUI Desktop v2 Architecture

## Status

Accepted for incremental implementation. The existing PySide6 entry point remains
available until the Electron client reaches functional parity.

## Boundaries

- Electron Main owns windows, native dialogs, updates, and the Python child process.
- Vue owns presentation state only. It never receives device credentials.
- Python owns inventory, sessions, commands, transfers, upgrades, AI execution,
  direct-execution policy, and audit records.
- Terminal connections belong to `SessionHub`; renderer tabs attach and detach.
- REST is used for queries and commands. WebSocket is used for terminal streams and
  other realtime events.
- AI tools call the controlled command layer, never protocol adapters directly.

## First Vertical Slice

1. Electron starts Python on a random loopback port with a per-launch token.
2. Vue loads real sample devices from `/api/v1/devices`.
3. Vue creates a simulated backend-owned terminal session.
4. xterm.js attaches over WebSocket and supports input, resize, reconnect, and replay.
5. Closing or remounting the renderer terminal does not close the Python session.

## Versioned Contracts

- HTTP routes live under `/api/v1`.
- WebSocket routes live under `/ws/v1`.
- Realtime events include `version`, `type`, `sessionId`, and `sequence`.
- The process startup handshake includes `apiVersion` and the random listening port.

## Security Baseline

- Python listens on `127.0.0.1` only.
- Electron generates a random token for every backend process.
- HTTP requests use a per-launch Bearer token held by Electron Main. Terminal and
  application-event WebSockets use short-lived, single-use, scope-bound tickets.
- Electron Renderer runs with `nodeIntegration: false`, `contextIsolation: true`, and
  `sandbox: true`.
- The preload bridge exposes a path/method/body-constrained API request channel,
  runtime discovery, backend-exit notification, and isolated credential-window
  actions. The bearer token and credential values remain in Electron Main.
- Automation rules execute inside Python. Manual terminal input cancels scheduled
  automation deterministically; secret-backed responses are filtered before terminal
  events, replay buffers, WebSockets, and session logs.
- File-transfer services and terminal plans execute inside Python. Service passwords
  stay in the OS vault, operation payloads contain no absolute source paths or
  credentials, and manual input releases an operation lease before it is delivered.
- AI plans, command execution, and redacted audit records are exposed by
  `AiApplicationService` under `/api/v1/ai/*`. AI/MCP requests do not require
  interactive user approval; their allowed operations remain constrained by the
  application-service tool boundary. MCP can opt into this API with
  `DEVICE_TUI_MCP_BACKEND_URL` and `DEVICE_TUI_MCP_BACKEND_TOKEN`; the legacy Qt
  app-control bridge remains a compatibility fallback during migration.
- The MCP compatibility facade is token-protected under `/api/v1/mcp/{tool}` and
  invokes application services plus the backend-owned terminal-plan executor directly.
  Application events use one-time event tickets and update the Vue workspace through
  a reconnecting WebSocket stream.
- In packaged builds, Electron Main launches the PyInstaller-produced backend from
  `process.resourcesPath/backend/device-tui-backend`. Source-mode launches still use
  `python -m src.desktop_backend.main`. Backend lifecycle diagnostics are written to
  the app user-data log directory, and unexpected runtime exits get a bounded restart
  attempt before being surfaced to the renderer. Main-process API calls read the
  current backend runtime at request time, and renderer WebSocket URLs refresh runtime
  discovery before opening, so a restarted backend does not strand new requests on an
  old loopback port.
- Production persistence lives under `DEVICE_TUI_DATA_DIR`: `device-tui.sqlite3`
  stores desktop metadata, `logs/` stores backend/session/audit logs, and
  `transfers/` is the default shared file root. Older SQLite schemas are backed up
  with SQLite's backup API before migration, and token-protected diagnostics expose
  schema/backup status for support without making the public health route leak paths.
  Session logs, AI/MCP audit JSONL, and Electron backend lifecycle logs have
  size-based rotation with environment-controlled retention for production installs.

## Migration Rule

New desktop capabilities are added behind Python application services first. The
legacy PySide6 UI may call the same services during migration, but no new business
logic should be added directly to widgets or window mixins.

The executable migration phases, parity matrix, non-regression rules, and validation
gates are tracked in [Desktop v2 Migration Task](../tasks/desktop-v2-migration.md).
