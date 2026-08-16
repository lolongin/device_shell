param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$desktopRoot = Split-Path -Parent $PSScriptRoot
$projectRoot = Split-Path -Parent $desktopRoot
$outputRoot = Join-Path $desktopRoot "resources\backend"
$workRoot = Join-Path $desktopRoot ".pyinstaller-work"
$specRoot = Join-Path $desktopRoot ".pyinstaller-spec"

$pyInstallerArgs = @(
    "--noconfirm",
    "--clean",
    "--onedir",
    "--name", "device-tui-backend",
    "--distpath", $outputRoot,
    "--workpath", $workRoot,
    "--specpath", $specRoot,
    "--paths", $projectRoot,
    "--collect-data", "device_tui",
    "--collect-all", "keyring",
    "--collect-all", "openpyxl",
    "--collect-all", "pyftpdlib",
    "--collect-all", "uvicorn"
)

$pluginDistributions = @(
    ($env:DEVICE_TUI_SOURCE_PLUGIN_DISTRIBUTIONS -split ",") |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ }
)
foreach ($distribution in $pluginDistributions) {
    if ($distribution -notmatch "^[A-Za-z0-9_.-]+$") {
        throw "Invalid device-source plugin distribution name: $distribution"
    }
    $pyInstallerArgs += @("--copy-metadata", $distribution)
}

$pluginModules = @(
    ($env:DEVICE_TUI_SOURCE_PLUGIN_MODULES -split ",") |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ }
)
foreach ($module in $pluginModules) {
    if ($module -notmatch "^[A-Za-z_][A-Za-z0-9_.]*$") {
        throw "Invalid device-source plugin module name: $module"
    }
    $pyInstallerArgs += @("--collect-all", $module)
}
$pyInstallerArgs += (Join-Path $projectRoot "device_tui\interfaces\desktop_api\frozen_main.py")

& $Python -m PyInstaller @pyInstallerArgs

$executable = Join-Path $outputRoot "device-tui-backend\device-tui-backend.exe"
if (-not (Test-Path -LiteralPath $executable)) {
    throw "PyInstaller did not produce $executable"
}

Write-Output "Bundled backend: $executable"
