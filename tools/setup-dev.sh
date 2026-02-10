#!/bin/bash
#
# File: setup-dev.sh
# Description: Legacy wrapper — delegates to tools/setup.sh
# Version: 2.0.0
# Author: bamr87
# Created: 2024-01-15
# Last Modified: 2026-02-10
#
# Usage: ./tools/setup-dev.sh [OPTIONS]
#   This script is a thin wrapper around tools/setup.sh for backward
#   compatibility. All new options and features live in setup.sh.
#
# Migration:
#   Use tools/setup.sh directly for full cross-platform support:
#     ./tools/setup.sh --help
#

set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[INFO]  setup-dev.sh is now a wrapper for tools/setup.sh"
echo "[INFO]  For full options run: ./tools/setup.sh --help"
echo ""

exec "${SCRIPT_DIR}/setup.sh" --local "$@"
