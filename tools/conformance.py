#!/usr/bin/env python3
"""
File: tools/conformance.py
Description: Executable Universal Project Standard (UPS) checker. Runs the
             machine-checkable rows of _data/specs.yml against one repository
             (in-repo CI via fleet-conformance.yml, or `dash spec check`) or
             against every checked-out submodule (`dash spec fleet`, writing
             _data/conformance.yml — the file the repo-evolution brief reads so
             the weekly agent pass closes real gaps).
             Static and offline: file presence, byte parity, small greps. Rows
             with no implemented check are counted as `manual`.
Author: bamr87
Created: 2026-09-01
Last Modified: 2026-09-01
Version: 0.1.0
Usage: python3 tools/conformance.py check [PATH] [--kinds site,app] [--tier active] [--gate] [--json] [--hub DIR]
       python3 tools/conformance.py fleet [--write _data/conformance.yml] [--json]
       python3 tools/conformance.py kinds [PATH]      # print detected kinds
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

CHECKER_VERSION = "0.1.0"
HUB_DEFAULT = Path(__file__).resolve().parent.parent
KINDS = ("site", "app", "api", "lib", "cli", "ext", "content", "fork")
LOCKFILES = ("package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock", "Gemfile.lock",
             "poetry.lock", "Pipfile.lock", "uv.lock", "composer.lock")
TEXT_EXT = {".md", ".html", ".tsx", ".jsx", ".ts", ".js", ".py", ".rb", ".erb", ".liquid", ".yml", ".yaml",
            ".json", ".css", ".scss", ".toml", ".cfg", ".txt", ".sh"}
SKIP_DIRS = {".git", "node_modules", "_site", "site", "dist", "build", ".venv", "venv", "vendor", "__pycache__",
             ".next", "coverage", "assets/vendor"}


# --------------------------------------------------------------------------- #
# repo model
# --------------------------------------------------------------------------- #
class Repo:
    def __init__(self, path: Path, hub: Path):
        self.path = path.resolve()
        self.hub = hub.resolve()
        self._tracked: list[str] | None = None
        self._files: list[Path] | None = None

    def has(self, *rel: str) -> bool:
        return any((self.path / r).exists() for r in rel)

    def read(self, rel: str, limit: int = 400_000) -> str:
        p = self.path / rel
        try:
            return p.read_text(encoding="utf-8", errors="replace")[:limit] if p.is_file() else ""
        except OSError:
            return ""

    def tracked(self) -> list[str]:
        if self._tracked is None:
            try:
                out = subprocess.run(["git", "-C", str(self.path), "ls-files", "-z"], capture_output=True, text=True, check=True).stdout
                self._tracked = [x for x in out.split("\0") if x]
            except (subprocess.CalledProcessError, FileNotFoundError):
                self._tracked = [str(p.relative_to(self.path)) for p in self.files()]
        return self._tracked

    def files(self, exts: set[str] | None = None, max_files: int = 6000) -> list[Path]:
        if self._files is None:
            acc: list[Path] = []
            for p in self.path.rglob("*"):
                rel = p.relative_to(self.path)
                if any(part in SKIP_DIRS for part in rel.parts) or str(rel).startswith("assets/vendor"):
                    continue
                if p.is_file():
                    acc.append(p)
                    if len(acc) >= max_files:
                        break
            self._files = acc
        return [p for p in self._files if exts is None or p.suffix in exts]

    def grep(self, pattern: str, exts: set[str] | None = None, max_bytes: int = 300_000) -> str | None:
        """Return the relative path of the first text file matching `pattern`."""
        rx = re.compile(pattern)
        for p in self.files(exts or TEXT_EXT):
            try:
                if p.stat().st_size > max_bytes:
                    continue
                if rx.search(p.read_text(encoding="utf-8", errors="replace")):
                    return str(p.relative_to(self.path))
            except OSError:
                continue
        return None

    def glob1(self, pattern: str) -> str | None:
        for p in self.path.glob(pattern):
            return str(p.relative_to(self.path))
        return None

    # stack facts ---------------------------------------------------------- #
    def package_json(self) -> dict:
        try:
            return json.loads(self.read("package.json") or "{}")
        except json.JSONDecodeError:
            return {}

    def js(self) -> bool:
        return self.has("package.json")

    def python(self) -> bool:
        return self.has("pyproject.toml", "requirements.txt", "setup.py", "setup.cfg")

    def jekyll_config(self) -> str:
        return self.read("_config.yml")

    def zer0_theme(self) -> bool:
        c = self.jekyll_config()
        return bool(re.search(r"remote_theme:\s*bamr87/zer0-mistakes|theme:\s*jekyll-theme-zer0", c))

    def is_theme_repo(self) -> bool:
        return bool(self.glob1("*.gemspec")) and "zer0" in (self.glob1("*.gemspec") or "")


def detect_kinds(r: Repo) -> list[str]:
    kinds: set[str] = set()
    pj = r.package_json()
    deps = {**(pj.get("dependencies") or {}), **(pj.get("devDependencies") or {})}
    pyreq = (r.read("pyproject.toml") + r.read("requirements.txt")).lower()
    if r.has("_config.yml") and ("jekyll" in r.read("Gemfile").lower() or r.zer0_theme() or r.has("_layouts", "_posts", "pages")):
        kinds.add("site")
    if r.has("mkdocs.yml"):
        kinds.add("site")
    if any(k in deps for k in ("react", "next", "vue", "svelte", "@angular/core")):
        kinds.add("app")
    if pj.get("engines", {}).get("vscode") or pj.get("contributes"):
        kinds.add("ext")
    if r.has("manage.py") or "django" in pyreq:
        kinds.update({"api", "app"})
    if any(k in pyreq for k in ("fastapi", "flask", "starlette", "aiohttp")):
        kinds.add("api")
    if r.has("config/application.rb"):
        kinds.add("app")
    if any(k in pyreq for k in ("click", "typer")) or "[project.scripts]" in pyreq:
        kinds.add("cli")
    if (r.has("pyproject.toml") or r.has("setup.py") or r.glob1("*.gemspec")) and not (kinds & {"api", "app", "site"}):
        kinds.add("lib")
    if pj.get("bin"):
        kinds.add("cli")
    if not r.js() and not r.python() and not r.has("Gemfile") and r.glob1("*.sh"):
        kinds.add("cli")
    for sub in ("frontend", "app", "web", "client"):
        if (r.path / sub / "package.json").exists():
            kinds.add("app")
        if (r.path / sub / "manage.py").exists() or (r.path / sub / "config" / "application.rb").exists():
            kinds.update({"app", "api"} if (r.path / sub / "manage.py").exists() else {"app"})
    for sub in ("backend", "api", "server"):
        if (r.path / sub).is_dir():
            kinds.add("api")
    if not kinds:
        kinds.add("content" if r.glob1("*.md") else "lib")
    return sorted(kinds)


# --------------------------------------------------------------------------- #
# checks — id -> function(repo, kinds) -> (ok, detail)
# --------------------------------------------------------------------------- #
CHECKS: dict[str, object] = {}


def check(rid: str):
    def deco(fn):
        CHECKS[rid] = fn
        return fn
    return deco


def _ok(msg: str = "") -> tuple[bool, str]:
    return True, msg


def _no(msg: str) -> tuple[bool, str]:
    return False, msg


@check("UPS-REPO-06")
def _readme(r, k):
    return _ok() if r.has("README.md", "README.rst") else _no("no README.md at the root")


@check("UPS-REPO-07")
def _no_lockfiles(r, k):
    bad = [t for t in r.tracked() if Path(t).name in LOCKFILES or "node_modules/" in t]
    return _ok() if not bad else _no(f"tracked: {', '.join(sorted(set(Path(b).name if 'node_modules' not in b else 'node_modules/' for b in bad))[:4])}")


@check("UPS-REPO-10")
def _readme_sections(r, k):
    t = r.read("README.md")
    h2 = re.findall(r"^##\s+(.+)$", t, re.M)
    if len(h2) < 3:
        return _no(f"README has {len(h2)} H2 sections (need Quick start … License)")
    joined = " | ".join(h2).lower()
    missing = [n for n, rx in (("Quick start/Usage", r"quick ?start|getting started|usage|install"), ("License", r"licen[cs]e")) if not re.search(rx, joined)]
    return _ok() if not missing else _no("README missing sections: " + ", ".join(missing))


@check("UPS-REPO-12")
def _license(r, k):
    return _ok() if r.glob1("LICENSE*") or r.glob1("COPYING*") else _no("no LICENSE file")


@check("UPS-REPO-13")
def _changelog(r, k):
    return _ok() if r.has("CHANGELOG.md") else _no("no CHANGELOG.md (release-please owns it)")


@check("UPS-REPO-14")
def _security(r, k):
    return _ok() if r.has("SECURITY.md", ".github/SECURITY.md") else _no("no SECURITY.md")


@check("UPS-REPO-15")
def _contributing(r, k):
    return _ok() if r.has("CONTRIBUTING.md", ".github/CONTRIBUTING.md") or re.search(r"CONTRIBUTING", r.read("README.md")) else _no("no CONTRIBUTING.md or README link")


@check("UPS-REPO-16")
def _codeowners(r, k):
    return _ok() if r.has(".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS") else _no("no CODEOWNERS")


@check("UPS-REPO-17")
def _editorconfig(r, k):
    hub = (r.hub / ".editorconfig").read_bytes() if (r.hub / ".editorconfig").exists() else b""
    mine = (r.path / ".editorconfig").read_bytes() if r.has(".editorconfig") else None
    if mine is None:
        return _no("no .editorconfig")
    return _ok() if mine == hub else _no(".editorconfig differs from the hub copy")


@check("UPS-REPO-18")
def _issue_templates(r, k):
    d = r.path / ".github" / "ISSUE_TEMPLATE"
    have = {p.name for p in d.glob("*")} if d.is_dir() else set()
    need = ["bug_report.yml", "feature_request.yml"] + (["page_feedback.yml"] if {"site", "app"} & set(k) else [])
    missing = [n for n in need if n not in have and n.replace(".yml", ".md") not in have]
    return _ok() if not missing else _no("missing issue templates: " + ", ".join(missing))


@check("UPS-REPO-19")
def _pr_template(r, k):
    return _ok() if r.has(".github/pull_request_template.md", ".github/PULL_REQUEST_TEMPLATE.md", "pull_request_template.md") else _no("no PR template")


@check("UPS-REPO-32")
def _env_example(r, k):
    reads = r.grep(r"process\.env\.|os\.environ|os\.getenv|import\.meta\.env|ENV\[", {".py", ".ts", ".tsx", ".js", ".rb"})
    if not reads:
        return _ok("no env reads found")
    return _ok() if r.has(".env.example", ".env.sample", ".env.template") else _no(f"code reads env ({reads}) but no .env.example")


@check("UPS-AGENT-01")
def _agent_file(r, k):
    return _ok() if r.has("CLAUDE.md", "AGENTS.md") else _no("no CLAUDE.md or AGENTS.md")


@check("UPS-AGENT-02")
def _agent_sections(r, k):
    t = r.read("CLAUDE.md") or r.read("AGENTS.md")
    if not t:
        return _no("no agent context file")
    if "<!-- TODO" in t:
        return _no("CLAUDE.md still carries kit scaffold TODOs")
    heads = " ".join(re.findall(r"^##\s+(.+)$", t, re.M)).lower()
    missing = [n for n, rx in (("Stack & commands", r"stack|commands"), ("Conventions", r"convention"), ("Fleet context", r"fleet|submodule")) if not re.search(rx, heads)]
    return _ok() if not missing else _no("CLAUDE.md missing sections: " + ", ".join(missing))


@check("UPS-AGENT-03")
def _kit_stamp(r, k):
    t = r.read("CLAUDE.md")
    if not t:
        return _ok("AGENTS.md-only repo")
    return _ok() if "<!-- kit: agent-context v" in t else _no("CLAUDE.md lacks the `<!-- kit: agent-context vX.Y.Z -->` stamp")


@check("UPS-AGENT-06")
def _claude_wf(r, k):
    return _ok() if r.has(".github/workflows/claude.yml") else _no("no .github/workflows/claude.yml")


@check("UPS-AGENT-10")
def _settings(r, k):
    return _ok() if r.has(".claude/settings.json") else _no("no .claude/settings.json baseline")


@check("UPS-AGENT-20")
def _schema(r, k):
    return _ok() if r.has("SCHEMA.md") else _no("no SCHEMA.md pyramid")


@check("UPS-AGENT-22")
def _vendored_parity(r, k):
    bad = []
    for name in ("schema_lint.py", "unwrap-prose.py"):
        mine = r.path / "tools" / name
        hub = r.hub / "tools" / name
        if mine.exists() and hub.exists() and mine.read_bytes() != hub.read_bytes():
            bad.append(name)
    return _ok() if not bad else _no("vendored copy differs from hub: " + ", ".join(bad))


@check("UPS-QA-01")
def _formatter(r, k):
    missing = []
    if r.js() and not (r.glob1(".prettierrc*") or r.has("prettier.config.js", "prettier.config.mjs") or "prettier" in r.read("package.json")):
        missing.append("prettier")
    if r.python() and "[tool.ruff" not in r.read("pyproject.toml") and not r.has("ruff.toml"):
        missing.append("ruff")
    return _ok() if not missing else _no("no formatter config: " + ", ".join(missing))


@check("UPS-QA-02")
def _ruff(r, k):
    if not r.python():
        return _ok("no python")
    if "[tool.ruff" not in r.read("pyproject.toml") and not r.has("ruff.toml"):
        return _no("ruff not configured")
    legacy = [f for f in (".flake8", ".pylintrc") if r.has(f)] + (["setup.cfg[flake8]"] if "[flake8]" in r.read("setup.cfg") else [])
    return _ok() if not legacy else _no("legacy linter config present: " + ", ".join(legacy))


@check("UPS-QA-03")
def _eslint(r, k):
    if not r.js():
        return _ok("no js")
    if r.glob1(".eslintrc*"):
        return _no("legacy .eslintrc present (use eslint.config.*)")
    return _ok() if r.glob1("eslint.config.*") or r.glob1("*/eslint.config.*") else _no("no eslint.config.*")


@check("UPS-QA-05")
def _oneline(r, k):
    return _ok() if r.has(".github/workflows/markdown-oneline.yml") else _no("no markdown-oneline.yml gate")


@check("UPS-QA-06")
def _precommit(r, k):
    return _ok() if r.has(".pre-commit-config.yaml") else _no("no .pre-commit-config.yaml")


@check("UPS-QA-10")
def _tests_exist(r, k):
    for d in ("tests", "test", "spec", "__tests__"):
        p = r.path / d
        if p.is_dir() and any(f.is_file() and f.suffix in (".py", ".ts", ".tsx", ".js", ".rb", ".sh", ".bats") for f in p.rglob("*")):
            return _ok()
    if r.glob1("**/*.test.*") or r.glob1("**/*.spec.*") or r.glob1("**/*_test.py") or r.glob1("**/test_*.py"):
        return _ok()
    return _no("no test files found")


@check("UPS-QA-11")
def _pytest_cfg(r, k):
    if not r.python():
        return _ok("no python")
    if r.has("pytest.ini") or "[tool:pytest]" in r.read("setup.cfg"):
        return _no("pytest configured in pytest.ini/setup.cfg (move to pyproject [tool.pytest.ini_options])")
    return _ok() if "[tool.pytest.ini_options]" in r.read("pyproject.toml") else _no("no [tool.pytest.ini_options] in pyproject.toml")


@check("UPS-QA-12")
def _js_tests(r, k):
    if not r.js() or "ext" in k:
        return _ok("n/a")
    if r.has("cypress") or r.glob1("cypress.config.*"):
        return _no("Cypress present (retired: migrate to Playwright)")
    pj = r.read("package.json") + " ".join(r.read(f"{s}/package.json") for s in ("frontend", "app", "web"))
    return _ok() if ("vitest" in pj or "@playwright/test" in pj or "jest" in pj) else _no("no vitest/playwright configured")


@check("UPS-QA-20")
def _ci_caller(r, k):
    t = r.read(".github/workflows/ci.yml")
    if not t:
        return _no("no .github/workflows/ci.yml")
    if re.search(r"uses:\s*bamr87/(bamr87/\.github/workflows/standard-ci\.yml|\.github/\.github/workflows/ci\.yml)@", t):
        return _ok()
    return _no("ci.yml is bespoke (not a thin caller of the shared gate)")


@check("UPS-QA-32")
def _release(r, k):
    return _ok() if r.has("release-please-config.json", ".release-please-manifest.json") else _no("no release-please config")


@check("UPS-QA-40")
def _always_latest(r, k):
    bad = [t for t in r.tracked() if Path(t).name in LOCKFILES]
    if bad:
        return _no("committed lockfile: " + ", ".join(sorted({Path(b).name for b in bad})[:3]))
    pinned = None
    for p in (r.path / ".github" / "workflows").glob("*.yml"):
        m = re.search(r"uses:\s*\S+@(v?\d+\.\d+(\.\d+)?|[0-9a-f]{40})\b", p.read_text(encoding="utf-8", errors="replace"))
        if m:
            pinned = f"{p.name}@{m.group(1)}"
            break
    return _ok() if not pinned else _no(f"action pinned below major tag: {pinned}")


@check("UPS-QA-41")
def _dependabot(r, k):
    return _ok() if r.has(".github/dependabot.yml") else _no("no .github/dependabot.yml")


@check("UPS-FE-01")
def _tokens(r, k):
    if r.zer0_theme():
        return _ok("theme-provided")
    hit = r.grep(r"--(fleet|zer0)-color-|--c-bg|@theme\s*\{|--color-canvas", {".css", ".scss"})
    return _ok(hit or "") if hit else _no("no design-token stylesheet (--fleet-* / --zer0-*)")


@check("UPS-FE-11")
def _skip_link(r, k):
    if r.zer0_theme():
        return _ok("theme-provided")
    hit = r.grep(r"#main-content|skip[- ]?(to|link)", {".html", ".tsx", ".jsx", ".erb", ".liquid", ".ts"})
    return _ok(hit or "") if hit else _no("no skip link found")


@check("UPS-FE-13")
def _feedback(r, k):
    if r.zer0_theme() or r.is_theme_repo():
        c = r.jekyll_config()
        m = re.search(r"page_feedback:\s*\n((?:\s+.+\n)+)", c)
        if m and re.search(r"enabled\s*:\s*true", m.group(1)):
            return _ok("theme widget enabled")
        return _no("zer0-mistakes theme but `page_feedback.enabled: true` is not set in _config.yml")
    hit = r.grep(r"<fleet-feedback|FeedbackButton|fleet-feedback\.js", {".html", ".tsx", ".jsx", ".erb", ".liquid", ".md"})
    return _ok(hit or "") if hit else _no("no feedback widget mounted (<fleet-feedback>)")


CHECKS["UPS-FB-01"] = _feedback


@check("UPS-FE-15")
def _404(r, k):
    if r.zer0_theme():
        return _ok("theme-provided")
    if r.has("404.html", "404.md", "pages/404.md", "public/404.html", "app/not-found.tsx", "src/app/not-found.tsx") or r.grep(r"NotFound|not-found", {".tsx", ".jsx", ".ts"}):
        return _ok()
    return _no("no 404 page/route")


@check("UPS-FE-25")
def _meta(r, k):
    if r.zer0_theme():
        return _ok("theme-provided")
    hit = r.grep(r'og:title|property="og:|jekyll-seo-tag|\{%\s*seo\s*%\}|export const metadata', {".html", ".tsx", ".erb", ".liquid", ".yml", ".ts"})
    return _ok(hit or "") if hit else _no("no og:/seo meta block")


@check("UPS-FB-07")
def _fb_template(r, k):
    return _ok() if r.has(".github/ISSUE_TEMPLATE/page_feedback.yml") else _no("no .github/ISSUE_TEMPLATE/page_feedback.yml")


@check("UPS-BE-10")
def _healthz(r, k):
    hit = r.grep(r"healthz|/health\b|readyz", {".py", ".ts", ".rb", ".js"})
    return _ok(hit or "") if hit else _no("no /healthz or /readyz route")


@check("UPS-BE-11")
def _version_route(r, k):
    hit = r.grep(r'["\']/version["\']|/api/version|route.*version', {".py", ".ts", ".rb", ".js"})
    return _ok(hit or "") if hit else _no("no /version endpoint")


@check("UPS-OPS-03")
def _env_not_tracked(r, k):
    bad = [t for t in r.tracked() if re.fullmatch(r"(.*/)?\.env(\.[A-Za-z]+)?", t) and not t.endswith((".example", ".sample", ".template"))]
    return _ok() if not bad else _no("tracked env file: " + ", ".join(bad[:3]))


# --------------------------------------------------------------------------- #
# running
# --------------------------------------------------------------------------- #
def load_specs(hub: Path) -> dict:
    return yaml.safe_load((hub / "_data" / "specs.yml").read_text(encoding="utf-8")) or {}


def binds(req: dict, kinds: list[str], tier: str) -> bool:
    if tier in ("fork", "archived"):
        return False
    applies = set(req.get("applies") or [])
    notes = " ".join(req.get("applies_notes") or []).lower()
    if "all" in applies:
        for kd in kinds:
            if f"except {kd}" in notes or (f"except" in notes and kd in notes.split("except", 1)[1]):
                if len(kinds) == 1:
                    return False
        return True
    return bool(applies & set(kinds))


def run_checks(repo: Repo, kinds: list[str], tier: str, specs: dict) -> dict:
    results, manual = [], 0
    for req in specs.get("requirements", []):
        if not binds(req, kinds, tier):
            continue
        fn = CHECKS.get(req["id"])
        if fn is None:
            manual += 1
            continue
        try:
            ok, detail = fn(repo, kinds)
        except Exception as e:  # noqa: BLE001 — a checker bug must not hide the other results
            ok, detail = False, f"checker error: {e}"
        results.append({"id": req["id"], "level": req["level"], "ok": bool(ok), "detail": detail,
                        "spec": req.get("area", "")})
    failing = [x for x in results if not x["ok"]]
    return {
        "path": str(repo.path), "kinds": kinds, "tier": tier,
        "checked": len(results), "passed": len(results) - len(failing),
        "must_failed": sum(1 for x in failing if x["level"] == "MUST"),
        "should_failed": sum(1 for x in failing if x["level"] == "SHOULD"),
        "manual": manual,
        "failing": [{"id": x["id"], "level": x["level"], "detail": x["detail"],
                     "spec": f"specs/{area_file(x['spec'], specs)}"} for x in failing],
    }


def area_file(area: str, specs: dict) -> str:
    for a in specs.get("areas", []):
        if a["id"] == area:
            return Path(a["file"]).name
    return "README.md"


def render_text(res: dict, name: str) -> str:
    lines = [f"UPS conformance — {name}  kinds={','.join(res['kinds'])} tier={res['tier']}",
             f"  checked {res['checked']}  passed {res['passed']}  MUST failing {res['must_failed']}  "
             f"SHOULD failing {res['should_failed']}  manual {res['manual']}"]
    for f in sorted(res["failing"], key=lambda x: (x["level"] != "MUST", x["id"])):
        lines.append(f"  {'✗' if f['level'] == 'MUST' else '~'} {f['id']:<14} {f['level']:<6} {f['detail']}  ({f['spec']})")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# fleet mode
# --------------------------------------------------------------------------- #
def registry_tier(entry: dict, standards: dict) -> str:
    if entry.get("tier"):
        return str(entry["tier"])
    ov = (standards.get("tier_overrides") or {}).get(entry.get("name"))
    if ov:
        return str(ov)
    return str((standards.get("status_tier") or {}).get(entry.get("status"), "experiment"))


def kinds_from_stack(entry: dict) -> list[str] | None:
    """Registry-declared kinds win; otherwise None (detect from files)."""
    k = entry.get("kinds")
    return [str(x) for x in k] if isinstance(k, list) and k else None


def fleet(hub: Path, write: Path | None, as_json: bool) -> int:
    specs = load_specs(hub)
    registry = yaml.safe_load((hub / "_data" / "projects.yml").read_text(encoding="utf-8")) or []
    standards = yaml.safe_load((hub / "_data" / "standards.yml").read_text(encoding="utf-8")) or {}
    repos, skipped = [], []
    for e in registry:
        sub = e.get("submodule_path")
        if not sub:
            continue
        path = hub / sub
        if not (path / ".git").exists() and not (path / "README.md").exists():
            skipped.append({"name": e["name"], "reason": "not checked out"})
            continue
        tier = registry_tier(e, standards)
        if tier in ("fork", "archived"):
            skipped.append({"name": e["name"], "reason": f"tier {tier}"})
            continue
        repo = Repo(path, hub)
        kinds = kinds_from_stack(e) or detect_kinds(repo)
        res = run_checks(repo, kinds, tier, specs)
        nwo = re.sub(r"^https://github\.com/", "", str(e.get("repo_url", ""))).rstrip("/")
        rec = {"name": e["name"], "nwo": nwo, "path": sub, **{k: v for k, v in res.items() if k != "path"}}
        repos.append(rec)
        if not as_json:
            print(render_text(res, e["name"]))
    out = {
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "spec_version": str(specs.get("version", "?")),
        "checker_version": CHECKER_VERSION,
        "implemented_checks": len(CHECKS),
        "summary": {
            "repos": len(repos),
            "conformant": sum(1 for r in repos if r["must_failed"] == 0),
            "must_failures": sum(r["must_failed"] for r in repos),
            "should_failures": sum(r["should_failed"] for r in repos),
            "top_failing_ids": top_ids(repos),
        },
        "skipped": skipped,
        "repos": repos,
    }
    if as_json:
        print(json.dumps(out, indent=2))
    else:
        s = out["summary"]
        print(f"\nfleet: {s['repos']} repos, {s['conformant']} with no MUST failures, "
              f"{s['must_failures']} MUST / {s['should_failures']} SHOULD failures; skipped {len(skipped)}")
        print("most common MUST gaps: " + ", ".join(f"{i} ({n})" for i, n in s["top_failing_ids"][:8]))
    if write:
        header = ("# GENERATED by tools/conformance.py fleet — the fleet's UPS conformance snapshot.\n"
                  "# Read by dash-gen targets (the repo-evolution brief) and the dash. Regenerate with\n"
                  "# `tools/dash spec fleet --write`; do not hand-edit.\n")
        write.write_text(header + yaml.safe_dump(out, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")
        print(f"wrote {write}")
    return 0


def top_ids(repos: list[dict]) -> list[list]:
    counts: dict[str, int] = {}
    for r in repos:
        for f in r["failing"]:
            if f["level"] == "MUST":
                counts[f["id"]] = counts.get(f["id"], 0) + 1
    return [[i, n] for i, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Universal Project Standard checker")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="check one repository (default: cwd)")
    c.add_argument("path", nargs="?", default=".")
    c.add_argument("--kinds", help="comma-separated stack kinds (default: detect)")
    c.add_argument("--tier", default="active")
    c.add_argument("--gate", action="store_true", help="exit 1 on any MUST failure")
    c.add_argument("--json", action="store_true")
    c.add_argument("--hub", default=str(HUB_DEFAULT), help="hub checkout holding _data/specs.yml")
    f = sub.add_parser("fleet", help="check every checked-out submodule")
    f.add_argument("--write", nargs="?", const=str(HUB_DEFAULT / "_data" / "conformance.yml"))
    f.add_argument("--json", action="store_true")
    f.add_argument("--hub", default=str(HUB_DEFAULT))
    k = sub.add_parser("kinds", help="print detected kinds for a path")
    k.add_argument("path", nargs="?", default=".")
    k.add_argument("--hub", default=str(HUB_DEFAULT))
    a = ap.parse_args(argv)
    hub = Path(a.hub)

    if a.cmd == "fleet":
        return fleet(hub, Path(a.write) if a.write else None, a.json)
    repo = Repo(Path(a.path), hub)
    if a.cmd == "kinds":
        print(",".join(detect_kinds(repo)))
        return 0
    kinds = [x.strip() for x in a.kinds.split(",") if x.strip()] if a.kinds else detect_kinds(repo)
    bad = [x for x in kinds if x not in KINDS]
    if bad:
        ap.error(f"unknown kinds: {bad} (valid: {', '.join(KINDS)})")
    res = run_checks(repo, kinds, a.tier, load_specs(hub))
    print(json.dumps(res, indent=2) if a.json else render_text(res, repo.path.name))
    return 1 if (a.gate and res["must_failed"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
