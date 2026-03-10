param(
    [string]$ExePath = "C:/Program Files (x86)/Steam/steamapps/common/Slay the Spire 2/SlayTheSpire2.exe",
    [int]$Attempts = 40,
    [int]$DelaySeconds = 2,
    [string]$Command = "help",
    [switch]$EnableDebugActions
)

$ErrorActionPreference = "Stop"

function Wait-ForHealth {
    param(
        [int]$MaxAttempts,
        [int]$SleepSeconds,
        [System.Diagnostics.Process]$Process
    )

    for ($i = 0; $i -lt $MaxAttempts; $i++) {
        Start-Sleep -Seconds $SleepSeconds

        try {
            $response = Invoke-WebRequest -Uri "http://127.0.0.1:8080/health" -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                return
            }
        } catch {
        }

        if ($Process.HasExited) {
            throw "Game process exited before /health became ready."
        }
    }

    throw "Timed out waiting for /health."
}

function Invoke-ActionJson {
    param(
        [string]$ActionName,
        [string]$ConsoleCommand
    )

    $body = @{
        action = $ActionName
        command = $ConsoleCommand
    } | ConvertTo-Json

    try {
        $response = Invoke-WebRequest -Method Post -Uri "http://127.0.0.1:8080/action" -ContentType "application/json" -Body $body -UseBasicParsing -TimeoutSec 5
        return $response.Content | ConvertFrom-Json
    } catch {
        if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
            return $_.ErrorDetails.Message | ConvertFrom-Json
        }

        if ($_.Exception.Response -and $_.Exception.Response.GetResponseStream()) {
            $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
            $content = $reader.ReadToEnd()
            if ($content) {
                return $content | ConvertFrom-Json
            }
        }

        throw
    }
}

$previousEnv = $env:STS2_ENABLE_DEBUG_ACTIONS

if ($EnableDebugActions) {
    [System.Environment]::SetEnvironmentVariable("STS2_ENABLE_DEBUG_ACTIONS", "1", "Process")
    $env:STS2_ENABLE_DEBUG_ACTIONS = "1"
} else {
    [System.Environment]::SetEnvironmentVariable("STS2_ENABLE_DEBUG_ACTIONS", $null, "Process")
    Remove-Item Env:STS2_ENABLE_DEBUG_ACTIONS -ErrorAction SilentlyContinue
}

$existing = Get-Process -Name "SlayTheSpire2" -ErrorAction SilentlyContinue
if ($existing) {
    Stop-Process -Id $existing.Id -Force
    Start-Sleep -Seconds 2
}

$startInfo = New-Object System.Diagnostics.ProcessStartInfo
$startInfo.FileName = $ExePath
$startInfo.UseShellExecute = $false

if ($EnableDebugActions) {
    $startInfo.EnvironmentVariables["STS2_ENABLE_DEBUG_ACTIONS"] = "1"
} else {
    $startInfo.EnvironmentVariables.Remove("STS2_ENABLE_DEBUG_ACTIONS")
}

$proc = [System.Diagnostics.Process]::Start($startInfo)

try {
    Wait-ForHealth -MaxAttempts $Attempts -SleepSeconds $DelaySeconds -Process $proc
    $result = Invoke-ActionJson -ActionName "run_console_command" -ConsoleCommand $Command

    if ($EnableDebugActions) {
        if (-not $result.ok -or $result.data.status -ne "completed") {
            throw "Expected debug command to succeed, but received: $($result | ConvertTo-Json -Depth 6 -Compress)"
        }
    } else {
        if ($result.ok -or $result.error.code -ne "invalid_action") {
            throw "Expected invalid_action while debug actions are disabled, but received: $($result | ConvertTo-Json -Depth 6 -Compress)"
        }
    }

    [pscustomobject]@{
        debug_actions_enabled = [bool]$EnableDebugActions
        ok = $result.ok
        status = $result.data.status
        error_code = $result.error.code
        message = if ($result.ok) { $result.data.message } else { $result.error.message }
    } | ConvertTo-Json -Compress
}
finally {
    if (-not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force
    }

    [System.Environment]::SetEnvironmentVariable("STS2_ENABLE_DEBUG_ACTIONS", $previousEnv, "Process")

    if ($null -eq $previousEnv) {
        Remove-Item Env:STS2_ENABLE_DEBUG_ACTIONS -ErrorAction SilentlyContinue
    } else {
        $env:STS2_ENABLE_DEBUG_ACTIONS = $previousEnv
    }
}
