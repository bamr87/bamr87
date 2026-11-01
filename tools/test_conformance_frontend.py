#!/usr/bin/env python3
"""Fixture tests for the § 18 frontend-platform rows in tools/conformance.py
(UPS-FE-70..73): N/A for tier none, tokens/shell per tier, warn-only until
`frontend.enforce: true`, fork detection. Offline, no pytest:

    python3 tools/test_conformance_frontend.py
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import conformance as c  # noqa: E402

HUB = Path(__file__).resolve().parent.parent


def repo(files: dict[str, str], fe: dict | None, tmp: Path) -> c.Repo:
    for rel, body in files.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    r = c.Repo(tmp, HUB)
    r.registry_entry = {"name": "x", **({"frontend": fe} if fe is not None else {})}
    return r


def fe(**kw):
    base = {"type": "app", "tier": "shell", "framework": "react", "surfaces": ["browser"],
            "token_version": "none", "entry_url": None, "shell": "own"}
    base.update(kw)
    return base


class FrontendConformance(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def run_id(self, rid, r):
        return c.CHECKS[rid](r, ["app"])

    def test_tier_none_is_na_everywhere(self):
        r = repo({}, fe(type="none", tier="none", shell="none"), self.tmp)
        for rid in ("UPS-FE-70", "UPS-FE-71", "UPS-FE-72", "UPS-FE-73"):
            ok, detail = self.run_id(rid, r)
            self.assertIs(ok, True, rid)
            self.assertIn("n/a", detail, rid)

    def test_missing_block_warns(self):
        ok, _ = self.run_id("UPS-FE-70", repo({}, None, self.tmp))
        self.assertEqual(ok, c.WARN)

    def test_tokens_missing_warns_then_fails(self):
        self.assertEqual(self.run_id("UPS-FE-71", repo({}, fe(), self.tmp))[0], c.WARN)
        self.assertIs(self.run_id("UPS-FE-71", repo({}, fe(enforce=True), self.tmp))[0], False)

    def test_tokens_present(self):
        r = repo({"src/app.css": ":root{--fleet-color-primary:#000}"}, fe(), self.tmp)
        self.assertIs(self.run_id("UPS-FE-71", r)[0], True)

    def test_feedback_widget_is_not_adoption(self):
        r = repo({"public/fleet-feedback.js": "x='--fleet-color-bg'"}, fe(), self.tmp)
        self.assertEqual(self.run_id("UPS-FE-71", r)[0], c.WARN)

    def test_zer0_site_tokens_theme_provided(self):
        r = repo({"_config.yml": "remote_theme: bamr87/zer0-mistakes\n"}, fe(type="site", tier="tokens", shell="zer0"), self.tmp)
        self.assertIs(self.run_id("UPS-FE-71", r)[0], True)

    def test_shell_only_for_shell_tier(self):
        game = repo({}, fe(type="game", tier="tokens", shell="none"), self.tmp)
        self.assertIs(self.run_id("UPS-FE-72", game)[0], True)
        app = repo({}, fe(), self.tmp)
        self.assertEqual(self.run_id("UPS-FE-72", app)[0], c.WARN)
        mounted = repo({"package.json": '{"dependencies":{"@bamr87/fleet-shell":"*"}}'}, fe(enforce=True), self.tmp)
        self.assertIs(self.run_id("UPS-FE-72", mounted)[0], True)

    def test_fork_detection(self):
        r = repo({"src/fleet-tokens.css": "/* fleet-tokens v1.0.0 */"}, fe(token_version="v1.0.0", enforce=True), self.tmp)
        self.assertIs(self.run_id("UPS-FE-73", r)[0], True)
        r2 = repo({"src/fleet-tokens.css": "/* fleet-tokens v0.9.0 */"}, fe(token_version="v1.0.0", enforce=True), self.tmp)
        self.assertIs(self.run_id("UPS-FE-73", r2)[0], False)

    def test_rows_exist_in_specs(self):
        import yaml
        ids = {q["id"] for q in yaml.safe_load((HUB / "_data" / "specs.yml").read_text())["requirements"]}
        self.assertTrue({"UPS-FE-70", "UPS-FE-71", "UPS-FE-72", "UPS-FE-73"} <= ids)


if __name__ == "__main__":
    unittest.main()
