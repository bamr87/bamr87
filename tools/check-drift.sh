#!/usr/bin/env bash
# ============================================================================
# tools/check-drift.sh — hard drift gate for the dash
#
# Checks (each contributes to the exit status unless --report):
#   (a) registry <-> .gitmodules parity + no stray/unregistered project dirs
#   (b) README.md AUTO:projects span is up to date
#   (c) broken internal links in the built dash        (--links only; needs _site)
#   (d) every top-level module dir has a README
#   (e) each submodule is on its declared branch
#   (f) submodule standardization conformance          (warn; see `dash audit`)
#   (g) registry <-> GitHub reality: renamed / deleted repos & branch drift
#       (warn; --remote / --ci only; needs gh + network). Catches the class the
#       set-vs-set parity check (a) cannot: registry and .gitmodules agreeing
#       with each other while both are stale vs GitHub (renames, org moves,
#       deletions). Advisory because the default CI token is repo-scoped, so a
#       private submodule can 404; self-skips if the API is unreachable.
#
# (e) is LOCAL-ONLY (skipped when submodules aren't checked out, e.g. CI).
# (c) the internal-link check needs a built _site + lychee, so it is NOT part of
#     the CI gate (which no longer builds the site) — run it locally with --links.
#
# Modes:
#   (default)   run gating checks (a,b,d, + e when checked out); non-zero on failure
#   --ci        gate + GitHub-reality (g). Fast: no Ruby/Jekyll/lychee. (needs gh)
#   --links     also run the link check (needs a locally built _site + lychee)
#   --remote    also run the GitHub-reality check (g)
#   --report    print a summary, never fail (used by `dash status`)
# ============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="gate"
RUN_LINKS=0
RUN_REMOTE=0
case "${1:-}" in
  --report) MODE="report" ;;
  --ci)     MODE="gate"; RUN_REMOTE=1 ;;   # no link check: CI doesn't build _site
  --links)  RUN_LINKS=1 ;;
  --remote) RUN_REMOTE=1 ;;
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
reg = yaml.safe_load(open(os.path.join(root, "_data/projects.yml"))) or []

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

# (e) current checked-out branch matches declared. LOCAL-ONLY: only runs for
# submodules actually checked out (a `.git` inside the dir). When a submodule is
# NOT checked out — e.g. CI, which is submodule-content-agnostic — `git -C` walks
# up to the PARENT repo and returns its branch ("main"), which false-positived the
# gate on every non-main submodule. Branch drift in CI is covered by (a) (static
# registry↔.gitmodules) and (g) (declared↔GitHub default). Detached HEAD at the
# recorded SHA (normal after `git submodule update`) is not drift.
for path, info in mods.items():
    if not os.path.exists(os.path.join(root, path, ".git")):
        continue  # not checked out here; can't (and shouldn't) infer its branch
    try:
        br = subprocess.run(["git","-C",os.path.join(root,path),"rev-parse","--abbrev-ref","HEAD"],
                            capture_output=True, text=True).stdout.strip()
    except Exception:
        br = "?"
    if br and br not in ("HEAD", "", info["branch"]):
        problems.append(f"submodule '{path}' on branch '{br}', declared '{info['branch']}'")

# stray/unregistered project dirs on disk. The parity loops above are set-vs-set
# and never look at the tree, so a project dropped into projects/ that is in
# neither the registry nor .gitmodules is otherwise invisible and CI stays green.
projects_dir = os.path.join(root, "projects")
if os.path.isdir(projects_dir):
    for entry in sorted(os.listdir(projects_dir)):
        full = os.path.join(projects_dir, entry)
        if not os.path.isdir(full):
            continue
        sp = f"projects/{entry}"
        if sp in reg_by_path or sp in mods:
            continue
        if os.path.exists(os.path.join(full, ".git")):
            problems.append(f"unregistered project dir '{sp}' contains a git repo — add it to .gitmodules + the registry (use /onboard-dir), or remove it")
        else:
            problems.append(f"stray dir '{sp}' is in neither the registry nor .gitmodules")

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
    _*|site|node_modules|assets|vendor|pages|lychee|.git) continue ;;
  esac
  [[ -f "${d}README.md" || -f "${d}readme.md" || -f "${d}README.rst" ]] || missing+=("$name")
done
if [[ ${#missing[@]} -eq 0 ]]; then ok "all module dirs have a README"; else bad "missing README in: ${missing[*]}"; fi

# --- (f): standardization conformance (report/warn, non-gating) ------------
# Filesystem-based via audit-standards.sh — most complete locally where the
# submodules are checked out; in a submodule-less CI checkout it self-skips.
echo "(f) standardization conformance"
if [[ -x "$ROOT/tools/audit-standards.sh" ]]; then
  summary="$("$ROOT/tools/audit-standards.sh" --json --no-color 2>/dev/null)"
  if [[ -n "$summary" ]]; then
    read -r audited failn < <(printf '%s' "$summary" | "$PY" -c 'import sys,json; d=json.load(sys.stdin)["summary"]; print(d["audited"], d["with_required_gaps"])' 2>/dev/null)
    if [[ "${audited:-0}" == "0" ]]; then warn "standardization: skipped (no submodules checked out)"
    elif [[ "${failn:-0}" == "0" ]]; then ok "all ${audited} checked-out submodules meet their tier baseline"
    else warn "${failn}/${audited} submodules missing required artifacts (run: tools/dash audit)"; fi
  else
    warn "could not run standardization audit"
  fi
else
  warn "tools/audit-standards.sh not found"
fi

# --- (h): SCHEMA.md pyramid (structural contracts) --------------------------
# The hub's own pyramid must lint green (errors gate; stray warnings surface),
# and projects/SCHEMA.md must match the registry it is generated from. Offline,
# stdlib + PyYAML — same deps the gate already requires. Projects are terminal
# rows, so this never needs submodule content and is CI-safe.
echo "(h) SCHEMA.md pyramid"
if [[ -f "$ROOT/SCHEMA.md" ]]; then
  if lint_out="$("$PY" "$ROOT/tools/schema_lint.py" check "$ROOT" 2>&1)"; then
    nwarn="$(printf '%s' "$lint_out" | grep -c '^warning' || true)"
    if [[ "${nwarn:-0}" -gt 0 ]]; then
      warn "hub pyramid: green with ${nwarn} stray warning(s) (python3 tools/schema_lint.py check .)"
    else
      ok "hub pyramid lints green"
    fi
  else
    bad "hub pyramid has schema errors (python3 tools/schema_lint.py check .)"
  fi
  if "$PY" "$ROOT/tools/gen-projects-schema.py" --check >/dev/null 2>&1; then
    ok "projects/SCHEMA.md matches .gitmodules + registry"
  else
    bad "projects/SCHEMA.md is stale (regenerate: tools/gen-projects-schema.py)"
  fi
else
  warn "no root SCHEMA.md yet (hub pyramid not seeded)"
fi

# --- (g): registry <-> GitHub reality (renames / deletions / branch) -------
# Closes the class the set-vs-set parity check (a) is blind to: registry and
# .gitmodules can agree with each other while both are stale vs GitHub. Advisory
# (warn) — the default CI token is repo-scoped so a private submodule may 404,
# and a network blip should never fail the gate.
if [[ $RUN_REMOTE -eq 1 ]]; then
  echo "(g) registry ↔ GitHub reality"
  if command -v gh >/dev/null 2>&1; then
    g_out="$("$PY" - "$ROOT" <<'PY'
import sys, os, subprocess, json
try:
    import yaml
except ImportError:
    sys.exit(2)
root = sys.argv[1]
reg = yaml.safe_load(open(os.path.join(root, "_data/projects.yml"))) or []

def gh(path):
    r = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr

# canary: is the API reachable + authenticated?
if gh("rate_limit")[0] != 0:
    sys.exit(2)

def slug_of(url):
    if not url or "github.com/" not in url:
        return None
    tail = url.split("github.com/", 1)[1].strip().rstrip("/")
    if tail.endswith(".git"):
        tail = tail[:-4]
    parts = tail.split("/")
    return f"{parts[0]}/{parts[1]}" if len(parts) >= 2 else None

problems = []
for p in reg:
    slug = slug_of(p.get("repo_url", ""))
    if not slug:
        continue
    name = p.get("name")
    rc, out, err = gh(f"repos/{slug}")
    if rc != 0:
        if "Not Found" in err or "404" in err:
            problems.append(f"{name}: {slug} not found on GitHub (deleted / renamed-without-redirect / private) — reconcile repo_url or remove")
        else:
            problems.append(f"{name}: could not verify {slug}")
        continue
    try:
        data = json.loads(out)
    except Exception:
        continue
    full = data.get("full_name") or ""
    defbr = data.get("default_branch") or ""
    if full and full.lower() != slug.lower():
        problems.append(f"{name}: renamed on GitHub {slug} -> {full} — update repo_url + .gitmodules url")
    decl = p.get("branch")
    if p.get("submodule_path") and decl and defbr and decl != defbr:
        problems.append(f"{name}: declared branch '{decl}' but GitHub default is '{defbr}'")

for x in problems:
    print(x)
PY
)"
    g_rc=$?
    if [[ $g_rc -eq 2 ]]; then
      warn "skipped (GitHub API unreachable or gh not authenticated)"
    elif [[ -z "$g_out" ]]; then
      ok "registry matches GitHub (names, branches)"
    else
      while IFS= read -r line; do warn "$line"; done <<< "$g_out"
    fi
  else
    warn "skipped (gh not installed)"
  fi
fi

# --- (c): internal links ---------------------------------------------------
if [[ $RUN_LINKS -eq 1 ]]; then
  echo "(c) internal link check"
  if command -v lychee >/dev/null && [[ -d "$ROOT/_site" ]]; then
    # --root-dir lets lychee resolve root-relative (/foo/) links against the built
    # site offline; without it every internal link errors as "provide a root dir".
    # Non-gating (warn): surfaced for visibility, but broken internal links don't
    # block the registry/README drift gate (re-promote to `bad` once links are clean).
    if lychee --offline --root-dir "$ROOT/_site" "$ROOT/_site" >/dev/null 2>&1; then ok "no broken internal links"; else warn "broken internal links (run: lychee --offline --root-dir _site _site)"; fi
  else
    warn "skipped (need lychee + built _site)"
  fi
fi

echo
if [[ "$MODE" == "report" ]]; then
  [[ $fail -eq 0 ]] && echo "No drift." || echo "${fail} drift issue(s) — informational (run 'tools/check-drift.sh' to gate)."
  exit 0
fi
[[ $fail -eq 0 ]] && { echo "✅ No drift."; exit 0; } || { echo "❌ ${fail} drift issue(s)."; exit 1; }
