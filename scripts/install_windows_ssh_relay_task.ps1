[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$relayTaskName = "Cheetsheet YouTube SSH Relay"
$relayScriptPath = Join-Path $PSScriptRoot "windows_ssh_relay.ps1"
$relayPowerShell = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"

if (-not (Test-Path -LiteralPath $relayScriptPath -PathType Leaf)) {
    throw "Relay script not found: $relayScriptPath"
}

$relayArguments = @(
    "-NoLogo"
    "-NoProfile"
    "-NonInteractive"
    "-ExecutionPolicy Bypass"
    "-WindowStyle Hidden"
    "-File `"$relayScriptPath`""
) -join " "

$relayAction = New-ScheduledTaskAction `
    -Execute $relayPowerShell `
    -Argument $relayArguments

# Logon starts the relay immediately. The repeating trigger is a watchdog:
# MultipleInstances=IgnoreNew makes it a no-op while healthy, but restarts it
# within one minute if the long-running task exits unexpectedly.
$relayLogonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$relayWatchdogTrigger = New-ScheduledTaskTrigger `
    -Once `
    -At ((Get-Date).AddMinutes(1)) `
    -RepetitionInterval (New-TimeSpan -Minutes 1)

$relayPrincipal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

$relaySettings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Stop-ScheduledTask -TaskName $relayTaskName -ErrorAction SilentlyContinue
Register-ScheduledTask `
    -TaskName $relayTaskName `
    -Action $relayAction `
    -Trigger @($relayLogonTrigger, $relayWatchdogTrigger) `
    -Principal $relayPrincipal `
    -Settings $relaySettings `
    -Description "Maintains and watches the reverse SOCKS relay used for YouTube downloads." `
    -Force | Out-Null
Start-ScheduledTask -TaskName $relayTaskName

Write-Output "Installed and started: $relayTaskName"
