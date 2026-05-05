# Repository Guidelines

## Project Structure & Module Organization
This project is a small Python package for a Textual-based device dashboard. Keep source code in `src/`.

- `src/app.py`: main TUI application, layout, key bindings, and connection actions.
- `src/data.py`: `Device` model and sample device data.
- `src/__init__.py`: package marker.
- `README.md`: user-facing setup and usage notes.
- `pyproject.toml`: package metadata and console script entry point (`device-tui`).

There is no `tests/` directory yet. Add new tests under `tests/` when the suite is introduced.

## Build, Test, and Development Commands
- `pip install -e .`: install the project in editable mode.
- `python src/app.py`: run the TUI directly during development.
- `device-tui`: run the packaged console entry point after installation.
- `python -m py_compile src\\*.py`: quick syntax check for source files.

Use a virtual environment and Python `3.10+`, matching `pyproject.toml`.

## Coding Style & Naming Conventions
Follow standard Python conventions:

- Use 4-space indentation and type hints for new code.
- Keep module names lowercase, for example `data.py`.
- Use `snake_case` for functions and variables, `PascalCase` for classes, and `UPPER_SNAKE_CASE` for constants.
- Keep UI strings, key bindings, and CSS-style constants grouped near the top of `src/app.py`.

Favor small helper methods over deeply nested event handlers.

## Testing Guidelines
Automated tests are not configured yet. For now, validate changes by:

- Launching `python src/app.py`
- Exercising filters, list navigation, and connection shortcuts
- Verifying sample device rendering and detail-panel updates

When adding tests, use `pytest`, place files in `tests/`, and name them `test_*.py`.

## Commit & Pull Request Guidelines
Git history is not available in this workspace, so no repository-specific commit pattern could be verified. Use short, imperative commit messages such as `Add CPU filter chips`.

Pull requests should include:

- A clear summary of behavior changes
- Manual test notes with commands used
- Screenshots or terminal captures for TUI layout changes
- Linked issue or task reference when applicable

## Security & Configuration Tips
`src/data.py` contains sample usernames, passwords, and IPs for local testing. Do not commit real credentials. Prefer environment-based configuration or a secure secrets store before connecting to production systems.
