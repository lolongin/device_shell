# VRP Package Builders

Device TUI runs system-package builders as external processes.  Builder plugins
are discovered through the `device_tui.package_builders` Entry Point group and
return a controlled `PreparedBuild`; the application owns operation state,
cancellation, logs, and artifact verification.

The built-in `internal-vrp` adapter expects the independently packaged CLI to
accept:

```text
vrp-builder build --request request.json --output image.cc --json-lines
```

The request file contains non-secret build data (`mrid`, `package_type`, model,
version, and options).  Credentials must not be passed in argv or written to
that file.

## Development

Set `DEVICE_TUI_VRP_BUILDER` to the CLI executable, for example:

```powershell
$env:DEVICE_TUI_VRP_BUILDER = "D:\tools\vrp-builder\vrp-builder.exe"
python -m device_tui.interfaces.desktop_api.main
```

The backend exposes:

```text
GET  /api/v1/package-builders
POST /api/v1/package-builds
GET  /api/v1/package-builds/{operation_id}
POST /api/v1/package-builds/{operation_id}/cancel
```

## Packaged desktop app

Place the PyInstaller `--onedir` output under `desktop/resources/vrp-builder`.
Electron copies it to `resources/vrp-builder` and injects the platform-specific
`vrp-builder(.exe)` path into the backend environment.  The CLI's Python
runtime and toolchain therefore remain separate from the frozen Device TUI
backend.
