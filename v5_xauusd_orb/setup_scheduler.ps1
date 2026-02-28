# ============================================================
#  Setup Windows Task Scheduler for XAUUSD ORB  (v5)
#
#  Run this ONCE (as Administrator) to create:
#    - "XAUUSD_ORB_Daily" task at 1:30 AM ET, Mon-Fri
#
#  To verify:   taskschd.msc  (or: schtasks /query /tn "XAUUSD_ORB_Daily")
#  To delete:   schtasks /delete /tn "XAUUSD_ORB_Daily" /f
#  To run now:  schtasks /run /tn "XAUUSD_ORB_Daily"
#  To disable:  schtasks /change /tn "XAUUSD_ORB_Daily" /disable
# ============================================================

$ErrorActionPreference = "Stop"

$ROOT        = "C:\nautilus0"
$TASK_NAME   = "XAUUSD_ORB_Daily"
$PS_EXE      = "powershell.exe"
$SCRIPT_PATH = "$ROOT\v5_xauusd_orb\daily_launcher.ps1"

# ── Auto-detect timezone and set trigger time ────────────────
# We need the script to run at ~6:30 UTC (after IBKR reset,
# before London open at 08:00 UTC).
# Task Scheduler uses LOCAL time, so we convert:
#   ET (UTC-5): 6:30 UTC = 1:30 AM ET
#   PT (UTC-8): 6:30 UTC = 10:30 PM PT (previous night!)
#   CT (UTC-6): 6:30 UTC = 12:30 AM CT
$utcOffset = [System.TimeZoneInfo]::Local.BaseUtcOffset.TotalHours
$targetUtcHour = 6.5   # 6:30 UTC
$localHour = $targetUtcHour + $utcOffset
if ($localHour -lt 0) { $localHour += 24 }
$triggerHour = [math]::Floor($localHour)
$triggerMin  = [int](($localHour - $triggerHour) * 60)
$START_TIME  = "{0:D2}:{1:D2}" -f $triggerHour, $triggerMin

Write-Host "  Your timezone: $([System.TimeZoneInfo]::Local.Id) (UTC$utcOffset)"
Write-Host "  Target: 6:30 UTC = $START_TIME local time"

# ── Verify prerequisites ────────────────────────────────────
if (-not (Test-Path $SCRIPT_PATH)) {
    Write-Host "ERROR: Script not found: $SCRIPT_PATH" -ForegroundColor Red
    exit 1
}

# ── Check admin ──────────────────────────────────────────────
$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host ""
    Write-Host "WARNING: Not running as Administrator." -ForegroundColor Yellow
    Write-Host "The task will be created to run only when you are logged in."
    Write-Host "For 'run whether user is logged on or not', re-run as Admin."
    Write-Host ""
}

# ── Remove existing task if present ──────────────────────────
$existing = schtasks /query /tn $TASK_NAME 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "Removing existing task '$TASK_NAME'..."
    schtasks /delete /tn $TASK_NAME /f | Out-Null
}

# ── Create the scheduled task via XML (more control) ─────────
# Using COM objects for cleaner task creation
$svc = New-Object -ComObject Schedule.Service
$svc.Connect()
$folder = $svc.GetFolder("\")

$taskDef = $svc.NewTask(0)

# ── Settings ─────────────────────────────────────────────────
$settings = $taskDef.Settings
$settings.Enabled = $true
$settings.AllowDemandStart = $true
$settings.StopIfGoingOnBatteries = $false
$settings.DisallowStartIfOnBatteries = $false
$settings.StartWhenAvailable = $true            # if missed (PC off), run on next wake
$settings.ExecutionTimeLimit = "PT14H"           # kill if still running after 14 hours
$settings.WakeToRun = $true                      # wake PC from sleep to run
$settings.RestartInterval = "PT5M"               # on failure, retry after 5 min
$settings.RestartCount = 3                       # max 3 retries

# ── Trigger: Daily at 1:30 AM, Mon-Fri ──────────────────────
$trigger = $taskDef.Triggers.Create(2)  # 2 = daily trigger
$trigger.StartBoundary = (Get-Date -Hour 1 -Minute 30 -Second 0).ToString("yyyy-MM-ddTHH:mm:ss")
$trigger.Enabled = $true

# Weekly trigger gives weekday control -- recreate as weekly
$taskDef.Triggers.Clear()
$weeklyTrigger = $taskDef.Triggers.Create(3)  # 3 = weekly trigger
$weeklyTrigger.StartBoundary = (Get-Date -Hour $triggerHour -Minute $triggerMin -Second 0).ToString("yyyy-MM-ddTHH:mm:ss")
$weeklyTrigger.DaysOfWeek = 0x3E  # Mon(2)+Tue(4)+Wed(8)+Thu(16)+Fri(32) = 62 = 0x3E
$weeklyTrigger.WeeksInterval = 1
$weeklyTrigger.Enabled = $true

# ── Action: Run PowerShell script ────────────────────────────
$action = $taskDef.Actions.Create(0)  # 0 = exec
$action.Path = $PS_EXE
$action.Arguments = "-ExecutionPolicy Bypass -NoProfile -File `"$SCRIPT_PATH`""
$action.WorkingDirectory = $ROOT

# ── Description ──────────────────────────────────────────────
$taskDef.RegistrationInfo.Description = "XAUUSD ORB: Launch daily trading script at $START_TIME local ($([System.TimeZoneInfo]::Local.Id)), Mon-Fri"

# ── Register the task ────────────────────────────────────────
# 6 = TASK_CREATE_OR_UPDATE, 3 = TASK_LOGON_INTERACTIVE_TOKEN
try {
    $folder.RegisterTaskDefinition($TASK_NAME, $taskDef, 6, $null, $null, 3) | Out-Null
    Write-Host ""
    Write-Host "SUCCESS: Task '$TASK_NAME' created!" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Schedule:     Daily at $START_TIME (Mon-Fri, $([System.TimeZoneInfo]::Local.Id))"
    Write-Host "  Script:       $SCRIPT_PATH"
    Write-Host "  Wake from sleep: YES"
    Write-Host "  Start if missed: YES (runs on next wake/logon)"
    Write-Host ""
    Write-Host "Useful commands:" -ForegroundColor Cyan
    Write-Host "  View:         taskschd.msc  (GUI)"
    Write-Host "  Status:       schtasks /query /tn `"$TASK_NAME`" /v /fo list"
    Write-Host "  Run now:      schtasks /run /tn `"$TASK_NAME`""
    Write-Host "  Disable:      schtasks /change /tn `"$TASK_NAME`" /disable"
    Write-Host "  Delete:       schtasks /delete /tn `"$TASK_NAME`" /f"
    Write-Host ""
    Write-Host "NOTE: Wednesday is included in the schedule because the"
    Write-Host "      orb_live.py script handles Wed skip internally."
    Write-Host "      This way Gateway stays fresh even on skip days."
    Write-Host ""
} catch {
    Write-Host "ERROR: Failed to create task: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "If you see 'Access denied', try running as Administrator:" -ForegroundColor Yellow
    Write-Host "  Right-click PowerShell -> Run as Administrator"
    Write-Host "  Then run this script again."
    exit 1
}
