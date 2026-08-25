#!/usr/bin/env python3
"""
run-dash orchestration driver — the map a Claude Code agent reads BEFORE
dispatching work into a submodule.

This repo is a hub: ~40 independent project repos vendored in as git submodules,
with a registry (_data/projects.yml) as the single source of truth. The dash CLI
(tools/dash) already covers status / monitor / serve. What it does NOT give you is
the one thing an orchestrating agent needs: a single joined view of, for each
project — its declared branch, whether it's even checked out yet, its stack, the
command that runs it, the context files to load, and its live health — plus the
exact copy-paste incantation to get into that submodule on the right branch.

That join is what this driver produces.

Usage:
  python3 .claude/skills/run-dash/driver.py            # the orchestration map (all projects)
  python3 .claude/skills/run-dash/driver.py map        # same, explicit
  python3 .claude/skills/run-dash/driver.py project cv-builder-pro   # work order for one project
  python3 .claude/skills/run-dash/driver.py map --json              # machine-readable
  python3 .claude/skills/run-dash/driver.py project README --json

Accepts a project by registry `name`, `slug`, or submodule path. Health columns
appear only if _data/project_health.yml exists (run `tools/dash gen health` first;
that file is ephemeral and gitignored — never commit it).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write(
        "run-dash driver requires PyYAML (same dep as tools/dash-gen): pip install pyyaml\n"
    )
    sys.exit(2)


# --------------------------------------------------------------------------- #
# repo location
# --------------------------------------------------------------------------- #
def repo_root() -> Path:
    here = Path(__file__).resolve().parent
    try:
        out = subprocess.run(
            ["git", "-C", str(here), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        if out:
            return Path(out)
    except Exception:
        pass
    # fallback: driver.py -> run-dash -> skills -> .claude -> <root>
    return Path(__file__).resolve().parents[3]


ROOT = repo_root()
REGISTRY = ROOT / "_data" / "projects.yml"
HEALTH = ROOT / "_data" / "project_health.yml"
GITMODULES = ROOT / ".gitmodules"


# --------------------------------------------------------------------------- #
# data gathering
# --------------------------------------------------------------------------- #
def load_registry() -> list[dict]:
    if not REGISTRY.exists():
        sys.stderr.write(f"registry not found: {REGISTRY}\n")
        sys.exit(2)
    with REGISTRY.open() as fh:
        return yaml.safe_load(fh) or []


def load_health() -> dict[str, dict]:
    if not HEALTH.exists():
        return {}
    with HEALTH.open() as fh:
        data = yaml.safe_load(fh) or []
    return {h["name"]: h for h in data if isinstance(h, dict) and "name" in h}


def gitmodules() -> dict[str, dict]:
    """path -> {url, branch} parsed via `git config -f .gitmodules`."""
    if not GITMODULES.exists():
        return {}
    out = subprocess.run(
        ["git", "config", "-f", str(GITMODULES), "--list"],
        capture_output=True, text=True,
    ).stdout
    subs: dict[str, dict] = {}
    fields: dict[str, dict] = {}
    for line in out.splitlines():
        if "=" not in line or not line.startswith("submodule."):
            continue
        key, val = line.split("=", 1)
        # submodule.<name>.<field>
        parts = key.split(".")
        if len(parts) < 3:
            continue
        name = ".".join(parts[1:-1])
        field = parts[-1]
        fields.setdefault(name, {})[field] = val
    for name, f in fields.items():
        if "path" in f:
            subs[f["path"]] = {"url": f.get("url"), "branch": f.get("branch")}
    return subs


def submodule_state() -> dict[str, str]:
    """path -> one of: missing(-), ok( ), modified(+), conflict(U)."""
    out = subprocess.run(
        ["git", "-C", str(ROOT), "submodule", "status"],
        capture_output=True, text=True,
    ).stdout
    states: dict[str, str] = {}
    legend = {"-": "uninit", " ": "ready", "+": "moved", "U": "conflict"}
    for line in out.splitlines():
        if not line:
            continue
        ch = line[0]
        rest = line[1:].split()
        if len(rest) < 2:
            continue
        path = rest[1]
        states[path] = legend.get(ch, "unknown")
    return states


# --------------------------------------------------------------------------- #
# per-project enrichment
# --------------------------------------------------------------------------- #
# stack tag -> (install, run, test/build) — best-effort heuristic. Confirmed
# against real manifests once the submodule is initialized (see detect_manifests).
STACK_RECIPES = [
    ({"react", "vite"}, "npm install", "npm run dev", "npm run lint && npm run build"),
    ({"firebase"}, "npm install", "npm run dev", "npm run build"),
    ({"typescript"}, "npm install", "npm run dev", "npm run build"),
    ({"jekyll", "ruby"}, "bundle install", "bundle exec jekyll serve", "bundle exec jekyll build"),
    ({"bootstrap"}, "bundle install", "bundle exec jekyll serve", "bundle exec jekyll build"),
    ({"mkdocs"}, "pip install -r requirements.txt", "mkdocs serve", "mkdocs build --strict"),
    ({"django"}, "pip install -r requirements.txt", "python manage.py runserver", "python manage.py test"),
    ({"python"}, "pip install -r requirements.txt", "python -m <module>", "pytest"),
    ({"bash"}, "—", "run a script directly", "shellcheck *.sh"),
    ({"markdown", "mcp", "agents"}, "—", "consumed as context (not run)", "—"),
]


def stack_recipe(stack: list[str]) -> dict | None:
    s = {t.lower() for t in (stack or [])}
    for tags, install, run, test in STACK_RECIPES:
        if s & tags:
            return {"install": install, "run": run, "test": test, "source": "stack-heuristic"}
    return None


def detect_manifests(path: Path) -> dict:
    """When a submodule IS checked out, read the ground truth instead of guessing."""
    info: dict = {"present": [], "npm_scripts": {}, "context_files": [], "run_skills": []}
    if not path.is_dir():
        return info
    checks = {
        "package.json": "node", "Gemfile": "ruby", "requirements.txt": "python",
        "pyproject.toml": "python", "manage.py": "django", "mkdocs.yml": "mkdocs",
        "_config.yml": "jekyll", "docker-compose.yml": "compose", "Dockerfile": "docker",
        "Makefile": "make",
    }
    for fname in checks:
        if (path / fname).exists():
            info["present"].append(fname)
    pkg = path / "package.json"
    if pkg.exists():
        try:
            info["npm_scripts"] = json.loads(pkg.read_text()).get("scripts", {}) or {}
        except Exception:
            pass
    for ctx in ("CLAUDE.md", "AGENTS.md", "README.md", ".cursorrules"):
        if (path / ctx).exists():
            info["context_files"].append(ctx)
    skills_dir = path / ".claude" / "skills"
    if skills_dir.is_dir():
        info["run_skills"] = sorted(
            p.name for p in skills_dir.iterdir() if p.is_dir() and p.name.startswith("run-")
        )
    return info


def build_view() -> list[dict]:
    reg = load_registry()
    gm = gitmodules()
    states = submodule_state()
    health = load_health()
    rows = []
    for p in reg:
        path = p.get("submodule_path")
        is_sub = bool(path)
        gm_entry = gm.get(path, {}) if is_sub else {}
        state = states.get(path, "external" if not is_sub else "unknown") if is_sub else "external"
        local = detect_manifests(ROOT / path) if (is_sub and state in ("ready", "moved")) else {}
        h = health.get(p["name"], {})
        att = h.get("attention", {})
        rel = p.get("release") or {}
        hrel = h.get("release", {}) if isinstance(h.get("release"), dict) else {}
        rows.append({
            "name": p["name"],
            "slug": p.get("slug"),
            "submodule_path": path,
            "is_submodule": is_sub,
            "category": p.get("category"),
            "status": p.get("status"),
            "featured": bool(p.get("featured")),
            "declared_branch": p.get("branch"),
            "gitmodules_branch": gm_entry.get("branch"),
            "repo_url": p.get("repo_url"),
            "stack": p.get("stack", []),
            "live_url": p.get("live_url"),
            "state": state,
            "branch_mismatch": is_sub and gm_entry.get("branch") not in (None, p.get("branch")),
            "recipe": stack_recipe(p.get("stack", [])),
            "local": local,
            "attention_level": att.get("level"),
            "attention_reasons": att.get("reasons", []),
            "attention_rank": h.get("attention_rank", 3),
            "release_engine": rel.get("engine"),
            "release_type": rel.get("type"),
            "release_registries": rel.get("registries", []),
            "release_status": rel.get("status", "none"),
            "release_pr": rel.get("pr"),
            "release_tag": hrel.get("tag"),
            "release_age_days": hrel.get("age_days"),
        })
    return rows


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
STATE_ICON = {"uninit": "·", "ready": "●", "moved": "▲", "conflict": "✗", "external": "◇"}
ATT_ICON = {"red": "🔴", "amber": "🟠", "green": "🟢", None: "  "}


def render_map(rows: list[dict]) -> str:
    out = []
    out.append(f"bamr87 dash — orchestration map  ({ROOT})")
    out.append("")
    has_health = any(r["attention_level"] for r in rows)
    hdr = f"{'':2} {'':2} {'NAME':<22}{'CATEGORY':<15}{'STATUS':<13}{'BR':<7}STATE"
    out.append(hdr)
    out.append("-" * len(hdr))
    # order: attention rank (red first) when health present, else featured then name
    if has_health:
        rows = sorted(rows, key=lambda r: (r["attention_rank"], not r["featured"], r["name"]))
    else:
        rows = sorted(rows, key=lambda r: (not r["featured"], r["name"]))
    for r in rows:
        star = "★" if r["featured"] else " "
        att = ATT_ICON.get(r["attention_level"], "  ")
        state = STATE_ICON.get(r["state"], "?")
        skills = " +run-skill" if r["local"].get("run_skills") else ""
        out.append(
            f"{att} {star} {r['name']:<22}{(r['category'] or ''):<15}"
            f"{(r['status'] or ''):<13}{(r['declared_branch'] or ''):<7}{state}{skills}"
        )
    out.append("")
    out.append("legend: state ● ready  · uninit  ▲ moved  ✗ conflict  ◇ external   ★ featured")
    if has_health:
        out.append("        health 🔴 needs work  🟠 watch  🟢 healthy   (run `tools/dash gen health` to refresh)")
    else:
        out.append("        (no health data — run `tools/dash gen health` then re-run for the 🔴/🟠/🟢 column)")
    uninit = sum(1 for r in rows if r["state"] == "uninit")
    out.append("")
    out.append(f"{len(rows)} projects · {uninit} not yet checked out · "
               f"{sum(1 for r in rows if r['featured'])} featured")
    out.append("")
    out.append("Next: pick one, then  python3 .claude/skills/run-dash/driver.py project <name>")
    return "\n".join(out)


def render_project(r: dict) -> str:
    o = []
    head = f"{r['name']}"
    if r["featured"]:
        head += "  ★ featured"
    o.append("=" * 64)
    o.append(head)
    o.append("=" * 64)
    o.append(f"  repo     : {r['repo_url']}")
    o.append(f"  category : {r['category']}   status: {r['status']}")
    o.append(f"  stack    : {', '.join(r['stack']) if r['stack'] else '—'}")
    if r["live_url"]:
        o.append(f"  live     : {r['live_url']}")
    if r["attention_level"]:
        o.append(f"  health   : {ATT_ICON[r['attention_level']]} {r['attention_level']} "
                 f"— {'; '.join(r['attention_reasons'])}")

    if not r["is_submodule"]:
        o.append("")
        o.append("  This is an EXTERNAL project (not a submodule). Clone it standalone:")
        o.append(f"    git clone {r['repo_url']}")
        return "\n".join(o)

    path = r["submodule_path"]
    branch = r["declared_branch"]
    o.append("")
    o.append(f"  submodule: {path}   declared branch: {branch}")
    if r["branch_mismatch"]:
        o.append(f"  ⚠ .gitmodules says branch '{r['gitmodules_branch']}' but registry says "
                 f"'{branch}' — reconcile via the update-registry skill.")
    o.append(f"  checkout state: {r['state']}")

    o.append("")
    o.append("  ── dispatch (copy-paste) ───────────────────────────────")
    if r["state"] == "uninit":
        o.append(f"  # not checked out yet — initialize it first")
        o.append(f"  git submodule update --init projects/{Path(path).name}")
    o.append(f"  cd {path}")
    o.append(f"  git checkout {branch}     # submodules land in detached HEAD")
    o.append( "  git pull --ff-only        # get the latest on that branch")
    o.append("  ────────────────────────────────────────────────────────")

    # run/test
    o.append("")
    local = r["local"]
    scripts = local.get("npm_scripts") or {}
    if scripts:
        o.append("  run/test (from this checkout's package.json):")
        for s in ("dev", "start", "build", "lint", "test", "kill"):
            if s in scripts:
                o.append(f"    npm run {s:<7} # {scripts[s]}")
    elif r["recipe"]:
        rec = r["recipe"]
        o.append(f"  run/test (likely — {rec['source']}; confirm after checkout):")
        o.append(f"    install: {rec['install']}")
        o.append(f"    run    : {rec['run']}")
        o.append(f"    test   : {rec['test']}")
    else:
        o.append("  run/test: unknown stack — inspect the project's README after checkout.")

    # context to load
    o.append("")
    ctx = local.get("context_files")
    if ctx:
        o.append(f"  context to read first: {', '.join(f'{path}/{c}' for c in ctx)}")
    elif r["state"] == "uninit":
        o.append("  context to read first (after init): README.md, CLAUDE.md / AGENTS.md if present")
    runsk = local.get("run_skills")
    if runsk:
        o.append(f"  already has run skill(s): {', '.join(runsk)}  → use those to launch it")
    else:
        o.append("  no run skill yet → from inside the submodule run /run-skill-generator to author one")
    return "\n".join(o)


def find_project(rows: list[dict], key: str) -> dict | None:
    k = key.lower().rstrip("/")
    for r in rows:
        cands = {str(r["name"]).lower(), str(r["slug"]).lower(),
                 str(r["submodule_path"]).lower(), f"projects/{str(r['name']).lower()}"}
        if k in cands:
            return r
    # loose: basename of submodule path
    for r in rows:
        if r["submodule_path"] and Path(r["submodule_path"]).name.lower() == k:
            return r
    return None


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
USAGE = """\
usage: driver.py [map | project <name> | releases] [--json]

  map                 orchestration map of all projects (default)
  project <name>      work order for one project (name, slug, or path)
  releases            release-pipeline adoption + version per repo
  --json              machine-readable output (works in any position)
"""


def render_releases(rows):
    o = []
    o.append("bamr87 release pipeline — adoption & versions")
    o.append("")
    hdr = f"{'':2} {'NAME':<22}{'TYPE':<9}{'REGISTRIES':<18}{'VERSION':<16}STATUS"
    o.append(hdr)
    o.append("-" * len(hdr))
    icon = {"adopted": "✅", "pending": "🟡", "none": "·"}
    # adopted/pending first, then the rest
    rank = {"adopted": 0, "pending": 1, "none": 2}
    rows = sorted(rows, key=lambda r: (rank.get(r["release_status"], 2), r["name"]))
    for r in rows:
        st = r["release_status"] or "none"
        regs = ",".join(r["release_registries"]) if r["release_registries"] else "—"
        ver = r["release_tag"] or "—"
        if r["release_age_days"] is not None:
            ver = f"{ver} ({r['release_age_days']}d)"
        o.append(f"{icon.get(st,'·')}  {r['name']:<22}{(r['release_type'] or '—'):<9}"
                 f"{regs:<18}{ver:<16}{st}")
    adopted = sum(1 for r in rows if r["release_status"] == "adopted")
    pending = sum(1 for r in rows if r["release_status"] == "pending")
    o.append("")
    o.append(f"{adopted} adopted · {pending} pending · {len(rows) - adopted - pending} not yet on the standard")
    o.append("legend: ✅ merged   🟡 PR open   · not started   |   version = last release tag (age)")
    o.append("")
    o.append("Adopt another:  tools/adopt-release.sh <repo>   (or /adopt-release <repo>)")
    return "\n".join(o)


def main(argv: list[str] | None = None) -> int:
    # Manual, order-independent parsing — small CLI, and it sidesteps the
    # argparse subparser quirk where a sub-scoped --json doesn't bind.
    args = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    if args and args[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0

    cmd = args[0] if args else "map"
    rows = build_view()

    if cmd == "project":
        if len(args) < 2:
            sys.stderr.write("usage: driver.py project <name>\n")
            return 1
        r = find_project(rows, args[1])
        if not r:
            sys.stderr.write(f"unknown project: {args[1]}\n")
            sys.stderr.write("known: " + ", ".join(sorted(x["name"] for x in rows)) + "\n")
            return 1
        print(json.dumps(r, indent=2) if as_json else render_project(r))
        return 0

    if cmd == "releases":
        print(json.dumps(rows, indent=2) if as_json else render_releases(rows))
        return 0

    if cmd != "map":
        sys.stderr.write(f"unknown command: {cmd}\n{USAGE}")
        return 1

    print(json.dumps(rows, indent=2) if as_json else render_map(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
