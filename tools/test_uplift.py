#!/usr/bin/env python3
"""Fleet uplift (tools/uplift.py, docs/UPLIFT.md): what one repo improved that the others still lack.

The scan decides everything from file contents, so these tests build a small
fleet of real git repositories and hold the decisions that make its output
safe to act on:

  * a repo that changed a file other repos still hold in an earlier version is
    a candidate, with exactly those repos behind, through a chain of edits too;
  * content that is the hub's own, that arrived on a fan-out branch, that
    carries a newer kit stamp, or that several repos already hold is a rollout
    in flight, never one repo's improvement;
  * a seed several repos each filled in differently is a fork, not a fix;
  * an empty file, a rename, a reverted edit, an ignored path and a bot's
    commit prove nothing and report nothing;
  * a repo that cannot be read is said to be unread, never quiet; an external
    upstream and an archived repo are never compared;
  * `file` previews offline, files only the bytes a person previewed, never
    files from a repo less visible than the hub, withholds a credential-shaped
    body, never files a candidate twice and stops at its caps.

Offline: git in a temp dir, a stubbed gh. No network, no model.

    python3 tools/test_uplift.py
"""
from __future__ import annotations

import atexit
import contextlib
import datetime as dt
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import uplift  # noqa: E402

NOW = dt.datetime(2026, 11, 20, 12, 0, tzinfo=dt.timezone.utc)
SEED, EARLY, RECENT = "2026-10-01T12:00:00+00:00", "2026-11-10T12:00:00+00:00", "2026-11-15T12:00:00+00:00"
OWNED = ("a", "b", "c", "d", "e")
FEATURES = "schema: features/v1\nfeatures:\n"
KIT_OLD, KIT_NEW = "# kit: demo v1.0.0\nbody\n", "# kit: demo v1.1.0\nbody\n"


def feature(fid: str, title: str, status: str = "shipped") -> str:
    return f"  - id: {fid}\n    title: {title}\n    status: {status}\n"


class Fleet:
    """A hub and its repos as real git repositories under one temp dir."""

    def __init__(self, tmp: str) -> None:
        self.hub = Path(tmp) / "hub"
        self.projects = self.hub / "projects"
        self.rows: list[dict] = []
        self.env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_AUTHOR_NAME": "Amr", "GIT_AUTHOR_EMAIL": "amr@example.invalid",
                    "GIT_COMMITTER_NAME": "Amr", "GIT_COMMITTER_EMAIL": "amr@example.invalid"}

    def git(self, repo: Path, *args: str, when: str | None = None, author: str | None = None) -> str:
        env = dict(self.env)
        if when:
            env.update(GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
        if author:
            env["GIT_AUTHOR_NAME"] = author
        return subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args], check=True,
                              capture_output=True, text=True, env=env).stdout

    def init(self, path: Path) -> Path:
        path.mkdir(parents=True)
        self.git(path, "init", "-q", "-b", "main")
        return path

    def repo(self, name: str, owner: str = "bamr87", status: str = "active", checkout: bool = True) -> Path:
        self.rows.append({"name": name, "submodule_path": f"projects/{name}", "branch": "main",
                          "repo_url": f"https://github.com/{owner}/{name}", "status": status})
        return self.init(self.projects / name) if checkout else self.projects / name

    def write(self, repo: Path, files: dict[str, str | bytes | None]) -> None:
        for rel, content in files.items():
            target = repo / rel
            if content is None:
                target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content if isinstance(content, bytes) else content.encode())

    def commit(self, repo: Path, files: dict[str, str | bytes | None], message: str, when: str,
               author: str | None = None) -> None:
        self.write(repo, files)
        self.git(repo, "add", "-A", ".")
        self.git(repo, "commit", "-q", "-m", message, when=when, author=author)
        self.publish(repo)

    def merge(self, repo: Path, branch: str, files: dict[str, str | bytes | None], number: int, title: str,
              when: str) -> None:
        self.git(repo, "checkout", "-q", "-b", branch)
        self.write(repo, files)
        self.git(repo, "add", "-A", ".")
        self.git(repo, "commit", "-q", "-m", "wip", when=when)
        self.git(repo, "checkout", "-q", "main")
        self.git(repo, "merge", "-q", "--no-ff", branch, "-m",
                 f"Merge pull request #{number} from bamr87/{branch}\n\n{title}", when=when)
        self.publish(repo)

    def publish(self, repo: Path) -> None:
        self.git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")

    def registry(self, uplift_cfg: dict | None = None) -> None:
        data = self.hub / "_data"
        data.mkdir(parents=True, exist_ok=True)
        (data / "projects.yml").write_text(yaml.safe_dump(self.rows))
        fleet = {"hub": {"repo": "bamr87/hub", "default_branch": "main", "owners": ["bamr87"]}}
        if uplift_cfg is not None:
            fleet["uplift"] = uplift_cfg
        (data / "fleet.yml").write_text(yaml.safe_dump(fleet))


def build(tmp: str) -> Fleet:
    f = Fleet(tmp)
    hub = f.init(f.hub)
    shared = {
        "ci.yml": "v1\n", "chain.txt": "A\n", "revert.txt": "A\n", "roll.txt": "old\n", "seed.yml": "placeholder\n",
        "kit.yml": "# kit: demo v1.0.0\nbody\n", "kitup.yml": "# kit: demo v1.0.0\nbody\n", "kitedit.yml": KIT_OLD,
        "hubsrc.txt": "hub source v1\n", "hubnew.txt": "hub old\n", "gone.txt": "delete me\n", "empty.py": "",
        "CHANGELOG.md": "log\n", "bot.txt": "x\n", "fan.txt": "x\n", "two.txt": "base\n", "land.txt": "o\n",
        "moved.txt": "move me, a file long enough for git to follow\nacross a rename\n", "image.bin": b"\0\1\2old",
    }
    for name in OWNED:
        repo = f.repo(name)
        files = dict(shared)
        files["features/features.yml"] = FEATURES + feature(f"{name.upper()}-001", f"{name} first feature")
        if name == "a":
            files["only-a.txt"] = "mine\n"
            files["features/features.yml"] += feature("A-002", "a second feature", "planned")
        if name == "b":
            files["chain.txt"] = "B\n"                     # b already holds what a passes through
            del files["features/features.yml"]
        f.commit(repo, files, "chore: seed", SEED)
    f.commit(f.repo("ext", owner="someone-else"), dict(shared), "chore: seed", SEED)
    f.commit(f.repo("old", status="archived"), dict(shared), "chore: seed", SEED)
    f.repo("ghost", checkout=False)
    a, b, c, d, e = (f.projects / n for n in OWNED)

    f.merge(a, "fix/ci", {"ci.yml": "v2\n"}, 7, "fix(ci): pin the action", RECENT)
    f.commit(a, {"chain.txt": "B\n", "revert.txt": "B\n", "kitedit.yml": KIT_NEW}, "fix: first pass", EARLY)
    f.commit(a, {"chain.txt": "C\n", "revert.txt": "A\n", "kit.yml": "# kit: demo v1.0.0\nbody2\n",
                 "kitup.yml": "# kit: demo v1.1.0\nbody\n", "hubsrc.txt": "improved\n", "hubnew.txt": "hub new\n",
                 "gone.txt": None, "empty.py": "code\n", "CHANGELOG.md": "log\nmore\n", "only-a.txt": "mine too\n",
                 "image.bin": b"\0\1\2new", "roll.txt": "new\n", "seed.yml": "a's\n", "two.txt": "a way\n",
                 "land.txt": "n\n", "kitedit.yml": KIT_NEW.replace("body", "body fixed")}, "fix: second pass (#12)", RECENT)
    f.git(a, "mv", "moved.txt", "moved2.txt")
    f.commit(a, {}, "refactor: rename", RECENT)
    f.commit(a, {"bot.txt": "y\n"}, "build(deps): bump x", RECENT, author="dependabot[bot]")
    f.merge(a, "chore/sdlc-kit", {"fan.txt": "y\n"}, 9, "chore(sdlc): adopt the sdlc kit (kit v9.9.9)", RECENT)
    f.commit(a, {"features/features.yml": FEATURES + feature("A-001", "a first feature")
                 + feature("A-002", "a second feature") + feature("A-003", "a third feature", "planned")},
             "docs: features", RECENT)

    f.commit(b, {"roll.txt": "new\n", "seed.yml": "b's\n", "two.txt": "b way\n", "land.txt": "n\n", "kitedit.yml": KIT_NEW,
                 "features/features.yml": FEATURES + feature("B-001", "b one") + feature("B-002", "b two")},
             "feat: b work", RECENT)
    f.commit(c, {"roll.txt": "new\n", "seed.yml": "c's\n", "land.txt": "n\n", "kitedit.yml": KIT_NEW}, "feat: c work", RECENT)
    f.commit(d, {"land.txt": "n\n", "kitedit.yml": KIT_NEW}, "feat: land", RECENT)
    f.commit(e, {"land.txt": "n\n"}, "feat: land", RECENT)
    for repo in (c, d, e):
        name = repo.name
        f.commit(repo, {"features/features.yml": FEATURES + feature(f"{name.upper()}-001", f"{name} first feature")
                        + feature(f"{name.upper()}-002", "Missions in constitution")}, "docs: missions", RECENT)

    f.write(hub, {"ci.yml": "v1\n", "templates/demo/hubsrc.txt": "hub source v1\n", "templates/demo/hubnew.txt": "hub new\n",
                  "tools/fanout.sh": '#!/usr/bin/env bash\ncase "$KIT" in\n  sdlc)\n    BRANCH="chore/sdlc-kit"\n    ;;\n'
                                     '  backlog)\n    BRANCH="$FANOUT_BRANCH"\n    ;;\nesac\n'})
    f.registry()
    f.write(hub, {"features/features.yml": FEATURES + feature("HUB-001", "hub first feature")})
    f.git(hub, "add", "ci.yml", "templates", "tools", "_data", "features")
    f.git(hub, "commit", "-q", "-m", "chore: hub", when=SEED)
    f.write(hub, {"features/features.yml": FEATURES + feature("HUB-001", "hub first feature")
                  + feature("HUB-002", "hub second feature")})
    f.git(hub, "add", "features")
    f.git(hub, "commit", "-q", "-m", "feat: a hub feature", when=RECENT)
    f.publish(hub)
    return f


_TEMPLATE: tempfile.TemporaryDirectory | None = None


def fleet_copy(tmp: str) -> Fleet:
    """The fixture fleet, built once for the run and copied: a build is about a hundred git calls."""
    global _TEMPLATE
    if _TEMPLATE is None:
        _TEMPLATE = tempfile.TemporaryDirectory()
        atexit.register(_TEMPLATE.cleanup)
        build(_TEMPLATE.name)
    shutil.copytree(Path(_TEMPLATE.name) / "hub", Path(tmp) / "hub", symlinks=True)
    return Fleet(tmp)


def entry(doc: dict, path: str, section: str = "candidates") -> dict:
    rows = [e for e in doc[section] if e["path"] == path]
    assert len(rows) == 1, f"{path}: {len(rows)} rows in {section}"
    return rows[0]


def paths(doc: dict, section: str) -> set[str]:
    return {e["path"] for e in doc[section]}


class StubGh(uplift.Gh):
    def __init__(self, visibility: dict[str, str] | None = None, issues: list[dict] | None = None) -> None:
        self.vis = {"bamr87/hub": "public", "bamr87/a": "public", **(visibility or {})}
        self.existing = issues or []
        self.created: list[dict] = []
        self.labels: list[str] = []

    def visibility(self, nwo: str) -> str | None:
        return self.vis.get(nwo)

    def issues(self, repo: str, label: str) -> list[dict]:
        return list(self.existing)

    def ensure_label(self, repo: str, label: str) -> None:
        self.labels.append(label)

    def create_issue(self, repo: str, title: str, body_file: Path, labels: list[str]) -> str:
        self.created.append({"repo": repo, "title": title, "body": Path(body_file).read_text(), "labels": labels})
        return f"https://github.com/{repo}/issues/{100 + len(self.created)}"


class Scan(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.fleet = fleet_copy(cls.tmp.name)
        cls.doc, cls.members = uplift.scan(cls.fleet.hub, cls.fleet.projects, now=NOW)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_a_change_others_still_hold_the_earlier_version_of_is_a_candidate(self) -> None:
        e = entry(self.doc, "ci.yml")
        self.assertEqual(e["behind"], ["b", "c", "d", "e", "hub"], "the hub is a member: the registry lists submodules only")
        self.assertEqual((e["holders"], e["route"], e["action"], e["class"]), (["a"], "patch", "edit", "candidate"))
        self.assertTrue(e["key"].startswith("u-") and len(e["key"]) == 12)

    def test_a_merge_commit_is_read_as_its_pull_request(self) -> None:
        src = entry(self.doc, "ci.yml")["from"]
        self.assertEqual((src["repo"], src["title"]), ("a", "fix(ci): pin the action"))
        self.assertEqual(src["url"], "https://github.com/bamr87/a/pull/7")
        self.assertEqual(entry(self.doc, "kit.yml")["from"]["url"], "https://github.com/bamr87/a/pull/12", "a squash names its number")

    def test_a_chain_of_edits_is_one_move_and_every_earlier_version_is_behind(self) -> None:
        e = entry(self.doc, "chain.txt")
        self.assertEqual(e["behind"], ["b", "c", "d", "e"], "b holds the middle version, the rest the first")
        self.assertEqual(len(e["ancestors"]), 2)
        self.assertEqual(e["origins"][0]["commits"], 2)

    def test_what_proves_nothing_reports_nothing(self) -> None:
        seen = paths(self.doc, "candidates") | paths(self.doc, "rollouts")
        for path, why in (("revert.txt", "it came back to where it started"), ("empty.py", "an empty file is everyone's"),
                          ("CHANGELOG.md", "an ignored path"), ("bot.txt", "a bot's commit"),
                          ("moved.txt", "a rename is not a deletion"), ("only-a.txt", "nobody else holds it")):
            with self.subTest(path=path):
                self.assertNotIn(path, seen, why)

    def test_a_deletion_others_still_hold_is_a_candidate(self) -> None:
        e = entry(self.doc, "gone.txt")
        self.assertEqual((e["action"], e["post"], e["behind"]), ("delete", None, ["b", "c", "d", "e"]))

    def test_a_binary_file_is_compared_and_never_printed(self) -> None:
        e = entry(self.doc, "image.bin")
        self.assertEqual(e["behind"], ["b", "c", "d", "e"])
        self.assertEqual(uplift.change_diff(e, self.members, 50), "(binary file: 6 bytes before, 6 bytes after)")

    def test_the_route_is_the_kit_when_the_earlier_version_is_the_hubs_or_stamped(self) -> None:
        stamped = entry(self.doc, "kit.yml")
        self.assertEqual((stamped["route"], stamped["kit"]), ("kit", {"name": "demo", "version": "1.0.0"}))
        hub_owned = entry(self.doc, "hubsrc.txt")
        self.assertEqual((hub_owned["route"], hub_owned["hub_source"]), ("kit", "templates/demo/hubsrc.txt"))
        self.assertIn("Do not patch the copies", uplift.route_text(stamped))
        self.assertIn("templates/demo/hubsrc.txt", uplift.route_text(hub_owned))

    def test_the_hubs_own_content_a_newer_kit_stamp_a_fanout_branch_and_many_holders_are_rollouts(self) -> None:
        candidates = paths(self.doc, "candidates")
        for path, why in (("hubnew.txt", "the new content is a hub source"), ("kitup.yml", "a newer kit stamp arrived"),
                          ("fan.txt", "it came in on a fan-out branch"), ("roll.txt", "three repos hold it")):
            with self.subTest(path=path):
                self.assertNotIn(path, candidates, why)
                self.assertEqual(entry(self.doc, path, "rollouts")["class"], "rollout")
        self.assertEqual(entry(self.doc, "kitup.yml", "rollouts")["kit"], {"name": "demo", "version": "1.1.0"})
        roll = entry(self.doc, "roll.txt", "rollouts")
        self.assertEqual((roll["holders"], roll["behind"]), (["a", "b", "c"], ["d", "e"]))
        self.assertIn("kit `demo` v1.1.0 arriving", uplift.route_text(entry(self.doc, "kitup.yml", "rollouts")))

    def test_an_edit_on_top_of_a_kit_upgrade_is_the_repos_own(self) -> None:
        # a took kit demo v1.1.0 and then fixed it: the stamp did not move with the fix, so the fix is a's own
        e = entry(self.doc, "kitedit.yml")
        self.assertEqual((e["route"], e["kit"], e["behind"]), ("kit", {"name": "demo", "version": "1.1.0"}, ["b", "c", "d", "e"]))
        diff = uplift.change_diff(e, self.members, 50)
        self.assertIn("-body\n+body fixed", diff)
        self.assertNotIn("v1.0.0", diff, "the diff starts at the version most repos behind hold: the upgrade, not the old seed")
        upgrade = entry(self.doc, "kitedit.yml", "rollouts")
        self.assertEqual((upgrade["holders"], upgrade["behind"], upgrade["kit"]["version"]), (["b", "c", "d"], ["e"], "1.1.0"))

    def test_a_rollout_that_reached_everyone_is_counted_not_listed(self) -> None:
        self.assertNotIn("land.txt", paths(self.doc, "rollouts") | paths(self.doc, "candidates"))
        self.assertEqual(self.doc["counts"]["landed"], 1)

    def test_a_seed_three_repos_filled_in_differently_is_a_fork(self) -> None:
        self.assertNotIn("seed.yml", paths(self.doc, "candidates"))
        (fork,) = self.doc["forks"]
        self.assertEqual((fork["path"], fork["variants"], fork["repos"], fork["behind"]),
                         ("seed.yml", 3, ["a", "b", "c"], ["d", "e"]))

    def test_two_repos_changing_one_file_differently_are_both_candidates_and_say_so(self) -> None:
        rows = [e for e in self.doc["candidates"] if e["path"] == "two.txt"]
        self.assertEqual(sorted(e["from"]["repo"] for e in rows), ["a", "b"])
        self.assertEqual({e["variants"] for e in rows}, {2})
        self.assertEqual({tuple(e["behind"]) for e in rows}, {("c", "d", "e")})

    def test_external_archived_and_unread_repos(self) -> None:
        self.assertEqual({s["repo"]: s["why"] for s in self.doc["skipped"]},
                         {"ext": "external upstream (someone-else/ext)", "old": "archived"})
        everyone = {r for e in self.doc["candidates"] + self.doc["rollouts"] for r in e["behind"] + e["holders"]}
        self.assertFalse({"ext", "old"} & everyone, "an upstream we do not own and an archived repo are never compared")
        ghost = next(r for r in self.doc["repos"] if r["repo"] == "ghost")
        self.assertEqual((ghost["read"], ghost["reason"]), (False, "no checkout"))
        self.assertIn("NOT READ (their activity is unknown, not absent): ghost (no checkout)",
                      uplift.render(self.doc, uplift.DEFAULTS))
        self.assertEqual((self.doc["counts"]["repos"], self.doc["counts"]["read"]), (7, 6))

    def test_keys_are_stable_and_candidates_are_ranked_by_who_is_behind(self) -> None:
        again, _ = uplift.scan(self.fleet.hub, self.fleet.projects, now=NOW)
        self.assertEqual([e["key"] for e in again["candidates"]], [e["key"] for e in self.doc["candidates"]])
        behind = [len(e["behind"]) for e in self.doc["candidates"]]
        self.assertEqual(behind, sorted(behind, reverse=True))
        self.assertEqual(len({e["key"] for e in self.doc["candidates"]}), len(self.doc["candidates"]))

    def test_the_window_is_honoured(self) -> None:
        doc, _ = uplift.scan(self.fleet.hub, self.fleet.projects, days=2, now=NOW)
        self.assertEqual((doc["counts"]["candidates"], doc["counts"]["rollouts"], doc["counts"]["commits"]), (0, 0, 0))

    def test_limiting_origins_still_compares_against_everyone(self) -> None:
        doc, _ = uplift.scan(self.fleet.hub, self.fleet.projects, only=["b"], now=NOW)
        self.assertEqual({e["from"]["repo"] for e in doc["candidates"]}, {"b"})
        self.assertEqual(entry(doc, "two.txt")["behind"], ["c", "d", "e"])
        with self.assertRaisesRegex(uplift.UpliftError, "not a fleet repo: nope"):
            uplift.scan(self.fleet.hub, self.fleet.projects, only=["nope"], now=NOW)

    def test_features_declared_or_shipped_and_the_fleet_wide_ones_apart(self) -> None:
        rows = {(f["repo"], f["id"]): f["change"] for f in self.doc["features"]}
        self.assertEqual(rows, {("a", "A-002"): "shipped", ("a", "A-003"): "new"})
        self.assertEqual(self.doc["feature_rollouts"], [{"title": "Missions in constitution", "repos": ["c", "d", "e"]}])
        self.assertEqual(self.doc["feature_notes"], [{"repo": "b", "file": "features/features.yml", "note": "created", "features": 2}])
        self.assertFalse([f for f in self.doc["features"] if f["repo"] == "hub"], "the hub's features are already the hub's")

    def test_a_stale_checkout_is_said_to_be_stale(self) -> None:
        fetch = self.fleet.projects / "e" / ".git" / "FETCH_HEAD"
        fetch.write_text("")
        old = (NOW - dt.timedelta(days=10)).timestamp()
        os.utime(fetch, (old, old))
        doc, _ = uplift.scan(self.fleet.hub, self.fleet.projects, now=NOW)
        self.assertEqual([r["repo"] for r in doc["repos"] if r["stale"]], ["e"])
        self.assertIn("STALE (last fetched over 3 days ago, newer commits are not seen): e", uplift.render(doc, uplift.DEFAULTS))
        fetch.unlink()

    def test_the_views_name_what_they_show(self) -> None:
        text = uplift.render(self.doc, uplift.DEFAULTS)
        for want in ("CANDIDATES", "ROLLOUTS IN FLIGHT", "FORKED", "FEATURES", "fleet-wide (3 repos", "kit demo v1.1.0"):
            self.assertIn(want, text)
        e = entry(self.doc, "ci.yml")
        shown = uplift.render_entry(e, self.members, uplift.DEFAULTS)
        self.assertIn("-v1\n+v2", shown)
        self.assertIn("5 repo(s) hold a version the origin held before, byte for byte", shown)
        brief = uplift.render_brief([e], self.members, self.doc, uplift.DEFAULTS)
        for want in ("**Is it general?**", "Propose only.", f"## {e['key']}: `ci.yml`", "```diff", "a `A-003` (new)"):
            self.assertIn(want, brief)
        self.assertIs(uplift.find(self.doc, e["key"][2:8]), e, "a key works without its prefix, and by its start")
        with self.assertRaisesRegex(uplift.UpliftError, "no candidate or rollout has the key"):
            uplift.find(self.doc, "u-0000000000")

    def test_a_long_diff_is_cut_and_says_where_the_rest_is(self) -> None:
        e = entry(self.doc, "ci.yml")
        cut = uplift.change_diff(e, self.members, 3).splitlines()
        self.assertEqual(len(cut), 4)
        self.assertRegex(cut[-1], r"^… \d+ more lines: https://github.com/bamr87/a/pull/7$")


class Filing(unittest.TestCase):
    """One fleet for the class; a test that changes a repo builds its own (`own_fleet`)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.shared_tmp = tempfile.TemporaryDirectory()
        cls.shared = fleet_copy(cls.shared_tmp.name)
        cls.shared_scan = uplift.scan(cls.shared.hub, cls.shared.projects, now=NOW)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.shared_tmp.cleanup()

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / "state"
        patch = unittest.mock.patch.dict(os.environ, {"UPLIFT_STATE": str(self.state)})
        patch.start()
        self.addCleanup(patch.stop)
        self.fleet = self.shared
        self.doc, self.members = self.shared_scan
        self.cfg = uplift.DEFAULTS
        self.key = entry(self.doc, "ci.yml")["key"]

    def own_fleet(self) -> None:
        self.fleet = fleet_copy(self.tmp.name)
        self.doc, self.members = uplift.scan(self.fleet.hub, self.fleet.projects, now=NOW)

    def run_file(self, keys: list[str], apply: bool, gh: StubGh | None = None, cfg: dict | None = None):
        gh = gh or StubGh()
        results, code = uplift.file_candidates(keys, hub=self.fleet.hub, doc=self.doc, members=self.members,
                                               cfg=cfg or self.cfg, apply=apply, gh=gh)
        return {r["key"]: r for r in results}, code, gh

    def test_a_preview_is_offline_and_carries_what_the_outbound_loops_read(self) -> None:
        class NoGh(uplift.Gh):
            def run(self, *args: str) -> str:
                raise AssertionError("a preview must not call GitHub")
        results, code = uplift.file_candidates([self.key], hub=self.fleet.hub, doc=self.doc, members=self.members,
                                               cfg=self.cfg, apply=False, gh=NoGh())
        self.assertEqual((results[0]["outcome"], code), ("preview", 0))
        body = (self.state / "previews" / f"{self.key}.md").read_text()
        self.assertTrue(body.startswith(f'<!-- fleet-uplift key="{self.key}" -->\n'), "the marker is the first line")
        self.assertRegex(body, r"(?m)^applies_to: b, c, d, e$", "the hub is not a fan-out target; the backlog fan-out reads this line")
        self.assertIn("The hub's own copy is one of them.", body)
        for want in ("## The change", "-v1\n+v2", "Route `patch`", "## Acceptance criteria", "https://github.com/bamr87/a/pull/7"):
            self.assertIn(want, body)
        meta = json.loads((self.state / "previews" / f"{self.key}.json").read_text())
        self.assertEqual(meta["labels"], ["uplift"])
        self.assertTrue(meta["title"].startswith("Uplift: ci.yml changed in a, 5 repo(s)"))

    def test_a_kit_route_names_no_fan_out_targets(self) -> None:
        key = entry(self.doc, "kit.yml")["key"]
        self.run_file([key], apply=False)
        body = (self.state / "previews" / f"{key}.md").read_text()
        self.assertNotRegex(body, r"(?m)^applies_to:", "a kit change deploys through the kit, not one tracking PR per repo")
        self.assertIn("Repos behind: b, c, d, e", body)
        self.assertIn("Route `kit`", body)

    def test_apply_files_only_what_a_person_previewed(self) -> None:
        results, code, gh = self.run_file([self.key], apply=True)
        self.assertEqual((results[self.key]["outcome"], code, gh.created), ("refused", 1, []))
        self.assertIn("no preview yet", results[self.key]["detail"])
        self.run_file([self.key], apply=False)
        results, code, gh = self.run_file([self.key], apply=True)
        self.assertEqual((results[self.key]["outcome"], code), ("filed", 0))
        (issue,) = gh.created
        self.assertEqual((issue["repo"], issue["labels"], gh.labels), ("bamr87/hub", ["uplift"], ["uplift"]))
        self.assertEqual(issue["body"], (self.state / "previews" / f"{self.key}.md").read_text())

    def test_a_candidate_that_changed_since_its_preview_is_refused(self) -> None:
        self.own_fleet()
        self.run_file([self.key], apply=False)
        self.fleet.commit(self.fleet.projects / "b", {"ci.yml": "v2\n"}, "fix: b took it", RECENT)
        self.doc, self.members = uplift.scan(self.fleet.hub, self.fleet.projects, now=NOW)
        results, code, gh = self.run_file([self.key], apply=True)
        self.assertEqual((results[self.key]["outcome"], code, gh.created), ("refused", 1, []))
        self.assertIn("changed since its preview", results[self.key]["detail"])

    def test_an_edited_preview_is_not_what_gets_filed(self) -> None:
        self.run_file([self.key], apply=False)
        path = self.state / "previews" / f"{self.key}.md"
        path.write_text(path.read_text() + "\nsomething nobody generated\n")
        results, _, gh = self.run_file([self.key], apply=True)
        self.assertEqual((results[self.key]["outcome"], gh.created), ("refused", []))

    def test_a_repo_less_visible_than_the_hub_is_never_filed_from(self) -> None:
        self.run_file([self.key], apply=False)
        for visibility in ("private", None):
            with self.subTest(visibility=visibility):
                results, code, gh = self.run_file([self.key], apply=True, gh=StubGh({"bamr87/a": visibility}))
                self.assertEqual((results[self.key]["outcome"], code, gh.created), ("withheld", 1, []))
        results, _, gh = self.run_file([self.key], apply=True, gh=StubGh({"bamr87/a": "private", "bamr87/hub": "private"}))
        self.assertEqual(results[self.key]["outcome"], "filed", "a private hub may hold a private repo's change")

    def test_a_credential_shaped_change_is_withheld_before_anything_is_written(self) -> None:
        self.own_fleet()
        token = "ghp_" + "A1b2C3d4E5" * 4
        self.fleet.commit(self.fleet.projects / "a", {"ci.yml": f"v3\ntoken: {token}\n"}, "fix: oops", RECENT)
        self.doc, self.members = uplift.scan(self.fleet.hub, self.fleet.projects, now=NOW)
        key = entry(self.doc, "ci.yml")["key"]
        results, code, _ = self.run_file([key], apply=False)
        self.assertEqual((results[key]["outcome"], code), ("withheld", 1))
        self.assertFalse((self.state / "previews" / f"{key}.md").exists())
        begin = "-----BEGIN " + "RSA PRIVATE KEY-----"
        self.assertTrue(uplift.CREDENTIAL_RX.search(begin) and uplift.CREDENTIAL_RX.search("x sk-ant-" + "a" * 24))

    def test_a_filed_candidate_is_never_filed_twice_open_or_closed(self) -> None:
        self.run_file([self.key], apply=False)
        for state in ("OPEN", "CLOSED"):
            with self.subTest(state=state):
                gh = StubGh(issues=[{"number": 5, "state": state, "url": "https://github.com/bamr87/hub/issues/5",
                                     "body": f'<!-- fleet-uplift key="{self.key}" -->\nearlier'}])
                results, code, gh = self.run_file([self.key], apply=True, gh=gh)
                self.assertEqual((results[self.key]["outcome"], code, gh.created), ("skipped", 0, []))
                self.assertIn("issues/5", results[self.key]["detail"])

    def test_the_caps(self) -> None:
        keys = [e["key"] for e in self.doc["candidates"]][:4]
        with self.assertRaisesRegex(uplift.UpliftError, "one run files at most 3"):
            self.run_file(keys, apply=False)
        self.run_file([self.key], apply=False)
        crowd = StubGh(issues=[{"number": n, "state": "OPEN", "url": "u", "body": ""} for n in range(10)])
        results, code, gh = self.run_file([self.key], apply=True, gh=crowd)
        self.assertEqual((results[self.key]["outcome"], code, gh.created), ("refused", 1, []))
        self.assertIn("10 uplift issues are open", results[self.key]["detail"])

    def test_a_rollout_is_not_filed_and_the_hold_label_is_configurable(self) -> None:
        roll = entry(self.doc, "roll.txt", "rollouts")["key"]
        results, code, _ = self.run_file([roll], apply=False)
        self.assertEqual((results[roll]["outcome"], code), ("refused", 1))
        held = uplift.merged(uplift.DEFAULTS, {"file": {"hold": True}})
        self.run_file([self.key], apply=False, cfg=held)
        _, _, gh = self.run_file([self.key], apply=True, cfg=held)
        self.assertEqual(gh.created[0]["labels"], ["uplift", "agent:hold"])


class Cli(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.fleet = fleet_copy(cls.tmp.name)
        cls.state = Path(cls.tmp.name) / "state"
        cls.base = ["--hub", str(cls.fleet.hub), "--projects", str(cls.fleet.projects), "--now", NOW.isoformat()]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with unittest.mock.patch.dict(os.environ, {"UPLIFT_STATE": str(self.state)}), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = uplift.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_scan_saves_what_status_reads(self) -> None:
        code, out, _ = self.run_cli("scan", *self.base, "--json")
        doc = json.loads(out)
        self.assertEqual((code, doc["schema"]), (0, "fleet-uplift/v1"))
        self.assertEqual(json.loads((self.state / "scan.json").read_text())["counts"], doc["counts"])
        code, out, _ = self.run_cli("status", *self.base)
        self.assertEqual(code, 0)
        self.assertIn("Last scan 2026-11-20 (0 day(s) ago), 14 days, 6 of 7 repos read", out)
        self.assertIn(uplift.headline(doc), out)

    def test_flags_alone_are_the_scan_and_the_other_views_run(self) -> None:
        code, out, _ = self.run_cli(*self.base)
        self.assertEqual(code, 0)
        self.assertIn("Fleet uplift — 14 days to 2026-11-20", out)
        key = re.search(r"(u-[0-9a-f]{10}) +\d+ behind +patch +ci\.yml", out).group(1)
        code, out, _ = self.run_cli("show", key, *self.base)
        self.assertEqual(code, 0)
        self.assertIn("-v1\n+v2", out)
        code, out, _ = self.run_cli("brief", "--top", "2", *self.base)
        self.assertEqual((code, out.count("\n## u-")), (0, 2))
        code, out, _ = self.run_cli("file", key, *self.base)
        self.assertEqual(code, 0)
        self.assertIn("Nothing was filed.", out)

    def test_a_refusal_is_one_line_and_exit_2(self) -> None:
        code, out, err = self.run_cli("show", "u-ffffffffff", *self.base)
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("uplift: no candidate or rollout has the key"))

    def test_status_without_a_scan(self) -> None:
        with tempfile.TemporaryDirectory() as empty, unittest.mock.patch.dict(os.environ, {"UPLIFT_STATE": empty}):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(uplift.main(["status", *self.base]), 0)
        self.assertEqual(out.getvalue(), "No scan yet: tools/dash uplift scan\n")


class Config(unittest.TestCase):
    def test_the_hubs_block_loads_and_holds_only_known_keys(self) -> None:
        cfg, fleet = uplift.load_config(ROOT)
        block = fleet.get("uplift")
        self.assertIsInstance(block, dict, "_data/fleet.yml declares `uplift:` (central configuration)")
        self.assertEqual(set(block), set(uplift.DEFAULTS), "every setting is declared in the central configuration")
        self.assertEqual(block, uplift.DEFAULTS, "the hub's settings and the tool's fallback are changed together")
        self.assertEqual(cfg, uplift.DEFAULTS)
        self.assertGreaterEqual(cfg["file"]["max_open"], cfg["file"]["max_per_run"])
        for pattern in cfg["ignore_subjects"] + cfg["rollout_subjects"]:
            re.compile(pattern)

    def test_an_unknown_key_and_a_bad_number_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = Fleet(tmp)
            for block, want in (({"dayz": 3}, "unknown keys: dayz"), ({"days": 0}, "`uplift.days` must be a whole number"),
                                ({"days": True}, "`uplift.days` must be a whole number")):
                with self.subTest(block=block):
                    f.registry(block)
                    with self.assertRaisesRegex(uplift.UpliftError, want):
                        uplift.load_config(f.hub)
            f.registry({"days": 30, "file": {"max_open": 2}})
            cfg, _ = uplift.load_config(f.hub)
            self.assertEqual((cfg["days"], cfg["file"]["max_open"], cfg["file"]["label"]), (30, 2, "uplift"))

    def test_the_fan_out_branches_come_from_the_fan_out_engine(self) -> None:
        exact, prefixes = uplift.fanout_branches(ROOT, uplift.DEFAULTS)
        self.assertIn("chore/sdlc-kit", exact)
        self.assertGreaterEqual(len(exact), 10, "every kit's branch, read from tools/fanout.sh, so a new kit is covered")
        self.assertFalse([b for b in exact if "$" in b], "a variable is not a branch name")
        self.assertIn("backlog/", prefixes)

    def test_the_front_doors_exist(self) -> None:
        dash = (ROOT / "tools" / "dash").read_text()
        self.assertRegex(dash, r"(?m)^\s+uplift\)\s+cmd_uplift \"\$@\" ;;")
        self.assertIn('"${TOOLS}/uplift.py"', dash)
        self.assertIn('"uplift": dict(', (ROOT / "tools" / "console" / "core.py").read_text())
        self.assertIn(".fleet/uplift/", (ROOT / ".gitignore").read_text().splitlines())
        self.assertTrue((ROOT / "docs" / "UPLIFT.md").is_file())

    def test_nothing_here_holds_a_key_block_header(self) -> None:
        header = "BEGIN " + "RSA PRIVATE KEY"
        for rel in ("tools/uplift.py", "tools/test_uplift.py"):
            self.assertNotIn(header, (ROOT / rel).read_text(), "the detect-private-key hook reads these files")


if __name__ == "__main__":
    sys.exit(unittest.main())
