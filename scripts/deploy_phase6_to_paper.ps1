# PowerShell
# Phase 6 Live Deployment to IBKR Paper Trading
# Version: 1.0
# Description: Orchestrates Phase 6 parameter deployment to IBKR paper trading account.

[CmdletBinding()]
param(
    [int]$Rank = 1,
    [string]$Output = ".env.phase6",
    [switch]$DryRun,
    [switch]$SkipValidation,
    [switch]$Force,
    [double]$AccountBalance,
    [switch]$Help
)

$ErrorActionPreference = 'Stop'

# Color constants
$Cyan = 'Cyan'
$Green = 'Green'
$Yellow = 'Yellow'
$Red = 'Red'
$Gray = 'Gray'

$script:PythonCommandParts = @("python")

function Show-Usage {
    Write-Host "" -ForegroundColor $Cyan
    Write-Host "Phase 6 Live Deployment to IBKR Paper Trading (v1.0)" -ForegroundColor $Cyan
    Write-Host "" -ForegroundColor $Cyan
    Write-Host "This script deploys optimized Phase 6 parameters to your .env for IBKR paper trading." -ForegroundColor $Gray
    Write-Host "It orchestrates tools/deploy_phase6_config.py with optional validation and safety checks." -ForegroundColor $Gray
    Write-Host "" -ForegroundColor $Cyan
    Write-Host "Parameters:" -ForegroundColor $Cyan
    Write-Host "  -Rank <int>              Phase 6 configuration rank to deploy (1-10). Default: 1" -ForegroundColor $Gray
    Write-Host "  -Output <string>          Output path for generated .env file. Default: .env.phase6" -ForegroundColor $Gray
    Write-Host "  -DryRun                   Preview deployment without making changes" -ForegroundColor $Gray
    Write-Host "  -SkipValidation           Skip validation checks (not recommended)" -ForegroundColor $Gray
    Write-Host "  -Force                    Overwrite existing files without prompting" -ForegroundColor $Gray
    Write-Host "  -AccountBalance <float>   Account balance for position sizing validation (optional)" -ForegroundColor $Gray
    Write-Host "  -Help                     Show this help and exit" -ForegroundColor $Gray
    Write-Host "" -ForegroundColor $Cyan
    Write-Host "Examples:" -ForegroundColor $Cyan
    Write-Host "  .\\scripts\\deploy_phase6_to_paper.ps1 -Rank 1" -ForegroundColor $Gray
    Write-Host "  .\\scripts\\deploy_phase6_to_paper.ps1 -Rank 2 -DryRun" -ForegroundColor $Gray
    Write-Host "  .\\scripts\\deploy_phase6_to_paper.ps1 -Rank 1 -AccountBalance 50000 -Force" -ForegroundColor $Gray
}

function Test-PythonAvailable {
    try {
        $versionOutput = (& python --version 2>&1)
        if ($LASTEXITCODE -eq 0 -or $versionOutput) {
            $script:PythonCommandParts = @("python")
            Write-Host "Python detected: $versionOutput" -ForegroundColor $Gray
            return $true
        }
    } catch {
        # ignore and try Windows launcher
    }
    try {
        $versionOutput = (& py -3 --version 2>&1)
        if ($LASTEXITCODE -eq 0 -or $versionOutput) {
            $script:PythonCommandParts = @("py", "-3")
            Write-Host "Python detected (via Windows launcher): $versionOutput" -ForegroundColor $Gray
            return $true
        }
    } catch {
        # ignore
    }
    return $false
}

$script:PaperPortDetected = $null
$script:LivePortDetected = $null
function Test-IBKRConnection {
    $paperPorts = @(7497, 4002)
    $livePorts = @(7496, 4001)
    $script:PaperPortDetected = $null
    $script:LivePortDetected = $null
    foreach ($p in $paperPorts) {
        try {
            $res = Test-NetConnection -ComputerName 'localhost' -Port $p -WarningAction SilentlyContinue
            if ($res.TcpTestSucceeded) {
                $script:PaperPortDetected = $p
                return $true
            }
        } catch {
            # ignore
        }
    }
    foreach ($p in $livePorts) {
        try {
            $res = Test-NetConnection -ComputerName 'localhost' -Port $p -WarningAction SilentlyContinue
            if ($res.TcpTestSucceeded) {
                $script:LivePortDetected = $p
                break
            }
        } catch {
            # ignore
        }
    }
    return $false
}

function Backup-EnvFile([string]$EnvPath) {
    if (Test-Path -LiteralPath $EnvPath) {
        $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $backup = "$EnvPath.backup.$timestamp"
        Copy-Item -LiteralPath $EnvPath -Destination $backup -Force
        Write-Host "Backup created: $backup" -ForegroundColor $Gray
        return $backup
    }
    return $null
}

function Show-PreFlightChecklist([int]$Rank, [string]$Output, [bool]$DryRun, [bool]$SkipValidation, [bool]$Force) {
    Write-Host "" -ForegroundColor $Cyan
    Write-Host "Pre-flight checklist" -ForegroundColor $Cyan
    Write-Host " - Load Phase 6 configuration (Rank: $Rank)" -ForegroundColor $Gray
    if (-not $SkipValidation) {
        Write-Host " - Run validation checks" -ForegroundColor $Gray
    } else {
        Write-Host " - Skip validation checks (NOT RECOMMENDED)" -ForegroundColor $Yellow
    }
    Write-Host " - Generate .env file: $Output" -ForegroundColor $Gray
    if (Test-Path -LiteralPath ".env") {
        Write-Host " - Backup existing .env" -ForegroundColor $Gray
        Write-Host " - Copy $Output to .env" -ForegroundColor $Gray
    } else {
        Write-Host " - No existing .env to backup" -ForegroundColor $Gray
        Write-Host " - Copy $Output to .env" -ForegroundColor $Gray
    }
    if ($DryRun) {
        Write-Host " - Dry run: no files will be modified" -ForegroundColor $Yellow
    }
    if ($Force -or $DryRun) {
        return $true
    }
    $resp = Read-Host "Proceed with deployment? [y/N]"
    if ([string]::IsNullOrWhiteSpace($resp)) { return $false }
    $respNorm = $resp.Trim().ToLowerInvariant()
    return @('y','yes') -contains $respNorm
}

try {
    if ($Help) {
        Show-Usage
        exit 0
    }

    Write-Host "============================================================" -ForegroundColor $Cyan
    Write-Host "Phase 6 Live Deployment to IBKR Paper Trading (v1.0)" -ForegroundColor $Cyan
    Write-Host "============================================================" -ForegroundColor $Cyan
    Write-Host "" -ForegroundColor $Cyan

    # Ensure working directory is repository root
    $repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
    Set-Location -LiteralPath $repoRoot

    Write-Host "Performing pre-flight checks..." -ForegroundColor $Cyan

    if (-not (Test-PythonAvailable)) {
        Write-Error "Python not found or not in PATH. Please install Python 3.10+ and ensure 'python' is available."
        exit 1
    }

    if (-not (Test-Path -LiteralPath "tools/deploy_phase6_config.py")) {
        Write-Error "Required tool not found: tools/deploy_phase6_config.py"
        exit 1
    }

    if (-not (Test-Path -LiteralPath "optimization/results/phase6_refinement_results_top_10.json")) {
        Write-Error "Phase 6 results not found: optimization/results/phase6_refinement_results_top_10.json"
        Write-Host "Run Phase 6 optimization before deployment." -ForegroundColor $Yellow
        exit 1
    }

    if (-not (Test-Path -LiteralPath ".env.example")) {
        Write-Host "Warning: .env.example not found (for reference)." -ForegroundColor $Yellow
    }

    Write-Host "`u2713 All pre-flight checks passed." -ForegroundColor $Green

    Write-Host "" -ForegroundColor $Cyan
    Write-Host "Checking IBKR connection..." -ForegroundColor $Cyan
    $paperReady = Test-IBKRConnection
    if ($paperReady) {
        Write-Host "IBKR paper trading port detected on port $script:PaperPortDetected. Use paper ports 7497/4002 for this deployment." -ForegroundColor $Green
    } elseif ($script:LivePortDetected) {
        Write-Host "IBKR live trading port detected on port $script:LivePortDetected, but no paper port was found. For this deployment, ensure paper TWS (7497) or Gateway (4002) is running." -ForegroundColor $Yellow
    } else {
        Write-Host "IBKR TWS/Gateway not detected. Ensure it's running before starting live trading." -ForegroundColor $Yellow
    }

    if (-not (Show-PreFlightChecklist -Rank $Rank -Output $Output -DryRun ([bool]$DryRun) -SkipValidation ([bool]$SkipValidation) -Force ([bool]$Force))) {
        Write-Host "Deployment cancelled." -ForegroundColor $Yellow
        exit 0
    }

    $command = @() + $script:PythonCommandParts + @("tools/deploy_phase6_config.py", "--rank", "$Rank", "--output", "$Output", "--verbose")
    if ($DryRun) { $command += "--dry-run" }
    if ($SkipValidation) { $command += "--skip-validation" }
    if ($Force) { $command += "--force" }
    if ($PSBoundParameters.ContainsKey('AccountBalance')) {
        $command += @("--account-balance", "$AccountBalance")
    }

    Write-Host "" -ForegroundColor $Cyan
    Write-Host "Executing Phase 6 deployment tool..." -ForegroundColor $Cyan
    Write-Host ("Command: " + ($command -join ' ')) -ForegroundColor $Gray

    & $command[0] $command[1..($command.Length-1)]
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        Write-Error "Deployment tool failed with exit code $exitCode."
        exit $exitCode
    }

    Write-Host "`u2713 Deployment tool completed successfully." -ForegroundColor $Green

    if (-not $DryRun) {
        if (-not (Test-Path -LiteralPath $Output)) {
            Write-Error "Expected output file '$Output' was not created. Aborting."
            exit 1
        }
        Write-Host "" -ForegroundColor $Cyan
        Write-Host "Backing up existing .env file..." -ForegroundColor $Cyan
        $backupPath = Backup-EnvFile ".env"
        if ($backupPath) {
            Write-Host "Backup path: $backupPath" -ForegroundColor $Gray
        } else {
            Write-Host "No existing .env found; skipping backup." -ForegroundColor $Gray
        }

        Write-Host "Copying Phase 6 configuration to active .env..." -ForegroundColor $Cyan
        try {
            Copy-Item -LiteralPath $Output -Destination ".env" -Force
            Write-Host "`u2713 Active .env file updated." -ForegroundColor $Green
        } catch {
            Write-Error "Failed to copy $Output to .env. $($_.Exception.Message)"
            exit 1
        }

        Write-Host "" -ForegroundColor $Cyan
        Write-Host "------------------------------------------------------------" -ForegroundColor $Cyan
        Write-Host "DEPLOYMENT COMPLETE" -ForegroundColor $Green
        Write-Host "Next steps:" -ForegroundColor $Cyan
        Write-Host " 1. Review deployment summary: ${Output}_summary.txt" -ForegroundColor $Gray
        Write-Host " 2. Verify IBKR TWS/Gateway is running (port 7497 for paper trading)" -ForegroundColor $Gray
        Write-Host " 3. Configure IBKR in .env: IB_HOST, IB_PORT, IB_CLIENT_ID, IB_ACCOUNT_ID" -ForegroundColor $Gray
        Write-Host " 4. Start live trading: python live/run_live.py" -ForegroundColor $Gray
        Write-Host " 5. Monitor logs: logs/live/" -ForegroundColor $Gray
        if ($backupPath) {
            Write-Host "Rollback: Copy backup file back to .env" -ForegroundColor $Yellow
            Write-Host "Backup location: $backupPath" -ForegroundColor $Yellow
        }
    } else {
        Write-Host "Dry run complete. No files were modified." -ForegroundColor $Yellow
    }

    exit 0
} catch {
    if ($_.Exception -is [System.Management.Automation.PipelineStoppedException] -or $_.Exception -is [System.OperationCanceledException]) {
        Write-Host "Interrupted by user" -ForegroundColor $Yellow
        exit 130
    }
    Write-Error ("Unexpected error: " + $_.Exception.Message)
    exit 1
}


