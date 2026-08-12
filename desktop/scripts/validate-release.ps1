param(
    [string]$CurrentInstaller = "",
    [string]$PreviousInstaller = "",
    [string]$WorkRoot = "",
    [switch]$KeepWorkRoot
)

$ErrorActionPreference = "Stop"

function Resolve-Installer([string]$PathValue, [string]$DefaultPath) {
    $candidate = if ($PathValue) { $PathValue } else { $DefaultPath }
    $resolved = Resolve-Path -LiteralPath $candidate -ErrorAction Stop
    return $resolved.Path
}

function Start-Installer([string]$Installer, [string]$InstallDir) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    $process = Start-Process `
        -FilePath $Installer `
        -ArgumentList "/S", "/D=$InstallDir" `
        -WindowStyle Hidden `
        -PassThru
    if (-not $process.WaitForExit(120000)) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        throw "Installer did not exit within 120 seconds: $Installer"
    }
    if ($process.ExitCode -ne 0) {
        throw "Installer exited with $($process.ExitCode): $Installer"
    }
}

function Invoke-PackagedCapture([string]$InstallDir, [string]$UserDataDir, [string]$CapturePath) {
    $appExe = Join-Path $InstallDir "Device TUI.exe"
    if (-not (Test-Path -LiteralPath $appExe)) {
        throw "Installed app executable was not found: $appExe"
    }
    New-Item -ItemType Directory -Path $UserDataDir -Force | Out-Null
    $stdout = Join-Path (Split-Path -Parent $CapturePath) "app.stdout.log"
    $stderr = Join-Path (Split-Path -Parent $CapturePath) "app.stderr.log"
    $env:DEVICE_TUI_CAPTURE_PATH = $CapturePath
    $env:DEVICE_TUI_CAPTURE_TERMINAL = "1"
    $env:ELECTRON_ENABLE_LOGGING = "1"
    $process = Start-Process `
        -FilePath $appExe `
        -ArgumentList "--user-data-dir=$UserDataDir" `
        -WorkingDirectory $InstallDir `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -WindowStyle Hidden `
        -PassThru
    if (-not $process.WaitForExit(30000)) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        throw "Packaged app capture did not exit within 30 seconds: $appExe"
    }
    if (-not (Test-Path -LiteralPath $CapturePath)) {
        $errorText = if (Test-Path -LiteralPath $stderr) { Get-Content -LiteralPath $stderr -Raw } else { "" }
        throw "Packaged app did not write capture: $CapturePath`n$errorText"
    }
    $backendLog = Join-Path $UserDataDir "logs\backend.log"
    if (-not (Test-Path -LiteralPath $backendLog)) {
        throw "Backend lifecycle log was not written: $backendLog"
    }
    $logText = Get-Content -LiteralPath $backendLog -Raw
    if ($logText -notmatch "device-tui-backend(.exe)? --port 0") {
        throw "Backend log does not show bundled backend startup: $backendLog"
    }
    $stdoutText = if (Test-Path -LiteralPath $stdout) { Get-Content -LiteralPath $stdout -Raw } else { "" }
    if ($stdoutText -notmatch "tokenExposed=false") {
        throw "Renderer runtime config exposed a backend token or capture output was incomplete: $stdout"
    }
}

function Invoke-Uninstall([string]$InstallDir) {
    $uninstaller = Get-ChildItem -LiteralPath $InstallDir -Filter "Uninstall*.exe" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $uninstaller) {
        throw "Uninstaller was not found in $InstallDir"
    }
    $process = Start-Process `
        -FilePath $uninstaller.FullName `
        -ArgumentList "/S" `
        -WindowStyle Hidden `
        -PassThru
    if (-not $process.WaitForExit(120000)) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        throw "Uninstaller did not exit within 120 seconds: $($uninstaller.FullName)"
    }
    if ($process.ExitCode -ne 0) {
        throw "Uninstaller exited with $($process.ExitCode): $($uninstaller.FullName)"
    }
}

$desktopRoot = Split-Path -Parent $PSScriptRoot
$defaultInstaller = Join-Path $desktopRoot "release\Device TUI Setup 0.1.0.exe"
$current = Resolve-Installer $CurrentInstaller $defaultInstaller
$previous = if ($PreviousInstaller) { Resolve-Installer $PreviousInstaller $PreviousInstaller } else { $current }
$createdWorkRoot = $false
if (-not $WorkRoot) {
    $WorkRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("device-tui-release-smoke-" + [System.Guid]::NewGuid().ToString("N"))
    $createdWorkRoot = $true
}
$WorkRoot = [System.IO.Path]::GetFullPath($WorkRoot)
$installDir = Join-Path $WorkRoot "install"
$userDataDir = Join-Path $WorkRoot "user-data"

try {
    New-Item -ItemType Directory -Path $WorkRoot -Force | Out-Null
    Start-Installer $previous $installDir
    Invoke-PackagedCapture $installDir $userDataDir (Join-Path $WorkRoot "previous.png")
    Start-Installer $current $installDir
    Invoke-PackagedCapture $installDir $userDataDir (Join-Path $WorkRoot "current.png")
    if ($PreviousInstaller) {
        Start-Installer $previous $installDir
        Invoke-PackagedCapture $installDir $userDataDir (Join-Path $WorkRoot "rollback.png")
    }
    Invoke-Uninstall $installDir
    Write-Output "Release validation passed"
    Write-Output "CurrentInstaller=$current"
    Write-Output "PreviousInstaller=$previous"
    Write-Output "WorkRoot=$WorkRoot"
}
finally {
    Remove-Item Env:DEVICE_TUI_CAPTURE_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:DEVICE_TUI_CAPTURE_TERMINAL -ErrorAction SilentlyContinue
    if ($createdWorkRoot -and -not $KeepWorkRoot) {
        $resolvedTemp = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
        if ($WorkRoot.StartsWith($resolvedTemp, [System.StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $WorkRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
