#!/usr/bin/env python3
"""
Fixture tests for the UPS-WORK rows in tools/conformance.py (planning and
delivery: SDLC profile, backlog of record, Definition of Done, ADRs, CHANGELOG
and feature-catalog hygiene, spec-gate, freshness, form labels, pinned hub
references, the CLAUDE.md loop).

Guards the invariants that keep a draft area safe to ship ahead of its spec:

  * the WORK rows are inert until _data/specs.yml carries them — the hub's
    current spec runs exactly as before;
  * a fact the offline checker cannot see (inherited PR template or forms,
    labels on GitHub) is `unverified`, never a pass or a failure;
  * the settled decisions are hard requirements: D4 (AGENTS.md canonical,
    CLAUDE.md a pointer to it) and D5 (CHANGELOG.md in every repo, content
    included);
  * each check passes the canonical shape and fails the drift it targets.

Deliberately dependency-light — no network, no gh, no pytest. Needs PyYAML and
git:

    python3 tools/test_conformance_work.py
"""
from __future__ import annotations

import contextlib
import datetime as dt
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import conformance as c  # noqa: E402

HUB = Path(__file__).resolve().parent.parent
SDLC = {"schema": "sdlc/v1", "kind": "app", "tier": "active", "backlog": {"mode": "issues"},
        "modules": {"spec_driven": False, "adr": True}}
DOD = """## Definition of Done

- [ ] PR title is a Conventional Commit
- [ ] CI gate is green
- [ ] Tests added or updated
- [ ] README / docs updated; features/features.yml updated
- [ ] Decision recorded in docs/adr/ if hard to reverse
- [ ] Backlog of record updated
- [ ] No secrets or unrelated changes
"""


def write(root: Path, rel: str, text: str = "x") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def git(root: Path, *args: str, when: dt.datetime | None = None) -> None:
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    if when:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = when.strftime("%Y-%m-%dT%H:%M:%S+0000")
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, env=env)


def commit(root: Path, msg: str = "c", when: dt.datetime | None = None) -> None:
    git(root, "add", "-A")
    git(root, "commit", "-q", "--allow-empty", "-m", msg, when=when)


def hub(tmp: Path, registry: list | None = None) -> Path:
    h = tmp / "hub"
    write(h, "_data/fleet.yml", yaml.safe_dump({"issue_pipeline": {"labels": {"types": list(c.FLEET_TYPES_FALLBACK)}}}))
    write(h, "_data/projects.yml", yaml.safe_dump(registry or []))
    return h


def repo(tmp: Path, files: dict[str, str] | None = None, name: str = "repo", git_init: bool = True) -> Path:
    r = tmp / name
    r.mkdir(parents=True, exist_ok=True)
    for rel, text in (files or {}).items():
        write(r, rel, text)
    if git_init:
        git(r, "init", "-q", "-b", "main")
        commit(r)
    return r


def run(rid: str, path: Path, h: Path, kinds=("app",)):
    return c.CHECKS[rid](c.Repo(path, h), list(kinds))


def test_rows_inert_without_spec():
    specs = c.load_specs(HUB)
    assert not [q for q in specs.get("requirements", []) if q["id"].startswith("UPS-WORK-")], "WORK rows landed: retire this test"
    with tempfile.TemporaryDirectory() as d:
        r = repo(Path(d), {"README.md": "# r\n"})
        res = c.run_checks(c.Repo(r, HUB), ["app"], "active", specs)
        ids = {x["id"] for x in res["failing"]} | {x["id"] for x in res["unverified"]}
        assert not [i for i in ids if i.startswith("UPS-WORK-")], ids


def test_unverified_is_not_counted():
    specs = {"requirements": [{"id": "UPS-WORK-03", "level": "MUST", "applies": ["all"], "area": "WORK"},
                              {"id": "UPS-WORK-10", "level": "MUST", "applies": ["all"], "area": "WORK"}]}
    with tempfile.TemporaryDirectory() as d:
        h = hub(Path(d))
        r = repo(Path(d), {".github/workflows/ci.yml": "jobs:\n  ci:\n    uses: bamr87/bamr87/.github/workflows/standard-ci.yml@main\n"})
        res = c.run_checks(c.Repo(r, h), ["app"], "active", specs)
        assert res["checked"] == 1 and res["must_failed"] == 1, res
        assert [u["id"] for u in res["unverified"]] == ["UPS-WORK-03"], res["unverified"]
        assert "? UPS-WORK-03" in c.render_text(res, "repo")


def test_work01_sdlc_profile():
    with tempfile.TemporaryDirectory() as d:
        t = Path(d)
        h = hub(t, [{"name": "reg", "repo_url": "https://github.com/bamr87/reg", "sdlc": SDLC}])
        assert run("UPS-WORK-01", repo(t, name="none"), h)[0] is False
        assert run("UPS-WORK-01", repo(t, {c.SDLC_FILE: yaml.safe_dump(SDLC)}, name="ok"), h) == (True, c.SDLC_FILE)
        partial = {k: v for k, v in SDLC.items() if k != "backlog"}
        ok, msg = run("UPS-WORK-01", repo(t, {c.SDLC_FILE: yaml.safe_dump(partial)}, name="partial"), h)
        assert ok is False and "backlog.mode" in msg, msg
        bad = dict(SDLC, backlog={"mode": "jira"})
        assert run("UPS-WORK-01", repo(t, {c.SDLC_FILE: yaml.safe_dump(bad)}, name="bad"), h)[0] is False
        reg = repo(t, name="reg")
        git(reg, "remote", "add", "origin", "https://github.com/bamr87/reg.git")
        ok, msg = run("UPS-WORK-01", reg, h)
        assert ok is True and "registry" in msg, msg


def test_work02_backlog_of_record():
    with tempfile.TemporaryDirectory() as d:
        t, h = Path(d), hub(Path(d))
        assert run("UPS-WORK-02", repo(t, {c.SDLC_FILE: yaml.safe_dump(SDLC)}, name="issues"), h)[0] is None
        fmode = dict(SDLC, backlog={"mode": "file", "file": "BACKLOG.md"})
        lint = "jobs:\n  spec-gate:\n    steps:\n      - run: python3 tools/backlog_lint.py\n"
        ok, msg = run("UPS-WORK-02", repo(t, {c.SDLC_FILE: yaml.safe_dump(fmode), "BACKLOG.md": "## Open\n",
                                              ".github/workflows/ci.yml": lint}, name="linted"), h)
        assert ok is True and "ci.yml" in msg, msg
        assert run("UPS-WORK-02", repo(t, {c.SDLC_FILE: yaml.safe_dump(fmode), "BACKLOG.md": "## Open\n"}, name="unlinted"), h)[0] is False
        assert run("UPS-WORK-02", repo(t, {c.SDLC_FILE: yaml.safe_dump(fmode)}, name="nofile"), h)[0] is False


def test_work03_definition_of_done():
    with tempfile.TemporaryDirectory() as d:
        t, h = Path(d), hub(Path(d))
        assert run("UPS-WORK-03", repo(t, name="inherits"), h)[0] is None
        assert run("UPS-WORK-03", repo(t, {".github/pull_request_template.md": DOD}, name="full"), h)[0] is True
        old = "## Checklist\n- [ ] Tests pass\n- [ ] Docs updated\n- [ ] CHANGELOG\n- [ ] Conventional title\n"
        ok, msg = run("UPS-WORK-03", repo(t, {".github/PULL_REQUEST_TEMPLATE.md": old}, name="short"), h)
        assert ok is False and "ADR" in msg and "backlog" in msg and "secrets" in msg, msg
        assert run("UPS-WORK-03", repo(t, {".github/pull_request_template.md": "## Summary\n"}, name="nobox"), h)[0] is False


def test_work04_adr_log():
    with tempfile.TemporaryDirectory() as d:
        t, h = Path(d), hub(Path(d))
        assert run("UPS-WORK-04", repo(t, {"docs/adr/0000-template.md": "x"}, name="tpl"), h)[0] is False
        assert run("UPS-WORK-04", repo(t, {"docs/adr/0001-record.md": "x"}, name="noidx"), h)[0] is False
        assert run("UPS-WORK-04", repo(t, {"docs/adr/0001-record.md": "x", "docs/adr/README.md": "x"}, name="ok"), h)[0] is True
        lineage = dict(SDLC, adr_path="lineage/decisions")
        ok, msg = run("UPS-WORK-04", repo(t, {c.SDLC_FILE: yaml.safe_dump(lineage), "lineage/decisions/ADR-0001-x.md": "x",
                                              "lineage/decisions/README.md": "x"}, name="lineage"), h)
        assert ok is True and "lineage/decisions" in msg, msg


def test_work05_changelog_hygiene():
    with tempfile.TemporaryDirectory() as d:
        t, h = Path(d), hub(Path(d))
        ok, msg = run("UPS-WORK-05", repo(t, name="none"), h)
        assert ok is False and "no CHANGELOG.md" in msg, msg
        dup = "# Changelog\n\n## [Unreleased]\n\n## [Unreleased] - 2026-03-08\n\n## [1.0.0] - 2026-01-01\n"
        assert run("UPS-WORK-05", repo(t, {"CHANGELOG.md": dup}, name="dup"), h)[0] is False
        cl = "# Changelog\n\n## [Unreleased]\n\n## [1.2.0] - 2026-01-01\n\n## [1.1.0] - 2025-12-01\n"
        notag = repo(t, {"CHANGELOG.md": cl}, name="notag")
        assert run("UPS-WORK-05", notag, h)[0] is True
        git(notag, "tag", "v1.1.0")
        ok, msg = run("UPS-WORK-05", notag, h)
        assert ok is False and "v1.1.0" in msg, msg
        git(notag, "tag", "v1.2.0")
        assert run("UPS-WORK-05", notag, h)[0] is True
        # release-please writes no [Unreleased] heading at all: allowed (at most one)
        assert run("UPS-WORK-05", repo(t, {"CHANGELOG.md": "## [0.1.0] - 2026-01-01\n"}, name="rp"), h)[0] is True
        # D5: content repos are held to the same rule — required, and hygienic
        assert run("UPS-WORK-05", repo(t, name="content-none"), h, kinds=("content",))[0] is False
        assert run("UPS-WORK-05", repo(t, {"CHANGELOG.md": dup}, name="content-dup"), h, kinds=("content",))[0] is False
        assert run("UPS-WORK-05", repo(t, {"CHANGELOG.md": cl}, name="content-ok"), h, kinds=("content",))[0] is True


def test_work06_features_hygiene():
    with tempfile.TemporaryDirectory() as d:
        t, h = Path(d), hub(Path(d))
        clean = "# features/features.yml\n# kit: verify v0.1.0\nschema: features/v1\nfeatures: []\n"
        assert run("UPS-WORK-06", repo(t, {"features/features.yml": clean}, name="clean"), h)[0] is True
        hdr = "# Feature registry\n# Version: 1.29.0\nfeatures: []\n"
        ok, msg = run("UPS-WORK-06", repo(t, {"features/features.yml": hdr, "_data/features.yml": hdr}, name="zer0"), h)
        assert ok is False and "duplicate" in msg and "version header" in msg, msg


LAW_CI = """
jobs:
  changes:
    runs-on: ubuntu-latest
    steps: [{run: echo}]
  spec-gate:
    needs: changes
    steps:
      - run: python scripts/spec_validator.py --strict
      - run: python scripts/backlog_lint.py
  tests:
    needs: [spec-gate, changes]
    steps: [{run: pytest}]
  build:
    needs: tests
    steps: [{run: make}]
"""
GITORIO_CI = """
jobs:
  build:
    steps: [{run: npm test}]
  spec-gate:
    steps:
      - run: python3 tools/spec_validator.py
      - run: python3 tools/backlog_lint.py
"""


def test_work07_spec_gate():
    with tempfile.TemporaryDirectory() as d:
        t, h = Path(d), hub(Path(d))
        assert run("UPS-WORK-07", repo(t, name="off"), h)[0] is True
        sd = yaml.safe_dump(dict(SDLC, modules={"spec_driven": True}))
        base = {c.SDLC_FILE: sd, "BACKLOG.md": "## Open\n", "specs/001-a/spec.md": "- **Status**: shipped\n"}
        ok, msg = run("UPS-WORK-07", repo(t, {**base, ".github/workflows/ci.yml": LAW_CI}, name="law"), h)
        assert ok is True and "spec-gate" in msg and "parity unchecked" in msg, msg
        ok, msg = run("UPS-WORK-07", repo(t, {**base, ".github/workflows/ci.yml": GITORIO_CI}, name="gitorio"), h)
        assert ok is False and "build" in msg, msg
        assert run("UPS-WORK-07", repo(t, {c.SDLC_FILE: sd}, name="bare"), h)[0] is False
        # kit parity once the hub publishes the kit
        write(h, "templates/sdlc/spec-driven/tools/spec_validator.py", "canonical\n")
        drift = repo(t, {**base, ".github/workflows/ci.yml": LAW_CI, "scripts/spec_validator.py": "forked\n"}, name="drift")
        ok, msg = run("UPS-WORK-07", drift, h)
        assert ok is False and "differs from the hub kit" in msg, msg


def test_work08_freshness():
    with tempfile.TemporaryDirectory() as d:
        t, h = Path(d), hub(Path(d))
        old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=90)
        r = repo(t, git_init=False)
        git(r, "init", "-q", "-b", "main")
        write(r, "specs/047-x/spec.md", "- **Status**: in-progress\n")
        write(r, "BACKLOG.md", "## Open\n")
        commit(r, "old", when=old)
        write(r, "src/app.py", "print(1)\n")
        commit(r, "new")
        ok, msg = run("UPS-WORK-08", r, h)
        assert ok is False and "047-x" in msg and "BACKLOG.md" in msg, msg
        write(r, "specs/047-x/spec.md", "- **Status**: shipped\n")
        write(r, "BACKLOG.md", "## Open\n- item\n")
        commit(r, "fresh")
        assert run("UPS-WORK-08", r, h)[0] is True
        assert run("UPS-WORK-08", repo(t, name="nogit", git_init=False), h)[0] is None


def test_work09_form_labels():
    with tempfile.TemporaryDirectory() as d:
        t, h = Path(d), hub(Path(d))
        assert run("UPS-WORK-09", repo(t, name="inherits"), h)[0] is None
        good = {".github/ISSUE_TEMPLATE/bug_report.yml": "labels: [bug]\n", ".github/ISSUE_TEMPLATE/feature_request.yml": "labels: [\"feature\"]\n",
                ".github/ISSUE_TEMPLATE/page_feedback.yml": "labels: [page-feedback]\n", ".github/ISSUE_TEMPLATE/config.yml": "blank_issues_enabled: false\n"}
        assert run("UPS-WORK-09", repo(t, good, name="good"), h)[0] is True
        ok, msg = run("UPS-WORK-09", repo(t, {**good, ".github/ISSUE_TEMPLATE/feature_request.yml": "labels: [\"enhancement\"]\n"}, name="dup"), h)
        assert ok is False and "enhancement" in msg, msg
        md = {".github/ISSUE_TEMPLATE/feature_request.md": "---\nname: Feature\nlabels: priority:P2\n---\nbody\n"}
        ok, msg = run("UPS-WORK-09", repo(t, md, name="md"), h)
        assert ok is False and "priority:P2" in msg, msg
        ok, msg = run("UPS-WORK-09", repo(t, {".github/ISSUE_TEMPLATE/task.yml": "labels: [triage]\n"}, name="untyped"), h)
        assert ok is False and "no fleet type" in msg, msg


def test_work10_hub_refs_pinned():
    with tempfile.TemporaryDirectory() as d:
        t, h = Path(d), hub(Path(d))
        pinned = """jobs:
  ci:
    # uses: bamr87/bamr87/.github/workflows/standard-ci.yml@main   (comment: ignored)
    uses: bamr87/bamr87/.github/workflows/standard-ci.yml@v1
  conf:
    uses: bamr87/bamr87/.github/workflows/fleet-conformance.yml@v1.0.0
  rel:
    uses: bamr87/.github/.github/workflows/release-please.yml@0123456789abcdef0123456789abcdef01234567
  local:
    uses: ./.github/workflows/local.yml
  ext:
    steps:
      - uses: actions/checkout@main
"""
        assert run("UPS-WORK-10", repo(t, {".github/workflows/ci.yml": pinned}, name="pinned"), h)[0] is True
        floating = "jobs:\n  ci:\n    uses: bamr87/bamr87/.github/workflows/standard-ci.yml@main\n  ai:\n    steps:\n      - uses: 'bamr87/bamr87/.github/actions/claude-auth@main'\n"
        ok, msg = run("UPS-WORK-10", repo(t, {".github/workflows/ci.yml": floating}, name="floating"), h)
        assert ok is False and "standard-ci.yml@main" in msg and "claude-auth@main" in msg, msg


CONVENTIONS = "## Conventions\n\nBacklog of record: GitHub Issues. Definition of Done: the PR template. ADRs: docs/adr/.\n\n## Fleet context\n"
POINTER = "# CLAUDE.md\n\nThe canonical guide is [AGENTS.md](AGENTS.md). Spec-driven commands live in .claude/commands/.\n"


def test_work12_agents_canonical():
    with tempfile.TemporaryDirectory() as d:
        t, h = Path(d), hub(Path(d))
        assert run("UPS-WORK-12", repo(t, {"AGENTS.md": "# AGENTS.md\n\n" + CONVENTIONS, "CLAUDE.md": POINTER,
                                           ".claude/commands/specify.md": "x"}, name="ok"), h)[0] is True
        # CLAUDE.md-canonical (the pre-D4 shape) fails: no AGENTS.md
        ok, msg = run("UPS-WORK-12", repo(t, {"CLAUDE.md": "# CLAUDE.md\n\n" + CONVENTIONS}, name="claude-only"), h)
        assert ok is False and "no AGENTS.md" in msg, msg
        # CLAUDE.md missing, or not pointing at AGENTS.md, or duplicating the conventions
        ok, msg = run("UPS-WORK-12", repo(t, {"AGENTS.md": "# A\n\n" + CONVENTIONS}, name="nopointer"), h)
        assert ok is False and "no CLAUDE.md pointer" in msg, msg
        ok, msg = run("UPS-WORK-12", repo(t, {"AGENTS.md": "# A\n\n" + CONVENTIONS, "CLAUDE.md": "# CLAUDE.md\n\nUse ruff.\n"}, name="stray"), h)
        assert ok is False and "does not point to AGENTS.md" in msg, msg
        ok, msg = run("UPS-WORK-12", repo(t, {"AGENTS.md": "# A\n\n" + CONVENTIONS, "CLAUDE.md": POINTER + "\n" + CONVENTIONS}, name="dup"), h)
        assert ok is False and "its own `## Conventions`" in msg, msg
        # AGENTS.md conventions must name the loop
        thin = "# A\n\n## Conventions\n\nUse ruff.\n\n## Backlog\n\nIssues.\n"
        ok, msg = run("UPS-WORK-12", repo(t, {"AGENTS.md": thin, "CLAUDE.md": POINTER}, name="thin"), h)
        assert ok is False and "backlog" in msg and "ADR" in msg, msg


def test_cli_check_runs():
    with tempfile.TemporaryDirectory() as d:
        r = repo(Path(d), {"README.md": "# r\n"})
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            assert c.main(["check", str(r), "--hub", str(HUB), "--kinds", "content"]) == 0
            try:
                c.main(["check", str(r), "--hub", str(HUB), "--enable-pending", "D4"])
            except SystemExit as e:
                assert e.code == 2  # the pending-decision switch is gone: D4/D5 are settled
            else:
                raise AssertionError("--enable-pending still accepted")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"ok   {t.__name__}")
        except AssertionError as e:  # noqa: PERF203
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERR  {t.__name__}: {type(e).__name__}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)
