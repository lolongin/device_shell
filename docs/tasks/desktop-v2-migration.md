# Desktop v2 Migration Task

## Objective

Incrementally replace the mixed PySide6/WebEngine desktop presentation layer with
Electron + Vue 3 while keeping Python as the only owner of device inventory,
credentials, sessions, terminal automation, transfers, upgrades, AI execution,
approvals, and audit records.

The existing PySide6 entry point remains available until the Electron client passes
the complete parity and packaging gates in this document.

## Non-regression rules

1. Do not add new business rules to Qt widgets, Vue components, or Electron Main.
2. Extract a Python application-service boundary before migrating its UI.
3. Keep `device-tui` and `device-tui-desktop` working during the migration.
4. Add contract and regression tests before replacing an existing behavior.
5. Never expose a device password, backend bearer token, or secret value to Vue.
6. A phase is complete only when its focused tests, legacy regression tests, desktop
   typecheck/build, and relevant manual checks have passed.
7. Existing failures must be recorded explicitly; no new failure may be classified as
   pre-existing without reproducing it on the phase baseline.

## Recorded baseline

Recorded on 2026-08-09 before the application-service extraction.

| Check | Result |
| --- | --- |
| `pytest -q` | 552 passed, 3 failed, 1 warning |
| Desktop backend tests | 4 passed |
| Electron/Vue production build | Passed in the first vertical slice |
| Legacy PySide6 entry point | Preserved |

Known baseline failures:

- `test_terminal_command_suggestion_uses_history_and_defaults`: persisted command
  history returns `reset board` before the default `reboot` suggestion.
- `test_temporary_panel_uses_workspace_cards`: process/user desktop state contributes
  an additional temporary-device card.
- `test_web_pages_share_workspace_theme`: the existing auto-response editor does not
  contain the expected `danger remove-step` class.

Known baseline warning:

- `test_connection_failure_does_not_popup`: an existing mocked failure path leaves the
  local `connect` coroutine unawaited.

These records describe the baseline only. They are not acceptance criteria for the
final migration and should be fixed in an isolated compatibility task.

## Functional parity matrix

| Capability | Current owner | Target owner | Migration gate |
| --- | --- | --- | --- |
| Device inventory and filtering | Repository + Qt table mixin | Device application service + Vue | API and legacy views return equivalent device sets |
| Occupancy and power actions | Qt occupancy mixin | Device operation service | Authorization, error, and refresh behavior covered by tests |
| Temporary devices | Qt state + JSON | Connection profile service + SQLite/secret store | CRUD and validation parity; secrets absent from API/state |
| Saved servers and groups | Qt server mixin | Connection profile service | Group CRUD, duplicate detection, and open-session parity |
| Terminal sessions | Qt session mixin | SessionHub | SSH/Telnet/serial/simulated integration tests pass |
| Terminal replay and reconnect | Partial SessionHub | SessionHub | Sequence resume, gap notification, reconnect generation tests pass |
| Session logs | Qt desktop-state mixin | Session logging service | Input/output redaction and rotation parity |
| Command history and records | Qt mixins + JSON | Command service + persistent store | Ordering, suggestions, grouping, import/export parity |
| Auto-response rules | Qt session mixin | Terminal orchestration service | Trigger, delay, loop, target, cancel, and secret tests pass |
| Managed file transfer | Qt operation mixin + Python helpers | Operation service | Upload/download/precheck/cancel/progress parity |
| Package upgrade | Qt operation mixin + Python plan | Operation service | Plan, approval, cancellation, and reboot gates pass |
| AI device gateway | Qt AI mixin + Python gateway | AI application service | No Qt dependency; results and progress available through API |
| MCP tools | App-control-to-Qt bridge | Application services | Existing schemas remain compatible; no UI thread dependency |
| Layout, theme, shortcuts | Qt state | Vue/Pinia presentation state | User-visible behavior and accessibility checks pass |
| Packaging and updates | Developer runtime | Electron installer + bundled Python | Clean-machine install, update, rollback, and uninstall pass |

## Execution phases

### Phase 0 — Baseline and gates

Deliverables:

- This migration task and parity matrix.
- Recorded full-suite and Electron build baseline.
- A reusable validation command set for later phases.

Exit criteria:

- Baseline results are reproducible.
- Existing user files and unrelated worktree changes are identified and preserved.

### Phase 1 — Python application boundary

Deliverables:

- UI-independent device, session, operation, credential, settings, and event
  application interfaces.
- A versioned API error envelope and event envelope.
- Dependency injection from FastAPI rather than direct repository/session
  construction in route handlers.
- Compatibility adapters allowing the legacy client to keep using existing behavior.

Exit criteria:

- New application modules do not import PySide6.
- Existing desktop backend contracts remain compatible.
- Unit, backend, and legacy tests introduce no regression beyond the recorded baseline.

Phase result, 2026-08-09:

- Added UI-independent device, session, credential, settings, event, and error
  boundaries under `src/application`.
- FastAPI device and session routes now use the application services while keeping
  their existing paths and successful response payloads.
- Added a versioned application error envelope and `/ws/v1/events` lifecycle stream.
- Focused application/backend/protocol checks: 34 passed.
- Full regression: 560 passed, the same 3 baseline failures, and the same warning.
- Electron typecheck and production build passed.

### Phase 2 — Production SessionHub

Deliverables:

- Protocol adapter factory for simulated, SSH, Telnet, and serial-over-Telnet.
- Credential resolution inside Python.
- Explicit lifecycle state machine, terminal resize, reconnect generations, logging,
  replay limits, consumer-gap notification, and session leases.

Exit criteria:

- Fake-adapter tests cover success, authentication failure, timeout, disconnect,
  reconnect, resize, backpressure, and shutdown.
- Opt-in real-device smoke tests pass for supported protocols.
- No credential value appears in HTTP/WebSocket payloads or logs.

Phase result, 2026-08-09:

- Added uniform adapters for simulated, SSH, Telnet, and serial-over-Telnet using
  the existing Python protocol implementations.
- Session creation now resolves endpoints and credentials inside Python and returns a
  backend-owned session while connection progress continues asynchronously.
- Added connection timeout/failure state, PTY resize, reconnect generations, stale
  callback rejection, byte/event bounded replay, explicit replay/subscriber gaps,
  session leases, authentication-stream secret filtering, and background file logs.
- Focused SessionHub/application/backend/protocol checks: 29 passed.
- Full regression: 571 passed, the same 3 baseline failures, and the same warning.
- Electron typecheck and production build passed.
- Real-device smoke tests were not run because no explicit lab target was authorized;
  existing SSH and Telnet adapter unit suites passed.

### Phase 3 — Electron terminal parity

Deliverables:

- Real connection creation, multi-session navigation, reconnect/disconnect, logs,
  terminal search, font/layout preferences, keyboard shortcuts, and workspace restore.
- One-time WebSocket tickets and a constrained preload/API bridge.

Exit criteria:

- Electron end-to-end tests cover session create, input, resize, detach/attach, replay,
  reconnect, close, and backend restart.
- PySide6 terminal paths remain operational.

Phase result, 2026-08-09:

- Added SSH, Telnet, serial-over-Telnet, and simulated connection actions to Vue.
- Added multi-session state restoration, disconnect/reconnect, log-tail viewing,
  terminal search, persistent font size, resize, and keyboard shortcuts.
- Renderer REST access now goes through a path/method/body constrained Electron IPC
  handler; the backend bearer token remains in Electron Main.
- Terminal WebSockets use single-use, session-scoped, short-lived tickets. The legacy
  token query remains temporarily available for compatibility.
- Focused backend/security checks: 24 passed; Electron typecheck/build passed.
- Actual Electron + Python child-process smoke test created a simulated session,
  rendered terminal output, wrote a session log, and reported `tokenExposed=false`.
- Full regression: 575 passed, the same 3 baseline failures, and the same warning.

### Phase 4 — Device and connection management

Deliverables:

- Device filters/details, occupancy actions, temporary connections, saved servers,
  groups, and connection profiles in Vue.
- SQLite schema migrations and OS-backed secret storage.

Exit criteria:

- CRUD, validation, authorization, and migration tests pass.
- Existing user state can be imported without losing data.

Phase result, 2026-08-09:

- Device claim, release, toggle, and power-off actions now pass through the
  UI-independent DeviceService and versioned API contracts.
- Vue exposes claim/release/power actions and replaces the selected device snapshot
  with the authoritative repository response.
- Added Vue device keyword/domain/status/CPU/ownership filters, expanded details,
  temporary-connection CRUD, saved-server CRUD/search, standalone groups, duplicate
  confirmation, and active-temporary-session deletion protection.
- Connection metadata and groups now use a versioned SQLite schema. Existing
  `desktop_state.json` temporary devices, servers, groups, and passwords are imported
  once; the source file remains byte-for-byte unchanged.
- Saved credentials use the OS credential vault. Manual one-time passwords use a
  sandboxed, non-Vue Electron credential window and a dedicated Main-to-Python path;
  the ordinary renderer API rejects sensitive keys and credential endpoints.
- Focused application/backend/security checks: 31 passed; Electron typecheck and
  production build passed.
- A Windows Vault round-trip test passed and removed its random test credential.
- Actual Electron + Python smoke tests rendered imported groups/profiles, created a
  one-time-credential session, reported `tokenExposed=false`, and confirmed the
  SQLite profile table has no password/secret columns.
- Full regression: 591 passed, the same 3 baseline failures, and the same warning.

### Phase 5 — Commands and long-running operations

Deliverables:

- Command records/history, auto-response editor, managed file transfer, and package
  upgrade UI backed by application services.
- Unified operation progress, cancellation, retry, lease, and result contracts.

Exit criteria:

- Cancellation and manual-input precedence are deterministic.
- Sensitive values are redacted from history, logs, events, and audit records.
- Existing orchestration and upgrade test suites remain compatible.

Progress, 2026-08-09 — command, auto-response, managed-transfer, and package-upgrade slices:

- Added a UI-independent command service with SQLite-backed command tabs/history,
  legacy import, suggestions, direct send, broadcast, and credential-like command
  redaction. Vue now provides the persisted command workspace and send modes.
- Added a UI-independent asynchronous automation service and SQLite schema v3.
  SessionHub events drive output matching, connection/manual/delayed triggers,
  multi-step workflows, action flows, finite/infinite loops, cross-session targets,
  cancellation, and manual-input precedence without a Qt dependency.
- Added a Vue automation workspace for create/edit/enable/disable/run/stop flows.
  Existing advanced step/action payloads remain intact when basic fields are edited.
- Legacy auto-response rules import once without changing the source JSON.
  Credential-like responses move to the OS vault; their API representation is masked,
  and split remote echoes are redacted before replay, WebSocket delivery, and logs.
- Added a UI-independent managed-transfer service and unified operation records for
  progress, result, error, and cancellation metadata. Upload/download plans reuse the
  existing terminal orchestration engine behind SessionHub leases and perform path,
  overwrite, free-space, source-fingerprint, and exact-byte verification checks.
- Vue now provides a native-directory-backed FTP/SFTP service panel, shared-file
  browser, upload/download form, operation progress, and cancellation. Local service
  passwords are generated and stored in the OS vault; only `has_password` reaches
  the API. Legacy plaintext transfer passwords are imported once without changing
  the source file or writing the secret to SQLite.
- Manual or command input synchronously takes ownership from a managed operation,
  cancels its child plan and pending terminal writes, and releases the session lease
  before the takeover keystroke is evaluated. Disconnect, reconnect, session close,
  explicit cancel, and application shutdown also terminate associated operations.
- Clean-user-data Electron startup found and fixed a lossless-import edge case where
  duplicate legacy SSH endpoints stopped backend startup. Both legacy profiles are
  now retained; the duplicate guard still applies to new edits.
- Focused transfer/backend/session/command/automation checks: 42 passed, including a
  five-run concurrency repetition for manual-input takeover. Full regression:
  614 passed, the same 3 baseline failures, and the same warning. Python syntax
  checks, Electron typecheck, and the production build passed.
- Actual Electron + Python smoke created a simulated terminal, saved and manually ran
  `display version`, rendered `SimOS V1.0`, reported `tokenExposed=false`, and saved
  the automation-panel capture. A second clean-user-data smoke selected a real local
  file through the Vue transfer workspace, completed the simulated PC-to-device
  transfer, verified all 43 bytes, reported `transferSecretField=false`, and showed
  the live FTP endpoint without exposing its password.
- Added a backend-owned package-upgrade service and API. It accepts only a shared-
  directory-relative `.cc` package, probes startup state and master/standby storage,
  protects current/next/target packages during cleanup, verifies source fingerprints,
  reuses the managed FTP/SFTP terminal plan, checks master/standby package sizes,
  confirms the final startup entry, and supports cancellation, disconnect cleanup,
  manual-input takeover, and an explicit `waiting_approval` gate before reboot.
- Vue now exposes the upgrade workspace with package selection, dual-controller and
  cleanup policies, an approval-required reboot option, a staged progress pipeline,
  and safe operation history. A prompt-detection regression test prevents commands
  containing `#` (for example `slave#flash:/`) from being mistaken for shell prompts.
- Upgrade/API focused checks: 43 passed for package, terminal, transfer, and backend
  contracts. A real clean-user-data Electron smoke selected a `.cc` package, completed
  the simulated dual-controller workflow, approved reboot, reported
  `upgradeStatus=completed`, `upgradeVerified=true`, `upgradeRebootApproved=true`,
  and `upgradePanelVisible=true`; the final capture is
  `electron_phase5_upgrade_run_check.png`. The capture harness now has a bounded
  exit fallback for renderer polling timers.
- Phase 5 exit criteria are now met. The final full-suite boundary run is
  `616 passed, 3 baseline failures, 1 warning`; full-suite and clean-machine packaging results
  are still required by later phases; the next active phase is AI, approvals, audit,
  and MCP integration.

### Phase 6 — AI, approvals, audit, and MCP

Deliverables:

- AI Gateway and MCP adapters call application services directly.
- Realtime operation progress, structured results, and audit views. AI/MCP requests
  execute without an interactive user-approval step.
- Removal of the Qt-thread app-control dependency from the new execution path.

Exit criteria:

- Existing MCP tool names and request/response schemas remain compatible.
- AI and MCP integration tests run without constructing a Qt window.
- Direct execution, idempotency, lease, cancellation, and audit tests pass.

Progress, 2026-08-09 — first AI/MCP slice:

- Added `src/application/ai.py` as a Qt-free `AiApplicationService`. It generates
  deterministic plans, executes commands/batches through `DesktopApplication.commands`,
  stores structured results, executes AI/MCP requests without interactive approval, and
  writes redacted audit entries.
- Added `/api/v1/ai/plan`, command/batch execution, result, compatibility approval, and
  audit routes. The Vue AI workspace shows reviewable plans while AI requests execute
  directly, without exposing the backend bearer token or credentials.
- Added `DesktopApiClient` and an environment-gated `McpGateway` route
  (`DEVICE_TUI_MCP_BACKEND_URL` plus token). The legacy app-control client remains the
  default, so the PySide6 path is unchanged while MCP can be moved incrementally.
- Focused checks: `31 passed` across AI, MCP, backend, transfer, and upgrade suites;
  `npm run build` passes; a live uvicorn + `DesktopApiClient` smoke created a simulated
  session and executed `display version` successfully.
- Progress, 2026-08-09 — MCP and realtime completion:

  - Added the token-protected `/api/v1/mcp/{tool}` compatibility facade. It covers the
    legacy device, session, terminal, transfer, package-upgrade, operation, and AI tool
    names through `DesktopApplication`, `SessionHub`, and the real terminal-plan executor;
    no Qt window or UI-thread dispatcher is involved.
  - `DesktopApiClient` now implements that full tool surface, while the legacy
    App-Control client remains functional. `ai_list_skills` is available on both paths.
  - Added controlled skill discovery/execution plus a safe `version_check` bundled skill.
    MCP calls are redacted in the audit log and respect idempotency keys.
  - Vue now holds a ticket-authenticated application-events WebSocket, reconnects after
    transport loss, and applies session/operation/AI-result events to the workspace state.
  - Focused MCP/backend/AI checks: `61 passed`; Electron typecheck/build passes; a live
    uvicorn + `DesktopApiClient` smoke listed devices, opened a session, ran
    `display version`, and discovered skills.
  - Full-suite boundary: `624 passed, 3 baseline failures, 1 warning`. The remaining
    failures and warning are unchanged legacy baseline items listed in Phase 0.

- Phase 6 exit criteria are met. The next active phase is distribution and reliability.

### Phase 7 — Distribution and reliability

Deliverables:

- Signed Electron installer with bundled Python backend and pinned dependencies.
- Graceful shutdown, bounded restart policy, crash diagnostics, schema migration,
  update/rollback, CSP, origin validation, and production logging.

Exit criteria:

- Clean Windows machine requires neither Python nor Node.js.
- Install, launch, upgrade, rollback, and uninstall smoke tests pass.
- Multi-session load and soak targets are met.

Progress, 2026-08-09 - distribution/runtime foundation:

- Added Electron distribution scripts and `electron-builder` configuration for a
  Windows NSIS package that includes the PyInstaller backend as an extra resource.
- Added `src.desktop_backend.frozen_main` and a PowerShell PyInstaller build script
  that produces `desktop/resources/backend/device-tui-backend/device-tui-backend.exe`.
- Electron Main now keeps source-mode startup unchanged, but packaged builds launch
  the bundled backend from `process.resourcesPath/backend/device-tui-backend`. The
  path can be overridden with `DEVICE_TUI_BACKEND_EXECUTABLE` for local packaging
  smoke tests.
- Backend lifecycle diagnostics are written to `backend.log` under Electron's
  user-data log directory. Unexpected exits after a successful startup are reported
  to Vue and get a bounded in-process restart attempt.
- Added packaging contract tests for the Python extra, Electron scripts, builder
  resource inclusion, PyInstaller output path, packaged launcher path, and frozen
  backend entrypoint.
- Validation completed:
  - `pytest -q tests/test_packaging.py tests/test_desktop_mcp_backend.py
    tests/test_ai_application_backend.py tests/test_desktop_backend.py
    tests/test_mcp_gateway.py tests/test_mcp_server.py` -> `37 passed`.
  - `python -m compileall -q src` passed.
  - `npm run build` passed.
  - `npm run build:backend` produced
    `desktop/resources/backend/device-tui-backend/device-tui-backend.exe`.
  - A bundled-backend smoke started the PyInstaller executable with a temporary
    data directory and received the startup ready handshake on `127.0.0.1`.
  - `npx electron-builder --config electron-builder.yml --dir --publish never`
    produced `desktop/release/win-unpacked` containing `Device TUI.exe`,
    `resources/app.asar`, and the bundled backend executable.
  - `npx electron-builder --config electron-builder.yml --publish never` produced
    `desktop/release/Device TUI Setup 0.1.0.exe` plus the installer blockmap after
    clearing an incomplete local NSIS cache.
  - `npm run dist` passed end-to-end, rebuilding Vue/Electron, rebuilding the
    PyInstaller backend, and producing the NSIS installer in one command.
  - A packaged `win-unpacked` clean-user-data smoke launched `Device TUI.exe`, opened
    a simulated terminal, confirmed the preload bridge exists, confirmed the backend
    token is not exposed to renderer runtime config, captured a screenshot, and wrote
    a bundled-backend startup log.
  - A packaged recovery smoke killed the bundled backend child process after startup;
    Electron Main logged the unexpected exit, restarted the backend after 500ms, and
    observed a second ready handshake on a new loopback port.
  - A real NSIS smoke installed `Device TUI Setup 0.1.0.exe` into a temporary
    directory, launched the installed app with clean user data, confirmed bundled
    backend startup and screenshot capture, then ran the generated silent uninstaller.
  - Added production persistence preparation for `DEVICE_TUI_DATA_DIR`: before
    `device-tui.sqlite3` is migrated, an older schema is copied with SQLite's backup
    API into `backups/`; the backend records schema-before, schema-after, target
    schema, and backup path in app state.
  - Added token-protected `/api/v1/diagnostics` so packaged builds can report
    persistence schema/backup status and legacy import counts without exposing
    credentials through renderer runtime config or public health checks.
  - Fixed the profile-store migration helper so reopening the desktop SQLite store
    no longer downgrades `PRAGMA user_version` from the desktop schema version back
    to the profile-only schema version.
  - Persistence checks: `pytest -q tests/test_desktop_persistence.py
    tests/test_desktop_backend.py::test_health_does_not_require_token` -> `4 passed`.
  - A bundled-backend diagnostics smoke started the PyInstaller executable against a
    temporary v1 SQLite data directory, called `/api/v1/diagnostics`, and confirmed
    `schema_version_before=1`, `schema_version_after=3`, and `backup_created=true`.
  - Added production log retention controls:
    `DEVICE_TUI_SESSION_LOG_MAX_BYTES/BACKUPS`,
    `DEVICE_TUI_AUDIT_LOG_MAX_BYTES/BACKUPS`, and
    `DEVICE_TUI_BACKEND_LOG_MAX_BYTES/BACKUPS`. Session logs, AI/MCP audit JSONL,
    and Electron backend lifecycle logs now rotate instead of growing without bound.
    `/api/v1/diagnostics` reports the Python-side session/audit log policy.
  - Added a multi-session simulated load sentinel that opens 12 backend-owned
    simulated sessions, dispatches commands through the migrated command API, verifies
    session logs, and closes all sessions.
  - Log/load checks: `pytest -q tests/test_desktop_backend.py::test_multi_session_simulated_load_sentinel
    tests/test_session_logging.py tests/test_app_control.py::test_audit_log_rotates_large_jsonl_file
    tests/test_desktop_persistence.py tests/test_packaging.py` -> `14 passed`.
  - Added `desktop/scripts/validate-release.ps1` and `npm run smoke:release`.
    The script silently installs a previous installer, launches the installed app
    with clean user data, verifies screenshot capture, bundled-backend startup, and
    `tokenExposed=false`, installs the current installer over the same directory,
    verifies the upgraded app, optionally reinstalls `-PreviousInstaller` as a
    rollback rehearsal, then runs the silent uninstaller.
  - Release smoke: `npm run smoke:release` passed against
    `desktop/release/Device TUI Setup 0.1.0.exe`, using the current installer as the
    same-version upgrade sentinel.
  - Added `desktop/scripts/soak-backend.ps1` and `npm run smoke:soak` to start the
    packaged PyInstaller backend from `desktop/release/win-unpacked`, open multiple
    simulated sessions through the public HTTP API, dispatch repeated commands,
    verify terminal logs, query diagnostics, and cleanly close sessions.
  - Packaged backend soak: `npm run smoke:soak` passed with 12 simulated sessions,
    3 command cycles, schema version 3, and the configured session-log rotation
    policy reported by diagnostics.
  - Added `desktop/scripts/soak-packaged-app.ps1`, `npm run smoke:app-soak`, and
    `npm run soak:app`.
    This starts the packaged Electron app from `release/win-unpacked`, opens a
    simulated terminal through the renderer, confirms the runtime token remains
    hidden, deliberately crashes the managed Python backend, verifies Electron Main
    restarts it on a new loopback port, and confirms renderer bridge requests still
    succeed after recovery. The same script supports `-Cycles`, `-DurationMinutes`,
    and `-PauseSeconds`; `smoke:app-soak` keeps a single fast cycle while
    `soak:app` runs the packaged-app recovery loop for 8 hours by default.
  - Packaged app soak: `npm run smoke:app-soak` passed against the regenerated
    `release/win-unpacked` build, with two backend ready handshakes observed.
  - Packaged app soak loop proof: `powershell -ExecutionPolicy Bypass -File
    scripts/soak-packaged-app.ps1 -Cycles 2` passed with `CyclesCompleted=2` and
    `ReadyCount=4`; the default `npm run smoke:app-soak` still passes with one
    cycle and two ready handshakes.
  - Regenerated release after the packaged-app recovery probe: `npm run dist`
    passed, `npm run smoke:release` passed against
    `desktop/release/Device TUI Setup 0.1.0.exe`, and `npm run smoke:soak`
    passed again with 12 simulated sessions and 3 command cycles.
  - Added `desktop/scripts/validate-clean-runtime.ps1` and
    `npm run smoke:clean-runtime`. The script installs the NSIS package, then
    launches the installed app with Python/Node/project-root environment variables
    removed and PATH reduced to Windows system directories. It verifies screenshot
    capture, hidden renderer token, bundled-backend startup from
    `resources/backend/device-tui-backend`, and no fallback to
    `python -m src.desktop_backend.main`.
  - Clean-runtime smoke: `npm run smoke:clean-runtime` passed against
    `desktop/release/Device TUI Setup 0.1.0.exe`.
  - Fixed the three previously known legacy baseline failures covering terminal
    command suggestions, temporary-device card refresh, and shared web workspace
    theme compatibility. Targeted regression checks for those cases now pass.
  - Added a cutover contract test that keeps `src/desktop_backend`,
    `src/application`, `src/infrastructure`, `src/device_mcp`, and shared terminal
    core modules free of PySide/PyQt imports.
  - Full Python regression baseline after legacy fixes and the cutover contract:
    `pytest -q` -> `643 passed`.
- Builder hardening notes:
  - `electronDist: node_modules/electron/dist` is required so builder reuses the
    locally installed Electron runtime instead of silently waiting while preparing
    one.
  - `publish` is intentionally passed as a CLI option; `publish: never` in config
    is interpreted as an invalid publish provider by electron-builder 26.
  - Current iterative packaging uses `compression: store` to keep large Python-bundle
    packaging fast; release builds can switch to a stronger compression setting after
    size/performance tradeoffs are accepted.
  - If NSIS hangs after `target=nsis`, inspect
    `%LOCALAPPDATA%/electron-builder/Cache/nsis-3.0.4.1`; a stale one-byte cache
    directory and `.lock` file can block progress until that exact cache entry is
    removed.

Remaining Phase 7 work:

- Repeat installer smoke on a true clean Windows VM or CI image without Python/Node.js
  to prove machine-level dependency independence. The local clean-runtime proxy gate
  is now passing as `npm run smoke:clean-runtime`, but it is not a full VM substitute.
- Run `npm run smoke:release` with a real older `-PreviousInstaller` artifact to
  prove cross-version upgrade and rollback. The same-version upgrade sentinel is in
  place and passing.
- Run an extended overnight/CI packaged-app soak before final cutover. The local
  packaged-backend and packaged-Electron recovery gates are scripted as
  `npm run smoke:soak` and `npm run smoke:app-soak`; the long packaged-app gate is
  scripted as `npm run soak:app` but still needs an overnight/CI run recorded.

### Current priority — functional and UX parity hardening

The product priority is currently functional parity, not release publication. Phase 7
installer, VM, rollback, and long-soak evidence can continue later, but final cutover
must wait until the Electron client is not visibly weaker than the PySide6 client in
daily device-operation flows.

Hardening goal:

- Preserve the Electron + Vue + Python backend architecture while keeping the legacy
  PySide6 entry point available as the reference behavior.
- Fix user-visible regressions before packaging work: device list fidelity, theme
  switching, device details, connection actions, terminal tabs, logs, command records,
  filtering/search, shortcuts, realtime status, and error/notice feedback.
- Add a focused parity test or build/typecheck gate for every fixed regression.
- Keep credentials inside Python/Electron Main boundaries. When PySide6 copied fields
  that the new renderer intentionally cannot receive, the Electron UI should expose a
  safe equivalent rather than leaking secrets to Vue.

Progress, 2026-08-09 — visible parity repairs:

- Restored the Electron device list to a legacy-table-like presentation with sequence,
  device, board type, CPU, slot, and status columns, backed by device snapshot fields
  from the Python application service.
- Restored renderer theme switching and made the terminal follow the active light/dark
  theme.
- Restored session tab close-current, close-other, and close-all actions; terminal
  reconnect/disconnect feedback; command find/replace feedback; terminal log copying;
  and automation runtime status notices.
- Restored device-table context menu parity for mouse right-click plus keyboard
  `ContextMenu` / `Shift+F10`. The Electron menu now supports copying the device row,
  visible SSH/Telnet/serial fields, safe connection summary, claim/release, power-off,
  and SSH/Telnet/serial open actions using backend-provided capability flags.
- Restored session-tab context menu parity for mouse right-click plus keyboard
  `ContextMenu` / `Shift+F10`. The Electron tab menu now supports closing the current,
  left-side, right-side, other, or all tabs, plus locating the tab's device and opening
  SSH/Telnet/serial sessions from the same device capability rules.
- Restored temporary-connection and saved-server list context menu parity for mouse
  right-click plus keyboard `ContextMenu` / `Shift+F10`. The Electron profile menu now
  supports opening available protocols, copying a secret-free connection summary,
  managing OS-vault credentials, editing, deleting, and moving saved servers between
  groups without exposing passwords to Vue.
- Restored terminal-area context menu parity for mouse right-click plus keyboard
  `ContextMenu` / `Shift+F10`. The Electron xterm surface now supports copying the
  current selection, copying the visible buffer, pasting through the normal terminal
  input path, clearing the local screen, opening search/logs, and disconnect/reconnect
  actions.
- Restored device-inspector copy parity. The Electron details panel now exposes
  per-field copy buttons for visible status, owner, ID, board, domain, location, CPU,
  version, SSH, Telnet, and serial fields, plus right-click / `ContextMenu` /
  `Shift+F10` access to the same safe device operation menu used by the device table.
- Restored command-workspace context shortcut parity. Command tabs now support
  right-click and `ContextMenu` / `Shift+F10` rename, create, and delete actions, while
  the command editor menu supports copying the selected/current command, pasting,
  selecting the current line, send, broadcast, find/replace, and clearing the current
  tab without changing the existing save/send service path.
- Focused checks for this parity slice: `pytest -q tests\test_electron_ui_parity.py`
  -> `18 passed`; `npm run build` -> passed.
- Progress, 2026-08-10 — live UI parity smoke gate:

  - Added `desktop/scripts/smoke-ui-parity.mjs` and `npm run smoke:ui-parity`.
    The gate builds Electron/Vue, launches the source-mode Electron app with a clean
    task-scoped user-data directory, starts the Python backend through Electron Main,
    opens a simulated terminal, and verifies the visible parity surface through the
    renderer: legacy device table columns, populated device rows, selected-device
    details/copy controls, theme toggle, device context menu, session-tab context menu,
    terminal context menu, command-tab context menu, command-editor context menu, and
    the profile context menu when seeded profile rows exist.
  - The smoke also keeps the security invariant in the same run by requiring
    `tokenExposed=false`; the renderer still receives only the constrained preload
    runtime config, not the backend bearer token.
  - Validation completed: `npm run smoke:ui-parity` -> passed, with capture written to
    `desktop/out/smoke/ui-parity.png`; `pytest -q tests\test_electron_ui_parity.py`
    -> `19 passed`.

- Progress, 2026-08-11 — device-row identity, shortcut, and terminal-state hardening:

  - Fixed the device summary to count the currently filtered rows, including idle,
    occupied, pipeline, and other states, matching the legacy table statistics.
  - Added credential-free `board_id` and stable `row_id` fields to the application and
    desktop API contracts. The Vue table now uses `row_id` for rendering and selection
    while connection and device-operation requests continue to use the original
    `device.id`. This fixes the four `XTN-NJ-018` board rows that legitimately share a
    chassis ID: filtering no longer leaves duplicate DOM rows, keyboard selection can
    distinguish boards, and the legacy sequence column shows the actual board ID.
  - Preserved existing renderer selection state through a legacy `selectedDeviceId`
    migration path and made chassis-scoped device actions refresh the dynamic state of
    every displayed board without overwriting board-specific presentation fields.
  - Restored a legacy-sized device navigator and responsive six-column grid. The live
    gate now requires all six columns to fit the default desktop viewport without a
    horizontal scrollbar (`clientWidth=490`, `scrollWidth=490`).
  - Scoped terminal shortcuts to the focused terminal pane. Command-editor `Ctrl+F`
    now opens only command find/replace, `Esc` closes it and restores editor focus, and
    the visible titles expose `Ctrl+F` and `Ctrl+Shift+R` shortcuts.
  - Added localized terminal connection-state labels and distinct connecting,
    detached, failed, and disconnected indicators. WebSocket-ticket/channel failures
    and log-read failures now stay inline and actionable instead of becoming unhandled
    renderer errors.
  - Expanded the real Electron parity smoke to cover keyword/domain/status/CPU filters,
    clearing filters, disabled connection reasons, scoped command shortcuts, simulated
    disconnect/reconnect feedback, command dispatch/history, and session-log viewing.
  - Added a smoke-only local protocol-failure switch that leaves the normal sample
    ports unchanged. The real renderer connection buttons now exercise deterministic
    SSH failure and retry, Telnet failure, and claim-then-serial failure through the
    production SessionHub adapters. Every path must show a localized failed state,
    the inline protocol error, and an enabled retry action.
  - Found and fixed a REST/realtime race where `session.created` and the create-session
    response could append the same session twice. Session state now uses sequence-aware
    ID upserts. A four-session renderer reload gate proves the session count, active
    tab, selected board row, theme, and renderer token boundary all restore correctly.
  - Completed the backend-exit feedback loop. Electron Main now sends a recovered event
    after its bounded Python restart succeeds; Vue pauses realtime subscription during
    downtime, reloads the workspace, clears the stale failure banner, shows a recovery
    notice, and resumes events. The smoke kills its own Python child and verifies the
    banner transition, changed backend runtime, refreshed 20-row inventory, and HTTP
    status 200.
  - Added dark and light rendered captures. Visual inspection found that the command
    header/action column and several success/error labels still used dark-theme literals;
    they now use theme surfaces and light-mode contrast overrides. The gate writes
    `desktop/out/smoke/ui-parity.png` and
    `desktop/out/smoke/ui-parity-light.png`.
  - The gate passes with `tokenExposed=false` before and after renderer reload.
  - Audited command-record ordering/import/export against the legacy client. The old
    PySide command workspace has no user-facing import, export, reorder, move-up, or
    move-down action. The required legacy behavior is the one-time state import, which
    already preserves group order, current group, Enter mode, history, source-file
    immutability, and secret redaction under `test_command_application.py`.
  - Validation completed: `pytest -q` -> `669 passed`; focused device, command,
    SessionHub, backend, and UI checks -> passed;
    `pytest -q tests\test_electron_ui_parity.py` -> `22 passed`;
    `npm run build` -> passed; `npm run smoke:ui-parity` -> passed.

- Progress, 2026-08-11 — settings, session-layout, and complete log-menu parity:

  - Replaced the inactive Settings rail button with a keyboard-focusable settings
    drawer. It now controls the persisted dark/light theme, native always-on-top
    state, shared terminal font size (`9`–`28` px), and the legacy top/side session-tab
    layout. Side layout uses a compact vertical session rail, supports the legacy
    remembered/default-collapsed state, and survives renderer reload together with the
    active tab and session count. The collapsed 42 px rail keeps one status marker per
    session, active-state styling, accessible tab labels/tooltips, keyboard context
    menus, and an explicit expand control instead of hiding sessions completely.
  - Replaced the inactive Help rail button with an accessible shortcut and security-
    boundary reference instead of leaving a clickable placeholder.
  - Restored the legacy current-session automation shortcut. The terminal toolbar and
    keyboard-accessible context menu now open the existing Python-backed automation
    workspace while preserving the active session as the run/stop target; automation
    rules and execution logic remain outside the Vue component.
  - Restored the complete legacy log menu surface: create a fresh current-session log,
    open the actual current log through Electron Main, view/copy the safe log tail,
    open the managed directory, save a safe copy, change the active log directory,
    and set the per-file rotation size from `1` to `1024` MB.
  - Log directory and rotation settings now use the Python application settings
    boundary with SQLite `app_meta` persistence. Existing PySide `log_directory` and
    `log_rotate_size_mb` values import once without modifying the legacy JSON file.
  - `FileSessionLogSink` serializes reconfiguration on its single writer thread. It
    closes and flushes active handles, rolls back a partial move on failure, migrates
    current active-session files, reopens handles under the new root, and keeps
    `read_tail()` consistent. Manual new-log actions archive the previous file before
    continuing with a fresh current log.
  - Native directory selection and file/directory opening remain Electron Main-owned.
    Vue receives neither the backend bearer token nor authority to open an arbitrary
    current-log path; Main resolves that path from the authenticated Python API.
  - The live smoke now changes the log root and rotation size, verifies persistence
    after a deliberate backend crash/restart, exercises manual new-log and native
    current-log opening, switches to side tabs, reloads four sessions, and requires the
    side layout and its collapsed state to restore. It also captures
    `desktop/out/smoke/ui-parity-settings.png` for visual review.
  - Validation completed: focused logging/backend/persistence/UI/security checks ->
    `63 passed`; `pytest -q` -> `680 passed`; `npm run build` -> passed;
    `npm run smoke:ui-parity` -> passed with `uiParityPassed=true`,
    `uiRestorePassed=true`, `backendRecoveryPassed=true`, and `tokenExposed=false`.

- Progress, 2026-08-11 — dedicated simulated-device inventory parity:

  - Moved the canonical `SIM-TERMINAL` definition out of the Qt session mixin into
    the UI-independent Python application layer. Both PySide and Electron now use the
    same device identity and presentation fields.
  - `DeviceService` reserves the simulator id, removes repository duplicates, and
    appends exactly one canonical simulator after repository rows. The 20-device sample
    inventory therefore exposes the same 21 navigation rows as the legacy client.
  - The safe API snapshot marks the row `is_simulated=true`, exposes no SSH, Telnet, or
    serial endpoint, and disables claim, release, and power-off capabilities. The
    credential boundary accepts only a credential-free `simulated` target for the
    reserved id and rejects SSH, Telnet, and serial requests server-side.
  - Renderer disabled reasons now explicitly identify unsupported simulator protocols
    and device operations. The live smoke selects the simulator row and requires one
    enabled simulated-session action, three disabled network/serial actions, and
    disabled claim/power actions with visible reasons.
  - Validation completed: focused application/backend/UI/security/PySide compatibility
    checks -> `70 passed`; `npm run build` -> passed; `npm run smoke:ui-parity` -> passed
    with 21 visible rows, `uiParityPassed=true`, `uiRestorePassed=true`,
    `backendRecoveryPassed=true`, and `tokenExposed=false`; latest complete Python run ->
    `689 passed`.

### Functional and UX parity audit, reopened 2026-08-11

The earlier all-`Pass` table only proved the paths implemented by the Electron smoke.
It did not inventory the complete PySide feature surface and therefore must not be
used as cutover evidence. Status now means:

- `Verified`: source mapping plus direct regression/runtime evidence exists.
- `Partial`: the primary path exists but a legacy interaction or fallback is absent.
- `Missing`: no Electron renderer implementation was found.
- `Security-adjusted`: behavior intentionally changes to keep credentials and the
  backend bearer token outside Vue; an equivalent native/Python-owned workflow is
  still required.
- `Needs lab proof`: deterministic failure paths pass, but authorized hardware success
  has not been exercised.

| Capability | Current status | Evidence or remaining gap | Operator sign-off |
| --- | --- | --- | --- |
| Device list presentation | Verified | Safe API exposes the six legacy columns, 21 rows, unique row IDs, board rows, and exactly one `SIM-TERMINAL`; live smoke covers selection and counts | [ ] Confirm density and column sizing |
| Filtering, search, and “我的” semantics | Verified | Keyword/domain/status/CPU/clear and hidden-field queries are covered; owned count uses unique devices while the filter retains board rows | [ ] Confirm production queries |
| Device details and copying | Verified (security-adjusted) | Visible metadata and endpoint copy controls exist; credentials intentionally remain in Python/native workflows and password reveal/copy does not return to Vue | [ ] Accept the native/Python credential workflow |
| Theme switching | Verified | Renderer and xterm persist and switch together; dark/light captures exist | [ ] Accept both captures and contrast |
| Occupancy and device actions | Verified | Claim/release/power capability flags, disabled reasons, state refresh, and simulator rejection are covered | [ ] Confirm operator wording |
| Canonical simulated terminal | Verified | UI always targets the application-owned `SIM-TERMINAL`, even when an ordinary row is selected; smoke must assert the created session device ID | [ ] Confirm terminal interaction feel |
| SSH, Telnet, and serial connection lifecycle | Not required (product decision) | Deterministic failure/retry paths and protocol-adapter success tests remain required; authorized hardware success evidence was removed from this parity target by product decision on 2026-08-12 | [x] Hardware proof is not a completion gate |
| Flat multi-session lifecycle and reload recovery | Verified | SessionHub ownership, REST/event deduplication, close/reconnect, active session restore, and renderer reload are covered | [ ] Confirm day-to-day switching feel |
| Terminal split panes and tab drag/drop | Verified | Electron supports left/right/top/bottom split, global and per-pane tab drag/drop, keyboard-accessible context actions, adjustable split ratio, persisted layout, and two live `TerminalPane` instances without duplicating SessionHub sessions | [ ] Confirm preferred pane density on production-sized windows |
| Hierarchical session manager | Verified | Electron right-side mode groups existing SessionHub sessions by device, supports device/session search, per-group and expand/collapse-all memory, device/session context actions, 200–480 px persisted resize, a 42 px accessible strip, drag/drop, responsive drawer behavior, and reload recovery without duplicating backend sessions | [ ] Confirm hierarchy and compact mode |
| Terminal quick toolbar and persistent quick-send buttons | Verified | Python persists definitions, sends through SessionHub, keeps sensitive values in the OS credential store, and exposes only masks to Vue; Electron supports add/edit/delete/send and persisted hide/restore, with live simulated-session smoke coverage | [ ] Confirm quick-send workflow |
| Basic automatic response | Verified | Create/update/enable/delete/run/stop and simple trigger/response fields are Python-backed and smoke-covered | [ ] Confirm basic rule behavior |
| Advanced automatic response editor | Verified | Vue edits basic responses, multi-step waits/responses/targets/delays, and recursive send/wait/loop/condition/exit action flows; Python remains the execution owner and preserves masked secret structures | [ ] Exercise representative advanced rules |
| Session/device context actions | Verified | Close-left/right/others/all, locate, protocol, terminal clipboard/search/log/automation, four-direction split, and per-device hierarchical actions are implemented and smoke-covered | [ ] Confirm menu grouping |
| Terminal logs | Verified | Content/copy/export, native open, new-log archive, root migration, rotation, legacy import, and restart persistence are covered | [ ] Confirm operational workflow |
| Command records and history | Verified | Groups, history, suggestions, find/replace, Enter mode, broadcast, collapse, redaction, pointer/keyboard height resize, window clamping, and height persistence are covered | [ ] Confirm preferred default height |
| Temporary connection profiles | Verified (security-adjusted) | CRUD and SSH/Telnet/serial open paths exist; passwords are entered or managed through Electron Main and the OS credential store rather than Vue | [ ] Accept credential UX |
| Saved servers and groups | Verified | CRUD, empty-group creation, search, move-to-group, copy, SSH open, keyboard-accessible group expand/collapse, search-time reveal, and collapse memory across reload are covered | [ ] Confirm group navigation |
| Local/managed file transfer | Verified | FTP/SFTP settings, lifecycle, shared files, upload/download, progress, cancel, verification, bounded realtime service log, copy/clear controls, and a password-free device client command hint are implemented and smoke-covered | [ ] Exercise real file service clients |
| Package upgrade | Verified | Python-managed precheck/cleanup/download/verify/sync/startup/reboot flow and the read-terminal/generate/edit/copy/send-script fallback are implemented; manual scripts expose only a password placeholder and Python resolves it at send time | [ ] Exercise a representative production package |
| AI plan generation | Verified | The renderer calls the Python planner and shows actions/warnings | [ ] Confirm plan presentation |
| AI plan/tool/skill execution | Not required (product decision) | Keep the Python AI/MCP command, batch, result, audit, skill, and tool services non-interactive and API-accessible; no additional Electron renderer surface is required | [x] Removed from UI parity scope by product decision on 2026-08-11 |
| Realtime notices and abnormal recovery | Verified | Session/operation/automation events, backend-exit banner, bounded restart, inventory reload, and subscription recovery are covered | [ ] Confirm recovery wording |
| Settings and help | Verified | Theme, pin, font, top/hierarchical-side mode, default manager collapse, log settings, shortcuts, security boundary, and the searchable/grouped/resizable side-manager behavior are documented in the active UI | [ ] Confirm settings wording |
| Security boundary | Verified | Renderer token exposure checks pass; device/profile/automation surfaces remain secret-free and credentials stay in Python/native boundaries | [ ] Security review acknowledgement |
| Legacy PySide non-regression | Verified | Final authoritative regression is `708 passed`; `src/desktop_app.py` and the `device-tui`/`device-tui-desktop` fallback entry points remain present | [ ] Optional side-by-side spot check |

Prioritized parity tasks:

1. P0: enforce the canonical simulator session target and add a runtime assertion.
2. P0: add Python-owned split-layout state and restore tab drag/drop to left, right,
   top, and bottom panes without creating duplicate backend sessions.
3. P0: completed 2026-08-11 — restored persistent quick-send definitions and their
   add/edit/delete/send UI, including sensitive-value credential storage.
   keep sensitive payloads in the credential boundary.
4. P1: completed 2026-08-12 — replaced the flat side rail with a searchable
   device/session hierarchy, expand/collapse-all, per-device context actions, and
   persisted width/collapse state.
5. P1: completed 2026-08-12 — exposed a complete editor for advanced
   automatic-response steps and recursive action flows.
6. P1: completed 2026-08-12 — file-service log/client hint, package-upgrade
   manual fallback, server-group collapse memory, and command-panel height resize.
7. Completed 2026-08-12 — every required row is verified; full Python tests,
   Vue typecheck/build, Electron runtime smoke, dark/light captures, renderer/backend
   recovery, and the security boundary all pass. Human operator sign-off remains a
   cutover activity rather than a parity implementation gap.

Split-pane implementation evidence, 2026-08-11:

- `TerminalSplitWorkspace` maps existing SessionHub session IDs into two presentation
  panes; splitting and dragging never call the session-create API.
- Tabs can be dropped to the nearest left/right/top/bottom edge. The same four actions
  are present in the keyboard-accessible session context menu.
- Both panes keep independent active sessions and live terminal WebSockets. The layout,
  assignments, active tabs, direction, and adjustable 20–80% ratio persist across
  renderer reload and are reconciled against the authoritative backend session list.
- The resize separator supports pointer dragging and arrow-key adjustment with explicit
  ARIA orientation/value metadata.
- Live Electron smoke proves two terminal panes, HTML drag/drop, unchanged backend
  session count, split restoration after reload, dark/light rendering, backend recovery,
  and `tokenExposed=false`.

Quick-send implementation evidence, 2026-08-11:

- `AutomationService` owns quick-send persistence and dispatch. Plain definitions use
  existing SQLite application metadata; sensitive payloads use the OS credential store,
  remain masked in API/Vue state, and never appear as plaintext in SQLite.
- The terminal quick toolbar supports persisted hide/restore, accessible editing, and
  add/edit/delete/send against the active SessionHub session. The legacy Ctrl+B default
  is retained.
- Focused Python/API/UI checks passed (`63 passed`), Vue typecheck/build passed, and the
  real Electron smoke created `display version`, received `SimOS V1.0`, edited and
  deleted the button through the UI, confirmed the Python workspace state, retained the
  default button, restored renderer and split state, recovered from a backend crash,
  and reported `tokenExposed=false`.
- Dark and light captures show the toolbar without clipping or contrast regressions:
  `desktop/out/smoke/ui-parity.png` and
  `desktop/out/smoke/ui-parity-light.png`.

Hierarchical session-manager evidence, 2026-08-12:

- Vue groups the authoritative `SessionSummary` records by `device_id`; switching,
  closing, splitting, and dragging continue to use existing session IDs and never call
  session creation from the manager.
- The right-side manager supports device/session search, remembered group collapse,
  expand/collapse-all, keyboard and pointer context menus at both hierarchy levels,
  device connection/occupancy actions, an accessible 42 px strip, and keyboard/pointer
  width adjustment clamped to 200–480 px.
- Structural UI checks passed (`29 passed`), Vue typecheck/build passed, and the real
  Electron smoke verified hierarchy, search, device actions, width/group persistence,
  four-session drag/drop with unchanged backend count, renderer reload, backend crash
  recovery, and `tokenExposed=false`.
- Expanded dark/light visual evidence is recorded in
  `desktop/out/smoke/ui-parity-session-manager.png` and
  `desktop/out/smoke/ui-parity-session-manager-light.png`.

Advanced automatic-response editor evidence, 2026-08-12:

- The renderer now provides explicit basic, step, and action-flow modes. Step rows edit
  trigger waits, multiple responses, per-response targets, delays, and Enter behavior;
  recursive action cards edit send, wait, finite/infinite loop, condition, and scoped
  exit nodes with move/delete controls.
- Target options are derived from safe `SessionSummary` records and serialize to the
  Python resolver's existing `source`, `current`, `next`, and
  `session:<device>:<kind>:<title>` forms. No credential or backend token is involved.
- Python decodes readable step text only at execution time, preserving legacy state
  round trips while supporting Ctrl keys, escape notation, and per-response Enter.
  Masked secret structures remain read-only for structural changes so stored secret
  references cannot be reassigned by index.
- Focused automation/backend/UI checks passed (`145 passed`), Vue typecheck/build
  passed, and the real Electron smoke created, persisted, and executed both a step rule
  and a nested action flow containing target, delay, loop, condition, and rule-scope
  exit fields. Renderer reload, backend recovery, and `tokenExposed=false` also passed.
- Expanded dark/light visual evidence is recorded in
  `desktop/out/smoke/ui-parity-advanced-automation.png` and
  `desktop/out/smoke/ui-parity-advanced-automation-light.png`.

File-service log and client-hint evidence, 2026-08-12:

- `ManagedTransferService` owns a thread-safe 300-entry service log and publishes the
  same bounded messages through application events. Authenticated GET/DELETE routes
  load and clear the authoritative log; refresh and backend recovery do not depend on
  renderer-only state.
- Python generates the FTP/SFTP client command from saved settings and the effective
  bound port. The hint contains username, host, and port only; the OS-vault password
  remains outside Vue.
- Focused transfer/backend/UI checks passed (`64 passed`), Vue typecheck/build passed,
  and the real Electron smoke started/stopped the FTP service, observed its live log,
  verified the safe client hint and copy controls, cleared the log through Python, and
  retained `tokenExposed=false` through recovery.
- Expanded dark/light visual evidence is recorded in
  `desktop/out/smoke/ui-parity-transfer-service.png` and
  `desktop/out/smoke/ui-parity-transfer-service-light.png`.

Package-upgrade manual-fallback evidence, 2026-08-12:

- `PackageUpgradeService` returns the redacted terminal tail, builds the editable
  Huawei upgrade script from the selected shared `.cc` package and precheck text,
  and sends non-comment commands in order through `SessionService`/`SessionHub`.
- The script returned to Vue contains `{{file_transfer.password}}` instead of a
  credential. Python accepts that placeholder only as a complete password command,
  resolves it from `ManagedTransferService`, protects terminal echo, rejects all
  unsupported placeholders, and never returns the resolved value.
- The Electron panel supports read, generate, edit, copy, explicit operator review,
  and send. Focused backend/security/UI checks passed (`66 passed`), Vue
  typecheck/build passed, and the real Electron smoke generated and copied a safe
  plan, edited it to `display version`, sent it through the active simulated session,
  observed the version output, recovered from renderer/backend restart, and reported
  `tokenExposed=false`.
- Dark/light visual evidence is recorded in
  `desktop/out/smoke/ui-parity-manual-upgrade.png` and
  `desktop/out/smoke/ui-parity-manual-upgrade-light.png`.

Saved-server group-collapse evidence, 2026-08-12:

- Server group headings are semantic buttons with synchronized `aria-expanded`
  state. The collapsed group-name set is presentation-only local state and does not
  duplicate Python-owned profile/group data.
- Searching temporarily reveals matching servers without erasing collapse memory;
  moving or saving a server expands its destination group so the result remains
  visible, and the operator can collapse it again.
- Vue typecheck and structural UI checks passed. The real Electron smoke created an
  empty group and a server, collapsed it, revealed it through search, moved it to
  ungrouped and back, re-collapsed it, reloaded the renderer, and confirmed both the
  persisted value and collapsed DOM state while `tokenExposed=false` and backend
  recovery remained green.
- Dark/light visual evidence is recorded in
  `desktop/out/smoke/ui-parity-server-groups.png` and
  `desktop/out/smoke/ui-parity-server-groups-light.png`.

Command-panel resize evidence, 2026-08-12:

- The command workspace owns a presentation-only preferred height. Its top separator
  supports pointer drag, Arrow keys, Shift acceleration, Home/End, and double-click
  reset with synchronized ARIA values and visible keyboard focus.
- The applied height is clamped to keep at least 180 px of the live workspace visible.
  A temporary small-window clamp does not overwrite the preferred height; expanding
  the window restores the preference, and collapse/expand plus renderer reload retain
  the final saved height.
- Vue typecheck and structural UI checks passed. The real Electron smoke dragged
  300 -> 370 px, used End to reach 680 px, resized the window and observed a 478 px
  clamp, restored 680 px when the window grew, saved 340 px, collapsed/reopened, and
  reloaded with the DOM and local state both at 340 px. Backend recovery and
  `tokenExposed=false` remained green.
- Dark/light visual evidence is recorded in
  `desktop/out/smoke/ui-parity-command-panel.png` and
  `desktop/out/smoke/ui-parity-command-panel-light.png`.

Automated acceptance command:

```powershell
pytest -q
cd desktop
npm run smoke:ui-parity
```

Rendered evidence:

- `desktop/out/smoke/ui-parity.png`
- `desktop/out/smoke/ui-parity-light.png`
- `desktop/out/smoke/ui-parity-settings.png`

Next hardening tasks:

- Complete the requirement-by-requirement operator acceptance checklist and attach
  the existing dark/light captures and live gate evidence to every visible parity row.
- Authorized SSH/Telnet/serial hardware success runs are optional follow-up evidence,
  not a parity completion gate, by product decision on 2026-08-12. Deterministic
  failure/retry UI paths and protocol-adapter success tests remain in the suite.
- Only after the parity checklist is accepted, resume Phase 7 clean-VM, true rollback,
  long-soak, and final cutover gates.

Final functional-parity gate, 2026-08-12:

- `pytest -q` -> `708 passed in 79.08s`.
- `python -m compileall -q src` -> passed.
- `git diff --check` -> passed; only existing Windows line-ending notices were emitted.
- `npm run typecheck` and `npm run build` -> passed.
- `npm run smoke:ui-parity` -> passed with all UI checks true, four SessionHub
  sessions restored, split layout restored, server-group and command-height state
  restored, `backendRecoveryPassed=true`, and `tokenExposed=false`.
- Dark/light captures were visually inspected for the complete workspace and the
  dedicated manual-upgrade, server-group, command-panel, session-manager, automation,
  and file-service surfaces. The upgrade workspace received an explicit light-theme
  contrast correction during this review.
- No module under `src/application`, `src/desktop_backend`, or `src/infrastructure`
  imports PySide6. The legacy `src/desktop_app.py` entry point remains available.
- Release packaging, clean-VM installation, update/rollback, default-entry cutover,
  and removal of the PySide fallback remain explicitly deferred.

Workspace layout refinement, 2026-08-12:

- Moved device and connection details from the detached right inspector into a
  collapsible detail section beneath the left inventory/profile list. Selection,
  copy controls, credential actions, occupancy, power, and connection metadata keep
  their existing behavior while the detail collapse state persists across reloads.
- Moved the hierarchical session manager from inside the terminal workspace to a
  dedicated right sidebar. Its search, grouping, context actions, drag/drop, width,
  group-collapse memory, and 42 px compact strip continue to use existing session IDs.
- At widths up to 1680 px, the expanded manager becomes a right overlay drawer so the
  terminal does not reflow; the collapsed 42 px strip occupies its own grid column and
  cannot cover terminal controls. Wider windows keep the manager docked.
- The expanded manager reserves separate rows for its toggle, heading, search, and
  scrollable tree, keeping device/session groups anchored directly below search.
- Updated Settings labels from side layout to right-side layout and reversed resize/
  disclosure directions to match the physical edge.
- Validation completed: `710 passed`; Python compile checks, Electron typecheck/build,
  and the complete UI parity smoke passed. Reload restored the right sidebar, manager
  width/groups/collapse state, left detail state, split layout, and command height;
  backend recovery passed and `tokenExposed=false`. Dark/light workspace and session-
  manager captures were visually inspected.

### Phase 8 — Cutover

Deliverables:

- Final parity report and operator acceptance checklist.
- Electron becomes the default entry point.
- PySide6 remains available for a defined fallback release window.

Exit criteria:

- All parity rows are accepted or explicitly removed by product decision.
- No Python core/backend module imports PySide6.
- No unresolved P0/P1 regression remains.
- Fallback and data rollback procedures are documented and exercised.

## Validation gates

Run at every phase boundary:

```powershell
python -m compileall -q src
pytest tests\test_desktop_backend.py -q
pytest -q
cd desktop
npm run typecheck
npm run build
```

Add focused commands for the capability being migrated. Run opt-in hardware tests only
when the required lab device and credentials are explicitly configured.

Manual verification must cover:

- Launching both Electron and the legacy PySide6 entry points.
- Inventory refresh and device selection.
- Terminal input, output, resize, detach/attach, reconnect, disconnect, and close.
- The migrated feature's success, validation-error, cancellation, and recovery paths.
- Confirmation that credentials are absent from renderer tools, API payloads, logs,
  persisted state, screenshots, and audit output.

## Change discipline

- Keep phases independently reviewable; do not combine a backend boundary extraction
  with a visual redesign.
- Prefer compatibility facades over broad call-site rewrites.
- Do not delete a legacy path in the same phase that introduces its replacement.
- Preserve `palette_picker.html` and unrelated user changes.
- Record every phase result and any newly discovered baseline issue in this file.
