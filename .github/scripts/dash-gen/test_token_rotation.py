#!/usr/bin/env python3
"""
Contract tests for token-rotation.yml's `report` job: the ONE tracking issue's
whole lifecycle, opened while a human is needed and closed once nothing is
(issue #148).

The job used to run only when `attention` was true or the secret probe failed,
so it could open and update "🔑 Fleet credential rotation needs attention" but
never close it: every other upsert-issue loop (api-keys, reconcile-registry,
schema-vendor) closes its issue on a clean run, and this one stayed open for
weeks after the ledger showed `attention: []` for every token. These tests
hold the fixed shape:

  * the report job runs whatever `attention` says, so a clean run reaches it;
  * the verdict step, executed for real with bash, says `open` while a human is
    needed (attention, a credential without secrets:write, or a probe that
    never ran), `close` only on an explicit `attention=false` from a full apply
    run, and `none` for anything else — a rotate step that crashed before
    judging (no `attention` output) or a dry-run / one-repo / one-token
    dispatch must not post a false all-clear;
  * the issue step passes that verdict as upsert-issue's `state`, with a close
    comment, and the report body is composed only when the issue opens;
  * "full apply run" is the same scope that publishes the ledger.

Needs PyYAML and bash; runs offline:

    python3 .github/scripts/dash-gen/test_token_rotation.py
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "token-rotation.yml"
UPSERT = "./.github/actions/utilities/upsert-issue"
NEEDS_OUTPUT = re.compile(r"^\$\{\{\s*needs\.rotate\.outputs\.(\w+)\s*\}\}$")


def load_jobs() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]


def report_steps() -> list[dict]:
    return load_jobs()["report"]["steps"]


def step_by_id(step_id: str) -> dict:
    for step in report_steps():
        if step.get("id") == step_id:
            return step
    raise AssertionError(f"report job has no step with id {step_id!r}")


def upsert_step() -> dict:
    steps = [s for s in report_steps() if s.get("uses") == UPSERT]
    if len(steps) != 1:
        raise AssertionError(f"expected one upsert-issue step in report, found {len(steps)}")
    return steps[0]


def run_verdict(outputs: dict[str, str]) -> str:
    """Execute the verdict step's script the way the runner would, with each
    `${{ needs.rotate.outputs.X }}` env value replaced by the fixture's X (an
    absent output is the empty string, as on GitHub), and return `state`."""
    step = step_by_id("verdict")
    env = {"PATH": os.environ["PATH"]}
    for key, expr in (step.get("env") or {}).items():
        m = NEEDS_OUTPUT.match(str(expr).strip())
        if not m:
            raise AssertionError(f"verdict env {key} is not a rotate output: {expr!r}")
        env[key] = outputs.get(m.group(1), "")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "github_output"
        out.touch()
        env["GITHUB_OUTPUT"] = str(out)
        result = subprocess.run(
            ["bash", "-e", "-c", step["run"]],
            env=env, capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise AssertionError(f"verdict step failed: {result.stderr}")
        states = [line.split("=", 1)[1] for line in out.read_text().splitlines()
                  if line.startswith("state=")]
    if len(states) != 1:
        raise AssertionError(f"verdict wrote {len(states)} state= lines")
    return states[0]


class ReportJobTests(unittest.TestCase):
    def test_report_job_runs_without_attention(self):
        cond = str(load_jobs()["report"].get("if", ""))
        self.assertIn("always()", cond)
        self.assertNotIn("attention", cond,
                         "a job gated on attention can never reach the close path")

    def test_verdict_closes_after_a_clean_full_run(self):
        self.assertEqual(
            run_verdict({"attention": "false", "can_write": "true", "full_run": "true"}),
            "close")

    def test_verdict_opens_while_a_human_is_needed(self):
        for outputs in (
            {"attention": "true", "can_write": "true", "full_run": "true"},
            {"attention": "true", "can_write": "true", "full_run": "false"},
            {"can_write": "false", "full_run": "true"},
            {"can_write": "", "full_run": "true"},
            {},
        ):
            with self.subTest(outputs=outputs):
                self.assertEqual(run_verdict(outputs), "open")

    def test_verdict_leaves_the_issue_without_proof_of_a_clean_fleet(self):
        for outputs in (
            # the rotate step crashed (or rotation is switched off) after the
            # probe passed: no verdict on the credentials at all
            {"can_write": "true", "full_run": "true"},
            # a dry-run, one-repo or one-token dispatch saw only part of it
            {"attention": "false", "can_write": "true", "full_run": "false"},
            {"attention": "false", "can_write": "true"},
        ):
            with self.subTest(outputs=outputs):
                self.assertEqual(run_verdict(outputs), "none")

    def test_verdict_reads_outputs_through_env_only(self):
        self.assertNotIn("${{", step_by_id("verdict")["run"])

    def test_upsert_state_is_the_verdict(self):
        step = upsert_step()
        self.assertEqual(step["with"]["state"].replace(" ", ""),
                         "${{steps.verdict.outputs.state}}")
        self.assertTrue(step["with"].get("close-comment"), "a close needs its comment")
        self.assertIn("steps.verdict.outputs.state != 'none'", step.get("if", ""))
        self.assertIn("steps.cfg.outputs.enabled == 'true'", step.get("if", ""))

    def test_report_body_is_composed_only_to_open(self):
        for step in report_steps():
            if step.get("name") == "Compose the report" or step.get("uses", "").startswith(
                    "actions/download-artifact"):
                with self.subTest(step=step.get("name") or step.get("uses")):
                    self.assertIn("steps.verdict.outputs.state == 'open'", step.get("if", ""))

    def test_full_run_is_the_ledger_scope(self):
        rotate = load_jobs()["rotate"]
        full = rotate["outputs"]["full_run"].replace(" ", "")
        publish = next(s for s in rotate["steps"] if s.get("name") == "Publish rotation ledger")
        for clause in ("steps.mode.outputs.apply!=''", "inputs.repo==''", "inputs.only==''"):
            with self.subTest(clause=clause):
                self.assertIn(clause, full)
                self.assertIn(clause, publish["if"].replace(" ", ""))


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
