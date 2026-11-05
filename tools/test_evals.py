#!/usr/bin/env python3
"""
Tests for tools/evals.py — the eval runner (constitution § 13.1–13.2).

The key test is `test_wrong_expectation_fails_the_run`: it copies the real
jev-classify set, flips one expected tier, and asserts the runner exits
non-zero. That is the proof that an eval regression fails the CI check in
.github/workflows/evals.yml. Everything runs offline: no network, no model.

Run: python3 tools/test_evals.py
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import evals  # noqa: E402

JEV_SET = evals.EVALS_DIR / "jev-classify" / "cases.yml"
T1_SET = evals.EVALS_DIR / "t1-intake" / "cases.yml"


def run_cli(*argv: str) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = evals.main(list(argv))
    return code, out.getvalue()


def write_set(data: dict) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="evals-test-")) / "cases.yml"
    tmp.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return tmp


class CommittedSets(unittest.TestCase):
    def test_roles_are_discovered(self):
        self.assertEqual(evals.roles(), ["jev-classify", "t1-intake"])

    def test_jev_classify_has_20_cases_and_passes_offline(self):
        data = evals.load_set(JEV_SET)
        self.assertGreaterEqual(len(data["cases"]), 20)
        code, out = run_cli("run", "jev-classify")
        self.assertEqual(code, 0, out)
        self.assertIn("0 failed", out)

    def test_t1_intake_has_10_seeds_and_validates_without_a_model(self):
        data = evals.load_set(T1_SET)
        self.assertGreaterEqual(len(data["cases"]), 10)
        exits = {c["expected"]["exit"] for c in data["cases"]}
        self.assertEqual(exits, {"ready", "blocked"}, "a seed set needs both exits")
        with mock.patch.object(evals.subprocess, "run", side_effect=AssertionError("no model in --dry-run")):
            code, out = run_cli("run", "t1-intake", "--dry-run")
        self.assertEqual(code, 0, out)

    def test_json_shape(self):
        code, out = run_cli("run", "jev-classify", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertIsInstance(payload, dict)
        for key in ("role", "passed", "failed", "cases"):
            self.assertIn(key, payload)
        self.assertEqual(payload["role"], "jev-classify")
        self.assertEqual(payload["failed"], 0)
        self.assertEqual(payload["passed"], len(payload["cases"]))

    def test_all_runs_every_role(self):
        code, out = run_cli("run", "--all", "--dry-run", "--json")
        self.assertEqual(code, 0, out)
        self.assertEqual([r["role"] for r in json.loads(out)], evals.roles())

    def test_t1_model_is_pinned(self):
        cfg = evals.fleet_config()
        self.assertIn(evals.load_set(T1_SET)["model"], evals.allowed_models(cfg))


class TheGateFails(unittest.TestCase):
    def test_wrong_expectation_fails_the_run(self):
        data = evals.load_set(JEV_SET)
        case = next(c for c in data["cases"] if c["id"] == "console-lockfile")
        case["expected"]["tier"] = "tier0"   # deliberately wrong: lockfiles are tier3
        code, out = run_cli("run", "jev-classify", "--cases", str(write_set(data)), "--json")
        self.assertNotEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["failed"], 1)
        failed = [c for c in payload["cases"] if not c["passed"]]
        self.assertEqual(failed[0]["id"], "console-lockfile")
        self.assertIn("tier3 != expected tier0", failed[0]["detail"])

    def test_wrong_kind_fails(self):
        data = evals.load_set(JEV_SET)
        case = next(c for c in data["cases"] if c["id"] == "token-rotation-is-secret")
        case["expected"]["kinds"] = {".github/workflows/token-rotation.yml": "workflow"}
        code, _ = run_cli("run", "jev-classify", "--cases", str(write_set(data)))
        self.assertEqual(code, 1)

    def test_too_few_cases_fails(self):
        data = evals.load_set(JEV_SET)
        data["cases"] = data["cases"][:5]
        code, out = run_cli("run", "jev-classify", "--cases", str(write_set(data)))
        self.assertEqual(code, 1)
        self.assertIn("min_cases", out)

    def test_malformed_case_fails(self):
        data = evals.load_set(JEV_SET)
        del data["cases"][0]["expected"]
        code, out = run_cli("run", "jev-classify", "--cases", str(write_set(data)))
        self.assertEqual(code, 1)
        self.assertIn("missing 'expected'", out)

    def test_duplicate_id_fails(self):
        data = evals.load_set(JEV_SET)
        data["cases"][1]["id"] = data["cases"][0]["id"]
        code, _ = run_cli("run", "jev-classify", "--cases", str(write_set(data)))
        self.assertEqual(code, 1)

    def test_bad_t1_exit_fails_dry_run(self):
        data = evals.load_set(T1_SET)
        data["cases"][0]["expected"]["exit"] = "maybe"
        code, out = run_cli("run", "t1-intake", "--dry-run", "--cases", str(write_set(data)))
        self.assertEqual(code, 1)
        self.assertIn("expected.exit", out)

    def test_unknown_role_fails(self):
        code, _ = run_cli("run", "no-such-role")
        self.assertEqual(code, 1)


class ModelRuns(unittest.TestCase):
    """The model path, with the `claude` CLI stubbed: pinned ids and the cap."""

    def test_unpinned_model_is_refused_before_any_call(self):
        with mock.patch.object(evals.subprocess, "run", side_effect=AssertionError("must not call")):
            code, out = run_cli("run", "t1-intake", "--model", "claude-opus-latest")
        self.assertEqual(code, 1)
        self.assertIn("ai_models.allowed", out)

    def _fake_claude(self, calls):
        def fake(cmd, **_):
            calls.append(cmd)
            prompt = cmd[cmd.index("-p") + 1]
            exit_ = "blocked" if "[human]" in prompt else "ready"
            data = evals.load_set(T1_SET)
            typ = next(c["expected"]["type"] for c in data["cases"] if c["input"]["title"] in prompt)
            reply = json.dumps({"exit": exit_, "type": typ})
            return mock.Mock(returncode=0, stderr="",
                             stdout=json.dumps({"result": reply, "total_cost_usd": 0.01}))
        return fake

    def test_model_run_passes_pinned_model_and_budget_cap(self):
        calls: list = []
        with mock.patch.object(evals.shutil, "which", return_value="/usr/bin/claude"), \
                mock.patch.object(evals.subprocess, "run", side_effect=self._fake_claude(calls)):
            code, out = run_cli("run", "t1-intake", "--json")
        self.assertEqual(code, 0, out)
        cfg = evals.fleet_config()
        first = calls[0]
        self.assertIn(first[first.index("--model") + 1], evals.allowed_models(cfg))
        self.assertLessEqual(float(first[first.index("--max-budget-usd") + 1]), evals.budget_cap(cfg))
        self.assertGreater(json.loads(out)["cost_usd"], 0)


if __name__ == "__main__":
    unittest.main()
