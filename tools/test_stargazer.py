#!/usr/bin/env python3
"""Offline tests for the open-source radar: the model (tools/fleetcore/stars.py), the collector and CLI
(tools/stargazer.py) and the SessionStart hook (.claude/hooks/stars_session_start.py). No network: GitHub
is a fake that answers from fixtures, and the clock is fixed.

    python3 tools/test_stargazer.py
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import stargazer as sg  # noqa: E402
from fleetcore import stars  # noqa: E402

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
# No test may push gauges to a live OTel collector (a refresh and a review push by default): every push in
# this module goes to a port nothing listens on, unless a test names its own endpoint.
os.environ["STARS_OTLP_ENDPOINT"] = "http://127.0.0.1:9"
HOOK = ROOT / ".claude" / "hooks" / "stars_session_start.py"
FLEET = {"hub": {"repo": "bamr87/bamr87", "owners": ["bamr87", "bash-365"]}, "stars": {"account": "bamr87"}}
REGISTRY = [
    {"name": "githubai", "submodule_path": "projects/githubai", "repo_url": "https://github.com/bamr87/githubai",
     "stack": ["github-actions", "ai", "claude-code"], "category": "full-stack-ai", "status": "active",
     "description": "Claude Code SDLC framework: reusable GitHub Actions that triage issues and review PRs."},
    {"name": "zer0-mistakes", "submodule_path": "projects/zer0-mistakes", "repo_url": "https://github.com/bamr87/zer0-mistakes",
     "stack": ["jekyll", "ruby", "bootstrap"], "category": "docs", "status": "active",
     "description": "Jekyll theme for GitHub Pages sites."},
    {"name": "old-thing", "submodule_path": "projects/old-thing", "repo_url": "https://github.com/bamr87/old-thing",
     "stack": ["jekyll"], "category": "docs", "status": "archived", "description": "gone"},
]


def day(n: int) -> str:
    return (NOW - timedelta(days=n)).strftime("%Y-%m-%dT%H:%M:%SZ")


def rec(name: str, *, topics=(), desc="", lang="Python", stars_=1000, forks=100, created=900, pushed=3, lic="MIT",
        private=False, archived=False, release=None, owner=None) -> dict:
    return {"name": name, "url": f"https://github.com/{name}", "description": desc, "homepage": None, "language": lang,
            "topics": list(topics), "stars": stars_, "forks": forks, "license": lic, "private": private,
            "archived": archived, "fork": False, "template": False, "created_at": day(created), "pushed_at": day(pushed),
            "updated_at": day(pushed), "release": release, "owner": owner or name.split("/")[0], "owner_type": "User",
            "avatar": "u/1"}


def raw_fixture() -> dict:
    agent = rec("acme/agent-kit", topics=["claude-code", "github-actions", "ai-agents", "code-review"],
                desc="Claude Code agents that review pull requests in GitHub Actions", release={"tag": "v2.0", "at": day(3), "url": None})
    theme = rec("jane/jekyll-docs-theme", topics=["jekyll", "jekyll-theme", "github-pages", "ruby"], lang="SCSS",
                desc="A documentation theme for Jekyll and GitHub Pages")
    dead = rec("old/jekyll-relic", topics=["jekyll", "jekyll-theme"], desc="An old Jekyll theme", pushed=900, lang="HTML")
    private = rec("acme/secret", topics=["claude-code"], desc="private", private=True)
    own = rec("bamr87/zer0-mistakes", topics=["jekyll"], desc="mine", lang="HTML")
    farmed = rec("spam12345/claude-code-pro", topics=["claude-code", "ai-agents"], desc="", stars_=9000, forks=3,
                 created=5, lic=None)
    rising = rec("new/actions-reviewer", topics=["github-actions", "claude-code", "code-review"],
                 desc="Review bot for GitHub Actions", stars_=3000, forks=200, created=10)
    noise = rec("far/unrelated-db", topics=["database", "rust"], desc="A storage engine", lang="Rust")
    return {
        "account": "bamr87", "starred_total": 5,
        "starred": [{"starred_at": day(2), "repo": agent}, {"starred_at": day(400), "repo": theme},
                    {"starred_at": day(500), "repo": dead}, {"starred_at": day(1), "repo": private},
                    {"starred_at": day(30), "repo": own}],
        "lists": [{"name": "Inspiration", "slug": "inspiration", "description": "", "repos": ["acme/agent-kit"]},
                  {"name": "Hidden", "slug": "hidden", "private": True, "repos": ["jane/jekyll-docs-theme"]}],
        "projects": {"bamr87": rec("bamr87/bamr87", topics=["monorepo", "claude-code", "devops"], desc="fleet hub"),
                     "githubai": rec("bamr87/githubai", topics=["github-actions", "claude-code", "sdlc"], desc="SDLC"),
                     "zer0-mistakes": own},
        "trending": [{"id": "new-7d", "title": "New this week", "q": "created:>x", "count": 2, "repos": [farmed, rising]}],
        "discovered": {"githubai": [rising, noise]},
        "errors": [],
    }


def build(history=None, now=NOW):
    return stars.build(raw_fixture(), registry=REGISTRY, fleet=FLEET, history=history, now=now)


class Text(unittest.TestCase):
    def test_terms_are_singular_without_mangling_names(self):
        for word, want in {"agents": "agent", "ai-agents": "ai-agent", "harnesses": "harness", "libraries": "library",
                           "devops": "devops", "gitops": "gitops", "nodejs": "nodejs", "kubernetes": "kubernetes",
                           "mkdocs": "mkdocs", "github-actions": "github-action", "rails": "rails", "games": "game"}.items():
            self.assertEqual(stars.norm(word), want, word)

    def test_clean_strips_control_and_direction_characters_and_clips(self):
        self.assertEqual(stars.clean("a‮b\x00c\n  d"), "a b c d")
        out = stars.clean("word " * 100, 40)
        self.assertLessEqual(len(out), 41)
        self.assertTrue(out.endswith("…"))

    def test_from_graphql_maps_a_node_and_refuses_what_is_not_one(self):
        node = {"nameWithOwner": "a/b", "url": "https://github.com/a/b", "description": "x​y", "homepageUrl": "javascript:alert(1)",
                "isPrivate": False, "stargazerCount": 5, "forkCount": 1, "primaryLanguage": {"name": "Go"},
                "licenseInfo": {"spdxId": "NOASSERTION"}, "owner": {"__typename": "User", "login": "a",
                                                                       "avatarUrl": "https://avatars.githubusercontent.com/u/42?u=abc&v=4"},
                "repositoryTopics": {"nodes": [{"topic": {"name": "Go"}}, {"topic": {"name": "bad topic"}}]},
                "latestRelease": {"tagName": "v1", "publishedAt": day(1), "url": "https://github.com/a/b/releases/tag/v1"}}
        r = stars.from_graphql(node)
        self.assertEqual((r["name"], r["language"], r["license"], r["avatar"], r["topics"]), ("a/b", "Go", "other", "u/42", ["go"]))
        self.assertIsNone(r["homepage"])  # only http(s) links survive
        self.assertEqual(r["description"], "x y")
        self.assertIsNone(stars.from_graphql({"nameWithOwner": "not a repo"}))
        self.assertIsNone(stars.from_graphql(None))


class Judgements(unittest.TestCase):
    cfg = stars.config(FLEET)

    def test_categorize_prefers_purpose_over_language_topics(self):
        r = rec("x/y", topics=["typescript", "nodejs", "javascript", "ai-agents", "mcp"], desc="An agent platform")
        self.assertEqual(stars.categorize(r, self.cfg)[0], "agents")
        self.assertEqual(stars.categorize(rec("x/z", topics=[], desc="", lang=None), self.cfg), ("other", []))
        self.assertEqual(stars.categorize(rec("x/t", topics=["jekyll", "jekyll-theme"]), self.cfg)[0], "sites")

    def test_suspect_needs_a_burst_and_a_sign(self):
        farmed = rec("spam12345/x", stars_=9000, forks=3, created=5, lic=None)
        self.assertTrue(stars.suspect(farmed, NOW, self.cfg))
        launch = rec("leanprover-community/proof", stars_=800, forks=90, created=3, lic=None, desc="A formal proof")
        self.assertEqual(stars.suspect(launch, NOW, self.cfg), [])
        no_forks = rec("someone/lib", stars_=150, forks=0, created=7)
        self.assertIn("not one fork", stars.suspect(no_forks, NOW, self.cfg)[0])
        old = rec("big/old", stars_=90000, forks=0, created=2000)
        self.assertEqual(stars.suspect(old, NOW, self.cfg), [])

    def test_health_from_the_last_push(self):
        self.assertEqual([stars.health(rec("a/b", pushed=d), NOW) for d in (1, 90, 300, 900)],
                         ["active", "maintained", "slowing", "stale"])
        self.assertEqual(stars.health(rec("a/b", archived=True), NOW), "archived")

    def test_history_thins_and_velocity_reads_it(self):
        hist = None
        for back in range(60, -1, -1):  # 61 daily refreshes, +10 stars a day
            hist = stars.next_history(hist, {"a/b": 1000 - 10 * back}, NOW - timedelta(days=back), self.cfg)
        pts = hist["repos"]["a/b"]["points"]
        self.assertLess(len(pts), 25)                       # 11 days daily + one a week
        self.assertEqual(pts[-1], [NOW.date().isoformat(), 1000])
        self.assertEqual(hist["repos"]["a/b"]["first_seen"], (NOW - timedelta(days=60)).date().isoformat())
        v = stars.velocity(pts, 1000, NOW, day(100))
        self.assertEqual((v["d1"], v["d7"]), (10, 70))
        self.assertGreaterEqual(v["d30"], 300)
        self.assertEqual(v["per_day"], 10.0)
        gone = stars.next_history(hist, {"c/d": 5}, NOW, self.cfg)
        self.assertEqual(list(gone["repos"]), ["c/d"])     # off the radar, out of the history


class Build(unittest.TestCase):
    def setUp(self):
        self.doc, self.hist = build()
        self.repos = self.doc["repos"]

    def test_private_repos_and_lists_never_enter_the_document(self):
        self.assertNotIn("acme/secret", self.repos)
        self.assertEqual([lst["name"] for lst in self.doc["lists"]], ["Inspiration"])
        self.assertEqual(self.repos["acme/agent-kit"]["lists"], ["Inspiration"])
        self.assertNotIn("acme/secret", json.dumps(self.doc))

    def test_starred_newest_first_and_the_fleets_own_repos_match_nothing(self):
        self.assertEqual(self.doc["starred"][0], "acme/agent-kit")
        self.assertNotIn("matches", self.repos["bamr87/zer0-mistakes"])
        self.assertTrue(self.repos["bamr87/zer0-mistakes"]["fleet_owned"])

    def test_matches_say_why(self):
        m = self.repos["acme/agent-kit"]["matches"][0]
        self.assertEqual(m["project"], "githubai")
        self.assertIn("claude-code", m["shared"])
        theme = self.repos["jane/jekyll-docs-theme"]["matches"][0]
        self.assertEqual(theme["project"], "zer0-mistakes")
        self.assertIn("jekyll", theme["shared"])
        self.assertIn("github-actions", m["shared"])  # a topic as written, never its singular form
        self.assertFalse(any(f["project"] == "old-thing" for f in self.doc["fleet"]))  # archived projects are not matched

    def test_incorporate_skips_suspect_stale_and_own(self):
        names = [i["repo"] for i in self.doc["incorporate"]]
        self.assertIn("acme/agent-kit", names)
        for bad in ("spam12345/claude-code-pro", "old/jekyll-relic", "bamr87/zer0-mistakes"):
            self.assertNotIn(bad, names)
        self.assertTrue(self.repos["spam12345/claude-code-pro"]["suspect"])
        first = self.doc["incorporate"][0]
        self.assertTrue(first["why"].startswith("shares "))

    def test_search_noise_is_pruned_and_the_record_is_compact(self):
        self.assertNotIn("far/unrelated-db", self.repos)
        self.assertNotIn("far/unrelated-db", self.hist["repos"])
        r = self.repos["acme/agent-kit"]
        for gone in ("url", "updated_at", "private", "relevance", "first_seen", "age_days"):
            self.assertNotIn(gone, r)
        self.assertEqual(r["release"], {"tag": "v2.0", "at": day(3)[:10]})
        self.assertEqual(len(r["pushed_at"]), 10)

    def test_feed_has_stars_and_releases_and_no_flood_on_the_first_run(self):
        kinds = {(e["kind"], e["repo"]) for e in self.doc["feed"]}
        self.assertIn(("starred", "acme/agent-kit"), kinds)
        self.assertIn(("release", "acme/agent-kit"), kinds)
        self.assertFalse([e for e in self.doc["feed"] if e["kind"] == "radar"])
        doc2, _ = build(history=self.hist, now=NOW + timedelta(days=1))
        self.assertFalse([e for e in doc2["feed"] if e["kind"] == "radar"])  # nothing new joined
        raw = raw_fixture()
        raw["trending"][0]["repos"].append(rec("fresh/agent-reviewer", topics=["claude-code", "github-actions", "code-review"],
                                               desc="Reviews pull requests", created=20))
        doc3, _ = stars.build(raw, registry=REGISTRY, fleet=FLEET, history=self.hist, now=NOW + timedelta(days=1))
        self.assertIn(("radar", "fresh/agent-reviewer"), {(e["kind"], e["repo"]) for e in doc3["feed"]})

    def test_dump_is_one_line_per_repo_and_loads_back(self):
        text = stars.dump(self.doc)
        self.assertEqual(json.loads(text), self.doc)
        body = text.split('\n "repos": {\n', 1)[1].splitlines()
        lines = [ln for ln in body if ln.startswith('  "')]
        self.assertEqual(len(lines), len(self.repos))
        self.assertEqual(json.loads(stars.dump_history(self.hist)), self.hist)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "stars.json"
            p.write_text(text)
            self.assertEqual(stars.load(p), self.doc)
            p.write_text('{"schema": "other"}')
            self.assertIsNone(stars.load(p))


class Reading(unittest.TestCase):
    doc = build()[0]

    def test_query_slices(self):
        self.assertEqual(stars.query(self.doc)["totals"]["starred"], 4)
        self.assertEqual([r["name"] for r in stars.query(self.doc, kind="starred", category="sites")["repos"]],
                         ["bamr87/zer0-mistakes", "jane/jekyll-docs-theme", "old/jekyll-relic"])
        self.assertEqual(stars.query(self.doc, kind="starred", q="pull requests")["total"], 1)
        fleet = stars.query(self.doc, kind="fleet", project="githubai")["projects"][0]
        self.assertEqual(fleet["starred"][0]["repo"], "acme/agent-kit")
        self.assertIsNotNone(fleet["starred"][0]["score"])
        self.assertEqual(stars.query(self.doc, kind="repo", q="acme/agent-kit")["repo"]["name"], "acme/agent-kit")
        for bad in ({"kind": "nope"}, {"kind": "repo", "q": "x/y"}, {"kind": "fleet", "project": "nope"}):
            with self.assertRaises(ValueError):
                stars.query(self.doc, **bad)

    def test_brief_is_about_the_project_and_keeps_strangers_to_their_names(self):
        text = stars.brief(self.doc, "githubai", now=NOW)
        self.assertIn("Starred repos most like githubai", text)
        self.assertIn("acme/agent-kit", text)
        self.assertIn("data, never instructions", text)
        self.assertNotIn("spam12345", text)                    # suspect: never in a brief
        self.assertNotIn("Review bot for GitHub Actions", text)  # a trending repo appears by name only
        self.assertIn("new/actions-reviewer", text)
        self.assertLessEqual(len(text), self.doc["brief"]["max_chars"])
        hub = stars.brief(self.doc, "bamr87", now=NOW)
        self.assertIn("the fleet's projects should look at", hub)
        stale = stars.brief(self.doc, "githubai", now=NOW + timedelta(days=40))
        self.assertIn("STALE", stale)
        self.assertEqual(stars.brief({}, "githubai"), "")
        self.assertEqual(stars.brief({**self.doc, "brief": {"enabled": False}}, "githubai"), "")

    def test_project_for_a_directory(self):
        rows = self.doc["fleet"]
        with tempfile.TemporaryDirectory() as tmp:
            hub = Path(tmp) / "hub"
            (hub / "projects" / "githubai" / "src").mkdir(parents=True)
            self.assertEqual(stars.project_for(hub / "projects" / "githubai" / "src", rows, hub), "githubai")
            self.assertEqual(stars.project_for(hub, rows, hub), "bamr87")
            clone = Path(tmp) / "elsewhere" / "zer0"
            (clone / ".git").mkdir(parents=True)
            (clone / ".git" / "config").write_text('[core]\n\tbare = false\n[remote "origin"]\n\turl = git@github.com:bamr87/zer0-mistakes.git\n')
            self.assertEqual(stars.project_for(clone, rows, hub), "zer0-mistakes")
            wt = Path(tmp) / "wt"  # a worktree: .git is a file, the config is in the common dir
            gitdir = clone / ".git" / "worktrees" / "wt"
            gitdir.mkdir(parents=True)
            (gitdir / "commondir").write_text("../..\n")
            wt.mkdir()
            (wt / ".git").write_text(f"gitdir: {gitdir}\n")
            self.assertEqual(stars.project_for(wt, rows, hub), "zer0-mistakes")
            self.assertIsNone(stars.project_for(Path(tmp), rows, hub))


class FakeGitHub:
    """Answers each query from its shape; `fail` names a phase that raises."""

    def __init__(self, fail: str = ""):
        self.fail, self.calls, self.notes = fail, 0, []
        raw = raw_fixture()
        self.starred, self.projects = raw["starred"], raw["projects"]

    def node(self, r: dict) -> dict:
        return {"nameWithOwner": r["name"], "url": r["url"], "description": r["description"], "isPrivate": r["private"],
                "isArchived": r["archived"], "stargazerCount": r["stars"], "forkCount": r["forks"],
                "createdAt": r["created_at"], "pushedAt": r["pushed_at"], "primaryLanguage": {"name": r["language"]},
                "licenseInfo": {"spdxId": r["license"]} if r["license"] else None,
                "owner": {"login": r["owner"], "__typename": "User", "avatarUrl": "https://avatars.githubusercontent.com/u/7?v=4"},
                "repositoryTopics": {"nodes": [{"topic": {"name": t}} for t in r["topics"]]}}

    def call(self, query: str, variables: dict | None = None) -> dict:
        self.calls += 1
        if "starredRepositories" in query:
            if self.fail == "stars":
                raise sg.GhError("GitHub answered 502")
            after = (variables or {}).get("after")
            page = self.starred[:3] if after is None else self.starred[3:]
            return {"user": {"starredRepositories": {
                "totalCount": len(self.starred), "pageInfo": {"hasNextPage": after is None, "endCursor": "c1"},
                "edges": [{"starredAt": s["starred_at"], "node": self.node(s["repo"])} for s in page]}}}
        if "lists(" in query:
            return {"user": {"lists": {"nodes": [{"name": "Inspiration", "slug": "inspiration", "isPrivate": False,
                                                   "items": {"nodes": [{"nameWithOwner": "acme/agent-kit"}]}},
                                                  {"name": "Private", "isPrivate": True, "items": {"nodes": []}}]}}}
        if "search(" in query:
            if self.fail == "search":
                raise sg.GhError("the refresh budget ran out")
            n = query.count("search(")
            hit = self.node(rec("new/actions-reviewer", topics=["github-actions", "claude-code"], created=10, stars_=3000))
            return {f"s{j}": {"repositoryCount": 1, "nodes": [hit]} for j in range(n)}
        if "repository(" in query:
            by = {r["name"]: r for r in self.projects.values()}
            out = {}
            for j in range(query.count("repository(")):
                frag = query.split(f"r{j}: repository(", 1)[1]
                owner = frag.split('owner: "', 1)[1].split('"', 1)[0]
                name = frag.split('name: "', 1)[1].split('"', 1)[0]
                r = by.get(f"{owner}/{name}")
                out[f"r{j}"] = self.node(r) if r else None
            return out
        raise AssertionError(query[:80])


class Collector(unittest.TestCase):
    def test_collect_reads_every_phase_and_drops_private_lists(self):
        gh = FakeGitHub()
        raw = sg.collect(gh, FLEET, REGISTRY, now=NOW, log=lambda m: None)
        self.assertEqual(len(raw["starred"]), 5)        # two pages
        self.assertEqual([lst["name"] for lst in raw["lists"]], ["Inspiration"])
        self.assertEqual(raw["projects"]["githubai"]["name"], "bamr87/githubai")
        self.assertTrue(raw["trending"] and raw["discovered"])
        self.assertEqual(raw["errors"], [])
        doc, _ = stars.build(raw, registry=REGISTRY, fleet=FLEET, history=None, now=NOW)
        self.assertNotIn("acme/secret", doc["repos"])

    def test_a_failed_search_keeps_the_last_documents_answer(self):
        prev, _ = build()
        raw = sg.collect(FakeGitHub(fail="search"), FLEET, REGISTRY, now=NOW, prev=prev, log=lambda m: None)
        self.assertEqual([r["name"] for r in raw["trending"][0]["repos"]], prev["trending"][0]["repos"])
        self.assertTrue(any("trending not read" in e for e in raw["errors"]))
        self.assertTrue(any("discovery not read" in e for e in raw["errors"]))

    def test_a_failed_star_read_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc_p, hist_p = Path(tmp) / "stars.json", Path(tmp) / "hist.json"
            with mock.patch.object(sg, "DOC", doc_p), mock.patch.object(sg, "HISTORY", hist_p), \
                    mock.patch.object(sg, "token", lambda: "t"), mock.patch.object(sg, "GitHub", lambda *a, **k: FakeGitHub("stars")), \
                    mock.patch.object(sg, "fleet_yml", lambda: FLEET), mock.patch.object(sg, "registry", lambda: REGISTRY), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(sg.main(["refresh"]), 1)
                self.assertFalse(doc_p.exists() or hist_p.exists())
                with contextlib.redirect_stdout(io.StringIO()):
                    with mock.patch.object(sg, "GitHub", lambda *a, **k: FakeGitHub()):
                        self.assertEqual(sg.main(["refresh"]), 0)
                self.assertEqual(stars.load(doc_p)["schema"], stars.SCHEMA)
                self.assertIn("acme/agent-kit", json.loads(hist_p.read_text())["repos"])

    def test_no_token_is_a_clear_refusal(self):
        with mock.patch.object(sg, "token", lambda: None), contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(sg.main(["refresh"]), 2)
        self.assertIn("no GitHub token", err.getvalue())


class Cli(unittest.TestCase):
    def run_cli(self, *argv: str) -> tuple[int, str]:
        doc, _ = build()
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "stars.json"
            p.write_text(stars.dump(doc))
            out = io.StringIO()
            with mock.patch.object(sg, "DOC", p), contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                code = sg.main(list(argv))
        return code, out.getvalue()

    def test_read_commands(self):
        code, out = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("Open-source radar", out)
        code, out = self.run_cli("similar", "githubai", "--json")
        self.assertEqual(json.loads(out)["projects"][0]["project"], "githubai")
        code, out = self.run_cli("show", "acme/agent-kit", "--json")
        self.assertEqual(json.loads(out)["repo"]["category"], "agents")
        self.assertEqual(self.run_cli("show", "no/such")[0], 1)
        code, out = self.run_cli("brief", "--project", "githubai")
        self.assertIn("acme/agent-kit", out)
        for cmd in ("starred", "trending", "incorporate", "feed", "gaining"):
            self.assertEqual(self.run_cli(cmd)[0], 0, cmd)

    def test_hook_install_is_a_dry_run_until_yes_and_happens_once(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": tmp}), \
                contextlib.redirect_stdout(io.StringIO()):
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps({"model": "x", "hooks": {"Stop": [{"hooks": []}]}}))
            self.assertEqual(sg.main(["hook", "--install"]), 0)
            self.assertNotIn("SessionStart", path.read_text())
            self.assertEqual(sg.main(["hook", "--install", "--yes"]), 0)
            self.assertEqual(sg.main(["hook", "--install", "--yes"]), 0)
            settings = json.loads(path.read_text())
            self.assertEqual(settings["model"], "x")  # the rest of the file is kept
            starts = settings["hooks"]["SessionStart"]
            self.assertEqual(len(starts), 1)
            self.assertTrue(starts[0]["hooks"][0]["command"].endswith('stars_session_start.py" --user'))


class AiPass(unittest.TestCase):
    def setUp(self):
        self.doc, _ = build()
        self.cfg = stars.config(FLEET)["ai"]

    def answer(self, names: list[str], **over) -> str:
        reviews = [{"repo": n, "summary": f"{n} does a thing", "kind": "tool", "verdict": "borrow", "project": "githubai",
                    "why": "close", "ideas": ["take the reviewer"], **over} for n in names]
        return "Here you go:\n" + json.dumps({"reviews": reviews}) + "\n"

    def test_candidates_skip_suspect_own_and_current_reviews(self):
        names = stars.review_candidates(self.doc, None, self.cfg, NOW)
        self.assertEqual(names[0], self.doc["incorporate"][0]["repo"])
        for bad in ("spam12345/claude-code-pro", "bamr87/zer0-mistakes"):
            self.assertNotIn(bad, names)
        got = stars.parse_reviews(self.answer(names), self.doc, names, model="m", now=NOW)
        ai = {**stars.empty_ai(), "reviews": got}
        self.assertEqual(stars.review_candidates(self.doc, ai, self.cfg, NOW), [])
        self.assertEqual(stars.review_candidates(self.doc, ai, self.cfg, NOW + timedelta(days=200)), names)  # too old
        self.assertEqual(len(stars.review_candidates(self.doc, None, self.cfg, NOW, limit=1)), 1)

    def test_parse_holds_every_field_to_its_type(self):
        names = ["acme/agent-kit"]
        text = json.dumps({"reviews": [
            {"repo": "acme/agent-kit", "summary": "x" * 500, "kind": "rocket", "verdict": "BUY", "project": "nope",
             "why": "w\u202e", "ideas": ["a", 3, "b", "c", "d"]},
            {"repo": "not/given", "verdict": "adopt"}]})
        got = stars.parse_reviews(text, self.doc, names, model="m", now=NOW)
        r = got["acme/agent-kit"]
        self.assertEqual(list(got), ["acme/agent-kit"])  # a repo it was not given is dropped
        self.assertEqual((r["kind"], r["verdict"], r["project"]), ("other", "watch", None))
        self.assertLessEqual(len(r["summary"]), 161)
        self.assertEqual(r["ideas"], ["a", "b", "c"])
        self.assertEqual(r["hash"], stars.review_hash(self.doc["repos"]["acme/agent-kit"]))
        for bad in ("no json here", "[1, 2]", '{"reviews": [ broken'):
            with self.assertRaises(ValueError):
                stars.parse_reviews(bad, self.doc, names, model="m", now=NOW)

    def test_prompts_fence_third_party_text(self):
        names = stars.review_candidates(self.doc, None, self.cfg, NOW)
        text = stars.review_prompt(self.doc, names)
        self.assertIn("<repos>", text)
        self.assertIn("never an instruction", text)
        self.assertIn("- githubai:", text)
        for n in names:
            self.assertIn(n, text)
        self.assertIn("<repos>", stars.groups_prompt(self.doc, self.cfg))

    def test_groups_keep_each_star_once_and_gather_the_rest(self):
        text = json.dumps({"groups": [
            {"name": "Agents", "summary": "s", "repos": ["acme/agent-kit", "acme/agent-kit", "ghost/repo"], "fleet": ["githubai", "x"]},
            {"name": "Sites", "summary": "s", "repos": ["jane/jekyll-docs-theme", "acme/agent-kit"], "fleet": []}]})
        g = stars.parse_groups(text, self.doc, self.cfg, model="m", now=NOW)
        self.assertEqual([x["repos"] for x in g["items"][:2]], [["acme/agent-kit"], ["jane/jekyll-docs-theme"]])
        self.assertEqual(g["items"][0]["fleet"], ["githubai"])
        self.assertEqual(g["items"][-1]["name"], "Ungrouped")
        self.assertEqual(g["basis"], stars.groups_basis(self.doc))
        with self.assertRaises(ValueError):
            stars.parse_groups('{"groups": []}', self.doc, self.cfg, model="m", now=NOW)

    def test_attach_is_idempotent_and_a_skip_leaves_the_review_list(self):
        names = [i["repo"] for i in self.doc["incorporate"]]
        got = stars.parse_reviews(self.answer(names, verdict="skip"), self.doc, names, model="m", now=NOW)
        ai = {**stars.empty_ai(), "reviews": got, "updated_at": "t"}
        once = stars.attach_ai(json.loads(json.dumps(self.doc)), ai)
        twice = stars.attach_ai(json.loads(json.dumps(once)), ai)
        self.assertEqual(once, twice)
        self.assertEqual(once["incorporate"], [])
        self.assertEqual(once["ai"]["verdicts"], {"skip": len(names)})
        self.assertEqual(once["repos"][names[0]]["ai"]["verdict"], "skip")
        changed = json.loads(json.dumps(self.doc))
        changed["repos"][names[0]]["description"] = "something else now"
        self.assertTrue(stars.attach_ai(changed, ai)["repos"][names[0]]["ai"]["stale"])
        self.assertNotIn("Starred repos most like githubai", stars.brief(once, "githubai", now=NOW))  # its one match was a skip

    def test_build_lays_the_committed_ai_over_the_radar(self):
        names = ["acme/agent-kit"]
        ai = {**stars.empty_ai(), "reviews": stars.parse_reviews(self.answer(names, verdict="adopt"), self.doc, names, model="m", now=NOW)}
        doc, _ = build()
        doc2, _ = stars.build(raw_fixture(), registry=REGISTRY, fleet=FLEET, history=None, now=NOW, ai=ai)
        self.assertNotIn("ai", doc["repos"]["acme/agent-kit"])
        self.assertEqual(doc2["repos"]["acme/agent-kit"]["ai"]["verdict"], "adopt")
        self.assertIn("AI: adopt", stars.brief(doc2, "githubai", now=NOW))
        self.assertEqual(json.loads(stars.dump_ai(ai)), ai)

    def test_review_command_plans_until_yes_and_splits_a_failed_batch(self):
        doc, _ = build()
        calls: list[list[str]] = []

        def fake_session(prompt: str, cfg: dict, hub: str):
            names = [line.split('"repo": "')[1].split('"')[0] for line in prompt.splitlines() if line.startswith('{"repo": ')]
            if names and len(names) > 1 and len(calls) == 0:
                calls.append(names)
                return "API Error: overloaded", {"cost_usd": 0.01, "outcome": "agent_error", "exit": 1}
            calls.append(names)
            if "Make " in prompt and "groups" in prompt:
                return json.dumps({"groups": [{"name": "All", "summary": "s", "repos": doc["starred"], "fleet": []}]}), {"cost_usd": 0.02}
            return self.answer(names), {"cost_usd": 0.03, "turns": 1, "outcome": "ok"}

        with tempfile.TemporaryDirectory() as tmp:
            doc_p, ai_p = Path(tmp) / "stars.json", Path(tmp) / "stars_ai.json"
            doc_p.write_text(stars.dump(doc))
            with mock.patch.object(sg, "DOC", doc_p), mock.patch.object(sg, "AI_FILE", ai_p), \
                    mock.patch.object(sg, "fleet_yml", lambda: FLEET), mock.patch.object(sg, "run_session", fake_session), \
                    mock.patch.object(sg, "push_metrics", lambda *a, **k: "not pushed"), \
                    mock.patch.object(sg.shutil, "which", lambda b: "/bin/claude"), \
                    contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(sg.main(["review"]), 0)
                self.assertIn("plan only", out.getvalue())
                self.assertFalse(ai_p.exists())
                self.assertEqual(sg.main(["review", "--yes"]), 0)
            ai = json.loads(ai_p.read_text())
            want = stars.review_candidates(doc, None, stars.config(FLEET)["ai"], datetime.now(timezone.utc))
            self.assertEqual(sorted(ai["reviews"]), sorted(want))   # the failed batch came back as two halves
            self.assertEqual(len(calls[1]) + len(calls[2]), len(calls[0]))
            self.assertEqual(ai["groups"]["items"][0]["name"], "All")
            self.assertEqual(stars.load(doc_p)["ai"]["reviewed"], len(want))
            self.assertEqual([r["outcome"] for r in ai["runs"]][:1], ["agent_error"])


class Metrics(unittest.TestCase):
    doc = build()[0]

    def test_gauges_and_their_two_encodings(self):
        samples = stars.metrics(self.doc)
        names = {x["name"] for x in samples}
        for want in ("fleet_stars_repo_stars", "fleet_stars_repo_similarity", "fleet_stars_category_repos", "fleet_stars_total"):
            self.assertIn(want, names)
        agent = [x for x in samples if x["name"] == "fleet_stars_repo_stars" and x["attrs"]["repo"] == "acme/agent-kit"][0]
        self.assertEqual((agent["value"], agent["attrs"]["starred"], agent["attrs"]["project"]), (1000.0, "true", "githubai"))
        text = stars.prom_text(samples)
        seen: list[str] = []
        for line in text.splitlines():  # a family's samples are contiguous
            if line.startswith("# TYPE "):
                self.assertNotIn(line.split()[2], seen)
                seen.append(line.split()[2])
        payload = stars.otlp_payload(samples, NOW)
        metrics = payload["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]
        self.assertEqual(sum(len(m["gauge"]["dataPoints"]) for m in metrics), len(samples))
        self.assertEqual(payload["resourceMetrics"][0]["resource"]["attributes"][0]["value"]["stringValue"], "stargazer")

    def test_push_without_a_collector_is_a_note_not_an_error(self):
        msg = sg.push_metrics(self.doc, FLEET, endpoint="http://127.0.0.1:9")
        self.assertIn("not pushed", msg)
        env = {k: v for k, v in os.environ.items() if k != "STARS_OTLP_ENDPOINT"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(sg.otlp_endpoint({"observability": {"claude_code": {"endpoint": "http://x:4318/"}}}),
                             "http://x:4318/v1/metrics")

    def test_the_committed_dashboard_is_the_render(self):
        want = json.dumps(stars.grafana_dashboard(), indent=2, sort_keys=True) + "\n"
        self.assertEqual(sg.GRAFANA_FILE.read_text(encoding="utf-8"), want, "run `tools/dash stars grafana --write`")
        dash = stars.grafana_dashboard()
        self.assertEqual(dash["uid"], "fleet-stars")
        for p in dash["panels"]:
            self.assertEqual(p["datasource"], {"type": "prometheus", "uid": "fleet-prometheus"}, p["title"])
            for t in p["targets"]:
                self.assertIn("fleet_stars_", t["expr"])
        ids = [p["id"] for p in dash["panels"]]
        self.assertEqual(len(ids), len(set(ids)))


class Hook(unittest.TestCase):
    def run_hook(self, payload: dict, *args: str, env: dict | None = None) -> str:
        e = {k: v for k, v in os.environ.items() if k not in ("STARS_SESSION_BRIEF", "CLAUDE_PROJECT_DIR")}
        e.update(env or {})
        out = subprocess.run([sys.executable, str(HOOK), *args], input=json.dumps(payload), capture_output=True,
                             text=True, env=e, timeout=30)
        self.assertEqual(out.returncode, 0)
        return out.stdout

    def test_it_briefs_the_session_or_stays_silent(self):
        has_doc = stars.load(ROOT / "_data" / "stars.json") is not None
        out = self.run_hook({"cwd": str(ROOT)})
        if has_doc:
            ctx = json.loads(out)["hookSpecificOutput"]
            self.assertEqual(ctx["hookEventName"], "SessionStart")
            self.assertIn("Starred-repo radar", ctx["additionalContext"])
        self.assertEqual(self.run_hook({"cwd": str(ROOT)}, env={"STARS_SESSION_BRIEF": "0"}), "")
        # the user-level copy defers to the project's own hook
        self.assertEqual(self.run_hook({"cwd": str(ROOT)}, "--user", env={"CLAUDE_PROJECT_DIR": str(ROOT)}), "")

    def test_garbage_in_is_silence_not_a_crash(self):
        out = subprocess.run([sys.executable, str(HOOK)], input="not json", capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
