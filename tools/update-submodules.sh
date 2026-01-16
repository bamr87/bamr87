#!/usr/bin/env bash
#
# Enhanced Submodule Update Script
# Updates submodules with status checking and selective updates
#

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

status() {
    echo -e "${BLUE}[STATUS]${NC} $1"
}

# Usage information
usage() {
    cat << EOF
Usage: $0 [OPTIONS] [SUBMODULE]

Updates Git submodules to their latest remote versions.

OPTIONS:
    -h, --help          Show this help message
    -s, --status        Show current submodule status only
    -a, --all           Update all submodules (default)
    -c, --check         Check for available updates without applying
    --no-commit         Don't create commit for pointer changes
    --no-push           Don't push changes (even in CI)

ARGUMENTS:
    SUBMODULE           Specific submodule path to update (e.g., cv, README, scripts)

EXAMPLES:
    $0                  # Update all submodules
    $0 cv               # Update only cv submodule
    $0 --status         # Show current status
    $0 --check          # Check for updates without applying

EOF
    exit 0
}

# Parse arguments
SUBMODULE=""
STATUS_ONLY=false
CHECK_ONLY=false
NO_COMMIT=false
NO_PUSH=false

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            usage
            ;;
        -s|--status)
            STATUS_ONLY=true
            shift
            ;;
        -a|--all)
            SUBMODULE=""
            shift
            ;;
        -c|--check)
            CHECK_ONLY=true
            shift
            ;;
        --no-commit)
            NO_COMMIT=true
            shift
            ;;
        --no-push)
            NO_PUSH=true
            shift
            ;;
        -*)
            error "Unknown option: $1"
            usage
            ;;
        *)
            SUBMODULE="$1"
            shift
            ;;
    esac
done

# Show current status
show_status() {
    info "Current submodule status:"
    echo ""
    git submodule status --recursive
    echo ""
    
    info "Checking for available updates..."
    git submodule foreach --quiet 'echo "  - $name ($(git rev-parse --abbrev-ref HEAD))"'
}

# Check for updates
check_updates() {
    info "Checking for available updates..."
    git submodule foreach --quiet '
        CURRENT=$(git rev-parse HEAD)
        git fetch origin --quiet
        LATEST=$(git rev-parse origin/$(git rev-parse --abbrev-ref HEAD))
        if [ "$CURRENT" != "$LATEST" ]; then
            echo "  ✓ $name: Updates available"
            git log --oneline $CURRENT..$LATEST | head -3 | sed "s/^/    /"
        else
            echo "  - $name: Up to date"
        fi
    '
}

# Main execution
if [ "$STATUS_ONLY" = true ]; then
    show_status
    exit 0
fi

if [ "$CHECK_ONLY" = true ]; then
    check_updates
    exit 0
fi

# Update submodules
if [ -n "$SUBMODULE" ]; then
    info "Updating submodule: $SUBMODULE"
    if [ ! -d "$SUBMODULE" ]; then
        error "Submodule '$SUBMODULE' not found"
        exit 1
    fi
    
    git submodule update --init --recursive --remote "$SUBMODULE"
else
    info "Updating all submodules..."
    git submodule sync --recursive
    git submodule update --init --recursive --remote
fi

# Check for changes
status "Checking for changes in parent repository..."
if ! git diff --quiet --exit-code; then
    info "Submodule pointer(s) changed"
    
    # Show what changed
    echo ""
    git diff --submodule=log
    echo ""
    
    if [ "$NO_COMMIT" = false ]; then
        # Create commit
        if [ -n "$SUBMODULE" ]; then
            COMMIT_MSG="chore: update $SUBMODULE submodule"
        else
            COMMIT_MSG="chore: update submodule pointers"
        fi
        
        info "Creating commit..."
        git add .
        git commit -m "$COMMIT_MSG"
        
        # Push if in CI or requested
        if [ -n "${GITHUB_ACTIONS:-}" ] && [ "$NO_PUSH" = false ]; then
            info "Running in GitHub Actions; pushing updates..."
            git push
        elif [ "$NO_PUSH" = false ]; then
            warn "Not in GitHub Actions."
            echo "Run 'git push' to publish changes."
        else
            info "Skipping push (--no-push specified)"
        fi
    else
        info "Skipping commit (--no-commit specified)"
        echo "Staged changes are ready for manual commit."
    fi
else
    info "No submodule pointer changes detected. Nothing to commit."
fi

# Final status
echo ""
info "Update complete!"
show_status
