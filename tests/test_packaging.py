"""Tests for packaging configuration."""
from __future__ import annotations

import json
import tomllib
from importlib import import_module
from pathlib import Path


def test_setuptools_includes_refactored_subpackages() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    package_find = pyproject["tool"]["setuptools"]["packages"]["find"]

    assert package_find["include"] == ["device_tui*"]
    assert pyproject["tool"]["setuptools"]["package-data"] == {
        "device_tui.application.ai.gateway": ["skills/*.json"]
    }


def test_python_packaging_extra_includes_pyinstaller() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    packaging_extra = pyproject["project"]["optional-dependencies"]["packaging"]

    assert "pyinstaller>=6,<7" in packaging_extra


def test_python_runtime_dependencies_include_websocket_transport() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    dependencies = pyproject["project"]["dependencies"]

    assert "websockets>=15,<17" in dependencies


def test_electron_package_scripts_build_bundled_backend() -> None:
    package_json = json.loads(Path("desktop/package.json").read_text(encoding="utf-8"))
    scripts = package_json["scripts"]

    assert scripts["build:backend"] == (
        "powershell -ExecutionPolicy Bypass -File scripts/build-python-backend.ps1"
    )
    assert "npm run build:backend" in scripts["dist"]
    assert "electron-builder --config electron-builder.yml" in scripts["dist"]
    assert "--publish never" in scripts["dist"]
    assert scripts["smoke:release"] == (
        "powershell -ExecutionPolicy Bypass -File scripts/validate-release.ps1"
    )
    assert scripts["smoke:clean-runtime"] == (
        "powershell -ExecutionPolicy Bypass -File scripts/validate-clean-runtime.ps1"
    )
    assert scripts["smoke:soak"] == (
        "powershell -ExecutionPolicy Bypass -File scripts/soak-backend.ps1"
    )
    assert scripts["smoke:app-soak"] == (
        "powershell -ExecutionPolicy Bypass -File scripts/soak-packaged-app.ps1"
    )
    assert scripts["soak:app"] == (
        "powershell -ExecutionPolicy Bypass -File scripts/soak-packaged-app.ps1 -DurationMinutes 480 -PauseSeconds 5"
    )
    assert "electron-builder" in package_json["devDependencies"]


def test_electron_builder_includes_pyinstaller_backend_resource() -> None:
    builder_config = Path("desktop/electron-builder.yml").read_text(encoding="utf-8")

    assert "electronVersion: 43.3.0" in builder_config
    assert "electronDist: node_modules/electron/dist" in builder_config
    assert "compression: store" in builder_config
    assert "output: release" in builder_config
    assert "from: resources/backend" in builder_config
    assert "to: backend" in builder_config
    assert "target:\n    - nsis" in builder_config


def test_backend_bundle_script_has_stable_pyinstaller_output() -> None:
    script = Path("desktop/scripts/build-python-backend.ps1").read_text(encoding="utf-8")

    assert '$pyInstallerArgs = @(' in script
    assert '"--noconfirm"' in script
    assert '"--clean"' in script
    assert '"--onedir"' in script
    assert '"--name", "device-tui-backend"' in script
    assert '"--collect-data", "device_tui"' in script
    assert '"--distpath", $outputRoot' in script
    assert '& $Python -m PyInstaller @pyInstallerArgs' in script
    assert 'device_tui\\interfaces\\desktop_api\\frozen_main.py' in script
    assert 'resources\\backend' in script
    assert 'device-tui-backend\\device-tui-backend.exe' in script


def test_release_validation_script_exercises_install_upgrade_rollback() -> None:
    script = Path("desktop/scripts/validate-release.ps1").read_text(encoding="utf-8")

    assert 'param(' in script
    assert '$CurrentInstaller' in script
    assert '$PreviousInstaller' in script
    assert 'Start-Installer $previous $installDir' in script
    assert 'Start-Installer $current $installDir' in script
    assert 'Invoke-PackagedCapture $installDir $userDataDir' in script
    assert 'if ($PreviousInstaller)' in script
    assert 'Invoke-Uninstall $installDir' in script
    assert 'tokenExposed=false' in script
    assert 'device-tui-backend(.exe)? --port 0' in script
    assert 'Remove-Item -LiteralPath $WorkRoot -Recurse -Force' in script


def test_clean_runtime_validation_script_masks_python_and_node() -> None:
    script = Path("desktop/scripts/validate-clean-runtime.ps1").read_text(encoding="utf-8")

    assert "$CurrentInstaller" in script
    assert "Start-Installer $current $installDir" in script
    assert "Invoke-CleanRuntimeCapture $installDir $userDataDir" in script
    assert '"PYTHONPATH"' in script
    assert '"DEVICE_TUI_PYTHON"' in script
    assert '"DEVICE_TUI_PROJECT_ROOT"' in script
    assert '"NODE_OPTIONS"' in script
    assert "System32\\WindowsPowerShell\\v1.0" in script
    assert "resources\\\\backend\\\\device-tui-backend" in script
    assert "python -m device_tui\\.interfaces\\.desktop_api\\.main" in script
    assert "Clean runtime validation passed" in script
    assert "Invoke-Uninstall $installDir" in script
    assert "Remove-Item -LiteralPath $WorkRoot -Recurse -Force" in script


def test_backend_soak_script_exercises_packaged_api_load() -> None:
    script = Path("desktop/scripts/soak-backend.ps1").read_text(encoding="utf-8")

    assert "$SessionCount" in script
    assert "$Cycles" in script
    assert "device-tui-backend.exe" in script
    assert "/api/v1/sessions" in script
    assert "/api/v1/commands/send" in script
    assert "/api/v1/diagnostics" in script
    assert "SimOS V1.0" in script
    assert "Packaged backend soak passed" in script
    assert "Remove-Item -LiteralPath $WorkRoot -Recurse -Force" in script


def test_packaged_app_soak_script_exercises_electron_recovery() -> None:
    script = Path("desktop/scripts/soak-packaged-app.ps1").read_text(encoding="utf-8")

    assert "Device TUI.exe" in script
    assert "$Cycles" in script
    assert "$DurationMinutes" in script
    assert "$PauseSeconds" in script
    assert "Invoke-AppRecoveryCycle" in script
    assert "DEVICE_TUI_CAPTURE_BACKEND_RECOVERY" in script
    assert "tokenExposed=false" in script
    assert "recoveryCrashed=true" in script
    assert "recoveryChanged=true" in script
    assert "recoveryRequestStatus=200" in script
    assert "Python backend ready at" in script
    assert "CyclesCompleted=$completedCycles" in script
    assert "$expectedReadyCount = $completedCycles * 2" in script
    assert "Packaged app soak passed" in script
    assert "Remove-Item -LiteralPath $WorkRoot -Recurse -Force" in script


def test_electron_backend_launcher_supports_packaged_recovery() -> None:
    launcher = Path("desktop/src/main/python-backend.ts").read_text(encoding="utf-8")
    main_process = Path("desktop/src/main/index.ts").read_text(encoding="utf-8")
    renderer_api = Path("desktop/src/renderer/src/transport/api.ts").read_text(encoding="utf-8")

    assert "DEVICE_TUI_BACKEND_EXECUTABLE" in launcher
    assert "app.isPackaged" in launcher
    assert "process.resourcesPath" in launcher
    assert "'backend', 'device-tui-backend', executable" in launcher
    assert "DEVICE_TUI_PACKAGED" in launcher
    assert "backend.log" in launcher
    assert "rotateDiagnosticIfNeeded" in launcher
    assert "DEVICE_TUI_BACKEND_LOG_MAX_BYTES" in launcher
    assert "DEVICE_TUI_BACKEND_LOG_BACKUPS" in launcher
    assert "scheduleRestart" in launcher
    assert "crashForRecoveryProbe" in launcher
    assert "DEVICE_TUI_CAPTURE_BACKEND_RECOVERY" in main_process
    assert "recoveryRequestStatus" in main_process
    assert "fetchBackend(backend.config" in main_process
    assert "apiBaseUrl: runtime.apiBaseUrl" in main_process
    assert "const runtime = await getRuntime(true)" in renderer_api


def test_frozen_backend_entrypoint_imports() -> None:
    module = import_module("device_tui.interfaces.desktop_api.frozen_main")

    assert callable(module.main)
