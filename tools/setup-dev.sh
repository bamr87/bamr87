#!/bin/bash
#
# Development Environment Setup Script
# Sets up all dependencies for the bamr87 monorepo
#

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
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

check_command() {
    if ! command -v "$1" &> /dev/null; then
        return 1
    fi
    return 0
}

# Main setup
info "Starting development environment setup..."

# Check if we're in the right directory
if [ ! -f "README.md" ] || [ ! -d ".git" ]; then
    error "This script must be run from the repository root"
    exit 1
fi

# Initialize submodules
info "Initializing Git submodules..."
if git submodule update --init --recursive; then
    info "✓ Submodules initialized"
else
    error "Failed to initialize submodules"
    exit 1
fi

# Check submodule status
info "Checking submodule status..."
git submodule status

# Setup CV Builder (Node.js project)
if [ -d "cv" ]; then
    info "Setting up CV Builder..."
    cd cv
    
    if check_command node; then
        NODE_VERSION=$(node --version)
        info "Node.js version: $NODE_VERSION"
        
        if check_command npm; then
            info "Installing npm dependencies..."
            npm install
            info "✓ CV Builder dependencies installed"
        else
            warn "npm not found. Skipping CV Builder setup."
        fi
    else
        warn "Node.js not found. Skipping CV Builder setup."
        warn "Install Node.js 18+ from https://nodejs.org"
    fi
    
    cd ..
fi

# Setup Documentation System (Python project)
if [ -d "README" ]; then
    info "Setting up Documentation system..."
    cd README
    
    if check_command python3; then
        PYTHON_VERSION=$(python3 --version)
        info "Python version: $PYTHON_VERSION"
        
        if check_command pip3; then
            info "Installing Python dependencies..."
            pip3 install -r requirements.txt --user
            info "✓ Documentation system dependencies installed"
        else
            warn "pip3 not found. Skipping README setup."
        fi
    else
        warn "Python 3 not found. Skipping README setup."
        warn "Install Python 3.8+ from https://python.org"
    fi
    
    cd ..
fi

# Setup MkDocs (root level)
if [ -f "requirements-docs.txt" ]; then
    info "Setting up MkDocs..."
    
    if check_command pip3; then
        info "Installing MkDocs dependencies..."
        pip3 install -r requirements-docs.txt --user
        info "✓ MkDocs dependencies installed"
    else
        warn "pip3 not found. Skipping MkDocs setup."
    fi
fi

# Make scripts executable
if [ -d "scripts" ]; then
    info "Making scripts executable..."
    chmod +x scripts/*.sh 2>/dev/null || true
    info "✓ Scripts are executable"
fi

# Make tools executable
if [ -d "tools" ]; then
    info "Making tools executable..."
    chmod +x tools/*.sh 2>/dev/null || true
    info "✓ Tools are executable"
fi

# Setup pre-commit hooks (optional)
if check_command pre-commit; then
    if [ -f ".pre-commit-config.yaml" ]; then
        info "Installing pre-commit hooks..."
        pre-commit install
        info "✓ Pre-commit hooks installed"
    fi
else
    warn "pre-commit not found. Skipping pre-commit hook setup."
    warn "Install with: pip install pre-commit"
fi

# Summary
echo ""
info "========================================="
info "Development environment setup complete!"
info "========================================="
echo ""

# Check what's installed
echo "Installed components:"
[ -d "cv/node_modules" ] && echo "  ✓ CV Builder (Node.js)"
[ -d "README/.venv" ] || check_command mkdocs && echo "  ✓ Documentation System (Python)"
check_command mkdocs && echo "  ✓ MkDocs (Documentation)"
echo ""

# Next steps
info "Next steps:"
echo "  1. Review docs/DEVELOPMENT.md for detailed setup"
echo "  2. Configure environment variables (see .env.example files)"
echo "  3. Run individual projects:"
echo "     - CV Builder:      cd cv && npm run dev"
echo "     - Documentation:   mkdocs serve"
echo "     - Scripts:         cd scripts && ./script-name.sh --help"
echo ""

# Warnings if components are missing
if ! check_command node; then
    warn "Node.js not installed - CV Builder won't work"
fi

if ! check_command python3; then
    warn "Python 3 not installed - Documentation system won't work"
fi

info "Setup complete! Happy coding! 🚀"
