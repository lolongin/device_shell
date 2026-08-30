param(
    [string]$BackendExecutable = "",
    [string]$WorkRoot = "",
    [int]$SessionCount = 12,
    [int]$Cycles = 3,
    [string]$Command = "display version",
    [switch]$KeepWorkRoot
)

$ErrorActionPreference = "Stop"

function Resolve-Backend([string]$PathValue, [string]$DefaultPath) {
    $candidate = if ($PathValue) { $PathValue } else { $DefaultPath }
    $resolved = Resolve-Path -LiteralPath $candidate -ErrorAction Stop
    return $resolved.Path
}

function Invoke-BackendApi(
    [string]$Method,
    [string]$Path,
    [object]$Body = $null
) {
    $uri = "$script:ApiBase$Path"
    $headers = @{ Authorization = "Bearer $script:Token" }
    if ($null -eq $Body) {
        return Invoke-RestMethod -Uri $uri -Method $Method -Headers $headers -TimeoutSec 30
    }
    return Invoke-RestMethod `
        -Uri $uri `
        -Method $Method `
        -Headers $headers `
        -ContentType "application/json" `
        -Body ($Body | ConvertTo-Json -Depth 8) `
        -TimeoutSec 30
}

function Wait-ForReady([string]$StdoutPath, [System.Diagnostics.Process]$Process) {
    for ($i = 0; $i -lt 80; $i += 1) {
        Start-Sleep -Milliseconds 500
        if (Test-Path -LiteralPath $StdoutPath) {
            $content = Get-Content -LiteralPath $StdoutPath -Raw -ErrorAction SilentlyContinue
            if ($content -match '"type"\s*:\s*"ready"' -and $content -match '"port"\s*:\s*(\d+)') {
                return [int]$Matches[1]
            }
        }
        if ($Process.HasExited) {
            throw "Backend exited before ready. ExitCode=$($Process.ExitCode)"
        }
    }
    throw "Backend did not become ready within 40 seconds."
}

function Wait-ForSessionOutput([string]$SessionId, [string]$Needle) {
    for ($attempt = 0; $attempt -lt 120; $attempt += 1) {
        $log = Invoke-BackendApi "GET" "/api/v1/sessions/$SessionId/log"
        if ([string]$log.content -match [regex]::Escape($Needle)) {
            return
        }
        Start-Sleep -Milliseconds 100
    }
    throw "Session output was not observed for $SessionId"
}

$desktopRoot = Split-Path -Parent $PSScriptRoot
$defaultBackend = Join-Path $desktopRoot "release\win-unpacked\resources\backend\odyterm-backend\odyterm-backend.exe"
$backend = Resolve-Backend $BackendExecutable $defaultBackend
$createdWorkRoot = $false
if (-not $WorkRoot) {
    $WorkRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("odyterm-backend-soak-" + [System.Guid]::NewGuid().ToString("N"))
    $createdWorkRoot = $true
}
$WorkRoot = [System.IO.Path]::GetFullPath($WorkRoot)
$dataRoot = Join-Path $WorkRoot "user-data"
$stdout = Join-Path $WorkRoot "backend.stdout.log"
$stderr = Join-Path $WorkRoot "backend.stderr.log"
$script:Token = "soak-" + [System.Guid]::NewGuid().ToString("N")
$sessions = @()
$process = $null

try {
    New-Item -ItemType Directory -Path $dataRoot -Force | Out-Null
    $env:DEVICE_TUI_DESKTOP_TOKEN = $script:Token
    $env:DEVICE_TUI_DATA_DIR = $dataRoot
    $env:DEVICE_TUI_LEGACY_STATE_PATH = Join-Path $WorkRoot "missing-legacy.json"
    $env:DEVICE_TUI_SESSION_LOG_MAX_BYTES = "1048576"
    $env:DEVICE_TUI_AUDIT_LOG_MAX_BYTES = "1048576"
    $process = Start-Process `
        -FilePath $backend `
        -ArgumentList "--port", "0" `
        -WorkingDirectory (Split-Path -Parent $backend) `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -WindowStyle Hidden `
        -PassThru
    $port = Wait-ForReady $stdout $process
    $script:ApiBase = "http://127.0.0.1:$port"
    $devices = Invoke-BackendApi "GET" "/api/v1/devices"
    $deviceId = [string]$devices.devices[0].id
    if (-not $deviceId) {
        throw "Backend returned no devices."
    }
    for ($index = 0; $index -lt $SessionCount; $index += 1) {
        $session = Invoke-BackendApi "POST" "/api/v1/sessions" @{
            device_id = $deviceId
            kind = "simulated"
            title = "soak-$index"
        }
        $sessions += $session
    }
    for ($cycle = 0; $cycle -lt $Cycles; $cycle += 1) {
        foreach ($session in $sessions) {
            Invoke-BackendApi "POST" "/api/v1/commands/send" @{
                session_id = $session.id
                command = $Command
            } | Out-Null
        }
        foreach ($session in $sessions) {
            Wait-ForSessionOutput ([string]$session.id) "SimOS V1.0"
        }
    }
    $diagnostics = Invoke-BackendApi "GET" "/api/v1/diagnostics"
    foreach ($session in $sessions) {
        Invoke-BackendApi "DELETE" "/api/v1/sessions/$($session.id)" | Out-Null
    }
    Write-Output "Packaged backend soak passed"
    Write-Output "Backend=$backend"
    Write-Output "WorkRoot=$WorkRoot"
    Write-Output "Port=$port"
    Write-Output "SessionCount=$SessionCount"
    Write-Output "Cycles=$Cycles"
    Write-Output "SchemaVersion=$($diagnostics.persistence.schema_version_after)"
    Write-Output "SessionLogMaxBytes=$($diagnostics.log_policy.session_log_max_bytes)"
}
finally {
    Remove-Item Env:DEVICE_TUI_DESKTOP_TOKEN -ErrorAction SilentlyContinue
    Remove-Item Env:DEVICE_TUI_DATA_DIR -ErrorAction SilentlyContinue
    Remove-Item Env:DEVICE_TUI_LEGACY_STATE_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:DEVICE_TUI_SESSION_LOG_MAX_BYTES -ErrorAction SilentlyContinue
    Remove-Item Env:DEVICE_TUI_AUDIT_LOG_MAX_BYTES -ErrorAction SilentlyContinue
    if ($null -ne $process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
    if ($createdWorkRoot -and -not $KeepWorkRoot) {
        $resolvedTemp = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
        if ($WorkRoot.StartsWith($resolvedTemp, [System.StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $WorkRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
