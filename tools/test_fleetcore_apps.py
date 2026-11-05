#!/usr/bin/env python3
"""Tests for tools/fleetcore/apps.py — the app portal's launcher: every registry
frontend joined to its live address and its local dev stack's (ADR 0005).
Offline, no pytest:  python3 tools/test_fleetcore_apps.py"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fleetcore import apps  # noqa: E402

HUB = Path(__file__).resolve().parent.parent

PORTS = {"projects": {
    "bamr87": {"host": "hub", "services": {"console": {"port": 4001, "band": "hub"}}},
    "shop": {"host": "compose", "services": {
        "db": {"port": 5440, "band": "database"},
        "api": {"port": 8120, "band": "api"},
        "web": {"port": 5120, "band": "frontend"},
        "docs": {"port": 8005, "band": "docs"},
    }, "debug": {"api": {"port": 5720, "band": "debug"}}},
    "zer0-cms": {"host": "compose", "services": {"content": {"port": 8117, "band": "api"}}},
    "notes": {"host": "devenv", "services": {"jekyll": {"port": 4012, "band": "jekyll"}}},
}}


def entry(name="shop", **fe):
    base = {"type": "app", "tier": "shell", "framework": "react", "surfaces": ["browser"],
            "token_version": "none", "entry_url": "https://shop.test/", "shell": "own"}
    base.update(fe)
    return {"name": name, "slug": name, "submodule_path": f"projects/{name}", "status": "active",
            "description": "d", "repo_url": f"https://github.com/x/{name}", "frontend": base}


class TargetTests(unittest.TestCase):
    def test_live_comes_from_entry_url_then_live_url(self):
        self.assertEqual(apps.targets(entry(), None)[0], {"id": "live", "kind": "live", "label": "Live", "url": "https://shop.test/"})
        e = {**entry(entry_url=None), "live_url": "https://fallback.test"}
        self.assertEqual(apps.targets(e, None)[0]["url"], "https://fallback.test")
        self.assertEqual(apps.targets(entry(entry_url=None), None), [])

    def test_local_targets_are_the_web_bands_most_page_like_first(self):
        t = apps.local_targets(PORTS, entry())
        self.assertEqual([x["id"] for x in t], ["local", "local-docs", "local-api"])
        self.assertEqual([x["port"] for x in t], [5120, 8005, 8120])
        self.assertEqual(t[0]["url"], "http://127.0.0.1:5120/")
        self.assertEqual(t[0]["start"], "tools/dash dev up shop")
        self.assertNotIn(5440, [x["port"] for x in t], "a database is not something a browser opens")
        self.assertNotIn(5720, [x["port"] for x in t], "a debug attach point is not a page")

    def test_the_ports_join_ignores_case(self):
        e = {**entry("zer0-CMS"), "slug": "zer0-cms"}
        self.assertEqual(apps.local_targets(PORTS, e)[0]["port"], 8117)
        e = {"name": "Zer0-CMS", "submodule_path": "projects/zer0-cms", "frontend": entry()["frontend"]}
        self.assertEqual(apps.local_targets(PORTS, e)[0]["start"], "tools/dash dev up zer0-cms")

    def test_a_devenv_hosted_project_has_no_fixed_local_address(self):
        """Its port is picked at launch (.vscode/launch.json), so offering the
        ports.yml number would frame a port nothing publishes."""
        e = entry("notes", type="site", tier="tokens")
        self.assertEqual(apps.local_targets(PORTS, e), [])
        app = apps.launcher([e], PORTS)["apps"][0]
        self.assertEqual(app["local_host"], "devenv")
        self.assertEqual([t["id"] for t in app["targets"]], ["live"])

    def test_malformed_allocations_are_skipped_not_fatal(self):
        ports = {"projects": {"shop": {"host": "compose", "services": {
            "web": {"port": "5120", "band": "frontend"}, "bad": "x", "ok": {"port": 5121, "band": "frontend"}}}}}
        self.assertEqual([t["port"] for t in apps.local_targets(ports, entry())], [5121])
        self.assertEqual(apps.local_targets({"projects": None}, entry()), [])
        self.assertEqual(apps.local_targets(None, entry()), [])


class LauncherTests(unittest.TestCase):
    def test_skips_tier_none_and_archived_and_keeps_the_v1_keys(self):
        reg = [entry(), {**entry("n", type="none", tier="none")}, {**entry("a"), "status": "archived"}, "junk", {"slug": "nameless"}]
        doc = apps.launcher(reg, PORTS)
        self.assertEqual(doc["schema"], "fleet-launcher/v1")
        self.assertEqual([a["id"] for a in doc["apps"]], ["shop"])
        a = doc["apps"][0]
        for key in ("id", "name", "type", "tier", "surfaces", "url", "deep_link", "description"):
            self.assertIn(key, a)
        self.assertEqual(a["deep_link"], "fleet://shop/")
        self.assertEqual(a["url"], "https://shop.test/")

    def test_embed_is_a_browser_surface_with_an_address(self):
        frame = apps.launcher([entry()], PORTS)["apps"][0]
        ext = apps.launcher([entry("x", type="ext", tier="tokens", surfaces=["vscode"], entry_url=None)], PORTS)["apps"][0]
        mobile = apps.launcher([entry("m", surfaces=["mobile"], entry_url=None)], PORTS)["apps"][0]
        nowhere = apps.launcher([entry("w", entry_url=None)], PORTS)["apps"][0]
        self.assertEqual([frame["embed"], ext["embed"], mobile["embed"], nowhere["embed"]], ["frame", "none", "none", "none"])

    def test_summary_counts(self):
        reg = [entry(), entry("notes", type="site", tier="tokens"), entry("x", type="ext", tier="tokens", surfaces=["vscode"], entry_url=None)]
        s = apps.summary(apps.launcher(reg, PORTS)["apps"])
        self.assertEqual((s["apps"], s["embeddable"], s["live"], s["local"]), (3, 2, 2, 1))
        self.assertEqual(s["by_type"], {"app": 1, "site": 1, "ext": 1})


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.apps = apps.launcher([entry(), entry("w", entry_url=None)], PORTS)["apps"]

    def test_default_named_target_and_path(self):
        self.assertEqual(apps.resolve(self.apps, "shop"), "https://shop.test/")
        self.assertEqual(apps.resolve(self.apps, "SHOP", "local"), "http://127.0.0.1:5120/")
        self.assertEqual(apps.resolve(self.apps, "shop", "local-api", "/v1/health"), "http://127.0.0.1:8120/v1/health")

    def test_unknown_app_or_target_says_what_exists(self):
        with self.assertRaisesRegex(ValueError, "known: shop, w"):
            apps.resolve(self.apps, "nope")
        with self.assertRaisesRegex(ValueError, "has: live, local, local-docs, local-api"):
            apps.resolve(self.apps, "shop", "staging")
        with self.assertRaisesRegex(ValueError, "no live or local address"):
            apps.resolve(self.apps, "w")


class ViewTests(unittest.TestCase):
    def test_viewports_come_from_the_verify_kit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual([v["id"] for v in apps.viewports(root)], ["desktop", "tablet", "mobile"])
            (root / "verify").mkdir()
            (root / "verify" / "verify.yml").write_text("viewports:\n  wide: {width: 1920, height: 1080}\n  bad: {width: x}\n", encoding="utf-8")
            self.assertEqual(apps.viewports(root), [{"id": "wide", "width": 1920, "height": 1080}])

    def test_a_tree_without_registries_is_an_empty_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = apps.apps_view(Path(tmp))
            self.assertEqual((doc["apps"], doc["summary"]["apps"]), ([], 0))

    def test_the_hub_launcher_is_coherent(self):
        doc = apps.apps_view(HUB)
        json.dumps(doc)  # what /api/apps and the snapshot serve
        self.assertGreater(doc["summary"]["embeddable"], 0)
        ids = [a["id"] for a in doc["apps"]]
        self.assertEqual(len(ids), len(set(ids)), "app ids are the deep-link keys: unique")
        ports = apps._load(HUB / "_data" / "ports.yml") or {}
        bands = ports.get("bands") or {}
        seen: dict[str, str] = {}
        for a in doc["apps"]:
            if a["embed"] == "frame":
                self.assertTrue(a["targets"], f"{a['id']} frames nothing")
            self.assertEqual(len({t["id"] for t in a["targets"]}), len(a["targets"]), a["id"])
            for t in a["targets"]:
                self.assertRegex(t["url"], r"^https?://", f"{a['id']}:{t['id']}")
                if t["kind"] != "local":
                    continue
                lo, hi = bands[t["band"]]["range"]
                self.assertTrue(lo <= t["port"] <= hi, f"{a['id']}:{t['id']} port {t['port']} outside its band")
                self.assertTrue(t["url"].startswith("http://127.0.0.1:"), "a local target is loopback only")
                self.assertNotIn(t["url"], seen, f"{a['id']} and {seen.get(t['url'])} claim {t['url']}")
                seen[t["url"]] = a["id"]


class CliTests(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = apps.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_list_url_and_json(self):
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("frontends", out.splitlines()[-1])
        code, out, _ = self.run_cli("json")
        self.assertEqual((code, json.loads(out)["schema"]), (0, "fleet-launcher/v1"))
        first = next(a for a in json.loads(out)["apps"] if a["targets"])
        code, out, _ = self.run_cli("url", first["id"])
        self.assertEqual((code, out.strip()), (0, first["targets"][0]["url"]))

    def test_an_unknown_app_exits_2_on_stderr(self):
        code, out, err = self.run_cli("url", "no-such-app")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("no frontend named", err)


if __name__ == "__main__":
    unittest.main()
