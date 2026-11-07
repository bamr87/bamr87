#!/usr/bin/env bash
#
# install-weekly.sh — run the weekly routine every Friday night (docs/WEEKLY.md)
#
# Installs a per-user macOS LaunchAgent (com.bamr87.weekly) that runs
# `tools/dash weekly run --scheduled` at the time in _data/fleet.yml
# `weekly.schedule`, local time. launchd runs a missed time at the next wake.
#
# Running this is a deploy step: constitution § 10.5 keeps the Mac hands-off
# until the maintainer says yes. A scheduled run makes no GitHub write.
#
#   tools/install-weekly.sh              # install or update the agent
#   tools/install-weekly.sh --print      # show the plist, change nothing
#   tools/install-weekly.sh --uninstall  # remove the agent
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.bamr87.weekly"
PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
LOG="${HOME}/Library/Logs/bamr87-weekly.log"
MODE="install"

case "${1:-}" in
  "") ;;
  --print) MODE="print" ;;
  --uninstall) MODE="uninstall" ;;
  *) echo "usage: $0 [--print|--uninstall]" >&2; exit 2 ;;
esac

if [[ "$(uname)" != "Darwin" ]]; then
  echo "install-weekly: macOS only (launchd)" >&2
  exit 1
fi

uid="$(id -u)"
if [[ "$MODE" == "uninstall" ]]; then
  launchctl bootout "gui/${uid}/${LABEL}" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Removed ${LABEL}."
  exit 0
fi

read -r WEEKDAY HOUR MINUTE < <(python3 -c '
import sys, yaml
s = yaml.safe_load(open(sys.argv[1]))["weekly"]["schedule"]
print(s["weekday"], s["hour"], s["minute"])' "$ROOT/_data/fleet.yml")

render() {
  cat <<PLIST_END
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
echo "=== weekly \$(date) ==="
caffeinate -i tools/dash weekly run --scheduled
echo "=== weekly done \$(date) ==="
        </string>
    </array>

    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>${WEEKDAY}</integer>
        <key>Hour</key>
        <integer>${HOUR}</integer>
        <key>Minute</key>
        <integer>${MINUTE}</integer>
    </dict>

    <key>ProcessType</key>
    <string>Background</string>

    <key>StandardOutPath</key>
    <string>${LOG}</string>
    <key>StandardErrorPath</key>
    <string>${LOG}</string>
</dict>
</plist>
PLIST_END
}

if [[ "$MODE" == "print" ]]; then
  render
  exit 0
fi

mkdir -p "$(dirname "$PLIST")"
render > "$PLIST"
launchctl bootout "gui/${uid}/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/${uid}" "$PLIST"
printf 'Installed %s: weekday %s at %02d:%02d local. Log: %s\n' "$LABEL" "$WEEKDAY" "$HOUR" "$MINUTE" "$LOG"
