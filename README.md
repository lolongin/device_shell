# Network Device Desktop

PySide6 desktop GUI for device inventory, occupancy management, and embedded
terminal sessions.

## Features

- Device list with keyword, domain, status, CPU, and "my occupancy" filters
- Device detail panel with Telnet, SSH, serial, asset, and owner information
- Embedded Telnet, Linux SSH, and serial Telnet sessions
- Multi-session device tabs, split terminal panes, reconnect, disconnect, and logs
- Command note panel with persisted command tabs
- Optional API-backed repository for integration with an external website/backend

## Install

```bash
pip install -e .
```

or install the runtime dependencies directly:

```bash
pip install PySide6 asyncssh pyte
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
