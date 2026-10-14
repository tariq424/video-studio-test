<#
.SYNOPSIS
  Register a Task Scheduler task that runs F:\scripts\start-video-studio.ps1 when you log on.

.DESCRIPTION
  Task "Start Video Studio" (current user, runs only when logged on, no admin rights needed):
    trigger  at logon of this user, 45 s delay (gives Pinokio time to start)
    action   powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File F:\scripts\start-video-studio.ps1 -WaitForPinokio 180
  Re-running this script replaces the task. Remove it with:  .\install-startup-task.ps1 -Remove
  Log of each run: F:\scripts\logs\start-video-studio.log
#>
param([switch]$Remove)

$ErrorActionPreference = 'Stop'
$TaskName = 'Start Video Studio'
$Script   = 'F:\scripts\start-video-studio.ps1'

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed scheduled task '$TaskName'." -ForegroundColor Green
    exit 0
}

if (-not (Test-Path $Script)) { Write-Host "Not found: $Script" -ForegroundColor Red; exit 1 }

$user = "$env:USERDOMAIN\$env:USERNAME"
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Script`" -WaitForPinokio 180"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$trigger.Delay = 'PT45S'
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
    -Description 'Starts Video Studio through Pinokio after logon and opens it in Opera (F:\scripts\start-video-studio.ps1).' -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName' (at logon of $user, 45 s delay)." -ForegroundColor Green
Write-Host "Run it now:   Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Remove it:    powershell -ExecutionPolicy Bypass -File F:\scripts\install-startup-task.ps1 -Remove"
