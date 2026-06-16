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

## Project Layout

- `src/desktop_app.py`: PySide6 desktop GUI
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
