# Repository Guidelines

## Project Structure & Module Organization

Device TUI has one desktop UI: Electron + Vue. Python is a headless backend and
must not introduce PySide/PyQt dependencies.

- `desktop/src/main/`: Electron lifecycle, backend supervision, secure IPC.
- `desktop/src/preload/`: narrow renderer bridge.
- `desktop/src/renderer/`: Vue UI and xterm.js terminal workspace.
- `src/desktop_backend/`: FastAPI and WebSocket backend.
- `src/application/`: UI-independent application services.
- `src/infrastructure/`: persistence and external adapters.
- `src/device_mcp/`: MCP entry point, tools, and gateway.
- `src/device_source_service.py`: active device-source policy and lifecycle.
- `src/device_source_plugins.py`: built-in sources and Entry Point discovery.
- `src/data.py`, `src/repository.py`: device model and repository contracts.
- `tests/`: pytest suite.

## Build, Test, and Development Commands

- `pip install -e .`: install the Python backend in editable mode.
- `python -m src.desktop_backend.main`: run the backend independently.
- `python -m pytest`: run Python tests.
- `python -m compileall -q src`: check Python syntax.
- `cd desktop && npm install`: install desktop packages.
- `cd desktop && npm run dev`: run the desktop App.
- `cd desktop && npm run typecheck`: run Vue and Electron TypeScript checks.
- `cd desktop && npm run build`: build the production desktop bundles.
- `cd desktop && npm run dist`: build the Windows installer and bundled backend.

Use Python 3.10+ and a virtual environment.

## Coding Style & Naming Conventions

- Use 4-space indentation and type hints for new Python code.
- Use `snake_case` for Python functions and variables, `PascalCase` for classes,
  and `UPPER_SNAKE_CASE` for constants.
- Keep Vue components focused; move shared behavior into composables, stores, or
  Python application services.
- Keep credentials and privileged operations outside the renderer.
- Favor small helpers over deeply nested event handlers.

## Testing Guidelines

Use `pytest` for Python tests under `tests/test_*.py`. For desktop changes, run
type checks and the production build in addition to the relevant pytest files.
Exercise filters, source workflows, terminal connection/reconnect, transfer plans,
and persistence when those areas change.

## Commit & Pull Request Guidelines

Use short, imperative commit messages such as `Simplify device source selection`.
Pull requests should include a behavior summary, validation commands, screenshots
for visible UI changes, and a linked issue when applicable.

## Security & Configuration Tips

Never commit real credentials. Keep passwords in the operating-system credential
vault and website cookies in backend memory. Renderer state, SQLite, logs, and MCP
results must remain free of secrets.
