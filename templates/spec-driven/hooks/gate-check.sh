#!/usr/bin/env bash
# kit: spec-driven — Claude Code PostToolUse hook (Write|Edit). After an edit to
# BACKLOG.md or anything under specs/, run the two stdlib gates (spec_validator +
# backlog_lint) and, if they fail, feed the failure back so the model fixes it
# before moving on.
#
# Two ways to run it:
#   plugin   hooks/hooks.json wires it with ${CLAUDE_PLUGIN_ROOT}; the tools are
#            the plugin's own tools/ (the by-reference mode: nothing vendored).
#   vendored lands at .claude/hooks/gate-check.sh and finds the tools in the
#            repo's tools/ (fleet default) or scripts/ (law-ai's old layout).
# Fleet copy: bamr87/bamr87 templates/spec-driven/hooks/ (keep it byte-identical).
set +e
command -v python3 >/dev/null 2>&1 || exit 0

payload="$(cat)"
f="$(printf '%s' "$payload" | python3 -c 'import json,sys;d=json.load(sys.stdin);ti=d.get("tool_input") or {};tr=d.get("tool_response") or {};print(ti.get("file_path") or tr.get("filePath") or "")' 2>/dev/null)"

# Anchor on THIS project's root, not the shell cwd: in cross-repo sessions the
# cwd can be a sibling checkout whose specs/ would otherwise match below and
# get gated with this repo's tool paths.
root="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"

# PostToolUse fires only on successful Write/Edit calls, whose file_path is
# always absolute. Gate only files inside THIS repo — sibling repos run their
# own gates — and only repos that carry the two artifacts the gates read.
case "$f" in
  "$root"/BACKLOG.md | "$root"/specs/*) ;;
  *) exit 0 ;;
esac
[ -f "$root/BACKLOG.md" ] || [ -d "$root/specs" ] || exit 0

# Tool resolution: the plugin's own copies first, then a vendored tools/ or
# scripts/ in the repo. No tools anywhere means nothing to gate with.
dir=""
for cand in "${CLAUDE_PLUGIN_ROOT:-}/tools" "$root/tools" "$root/scripts"; do
  [ -f "$cand/spec_validator.py" ] && [ -f "$cand/backlog_lint.py" ] && { dir="$cand"; break; }
done
[ -n "$dir" ] || exit 0

sv_out="$(cd "$root" && python3 "$dir/spec_validator.py" --root "$root" 2>&1)"; sv=$?
bl_out="$(cd "$root" && python3 "$dir/backlog_lint.py" --root "$root" 2>&1)"; bl=$?
out="$(printf '%s\n---\n%s' "$sv_out" "$bl_out")"

if [ "$sv" -ne 0 ] || [ "$bl" -ne 0 ]; then
  python3 - "$out" <<'PY' 2>/dev/null || printf '{}'
import json, sys
msg = "Spec/backlog gate failed after your edit (fix before continuing):\n" + sys.argv[1][:2500]
print(json.dumps({"decision": "block", "reason": msg}))
PY
fi
exit 0
