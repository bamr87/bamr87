#!/usr/bin/env python3
"""Tests for tools/fleetcore/aimodels.py — which model each kind of AI work runs on,
every place that is written, and what a switch would take (ADR 0019) — and for the
row tools/evals.py records as proof of a run.
Offline, no model call, no pytest:  python3 tools/test_fleetcore_aimodels.py"""
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
import evals  # noqa: E402
from fleetcore import aimodels  # noqa: E402

HUB = Path(__file__).resolve().parent.parent

# Made-up providers and models: the reader must work from the settings alone.
BLOCK = {
    "allowed": {"acme": ["acme-big-1", "acme-small-1"], "plat": ["plat-mid-2"]},
    "classes": {"deep": "acme-big-1", "fast": "acme-small-1"},
    "evals": {"intake": {"agents": ["ci:hub:intake"], "covers": "step 1 of 3"}, "review": {"agents": ["ci:hub:review"]}},
    "scan": {"tables": [".github/scripts/prices.py"]},
}
MODEL = aimodels.normalize(BLOCK)


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def instance(root: Path, block: dict | None = None, settings: dict | None = None, agents: list | None = None) -> Path:
    """A control plane holding only what the reader needs."""
    write(root, "_data/fleet.yml", yaml.safe_dump({
        "hub": {"repo": "own/hub", "owners": ["own"]}, "ai_models": copy.deepcopy(block or BLOCK), **(settings or {})}))
    write(root, "_data/projects.yml", yaml.safe_dump([
        {"name": "site", "submodule_path": "projects/site", "repo_url": "https://github.com/own/site"},
        {"name": "mirror", "submodule_path": "projects/mirror", "repo_url": "https://github.com/someone/mirror"}]))
    write(root, "_data/agents.yml", yaml.safe_dump({"schema": "agents/v1", "agents": agents if agents is not None else [
        {"id": "ci:hub:intake", "repo": "own/hub", "kind": "ci-event", "model": "acme-big-1"},
        {"id": "ci:hub:review", "repo": "own/hub", "kind": "ci-event", "model": "acme-big-1"},
        {"id": "ci:site:helper", "repo": "own/site", "kind": "ci-mention", "model": "acme-small-1"},
        {"id": "loop:hub:both", "repo": "own/hub", "kind": "loop-step", "model": ["acme-big-1", "acme-small-1"]},
        {"id": "local:hub:sync", "repo": "own/hub", "kind": "local-job", "model": "none"},
        {"id": "ci:hub:unset", "repo": "own/hub", "kind": "ci-event", "model": None}]}))
    for name in ("site", "mirror"):
        write(root, f"projects/{name}/.git", "gitdir: x\n")
    return root


def eval_set(root: Path, role: str, mode: str = "model", pin: str | None = "acme-big-1", cases: int = 3) -> Path:
    return write(root, f"evals/{role}/cases.yml", yaml.safe_dump({
        "schema": "evals/v1", "role": role, "mode": mode, **({"model": pin} if pin else {}),
        "cases": [{"id": f"c{i}"} for i in range(cases)]}))


def runs_file(root: Path, rows: list[dict]) -> None:
    write(root, "_data/eval_runs.yml", yaml.safe_dump({"schema": "eval-runs/v1", "runs": rows}))


class ModelTests(unittest.TestCase):
    def test_the_committed_settings_read_and_every_class_is_an_allowed_model(self):
        model = aimodels.load_model(HUB, HUB)
        self.assertTrue(model["classes"], "at least one class of work is bound")
        for name, mid in model["classes"].items():
            self.assertIn(mid, model["provider_of"], f"class {name} is bound to a model ai_models.allowed lists")

    def test_settings_that_cannot_be_read_say_every_reason(self):
        bad = {"allowed": {"acme": ["m1", "shared"], "plat": ["shared"], "broken": "m9"},
               "classes": {"Deep": "m1", "fast": "not-allowed"}, "evals": {"intake": {}}, "scan": []}
        text = " | ".join(aimodels.model_problems(bad))
        for needle in ("shared is listed under acme and plat", "ai_models.allowed.broken must be a list",
                       "ai_models.classes.Deep: a class name is", "'not-allowed' is not in ai_models.allowed",
                       "ai_models.evals.intake needs `agents`", "`ai_models.scan` must be a mapping"):
            self.assertIn(needle, text)
        self.assertEqual(aimodels.model_problems(BLOCK), [])
        self.assertEqual(aimodels.model_problems({"allowed": {"acme": ["m1"]}}),
                         ["`ai_models.classes` must bind at least one class of work to a model"])
        self.assertEqual(aimodels.model_problems(None), ["`ai_models:` must be a mapping"])

    def test_a_model_has_one_provider_and_a_class(self):
        self.assertEqual(aimodels.provider_of(MODEL, "plat-mid-2"), "plat")
        self.assertIsNone(aimodels.provider_of(MODEL, "never-heard-of-it"))
        self.assertEqual(aimodels.classes_of(MODEL, "acme-big-1"), ["deep"])
        self.assertEqual(aimodels.classes_of(MODEL, "plat-mid-2"), [])

    def test_an_instance_lays_its_settings_over_the_frameworks(self):
        with tempfile.TemporaryDirectory() as tmp:
            fw, inst = instance(Path(tmp) / "fw"), Path(tmp) / "inst"
            write(inst, "_data/fleet.yml", yaml.safe_dump({"ai_models": {"classes": {"fast": "plat-mid-2"}}}))
            model = aimodels.load_model(inst, fw)
            self.assertEqual(model["classes"], {"deep": "acme-big-1", "fast": "plat-mid-2"})
            with self.assertRaises(aimodels.ModelError):
                aimodels.load_model(inst, inst)


class BindingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = instance(Path(self._tmp.name), settings={
            "weekly": {"agent": {"model": "acme-big-1"}}, "tiers": [{"model": "acme-small-1"}], "note": "acme-big-1 in prose"})

    def found(self):
        rows, unlisted, read = aimodels.bindings(self.root, MODEL)
        return rows, unlisted, read

    def by(self, kind):
        return [(b["file"], b.get("line") or b.get("key"), b["model"]) for b in self.found()[0] if b["class"] == kind]

    def test_a_setting_is_a_key_outside_the_ai_models_block(self):
        self.assertEqual(sorted((b["key"], b["model"]) for b in self.found()[0] if b["class"] == "setting"),
                         [("tiers.0.model", "acme-small-1"), ("weekly.agent.model", "acme-big-1")],
                         "a whole value only: a model named inside a sentence is not a setting, and the block itself is not counted")

    def test_a_literal_is_found_with_its_line_and_a_comment_is_not(self):
        write(self.root, ".github/workflows/run.yml", "jobs:\n  a:\n    steps:\n      # was acme-small-1\n"
                                                      "      - run: agent --model acme-big-1 --turns 3\n")
        self.assertEqual(self.by("workflow"), [(".github/workflows/run.yml", 5, "acme-big-1")])

    def test_a_model_is_matched_as_a_whole_token(self):
        write(self.root, "tools/x.py", 'A = "acme-big-1-preview"\nB = "xacme-big-1"\nC = "my.acme-big-1"\nD = "acme-big-1"\nE = "acme-big-1,acme-small-1"\n')
        self.assertEqual(self.by("tool"), [("tools/x.py", 4, "acme-big-1"), ("tools/x.py", 5, "acme-big-1"), ("tools/x.py", 5, "acme-small-1")])

    def test_each_area_is_its_own_class(self):
        write(self.root, ".github/actions/run/run.sh", 'model="acme-big-1"\n')
        write(self.root, ".github/scripts/gen/x.py", 'DEFAULT = "acme-big-1"\n')
        write(self.root, "tools/jev/steps/loop/step.yml", "model: acme-small-1\n")
        write(self.root, "templates/kit/agent.yml", 'args: "--model acme-small-1"\n')
        write(self.root, ".github/scripts/prices.py", 'PRICES = {"acme-big-1": 1, "plat-mid-2": 2}\n')
        rows = self.found()[0]
        got = {b["class"]: b["file"] for b in rows if b["class"] != "setting"}
        self.assertEqual(got, {"action": ".github/actions/run/run.sh", "generator": ".github/scripts/gen/x.py",
                               "step": "tools/jev/steps/loop/step.yml", "kit": "templates/kit/agent.yml",
                               "table": ".github/scripts/prices.py"})
        self.assertEqual(sum(1 for b in rows if b["file"] == "tools/jev/steps/loop/step.yml"), 1,
                         "a step spec under tools/ is a step, never also a tool")
        self.assertEqual(sum(1 for b in rows if b["class"] == "table"), 2, "a table holds a row per model")

    def test_tests_fixtures_archives_and_hidden_directories_are_not_what_runs(self):
        for rel in ("tools/test_thing.py", "tools/thing_test.py", "tools/tests/x.py", "tools/pkg/fixtures/x.py",
                    "templates/kit/archive/old.yml", "tools/.venv/lib/x.py", "tools/web/node_modules/p/x.py",
                    ".github/workflows/sub/nested.yml", "tools/notes.md"):
            write(self.root, rel, 'M = "acme-big-1"\n')
        self.assertEqual([b for b in self.found()[0] if b["class"] != "setting"], [])

    def test_an_eval_set_pins_a_model(self):
        eval_set(self.root, "intake")
        eval_set(self.root, "classify", mode="deterministic", pin=None)
        self.assertEqual(self.by("pin"), [("evals/intake/cases.yml", None, "acme-big-1")])

    def test_an_owned_repos_workflows_are_read_and_another_owners_never(self):
        write(self.root, "projects/site/.github/workflows/agent.yml", 'x: "--model acme-small-1"\n')
        write(self.root, "projects/site/tools/x.py", 'M = "acme-big-1"\n')
        write(self.root, "projects/mirror/.github/workflows/agent.yml", 'x: "--model acme-small-1"\n')
        rows, _, read = self.found()
        self.assertEqual([(b["repo"], b["file"], b["line"]) for b in rows if b["class"] == "fleet-workflow"],
                         [("own/site", ".github/workflows/agent.yml", 1)],
                         "a fleet repo's workflows only: its other files are that repo's to count")
        self.assertEqual((read["repos"], read["external"], read["hub"]), (2, 1, "own/hub"))

    def test_a_model_flag_the_allowlist_does_not_know_is_reported(self):
        write(self.root, ".github/workflows/run.yml", "run: agent --model other-model-9 && agent --model=acme-big-1 && agent --model ${{ inputs.m }}\n")
        write(self.root, "tools/x.sh", "agent --model other-model-9\n")
        _, unlisted, _ = self.found()
        self.assertEqual(unlisted, [{"repo": "own/hub", "file": ".github/workflows/run.yml", "line": 1, "model": "other-model-9"}],
                         "in a workflow only, and never an expression or an allowed model")


class EvalStateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = instance(Path(self._tmp.name))
        eval_set(self.root, "intake")
        eval_set(self.root, "review")
        eval_set(self.root, "classify", mode="deterministic", pin=None)
        self.sets = {s["role"]: s for s in aimodels.eval_sets(self.root, MODEL)}

    def row(self, role="review", model="plat-mid-2", **over):
        base = aimodels.run_record(role, model, "plat", 3, 0, aimodels.WHOLE_SET, self.sets[role]["set"], 0.5, "2026-11-28")
        return {**base, **over}

    def state(self, rows, role="review", model="plat-mid-2"):
        return aimodels.eval_state(rows, self.sets[role], model)["state"]

    def test_the_sets_in_the_tree(self):
        self.assertEqual({r: (s["mode"], s["pin"], s["cases"], s["agents"], s["covers"]) for r, s in self.sets.items()}, {
            "classify": ("deterministic", None, 3, [], ""), "intake": ("model", "acme-big-1", 3, ["ci:hub:intake"], "step 1 of 3"),
            "review": ("model", "acme-big-1", 3, ["ci:hub:review"], "")})
        self.assertTrue(self.sets["review"]["set"].startswith("sha256:"))

    def test_only_a_whole_green_run_of_todays_set_is_proof(self):
        self.assertEqual(self.state([]), "unproven")
        self.assertEqual(self.state([self.row()]), "proven")
        self.assertEqual(self.state([self.row(failed=1, passed=2)]), "failed")
        self.assertEqual(self.state([self.row(scope="2 of 3 cases")]), "partial")
        self.assertEqual(self.state([self.row(set="sha256:older")]), "stale")
        self.assertEqual(self.state([self.row(model="acme-big-1")]), "unproven", "a run on another model proves nothing here")
        self.assertEqual(self.state([self.row(role="intake", set=self.sets["intake"]["set"])]), "unproven", "nor does another role's")

    def test_the_latest_run_decides(self):
        self.assertEqual(self.state([self.row(), self.row(failed=2, passed=1)]), "failed")
        self.assertEqual(self.state([self.row(failed=2, passed=1), self.row()]), "proven")

    def test_a_set_that_changes_makes_its_runs_stale(self):
        rows = [self.row()]
        eval_set(self.root, "review", cases=4)
        aimodels.yamlio.forget()
        fresh = {s["role"]: s for s in aimodels.eval_sets(self.root, MODEL)}["review"]
        self.assertEqual(aimodels.eval_state(rows, fresh, "plat-mid-2")["state"], "stale")

    def test_an_agent_is_proven_only_when_all_of_it_is(self):
        sets = list(self.sets.values())
        review = [self.row()]
        self.assertEqual(aimodels.agent_state("ci:hub:review", sets, review, "plat-mid-2")["state"], "proven")
        self.assertEqual(aimodels.agent_state("ci:hub:review", sets, [], "plat-mid-2")["state"], "unproven")
        self.assertEqual(aimodels.agent_state("ci:site:helper", sets, review, "plat-mid-2")["state"], "no-evals")
        part = aimodels.agent_state("ci:hub:intake", sets, [self.row(role="intake", set=self.sets["intake"]["set"])], "plat-mid-2")
        self.assertEqual(part["state"], "partial")
        self.assertIn("step 1 of 3", part["why"], "a set that tests part of an agent never reads as the whole")


class DocAndPlanTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = instance(Path(self._tmp.name), settings={"weekly": {"agent": {"model": "acme-big-1"}}})
        write(self.root, ".github/workflows/run.yml", "run: agent --model acme-big-1\n")
        write(self.root, "projects/site/.github/workflows/agent.yml", 'x: "--model acme-small-1"\n')
        eval_set(self.root, "intake")
        eval_set(self.root, "review")

    def test_the_document_has_its_contract(self):
        doc = aimodels.status_doc(self.root, self.root)
        self.assertEqual(doc["schema"], "fleet-ai-models/v1")
        self.assertEqual(set(doc), {"schema", "generated_at", "hub", "providers", "classes", "bindings", "evals", "agents",
                                    "findings", "read", "summary"})
        json.dumps(doc)
        deep, fast = doc["classes"]
        self.assertEqual((deep["id"], deep["model"], deep["provider"], deep["settings"], deep["literals"], deep["fleet_literals"],
                          deep["pins"], deep["edits"], deep["agents"], deep["proven"], deep["no_evals"]),
                         ("deep", "acme-big-1", "acme", 1, 1, 0, 2, 2, 3, 0, 1))
        self.assertEqual((fast["fleet_literals"], fast["edits"], fast["agents"]), (1, 1, 2))
        self.assertEqual(doc["agents"], {"total": 6, "with_model": 4, "covered": 2,
                                         "by_model": {"acme-big-1": 3, "acme-small-1": 2, "plat-mid-2": 0}})
        self.assertEqual(doc["summary"]["edits"], 3, "what every switch together would edit beyond the class lines")
        self.assertEqual(doc["summary"]["pins"], 2)

    def test_findings(self):
        write(self.root, "tools/x.py", 'M = "plat-mid-2"\n')
        write(self.root, ".github/workflows/odd.yml", "run: agent --model other-model-9\n")
        eval_set(self.root, "orphan")
        got = {(f["rule"], f["level"]) for f in aimodels.status_doc(self.root, self.root)["findings"]}
        self.assertEqual(got, {("unlisted-model", "note"), ("classless-model", "note"), ("uncovered-set", "note")})

    def plan(self, **kw):
        return aimodels.switch_plan(self.root, framework=self.root, **kw)

    def test_a_plan_names_every_edit_and_every_agent_it_moves(self):
        plan = self.plan(new="plat-mid-2", cls="deep")
        self.assertEqual((plan["from"], plan["to"], plan["class"]), ("acme-big-1", "plat-mid-2", "deep"))
        self.assertEqual(plan["provider"], {"from": "acme", "to": "plat", "changes": True, "allowed": True})
        easy = plan["easy"]
        self.assertEqual((easy["class_lines"], [b["key"] for b in easy["settings"]], [b["file"] for b in easy["literals"]],
                          easy["fleet_literals"], len(easy["pins"]), easy["edits"]),
                         (1, ["weekly.agent.model"], [".github/workflows/run.yml"], [], 2, 2))
        self.assertEqual({a["id"]: a["state"] for a in plan["safe"]["agents"]},
                         {"ci:hub:intake": "unproven", "ci:hub:review": "unproven", "loop:hub:both": "no-evals"})
        self.assertFalse(plan["ready"])
        text = " | ".join(plan["reasons"])
        for needle in ("the provider changes (acme to plat)", "2 place(s) besides the class line", "3 of 3 agent(s)"):
            self.assertIn(needle, text)

    def test_a_model_the_allowlist_does_not_know_is_a_gated_change_first(self):
        plan = self.plan(new="brand-new-1", cls="fast")
        self.assertFalse(plan["provider"]["allowed"])
        self.assertIn("brand-new-1 is not in ai_models.allowed", plan["reasons"][0])

    def test_a_switch_is_ready_when_it_is_one_line_and_everything_it_moves_is_proven(self):
        root = instance(Path(self._tmp.name) / "clean", agents=[{"id": "ci:hub:review", "repo": "own/hub", "model": "acme-small-1"}])
        path = eval_set(root, "review", pin=None)
        runs_file(root, [aimodels.run_record("review", "acme-big-1", "acme", 3, 0, aimodels.WHOLE_SET, aimodels.set_hash(path),
                                             0.2, "2026-11-28")])
        plan = aimodels.switch_plan(root, "acme-big-1", cls="fast", framework=root)
        self.assertEqual((plan["easy"]["edits"], plan["safe"]["counts"]), (0, {"proven": 1}))
        self.assertTrue(plan["ready"], plan["reasons"])
        self.assertIn("acme-big-1 is already bound to deep", plan["notes"][0], "said, and it does not block: the switch itself is one line")

    def test_a_model_two_classes_share_cannot_be_switched_for_one_of_them(self):
        block = copy.deepcopy(BLOCK)
        block["classes"] = {"deep": "acme-big-1", "fast": "acme-big-1"}
        root = instance(Path(self._tmp.name) / "shared", block=block, agents=[])
        self.assertEqual([f["rule"] for f in aimodels.status_doc(root, root)["findings"]], ["shared-model"])
        plan = aimodels.switch_plan(root, "plat-mid-2", cls="fast", framework=root)
        self.assertIn("acme-big-1 is also bound to deep", " | ".join(plan["reasons"]))

    def test_a_plan_needs_a_class_or_a_model(self):
        with self.assertRaises(aimodels.ModelError):
            self.plan(new="plat-mid-2", cls="nope")
        with self.assertRaises(aimodels.ModelError):
            self.plan(new="plat-mid-2")
        self.assertEqual(self.plan(new="plat-mid-2", old="acme-small-1")["easy"]["class_lines"], 1)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = aimodels.main(list(argv))
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def test_cli(self):
        real = aimodels.HUB
        aimodels.HUB = self.root  # the framework whose settings lie under the instance's
        self.addCleanup(setattr, aimodels, "HUB", real)
        inst = ["--instance", str(self.root)]
        code, out, _ = self.run_cli("models", *inst)
        self.assertEqual(code, 0)
        for needle in ("CLASS", "acme-big-1", "A switch should be ONE line", "1 in the workflows of the 1 fleet repo(s) read",
                       "2 of 4 agent(s) that run a model are covered"):
            self.assertIn(needle, out)
        self.assertEqual(self.run_cli(*inst)[1], out, "no subcommand is the same view")
        code, out, _ = self.run_cli("bindings", "--class", "workflow", *inst)
        self.assertIn(".github/workflows/run.yml:1", out)
        self.assertNotIn("weekly.agent.model", out)
        code, out, _ = self.run_cli("json", *inst)
        self.assertEqual(json.loads(out)["schema"], "fleet-ai-models/v1")
        code, out, _ = self.run_cli("switch", "deep", "--to", "plat-mid-2", *inst)
        self.assertEqual(code, 0, "a plan that is not ready still prints: it is advice")
        for needle in ("switch deep: acme-big-1 → plat-mid-2", "NOT READY:", "weekly.agent.model", "unproven  ci:hub:intake"):
            self.assertIn(needle, out)
        self.assertEqual(self.run_cli("switch", "deep", "--to", "plat-mid-2", "--strict", *inst)[0], 1)
        self.assertEqual(json.loads(self.run_cli("switch", "--from", "acme-big-1", "--to", "plat-mid-2", "--json", *inst)[1])["to"], "plat-mid-2")
        self.assertEqual(self.run_cli("switch", "--to", "plat-mid-2", *inst)[0], 2, "a class or --from is required")
        code, _, err = self.run_cli("switch", "nope", "--to", "plat-mid-2", *inst)
        self.assertEqual(code, 2)
        self.assertIn("no class 'nope'", err)


class RecordTests(unittest.TestCase):
    """tools/evals.py is the one writer of _data/eval_runs.yml."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = instance(Path(self._tmp.name))
        self.set = eval_set(self.root, "review")
        self.path = self.root / "_data" / "eval_runs.yml"
        self.cfg = yaml.safe_load((self.root / "_data" / "fleet.yml").read_text())

    def result(self, passed=3, failed=0, **over):
        res = evals.RoleResult(role="review", mode="model", model="plat-mid-2", cost_usd=0.4321)
        res.cases = [evals.CaseResult(id=f"c{i}", passed=i < passed, expected={}) for i in range(passed + failed)]
        for key, value in over.items():
            setattr(res, key, value)
        return res

    def record(self, *results):
        return evals.record_runs(list(results), self.cfg, path=self.path, evals_dir=self.root / "evals", today="2026-11-28")

    def test_a_whole_run_is_recorded_as_the_reader_expects_it(self):
        notes = self.record(self.result())
        self.assertIn("recorded: review on plat-mid-2 (all: 3 passed, 0 failed)", notes[0])
        (row,) = aimodels.eval_runs(self.root)
        self.assertEqual(row, {"role": "review", "model": "plat-mid-2", "provider": "plat", "date": "2026-11-28", "scope": "all",
                               "passed": 3, "failed": 0, "set": aimodels.set_hash(self.set), "cost_usd": 0.4321,
                               "cost_label": "API-equivalent (estimate)"})
        sets = aimodels.eval_sets(self.root, MODEL)
        self.assertEqual(aimodels.agent_state("ci:hub:review", sets, [row], "plat-mid-2")["state"], "proven")
        self.assertTrue(self.path.read_text().startswith("# _data/eval_runs.yml"), "the file keeps the header that says who writes it")

    def test_a_sample_is_recorded_as_a_sample_and_a_second_run_is_appended(self):
        self.record(self.result(passed=2))
        self.record(self.result(passed=2, failed=1))
        first, second = aimodels.eval_runs(self.root)
        self.assertEqual((first["scope"], second["scope"], second["failed"]), ("2 of 3 cases", "all", 1))

    def test_what_is_not_a_result_on_a_model_leaves_no_row(self):
        notes = self.record(self.result(dry_run=True), self.result(mode="deterministic", model=None),
                            self.result(errors=["the set is malformed"]), self.result(passed=0, failed=0))
        self.assertEqual(len(notes), 4)
        self.assertTrue(all(n.startswith("not recorded") for n in notes))
        self.assertFalse(self.path.exists())

    def test_the_flag_refuses_a_dry_run_or_another_set(self):
        for argv in (["run", "review", "--record", "--dry-run"], ["run", "review", "--record", "--cases", str(self.set)]):
            with self.assertRaises(SystemExit) as stop, contextlib.redirect_stderr(io.StringIO()):
                evals.main(argv)
            self.assertEqual(stop.exception.code, 2)


class NeutralityTests(unittest.TestCase):
    """AI-agnostic is a property of the code: every provider and model it knows comes from the settings."""

    def test_the_reader_names_no_provider_and_no_model(self):
        source = (HUB / "tools" / "fleetcore" / "aimodels.py").read_text(encoding="utf-8").lower()
        allowed = yaml.safe_load((HUB / "_data" / "fleet.yml").read_text(encoding="utf-8"))["ai_models"]["allowed"]
        words = {str(p).lower() for p in allowed} | {str(m).lower() for ids in allowed.values() for m in ids}
        # the family name each id starts with ("acme" of "acme-big-1"), which is how a literal would creep in
        words |= {m.split("-")[0] for m in words if "-" in m}
        for word in sorted(words):
            self.assertIsNone(re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", source),
                              f"tools/fleetcore/aimodels.py names '{word}': that belongs in _data/fleet.yml ai_models:")

    def test_the_committed_fleet_builds_a_document(self):
        doc = aimodels.status_doc(HUB, HUB)
        settings = yaml.safe_load((HUB / "_data" / "fleet.yml").read_text(encoding="utf-8"))
        self.assertEqual(doc["hub"], settings["hub"]["repo"])
        self.assertEqual([c["id"] for c in doc["classes"]], list(settings["ai_models"]["classes"]))
        self.assertEqual([f for f in doc["findings"] if f["rule"] == "classless-model"], [],
                         "every model the hub names is bound to a class, so a switch plan covers every place")
        self.assertEqual([f for f in doc["findings"] if f["rule"] == "uncovered-set"], [],
                         "every model-backed eval set is mapped to the agent it tests")
        ids = {a["id"] for a in aimodels.agents(HUB)}
        for role, spec in settings["ai_models"]["evals"].items():
            self.assertTrue((HUB / "evals" / role / "cases.yml").is_file(), f"ai_models.evals.{role} names an eval set that exists")
            for agent in spec["agents"]:
                self.assertIn(agent, ids, f"ai_models.evals.{role}: {agent} is an agent in _data/agents.yml")

    def test_the_committed_runs_file_reads(self):
        doc = yaml.safe_load((HUB / "_data" / "eval_runs.yml").read_text(encoding="utf-8"))
        self.assertEqual(doc["schema"], aimodels.RUNS_SCHEMA)
        self.assertIsInstance(doc["runs"], list)


if __name__ == "__main__":
    unittest.main()
