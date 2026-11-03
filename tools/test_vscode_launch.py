#!/usr/bin/env python3
# ============================================================================
# File:          tools/test_vscode_launch.py
# Description:   The editor-is-a-front-door gate (constitution § 20): .vscode/
#                parses, every task / input / compound member resolves, each
#                picker equals its registry, every port an entry names is one
#                the plane it talks to publishes, and no entry bypasses
#                tools/dash. Plus fixture tests for conformance.py UPS-REPO-40.
# Author:        bamr87
# Created:       2026-11-02
# Last Modified: 2026-11-02
# Version:       1.0.0
# Usage:         python3 tools/test_vscode_launch.py          (PyYAML only)
#                run by tools/run-all-tests.sh
# ============================================================================
"""Why a test and not a review: .vscode/launch.json had drifted for weeks —
entries for six retired repositories, ports devenv no longer published, a
second hub compose project that collided with the running one — and nothing
noticed, because nothing held the file to the registries it quotes. Each
test here is one of those failures, made impossible."""
from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
VSCODE = ROOT / ".vscode"
PORT_IN_NAME = re.compile(r":(\d{4,5})\b")
INPUT_REF = re.compile(r"\$\{input:([A-Za-z0-9_]+)\}")
ENV_PREFIX = re.compile(r"^(?:[A-Z_][A-Z0-9_]*=\S*\s+)+")

# What an editor entry may call (constitution § 20.1): the router, a tool's own
# entry point, or compose against the hub's own services. A picker of gates
# is allowed as a whole because each of its options is checked on its own.
LAUNCH_FRONT_DOORS = (
    "tools/dash", "tools/dash-gen", "tools/check-drift.sh", "tools/console/build-pages.sh",
    "docker compose", ".venv-console/bin/python", "python3 ", "for ", "${input:gateCommand}",
)
TASK_FRONT_DOORS = (
    "tools/", "docker ", "python3 ", ".venv-console/bin/python", "npx ", "npm ",
    "shellcheck ", "actionlint ", "test ", "[ ", "for ",
)
GATE_FRONT_DOORS = ("tools/", "python3 ", "shellcheck ", "actionlint ")
# What an entry may never do beside the running `fleet` core (.vscode/README.md "Ports").
FORBIDDEN = ("fleet-dev.sh", "dev up hub", "dev up --all", "dev down --all")


def jsonc(path: Path) -> dict:
    """VS Code's JSONC: line comments and trailing commas are fine."""
    text = re.sub(r"^\s*//.*$", "", path.read_text(encoding="utf-8"), flags=re.M)
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    return json.loads(text)


def load_yaml(rel: str):
    return yaml.safe_load((ROOT / rel).read_text(encoding="utf-8")) or {}


LAUNCH = jsonc(VSCODE / "launch.json")
TASKS = jsonc(VSCODE / "tasks.json")
SETTINGS = jsonc(VSCODE / "settings.json")
EXTENSIONS = jsonc(VSCODE / "extensions.json")
README = (VSCODE / "README.md").read_text(encoding="utf-8")
PORTS = load_yaml("_data/ports.yml")
FLEET = load_yaml("_data/fleet.yml")
COMPOSE = load_yaml("docker-compose.yml")

CONFIGS = LAUNCH.get("configurations") or []
TASK_LABELS = {t.get("label") for t in TASKS.get("tasks") or []}


def inputs(doc: dict) -> dict[str, dict]:
    return {i["id"]: i for i in doc.get("inputs") or []}


def commands() -> list[tuple[str, str]]:
    """(name, command) for every node-terminal entry."""
    return [(c["name"], c["command"]) for c in CONFIGS if c.get("type") == "node-terminal"]


def host_ports(mapping: str) -> set[int]:
    """Host ports a compose `ports:` string publishes: `127.0.0.1:${X:-4000}:4000`,
    `127.0.0.1:4040-4049:4040-4049`, `8080:8080`. The default of a variable is
    what the hub binds without a .env."""
    # `${VAR:-default}` carries a colon of its own, so this is a regex, not a split.
    m = re.match(r"^(?:[\d.]+:)?(?P<host>\$\{[A-Z0-9_]+:-\d+\}|\d+(?:-\d+)?):(?P<cont>\d+(?:-\d+)?)(?:/(?:tcp|udp))?$", mapping)
    if not m:
        return set()
    host = m.group("host")
    v = re.match(r"\$\{[A-Z0-9_]+:-(\d+)\}$", host)
    if v:
        return {int(v.group(1))}
    if "-" in host:
        lo, hi = (int(x) for x in host.split("-"))
        return set(range(lo, hi + 1))
    return {int(host)}


def service_ports(service: str) -> set[int]:
    out: set[int] = set()
    for p in (COMPOSE["services"].get(service) or {}).get("ports") or []:
        out |= host_ports(str(p))
    return out


def compose_hosted() -> set[str]:
    return {n for n, s in (PORTS.get("projects") or {}).items() if (s or {}).get("host") == "compose"}


def allocations(project: str) -> set[int]:
    spec = (PORTS.get("projects") or {}).get(project) or {}
    out = {a["port"] for a in (spec.get("services") or {}).values()}
    out |= {a["port"] for a in (spec.get("debug") or {}).values()}
    out |= {a["livereload"] for a in (spec.get("services") or {}).values() if a.get("livereload")}
    return out


def debug_allocations() -> set[int]:
    return {a["port"] for s in (PORTS.get("projects") or {}).values() for a in ((s or {}).get("debug") or {}).values()}


def gitmodule_dirs() -> set[str]:
    text = (ROOT / ".gitmodules").read_text(encoding="utf-8")
    return {m.group(1).rsplit("/", 1)[-1] for m in re.finditer(r"^\s*path\s*=\s*(\S+)", text, flags=re.M)}


def content_sites() -> set[str]:
    sites = (FLEET.get("content") or {}).get("sites") or {}
    if isinstance(sites, dict):
        return set(sites)
    return {s.get("id") or s.get("name") for s in sites}


class Files(unittest.TestCase):
    """The four tracked files, and only what .gitignore tracks."""

    def test_launch_tasks_settings_extensions_parse(self):
        self.assertTrue(CONFIGS, "launch.json has no configurations")
        self.assertTrue(TASK_LABELS, "tasks.json has no tasks")
        self.assertIn("recommendations", EXTENSIONS)
        self.assertIn("git.detectSubmodulesLimit", SETTINGS)

    def test_tracked_set_matches_gitignore(self):
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for name in ("README.md", "SCHEMA.md", "extensions.json", "launch.json", "settings.json", "tasks.json"):
            self.assertIn(f"!.vscode/{name}", ignore, f".gitignore does not re-allow .vscode/{name}")

    def test_no_personal_preferences_in_settings(self):
        # home.code-workspace says these stay there, not in each repo's settings.json.
        for key in ("editor.fontSize", "editor.lineHeight", "files.autoSave", "editor.minimap.enabled"):
            self.assertNotIn(key, SETTINGS, f"{key} is a personal preference (home.code-workspace)")


class References(unittest.TestCase):
    """Everything an entry names exists."""

    def test_every_prelaunch_and_postdebug_task_exists(self):
        for c in CONFIGS:
            for key in ("preLaunchTask", "postDebugTask"):
                if c.get(key):
                    self.assertIn(c[key], TASK_LABELS, f"{c['name']}: {key} {c[key]!r} is not a task label")

    def test_every_task_dependency_exists(self):
        for t in TASKS.get("tasks") or []:
            deps = t.get("dependsOn") or []
            for d in ([deps] if isinstance(deps, str) else deps):
                self.assertIn(d, TASK_LABELS, f"task {t.get('label')!r} dependsOn {d!r}, which does not exist")

    def test_compound_members_exist(self):
        names = {c["name"] for c in CONFIGS}
        for comp in LAUNCH.get("compounds") or []:
            for member in comp["configurations"]:
                self.assertIn(member, names, f"compound {comp['name']!r} names {member!r}")

    def test_inputs_are_defined_and_used(self):
        for label, doc, path in (("launch", LAUNCH, VSCODE / "launch.json"), ("tasks", TASKS, VSCODE / "tasks.json")):
            defined = set(inputs(doc))
            used = set(INPUT_REF.findall(path.read_text(encoding="utf-8")))
            self.assertEqual(used - defined, set(), f"{label}.json uses undefined inputs")
            self.assertEqual(defined - used, set(), f"{label}.json defines unused inputs")

    def test_names_are_unique(self):
        names = [c["name"] for c in CONFIGS]
        self.assertEqual(len(names), len(set(names)), "duplicate configuration names")


class Pickers(unittest.TestCase):
    """§ 20.2 — a picker equals its registry."""

    def test_fleet_project_picker_equals_ports_registry(self):
        picker = inputs(LAUNCH)["fleetProject"]
        self.assertEqual(set(picker["options"]), compose_hosted(), "fleetProject ≠ _data/ports.yml compose-hosted projects")
        self.assertIn(picker["default"], picker["options"])
        several = inputs(LAUNCH)["fleetProjects"]["default"].split()
        self.assertTrue(set(several) <= compose_hosted(), f"fleetProjects default {several} names a non-registry project")

    def test_submodule_pickers_equal_gitmodules(self):
        want = gitmodule_dirs()
        for label, doc in (("launch", LAUNCH), ("tasks", TASKS)):
            got = set(inputs(doc)["submodule"]["options"])
            self.assertEqual(got, want, f"{label}.json submodule picker ≠ .gitmodules")

    def test_content_site_picker_equals_fleet_yml(self):
        self.assertEqual(set(inputs(LAUNCH)["contentSite"]["options"]), content_sites())

    def test_verify_scenario_picker_equals_scenarios_dir(self):
        want = {p.stem for p in (ROOT / "verify" / "scenarios").glob("*.yml")}
        self.assertEqual(set(inputs(LAUNCH)["verifyScenario"]["options"]), want)

    def test_hub_profile_picker_is_a_subset_of_compose_profiles(self):
        declared = {p for s in COMPOSE["services"].values() for p in (s.get("profiles") or [])}
        self.assertTrue(set(inputs(LAUNCH)["hubProfile"]["options"]) <= declared,
                        f"hubProfile names a profile docker-compose.yml does not declare: {set(inputs(LAUNCH)['hubProfile']['options']) - declared}")

    def test_hub_port_picker_is_published_by_the_hub(self):
        hub = set()
        for s in COMPOSE["services"]:
            hub |= service_ports(s)
        hub |= {4004, 5173}  # the native debug console and the page's dev server (.vscode/README.md "Ports")
        for opt in inputs(LAUNCH)["portNumber"]["options"]:
            self.assertIn(int(opt), hub, f"portNumber offers {opt}, which nothing of the hub's publishes")

    def test_gate_picker_options_are_front_doors(self):
        for opt in inputs(LAUNCH)["gateCommand"]["options"]:
            self.assertTrue(opt.startswith(GATE_FRONT_DOORS), f"gate option {opt!r} is not a hub tool")


class Ports(unittest.TestCase):
    """§ 20.2 — a port in an entry's name is one its plane publishes."""

    def test_workspace_entries_use_ports_devenv_publishes(self):
        devenv = service_ports("devenv")
        for name, cmd in commands():
            if "exec" in cmd and "devenv" in cmd:
                for port in map(int, PORT_IN_NAME.findall(name)):
                    self.assertIn(port, devenv, f"{name}: devenv does not publish {port} (docker-compose.yml devenv ports)")

    def test_dev_entries_use_ports_yml_allocations(self):
        for name, cmd in commands():
            m = re.search(r"tools/dash dev up ([a-z0-9.-]+)", cmd)
            if not m or m.group(1).startswith("$"):
                continue
            allowed = allocations(m.group(1))
            for port in map(int, PORT_IN_NAME.findall(name)):
                self.assertIn(port, allowed, f"{name}: {port} is not an _data/ports.yml allocation of {m.group(1)}")

    def test_attach_ports_are_debug_allocations_and_in_the_name(self):
        for c in CONFIGS:
            if c.get("type") == "debugpy" and c.get("request") == "attach":
                port = (c.get("connect") or {}).get("port")
                self.assertIn(port, debug_allocations(), f"{c['name']}: {port} is not a debug: allocation in _data/ports.yml")
                self.assertIn(f":{port}", c["name"], f"{c['name']}: carry the port in the name for the /docker/ page")

    def test_native_debug_ports_never_collide_with_the_core(self):
        hub = set()
        for s in COMPOSE["services"]:
            hub |= service_ports(s)
        for c in CONFIGS:
            if c.get("type") == "debugpy" and c.get("request") == "launch" and "--port" in (c.get("args") or []):
                port = int(c["args"][c["args"].index("--port") + 1])
                self.assertNotIn(port, hub, f"{c['name']}: {port} is a port the compose core publishes")


class FrontDoor(unittest.TestCase):
    """§ 20.1 — entries call tools/dash or a tool's own entry point, and never
    start a second hub project beside the running core."""

    def test_launch_commands_go_through_the_front_door(self):
        for name, cmd in commands():
            head = ENV_PREFIX.sub("", cmd.strip())
            self.assertTrue(head.startswith(LAUNCH_FRONT_DOORS), f"{name}: {cmd!r} does not start with a front door")

    def test_task_commands_go_through_the_front_door(self):
        for t in TASKS.get("tasks") or []:
            if t.get("type") != "shell":
                continue
            head = ENV_PREFIX.sub("", str(t.get("command", "")).strip())
            self.assertTrue(head.startswith(TASK_FRONT_DOORS), f"task {t.get('label')!r}: {head!r} does not start with a front door")

    def test_nothing_bypasses_dash_or_starts_fleet_hub(self):
        texts = [cmd for _, cmd in commands()] + [str(t.get("command", "")) for t in TASKS.get("tasks") or []]
        texts += [str(t.get("args", "")) for t in TASKS.get("tasks") or []]
        for text in texts:
            for bad in FORBIDDEN:
                self.assertNotIn(bad, text, f"{text!r} contains {bad!r} (.vscode/README.md 'Ports': never beside the running core)")


class Readme(unittest.TestCase):
    """§ 20.3 — README-Last applies to .vscode/."""

    def test_readme_lists_every_group(self):
        groups = {c.get("presentation", {}).get("group") for c in CONFIGS if c.get("presentation", {}).get("group")}
        listed = set(re.findall(r"\*\*(\d+-[a-z]+)\*\*", README))
        self.assertEqual(groups - listed, set(), "launch.json groups missing from .vscode/README.md")

    def test_readme_names_every_picker(self):
        for pid in inputs(LAUNCH):
            if pid in ("downScope", "configKey", "dashCommand", "indexQuery", "workflowId", "evidenceRepo",
                       "evidenceIssue", "unittestCase", "devenvCommand", "npmScript", "lakeDays", "workflowKind",
                       "portNumber", "fleetProjects"):
                continue  # free-text or self-explanatory pickers
            self.assertIn(f"`{pid}`", README, f"README 'Inputs' does not name the picker {pid}")


class ConformanceVscode(unittest.TestCase):
    """conformance.py UPS-REPO-40 — the fleet half of § 20."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / "tools"))
        import conformance  # noqa: E402
        cls.c = conformance

    def _repo(self, files: dict[str, str]):
        d = Path(tempfile.mkdtemp(prefix="ups-repo-40-"))
        for rel, text in files.items():
            p = d / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        return self.c.Repo(d, ROOT)

    def _check(self, files):
        return self.c.CHECKS["UPS-REPO-40"](self._repo(files), ["app"])

    def test_missing_launch_fails(self):
        ok, detail = self._check({"README.md": "# x\n"})
        self.assertFalse(ok); self.assertIn("launch.json", detail)

    def test_jsonc_with_resolving_tasks_passes(self):
        ok, detail = self._check({
            ".vscode/launch.json": '{\n  // a comment\n  "version": "0.2.0",\n  "configurations": [\n    {"name": "dev", "type": "node-terminal", "request": "launch", "command": "npm run dev", "preLaunchTask": "up"},\n  ]\n}\n',
            ".vscode/tasks.json": '{"version": "2.0.0", "tasks": [{"label": "up", "type": "shell", "command": "docker compose up -d"}]}',
        })
        self.assertTrue(ok, detail); self.assertIn("1 configuration", detail)

    def test_dangling_prelaunch_task_fails(self):
        ok, detail = self._check({
            ".vscode/launch.json": '{"configurations": [{"name": "dev", "preLaunchTask": "up"}]}',
            ".vscode/tasks.json": '{"tasks": [{"label": "other"}]}',
        })
        self.assertFalse(ok); self.assertIn("up", detail)

    def test_unparseable_launch_fails(self):
        ok, detail = self._check({".vscode/launch.json": "{ not json"})
        self.assertFalse(ok); self.assertIn("parse", detail)

    def test_hub_itself_passes(self):
        ok, detail = self.c.CHECKS["UPS-REPO-40"](self.c.Repo(ROOT, ROOT), ["app"])
        self.assertTrue(ok, detail)


if __name__ == "__main__":
    unittest.main(verbosity=1)
