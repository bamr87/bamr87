#!/usr/bin/env python3
"""Tests for the loop switches (tools/console/switches.py; constitution § 17, HUB-057, FR54).

Every GitHub call is mocked: a fake REST API stands in for github_link.api (and, for the token
test, github_link._http behind the real client). Nothing here reads a live variable or writes one.

    python3 tools/console/test_switches.py      (the splice tests need ruamel.yaml; skipped without it)
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import core  # noqa: E402
import github_link as ghl  # noqa: E402
import switches as sw  # noqa: E402

try:
    import ruamel.yaml  # noqa: F401
    HAS_RUAMEL = True
except ImportError:  # pragma: no cover - the console's venv has it
    HAS_RUAMEL = False

TODAY = "2026-11-25"
TOKEN = "ghp_" + "Z9" * 18          # token-shaped, never real
HUB, LH, ORG = "bamr87/bamr87", "bamr87/lifehacker.dev", "bash-365/bash-365.com"

FLEET = f"""\
# the fleet's control plane (a fixture)
hub:
  repo: {HUB}

variables:
  NODE_VERSION: "20"
  PR_READINESS_ENABLED: "true"

# --------------------------------------------------------------------------- #
# Loop switches — a comment block above the map that must survive byte for byte
# --------------------------------------------------------------------------- #
switches:
  schema: switches/v1
  global:
    state: 'on'
    reason: null
    set_by: null
    set_at: null
    expires: null
  groups:
    hub-loops:
      state: 'on'
      reason: null
      expires: null
    lh-loops:
      state: 'on'
      reason: null
      expires: null
    paused:
      state: 'off'
      reason: 'paused for the audit'
      expires: null
  loops:
    hub/pulse:
      repo: {HUB}
      workflow: .github/workflows/fleet-pulse.yml
      group: hub-loops
      owner: bamr87
      scope: loop
      gate:
        kind: repo_variable
        name: FLEET_PULSE_ENABLED
        semantics: opt_out
      default: 'on'
      state: unverified
      verified: false
      flip: 'gh variable set FLEET_PULSE_ENABLED -R {HUB} --body false  # pause; record the flip here in the same PR'
      cron: 37 5 * * *
      dispatch_bypasses: true
    hub/pm:
      repo: {HUB}
      workflow: .github/workflows/fleet-pm.yml
      group: hub-loops
      owner: bamr87
      scope: loop
      gate:
        kind: repo_variable
        name: FLEET_PM_ENABLED
        semantics: opt_in
      default: 'off'
      state: 'on'
      verified: true
      flip: 'gh variable set FLEET_PM_ENABLED -R {HUB} --body true  # enable'
      reason: 'turned on for the review'
      set_by: bamr87
      set_at: '2026-11-20'
    hub/readiness:
      repo: {HUB}
      workflow: .github/workflows/pr-review.yml
      group: hub-loops
      owner: bamr87
      scope: loop
      gate:
        kind: repo_variable
        name: PR_READINESS_ENABLED
        semantics: opt_in
      default: 'off'
      state: unverified
      verified: false
      flip: 'tools/dash config sync --apply'
    hub/claude:
      repo: {HUB}
      workflow: .github/workflows/claude.yml
      group: hub-loops
      owner: bamr87
      scope: loop
      gate:
        kind: none
      default: 'on'
      state: 'on'
      verified: false
      flip: 'no switch yet'
    lh/factory:
      repo: {LH}
      workflow: .github/workflows/content-factory.yml
      group: lh-loops
      owner: bamr87
      scope: loop
      gate:
        kind: repo_variable
        name: CONTENT_FACTORY_ENABLED
        semantics: opt_in
      default: 'off'
      state: 'on'
      verified: true
      flip: 'gh variable set CONTENT_FACTORY_ENABLED -R {LH} --body true  # enable'
      reason: 'maintainer instruction'
      set_by: bamr87
      set_at: '2026-11-24'
    lh/auto-merge:
      repo: {LH}
      workflow: .github/workflows/auto-merge.yml
      group: lh-loops
      owner: bamr87
      scope: loop
      gate:
        kind: repo_variable
        name: AUTO_MERGE_ENABLED
        semantics: opt_in
      default: 'off'
      state: 'off'
      verified: true
      flip: 'gh variable set AUTO_MERGE_ENABLED -R {LH} --body true  # enable'
      reason: 'held by amendment'
      set_by: bamr87
      set_at: '2026-11-24'
      hold:
        kind: env
        name: HUB_ORIGINATION_HOLD
        value: 'true'
        source: lifehacker.dev#800
        lift: 'needs a new amendment'
    lh/paused-loop:
      repo: {LH}
      workflow: .github/workflows/explore.yml
      group: paused
      owner: bamr87
      scope: loop
      gate:
        kind: repo_variable
        name: EXPLORER_ENABLED
        semantics: opt_in
      default: 'off'
      state: 'on'
      verified: true
      flip: 'gh variable set EXPLORER_ENABLED -R {LH} --body true'
      reason: 'on'
      set_by: bamr87
      set_at: '2026-11-24'
    org/content-loop:
      repo: {ORG}
      workflow: .github/workflows/content-loop.yml
      group: lh-loops
      owner: bamr87
      scope: loop
      gate:
        kind: repo_variable
        name: CONTENT_LOOP_ENABLED
        semantics: opt_in
      default: 'off'
      state: unverified
      verified: false
      flip: 'gh variable set CONTENT_LOOP_ENABLED -R {ORG} --body false'
  repos: {{}}


# --------------------------------------------------------------------------- #
# The next block, whose comment above must not move
# --------------------------------------------------------------------------- #
ux_audit:
  enabled: false          # flip when hub critique workflow ships
  schedule: "0 15 * * 1"
"""


class FakeGitHub:
    """The REST calls switches.py makes, over an in-memory variable store. `unreadable` repos answer 403."""

    def __init__(self, store: dict[str, dict[str, str]], unreadable: tuple[str, ...] = (), login: str = "bamr87",
                 fail_patch: tuple[str, ...] = ()):
        self.store = {r: dict(v) for r, v in store.items()}
        self.unreadable, self.login, self.fail_patch = set(unreadable), login, set(fail_patch)
        self.calls: list[tuple[str, str, dict | None]] = []

    def writes(self) -> list[tuple[str, str, dict | None]]:
        return [c for c in self.calls if c[0] != "GET"]

    def __call__(self, method: str, path: str, payload: dict | None = None, **_kw):
        self.calls.append((method, path, payload))
        if path == "/user":
            return {"login": self.login}
        parts = path.split("?")[0].strip("/").split("/")          # repos/o/r/actions/variables[/NAME]
        repo = f"{parts[1]}/{parts[2]}"
        if repo in self.unreadable:
            raise ghl.GitHubError(403, f"GitHub 403: Resource not accessible by integration {TOKEN}")
        vars_ = self.store.setdefault(repo, {})
        if method == "GET" and len(parts) == 5:
            page = int(path.split("page=")[-1]) if "page=" in path else 1
            names = sorted(vars_)
            chunk = names[(page - 1) * sw.VARIABLES_PAGE: page * sw.VARIABLES_PAGE]
            return {"total_count": len(names), "variables": [{"name": n, "value": vars_[n], "updated_at": "2026-11-23T21:38:00Z"}
                                                             for n in chunk]}
        name = parts[5] if len(parts) > 5 else (payload or {}).get("name")
        if method == "GET":
            if name not in vars_:
                raise ghl.GitHubError(404, "GitHub 404: Not Found")
            return {"name": name, "value": vars_[name], "updated_at": "2026-11-25T20:00:00Z"}
        if method == "PATCH":
            if name in self.fail_patch:
                raise ghl.GitHubError(403, "GitHub 403: Must have admin rights")
            if name not in vars_:
                raise ghl.GitHubError(404, "GitHub 404: Not Found")
            vars_[name] = payload["value"]
            return None
        if method == "POST":
            vars_[name] = payload["value"]
            return None
        raise AssertionError(f"unexpected call {method} {path}")


LIVE = {HUB: {"FLEET_PM_ENABLED": "true", "PR_READINESS_ENABLED": "false"},
        LH: {"CONTENT_FACTORY_ENABLED": "true", "AUTO_MERGE_ENABLED": "true", "EXPLORER_ENABLED": "true"},
        ORG: {"CONTENT_LOOP_ENABLED": "true"}}


class Base(unittest.TestCase):
    """A temporary hub root with the fixture fleet.yml, the state dir and the activity spool in it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "_data").mkdir()
        self.fleet = self.root / "_data" / "fleet.yml"
        self.fleet.write_text(FLEET)
        self.env = mock.patch.dict(os.environ, {"DASH_SWITCHES_DIR": str(self.root / ".fleet" / "switches"),
                                                "FLEET_ACTIVITY_QUEUE": str(self.root / "activity.jsonl"),
                                                "GH_TOKEN": TOKEN})
        self.env.start()
        os.environ.pop("HARNESS_PROJECTS_AUDIT", None)
        os.environ.pop("FLEET_ACTIVITY_ENDPOINT", None)
        sw._LIVE.update(at=0.0, key=None, data=None)        # the console's own 30 s cache, never shared by tests
        sw._LOGIN.update(at=0.0, login=None)
        self.patches = [mock.patch.object(sw, "writable_repos", return_value={HUB, LH}),
                        mock.patch.object(ghl, "GITHUB_WRITES", True), mock.patch.object(core, "AUTH_WRITES", True)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.env.stop()
        self.tmp.cleanup()

    def doc(self, gh: FakeGitHub | None = None) -> dict:
        return sw.document(self.root, api=gh or FakeGitHub(LIVE))

    def row(self, key: str, gh: FakeGitHub | None = None) -> dict:
        return next(r for repo in self.doc(gh)["repos"] for r in repo["loops"] if r["key"] == key)


class Reading(Base):
    def test_opt_in_and_opt_out_semantics(self):
        self.assertEqual([sw.variable_on("opt_in", v) for v in ("true", "", "false", "TRUE")], [True, False, False, False])
        self.assertEqual([sw.variable_on("opt_out", v) for v in ("true", "", "false", "nope")], [True, True, False, True])
        self.assertIsNone(sw.variable_on("opt_in", None))
        pulse = self.row("hub/pulse")                       # opt_out, unset
        self.assertEqual((pulse["live"]["state"], pulse["live"]["value"], pulse["effective"]["on"]), ("unset", "", True))
        gh = FakeGitHub({**LIVE, HUB: {**LIVE[HUB], "FLEET_PM_ENABLED": "yes"}})
        self.assertFalse(self.row("hub/pm", gh)["effective"]["on"], "opt_in runs only on exactly 'true'")

    def test_unreadable_is_never_off(self):
        gh = FakeGitHub(LIVE, unreadable=(LH,))
        doc = self.doc(gh)
        repo = next(r for r in doc["repos"] if r["repo"] == LH)
        self.assertFalse(repo["readable"])
        factory = next(r for r in repo["loops"] if r["key"] == "lh/factory")
        self.assertEqual(factory["live"]["state"], "unreadable")
        self.assertIsNone(factory["live"]["value"])
        self.assertIsNone(factory["effective"]["on"])
        self.assertIsNone(factory["drift"])
        self.assertFalse(factory["flippable"])
        self.assertIn("written blind", factory["not_flippable"])

    def test_the_most_restrictive_level_wins(self):
        paused = self.row("lh/paused-loop")                 # its group is off, its variable is 'true'
        self.assertFalse(paused["effective"]["on"])
        self.assertIn("group paused is off", paused["effective"]["why"])
        self.assertTrue(paused["drift"], "the map says off (its group), the variable says on")
        text = FLEET.replace("  repos: {}", f"  repos:\n    {LH}:\n      state: 'off'\n      reason: 'repo paused'")
        self.fleet.write_text(text)
        self.assertFalse(self.row("lh/factory")["effective"]["on"])
        self.assertIn("repo bamr87/lifehacker.dev is off", self.row("lh/factory")["effective"]["why"])
        self.fleet.write_text(FLEET.replace("  global:\n    state: 'on'", "  global:\n    state: 'off'"))
        self.assertFalse(self.row("hub/pm")["effective"]["on"])

    def test_drift_is_the_map_against_the_variable(self):
        self.assertFalse(self.row("hub/pm")["drift"])
        gh = FakeGitHub({**LIVE, HUB: {**LIVE[HUB], "FLEET_PM_ENABLED": "false"}})
        self.assertTrue(self.row("hub/pm", gh)["drift"])
        self.assertIsNone(self.row("hub/pulse")["drift"], "an unverified record makes no claim")
        self.assertIsNone(self.row("hub/claude")["drift"], "no variable, no drift")

    def test_a_hold_idles_the_loop_and_shows(self):
        held = self.row("lh/auto-merge")
        self.assertEqual(held["hold"]["name"], "HUB_ORIGINATION_HOLD")
        self.assertFalse(held["effective"]["on"])
        self.assertIn("held by", held["effective"]["why"])

    def test_document_groups_by_repo_and_counts(self):
        doc = self.doc()
        self.assertEqual(doc["schema"], sw.DOC_SCHEMA)
        self.assertEqual([r["repo"] for r in doc["repos"]], sorted([HUB, LH, ORG]))
        org = next(r for r in doc["repos"] if r["repo"] == ORG)
        self.assertFalse(org["writable"])
        self.assertIn("not a repository the hub owns", org["loops"][0]["not_flippable"])
        self.assertEqual(doc["counts"]["loops"], 8)
        self.assertTrue(doc["writes"]["enabled"])
        with mock.patch.object(ghl, "GITHUB_WRITES", False):
            self.assertIn("DASH_CONSOLE_GITHUB_WRITES", self.doc()["writes"]["why"])

    def test_one_paged_list_call_per_repo(self):
        many = {HUB: {f"V{i:03d}_ENABLED": "true" for i in range(70)}, LH: {}, ORG: {}}
        gh = FakeGitHub(many)
        got = sw.fetch_variables(HUB, gh)
        self.assertEqual(len(got["variables"]), 70)
        self.assertEqual(sum(1 for c in gh.calls if c[1].startswith(f"/repos/{HUB}/actions/variables?")), 3)


@unittest.skipUnless(HAS_RUAMEL, "ruamel.yaml absent (the console's venv has it)")
class Splice(Base):
    def outside(self, text: str, keys: list[str]) -> str:
        lines = text.splitlines(keepends=True)
        for k in sorted(keys, key=lambda k: sw._record_span(lines, k)[0], reverse=True):
            s, e = sw._record_span(lines, k)
            lines[s:e] = [f"<{k}>\n"]
        return "".join(lines)

    def test_only_the_touched_records_change(self):
        up = {"hub/pulse": {"state": "off", "verified": True, "reason": "pause: it's noisy", "set_by": "bamr87", "set_at": TODAY},
              "lh/factory": {"state": "off", "verified": True, "reason": "pause", "set_by": "bamr87", "set_at": TODAY}}
        out = sw.splice_records(FLEET, up)
        self.assertEqual(self.outside(out, list(up)), self.outside(FLEET, list(up)), "every other byte is the original's")
        data = yaml.safe_load(out)["switches"]["loops"]
        self.assertEqual({k: data["hub/pulse"][k] for k in up["hub/pulse"]}, up["hub/pulse"])
        self.assertEqual(data["hub/pulse"]["cron"], "37 5 * * *")
        # the fields the hub record lacked land after its flip line, the quoting style of the file
        lines = [ln.strip() for ln in out.splitlines()]
        i = lines.index("hub/pulse:")
        rec = lines[i:i + 18]
        self.assertLess(rec.index(next(x for x in rec if x.startswith("flip:"))), rec.index("reason: 'pause: it''s noisy'"))
        self.assertIn("set_at: '2026-11-25'", rec)
        self.assertIn("state: 'off'", rec)
        self.assertIn("global:\n    state: 'on'\n    reason: null", out, "nulls stay nulls")

    def test_an_unknown_record_is_refused(self):
        with self.assertRaises(ValueError):
            sw.splice_records(FLEET, {"no/such": {"state": "off"}})

    def test_the_diff_reads_like_git(self):
        out = sw.splice_records(FLEET, {"lh/factory": {"state": "off", "verified": True, "reason": "r", "set_by": "bamr87",
                                                       "set_at": TODAY}})
        diff = sw.unified(FLEET, out)
        self.assertTrue(diff.startswith("--- a/_data/fleet.yml\n+++ b/_data/fleet.yml\n@@ "))
        self.assertNotIn("-      set_by: bamr87", diff, "an unchanged line is context, not removed and re-added")
        self.assertIn("+      state: 'off'", diff)


@unittest.skipUnless(HAS_RUAMEL, "ruamel.yaml absent (the console's venv has it)")
class Preview(Base):
    def plan(self, scope="loop", key="hub/pulse", target="off", reason="pause for the audit", gh=None):
        gh = gh or FakeGitHub(LIVE)
        return sw.plan(scope, key, target, reason, root=self.root, api=gh, today=TODAY), gh

    def test_preview_writes_nothing_but_its_plan_file(self):
        doc, gh = self.plan()
        self.assertEqual(self.fleet.read_text(), FLEET)
        self.assertEqual(gh.writes(), [], "a preview makes no write call")
        self.assertTrue((self.root / ".fleet" / "switches" / "plans" / f"{doc['plan_id']}.json").is_file())
        (item,) = doc["items"]
        self.assertEqual((item["current"], item["new"], item["write_variable"], item["do"]), ("", "false", True, True))
        self.assertIn("+      state: 'off'", doc["diff"])
        self.assertIn("+      reason: 'pause for the audit'", doc["diff"])
        self.assertIn("+      set_by: bamr87", doc["diff"])
        self.assertIn("+      set_at: '2026-11-25'", doc["diff"])
        self.assertIn("flip: 'gh variable set FLEET_PULSE_ENABLED", doc["diff"], "the flip line is kept")
        self.assertEqual(doc["plan_id"], self.plan()[0]["plan_id"], "deterministic")

    def test_semantics_pick_the_value(self):
        gh = FakeGitHub({**LIVE, HUB: {"FLEET_PULSE_ENABLED": "false"}})
        self.assertEqual(self.plan(target="on", gh=gh)[0]["items"][0]["new"], "true", "opt_out on writes 'true'")
        gh = FakeGitHub({**LIVE, HUB: {}})
        self.assertEqual(self.plan(key="hub/pm", target="on", gh=gh)[0]["items"][0]["new"], "true", "opt_in on writes 'true'")
        doc, _ = self.plan(key="hub/pm", target="off")
        self.assertEqual(doc["items"][0]["new"], "false")

    def test_already_there_is_skipped_or_only_recorded(self):
        doc, _ = self.plan(key="hub/pm", target="on")
        self.assertFalse(doc["items"][0]["do"])
        self.assertIn("already on", doc["items"][0]["skip"])
        doc, _ = self.plan(key="hub/pulse", target="on")       # unset opt_out reads on; the map is unverified
        item = doc["items"][0]
        self.assertTrue(item["do"] and item["write_map"] and not item["write_variable"])
        self.assertEqual(item["new"], "", "nothing is written to the variable")

    def test_what_the_console_will_not_flip(self):
        skips = {i["key"]: i["skip"] for i in self.plan(scope="all", key="", target="on")[0]["items"] if not i["do"]}
        self.assertIn("held by HUB_ORIGINATION_HOLD", skips["lh/auto-merge"])
        self.assertIn("canonical variable", skips["hub/readiness"])
        self.assertIn("no variable switch", skips["hub/claude"])
        off = {i["key"]: i for i in self.plan(scope="repo", key=ORG, target="off")[0]["items"]}
        self.assertIn("not a repository the hub owns", off["org/content-loop"]["skip"])
        on = {i["key"]: i for i in self.plan(scope="repo", key=ORG, target="on")[0]["items"]}
        self.assertTrue(on["org/content-loop"]["do"] and not on["org/content-loop"]["write_variable"],
                        "a variable already at the target is recorded in the map: no GitHub write")

    def test_scopes_and_reason(self):
        self.assertEqual({i["key"] for i in self.plan(scope="group", key="lh-loops")[0]["items"]},
                         {"lh/factory", "lh/auto-merge", "org/content-loop"})
        for bad in ("", "ok", "x" * 301, f"see {TOKEN}"):
            with self.assertRaises(ValueError):
                self.plan(reason=bad)
        with self.assertRaises(ValueError):
            self.plan(key="no/such")
        with self.assertRaises(ValueError):
            self.plan(scope="everything")


@unittest.skipUnless(HAS_RUAMEL, "ruamel.yaml absent (the console's venv has it)")
class Apply(Base):
    def preview(self, gh, **kw):
        args = {"scope": "loop", "key": "lh/factory", "target": "off", "reason": "pause the factory"} | kw
        return sw.plan(args["scope"], args["key"], args["target"], args["reason"], root=self.root, api=gh, today=TODAY)

    def apply(self, plan_id, gh, do_apply=True):
        out: list[str] = []
        doc = sw.apply(plan_id, do_apply=do_apply, root=self.root, api=gh, out=out.append, today=TODAY)
        return doc, "\n".join(out)

    def test_dry_run_only_says_it_still_matches(self):
        gh = FakeGitHub(LIVE)
        doc, text = self.apply(self.preview(gh)["plan_id"], gh, do_apply=False)
        self.assertFalse(doc["applied"])
        self.assertIn("still matches", text)
        self.assertEqual(gh.writes(), [])
        self.assertEqual(self.fleet.read_text(), FLEET)

    def test_apply_sets_reads_back_records_and_audits(self):
        gh = FakeGitHub(LIVE)
        plan = self.preview(gh, scope="repo", key=HUB, target="off")
        doc, text = self.apply(plan["plan_id"], gh)
        self.assertEqual(gh.store[HUB]["FLEET_PULSE_ENABLED"], "false")
        self.assertEqual(gh.store[HUB]["FLEET_PM_ENABLED"], "false")
        methods = {(c[0], c[2]["name"]) for c in gh.writes()}
        self.assertIn(("POST", "FLEET_PULSE_ENABLED"), methods, "a missing variable is created")
        self.assertIn(("PATCH", "FLEET_PM_ENABLED"), methods)
        self.assertNotIn("PR_READINESS_ENABLED", {c[2]["name"] for c in gh.writes()}, "a canonical variable is left to config sync")
        self.assertTrue(any(c[0] == "GET" and c[1].endswith("/FLEET_PM_ENABLED") for c in gh.calls), "read back")
        self.assertEqual(doc["failed"], 0)
        new = self.fleet.read_text()
        loops = yaml.safe_load(new)["switches"]["loops"]
        self.assertEqual((loops["hub/pm"]["state"], loops["hub/pm"]["set_at"], loops["hub/pm"]["reason"]),
                         ("off", TODAY, "pause the factory"))
        self.assertEqual(loops["hub/readiness"]["state"], "unverified")
        self.assertEqual(doc["diff"], sw.unified(FLEET, new))
        self.assertIn("commit it in a PR", text)
        audit = [json.loads(x) for x in (self.root / ".fleet" / "switches" / "github-writes.jsonl").read_text().splitlines()]
        self.assertEqual({a["loop"] for a in audit}, {"hub/pulse", "hub/pm"})
        self.assertTrue(all(a["actor"] == "bamr87" and a["reason"] == "pause the factory" and a["result"] == "set" for a in audit))
        events = [json.loads(x) for x in (self.root / "activity.jsonl").read_text().splitlines()]
        self.assertEqual(len(events), 2)
        d = events[0]["detail"]
        self.assertEqual(set(d) >= {"who", "what", "scope", "reason", "old", "new"}, True)
        self.assertEqual((d["who"], d["scope"], d["reason"]), ("bamr87", f"repo {HUB}", "pause the factory"))
        self.assertEqual(events[0]["outcome"], "success")
        self.assertFalse(d["dry_run"])

    def test_a_failed_write_is_not_recorded_in_the_map(self):
        gh = FakeGitHub(LIVE, fail_patch=("CONTENT_FACTORY_ENABLED",))
        doc, text = self.apply(self.preview(gh)["plan_id"], gh)
        self.assertEqual(doc["failed"], 1)
        self.assertEqual(self.fleet.read_text(), FLEET)
        self.assertIn("FAIL", text)

    def test_refused_without_github_writes(self):
        gh = FakeGitHub(LIVE)
        plan = self.preview(gh)
        with mock.patch.object(ghl, "GITHUB_WRITES", False):
            with self.assertRaises(sw.Refused) as cm:
                self.apply(plan["plan_id"], gh)
        self.assertIn("switched off", str(cm.exception))
        self.assertEqual(gh.writes(), [])
        self.assertEqual(self.fleet.read_text(), FLEET)

    def test_refused_for_a_repo_the_hub_does_not_own(self):
        gh = FakeGitHub(LIVE)
        plan = self.preview(gh)
        with mock.patch.object(sw, "writable_repos", return_value={HUB}):
            with self.assertRaises(sw.Refused):
                self.apply(plan["plan_id"], gh)
        self.assertEqual(gh.writes(), [])
        org = sw.plan("repo", ORG, "off", "pause", root=self.root, api=gh, today=TODAY)
        self.assertEqual(org["counts"]["do"], 0)

    def test_refused_when_it_moved_or_is_stale_or_unknown(self):
        gh = FakeGitHub(LIVE)
        plan = self.preview(gh)
        gh.store[LH]["CONTENT_FACTORY_ENABLED"] = "false"
        with self.assertRaises(sw.Refused) as cm:
            self.apply(plan["plan_id"], gh)
        self.assertEqual(cm.exception.code, 4)
        self.assertIn("CONTENT_FACTORY_ENABLED 'true' → 'false'", str(cm.exception))
        gh = FakeGitHub(LIVE)
        plan = self.preview(gh)
        self.fleet.write_text(FLEET.replace("reason: 'maintainer instruction'", "reason: 'edited by hand'"))
        with self.assertRaises(sw.Refused) as cm:
            self.apply(plan["plan_id"], gh)
        self.assertIn("record changed", str(cm.exception))
        self.fleet.write_text(FLEET)
        plan = self.preview(gh)
        with self.assertRaises(sw.Refused) as cm:
            sw.apply(plan["plan_id"], do_apply=True, root=self.root, api=gh, out=lambda _s: None, today="2026-11-26")
        self.assertIn("previewed on 2026-11-25", str(cm.exception))
        with self.assertRaises(sw.Refused) as cm:
            self.apply("0123456789abcdef", gh)
        self.assertEqual(cm.exception.code, 2)
        with self.assertRaises(ValueError):
            sw.stored_plan("../../etc/passwd", self.root)
        self.assertEqual(gh.writes(), [])


class TheConsoleGate(unittest.TestCase):
    """switches-apply is a remote op: it writes only with apply, and the job manager refuses it without confirm."""

    def test_the_operation(self):
        argv, remote = core.build_argv("switches-apply", {"plan_id": "0123456789abcdef"})
        self.assertEqual((argv[1:], remote), (["switches", "apply", "--plan-id", "0123456789abcdef"], False))
        argv, remote = core.build_argv("switches-apply", {"plan_id": "0123456789abcdef", "apply": True})
        self.assertEqual((argv[-1], remote), ("--apply", True))
        self.assertEqual(core.OPS["switches-apply"]["exclusive"], "switches")
        op = next(o for o in core.list_ops() if o["id"] == "switches-apply")
        self.assertEqual((op["remote_write"], op["confirm"]), (True, "write"))
        for bad in ({}, {"plan_id": "../x"}, {"plan_id": "0123456789ABCDEF"}):
            with self.assertRaises(ValueError):
                core.build_argv("switches-apply", bad)
        self.assertEqual(core.build_argv("switches", {"repo": HUB})[0][1:], ["switches", "list", "--repo", HUB])
        with self.assertRaises(ValueError):
            core.build_argv("switches", {"repo": "x; rm -rf /"})

    def test_refused_without_confirm(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs = core.JobManager(Path(tmp))
            with self.assertRaises(PermissionError):
                jobs.submit("switches-apply", {"plan_id": "0123456789abcdef", "apply": True}, confirm=False)
            self.assertEqual(jobs.order, [])

    def test_over_http(self):
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("fastapi not installed")
        import app as console_app
        client = TestClient(console_app.app, base_url="http://127.0.0.1:4001")
        r = client.post("/api/jobs", json={"op": "switches-apply", "params": {"plan_id": "0123456789abcdef", "apply": True}})
        self.assertEqual(r.status_code, 409)
        self.assertIn("confirm=true", r.json()["detail"])
        self.assertEqual(client.post("/api/switches/preview", json={"scope": "loop", "key": "x", "target": "off"}).status_code, 422)
        self.assertEqual(client.post("/api/switches/preview", json={"scope": "x", "target": "off", "reason": "r"}).status_code, 422)
        with mock.patch.object(console_app.switches, "plan", side_effect=ValueError("no loop 'x'")):
            r = client.post("/api/switches/preview", json={"scope": "loop", "key": "x", "target": "off", "reason": "why"})
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "no loop 'x'"))
        with mock.patch.object(console_app.switches, "document", return_value={"schema": sw.DOC_SCHEMA, "repos": []}) as d:
            self.assertEqual(client.get("/api/switches?refresh=true").json()["schema"], sw.DOC_SCHEMA)
        self.assertTrue(d.call_args.kwargs["refresh"])


class NoSecrets(Base):
    """§ 17.8: the token is used, never shown — not in a document, a plan, the CLI, the audit or the activity log."""

    def test_the_real_client_sends_the_token_and_never_returns_it(self):
        seen = []

        def http(method, url, *, headers, body, timeout=20.0):
            seen.append(headers.get("Authorization"))
            if url.endswith("/user"):
                return 200, {}, {"login": "bamr87"}
            if ORG.split("/")[0] in url:
                return 403, {}, {"message": f"Bad credentials for {TOKEN}"}
            return 200, {}, {"total_count": 1, "variables": [{"name": "FLEET_PM_ENABLED", "value": "true"}]}

        with mock.patch.object(ghl, "_http", side_effect=http), mock.patch.object(ghl, "token_source", return_value=("GH_TOKEN", TOKEN)):
            doc = sw.document(self.root, refresh=True)
        self.assertIn(f"Bearer {TOKEN}", seen)
        blob = json.dumps(doc)
        self.assertNotIn(TOKEN, blob)
        org = next(r for r in doc["repos"] if r["repo"] == ORG)
        self.assertFalse(org["readable"])
        self.assertIn("403", org["error"])

    @unittest.skipUnless(HAS_RUAMEL, "ruamel.yaml absent")
    def test_nothing_written_or_printed_carries_it(self):
        gh = FakeGitHub(LIVE, unreadable=(ORG,))
        out = io.StringIO()
        with mock.patch.object(sw, "ROOT", self.root), mock.patch.object(sw, "_api", side_effect=lambda api: api or gh), \
                mock.patch.object(sw, "gh_login", return_value="bamr87"), contextlib.redirect_stdout(out):
            self.assertEqual(sw.main(["list", "--json"]), 0)
            self.assertEqual(sw.main(["plan", "--all", "--to", "off", "--reason", "pause everything"]), 0)
            plan_id = next(p.stem for p in (self.root / ".fleet" / "switches" / "plans").iterdir())
            self.assertEqual(sw.main(["apply", "--plan-id", plan_id, "--apply"]), 0)
        files = [p for p in self.root.rglob("*") if p.is_file()]
        self.assertTrue(any(p.name == "github-writes.jsonl" for p in files) and any(p.name == "activity.jsonl" for p in files))
        for p in files:
            self.assertNotIn(TOKEN, p.read_text(), p.name)
        self.assertNotIn(TOKEN, out.getvalue())
        self.assertIn("unreadable", out.getvalue())


if __name__ == "__main__":
    unittest.main()
