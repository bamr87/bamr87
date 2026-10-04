#!/usr/bin/env python3
"""
Fixture tests for the contract-keyed rows in tools/conformance.py: UPS-WORK-01..13
(planning & delivery), UPS-AGENT-07/08/09 (decision D4: AGENTS.md canonical,
CLAUDE.md a pointer, the kit stamp) and UPS-REPO-21 (decision D5: release-please
CHANGELOG in every repo), plus the retired-row and warning-severity plumbing.

The checker reads its paths, keys and regexes from the hub's
specs/WORK.contract.yml, so these tests build a throwaway hub from the real
files: the contract and specs.yml (bamr87/bamr87#323), the sdlc kit's schema and
templates (#324), the spec-driven kit tools (#325) and the community kit's PR
template (#319). Each comes from this checkout when it has it, otherwise from
the PR branch via `git show origin/<branch>:<path>`; a test whose inputs are in
neither place is reported as `skip`, never as a pass.

No network, no pytest. Needs PyYAML and git:

    python3 tools/test_conformance_work.py
"""
from __future__ import annotations

import contextlib
import datetime as dt
import io
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import conformance as c  # noqa: E402

HUB = Path(__file__).resolve().parent.parent
# Where each dependency lives until its PR merges.
SOURCES = {
    "specs/WORK.contract.yml": "origin/fix/work-contract-gaps",
    "_data/specs.yml": "origin/fix/work-contract-gaps",
    "templates/sdlc/sdlc.schema.json": "origin/feat/sdlc-kit",
    "templates/sdlc/sdlc.yml": "origin/feat/sdlc-kit",
    "templates/sdlc/AGENTS.template.md": "origin/feat/sdlc-kit",
    "templates/sdlc/CLAUDE.template.md": "origin/feat/sdlc-kit",
    "templates/community/.github/pull_request_template.md": "origin/feat/community-kit",
    **{f"templates/spec-driven/tools/{t}": "origin/feat/spec-driven-kit"
       for t in ("spec_validator.py", "backlog_lint.py", "next_backlog_id.py", "pick_backlog_item.py")},
}


class Skip(Exception):
    pass


# Text that only the revision these tests target has (bamr87/bamr87#327).
SENTINEL = {"specs/WORK.contract.yml": "backlog_lint_keys", "_data/specs.yml": "never in raw workflow text"}


def dep(rel: str) -> str:
    """A hub file's text: this checkout if it has the merged version, else the PR branch."""
    p = HUB / rel
    if p.is_file() and SENTINEL.get(rel, "") in p.read_text(encoding="utf-8"):
        return p.read_text(encoding="utf-8")
    out = subprocess.run(["git", "-C", str(HUB), "show", f"{SOURCES[rel]}:{rel}"], capture_output=True, text=True)
    if out.returncode:
        raise Skip(f"{rel} is in neither this checkout nor {SOURCES[rel]}")
    return out.stdout


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


def hub(tmp: Path, registry: list | None = None, with_: tuple[str, ...] = tuple(SOURCES)) -> Path:
    """A throwaway hub: the contract plus whichever kit files `with_` names."""
    h = tmp / "hub"
    write(h, "_data/fleet.yml", yaml.safe_dump({"issue_pipeline": {"labels": {"types": list(c.FLEET_TYPES_FALLBACK)}}}))
    write(h, "_data/projects.yml", yaml.safe_dump(registry or []))
    for rel in with_:
        write(h, rel, dep(rel))
    c._CONTRACTS.pop(h.resolve(), None)
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


def sdlc(**over) -> str:
    base = {"schema": "sdlc/v1", "type": "app", "tier": "active", "backlog": {"mode": "issues"},
            "modules": {"spec_driven": False, "adr": True}, "adr_path": "docs/adr", "release": {"type": "node"}}
    base.update(over)
    return yaml.safe_dump(base, sort_keys=False)


AGENTS = """<!-- kit: sdlc v0.1.0 -->
# repo

## What this repo is

A thing.

## Stack & commands

```bash
make test
```

## Layout

see SCHEMA.md

## Conventions

- **Backlog of record:** GitHub Issues.
- **Definition of Done:** the checklist in `.github/pull_request_template.md`.
- **Decisions:** ADRs in `docs/adr/NNNN-slug.md`.

## Fleet context

Member of the bamr87 fleet.

## Standard deviations

none
"""
CLAUDE = "<!-- kit: sdlc v0.1.0 · pointer only -->\n# repo\n\nSee [AGENTS.md](AGENTS.md).\n\n@AGENTS.md\n"


# --- contract keying ------------------------------------------------------- #
def test_inline_rule_regexes_are_verbatim_in_the_contract():
    data = yaml.safe_load(dep("specs/WORK.contract.yml"))
    rules = {**data["rules"], **data["related"]}
    for key, rx in c.RULE_RX.items():
        rid = key.split("/")[0]
        assert rx in " ".join(str(rules[rid]["pass"]).split()), f"{key}: {rx!r} not in contract {rid}.pass"


def test_every_definition_the_checker_reads_exists_in_the_contract():
    """A renamed contract key (fleet_uses_re -> fleet_uses_value_re) must fail
    here, not as a `checker error` in every repo."""
    defs = yaml.safe_load(dep("specs/WORK.contract.yml"))["definitions"]
    src = (Path(c.__file__)).read_text(encoding="utf-8")
    used = set(re.findall(r'\b(?:d|defs)\[\"(\w+)\"\]', src)) | set(re.findall(r'(?:_defs\(r\)|\bd|\bdefs)\.get\(\"(\w+)\"', src))
    assert used, "no definition reads found"
    missing = sorted(used - set(defs))
    assert not missing, f"conformance.py reads definitions the contract lacks: {missing}"
    stamp = set(re.findall(r'\bks\[\"(\w+)\"\]', src)) | set(re.findall(r'\bks\.get\(\"(\w+)\"', src))
    assert stamp <= set(defs["kit_stamp"]), stamp - set(defs["kit_stamp"])
    assert set(defs["uses_keys"]) == {"workflow", "action"}, defs["uses_keys"]


def test_rows_read_definitions_from_the_contract():
    """Change a definition in the contract and the check follows it."""
    with tempfile.TemporaryDirectory() as d:
        t = Path(d)
        h = hub(t, with_=("specs/WORK.contract.yml",))
        caller = {".github/workflows/ci.yml": "jobs:\n  ci:\n    uses: bamr87/bamr87/.github/workflows/standard-ci.yml@v1\n"}
        r = repo(t, caller)
        assert run("UPS-WORK-10", r, h)[0] is True
        cfile = h / "specs/WORK.contract.yml"
        cfile.write_text(cfile.read_text().replace(r"pinned_ref_re: '^(v\d+|", r"pinned_ref_re: '^(", 1))
        c._CONTRACTS.clear()
        assert run("UPS-WORK-10", r, h)[0] is False
        c._CONTRACTS.clear()


def test_no_contract_means_unverified_not_pass_or_fail():
    with tempfile.TemporaryDirectory() as d:
        t = Path(d)
        h = hub(t, with_=())
        r = repo(t, {"README.md": "# r\n"})
        for rid in ("UPS-WORK-01", "UPS-WORK-10", "UPS-WORK-12", "UPS-AGENT-07", "UPS-AGENT-08", "UPS-AGENT-09", "UPS-REPO-21"):
            ok, msg = run(rid, r, h)
            assert ok is None and "WORK.contract.yml" in msg, (rid, ok, msg)


# --- retired rows and warnings --------------------------------------------- #
RETIRED = {"UPS-AGENT-01", "UPS-AGENT-02", "UPS-AGENT-03", "UPS-REPO-13"}


def test_retired_rows_are_not_checked_and_nothing_errors():
    specs = yaml.safe_load(dep("_data/specs.yml"))
    assert RETIRED <= {q["id"] for q in specs["requirements"] if q["level"] == "retired"}
    assert not RETIRED & set(c.CHECKS), "retired rows still have checks"
    with tempfile.TemporaryDirectory() as d:
        t = Path(d)
        h = hub(t)
        for files in ({"README.md": "# r\n"}, {"CLAUDE.md": "# old\n## Stack\n"}, {}):
            res = c.run_checks(c.Repo(repo(t, files, name=f"r{len(files)}{id(files)}"), h), ["app"], "active", specs)
            seen = {x["id"] for k in ("failing", "unverified", "warnings") for x in res[k]}
            assert not seen & RETIRED, seen & RETIRED
            errs = [x for k in ("failing", "unverified", "warnings") for x in res[k] if "checker error" in x["detail"]]
            assert not errs, errs
        # a retired row is skipped even when something registers a check for it
        c.CHECKS["UPS-REPO-13"] = lambda r, k: (False, "should never run")
        try:
            res = c.run_checks(c.Repo(repo(t, name="x"), h), ["app"], "active",
                               {"requirements": [{"id": "UPS-REPO-13", "level": "retired", "applies": ["all"], "area": "REPO"}]})
            assert res["checked"] == 0 and not res["failing"], res
        finally:
            del c.CHECKS["UPS-REPO-13"]


ROLLOUT = {"UPS-WORK-01", "UPS-WORK-07", "UPS-WORK-12", "UPS-AGENT-07", "UPS-AGENT-08", "UPS-AGENT-09", "UPS-REPO-21"}


def test_rollout_warn_comes_from_the_contract_and_flips_by_deleting_the_marker():
    specs = {"requirements": [{"id": "UPS-AGENT-07", "level": "MUST", "applies": ["all"], "area": "AGENT"},
                              {"id": "UPS-WORK-10", "level": "MUST", "applies": ["all"], "area": "WORK"}]}
    floating = {".github/workflows/ci.yml": "jobs:\n  ci:\n    uses: bamr87/bamr87/.github/workflows/standard-ci.yml@main\n"}
    with tempfile.TemporaryDirectory() as d:
        t = Path(d)
        h = hub(t)
        r = repo(t, {"CLAUDE.md": "# legacy\n", **floating})
        assert set(c.warn_only(c.Repo(r, h))) == ROLLOUT
        res = c.run_checks(c.Repo(r, h), ["app"], "active", specs)
        assert res["must_failed"] == 1 and [f["id"] for f in res["failing"]] == ["UPS-WORK-10"], res
        assert [w["id"] for w in res["warnings"]] == ["UPS-AGENT-07"], res["warnings"]
        assert "rollout: warn" in res["warnings"][0]["why_warn"]
        assert "! UPS-AGENT-07" in c.render_text(res, "r")
        # Fleet Ops deletes the marker in the contract: the rule gates, nothing else changes
        cf = h / "specs/WORK.contract.yml"
        text = cf.read_text()
        i = text.index("  UPS-AGENT-07:\n")
        cf.write_text(text[:i] + text[i:].replace("    rollout: warn\n", "", 1))
        c._CONTRACTS.clear()
        assert "UPS-AGENT-07" not in c.warn_only(c.Repo(r, h))
        res = c.run_checks(c.Repo(r, h), ["app"], "active", specs)
        assert res["must_failed"] == 2 and not res["warnings"], res
        c._CONTRACTS.clear()


def test_a_rules_own_warn_clause_is_a_warning_result():
    specs = {"requirements": [{"id": "UPS-WORK-04", "level": "MUST", "applies": ["app"], "area": "WORK"}]}
    with tempfile.TemporaryDirectory() as d:
        t = Path(d)
        h = hub(t)
        r = repo(t, {"docs/adr/ADR-0001-x.md": "x", "docs/adr/README.md": "x"})
        res = c.run_checks(c.Repo(r, h), ["app"], "active", specs)
        assert res["must_failed"] == 0 and [w["id"] for w in res["warnings"]] == ["UPS-WORK-04"], res
        assert "deprecated" in res["warnings"][0]["why_warn"]


def test_gate_ignores_warnings():
    with tempfile.TemporaryDirectory() as d:
        t = Path(d)
        h = hub(t)
        write(h, "_data/specs.yml", yaml.safe_dump({"requirements": [
            {"id": "UPS-AGENT-07", "level": "MUST", "applies": ["all"], "area": "AGENT"},
            {"id": "UPS-AGENT-08", "level": "MUST", "applies": ["all"], "area": "AGENT"}]}))
        r = repo(t, {"CLAUDE.md": "# legacy\n"})
        with contextlib.redirect_stdout(io.StringIO()):
            assert c.main(["check", str(r), "--hub", str(h), "--kinds", "app", "--gate"]) == 0


# --- UPS-WORK-01 ----------------------------------------------------------- #
def test_work01_profile_validates_against_the_kit_schema():
    with tempfile.TemporaryDirectory() as d:
        t = Path(d)
        h = hub(t, [{"name": "reg", "repo_url": "https://github.com/bamr87/reg",
                     "sdlc": {"schema": "sdlc/v1", "type": "site", "tier": "active", "backlog": {"mode": "issues"},
                              "modules": ["adr", "features"], "release": {"type": "simple"}}}])
        assert run("UPS-WORK-01", repo(t, name="none"), h)[0] is False
        kit = dep("templates/sdlc/sdlc.yml")
        ok, msg = run("UPS-WORK-01", repo(t, {".github/sdlc.yml": kit}, name="kit"), h)
        assert ok is True and "type app" in msg, msg
        # `kind:` (the pre-contract key) is an unknown key and `type` is missing
        old = kit.replace("\ntype: app", "\nkind: app")
        ok, msg = run("UPS-WORK-01", repo(t, {".github/sdlc.yml": old}, name="kind"), h)
        assert ok is False and "/kind: unknown key" in msg and "missing required `type`" in msg, msg
        ok, msg = run("UPS-WORK-01", repo(t, {".github/sdlc.yml": sdlc(backlog={"mode": "file"})}, name="nofile"), h)
        assert ok is False and "missing required `file`" in msg, msg
        ok, msg = run("UPS-WORK-01", repo(t, {".github/sdlc.yml": sdlc(modules={"specs": True})}, name="badmod"), h)
        assert ok is False and "/modules/specs: unknown key" in msg, msg
        prof = yaml.safe_load(sdlc())
        del prof["release"]
        ok, msg = run("UPS-WORK-01", repo(t, {".github/sdlc.yml": yaml.safe_dump(prof)}, name="norel"), h)
        assert ok is False and "`release`" in msg, msg
        prof["type"] = "fork"
        assert run("UPS-WORK-01", repo(t, {".github/sdlc.yml": yaml.safe_dump(prof)}, name="fork"), h)[0] is True
        # an unquoted YAML date (`until: 2027-01-01`, as in the kit's example) is accepted
        dev = sdlc() + "deviations:\n  - { id: UPS-WORK-11, reason: later, until: 2027-01-01 }\n"
        assert run("UPS-WORK-01", repo(t, {".github/sdlc.yml": dev}, name="dev"), h)[0] is True
        assert run("UPS-WORK-01", repo(t, {".github/sdlc.yml": "type: [\n"}, name="yamlerr"), h)[0] is False
        # the registry block (modules as a list is allowed there) when there is no file
        reg = repo(t, name="reg")
        git(reg, "remote", "add", "origin", "https://github.com/bamr87/reg.git")
        ok, msg = run("UPS-WORK-01", reg, h)
        assert ok is True and "registry" in msg, msg
        # no schema in the hub checkout: unverified, not a pass
        h2 = hub(t / "h2", with_=("specs/WORK.contract.yml",))
        assert run("UPS-WORK-01", repo(t, {".github/sdlc.yml": kit}, name="noschema"), h2)[0] is None


def test_schema_subset_covers_the_kit_schema():
    import json
    schema = json.loads(dep("templates/sdlc/sdlc.schema.json"))
    used: set[str] = set()

    def walk(s):
        if isinstance(s, dict):
            used.update(k for k in s if k not in ("properties",))
            for k, v in s.items():
                if k == "properties":
                    for sub in v.values():
                        walk(sub)
                elif isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(s, list):
            for x in s:
                walk(x)
    walk(schema)
    assert used <= c.SCHEMA_KEYWORDS | {"properties"}, used - c.SCHEMA_KEYWORDS


def test_profile_kinds_follow_type():
    with tempfile.TemporaryDirectory() as d:
        t = Path(d)
        h = hub(t, with_=("specs/WORK.contract.yml",))
        for typ, want in (("docs", ["content"]), ("control-plane", ["site"]), ("library", ["lib"])):
            r = repo(t, {".github/sdlc.yml": sdlc(type=typ, kinds=None)}, name=typ)
            p = yaml.safe_load((r / ".github/sdlc.yml").read_text())
            p.pop("kinds")
            (r / ".github/sdlc.yml").write_text(yaml.safe_dump(p))
            assert c.profile_kinds(c.Repo(r, h)) == want, typ
        assert c.profile_kinds(c.Repo(repo(t, {".github/sdlc.yml": sdlc(kinds=["app", "api"])}, name="k"), h)) == ["app", "api"]
        assert c.profile_kinds(c.Repo(repo(t, name="none"), h)) is None


# --- UPS-WORK-02/03/04/05/06 ----------------------------------------------- #
def test_work02_backlog_of_record():
    with tempfile.TemporaryDirectory() as d:
        t = Path(d)
        h = hub(t)
        assert run("UPS-WORK-02", repo(t, {".github/sdlc.yml": sdlc()}, name="issues"), h)[0] is None
        fmode = sdlc(backlog={"mode": "file", "file": "BACKLOG.md"})
        for i, step in enumerate(("python3 tools/backlog_lint.py", "npm run validate-backlog")):
            ok, msg = run("UPS-WORK-02", repo(t, {".github/sdlc.yml": fmode, "BACKLOG.md": "## Open\n",
                                                  ".github/workflows/ci.yml": f"jobs:\n  g:\n    steps:\n      - run: {step}\n"}, name=f"l{i}"), h)
            assert ok is True and "ci.yml" in msg, msg
        sync = {".github/workflows/sync.yml": "jobs:\n  s:\n    steps:\n      - run: ruby sync-backlog.rb\n"}
        assert run("UPS-WORK-02", repo(t, {".github/sdlc.yml": fmode, "BACKLOG.md": "x", **sync}, name="sync"), h)[0] is False
        assert run("UPS-WORK-02", repo(t, {".github/sdlc.yml": fmode}, name="nofile"), h)[0] is False
        # only parsed values at backlog_lint_keys count: never comments, `name:` or env text
        for i, wf in enumerate((
                "# TODO: add backlog_lint.py\njobs:\n  g:\n    steps:\n      - run: make test\n",
                "jobs:\n  g:\n    name: backlog-lint\n    steps:\n      - name: backlog lint\n        run: make test\n",
                "env:\n  STEP: python3 tools/backlog_lint.py\njobs:\n  g:\n    steps:\n      - run: echo $STEP\n",
                "jobs: [\n  run: python3 tools/backlog_lint.py\n")):
            ok, msg = run("UPS-WORK-02", repo(t, {".github/sdlc.yml": fmode, "BACKLOG.md": "x", ".github/workflows/ci.yml": wf}, name=f"raw{i}"), h)
            assert ok is False and "no CI lint" in msg, (i, msg)
        # a step `uses:`, a job-level `uses:` and a .yaml workflow all count
        for i, (fn, wf) in enumerate((
                ("ci.yml", "jobs:\n  g:\n    steps:\n      - uses: org/backlog-lint-action@v1\n"),
                ("ci.yml", "jobs:\n  g:\n    uses: org/repo/.github/workflows/validate-backlog.yml@v1\n"),
                ("lint.yaml", "jobs:\n  g:\n    steps:\n      - run: |\n          set -e\n          python3 tools/backlog_lint.py BACKLOG.md\n"))):
            ok, msg = run("UPS-WORK-02", repo(t, {".github/sdlc.yml": fmode, "BACKLOG.md": "x", f".github/workflows/{fn}": wf}, name=f"val{i}"), h)
            assert ok is True and fn in msg, (i, msg)
        # the lint regex is the contract's backlog_lint_value_re, not a copy
        assert "UPS-WORK-02" not in c.RULE_RX
        _set_def(h, "backlog_lint_value_re", "'never-matches-anything'")
        assert run("UPS-WORK-02", repo(t, {".github/sdlc.yml": fmode, "BACKLOG.md": "x", ".github/workflows/ci.yml":
                                           "jobs:\n  g:\n    steps:\n      - run: python3 tools/backlog_lint.py\n"}, name="redef"), h)[0] is False


def test_work03_dod_block_matches_the_reference():
    ref = dep("templates/community/.github/pull_request_template.md")
    with tempfile.TemporaryDirectory() as d:
        t = Path(d)
        h = hub(t)
        assert run("UPS-WORK-03", repo(t, name="inherits"), h)[0] is None
        ok, msg = run("UPS-WORK-03", repo(t, {".github/pull_request_template.md": ref}, name="kit"), h)
        assert ok is True and "v1" in msg, msg
        extra = ref.replace("<!-- fleet-dod:end -->", "<!-- fleet-dod:end -->\n- [ ] **E2E** passes")
        assert run("UPS-WORK-03", repo(t, {".github/PULL_REQUEST_TEMPLATE.md": extra}, name="extra"), h)[0] is True
        lines = ref.splitlines()
        boxes = [i for i, x in enumerate(lines) if x.startswith("- [ ] **")]
        dropped = "\n".join(x for i, x in enumerate(lines) if i != boxes[5])
        ok, msg = run("UPS-WORK-03", repo(t, {".github/pull_request_template.md": dropped}, name="drop"), h)
        assert ok is False and "missing: Decision recorded" in msg, msg
        swapped = list(lines)
        swapped[boxes[0]], swapped[boxes[1]] = swapped[boxes[1]], swapped[boxes[0]]
        ok, msg = run("UPS-WORK-03", repo(t, {".github/pull_request_template.md": "\n".join(swapped)}, name="swap"), h)
        assert ok is False and "order or wording" in msg, msg
        ok, msg = run("UPS-WORK-03", repo(t, {".github/pull_request_template.md": "## DoD\n- [ ] tests\n"}, name="nomark"), h)
        assert ok is False and "fleet-dod" in msg, msg
        ok, msg = run("UPS-WORK-03", repo(t, {".github/PULL_REQUEST_TEMPLATE/feature.md": ref}, name="dir"), h)
        assert ok is True, msg
        # dod_versions: with the hub kit at v2, v2 passes, v1 (previous) warns (boxes not compared), v0 and v3 fail
        write(h, "templates/community/.github/pull_request_template.md", ref.replace("fleet-dod:start v1", "fleet-dod:start v2"))
        v = {n: ref.replace("fleet-dod:start v1", f"fleet-dod:start v{n}") for n in (0, 2, 3)}
        assert run("UPS-WORK-03", repo(t, {".github/pull_request_template.md": v[2]}, name="v2"), h)[0] is True
        ok, msg = run("UPS-WORK-03", repo(t, {".github/pull_request_template.md": dropped}, name="v1"), h)
        assert ok == c.WARN and "previous version" in msg, msg
        for n in (0, 3):
            ok, msg = run("UPS-WORK-03", repo(t, {".github/pull_request_template.md": v[n]}, name=f"v{n}x"), h)
            assert ok is False and f"v{n}" in msg, msg
        h2 = hub(t / "h2", with_=("specs/WORK.contract.yml",))
        assert run("UPS-WORK-03", repo(t, {".github/pull_request_template.md": ref}, name="noref"), h2)[0] is None


def test_work04_adr_log():
    with tempfile.TemporaryDirectory() as d:
        t = Path(d)
        h = hub(t)
        for name, files in (("tpl", {"docs/adr/0000-template.md": "x", "docs/adr/ADR-0000-template.md": "x", "docs/adr/README.md": "x"}),
                            ("noidx", {"docs/adr/0001-record.md": "x"}), ("none", {})):
            assert run("UPS-WORK-04", repo(t, files, name=name), h)[0] is False, name
        assert run("UPS-WORK-04", repo(t, {"docs/adr/0001-record.md": "x", "docs/adr/README.md": "x"}, name="ok"), h)[0] is True
        # year-of-ai: the deprecated ADR- alias at a declared transition path warns and names the files
        yoa = {".github/sdlc.yml": sdlc(adr_path="lineage/decisions"), "lineage/decisions/ADR-0001-growth.md": "x",
               "lineage/decisions/README.md": "x"}
        ok, msg = run("UPS-WORK-04", repo(t, yoa, name="yoa"), h)
        assert ok == c.WARN and "ADR-0001-growth.md" in msg and "lineage/decisions" in msg, msg
        mixed = {"docs/adr/0001-a.md": "x", "docs/adr/ADR-0002-b.md": "x", "docs/adr/README.md": "x"}
        assert run("UPS-WORK-04", repo(t, mixed, name="mixed"), h)[0] == c.WARN
        assert run("UPS-WORK-04", repo(t, {"docs/adr/ADR-0001-x.md": "x"}, name="alias-noidx"), h)[0] is False
        assert c.CHECKS["UPS-WORK-13"] is c.CHECKS["UPS-WORK-04"]


def test_work05_changelog_hygiene():
    with tempfile.TemporaryDirectory() as d:
        t = Path(d)
        h = hub(t)
        ok, msg = run("UPS-WORK-05", repo(t, name="none"), h)
        assert ok is True and msg == "no CHANGELOG.md, see UPS-REPO-21", msg  # one root cause, one failing row
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
        assert run("UPS-WORK-05", repo(t, {"CHANGELOG.md": "## [0.1.0] - 2026-01-01\n"}, name="rp"), h)[0] is True


def test_work06_features_hygiene():
    with tempfile.TemporaryDirectory() as d:
        t = Path(d)
        h = hub(t)
        clean = "# features/features.yml\n# kit: verify v0.1.0\nschema: features/v1\nfeatures: []\n"
        assert run("UPS-WORK-06", repo(t, {"features/features.yml": clean}, name="clean"), h)[0] is True
        hdr = "# Feature registry\n# Version: 1.29.0\nfeatures: []\n"
        ok, msg = run("UPS-WORK-06", repo(t, {"features/features.yml": hdr, "_data/features.yml": hdr}, name="zer0"), h)
        assert ok is False and "duplicate" in msg and "version header" in msg, msg


# --- UPS-WORK-07 ----------------------------------------------------------- #
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


def test_work07_spec_gate_and_kit_parity():
    tools = {f"scripts/{n}": dep(f"templates/spec-driven/tools/{n}") for n in ("spec_validator.py", "backlog_lint.py")}
    with tempfile.TemporaryDirectory() as d:
        t = Path(d)
        h = hub(t)
        assert run("UPS-WORK-07", repo(t, name="off"), h)[0] is True
        sd = sdlc(modules={"spec_driven": True})
        base = {".github/sdlc.yml": sd, "BACKLOG.md": "## Open\n", "specs/001-a/spec.md": "- **Status**: shipped\n"}
        ok, msg = run("UPS-WORK-07", repo(t, {**base, ".github/workflows/ci.yml": LAW_CI, **tools}, name="law"), h)
        assert ok is True and "spec-gate" in msg, msg
        ok, msg = run("UPS-WORK-07", repo(t, {**base, ".github/workflows/ci.yml": GITORIO_CI, **tools}, name="gitorio"), h)
        assert ok is False and "build" in msg, msg
        assert run("UPS-WORK-07", repo(t, {".github/sdlc.yml": sd}, name="bare"), h)[0] is False
        drift = repo(t, {**base, ".github/workflows/ci.yml": LAW_CI, **tools, "scripts/spec_validator.py": "forked\n"}, name="drift")
        ok, msg = run("UPS-WORK-07", drift, h)
        assert ok is False and "scripts/spec_validator.py differs from the hub kit" in msg, msg
        # untracked copies are not the repo's files
        loose = repo(t, {**base, ".github/workflows/ci.yml": LAW_CI, **tools}, name="loose")
        write(loose, "tmp/backlog_lint.py", "scratch\n")
        assert run("UPS-WORK-07", loose, h)[0] is True
        h2 = hub(t / "h2", with_=("specs/WORK.contract.yml",))
        ok, msg = run("UPS-WORK-07", repo(t, {**base, ".github/workflows/ci.yml": LAW_CI}, name="nokit"), h2)
        assert ok is True and "parity unchecked" in msg, msg


def test_work08_freshness():
    with tempfile.TemporaryDirectory() as d:
        t = Path(d)
        h = hub(t)
        old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=90)
        r = repo(t, git_init=False)
        git(r, "init", "-q", "-b", "main")
        write(r, ".github/sdlc.yml", sdlc(backlog={"mode": "file", "file": "BACKLOG.md"}))
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


# --- UPS-WORK-09/10/11/12 -------------------------------------------------- #
def test_work09_form_labels_exactly_one_type():
    with tempfile.TemporaryDirectory() as d:
        t = Path(d)
        h = hub(t)
        assert run("UPS-WORK-09", repo(t, name="inherits"), h)[0] is None
        good = {".github/ISSUE_TEMPLATE/bug_report.yml": "labels: [bug]\n", ".github/ISSUE_TEMPLATE/feature_request.yml": "labels: [\"feature\", \"agent:queued\"]\n",
                ".github/ISSUE_TEMPLATE/page_feedback.yml": "labels: [page-feedback]\n", ".github/ISSUE_TEMPLATE/config.yml": "blank_issues_enabled: false\n"}
        assert run("UPS-WORK-09", repo(t, good, name="good"), h)[0] is True
        ok, msg = run("UPS-WORK-09", repo(t, {**good, ".github/ISSUE_TEMPLATE/feature_request.yml": "labels: [\"enhancement\"]\n"}, name="dup"), h)
        assert ok is False and "enhancement" in msg, msg
        ok, msg = run("UPS-WORK-09", repo(t, {".github/ISSUE_TEMPLATE/feature_request.md": "---\nname: F\nlabels: priority:P2\n---\n"}, name="md"), h)
        assert ok is False and "priority:P2" in msg, msg
        ok, msg = run("UPS-WORK-09", repo(t, {".github/ISSUE_TEMPLATE/task.yml": "labels: [bug, chore]\n"}, name="two"), h)
        assert ok is False and "2 fleet type labels" in msg, msg


def test_work10_pins_per_contract():
    with tempfile.TemporaryDirectory() as d:
        t = Path(d)
        h = hub(t)
        pinned = """jobs:
  ci:
    # uses: bamr87/bamr87/.github/workflows/standard-ci.yml@main   (comment: ignored)
    uses: bamr87/bamr87/.github/workflows/standard-ci.yml@v1
  conf:
    uses: bamr87/bamr87/.github/workflows/fleet-conformance.yml@v1.0.0
  rel:
    uses: bamr87/.github/.github/workflows/release-please.yml@0123456789abcdef0123456789abcdef01234567 # v1.0.0
  local:
    uses: ./.github/workflows/local.yml
  ext:
    steps:
      - uses: actions/checkout@main
      - run: |
          cat > caller.yml <<'EOF'
          uses: bamr87/bamr87/.github/workflows/standard-ci.yml@main
          EOF
        env:
          NOTE: "uses: bamr87/bamr87/.github/actions/claude-auth@main"
"""
        ok, msg = run("UPS-WORK-10", repo(t, {".github/workflows/ci.yml": pinned}, name="pinned"), h)
        assert ok is True, msg  # run: text, strings and comments are never inspected
        for ref in ("main", "v1.2", "1.2.3", "0123456", "release/v1"):
            files = {".github/workflows/ci.yml": f"jobs:\n  ci:\n    uses: bamr87/bamr87/.github/workflows/standard-ci.yml@{ref}\n"}
            ok, msg = run("UPS-WORK-10", repo(t, files, name=f"f-{ref.replace('/', '-')}"), h)
            assert ok is False and f"standard-ci.yml@{ref}" in msg, (ref, msg)
        nested = {".github/actions/ai/run/action.yml": "runs:\n  using: composite\n  steps:\n    - uses: 'bamr87/bamr87/.github/actions/claude-auth@main'\n",
                  ".github/workflows/x.yaml": "jobs:\n  a:\n    uses: bamr87/.github/.github/workflows/publish.yml@main\n"}
        ok, msg = run("UPS-WORK-10", repo(t, nested, name="nested"), h)
        assert ok is False and "claude-auth@main" in msg and "publish.yml@main" in msg, msg
        ok, msg = run("UPS-WORK-10", repo(t, {".github/workflows/bad.yml": "jobs: [\n"}, name="badyaml"), h)
        assert ok is False and "not valid YAML: .github/workflows/bad.yml" in msg, msg


def test_work11_planning_files():
    with tempfile.TemporaryDirectory() as d:
        t = Path(d)
        h = hub(t)
        assert run("UPS-WORK-11", repo(t, name="none"), h)[0] is True
        ok_txt = "# Roadmap\n\nThemes only. Work items: https://github.com/o/r/issues ([BL-20260101-01](BACKLOG.md)).\n"
        assert run("UPS-WORK-11", repo(t, {"ROADMAP.md": ok_txt}, name="ok"), h)[0] is True
        ok, msg = run("UPS-WORK-11", repo(t, {"TODO.md": "- [ ] ship it\n- [x] done\n/issues\n"}, name="tasks"), h)
        assert ok is False and "task-list" in msg, msg
        ok, msg = run("UPS-WORK-11", repo(t, {"docs/PRD.md": "Scope: T-101 and BL-20260101-02.\n/issues\n"}, name="ids"), h)
        assert ok is False and "T-101" in msg, msg
        ok, msg = run("UPS-WORK-11", repo(t, {"ROADMAP.md": "# Roadmap\n"}, name="nolink"), h)
        assert ok is False and "does not link" in msg, msg
        hubl = "See https://github.com/bamr87/bamr87/blob/main/_data/roadmap.yml\n"
        assert run("UPS-WORK-11", repo(t, {"ROADMAP.md": hubl}, name="hub"), h)[0] is True
        fmode = {".github/sdlc.yml": sdlc(backlog={"mode": "file", "file": "BACKLOG.md"}), "ROADMAP.md": "Items: [backlog](BACKLOG.md)\n"}
        assert run("UPS-WORK-11", repo(t, fmode, name="file"), h)[0] is True


def test_work12_conventions_name_the_loop():
    with tempfile.TemporaryDirectory() as d:
        t = Path(d)
        h = hub(t)
        assert run("UPS-WORK-12", repo(t, {"AGENTS.md": AGENTS}, name="ok"), h)[0] is True
        # the kit template itself satisfies WORK-12 (its words are capitalised: case-insensitive)
        assert run("UPS-WORK-12", repo(t, {"AGENTS.md": dep("templates/sdlc/AGENTS.template.md")}, name="kit"), h)[0] is True
        assert run("UPS-WORK-12", repo(t, {"AGENTS.md": AGENTS.replace("docs/adr", "DOCS/ADR")}, name="case"), h)[0] is True
        # one root cause: a missing AGENTS.md is UPS-AGENT-07's failure
        assert run("UPS-WORK-12", repo(t, {"CLAUDE.md": AGENTS}, name="claude-only"), h) == (True, "no AGENTS.md, see UPS-AGENT-07")
        # ... and so is a missing `## Conventions` heading (it is in agents_required_headings)
        noconv = AGENTS.replace("## Conventions", "## House rules")
        assert run("UPS-WORK-12", repo(t, {"AGENTS.md": noconv}, name="noconv"), h) == (True, "no `## Conventions` section, see UPS-AGENT-07")
        assert run("UPS-AGENT-07", repo(t, {"AGENTS.md": noconv}, name="noconv7"), h)[0] is False
        ok, msg = run("UPS-WORK-12", repo(t, {".github/sdlc.yml": sdlc(adr_path="lineage/decisions"), "AGENTS.md": AGENTS}, name="path"), h)
        assert ok is False and "lineage/decisions" in msg, msg
        off = AGENTS.replace("ADRs in `docs/adr/NNNN-slug.md`", "ADR log not used")
        assert run("UPS-WORK-12", repo(t, {".github/sdlc.yml": sdlc(modules={"adr": False}), "AGENTS.md": off}, name="off"), h)[0] is True
        # adr merely unset (not false) still needs the path
        assert run("UPS-WORK-12", repo(t, {".github/sdlc.yml": sdlc(modules={"features": True}), "AGENTS.md": off}, name="unset"), h)[0] is False
        thin = "# A\n\n## Conventions\n\nUse ruff.\n\n## Backlog\n\nIssues.\n"
        ok, msg = run("UPS-WORK-12", repo(t, {"AGENTS.md": thin}, name="thin"), h)
        assert ok is False and "backlog" in msg and "Definition of Done" in msg and "docs/adr" in msg, msg


# --- UPS-AGENT-07/08/09 ---------------------------------------------------- #
def _set_def(h: Path, key: str, value: str) -> None:
    cf = h / "specs/WORK.contract.yml"
    cf.write_text(re.sub(rf"^(  {key}:) .*$", rf"\1 {value}", cf.read_text(), count=1, flags=re.M))
    c._CONTRACTS.clear()


def test_agent07_required_headings_any_order_and_no_todo():
    with tempfile.TemporaryDirectory() as d:
        t = Path(d)
        h = hub(t)
        assert run("UPS-AGENT-07", repo(t, {"AGENTS.md": AGENTS}, name="ok"), h)[0] is True
        extra = AGENTS.replace("## Layout", "## Testing\n\nmore\n\n## Layout")
        assert run("UPS-AGENT-07", repo(t, {"AGENTS.md": extra}, name="extra"), h)[0] is True
        moved = AGENTS.replace("## Fleet context", "## TEMP").replace("## Conventions", "## Fleet context").replace("## TEMP", "## Conventions")
        assert run("UPS-AGENT-07", repo(t, {"AGENTS.md": moved}, name="order"), h)[0] is True  # agents_heading_order: false
        assert run("UPS-AGENT-07", repo(t, {"AGENTS.md": AGENTS.replace("## Layout", "## LAYOUT ##")}, name="case"), h)[0] is True
        ok, msg = run("UPS-AGENT-07", repo(t, {"AGENTS.md": dep("templates/sdlc/AGENTS.template.md")}, name="kit"), h)
        assert ok is False and "TODO:" in msg, msg  # the unfilled scaffold
        ok, msg = run("UPS-AGENT-07", repo(t, {"AGENTS.md": AGENTS.replace("## Layout\n", "")}, name="miss"), h)
        assert ok is False and "missing ## Layout" in msg, msg
        ok, msg = run("UPS-AGENT-07", repo(t, {"CLAUDE.md": AGENTS}, name="pre-d4"), h)
        assert ok is False and "no AGENTS.md" in msg, msg
        # the switches are read from the contract
        _set_def(h, "agents_heading_order", "true")
        ok, msg = run("UPS-AGENT-07", repo(t, {"AGENTS.md": moved}, name="order2"), h)
        assert ok is False and "out of order" in msg, msg
        _set_def(h, "agents_extra_headings", "false")
        ok, msg = run("UPS-AGENT-07", repo(t, {"AGENTS.md": extra}, name="extra2"), h)
        assert ok is False and "extra headings: testing" in msg, msg
        c._CONTRACTS.clear()


def test_agent08_claude_is_a_pointer():
    with tempfile.TemporaryDirectory() as d:
        t = Path(d)
        h = hub(t)
        assert run("UPS-AGENT-08", repo(t, {"CLAUDE.md": CLAUDE}, name="ok"), h)[0] is True
        assert run("UPS-AGENT-08", repo(t, {"CLAUDE.md": dep("templates/sdlc/CLAUDE.template.md")}, name="kit"), h)[0] is True
        ok, msg = run("UPS-AGENT-08", repo(t, {"CLAUDE.md": "# r\n\nRead AGENTS.md.\n"}, name="noimport"), h)
        assert ok is False and "@AGENTS.md" in msg, msg
        ok, msg = run("UPS-AGENT-08", repo(t, {"CLAUDE.md": CLAUDE + "\n## stack & commands\n\nmake\n"}, name="dup"), h)
        assert ok is False and "stack & commands" in msg, msg
        n = sum(1 for x in CLAUDE.splitlines() if x.strip())
        at_limit = CLAUDE + "".join(f"line {i}\n" for i in range(20 - n))
        assert run("UPS-AGENT-08", repo(t, {"CLAUDE.md": at_limit}, name="limit"), h)[0] is True  # inclusive
        ok, msg = run("UPS-AGENT-08", repo(t, {"CLAUDE.md": at_limit + "one more\n"}, name="long"), h)
        assert ok is False and "21 non-blank lines (max 20)" in msg, msg
        assert run("UPS-AGENT-08", repo(t, name="none"), h)[0] is False


def test_agent09_kit_stamp():
    with tempfile.TemporaryDirectory() as d:
        t = Path(d)
        h = hub(t)
        ok, msg = run("UPS-AGENT-09", repo(t, {"AGENTS.md": AGENTS}, name="sdlc"), h)
        assert ok is True and "sdlc v0.1.0" in msg, msg
        legacy = AGENTS.replace("kit: sdlc v0.1.0", "kit: agent-context v0.3.1 · seeded")
        assert run("UPS-AGENT-09", repo(t, {"AGENTS.md": legacy}, name="ac"), h)[0] is True
        assert run("UPS-AGENT-09", repo(t, {"AGENTS.md": AGENTS.replace("<!-- kit: sdlc v0.1.0 -->\n", "")}, name="none"), h)[0] is False
        assert run("UPS-AGENT-09", repo(t, {"AGENTS.md": AGENTS.replace("kit: sdlc", "kit: verify")}, name="other"), h)[0] is False
        # one root cause: no AGENTS.md is UPS-AGENT-07's failure
        assert run("UPS-AGENT-09", repo(t, {"CLAUDE.md": legacy}, name="claude-stamp"), h) == (True, "no AGENTS.md, see UPS-AGENT-07")


# --- UPS-REPO-21 ----------------------------------------------------------- #
RP_CFG = '{"packages": {".": {"release-type": "simple"}}}'
RP_CALLER = "on: push\njobs:\n  release:\n    uses: bamr87/bamr87/.github/workflows/release-please.yml@{ref}\n    secrets: inherit\n"


def test_repo21_release_please_owns_the_changelog():
    with tempfile.TemporaryDirectory() as d:
        t = Path(d)
        h = hub(t)
        full = {"CHANGELOG.md": "# Changelog\n", "release-please-config.json": RP_CFG, ".release-please-manifest.json": '{".": "0.1.0"}',
                ".github/workflows/release.yml": RP_CALLER.format(ref="v1")}
        assert run("UPS-REPO-21", repo(t, full, name="ok"), h, kinds=("content",))[0] is True
        ok, msg = run("UPS-REPO-21", repo(t, {**full, ".github/workflows/release.yml": RP_CALLER.format(ref="main")}, name="main"), h)
        assert ok is False and "unpinned" in msg, msg
        # the legacy bamr87/.github caller fails at any ref, @main and pinned alike, naming the hub workflow
        for ref in ("main", "v1"):
            dotgh = RP_CALLER.format(ref=ref).replace("bamr87/bamr87/", "bamr87/.github/")
            ok, msg = run("UPS-REPO-21", repo(t, {**full, ".github/workflows/release.yml": dotgh}, name=f"dotgh-{ref}"), h)
            assert ok is False and "migrate to bamr87/bamr87/.github/workflows/release-please.yml@v1 (decision D3)" in msg, (ref, msg)
        ok, msg = run("UPS-REPO-21", repo(t, {".github/workflows/release.yml": dotgh}, name="dotgh-bare"), h)
        assert ok is False and "no CHANGELOG.md" in msg, msg
        # a step that merely mentions the workflow is not a caller (job-level uses only)
        step = "jobs:\n  r:\n    steps:\n      - run: echo uses bamr87/bamr87/.github/workflows/release-please.yml@v1\n"
        ok, msg = run("UPS-REPO-21", repo(t, {**full, ".github/workflows/release.yml": step}, name="step"), h)
        assert ok is False and "no job calls" in msg, msg
        # release_types by repo type
        node = '{"packages": {".": {"release-type": "node"}}}'
        site = {**full, ".github/sdlc.yml": sdlc(type="site", release={"type": "simple"}), "release-please-config.json": node}
        ok, msg = run("UPS-REPO-21", repo(t, site, name="site-node"), h)
        assert ok is False and "type site: simple" in msg, msg
        app = {**full, ".github/sdlc.yml": sdlc(type="app"), "release-please-config.json": node}
        assert run("UPS-REPO-21", repo(t, app, name="app-node"), h)[0] is True
        ok, msg = run("UPS-REPO-21", repo(t, {**full, "release-please-config.json": '{"packages": {".": {"release-type": "go"}}}'}, name="go"), h)
        assert ok is False and "'go'" in msg, msg
        fork = yaml.safe_load(sdlc(type="fork"))
        del fork["release"]
        assert run("UPS-REPO-21", repo(t, {".github/sdlc.yml": yaml.safe_dump(fork)}, name="fork"), h)[0] is True
        ok, msg = run("UPS-REPO-21", repo(t, {**full, ".release-please-manifest.json": "{"}, name="badjson"), h)
        assert ok is False and "not valid JSON" in msg, msg
        ok, msg = run("UPS-REPO-21", repo(t, {"README.md": "x"}, name="bare"), h)
        assert ok is False and "no CHANGELOG.md" in msg and "no release-please-config.json" in msg, msg


def test_repo21_legacy_caller_warns_only_while_the_rollout_marker_is_present():
    """rollout_effect: `rollout: warn` reports the legacy-caller failure as a
    warning; once Fleet Ops deletes the marker it fails (and gates)."""
    specs = {"requirements": [{"id": "UPS-REPO-21", "level": "MUST", "applies": ["all"], "area": "REPO"}]}
    with tempfile.TemporaryDirectory() as d:
        t = Path(d)
        h = hub(t)
        rule = yaml.safe_load((h / "specs/WORK.contract.yml").read_text())["related"]["UPS-REPO-21"]
        assert rule.get("rollout") == "warn" and rule.get("rollout_effect") and "warn" not in rule, rule
        dotgh = RP_CALLER.format(ref="main").replace("bamr87/bamr87/", "bamr87/.github/")
        r = repo(t, {"CHANGELOG.md": "# Changelog\n", "release-please-config.json": RP_CFG,
                     ".release-please-manifest.json": '{".": "0.1.0"}', ".github/workflows/release.yml": dotgh})
        res = c.run_checks(c.Repo(r, h), ["app"], "active", specs)
        assert res["must_failed"] == 0 and [w["id"] for w in res["warnings"]] == ["UPS-REPO-21"], res
        assert "rollout: warn" in res["warnings"][0]["why_warn"] and "rollout_effect" in res["warnings"][0]["why_warn"]
        assert "migrate to" in res["warnings"][0]["detail"]
        cf = h / "specs/WORK.contract.yml"
        text = cf.read_text()
        i = text.index("  UPS-REPO-21:\n")
        cf.write_text(text[:i] + text[i:].replace("    rollout: warn\n", "", 1))
        c._CONTRACTS.clear()
        res = c.run_checks(c.Repo(r, h), ["app"], "active", specs)
        assert res["must_failed"] == 1 and not res["warnings"], res
        assert [f["id"] for f in res["failing"]] == ["UPS-REPO-21"] and "migrate to" in res["failing"][0]["detail"], res
        c._CONTRACTS.clear()


def test_cli_check_runs_on_the_new_spec():
    with tempfile.TemporaryDirectory() as d:
        t = Path(d)
        h = hub(t)
        write(h, "_data/specs.yml", dep("_data/specs.yml"))
        r = repo(t, {"README.md": "# r\n", "CLAUDE.md": "# legacy\n"})
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            assert c.main(["check", str(r), "--hub", str(h), "--kinds", "content"]) == 0
        text = out.getvalue()
        assert "! UPS-AGENT-07" in text and "! UPS-AGENT-08" in text, text
        assert "UPS-AGENT-01" not in text and "UPS-REPO-13" not in text, text
        assert "checker error" not in text, text


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = skipped = 0
    for t in tests:
        try:
            t()
            print(f"ok   {t.__name__}")
        except Skip as e:
            skipped += 1
            print(f"skip {t.__name__}: {e}")
        except AssertionError as e:  # noqa: PERF203
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERR  {t.__name__}: {type(e).__name__}: {e}")
    print(f"{len(tests) - failed - skipped}/{len(tests)} passed, {skipped} skipped")
    raise SystemExit(1 if failed else 0)
