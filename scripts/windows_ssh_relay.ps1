[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"

$relaySshExecutable = Join-Path $env:WINDIR "System32\OpenSSH\ssh.exe"
$relaySshConfigPath = Join-Path $env:USERPROFILE ".ssh\config"
$relayLogDirectory = Join-Path $env:LOCALAPPDATA "Cheetsheet"
$relayStatusLogPath = Join-Path $relayLogDirectory "youtube-ssh-relay-status.log"

New-Item -ItemType Directory -Force -Path $relayLogDirectory | Out-Null

while ($true) {
    $relayStartedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $relaySessionId = "{0}-{1}" -f (Get-Date -Format "yyyyMMdd-HHmmss"), $PID
    $relaySessionLogPath = Join-Path $relayLogDirectory "youtube-ssh-session-$relaySessionId.log"
    Add-Content -LiteralPath $relayStatusLogPath -Value "[$relayStartedAt] starting SSH reverse SOCKS relay; session=$relaySessionId"

    & $relaySshExecutable `
        -NT `
        -F $relaySshConfigPath `
        -o BatchMode=yes `
        -o ConnectTimeout=20 `
        -o ExitOnForwardFailure=yes `
        -o ServerAliveInterval=10 `
        -o ServerAliveCountMax=2 `
        -o TCPKeepAlive=yes `
        -E $relaySessionLogPath `
        -R 127.0.0.1:17880 `
        hostinger-VPS-new

    $relayExitCode = $LASTEXITCODE
    $relayStoppedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $relayStatusLogPath -Value "[$relayStoppedAt] SSH exited with code $relayExitCode; session=$relaySessionId; reconnecting in 5 seconds"
    Get-ChildItem -LiteralPath $relayLogDirectory -Filter "youtube-ssh-session-*.log" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -Skip 20 |
        Remove-Item -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 5
}
