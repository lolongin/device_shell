param(
    [string]$CurrentInstaller = "",
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

function Invoke-CleanRuntimeCapture([string]$InstallDir, [string]$UserDataDir, [string]$CapturePath) {
    $appExe = Join-Path $InstallDir "OdyTerm.exe"
    if (-not (Test-Path -LiteralPath $appExe)) {
        throw "Installed app executable was not found: $appExe"
    }
    New-Item -ItemType Directory -Path $UserDataDir -Force | Out-Null
    $stdout = Join-Path (Split-Path -Parent $CapturePath) "app.stdout.log"
    $stderr = Join-Path (Split-Path -Parent $CapturePath) "app.stderr.log"
    $envNames = @(
        "PATH",
        "PYTHONHOME",
        "PYTHONPATH",
        "DEVICE_TUI_PYTHON",
        "DEVICE_TUI_PROJECT_ROOT",
        "DEVICE_TUI_BACKEND_EXECUTABLE",
        "DEVICE_TUI_BACKEND_URL",
        "DEVICE_TUI_DESKTOP_TOKEN",
        "NODE_OPTIONS",
        "NPM_CONFIG_PREFIX",
        "npm_config_prefix"
    )
    $originalEnv = @{}
    foreach ($name in $envNames) {
        $originalEnv[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
    }
    $systemRoot = [Environment]::GetEnvironmentVariable("SystemRoot", "Machine")
    if (-not $systemRoot) {
        $systemRoot = $env:SystemRoot
    }
    $cleanPath = @(
        (Join-Path $systemRoot "System32"),
        $systemRoot,
        (Join-Path $systemRoot "System32\Wbem"),
        (Join-Path $systemRoot "System32\WindowsPowerShell\v1.0")
    ) -join ";"

    try {
        [Environment]::SetEnvironmentVariable("PATH", $cleanPath, "Process")
        foreach ($name in $envNames) {
            if ($name -ne "PATH") {
                [Environment]::SetEnvironmentVariable($name, $null, "Process")
            }
        }
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
            throw "Packaged app clean-runtime capture did not exit within 30 seconds: $appExe"
        }
    }
    finally {
        foreach ($name in $envNames) {
            [Environment]::SetEnvironmentVariable($name, $originalEnv[$name], "Process")
        }
        Remove-Item Env:DEVICE_TUI_CAPTURE_PATH -ErrorAction SilentlyContinue
        Remove-Item Env:DEVICE_TUI_CAPTURE_TERMINAL -ErrorAction SilentlyContinue
    }

    if (-not (Test-Path -LiteralPath $CapturePath)) {
        $errorText = if (Test-Path -LiteralPath $stderr) { Get-Content -LiteralPath $stderr -Raw } else { "" }
        throw "Packaged app did not write capture under clean runtime env: $CapturePath`n$errorText"
    }
    $stdoutText = if (Test-Path -LiteralPath $stdout) { Get-Content -LiteralPath $stdout -Raw } else { "" }
    if ($stdoutText -notmatch "tokenExposed=false") {
        throw "Renderer runtime config exposed a backend token or capture output was incomplete: $stdout"
    }
    $backendLog = Join-Path $UserDataDir "logs\backend.log"
    if (-not (Test-Path -LiteralPath $backendLog)) {
        throw "Backend lifecycle log was not written: $backendLog"
    }
    $logText = Get-Content -LiteralPath $backendLog -Raw
    if ($logText -notmatch "resources\\backend\\odyterm-backend\\odyterm-backend(.exe)? --port 0") {
        throw "Backend log does not show bundled backend startup under clean runtime env: $backendLog"
    }
    if ($logText -match "python -m device_tui\.interfaces\.desktop_api\.main") {
        throw "Packaged app fell back to source-mode Python backend under clean runtime env: $backendLog"
    }
}

$desktopRoot = Split-Path -Parent $PSScriptRoot
$defaultInstaller = Join-Path $desktopRoot "release\OdyTerm Setup 0.1.0.exe"
$current = Resolve-Installer $CurrentInstaller $defaultInstaller
$createdWorkRoot = $false
if (-not $WorkRoot) {
    $WorkRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("odyterm-clean-runtime-" + [System.Guid]::NewGuid().ToString("N"))
    $createdWorkRoot = $true
}
$WorkRoot = [System.IO.Path]::GetFullPath($WorkRoot)
$installDir = Join-Path $WorkRoot "install"
$userDataDir = Join-Path $WorkRoot "user-data"

try {
    New-Item -ItemType Directory -Path $WorkRoot -Force | Out-Null
    Start-Installer $current $installDir
    Invoke-CleanRuntimeCapture $installDir $userDataDir (Join-Path $WorkRoot "clean-runtime.png")
    Invoke-Uninstall $installDir
    Write-Output "Clean runtime validation passed"
    Write-Output "CurrentInstaller=$current"
    Write-Output "WorkRoot=$WorkRoot"
}
finally {
    if ($createdWorkRoot -and -not $KeepWorkRoot) {
        $resolvedTemp = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
        if ($WorkRoot.StartsWith($resolvedTemp, [System.StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $WorkRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
