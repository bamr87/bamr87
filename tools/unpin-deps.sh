#!/usr/bin/env bash
# ============================================================================
# tools/unpin-deps.sh — convert one repo to the fleet's ALWAYS-LATEST policy
#
# The mechanical half of the dependency policy declared in _data/fleet.yml
# (`dependencies:`) and explained in docs/DEPENDENCIES.md: every install
# resolves whatever is newest, breakage surfaces in CI, and the daily
# fleet-pulse loop triages it. Run against a repo checkout (cwd by default);
# the deps-latest kit in tools/fanout.sh calls this inside each clone.
#
# WHAT IT DOES (idempotent — a converted repo comes out unchanged):
#   1. `git rm`s every committed lockfile (npm/pnpm/yarn/bundler/poetry/
#      pipenv/uv/composer) at any depth.
#   2. Appends a marker-guarded lockfile block to .gitignore.
#   3. package.json: every registry semver range in dependencies /
#      devDependencies / optionalDependencies becomes "*" (latest).
#      file:/link:/workspace:/git/URL/alias specifiers are left alone.
#   4. requirements*.txt (and requirements/*.txt): version specifiers are
#      stripped to bare `name[extras]`, keeping env markers, comments,
#      option lines (-r/-e/--index-url), URLs, and local paths.
#   5. Gemfile: quoted version-requirement args are dropped from `gem` lines
#      (kwargs like group:/require:/path:/github: survive); exact
#      `ruby "X.Y.Z"` pins are removed so CI's toolchain version rules.
#   6. .github/workflows/*.yml: `npm ci` → `npm install`,
#      --frozen-lockfile/--immutable dropped, lockfile-keyed `cache:` lines
#      removed, and `uses: owner/action@vX.Y.Z` floated to `@vX`.
#
# WHAT IT LEAVES (reported as follow-ups, for a human or the doctor agent):
#   pyproject.toml/poetry/Pipfile dependency tables (no safe stdlib TOML
#   writer), hash-pinned requirements files, npm overrides/resolutions,
#   and toolchain files (.ruby-version/.nvmrc/.python-version — toolchain
#   versions are governed by _data/fleet.yml, not this script).
#
# Usage: tools/unpin-deps.sh [repo-dir]
# ============================================================================
set -euo pipefail

TARGET_DIR="${1:-.}"
cd "$TARGET_DIR"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 \
  || { echo "unpin-deps: not a git work tree: $TARGET_DIR" >&2; exit 2; }

LOCKS=(package-lock.json npm-shrinkwrap.json pnpm-lock.yaml yarn.lock
       Gemfile.lock poetry.lock Pipfile.lock uv.lock composer.lock)

# --- 1. drop committed lockfiles (any depth) --------------------------------
spec=()
for l in "${LOCKS[@]}"; do spec+=("$l" "*/$l"); done
while IFS= read -r -d '' f; do
  git rm -q -f -- "$f"
  echo "removed lockfile: $f"
done < <(git ls-files -z -- "${spec[@]}")

# --- 2. gitignore the lot, marker-guarded so reruns are no-ops --------------
MARK="# --- always-latest dependency policy: lockfiles are local ephemera (bamr87/bamr87 docs/DEPENDENCIES.md) ---"
if ! grep -qFx "$MARK" .gitignore 2>/dev/null; then
  if [ -f .gitignore ] && [ -n "$(tail -c1 .gitignore)" ]; then echo >> .gitignore; fi
  { echo "$MARK"; printf '%s\n' "${LOCKS[@]}"; } >> .gitignore
  echo "updated: .gitignore (lockfiles ignored)"
fi

# --- 3-6. manifest + workflow rewrites (python3 for reliable parsing) -------
python3 - <<'PY'
import json, re, subprocess, sys

tracked = subprocess.run(["git", "ls-files", "-z"], capture_output=True,
                         check=True).stdout.decode().split("\0")
tracked = [t for t in tracked if t]

def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()

def write(p, s):
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(s)
    print(f"unpinned: {p}")

followups = []

# ---- package.json: registry semver ranges -> "*" ---------------------------
KEEP = ("file:", "link:", "portal:", "workspace:", "npm:", "catalog:",
        "git", "github:", "http://", "https://")
for p in [t for t in tracked if t.split("/")[-1] == "package.json"
          and "node_modules/" not in t]:
    try:
        data = json.loads(read(p))
    except (json.JSONDecodeError, UnicodeDecodeError):
        followups.append(f"{p}: unparseable JSON — convert by hand")
        continue
    changed = False
    for sect in ("dependencies", "devDependencies", "optionalDependencies"):
        for name, rng in list((data.get(sect) or {}).items()):
            if isinstance(rng, str) and rng != "*" and not rng.startswith(KEEP):
                data[sect][name] = "*"
                changed = True
    if changed:
        write(p, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    for sect in ("overrides", "resolutions", "pnpm"):
        if isinstance(data, dict) and data.get(sect):
            followups.append(f"{p}: has `{sect}` forcing transitive versions — review by hand")

# ---- requirements*.txt: strip specifiers to bare name[extras] --------------
REQ_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*(\[[^\]]*\])?)")
def unpin_requirements(text):
    out, changed = [], False
    for line in text.splitlines():
        s = line.strip()
        if (not s or s.startswith(("#", "-", "/", ".")) or "://" in s
                or " @ " in s or s.endswith("\\")):
            out.append(line)          # comments, options, paths, URLs, continuations
            continue
        req, sep, marker = line.partition(";")
        req_part, hash_, comment = req.partition(" #")
        m = REQ_NAME.match(req_part)
        if not m:
            out.append(line)
            continue
        new = m.group(1)
        if marker:
            new += " ;" + marker
        if comment:
            new += "  #" + comment
        out.append(new)
        changed = changed or new != line
    return "\n".join(out) + "\n", changed

for p in [t for t in tracked if re.search(r"(^|/)requirements[^/]*\.txt$", t)
          or re.search(r"(^|/)requirements/[^/]+\.txt$", t)]:
    text = read(p)
    if "--hash" in text:
        followups.append(f"{p}: hash-pinned — hashes require exact pins; convert deliberately")
        continue
    new, changed = unpin_requirements(text)
    if changed:
        write(p, new)

# ---- Gemfile: drop quoted version args + exact ruby pins --------------------
GEM_VER = re.compile(r"""^(\s*gem\s+(["'])[A-Za-z0-9._-]+\2)(?:\s*,\s*(["'])[^"']*\3)+""")
RUBY_PIN = re.compile(r"""^\s*ruby\s+["'][^"']+["']\s*$""")
for p in [t for t in tracked if t.split("/")[-1] in ("Gemfile", "gems.rb")]:
    out, changed = [], False
    for line in read(p).splitlines():
        if RUBY_PIN.match(line):
            changed = True            # CI's toolchain version rules; drop the pin
            continue
        new = GEM_VER.sub(r"\1", line)
        changed = changed or new != line
        out.append(new)
    if changed:
        write(p, "\n".join(out) + "\n")

# ---- workflows: lockfile-dependent installs/caches + action tags -----------
CACHE_LINE = re.compile(r"""^\s*cache:\s*["']?(npm|pnpm|yarn)["']?\s*$""")
CACHE_DEP = re.compile(r"^\s*cache-dependency-path:.*(lock|shrinkwrap)", re.I)
USES_TAG = re.compile(r"(uses:\s*[^\s@]+@v)(\d+)\.[\d.]+")
for p in [t for t in tracked if t.startswith(".github/workflows/")
          and t.endswith((".yml", ".yaml"))]:
    out, changed = [], False
    for line in read(p).splitlines():
        if CACHE_LINE.match(line) or CACHE_DEP.match(line):
            changed = True
            continue
        new = re.sub(r"\bnpm ci\b", "npm install", line)
        new = re.sub(r"\s--(frozen-lockfile|immutable)\b", "", new)
        new = USES_TAG.sub(r"\1\2", new)
        changed = changed or new != line
        out.append(new)
    if changed:
        write(p, "\n".join(out) + "\n")

# ---- follow-ups the script deliberately does not automate -------------------
for t in tracked:
    base = t.split("/")[-1]
    if base == "pyproject.toml" and re.search(
            r"^\s*(dependencies\s*=|\[tool\.poetry)", read(t), re.M):
        followups.append(f"{t}: dependency table not auto-edited (no stdlib TOML writer) — unpin by hand or let the doctor agent")
    elif base == "Pipfile":
        followups.append(f"{t}: Pipfile not auto-edited — unpin by hand")

for f in dict.fromkeys(followups):
    print(f"follow-up: {f}")
PY

echo "unpin-deps: done — review with 'git status' / 'git diff'"
