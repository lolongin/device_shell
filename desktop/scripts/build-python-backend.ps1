param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$desktopRoot = Split-Path -Parent $PSScriptRoot
$projectRoot = Split-Path -Parent $desktopRoot
$outputRoot = Join-Path $desktopRoot "resources\backend"
$workRoot = Join-Path $desktopRoot ".pyinstaller-work"
$specRoot = Join-Path $desktopRoot ".pyinstaller-spec"

& $Python -m PyInstaller --noconfirm --clean --onedir `
    --name "device-tui-backend" `
    --distpath $outputRoot `
    --workpath $workRoot `
    --specpath $specRoot `
    --paths $projectRoot `
    --collect-all keyring `
    --collect-all pyftpdlib `
    --collect-all uvicorn `
    (Join-Path $projectRoot "src\desktop_backend\frozen_main.py")

$executable = Join-Path $outputRoot "device-tui-backend\device-tui-backend.exe"
if (-not (Test-Path -LiteralPath $executable)) {
    throw "PyInstaller did not produce $executable"
}

Write-Output "Bundled backend: $executable"
