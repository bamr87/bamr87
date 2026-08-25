#!/usr/bin/env bash
# ============================================================================
# tools/check-drift.sh — hard drift gate for the dash
#
# Checks ((a,b,d,e,h,j) gate the exit status unless --report; (c,f,g,i,k) warn only):
#   (a) registry <-> .gitmodules parity (paths, branches, AND urls) + no
#       stray/unregistered project dirs. The url leg is offline, so it gates on
#       every PR; the live GitHub side (renames/deletions) is (g) + `dash reconcile`.
#   (b) README.md AUTO:projects span is up to date
#   (c) broken internal links in the built dash        (warn; --links only; needs _site)
#   (d) every top-level module dir has a README
#   (e) each submodule is on its declared branch
#   (f) submodule standardization conformance          (warn; see `dash audit`)
#   (g) registry <-> GitHub reality: renamed / deleted repos & branch drift
#       (warn; --remote / --ci only; needs gh + network). Catches the class the
#       set-vs-set parity check (a) cannot: registry and .gitmodules agreeing
#       with each other while both are stale vs GitHub (renames, org moves,
#       deletions). Advisory because the default CI token is repo-scoped, so a
#       private submodule can 404; self-skips if the API is unreachable.
#   (h) SCHEMA.md pyramid: the hub pyramid lints clean — errors AND warnings
#       gate (--werror posture: the hub practices the discipline it seeds;
#       gitignored ephemera are registered `generated`, so a clean checkout
#       and a working tree agree) — and the generated projects/SCHEMA.md
#       matches .gitmodules + the registry. Offline, submodule-content-agnostic,
#       so it runs in CI too. Mechanical drift: tools/schema_lint.py check . --fix
#   (j) always-latest dependency policy: no SHA-pinned `uses:`, no seed template
#       trailing the hub's action majors, no committed lockfiles, no exact or
#       ceiling pins in hub manifests (docs/DEPENDENCIES.md, `dependencies:` in
#       _data/fleet.yml). Offline and hub-scoped, so it gates on every PR.
#   (k) the fleet half of (j): committed lockfiles and SHA-pinned `uses:` in
#       every registry repo (warn; --remote / --ci only; needs gh + network).
#       Advisory for (g)'s reason — a repo-scoped token 404s on a private repo
#       exactly as on a deleted one — so unreadable repos are reported as
#       UNREAD rather than counted clean.
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
mods = {}  # path -> {branch, url}
cur = None
for line in open(gm_path):
    line = line.strip()
    m = re.match(r'\[submodule "(.+)"\]', line)
    if m:
        cur = {"path": None, "branch": "main", "url": ""}
        continue
    if cur is not None and "=" in line:
        k, v = [x.strip() for x in line.split("=", 1)]
        if k == "path": cur["path"] = v; mods[v] = cur
        elif k == "branch": cur["branch"] = v
        elif k == "url": cur["url"] = v


def norm_url(u):
    """Compare urls without tripping on .git / trailing slash / case."""
    return (u or "").strip().rstrip("/").removesuffix(".git").lower()

reg_by_path = {p["submodule_path"]: p for p in reg if p.get("submodule_path")}
problems = []

# every submodule registered with matching branch
for path, info in mods.items():
    p = reg_by_path.get(path)
    if not p:
        problems.append(f"submodule '{path}' is not in projects.yml")
    elif p.get("branch") != info["branch"]:
        problems.append(f"submodule '{path}' branch mismatch: registry={p.get('branch')} .gitmodules={info['branch']}")
    # URL parity: the registry and .gitmodules can name DIFFERENT repos for the
    # same path and every other check still passes (paths and branches agree),
    # so the fleet silently fetches something other than what the dash
    # advertises. Offline, so it gates on every PR; the live GitHub side of this
    # (renames/deletions) is check (g) and `dash-gen reconcile`.
    if p and p.get("repo_url") and norm_url(p["repo_url"]) != norm_url(info["url"]):
        problems.append(
            f"submodule '{path}' url mismatch: registry={p.get('repo_url')} .gitmodules={info['url']}")

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
# The hub's own pyramid must lint clean: errors AND warnings gate (the hub is
# the flagship adopter — a warning that can sit is a contract that rots, which
# is the exact failure the framework exists to prevent). Ephemeral gitignored
# artifacts are registered `generated`, so clean checkouts and working trees
# agree. projects/SCHEMA.md must match the registry it is generated from.
# Offline, stdlib + PyYAML — same deps the gate already requires. Projects are
# terminal rows, so this never needs submodule content and is CI-safe.
echo "(h) SCHEMA.md pyramid"
if [[ -f "$ROOT/SCHEMA.md" ]]; then
  if lint_out="$("$PY" "$ROOT/tools/schema_lint.py" check "$ROOT" 2>&1)"; then
    nwarn="$(printf '%s' "$lint_out" | grep -c '^warning' || true)"
    if [[ "${nwarn:-0}" -gt 0 ]]; then
      bad "hub pyramid has ${nwarn} warning(s) — warnings gate here; mechanical drift (strays/stale rows) auto-fixes with: python3 tools/schema_lint.py check . --fix"
      printf '%s\n' "$lint_out" | grep '^warning' | sed 's/^/      /'
    else
      ok "hub pyramid lints clean (errors and warnings)"
    fi
  else
    bad "hub pyramid has schema errors (python3 tools/schema_lint.py check .)"
    printf '%s\n' "$lint_out" | grep '^ERROR\|^warning' | sed 's/^/      /'
  fi
  if "$PY" "$ROOT/tools/gen-projects-schema.py" --check >/dev/null 2>&1; then
    ok "projects/SCHEMA.md matches .gitmodules + registry"
  else
    bad "projects/SCHEMA.md is stale (regenerate: tools/gen-projects-schema.py)"
  fi
else
  warn "no root SCHEMA.md yet (hub pyramid not seeded)"
fi

# --- (l): composite action manifests carry no stray expressions -------------
# An action.yml is itself a TEMPLATE: GitHub evaluates `${{ … }}` wherever it
# appears, INCLUDING inside `description:` prose. A context named there purely
# as documentation is parsed as a real expression against a context that does
# not exist at manifest-load time, and the action then fails to load AT ALL —
# taking down every workflow that uses it, before a single step runs.
#
# That is not hypothetical: resolve-fleet-token documented its default as
# "normally ${'$'}{{ github.token }}" in a description, and the first scheduled
# token-rotation run died with "Unrecognized named-value: 'github'" in 34
# seconds. actionlint does not check action manifests, so nothing caught it
# until it ran in production. Descriptions name contexts in backticks instead.
echo "(l) composite action manifests"
if [[ -d "$ROOT/.github/actions" ]]; then
  manifest_hits=0
  while IFS= read -r manifest; do
    offenders="$("$PY" - "$manifest" <<'PYEOF'
import sys, yaml
path = sys.argv[1]
try:
    doc = yaml.safe_load(open(path)) or {}
except Exception as exc:                      # a manifest that will not parse
    print(f"unparseable: {exc}")              # is itself the finding
    sys.exit(0)
for section in ("inputs", "outputs"):
    for name, spec in (doc.get(section) or {}).items():
        if isinstance(spec, dict) and "${{" in str(spec.get("description", "")):
            print(f"{section}.{name}.description")
PYEOF
)"
    if [[ -n "$offenders" ]]; then
      manifest_hits=$((manifest_hits+1))
      bad "${manifest#"$ROOT"/} evaluates expressions in description prose — name contexts in backticks instead"
      printf '%s\n' "$offenders" | sed 's/^/      /'
    fi
  done < <(find "$ROOT/.github/actions" -name 'action.yml' -o -name 'action.yaml' | sort)
  [[ $manifest_hits -eq 0 ]] && ok "no action manifest evaluates expressions in its descriptions"
else
  warn "no .github/actions/ directory"
fi

# Every `scope: fleet` secret in the token contract must be handed to the
# rotation loop by name. GitHub gives a workflow no way to enumerate `secrets.*`
# and never returns a secret's value through the API, so the ONLY route from the
# hub's store to another repo is token-rotation.yml naming it explicitly. A
# contract secret that is not named there can never propagate — and nothing
# would say so: the contract looks right, `dash secrets` reports the repos as
# missing it forever, and every weekly run quietly writes nothing.
if [[ -f "$ROOT/.github/workflows/token-rotation.yml" ]]; then
  unwired="$("$PY" - "$ROOT" <<'PYEOF'
import sys, pathlib, yaml
root = pathlib.Path(sys.argv[1])
cfg = yaml.safe_load((root / "_data/fleet.yml").read_text()) or {}
wf = (root / ".github/workflows/token-rotation.yml").read_text()
for t in cfg.get("tokens") or []:
    if t.get("deprecated") or t.get("scope") != "fleet":
        continue
    if not ((t.get("rotation") or {}).get("enabled")):
        continue
    if f"secrets.{t['name']}" not in wf:
        print(t["name"])
PYEOF
)"
  if [[ -n "$unwired" ]]; then
    bad "fleet-scoped contract secret(s) never handed to token-rotation.yml — they can never propagate"
    printf '%s\n' "$unwired" | sed 's/^/      /'
  else
    ok "every rotating fleet secret is wired into token-rotation.yml"
  fi
fi

# --- (j): always-latest dependency policy ----------------------------------
# The policy (docs/DEPENDENCIES.md, `dependencies:` in _data/fleet.yml) was
# declared in three places and enforced in none, which is how four PRs
# proposing SHA-pinned `uses:` refs came to sit open against it at once. This
# gates the three ways currency actually gets lost:
#
#   1. a SHA-pinned `uses:` — frozen forever by design, the exact thing the
#      policy forbids (the Actions exception is `@vN` major tags, nothing else);
#   2. a seed template whose action major trails the hub's own — templates are
#      copied verbatim into ~40 repos, so a stale one DOWNGRADES every repo it
#      reaches. This already happened twice (see the prose kit's 0.2.0 and
#      agent-context's 0.3.1 changelogs, both written after the fact);
#   3. a committed lockfile or an exact/ceiling pin in a hub manifest.
#
# Offline and hub-scoped, so it gates on every PR. `archive/` templates are
# EXEMPT: those are deliberately frozen shapes that `fanout.sh --upgrade` uses
# to recognize machine-seeded copies — freezing them is the point.
echo "(j) always-latest dependency policy"
dep_out="$("$PY" - "$ROOT" <<'PY'
import os, re, sys

root = sys.argv[1]
problems = []

LOCKS = {"package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock",
         "Gemfile.lock", "poetry.lock", "Pipfile.lock", "uv.lock", "composer.lock"}
SKIP_DIRS = {".git", "projects", "node_modules", "_site", "vendor", ".venv"}
USES = re.compile(r"^\s*-?\s*uses:\s*['\"]?([^'\"\s#]+)")

def walk(*subs):
    for sub in subs:
        base = os.path.join(root, sub)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                yield os.path.join(dirpath, fn)

# 1. no SHA-pinned `uses:` (40-hex ref) anywhere in hub YAML.
# 2. collect action majors so templates can be compared against the workflows.
majors = {}          # action -> {major: [rel paths]}
for path in walk(".github", "templates"):
    if not path.endswith((".yml", ".yaml")):
        continue
    rel = os.path.relpath(path, root)
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except (OSError, UnicodeDecodeError):
        continue
    for n, line in enumerate(lines, 1):
        m = USES.match(line)
        if not m:
            continue
        ref = m.group(1)
        if ref.startswith((".", "docker://")):
            continue
        name, _, rev = ref.partition("@")
        if re.fullmatch(r"[0-9a-f]{40}", rev):
            problems.append(f"{rel}:{n}: SHA-pinned action `{ref}` — policy is major tags (@vN); see docs/DEPENDENCIES.md")
            continue
        mv = re.fullmatch(r"v(\d+)(?:\.\d+)*", rev)
        if mv:
            if re.fullmatch(r"v\d+\.\d+.*", rev):
                problems.append(f"{rel}:{n}: `{ref}` pins a minor/patch — float it to @v{mv.group(1)}")
            majors.setdefault(name, {}).setdefault(int(mv.group(1)), []).append(f"{rel}:{n}")

# 2b. a live seed template must not trail the hub's own workflows for the same
# action: fan-out copies it verbatim, so trailing = a fleet-wide downgrade.
for action, by_major in majors.items():
    hub = [mj for mj, refs in by_major.items()
           if any(r.startswith(".github/") for r in refs)]
    if not hub:
        continue
    newest = max(hub)
    for mj, refs in by_major.items():
        if mj >= newest:
            continue
        for r in refs:
            if r.startswith("templates/") and "/archive/" not in r:
                problems.append(
                    f"{r}: seed template pins `{action}@v{mj}` but the hub runs @v{newest} "
                    f"— fan-out would downgrade every repo it reaches")

# 3. no committed lockfiles, no exact/ceiling pins in hub manifests.
for path in walk(".github", "templates", "tools", "_data", "pages"):
    if os.path.basename(path) in LOCKS:
        problems.append(f"{os.path.relpath(path, root)}: committed lockfile — never committed (gitignored fleet-wide)")
for fn in sorted(os.listdir(root)):
    if fn in LOCKS:
        problems.append(f"{fn}: committed lockfile — never committed (gitignored fleet-wide)")

for path in walk(".github", "tools"):
    base = os.path.basename(path)
    if not (base.startswith("requirements") and base.endswith(".txt")):
        continue
    rel = os.path.relpath(path, root)
    for n, line in enumerate(open(path, encoding="utf-8").read().splitlines(), 1):
        spec = line.split("#", 1)[0].strip()
        if not spec or spec.startswith("-"):
            continue
        if re.search(r"(==|~=|<=?)\s*\d", spec):
            problems.append(f"{rel}:{n}: `{spec}` pins or caps a version — floors (>=) only")

for x in problems:
    print(x)
PY
)"
if [[ -z "$dep_out" ]]; then
  ok "no SHA pins, no stale seed templates, no lockfiles or version ceilings"
else
  while IFS= read -r line; do bad "$line"; done <<< "$dep_out"
fi

# --- (i): vendored-tool parity ---------------------------------------------
# The hub VENDORS two tools into the fleet: tools/unwrap-prose.py (the prose kit
# payload — it defines what the markdown-oneline gate actually enforces) and
# tools/schema_lint.py (the schema kit's linter, itself vendored from
# bamr87/SCHEMA). A vendored copy that drifts is worse than a missing one: the
# repo still passes a gate, just not the same gate as everyone else.
#
# Nothing detected this before, and it happened three times: schema_lint.py
# exists in projects/README (independently rewritten, ~600 diff lines) and
# projects/zer0-pages (~110 diff lines) alongside the hub's canonical copy. The
# schema kit's own VERSION file already states the policy — improvements go
# upstream first, then re-vendor — it simply had no enforcement.
#
# Advisory, never gating: a submodule may legitimately be mid-upgrade, and this
# reads working trees that CI does not check out. Local-only for that reason.
if [[ -d "$ROOT/projects" ]]; then
  echo "(i) vendored-tool parity"
  vend_checked=0 vend_drift=0
  for tool in unwrap-prose.py schema_lint.py; do
    [[ -f "$ROOT/tools/$tool" ]] || continue
    while IFS= read -r copy; do
      [[ -f "$copy" ]] || continue
      vend_checked=$((vend_checked + 1))
      if ! cmp -s "$ROOT/tools/$tool" "$copy"; then
        vend_drift=$((vend_drift + 1))
        warn "${copy#"$ROOT"/} differs from tools/${tool} ($(diff "$ROOT/tools/$tool" "$copy" | grep -c '^[<>]' || true) changed line(s))"
      fi
    done < <(find "$ROOT/projects" -mindepth 2 -maxdepth 3 -name "$tool" -not -path '*/node_modules/*' 2>/dev/null)
  done
  if [[ $vend_checked -eq 0 ]]; then
    warn "skipped (no submodule copies found — submodules not checked out?)"
  elif [[ $vend_drift -eq 0 ]]; then
    ok "all ${vend_checked} vendored copies match the hub"
  else
    # Two different remedies, because the two tools are vendored by different
    # kits: unwrap-prose.py rides the prose fan-out, schema_lint.py is a
    # re-vendor from bamr87/SCHEMA via the schema kit.
    warn "${vend_drift}/${vend_checked} vendored copies drifted"
    warn "  unwrap-prose.py → tools/fanout.sh --kit prose --target <name> --upgrade"
    warn "  schema_lint.py  → upstream the change to bamr87/SCHEMA first, then re-vendor (templates/schema/VERSION)"
  fi
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

# --- (k): fleet-wide dependency policy -------------------------------------
# Check (j) is offline and hub-scoped: it proves the HUB is clean and that no
# seed template will downgrade anyone, but it cannot see the ~40 repos the
# policy actually governs. This is the other half — one git-tree read per repo,
# looking for the two violations that are visible without cloning: committed
# lockfiles and SHA-pinned `uses:` refs.
#
# Advisory and --remote/--ci only, for the same reason as (g): a repo-scoped
# token 404s on a private repo exactly as on a deleted one, so a miss here is
# not evidence of a clean repo. Unreadable repos are reported as unread rather
# than counted as passing — the distinction matters, since "0 violations" over
# 40 unread repos would otherwise read as a fleet-wide all-clear.
if [[ $RUN_REMOTE -eq 1 ]]; then
  echo "(k) fleet-wide dependency policy"
  if command -v gh >/dev/null 2>&1; then
    k_out="$("$PY" - "$ROOT" <<'PY'
import sys, os, subprocess, json, re, base64
try:
    import yaml
except ImportError:
    sys.exit(2)

root = sys.argv[1]
reg = yaml.safe_load(open(os.path.join(root, "_data/projects.yml"))) or []
if isinstance(reg, dict):
    reg = reg.get("projects", [])

def gh(path):
    r = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    return r.returncode, r.stdout

if gh("rate_limit")[0] != 0:
    sys.exit(2)

LOCKS = {"package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock",
         "Gemfile.lock", "poetry.lock", "Pipfile.lock", "uv.lock", "composer.lock"}
SHA_USES = re.compile(r"^\s*-?\s*uses:\s*['\"]?([^'\"\s#]+@[0-9a-f]{40})")
PIN_USES = re.compile(r"^\s*-?\s*uses:\s*['\"]?([^'\"\s#]+@v\d+\.\d+[^'\"\s#]*)")
REQ_PIN = re.compile(r"(==|~=|<)")

def slug_of(url):
    if not url or "github.com/" not in url:
        return None
    tail = url.split("github.com/", 1)[1].strip().rstrip("/")
    if tail.endswith(".git"):
        tail = tail[:-4]
    parts = tail.split("/")
    return f"{parts[0]}/{parts[1]}" if len(parts) >= 2 else None

problems, unread, scanned = [], [], 0
for p in reg:
    slug = slug_of(p.get("repo_url", ""))
    if not slug:
        continue
    branch = p.get("branch") or "main"
    rc, out = gh(f"repos/{slug}/git/trees/{branch}?recursive=1")
    if rc != 0:
        unread.append(slug)
        continue
    try:
        tree = json.loads(out).get("tree", [])
    except json.JSONDecodeError:
        unread.append(slug)
        continue
    scanned += 1
    paths = [e["path"] for e in tree if e.get("type") == "blob"]

    for path in paths:
        if os.path.basename(path) in LOCKS:
            problems.append(f"{slug}: committed lockfile {path}")

    # SHA pins live in workflow YAML; read only those, and only if present.
    for path in paths:
        if not re.fullmatch(r"\.github/workflows/[^/]+\.ya?ml", path):
            continue
        rc, out = gh(f"repos/{slug}/contents/{path}?ref={branch}")
        if rc != 0:
            continue
        try:
            blob = json.loads(out)
            text = base64.b64decode(blob.get("content", "")).decode("utf-8", "replace")
        except Exception:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            m = SHA_USES.match(line)
            if m:
                problems.append(f"{slug}: SHA-pinned action {path}:{n} `{m.group(1)}`")
                continue
            m = PIN_USES.match(line)
            if m:
                problems.append(f"{slug}: minor/patch-pinned action {path}:{n} `{m.group(1)}`")

    # Manifest pins. Counted per file rather than per dependency: a repo with 71
    # pinned requirements is one conversion job, and 71 warning lines would bury
    # every other repo in the report.
    for path in paths:
        base = os.path.basename(path)
        if "node_modules" in path or "/vendor/" in path:
            continue
        if base.startswith("requirements") and base.endswith(".txt"):
            kind = "req"
        elif base == "package.json":
            kind = "npm"
        elif base == "Gemfile":
            kind = "gem"
        else:
            continue
        rc, out = gh(f"repos/{slug}/contents/{path}?ref={branch}")
        if rc != 0:
            continue
        try:
            text = base64.b64decode(json.loads(out).get("content", "")).decode("utf-8", "replace")
        except Exception:
            continue

        pinned = []
        if kind == "req":
            for line in text.splitlines():
                spec = line.split("#", 1)[0].strip()
                if spec and not spec.startswith("-") and REQ_PIN.search(spec):
                    pinned.append(spec)
        elif kind == "npm":
            try:
                d = json.loads(text)
            except Exception:
                continue
            for k in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                for name, spec in (d.get(k) or {}).items():
                    # `*` and a bare floor are the compliant shapes; local/git/url
                    # specifiers name no version at all, so they cannot pin one.
                    if not isinstance(spec, str) or spec == "*" or spec.startswith(
                            (">=", "file:", "link:", "workspace:", "git", "http", "npm:")):
                        continue
                    pinned.append(f"{name}@{spec}")
        else:
            for line in text.splitlines():
                s = line.split("#", 1)[0].strip()
                m = re.match(r'gem\s+["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']', s)
                # A FLOOR IS NOT A PIN. Matching the version off the gem name and
                # then testing the whole remainder for `>=` is how a first pass at
                # this reported the hub's own compliant `github-pages ">= 228"`.
                if m and not m.group(2).strip().startswith(">="):
                    pinned.append(f"{m.group(1)} {m.group(2)}")

        if pinned:
            shown = ", ".join(pinned[:3])
            more = f" (+{len(pinned) - 3} more)" if len(pinned) > 3 else ""
            problems.append(f"{slug}: {len(pinned)} pinned in {path} — {shown}{more}")

print(f"__SCANNED__ {scanned}")
if unread:
    print(f"__UNREAD__ {len(unread)} {' '.join(sorted(unread)[:6])}")
for x in problems:
    print(x)
PY
)"
    k_rc=$?
    if [[ $k_rc -eq 2 ]]; then
      warn "skipped (GitHub API unreachable or gh not authenticated)"
    else
      k_scanned="$(printf '%s\n' "$k_out" | sed -n 's/^__SCANNED__ //p')"
      k_unread="$(printf '%s\n' "$k_out" | sed -n 's/^__UNREAD__ //p')"
      k_probs="$(printf '%s\n' "$k_out" | grep -v '^__' | grep -v '^$' || true)"
      if [[ -z "$k_probs" ]]; then
        ok "no lockfiles or SHA pins in ${k_scanned:-0} readable fleet repo(s)"
      else
        while IFS= read -r line; do warn "$line"; done <<< "$k_probs"
        warn "  convert a repo with: tools/unpin-deps.sh <checkout>  (fleet-wide: deps-fanout.yml)"
      fi
      # Never let unread repos masquerade as clean ones.
      [[ -n "$k_unread" ]] && warn "${k_unread% *} unread (private or 404 under a repo-scoped token) — NOT verified clean"
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
