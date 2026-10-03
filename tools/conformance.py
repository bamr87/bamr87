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
             with no implemented check are counted as `manual`; rows a check
             cannot decide offline, or that wait on a pending decision
             (--enable-pending), are listed as `unverified`.
Author: bamr87
Created: 2026-09-01
Last Modified: 2026-10-03
Version: 0.2.0
Usage: python3 tools/conformance.py check [PATH] [--kinds site,app] [--tier active] [--gate] [--json] [--hub DIR] [--enable-pending D4,D5]
       python3 tools/conformance.py fleet [--write _data/conformance.yml] [--json] [--enable-pending D4,D5]
       python3 tools/conformance.py kinds [PATH]      # print detected kinds
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

CHECKER_VERSION = "0.2.0"
HUB_DEFAULT = Path(__file__).resolve().parent.parent
KINDS = ("site", "app", "api", "lib", "cli", "ext", "content", "fork")
LOCKFILES = ("package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock", "Gemfile.lock",
             "poetry.lock", "Pipfile.lock", "uv.lock", "composer.lock")
TEXT_EXT = {".md", ".html", ".tsx", ".jsx", ".ts", ".js", ".py", ".rb", ".erb", ".liquid", ".yml", ".yaml",
            ".json", ".css", ".scss", ".toml", ".cfg", ".txt", ".sh"}
SKIP_DIRS = {".git", "node_modules", "_site", "site", "dist", "build", ".venv", "venv", "vendor", "__pycache__",
             ".next", "coverage", "assets/vendor", ".fleet-hub"}


# --------------------------------------------------------------------------- #
# repo model
# --------------------------------------------------------------------------- #
class Repo:
    def __init__(self, path: Path, hub: Path):
        self.path = path.resolve()
        self.hub = hub.resolve()
        self._tracked: list[str] | None = None
        self._files: list[Path] | None = None
        self.enabled_decisions: set[str] = set()  # pending decisions opted into (PENDING_DECISIONS)
        self.registry_entry: dict | None = None   # hub registry entry; fleet mode sets it

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
            nested: list[Path] = []  # nested repos (submodules, vendored checkouts) are not this repo
            for p in sorted(self.path.rglob("*")):
                rel = p.relative_to(self.path)
                if any(part in SKIP_DIRS for part in rel.parts) or str(rel).startswith("assets/vendor"):
                    continue
                if any(str(rel).startswith(str(n) + "/") for n in nested):
                    continue
                if p.is_dir() and p != self.path and (p / ".git").exists():
                    nested.append(rel)
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
        return bool(re.search(r"""remote_theme\s*:\s*["']?bamr87/zer0-mistakes|(?<![a-z_])theme\s*:\s*["']?jekyll-theme-zer0""", c))

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


def _features(r):
    """Lazy import: features_index.py lives beside this file and needs only PyYAML."""
    if not hasattr(r, "_features_res"):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import features_index  # noqa: PLC0415
        r._features_res = features_index.analyze(r.path)
    return r._features_res


@check("UPS-QA-50")
def _feature_index(r, k):
    res = _features(r)
    if res["format"] == "none":
        return _no("no features/features.yml (seed: tools/fanout.sh --kit verify)")
    if res["format"] == "prose":
        return _no(f"{res['index']} is prose only — convert to features/features.yml (features/v1)")
    if not res["ok"]:
        return _no(f"{len(res['errors'])} error(s): {res['errors'][0]}")
    return _ok("legacy shape" if res["format"] == "legacy" else "")


@check("UPS-QA-51")
def _verify_kit(r, k):
    kit = _features(r)["kit"]
    if kit["legacy_evidence_kit"] and kit["legacy_visual_evidence_skill"]:
        return _ok("precedent evidence kit (test/visual/evidence-kit.mjs + visual-evidence skill)")
    missing = [name for name, present in (("verify/verify.yml", kit["config"]), ("verify/scenarios/*.yml", kit["scenarios"] > 0),
                                          ("verify/runner.mjs", kit["runner"]), (".github/workflows/verify.yml", kit["workflow"])) if not present]
    return _no("missing " + ", ".join(missing)) if missing else _ok()


@check("UPS-QA-53")
def _ui_verified(r, k):
    res = _features(r)
    if res["format"] in ("none", "prose"):
        return _no("no feature index to grade")
    c = res["counts"]
    if c["ui"] == 0:
        return _ok("no implemented UI features indexed")
    if c["ui_covered"] < c["ui"]:
        return _no(f"{c['ui'] - c['ui_covered']} of {c['ui']} implemented UI features have no test or scenario")
    if c["ui_verified"] == 0:
        return _no(f"{c['ui']} UI features covered, none carries a verified: stamp")
    return _ok(f"{c['ui_verified']}/{c['ui']} verified")


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


@check("UPS-FB-04")
def _fb_capture(r, k):
    """Console/error capture installed — the half of a report an agent cannot
    ask the reader to reconstruct. The theme installs it from <head> under its
    own name; everyone else vendors the kit's buffer."""
    if r.zer0_theme() or r.is_theme_repo():
        return _ok("theme-provided (console-capture)")
    hit = r.grep(r"__fleetFeedback|fleet-feedback-capture", {".js", ".html", ".tsx", ".jsx", ".erb", ".liquid"})
    return _ok(hit or "") if hit else _no("no console/error capture buffer (vendor capture.js)")


@check("UPS-FB-23")
def _fb_contract(r, k):
    """The issue body contract. The marker comment is the machine-readable half
    — without it the issue pipeline re-templates a report that is already
    structured — and it only exists in an implementation that speaks the
    contract, so grepping for it checks the whole section shape by proxy.

    Theme consumers ship no widget of their own — the theme emits the body, the
    same way it provides the skip link and the 404 page. Deferring here is the
    model FB-01 and FB-04 already use."""
    if r.zer0_theme():
        return _ok("theme-provided")
    hit = r.grep(r"fleet-feedback v1 type=", {".js", ".ts", ".tsx", ".html", ".rb", ".py", ".liquid"})
    return _ok(hit or "") if hit else _no("no fleet-feedback issue marker — the widget does not emit the contract body")


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
# UPS-WORK — planning & delivery (draft area, rows proposed for specs/WORK.md)
#
# Built to the WORK table in the SDLC harmonization plan (Wave 1). Like every
# check here, a row only runs once _data/specs.yml carries it, so this block is
# inert until the WORK spec lands. Static and offline, like the rest: a fact
# the checker cannot see from the tree (files inherited from the owner's
# `.github` repo, labels that live on GitHub, a rule waiting on an unratified
# decision) returns ok=None and is reported as `unverified`, never as a pass or
# a failure.
# --------------------------------------------------------------------------- #
# Rules whose meaning depends on a decision that is not ratified yet. They are
# skipped unless the caller opts in with --enable-pending (fleet-conformance.yml
# input `enable-pending`).
PENDING_DECISIONS = {
    "D4": "AGENTS.md vs CLAUDE.md as the canonical agent file",
    "D5": "whether content repos keep a CHANGELOG (UPS-REPO-13 vs UPS-QA-33)",
}
SDLC_FILE = ".github/sdlc.yml"
BACKLOG_FILES = ("BACKLOG.md", "_data/backlog.yml")
PR_TEMPLATES = (".github/pull_request_template.md", ".github/PULL_REQUEST_TEMPLATE.md", "pull_request_template.md",
                "docs/pull_request_template.md")
# The fleet Definition of Done (UPS-WORK-03): each item must appear on a checklist line.
DOD_ITEMS = (("Conventional title", r"conventional"), ("CI green", r"\bci\b|\bgates?\b|checks"),
             ("tests", r"\btests?\b"), ("docs or features", r"\bdocs?\b|readme|documentation|features\.ya?ml"),
             ("ADR if irreversible", r"\badrs?\b|decision record|docs/adr"), ("backlog updated", r"backlog"),
             ("no secrets", r"secret"))
FLEET_TYPES_FALLBACK = ("bug", "feature", "docs", "chore", "ci", "refactor", "test", "security", "question")
DUPLICATE_LABEL = re.compile(r"^(enhancement|documentation|priority:\s*p\d)$", re.I)
FORM_LABEL_EXEMPT = {"page_feedback"}  # its label is fixed by UPS-FB-07
ADR_NAME = re.compile(r"^(ADR-)?\d{3,4}-[\w.-]+\.md$", re.I)
HUB_USES = re.compile(r"""^\s*(?:-\s*)?uses:\s*['"]?(bamr87/(?:bamr87|\.github)/[^@\s'"]+)@([^\s'"#]+)""", re.M)
PINNED_REF = re.compile(r"v\d+(\.\d+){0,2}|[0-9a-f]{40}")
SPEC_STALE_DAYS, BACKLOG_LAG_DAYS = 30, 60


def _skip(msg: str) -> tuple[None, str]:
    return None, msg


def _pending(r, decision: str, what: str):
    """A skip result while `decision` is pending and not enabled; None means: run the rule."""
    if decision in r.enabled_decisions:
        return None
    return _skip(f"pending decision {decision} ({PENDING_DECISIONS[decision]}); enable with --enable-pending {decision} — {what}")


def _git(r, *args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(r.path), *args], capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _last_commit(r, rel: str | None = None) -> dt.datetime | None:
    out = _git(r, "log", "-1", "--format=%ct", *(["--", rel] if rel else []))
    return dt.datetime.fromtimestamp(int(out), dt.timezone.utc) if out.isdigit() else None


def _origin_nwo(r) -> str | None:
    url = _git(r, "remote", "get-url", "origin")
    if not url and r.path == Path.cwd().resolve():
        url = os.environ.get("GITHUB_REPOSITORY", "")
    m = re.search(r"(?:github\.com[:/])?([\w.-]+/[\w.-]+?)(?:\.git)?/?$", url)
    return m.group(1).lower() if m else None


def registry_entry(r) -> dict | None:
    """The repo's hub registry entry: set by fleet mode, else matched on the origin remote."""
    if r.registry_entry is None:
        r.registry_entry = {}
        nwo = _origin_nwo(r)
        reg = r.hub / "_data" / "projects.yml"
        if nwo and reg.is_file():
            for e in yaml.safe_load(reg.read_text(encoding="utf-8")) or []:
                if re.sub(r"^https://github\.com/", "", str(e.get("repo_url", ""))).rstrip("/").lower() == nwo:
                    r.registry_entry = e
                    break
    return r.registry_entry or None


def sdlc_profile(r) -> tuple[dict | None, str]:
    """(profile, source). `.github/sdlc.yml` wins over the registry `sdlc:` block; {} = present but unreadable."""
    if not hasattr(r, "_sdlc"):
        prof, src = None, ""
        if r.has(SDLC_FILE):
            try:
                data = yaml.safe_load(r.read(SDLC_FILE))
            except yaml.YAMLError:
                data = None
            prof, src = (data if isinstance(data, dict) else {}), SDLC_FILE
        else:
            e = registry_entry(r)
            if e and isinstance(e.get("sdlc"), dict):
                prof, src = e["sdlc"], "registry `sdlc:` block"
        r._sdlc = (prof, src)
    return r._sdlc


def sdlc_modules(prof: dict | None) -> set[str]:
    """Modules as a map (`.github/sdlc.yml`) or a list (registry block) — both shapes are in the plan."""
    m = (prof or {}).get("modules")
    if isinstance(m, dict):
        return {str(k) for k, v in m.items() if v}
    return {str(x) for x in m} if isinstance(m, list) else set()


def _backlog_decl(prof: dict | None) -> dict:
    b = (prof or {}).get("backlog")
    return b if isinstance(b, dict) else {}


def _workflow_texts(r) -> list[tuple[str, str]]:
    d = r.path / ".github" / "workflows"
    return [(p.name, p.read_text(encoding="utf-8", errors="replace")) for p in sorted(d.glob("*.y*ml"))] if d.is_dir() else []


def _section(text: str, heading_rx: str) -> str | None:
    m = re.search(rf"^##\s+(?:{heading_rx})\b.*$", text, re.I | re.M)
    if not m:
        return None
    nxt = re.search(r"^##\s", text[m.end():], re.M)
    return text[m.end(): m.end() + nxt.start()] if nxt else text[m.end():]


@check("UPS-WORK-01")
def _sdlc_declared(r, k):
    prof, src = sdlc_profile(r)
    if prof is None:
        return _no(f"no {SDLC_FILE} and no registry `sdlc:` block")
    mode = _backlog_decl(prof).get("mode")
    missing = [key for key in ("kind", "tier", "modules") if key not in prof] + ([] if mode else ["backlog.mode"])
    if missing:
        return _no(f"{src} missing: {', '.join(missing)}")
    if mode not in ("issues", "file"):
        return _no(f"{src}: backlog.mode `{mode}` is not issues|file")
    return _ok(src)


@check("UPS-WORK-02")
def _backlog_of_record(r, k):
    """File mode only: the declared file exists and a CI workflow lints it. The
    "other planning files hold no item lists" clause is not machine-checked."""
    b = _backlog_decl(sdlc_profile(r)[0])
    if (b.get("mode") or "issues") != "file":
        return _skip("issues mode: the fleet labels on Issues are not visible to the offline checker")
    f = b.get("file") or next((x for x in BACKLOG_FILES if r.has(x)), None)
    if not f or not r.has(f):
        return _no(f"backlog.mode is file but {f or ' / '.join(BACKLOG_FILES)} is missing")
    lint = next((n for n, t in _workflow_texts(r) if re.search(r"backlog[_-]?lint|lint[_-]?backlog", t, re.I)), None)
    return _ok(f"{f}, linted in {lint}") if lint else _no(f"{f} has no CI lint (no workflow runs a backlog lint)")


@check("UPS-WORK-03")
def _definition_of_done(r, k):
    path = next((p for p in PR_TEMPLATES if r.has(p)), None) or r.glob1(".github/PULL_REQUEST_TEMPLATE/*.md")
    if not path:
        return _skip("no PR template in the tree; the owner's `.github` default applies and is not visible offline")
    boxes = "\n".join(re.findall(r"^\s*[-*]\s*\[[ xX]\]\s*(.+)$", r.read(path), re.M)).lower()
    if not boxes:
        return _no(f"{path} has no Definition of Done checklist")
    missing = [n for n, rx in DOD_ITEMS if not re.search(rx, boxes)]
    return _ok(path) if not missing else _no(f"{path} DoD lacks: {', '.join(missing)}")


@check("UPS-WORK-04")
def _adr_log(r, k):
    prof = sdlc_profile(r)[0] or {}
    d = str(prof.get("adr_path") or "docs/adr").strip("/")
    p = r.path / d
    adrs = [x.name for x in p.glob("*.md") if ADR_NAME.match(x.name) and not re.match(r"^(ADR-)?0+-", x.name, re.I)] if p.is_dir() else []
    if not adrs:
        return _no(f"no ADRs in {d}/ (NNNN-slug.md)")
    if not (p / "README.md").is_file():
        return _no(f"{d}/ has {len(adrs)} ADR(s) but no README.md index")
    return _ok(f"{len(adrs)} ADR(s) in {d}/")


def _latest_tag(r) -> str | None:
    tags = [t for t in _git(r, "tag", "--list", "--sort=-v:refname").splitlines() if re.fullmatch(r"v?\d+\.\d+\.\d+", t)]
    return tags[0] if tags else None


@check("UPS-WORK-05")
def _changelog_hygiene(r, k):
    if "content" in k:
        p = _pending(r, "D5", "CHANGELOG rules for content repos")
        if p:
            return p
    t = r.read("CHANGELOG.md")
    if not t:
        return _ok("no CHANGELOG.md (presence is UPS-REPO-13)")
    n = len(re.findall(r"^##\s*\[?unreleased\b", t, re.I | re.M))
    if n > 1:
        return _no(f"CHANGELOG.md has {n} `## [Unreleased]` headings (keep one)")
    vers = re.findall(r"^##\s*\[?v?(\d+\.\d+\.\d+[\w.+-]*)\]?", t, re.M)
    if not vers:
        return _ok("no released version headings yet")
    tag = _latest_tag(r)
    if tag is None:
        return _ok(f"newest heading {vers[0]}; no version tags in this checkout to compare")
    return _ok(f"{vers[0]} = {tag}") if vers[0] == tag.lstrip("v") else _no(f"newest CHANGELOG heading {vers[0]} ≠ newest tag {tag}")


@check("UPS-WORK-06")
def _features_hygiene(r, k):
    main = "features/features.yml"
    if not r.has(main):
        return _ok("no features/features.yml (presence is UPS-QA-50)")
    t = r.read(main)
    head = "\n".join(t.splitlines()[:40])
    bad = (["duplicate _data/features.yml"] if r.has("_data/features.yml") else []) + (
        ["hand-maintained version header"] if re.search(r"^\s*#.*\bversion\s*:\s*v?\d+\.\d+", head, re.I | re.M)
        or re.search(r"^version\s*:", t, re.M) else [])
    return _ok() if not bad else _no(f"{main}: " + ", ".join(bad))


def _jobs(text: str) -> dict:
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return {}
    jobs = data.get("jobs") if isinstance(data, dict) else None
    return jobs if isinstance(jobs, dict) else {}


def _needs(job: dict) -> set[str]:
    n = job.get("needs") if isinstance(job, dict) else None
    return {n} if isinstance(n, str) else set(n or [])


def _closure(jobs: dict, start: str) -> set[str]:
    seen, todo = set(), [start]
    while todo:
        for n in _needs(jobs.get(todo.pop(), {})) - seen:
            seen.add(n)
            todo.append(n)
    return seen


@check("UPS-WORK-07")
def _spec_gate(r, k):
    if "spec_driven" not in sdlc_modules(sdlc_profile(r)[0]):
        return _ok("module spec_driven not declared")
    problems = ([] if r.glob1("specs/[0-9][0-9][0-9]-*/spec.md") else ["no specs/NNN-slug/spec.md"]) + \
               ([] if r.has("BACKLOG.md") else ["no BACKLOG.md"])
    gate = None
    for name, text in _workflow_texts(r):
        jobs = _jobs(text)
        for jid, job in jobs.items():
            if "spec_validator" in yaml.safe_dump(job):
                ungated = [o for o in jobs if o != jid and o not in _closure(jobs, jid) and jid not in _closure(jobs, o)]
                gate = (name, jid, ungated, "backlog_lint" in text)
                break
        if gate:
            break
    if not gate:
        problems.append("no CI job runs spec_validator.py (spec-gate)")
    else:
        name, jid, ungated, linted = gate
        if not linted:
            problems.append(f"{name} does not run backlog_lint.py")
        if ungated:
            problems.append(f"jobs in {name} not gated on `{jid}`: {', '.join(ungated)}")
    kit, note = r.hub / "templates" / "sdlc" / "spec-driven", ""
    if kit.is_dir():
        for tool in ("spec_validator.py", "backlog_lint.py"):
            ref = next(iter(kit.rglob(tool)), None)
            mine = next((t for t in r.tracked() if Path(t).name == tool), None)
            if ref and mine and (r.path / mine).read_bytes() != ref.read_bytes():
                problems.append(f"{mine} differs from the hub kit")
    else:
        note = "; hub kit templates/sdlc/spec-driven/ not published yet, tool parity unchecked"
    return _no("; ".join(problems) + note) if problems else _ok(f"spec-gate `{gate[1]}` in {gate[0]}{note}")


@check("UPS-WORK-08")
def _freshness(r, k):
    """Scorecard-only (SHOULD). Covers the in-progress spec and backlog-lag
    clauses from git history; the P0/P1 idle clause needs the Issues API."""
    head = _last_commit(r)
    if head is None:
        return _skip("no git history in this checkout")
    now, flags = dt.datetime.now(dt.timezone.utc), []
    for spec in sorted(r.path.glob("specs/[0-9][0-9][0-9]-*/spec.md")):
        m = re.search(r"^\s*(?:[-*]\s*)?\**status\**\s*:\s*\**\s*([a-z-]+)", spec.read_text(encoding="utf-8", errors="replace"), re.I | re.M)
        last = _last_commit(r, str(spec.parent.relative_to(r.path)))
        if m and m.group(1).lower() == "in-progress" and last and (now - last).days > SPEC_STALE_DAYS:
            flags.append(f"{spec.parent.name} in-progress, idle {(now - last).days}d")
    b = _backlog_decl(sdlc_profile(r)[0]).get("file") or next((x for x in BACKLOG_FILES if r.has(x)), None)
    if b and r.has(b):
        last = _last_commit(r, b)
        if last and (head - last).days > BACKLOG_LAG_DAYS:
            flags.append(f"{b} last touched {(head - last).days}d before the last commit")
    return _ok() if not flags else _no("; ".join(flags))


def fleet_types(hub: Path) -> set[str]:
    try:
        cfg = yaml.safe_load((hub / "_data" / "fleet.yml").read_text(encoding="utf-8")) or {}
        types = cfg["issue_pipeline"]["labels"]["types"]
        return {str(t) for t in types} if types else set(FLEET_TYPES_FALLBACK)
    except (OSError, KeyError, TypeError, yaml.YAMLError):
        return set(FLEET_TYPES_FALLBACK)


def _form_labels(p: Path) -> list[str] | None:
    t = p.read_text(encoding="utf-8", errors="replace")
    if p.suffix == ".md":
        m = re.match(r"^---\s*\n(.*?)\n---", t, re.S)
        t = m.group(1) if m else ""
    try:
        labels = (yaml.safe_load(t) or {}).get("labels") or []
    except (yaml.YAMLError, AttributeError):
        return None
    return [x.strip() for x in labels.split(",")] if isinstance(labels, str) else [str(x) for x in labels]


@check("UPS-WORK-09")
def _form_labels_check(r, k):
    """The issue-form half of the row. Whether the taxonomy exists on GitHub
    (and the defaults are renamed) needs the labels API — `gh label list`."""
    d = r.path / ".github" / "ISSUE_TEMPLATE"
    forms = sorted(p for p in d.glob("*") if p.suffix in (".yml", ".yaml", ".md") and p.stem != "config") if d.is_dir() else []
    if not forms:
        return _skip("no issue templates in the tree; inherited forms and repo labels are not visible offline")
    types, bad = fleet_types(r.hub), []
    for p in forms:
        labels = _form_labels(p)
        if labels is None:
            bad.append(f"{p.name} unparseable")
        elif dup := [x for x in labels if DUPLICATE_LABEL.match(x)]:
            bad.append(f"{p.name} applies {', '.join(dup)}")
        elif p.stem not in FORM_LABEL_EXEMPT and not set(labels) & types:
            bad.append(f"{p.name} applies no fleet type label")
    return _ok("forms only; repo labels not checked offline") if not bad else _no("; ".join(bad))


@check("UPS-WORK-10")
def _hub_refs_pinned(r, k):
    files = sorted((r.path / ".github" / "workflows").glob("*.y*ml")) + sorted((r.path / ".github" / "actions").glob("*/action.y*ml"))
    floating = [f"{p.name}: {m.group(1).rsplit('/', 1)[-1]}@{m.group(2)}"
                for p in files for m in HUB_USES.finditer(p.read_text(encoding="utf-8", errors="replace"))
                if not PINNED_REF.fullmatch(m.group(2))]
    return _ok() if not floating else _no("hub workflow/action not pinned to a tag or SHA: " + ", ".join(floating[:4])
                                          + (f" (+{len(floating) - 4} more)" if len(floating) > 4 else ""))


@check("UPS-WORK-12")
def _agent_names_the_loop(r, k):
    p = _pending(r, "D4", "which agent file carries § Conventions")
    if p:
        return p
    t = r.read("CLAUDE.md")
    if not t:
        return _no("no CLAUDE.md")
    sec = _section(t, r"conventions?")
    if sec is None:
        return _no("CLAUDE.md has no `## Conventions` section")
    missing = [n for n, rx in (("backlog of record", r"backlog"), ("DoD location", r"definition of done|\bdod\b|pull_request_template"),
                                ("ADR path", r"\badrs?\b|decisions?/|DECISIONS\.md")) if not re.search(rx, sec, re.I)]
    return _ok() if not missing else _no("CLAUDE.md § Conventions does not name: " + ", ".join(missing))


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
    results, unverified, manual = [], [], 0
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
        if ok is None:  # not decidable offline, or waiting on a pending decision
            unverified.append({"id": req["id"], "level": req["level"], "detail": detail})
            continue
        results.append({"id": req["id"], "level": req["level"], "ok": bool(ok), "detail": detail,
                        "spec": req.get("area", "")})
    failing = [x for x in results if not x["ok"]]
    return {
        "path": str(repo.path), "kinds": kinds, "tier": tier,
        "checked": len(results), "passed": len(results) - len(failing),
        "must_failed": sum(1 for x in failing if x["level"] == "MUST"),
        "should_failed": sum(1 for x in failing if x["level"] == "SHOULD"),
        "manual": manual,
        "unverified": unverified,
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
             f"SHOULD failing {res['should_failed']}  manual {res['manual']}"
             + (f"  unverified {len(res['unverified'])}" if res.get("unverified") else "")]
    for f in sorted(res["failing"], key=lambda x: (x["level"] != "MUST", x["id"])):
        lines.append(f"  {'✗' if f['level'] == 'MUST' else '~'} {f['id']:<14} {f['level']:<6} {f['detail']}  ({f['spec']})")
    for u in res.get("unverified", []):
        lines.append(f"  ? {u['id']:<14} {u['level']:<6} {u['detail']}")
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


def fleet(hub: Path, write: Path | None, as_json: bool, enabled: set[str] | None = None) -> int:
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
        repo.registry_entry, repo.enabled_decisions = e, set(enabled or ())
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
    pend = "comma-separated pending decisions whose rules to enforce (" + ", ".join(PENDING_DECISIONS) + "); default: none"
    c.add_argument("--enable-pending", default="", help=pend)
    f = sub.add_parser("fleet", help="check every checked-out submodule")
    f.add_argument("--write", nargs="?", const=str(HUB_DEFAULT / "_data" / "conformance.yml"))
    f.add_argument("--json", action="store_true")
    f.add_argument("--hub", default=str(HUB_DEFAULT))
    f.add_argument("--enable-pending", default="", help=pend)
    k = sub.add_parser("kinds", help="print detected kinds for a path")
    k.add_argument("path", nargs="?", default=".")
    k.add_argument("--hub", default=str(HUB_DEFAULT))
    a = ap.parse_args(argv)
    hub = Path(a.hub)
    enabled = {x.strip().upper() for x in getattr(a, "enable_pending", "").split(",") if x.strip()}
    if enabled - set(PENDING_DECISIONS):
        ap.error(f"unknown pending decisions: {sorted(enabled - set(PENDING_DECISIONS))} (valid: {', '.join(PENDING_DECISIONS)})")

    if a.cmd == "fleet":
        return fleet(hub, Path(a.write) if a.write else None, a.json, enabled)
    repo = Repo(Path(a.path), hub)
    repo.enabled_decisions = enabled
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
