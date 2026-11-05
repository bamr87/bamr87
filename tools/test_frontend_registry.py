#!/usr/bin/env python3
"""Tests for tools/frontend_registry.py — the § 18 frontend: block lint and the
launcher projection. Offline, no pytest:  python3 tools/test_frontend_registry.py"""
from __future__ import annotations

import http.server
import socket
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import frontend_registry as fr  # noqa: E402


def entry(**fe):
    base = {"type": "app", "tier": "shell", "framework": "react", "surfaces": ["browser"],
            "token_version": "none", "entry_url": "https://x.test/", "shell": "own"}
    base.update(fe)
    return {"name": "x", "slug": "x", "submodule_path": "projects/x", "status": "active", "frontend": base}


class FrontendRegistryTests(unittest.TestCase):
    def test_hub_registry_is_clean(self):
        reg = fr.load(fr.HUB / "_data" / "projects.yml")
        self.assertEqual(fr.lint(reg), [])
        subs = [e for e in reg if e.get("submodule_path")]
        self.assertTrue(all("frontend" in e for e in subs))

    def test_valid_entry(self):
        self.assertEqual(fr.lint_entry(entry()), [])

    def test_missing_block_on_submodule(self):
        self.assertTrue(fr.lint_entry({"name": "y", "submodule_path": "projects/y"}))
        self.assertEqual(fr.lint_entry({"name": "ext"}), [])

    def test_bad_enums(self):
        self.assertTrue(fr.lint_entry(entry(tier="full")))
        self.assertTrue(fr.lint_entry(entry(surfaces=["watch"])))
        self.assertTrue(fr.lint_entry(entry(shell="mine")))
        self.assertTrue(fr.lint_entry(entry(token_version="latest")))
        self.assertEqual(fr.lint_entry(entry(token_version="v1.2.0")), [])

    def test_tier_coherence(self):
        self.assertTrue(fr.lint_entry(entry(type="game", tier="shell")))
        self.assertEqual(fr.lint_entry(entry(type="game", tier="tokens", shell="none")), [])
        self.assertTrue(fr.lint_entry(entry(type="site", tier="none")))
        self.assertTrue(fr.lint_entry(entry(type="none", tier="none", enforce=True)))

    def test_launcher_skips_none_and_archived(self):
        reg = [entry(), {**entry(type="none", tier="none"), "name": "n", "slug": "n"},
               {**entry(), "name": "a", "slug": "a", "status": "archived"}]
        apps = fr.launcher(reg)["apps"]
        self.assertEqual([a["id"] for a in apps], ["x"])
        self.assertEqual(apps[0]["deep_link"], "fleet://x/")

    def test_launcher_carries_targets_from_the_port_registry(self):
        ports = {"projects": {"x": {"host": "compose", "services": {"web": {"port": 5120, "band": "frontend"}}}}}
        app = fr.launcher([entry()], ports)["apps"][0]
        self.assertEqual([(t["id"], t["url"]) for t in app["targets"]],
                         [("live", "https://x.test/"), ("local", "http://127.0.0.1:5120/")])
        self.assertEqual(fr.launcher([entry()])["apps"][0]["url"], "https://x.test/")  # v1 call shape still works


class FramePolicyTests(unittest.TestCase):
    def test_no_header_is_open(self):
        self.assertEqual(fr.frame_policy({"Content-Type": "text/html"}), ("open", True))

    def test_x_frame_options_refuses_a_cross_origin_shell(self):
        self.assertEqual(fr.frame_policy({"X-Frame-Options": "DENY"}), ("x-frame-options deny", False))
        self.assertEqual(fr.frame_policy({"x-frame-options": "SAMEORIGIN"}), ("x-frame-options sameorigin", False))

    def test_frame_ancestors_admits_only_a_listed_shell(self):
        csp = "default-src 'self'; frame-ancestors {}; img-src *"
        self.assertFalse(fr.frame_policy({"Content-Security-Policy": csp.format("'none'")})[1])
        self.assertFalse(fr.frame_policy({"Content-Security-Policy": csp.format("'self'")})[1])
        self.assertFalse(fr.frame_policy({"Content-Security-Policy": csp.format("https://elsewhere.test")})[1])
        self.assertTrue(fr.frame_policy({"Content-Security-Policy": csp.format("'self' https://bamr87.github.io")})[1])
        self.assertTrue(fr.frame_policy({"Content-Security-Policy": csp.format("*")})[1])
        policy, ok = fr.frame_policy({"Content-Security-Policy": csp.format("*"), "X-Frame-Options": "DENY"})
        self.assertFalse(ok, "either header refusing is a refusal")
        self.assertTrue(policy.startswith("frame-ancestors"))


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 — http.server's name
        port = self.server.server_address[1]
        body = b""
        if self.path.startswith("/hop"):  # an HTTP redirect to another origin (same server, other host name)
            self.send_response(302)
            self.send_header("Location", f"http://localhost:{port}/")
        else:
            self.send_response(404 if self.path.startswith("/missing") else 200)
        if self.path.startswith("/deny"):
            self.send_header("X-Frame-Options", "DENY")
        if self.path.startswith("/apex"):  # a static page that forwards the browser, as an apex → www page does
            body = b'<!doctype html><meta http-equiv="refresh" content="0; url=https://www.elsewhere.test/">'
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class ProbeTests(unittest.TestCase):
    """Against a loopback server: the probe is the one subcommand that reads
    the network, and it only ever asks the addresses the launcher holds."""

    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        with socket.socket() as s:  # a port nothing listens on
            s.bind(("127.0.0.1", 0))
            cls.dead = f"http://127.0.0.1:{s.getsockname()[1]}/"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def apps(self):
        def app(i, live, local=None):
            t = [{"id": "live", "kind": "live", "url": live}]
            if local:
                t.append({"id": "local", "kind": "local", "url": local})
            return {"id": i, "name": i.upper(), "targets": t}
        return [app("open", f"{self.base}/"), app("deny", f"{self.base}/deny"), app("gone", f"{self.base}/missing"),
                app("down", self.dead, local=f"{self.base}/"), app("odd", "ftp://x.test/")]

    def test_status_and_frame_policy_per_address(self):
        rows = {r["app"]: r for r in fr.probe(self.apps())}
        self.assertEqual(set(rows), {"open", "deny", "gone", "down"}, "only http(s) addresses are asked")
        self.assertEqual((rows["open"]["status"], rows["open"]["ok"], rows["open"]["frameable"]), (200, True, True))
        self.assertEqual((rows["deny"]["ok"], rows["deny"]["frameable"], rows["deny"]["policy"]), (True, False, "x-frame-options deny"))
        self.assertEqual((rows["gone"]["status"], rows["gone"]["ok"]), (404, False))
        self.assertEqual((rows["down"]["status"], rows["down"]["ok"], rows["down"]["frameable"]), (None, False, None))
        self.assertTrue(rows["down"]["error"])

    def test_an_address_that_moves_to_an_undeclared_origin_cannot_be_framed(self):
        """Headers alone said bash-365.com was frameable; its apex page forwards
        to www, an origin no registry entry declared, and the shell refused it."""
        def app(i, path, embed="frame"):
            return {"id": i, "name": i, "embed": embed, "targets": [{"id": "live", "kind": "live", "url": f"{self.base}{path}"}]}
        port = self.server.server_address[1]
        rows = {r["app"]: r for r in fr.probe([app("apex", "/apex"), app("hop", "/hop")])}
        self.assertEqual(rows["apex"]["moves_to"], "https://www.elsewhere.test")
        self.assertFalse(rows["apex"]["frameable"])
        self.assertIn("no registry entry declares", rows["apex"]["policy"])
        self.assertEqual((rows["hop"]["moves_to"], rows["hop"]["frameable"]), (f"http://localhost:{port}", False))
        # …and is fine once another entry declares the origin it lands on.
        declared = [app("hop", "/hop"), {"id": "www", "name": "www", "embed": "frame",
                                         "targets": [{"id": "live", "kind": "live", "url": f"http://localhost:{port}/"}]}]
        rows = {r["app"]: r for r in fr.probe(declared)}
        self.assertEqual((rows["hop"]["moves_to"], rows["hop"]["frameable"], rows["hop"]["policy"]),
                         (f"http://localhost:{port}", True, "open"))
        self.assertIsNone(rows["www"]["moves_to"])

    def test_moved_to_reads_both_kinds_of_redirect(self):
        self.assertIsNone(fr.moved_to("https://a.test/", "https://a.test/home", "<p>hi</p>"))
        self.assertEqual(fr.moved_to("https://a.test/", "https://b.test/", ""), "https://b.test")
        self.assertEqual(fr.moved_to("https://a.test/", "https://a.test/", "<META HTTP-EQUIV=refresh CONTENT='0;URL=//c.test/x'>"), "https://c.test")
        self.assertIsNone(fr.moved_to("https://a.test/", "https://a.test/", '<meta http-equiv="refresh" content="0; url=/next">'))

    def test_target_filter_app_filter_and_cap(self):
        self.assertEqual([r["target"] for r in fr.probe(self.apps(), "local")], ["local"])
        self.assertEqual(len(fr.probe(self.apps(), "all")), 5)
        self.assertEqual([r["app"] for r in fr.probe(self.apps(), "live", ["DENY"])], ["deny"])
        self.assertEqual(len(fr.probe(self.apps(), "all", cap=2)), 2)
        self.assertIn("no (x-frame-options deny)", fr.probe_table(fr.probe(self.apps(), "live", ["deny"])))


if __name__ == "__main__":
    unittest.main()
