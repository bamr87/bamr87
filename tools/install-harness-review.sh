#!/usr/bin/env bash
#
# install-harness-review.sh — review the agents' week and reflect on it, on a schedule
#
# Installs a per-user macOS LaunchAgent (com.bamr87.harness-review) that runs
# once a day, off the hour, against the hub checkout at --root:
#   1. tools/dash-gen lake sessions --days 2    this machine's Claude Code transcripts into the lake ($0, local)
#   2. tools/dash-gen lake sync --days 2 --jobs ai --logs ai
#                                               the CI agent runs of the last two days (GitHub reads)
#   3. tools/dash-gen lake review --days 7 --json > .fleet/refine/review-latest.json
#   4. tools/dash refine reflect --scheduled   the incident reflector — GUARDED: skipped quietly while
#                                               `refine reflect` does not exist in the checkout or
#                                               _data/fleet.yml harness_refinement.enabled is not true
# Step 4 runs daily but reflects weekly: the engine waits reflect.every_days
# after the last scheduled run that spent, stops at budget.loops'
# scheduled_stop_pct, and never files — it previews, posts a notification,
# and a person files with `tools/dash refine reflect publish <stamp> --apply`
# (constitution § 11.8, § 13.8; docs/HARNESS-REFINEMENT.md). Each step's
# failure is logged and the next step still runs.
#
# This changes the Mac, so run it yourself (§ 10.5). launchd runs a missed
# job after wake. Output is appended to ~/Library/Logs/bamr87-harness-review.log.
#
# launchd starts the job without a login shell, so a PYTHONPATH that only a
# shell profile sets (where `lake sync`'s PyGithub and requests live) never
# reaches it. The installer bakes in the PYTHONPATH of the shell that runs
# it; pass --pythonpath to set another one, or --pythonpath '' for none.
#
# Usage:
#   tools/install-harness-review.sh [--root PATH] [--at HH:MM] [--pythonpath P]   # install/update (default 06:23 local)
#   tools/install-harness-review.sh --uninstall                  # remove the agent
#   tools/install-harness-review.sh [--root PATH] --print-job    # print the job script, install nothing
#   tools/install-harness-review.sh [--root PATH] --print-plist  # print the plist, install nothing
#

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.bamr87.harness-review"
PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
LOG="${HOME}/Library/Logs/bamr87-harness-review.log"
AT="06:23"
MODE=install
PYPATH="${PYTHONPATH:-}"

while [[ $# -gt 0 ]]; do
    case $1 in
        --uninstall)   MODE=uninstall; shift ;;
        --print-job)   MODE=print-job; shift ;;
        --print-plist) MODE=print-plist; shift ;;
        --root)        ROOT="${2:?--root needs a path}"; shift 2 ;;
        --at)          AT="${2:?--at needs HH:MM}"; shift 2 ;;
        --pythonpath)  [[ $# -ge 2 ]] || { echo "--pythonpath needs a value ('' for none)" >&2; exit 1; }
                       PYPATH="$2"; shift 2 ;;
        -h|--help)     sed -n '2,34p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)             echo "unknown option: $1" >&2; exit 1 ;;
    esac
done

[[ "$AT" =~ ^([01][0-9]|2[0-3]):([0-5][0-9])$ ]] || { echo "--at must be HH:MM (24-hour)" >&2; exit 1; }
HOUR=$((10#${BASH_REMATCH[1]}))
MINUTE=$((10#${BASH_REMATCH[2]}))
# No hub schedule fires on the hour (AGENTS.md); neither does this one.
[[ "$MINUTE" -ne 0 ]] || { echo "--at must be off the hour (minute 00 is refused)" >&2; exit 1; }

if [[ "$MODE" != uninstall ]]; then
    ROOT="$(cd "$ROOT" 2>/dev/null && pwd)" || { echo "--root: not a directory" >&2; exit 1; }
    [[ -x "$ROOT/tools/dash" && -x "$ROOT/tools/dash-gen" ]] \
        || { echo "--root $ROOT is not a hub checkout (no tools/dash, tools/dash-gen)" >&2; exit 1; }
    [[ "$ROOT" != *"'"* ]] || { echo "--root may not contain a single quote" >&2; exit 1; }
    [[ "$PYPATH" != *"'"* ]] || { echo "--pythonpath may not contain a single quote" >&2; exit 1; }
fi

if [[ -n "$PYPATH" ]]; then
    PYLINE="export PYTHONPATH='${PYPATH}'"
else
    PYLINE=": no PYTHONPATH baked in"
fi

# The job, as bash 3.2 runs it (macOS /bin/bash). It calls only entry points
# that exist on main, plus the guarded reflect step. The interpreter is the
# first that imports everything `lake sync` needs; failing that, the first
# with PyYAML, which runs every step but the sync.
job_script() {
    cat <<EOF
cd '${ROOT}' || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:\${PATH}"
${PYLINE}
PY=""
for need in 'import yaml, github, requests' 'import yaml'; do
    for cand in "\${PYTHON:-}" python3 /usr/bin/python3; do
        [ -n "\$cand" ] || continue
        command -v "\$cand" >/dev/null 2>&1 || continue
        if "\$cand" -c "\$need" >/dev/null 2>&1; then PY="\$cand"; break 2; fi
    done
done
[ -n "\$PY" ] || { echo "harness-review: no python3 with PyYAML on PATH" >&2; exit 1; }
export PYTHON="\$PY"
step() {
    echo "--- \$* (\$(date '+%H:%M:%S'))"
    "\$@"
    rc=\$?
    [ "\$rc" -eq 0 ] || echo "harness-review: '\$*' exited \$rc — continuing"
    return 0
}
echo "=== harness-review \$(date) ==="
step tools/dash-gen lake sessions --days 2
step tools/dash-gen lake sync --days 2 --jobs ai --logs ai
mkdir -p .fleet/refine
if tools/dash-gen lake review --days 7 --json > .fleet/refine/review-latest.json.tmp; then
    mv .fleet/refine/review-latest.json.tmp .fleet/refine/review-latest.json
    echo "--- lake review: .fleet/refine/review-latest.json"
else
    rm -f .fleet/refine/review-latest.json.tmp
    echo "harness-review: lake review failed — continuing"
fi
if ! "\$PY" -m tools.jev refine reflect --help >/dev/null 2>&1; then
    echo "--- reflect: skipped (refine reflect is not in this checkout yet)"
elif ! "\$PY" -c 'import sys, yaml; c = (yaml.safe_load(open("_data/fleet.yml")) or {}).get("harness_refinement") or {}; sys.exit(0 if c.get("enabled") is True else 1)' 2>/dev/null; then
    echo "--- reflect: skipped (_data/fleet.yml harness_refinement.enabled is not true)"
else
    step tools/dash refine reflect --scheduled
fi
echo "=== harness-review done \$(date) ==="
EOF
}

xml_escape() { sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }

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
    <dict>
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
EOF
}

case "$MODE" in
    print-job)   job_script; exit 0 ;;
    print-plist) plist; exit 0 ;;
esac

[[ "$(uname)" == "Darwin" ]] || { echo "launchd is macOS-only; on Linux use cron/systemd instead" >&2; exit 1; }
uid="$(id -u)"

if [[ "$MODE" == uninstall ]]; then
    launchctl bootout "gui/${uid}/${LABEL}" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Removed ${LABEL}."
    exit 0
fi

mkdir -p "${HOME}/Library/LaunchAgents" "${HOME}/Library/Logs"
plist > "$PLIST"
plutil -lint "$PLIST" >/dev/null

# Reload cleanly whether or not a previous version was bootstrapped.
launchctl bootout "gui/${uid}/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/${uid}" "$PLIST"

printf 'Installed %s: daily at %02d:%02d against %s.\n' "$LABEL" "$HOUR" "$MINUTE" "$ROOT"
echo "Log: ${LOG}"
