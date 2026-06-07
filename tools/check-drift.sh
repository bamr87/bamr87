#!/usr/bin/env bash
# ============================================================================
# tools/check-drift.sh — hard drift gate for the dash
#
# Checks (each contributes to the exit status unless --report):
#   (a) registry <-> .gitmodules parity (paths + branches)
#   (b) README.md AUTO:projects span is up to date
#   (c) broken internal links in the built dash        (--links / --ci only)
#   (d) every top-level dir + submodule has a README
#   (e) each submodule is on its declared branch
#
# Modes:
#   (default)   run gating checks (a,b,d,e); exit non-zero on any failure
#   --ci        run all checks incl. links (requires dash/_site built + lychee)
#   --links     also run the link check
#   --report    print a summary, never fail (used by `dash status`)
# ============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="gate"
RUN_LINKS=0
case "${1:-}" in
  --report) MODE="report" ;;
  --ci)     MODE="gate"; RUN_LINKS=1 ;;
  --links)  RUN_LINKS=1 ;;
esac

PY="${PYTHON:-python3}"
fail=0
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$1"; fail=$((fail+1)); }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; }

echo "== Drift check =="

# --- (a) + (e): registry parity & submodule branches ----------------------
echo "(a) registry ↔ .gitmodules parity / (e) submodule branches"
"$PY" - "$ROOT" <<'PY'
import sys, subprocess, configparser, os, re
import yaml

root = sys.argv[1]
reg = yaml.safe_load(open(os.path.join(root, "dash/_data/projects.yml"))) or []

# parse .gitmodules
gm_path = os.path.join(root, ".gitmodules")
mods = {}  # path -> branch
cur = None
for line in open(gm_path):
    line = line.strip()
    m = re.match(r'\[submodule "(.+)"\]', line)
    if m:
        cur = {"path": None, "branch": "main"}
        continue
    if cur is not None and "=" in line:
        k, v = [x.strip() for x in line.split("=", 1)]
        if k == "path": cur["path"] = v; mods[v] = cur
        elif k == "branch": cur["branch"] = v

reg_by_path = {p["submodule_path"]: p for p in reg if p.get("submodule_path")}
problems = []

# every submodule registered with matching branch
for path, info in mods.items():
    p = reg_by_path.get(path)
    if not p:
        problems.append(f"submodule '{path}' is not in projects.yml")
    elif p.get("branch") != info["branch"]:
        problems.append(f"submodule '{path}' branch mismatch: registry={p.get('branch')} .gitmodules={info['branch']}")

# every registry submodule_path exists in .gitmodules
for path in reg_by_path:
    if path not in mods:
        problems.append(f"registry submodule_path '{path}' not in .gitmodules")

# (e) current checked-out branch matches declared.
# NOTE: a fresh `git submodule update`/CI checkout leaves submodules in DETACHED
# HEAD at the recorded SHA — that is normal and NOT drift. We only flag a *named*
# branch that differs from the declared one (a real local divergence).
for path, info in mods.items():
    try:
        br = subprocess.run(["git","-C",os.path.join(root,path),"rev-parse","--abbrev-ref","HEAD"],
                            capture_output=True, text=True).stdout.strip()
    except Exception:
        br = "?"
    if br and br not in ("HEAD", "", info["branch"]):
        problems.append(f"submodule '{path}' on branch '{br}', declared '{info['branch']}'")

for p in problems:
    print("DRIFT:" + p)
sys.exit(1 if problems else 0)
PY
if [[ $? -eq 0 ]]; then ok "registry/submodule parity"; else bad "registry/submodule parity (see DRIFT lines above)"; fi

# --- (b): README AUTO:projects freshness ----------------------------------
echo "(b) README AUTO:projects freshness"
if "$ROOT/tools/dash-gen" readme --check >/dev/null 2>&1; then
  ok "README AUTO:projects up to date"
else
  rc=$?
  if [[ $rc -eq 1 ]]; then bad "README AUTO:projects is stale (run: tools/dash-gen readme)"; else warn "could not check README (dash-gen error)"; fi
fi

# --- (d): missing READMEs --------------------------------------------------
# Checks code/module dirs only. Skips: dot-dirs (not matched by */), Jekyll
# underscore dirs (_site/_data/_includes/...), build artifacts, and content dirs.
echo "(d) README presence"
missing=()
for d in "$ROOT"/*/; do
  name="$(basename "$d")"
  case "$name" in
    _*|site|node_modules|assets|vendor|pages|.git) continue ;;
  esac
  [[ -f "${d}README.md" || -f "${d}readme.md" || -f "${d}README.rst" ]] || missing+=("$name")
done
if [[ ${#missing[@]} -eq 0 ]]; then ok "all module dirs have a README"; else bad "missing README in: ${missing[*]}"; fi

# --- (c): internal links ---------------------------------------------------
if [[ $RUN_LINKS -eq 1 ]]; then
  echo "(c) internal link check"
  if command -v lychee >/dev/null && [[ -d "$ROOT/dash/_site" ]]; then
    if lychee --offline "$ROOT/dash/_site" >/dev/null 2>&1; then ok "no broken internal links"; else bad "broken internal links (run: lychee --offline dash/_site)"; fi
  else
    warn "skipped (need lychee + built dash/_site)"
  fi
fi

echo
if [[ "$MODE" == "report" ]]; then
  [[ $fail -eq 0 ]] && echo "No drift." || echo "${fail} drift issue(s) — informational (run 'tools/check-drift.sh' to gate)."
  exit 0
fi
[[ $fail -eq 0 ]] && { echo "✅ No drift."; exit 0; } || { echo "❌ ${fail} drift issue(s)."; exit 1; }
