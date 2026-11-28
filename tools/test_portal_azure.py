#!/usr/bin/env python3
# ============================================================================
# File:          tools/test_portal_azure.py
# Description:   The bash-365 portal's Azure deployment (infra/azure/portal/)
#                agrees with itself and with the hub: the Bicep and its
#                parameters, the address in _data/profile.yml, the headers the
#                build ships, the workflow job that deploys it, the scripts the
#                maintainer runs, and its kill switch.
# Created:       2026-11-26
# Usage:         python3 tools/test_portal_azure.py          (PyYAML only)
#                run by tools/run-all-tests.sh
# ============================================================================
"""Offline: nothing here reaches Azure or GitHub. infra.yml compiles the Bicep."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from urllib.parse import urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[1]
PORTAL = ROOT / "infra" / "azure" / "portal"
WORKFLOW = ROOT / ".github" / "workflows" / "build-dash.yml"
INFRA_WORKFLOW = ROOT / ".github" / "workflows" / "infra.yml"


def bicep_params(path: Path) -> dict[str, bool]:
    """name → has a default, for each `param` line of a Bicep file."""
    out = {}
    for m in re.finditer(r"^param\s+(\w+)\s+\w+(\s*=)?", path.read_text(), re.M):
        out[m.group(1)] = bool(m.group(2))
    return out


def parameters() -> dict:
    return {k: v["value"] for k, v in json.loads((PORTAL / "parameters.json").read_text())["parameters"].items()}


def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def portal_site() -> tuple[str, dict]:
    """The site key the workflow builds, and that site's settings."""
    build = workflow()["jobs"]["build"]["steps"]
    step = next(s for s in build if s.get("name") == "Build the bash-365 site build")
    key = step["env"]["CONSOLE_SITE"]
    sites = yaml.safe_load((ROOT / "_data" / "profile.yml").read_text()).get("sites") or {}
    return key, sites.get(key) or {}


class Bicep(unittest.TestCase):
    def test_parameters_name_only_declared_params_and_every_required_one(self):
        declared = bicep_params(PORTAL / "main.bicep")
        given = set(parameters())
        self.assertEqual(given - set(declared), set(), "parameters.json names a param main.bicep does not declare")
        required = {n for n, has_default in declared.items() if not has_default}
        self.assertEqual(required - given, set(), "a param without a default is missing from parameters.json")

    def test_the_module_takes_every_param_main_passes(self):
        module = bicep_params(PORTAL / "portal.bicep")
        passed = re.search(r"module portal 'portal\.bicep'.*?params: \{(.*?)\n  \}", (PORTAL / "main.bicep").read_text(), re.S).group(1)
        self.assertEqual(set(re.findall(r"^\s+(\w+):", passed, re.M)), set(module))

    def test_the_deploy_role_is_scoped_to_the_app(self):
        text = (PORTAL / "portal.bicep").read_text()
        role = text[text.index("resource deployer"):]
        self.assertIn("scope: swa", role, "the deploy identity's role must sit on the Static Web App, not wider")
        self.assertNotIn("targetScope", text)

    def test_the_app_is_not_linked_to_a_repository(self):
        text = (PORTAL / "portal.bicep").read_text()
        self.assertIn("provider: 'None'", text)
        self.assertNotRegex(text, r"repositoryUrl|repositoryToken|branch:")


class Address(unittest.TestCase):
    def test_the_custom_domain_is_empty_or_the_sites_own_host(self):
        _, site = portal_site()
        domain = parameters()["customDomain"]
        if domain:
            self.assertEqual(domain, urlsplit(site["url"]).hostname, "customDomain ≠ the host of _data/profile.yml sites.<key>.url")

    def test_the_workflow_builds_a_declared_site(self):
        key, site = portal_site()
        self.assertTrue(site, f"build-dash.yml builds CONSOLE_SITE={key}, which _data/profile.yml does not declare")
        self.assertTrue(urlsplit(site["url"]).hostname, "the site needs an address with a host to serve at")


class SiteConfig(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads((PORTAL / "staticwebapp.config.json").read_text())

    def test_unknown_addresses_answer_404_with_the_apps_page(self):
        self.assertEqual(self.cfg["responseOverrides"]["404"], {"rewrite": "/404.html"})
        self.assertNotIn("navigationFallback", self.cfg, "a fallback would answer 200 for addresses that do not exist")

    def test_only_the_portal_frames_its_pages(self):
        self.assertEqual(self.cfg["globalHeaders"]["Content-Security-Policy"], "frame-ancestors 'self'")
        self.assertEqual(self.cfg["globalHeaders"]["X-Content-Type-Options"], "nosniff")

    def test_no_route_claims_an_azure_reserved_path(self):
        for r in self.cfg.get("routes") or []:
            self.assertFalse(r["route"].startswith(("/api", "/.auth")), r["route"])


class Workflow(unittest.TestCase):
    def setUp(self):
        self.wf = workflow()
        self.job = self.wf["jobs"]["deploy-portal"]
        self.text = WORKFLOW.read_text()

    def test_deploys_only_from_main_and_only_when_switched_on(self):
        cond = self.job["if"]
        self.assertIn("github.event_name != 'pull_request'", cond)
        self.assertIn("vars.PORTAL_DEPLOY_ENABLED == 'true'", cond)
        upload = next(s for s in self.wf["jobs"]["build"]["steps"] if s.get("name") == "Upload the bash-365 build")
        self.assertEqual(upload["if"], cond, "the artifact is uploaded exactly when it is deployed")

    def test_oidc_only_in_the_deploy_jobs(self):
        self.assertEqual(self.wf["permissions"], {"contents": "read"})
        self.assertEqual(self.job["permissions"], {"contents": "read", "id-token": "write"})
        self.assertNotRegex(self.text, r"secrets\.(AZURE|PORTAL)", "the portal deploy stores no Azure secret")

    def test_the_environment_is_the_one_the_credential_trusts(self):
        boot = (PORTAL / "bootstrap.sh").read_text()
        self.assertIn(f'PORTAL_ENVIRONMENT:-{self.job["environment"]["name"]}', boot)

    def test_the_token_is_masked_and_names_come_from_parameters(self):
        run = next(s["run"] for s in self.job["steps"] if s.get("id") == "deploy")
        self.assertIn('echo "::add-mask::$token"', run)
        self.assertEqual(len(re.findall(r"\$token", run)), 2, "the token is masked, then handed to the CLI, and used nowhere else")
        p = parameters()
        for name in (p["resourceGroupName"], p["staticWebAppName"]):
            self.assertNotIn(name, self.text, "the workflow reads names from parameters.json; a literal here can drift")
        self.assertIn("infra/azure/portal/parameters.json", run)

    def test_its_switch_is_registered(self):
        loops = yaml.safe_load((ROOT / "_data" / "fleet.yml").read_text())["switches"]["loops"]
        entry = loops["hub/bash-365-portal"]
        self.assertEqual(entry["workflow"], ".github/workflows/build-dash.yml")
        self.assertEqual((entry["gate"]["name"], entry["gate"]["semantics"], entry["default"]), ("PORTAL_DEPLOY_ENABLED", "opt_in", "off"))


class Scripts(unittest.TestCase):
    def test_every_script_previews_unless_told_to_apply(self):
        for name in ("bootstrap.sh", "deploy.sh"):
            with self.subTest(script=name):
                text = (PORTAL / name).read_text()
                self.assertIn("APPLY=0", text)
                self.assertRegex(text, r'if \[\[ "\$APPLY" != 1 \]\]; then')
                self.assertNotRegex(text, r"credential reset|--password|client-secret", "no client secret is ever made")

    def test_infra_workflow_builds_bicep_and_keeps_opentofu_off_it(self):
        text = INFRA_WORKFLOW.read_text()
        self.assertIn('compgen -G "${dir}*.tf" >/dev/null || continue', text)
        self.assertIn("az bicep build --file", text)
        self.assertNotIn("azure/login", text, "CI compiles the Bicep and never deploys it")


if __name__ == "__main__":
    unittest.main(verbosity=1)
