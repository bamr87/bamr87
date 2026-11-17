#!/usr/bin/env python3
"""Offline tests for the weekend's other stages: Saturday's preflight (tools/weekly/prepare.py),
Sunday's plan (tools/weekly/agenda.py), the dispatcher and command line (tools/weekly/cli.py), what
`confirm` gained, and the installer. No network: `gh`, `docker` and `launchctl` are functions the
tests supply, on throwaway git repositories where git's behaviour is the point.
Run: python3 tools/test_weekly_stages.py
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import time
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import test_weekly as base  # noqa: E402  (the git fixtures; its tests are not re-run from here)
from tools.weekly import agenda, cli, core, prepare  # noqa: E402

WEEK = "2026-W47"
START, END = prepare.week_window(WEEK)
NOW = datetime(2026, 11, 14, 17, 37, tzinfo=timezone.utc)
CFG = prepare.config({})


def done(code=0, out="", err=""):
    return subprocess.CompletedProcess([], code, out, err)


class Cron(unittest.TestCase):
    def test_the_window_is_monday_to_monday_in_utc(self):
        self.assertEqual((START.isoformat(), END.isoformat()), ("2026-11-16T00:00:00+00:00", "2026-11-23T00:00:00+00:00"))

    def test_fires(self):
        for cron, count in (("37 5 * * *", 7), ("7 2 * * 1", 1), ("23 */6 * * *", 28), ("17 6 * * 0", 1), ("0 12 1 * *", 0),
                            ("30 9 * * 1-5", 5), ("*/15 3 * * 6", 4)):
            self.assertEqual(len(prepare.fires(cron, START, END)), count, cron)

    def test_the_first_fire_is_where_cron_puts_it(self):
        self.assertEqual(prepare.fires("7 2 * * 1", START, END)[0].isoformat(), "2026-11-16T02:07:00+00:00")
        self.assertEqual(prepare.fires("17 6 * * 0", START, END)[0].isoformat(), "2026-11-22T06:17:00+00:00")

    def test_day_of_month_or_day_of_week_when_both_are_set(self):
        got = [t.day for t in prepare.fires("0 0 18 * 2", START, END)]  # Tuesday the 17th, and the 18th
        self.assertEqual(got, [17, 18])

    def test_a_cron_that_does_not_parse_is_none(self):
        for cron in ("", "every day", "61 5 * * *", "5 * * *"):
            self.assertIsNone(prepare.fires(cron, START, END), cron)


class Switches(unittest.TestCase):
    ON = {"global": {"state": "on"}, "groups": {"g": {"state": "on"}}}

    def entry(self, **over):
        return {"repo": "o/r", "group": "g", "default": "on", "state": "unverified",
                "gate": {"kind": "repo_variable", "name": "X_ENABLED", "semantics": "opt_out"}, **over}

    def state(self, entry, switches=None, fleet=None, value=None, error=None):
        live = (lambda repo, name: (value, error)) if value is not None or error else None
        return prepare.switch_state(entry, switches or self.ON, fleet or {}, live)

    def test_the_most_restrictive_level_wins(self):
        self.assertFalse(self.state(self.entry(), {"global": {"state": "off", "reason": "freeze"}, "groups": {}}, value="true")["on"])
        self.assertFalse(self.state(self.entry(), {"global": {"state": "on"}, "groups": {"g": {"state": "off"}}}, value="true")["on"])

    def test_an_opt_out_variable_is_on_unless_it_says_false(self):
        self.assertTrue(self.state(self.entry(), value="")["on"])
        self.assertTrue(self.state(self.entry(), value="true")["on"])
        got = self.state(self.entry(), value="false")
        self.assertEqual((got["on"], got["verified"], got.get("drift")), (False, True, True))

    def test_an_opt_in_variable_is_off_unless_it_says_true(self):
        entry = self.entry(default="off", gate={"kind": "repo_variable", "name": "X_ENABLED", "semantics": "opt_in"})
        self.assertEqual((self.state(entry, value="")["on"], self.state(entry, value="").get("drift")), (False, False))
        got = self.state(entry, value="true")
        self.assertEqual((got["on"], got.get("drift")), (True, True))

    def test_a_variable_that_cannot_be_read_is_unknown(self):
        self.assertIsNone(self.state(self.entry(), error="HTTP 403")["on"])

    def test_without_a_live_read_the_default_stands_unverified(self):
        got = self.state(self.entry())
        self.assertEqual((got["on"], got["verified"]), (True, False))

    def test_a_fleet_config_gate_reads_the_file(self):
        entry = self.entry(gate={"kind": "fleet_config", "name": "rotation.enabled"})
        self.assertTrue(self.state(entry, fleet={"rotation": {"enabled": True}})["on"])
        self.assertFalse(self.state(entry, fleet={"rotation": {"enabled": False}})["on"])
        self.assertIsNone(self.state(entry, fleet={})["on"])

    def test_reading_a_variable(self):
        self.assertEqual(prepare.variable_value("o/r", "X", lambda cmd, **k: done(0, "true\n")), ("true", None))
        self.assertEqual(prepare.variable_value("o/r", "X", lambda cmd, **k: done(1, "", "HTTP 404: Not Found")), ("", None))
        self.assertEqual(prepare.variable_value("o/r", "X", lambda cmd, **k: done(1, "", "HTTP 403"))[0], None)


FLEET = {"hub": {"repo": "o/hub"},
         "switches": {"global": {"state": "on"}, "groups": {"g": {"state": "on"}}, "loops": {
             "hub/pulse": {"repo": "o/hub", "workflow": ".github/workflows/pulse.yml", "group": "g", "default": "on", "state": "on",
                           "gate": {"kind": "none"}, "cron": "37 5 * * *"},
             "hub/off": {"repo": "o/hub", "workflow": ".github/workflows/off.yml", "group": "g", "default": "off", "state": "off",
                         "gate": {"kind": "none"}, "cron": "7 7 * * *", "flip": "gh variable set OFF_ENABLED"},
             "hub/local": {"repo": "o/hub", "workflow": "tools/weekly/cli.py", "group": "g", "default": "on", "state": "on", "gate": {"kind": "none"}}}}}
REGISTRY = {"repos": [{"repo": "site", "nwo": "o/site"}],
            "schedule": [{"repo": "hub", "path": ".github/workflows/pulse.yml", "cron": "37 5 * * *", "ai": True},
                         {"repo": "site", "path": ".github/workflows/build.yml", "cron": "10 11 * * *", "ai": False},
                         {"repo": "site", "path": ".github/workflows/odd.yml", "cron": "whenever", "ai": False}]}
USAGE = {"generated_at": "2026-11-13 05:40 UTC", "workflows": [
    {"repo": "hub", "repo_url": "https://github.com/o/hub", "path": ".github/workflows/pulse.yml", "last_conclusion": "success", "last_run_at": "2026-11-13T05:40:00+00:00", "runs": 9, "success_rate_pct": 100},
    {"repo": "site", "repo_url": "https://github.com/o/site", "path": ".github/workflows/build.yml", "last_conclusion": "failure", "last_run_at": "2026-11-12T11:10:00+00:00", "runs": 9, "success_rate_pct": 60}]}


class Activities(unittest.TestCase):
    def setUp(self):
        self.rows = {r["id"]: r for r in prepare.activities(FLEET, REGISTRY, USAGE, WEEK, CFG)}

    def test_each_workflow_appears_once_with_its_state(self):
        self.assertEqual({k: v["state"] for k, v in self.rows.items()},
                         {"hub/pulse": "ready", "hub/off": "off", "site:build": "at-risk", "site:odd": "unknown"})

    def test_a_local_job_in_the_switch_map_is_not_a_utc_cron(self):
        self.assertNotIn("hub/local", self.rows)

    def test_the_last_result_is_joined_through_the_repo_url(self):
        self.assertEqual(self.rows["hub/pulse"]["last_conclusion"], "success")
        self.assertIn("its last run ended failure on 2026-11-12", self.rows["site:build"]["notes"])

    def test_a_switched_off_loop_says_how_to_turn_it_on(self):
        self.assertIn("gh variable set OFF_ENABLED", " ".join(self.rows["hub/off"]["notes"]))

    def test_the_calendar_shows_the_hub_and_counts_the_rest(self):
        days = prepare.calendar(list(self.rows.values()), WEEK, "o/hub", tz=timezone.utc)
        self.assertEqual([d["name"] for d in days], list(prepare.DAY_NAMES))
        self.assertEqual([[s["id"] for s in d["hub"]] for d in days], [["hub/pulse"]] * 7)
        self.assertEqual([d["fleet"] for d in days], [1] * 7)

    def test_days_are_the_readers_own(self):
        west = timezone(timedelta(hours=-7))
        days = prepare.calendar(list(self.rows.values()), WEEK, "o/hub", tz=west)
        self.assertEqual([(d["name"], d["date"]) for d in days][0], ("Sunday", "2026-11-15"))
        self.assertEqual(len(days), 8)
        self.assertEqual(days[0]["hub"][0]["local"], "Sun 22:37")       # Monday 05:37 UTC
        self.assertEqual(sum(len(d["hub"]) for d in days), 7)
        for d in days:
            self.assertEqual([s["at"] for s in d["hub"]], sorted(s["at"] for s in d["hub"]))

    def test_at_risk_sorts_first(self):
        self.assertEqual(prepare.activities(FLEET, REGISTRY, USAGE, WEEK, CFG)[0]["state"], "at-risk")


class Checks(base.Repo):
    def write(self, rel, text):
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_credentials_are_judged_from_the_ledgers(self):
        self.write("_data/token_rotation.yml", "tokens:\n- {name: OK, oldest_age_days: 3, max_age_days: 45, attention: [], counts: {repos: 2, missing: 0}}\n"
                   "- {name: OLD, oldest_age_days: 40, max_age_days: 45, attention: [], counts: {repos: 2, missing: 0}}\n"
                   "- {name: GONE, oldest_age_days: 1, max_age_days: 45, attention: [], counts: {repos: 2, missing: 1}}\n")
        self.write("_data/api_keys.yml", "slots:\n  a: {expires_at: '2026-11-18 00:00:00+00:00'}\n  b: {expires_at: '2026-12-25 00:00:00+00:00'}\n  c: {}\n"
                   "  d: {expires_at: '2026-10-22 22:56:23.892000+00:00'}\n")
        checks = {k["name"]: k for k in prepare.credential_checks(self.repo, WEEK, NOW)}
        self.assertEqual({n: k["state"] for n, k in checks.items()},
                         {"token OK": "ready", "token OLD": "at-risk", "token GONE": "at-risk",
                          "API key a": "at-risk", "API key b": "ready", "API key c": "unknown", "API key d": "at-risk"})
        self.assertIn("inside the week", checks["API key a"]["why"])
        self.assertIn("expired 2026-10-22", checks["API key d"]["why"])

    def test_a_tokens_age_counts_the_days_since_the_ledger_was_written(self):
        self.write("_data/token_rotation.yml", "generated_at: 2026-11-04 02:20 UTC\ntokens:\n"
                   "- {name: T, oldest_age_days: 30, max_age_days: 45, attention: [], counts: {repos: 1, missing: 0}}\n"
                   "- {name: PAST, oldest_age_days: 40, max_age_days: 45, attention: [], counts: {repos: 1, missing: 0}}\n")
        checks = {k["name"]: k for k in prepare.credential_checks(self.repo, WEEK, NOW)}
        self.assertIn("40 days old: it passes its 45-day limit before the week ends", checks["token T"]["why"])
        self.assertIn("50 days old, past its 45-day limit", checks["token PAST"]["why"])

    def test_a_value_that_strays_into_a_ledger_is_never_repeated(self):
        """The ledgers hold names and dates. If a value ever lands in one, the checks still print only
        the fields they name: the name, the ages, the counts and the attention notes."""
        token = "ghp_" + "a1B2" * 9
        self.write("_data/token_rotation.yml", f"tokens:\n- {{name: T, value: {token}, oldest_age_days: 99, max_age_days: 45, attention: [], "
                   f"counts: {{repos: 1}}, repos: [{{nwo: o/r, secret: {token}}}]}}\n")
        self.write("_data/api_keys.yml", f"slots:\n  a: {{expires_at: '2026-11-18 00:00:00+00:00', key: {token}, key_id: {token}}}\n")
        text = json.dumps(prepare.credential_checks(self.repo, WEEK, NOW))
        self.assertNotIn(token, text)
        self.assertIn("token T", text)

    def test_sources_are_held_to_their_freshness(self):
        self.write("_data/a.yml", "generated_at: 2026-11-13 05:40 UTC\n")
        self.write("_data/b.yml", "generated_at: '2026-11-01T00:00:00Z'\n")
        fleet = {"harness": {"sources": {"fresh": {"path": "_data/a.yml", "slo_days": 3, "writer": "w"},
                                         "old": {"path": "_data/b.yml", "slo_days": 3, "writer": "pulse"},
                                         "on-change": {"path": "_data/a.yml", "slo": "on-change"},
                                         "missing": {"path": "_data/none.yml", "slo_days": 1}}}}
        got = {k["name"]: k for k in prepare.source_checks(self.repo, fleet, NOW)}
        self.assertEqual({n: k["state"] for n, k in got.items()}, {"source fresh": "ready", "source old": "at-risk"})
        self.assertIn("pulse", got["source old"]["fix"])

    def test_the_budget_is_read_against_the_scheduled_ceiling(self):
        room = types.SimpleNamespace(spent_usd=10.0, ceiling_usd=40.0, month="2026-11")
        none = types.SimpleNamespace(spent_usd=39.5, ceiling_usd=40.0, month="2026-11")
        self.assertEqual(prepare.budget_checks({}, None, lambda scheduled: room)[0]["state"], "ready")
        got = prepare.budget_checks({}, None, lambda scheduled: none)[0]
        self.assertEqual(got["state"], "at-risk")
        self.assertIn("API-equivalent", got["why"])

        def broken(scheduled):
            raise OSError("no ledger")
        self.assertEqual(prepare.budget_checks({}, None, broken)[0]["state"], "unknown")

    def test_a_breached_fleet_budget_is_at_risk(self):
        registry = {"trends": {"ai_cost_usd": {"status": "breach", "projected_monthly": 394.7, "budget_monthly": 200}}}
        got = prepare.budget_checks({}, registry, lambda s: types.SimpleNamespace(spent_usd=0, ceiling_usd=40, month="m"))
        self.assertEqual([k["state"] for k in got], ["ready", "at-risk"])

    def test_only_a_listed_command_is_refreshed(self):
        ran = []
        cfg = {**CFG, "refresh": ["tools/dash decisions refresh", "rm -rf /", "tools/dash x; rm -rf /", "tools/dash x > /etc/passwd",
                                  "tools/dash $(whoami)", "tools/dash weekly confirm --apply --merge", "tools/dash weekly close --apply",
                                  "tools/dash decisions refresh --anything", "tools/dash  decisions   refresh"]}
        out = prepare.refresh(self.repo, cfg, lambda cmd, **k: ran.append(cmd) or done(0, "fresh\n"))
        self.assertEqual(ran, [["tools/dash", "decisions", "refresh"]] * 2)     # the last differs only in spacing
        self.assertEqual([r["ok"] for r in out], [True, False, False, False, False, False, False, False, True])

    def test_part_of_a_listed_command_is_not_the_command(self):
        ran = []
        cfg = {**CFG, "refresh": ["tools/dash", "tools/dash decisions", "tools/dash lake", "decisions refresh", ""]}
        out = prepare.refresh(self.repo, cfg, lambda cmd, **k: ran.append(cmd) or done(0))
        self.assertEqual((ran, [r["ok"] for r in out]), ([], [False] * 5))
        self.assertEqual(prepare.refresh(self.repo, {**CFG, "refresh": None}, lambda cmd, **k: self.fail("ran")), [])

    def test_nothing_refreshable_writes(self):
        for command in prepare.REFRESHABLE:
            self.assertRegex(command, r"^tools/dash (decisions refresh|lake status --no-probe)$")

    def test_local_jobs_report_what_launchd_has_loaded(self):
        self.write("_data/agents.yml", "agents:\n- {id: 'local:weekly', kind: local-job, trigger: 'launchd com.bamr87.weekly: on a calendar', where: tools/install-weekly.sh}\n"
                   "- {id: 'ci:x', kind: ci-scheduled}\n")
        asked = []
        got = prepare.local_jobs(self.repo, lambda cmd, **k: asked.append(cmd) or done(113))
        self.assertEqual([(j["label"], j["loaded"]) for j in got], [("com.bamr87.weekly", False)])
        self.assertEqual(asked[0][:2], ["launchctl", "print"])


ASKED: list[list[str]] = []
#: Every external command a read-and-report stage may run. Anything else is a write, or a new read to review.
READS = (["docker", "info"], ["gh", "api", "user"], ["gh", "variable", "get"], ["launchctl", "print"], ["gh", "pr", "view"],
         ["gh", "issue", "view"], ["gh", "issue", "list"], ["gh", "api"])


def only_reads(commands):
    return [c for c in commands if not any(c[:len(r)] == r for r in READS)]


def fake_tools(cmd, **kwargs):
    ASKED.append(list(cmd))
    if cmd[0] == "docker":
        return done(0, "29.0\n")
    if cmd[:3] == ["gh", "api", "user"]:
        return done(0, "octo\n")
    if cmd[:3] == ["gh", "variable", "get"]:
        return done(1, "", "HTTP 404")
    if cmd[0] == "launchctl":
        return done(113)
    return done(0, "ok\n")


class Hub(base.Repo):
    """A small hub with a switch map, for whole stages."""

    def setUp(self):
        super().setUp()
        (self.repo / "_data").mkdir()
        (self.repo / "_data" / "fleet.yml").write_text(json.dumps({**FLEET, "weekly": {"prepare": {"refresh": []}}}))
        (self.repo / "_data" / "harness_registry.yml").write_text(json.dumps(REGISTRY))
        (self.repo / "_data" / "actions_usage.yml").write_text(json.dumps(USAGE))
        (self.repo / "_data" / "work_queue.yml").write_text("schema: work-queue/v1\norder: []\npriority: {}\nnotes: {}\n")
        base.g(self.repo, "add", "-A")
        base.g(self.repo, "commit", "-q", "-m", "feat: the hub (#1)")
        base.g(self.repo, "push", "-q", "origin", "main")
        self.state = self.tmp / "state"

    def fingerprint(self):
        return (base.g(self.repo, "for-each-ref"), base.g(self.repo, "status", "--porcelain"), base.g(self.repo, "rev-parse", "HEAD"),
                base.g(self.origin, "for-each-ref"))

    def quiet(self, fn, *args, **kwargs):
        with mock.patch.object(core, "notify"), contextlib.redirect_stdout(io.StringIO()) as out:
            code = fn(*args, **kwargs)
        return code, out.getvalue()

    def run_of(self, stage):
        return core.latest(self.state, stage)


class Prepare(Hub):
    def go(self, **flags):
        args = argparse.Namespace(scheduled=False, offline=False, **flags)
        return self.quiet(cli.cmd_prepare, args, self.repo, self.state, now=NOW, runner=fake_tools,
                          position=lambda s: types.SimpleNamespace(spent_usd=1.0, ceiling_usd=40.0, month="2026-11"))

    def test_it_reports_and_changes_nothing(self):
        before = self.fingerprint()
        del ASKED[:]
        code, out = self.go()
        self.assertEqual(code, 0)
        self.assertEqual(self.fingerprint(), before)
        self.assertTrue(ASKED)
        self.assertEqual(only_reads(ASKED), [])
        folder, rec = self.run_of("prepare")
        self.assertEqual((rec["stage"], rec["week"], rec["counts"]["ready"], rec["counts"]["at-risk"]), ("prepare", WEEK, 1, 1))
        self.assertTrue(folder.name.endswith("-prepare"))
        self.assertIn("## Fix before Monday", out)
        self.assertIn("site:build", out)
        doc = json.loads((folder / "prepare.json").read_text())
        self.assertEqual(doc["window"]["start"], START.isoformat())
        self.assertIn("Saturday: direction for the week", (folder / "grok-brief.md").read_text())

    def test_a_scheduled_run_honours_the_switch(self):
        (self.repo / "_data" / "fleet.yml").write_text(json.dumps({**FLEET, "weekly": {"enabled": False}}))
        code, out = self.quiet(cli.cmd_prepare, argparse.Namespace(scheduled=True, offline=False), self.repo, self.state, now=NOW, runner=fake_tools)
        self.assertEqual((code, self.run_of("prepare")), (3, None))
        self.assertIn("weekly.enabled is false", out)

    def test_it_does_not_count_toward_the_report_only_fridays(self):
        self.quiet(cli.cmd_prepare, argparse.Namespace(scheduled=True, offline=True), self.repo, self.state, now=NOW, runner=fake_tools,
                   position=lambda s: types.SimpleNamespace(spent_usd=1.0, ceiling_usd=40.0, month="m"))
        self.assertEqual(core.scheduled_count(self.state), 0)


def item(number, labels=(), kind="issue", repo="o/r", created="2026-10-01T00:00:00Z"):
    return {"repo": repo, "number": number, "title": f"t{number}", "url": f"u{number}", "labels": list(labels), "kind": kind, "created_at": created}


MODEL = {"generated_at": "2026-11-13T00:00:00Z", "repos": [{"repo": "o/r", "prs": {}, "items": [
    item(1, ["P0"]), item(2, ["P3"]), item(3, ["P3", "executor:claude-code"]), item(4, ["needs-amr"])]}], "board": {"items": []}}


class Agenda(unittest.TestCase):
    def plan(self, boost=None, queue=None):
        return core.rank(MODEL, queue or {}, core.load_config({}), [], NOW, boost)

    def test_a_handoff_outranks_priority_and_not_a_pin(self):
        told = {"handoffs": ["o/r#2"]}
        boost = agenda.handoff_boost(MODEL, told, "executor:claude-code", 2000)
        self.assertEqual(sorted(boost), ["o/r#2", "o/r#3"])
        order = [r["ref"] for r in self.plan(boost)["lanes"]["do"]]
        self.assertEqual(order[-1], "o/r#1")
        self.assertEqual(set(order[:2]), {"o/r#2", "o/r#3"})
        pinned = [r["ref"] for r in self.plan(boost, {"order": ["issue:o/r#1"]})["lanes"]["do"]]
        self.assertEqual(pinned[0], "o/r#1")

    def test_the_reason_says_it_was_handed_off(self):
        boost = agenda.handoff_boost(MODEL, {"handoffs": ["o/r#2"]}, "executor:claude-code", 2000)
        rows = {r["ref"]: r for r in self.plan(boost)["lanes"]["do"]}
        self.assertEqual(rows["o/r#2"]["reasons"][0], "handed off for this week")
        self.assertEqual(rows["o/r#3"]["reasons"][0], "labelled executor:claude-code")

    def test_without_a_boost_the_ranking_is_unchanged(self):
        self.assertEqual(self.plan(), self.plan({}))

    def test_handoffs_are_sorted_into_planned_unplanned_and_not_open(self):
        plan = {"lanes": {"decide": [], "finish": [], "unblock": [], "do": [{"ref": "o/r#2"}]}}
        got = agenda.handoff_status(MODEL, {"handoffs": ["o/r#2", "o/r#3", "o/gone#9"]}, plan)
        self.assertEqual(got, {"planned": ["o/r#2"], "unplanned": ["o/r#3"], "not_open": ["o/gone#9"]})

    def test_saturdays_findings_are_shortened(self):
        prep = {"checks": [prepare.check("token T", "at-risk", "old", "rotate"), prepare.check("disk", "ready", "fine")],
                "activities": [{"id": "a", "state": "at-risk", "notes": ["failed"]}, {"id": "b", "state": "ready", "notes": []}],
                "local_jobs": [{"label": "com.bamr87.weekly", "loaded": False, "installer": "tools/install-weekly.sh"}], "counts": {"at-risk": 1}}
        got = agenda.readiness(prep, 2)
        self.assertEqual((got["ran"], len(got["fix"]), got["more"]), (True, 2, 1))
        self.assertEqual(agenda.readiness(None, 5)["ran"], False)

    def test_each_day_gets_its_focus_lane_and_its_loops(self):
        calendar = prepare.calendar(prepare.activities(FLEET, REGISTRY, USAGE, WEEK, CFG), WEEK, "o/hub", tz=timezone.utc)
        days = agenda.days(calendar, self.plan(), agenda.config({}))
        by = {d["name"]: d for d in days}
        self.assertEqual((by["Monday"]["focus"], [i["ref"] for i in by["Monday"]["items"]]), ("decide", ["o/r#4"]))
        self.assertEqual((by["Friday"]["focus"], by["Friday"]["items"]), ("close", []))
        self.assertEqual(by["Sunday"]["focus"], None)
        self.assertEqual(by["Monday"]["loops"][0]["id"], "hub/pulse")

    def brief(self, **over):
        record = {"week": WEEK, "plan": self.plan(), "errors": [], "confirmed": False, "days": [], "handoffs": {},
                  "readiness": {"ran": False, "fix": []}, "direction": {"found": False, "title": f"Week {WEEK} — close-out and plan"}}
        record.update(over)
        record["headline"] = agenda.headline(record)
        return agenda.render(record)

    def test_the_brief_starts_with_what_to_do_first(self):
        text = self.brief()
        self.assertLess(text.index("## First thing Monday"), text.index("## The plan"))
        self.assertIn("tools/dash weekly confirm", text)
        self.assertIn("Saturday's preflight did not run", text)
        self.assertIn("the Grok half has not set direction", text)
        self.assertIn("[o/r#4](u4)", text)

    def test_a_quiet_week_says_so(self):
        quiet = {"lanes": {lane: [] for lane in core.LANES}, "ranked": 0, "held": 0, "by_lane": {lane: 0 for lane in core.LANES}}
        text = self.brief(plan=quiet, confirmed=True, readiness={"ran": True, "fix": [], "counts": {}})
        self.assertIn("Nothing is waiting", text)

    def test_the_direction_issue_is_linked_with_what_is_missing(self):
        text = self.brief(direction={"found": True, "title": "Week 2026-W47 — close-out and plan", "url": "https://x/3", "sections": ["friday"]},
                          handoffs={"planned": ["o/r#2"], "unplanned": ["o/r#3"], "not_open": []})
        self.assertIn("friday done, saturday missing, sunday missing", text)
        self.assertIn("In the plan: o/r#2", text)


class Plan(Hub):
    def go(self, model=MODEL, told=None, **flags):
        (self.repo / ".fleet" / "pm").mkdir(parents=True, exist_ok=True)
        (self.repo / ".fleet" / "pm" / "model.json").write_text(json.dumps(model))
        (self.repo / ".fleet" / "pm" / "review.json").write_text("{}")
        args = argparse.Namespace(scheduled=False, offline=False, **flags)
        with mock.patch.object(core, "run_pm", return_value={"ok": True, "error": None}):
            return self.quiet(cli.cmd_plan, args, self.repo, self.state, now=NOW,
                              direction=lambda week, fleet: told or {"title": f"Week {week} — close-out and plan", "found": False, "handoffs": [], "sections": [], "error": None},
                              read_index=lambda root, offline: (None, None, None, "no index in this test"))

    def test_it_writes_the_brief_and_only_its_run_folder(self):
        base.g(self.repo, "add", "-A")  # nothing staged yet; .fleet is created by the run and is untracked either way
        before = self.fingerprint()
        code, out = self.go()
        self.assertEqual(code, 0)
        after = self.fingerprint()
        self.assertEqual((after[0], after[2], after[3]), (before[0], before[2], before[3]))
        folder, rec = self.run_of("plan")
        self.assertTrue(folder.name.endswith("-plan"))
        self.assertEqual((rec["stage"], rec["plan"]["ranked"], rec["confirmed"]), ("plan", 4, False))
        self.assertIn("# The week ahead: 2026-W47", out)
        self.assertEqual(sorted(rec["open_keys"]), ["issue:o/r#1", "issue:o/r#2", "issue:o/r#3", "issue:o/r#4"])
        self.assertIn("Sunday: the plan sign-off", (folder / "grok-brief.md").read_text())

    def test_what_grok_handed_off_leads_the_do_lane(self):
        told = {"title": "Week 2026-W47 — close-out and plan", "found": True, "url": "https://x/3", "sections": ["saturday"], "handoffs": ["o/r#2"], "error": None}
        self.go(told=told)
        _, rec = self.run_of("plan")
        self.assertIn(rec["plan"]["lanes"]["do"][0]["ref"], ("o/r#2", "o/r#3"))
        self.assertEqual(rec["handoffs"]["planned"], ["o/r#2"])

    def test_saturdays_run_for_the_same_week_feeds_the_brief(self):
        self.quiet(cli.cmd_prepare, argparse.Namespace(scheduled=False, offline=False), self.repo, self.state,
                   now=NOW - timedelta(hours=30), runner=fake_tools, position=lambda s: types.SimpleNamespace(spent_usd=1.0, ceiling_usd=40.0, month="m"))
        _, out = self.go()
        _, rec = self.run_of("plan")
        self.assertTrue(rec["readiness"]["ran"])
        self.assertIn("Fix what Saturday found", out)

    def test_sunday_reads_the_candidates_live_as_friday_did(self):
        index = {"prs": {"a": {"type": "pr", "repo": "o/r", "number": 1, "title": "ci: y", "url": "u", "author": "bamr87", "bot": False,
                               "labels": [], "draft": False, "created_at": "2026-11-01T00:00:00Z", "updated_at": "2026-11-12T00:00:00Z",
                               "enrich": {"mergeable": "MERGEABLE", "merge_state": "CLEAN", "checks": "SUCCESS", "review": None}}}}
        (self.repo / "_data" / "fleet.yml").write_text(json.dumps({**FLEET, "jev": {"allowed_authors": ["bamr87"]}}))
        (self.repo / ".fleet" / "pm").mkdir(parents=True, exist_ok=True)
        (self.repo / ".fleet" / "pm" / "model.json").write_text(json.dumps(MODEL))
        asked = []

        def gh(cmd, **kwargs):
            asked.append(list(cmd))
            if cmd[:3] == ["gh", "pr", "view"]:
                return done(0, json.dumps({**Confirm.LIVE, "files": [{"path": ".github/workflows/ci.yml", "changeType": "MODIFIED"}]}))
            return done(0, json.dumps(Confirm.FACTS))
        with mock.patch.object(core, "run_pm", return_value={"ok": True, "error": None}):
            code, out = self.quiet(cli.cmd_plan, argparse.Namespace(scheduled=False, offline=False), self.repo, self.state, now=NOW,
                                   direction=lambda w, f: {"title": "t", "found": False, "handoffs": [], "sections": [], "error": None},
                                   read_index=lambda root, offline: (index, lambda rec, cfg: ([], [], {}), None, "fresh"), runner=gh)
        _, rec = self.run_of("plan")
        self.assertEqual((rec["closeout"]["counts"]["merge"]["pr"], rec["closeout"]["counts"]["amr"]["pr"], rec["closeout"]["scanned"]), (0, 1, True))
        self.assertEqual(only_reads(asked), [])
        self.assertIn("0 ready to merge", out)

    def test_no_model_is_a_failed_plan_that_still_reports(self):
        args = argparse.Namespace(scheduled=False, offline=False)
        with mock.patch.object(core, "run_pm", return_value={"ok": False, "error": "rate limited"}):
            code, out = self.quiet(cli.cmd_plan, args, self.repo, self.state, now=NOW, direction=lambda w, f: {"title": "t", "found": False, "handoffs": [], "sections": [], "error": None},
                                   read_index=lambda root, offline: (None, None, None, "none"))
        self.assertEqual(code, 1)
        self.assertIn("pm review: rate limited", out)


def local(text):
    return datetime.fromisoformat(text).astimezone()


SCHEDULE = core.load_config({})["schedule"]


class Dispatcher(unittest.TestCase):
    def due(self, when, ran=()):
        return cli.due_stages(local(when), SCHEDULE, lambda stage, since: stage in ran)

    def test_slots(self):
        friday = cli.slot_before(local("2026-11-14T09:00:00"), SCHEDULE["close"])
        self.assertEqual((friday.strftime("%a %H:%M"), friday.day), ("Fri 22:37", 13))
        self.assertEqual(cli.slot_after(friday, SCHEDULE["prepare"]).strftime("%a %d %H:%M"), "Sat 14 10:37")
        self.assertEqual(cli.slot_after(local("2026-11-14T10:37:00"), SCHEDULE["plan"]).strftime("%a %d %H:%M"), "Sun 15 16:37")
        self.assertEqual(cli.slot_before(local("2026-11-13T22:37:00"), SCHEDULE["close"]).day, 13)

    def test_nothing_is_due_before_fridays_slot(self):
        self.assertEqual(self.due("2026-11-13T22:34:00"), [])
        self.assertEqual(self.due("2026-11-11T12:00:00"), [])

    def test_a_firing_a_moment_early_is_its_slot(self):
        self.assertEqual(self.due("2026-11-13T22:36:58"), ["close"])
        self.assertEqual(self.due("2026-11-14T10:36:30", ran=["close"]), ["prepare"])
        self.assertEqual(self.due("2026-11-15T16:36:00", ran=["close", "prepare"]), ["plan"])
        self.assertEqual(self.due("2026-11-15T16:34:00", ran=["close", "prepare"]), [])

    def test_a_schedule_that_cannot_work_is_named(self):
        ok = cli.schedule_problem
        self.assertIsNone(ok(SCHEDULE))
        for change, said in (({"close": {"weekday": 5, "hour": 22, "minute": 0}}, "never on the hour"),
                             ({"close": {"weekday": 5, "hour": 22.9, "minute": 5}}, "whole number"),
                             ({"close": {"weekday": True, "hour": 22, "minute": 5}}, "whole number"),
                             ({"close": {"weekday": 8, "hour": 22, "minute": 5}}, "from 0 to 7"),
                             ({"prepare": {"weekday": 4, "hour": 9, "minute": 5}}, "in that order"),
                             ({"plan": {"weekday": 5, "hour": 9, "minute": 5}}, "in that order"),
                             ({"prepare": SCHEDULE["close"]}, "in that order"),
                             ({"plan": "sunday"}, "is missing"), ({"catch_up_hours": "long"}, "catch_up_hours")):
            self.assertIn(said, ok({**SCHEDULE, **change}) or "", change)

    def test_each_stage_is_due_from_its_slot(self):
        self.assertEqual(self.due("2026-11-13T22:37:00"), ["close"])
        self.assertEqual(self.due("2026-11-14T10:37:00", ran=["close"]), ["prepare"])
        self.assertEqual(self.due("2026-11-15T16:37:00", ran=["close", "prepare"]), ["plan"])
        self.assertEqual(self.due("2026-11-15T20:00:00", ran=["close", "prepare", "plan"]), [])

    def test_a_missed_stage_runs_first_and_in_order(self):
        self.assertEqual(self.due("2026-11-14T08:00:00"), ["close"])
        self.assertEqual(self.due("2026-11-14T11:00:00"), ["close", "prepare"])
        self.assertEqual(self.due("2026-11-16T09:00:00"), ["close", "prepare", "plan"])
        self.assertEqual(self.due("2026-11-16T09:00:00", ran=["prepare"]), ["close", "plan"])

    def test_the_weekend_ends(self):
        self.assertEqual(self.due("2026-11-16T10:38:00"), [])
        self.assertEqual(self.due("2026-11-17T09:00:00"), [])

    def test_every_slot_is_off_the_hour(self):
        for stage in core.STAGES:
            self.assertNotEqual(SCHEDULE[stage]["minute"], 0, stage)

    def in_zone(self, zone):
        old = os.environ.get("TZ")

        def restore():
            if old is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old
            time.tzset()
        self.addCleanup(restore)
        os.environ["TZ"] = zone
        time.tzset()

    def test_the_weekend_the_clocks_go_back_runs_each_stage_once(self):
        """Denver leaves daylight time on Sunday 2027-11-07. Friday's 22:37 was MDT (04:37 UTC); read on
        Sunday at a fixed -07:00 it would look like 21:37, before the slot, and the close would run again."""
        self.in_zone("America/Denver")
        friday_run = datetime(2027, 11, 6, 4, 38, tzinfo=timezone.utc)          # Friday 22:38 MDT
        saturday_run = datetime(2027, 11, 6, 16, 38, tzinfo=timezone.utc)       # Saturday 10:38 MDT
        ran = {"close": friday_run, "prepare": saturday_run}
        sunday = datetime(2027, 11, 7, 23, 40, tzinfo=timezone.utc)             # Sunday 16:40 MST
        due = cli.due_stages(sunday, SCHEDULE, lambda stage, since: stage in ran and cli.wall(ran[stage]) >= since)
        self.assertEqual(due, ["plan"])

    def test_the_weekend_the_clocks_go_forward_runs_each_stage_once(self):
        self.in_zone("America/Denver")
        ran = {"close": datetime(2027, 3, 13, 5, 38, tzinfo=timezone.utc), "prepare": datetime(2027, 3, 13, 17, 38, tzinfo=timezone.utc)}
        sunday = datetime(2027, 3, 14, 22, 40, tzinfo=timezone.utc)             # Sunday 16:40 MDT
        due = cli.due_stages(sunday, SCHEDULE, lambda stage, since: stage in ran and cli.wall(ran[stage]) >= since)
        self.assertEqual(due, ["plan"])

    def test_wall_time_is_the_machines_clock_without_a_zone(self):
        self.in_zone("America/Denver")
        self.assertEqual(cli.wall(datetime(2027, 11, 6, 4, 37, tzinfo=timezone.utc)), datetime(2027, 11, 5, 22, 37))
        self.assertEqual(cli.wall(datetime(2027, 11, 5, 22, 37)), datetime(2027, 11, 5, 22, 37))


class Auto(Hub):
    def go(self, when, codes=None):
        ran = []
        codes = codes or {}
        table = {stage: (lambda s=stage: ran.append(s) or codes.get(s, 0)) for stage in core.STAGES}
        code, out = self.quiet(cli.cmd_auto, argparse.Namespace(scheduled=True), self.repo, self.state, self.tmp / "archive",
                               now=local(when), stages=table)
        return code, ran, out

    def record(self, stage, started, scheduled=True, finished=True):
        folder = self.state / (f"{started.strftime('%Y%m%dT%H%M%SZ')}-{WEEK}" + ("" if stage == "close" else f"-{stage}"))
        folder.mkdir(parents=True)
        stamp = started.astimezone(timezone.utc).isoformat()                 # as a real run records it: in UTC, not local time
        (folder / "run.json").write_text(json.dumps({"id": folder.name, "stage": stage, "week": WEEK, "scheduled": scheduled,
                                                     "started": stamp, "finished": stamp if finished else None, "mode": "x"}))

    def test_it_runs_what_is_due_in_order(self):
        self.assertEqual(self.go("2026-11-14T11:00:00")[1], ["close", "prepare"])

    def test_a_run_is_judged_by_its_local_time_not_its_utc_digits(self):
        """West of Greenwich a run's UTC clock reads later than the wall: Friday 16:00 in Denver is 23:00
        UTC. Read without its zone, an afternoon run would look like it came after the 22:37 slot."""
        old = os.environ.get("TZ")

        def restore():
            if old is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old
            time.tzset()
        self.addCleanup(restore)
        os.environ["TZ"] = "America/Denver"
        time.tzset()
        self.record("close", local("2026-11-13T16:00:00"))
        self.assertEqual(self.go("2026-11-13T23:00:00")[1], ["close"])

    def test_a_stage_that_already_ran_this_weekend_is_not_repeated(self):
        self.record("close", local("2026-11-13T22:40:00"))
        self.assertEqual(self.go("2026-11-14T11:00:00")[1], ["prepare"])

    def test_last_weekends_runs_and_manual_or_unfinished_runs_do_not_count(self):
        self.record("close", local("2026-11-06T22:40:00"))
        self.assertEqual(self.go("2026-11-13T23:00:00")[1], ["close"])
        self.record("prepare", local("2026-11-14T10:40:00"), scheduled=False)
        self.record("plan", local("2026-11-15T16:40:00"), finished=False)
        self.assertEqual(self.go("2026-11-15T17:00:00")[1], ["close", "prepare", "plan"])

    def test_nothing_due_runs_nothing(self):
        code, ran, out = self.go("2026-11-11T12:00:00")
        self.assertEqual((code, ran), (0, []))
        self.assertIn("nothing is due", out)

    def test_switched_off_runs_nothing(self):
        (self.repo / "_data" / "fleet.yml").write_text(json.dumps({**FLEET, "weekly": {"enabled": False}}))
        self.assertEqual(self.go("2026-11-14T11:00:00")[:2], (3, []))

    def test_a_failed_stage_does_not_stop_the_next(self):
        code, ran, _ = self.go("2026-11-14T11:00:00", codes={"close": 1})
        self.assertEqual((code, ran), (1, ["close", "prepare"]))

    def test_a_stage_that_crashes_does_not_cost_the_weekend_the_next_one(self):
        ran = []

        def boom():
            ran.append("close")
            raise TypeError("unhashable type: 'list'")

        def held():
            ran.append("prepare")
            raise SystemExit("weekly: another run holds the lock")
        table = {"close": boom, "prepare": held, "plan": lambda: ran.append("plan") or 0}
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code, _ = self.quiet(cli.cmd_auto, argparse.Namespace(scheduled=True), self.repo, self.state, self.tmp / "archive",
                                 now=local("2026-11-16T09:00:00"), stages=table)
        self.assertEqual((code, ran), (1, ["close", "prepare", "plan"]))
        self.assertIn("close failed: TypeError", err.getvalue())

    def test_the_stages_it_starts_are_scheduled_and_never_forced_active(self):
        """`--apply` skips the report-only Fridays. The dispatcher must never pass it."""
        seen = []
        with mock.patch.object(core, "cmd_run", lambda args, *a, **k: seen.append(("close", args.scheduled, args.apply)) or 0), \
                mock.patch.object(cli, "cmd_prepare", lambda args, *a, **k: seen.append(("prepare", args.scheduled, getattr(args, "apply", False))) or 0), \
                mock.patch.object(cli, "cmd_plan", lambda args, *a, **k: seen.append(("plan", args.scheduled, getattr(args, "apply", False))) or 0):
            self.quiet(cli.cmd_auto, argparse.Namespace(scheduled=True), self.repo, self.state, self.tmp / "archive", now=local("2026-11-16T09:00:00"))
        self.assertEqual(seen, [("close", True, False), ("prepare", True, False), ("plan", True, False)])

    def test_a_schedule_that_cannot_work_runs_nothing(self):
        bad = {**FLEET, "weekly": {"schedule": {"plan": {"weekday": 5, "hour": 9, "minute": 5}}}}
        (self.repo / "_data" / "fleet.yml").write_text(json.dumps(bad))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code, ran, _ = self.go("2026-11-14T11:00:00")
        self.assertEqual((code, ran), (2, []))
        self.assertIn("in that order", err.getvalue())

    def test_a_truncated_run_record_is_skipped_not_fatal(self):
        self.record("close", local("2026-11-13T22:40:00"))
        broken = self.state / "20261114T000000Z-2026-W47-prepare"
        broken.mkdir()
        (broken / "run.json").write_text('{"id": "x", "stage": "prep')
        self.assertEqual(len(core.run_dirs(self.state)), 1)
        self.assertEqual(self.go("2026-11-14T11:00:00")[1], ["prepare"])
        self.assertEqual(self.quiet(core.cmd_status, self.state)[0], 0)


class CloseOutWiring(Hub):
    """Friday's whole run with the close-out, the gate scan and the agent in it: what it must not do."""

    INDEX = {"prs": {"a": {"type": "pr", "repo": "o/r", "number": 1, "title": "fix: x", "url": "u1", "author": "bamr87", "bot": False,
                           "labels": [], "draft": False, "created_at": "2026-11-01T00:00:00Z", "updated_at": "2026-11-12T00:00:00Z",
                           "enrich": {"mergeable": "MERGEABLE", "merge_state": "CLEAN", "checks": "SUCCESS", "review": None}},
                     "b": {"type": "pr", "repo": "o/r", "number": 2, "title": "ci: y", "url": "u2", "author": "bamr87", "bot": False,
                           "labels": [], "draft": False, "created_at": "2026-11-01T00:00:00Z", "updated_at": "2026-11-12T00:00:00Z",
                           "enrich": {"mergeable": "MERGEABLE", "merge_state": "CLEAN", "checks": "SUCCESS", "review": None}}}}
    MODEL = {"repos": [{"repo": "o/r", "prs": {}, "items": [{"repo": "o/r", "number": 9, "kind": "issue", "title": "old", "url": "u9", "labels": [],
                                                              "created_at": "2026-08-01T00:00:00Z", "updated_at": "2026-08-01T00:00:00Z"}]}],
             "board": {"items": []}}

    def setUp(self):
        super().setUp()
        (self.repo / "_data" / "fleet.yml").write_text(json.dumps({**FLEET, "jev": {"allowed_authors": ["bamr87"]},
                                                                   "ai_models": {"allowed": {"anthropic": ["claude-sonnet-5-5"]}}}))
        (self.repo / ".fleet" / "pm").mkdir(parents=True, exist_ok=True)
        (self.repo / ".fleet" / "pm" / "model.json").write_text(json.dumps(self.MODEL))
        (self.repo / ".fleet" / "pm" / "review.json").write_text("{}")

    def go(self, read_index=None, session=None, scheduled=False, agent=False):
        asked = []

        def gh(cmd, **kwargs):
            asked.append(list(cmd))
            if cmd[:3] == ["gh", "pr", "view"]:
                doc = dict(Confirm.LIVE)
                if cmd[3] == "2":
                    doc["files"] = [{"path": ".github/workflows/ci.yml", "changeType": "MODIFIED"}]
                return done(0, json.dumps(doc))
            if cmd[:2] == ["gh", "api"]:
                return done(0, json.dumps(Confirm.FACTS))
            return done(1, "", "unexpected")
        args = argparse.Namespace(scheduled=scheduled, apply=False, offline=False, no_plan=False, agent=agent)
        index = read_index or (lambda root, offline: (self.INDEX, lambda rec, cfg: ([], [], {}), None, "fresh, live"))
        with mock.patch.object(core, "refresh", return_value={"ok": True, "notes": []}), \
                mock.patch.object(core, "run_pm", return_value={"ok": True, "error": None}):
            code, out = self.quiet(core.cmd_run, args, self.repo, self.state, self.tmp / "archive", live=base.NOBODY,
                                   prs_for=lambda _: [], now=datetime.now(timezone.utc), read_index=index, session=session, runner=gh)
        return code, out, asked

    def local_state(self):
        """Branches, HEAD, worktrees and the remote's refs: what a run must not change. A fetch may
        update remote-tracking refs, and the run folder under .fleet/ is the run's own."""
        return (base.g(self.repo, "for-each-ref", "refs/heads"), base.g(self.repo, "rev-parse", "HEAD"),
                base.g(self.repo, "worktree", "list"), base.g(self.origin, "for-each-ref"),
                [l for l in base.g(self.repo, "status", "--porcelain").splitlines() if ".fleet" not in l])

    def test_it_dispositions_reads_the_gate_and_writes_nothing(self):
        before = self.local_state()
        code, out, asked = self.go()
        self.assertEqual(self.local_state(), before)
        self.assertEqual(only_reads(asked), [])
        folder, rec = self.run_of("close")
        self.assertEqual(rec["closeout"]["counts"]["merge"]["pr"], 1)            # #2 changes a workflow: held
        self.assertEqual(rec["closeout"]["counts"]["amr"]["pr"], 1)
        self.assertEqual(rec["closeout"]["counts"]["stale"]["issue"], 1)
        self.assertEqual(Path(rec["closeout"]["lists"]["merge"]).read_text(), "o/r 1\n")
        self.assertIn("read from live GitHub", out)
        self.assertIn("The decision index: fresh, live", out)
        self.assertIsNone(rec["agent"])                                          # a bare preview never runs the agent
        self.assertTrue(json.loads((folder / "closeout.json").read_text())["scanned"])

    def test_a_scheduled_run_asks_the_agent_and_still_writes_nothing(self):
        sessions = []

        def session(record, evidence, cfg, fleet, **kw):
            sessions.append(json.loads((evidence / "brief.json").read_text()))
            self.assertTrue(kw["scheduled"])                                # so the week's one session is remembered
            return {"status": "ok", "why": "", "cost_usd": 0.3, "final": "```json\n" + json.dumps(
                {"proposals": [{"key": "issue:o/r#9", "action": "close", "reason": "abandoned"}, {"key": ["issue:o/r#9"], "action": "close", "reason": "x"}]}) + "\n```"}
        code, out, asked = self.go(session=session, scheduled=True)
        self.assertEqual(only_reads(asked), [])
        _, rec = self.run_of("close")
        self.assertEqual(len(sessions), 1)
        self.assertEqual([p["key"] for p in rec["agent"]["accepted"]], ["issue:o/r#9"])
        self.assertEqual(len(rec["agent"]["dropped"]), 1)                        # the malformed one is dropped, not fatal
        self.assertEqual(rec["mode"], "report-only")
        self.assertIn("1 stale items, 1 of which the close-out agent proposes closing", out)
        self.assertIn("the routine never merges or closes", out)

    def test_a_close_out_that_fails_still_leaves_the_runs_record(self):
        def broken(root, offline):
            raise TypeError("unhashable type: 'list'")
        code, out, _ = self.go(read_index=broken)
        self.assertEqual(code, 1)
        _, rec = self.run_of("close")
        self.assertTrue(rec["finished"])
        self.assertIn("close-out: TypeError", " ".join(rec["errors"]))
        self.assertIn("The close-out failed", out)
        self.assertTrue(rec["posts"])                                            # the rest of the run went on


class Confirm(Hub):
    LIVE = {"state": "OPEN", "isDraft": False, "title": "fix: x", "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN", "labels": [],
            "files": [{"path": "src/a.py", "changeType": "MODIFIED"}], "author": {"login": "bamr87", "is_bot": False}, "headRefOid": "c" * 40,
            "headRefName": "fix/x", "baseRefName": "main", "updatedAt": "u",
            "statusCheckRollup": [{"name": "ci", "status": "COMPLETED", "conclusion": "SUCCESS"}]}
    FACTS = {"allow_merge_commit": True, "default_branch": "main", "private": False}
    COUNTS = {d: {"pr": 0, "issue": 0} for d in ("merge", "ratify", "amr", "resolve", "fix", "wait", "stale", "carry")}

    def close_run(self, closeout=None, agent=None):
        args = argparse.Namespace(scheduled=False, apply=False, offline=True, no_plan=True)
        with mock.patch.object(core, "refresh", return_value={"ok": True, "notes": []}):
            self.quiet(core.cmd_run, args, self.repo, self.state, self.tmp / "archive", live=base.NOBODY, prs_for=lambda _: [],
                       now=datetime.now(timezone.utc))
        folder, rec = self.run_of("close")
        if closeout is not None or agent is not None:
            rec["closeout"] = closeout or {"counts": self.COUNTS, "open": {"pr": 0, "issue": 0}, "lists": {}}
            rec["agent"] = {"accepted": agent or []}
            (folder / "run.json").write_text(json.dumps(rec, default=str))
        return folder

    def gh(self):
        calls = []

        def run(cmd, **kwargs):
            calls.append(list(cmd))
            if cmd[:3] == ["gh", "pr", "list"]:
                return done(0, "")                       # no weekly PR is open yet
            if cmd[:3] == ["gh", "pr", "view"]:
                return done(0, "OPEN\n")
            return done(0, "https://example.test/pr/1\n")
        run.calls = calls
        run.writes = lambda: [c for c in calls if c[2] not in ("view", "list")]
        return run

    def confirm(self, gh=None, **flags):
        """`confirm`, with git real and every `gh` call answered by the fake."""
        gh = gh or self.gh()
        real = core.run

        def run(cmd, **kwargs):
            return gh(cmd, **kwargs) if cmd[0] == "gh" else real(cmd, **kwargs)
        args = argparse.Namespace(**{"apply": False, "keep_drafts": False, "publish": [], "allow": [], **flags})
        err = io.StringIO()
        with mock.patch.object(core, "run", run), contextlib.redirect_stderr(err):
            code, out = self.quiet(core.cmd_confirm, args, self.repo, self.state)
        return code, out + err.getvalue(), gh

    def test_a_dry_run_writes_nothing_anywhere(self):
        folder = self.close_run()
        before = self.fingerprint()
        code, out, gh = self.confirm()
        self.assertEqual((code, gh.writes()), (0, []))
        self.assertEqual(self.fingerprint(), before)
        self.assertFalse((folder / "confirm.json").exists())
        self.assertIn("Dry run: nothing was pushed, applied or opened", out)

    def test_apply_opens_the_weekly_pr_and_never_merges_or_closes(self):
        counts = {**self.COUNTS, "merge": {"pr": 3, "issue": 0}, "stale": {"pr": 1, "issue": 4}}
        folder = self.close_run(closeout={"counts": counts, "open": {"pr": 9, "issue": 9}, "lists": {}},
                                agent=[{"key": "issue:o/r#2", "action": "close", "reason": "dup"}])
        code, out, gh = self.confirm(apply=True)
        self.assertEqual([c[:3] for c in gh.writes()], [["gh", "pr", "create"]])
        self.assertIn("Not done here: 3 pull requests are ready to merge and 5 items are stale", out)
        self.assertTrue((folder / "confirm.json").exists())

    def test_the_command_line_has_no_way_to_ask_for_a_merge_or_a_close(self):
        for flag in ("--merge", "--close-proposed", "--close"):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                cli.main(["--root", str(self.repo), "confirm", flag])
        source = Path(core.__file__).read_text() + Path(cli.__file__).read_text()
        for verb in ('"pr", "merge"', '"pr", "close"', '"issue", "close"', "--admin", "--squash"):
            self.assertNotIn(verb, source, verb)

    def test_every_write_happens_under_the_lock(self):
        self.close_run()
        seen = []
        real = core.open_weekly_pr

        def watched(*args, **kwargs):
            seen.append((self.state / ".lock").exists())
            return real(*args, **kwargs)
        with mock.patch.object(core, "open_weekly_pr", watched):
            self.confirm(apply=True)
        self.assertEqual(seen, [True])
        self.assertFalse((self.state / ".lock").exists())

    def test_what_was_done_is_on_record_even_if_a_later_part_fails(self):
        folder = self.close_run()
        with mock.patch.object(core, "open_weekly_pr", side_effect=RuntimeError("GitHub went away")):
            with self.assertRaises(RuntimeError):
                self.confirm(apply=True)
        record = json.loads((folder / "confirm.json").read_text())
        self.assertEqual((record["pr"], isinstance(record["wip"], dict)), (None, True))
        self.assertFalse(list(folder.glob("confirm.json.tmp")))

    def test_finished_board_batches_are_on_record_before_the_pr_is_tried(self):
        folder = self.close_run()
        with mock.patch.object(core, "next_batches", return_value=[0]), \
                mock.patch.object(core, "apply_board", return_value=[{"index": 0, "ok": True, "note": "batch 0 applied"}]), \
                mock.patch.object(core, "open_weekly_pr", side_effect=RuntimeError("GitHub went away")):
            with self.assertRaises(RuntimeError):
                self.confirm(apply=True)
        self.assertEqual(json.loads((folder / "confirm.json").read_text())["batches"], [0])

    def test_a_record_that_cannot_be_trusted_starts_again_and_says_so(self):
        folder = self.close_run()
        for text in ("", "{trunc", "[1, 2]", '"text"', '{"wip": null, "batches": "all", "pr": 7, "pr_files": [], "board_plan": {}}',
                     '{"batches": [true, 1]}'):
            (folder / "confirm.json").write_text(text)
            code, out, gh = self.confirm()
            self.assertEqual(code, 0, text)
            self.assertIn("Note: confirm.json", out, text)
        (folder / "confirm.json").write_text('{"wip": {"hub:x": "pushed"}, "batches": [0, 1], "pr": "https://x/pr/1", "extra": 1}')
        progress, note = core.load_progress(folder / "confirm.json")
        self.assertEqual((progress["batches"], progress["pr"], note, "extra" in progress), ([0, 1], "https://x/pr/1", None, False))

    def test_the_record_is_replaced_whole(self):
        folder = self.close_run()
        target = folder / "confirm.json"
        core.save_progress(target, {"batches": [1]})
        with mock.patch.object(core.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                core.save_progress(target, {"batches": [1, 2]})
        self.assertEqual(json.loads(target.read_text()), {"batches": [1]})

    def test_sundays_plan_replaces_fridays_in_the_weekly_pr(self):
        folder = self.close_run()
        friday = core.read_run(folder)
        plan = {"lanes": {**{lane: [] for lane in core.LANES}, "do": [{"key": "issue:o/r#5", "ref": "o/r#5", "title": "t", "url": "u", "priority": "P1", "reasons": ["handed off for this week"], "lane": "do", "score": 1}]},
                "ranked": 1, "held": 0, "by_lane": {lane: 0 for lane in core.LANES}}
        later = datetime.fromisoformat(friday["started"]) + timedelta(hours=40)
        sunday = self.state / f"{later.strftime('%Y%m%dT%H%M%SZ')}-{friday['week']}-plan"
        sunday.mkdir()
        (sunday / "run.json").write_text(json.dumps({"id": sunday.name, "stage": "plan", "week": friday["week"], "started": later.isoformat(),
                                                     "finished": later.isoformat(), "mode": "manual", "plan": plan, "pinned": [], "open_keys": ["issue:o/r#5"]}))
        code, out, _ = self.confirm()
        self.assertIn(f"with the plan from {sunday.name}", out)
        self.assertIn("_data/work_queue.yml", out)

    def test_a_plan_for_another_week_is_ignored(self):
        folder = self.close_run()
        friday = core.read_run(folder)
        later = datetime.fromisoformat(friday["started"]) + timedelta(hours=40)
        other = self.state / f"{later.strftime('%Y%m%dT%H%M%SZ')}-1999-W01-plan"
        other.mkdir()
        (other / "run.json").write_text(json.dumps({"id": other.name, "stage": "plan", "week": "1999-W01", "started": later.isoformat(),
                                                    "finished": later.isoformat(), "mode": "manual", "plan": {"lanes": {}}}))
        _, out, _ = self.confirm()
        self.assertNotIn("with the plan from", out)


class WeeklyBranch(Hub):
    """Sunday's plan added to the PR that Friday's confirm opened."""

    def setUp(self):
        super().setUp()
        self.branch = "chore/weekly-2026-w47-x"
        base.g(self.repo, "checkout", "-q", "-b", self.branch)
        base.commit(self.repo, "_data/weekly_plan.yml", "plan: friday\n", "chore(weekly): recap")
        (self.repo / "pages").mkdir()
        base.commit(self.repo, "pages/retro.md", "retro as drafted\n", "retro")
        base.g(self.repo, "push", "-q", "origin", self.branch)
        base.g(self.repo, "checkout", "-q", "main")
        self.pushed = {"_data/weekly_plan.yml": core.text_sha("plan: friday\n"), "pages/retro.md": core.text_sha("retro as drafted\n")}

    def update(self, files, state="OPEN"):
        real = core.run

        def run(cmd, **kwargs):
            return done(0, state + "\n") if cmd[:3] == ["gh", "pr", "view"] else real(cmd, **kwargs)
        with mock.patch.object(core, "run", run):
            return core.update_weekly_branch(self.repo, "https://x/pr/1", self.branch, files, self.pushed, core.load_config({}), WEEK)

    def on_branch(self, rel):
        return base.g(self.origin, "show", f"{self.branch}:{rel}")

    def test_an_untouched_plan_file_is_updated_on_top(self):
        before = base.g(self.origin, "rev-parse", self.branch)
        note = self.update({"_data/weekly_plan.yml": "plan: sunday\n"})
        self.assertIn("updated _data/weekly_plan.yml", note)
        self.assertEqual(self.on_branch("_data/weekly_plan.yml"), "plan: sunday")
        self.assertEqual(base.g(self.origin, "rev-parse", f"{self.branch}~1"), before)
        self.assertEqual(self.pushed["_data/weekly_plan.yml"], core.text_sha("plan: sunday\n"))

    def test_a_file_edited_on_the_branch_is_left_as_edited(self):
        other = self.tmp / "other"
        subprocess.run(["git", "clone", "-q", "-b", self.branch, str(self.origin), str(other)], check=True, env=base.ENV, capture_output=True)
        base.commit(other, "_data/weekly_plan.yml", "plan: the maintainer's\n", "my edit")
        base.g(other, "push", "-q", "origin", f"HEAD:{self.branch}")
        tip = base.g(self.origin, "rev-parse", self.branch)
        note = self.update({"_data/weekly_plan.yml": "plan: sunday\n"})
        self.assertIn("left _data/weekly_plan.yml as edited on the branch", note)
        self.assertEqual(base.g(self.origin, "rev-parse", self.branch), tip)
        self.assertEqual(self.on_branch("_data/weekly_plan.yml"), "plan: the maintainer's")

    def test_nothing_changed_pushes_nothing(self):
        tip = base.g(self.origin, "rev-parse", self.branch)
        self.assertEqual(self.update({"_data/weekly_plan.yml": "plan: friday\n"}), "unchanged")
        self.assertEqual(base.g(self.origin, "rev-parse", self.branch), tip)

    def test_a_file_added_on_the_branch_that_this_routine_did_not_push_is_not_touched(self):
        tip = base.g(self.origin, "rev-parse", self.branch)
        self.pushed.pop("pages/retro.md")
        note = self.update({"pages/retro.md": "retro rewritten\n"})
        self.assertIn("left pages/retro.md as edited on the branch", note)
        self.assertEqual(base.g(self.origin, "rev-parse", self.branch), tip)

    def test_a_file_main_has_and_the_branch_never_touched_takes_sundays_plan(self):
        """Friday had no plan, so the queue was not in its commit; it is on the branch only because main has it."""
        self.assertNotIn("_data/work_queue.yml", self.pushed)
        note = self.update({"_data/work_queue.yml": "schema: work-queue/v1\norder: [a]\n"})
        self.assertIn("updated _data/work_queue.yml", note)
        self.assertEqual(self.on_branch("_data/work_queue.yml"), "schema: work-queue/v1\norder: [a]")

    def test_a_file_main_has_that_was_edited_on_the_branch_is_left(self):
        other = self.tmp / "other"
        subprocess.run(["git", "clone", "-q", "-b", self.branch, str(self.origin), str(other)], check=True, env=base.ENV, capture_output=True)
        base.commit(other, "_data/work_queue.yml", "schema: work-queue/v1\norder: [mine]\n", "my pins")
        base.g(other, "push", "-q", "origin", f"HEAD:{self.branch}")
        tip = base.g(self.origin, "rev-parse", self.branch)
        note = self.update({"_data/work_queue.yml": "schema: work-queue/v1\norder: [a]\n"})
        self.assertIn("left _data/work_queue.yml as edited on the branch", note)
        self.assertEqual(base.g(self.origin, "rev-parse", self.branch), tip)

    def test_a_pull_request_that_is_no_longer_open_is_left_alone(self):
        tip = base.g(self.origin, "rev-parse", self.branch)
        for state in ("MERGED", "CLOSED", ""):
            self.assertIn("no longer open", self.update({"_data/weekly_plan.yml": "plan: sunday\n"}, state=state))
        self.assertEqual(base.g(self.origin, "rev-parse", self.branch), tip)

    def test_a_branch_that_is_gone_is_left_alone(self):
        base.g(self.repo, "push", "-q", "origin", "--delete", self.branch)
        self.assertIn("gone", self.update({"_data/weekly_plan.yml": "plan: sunday\n"}))

    def test_the_push_is_never_forced(self):
        pushes, real = [], core.git

        def spy(repo, *args, **kwargs):
            if args and args[0] == "push":
                pushes.append(args)
            return real(repo, *args, **kwargs)
        with mock.patch.object(core, "git", spy):
            self.update({"_data/weekly_plan.yml": "plan: sunday\n"})
        self.assertEqual(len(pushes), 1)
        self.assertFalse([a for a in pushes[0] if a.startswith("+") or a.startswith("--force") or a == "-f"])
        self.assertEqual(pushes[0][-1], f"HEAD:refs/heads/{self.branch}")

    def test_a_plan_file_the_branch_does_not_have_is_added(self):
        note = self.update({"_data/work_queue.yml.new": "order: [a]\n"})
        self.assertIn("updated _data/work_queue.yml.new", note)
        self.assertEqual(self.on_branch("_data/work_queue.yml.new"), "order: [a]")

    def test_what_was_pushed_is_read_from_the_branch(self):
        got = core.branch_shas(self.repo, self.branch, ["_data/weekly_plan.yml", "pages/retro.md", "nope.txt"])
        self.assertEqual(got, self.pushed)
        self.assertEqual(core.branch_shas(self.repo, "no/such-branch", ["a"]), {})
        self.assertEqual(base.g(self.repo, "for-each-ref", "refs/weekly"), "")

    def test_it_leaves_no_worktree_and_no_ref_behind(self):
        self.update({"_data/weekly_plan.yml": "plan: sunday\n"})
        self.assertEqual(base.g(self.repo, "worktree", "list").count("\n"), 0)
        self.assertEqual(base.g(self.repo, "for-each-ref", "refs/weekly"), "")
        self.assertEqual(base.g(self.repo, "status", "--porcelain"), "")


class Installer(unittest.TestCase):
    SCRIPT = HERE / "install-weekly.sh"

    def run_it(self, *args):
        r = subprocess.run(["bash", str(self.SCRIPT), *args], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_the_plist_has_one_slot_a_stage_from_the_schedule(self):
        doc = plistlib.loads(self.run_it("--print-plist").encode())
        self.assertEqual(doc["Label"], "com.bamr87.weekly")
        schedule = core.load_config(core.load_fleet(core.ROOT))["schedule"]
        want = [{"Weekday": schedule[s]["weekday"], "Hour": schedule[s]["hour"], "Minute": schedule[s]["minute"]} for s in core.STAGES]
        self.assertEqual(doc["StartCalendarInterval"], want)
        self.assertTrue(all(slot["Minute"] != 0 for slot in doc["StartCalendarInterval"]))
        self.assertNotIn("RunAtLoad", doc)
        self.assertIn("tools/dash weekly auto --scheduled", doc["ProgramArguments"][-1])

    def test_the_job_runs_one_command_through_the_front_door(self):
        job = self.run_it("--print-job")
        commands = [l.strip() for l in job.splitlines() if l.strip().startswith(("step tools/", "tools/"))]
        self.assertEqual(commands, ["step tools/dash weekly auto --scheduled"])
        self.assertIn("caffeinate -i", job)
        self.assertNotIn("--apply", job)

    def test_the_agent_inventory_reads_it(self):
        sys.path.insert(0, str(core.ROOT / ".github" / "scripts" / "dash-gen"))
        import agent_inventory
        facts = agent_inventory.parse_installer(self.SCRIPT)
        self.assertEqual((facts["name"], facts["runs"], facts["uninstall"]), ("weekly", ["tools/dash weekly auto --scheduled"], "tools/install-weekly.sh --uninstall"))
        self.assertEqual(facts["schedule"], "on a calendar")

    def test_an_unknown_option_is_refused(self):
        r = subprocess.run(["bash", str(self.SCRIPT), "--force"], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)


class Siblings(base.Repo):
    """The folders beside the hub (tmp/repo-*), and the tidy that removes only what is proven safe."""

    def setUp(self):
        super().setUp()
        self.archive = self.tmp / "repo-archive" / "weekly"
        (self.repo / "_data").mkdir()
        (self.repo / "_data" / "fleet.yml").write_text(json.dumps({"weekly": {"archive_dir": str(self.archive)}}))
        base.commit(self.repo, "_data/fleet.yml", (self.repo / "_data" / "fleet.yml").read_text(), "config")
        base.g(self.repo, "push", "-q", "origin", "main")
        base.g(self.repo, "worktree", "add", "-q", "-b", "dead-work", str(self.tmp / "repo-dead"))
        base.g(self.repo, "worktree", "add", "-q", "-b", "dirty-work", str(self.tmp / "repo-dirty"))
        (self.tmp / "repo-dirty" / "wip.txt").write_text("not committed\n")
        base.g(self.repo, "worktree", "add", "-q", "-b", "busy-work", str(self.tmp / "repo-busy"))
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.tmp / "repo-clone")], check=True, env=base.ENV, capture_output=True)
        base.commit(self.tmp / "repo-clone", "mine.txt", "unpushed\n", "work only here")
        (self.tmp / "repo-orphan").mkdir()
        (self.tmp / "repo-orphan" / ".git").write_text("gitdir: /nonexistent/worktrees/gone\n")
        (self.tmp / "repo-notes").mkdir()
        (self.tmp / "repo-notes" / "todo.md").write_text("x\n")
        self.archive.mkdir(parents=True)
        base.g(self.repo, "worktree", "add", "-q", "-b", "elsewhere-work", str(self.tmp / "other" / "wt"))
        self.busy = {**base.NOBODY, "paths": [base.weekly.real(self.tmp / "repo-busy")]}
        self.state = self.tmp / "state"

    def tidy(self, apply=False, path=(), branches=False):
        args = argparse.Namespace(apply=apply, path=list(path), branches=branches, offline=True)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = core.cmd_tidy(args, self.repo, self.state, self.archive, live=self.busy, prs_for=lambda _: [], now=base.LATER)
        return code, out.getvalue(), core.latest(self.state, "tidy")[1]

    def test_every_folder_is_accounted_for_and_the_archive_is_not_one_of_them(self):
        code, out, rec = self.tidy()
        got = {r["name"]: (r["kind"], r["state"], r["removable"]) for r in rec["siblings"]}
        self.assertEqual(got, {"repo-dead": ("worktree", "dead", True), "repo-dirty": ("worktree", "dirty", False),
                               "repo-busy": ("worktree", "live", False), "repo-clone": ("clone", "clone", False),
                               "repo-orphan": ("worktree", "orphan", False), "repo-notes": ("folder", "folder", False)})
        clone = next(r for r in rec["siblings"] if r["name"] == "repo-clone")
        self.assertIn("1 commit(s) on no remote", clone["why"])
        self.assertIn("## Folders beside the hub", out)
        self.assertEqual((code, rec["stage"], rec["mode"]), (0, "tidy", "preview"))

    def test_a_preview_removes_nothing(self):
        before = base.g(self.repo, "worktree", "list")
        self.tidy()
        self.assertEqual(base.g(self.repo, "worktree", "list"), before)
        self.assertTrue((self.tmp / "repo-dead").exists())
        self.assertEqual(list(self.archive.iterdir()), [])                     # and saves nothing

    def test_apply_removes_only_the_dead_worktree_in_scope_and_keeps_its_branch(self):
        code, out, rec = self.tidy(apply=True)
        self.assertEqual(code, 0, out)
        self.assertFalse((self.tmp / "repo-dead").exists())
        self.assertTrue(base.g(self.repo, "rev-parse", "--verify", "-q", "refs/heads/dead-work"))
        for kept in ("repo-dirty", "repo-busy", "repo-clone", "repo-orphan", "repo-notes", "repo-archive", "other/wt"):
            self.assertTrue((self.tmp / kept).exists(), kept)
        self.assertEqual((self.tmp / "repo-dirty" / "wip.txt").read_text(), "not committed\n")
        self.assertTrue(list(self.archive.rglob("*.bundle")) or list(self.archive.rglob("refs/*.txt")))
        self.assertEqual(rec["mode"], "applied")
        self.assertIn("| removed |", out)

    def test_another_scope_reaches_only_what_it_names(self):
        self.tidy(apply=True, path=[str(self.tmp / "other" / "*")])
        self.assertFalse((self.tmp / "other" / "wt").exists())
        self.assertTrue((self.tmp / "repo-dead").exists())

    def test_branches_go_only_when_asked_and_only_if_merged(self):
        base.g(self.repo, "branch", "merged-already")
        self.tidy(apply=True)
        self.assertEqual(base.g(self.repo, "branch", "--list", "merged-already"), "merged-already")
        self.tidy(apply=True, branches=True)
        self.assertEqual(base.g(self.repo, "branch", "--list", "merged-already"), "")
        self.assertTrue(base.g(self.repo, "rev-parse", "--verify", "-q", "refs/heads/dirty-work"))   # held by a surviving worktree

    def test_a_tidy_is_not_a_close_out(self):
        self.tidy(apply=True)
        self.assertIsNone(core.latest(self.state, "close"))
        self.assertEqual(core.scheduled_count(self.state), 0)

    def test_fridays_report_lists_the_folders_too(self):
        args = argparse.Namespace(scheduled=False, apply=False, offline=True, no_plan=True)
        with mock.patch.object(core, "notify"), contextlib.redirect_stdout(io.StringIO()) as out:
            core.cmd_run(args, self.repo, self.state, self.archive, live=self.busy, prs_for=lambda _: [], now=base.LATER)
        self.assertIn("## Folders beside the hub", out.getvalue())
        self.assertIn("6 folders", out.getvalue())
        self.assertEqual(len(core.latest(self.state, "close")[1]["siblings"]), 6)

    def test_scope_matching_sees_through_symlinked_parents(self):
        self.assertTrue(core.in_scope(str(self.tmp / "repo-dead"), [str(self.tmp / "repo-*")]))
        self.assertTrue(core.in_scope(base.weekly.real(self.tmp / "repo-dead"), [str(self.tmp / "repo-*")]))
        self.assertFalse(core.in_scope(str(self.tmp / "other" / "wt"), [str(self.tmp / "repo-*")]))


class Packaging(unittest.TestCase):
    def test_no_source_file_holds_an_invisible_separator(self):
        """A line or paragraph separator pasted into source splits a line for some tools and not others."""
        for path in [*(HERE / "weekly").rglob("*"), *HERE.glob("test_weekly*.py"), HERE / "install-weekly.sh"]:
            if path.is_file() and path.suffix in (".py", ".sh", ".md", ".txt"):
                text = path.read_text(encoding="utf-8")
                self.assertFalse([c for c in text if c in "\u2028\u2029\x0b\x0c\x85"], path.name)

    def test_every_module_confirm_needs_imports_from_the_hub_root(self):
        """As `python3 -m tools.weekly` runs it: the working directory is the hub, and nothing put
        tools/ on the path the way running a script inside it used to."""
        code = "from tools.weekly import core; import pm_review, work_queue, harness_registry; print(pm_review.__name__)"
        r = subprocess.run([sys.executable, "-c", code], cwd=core.ROOT, capture_output=True, text=True,
                           env={k: v for k, v in os.environ.items() if k != "PYTHONSAFEPATH"})
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "pm_review"), r.stderr[-400:])


class BadSchedule(unittest.TestCase):
    """A schedule the installer cannot use stops it before anything is written."""

    def root(self, schedule):
        tmp = Path(tempfile.mkdtemp(prefix="weekly-install-"))
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        (tmp / "tools").mkdir()
        (tmp / "_data").mkdir()
        for name in ("dash", "weekly", "jev"):
            (tmp / "tools" / name).symlink_to(HERE / name)
        (tmp / "_data" / "fleet.yml").write_text(json.dumps({"weekly": {"schedule": schedule}}))
        return tmp

    def run_it(self, schedule, mode):
        return subprocess.run(["bash", str(HERE / "install-weekly.sh"), "--root", str(self.root(schedule)), mode], capture_output=True, text=True)

    def test_a_slot_on_the_hour_is_refused(self):
        r = self.run_it({"close": {"weekday": 5, "hour": 22, "minute": 0}}, "--print-plist")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("never on the hour", r.stderr)
        self.assertIn("nothing was changed", r.stderr)
        self.assertNotIn("<plist", r.stdout)

    def test_a_good_schedule_from_another_root_renders(self):
        r = self.run_it({"plan": {"weekday": 7, "hour": 9, "minute": 15}}, "--print-plist")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(plistlib.loads(r.stdout.encode())["StartCalendarInterval"][2], {"Weekday": 7, "Hour": 9, "Minute": 15})


class CommandLine(unittest.TestCase):
    def test_every_stage_and_confirm_option_parses(self):
        for argv in (["close", "--scheduled"], ["close", "--apply", "--agent"], ["prepare", "--offline"], ["plan", "--scheduled"],
                     ["confirm", "--apply", "--keep-drafts", "--allow", "hub:x"], ["brief", "plan", "--week", "2026-W47"]):
            with mock.patch.object(cli.core, "cmd_run", return_value=0), mock.patch.object(cli.core, "cmd_confirm", return_value=0), \
                    mock.patch.object(cli, "cmd_prepare", return_value=0), mock.patch.object(cli, "cmd_plan", return_value=0), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(argv), 0, argv)

    def test_scheduled_and_apply_cannot_be_combined(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["close", "--scheduled", "--apply"])

    def test_auto_only_runs_scheduled(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["auto"])

    def test_brief_prints_the_grok_half(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["brief", "close", "--week", "2026-W47"])
        self.assertIn("# Friday: the direction close-out", out.getvalue())


if __name__ == "__main__":
    unittest.main()
