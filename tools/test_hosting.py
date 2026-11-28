#!/usr/bin/env python3
"""Tests for the platform's hosting on Google Cloud (ADR 0020): _data/hosting.yml,
the OpenTofu modules under infra/gcp/ that read it, and their deploy script.
Offline: no cloud call, no OpenTofu (CI's infra.yml validates the HCL itself).
    python3 tools/test_hosting.py"""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from urllib.parse import urlsplit

import yaml

HUB = Path(__file__).resolve().parent.parent
HOSTING = HUB / "_data" / "hosting.yml"
GCP = HUB / "infra" / "gcp"
LABELS = ("project", "env", "managed-by", "source")


def load(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def problems(doc: dict) -> list[str]:
    """The rules of hosting/v1 as sentences; empty means the file may ship."""
    out = []
    node, services = doc.get("node") or {}, doc.get("services") or {}
    for key in ("enabled", "public"):
        if not isinstance(node.get(key), bool):
            out.append(f"node.{key} must be true or false")
    if node.get("public") and not node.get("enabled"):
        out.append("node.public needs node.enabled: there is no front door without a machine")
    if not re.fullmatch(r"([01]\d|2[0-3]):00", str((node.get("snapshots") or {}).get("daily_at"))):
        out.append("node.snapshots.daily_at must be a whole hour, HH:00 (the provider takes no other)")
    for name, svc in services.items():
        at = f"services.{name}"
        if not isinstance(svc.get("enabled"), bool):
            out.append(f"{at}.enabled must be true or false")
        for key in ("sign_in", "health"):
            if not str(svc.get(key) or "").startswith("/"):
                out.append(f"{at}.{key} must be a path on the service's own host")
        if not isinstance(svc.get("needs"), list):
            out.append(f"{at}.needs must be a list, empty once nothing is owed")
        if svc.get("enabled"):
            if svc.get("needs"):
                out.append(f"{at} is enabled while {len(svc['needs'])} thing(s) are still owed (its `needs`)")
            if not node.get("public"):
                out.append(f"{at} is enabled while node.public is false: the main site would offer a door that is shut")
    return out


class HostingFile(unittest.TestCase):
    def setUp(self):
        self.doc = load(HOSTING)

    def test_the_committed_file_keeps_its_rules(self):
        self.assertEqual(self.doc["schema"], "hosting/v1")
        self.assertEqual(problems(self.doc), [])

    def test_the_rules_catch_each_way_to_get_it_wrong(self):
        doc = load(HOSTING)
        doc["node"].update(enabled=False, public=True)
        doc["node"]["snapshots"]["daily_at"] = "09:37"
        svc = next(iter(doc["services"].values()))
        svc.update(enabled=True, sign_in="studio/", needs=["something"])
        text = " | ".join(problems(doc))
        for needle in ("node.public needs node.enabled", "must be a whole hour", "sign_in must be a path",
                       "is enabled while 1 thing(s) are still owed"):
            self.assertIn(needle, text)
        doc = load(HOSTING)
        next(iter(doc["services"].values())).update(enabled=True, needs=[])
        self.assertIn("is enabled while node.public is false", " | ".join(problems(doc)))
        doc["node"].update(enabled=True, public=True)
        self.assertEqual(problems(doc), [], "a machine that is up and open, and a service that owes nothing, may be offered")

    def test_it_names_things_the_other_registries_know(self):
        fleet = load(HUB / "_data" / "fleet.yml")
        self.assertIn(self.doc["provider"], fleet["clouds"]["providers"], "the provider is one _data/fleet.yml clouds: declares")
        names = {str(e["name"]) for e in load(HUB / "_data" / "projects.yml")}
        self.assertIn(self.doc["entry"]["repo"], names, "the main site is a registry repo")
        for name, svc in self.doc["services"].items():
            self.assertIn(svc["repo"], names, f"services.{name}.repo is a registry repo")

    def test_every_service_is_entered_on_the_main_sites_own_domain(self):
        site = urlsplit(self.doc["entry"]["url"])
        self.assertEqual(site.scheme, "https")
        domain = ".".join(site.hostname.split(".")[-2:])
        self.assertTrue(self.doc["entry"]["path"].startswith("/"))
        hosts = [svc["host"] for svc in self.doc["services"].values()]
        self.assertEqual(len(hosts), len(set(hosts)), "each service has its own host, so its cookies are its own")
        for host in hosts:
            self.assertTrue(host.endswith("." + domain), f"{host} is a host of {domain}")
            self.assertNotEqual(host, site.hostname, "a service never shares the main site's host")


class NoIdentifierInTheRepo(unittest.TestCase):
    """`_data/` is public site data, and so is the rest of the tree (ADR 0018, decision 8)."""

    def files(self):
        return [HOSTING, *sorted(p for p in GCP.rglob("*") if p.is_file())]

    def test_no_address_and_no_project_number(self):
        allowed = {"0.0.0.0/0", "35.235.240.0/20", "10.10.0.0/24"}  # the internet, the provider's tunnel, the private subnet
        for path in self.files():
            text = path.read_text(encoding="utf-8")
            for hit in re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?\b", text):
                self.assertIn(hit, allowed, f"{path.relative_to(HUB)} holds the address {hit}")
            self.assertIsNone(re.search(r"\bprojects/\d{6,}\b", text), f"{path.relative_to(HUB)} holds a project number")
            self.assertIsNone(re.search(r"\b[0-9A-F]{6}-[0-9A-F]{6}-[0-9A-F]{6}\b", text),
                              f"{path.relative_to(HUB)} holds a billing account id")

    def test_the_project_comes_from_the_environment(self):
        for module in ("foundation", "node"):
            text = (GCP / module / "versions.tf").read_text(encoding="utf-8")
            self.assertIn("project = var.project_id", text)
            self.assertNotIn("default", (GCP / module / "variables.tf").read_text(encoding="utf-8").split('variable "env"')[0],
                             f"infra/gcp/{module}: project_id has no default")
        self.assertIn('export TF_VAR_project_id="$GCP_PROJECT_ID"', (GCP / "deploy.sh").read_text(encoding="utf-8"))


class Modules(unittest.TestCase):
    def text(self, module: str) -> str:
        return (GCP / module / "main.tf").read_text(encoding="utf-8")

    def test_each_module_reads_the_one_file(self):
        for module in ("foundation", "node"):
            self.assertIn('yamldecode(file("${path.module}/../../../_data/hosting.yml"))', self.text(module))

    def test_every_resource_carries_the_four_labels(self):
        for module in ("foundation", "node"):
            block = re.search(r"\n  labels = \{\n(.*?)\n  \}", self.text(module), re.S)
            self.assertIsNotNone(block, f"infra/gcp/{module} declares its labels once")
            keys = re.findall(r"^\s+([a-z-]+)\s+=", block.group(1), re.M)
            self.assertEqual(tuple(keys), LABELS, f"infra/gcp/{module}: the four labels of ADR 0018, in order")
            source = re.search(r'source\s+= "([^"]+)"', block.group(1)).group(1)
            self.assertRegex(source, r"^[a-z0-9_-]{1,63}$", "a label value the provider accepts")
            self.assertEqual(source, f"bamr87_bamr87--infra_gcp_{module}")

    def test_the_machine_is_created_only_behind_its_switch(self):
        text = self.text("node")
        resources = re.findall(r'\nresource "([a-z_]+)" "([a-z_]+)" \{\n(.*?)\n\}\n', text + "\n", re.S)
        self.assertGreaterEqual(len(resources), 10)
        for kind, name, body in resources:
            head = body.split("\n\n")[0]
            self.assertRegex(head, r"^\s+(count|for_each) = local\.(create|public) \?",
                             f"{kind}.{name} is gated by node.enabled (or node.public) on its first line")

    def test_ssh_comes_only_from_the_tunnel_and_the_front_door_has_its_own_switch(self):
        text = self.text("node")
        rules = dict((name, body) for _, name, body in
                     re.findall(r'\nresource "(google_compute_firewall)" "([a-z_]+)" \{\n(.*?)\n\}\n', text, re.S))
        self.assertEqual(set(rules), {"ssh_from_tunnel", "web"}, "two ways in, and no third")
        self.assertIn("source_ranges = [local.tunnel_range]", rules["ssh_from_tunnel"])
        self.assertIn('ports    = ["22"]', rules["ssh_from_tunnel"])
        self.assertIn("count = local.public ? 1 : 0", rules["web"])
        self.assertIn('ports    = ["80", "443"]', rules["web"])
        self.assertEqual(text.count('"0.0.0.0/0"'), 1, "the internet is named once, in the front door's rule")
        self.assertIsNone(re.search(r"^\s+ssh-keys\s+=", text, re.M), "no SSH key is written into the machine's metadata")
        self.assertIn('enable-oslogin         = "TRUE"', text)

    def test_what_holds_data_cannot_be_planned_away(self):
        text = self.text("node")
        for kind, name in (("google_compute_disk", "data"), ("google_storage_bucket", "backups")):
            body = re.search(rf'\nresource "{kind}" "{name}" \{{\n(.*?)\n\}}\n', text, re.S).group(1)
            self.assertIn("prevent_destroy = true", body, f"{kind}.{name}")
        self.assertIn("deletion_protection       = true", text)
        self.assertNotIn("objectAdmin", text, "the node may add and read a backup, never delete one")

    def test_no_key_is_created_and_a_deploy_identity_starts_with_no_role(self):
        for module in ("foundation", "node"):
            self.assertNotIn("google_service_account_key", self.text(module))
        text = self.text("foundation")
        self.assertIn('issuer_uri = "https://token.actions.githubusercontent.com"', text)
        self.assertIn("attribute_condition = local.trust_condition", text)
        self.assertNotIn("google_project_iam_member", text, "the landing zone grants a deploy identity nothing")


class DeployScript(unittest.TestCase):
    def setUp(self):
        self.text = (GCP / "deploy.sh").read_text(encoding="utf-8")

    def test_it_plans_unless_told_to_apply(self):
        self.assertIn("APPLY=0", self.text)
        before, after = self.text.split('if [[ "$APPLY" -eq 1 ]]; then', 1)
        self.assertNotRegex(before, r'"\$TOOL"[^\n]* apply\b', "nothing applies before the --apply branch")
        apply_branch, plan_branch = after.split("\nfi\n", 1)
        self.assertIn('apply -input=false "$PLAN"', apply_branch, "it applies the saved plan, never a fresh one")
        self.assertIn("-newer \"$PLAN\"", apply_branch, "a change after the plan needs a new plan")
        self.assertNotRegex(plan_branch, r'"\$TOOL"[^\n]* apply\b')
        self.assertIn('plan -input=false -out="$PLAN"', plan_branch)

    def test_state_lives_outside_the_checkout(self):
        self.assertIn('STATE_DIR="${FLEET_INFRA_STATE:-$HOME/.local/state/bamr87-infra}"', self.text)
        self.assertIn('-backend-config="path=$STATE"', self.text)
        for module in ("foundation", "node"):
            self.assertIn('backend "local" {}', (GCP / module / "versions.tf").read_text(encoding="utf-8"))

    def test_ci_validates_the_modules_and_holds_no_credential(self):
        workflow = (HUB / ".github" / "workflows" / "infra.yml").read_text(encoding="utf-8")
        self.assertIn("for dir in infra/*/ infra/*/*/; do", workflow, "the root modules one level down are validated too")
        self.assertNotIn("google-github-actions/auth", workflow)
        self.assertNotIn("id-token: write", workflow)


if __name__ == "__main__":
    unittest.main()
