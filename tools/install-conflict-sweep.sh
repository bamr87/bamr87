#!/usr/bin/env bash
#
# install-conflict-sweep.sh — resolve merge conflicts in a local session, on a schedule
#
# Installs a per-user macOS LaunchAgent (com.bamr87.conflict-sweep) that runs
# `tools/dash conflicts sweep --scheduled` every few hours: every conflicting PR
# up JEV's tiers, script first, then a capped model, on this machine's Claude
# Code login (constitution § 10.9). CI runs the free script tier on its own, so
# this is what picks up the conflicts that need a model.
#
# It pushes merge commits to PR branches and never merges a PR. A scheduled run
# stops at budget.jev.scheduled_stop_pct of the monthly cap. This changes the
# Mac, so run it yourself (§ 10.5). launchd runs a missed job after wake.
# Output is appended to ~/Library/Logs/bamr87-conflict-sweep.log.
#
# Usage:
#   tools/install-conflict-sweep.sh [--hours N]   # install/update (default every 6)
#   tools/install-conflict-sweep.sh --uninstall   # remove the agent
#

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.bamr87.conflict-sweep"
PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
LOG="${HOME}/Library/Logs/bamr87-conflict-sweep.log"
HOURS=6
UNINSTALL=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --uninstall) UNINSTALL=true; shift ;;
        --hours)     HOURS="${2:?--hours needs a value}"; shift 2 ;;
        -h|--help)   sed -n '2,18p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)           echo "unknown option: $1" >&2; exit 1 ;;
    esac
done

[[ "$HOURS" =~ ^[0-9]+$ && "$HOURS" -ge 1 ]] || { echo "--hours must be a whole number of 1 or more" >&2; exit 1; }
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
echo "=== conflict-sweep \$(date) ==="
tools/dash conflicts sweep --scheduled
echo "=== conflict-sweep done \$(date) ==="
        </string>
    </array>

    <key>StartInterval</key>
    <integer>$(( HOURS * 3600 ))</integer>

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

echo "Installed ${LABEL}: every ${HOURS} hour(s)."
echo "Log: ${LOG}"
