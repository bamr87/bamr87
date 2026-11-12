#!/usr/bin/env python3
"""Offline tests for decision_index — the fleet's decision queue in one call.

A GitHub GraphQL endpoint in memory (FakeGitHub) stands in for api.github.com,
so nothing here reaches the network or needs a token. What is held:

  * each kind of decision is recognised from GitHub-shaped answers, and what is
    not Amr's to decide stays out (a draft, a held PR, a conflict, changes
    requested, the ratification-record branch);
  * the index is a cache: served inside the TTL with no call, re-read after it,
    never read with refresh=never, and a call that was cut resumes;
  * the time budget is a wall clock: a slow GitHub returns a partial answer on
    time, with the label-based rows it already has;
  * Design for Failure: no token, a refused token, the rate limit, a 502, a dead
    network, a truncated search, a corrupt index and an unwritable one each
    leave an answer that says what it is (status, errors, hint);
  * no token-like string reaches the answer or the index file.

    python3 tools/console/test_decision_index.py
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import stat
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import decision_index as d  # noqa: E402

FX = json.loads((HERE / "test_decision_index_fixtures.json").read_text(encoding="utf-8"))
RATE_HEADERS = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1800003600"}


def config(**over) -> dict:
    cfg = copy.deepcopy(d.DEFAULTS)
    cfg.update(owners=["bamr87", "bash-365"], registry=["bamr87/bamr87", "bamr87/zer0-mistakes"])
    cfg.update(over)
    return cfg


def bulk(n: int) -> tuple[list[dict], dict]:
    """n ready pull requests and their enrichment, for the paging and budget cases."""
    prs = [{"__typename": "PullRequest", "id": f"PR_B{i:03d}", "number": i + 1, "title": f"feat: change {i}",
            "url": f"https://github.com/bamr87/bulk/pull/{i + 1}", "createdAt": "2026-11-01T09:00:00Z",
            "updatedAt": "2026-11-10T12:00:00Z", "author": {"login": "bamr87", "__typename": "User"},
            "repository": {"nameWithOwner": "bamr87/bulk", "isPrivate": False}, "labels": {"nodes": []},
            "isDraft": False, "baseRefName": "main", "headRefName": f"feature/{i}"} for i in range(n)]
    enrich = {p["id"]: {"id": p["id"], "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN", "reviewDecision": None,
                        "autoMergeRequest": None, "files": {"totalCount": 1, "nodes": [{"path": "src/app.py"}]},
                        "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": "SUCCESS"}}}]}} for p in prs}
    return prs, enrich


class FakeGitHub:
    """api.github.com/graphql in memory: the three searches, paged, and the enrichment by node id."""

    def __init__(self, prs=None, issues=None, repos=None, enrich=None):
        self.prs = copy.deepcopy(FX["prs"] if prs is None else prs)
        self.issues = copy.deepcopy(FX["issues"] if issues is None else issues)
        self.repos = copy.deepcopy(FX["repos"] if repos is None else repos)
        self.enrich = copy.deepcopy(FX["enrich"] if enrich is None else enrich)
        self.calls: list[tuple[str, dict]] = []
        self.lock = threading.Lock()
        self.max_page = 100          # a larger search page answers 502, as GitHub does past its own 10 s
        self.max_batch = 100         # the same for an enrichment batch
        self.poison: set[str] = set()        # a batch holding one of these ids answers 502
        self.unknown_once: set[str] = set()  # `mergeable` is UNKNOWN the first time these are asked
        self.script: dict[str, list] = {}    # stage -> answers given first; None means "answer normally"
        self.delay: dict[str, float] = {}
        self.remaining = 4800
        self.inflate = 0             # added to the search's count: a search that returns fewer than it counted
        self.soft: dict[str, list] = {}

    @staticmethod
    def stage(query: str, variables: dict) -> str:
        if "nodes(ids" in query:
            return "enrich"
        if "type:REPOSITORY" in query:
            return "repos"
        return "issues" if "is:issue" in variables["q"] else "prs"

    def sizes(self, stage: str) -> list[int]:
        return [len(v["ids"]) if stage == "enrich" else v["n"] for s, v in self.calls if s == stage]

    def __call__(self, query, variables, tok, timeout):
        assert "mutation" not in query, "decision_index must never send a mutation"
        stage = self.stage(query, variables)
        with self.lock:
            self.calls.append((stage, copy.deepcopy(variables)))
            scripted = self.script.get(stage) or []
            hit = scripted.pop(0) if scripted else None
        wait = self.delay.get(stage, 0)
        if wait > timeout:  # what a real socket does: it gives up at the timeout it was given
            time.sleep(timeout)
            raise TimeoutError("timed out")
        time.sleep(wait)
        if isinstance(hit, Exception):
            raise hit
        if hit is not None:
            return hit
        rate = {"cost": 1, "remaining": self.remaining, "resetAt": "2027-01-15T09:00:00Z"}
        if stage == "enrich":
            ids = variables["ids"]
            if len(ids) > self.max_batch or self.poison & set(ids):
                return 502, {}, None
            nodes = []
            for i in ids:
                node = copy.deepcopy(self.enrich.get(i))
                with self.lock:
                    if node and i in self.unknown_once:
                        self.unknown_once.discard(i)
                        node.update(mergeable="UNKNOWN", mergeStateStatus="UNKNOWN")
                nodes.append(node)
            body = {"data": {"nodes": nodes, "rateLimit": rate}}
        else:
            rows = {"prs": self.prs, "issues": self.issues, "repos": self.repos}[stage]
            if variables["n"] > self.max_page:
                return 502, {}, None
            start = int(variables.get("after") or 0)
            more = start + variables["n"] < len(rows)
            count = "repositoryCount" if stage == "repos" else "issueCount"
            body = {"data": {"search": {count: len(rows) + self.inflate,
                                        "pageInfo": {"hasNextPage": more, "endCursor": str(start + variables["n"]) if more else None},
                                        "nodes": rows[start:start + variables["n"]]}, "rateLimit": rate}}
        if self.soft.get(stage):
            body["errors"] = self.soft[stage]
        return 200, {}, body


def boom(*a, **k):
    raise AssertionError("GitHub was called")


def settle() -> None:
    """Let the daemon workers of a call that was cut finish, so they cannot write into the next assertion."""
    for t in threading.enumerate():
        if t.name == "decision-index":
            t.join(timeout=5)


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.index = Path(tmp.name) / "decisions" / "index.json"
        for patch in (mock.patch.dict(os.environ, {"DASH_DECISIONS_INDEX": str(self.index)}),
                      mock.patch.object(d, "UNKNOWN_RETRY_DELAY_S", 0.0)):
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(settle)
        self.clock = 1_800_000_000.0
        self.cfg = config()
        self.gh = FakeGitHub()

    def ask(self, **kw) -> dict:
        kw.setdefault("http", self.gh)
        kw.setdefault("token", "t0ken-value")
        kw.setdefault("cfg", self.cfg)
        return d.queue(ROOT, now=lambda: self.clock, **kw)

    def kinds(self, doc: dict) -> dict:
        return {i["key"]: i["kinds"] for i in doc["items"]}

    def error_kinds(self, doc: dict) -> set:
        return {(e["stage"], e["kind"]) for e in doc["errors"]}


class Classification(Base):
    def test_each_kind_is_recognised_and_the_rest_stays_out(self):
        doc = self.ask()
        self.assertEqual(self.kinds(doc), {
            "pr:bamr87/bamr87#825": ["needs_amr", "ready_to_merge"],
            "issue:bamr87/bamr87#565": ["needs_amr"],
            "issue:bamr87/it-journey#900": ["needs_amr"],
            "pr:bamr87/bashcrawl#137": ["ratification"],                  # behind its base: not ready
            "pr:bamr87/gitorio#160": ["ratification", "ready_to_merge"],
            "pr:bamr87/bashos#38": ["dependabot"],                        # a minor bump, but its checks fail
            "pr:bamr87/lifehacker.dev#809": ["dependabot", "ready_to_merge"],   # a major bump that is green
            "pr:bamr87/bamr87#830": ["ready_to_merge"],                   # the ratification-record branch
            "pr:bamr87/bamr87#831": ["ready_to_merge"],                   # a repo with no checks at all
            "pr:bamr87/law-ai#210": ["ready_to_merge"],                   # a grouped update states no version
            "pr:bamr87/recon-engine#2": ["ready_to_merge"],               # templates and indexes are not records
            "pr:bamr87/zer0-mistakes#615": ["ready_to_merge"],
            "pr:bash-365/private-lab#3": ["ready_to_merge"],
        })
        self.assertEqual(doc["counts"], {"needs_amr": 3, "ratification": 2, "dependabot": 2, "ready_to_merge": 9})
        self.assertEqual((doc["total"], doc["status"], doc["complete"], doc["source"]), (13, "fresh", True, "live"))
        self.assertEqual([i["kind"] for i in doc["items"]],
                         ["needs_amr"] * 3 + ["ratification"] * 2 + ["dependabot"] * 2 + ["ready_to_merge"] * 6)
        out = {"pr:bamr87/fleet-observe#5": "a draft", "pr:bamr87/scripts#28": "held by agent:hold",
               "pr:bamr87/README#61": "changes requested", "pr:bamr87/zer0-mistakes#587": "conflicting"}
        for key, why in out.items():
            self.assertNotIn(key, self.kinds(doc), why)

    def test_every_row_says_why_and_carries_its_state(self):
        rows = {i["key"]: i for i in self.ask()["items"]}
        self.assertEqual(rows["pr:bamr87/bamr87#825"]["why"], ["labelled needs-amr", "mergeable, checks SUCCESS"])
        self.assertIn("docs/amendments/proposed/agent-merge-review-gate.md", rows["pr:bamr87/bashcrawl#137"]["why"][0])
        self.assertEqual(rows["pr:bamr87/bashcrawl#137"]["merge_state"], "BEHIND")
        self.assertEqual(rows["pr:bamr87/gitorio#160"]["governs"],
                         ["docs/amendments/0002-harness-studio-mission.md", "docs/constitution.md", "docs/adr/0004-studio.md"])
        self.assertEqual(rows["pr:bamr87/gitorio#160"]["review"], "APPROVED")
        self.assertEqual(rows["pr:bamr87/lifehacker.dev#809"]["why"][0], "major bump 7.2.3.1 → 8.0.5.2")
        self.assertEqual(rows["pr:bamr87/lifehacker.dev#809"]["bump"], {"from": "7.2.3.1", "to": "8.0.5.2", "major": True})
        self.assertEqual(rows["pr:bamr87/bashos#38"]["why"], ["checks FAILURE"])
        self.assertEqual(rows["pr:bamr87/bamr87#831"]["why"], ["mergeable, no checks"])
        self.assertIs(rows["pr:bash-365/private-lab#3"]["private"], True)
        self.assertNotIn("bump", rows["pr:bamr87/law-ai#210"])
        self.assertTrue(all(r["url"].startswith("https://github.com/") for r in rows.values()))

    def test_no_token_like_string_reaches_the_answer_or_the_index(self):
        doc = self.ask()
        row = next(i for i in doc["items"] if i["key"] == "pr:bamr87/bamr87#831")
        self.assertIn("[redacted]", row["title"])
        for text in (json.dumps(doc), self.index.read_text()):
            self.assertNotIn("ghp_", text)
            self.assertNotIn("t0ken-value", text)

    def test_bump_parser(self):
        for title, want in (
                ("build(deps-dev): bump activesupport from 7.2.3.1 to 8.0.5.2", ("7.2.3.1", "8.0.5.2", True)),
                ("chore(deps): update pydantic requirement from >=2.14.2 to >=2.14.3", ("2.14.2", "2.14.3", False)),
                ("chore(deps): Update github-pages requirement from ~> 232 to ~> 233", ("232", "233", True)),
                ("ci(deps): bump actions/checkout from 4 to 7 in the github-actions group", ("4", "7", True)),
                ("chore(deps): bump python from 3.14-slim to 3.15-slim in /docker", ("3.14-slim", "3.15-slim", False)),
                ("bump serde from 0.2.9 to 0.3.0", ("0.2.9", "0.3.0", True)),      # under 0.x the minor breaks
                ("bump tool from v1.2 to v1.3.", ("1.2", "1.3", False))):
            got = d.bump_of(title)
            self.assertEqual((got["from"], got["to"], got["major"]), want, title)
        self.assertIsNone(d.bump_of("chore(deps): bump the frontend-npm group in /frontend with 10 updates"))

    def test_a_title_stands_in_for_files_that_were_not_read(self):
        rec = {"type": "pr", "title": "docs(governance): propose amendment for the merge gate", "labels": [],
               "author": "bamr87", "head": "docs/x", "draft": False}
        kinds, why, extra = d.classify(rec, self.cfg)
        self.assertEqual((kinds, extra), (["ratification"], {"heuristic": True}))
        self.assertIn("not all read", why[0])
        read = {**rec, "enrich": {"mergeable": "MERGEABLE", "merge_state": "CLEAN", "checks": "SUCCESS",
                                  "files": 1, "files_read": 1, "governs": []}}
        self.assertEqual(d.classify(read, self.cfg)[0], ["ready_to_merge"], "its files were read and none is a record")

    def test_every_query_is_a_read(self):
        for q in (d.SCAN_Q, d.REPOS_Q, d.ENRICH_Q):
            self.assertTrue(q.lstrip().startswith("query("), q[:40])
            self.assertNotIn("mutation", q)
        source = (HERE / "decision_index.py").read_text(encoding="utf-8")
        self.assertEqual(source.count('"""query('), 3, "the three documents above are the only ones the module sends")

    def test_filters_and_limit(self):
        self.ask()
        doc = self.ask(kind="ready_to_merge", http=boom)
        self.assertEqual((doc["matched"], doc["total"], doc["filters"]), (9, 13, {"kind": "ready_to_merge"}))
        self.assertTrue(all("ready_to_merge" in i["kinds"] for i in doc["items"]))
        self.assertEqual([i["number"] for i in self.ask(repo="bamr87/bamr87", http=boom)["items"]], [825, 565, 831, 830])
        self.assertEqual(self.ask(repo="BAMR87", http=boom)["matched"], 4, "a bare repo name matches, whatever its case")
        doc = self.ask(limit=2, http=boom)
        self.assertEqual((doc["returned"], len(doc["items"]), doc["matched"]), (2, 2, 13))
        self.assertEqual(self.ask(limit=0, http=boom)["items"], [])
        for bad in ({"kind": "everything"}, {"refresh": "sometimes"}, {"repo": "../etc"}):
            with self.assertRaises(ValueError):
                self.ask(**bad)

    def test_inventory_per_repo_and_the_cross_check(self):
        doc = self.ask()
        rows = {r["repo"]: r for r in doc["repos"]}
        hub = rows["bamr87/bamr87"]
        self.assertEqual((hub["decisions"], hub["open_prs"], hub["open_issues"], hub["registry"]), (4, 3, 241, True))
        self.assertEqual(hub["by_kind"], {"needs_amr": 2, "ready_to_merge": 3})
        self.assertEqual(hub["prs_reported"], 4, "the repo counts a pull request the search did not return")
        zer0 = rows["bamr87/zer0-mistakes"]
        self.assertEqual((zer0["open_prs"], zer0["dependabot_prs"], zer0["conflicting_prs"], zer0["decisions"]), (2, 1, 1, 1))
        self.assertNotIn("prs_reported", zer0)
        self.assertIs(rows["bash-365/private-lab"]["private"], True)
        self.assertIs(rows["bamr87/bashos"]["registry"], False)
        self.assertNotIn("bamr87/quiet", rows)
        self.assertEqual(rows["bamr87/it-journey"]["decisions"], 1, "a repo with only a gate-labelled issue is listed")
        self.assertEqual(doc["inventory"], {"repos": 13, "open_prs": 15, "open_issues": 314, "dependabot_prs": 4,
                                            "draft_prs": 1, "failing_prs": 1, "conflicting_prs": 1})
        self.assertTrue(any("returned 15 open pull request(s) but the repos report 16" in w for w in doc["warnings"]))


class Cache(Base):
    def test_one_refresh_is_a_handful_of_queries(self):
        doc = self.ask()
        self.assertEqual(sorted(s for s, _ in self.gh.calls), ["enrich", "enrich", "issues", "prs", "repos"])
        self.assertEqual(doc["refresh"], {"attempted": True, "gained": True, "finished": True, "requests": 5,
                                          "enriched": 15, "rate": {"remaining": 4800, "reset_at": "2027-01-15T09:00:00Z"}})
        prs_q = next(v["q"] for s, v in self.gh.calls if s == "prs")
        self.assertEqual(prs_q, "user:bamr87 user:bash-365 is:pr is:open archived:false sort:updated-desc")
        self.assertIn('label:"needs-amr"', next(v["q"] for s, v in self.gh.calls if s == "issues"))

    def test_fresh_index_is_served_without_a_call(self):
        first = self.ask()
        self.clock += self.cfg["ttl_s"] - 1
        doc = self.ask(http=boom, token=boom)
        self.assertEqual((doc["status"], doc["source"], doc["age_s"]), ("fresh", "cache", self.cfg["ttl_s"] - 1))
        self.assertEqual(doc["refresh"], {"attempted": False})
        self.assertEqual(self.kinds(doc), self.kinds(first))

    def test_index_past_its_ttl_is_read_again(self):
        self.ask()
        self.gh.calls.clear()
        self.gh.prs = [p for p in self.gh.prs if p["number"] != 825]          # merged in the meantime
        self.clock += self.cfg["ttl_s"] + 1
        doc = self.ask()
        self.assertEqual((doc["status"], doc["source"], doc["age_s"]), ("fresh", "live", 0))
        self.assertEqual(sorted(s for s, _ in self.gh.calls), ["enrich", "enrich", "issues", "prs", "repos"])
        self.assertNotIn("pr:bamr87/bamr87#825", self.kinds(doc), "a complete scan drops what is no longer open")

    def test_never_serves_the_index_whatever_its_age(self):
        self.ask()
        self.clock += 3600
        doc = self.ask(refresh="never", http=boom, token=boom)
        self.assertEqual((doc["status"], doc["complete"], doc["source"], doc["total"]), ("stale", False, "cache", 13))
        self.assertTrue(all(i.get("stale") for i in doc["items"]))
        self.assertTrue(any("could not be refreshed" in w for w in doc["warnings"]))
        self.clock += self.cfg["max_stale_s"]
        doc = self.ask(refresh="never", http=boom)
        self.assertEqual(doc["status"], "expired")
        self.assertTrue(any("a lead to check, not a fact" in w for w in doc["warnings"]))

    def test_force_reads_inside_the_ttl(self):
        self.ask()
        self.gh.calls.clear()
        doc = self.ask(refresh="force")
        self.assertEqual((len(self.gh.calls), doc["status"]), (5, "fresh"))

    def test_a_changed_pull_request_is_read_again_and_nothing_else(self):
        self.ask()
        self.gh.calls.clear()
        self.clock += self.cfg["ttl_s"] - 60          # the scans are still fresh
        doc = self.ask(http=boom)
        self.assertEqual(doc["status"], "fresh")
        index = json.loads(self.index.read_text())
        index["stages"]["prs"]["at"] = 0              # the scan alone has to be read again
        self.index.write_text(json.dumps(index))
        next(p for p in self.gh.prs if p["id"] == "PR_07").update(updatedAt="2027-01-15T08:00:00Z", isDraft=False)
        self.gh.enrich["PR_07"].update(mergeStateStatus="CLEAN")
        self.clock -= self.cfg["ttl_s"] - 120         # …while the merge state is two minutes old
        doc = self.ask()
        self.assertEqual(self.gh.sizes("enrich"), [1], "only the pull request that moved")
        self.assertIn("pr:bamr87/fleet-observe#5", self.kinds(doc))
        self.assertEqual(doc["status"], "fresh")

    def test_index_file_is_owner_only_and_atomic(self):
        self.ask()
        self.assertEqual(stat.S_IMODE(self.index.stat().st_mode), 0o600)
        self.assertEqual([p.name for p in self.index.parent.iterdir()], ["index.json"], "no temp file left behind")
        self.assertEqual(json.loads(self.index.read_text())["schema"], d.INDEX_SCHEMA)


class Failure(Base):
    def stale_index(self) -> dict:
        first = self.ask()
        self.gh.calls.clear()
        self.clock += self.cfg["ttl_s"] + 300
        return first

    def test_no_token_and_no_index_is_unavailable_and_says_how_to_fix_it(self):
        doc = self.ask(token=lambda: None)
        self.assertEqual((doc["status"], doc["source"], doc["items"], doc["complete"]), ("unavailable", "none", [], False))
        self.assertEqual(self.error_kinds(doc), {("auth", "no_token")})
        self.assertIn("GH_TOKEN", doc["hint"])
        self.assertEqual(self.gh.calls, [])

    def test_a_refused_token_falls_back_to_the_index(self):
        first = self.stale_index()
        for stage in ("prs", "issues", "repos"):
            self.gh.script[stage] = [(401, {}, {"message": "Bad credentials"})]
        doc = self.ask()
        self.assertEqual((doc["status"], doc["source"], doc["age_s"]), ("stale", "cache", self.cfg["ttl_s"] + 300))
        self.assertEqual(self.kinds(doc), self.kinds(first))
        self.assertEqual({k for _, k in self.error_kinds(doc)}, {"auth"})
        self.assertIn("refused the token", doc["hint"])
        later = self.ask(refresh="never", http=boom)
        self.assertEqual({k for _, k in self.error_kinds(later)}, {"auth"}, "the index remembers why it is old")

    def test_rate_limit_is_named_with_its_reset(self):
        self.stale_index()
        for stage in ("prs", "issues", "repos"):
            self.gh.script[stage] = [(403, RATE_HEADERS, {"message": "API rate limit exceeded"})]
        doc = self.ask()
        self.assertEqual(doc["status"], "stale")
        err = next(e for e in doc["errors"] if e["stage"] == "prs")
        self.assertEqual(err["kind"], "rate_limited")
        self.assertIn("2027-01-15T09:00:00Z", err["message"])
        self.assertEqual(self.gh.sizes("prs"), [100], "a spent rate limit is not retried")
        self.gh.script = {s: [(200, {}, {"data": None, "errors": [{"type": "RATE_LIMITED", "message": "limit"}]})]
                          for s in ("prs", "issues", "repos")}
        self.assertEqual({k for _, k in self.error_kinds(self.ask())}, {"rate_limited"})

    def test_a_dead_network_falls_back_to_the_index(self):
        first = self.stale_index()
        for stage in ("prs", "issues", "repos"):
            self.gh.script[stage] = [urllib.error.URLError("no route to host")]
        doc = self.ask()
        self.assertEqual((doc["status"], doc["total"]), ("stale", first["total"]))
        self.assertEqual({k for _, k in self.error_kinds(doc)}, {"network"})
        self.assertIn("not reachable", doc["hint"])

    def test_a_502_halves_the_search_page_and_asks_again(self):
        prs, enrich = bulk(60)
        self.gh = FakeGitHub(prs=prs, enrich=enrich, issues=[], repos=[])
        self.gh.max_page = 30
        doc = self.ask()
        self.assertEqual(self.gh.sizes("prs"), [100, 50, 25, 25, 25])
        self.assertEqual((doc["status"], doc["counts"]["ready_to_merge"], doc["errors"]), ("fresh", 60, []))

    def test_a_failed_enrichment_batch_is_split(self):
        self.gh.max_batch = 3
        doc = self.ask()
        self.assertEqual((doc["status"], doc["parts"]["enrich"]["have"]), ("fresh", 15))
        self.assertEqual(sorted(self.gh.sizes("enrich")), [2, 2, 2, 3, 3, 3, 5, 5, 5, 10])

    def test_one_unreadable_pull_request_does_not_take_the_rest_down(self):
        self.gh.poison = {"PR_15"}
        doc = self.ask()
        self.assertEqual(doc["status"], "partial")
        self.assertEqual((doc["parts"]["enrich"]["pending"], doc["parts"]["enrich"]["never_read"]), (1, 1))
        self.assertIn(("enrich", "upstream_timeout"), self.error_kinds(doc))
        self.assertTrue(any("not current for 1 of 15" in w for w in doc["warnings"]))
        self.assertEqual(doc["counts"]["ready_to_merge"], 8, "the others were read")
        self.assertNotIn("pr:bamr87/gitorio#160", self.kinds(doc))
        self.gh.poison.clear()
        self.gh.calls.clear()
        doc = self.ask()
        self.assertEqual([(s, v.get("ids")) for s, v in self.gh.calls], [("enrich", ["PR_15"])], "the next call resumes")
        self.assertEqual((doc["status"], self.kinds(doc)["pr:bamr87/gitorio#160"]),
                         ("fresh", ["ratification", "ready_to_merge"]))

    def test_partial_graphql_errors_keep_the_data_and_are_reported(self):
        self.gh.soft["prs"] = [{"type": "FORBIDDEN", "message": "Resource not accessible by ghp_abcdefghijklmnopqrstuvwxyz0123"}]
        doc = self.ask()
        self.assertEqual((doc["status"], doc["total"]), ("fresh", 13))
        err = next(e for e in doc["errors"] if e["kind"] == "graphql_partial")
        self.assertEqual((err["stage"], "[redacted]" in err["message"], "ghp_" in err["message"]), ("prs", True, False))

    def test_a_low_rate_limit_skips_the_slow_reads(self):
        self.gh.remaining = 50
        doc = self.ask()
        self.assertEqual(self.gh.sizes("enrich"), [])
        self.assertEqual(doc["status"], "partial")
        self.assertIn(("enrich", "rate_floor"), self.error_kinds(doc))
        self.assertIn("min_rate_remaining", doc["hint"])
        self.assertEqual((doc["counts"]["needs_amr"], doc["counts"]["ready_to_merge"]), (3, 0), "labels need no slow read")
        self.assertEqual(self.kinds(doc)["pr:bamr87/lifehacker.dev#809"], ["dependabot"], "a major bump is in the title")
        self.assertEqual(self.kinds(doc)["pr:bamr87/bashcrawl#137"], ["ratification"], "and so is an amendment")

    def test_a_search_that_returns_less_than_it_counted_is_not_called_complete(self):
        self.gh.inflate = 1200
        doc = self.ask()
        self.assertEqual(doc["status"], "partial")
        self.assertIn(("prs", "truncated"), self.error_kinds(doc))
        self.assertIsNone(doc["parts"]["prs"]["age_s"], "the scan never completed")
        self.assertEqual(doc["counts"]["needs_amr"], 3, "what it did return is used")

    def test_an_answer_with_no_search_in_it_never_empties_the_index(self):
        first = self.stale_index()
        for stage in ("prs", "issues"):
            self.gh.script[stage] = [(200, {}, {"data": {"search": None}, "errors": [{"message": "Something odd"}]})]
        doc = self.ask()
        self.assertEqual(doc["total"], first["total"], "a null search is not 'nothing is open'")
        self.assertIn(("prs", "bad_response"), self.error_kinds(doc))
        self.assertFalse(doc["parts"]["prs"]["fresh"])
        self.assertEqual(d.DEFAULTS["labels"], {"gate": ["needs-amr"], "hold": ["agent:hold", "blocked"]})

    def test_an_incomplete_scan_keeps_what_it_did_not_reach(self):
        prs, enrich = bulk(30)
        self.gh = FakeGitHub(prs=prs, enrich=enrich, issues=[], repos=[])
        self.cfg = config(scan_page=10)
        self.ask()
        self.clock += self.cfg["ttl_s"] + 1
        self.gh.script["prs"] = [None, (500, {}, {"message": "boom"})]
        doc = self.ask()
        self.assertEqual((doc["status"], doc["total"]), ("partial", 30), "page one is new, the rest is the old index")
        self.assertEqual(sum(1 for i in doc["items"] if i.get("stale")), 20)
        self.assertIn(("prs", "http"), self.error_kinds(doc))

    def test_a_corrupt_or_foreign_index_is_set_aside_and_rebuilt(self):
        self.index.parent.mkdir(parents=True)
        for text, why in (("{not json", "could not be read"), (json.dumps({"schema": "other/v9", "prs": []}), "is not a")):
            self.index.write_text(text)
            doc = self.ask(refresh="force")
            self.assertTrue(any(why in w for w in doc["warnings"]), doc["warnings"])
            self.assertEqual((doc["status"], doc["total"]), ("fresh", 13))
            self.assertEqual(json.loads(self.index.read_text())["schema"], d.INDEX_SCHEMA)
        self.index.write_text("{not json")
        doc = self.ask(refresh="never", http=boom)
        self.assertEqual(doc["status"], "unavailable", "an index that cannot be trusted is not served")

    def test_an_unwritable_index_still_answers(self):
        self.index.parent.mkdir(parents=True)
        blocker = self.index.parent / "file"
        blocker.write_text("")
        with mock.patch.dict(os.environ, {"DASH_DECISIONS_INDEX": str(blocker / "index.json")}):
            doc = self.ask()
        self.assertEqual((doc["status"], doc["total"]), ("fresh", 13))
        self.assertTrue(any("could not be saved" in w for w in doc["warnings"]))

    def test_an_index_built_for_other_owners_or_labels_is_rebuilt(self):
        self.ask()
        self.gh.calls.clear()
        self.cfg = config(owners=["bamr87"])
        doc = self.ask(refresh="never", http=boom)
        self.assertEqual(doc["status"], "unavailable", "another fleet's index is not this one's answer")
        self.assertTrue(any("other owners or gate labels" in w for w in doc["warnings"]))
        doc = self.ask()
        self.assertEqual((doc["status"], len(self.gh.calls)), ("fresh", 5))
        self.assertEqual(next(v["q"] for s, v in self.gh.calls if s == "prs").split(" is:pr")[0], "user:bamr87")

    def test_a_token_that_dies_midway_stops_the_batches_still_queued(self):
        self.cfg = config(enrich_batch=1, concurrency=1)
        self.gh.script["enrich"] = [None, (401, {}, {"message": "Bad credentials"})]
        doc = self.ask()
        self.assertEqual(self.gh.sizes("enrich"), [1, 1], "thirteen more were queued and never sent")
        self.assertEqual((doc["status"], doc["parts"]["enrich"]["have"]), ("partial", 1))
        self.assertEqual([e for e in doc["errors"] if e["stage"] == "enrich"],
                         [{"stage": "enrich", "kind": "auth", "message": "GitHub refused the token (401)", "prs": 1}])

    def test_no_owners_is_reported_not_guessed(self):
        self.cfg = config(owners=[])
        doc = self.ask()
        self.assertEqual((doc["status"], self.error_kinds(doc), self.gh.calls), ("unavailable", {("config", "no_owners")}, []))


class TimeBudget(Base):
    def test_a_slow_github_returns_a_partial_answer_on_time_and_the_next_call_resumes(self):
        self.gh.delay = {"enrich": 30.0}
        t0 = time.monotonic()
        doc = self.ask(budget_s=1.0)
        took = time.monotonic() - t0
        self.assertLess(took, 2.5, "the budget is a wall clock")
        self.assertEqual((doc["status"], doc["complete"], doc["source"]), ("partial", False, "live"))
        self.assertIn(("budget", "budget"), self.error_kinds(doc))
        self.assertIn("tools/dash decisions refresh", doc["hint"])
        self.assertEqual(doc["parts"]["enrich"]["pending"], 15)
        self.assertEqual((doc["counts"]["needs_amr"], doc["counts"]["dependabot"]), (3, 1), "labels and titles are already in")
        self.assertTrue(doc["parts"]["prs"]["fresh"] and doc["parts"]["issues"]["fresh"])
        settle()
        self.gh.delay = {}
        self.gh.calls.clear()
        doc = self.ask(budget_s=5.0)
        self.assertEqual({s for s, _ in self.gh.calls}, {"enrich"}, "the scans are still fresh: only the merge state is read")
        self.assertEqual((doc["status"], doc["total"], doc["source"]), ("fresh", 13, "live"))

    def test_a_slow_search_still_returns_the_fast_one(self):
        self.gh.delay = {"prs": 30.0}
        t0 = time.monotonic()
        doc = self.ask(budget_s=1.0)
        self.assertLess(time.monotonic() - t0, 2.5)
        self.assertEqual(doc["status"], "partial")
        self.assertEqual(self.kinds(doc), {"issue:bamr87/bamr87#565": ["needs_amr"], "issue:bamr87/it-journey#900": ["needs_amr"]})
        self.assertFalse(doc["parts"]["prs"]["fresh"])

    def test_past_the_budget_the_old_index_is_the_answer(self):
        first = self.ask()
        self.clock += self.cfg["ttl_s"] + 1
        self.gh.delay = {"prs": 30.0, "issues": 30.0, "repos": 30.0}
        t0 = time.monotonic()
        doc = self.ask(budget_s=1.0)
        self.assertLess(time.monotonic() - t0, 2.5)
        self.assertEqual((doc["status"], doc["source"], doc["total"]), ("stale", "cache", first["total"]))
        self.assertIn("budget", {k for _, k in self.error_kinds(doc)})

    def test_one_refresh_at_a_time(self):
        self.ask()
        self.clock += self.cfg["ttl_s"] + 1
        self.gh.calls.clear()
        self.assertTrue(d._REFRESH_LOCK.acquire(timeout=1))
        try:
            t0 = time.monotonic()
            doc = self.ask(budget_s=1.0)
        finally:
            d._REFRESH_LOCK.release()
        self.assertLess(time.monotonic() - t0, 2.0)
        self.assertEqual((doc["status"], self.gh.calls, self.error_kinds(doc)), ("stale", [], {("refresh", "busy")}))

    def test_mergeable_unknown_is_asked_once_more(self):
        self.gh.unknown_once = {"PR_05"}
        doc = self.ask()
        self.assertIn(["PR_05"], [v["ids"] for s, v in self.gh.calls if s == "enrich"])
        self.assertEqual(self.kinds(doc)["pr:bamr87/zer0-mistakes#615"], ["ready_to_merge"])

    def test_the_budget_goes_to_what_can_be_decided_first(self):
        prs = {"a": {"id": "a", "repo": "r/a", "number": 1, "draft": True, "updated_at": "u"},
               "b": {"id": "b", "repo": "r/b", "number": 2, "draft": False, "updated_at": "u",
                     "enrich": {"at": self.clock - 400, "for_updated_at": "u"}},
               "c": {"id": "c", "repo": "r/c", "number": 3, "draft": False, "updated_at": "u"},
               "d": {"id": "d", "repo": "r/d", "number": 4, "draft": False, "updated_at": "u",
                     "enrich": {"at": self.clock - 10, "for_updated_at": "u"}}}
        self.assertEqual(d.enrich_order(prs, 300, self.clock, False), ["c", "b", "a"], "never read, then oldest, drafts last")
        self.assertEqual(d.enrich_order(prs, 300, self.clock, True), ["c", "b", "d", "a"])

    def test_a_late_answer_cannot_change_a_returned_result(self):
        col = d.Collector()
        col.enrich({"a": {"at": 1}})
        col.close()
        col.enrich({"b": {"at": 2}})
        col.scan("prs", {"nodes": []})
        col.error("prs", "http", "late")
        self.assertEqual((sorted(col.enriched), col.scans, col.errors), (["a"], {}, []))

    def test_a_crashing_task_is_reported_and_never_hangs_the_wait(self):
        pool = d.Pool(2, d.Budget(5))
        done = []
        pool.add(lambda: 1 / 0)
        pool.add(lambda: done.append(1))
        self.assertTrue(pool.wait())
        self.assertEqual((done, pool.unfinished()), ([1], 0))
        self.assertIn("ZeroDivisionError", pool.crashed[0])


class Config(unittest.TestCase):
    def test_fleet_yml_states_the_defaults(self):
        import yaml
        block = yaml.safe_load((ROOT / "_data" / "fleet.yml").read_text(encoding="utf-8")).get("decisions")
        self.assertIsInstance(block, dict, "_data/fleet.yml has a decisions: block")
        self.assertEqual(block, d.DEFAULTS, "the block and decision_index.DEFAULTS say the same thing")
        cfg = d.load_config(ROOT)
        self.assertIn("bamr87", cfg["owners"])
        self.assertIn("bamr87/bamr87", cfg["registry"])
        self.assertLess(cfg["budget_s"], 20, "under the MCP client's 20 s timeout")

    def test_bad_values_fall_back_or_are_clamped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "_data").mkdir()
            (root / "_data" / "fleet.yml").write_text(
                "hub: {repo: acme/hub, owners: [acme, 'bad owner!']}\n"
                "decisions: {ttl_s: 1, budget_s: 9999, concurrency: lots, labels: {gate: needs-amr},\n"
                "            ratification: {paths: ['(unclosed', 'docs/rules\\.md$']}}\n")
            (root / "_data" / "projects.yml").write_text("- {name: site, repo_url: 'https://github.com/acme/site.git'}\n")
            cfg = d.load_config(root)
        self.assertEqual((cfg["ttl_s"], cfg["budget_s"], cfg["concurrency"]), (30, d.BUDGET_MAX_S, d.DEFAULTS["concurrency"]))
        self.assertEqual((cfg["owners"], cfg["registry"]), (["acme"], ["acme/hub", "acme/site"]))
        self.assertEqual(cfg["labels"], {"gate": ["needs-amr"], "hold": ["agent:hold", "blocked"]}, "a string is not a list")
        self.assertEqual(len(d._rx(cfg["ratification"]["paths"])), 1, "a pattern that does not compile matches nothing")

    def test_a_missing_fleet_yml_leaves_the_defaults_and_no_owners(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = d.load_config(Path(tmp))
        self.assertEqual((cfg["ttl_s"], cfg["owners"], cfg["registry"]), (d.DEFAULTS["ttl_s"], [], []))


class Cli(Base):
    def run_cli(self, *argv) -> tuple[int, str]:
        out = io.StringIO()
        with mock.patch.object(d, "_http", self.gh), mock.patch.object(d, "resolve_token", lambda: "t0ken-value"), \
                mock.patch.object(d.time, "time", lambda: self.clock), contextlib.redirect_stdout(out):
            code = d.main(list(argv))
        return code, out.getvalue()

    def test_queue_refresh_status_and_their_exit_codes(self):
        code, text = self.run_cli("status")
        self.assertEqual(code, 1, "nothing to serve")
        self.assertIn("status unavailable", text)
        code, text = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("FRESH", text)
        self.assertIn("NEEDS AMR (", text)
        self.assertIn("bamr87/bashcrawl#137", text)
        code, text = self.run_cli("--kind", "dependabot", "--json", "--refresh", "never")
        doc = json.loads(text)
        self.assertEqual((code, doc["schema"], doc["matched"], doc["source"]), (0, d.SCHEMA, 2, "cache"))
        code, text = self.run_cli("queue", "--repos", "--limit", "0", "--refresh", "never")
        self.assertIn("REPOS (", text)
        code, text = self.run_cli("status")
        self.assertEqual(code, 0)
        self.assertIn("enrich  fresh", text)
        self.assertNotIn("t0ken-value", text)

    def test_refresh_fails_loudly_when_it_cannot_complete(self):
        code, text = self.run_cli("refresh")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.gh.calls), 5)
        self.gh.script = {s: [(401, {}, {"message": "Bad credentials"})] for s in ("prs", "issues", "repos")}
        code, text = self.run_cli("refresh")
        self.assertEqual(code, 1, "a scheduled refresh that did not complete must not look green")
        self.assertIn("hint:", text)

    def test_a_bad_flag_is_a_usage_error(self):
        with self.assertRaises(SystemExit) as caught, contextlib.redirect_stderr(io.StringIO()):
            d.main(["--kind", "everything"])
        self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main(verbosity=1)
