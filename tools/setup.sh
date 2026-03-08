#!/bin/bash
#
# File: setup.sh
# Description: Cross-platform development environment setup entrypoint for bamr87 monorepo
# Version: 2.2.0
# Author: bamr87
# Created: 2026-02-10
# Last Modified: 2026-02-10
#
# Usage: ./tools/setup.sh [OPTIONS] [COMPONENTS...]
#   OPTIONS:
#     -h, --help          Display this help message
#     -v, --verbose       Enable verbose output
#     -d, --dry-run       Preview actions without executing
#     -q, --quiet         Suppress non-error output
#     --skip-deps         Skip OS-level dependency installation
#     --skip-submodules   Skip git submodule initialization
#     --docker            Set up Docker/dev container environment only
#     --local             Set up local (non-Docker) development environment only
#     --all               Install all components (default)
#
#   COMPONENTS (optional, defaults to all):
#     cv                  CV Builder (Node.js/React)
#     docs                Documentation system (Python/MkDocs)
#     scripts             Shell scripts and utilities (forkme, stashme, etc.)
#     wiki                Wiki.js (Docker only)
#
#   SCRIPT TOOLS INSTALLED:
#     forkme              GitHub repo forking/cloning utility (interactive batch mode)
#     stashme             Multi-repo cloud stash (backup uncommitted changes)
#     git-init            New repo initialization wizard
#     project-wizard      Multi-stack project scaffolding wizard
#     rename-dir          Safe directory renaming with backup
#     github-setup        .github folder structure builder
#
# Examples:
#   ./tools/setup.sh                        # Full setup with auto-detected platform
#   ./tools/setup.sh --docker               # Docker-only setup
#   ./tools/setup.sh --local cv docs        # Local setup for cv and docs only
#   ./tools/setup.sh --dry-run --verbose    # Preview all actions
#   ./tools/setup.sh --skip-deps            # Skip OS package installation
#
# Exit Codes:
#   0 - Success
#   1 - General error
#   2 - Invalid arguments
#   3 - Unsupported platform
#   4 - Missing prerequisite
#   5 - Component setup failure
#
# Dependencies:
#   - git (2.13+)
#   - bash (4.0+ recommended; 3.2+ supported on macOS)
#
# Environment Variables:
#   BAMR87_SKIP_DEPS      - Skip OS dependency install (0|1, default: 0)
#   BAMR87_COMPONENTS     - Comma-separated components to install
#   BAMR87_DEV_MODE       - Development mode: docker|local|all (default: all)
#

# ============================================================================
# INITIALIZATION AND CONFIGURATION
# ============================================================================

set -euo pipefail

[[ "${DEBUG:-}" == "true" ]] && set -x

readonly SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly SCRIPT_VERSION="2.2.0"
readonly SCRIPTS_DIR="${PROJECT_ROOT}/scripts"
readonly LOCAL_BIN="${HOME}/.local/bin"
readonly DEVTOOLS_CONF="${SCRIPT_DIR}/devtools.conf"
readonly BREWFILE="${SCRIPT_DIR}/Brewfile"

# Runtime configuration
VERBOSE="${VERBOSE:-false}"
DRY_RUN="${DRY_RUN:-false}"
QUIET="${QUIET:-false}"
SKIP_DEPS="${BAMR87_SKIP_DEPS:-false}"
SKIP_SUBMODULES=false
DEV_MODE="${BAMR87_DEV_MODE:-all}"
INTERACTIVE=false
COMPONENTS=()

# Platform detection
OS=""
ARCH=""
PKG_MANAGER=""

# Colors for output (terminal-only)
if [[ -t 1 ]]; then
    readonly RED='\033[0;31m'
    readonly GREEN='\033[0;32m'
    readonly YELLOW='\033[1;33m'
    readonly BLUE='\033[0;34m'
    readonly CYAN='\033[0;36m'
    readonly BOLD='\033[1m'
    readonly NC='\033[0m'
else
    readonly RED='' GREEN='' YELLOW='' BLUE='' CYAN='' BOLD='' NC=''
fi

# ============================================================================
# LOGGING
# ============================================================================

log_info()  { if [[ "$QUIET" != "true" ]]; then echo -e "${GREEN}[INFO]${NC}  $1"; fi; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1" >&2; }
log_debug() { if [[ "$VERBOSE" == "true" ]]; then echo -e "${CYAN}[DEBUG]${NC} $1"; fi; }
log_step()  { if [[ "$QUIET" != "true" ]]; then echo -e "${BLUE}[STEP]${NC}  ${BOLD}$1${NC}"; fi; }

# ============================================================================
# ERROR HANDLING
# ============================================================================

error_handler() {
    local line_number="${1:-unknown}"
    local exit_code="${2:-1}"
    log_error "Failed at line ${line_number} (exit code: ${exit_code})"
    log_error "Command: ${BASH_COMMAND}"
    exit "$exit_code"
}

trap 'error_handler ${LINENO} $?' ERR

cleanup() {
    local exit_code=$?
    if [[ $exit_code -eq 0 ]]; then
        log_debug "Setup completed cleanly"
    else
        log_error "Setup exited with code ${exit_code}"
    fi
}

trap cleanup EXIT
trap 'log_warn "Interrupted by user"; exit 130' INT TERM

# ============================================================================
# USAGE
# ============================================================================

usage() {
    echo -e "${BOLD}Usage:${NC} ${SCRIPT_NAME} [OPTIONS] [COMPONENTS...]"
    echo ""
    echo -e "${BOLD}Cross-platform development environment setup for the bamr87 monorepo.${NC}"
    echo ""
    echo "Detects your OS and installs dependencies using the native package manager:"
    echo "  macOS:   Homebrew (brew)"
    echo "  Linux:   apt (Ubuntu/Debian)"
    echo "  Windows: winget (via WSL or Git Bash)"
    echo ""
    echo -e "${BOLD}Options:${NC}"
    echo "  -h, --help            Show this help message"
    echo "  -i, --interactive     Interactive guided setup wizard"
    echo "  -v, --verbose         Enable verbose/debug output"
    echo "  -d, --dry-run         Preview actions without executing"
    echo "  -q, --quiet           Suppress non-error output"
    echo "  --skip-deps           Skip OS-level dependency installation"
    echo "  --skip-submodules     Skip git submodule initialization"
    echo "  --docker              Set up Docker/dev container environment only"
    echo "  --local               Set up local (non-Docker) development only"
    echo "  --all                 Set up everything (default)"
    echo ""
    echo -e "${BOLD}Components:${NC}"
    echo "  cv                    CV Builder (Node.js/React/Vite)"
    echo "  docs                  Documentation system (Python/MkDocs)"
    echo "  scripts               Shell script utilities"
    echo "  wiki                  Wiki.js (Docker compose service)"
    echo ""
    echo "  If no components are specified, all are set up."
    echo ""
    echo -e "${BOLD}Examples:${NC}"
    echo "  ${SCRIPT_NAME}                          # Full auto-detected setup"
    echo "  ${SCRIPT_NAME} --docker                 # Docker environment only"
    echo "  ${SCRIPT_NAME} --local cv docs          # Local setup for specific components"
    echo "  ${SCRIPT_NAME} --dry-run --verbose      # See what would happen"
    echo "  ${SCRIPT_NAME} --skip-deps             # Skip brew/apt/winget install"
    echo "  ${SCRIPT_NAME} -i                        # Interactive guided setup"
    echo ""
    echo -e "${BOLD}Environment Variables:${NC}"
    echo "  BAMR87_SKIP_DEPS=1    Skip OS dependency install"
    echo "  BAMR87_DEV_MODE=docker|local|all"
    echo "  BAMR87_COMPONENTS=cv,docs,scripts"
    echo ""
    trap - EXIT ERR
    exit 0
}

# ============================================================================
# INTERACTIVE PROMPTS
# ============================================================================

# Prompt user with a numbered menu. Sets REPLY to the chosen value.
# Arguments:
#   $1 - Prompt question
#   $2..N - Options ("value:label" or just "value")
# Returns: selected value in global MENU_CHOICE
MENU_CHOICE=""
menu_prompt() {
    local question="$1"
    shift
    local options=("$@")
    local count=${#options[@]}

    echo ""
    echo -e "${BOLD}${question}${NC}"
    local i=1
    for opt in "${options[@]}"; do
        local label="${opt#*:}"
        local value="${opt%%:*}"
        if [[ "$label" == "$value" ]]; then
            label="$value"
        fi
        echo -e "  ${CYAN}${i})${NC} ${label}"
        ((i++))
    done
    echo ""

    while true; do
        read -r -p "Enter choice [1-${count}]: " choice
        if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= count )); then
            local selected="${options[$((choice-1))]}"
            MENU_CHOICE="${selected%%:*}"
            return 0
        fi
        echo -e "${RED}Invalid choice.${NC} Please enter a number between 1 and ${count}."
    done
}

# Prompt yes/no question. Returns 0 for yes, 1 for no.
# Arguments:
#   $1 - Question text
#   $2 - Default (y/n, default: y)
confirm_prompt() {
    local question="$1"
    local default="${2:-y}"
    local hint="Y/n"
    [[ "$default" == "n" ]] && hint="y/N"

    while true; do
        read -r -p "${question} [${hint}]: " answer
        answer="${answer:-$default}"
        # tr for bash 3.2 compatibility (macOS)
        answer="$(echo "$answer" | tr '[:upper:]' '[:lower:]')"
        case "$answer" in
            y|yes) return 0 ;;
            n|no)  return 1 ;;
            *)     echo "Please answer y or n." ;;
        esac
    done
}

# Multi-select prompt. Returns selected values in MULTI_CHOICES array.
# Arguments:
#   $1 - Question text
#   $2..N - Options ("value:label")
MULTI_CHOICES=()
multi_select_prompt() {
    local question="$1"
    shift
    local options=("$@")
    local count=${#options[@]}
    # Default all selected
    local selected=()
    for ((i=0; i<count; i++)); do
        selected+=(1)
    done

    echo ""
    echo -e "${BOLD}${question}${NC}"
    echo -e "  ${CYAN}Toggle items by number, 'a' for all, 'n' for none, Enter to confirm.${NC}"

    while true; do
        echo ""
        local i=1
        for opt in "${options[@]}"; do
            local label="${opt#*:}"
            if [[ ${selected[$((i-1))]} -eq 1 ]]; then
                echo -e "  ${GREEN}[x]${NC} ${i}) ${label}"
            else
                echo -e "  ${RED}[ ]${NC} ${i}) ${label}"
            fi
            ((i++))
        done
        echo ""
        read -r -p "Toggle [1-${count}], (a)ll, (n)one, Enter to confirm: " toggle

        if [[ -z "$toggle" ]]; then
            # Confirm selection
            break
        elif [[ "$toggle" == "a" ]]; then
            for ((i=0; i<count; i++)); do selected[$i]=1; done
        elif [[ "$toggle" == "n" ]]; then
            for ((i=0; i<count; i++)); do selected[$i]=0; done
        elif [[ "$toggle" =~ ^[0-9]+$ ]] && (( toggle >= 1 && toggle <= count )); then
            local idx=$((toggle-1))
            if [[ ${selected[$idx]} -eq 1 ]]; then
                selected[$idx]=0
            else
                selected[$idx]=1
            fi
        else
            echo -e "${RED}Invalid input.${NC}"
        fi
    done

    MULTI_CHOICES=()
    for ((i=0; i<count; i++)); do
        if [[ ${selected[$i]} -eq 1 ]]; then
            local val="${options[$i]}"
            MULTI_CHOICES+=("${val%%:*}")
        fi
    done
}

# Run the interactive setup wizard
run_interactive() {
    echo ""
    echo -e "${BOLD}==========================================${NC}"
    echo -e "${BOLD}  bamr87 Development Environment Setup${NC}"
    echo -e "${BOLD}==========================================${NC}"
    echo ""
    echo -e "  Platform:  ${GREEN}${OS}${NC} (${ARCH})"
    echo -e "  Manager:   ${GREEN}${PKG_MANAGER}${NC}"
    echo -e "  Manifest:  ${CYAN}${DEVTOOLS_CONF}${NC}"
    echo -e "  Version:   ${SCRIPT_VERSION}"
    echo ""

    # 1. Development mode
    menu_prompt "How do you want to set up the environment?" \
        "all:Full setup (Docker + Local)" \
        "local:Local development only (no Docker)" \
        "docker:Docker/dev container only"
    DEV_MODE="$MENU_CHOICE"
    log_debug "Selected dev mode: ${DEV_MODE}"

    # 2. Component selection
    multi_select_prompt "Which components do you want to set up?" \
        "cv:CV Builder (Node.js/React/Vite)" \
        "docs:Documentation system (Python/MkDocs)" \
        "scripts:Script toolkit (forkme, stashme, git-init, project-wizard, etc.)" \
        "wiki:Wiki.js (Docker compose service)"
    COMPONENTS=("${MULTI_CHOICES[@]}")
    log_debug "Selected components: ${COMPONENTS[*]}"

    # 3. Options
    echo ""
    echo -e "${BOLD}Additional Options:${NC}"

    if confirm_prompt "  Install OS-level dependencies (${PKG_MANAGER})?" "y"; then
        SKIP_DEPS=false
    else
        SKIP_DEPS=true
    fi

    if confirm_prompt "  Initialize/update git submodules?" "y"; then
        SKIP_SUBMODULES=false
    else
        SKIP_SUBMODULES=true
    fi

    if confirm_prompt "  Enable verbose output?" "n"; then
        VERBOSE=true
    fi

    # 4. Confirmation summary
    echo ""
    echo -e "${BOLD}Setup Plan:${NC}"
    echo -e "  Mode:        ${GREEN}${DEV_MODE}${NC}"
    echo -e "  Components:  ${GREEN}${COMPONENTS[*]:-all}${NC}"
    echo -e "  OS deps:     $(if [[ "$SKIP_DEPS" == "true" ]]; then echo -e "${YELLOW}skip${NC}"; else echo -e "${GREEN}install${NC}"; fi)"
    echo -e "  Submodules:  $(if [[ "$SKIP_SUBMODULES" == "true" ]]; then echo -e "${YELLOW}skip${NC}"; else echo -e "${GREEN}init${NC}"; fi)"
    echo -e "  Verbose:     $(if [[ "$VERBOSE" == "true" ]]; then echo -e "${GREEN}yes${NC}"; else echo "no"; fi)"
    echo -e "  Dry run:     $(if [[ "$DRY_RUN" == "true" ]]; then echo -e "${YELLOW}yes${NC}"; else echo "no"; fi)"
    echo ""

    if ! confirm_prompt "Proceed with setup?" "y"; then
        log_info "Setup cancelled by user."
        trap - EXIT ERR
        exit 0
    fi

    echo ""
}

# ============================================================================
# PLATFORM DETECTION
# ============================================================================

detect_platform() {
    log_step "Detecting platform..."

    ARCH="$(uname -m)"

    case "$(uname -s)" in
        Darwin)
            OS="macos"
            PKG_MANAGER="brew"
            ;;
        Linux)
            if grep -qi "microsoft" /proc/version 2>/dev/null; then
                OS="wsl"
                if command -v apt-get &>/dev/null; then
                    PKG_MANAGER="apt"
                fi
            elif command -v apt-get &>/dev/null; then
                OS="linux"
                PKG_MANAGER="apt"
            elif command -v dnf &>/dev/null; then
                OS="linux"
                PKG_MANAGER="dnf"
            else
                OS="linux"
                PKG_MANAGER="unknown"
            fi
            ;;
        MINGW*|MSYS*|CYGWIN*)
            OS="windows"
            PKG_MANAGER="winget"
            ;;
        *)
            log_error "Unsupported operating system: $(uname -s)"
            exit 3
            ;;
    esac

    log_info "Platform: ${OS} (${ARCH}), Package manager: ${PKG_MANAGER}"
}

# ============================================================================
# MANIFEST PARSER — reads tools/devtools.conf
# ============================================================================

command_exists() {
    command -v "$1" &>/dev/null
}

run_cmd() {
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY RUN] $*"
        return 0
    fi
    log_debug "Running: $*"
    "$@"
}

# Parse devtools.conf and populate arrays by platform prefix.
# Sets global arrays: PKGS_BREW, PKGS_CASK, PKGS_APT, PKGS_WINGET,
#                     PKGS_PIP, PKGS_NPM, PKGS_CUSTOM, PKGS_GENERIC
parse_devtools_conf() {
    if [[ ! -f "$DEVTOOLS_CONF" ]]; then
        log_error "Manifest not found: ${DEVTOOLS_CONF}"
        log_error "Cannot determine which packages to install."
        exit 1
    fi

    log_debug "Parsing manifest: ${DEVTOOLS_CONF}"

    PKGS_BREW=()
    PKGS_CASK=()
    PKGS_APT=()
    PKGS_WINGET=()
    PKGS_PIP=()
    PKGS_NPM=()
    PKGS_CUSTOM=()
    PKGS_GENERIC=()

    local current_section=""

    while IFS= read -r line || [[ -n "$line" ]]; do
        # Strip inline comments (but keep the package name)
        line="${line%%#*}"
        # Trim whitespace
        line="$(echo "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
        # Skip empty lines
        [[ -z "$line" ]] && continue

        # Section headers: [core], [languages], etc.
        if [[ "$line" =~ ^\[([a-zA-Z0-9_-]+)\]$ ]]; then
            current_section="${BASH_REMATCH[1]}"
            log_debug "  Section: [${current_section}]"
            continue
        fi

        # Skip env section (handled by devtools-env.sh)
        [[ "$current_section" == "env" ]] && continue
        # Skip reference-only sections
        [[ "$current_section" == "python-docs" ]] && continue
        [[ "$current_section" == "node-cv" ]] && continue

        # Platform-prefixed entries
        if [[ "$line" =~ ^@([a-zA-Z]+)[[:space:]]+(.+)$ ]]; then
            local prefix="${BASH_REMATCH[1]}"
            local pkg="${BASH_REMATCH[2]}"
            pkg="$(echo "$pkg" | sed 's/[[:space:]]*$//')"
            case "$prefix" in
                brew)   PKGS_BREW+=("$pkg") ;;
                cask)   PKGS_CASK+=("$pkg") ;;
                apt)    PKGS_APT+=("$pkg") ;;
                winget) PKGS_WINGET+=("$pkg") ;;
                pip)    PKGS_PIP+=("$pkg") ;;
                npm)    PKGS_NPM+=("$pkg") ;;
                custom) PKGS_CUSTOM+=("$pkg") ;;
                *)      log_warn "Unknown prefix @${prefix} for '${pkg}'" ;;
            esac
        else
            # Generic (cross-platform) package
            PKGS_GENERIC+=("$line")
        fi
    done < "$DEVTOOLS_CONF"

    log_debug "Parsed: ${#PKGS_GENERIC[@]} generic, ${#PKGS_BREW[@]} brew, ${#PKGS_CASK[@]} cask, ${#PKGS_APT[@]} apt, ${#PKGS_WINGET[@]} winget, ${#PKGS_PIP[@]} pip, ${#PKGS_CUSTOM[@]} custom"
}

# ============================================================================
# DEPENDENCY INSTALLATION (per platform, manifest-driven)
# ============================================================================

install_brew_if_missing() {
    if ! command_exists brew; then
        log_info "Installing Homebrew..."
        run_cmd /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    else
        log_info "Homebrew already installed: $(brew --version | head -1)"
    fi
}

install_brew_pkg() {
    local pkg="$1"
    if brew list "$pkg" &>/dev/null; then
        log_debug "Already installed: ${pkg}"
    else
        log_info "Installing ${pkg}..."
        run_cmd brew install "$pkg"
    fi
}

install_brew_cask() {
    local pkg="$1"
    if brew list --cask "$pkg" &>/dev/null; then
        log_debug "Already installed (cask): ${pkg}"
    else
        log_info "Installing ${pkg} (cask)..."
        run_cmd brew install --cask "$pkg"
    fi
}

install_apt_pkg() {
    local pkg="$1"
    if dpkg -l "$pkg" &>/dev/null 2>&1; then
        log_debug "Already installed: ${pkg}"
    else
        log_info "Installing ${pkg}..."
        run_cmd sudo apt-get install -y -qq "$pkg"
    fi
}

# Handle @custom entries that require special install logic
install_custom() {
    local label="$1"
    case "$label" in
        node-linux)
            if ! command_exists node; then
                log_info "Installing Node.js LTS via NodeSource..."
                run_cmd curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
                run_cmd sudo apt-get install -y -qq nodejs
            else
                log_info "Node.js already installed: $(node --version)"
            fi
            ;;
        docker-linux)
            if ! command_exists docker; then
                log_info "Installing Docker Engine..."
                run_cmd curl -fsSL https://get.docker.com | sudo sh
                run_cmd sudo usermod -aG docker "${USER}"
                log_warn "Docker group membership added. You may need to log out and back in."
            else
                log_info "Docker already installed: $(docker --version)"
            fi
            ;;
        compose-linux)
            if ! docker compose version &>/dev/null 2>&1; then
                log_info "Installing Docker Compose plugin..."
                run_cmd sudo apt-get install -y -qq docker-compose-plugin
            fi
            ;;
        gh-linux)
            if ! command_exists gh; then
                log_info "Installing GitHub CLI..."
                run_cmd curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
                    | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
                echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
                    | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
                run_cmd sudo apt-get update -qq
                run_cmd sudo apt-get install -y -qq gh
            fi
            ;;
        *)
            log_warn "Unknown custom install target: ${label}"
            ;;
    esac
}

install_deps_macos() {
    log_step "Installing macOS dependencies via Homebrew..."
    install_brew_if_missing

    # Brewfile-based install (preferred, atomic)
    if [[ -f "$BREWFILE" ]]; then
        log_info "Installing from Brewfile: ${BREWFILE}"
        run_cmd brew bundle --file="$BREWFILE"
    else
        # Fallback: install from parsed manifest
        for pkg in "${PKGS_GENERIC[@]}"; do install_brew_pkg "$pkg"; done
        for pkg in "${PKGS_BREW[@]}";    do install_brew_pkg "$pkg"; done
        for pkg in "${PKGS_CASK[@]}";    do install_brew_cask "$pkg"; done
    fi

    # pip packages
    for pkg in "${PKGS_PIP[@]}"; do
        if command_exists "$pkg" 2>/dev/null || pip3 show "$pkg" &>/dev/null 2>&1; then
            log_debug "Already installed (pip): ${pkg}"
        else
            log_info "Installing ${pkg} via pip..."
            run_cmd pip3 install --user "$pkg"
        fi
    done
}

install_deps_linux() {
    log_step "Installing Linux dependencies via apt..."
    run_cmd sudo apt-get update -qq

    # Generic packages (available in apt)
    for pkg in "${PKGS_GENERIC[@]}"; do install_apt_pkg "$pkg"; done

    # apt-specific packages
    for pkg in "${PKGS_APT[@]}"; do install_apt_pkg "$pkg"; done

    # Custom install targets (Node, Docker, gh, etc.)
    for label in "${PKGS_CUSTOM[@]}"; do install_custom "$label"; done

    # pip packages
    for pkg in "${PKGS_PIP[@]}"; do
        if command_exists "$pkg" 2>/dev/null || pip3 show "$pkg" &>/dev/null 2>&1; then
            log_debug "Already installed (pip): ${pkg}"
        else
            log_info "Installing ${pkg} via pip..."
            run_cmd pip3 install --user "$pkg"
        fi
    done
}

install_deps_windows() {
    log_step "Installing Windows dependencies via winget..."

    # Generic packages via winget (best-effort name mapping)
    for pkg in "${PKGS_GENERIC[@]}"; do
        log_info "Ensuring ${pkg} (generic)..."
        run_cmd winget install --id "$pkg" --accept-source-agreements --accept-package-agreements --silent 2>/dev/null || {
            log_debug "${pkg} may already be installed or not in winget"
        }
    done

    # winget-specific IDs
    for pkg in "${PKGS_WINGET[@]}"; do
        log_info "Ensuring ${pkg}..."
        run_cmd winget install --id "$pkg" --accept-source-agreements --accept-package-agreements --silent 2>/dev/null || {
            log_debug "${pkg} may already be installed or winget unavailable"
        }
    done

    log_warn "For pip packages (pre-commit, black, flake8), run:"
    for pkg in "${PKGS_PIP[@]}"; do
        log_warn "  pip install ${pkg}"
    done
}

install_os_dependencies() {
    if [[ "$SKIP_DEPS" == "true" ]]; then
        log_info "Skipping OS dependency installation (--skip-deps)"
        return 0
    fi

    # Parse the manifest first
    parse_devtools_conf

    case "$OS" in
        macos)      install_deps_macos ;;
        linux|wsl)  install_deps_linux ;;
        windows)    install_deps_windows ;;
        *)          log_warn "Unknown OS '${OS}'; skipping dependency install" ;;
    esac
}

# ============================================================================
# PREREQUISITE VALIDATION
# ============================================================================

validate_prerequisites() {
    log_step "Validating prerequisites..."

    # In dry-run mode, skip validation since deps were not actually installed
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "Skipping prerequisite validation (dry-run mode)"
        return 0
    fi

    local missing=()

    command_exists git || missing+=("git")

    if [[ "$DEV_MODE" == "docker" || "$DEV_MODE" == "all" ]]; then
        command_exists docker || missing+=("docker")
    fi

    if [[ "$DEV_MODE" == "local" || "$DEV_MODE" == "all" ]]; then
        # Check for component-specific requirements
        if should_install "cv"; then
            command_exists node || missing+=("node")
            command_exists npm  || missing+=("npm")
        fi
        if should_install "docs"; then
            command_exists python3 || missing+=("python3")
        fi
    fi

    if [[ ${#missing[@]} -gt 0 ]]; then
        log_error "Missing required tools: ${missing[*]}"
        log_error "Run without --skip-deps to install them, or install manually."
        return 4
    fi

    log_info "All prerequisites satisfied"
    return 0
}

# ============================================================================
# COMPONENT HELPERS
# ============================================================================

should_install() {
    local component="$1"
    # If no components specified, install all
    if [[ ${#COMPONENTS[@]} -eq 0 ]]; then
        return 0
    fi
    # Check if component is in the list
    for c in "${COMPONENTS[@]}"; do
        [[ "$c" == "$component" ]] && return 0
    done
    return 1
}

# ============================================================================
# SUBMODULE SETUP
# ============================================================================

setup_submodules() {
    if [[ "$SKIP_SUBMODULES" == "true" ]]; then
        log_info "Skipping submodule initialization (--skip-submodules)"
        return 0
    fi

    log_step "Initializing Git submodules..."

    cd "$PROJECT_ROOT"

    run_cmd git submodule sync --recursive
    run_cmd git submodule update --init --recursive

    log_info "Submodule status:"
    git submodule status
}

# ============================================================================
# DOCKER / DEV CONTAINER SETUP
# ============================================================================

setup_docker() {
    if [[ "$DEV_MODE" != "docker" && "$DEV_MODE" != "all" ]]; then
        return 0
    fi

    log_step "Setting up Docker development environment..."

    cd "$PROJECT_ROOT"

    # Ensure root docker-compose.yml exists
    if [[ ! -f "docker-compose.yml" ]]; then
        log_info "Creating root docker-compose.yml..."
        run_cmd cp "${SCRIPT_DIR}/docker-compose.dev.yml" docker-compose.yml 2>/dev/null || {
            log_warn "No docker-compose.dev.yml template found; skipping root compose creation"
        }
    fi

    # Ensure devcontainer config exists
    if [[ ! -d ".devcontainer" ]]; then
        log_info "Dev container configuration found at .devcontainer/"
    else
        log_debug ".devcontainer/ already exists"
    fi

    # Build and verify
    if command_exists docker; then
        if [[ -f "docker-compose.yml" ]]; then
            log_info "Pulling/building Docker images..."
            run_cmd docker compose pull --ignore-pull-failures 2>/dev/null || true
            run_cmd docker compose build
            log_info "Docker environment ready. Start with: docker compose up -d"
        fi
    else
        log_warn "Docker not available. Install Docker to use container-based development."
    fi
}

# ============================================================================
# LOCAL COMPONENT SETUP
# ============================================================================

setup_cv() {
    if ! should_install "cv"; then return 0; fi
    if [[ "$DEV_MODE" == "docker" ]]; then return 0; fi
    if [[ ! -d "${PROJECT_ROOT}/cv" ]]; then
        log_warn "cv/ directory not found; skipping CV Builder setup"
        return 0
    fi

    log_step "Setting up CV Builder (Node.js/React)..."

    cd "${PROJECT_ROOT}/cv"

    if command_exists node; then
        log_info "Node.js: $(node --version)"
        log_info "Installing npm dependencies..."
        run_cmd npm install
        log_info "CV Builder ready. Start with: cd cv && npm run dev"
    else
        log_warn "Node.js not found; skipping CV Builder setup"
    fi
}

setup_docs() {
    if ! should_install "docs"; then return 0; fi
    if [[ "$DEV_MODE" == "docker" ]]; then return 0; fi

    log_step "Setting up Documentation system (Python/MkDocs)..."

    cd "${PROJECT_ROOT}"

    if ! command_exists python3; then
        log_warn "Python 3 not found; skipping docs setup"
        return 0
    fi

    log_info "Python: $(python3 --version)"

    # Root-level MkDocs venv
    if [[ -f "requirements-docs.txt" ]]; then
        log_info "Creating MkDocs virtual environment..."
        if [[ ! -d ".venv-docs" ]]; then
            run_cmd python3 -m venv .venv-docs
        fi
        log_info "Installing MkDocs dependencies..."
        run_cmd .venv-docs/bin/pip install --quiet --upgrade pip
        run_cmd .venv-docs/bin/pip install --quiet -r requirements-docs.txt
        log_info "MkDocs ready. Run: source .venv-docs/bin/activate && mkdocs serve"
    fi

    # README submodule venv
    if [[ -d "README" && -f "README/requirements.txt" ]]; then
        log_info "Creating README documentation virtual environment..."
        if [[ ! -d "README/.venv" ]]; then
            run_cmd python3 -m venv README/.venv
        fi
        log_info "Installing README dependencies..."
        run_cmd README/.venv/bin/pip install --quiet --upgrade pip
        run_cmd README/.venv/bin/pip install --quiet -r README/requirements.txt
        log_info "README docs ready."
    fi
}

setup_scripts() {
    if ! should_install "scripts"; then return 0; fi
    if [[ ! -d "${SCRIPTS_DIR}" ]]; then
        log_warn "scripts/ directory not found; skipping"
        return 0
    fi

    log_step "Setting up shell script utilities..."

    cd "${PROJECT_ROOT}"

    log_info "Making scripts executable..."
    find scripts -name '*.sh' -exec chmod +x {} \; 2>/dev/null || true
    find tools -name '*.sh' -exec chmod +x {} \; 2>/dev/null || true

    # Validate with shellcheck if available
    if command_exists shellcheck; then
        log_info "ShellCheck available: $(shellcheck --version | head -2 | tail -1)"
    else
        log_warn "ShellCheck not installed; consider installing for script linting"
    fi

    # Install script CLI tools as symlinks in ~/.local/bin
    setup_script_cli_tools

    log_info "Scripts ready."
}

#######################################
# Install script CLI tools as commands in ~/.local/bin
# Creates symlinks so scripts can be invoked by name from anywhere.
# Globals:
#   SCRIPTS_DIR, LOCAL_BIN, DRY_RUN
# Arguments:
#   None
# Returns:
#   0 on success
#######################################
setup_script_cli_tools() {
    log_step "Installing script CLI tools..."

    # Ensure ~/.local/bin exists
    run_cmd mkdir -p "${LOCAL_BIN}"

    # Tool definitions: "command_name:relative_script_path" (bash 3.2 compatible)
    local tool_entries=(
        "forkme:forkme.sh"
        "stashme:STASHME/stashme.sh"
        "git-init:git_init.sh"
        "project-wizard:project-init.sh"
        "rename-dir:rename-directory.sh"
        "github-setup:.github.sh"
        "create-package:create_package.sh"
    )

    local installed=0
    local skipped=0

    for entry in "${tool_entries[@]}"; do
        local cmd_name="${entry%%:*}"
        local rel_path="${entry#*:}"
        local script_path="${SCRIPTS_DIR}/${rel_path}"
        local link_path="${LOCAL_BIN}/${cmd_name}"

        if [[ ! -f "$script_path" ]]; then
            log_debug "Script not found, skipping: ${rel_path}"
            ((skipped++)) || true
            continue
        fi

        # Ensure executable
        chmod +x "$script_path" 2>/dev/null || true

        if [[ -L "$link_path" ]]; then
            local existing_target
            existing_target=$(readlink "$link_path" 2>/dev/null || echo "")
            if [[ "$existing_target" == "$script_path" ]]; then
                log_debug "Symlink already correct: ${cmd_name} -> ${script_path}"
                ((installed++)) || true
                continue
            fi
            # Update stale symlink
            log_info "Updating symlink: ${cmd_name}"
            run_cmd ln -sf "$script_path" "$link_path"
        elif [[ -e "$link_path" ]]; then
            log_warn "${link_path} exists but is not a symlink; skipping (remove manually to fix)"
            ((skipped++)) || true
            continue
        else
            log_info "Creating symlink: ${cmd_name} -> ${script_path}"
            run_cmd ln -sf "$script_path" "$link_path"
        fi
        ((installed++)) || true
    done

    log_info "Installed ${installed} CLI tools, skipped ${skipped}"

    # Ensure ~/.local/bin is on PATH
    ensure_local_bin_on_path
}

#######################################
# Ensure ~/.local/bin is on the user's PATH.
# Adds it to shell RC file if missing.
# Globals:
#   LOCAL_BIN, DRY_RUN
# Arguments:
#   None
#######################################
ensure_local_bin_on_path() {
    # Already on PATH?
    if echo "$PATH" | tr ':' '\n' | grep -qx "${LOCAL_BIN}"; then
        log_debug "${LOCAL_BIN} already on PATH"
        return 0
    fi

    log_info "Adding ${LOCAL_BIN} to PATH..."

    local shell_rc=""
    if [[ -n "${ZSH_VERSION:-}" ]] || [[ "$(basename "${SHELL:-}")" == "zsh" ]]; then
        shell_rc="${HOME}/.zshrc"
    elif [[ -n "${BASH_VERSION:-}" ]] || [[ "$(basename "${SHELL:-}")" == "bash" ]]; then
        shell_rc="${HOME}/.bashrc"
    fi

    if [[ -n "$shell_rc" ]]; then
        if ! grep -q '# bamr87 script tools' "$shell_rc" 2>/dev/null; then
            log_info "Appending PATH entry to ${shell_rc}"
            if [[ "$DRY_RUN" != "true" ]]; then
                cat >> "$shell_rc" <<'PATHEOF'

# bamr87 script tools
export PATH="$HOME/.local/bin:$PATH"
PATHEOF
            else
                log_info "[DRY RUN] Would append PATH entry to ${shell_rc}"
            fi
            log_warn "Run 'source ${shell_rc}' or open a new terminal to use CLI tools."
        else
            log_debug "PATH entry already in ${shell_rc}"
        fi
    else
        log_warn "Could not detect shell RC file. Add ${LOCAL_BIN} to your PATH manually."
    fi
}

setup_precommit() {
    if [[ ! -f "${PROJECT_ROOT}/.pre-commit-config.yaml" ]]; then
        return 0
    fi

    log_step "Setting up pre-commit hooks..."

    cd "${PROJECT_ROOT}"

    if command_exists pre-commit; then
        run_cmd pre-commit install
        log_info "Pre-commit hooks installed."
    else
        log_warn "pre-commit not found. Install with: pip install pre-commit"
    fi
}

# ============================================================================
# ENVIRONMENT FILE SETUP
# ============================================================================

setup_env_files() {
    log_step "Checking environment files..."

    cd "${PROJECT_ROOT}"

    # Root .env from example
    if [[ -f "scripts/env.example" && ! -f ".env" ]]; then
        log_info "Creating .env from scripts/env.example..."
        run_cmd cp scripts/env.example .env
        log_warn "Review and edit .env with your configuration values."
    elif [[ -f ".env" ]]; then
        log_debug ".env already exists"
    fi
}

# ============================================================================
# SUMMARY
# ============================================================================

print_summary() {
    echo ""
    echo -e "${BOLD}=========================================${NC}"
    echo -e "${BOLD} Development Environment Setup Complete${NC}"
    echo -e "${BOLD}=========================================${NC}"
    echo ""
    echo -e "${BOLD}Platform:${NC}  ${OS} (${ARCH})"
    echo -e "${BOLD}Mode:${NC}      ${DEV_MODE}"
    echo -e "${BOLD}Version:${NC}   ${SCRIPT_VERSION}"
    echo -e "${BOLD}Manifest:${NC}  ${DEVTOOLS_CONF}"
    echo ""

    echo -e "${BOLD}Component Status:${NC}"
    [[ -d "${PROJECT_ROOT}/cv/node_modules" ]] \
        && echo -e "  ${GREEN}✓${NC} CV Builder (Node.js)" \
        || echo -e "  ${YELLOW}○${NC} CV Builder (not set up locally)"
    [[ -d "${PROJECT_ROOT}/.venv-docs" ]] \
        && echo -e "  ${GREEN}✓${NC} MkDocs Documentation" \
        || echo -e "  ${YELLOW}○${NC} MkDocs Documentation (not set up)"
    [[ -d "${PROJECT_ROOT}/README/.venv" ]] \
        && echo -e "  ${GREEN}✓${NC} README Documentation" \
        || echo -e "  ${YELLOW}○${NC} README Documentation (not set up)"
    command_exists docker \
        && echo -e "  ${GREEN}✓${NC} Docker ($(docker --version 2>/dev/null | head -1))" \
        || echo -e "  ${YELLOW}○${NC} Docker (not installed)"
    command_exists shellcheck \
        && echo -e "  ${GREEN}✓${NC} ShellCheck" \
        || echo -e "  ${YELLOW}○${NC} ShellCheck (not installed)"
    command_exists pre-commit \
        && echo -e "  ${GREEN}✓${NC} Pre-commit hooks" \
        || echo -e "  ${YELLOW}○${NC} Pre-commit (not installed)"
    echo ""

    # Script CLI tools status
    echo -e "${BOLD}Script CLI Tools:${NC}"
    local cli_tools=(forkme stashme git-init project-wizard rename-dir github-setup create-package)
    local cli_descriptions=(
        "GitHub repo forking/cloning (batch interactive mode)"
        "Multi-repo cloud stash (backup uncommitted changes)"
        "New repository initialization wizard"
        "Multi-stack project scaffolding wizard"
        "Safe directory renaming with backup"
        ".github folder structure builder"
        "Python package bootstrapper"
    )
    for i in "${!cli_tools[@]}"; do
        local tool="${cli_tools[$i]}"
        local desc="${cli_descriptions[$i]}"
        if [[ -L "${LOCAL_BIN}/${tool}" ]] && [[ -x "${LOCAL_BIN}/${tool}" ]]; then
            echo -e "  ${GREEN}✓${NC} ${tool}  — ${desc}"
        else
            echo -e "  ${YELLOW}○${NC} ${tool}  — ${desc} (not linked)"
        fi
    done
    echo ""

    echo -e "${BOLD}Quick Start:${NC}"
    if [[ "$DEV_MODE" == "docker" || "$DEV_MODE" == "all" ]]; then
        echo "  Docker:       docker compose up -d"
        echo "  Dev Shell:    docker compose exec app bash"
    fi
    if [[ "$DEV_MODE" == "local" || "$DEV_MODE" == "all" ]]; then
        echo "  CV Builder:   cd cv && npm run dev"
        echo "  MkDocs:       source .venv-docs/bin/activate && mkdocs serve"
    fi
    echo ""
    echo -e "${BOLD}Script Tools (run from anywhere after setup):${NC}"
    echo "  forkme -i --user <github-user>    Clone/fork repos interactively"
    echo "  stashme ~/github                  Backup uncommitted changes to cloud"
    echo "  git-init                          Initialize a new GitHub repository"
    echo "  project-wizard                    Scaffold a new project"
    echo "  rename-dir <old> <new>            Safely rename a directory"
    echo "  github-setup <project-type>       Set up .github structure"
    echo ""
    echo -e "  Full docs:  ${CYAN}docs/DEVELOPMENT.md${NC}"
    echo ""
}

# ============================================================================
# ARGUMENT PARSING
# ============================================================================

parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -h|--help)       usage ;;
            -i|--interactive) INTERACTIVE=true; shift ;;
            -v|--verbose)    VERBOSE=true; shift ;;
            -d|--dry-run)    DRY_RUN=true; log_info "Dry-run mode enabled"; shift ;;
            -q|--quiet)      QUIET=true; shift ;;
            --skip-deps)     SKIP_DEPS=true; shift ;;
            --skip-submodules) SKIP_SUBMODULES=true; shift ;;
            --docker)        DEV_MODE="docker"; shift ;;
            --local)         DEV_MODE="local"; shift ;;
            --all)           DEV_MODE="all"; shift ;;
            --version)       echo "${SCRIPT_NAME} v${SCRIPT_VERSION}"; trap - EXIT ERR; exit 0 ;;
            -*)              log_error "Unknown option: $1"; usage ;;
            cv|docs|scripts|wiki)
                COMPONENTS+=("$1"); shift ;;
            *)               log_error "Unknown component: $1"; usage ;;
        esac
    done
}

# ============================================================================
# MAIN
# ============================================================================

main() {
    parse_arguments "$@"

    log_info "Starting ${SCRIPT_NAME} v${SCRIPT_VERSION}"

    # 1. Detect platform
    detect_platform

    # 1.5 Interactive mode — prompt user for all options
    if [[ "$INTERACTIVE" == "true" ]]; then
        run_interactive
    fi

    # 2. Install OS-level dependencies
    install_os_dependencies

    # 3. Validate prerequisites
    validate_prerequisites || exit $?

    # 4. Initialize submodules
    setup_submodules

    # 5. Set up env files
    setup_env_files

    # 6. Docker / dev container setup
    setup_docker

    # 7. Local component setup
    setup_cv
    setup_docs
    setup_scripts

    # 8. Pre-commit hooks
    setup_precommit

    # 9. Summary
    print_summary
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
