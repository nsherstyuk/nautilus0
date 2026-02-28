# ============================================================
#  XAUUSD ORB Daily Launcher  (v5)
#
#  What it does:
#    1. Verifies IB Gateway is running + API port is open
#    2. Kills any stale orb_live.py processes from yesterday
#    3. Launches orb_live.py for today's session
#
#  IB Gateway lifecycle:
#    - You start Gateway ONCE manually (with login)
#    - Gateway stays running 24/7
#    - AutoRestart=1 in Gateway config handles the daily
#      IBKR reset (~11:45 PM ET) automatically -- no login needed
#    - This script NEVER kills Gateway
#
#  Scheduled at 1:30 AM ET via Task Scheduler.
#  See setup_scheduler.ps1 to create the task.
# ============================================================

$ErrorActionPreference = "Continue"

# ── Paths ────────────────────────────────────────────────────
$ROOT         = "C:\nautilus0"
$PYTHON       = "$ROOT\.venv\Scripts\python.exe"
$LOG_DIR      = "$ROOT\v5_xauusd_orb\logs"
$LOG_FILE     = "$LOG_DIR\daily_launcher.log"

# ── Config ───────────────────────────────────────────────────
$IBKR_PORT            = 4002          # 4002=paper, 4001=live
$PORT_CHECK_RETRIES   = 18            # how many times to check port
$PORT_CHECK_INTERVAL  = 10            # seconds between checks (total wait: 3 min)
$PROCESS_NAME         = "ibgateway"

# ── Helpers ──────────────────────────────────────────────────
function Write-Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "$ts  $msg"
    Write-Host $line
    Add-Content -Path $LOG_FILE -Value $line
}

function Test-Port($port) {
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $tcp.Connect("127.0.0.1", $port)
        $tcp.Close()
        return $true
    } catch {
        return $false
    }
}

# ── Ensure log directory exists ──────────────────────────────
if (-not (Test-Path $LOG_DIR)) {
    New-Item -ItemType Directory -Path $LOG_DIR -Force | Out-Null
}

Write-Log "========================================"
Write-Log "  XAUUSD ORB Daily Launcher starting"
Write-Log "========================================"

# ── Check: is it a weekday? ──────────────────────────────────
$dow = (Get-Date).DayOfWeek
if ($dow -eq "Saturday" -or $dow -eq "Sunday") {
    Write-Log "Weekend ($dow) -- skipping."
    exit 0
}

# ── Step 1: Kill any stale orb_live python processes ─────────
Write-Log "Step 1: Checking for stale orb_live processes..."
$pyProcs = Get-Process python -ErrorAction SilentlyContinue |
    Where-Object {
        try {
            $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)").CommandLine
            $cmdLine -match "orb_live"
        } catch { $false }
    }
if ($pyProcs) {
    Write-Log "  Found $($pyProcs.Count) stale orb_live process(es). Killing..."
    $pyProcs | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep 2
} else {
    Write-Log "  No stale processes."
}

# ── Step 2: Verify Gateway is running ────────────────────────
Write-Log "Step 2: Checking IB Gateway..."
$gw = Get-Process -Name $PROCESS_NAME -ErrorAction SilentlyContinue
if ($gw) {
    Write-Log "  Gateway is RUNNING (PID $($gw.Id))"
} else {
    Write-Log "  WARNING: Gateway is NOT running!"
    Write-Log "  It may still be restarting after the daily IBKR reset."
    Write-Log "  Waiting up to $($PORT_CHECK_RETRIES * $PORT_CHECK_INTERVAL)s..."

    # Wait -- AutoRestart may be bringing it back up
    $gwUp = $false
    for ($i = 1; $i -le $PORT_CHECK_RETRIES; $i++) {
        Start-Sleep $PORT_CHECK_INTERVAL
        $gw2 = Get-Process -Name $PROCESS_NAME -ErrorAction SilentlyContinue
        if ($gw2) {
            Write-Log "  Gateway came back up (PID $($gw2.Id)) after $($i * $PORT_CHECK_INTERVAL)s"
            $gwUp = $true
            break
        }
        Write-Log "  Still waiting... ($i/$PORT_CHECK_RETRIES)"
    }
    if (-not $gwUp) {
        Write-Log "  ERROR: Gateway did not come back."
        Write-Log "  You need to start IB Gateway manually and log in."
        Write-Log "  Aborting today's session."
        exit 1
    }
}

# ── Step 3: Wait for API port ────────────────────────────────
Write-Log "Step 3: Waiting for API port $IBKR_PORT..."
$portReady = $false
for ($i = 1; $i -le $PORT_CHECK_RETRIES; $i++) {
    if (Test-Port $IBKR_PORT) {
        Write-Log "  Port $IBKR_PORT is OPEN"
        $portReady = $true
        break
    }
    Write-Log "  Port not ready yet ($i/$PORT_CHECK_RETRIES)..."
    Start-Sleep $PORT_CHECK_INTERVAL
}

if (-not $portReady) {
    Write-Log "  ERROR: API port $IBKR_PORT not available."
    Write-Log "  Gateway may need manual attention."
    Write-Log "  Aborting today's session."
    exit 1
}

# ── Step 4: Launch orb_live.py ───────────────────────────────
Write-Log "Step 4: Launching orb_live.py..."
$orbArgs = "-m v5_xauusd_orb.orb_live"

# Uncomment for dry run:
# $orbArgs = "-m v5_xauusd_orb.orb_live --dry-run"

Set-Location $ROOT
Write-Log "  Command: $PYTHON $orbArgs"

# Run orb_live.py in foreground (Task Scheduler keeps it alive).
# It exits on its own when the trade window closes (~11 AM EST).
& $PYTHON $orbArgs.Split(" ")
$exitCode = $LASTEXITCODE

Write-Log "orb_live.py exited with code $exitCode"
Write-Log "Daily session complete."
Write-Log "========================================"
