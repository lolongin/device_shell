# Electron Desktop Migration

## Status

Complete. Electron + Vue is the sole desktop App. The former Qt desktop entry
point, widgets, WebEngine resources, dependencies, package data, and UI-only tests
have been removed.

## Completed Cutover

- Electron Main supervises the headless Python backend.
- Vue provides device, session, terminal, transfer, upgrade, automation, AI, and
  settings workspaces.
- xterm.js is loaded through the desktop npm dependency instead of bundled
  WebEngine assets.
- Python application services own sessions, credentials, operations, persistence,
  managed transfer, package upgrades, and MCP behavior.
- Device data uses one active `DeviceSourceService` source with product-profile
  policy and external Entry Point plugins.
- Installer builds bundle the backend and validate clean-machine startup.
- Backend bearer tokens, terminal tickets, credentials, and website cookies remain
  outside the renderer.

## Removed Compatibility Surface

- `src/desktop_app.py`
- `src/app/`
- `src/widgets/`
- `src/web/`
- Qt-only state, style, helper, and event-loop bridge modules
- `device-tui` and `device-tui-desktop` Python GUI console scripts
- PySide6, PySide6-WebEngine, and pyte runtime dependencies
- Legacy Qt UI capture and regression tests

## Ongoing Contract

The cutover contract in `tests/test_cutover_contract.py` prevents reintroducing Qt
dependencies or deleted paths. New UI behavior belongs in
`desktop/src/renderer/`; privileged desktop behavior belongs in Electron Main or
the Python backend. Shared domain behavior belongs in `src/application/`.

## Validation

```powershell
python -m pytest
python -m compileall -q src
Set-Location desktop
npm run typecheck
npm run build
```
