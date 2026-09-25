#!/usr/bin/env bash
# ==============================================================================
# Chetna - AI Flood Early-Warning System (B2 Lead Setup Script)
# Author: Senior Backend Engineer / B2 Team
# Description:
#   Sets up Python 3.10+ virtual environment (or Conda), installs required
#   B2/GIS dependencies, and scaffolds the core project directory structure.
# ==============================================================================

set -euo pipefail

# ------------------------------------------------------------------------------
# Formatting & Color Definitions
# ------------------------------------------------------------------------------
BOLD='\033[1m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

info()    { echo -e "${CYAN}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} ${BOLD}$1${NC}"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1" >&2; }

# ------------------------------------------------------------------------------
# Configuration Defaults
# ------------------------------------------------------------------------------
ENV_TYPE="auto"        # 'auto', 'venv', or 'conda'
ENV_NAME="chetna-b2"   # Conda env name or venv directory (.venv)
VENV_DIR=".venv"
MIN_PY_MAJOR=3
MIN_PY_MINOR=10
SKIP_DEPS=false

print_usage() {
    cat <<EOF
Usage: ./setup_env.sh [OPTIONS]

Options:
  --venv          Force creation of standard Python venv in .venv/
  --conda         Force creation of a Conda environment (${ENV_NAME})
  --skip-deps     Skip pip/conda package installation
  -h, --help      Show this help message
EOF
}

# Parse CLI arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --venv)
            ENV_TYPE="venv"
            shift
            ;;
        --conda)
            ENV_TYPE="conda"
            shift
            ;;
        --skip-deps)
            SKIP_DEPS=true
            shift
            ;;
        -h|--help)
            print_usage
            exit 0
            ;;
        *)
            error "Unknown argument: $1"
            print_usage
            exit 1
            ;;
    esac
done

echo -e "${BOLD}${CYAN}"
echo "======================================================================"
echo "    CHETNA: AI Flood Early-Warning System - B2 Environment Setup      "
echo "======================================================================"
echo -e "${NC}"

# ------------------------------------------------------------------------------
# 1. Detect and Verify Python (3.10+)
# ------------------------------------------------------------------------------
detect_python() {
    info "Checking Python version..."
    PYTHON_BIN=""

    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            # Verify version >= 3.10
            is_valid=$("$candidate" -c "import sys; print(1 if sys.version_info >= ($MIN_PY_MAJOR, $MIN_PY_MINOR) else 0)" 2>/dev/null || echo 0)
            if [[ "$is_valid" -eq 1 ]]; then
                PYTHON_BIN="$candidate"
                break
            fi
        fi
    done

    if [[ -z "$PYTHON_BIN" ]]; then
        error "Python 3.10 or higher is required. None was found in PATH."
        error "Please install Python 3.10+ or activate a suitable environment."
        exit 1
    fi

    PY_VERSION=$("$PYTHON_BIN" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")
    success "Found compatible Python: $PYTHON_BIN (v$PY_VERSION)"
}

# ------------------------------------------------------------------------------
# 2. Virtual Environment Management (Conda or venv)
# ------------------------------------------------------------------------------
setup_environment() {
    # Check if Conda should be used
    USE_CONDA=false
    if [[ "$ENV_TYPE" == "conda" ]]; then
        USE_CONDA=true
    elif [[ "$ENV_TYPE" == "auto" ]] && command -v conda >/dev/null 2>&1; then
        # Default to conda if present in environment
        USE_CONDA=true
    fi

    if [[ "$USE_CONDA" == true ]]; then
        if ! command -v conda >/dev/null 2>&1; then
            error "Conda selected but 'conda' command was not found in PATH."
            exit 1
        fi
        info "Setting up Conda environment: '${ENV_NAME}' (Python 3.10)..."
        if conda env list | grep -q "^${ENV_NAME} "; then
            info "Conda environment '${ENV_NAME}' already exists. Skipping creation."
        else
            conda create -n "${ENV_NAME}" python=3.10 -y
            success "Conda environment '${ENV_NAME}' created."
        fi
        ACTIVATE_CMD="conda activate ${ENV_NAME}"
        PIP_CMD="conda run -n ${ENV_NAME} pip"
    else
        info "Setting up Python standard virtual environment in '${VENV_DIR}'..."
        if [[ ! -d "$VENV_DIR" ]]; then
            "$PYTHON_BIN" -m venv "$VENV_DIR"
            success "Virtual environment created at '${VENV_DIR}'."
        else
            info "Virtual environment directory '${VENV_DIR}' already exists."
        fi

        # Detect platform activation script (Windows Git Bash vs Linux/macOS)
        if [[ -f "$VENV_DIR/Scripts/activate" ]]; then
            ACTIVATE_PATH="$VENV_DIR/Scripts/activate"
            PIP_CMD="$VENV_DIR/Scripts/pip"
        elif [[ -f "$VENV_DIR/bin/activate" ]]; then
            ACTIVATE_PATH="$VENV_DIR/bin/activate"
            PIP_CMD="$VENV_DIR/bin/pip"
        else
            error "Could not find activate script in '$VENV_DIR'."
            exit 1
        fi
        ACTIVATE_CMD="source ${ACTIVATE_PATH}"
    fi
}

# ------------------------------------------------------------------------------
# 3. Install Dependencies
# ------------------------------------------------------------------------------
install_dependencies() {
    if [[ "$SKIP_DEPS" == true ]]; then
        warn "Skipping dependency installation as requested (--skip-deps)."
        return 0
    fi

    info "Upgrading pip, setuptools, and wheel..."
    $PIP_CMD install --upgrade pip setuptools wheel

    info "Installing required B2/GIS dependencies:"
    info "  - requests, twilio, python-telegram-bot, python-dotenv"
    info "  - pandas, pytest, pytest-mock"
    info "  [NOTE] sqlite3 is built directly into Python standard library."

    if [[ -f "requirements.txt" ]]; then
        info "Installing from requirements.txt..."
        $PIP_CMD install -r requirements.txt
    else
        info "Installing core packages directly..."
        $PIP_CMD install requests twilio python-telegram-bot python-dotenv pandas pytest pytest-mock
    fi

    success "Dependencies installed successfully."
}

# ------------------------------------------------------------------------------
# 4. Scaffolding Core Directory Structure
# ------------------------------------------------------------------------------
scaffold_directories() {
    info "Scaffolding core project directory structure..."

    DIRECTORIES=(
        "config"
        "database"
        "simulators"
        "alerts"
        "tests"
        "data"
    )

    for dir in "${DIRECTORIES[@]}"; do
        if [[ ! -d "$dir" ]]; then
            mkdir -p "$dir"
            info "  Created directory: $dir/"
        else
            info "  Directory exists: $dir/"
        fi

        # Ensure Python packages have __init__.py (except data/)
        if [[ "$dir" != "data" && ! -f "$dir/__init__.py" ]]; then
            touch "$dir/__init__.py"
            info "  Created $dir/__init__.py"
        fi
    done

    success "Core directories validated and prepared."
}

# ------------------------------------------------------------------------------
# 5. Generate .env.example and .env
# ------------------------------------------------------------------------------
generate_env_templates() {
    info "Generating environment configuration templates..."

    if [[ ! -f ".env.example" ]]; then
        cat << 'EOF' > .env.example
# ==============================================================================
# Chetna - AI Flood Early-Warning System (B2 Alerts & Sensor Configuration)
# Copy this file to '.env' and populate with your credentials.
# ==============================================================================

# Twilio SMS & Voice Call Configuration
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_twilio_auth_token_here
TWILIO_PHONE_NUMBER=+1234567890

# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ_example
TELEGRAM_CHAT_ID=-1001234567890

# System & Operational Settings
ALERT_DRY_RUN=true
ALERT_LOG_LEVEL=INFO
ALERT_RETRY_ATTEMPTS=3

# Database configuration
DATABASE_PATH=data/chetna.db

# Sensor Simulator Thresholds (cm / mm)
WATER_LEVEL_WARNING_THRESHOLD_CM=75.0
WATER_LEVEL_CRITICAL_THRESHOLD_CM=120.0
RAINFALL_HOURLY_WARNING_MM=30.0
RAINFALL_HOURLY_CRITICAL_MM=60.0

# Emergency Fallback Phone Contacts
EMERGENCY_BROADCAST_NUMBERS=+919876543210
EOF
        success "Created .env.example"
    else
        info ".env.example already exists."
    fi

    # Ensure config/.env.template also mirrors .env.example
    if [[ ! -f "config/.env.template" ]]; then
        cp .env.example config/.env.template
        info "Copied template to config/.env.template"
    fi

    # Create local .env if it does not exist yet
    if [[ ! -f ".env" ]]; then
        cp .env.example .env
        warn "Created local '.env' from '.env.example' (ALERT_DRY_RUN is enabled by default)."
    else
        info "Local '.env' already exists. Preserving existing values."
    fi
}

# ------------------------------------------------------------------------------
# Main Execution Pipeline
# ------------------------------------------------------------------------------
main() {
    detect_python
    setup_environment
    install_dependencies
    scaffold_directories
    generate_env_templates

    echo
    echo -e "${BOLD}${GREEN}======================================================================${NC}"
    echo -e "${BOLD}${GREEN}           B2 Environment Setup Completed Successfully!               ${NC}"
    echo -e "${BOLD}${GREEN}======================================================================${NC}"
    echo
    echo -e "${BOLD}Next steps for B2 development:${NC}"
    echo -e "  1. Activate your environment:"
    echo -e "     ${CYAN}${ACTIVATE_CMD}${NC}"
    echo -e "  2. Review and configure your API tokens:"
    echo -e "     ${CYAN}nano .env${NC}  or  ${CYAN}code .env${NC}"
    echo -e "  3. Run the automated test suite:"
    echo -e "     ${CYAN}pytest -v${NC}"
    echo -e "  4. Test the sensor simulator and alert dispatcher:"
    echo -e "     ${CYAN}python -m simulators.sensor_simulator${NC}"
    echo
}

main
