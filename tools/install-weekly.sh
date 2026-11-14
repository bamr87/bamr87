#!/usr/bin/env bash
#
# install-weekly.sh — close the week on Friday, prepare the next on Saturday, plan it on Sunday
#
# Installs ONE per-user macOS LaunchAgent (com.bamr87.weekly) with three calendar
# slots, read from _data/fleet.yml `weekly.schedule` (local time, off the hour):
#   close    Friday    save, tidy and close out the week
#   prepare  Saturday  check that next week's scheduled activities can run
#   plan     Sunday    the week's plan, its agenda and the Monday brief
# Each slot runs the same command against the hub checkout at --root:
#   tools/dash weekly auto --scheduled
# which runs every stage that is due this weekend and has not run, in order. So
# a slot missed while the Mac slept is made up at the next one, or at the next
# wake (launchd runs a missed job then), and Friday's close-out always comes
# before Saturday's preflight. Docs: docs/WEEKLY.md.
#
# A scheduled stage makes no GitHub write and, for its first
# `weekly.report_only_runs` Fridays, removes nothing: it reports. Every external
# write waits for `tools/dash weekly confirm --apply`. The switch is
# `weekly.enabled` in _data/fleet.yml (constitution § 17).
#
# This changes the Mac, so run it yourself (§ 10.5). Output is appended to
# ~/Library/Logs/bamr87-weekly.log.
#
# launchd starts the job without a login shell, so a PYTHONPATH that only a
# shell profile sets never reaches it. The installer bakes in the PYTHONPATH of
# the shell that runs it; pass --pythonpath to set another, or '' for none.
#
# Usage:
#   tools/install-weekly.sh [--root PATH] [--pythonpath P]   # install or update
#   tools/install-weekly.sh --uninstall                      # remove the agent
#   tools/install-weekly.sh [--root PATH] --print-job        # print the job script, install nothing
#   tools/install-weekly.sh [--root PATH] --print-plist      # print the plist, install nothing
#

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.bamr87.weekly"
PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
LOG="${HOME}/Library/Logs/bamr87-weekly.log"
MODE=install
PYPATH="${PYTHONPATH:-}"

while [[ $# -gt 0 ]]; do
    case $1 in
        --uninstall)   MODE=uninstall; shift ;;
        --print-job)   MODE=print-job; shift ;;
        --print-plist) MODE=print-plist; shift ;;
        --root)        ROOT="${2:?--root needs a path}"; shift 2 ;;
        --pythonpath)  [[ $# -ge 2 ]] || { echo "--pythonpath needs a value ('' for none)" >&2; exit 1; }
                       PYPATH="$2"; shift 2 ;;
        -h|--help)     sed -n '2,34p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)             echo "unknown option: $1" >&2; exit 1 ;;
    esac
done

if [[ "$MODE" != uninstall ]]; then
    ROOT="$(cd "$ROOT" 2>/dev/null && pwd)" || { echo "--root: not a directory" >&2; exit 1; }
    [[ -x "$ROOT/tools/dash" && -f "$ROOT/tools/weekly/cli.py" ]] \
        || { echo "--root $ROOT is not a hub checkout with the weekly routine (no tools/dash, tools/weekly/cli.py)" >&2; exit 1; }
    [[ "$ROOT" != *"'"* ]] || { echo "--root may not contain a single quote" >&2; exit 1; }
    [[ "$PYPATH" != *"'"* ]] || { echo "--pythonpath may not contain a single quote" >&2; exit 1; }
fi

if [[ -n "$PYPATH" ]]; then
    PYLINE="export PYTHONPATH='${PYPATH}'"
else
    PYLINE=": no PYTHONPATH baked in"
fi

# The three slots, as "weekday hour minute" lines in stage order, from the one
# place they are declared. Minute 00 is refused: no hub schedule fires on the
# hour (AGENTS.md).
slots() {
    PYTHONPATH="$PYPATH" python3 - "$ROOT" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from tools.weekly import cli, core
schedule = core.load_config(core.load_fleet(Path(sys.argv[1])))["schedule"]
problem = cli.schedule_problem(schedule)   # the check the dispatcher makes: whole numbers, off the hour, in order
if problem:
    sys.exit(problem)
for stage in core.STAGES:
    print(schedule[stage]["weekday"], schedule[stage]["hour"], schedule[stage]["minute"])
PY
}

# The job, as bash 3.2 runs it (macOS /bin/bash). The interpreter is the first
# with PyYAML; `caffeinate -i` keeps the Mac awake until the stage ends.
job_script() {
    cat <<EOF
cd '${ROOT}' || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:\${PATH}"
${PYLINE}
PY=""
for cand in "\${PYTHON:-}" python3 /usr/bin/python3; do
    [ -n "\$cand" ] || continue
    command -v "\$cand" >/dev/null 2>&1 || continue
    if "\$cand" -c 'import yaml' >/dev/null 2>&1; then PY="\$cand"; break; fi
done
[ -n "\$PY" ] || { echo "weekly: no python3 with PyYAML on PATH" >&2; exit 1; }
export PYTHON="\$PY"
step() {
    echo "--- \$* (\$(date '+%H:%M:%S'))"
    caffeinate -i "\$@"
    rc=\$?
    [ "\$rc" -eq 0 ] || echo "weekly: '\$*' exited \$rc"
    return 0
}
echo "=== weekly \$(date) ==="
step tools/dash weekly auto --scheduled
echo "=== weekly done \$(date) ==="
EOF
}

xml_escape() { sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }

calendar() {
    local weekday hour minute
    while read -r weekday hour minute; do
        cat <<EOF
        <dict>
            <key>Weekday</key>
            <integer>${weekday}</integer>
            <key>Hour</key>
            <integer>${hour}</integer>
            <key>Minute</key>
            <integer>${minute}</integer>
        </dict>
EOF
    done
}

plist() {
    cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-c</string>
        <string>
$(job_script | xml_escape)
        </string>
    </array>

    <key>StartCalendarInterval</key>
    <array>
$(calendar <<<"$SLOTS")
    </array>

    <key>ProcessType</key>
    <string>Background</string>

    <key>StandardOutPath</key>
    <string>${LOG}</string>
    <key>StandardErrorPath</key>
    <string>${LOG}</string>
</dict>
</plist>
EOF
}

if [[ "$MODE" == print-job ]]; then
    job_script
    exit 0
fi

if [[ "$MODE" != uninstall ]]; then
    # Read the schedule once, here, where a failure stops the script: inside a command substitution
    # errexit is off, and a bad schedule would otherwise install an agent with no slots.
    SLOTS="$(slots)" || { echo "install-weekly: the schedule could not be read; nothing was changed" >&2; exit 1; }
    [[ "$(wc -l <<<"$SLOTS" | tr -d ' ')" == 3 ]] \
        || { echo "install-weekly: expected three slots in weekly.schedule; nothing was changed" >&2; exit 1; }
fi

if [[ "$MODE" == print-plist ]]; then
    plist
    exit 0
fi

[[ "$(uname)" == "Darwin" ]] || { echo "launchd is macOS-only; on Linux use cron/systemd instead" >&2; exit 1; }
uid="$(id -u)"

if [[ "$MODE" == uninstall ]]; then
    launchctl bootout "gui/${uid}/${LABEL}" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Removed ${LABEL}."
    exit 0
fi

# Render and check the plist before the installed one is touched.
rendered="$(plist)"
[[ "$(grep -c '<key>Weekday</key>' <<<"$rendered")" == 3 ]] \
    || { echo "install-weekly: the plist did not render three slots; nothing was changed" >&2; exit 1; }
mkdir -p "${HOME}/Library/LaunchAgents" "${HOME}/Library/Logs"
printf '%s\n' "$rendered" > "${PLIST}.new"
plutil -lint "${PLIST}.new" >/dev/null
mv "${PLIST}.new" "$PLIST"

# Reload cleanly whether or not a previous version was bootstrapped.
launchctl bootout "gui/${uid}/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/${uid}" "$PLIST"

echo "Installed ${LABEL} against ${ROOT}:"
while read -r weekday hour minute; do
    printf '  weekday %s at %02d:%02d local\n' "$weekday" "$hour" "$minute"
done <<<"$SLOTS"
echo "Log: ${LOG}"
