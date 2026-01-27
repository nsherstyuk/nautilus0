param(
    [int]$WaitSeconds = 2
)

$ErrorActionPreference = 'SilentlyContinue'

$repoRoot = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $repoRoot 'live\run_live_mtf_v2_entry_confirmed_v2.py'
$toggle = Join-Path $repoRoot 'scripts\toggle_debug.py'

Write-Host "Stopping existing live runner processes..."

# Kill any python process whose command line contains the runner name
Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -and ($_.CommandLine -like "*run_live_mtf_v2_entry_confirmed_v2.py*") } |
    ForEach-Object {
        Write-Host "Stopping PID $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force
    }

Start-Sleep -Seconds $WaitSeconds

Write-Host "Ensuring console debug is OFF..."
python $toggle off

Write-Host "Starting live runner..."
python $runner
