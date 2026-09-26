#!/usr/bin/env python3
"""
Fixture tests for content_atlas.py — the content atlas + the editorial plan.

Guards the properties that make the atlas trustworthy as a CMS monitor and
the plan trustworthy as the record of an editorial decision:

  * extraction reads Jekyll the way Jekyll does: `_name` segments are
    collections, files without front matter are not documents, invalid YAML
    is a finding rather than a crash, filename date prefixes count as dates,
    and _config.yml's exclude list is honoured — except under explicit roots;
  * git history dates documents from real commits, and a SHALLOW clone's
    boundary commit (which "adds" every file) does not date the whole site;
  * the analysis buckets ages, splits human from bot commits, measures pillar
    coverage against targets, and its suggestions have STABLE keys that
    disappear once the plan carries a decision for them;
  * plan writes validate (unknown site, bad transitions, control characters,
    bad issue URLs), preserve comments, and round-trip byte-for-byte outside
    the edited lines (skipped without ruamel.yaml);
  * `file` is a dry run by default, dedupes against issues already carrying
    the marker, and a CLOSED issue marks its directive done.

No network, no gh, no pytest — git and PyYAML only:

    python3 .github/scripts/dash-gen/test_content_atlas.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import content_atlas as ca  # noqa: E402

TODAY = dt.date(2026, 9, 26)


def _has_ruamel() -> bool:
    try:
        import ruamel.yaml  # noqa: F401
        return True
    except ImportError:
        return False


def _git(tree: Path, *args: str, date: str | None = None, author: str = "Ada") -> None:
    env = dict(os.environ, GIT_AUTHOR_NAME=author, GIT_AUTHOR_EMAIL="a@example.com",
               GIT_COMMITTER_NAME=author, GIT_COMMITTER_EMAIL="a@example.com")
    if date:
        env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    subprocess.run(["git", "-C", str(tree), *args], check=True, capture_output=True, env=env)


def _write(tree: Path, rel: str, text: str) -> None:
    p = tree / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


POST = """---
title: {title}
description: A description that is long enough to pass the fifty character floor, easily.
date: {date}
tags: [{tags}]
author: ada
---
# {title}

{body}
"""


def _site(tmp: Path) -> Path:
    tree = tmp / "demo-site"
    tree.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(tree)], check=True)
    _write(tree, "_config.yml", "collections_dir: pages\nexclude: [pages/_drafts-private]\n")
    _write(tree, "pages/_posts/hacks/2026-09-01-new-hack.md",
           POST.format(title="New hack", date="2026-09-01", tags="shell, git", body="word " * 400))
    _write(tree, "pages/_posts/hacks/2024-01-05-old-hack.md",
           POST.format(title="Old hack", date="2024-01-05", tags="shell", body="word " * 400))
    _write(tree, "pages/_posts/tools/2026-08-20-a-tool.md",
           POST.format(title="A tool", date="2026-08-20", tags="ai", body="short body [x](/y/) [[Wiki]]"))
    _write(tree, "pages/_docs/guide.md", "---\ntitle: Guide\n---\nno date, no tags\n")
    _write(tree, "pages/_docs/broken.md", "---\ntitle: Broken\ndomain: a: b\n---\nbody\n")
    _write(tree, "pages/_posts/hacks/2026-09-10-undated-fm.md",
           "---\ntitle: Filename-dated\ndescription: x\ntags: [git]\n---\nbody\n")
    _write(tree, "pages/notes.md", "no front matter here — not a document\n")
    _write(tree, "pages/_drafts-private/secret.md", "---\ntitle: excluded by _config\n---\n")
    _write(tree, "README.md", "---\ntitle: never a document\n---\n")
    _git(tree, "add", "-A")
    _git(tree, "commit", "-qm", "seed", date="2024-01-05T10:00:00Z")
    _write(tree, "pages/_posts/hacks/2026-09-01-new-hack.md",
           POST.format(title="New hack", date="2026-09-01", tags="shell, git", body="word " * 420))
    _git(tree, "commit", "-qam", "edit", date="2026-09-02T10:00:00Z", author="github-actions[bot]")
    return tree


def _contract(tree: Path) -> dict:
    c = ca._merge(ca.DEFAULTS, {})
    c["sites"] = [{"name": "demo", "repo": "acme/demo", "live_url": None, "branch": "main", "roots": [],
                   "exclude": [], "checkout": str(tree), "quality": c["quality"], "dates": "frontmatter"}]
    return c


def _synced(tmp: Path):
    tree = _site(tmp)
    contract = _contract(tree)
    conn = ca.connect(tmp / "lake")
    docs, skipped = ca.scan_tree(tree, contract["sites"][0], contract)
    history, commits = ca.git_history(tree, 3650, now=TODAY)
    ca.store_site(conn, contract["sites"][0], "checkout", tree, docs, history, commits, skipped)
    return tree, contract, conn, docs, skipped


def test_scan_reads_jekyll_the_way_jekyll_does():
    tmp = Path(tempfile.mkdtemp())
    try:
        tree, contract, conn, docs, skipped = _synced(tmp)
        by = {d["path"]: d for d in docs}
        assert "pages/notes.md" not in by and skipped == 1, "a file without front matter is not a document"
        assert not any("_drafts-private" in p for p in by), "_config.yml exclude is honoured"
        assert "README.md" not in by, "root docs are never content"
        new = by["pages/_posts/hacks/2026-09-01-new-hack.md"]
        assert (new["collection"], new["section"]) == ("posts", "hacks"), new
        assert new["tags"] == ["shell", "git"] and new["words"] >= 400
        tool = by["pages/_posts/tools/2026-08-20-a-tool.md"]
        assert tool["links"] == 1 and tool["wikilinks"] == 1 and "thin" in tool["issues"]
        assert "frontmatter-invalid" in by["pages/_docs/broken.md"]["issues"], "bad YAML is a finding, not a crash"
        guide = by["pages/_docs/guide.md"]
        assert {"missing-description", "missing-tags", "missing-date"} <= set(guide["issues"]), guide["issues"]
        assert by["pages/_posts/hacks/2026-09-10-undated-fm.md"]["date"] == "2026-09-10", "filename date prefix counts"
    finally:
        shutil.rmtree(tmp)


def test_explicit_roots_bypass_config_exclude_and_classify_by_first_dir():
    tmp = Path(tempfile.mkdtemp())
    try:
        tree = tmp / "vaultish"
        _write(tree, "_config.yml", "exclude: [vault]\n")
        _write(tree, "vault/paradoxes/liar.md", "---\ntitle: The Liar\ntype: paradox\nstatus: canon\n---\nx\n")
        _write(tree, "vault/templates/entry.md", "---\ntitle: template\n---\n")
        c = ca._merge(ca.DEFAULTS, {})
        site = {"name": "v", "roots": ["vault"], "exclude": ["templates"], "quality": c["quality"]}
        docs, _ = ca.scan_tree(tree, site, c)
        assert [d["path"] for d in docs] == ["vault/paradoxes/liar.md"], docs
        assert docs[0]["collection"] == "paradoxes"
    finally:
        shutil.rmtree(tmp)


def test_git_history_dates_and_skips_the_shallow_boundary():
    tmp = Path(tempfile.mkdtemp())
    try:
        tree = _site(tmp)
        files, commits = ca.git_history(tree, 3650, now=TODAY)
        new = files["pages/_posts/hacks/2026-09-01-new-hack.md"]
        assert new == {"modified": "2026-09-02", "created": "2024-01-05", "commits": 2}, new
        assert [c["bot"] for c in commits] == [1, 0], "github-actions[bot] is a bot; Ada is not"
        shallow = tmp / "shallow"
        subprocess.run(["git", "clone", "-q", "--depth", "1", f"file://{tree}", str(shallow)], check=True)
        files, commits = ca.git_history(shallow, 3650, now=TODAY)
        assert commits == [] and files == {}, "the boundary commit must not date every file to the clone"
    finally:
        shutil.rmtree(tmp)


def test_analysis_aging_cadence_and_pillar_coverage():
    tmp = Path(tempfile.mkdtemp())
    try:
        tree, contract, conn, _, _ = _synced(tmp)
        plan = {"sites": {"demo": {"narrative": "N", "pillars": [
            {"id": "hacks", "title": "Hacks", "target_share": 0.2, "match": {"sections": ["hacks"]}},
            {"id": "ai", "title": "AI", "target_share": 0.8, "match": {"tags": ["ai"]}},
        ], "directives": []}}}
        doc = ca.report(conn, contract, plan, today=TODAY)
        a = doc["sites"][0]
        t = a["totals"]
        assert t["docs"] == 6 and t["recent"] == 3, t
        # the old post, plus the two undated docs whose only commit is the 2024 seed
        assert t["stale"] == 3 and "Old hack" in {d["title"] for d in a["stale_docs"]}, "untouched since 2024 is stale"
        assert sum(b["docs"] for b in a["aging"]) == 6
        assert sum(w["bot"] for w in a["cadence"]) == 1, "the bot edit lands in its week"
        hacks = next(p for p in a["pillars"] if p["id"] == "hacks")
        assert hacks["docs"] == 3 and hacks["recent"] == 2, hacks
        keys = {s["key"] for s in a["suggestions"]}
        assert "pillar-over:hacks" not in keys, "over needs >= 3 recent pieces"
        assert "pillar-gap:ai" in keys, "1 of 3 recent against an 80% target is a gap"
        assert "hygiene:frontmatter-invalid" in keys and "refresh:pages/_posts/hacks/2024-01-05-old-hack.md" in keys
        json.dumps(doc)  # the console serves it as-is
        plan["sites"]["demo"]["directives"] = [{"key": "pillar-gap:ai", "status": "rejected"}]
        again = {s["key"] for s in ca.report(conn, contract, plan, today=TODAY)["sites"][0]["suggestions"]}
        assert "pillar-gap:ai" not in again, "a decided key is never re-suggested"
        rows = ca.documents(conn, "demo", view="stale", today=TODAY, contract=contract)
        # invalid front matter yields no title, so the file stem stands in
        assert {r["title"] for r in rows} == {"Old hack", "Guide", "broken"}, rows
        rows = ca.documents(conn, "demo", view="pillar:ai", today=TODAY, contract=contract, plan=plan)
        assert [r["title"] for r in rows] == ["A tool"]
    finally:
        shutil.rmtree(tmp)


def test_no_pillars_asks_for_them_and_cadence_fires_when_quiet():
    a = {"totals": {"docs": 10, "days_since_publish": 90, "recent": 0, "recent_days": 90},
         "pillars": [], "topics": [{"tag": "x"}], "unmapped": {"share": 1, "docs": 10, "top_tags": []},
         "stale_docs": [], "issues": [], "directives": []}
    keys = [s["key"] for s in ca.suggestions(a, ca.DEFAULTS, TODAY)]
    assert keys == ["cadence", "define-pillars"], keys


PLAN = """# the editorial plan — this comment must survive
schema: editorial/v1
sites:
  demo:
    narrative: >-
      The story.
    pillars:
      - id: hacks
        title: Hacks
        target_share: 0.3 # keep me
        status: active
        match:
          sections: [hacks]
    directives: []
"""


def test_plan_writes_validate_and_preserve_comments():
    if not _has_ruamel():
        print("    (skipped: ruamel.yaml not installed)")
        return
    tmp = Path(tempfile.mkdtemp())
    try:
        path = tmp / "editorial.yml"
        path.write_text(PLAN)
        c = {"sites": [{"name": "demo"}]}
        sugg = {"key": "pillar-gap:hacks", "kind": "write", "priority": "P1", "title": "Publish hacks",
                "brief": "b", "pillar": "hacks"}
        ca.decide(path, "demo", "approve", "pillar-gap:hacks", c, suggestion=sugg, today=TODAY)
        text = path.read_text()
        assert "this comment must survive" in text and "# keep me" in text
        assert text.startswith(PLAN.split("    directives: []")[0]), "lines above the edit are byte-identical"
        d = ca.site_plan(ca.load_plan(path), "demo")["directives"][0]
        assert (d["status"], d["source"], d["decided"]) == ("approved", "atlas", "2026-09-26"), d
        for bad in (lambda: ca.decide(path, "nope", "approve", "k", c, suggestion=sugg),
                    lambda: ca.decide(path, "demo", "approve", "unknown-key", c),
                    lambda: ca.decide(path, "demo", "status", "pillar-gap:hacks", c, fields={"status": "bogus"}),
                    lambda: ca.decide(path, "demo", "remove", "pillar-gap:hacks", c),
                    lambda: ca.decide(path, "demo", "add", "k2", c, fields={"title": "bad\x07title"}),
                    lambda: ca.decide(path, "demo", "status", "pillar-gap:hacks", c,
                                      fields={"status": "filed", "issue": "https://evil.example/1"}),
                    lambda: ca.update_site(path, "demo", c, {"pillar": {"id": "hacks", "target_share": 3}})):
            try:
                bad()
            except ValueError:
                continue
            raise AssertionError("an invalid plan write was accepted")
        ca.decide(path, "demo", "status", "pillar-gap:hacks", c,
                  fields={"status": "filed", "issue": "https://github.com/acme/demo/issues/7"}, today=TODAY)
        ca.update_site(path, "demo", c, {"narrative": "New story", "pillar": {"id": "hacks", "target_share": 0.4}})
        sp = ca.site_plan(ca.load_plan(path), "demo")
        assert sp["narrative"] == "New story" and sp["pillars"][0]["target_share"] == 0.4
        assert sp["directives"][0]["issue"].endswith("/issues/7")
        assert "# keep me" in path.read_text(), "a value edit keeps its trailing comment"
    finally:
        shutil.rmtree(tmp)


def test_file_is_dry_by_default_dedupes_and_closes():
    tmp = Path(tempfile.mkdtemp())
    try:
        path = tmp / "editorial.yml"
        path.write_text(PLAN)
        a = {"site": "demo", "repo": "acme/demo", "narrative": "N", "directives": [
            {"key": "k-new", "title": "New one", "status": "approved", "kind": "write", "priority": "P2"},
            {"key": "k-old", "title": "Old one", "status": "filed", "kind": "write", "priority": "P2"}]}
        calls = []
        closed = [{"url": "https://github.com/acme/demo/issues/3", "state": "CLOSED",
                   "body": "<!-- editorial-directive key=k-old site=demo -->\n..."}]

        def fake(argv, timeout=60, stdin=None, cwd=None):
            calls.append(argv)
            if argv[:3] == ["gh", "issue", "list"]:
                return 0, json.dumps(closed)
            return 0, "https://github.com/acme/demo/issues/9\n"

        res = ca.file_directives(a, {}, path, apply=False, log=lambda *_: None, run=fake)
        assert {r["key"]: r["action"] for r in res} == {"k-new": "would-file", "k-old": "linked"}
        assert all(c[:3] == ["gh", "issue", "list"] for c in calls), "a dry run only reads"
        assert "k-new" in ca.issue_body(a, a["directives"][0]) and "The narrative this serves" in ca.issue_body(a, a["directives"][0])
        if _has_ruamel():
            ca.decide(path, "demo", "add", "k-new", {"sites": [{"name": "demo"}]}, fields={"title": "New one"})
            ca.decide(path, "demo", "add", "k-old", {"sites": [{"name": "demo"}]}, fields={"title": "Old one"})
            ca.decide(path, "demo", "status", "k-old", {"sites": [{"name": "demo"}]}, fields={"status": "filed"})
            calls.clear()
            res = ca.file_directives(a, {"sites": [{"name": "demo"}]}, path, apply=True, log=lambda *_: None,
                                     run=fake, today=TODAY)
            assert any(c[:3] == ["gh", "issue", "create"] for c in calls)
            assert not any("k-old" in " ".join(c) for c in calls if c[:3] == ["gh", "issue", "create"])
            ds = {d["key"]: d for d in ca.site_plan(ca.load_plan(path), "demo")["directives"]}
            assert ds["k-new"]["status"] == "filed" and ds["k-new"]["issue"].endswith("/9")
            assert ds["k-old"]["status"] == "done", "a closed issue marks its directive done"
    finally:
        shutil.rmtree(tmp)


def test_committed_contract_and_plan_agree():
    """Every site in the committed plan is declared in fleet.yml, and every
    declared site resolves to a repo — the plan can never steer a ghost."""
    contract = ca.load_contract()
    names = {s["name"] for s in contract["sites"]}
    assert names, "fleet.yml declares content sites"
    assert all(s.get("repo") for s in contract["sites"]), [s["name"] for s in contract["sites"] if not s.get("repo")]
    plan = ca.load_plan()
    assert plan.get("schema") == ca.PLAN_SCHEMA
    stray = set(plan["sites"]) - names
    assert not stray, f"editorial.yml plans undeclared sites: {stray}"
    for site, sp in plan["sites"].items():
        for p in sp.get("pillars") or []:
            assert ca.ID_RX.match(p["id"]), p
            ts = p.get("target_share")
            assert ts is None or 0 <= ts <= 1, (site, p)
        for d in sp.get("directives") or []:
            assert d.get("status") in ca.DIRECTIVE_STATES, (site, d)


def main() -> int:
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ✓ {name}")
            except AssertionError as exc:
                failures += 1
                print(f"  ✗ {name}: {exc}")
    print(f"{'FAIL' if failures else 'OK'} — content_atlas fixture tests")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
