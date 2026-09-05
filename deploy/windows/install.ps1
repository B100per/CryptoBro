# Register the collector, the retention rollup and the control panel as
# Windows scheduled tasks. The Windows twin of the Mac's launchd plists and
# deploy/*.service. Run from any directory, no admin needed:
#
#   powershell -ExecutionPolicy Bypass -File deploy\windows\install.ps1
#   powershell -ExecutionPolicy Bypass -File deploy\windows\install.ps1 -NoStart
#
# The tasks run as the user who runs this script, from logon, with no
# window (hidden.vbs). Like the launchd user agents they replace, they need
# that user logged in: a reboot nobody logs in after runs nothing.
# ponytail: a "run whether logged on or not" task (S4U logon) needs an
# elevated shell to register; switch the principal to that if it matters.
param([switch]$NoStart)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Resolve-Path (Join-Path $here "..\..")
New-Item -ItemType Directory -Force (Join-Path $root "logs") | Out-Null

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$forever = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$oneShot = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew `
    -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$hidden = { param($script) New-ScheduledTaskAction -Execute "wscript.exe" `
    -Argument "`"$(Join-Path $here 'hidden.vbs')`" `"$(Join-Path $here $script)`"" -WorkingDirectory $root }
$atLogon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$tasks = @(
    @{ Name = "CryptoBro collector"; Action = (& $hidden "collector.cmd"); Trigger = $atLogon; Settings = $forever
       Description = "5m klines + positioning into data.db, forever. Restarted a minute after any exit." },
    @{ Name = "CryptoBro retention"; Action = (& $hidden "retention.cmd"); Trigger = (New-ScheduledTaskTrigger -Daily -At 04:30); Settings = $oneShot
       Description = "Roll bars older than 45 days up to hourly and VACUUM data.db." },
    @{ Name = "CryptoBro control"; Action = (& $hidden "control.cmd"); Trigger = $atLogon; Settings = $forever
       Description = "Control panel and both paper books on http://127.0.0.1:8787 (token in .env)." }
)
foreach ($t in $tasks) {
    Register-ScheduledTask -TaskName $t.Name -Action $t.Action -Trigger $t.Trigger -Settings $t.Settings `
        -Principal $principal -Description $t.Description -Force | Out-Null
    Write-Host "registered: $($t.Name)"
}
if (-not $NoStart) {
    # Not the collector: install.sh backfills first, and two writers on one
    # sqlite file is a lock fight. Start it when the backfill is done:
    #   Start-ScheduledTask "CryptoBro collector"
    Start-ScheduledTask "CryptoBro control"
    Write-Host "started: CryptoBro control -> http://127.0.0.1:8787"
}
Get-ScheduledTask "CryptoBro *" | Format-Table TaskName, State -AutoSize
