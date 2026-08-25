#!/usr/bin/env bash
#
# install-workspace-sync.sh — keep this clone automatically in sync, daily
#
# Installs a per-user macOS LaunchAgent (com.bamr87.workspace-sync) that, every
# day and at every login, brings the local workspace current:
#
#   1. fast-forwards the hub repo (only when checked out on main)
#   2. runs tools/update-submodules.sh --no-commit --no-push, which puts every
#      submodule ON its declared branch at the latest remote commit (dirty or
#      diverged submodules are skipped, never reset)
#   3. unstages the moved pointers — recording them is owned by the daily
#      update-submodules.yml PR, so local main never diverges from the
#      protected branch
#
# launchd runs missed jobs after wake, so a closed laptop syncs on next login.
# Output is appended to ~/Library/Logs/bamr87-workspace-sync.log.
#
# Usage:
#   tools/install-workspace-sync.sh [--hour N]   # install/update (default 07:00)
#   tools/install-workspace-sync.sh --uninstall  # remove the agent
#

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.bamr87.workspace-sync"
PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
LOG="${HOME}/Library/Logs/bamr87-workspace-sync.log"
HOUR=7
UNINSTALL=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --uninstall) UNINSTALL=true; shift ;;
        --hour)      HOUR="${2:?--hour needs a value}"; shift 2 ;;
        -h|--help)   sed -n '2,22p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)           echo "unknown option: $1" >&2; exit 1 ;;
    esac
done

[[ "$(uname)" == "Darwin" ]] || { echo "launchd is macOS-only; on Linux use cron/systemd instead" >&2; exit 1; }

uid="$(id -u)"

if [[ "$UNINSTALL" == true ]]; then
    launchctl bootout "gui/${uid}/${LABEL}" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Removed ${LABEL}."
    exit 0
fi

mkdir -p "${HOME}/Library/LaunchAgents" "${HOME}/Library/Logs"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/zsh</string>
        <string>-lc</string>
        <string>
cd ${ROOT} || exit 1
export PATH=/opt/homebrew/bin:/usr/local/bin:\$PATH
echo "=== workspace-sync \$(date) ==="
if [ "\$(git symbolic-ref --short -q HEAD)" = main ]; then
  git pull --ff-only --quiet || echo "[WARN] root pull skipped (non-ff or offline)"
else
  echo "[INFO] root not on main; skipping root pull"
fi
tools/update-submodules.sh --no-commit --no-push
git reset --quiet -- projects .gitmodules
echo "=== workspace-sync done \$(date) ==="
        </string>
    </array>

    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>${HOUR}</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>ProcessType</key>
    <string>Background</string>

    <key>StandardOutPath</key>
    <string>${LOG}</string>
    <key>StandardErrorPath</key>
    <string>${LOG}</string>
</dict>
</plist>
EOF

# Reload cleanly whether or not a previous version was bootstrapped.
launchctl bootout "gui/${uid}/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/${uid}" "$PLIST"

echo "Installed ${LABEL}: daily at $(printf '%02d:00' "$HOUR") + every login (RunAtLoad)."
echo "Log: ${LOG}"
