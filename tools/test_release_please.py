#!/usr/bin/env python3
"""The release credential: `.github/workflows/release-please.yml` and its contract.

The fleet's release PRs are opened by a GitHub App (docs/RELEASES.md "The
release app"). These checks hold the properties that make that safe to run on
every repo at once:

  * the order is the app, then the legacy PAT, then GITHUB_TOKEN, at every
    place a token is used, so a repo holding only the PAT releases as before;
  * the KEY arms the app and the client ID alone is inert, which is why the
    token contract declares the client ID first: the fan-out writes in that
    order, and no repo is left holding a key it cannot use;
  * a key with no client ID, and an app that cannot mint, fail the run; neither
    falls through to another credential;
  * the minted token is cut down to what a release needs, and `relock` mints
    its own (a token is revoked when its job ends);
  * every secret a caller may pass by name is declared by the workflow (an
    undeclared one rejects the caller's whole run before any job starts), and
    every secret the workflow reads is in the token contract and handed to
    `token-rotation.yml`.

Offline: reads the workflow, `_data/fleet.yml` and the sdlc kit; no network.

    python3 tools/test_release_please.py
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "release-please.yml"
ROTATION = ROOT / ".github" / "workflows" / "token-rotation.yml"
FLEET = ROOT / "_data" / "fleet.yml"
KIT_CALLER = ROOT / "templates" / "sdlc" / "release" / "release.yml"

APP_ID, APP_KEY, PAT = "RELEASE_APP_CLIENT_ID", "RELEASE_APP_PRIVATE_KEY", "RELEASE_PLEASE_TOKEN"
ORDER = "${{ steps.app.outputs.token || secrets.RELEASE_PLEASE_TOKEN || secrets.GITHUB_TOKEN }}"
MINT = "actions/create-github-app-token"


def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def on(wf: dict) -> dict:
    return wf.get("on") or wf.get(True)  # PyYAML reads a bare `on:` as True


def steps(job: dict, **match) -> list[dict]:
    return [s for s in job["steps"] if all(str(s.get(k, "")).startswith(v) for k, v in match.items())]


class Credential(unittest.TestCase):
    def setUp(self) -> None:
        self.wf = workflow()
        self.release = self.wf["jobs"]["release-please"]
        self.relock = self.wf["jobs"]["relock"]

    def test_every_token_follows_the_order(self) -> None:
        used = [s["with"]["token"] for job in (self.release, self.relock)
                for s in job["steps"] if "token" in (s.get("with") or {})]
        self.assertEqual(used, [ORDER] * 3, "tag pass, PR pass, relock checkout")

    def test_the_key_arms_the_app_and_the_client_id_alone_is_inert(self) -> None:
        (cred,) = steps(self.release, id="cred")
        self.assertEqual(cred["env"]["HAVE_ID"], "${{ secrets.%s != '' }}" % APP_ID)
        self.assertEqual(cred["env"]["HAVE_KEY"], "${{ secrets.%s != '' }}" % APP_KEY)
        run = cred["run"]
        self.assertIn('echo "app=$HAVE_KEY" >> "$GITHUB_OUTPUT"', run)
        # A key without a client ID stops the run; the reverse only warns.
        fails = re.search(r'if \[ "\$HAVE_KEY" = "true" \] && \[ "\$HAVE_ID" != "true" \]; then\n(.*?)\n\s*fi', run, re.S)
        self.assertIsNotNone(fails)
        self.assertIn("::error", fails.group(1))
        self.assertIn("exit 1", fails.group(1))
        warns = re.search(r'if \[ "\$HAVE_ID" = "true" \] && \[ "\$HAVE_KEY" != "true" \]; then\n(.*?)\n\s*fi', run, re.S)
        self.assertIsNotNone(warns)
        self.assertIn("::warning", warns.group(1))
        self.assertNotIn("exit", warns.group(1))

    def test_no_step_prints_a_secret(self) -> None:
        # `env:` may hold a comparison (true/false), never a bare secret.
        for name, job in self.wf["jobs"].items():
            for s in job["steps"]:
                for key, value in (s.get("env") or {}).items():
                    with self.subTest(job=name, env=key):
                        if "secrets." in str(value):
                            self.assertRegex(str(value), r"^\$\{\{ secrets\.[A-Z_]+ != '' \}\}$")

    def test_the_mint_is_scoped_and_runs_only_when_armed(self) -> None:
        (mint,) = steps(self.release, uses=MINT)
        self.assertEqual(mint["if"], "steps.cred.outputs.app == 'true'")
        self.assertRegex(mint["uses"], r"@v\d+$", "actions ride a major tag")
        w = mint["with"]
        # `client-id` is the input's name from v3.1.0; `app-id` is read into the
        # same value and is the one actionlint knows. Either, never both.
        ids = [w[k] for k in ("client-id", "app-id") if k in w]
        self.assertEqual(ids, ["${{ secrets.%s }}" % APP_ID])
        self.assertEqual(w["private-key"], "${{ secrets.%s }}" % APP_KEY)
        scopes = {k: v for k, v in w.items() if k.startswith("permission-")}
        self.assertEqual(scopes, {"permission-contents": "write", "permission-pull-requests": "write"})
        # This repo only: naming an owner or repositories would widen the token.
        self.assertFalse({"owner", "repositories"} & set(w))
        self.assertNotIn("continue-on-error", mint, "an armed app that cannot mint must fail the run")

    def test_a_failed_mint_is_explained_and_never_falls_back(self) -> None:
        (explain,) = [s for s in self.release["steps"] if s.get("name") == "Explain a failed mint"]
        self.assertEqual(explain["if"], "failure() && steps.app.conclusion == 'failure'")
        for cause in ("not installed", "does not belong", "lacks a permission"):
            self.assertIn(cause, explain["run"])

    def test_relock_mints_its_own_token(self) -> None:
        self.assertEqual(self.release["outputs"]["app"], "${{ steps.cred.outputs.app }}")
        first, second = self.relock["steps"][0], self.relock["steps"][1]
        self.assertTrue(first["uses"].startswith(MINT), "minted before the checkout that uses it")
        self.assertEqual(first["if"], "needs.release-please.outputs.app == 'true'")
        self.assertEqual({k: v for k, v in first["with"].items() if k.startswith("permission-")},
                         {"permission-contents": "write"}, "a lockfile commit needs contents only")
        self.assertTrue(second["uses"].startswith("actions/checkout"))
        self.assertEqual(second["with"]["token"], ORDER)

    def test_the_guard_treats_a_provisioned_app_as_a_defect(self) -> None:
        (guard,) = [s for s in self.release["steps"] if s.get("name") == "Guard the release-PR denial"]
        self.assertEqual(guard["env"]["HAVE_APP"], "${{ steps.cred.outputs.app }}")
        run = guard["run"]
        app, pat, strict, warn = (run.index(m) for m in ('"$HAVE_APP" = "true"', '"$HAVE_PAT" = "true"',
                                                         '"$STRICT" = "true"', "::warning"))
        self.assertLess(app, pat)
        self.assertLess(pat, strict)
        self.assertLess(strict, warn, "only a repo with no credential at all gets the warning")
        self.assertEqual(run.count("exit 1"), 3)


class Contract(unittest.TestCase):
    def setUp(self) -> None:
        self.wf = workflow()
        self.declared = on(self.wf)["workflow_call"]["secrets"]
        self.tokens = yaml.safe_load(FLEET.read_text())["tokens"]
        self.by_name = {t["name"]: t for t in self.tokens}

    def test_every_secret_the_workflow_reads_is_declared_and_optional(self) -> None:
        read = set(re.findall(r"secrets\.([A-Z][A-Z0-9_]+)", WORKFLOW.read_text())) - {"GITHUB_TOKEN"}
        self.assertEqual(read, {APP_ID, APP_KEY, PAT})
        self.assertEqual(set(self.declared), read,
                         "a caller under another owner passes these by name; an undeclared one rejects its run")
        for name, spec in self.declared.items():
            with self.subTest(secret=name):
                self.assertIs(spec.get("required"), False, "a caller that holds none must still run")

    def test_the_kit_caller_passes_nothing_the_workflow_does_not_declare(self) -> None:
        passed = yaml.safe_load(KIT_CALLER.read_text())["jobs"]["release"].get("secrets")
        if passed == "inherit":
            return
        self.assertLessEqual(set(passed), set(self.declared))
        for name, value in passed.items():
            with self.subTest(secret=name):
                self.assertEqual(value, "${{ secrets.%s }}" % name)

    def test_the_contract_carries_the_app_to_the_fleet(self) -> None:
        wiring = ROTATION.read_text()
        for name in (APP_ID, APP_KEY, PAT):
            with self.subTest(secret=name):
                token = self.by_name[name]
                self.assertEqual(token["scope"], "fleet")
                self.assertFalse(token.get("required"))
                self.assertIn("release-please.yml", token["used_by"])
                self.assertTrue(token["rotation"]["enabled"])
                self.assertIn(f"{name}: ${{{{ secrets.{name} }}}}", wiring)
        for name in (APP_ID, APP_KEY):
            with self.subTest(secret=name):
                self.assertEqual(self.by_name[name]["rotation"]["lifetime_days"], 0, "an app credential does not expire")

    def test_the_client_id_is_declared_before_the_key(self) -> None:
        names = [t["name"] for t in self.tokens]
        self.assertLess(names.index(APP_ID), names.index(APP_KEY),
                        "push and rotate write in contract order, and the key is what arms the app")

    def test_no_value_in_the_contract(self) -> None:
        blob = yaml.safe_dump([self.by_name[n] for n in (APP_ID, APP_KEY)])
        self.assertNotRegex(blob, r"Iv[0-9A-Za-z.]{8,}")
        self.assertNotRegex(blob, r"[A-Za-z0-9+/]{40,}")


if __name__ == "__main__":
    sys.exit(unittest.main())
