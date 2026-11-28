#!/usr/bin/env python3
"""Tests for tools/fleetcore/clouds.py — where each fleet repo's deliverable runs,
read from the repos' own workflows and infrastructure files (ADR 0018).
Offline, no pytest:  python3 tools/test_fleetcore_clouds.py"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fleetcore import clouds  # noqa: E402

HUB = Path(__file__).resolve().parent.parent

# Two made-up providers: the reader must work from data alone, whatever the vendor.
BLOCK = {
    "providers": {
        "plat": {
            "title": "Plat", "enabled": True, "identity": "platform",
            "services": {"pages": {"kind": "static", "uses": ["plat/deploy-pages"], "hosts": ["*.plat.test"],
                                   "files": ["CNAME"], "secret": ["deploy_key"]}},
        },
        "acme": {
            "title": "Acme", "enabled": False, "identity": "oidc",
            "login": [{"uses": "acme/login", "oidc": ["client-id"], "secret": ["creds"]}],
            "services": {
                "sites": {"kind": "static", "uses": ["acme/sites-deploy"], "run": ["acme site push"], "secret": ["api_token"]},
                "boxes": {"kind": "container", "run": ["acme box deploy"]},
            },
            "iac": [{"name": "*.acme"}, {"name": "*.tf", "contains": "vendor/acme"}],
        },
    },
    "scan": {"skip_dirs": ["node_modules", "docs"], "max_depth": 3, "max_files": 50},
}
MODEL = clouds.normalize(BLOCK)


def job(*steps, **extra):
    return {"runs-on": "ubuntu-latest", "steps": list(steps), **extra}


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def workflow(root: Path, name: str, jobs: dict) -> Path:
    return write(root, f".github/workflows/{name}", yaml.safe_dump({"name": name, "on": {"push": None}, "jobs": jobs}))


class ModelTests(unittest.TestCase):
    def test_the_committed_model_reads_and_declares_the_three_clouds(self):
        model = clouds.load_model(HUB, HUB)
        self.assertLessEqual({"github", "azure", "aws", "gcp"}, set(model["providers"]))
        for pid in ("azure", "aws", "gcp"):
            prov = model["providers"][pid]
            self.assertFalse(prov["enabled"], f"{pid}: the read switch ships off; turning it on is a deploy step")
            self.assertEqual(prov["identity"], "oidc", f"{pid}: no stored credential is the rule")
            self.assertTrue(prov["login"] and prov["iac"], f"{pid}: a sign-in step and its infrastructure files are recognised")
            self.assertTrue({"static", "container"} <= {s["kind"] for s in prov["services"].values()},
                            f"{pid}: a static site and a container service can both be recognised")

    def test_a_block_that_cannot_be_read_says_every_reason(self):
        bad = {"providers": {
            "Acme": {"enabled": "yes", "identity": "password", "services": {"x": {"kind": "vm"}}, "login": [{}], "iac": [{}]},
            "bare": {"enabled": True, "identity": "oidc"}}}
        text = " | ".join(clouds.model_problems(bad))
        for needle in ("clouds.providers.Acme: an id is", "enabled must be true or false", "identity must be one of",
                       "services.x.kind must be one of", "has nothing to recognise it by", "login[0] needs `uses`",
                       "iac[0] needs `name`", "clouds.providers.bare.services must name at least one service"):
            self.assertIn(needle, text)
        self.assertEqual(clouds.model_problems(BLOCK), [])
        self.assertEqual(clouds.model_problems(None), ["`clouds:` must be a mapping"])

    def test_an_instance_lays_its_block_over_the_frameworks(self):
        with tempfile.TemporaryDirectory() as tmp:
            fw, inst = Path(tmp) / "framework", Path(tmp) / "instance"
            write(fw, "_data/fleet.yml", yaml.safe_dump({"clouds": BLOCK}))
            write(inst, "_data/fleet.yml", yaml.safe_dump({"clouds": {"providers": {"acme": {"enabled": True}}}}))
            model = clouds.load_model(inst, fw)
            self.assertTrue(model["providers"]["acme"]["enabled"], "the instance's switch wins")
            self.assertEqual(model["providers"]["acme"]["services"]["sites"]["uses"], ["acme/sites-deploy"],
                             "how a provider is recognised still comes from the framework")
            write(inst, "_data/fleet.yml", "hub: {repo: o/hub}\n")
            self.assertFalse(clouds.load_model(inst, fw)["providers"]["acme"]["enabled"],
                             "an instance that declares nothing gets the framework's block")
            with self.assertRaises(clouds.ModelError):
                clouds.load_model(inst, inst)


class ScanJobTests(unittest.TestCase):
    def hit(self, j, service="sites"):
        rows = [r for r in clouds.scan_job(j, MODEL) if r["service"] == service]
        self.assertEqual(len(rows), 1, rows)
        return rows[0]

    def test_a_federated_login_is_oidc_and_keeps_only_names(self):
        got = self.hit(job({"uses": "Acme/Login@v3", "with": {"client-id": "${{ secrets.ACME_CLIENT_ID }}", "tenant": "${{ vars.ACME_TENANT }}"}},
                           {"run": "acme site push ./out"}))
        self.assertEqual(got["identity"], "oidc")
        self.assertEqual((got["credential_names"], got["variable_names"]), ({"ACME_CLIENT_ID"}, {"ACME_TENANT"}))

    def test_only_a_name_written_in_the_workflow_is_kept_never_a_value(self):
        got = self.hit(job({"uses": "acme/sites-deploy@v1", "with": {"api_token": "a-value-typed-into-the-workflow"},
                            "env": {"A": "${{ secrets.REAL_NAME }}", "B": "plain-value", "C": "${{ secrets['odd key'] }}"}}))
        self.assertEqual((got["credential_names"], got["variable_names"]), ({"REAL_NAME"}, set()))
        self.assertNotIn("a-value", json.dumps(sorted(got["credential_names"])))

    def test_a_stored_credential_wins_over_a_federated_input(self):
        got = self.hit(job({"uses": "acme/login@v3", "with": {"client-id": "x", "creds": "${{ secrets.ACME_CREDS }}"}},
                           {"uses": "acme/sites-deploy@v1"}))
        self.assertEqual(got["identity"], "secret")

    def test_a_deploy_step_with_a_secret_input_and_no_login_is_secret(self):
        got = self.hit(job({"uses": "acme/sites-deploy@v1", "with": {"api_token": "${{ secrets.ACME_TOKEN }}"}}))
        self.assertEqual((got["identity"], got["credential_names"]), ("secret", {"ACME_TOKEN"}))

    def test_a_step_handed_a_secret_in_its_environment_is_secret(self):
        got = self.hit(job({"run": "acme box deploy", "env": {"ACME_KEY": "${{ secrets.ACME_KEY }}"}}), "boxes")
        self.assertEqual(got["identity"], "secret")

    def test_the_platform_token_is_not_a_stored_credential(self):
        got = self.hit(job({"run": "acme box deploy", "env": {"GH": "${{ secrets.GITHUB_TOKEN }}"}}), "boxes")
        self.assertEqual((got["identity"], got["credential_names"]), ("unknown", set()))

    def test_a_deploy_with_no_sign_in_reads_unknown_never_a_guess(self):
        self.assertEqual(self.hit(job({"run": "acme box deploy"}), "boxes")["identity"], "unknown")

    def test_a_platform_provider_signs_in_with_the_platform_token(self):
        self.assertEqual(self.hit(job({"uses": "plat/deploy-pages@v5"}), "pages")["identity"], "platform")
        self.assertEqual(self.hit(job({"uses": "plat/deploy-pages@v5", "with": {"deploy_key": "k"}}), "pages")["identity"], "secret")

    def test_a_command_named_in_a_comment_deploys_nothing(self):
        self.assertEqual(clouds.scan_job(job({"run": "# acme site push would go here\necho later"}), MODEL), [])

    def test_only_the_named_action_matches(self):
        for uses in ("acme/sites-deploy-extra@v1", "./.github/actions/acme/sites-deploy", "docker://acme/sites-deploy", "other/acme"):
            self.assertEqual(clouds.scan_job(job({"uses": uses}), MODEL), [], uses)
        self.assertEqual(self.hit(job({"uses": "acme/sites-deploy/sub@v1"}))["service"], "sites")

    def test_a_nested_value_where_text_belongs_is_never_printed(self):
        bomb = {"a": ["x" * 10] * 10}
        j = job({"uses": bomb, "run": bomb, "with": {"api_token": bomb}, "env": {"K": bomb}},
                {"uses": "acme/sites-deploy@v1", "with": {"note": bomb}}, environment={"name": bomb, "url": bomb})
        self.assertEqual(self.hit(j)["identity"], "unknown")
        self.assertEqual(clouds._environment(j), (None, None))
        self.assertEqual((clouds._text(3), clouds._text(True), clouds._text(None), clouds._text(["a"])), ("3", "", "", ""))

    def test_a_job_that_calls_a_workflow_is_read_as_one_step(self):
        got = self.hit({"uses": "acme/sites-deploy/.github/workflows/go.yml@v1", "with": {"api_token": "t"}})
        self.assertEqual(got["identity"], "secret")


class ScanRepoTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)

    def test_jobs_of_one_workflow_are_one_deployment(self):
        workflow(self.repo, "deploy.yml", {
            "live": job({"uses": "acme/login@v1", "with": {"client-id": "x"}}, {"run": "acme site push"},
                        environment={"name": "production", "url": "https://shop.test/"}),
            "preview": job({"uses": "acme/login@v1", "with": {"client-id": "x"}}, {"run": "acme site push --pr"},
                           environment="${{ needs.plan.outputs.env }}"),
            "lint": job({"run": "echo ok"}),
        })
        got = clouds.scan_repo(self.repo, MODEL)
        self.assertEqual(got["workflows"], 1)
        (d,) = got["deployments"]
        self.assertEqual((d["provider"], d["service"], d["workflow"], d["evidence"]),
                         ("acme", "sites", ".github/workflows/deploy.yml", "workflow"))
        self.assertEqual(d["jobs"], ["live", "preview"])
        self.assertEqual(d["environments"], ["production", clouds.COMPUTED])
        self.assertEqual((d["urls"], d["identity"]), (["https://shop.test/"], "oidc"))

    def test_one_job_with_a_stored_credential_decides_the_deployment(self):
        workflow(self.repo, "deploy.yml", {
            "a": job({"uses": "acme/login@v1", "with": {"client-id": "x"}}, {"run": "acme site push"}),
            "b": job({"uses": "acme/sites-deploy@v1", "with": {"api_token": "${{ secrets.T }}"}})})
        (d,) = clouds.scan_repo(self.repo, MODEL)["deployments"]
        self.assertEqual((d["identity"], d["credential_names"]), ("secret", {"T"}))

    def test_an_address_on_the_providers_host_is_a_deployment_no_workflow_makes(self):
        (d,) = clouds.scan_repo(self.repo, MODEL, "https://me.plat.test/site/")["deployments"]
        self.assertEqual((d["provider"], d["service"], d["evidence"], d["workflow"], d["identity"]),
                         ("plat", "pages", "live_url", None, "platform"))
        self.assertEqual(clouds.scan_repo(self.repo, MODEL, "https://elsewhere.test/")["deployments"], [])

    def test_a_marker_file_at_the_root_is_evidence_too(self):
        write(self.repo, "CNAME", "shop.test\n")
        write(self.repo, "nested/CNAME", "no\n")
        (d,) = clouds.scan_repo(self.repo, MODEL, "https://shop.test/")["deployments"]
        self.assertEqual((d["service"], d["evidence"], d["urls"]), ("pages", "file:CNAME", ["https://shop.test/"]))

    def test_a_workflow_that_deploys_the_service_is_not_counted_twice(self):
        write(self.repo, "CNAME", "shop.test\n")
        workflow(self.repo, "pages.yml", {"deploy": job({"uses": "plat/deploy-pages@v5"})})
        (d,) = clouds.scan_repo(self.repo, MODEL, "https://me.plat.test/")["deployments"]
        self.assertEqual(d["evidence"], "workflow")

    def test_the_registry_address_goes_to_one_deployment_only(self):
        workflow(self.repo, "pages.yml", {"deploy": job({"uses": "plat/deploy-pages@v5"})})
        workflow(self.repo, "sites.yml", {"deploy": job({"run": "acme site push"})})
        by = {d["provider"]: d for d in clouds.scan_repo(self.repo, MODEL, "https://me.plat.test/")["deployments"]}
        self.assertEqual((by["plat"]["urls"], by["acme"]["urls"]), (["https://me.plat.test/"], []),
                         "the address is on the first provider's own host")
        by = {d["provider"]: d for d in clouds.scan_repo(self.repo, MODEL, "https://shop.test/")["deployments"]}
        self.assertEqual((by["plat"]["urls"], by["acme"]["urls"]), ([], []), "two static deployments: neither is claimed")

    def test_infrastructure_files_are_matched_by_name_and_content(self):
        write(self.repo, "infra/main.acme", "resource x\n")
        write(self.repo, "infra/net/main.tf", 'required_providers { a = { source = "vendor/acme" } }\n')
        write(self.repo, "infra/other.tf", 'source = "vendor/other"\n')
        write(self.repo, "docs/copied/main.acme", "a copy\n")
        write(self.repo, "node_modules/pkg/main.acme", "a dependency\n")
        write(self.repo, ".cache/main.acme", "tooling\n")
        write(self.repo, "a/b/c/d/deep.acme", "below the depth limit\n")
        write(self.repo, "vendored/.git", "gitdir: elsewhere\n")
        write(self.repo, "vendored/main.acme", "another repo's\n")
        got = clouds.scan_repo(self.repo, MODEL)
        self.assertEqual(got["iac"], {"acme": ["infra/main.acme", "infra/net/main.tf"]})
        self.assertFalse(got["iac_cut"])

    def test_a_walk_cut_short_says_so(self):
        for i in range(60):
            write(self.repo, f"infra/r{i:02}.acme", "x\n")
        got = clouds.scan_repo(self.repo, MODEL)
        self.assertTrue(got["iac_cut"])
        self.assertEqual(len(got["iac"]["acme"]), 50)

    def test_a_workflow_that_cannot_be_read_is_listed_not_fatal(self):
        write(self.repo, ".github/workflows/broken.yml", "jobs: [unclosed\n")
        write(self.repo, ".github/workflows/empty.yml", "name: nothing\n")
        workflow(self.repo, "ok.yml", {"deploy": job({"uses": "plat/deploy-pages@v5"})})
        got = clouds.scan_repo(self.repo, MODEL)
        self.assertEqual(got["unreadable"], [".github/workflows/broken.yml", ".github/workflows/empty.yml"])
        self.assertEqual((got["workflows"], len(got["deployments"])), (3, 1))


class StatusDocTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.inst = Path(self._tmp.name)
        write(self.inst, "_data/fleet.yml", yaml.safe_dump({
            "hub": {"repo": "own/hub", "owners": ["own", "org"]}, "clouds": copy.deepcopy(BLOCK),
            "tokens": [{"name": "ACME_TOKEN", "scope": "fleet"}]}))
        write(self.inst, "_data/projects.yml", yaml.safe_dump([
            {"name": "shop", "submodule_path": "projects/shop", "repo_url": "https://github.com/org/shop", "status": "active",
             "live_url": "https://shop.test/"},
            {"name": "blog", "submodule_path": "projects/blog", "repo_url": "https://github.com/own/blog.git", "status": "active",
             "live_url": "https://own.plat.test/blog/"},
            {"name": "infra-only", "submodule_path": "projects/infra-only", "repo_url": "https://github.com/own/infra-only"},
            {"name": "absent", "submodule_path": "projects/absent", "repo_url": "https://github.com/own/absent"},
            {"name": "listed", "repo_url": "https://github.com/own/listed"},
            {"name": "mirror", "submodule_path": "projects/mirror", "repo_url": "https://github.com/someone/mirror"},
        ]))
        for name in ("shop", "blog", "infra-only", "mirror"):
            write(self.inst, f"projects/{name}/.git", "gitdir: ../../.git/modules/x\n")
        workflow(self.inst / "projects/shop", "deploy.yml", {
            "site": job({"uses": "acme/sites-deploy@v1", "with": {"api_token": "${{ secrets.ACME_TOKEN }}", "extra": "${{ secrets.LOOSE }}"}}),
            "box": job({"run": "acme box deploy"})})
        write(self.inst, "projects/infra-only/main.acme", "resource\n")
        workflow(self.inst / "projects/mirror", "deploy.yml", {"site": job({"uses": "acme/sites-deploy@v1"})})
        workflow(self.inst, "hub.yml", {"pages": job({"uses": "plat/deploy-pages@v5"}, environment="pages")})
        self.doc = clouds.status_doc(self.inst, self.inst)

    def test_the_document_has_its_contract(self):
        self.assertEqual(self.doc["schema"], "fleet-clouds/v1")
        self.assertEqual(set(self.doc), {"schema", "generated_at", "hub", "providers", "deployments", "iac", "repos", "read",
                                         "findings", "summary"})
        self.assertEqual(self.doc["hub"], "own/hub")
        self.assertEqual(set(self.doc["deployments"][0]), {"repo", "name", "provider", "service", "kind", "evidence", "workflow",
                                                          "jobs", "environments", "urls", "identity", "expected", "credential_names",
                                                          "variable_names"})
        json.dumps(self.doc)  # every value is plain data

    def test_every_owned_checkout_is_read_the_hub_included(self):
        got = {(d["repo"], d["provider"], d["service"]) for d in self.doc["deployments"]}
        self.assertEqual(got, {("own/hub", "plat", "pages"), ("own/blog", "plat", "pages"),
                               ("org/shop", "acme", "sites"), ("org/shop", "acme", "boxes")})
        self.assertEqual(self.doc["read"]["repos"], 4)

    def test_a_repo_that_was_not_read_is_named_never_counted_as_clean(self):
        self.assertEqual(self.doc["read"]["unread"], [
            {"name": "absent", "repo": "own/absent", "why": "not checked out"},
            {"name": "listed", "repo": "own/listed", "why": "not a submodule of this instance"}])

    def test_another_owners_repo_is_never_read(self):
        self.assertEqual(self.doc["read"]["external"], 1)
        self.assertNotIn("someone/mirror", {d["repo"] for d in self.doc["deployments"]})
        self.assertNotIn("mirror", {r["name"] for r in self.doc["repos"]})

    def test_the_hub_does_not_claim_a_submodules_infrastructure(self):
        self.assertEqual([(i["repo"], i["provider"], i["paths"]) for i in self.doc["iac"]],
                         [("own/infra-only", "acme", ["main.acme"])])

    def test_findings(self):
        got = {(f["rule"], f["level"], f["repo"]) for f in self.doc["findings"]}
        self.assertEqual(got, {
            ("stored-credential", "warn", "org/shop"),      # the provider's rule is oidc
            ("unmanaged-credential", "note", "org/shop"),   # LOOSE is not in tokens:
            ("identity-unknown", "note", "org/shop"),       # the box job signs in nowhere a step shows
            ("no-iac", "note", "org/shop"),                 # deploys, and declares no resource
            ("iac-without-deploy", "note", "own/infra-only"),
        })
        loose = next(f for f in self.doc["findings"] if f["rule"] == "unmanaged-credential")
        self.assertIn("LOOSE", loose["message"])
        self.assertNotIn("ACME_TOKEN", loose["message"], "a credential the token contract names is managed")
        self.assertEqual(self.doc["findings"][0]["level"], "warn", "warnings first")

    def test_the_summary_counts_what_nothing_watches(self):
        s = self.doc["summary"]
        self.assertEqual((s["providers"], s["in_use"], s["deployments"], s["repos"]), (2, 2, 4, 3))
        self.assertEqual(s["unwatched"], 2, "both Acme deployments: its read switch is off")
        self.assertEqual(s["kinds"], {"static": 3, "container": 1})
        self.assertEqual(s["findings"], {"warn": 1, "note": 4})
        acme = next(p for p in self.doc["providers"] if p["id"] == "acme")
        self.assertEqual((acme["state"], acme["deployments"], acme["repos"], acme["iac"], acme["by_identity"]),
                         ("off", 2, 1, 1, {"secret": 1, "unknown": 1}))

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = clouds.main([*argv, "--instance", str(self.inst)])
        return code, out.getvalue(), err.getvalue()

    def test_cli(self):
        # The CLI reads how a provider is recognised from THIS checkout, so the
        # made-up providers are not known to it: point both roots at the fixture.
        real = clouds.HUB
        clouds.HUB = self.inst
        self.addCleanup(setattr, clouds, "HUB", real)
        code, out, _ = self.run_cli("json")
        self.assertEqual((code, json.loads(out)["summary"]["deployments"]), (0, 4))
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        for needle in ("PROVIDER", "acme/sites", "4 deployment(s) in 3 repo(s) on 2 of 2 provider(s)",
                       "2 on a provider the hub does not read", "NOT read: 2 (absent, listed)", "1 under another owner"):
            self.assertIn(needle, out)
        code, out, _ = self.run_cli("map", "--provider", "plat", "--repo", "blog")
        self.assertEqual(code, 0)
        self.assertIn("own/blog", out)
        self.assertNotIn("org/shop", out)
        self.assertEqual(self.run_cli("check")[0], 0, "findings are advisory")
        code, out, _ = self.run_cli("check", "--strict")
        self.assertEqual(code, 1)
        self.assertIn("stored-credential", out)
        write(self.inst, "_data/fleet.yml", "hub: {repo: own/hub}\nclouds: {providers: {}}\n")
        code, _, err = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn("dash cloud:", err)


class NeutralityTests(unittest.TestCase):
    """Cloud-agnostic is a property of the code: every vendor fact is data."""

    # Workflows are read from the CI platform's own directory, so its name is in the path.
    CI_PLATFORM = {"github"}

    def test_the_reader_names_no_provider(self):
        source = (HUB / "tools" / "fleetcore" / "clouds.py").read_text(encoding="utf-8").lower()
        block = yaml.safe_load((HUB / "_data" / "fleet.yml").read_text(encoding="utf-8"))["clouds"]
        words = set()
        for pid, prov in block["providers"].items():
            words |= {str(pid).lower()} | set(re.findall(r"[a-z]{3,}", str(prov.get("title") or "").lower()))
        for word in sorted(words - self.CI_PLATFORM - {"cloud"}):
            self.assertIsNone(re.search(rf"\b{re.escape(word)}\b", source),
                              f"tools/fleetcore/clouds.py names the provider '{word}': that fact belongs in _data/fleet.yml clouds:")

    def test_the_committed_fleet_builds_a_document(self):
        doc = clouds.status_doc(HUB, HUB)
        fleet = yaml.safe_load((HUB / "_data" / "fleet.yml").read_text(encoding="utf-8"))
        self.assertEqual(doc["hub"], fleet["hub"]["repo"])
        self.assertEqual([p["id"] for p in doc["providers"]], list(fleet["clouds"]["providers"]))
        self.assertIn(doc["hub"], {r["repo"] for r in doc["repos"]}, "the hub's own checkout is always read")


if __name__ == "__main__":
    unittest.main()
