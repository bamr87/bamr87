#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CHUI_ROOT="${CHUI_ROOT:-$HOME/github/chui}"
CHUI_REPO="${CHUI_REPO:-https://github.com/bamr87/chui.git}"
LOCAL_ZSH="${HOME}/.config/chui/local.zsh"
ZPROFILE="${HOME}/.zprofile"
DRY_RUN=false
VERBOSE=false

log_info()  { echo "[INFO]  $*"; }
log_warn()  { echo "[WARN]  $*" >&2; }
log_error() { echo "[ERROR] $*" >&2; }
log_debug() { if [[ "$VERBOSE" == "true" ]]; then echo "[DEBUG] $*"; fi; }
log_step()  { echo "[STEP]  $*"; }

run_cmd() {
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY RUN] $*"
        return 0
    fi
    log_debug "Running: $*"
    "$@"
}

usage() {
    cat <<EOF
Usage: $(basename "$0") [--dry-run] [--verbose]

Bootstrap the macOS terminal CHUI (bamr87/chui): Oh My Zsh, Powerlevel10k,
MesloLGS Nerd Font, Apple Terminal keys/font, and bamr87 env in
~/.config/chui/local.zsh.

EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) usage ;;
        -d|--dry-run) DRY_RUN=true; shift ;;
        -v|--verbose) VERBOSE=true; shift ;;
        *) log_error "Unknown option: $1"; usage ;;
    esac
done

if [[ "$(uname -s)" != "Darwin" ]]; then
    log_info "Not macOS; skipping terminal CHUI"
    exit 0
fi

ensure_chui() {
    log_step "Ensuring bamr87/chui at ${CHUI_ROOT}"
    if [[ -d "${CHUI_ROOT}/.git" ]]; then
        log_info "chui already cloned"
        return 0
    fi
    run_cmd mkdir -p "$(dirname "$CHUI_ROOT")"
    if command -v gh >/dev/null 2>&1; then
        run_cmd gh repo clone bamr87/chui "$CHUI_ROOT"
    else
        run_cmd git clone "$CHUI_REPO" "$CHUI_ROOT"
    fi
}

install_chui() {
    log_step "Installing CHUI"
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY RUN] ${CHUI_ROOT}/install.sh"
        return 0
    fi
    chmod +x "${CHUI_ROOT}/install.sh" "${CHUI_ROOT}/backup.sh" "${CHUI_ROOT}/check.sh"
    (cd "$CHUI_ROOT" && ./install.sh)
}

register_fonts() {
    log_step "Registering MesloLGS Nerd Font with CoreText"
    local swift="${SCRIPT_DIR}/macos-register-nerd-fonts.swift"
    if [[ ! -f "$swift" ]]; then
        log_warn "Missing ${swift}; skipping font registration"
        return 0
    fi
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY RUN] swift ${swift}"
        return 0
    fi
    if ! command -v swift >/dev/null 2>&1; then
        log_warn "swift not found; font files may not be visible to Terminal.app"
        return 0
    fi
    swift "$swift" || log_warn "Font registration reported a problem"
}

apply_terminal_font() {
    log_step "Applying MesloLGS Nerd Font to Apple Terminal"
    local font_sh="${CHUI_ROOT}/config/terminal/macos-font.sh"
    if [[ -f "$font_sh" ]]; then
        run_cmd bash "$font_sh" || true
    fi
    if [[ "$DRY_RUN" == "true" ]]; then
        return 0
    fi
    osascript <<'EOF' >/dev/null || true
tell application "Terminal"
  set font name of default settings to "MesloLGS Nerd Font"
  set font size of default settings to 13
  try
    set font name of settings set "Clear Dark" to "MesloLGS Nerd Font"
    set font size of settings set "Clear Dark" to 13
  end try
  repeat with w in windows
    try
      set font name of current settings of w to "MesloLGS Nerd Font"
      set font size of current settings of w to 13
    end try
  end repeat
end tell
EOF
}

write_local_zsh() {
    log_step "Writing bamr87 env into ${LOCAL_ZSH}"
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY RUN] would ensure ${LOCAL_ZSH} sources ${PROJECT_ROOT}/tools/devtools-env.sh"
        return 0
    fi
    mkdir -p "$(dirname "$LOCAL_ZSH")"
    if [[ -f "$LOCAL_ZSH" ]] && grep -q 'devtools-env.sh' "$LOCAL_ZSH" 2>/dev/null; then
        log_debug "local.zsh already sources devtools-env.sh"
        return 0
    fi
    cat >> "$LOCAL_ZSH" <<EOF

if [[ -f "${PROJECT_ROOT}/tools/devtools-env.sh" ]]; then
  source "${PROJECT_ROOT}/tools/devtools-env.sh"
fi
EOF
    log_info "Appended bamr87 env to ${LOCAL_ZSH}"
}

ensure_zprofile() {
    log_step "Ensuring Homebrew + bamr87 in ${ZPROFILE}"
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY RUN] would ensure brew shellenv in ${ZPROFILE}"
        return 0
    fi
    touch "$ZPROFILE"
    if ! grep -q 'brew shellenv' "$ZPROFILE" 2>/dev/null; then
        local brew_bin=""
        if [[ -x /opt/homebrew/bin/brew ]]; then
            brew_bin=/opt/homebrew/bin/brew
        elif [[ -x /usr/local/bin/brew ]]; then
            brew_bin=/usr/local/bin/brew
        fi
        if [[ -n "$brew_bin" ]]; then
            local tmp
            tmp="$(mktemp)"
            printf 'eval "$(%s shellenv)"\n\n' "$brew_bin" > "$tmp"
            cat "$ZPROFILE" >> "$tmp"
            mv "$tmp" "$ZPROFILE"
            log_info "Prepended brew shellenv to ${ZPROFILE}"
        fi
    fi
    if [[ -d "${HOME}/.docker/bin" ]] && ! grep -q '.docker/bin' "$ZPROFILE" 2>/dev/null; then
        cat >> "$ZPROFILE" <<'EOF'
export PATH="$PATH:$HOME/.docker/bin"
EOF
    fi
}

verify() {
    if [[ "$DRY_RUN" == "true" ]]; then
        return 0
    fi
    if [[ -x "${CHUI_ROOT}/check.sh" ]]; then
        log_step "CHUI check"
        "${CHUI_ROOT}/check.sh" || log_warn "chui check reported failures (open a new Terminal window if the font is still SF Mono)"
    fi
}

ensure_chui
install_chui
register_fonts
apply_terminal_font
write_local_zsh
ensure_zprofile
verify
log_info "Terminal CHUI ready. Run ls again if icons still show as '?'."
