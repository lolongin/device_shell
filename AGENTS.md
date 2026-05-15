# Repository Guidelines

## Project Structure & Module Organization
This project is a small Python package for a PySide6 desktop device dashboard.
Keep source code in `src/`.

- `src/desktop_app.py`: main desktop GUI, layout, device actions, and terminal tabs.
- `src/data.py`: `Device` model and sample/generated device data.
- `src/repository.py`: sample and API-backed repository implementations.
- `src/api_client.py`: HTTP API client used by GUI API mode.
- `src/telnet_session.py`: device Telnet session implementation.
- `src/linux_session.py`: Linux SSH session implementation.
- `src/session_protocol.py`: shared session callback/protocol types.
- `src/__init__.py`: package marker.
- `README.md`: user-facing setup and usage notes.
- `pyproject.toml`: package metadata and desktop console script entry points.

There is no `tests/` directory yet. Add new tests under `tests/` when the suite is introduced.

## Build, Test, and Development Commands
- `pip install -e .`: install the project in editable mode.
- `python src/desktop_app.py`: run the desktop GUI directly during development.
- `device-tui`: run the packaged desktop entry point after installation.
- `python -m py_compile src\\*.py`: quick syntax check for source files.

Use a virtual environment and Python `3.10+`, matching `pyproject.toml`.

## Coding Style & Naming Conventions
Follow standard Python conventions:

- Use 4-space indentation and type hints for new code.
- Keep module names lowercase, for example `data.py`.
- Use `snake_case` for functions and variables, `PascalCase` for classes, and `UPPER_SNAKE_CASE` for constants.
- Keep UI strings, key bindings, and style constants grouped near the top of `src/desktop_app.py`.

Favor small helper methods over deeply nested event handlers.

## Testing Guidelines
Automated tests are not configured yet. For now, validate changes by:

- Launching `python src/desktop_app.py`
- Exercising filters, list navigation, device detail updates, and connection shortcuts
- Verifying terminal tabs, reconnect/disconnect actions, command notes, and log controls

When adding tests, use `pytest`, place files in `tests/`, and name them `test_*.py`.

## Commit & Pull Request Guidelines
Use short, imperative commit messages such as `Add CPU filter chips`.

Pull requests should include:

- A clear summary of behavior changes
- Manual test notes with commands used
- Screenshots or terminal captures for GUI layout changes
- Linked issue or task reference when applicable

## Security & Configuration Tips
`src/data.py` contains sample usernames, passwords, and IPs for local testing.
Do not commit real credentials. Prefer environment-based configuration or a
secure secrets store before connecting to production systems.
