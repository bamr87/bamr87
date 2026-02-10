#!/bin/bash
# ============================================================================
# File: devtools-env.sh
# Description: Shell environment for bamr87 monorepo development
# Version: 1.0.0
# Author: bamr87
# Created: 2026-02-10
# Last Modified: 2026-02-10
#
# Source this file from your shell profile (.zprofile, .bashrc, etc.):
#   source ~/bamr87/tools/devtools-env.sh
#
# It reads the [env] section of tools/devtools.conf and exports those
# variables, plus adds convenience aliases and PATH entries.
# ============================================================================

# Resolve paths
_DEVTOOLS_DIR="${BASH_SOURCE[0]:-${(%):-%x}}"
_DEVTOOLS_DIR="$(cd "$(dirname "$_DEVTOOLS_DIR")" 2>/dev/null && pwd)"
_PROJECT_ROOT="$(cd "${_DEVTOOLS_DIR}/.." 2>/dev/null && pwd)"

# --------------------------------------------------------------------------
# Core exports — always available
# --------------------------------------------------------------------------
export BAMR87_HOME="${_PROJECT_ROOT}"
export BAMR87_TOOLS="${_PROJECT_ROOT}/tools"
export BAMR87_SCRIPTS="${_PROJECT_ROOT}/scripts"

# --------------------------------------------------------------------------
# Parse [env] section from devtools.conf (if present)
# --------------------------------------------------------------------------
_DEVTOOLS_CONF="${_DEVTOOLS_DIR}/devtools.conf"

if [[ -f "$_DEVTOOLS_CONF" ]]; then
    _in_env_section=false
    while IFS= read -r _line || [[ -n "$_line" ]]; do
        _line="${_line%%#*}"
        _line="$(echo "$_line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
        [[ -z "$_line" ]] && continue

        if [[ "$_line" =~ ^\[env\]$ ]]; then
            _in_env_section=true
            continue
        elif [[ "$_line" =~ ^\[.*\]$ ]]; then
            _in_env_section=false
            continue
        fi

        if [[ "$_in_env_section" == true && "$_line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
            _var_name="${BASH_REMATCH[1]}"
            _var_value="${BASH_REMATCH[2]}"
            # Expand ~ and $BAMR87_HOME references
            _var_value="${_var_value//\~/$HOME}"
            _var_value="${_var_value//\$BAMR87_HOME/$BAMR87_HOME}"
            export "$_var_name=$_var_value"
        fi
    done < "$_DEVTOOLS_CONF"
    unset _in_env_section _line _var_name _var_value
fi

unset _DEVTOOLS_CONF

# --------------------------------------------------------------------------
# PATH additions — project scripts and tools
# --------------------------------------------------------------------------
[[ -d "${BAMR87_TOOLS}" ]]   && export PATH="${BAMR87_TOOLS}:${PATH}"
[[ -d "${BAMR87_SCRIPTS}" ]] && export PATH="${BAMR87_SCRIPTS}:${PATH}"

# MkDocs venv (if activated)
[[ -d "${BAMR87_HOME}/.venv-docs/bin" ]] && export PATH="${BAMR87_HOME}/.venv-docs/bin:${PATH}"

# --------------------------------------------------------------------------
# Aliases — common dev tasks
# --------------------------------------------------------------------------
alias bamr87-setup="${BAMR87_TOOLS}/setup.sh"
alias bamr87-update="${BAMR87_TOOLS}/update-submodules.sh"
alias bamr87-cv="cd ${BAMR87_HOME}/cv && npm run dev"
alias bamr87-docs="cd ${BAMR87_HOME} && mkdocs serve"
alias bamr87-dc="cd ${BAMR87_HOME} && docker compose"

# --------------------------------------------------------------------------
# Completion hint
# --------------------------------------------------------------------------
if [[ -n "${BASH_VERSION:-}" || -n "${ZSH_VERSION:-}" ]]; then
    # Notify user (only in interactive shells)
    if [[ $- == *i* ]]; then
        echo "[bamr87] Dev environment loaded. Run 'bamr87-setup --help' for options."
    fi
fi

# Cleanup internal variables
unset _DEVTOOLS_DIR _PROJECT_ROOT
