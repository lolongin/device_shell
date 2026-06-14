# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Test

```bash
pip install -e .                          # editable install
python -m py_compile src\*.py             # quick compilation check
pytest                                    # run all tests
pytest tests/test_api_client.py -v        # run a single test file
```

The `[tool.pytest.ini_options]` in `pyproject.toml` sets `testpaths = ["tests"]` and `pythonpath = ["src"]`, so tests import from `src` directly.

## Architecture

### Class composition via mixins

`DeviceDesktopApp` (in `src/app/main_window.py`) is built by composing seven mixins with `QMainWindow`:

```
SessionOpsMixin, OccupancyOpsMixin, CommandRecordOpsMixin,
DesktopStateMixin, FileTransferOpsMixin, TemporaryDeviceOpsMixin,
TableOpsMixin, QMainWindow
```

Each mixin lives in its own `src/app/<domain>_ops.py` file and handles one cross-cutting concern (session lifecycle, occupancy toggling, command record panel, state persistence, file transfer service, temporary connections, table rendering). The main window class itself contains all UI construction (`_build_*` methods) and event wiring.

### Data flow

```
DeviceRepository (Protocol)
  ├── SampleDeviceRepository    (in-memory, default)
  └── ApiDeviceRepository       (HTTP API, opt-in via DEVICE_TUI_DATA_SOURCE=api)
         └── DeviceApiClient    (src/api_client.py)
```

`repo_factory.create_repository_from_env()` selects the implementation at startup. The repository is polled on a `QTimer` in API mode; in sample mode it returns a static snapshot. `RepositorySnapshot` (`app_state.py`) bundles the current user, device list, and owned device IDs for the UI.

### Session layer

```
CommandSession (Protocol, session_protocol.py)
  ├── HuaweiTelnetSession    (telnet_session.py)
  └── LinuxSshSession        (linux_session.py)
```

Sessions are async (`asyncssh` for SSH, `telnetlib3` for Telnet) and run on `AsyncLoopThread` — a dedicated daemon thread with its own `asyncio` event loop. `AsyncLoopThread.submit(coro)` schedules coroutines thread-safely and returns a `concurrent.futures.Future`.

### Terminal rendering

Three backends, selected via `DEVICE_TUI_TERMINAL_WIDGET`:
- `xterm` (default): `QWebEngineView` + xterm.js + `QtWebChannel` bridge — `src/widgets/xterm_web_widget.py`
- `canvas`: PySide/pyte-based canvas renderer — `src/widgets/terminal_canvas.py`
- `legacy`: `QPlainTextEdit` — `src/widgets/terminal_widget.py`

The xterm backend loads assets from `src/web/assets/` (xterm.js, xterm.css, addon-fit.js) with a CDN fallback.

### Web surfaces

`src/web/` contains HTML pages rendered in `QWebEngineView`:
- `web_shell.html` — home dashboard
- `device_navigation.html` — compact terminal session navigation
- `xterm_terminal.html` — xterm.js terminal
- `auto_response_editor.html` — auto-response rule editor

All Web pages link `src/web/assets/workspace-theme.css` for shared OLED theme tokens. Python ↔ JavaScript communication uses `QtWebChannel` with bridge objects exposed from the Python side.

### Qt UI thread safety

All UI mutations must happen on the Qt main thread. Background work (network I/O) runs on `AsyncLoopThread`, which posts results to `self.ui_queue`. A 10ms `QTimer` (`ui_timer`) drains the queue on the main thread via `_drain_ui_queue()`.

### Design system

`design-system/MASTER.md` is the source of truth for colors, tokens, and visual language. The theme tokens apply across Qt stylesheets (`src/styles.py`), Web CSS (`workspace-theme.css`), canvas rendering, and generated HTML. When changing colors, update `design-system/MASTER.md` first, then propagate to all surfaces.

### Auto-response rules

`src/auto_response.py` defines `AutoResponseRule` — patterns that match terminal output and automatically send responses. Rules support match/regex triggers, multi-step workflows, action flows (send/wait/loop/exit/condition), and per-session trigger counting. Rules are serialized to/from desktop state JSON.

### Desktop state persistence

`DesktopStateMixin` (`src/app/desktop_state.py`) saves/loads window geometry, session tabs, command record content, auto-response rules, quick-send buttons, and UI toggle states to a JSON file. State is debounced via `state_save_timer`.

### Temporary devices

`TemporaryDeviceOpsMixin` manages ephemeral connections that don't appear in the device table — stored in `self.temporary_devices` as `Device` objects and rendered in the "临时连接" panel.

### Key data types

- `Device` (`src/data.py`): `@dataclass(slots=True)` with fields for id, name, domain, status, owner, SSH/Telnet/Serial connection params, asset metadata, and an `extra: dict` for extensibility.
- `DeviceTabState` / `SessionTabState` (`src/app_state.py`): runtime state for device-level tabs (which can contain session splitters) and individual session tabs.
- `SessionCallbacks` (`src/session_protocol.py`): `on_output` and `on_status` emitters passed to session backends.
