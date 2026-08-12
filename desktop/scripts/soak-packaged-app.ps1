param(
    [string]$AppExecutable = "",
    [string]$WorkRoot = "",
    [int]$Cycles = 1,
    [int]$DurationMinutes = 0,
    [int]$PauseSeconds = 0,
    [switch]$KeepWorkRoot
)

$ErrorActionPreference = "Stop"

function Resolve-App([string]$PathValue, [string]$DefaultPath) {
    $candidate = if ($PathValue) { $PathValue } else { $DefaultPath }
    $resolved = Resolve-Path -LiteralPath $candidate -ErrorAction Stop
    return $resolved.Path
}

function Assert-Contains([string]$Text, [string]$Pattern, [string]$Message) {
    if ($Text -notmatch $Pattern) {
        throw $Message
    }
}

function Invoke-AppRecoveryCycle(
    [string]$AppExe,
    [string]$UserDataDir,
    [string]$CycleRoot,
    [int]$CycleNumber
) {
    New-Item -ItemType Directory -Path $CycleRoot -Force | Out-Null
    $capturePath = Join-Path $CycleRoot "capture.png"
    $stdout = Join-Path $CycleRoot "app.stdout.log"
    $stderr = Join-Path $CycleRoot "app.stderr.log"

    $env:DEVICE_TUI_CAPTURE_PATH = $capturePath
    $env:DEVICE_TUI_CAPTURE_TERMINAL = "1"
    $env:DEVICE_TUI_CAPTURE_BACKEND_RECOVERY = "1"
    $env:ELECTRON_ENABLE_LOGGING = "1"
    $process = Start-Process `
        -FilePath $AppExe `
        -ArgumentList "--user-data-dir=$UserDataDir" `
        -WorkingDirectory (Split-Path -Parent $AppExe) `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -WindowStyle Hidden `
        -PassThru
    if (-not $process.WaitForExit(45000)) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        throw "Packaged app soak cycle $CycleNumber did not exit within 45 seconds: $AppExe"
    }
    if (-not (Test-Path -LiteralPath $capturePath)) {
        $errorText = if (Test-Path -LiteralPath $stderr) { Get-Content -LiteralPath $stderr -Raw } else { "" }
        throw "Packaged app did not write capture in cycle $CycleNumber`: $capturePath`n$errorText"
    }

    $stdoutText = Get-Content -LiteralPath $stdout -Raw
    Assert-Contains $stdoutText "desktopApi=object" "Renderer preload bridge was not available in cycle $CycleNumber."
    Assert-Contains $stdoutText "tokenExposed=false" "Renderer runtime config exposed backend token in cycle $CycleNumber."
    Assert-Contains $stdoutText "recoveryCrashed=true" "Recovery probe did not crash the managed backend in cycle $CycleNumber."
    Assert-Contains $stdoutText "recoveryChanged=true" "Renderer runtime did not observe a restarted backend port in cycle $CycleNumber."
    Assert-Contains $stdoutText "recoveryRequestStatus=200" "Renderer bridge request did not succeed after backend restart in cycle $CycleNumber."
}

$desktopRoot = Split-Path -Parent $PSScriptRoot
$defaultApp = Join-Path $desktopRoot "release\win-unpacked\Device TUI.exe"
$appExe = Resolve-App $AppExecutable $defaultApp
$Cycles = [Math]::Max(1, $Cycles)
$DurationMinutes = [Math]::Max(0, $DurationMinutes)
$PauseSeconds = [Math]::Max(0, $PauseSeconds)
$createdWorkRoot = $false
if (-not $WorkRoot) {
    $WorkRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("device-tui-packaged-app-soak-" + [System.Guid]::NewGuid().ToString("N"))
    $createdWorkRoot = $true
}
$WorkRoot = [System.IO.Path]::GetFullPath($WorkRoot)
$userDataDir = Join-Path $WorkRoot "user-data"
$deadline = if ($DurationMinutes -gt 0) { (Get-Date).AddMinutes($DurationMinutes) } else { $null }
$completedCycles = 0

try {
    New-Item -ItemType Directory -Path $userDataDir -Force | Out-Null
    do {
        $completedCycles += 1
        Invoke-AppRecoveryCycle $appExe $userDataDir (Join-Path $WorkRoot "cycle-$completedCycles") $completedCycles
        if ($PauseSeconds -gt 0) {
            Start-Sleep -Seconds $PauseSeconds
        }
    } while ($completedCycles -lt $Cycles -or ($null -ne $deadline -and (Get-Date) -lt $deadline))

    $backendLog = Join-Path $userDataDir "logs\backend.log"
    if (-not (Test-Path -LiteralPath $backendLog)) {
        throw "Backend lifecycle log was not written: $backendLog"
    }
    $logText = Get-Content -LiteralPath $backendLog -Raw
    Assert-Contains $logText "Crashing Python backend for packaged recovery probe" "Backend recovery probe was not logged."
    Assert-Contains $logText "Python backend exited" "Backend unexpected exit was not logged."
    Assert-Contains $logText "restarting backend" "Backend restart scheduling was not logged."
    $readyCount = ([regex]::Matches($logText, "Python backend ready at")).Count
    $expectedReadyCount = $completedCycles * 2
    if ($readyCount -lt $expectedReadyCount) {
        throw "Backend log did not show two ready handshakes per recovery cycle. ReadyCount=$readyCount Expected=$expectedReadyCount"
    }

    Write-Output "Packaged app soak passed"
    Write-Output "App=$appExe"
    Write-Output "WorkRoot=$WorkRoot"
    Write-Output "CyclesCompleted=$completedCycles"
    Write-Output "DurationMinutes=$DurationMinutes"
    Write-Output "ReadyCount=$readyCount"
}
finally {
    Remove-Item Env:DEVICE_TUI_CAPTURE_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:DEVICE_TUI_CAPTURE_TERMINAL -ErrorAction SilentlyContinue
    Remove-Item Env:DEVICE_TUI_CAPTURE_BACKEND_RECOVERY -ErrorAction SilentlyContinue
    if ($createdWorkRoot -and -not $KeepWorkRoot) {
        $resolvedTemp = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
        if ($WorkRoot.StartsWith($resolvedTemp, [System.StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $WorkRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
