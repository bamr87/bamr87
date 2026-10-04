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
             cannot decide offline are listed as `unverified`; rows at spec
             level `retired` are skipped. Results are pass | warn | fail |
             unverified: a warning is reported but never counts toward
             must_failed or `--gate`. Rules marked `rollout: warn` in the hub's
             specs/WORK.contract.yml report a failure as a warning (delete the
             marker to make the rule gate). The UPS-WORK, UPS-AGENT-07/08/09 and
             UPS-REPO-21 rows are keyed to that contract.
Author: bamr87
Created: 2026-09-01
Last Modified: 2026-10-04
Version: 0.3.1
Usage: python3 tools/conformance.py check [PATH] [--kinds site,app] [--tier active] [--gate] [--json] [--hub DIR]
       python3 tools/conformance.py fleet [--write _data/conformance.yml] [--json]
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

CHECKER_VERSION = "0.3.1"
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
    if re.search(r"uses:\s*bamr87/bamr87/\.github/workflows/standard-ci\.yml@", t):
        return _ok()
    if re.search(r"uses:\s*bamr87/\.github/\.github/workflows/ci\.yml@", t):
        return _no("ci.yml calls bamr87/.github ci.yml, which is retired — call bamr87/bamr87 standard-ci.yml")
    return _no("ci.yml is bespoke (not a thin caller of the shared gate, bamr87/bamr87 standard-ci.yml)")


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
# UPS-WORK — planning & delivery (specs/WORK.md), plus the rows that changed
# with it: UPS-AGENT-07/08/09 (decision D4) and UPS-REPO-21 (decision D5).
#
# KEYED TO THE CONTRACT. specs/WORK.contract.yml (hub) is the machine contract
# for these rows: every path, key, list and regex it names under `definitions:`
# is read from it at run time (`_defs(r)`), never copied here. The few regexes
# the contract states only inside a rule's `pass:` text are in `RULE_RX`, keyed
# by rule id; tools/test_conformance_work.py fails if one stops appearing
# verbatim in the contract. When the hub checkout has no contract (it predates
# bamr87/bamr87#323), these rows report `unverified` instead of guessing.
#
# Result vocabulary (the contract's): pass | warn | fail | unverified. A check
# returns True / WARN / False / None. WARN is a deprecated-but-accepted shape
# (a rule's own `warn:` clause). Separately, every rule the contract marks
# `rollout: warn` reports a would-be fail as a warning too (see warn_only()).
#
# One failure per root cause: a rule that only reads a file another rule owns
# passes, naming the owner, when the file is missing (CHANGELOG.md belongs to
# UPS-REPO-21; AGENTS.md and its `## Conventions` heading to UPS-AGENT-07).
# --------------------------------------------------------------------------- #
CONTRACT_FILE = "specs/WORK.contract.yml"
WARN = "warn"
FLEET_TYPES_FALLBACK = ("bug", "feature", "docs", "chore", "ci", "refactor", "test", "security", "question")
SPEC_STALE_DAYS, BACKLOG_LAG_DAYS = 30, 60
# Regexes and literals the contract states inside a rule's `pass:` prose (it has
# no named definition for them). Each must appear verbatim in that rule's text.
RULE_RX = {
    "UPS-WORK-03": r"^- \[ \] \*\*(.+?)\*\*",
    "UPS-WORK-05/unreleased": r"^##\s*\[?unreleased\b",
    "UPS-WORK-05/tag": r"^v?\d+\.\d+\.\d+$",
    "UPS-WORK-05/heading": r"^##\s*\[?v?(\d+\.\d+\.\d+)",
    "UPS-WORK-11/task": r"^\s*[-*] \[[ xX]\] ",
    "UPS-WORK-11/id": r"\b(BL-\d{8}-\d{2}|T-\d{3,})\b",
    "UPS-WORK-11/hub-roadmap": "bamr87/bamr87/blob/main/_data/roadmap.yml",
    "UPS-WORK-12/section": r"^##\s+Conventions\b",
    "UPS-WORK-12/dod": r"Definition of Done|pull_request_template",
    "UPS-REPO-21/no-profile": "simple|node|python|ruby",
}

_CONTRACTS: dict[Path, dict | None] = {}


def contract(r) -> dict | None:
    """The hub's WORK contract: {"defs", "rules", "related"}, or None if absent."""
    if r.hub not in _CONTRACTS:
        p = r.hub / CONTRACT_FILE
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) if p.is_file() else None
        except (OSError, yaml.YAMLError):
            data = None
        _CONTRACTS[r.hub] = None if not isinstance(data, dict) else {
            "defs": data.get("definitions") or {}, "rules": data.get("rules") or {}, "related": data.get("related") or {}}
    return _CONTRACTS[r.hub]


def _need_contract(fn):
    """Decorator: report `unverified` (not pass/fail) when the hub has no contract."""
    def wrapped(r, k):
        if contract(r) is None:
            return None, f"hub checkout has no {CONTRACT_FILE} (bamr87/bamr87#323); row not evaluated"
        return fn(r, k)
    wrapped.__name__, wrapped.__doc__ = fn.__name__, fn.__doc__
    return wrapped


def _defs(r) -> dict:
    return (contract(r) or {}).get("defs") or {}


def _rule(r, rid: str) -> dict:
    c = contract(r) or {}
    return (c.get("rules") or {}).get(rid) or (c.get("related") or {}).get(rid) or {}


def warn_only(r) -> dict[str, str]:
    """Rules the contract marks `rollout: warn`: a failure is reported as a
    warning that never counts toward must_failed or `--gate`. Fleet Ops makes a
    rule gate by deleting its marker in specs/WORK.contract.yml; nothing here
    changes."""
    c = contract(r) or {}
    rules = {**(c.get("rules") or {}), **(c.get("related") or {})}
    return {rid: "rollout: warn in specs/WORK.contract.yml"
            + (" (rollout_effect: fails once the marker is removed)" if v.get("rollout_effect") else "")
            for rid, v in rules.items() if isinstance(v, dict) and v.get("rollout") == "warn"}


def _hub_path(r, ref: str) -> Path:
    """A contract path: `hub:x` is relative to the hub checkout, anything else to the repo."""
    ref = str(ref).split()[0]
    return r.hub / ref[4:] if ref.startswith("hub:") else r.path / ref


def _skip(msg: str) -> tuple[None, str]:
    return None, msg


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


def _jsonable(v):
    """YAML -> JSON data model: an unquoted `until: 2027-01-01` loads as a date."""
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    return v


def sdlc_profile(r) -> tuple[dict | None, str, str | None]:
    """(profile, source, error) per the contract's `profile_precedence`:
    `.github/sdlc.yml` first, then the registry `sdlc:` block. A registry
    `modules:` list is normalised to the canonical map (allowed there only)."""
    if not hasattr(r, "_sdlc"):
        f = str(_defs(r).get("sdlc_file") or ".github/sdlc.yml")
        prof, src, err = None, "", None
        if r.has(f):
            src = f
            try:
                data = yaml.safe_load(r.read(f))
                prof = _jsonable(data) if isinstance(data, dict) else {}
                if not isinstance(data, dict):
                    err = "not a YAML mapping"
            except yaml.YAMLError as e:
                prof, err = {}, f"YAML error: {str(e).splitlines()[0]}"
        else:
            e = registry_entry(r)
            if e and isinstance(e.get("sdlc"), dict):
                prof, src = _jsonable(e["sdlc"]), "registry `sdlc:` block"
                if isinstance(prof.get("modules"), list):
                    prof["modules"] = {str(m): True for m in prof["modules"]}
        r._sdlc = (prof, src, err)
    return r._sdlc


def sdlc_modules(prof: dict | None) -> set[str]:
    m = (prof or {}).get("modules")
    if isinstance(m, dict):
        return {str(k) for k, v in m.items() if v}
    return {str(x) for x in m} if isinstance(m, list) else set()


def profile_kinds(r) -> list[str] | None:
    """Kinds from the profile (D6): `kinds:` if given, else the contract's
    `type_kinds` default for `type:`. Marker kinds (`hub`) are dropped."""
    prof = sdlc_profile(r)[0] or {}
    ks = prof.get("kinds") or (_defs(r).get("type_kinds") or {}).get(prof.get("type"))
    ks = [str(x) for x in ks or [] if str(x) in KINDS]
    return ks or None


def _backlog_decl(prof: dict | None) -> dict:
    b = (prof or {}).get("backlog")
    return b if isinstance(b, dict) else {}


def _adr_path(r, prof: dict | None) -> str:
    return str((prof or {}).get("adr_path") or _defs(r).get("adr_path_default") or "docs/adr").strip("/")


def _workflow_texts(r) -> list[tuple[str, str]]:
    d = r.path / ".github" / "workflows"
    return [(p.name, p.read_text(encoding="utf-8", errors="replace")) for p in sorted(d.glob("*.y*ml"))] if d.is_dir() else []


def _section(text: str, heading_rx: str) -> str | None:
    m = re.search(heading_rx + r".*$", text, re.I | re.M)
    if not m:
        return None
    nxt = re.search(r"^##\s", text[m.end():], re.M)
    return text[m.end(): m.end() + nxt.start()] if nxt else text[m.end():]


def _at(node, segs: list[str]) -> list:
    """Values at a contract key path: `<name>` = every value of a mapping,
    `key[]` = every item of the list at key, `key` = that key."""
    if not segs:
        return [node]
    seg, rest = segs[0], segs[1:]
    if seg.startswith("<") and seg.endswith(">"):
        return [v for x in (node.values() if isinstance(node, dict) else []) for v in _at(x, rest)]
    if seg.endswith("[]"):
        items = node.get(seg[:-2]) if isinstance(node, dict) else None
        return [v for x in (items if isinstance(items, list) else []) for v in _at(x, rest)]
    return _at(node[seg], rest) if isinstance(node, dict) and seg in node else []


def yaml_values(p: Path, keys: list[str]) -> list[str] | None:
    """String values parsed (yaml.safe_load) from p at the contract key paths
    `keys` (see _at). Raw text, comments and other keys never count.
    None = the file is not valid YAML."""
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8", errors="replace"))
    except yaml.YAMLError:
        return None
    return [v.strip() for key in keys for v in _at(doc, str(key).split(".")) if isinstance(v, str)]


def uses_values(r, p: Path, only: str | None = None) -> list[str] | None:
    """The `uses:` values parsed from a pin_scope file at the contract's
    uses_keys (workflow keys under .github/workflows/, action keys elsewhere);
    `only` restricts to one key path. None = the file is not valid YAML."""
    keys = (_defs(r).get("uses_keys") or {}).get("workflow" if p.parent.name == "workflows" else "action") or []
    return yaml_values(p, [k for k in keys if only is None or k == only])


def _pin_files(r) -> list[Path]:
    """Contract pin_scope (globs relative to the repo root; `**` is recursive)."""
    out: set[Path] = set()
    for g in _defs(r).get("pin_scope") or []:
        out.update(p for p in r.path.glob(g) if p.is_file())
    return sorted(out)


# --- a JSON Schema subset, enough for templates/sdlc/sdlc.schema.json ------ #
# (PyYAML is the checker's only dependency; jsonschema is not installed in CI.)
SCHEMA_KEYWORDS = {"$schema", "$id", "title", "description", "default", "type", "const", "enum", "required",
                   "properties", "additionalProperties", "items", "minItems", "uniqueItems", "pattern",
                   "minLength", "if", "then", "else", "not", "anyOf", "allOf"}
_JSON_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool}


def schema_errors(inst, schema: dict, ptr: str = "") -> list[str]:
    """Violations as `<json-pointer>: message` (empty list = valid)."""
    errs: list[str] = []
    at = ptr or "/"
    unknown = set(schema) - SCHEMA_KEYWORDS
    if unknown:
        return [f"{at}: schema keyword(s) {', '.join(sorted(unknown))} not supported by the checker"]
    t = schema.get("type")
    if t:
        py = _JSON_TYPES.get(t)
        if py is None or not isinstance(inst, py) or (py is not bool and isinstance(inst, bool)):
            return [f"{at}: expected {t}"]
    if "const" in schema and inst != schema["const"]:
        errs.append(f"{at}: must be {json.dumps(schema['const'])}")
    if "enum" in schema and inst not in schema["enum"]:
        errs.append(f"{at}: {json.dumps(inst)} is not one of {', '.join(map(str, schema['enum']))}")
    if isinstance(inst, str):
        if "pattern" in schema and not re.search(schema["pattern"], inst):
            errs.append(f"{at}: {inst!r} does not match {schema['pattern']}")
        if len(inst) < schema.get("minLength", 0):
            errs.append(f"{at}: shorter than {schema['minLength']}")
    if isinstance(inst, list):
        if len(inst) < schema.get("minItems", 0):
            errs.append(f"{at}: fewer than {schema['minItems']} item(s)")
        if schema.get("uniqueItems") and len({json.dumps(x, sort_keys=True) for x in inst}) != len(inst):
            errs.append(f"{at}: items are not unique")
        if isinstance(schema.get("items"), dict):
            for i, x in enumerate(inst):
                errs += schema_errors(x, schema["items"], f"{ptr}/{i}")
    if isinstance(inst, dict):
        for req in schema.get("required", []):
            if req not in inst:
                errs.append(f"{at}: missing required `{req}`")
        props = schema.get("properties") or {}
        for key, val in inst.items():
            if key in props:
                errs += schema_errors(val, props[key], f"{ptr}/{key}")
            elif schema.get("additionalProperties") is False:
                errs.append(f"{ptr}/{key}: unknown key")
    for sub in schema.get("allOf", []):
        errs += schema_errors(inst, sub, ptr)
    if "anyOf" in schema and not any(not schema_errors(inst, s, ptr) for s in schema["anyOf"]):
        errs.append(f"{at}: matches none of anyOf")
    if "not" in schema and not schema_errors(inst, schema["not"], ptr):
        errs.append(f"{at}: matches a forbidden shape (not)")
    if "if" in schema:
        branch = schema.get("then") if not schema_errors(inst, schema["if"], ptr) else schema.get("else")
        if branch:
            errs += schema_errors(inst, branch, ptr)
    return errs


@check("UPS-WORK-01")
@_need_contract
def _sdlc_declared(r, k):
    """Contract UPS-WORK-01: a profile (sdlc_file, else registry_block) valid against sdlc_schema."""
    prof, src, err = sdlc_profile(r)
    if prof is None:
        return _no(f"no {_defs(r).get('sdlc_file')} and no registry `sdlc:` block")
    if err:
        return _no(f"{src}: {err}")
    sp = _hub_path(r, _defs(r).get("sdlc_schema", "hub:templates/sdlc/sdlc.schema.json"))
    if not sp.is_file():
        return _skip(f"{src} found, but the hub checkout has no {sp.relative_to(r.hub)} (bamr87/bamr87#324) to validate it")
    errs = schema_errors(prof, json.loads(sp.read_text(encoding="utf-8")))
    if errs:
        return _no(f"{src}: " + "; ".join(errs[:4]) + (f" (+{len(errs) - 4} more)" if len(errs) > 4 else ""))
    return _ok(f"{src} (type {prof.get('type')})")


@check("UPS-WORK-02")
@_need_contract
def _backlog_of_record(r, k):
    """Contract UPS-WORK-02: file mode = backlog.file exists and, in a
    backlog_lint_scope file parsed as YAML, a value at backlog_lint_keys matches
    backlog_lint_value_re (re.I). Comments, `name:` and invalid YAML never count."""
    b = _backlog_decl(sdlc_profile(r)[0])
    if (b.get("mode") or "issues") != "file":
        return _skip("issues mode: the fleet labels on Issues are not visible offline (UPS-WORK-14)")
    f = b.get("file")
    if not f or not r.has(f):
        return _no(f"backlog.mode is file but backlog.file {f or '(unset)'} is missing")
    d = _defs(r)
    rx = re.compile(d["backlog_lint_value_re"], re.I)
    keys = (d.get("backlog_lint_keys") or {}).get("workflow") or []
    files = sorted({p for g in d.get("backlog_lint_scope") or [] for p in r.path.glob(g) if p.is_file()})
    lint = next((p.name for p in files if any(rx.search(v) for v in yaml_values(p, keys) or [])), None)
    return _ok(f"{f}, linted in {lint}") if lint else _no(f"{f} has no CI lint (no workflow step or job runs a backlog lint; a sync job is not one)")


def _dod_block(text: str, rx: str) -> tuple[str, list[str]] | None:
    m = re.search(rx, text, re.S)
    return (m.group(1), re.findall(RULE_RX["UPS-WORK-03"], m.group(2), re.M)) if m else None


@check("UPS-WORK-03")
@_need_contract
def _definition_of_done(r, k):
    """Contract UPS-WORK-03: the first PR template carries the fleet-dod block with the reference boxes."""
    d = _defs(r)
    path = None
    for p in d.get("pr_templates") or []:
        path = r.glob1(p) if "*" in p else (p if r.has(p) else None)
        if path:
            break
    if not path:
        return _skip("no PR template in the tree; the owner's `.github` default applies and is not visible offline")
    mine = _dod_block(r.read(path), d["dod_block_re"])
    if not mine:
        return _no(f"{path} has no `<!-- fleet-dod:start vN -->` … `<!-- fleet-dod:end -->` block")
    ref_p = _hub_path(r, d["dod_reference"])
    ref = _dod_block(ref_p.read_text(encoding="utf-8"), d["dod_block_re"]) if ref_p.is_file() else None
    if not ref:
        return _skip(f"{path} has a v{mine[0]} block; the hub has no reference template (bamr87/bamr87#319) to compare")
    vers = _defs(r).get("dod_versions") or {"pass_offset": 0, "warn_offset": -1}
    n, have = int(ref[0]), int(mine[0])
    if have == n + int(vers.get("warn_offset", -1)) and have != n + int(vers.get("pass_offset", 0)):
        return WARN, f"{path} carries fleet-dod v{have}; the hub kit is v{n} (previous version: update during the rollout)"
    if have != n + int(vers.get("pass_offset", 0)):
        return _no(f"{path} carries fleet-dod v{have}; the hub kit is v{n}")
    if mine[1] != ref[1]:
        missing = [b for b in ref[1] if b not in mine[1]]
        return _no(f"{path} DoD boxes differ from the kit" + (f" (missing: {', '.join(missing)})" if missing else " (order or wording)"))
    return _ok(f"{path} (fleet-dod v{mine[0]})")


@check("UPS-WORK-04")
@_need_contract
def _adr_log(r, k):
    """Contract UPS-WORK-04 (and WORK-13): <adr_path>/<adr_index> + >= 1 adr_file_re
    file (adr_template_re never counts). adr_alias_re files (ADR-NNNN-slug.md)
    count with a warning until the D2 rename."""
    defs = _defs(r)
    d = _adr_path(r, sdlc_profile(r)[0])
    p = r.path / d
    names = sorted(x.name for x in p.glob("*.md")) if p.is_dir() else []
    tpl = re.compile(defs.get("adr_template_re") or r"^(ADR-)?0000-")
    canon = [n for n in names if re.match(defs["adr_file_re"], n) and not tpl.match(n)]
    alias = [n for n in names if re.match(defs["adr_alias_re"], n) and not tpl.match(n)]
    index = str(defs.get("adr_index") or "README.md")
    if not canon and not alias:
        return _no(f"no ADRs in {d}/ (NNNN-slug.md)")
    if not (p / index).is_file():
        return _no(f"{d}/ has {len(canon) + len(alias)} ADR(s) but no {index} index")
    if alias:
        return WARN, f"{d}/: deprecated ADR- names, rename to NNNN-slug.md (D2): " + ", ".join(alias[:4]) + (f" (+{len(alias) - 4} more)" if len(alias) > 4 else "")
    return _ok(f"{len(canon)} ADR(s) in {d}/")


CHECKS["UPS-WORK-13"] = CHECKS["UPS-WORK-04"]  # contract: same_as UPS-WORK-04


def _latest_tag(r) -> str | None:
    tags = [t for t in _git(r, "tag", "--list", "--sort=-v:refname").splitlines() if re.match(RULE_RX["UPS-WORK-05/tag"], t)]
    return tags[0] if tags else None


@check("UPS-WORK-05")
@_need_contract
def _changelog_hygiene(r, k):
    """Contract UPS-WORK-05: at most one [Unreleased]; newest heading == newest tag."""
    t = r.read(str(_defs(r).get("changelog") or "CHANGELOG.md"))
    if not t:
        return _ok("no CHANGELOG.md, see UPS-REPO-21")
    n = len(re.findall(RULE_RX["UPS-WORK-05/unreleased"], t, re.I | re.M))
    if n > 1:
        return _no(f"CHANGELOG.md has {n} `## [Unreleased]` headings (at most one)")
    m = re.search(RULE_RX["UPS-WORK-05/heading"], t, re.M)
    if not m:
        return _ok("no released version headings yet")
    tag = _latest_tag(r)
    if tag is None:
        return _ok(f"newest heading {m.group(1)}; no version tags in this checkout to compare")
    return _ok(f"{m.group(1)} = {tag}") if m.group(1) == tag.lstrip("v") else _no(f"newest CHANGELOG heading {m.group(1)} ≠ newest tag {tag}")


@check("UPS-WORK-06")
@_need_contract
def _features_hygiene(r, k):
    """Contract UPS-WORK-06: one catalog, no hand-maintained version header."""
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
@_need_contract
def _spec_gate(r, k):
    """Contract UPS-WORK-07 (binds only with modules.spec_driven): spec packages,
    BACKLOG.md, a spec-gate job every other job needs, backlog_lint in that
    workflow, and the kit tools byte-identical to the hub's copies."""
    if "spec_driven" not in sdlc_modules(sdlc_profile(r)[0]):
        return _ok("module spec_driven not declared")
    d = _defs(r)
    problems = ([] if r.glob1("specs/[0-9][0-9][0-9]-*/spec.md") else ["no specs/NNN-slug/spec.md"]) + \
               ([] if r.has("BACKLOG.md") else ["no BACKLOG.md"])
    gate = None
    for name, text in _workflow_texts(r):
        jobs = _jobs(text)
        for jid, job in jobs.items():
            if "spec_validator.py" in yaml.safe_dump(job):
                ungated = [o for o in jobs if o != jid and o not in _closure(jobs, jid) and jid not in _closure(jobs, o)]
                gate = (name, jid, ungated, "backlog_lint.py" in text)
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
    kit, note = _hub_path(r, d.get("spec_driven_kit", "hub:templates/spec-driven/tools/")), ""
    tools = set(d.get("spec_driven_tools") or [])
    if kit.is_dir():
        for rel in r.tracked():
            base = Path(rel).name
            if base in tools and (kit / base).is_file() and (r.path / rel).is_file() \
                    and (r.path / rel).read_bytes() != (kit / base).read_bytes():
                problems.append(f"{rel} differs from the hub kit")
    else:
        note = f"; hub kit {kit.relative_to(r.hub)}/ not in this checkout (bamr87/bamr87#325), tool parity unchecked"
    return _no("; ".join(problems) + note) if problems else _ok(f"spec-gate `{gate[1]}` in {gate[0]}{note}")


@check("UPS-WORK-08")
@_need_contract
def _freshness(r, k):
    """Contract UPS-WORK-08 (scorecard, SHOULD): in-progress spec idle > 30 days;
    backlog file last committed > 60 days before HEAD. The P0/P1 clause is online."""
    head = _last_commit(r)
    if head is None:
        return _skip("no git history in this checkout")
    now, flags = dt.datetime.now(dt.timezone.utc), []
    for spec in sorted(r.path.glob("specs/*/spec.md")):
        m = re.search(r"^\s*(?:[-*]\s*)?\**status\**\s*:\s*\**\s*([a-z-]+)", spec.read_text(encoding="utf-8", errors="replace"), re.I | re.M)
        last = _last_commit(r, str(spec.parent.relative_to(r.path)))
        if m and m.group(1).lower() == "in-progress" and last and (now - last).days > SPEC_STALE_DAYS:
            flags.append(f"{spec.parent.name} in-progress, idle {(now - last).days}d")
    b = _backlog_decl(sdlc_profile(r)[0]).get("file")
    if b and r.has(b):
        last = _last_commit(r, b)
        if last and (head - last).days > BACKLOG_LAG_DAYS:
            flags.append(f"{b} last touched {(head - last).days}d before the last commit")
    return _ok() if not flags else _no("; ".join(flags))


def fleet_types(r) -> set[str]:
    """Contract labels_source: hub _data/fleet.yml issue_pipeline.labels (types)."""
    try:
        cfg = yaml.safe_load((r.hub / "_data" / "fleet.yml").read_text(encoding="utf-8")) or {}
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
@_need_contract
def _form_labels_check(r, k):
    """Contract UPS-WORK-09: no duplicate_label_re label; exactly one fleet type label (form_label_exempt aside)."""
    d = _defs(r)
    dup_rx = re.compile(d["duplicate_label_re"], re.I)
    exempt = set(d.get("form_label_exempt") or [])
    fd = r.path / ".github" / "ISSUE_TEMPLATE"
    forms = sorted(p for p in fd.glob("*") if p.suffix in (".yml", ".yaml", ".md") and p.stem != "config") if fd.is_dir() else []
    if not forms:
        return _skip("no issue forms in the tree (inherited forms are not visible offline)")
    types, bad = fleet_types(r), []
    for p in forms:
        labels = _form_labels(p)
        if labels is None:
            bad.append(f"{p.name} unparseable")
            continue
        if dup := [x for x in labels if dup_rx.match(x)]:
            bad.append(f"{p.name} applies {', '.join(dup)}")
        n = len(set(labels) & types)
        if p.stem not in exempt and n != 1:
            bad.append(f"{p.name} applies {n} fleet type labels (exactly one)")
    return _ok(f"{len(forms)} form(s); repo labels are UPS-WORK-14 (online)") if not bad else _no("; ".join(bad))


@check("UPS-WORK-10")
@_need_contract
def _hub_refs_pinned(r, k):
    """Contract UPS-WORK-10: every parsed `uses:` value (uses_keys) matching
    fleet_uses_value_re has a ref that fullmatches pinned_ref_re. `run:` text,
    other strings and comments are never inspected."""
    d = _defs(r)
    fleet, pin = re.compile(d["fleet_uses_value_re"]), re.compile(d["pinned_ref_re"])
    floating, broken = [], []
    for p in _pin_files(r):
        vals = uses_values(r, p)
        if vals is None:
            broken.append(str(p.relative_to(r.path)))
            continue
        for v in vals:
            m = fleet.match(v)
            if m and not pin.fullmatch(m.group(2)):
                floating.append(f"{p.name}: {m.group(1).rsplit('/', 1)[-1]}@{m.group(2)}")
    problems = ([f"not valid YAML: {', '.join(broken)}"] if broken else []) + (
        ["fleet workflow/action not pinned to @vN, @vX.Y.Z or a full SHA: " + ", ".join(floating[:4])
         + (f" (+{len(floating) - 4} more)" if len(floating) > 4 else "")] if floating else [])
    return _ok() if not problems else _no("; ".join(problems))


def _strip_md_links(t: str) -> str:
    return re.sub(r"!?\[[^\]]*\]\([^)]*\)|<https?://[^>]+>", "", t)


@check("UPS-WORK-11")
@_need_contract
def _planning_files(r, k):
    """Contract UPS-WORK-11: planning files hold no item list and link the backlog of record."""
    b = _backlog_decl(sdlc_profile(r)[0])
    link = b.get("file") if b.get("mode") == "file" and b.get("file") else "/issues"
    bad = []
    for f in _rule(r, "UPS-WORK-11").get("reads") or []:
        t = r.read(f)
        if not r.has(f):
            continue
        plain = _strip_md_links(t)
        if re.search(RULE_RX["UPS-WORK-11/task"], t, re.M):
            bad.append(f"{f} has task-list items")
        if ids := re.findall(RULE_RX["UPS-WORK-11/id"], plain):
            bad.append(f"{f} carries backlog ids ({', '.join(sorted(set(ids))[:3])})")
        if link not in t and RULE_RX["UPS-WORK-11/hub-roadmap"] not in t:
            bad.append(f"{f} does not link the backlog of record ({link})")
    return _ok() if not bad else _no("; ".join(bad))


@check("UPS-WORK-12")
@_need_contract
def _agents_conventions(r, k):
    """Contract UPS-WORK-12: AGENTS.md § Conventions names the backlog, the DoD and
    the literal adr_path (re.I; 'ADR' when the profile sets modules.adr: false).
    A missing AGENTS.md or `## Conventions` heading is UPS-AGENT-07's failure
    (Conventions is one of agents_required_headings); this row then passes."""
    a = r.read(str(_defs(r).get("agents_file") or "AGENTS.md"))
    if not a:
        return _ok("no AGENTS.md, see UPS-AGENT-07")
    sec = _section(a, RULE_RX["UPS-WORK-12/section"])
    if sec is None:
        return _ok("no `## Conventions` section, see UPS-AGENT-07")
    prof = sdlc_profile(r)[0]
    adr_off = isinstance((prof or {}).get("modules"), dict) and prof["modules"].get("adr") is False
    adr = "ADR" if adr_off else _adr_path(r, prof)
    missing = [n for n, ok in (("backlog", re.search(r"backlog", sec, re.I)),
                               ("Definition of Done", re.search(RULE_RX["UPS-WORK-12/dod"], sec, re.I)),
                               (f"ADR path `{adr}`", re.search(re.escape(adr), sec, re.I))) if not ok]
    return _ok() if not missing else _no("AGENTS.md § Conventions does not name: " + ", ".join(missing))


def _h2(r, text: str) -> list[str]:
    rx = _defs(r).get("agents_heading_re") or r"^##[ \t]+(.+?)[ \t]*#*[ \t]*$"
    return [h.strip() for h in re.findall(rx, text, re.M)]


@check("UPS-AGENT-07")
@_need_contract
def _agents_md(r, k):
    """Contract related.UPS-AGENT-07: agents_file has every agents_required_headings
    name (trimmed, case-insensitive; agents_heading_order / agents_extra_headings
    decide order and extras) and no agents_todo_re line."""
    d = _defs(r)
    a = r.read(str(d.get("agents_file") or "AGENTS.md"))
    if not a:
        return _no("no AGENTS.md (canonical agent file, D4)")
    want = [str(x) for x in d.get("agents_required_headings") or []]
    heads = [h.lower() for h in _h2(r, a)]
    problems = []
    absent = [w for w in want if w.lower() not in heads]
    if absent:
        problems.append("missing ## " + ", ".join(absent))
    elif d.get("agents_heading_order") and [h for h in heads if h in {w.lower() for w in want}] != [w.lower() for w in want]:
        problems.append("required headings out of order")
    if d.get("agents_extra_headings") is False and (extra := [h for h in heads if h not in {w.lower() for w in want}]):
        problems.append("extra headings: " + ", ".join(extra[:3]))
    if re.search(d.get("agents_todo_re") or r"^TODO:", a, re.M):
        problems.append("scaffold `TODO:` lines left")
    return _ok() if not problems else _no("AGENTS.md: " + "; ".join(problems))


@check("UPS-AGENT-08")
@_need_contract
def _claude_pointer(r, k):
    """Contract related.UPS-AGENT-08: claude_file has a claude_pointer_re line, no
    agents_required_headings heading, and <= claude_max_nonblank_lines non-blank lines."""
    d = _defs(r)
    t = r.read(str(d.get("claude_file") or "CLAUDE.md"))
    if not t:
        return _no("no CLAUDE.md pointer")
    problems = []
    if not re.search(d["claude_pointer_re"], t, re.M):
        problems.append(f"no `{d.get('claude_pointer', '@AGENTS.md')}` import line")
    want = {str(x).lower() for x in d.get("agents_required_headings") or []}
    if dup := [h for h in _h2(r, t) if h.lower() in want]:
        problems.append("carries AGENTS.md headings: " + ", ".join(dup[:3]))
    limit = int(d.get("claude_max_nonblank_lines", 20))
    n = sum(1 for line in t.splitlines() if line.strip())
    if n > limit:
        problems.append(f"{n} non-blank lines (max {limit})")
    return _ok() if not problems else _no("CLAUDE.md: " + "; ".join(problems))


@check("UPS-AGENT-09")
@_need_contract
def _agents_kit_stamp(r, k):
    """Contract related.UPS-AGENT-09: kit_stamp.file matches kit_stamp.re. A
    missing AGENTS.md is UPS-AGENT-07's failure."""
    ks = _defs(r).get("kit_stamp") or {}
    f = str(ks.get("file") or "AGENTS.md")
    a = r.read(f)
    if not a:
        return _ok(f"no {f}, see UPS-AGENT-07")
    m = re.search(ks["re"], a)
    return _ok(f"kit {m.group(1)} v{m.group(2)}") if m else _no(f"{f} lacks the kit stamp {ks.get('format', '')}".rstrip())


@check("UPS-REPO-21")
@_need_contract
def _release_please(r, k):
    """Contract related.UPS-REPO-21: CHANGELOG.md; release_files parse; release-type
    allowed for the repo type (release_types); a job-level `uses:` of
    release_workflow at a pinned ref. A legacy_release_workflow caller (instead
    of release_workflow) fails at any ref; `rollout: warn` reports it as a warning
    (the rule's rollout_effect), like every other failure of this rule."""
    d = _defs(r)
    prof = sdlc_profile(r)[0] or {}
    rtype = prof.get("type")
    allowed_map = d.get("release_types") or {}
    if rtype in allowed_map and not allowed_map[rtype]:
        return _ok(f"type {rtype}: release-please does not apply")
    allowed = allowed_map.get(rtype) if rtype in allowed_map else RULE_RX["UPS-REPO-21/no-profile"].split("|")
    problems = [] if r.has(str(d.get("changelog") or "CHANGELOG.md")) else ["no CHANGELOG.md"]
    cfg = None
    for f in d.get("release_files") or []:
        if not r.has(f):
            problems.append(f"no {f}")
            continue
        try:
            data = json.loads(r.read(f))
        except json.JSONDecodeError:
            problems.append(f"{f} is not valid JSON")
            continue
        if f == "release-please-config.json":
            cfg = data
    if isinstance(cfg, dict):
        rt = ((cfg.get("packages") or {}).get(".") or {}).get("release-type")
        if rt not in allowed:
            problems.append(f"packages[\".\"].release-type is {rt!r} (allowed for {'type ' + rtype if rtype in allowed_map else 'a repo with no profile'}: {'|'.join(allowed)})")
    job_key = next(iter((d.get("uses_keys") or {}).get("workflow") or []), None)
    calls = [v for p in _pin_files(r) if p.parent.name == "workflows" for v in (uses_values(r, p, only=job_key) or [])]
    pin = re.compile(d["pinned_ref_re"])
    hub_refs = [v.split("@", 1)[1] for v in calls if v.split("@", 1)[0] == d["release_workflow"] and "@" in v]
    legacy = [v for v in calls if v.split("@", 1)[0] == d.get("legacy_release_workflow")]
    if hub_refs and not any(pin.fullmatch(x) for x in hub_refs):
        problems.append(f"release-please.yml called at an unpinned ref (@{hub_refs[0]})")
    elif not hub_refs and legacy:
        problems.append(f"migrate to {d['release_workflow']}@v1 (decision D3); today it calls {legacy[0]}")
    elif not hub_refs:
        problems.append(f"no job calls {d['release_workflow']}")
    return _no("; ".join(problems)) if problems else _ok()


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
    results, unverified, warnings, manual = [], [], [], 0
    for req in specs.get("requirements", []):
        if req.get("level") == "retired":  # kept in the spec for history; never checked
            continue
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
        if ok is None:  # not decidable offline
            unverified.append({"id": req["id"], "level": req["level"], "detail": detail})
            continue
        rollout = warn_only(repo)
        if ok == WARN or (not ok and req["id"] in rollout):  # reported, never counted
            warnings.append({"id": req["id"], "level": req["level"], "detail": detail,
                             "why_warn": "deprecated shape (the rule's warn clause)" if ok == WARN else rollout[req["id"]],
                             "spec": f"specs/{area_file(req.get('area', ''), specs)}"})
            continue
        results.append({"id": req["id"], "level": req["level"], "ok": bool(ok), "detail": detail,
                        "spec": req.get("area", "")})
    failing = [x for x in results if not x["ok"]]
    return {
        "path": str(repo.path), "kinds": kinds, "tier": tier,
        "checked": len(results) + len(warnings), "passed": len(results) - len(failing),
        "must_failed": sum(1 for x in failing if x["level"] == "MUST"),
        "should_failed": sum(1 for x in failing if x["level"] == "SHOULD"),
        "manual": manual,
        "unverified": unverified,
        "warnings": warnings,
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
             + (f"  unverified {len(res['unverified'])}" if res.get("unverified") else "")
             + (f"  warnings {len(res['warnings'])}" if res.get("warnings") else "")]
    for f in sorted(res["failing"], key=lambda x: (x["level"] != "MUST", x["id"])):
        lines.append(f"  {'✗' if f['level'] == 'MUST' else '~'} {f['id']:<14} {f['level']:<6} {f['detail']}  ({f['spec']})")
    for w in res.get("warnings", []):
        lines.append(f"  ! {w['id']:<14} WARN   {w['detail']}  ({w['spec']}; {w['why_warn']})")
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
        repo.registry_entry = e
        kinds = kinds_from_stack(e) or profile_kinds(repo) or detect_kinds(repo)
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
            "warnings": sum(len(r.get("warnings", [])) for r in repos),
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
              f"{s['must_failures']} MUST / {s['should_failures']} SHOULD failures, {s['warnings']} warnings; skipped {len(skipped)}")
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
    kinds = [x.strip() for x in a.kinds.split(",") if x.strip()] if a.kinds else (profile_kinds(repo) or detect_kinds(repo))
    bad = [x for x in kinds if x not in KINDS]
    if bad:
        ap.error(f"unknown kinds: {bad} (valid: {', '.join(KINDS)})")
    res = run_checks(repo, kinds, a.tier, load_specs(hub))
    print(json.dumps(res, indent=2) if a.json else render_text(res, repo.path.name))
    return 1 if (a.gate and res["must_failed"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
