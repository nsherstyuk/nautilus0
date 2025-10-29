#!/bin/bash
# Phase 6 Live Deployment to IBKR Paper Trading
# Version: 1.0
# Description: Orchestrates Phase 6 parameter deployment to IBKR paper trading account.

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GRAY='\033[0;37m'
NC='\033[0m'

# Determine repository root and set as working directory
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"
cd "$repo_root"

# Defaults
RANK=1
OUTPUT=".env.phase6"
DRY_RUN=false
SKIP_VALIDATION=false
FORCE=false
ACCOUNT_BALANCE=""
PYTHON_CMD="python3"

print_status() { echo -e "${GREEN}$1${NC}"; }
print_warning() { echo -e "${YELLOW}$1${NC}"; }
print_error() { echo -e "${RED}$1${NC}"; }
print_info() { echo -e "${CYAN}$1${NC}"; }
print_gray() { echo -e "${GRAY}$1${NC}"; }

show_usage() {
  echo -e "${CYAN}Phase 6 Live Deployment to IBKR Paper Trading (v1.0)${NC}"
  echo "This script deploys optimized Phase 6 parameters to your .env for IBKR paper trading."
  echo ""
  echo "Options:"
  echo "  -r, --rank <int>             Phase 6 configuration rank to deploy (1-10). Default: 1"
  echo "  -o, --output <path>          Output path for generated .env file. Default: .env.phase6"
  echo "  -d, --dry-run                Preview deployment without making changes"
  echo "  -s, --skip-validation        Skip validation checks (not recommended)"
  echo "  -f, --force                  Overwrite existing files without prompting"
  echo "  -b, --account-balance <num>  Account balance for position sizing validation (optional)"
  echo "  -h, --help                   Show this help and exit"
  echo ""
  echo "Examples:"
  echo "  ./scripts/deploy_phase6_to_paper.sh --rank 1"
  echo "  ./scripts/deploy_phase6_to_paper.sh --rank 2 --dry-run"
  echo "  ./scripts/deploy_phase6_to_paper.sh --rank 1 --account-balance 50000 --force"
}

test_python_available() {
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD="python3"
    print_gray "Python detected: $($PYTHON_CMD --version 2>&1)"
    return 0
  elif command -v python >/dev/null 2>&1; then
    PYTHON_CMD="python"
    print_gray "Python detected: $($PYTHON_CMD --version 2>&1)"
    return 0
  else
    return 1
  fi
}

detected_paper_port=""
detected_live_port=""

port_open() {
  local p="$1"
  if command -v nc >/dev/null 2>&1; then
    nc -z localhost "$p" >/dev/null 2>&1
  else
    "$PYTHON_CMD" -c 'import socket,sys; s=socket.socket(); s.settimeout(1); port=int(sys.argv[1]);
try:
    s.connect(("127.0.0.1", port)); s.close(); sys.exit(0)
except Exception:
    sys.exit(1)' "$p"
  fi
}

test_ibkr_connection() {
  local p
  local paper_ports=(7497 4002)
  local live_ports=(7496 4001)
  detected_paper_port=""
  detected_live_port=""
  for p in "${paper_ports[@]}"; do
    if port_open "$p"; then
      detected_paper_port="$p"
      return 0
    fi
  done
  for p in "${live_ports[@]}"; do
    if port_open "$p"; then
      detected_live_port="$p"
      break
    fi
  done
  return 1
}

backup_env_file() {
  if [[ -f ".env" ]]; then
    local ts
    ts=$(date +%Y%m%d_%H%M%S)
    local backup=".env.backup.${ts}"
    cp .env "$backup"
    echo "$backup"
  else
    echo ""
  fi
}

show_preflight_checklist() {
  print_info "Pre-flight checklist"
  print_gray " - Load Phase 6 configuration (Rank: ${RANK} )"
  if [[ "$SKIP_VALIDATION" == "true" ]]; then
    print_warning " - Skip validation checks (NOT RECOMMENDED)"
  else
    print_gray " - Run validation checks"
  fi
  print_gray " - Generate .env file: ${OUTPUT}"
  if [[ -f ".env" ]]; then
    print_gray " - Backup existing .env"
    print_gray " - Copy ${OUTPUT} to .env"
  else
    print_gray " - No existing .env to backup"
    print_gray " - Copy ${OUTPUT} to .env"
  fi
  if [[ "$DRY_RUN" == "true" ]]; then
    print_warning " - Dry run: no files will be modified"
  fi
  if [[ "$FORCE" == "true" || "$DRY_RUN" == "true" ]]; then
    return 0
  fi
  read -rp "Proceed with deployment? [y/N]: " response || true
  case "${response,,}" in
    y|yes) return 0 ;;
    *) return 1 ;;
  esac
}

trap 'print_warning "Interrupted by user"; exit 130' INT

# Argument parsing
while [[ $# -gt 0 ]]; do
  case "$1" in
    -r|--rank)
      RANK="$2"; shift 2;;
    -o|--output)
      OUTPUT="$2"; shift 2;;
    -d|--dry-run)
      DRY_RUN=true; shift;;
    -s|--skip-validation)
      SKIP_VALIDATION=true; shift;;
    -f|--force)
      FORCE=true; shift;;
    -b|--account-balance)
      ACCOUNT_BALANCE="$2"; shift 2;;
    -h|--help)
      show_usage; exit 0;;
    *)
      print_error "Unknown option: $1"; show_usage; exit 1;;
  esac
done

print_info "============================================================"
print_info "Phase 6 Live Deployment to IBKR Paper Trading (v1.0)"
print_info "============================================================"

print_info "Performing pre-flight checks..."
if ! test_python_available; then
  print_error "Python not found or not in PATH. Please install Python 3.10+ and ensure 'python' or 'python3' is available."
  exit 1
fi

if [[ ! -f "tools/deploy_phase6_config.py" ]]; then
  print_error "Required tool not found: tools/deploy_phase6_config.py"
  exit 1
fi

if [[ ! -f "optimization/results/phase6_refinement_results_top_10.json" ]]; then
  print_error "Phase 6 results not found: optimization/results/phase6_refinement_results_top_10.json"
  print_warning "Run Phase 6 optimization before deployment."
  exit 1
fi

if [[ ! -f ".env.example" ]]; then
  print_warning ".env.example not found (for reference)."
fi

print_status "\xE2\x9C\x93 All pre-flight checks passed."

print_info "Checking IBKR connection..."
if test_ibkr_connection; then
  print_status "IBKR paper trading port detected on ${detected_paper_port}. Use paper ports 7497/4002 for this deployment."
else
  if [[ -n "$detected_live_port" ]]; then
    print_warning "IBKR live trading port detected on ${detected_live_port}, but no paper port found. For this deployment, ensure paper TWS (7497) or Gateway (4002) is running."
  else
    print_warning "IBKR TWS/Gateway not detected on paper or live ports."
  fi
fi

if ! show_preflight_checklist; then
  print_warning "Deployment cancelled."
  exit 0
fi

COMMAND=("$PYTHON_CMD" "tools/deploy_phase6_config.py" "--rank" "$RANK" "--output" "$OUTPUT" "--verbose")
[[ "$DRY_RUN" == "true" ]] && COMMAND+=("--dry-run")
[[ "$SKIP_VALIDATION" == "true" ]] && COMMAND+=("--skip-validation")
[[ "$FORCE" == "true" ]] && COMMAND+=("--force")
[[ -n "$ACCOUNT_BALANCE" ]] && COMMAND+=("--account-balance" "$ACCOUNT_BALANCE")

print_info "Executing Phase 6 deployment tool..."
print_gray "Command: ${COMMAND[*]}"
"${COMMAND[@]}"

print_status "\xE2\x9C\x93 Deployment tool completed successfully."

if [[ "$DRY_RUN" == "false" ]]; then
  if [[ ! -f "$OUTPUT" ]]; then
    print_error "Expected output file '$OUTPUT' was not created. Aborting."
    exit 1
  fi
  print_info "Backing up existing .env file..."
  BACKUP_PATH=$(backup_env_file)
  if [[ -n "$BACKUP_PATH" ]]; then
    print_gray "Backup path: $BACKUP_PATH"
  else
    print_gray "No existing .env found; skipping backup."
  fi
  print_info "Copying Phase 6 configuration to active .env..."
  cp "$OUTPUT" ".env"
  print_status "\xE2\x9C\x93 Active .env file updated."
  print_info "------------------------------------------------------------"
  print_status "DEPLOYMENT COMPLETE"
  print_info "Next steps:"
  print_gray " 1. Review deployment summary: ${OUTPUT}_summary.txt"
  print_gray " 2. Verify IBKR TWS/Gateway is running (port 7497 for paper trading)"
  print_gray " 3. Configure IBKR in .env: IB_HOST, IB_PORT, IB_CLIENT_ID, IB_ACCOUNT_ID"
  print_gray " 4. Start live trading: python live/run_live.py"
  print_gray " 5. Monitor logs: logs/live/"
  if [[ -n "$BACKUP_PATH" ]]; then
    print_warning "Rollback: Copy backup file back to .env"
    print_warning "Backup location: $BACKUP_PATH"
  fi
else
  print_warning "Dry run complete. No files were modified."
fi

exit 0


