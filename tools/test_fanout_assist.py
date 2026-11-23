#!/usr/bin/env python3
"""Tests for the assistant arm of tools/fanout.sh (`--kit assist`): where the kit lands in a repo.

The first dry run across the fleet (2026-11-22) showed the arm reading only the files at a repo's root: it seeded
nothing in five of the nineteen page repos, whose app sits in a subfolder, and put the React adapter outside the app
in two more. Each layout below is one of those repos, reduced to the files that decide the answer:

- the platform family comes from the planner (`fleetcore.assist.family`, the registry), not from the root's files;
- the payload and the adapter go where the app is, not where the repo starts;
- a zer0-mistakes consumer vendors nothing, because the theme carries the page bridge (ADR 0014 P1);
- a copy the repo already has is the one kept, wherever it was moved to, so a re-run never seeds a second.

Offline: sources the arm's functions out of fanout.sh and runs them in bash, in a temp folder. Run:
    python3 tools/test_fanout_assist.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HUB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUB / "tools"))
from fleetcore import assist  # noqa: E402

BASH = shutil.which("bash") or "/bin/bash"
KIT = HUB / "templates" / "assistant"
PAYLOAD = (KIT / "fleet-assist.js").read_text(encoding="utf-8")
FUNCTIONS = ("feedback_stack", "seed_vendored_asset", "assist_family", "assist_is_app", "assist_app_root",
             "assist_component_dir", "assist_page_dir", "assist_static_asset_dir", "assist_mkdocs_key",
             "assist_existing", "assist_seed_adapter", "seed_assist")
HARNESS = r"""
set -euo pipefail
HUB="$1"; UPGRADE=0; FB_VERSION="0.0.0"; AST_VERSION="9.9.9"
eval "$(sed -n '""" + " ".join(f"/^{f}()/,/^}}/p;" for f in FUNCTIONS) + r"""' "$HUB/tools/fanout.sh")"
if [[ -n "${FAMILY:-}" ]]; then assist_family() { echo "$FAMILY"; }; fi
cd "$2"
if [[ "${4:-seed}" == "family" ]]; then assist_family "$3"; else seed_assist "$3" main; fi
"""
REACT = '{"dependencies": {"react": "latest"}, "devDependencies": {"vite": "latest"}}'
NEXT = '{"dependencies": {"next": "latest", "react": "latest"}}'


class Layout(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="fanout-assist-"))
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)

    def put(self, rel: str, text: str = "") -> Path:
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def files(self) -> set[str]:
        return {str(p.relative_to(self.repo)) for p in self.repo.rglob("*") if p.is_file()}

    def run_arm(self, family: str | None, name: str = "demo", mode: str = "seed") -> subprocess.CompletedProcess:
        env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin:" + str(Path(sys.executable).parent), "PYTHON": sys.executable}
        if os.environ.get("PYTHONPATH"):  # where a local checkout keeps PyYAML (tools/devtools-env.sh)
            env["PYTHONPATH"] = os.environ["PYTHONPATH"]
        if family is not None:
            env["FAMILY"] = family
        proc = subprocess.run([BASH, "-c", HARNESS, "test", str(HUB), str(self.repo), name, mode],
                              capture_output=True, text=True, timeout=120, env=env)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc

    def seed(self, family: str, name: str = "demo") -> tuple[set[str], str]:
        before = self.files()
        out = self.run_arm(family, name).stdout
        return self.files() - before, out


class ReactAndNext(Layout):
    def test_an_app_in_a_subfolder_gets_the_kit_inside_it(self):
        """gitorio, cv-pro: app/ holds the Vite app and the root has no package.json."""
        self.put("app/package.json", REACT)
        self.put("app/index.html")
        self.put("app/src/main.tsx")
        new, out = self.seed("react", "gitorio")
        self.assertEqual(new, {"app/public/fleet-assist.js", "app/src/components/AssistBridge.tsx"})
        self.assertIn("import it from app/src/components/AssistBridge.tsx", out)
        self.assertIn('repo="bamr87/gitorio"', out)

    def test_a_next_app_in_frontend_keeps_its_adapter_out_of_the_repo_root(self):
        """law-ai: frontend/ is the app, lsat-static/ is a second one, and the root has a components/ of its own."""
        self.put("frontend/package.json", NEXT)
        self.put("frontend/components/shell/Nav.tsx")
        self.put("lsat-static/package.json", NEXT)
        self.put("components/FeedbackButton.tsx")
        new, out = self.seed("nextjs", "law-ai")
        self.assertEqual(new, {"frontend/public/fleet-assist.js", "frontend/components/AssistBridge.tsx",
                               "frontend/components/AssistBridgeNext.tsx"})
        self.assertIn("frontend/app/layout.tsx", out)

    def test_an_app_two_folders_down_is_found_past_a_workspace_root_and_a_ui_package(self):
        """zer0-CMS: an extension's package.json at the root, a workspace in web/, the app in web/studio."""
        self.put("package.json", '{"engines": {"vscode": "^1.90.0"}}')
        self.put("web/package.json", '{"devDependencies": {"vite": "latest"}}')
        self.put("web/packages/ui/package.json", '{"dependencies": {"react": "latest"}}')
        self.put("web/studio/package.json", REACT)
        self.put("web/studio/index.html")
        self.put("web/studio/src/main.tsx")
        new, _ = self.seed("react", "zer0-CMS")
        self.assertEqual(new, {"web/studio/public/fleet-assist.js", "web/studio/src/components/AssistBridge.tsx"})

    def test_an_app_at_the_root_is_still_the_root(self):
        self.put("package.json", REACT)
        self.put("vite.config.ts")
        self.put("src/main.tsx")
        new, _ = self.seed("react")
        self.assertEqual(new, {"public/fleet-assist.js", "src/components/AssistBridge.tsx"})

    def test_a_package_that_only_depends_on_react_is_not_an_app(self):
        self.put("packages/ui/package.json", '{"dependencies": {"react": "latest"}}')
        new, out = self.seed("react")
        self.assertEqual(new, set())
        self.assertIn("nothing seeded", out)


class StaticPages(Layout):
    def test_a_page_inside_a_package_gets_the_payload_beside_it(self):
        """ocrmd: the page is ocrmd/web/static/index.html; the root public/ is served by nothing."""
        self.put("ocrmd/web/static/index.html")
        self.put("public/fleet-feedback.js")
        new, out = self.seed("static", "ocrmd")
        self.assertEqual(new, {"ocrmd/web/static/fleet-assist.js"})
        self.assertIn("ocrmd/web/static/index.html", out)

    def test_a_page_in_static_keeps_its_script_in_static(self):
        """ragio-ai: FastAPI serves static/; assets/js at the root would be out of reach."""
        self.put("static/index.html")
        new, _ = self.seed("static", "ragio-ai")
        self.assertEqual(new, {"static/fleet-assist.js"})

    def test_a_page_at_the_root_uses_the_folder_the_repo_already_has(self):
        self.put("index.html")
        self.put("public/fleet-feedback.js")
        new, _ = self.seed("static", "bash-365-apex")
        self.assertEqual(new, {"public/fleet-assist.js"})

    def test_a_page_at_the_root_with_no_script_folder_gets_assets_js(self):
        self.put("index.html")
        new, _ = self.seed("static")
        self.assertEqual(new, {"assets/js/fleet-assist.js"})

    def test_a_static_repo_with_no_page_gets_nothing(self):
        self.put("README.md")
        new, out = self.seed("static")
        self.assertEqual(new, set())
        self.assertIn("no index.html", out)


class Jekyll(Layout):
    def test_a_theme_consumer_vendors_nothing(self):
        """The seven zer0-mistakes sites take the page bridge from the theme: one key in _config.yml, no copy."""
        self.put("_config.yml", "remote_theme: bamr87/zer0-mistakes\n")
        new, out = self.seed("jekyll", "it-journey")
        self.assertEqual(new, set())
        self.assertIn("fleet_assist:", out)
        self.assertIn("enabled: true", out)

    def test_a_consumer_that_set_the_key_is_done(self):
        self.put("_config.yml", "remote_theme: bamr87/zer0-mistakes\nfleet_assist:\n  enabled: true\n")
        new, out = self.seed("jekyll", "it-journey")
        self.assertEqual(new, set())
        self.assertIn("nothing to seed", out)

    def test_the_theme_itself_carries_the_payload_with_its_components(self):
        self.put("_config.yml", "title: zer0-mistakes\n")
        self.put("jekyll-theme-zer0.gemspec")
        self.put("_includes/components/page-feedback.html")
        new, out = self.seed("jekyll", "zer0-mistakes")
        self.assertEqual(new, {"assets/js/fleet-assist.js", "_includes/components/fleet-assist.html"})
        self.assertIn("{% include components/fleet-assist.html %}", out)

    def test_a_plain_jekyll_site_keeps_the_include_in_custom(self):
        self.put("_config.yml", "title: a site\n")
        new, _ = self.seed("jekyll")
        self.assertEqual(new, {"assets/js/fleet-assist.js", "_includes/custom/fleet-assist.html"})


class DjangoAndMkdocs(Layout):
    def test_django_uses_public_when_the_repo_maps_it_and_static_js_otherwise(self):
        self.put("manage.py")
        self.put("public/fleet-feedback.js")
        new, _ = self.seed("django", "djangoerp")
        self.assertEqual(new, {"public/fleet-assist.js", "templates/includes/fleet-assist.html"})

    def test_django_without_public_gets_static_js(self):
        self.put("manage.py")
        new, _ = self.seed("django")
        self.assertEqual(new, {"static/js/fleet-assist.js", "templates/includes/fleet-assist.html"})

    def test_mkdocs_reads_docs_dir_and_never_replaces_an_existing_override(self):
        self.put("mkdocs.yml", "docs_dir: content   # the pages\ntheme:\n  name: material\n  custom_dir: 'theme'\n")
        main = self.put("theme/main.html", '{% extends "base.html" %}\n')
        new, out = self.seed("mkdocs", "README")
        self.assertEqual(new, {"content/assets/js/fleet-assist.js"})
        self.assertEqual(main.read_text(), '{% extends "base.html" %}\n')
        self.assertIn("theme/main.html exists", out)

    def test_mkdocs_without_an_override_gets_the_adapter(self):
        self.put("mkdocs.yml", "site_name: docs\n")
        new, _ = self.seed("mkdocs")
        self.assertEqual(new, {"docs/assets/js/fleet-assist.js", "overrides/main.html"})


class WhatIsAlreadyThere(Layout):
    def test_a_second_run_changes_nothing(self):
        self.put("app/package.json", REACT)
        self.put("app/index.html")
        self.seed("react")
        new, out = self.seed("react")
        self.assertEqual(new, set())
        self.assertIn("fleet-assist.js: current", out)
        self.assertIn("adapter present", out)

    def test_a_copy_moved_by_hand_is_the_copy_that_is_kept(self):
        """A repo that put the adapter with its own chrome and the payload in its own folder gets no second copy."""
        self.put("package.json", REACT)
        self.put("vite.config.mts")
        self.put("web/src/chrome/AssistBridge.tsx", "// moved\n")
        self.put("web/public/fleet-assist.js", PAYLOAD)
        new, out = self.seed("react", "bashcrawl")
        self.assertEqual(new, set())
        self.assertIn("web/src/chrome/AssistBridge.tsx", out)

    def test_a_changed_payload_is_left_alone_and_said_so(self):
        self.put("index.html")
        self.put("js/fleet-assist.js", "// edited here\n")
        new, out = self.seed("static")
        self.assertEqual(new, set())
        self.assertIn("hand-modified", out)

    def test_a_repo_with_no_page_gets_nothing(self):
        self.put("README.md")
        for family in ("none", "gap"):
            new, out = self.seed(family)
            self.assertEqual(new, set(), family)
            self.assertIn("nothing to seed", out)


class TheFamilyComesFromThePlanner(Layout):
    def test_the_arm_answers_what_the_planner_answers_for_every_page_repo(self):
        """An EMPTY folder: the files cannot be what decided."""
        rows = [r for r in assist.plan(HUB)["rows"] if r["level"] == "page"]
        self.assertTrue(rows, "the registry has no page repo")
        for row in rows:
            got = self.run_arm(None, row["name"], "family").stdout.strip()
            self.assertEqual(got, row["family"], row["name"])

    def test_a_repo_the_registry_does_not_know_falls_back_to_its_files(self):
        self.put("index.html")
        proc = self.run_arm(None, "not-a-fleet-repo", "family")
        self.assertEqual(proc.stdout.strip(), "static")
        self.assertIn("not in the registry", proc.stderr)

    def test_the_planner_says_none_for_a_repo_with_no_page_and_nothing_for_an_unknown_one(self):
        context = next(r["name"] for r in assist.plan(HUB)["rows"] if r["level"] == "context")
        self.assertEqual(assist.family(context, HUB), "none")
        self.assertIsNone(assist.family("not-a-fleet-repo", HUB))
        self.assertIsNone(assist.family("", HUB))
        self.assertEqual(assist.main(["family", "not-a-fleet-repo"]), 3)

    def test_every_family_the_planner_can_name_has_an_arm(self):
        fanout = (HUB / "tools" / "fanout.sh").read_text(encoding="utf-8")
        arm = fanout[fanout.index("seed_assist() {"):fanout.index("feedback_ensure_labels() {")]
        for family, *_ in assist.ADAPTERS:
            self.assertRegex(arm, rf"(?m)^\s+(\w+\|)*{family}(\|\w+)*\)", f"seed_assist has no arm for {family}")


if __name__ == "__main__":
    unittest.main(verbosity=1)
