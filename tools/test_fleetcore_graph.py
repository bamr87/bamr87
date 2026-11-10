#!/usr/bin/env python3
"""Tests for tools/fleetcore/graph.py — the fleet graph: the model, the builders
over a fixture checkout, the surface parsers, the checks, and the hub's own
graph (no dangling edge, every input read). Offline, no pytest:
python3 tools/test_fleetcore_graph.py"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fleetcore import graph as fg  # noqa: E402

HUB = Path(__file__).resolve().parent.parent


def tiny() -> fg.Graph:
    """file ← source ← agent → workflow → action, a loop that runs the workflow, and a repo that owns it all."""
    g = fg.Graph("o/hub")
    g.node("repo:o/hub", "o/hub", hub=True)
    for nid in ("workflow:o/hub:pulse", "action:o/hub:cost", "agent:ci:pulse", "source:usage", "file:_data/usage.yml",
                "loop:hub/pulse", "var:PULSE_ENABLED", "workflow:o/hub:other"):
        kind = nid.split(":")[0]
        g.node(nid, file=f".github/{nid.split(':')[-1]}.yml" if kind in ("workflow", "action") else None,
               writer="pulse.yml" if kind == "source" else None, repo="o/hub" if kind == "loop" else None)
        if nid.split(":")[0] in ("workflow", "action", "agent", "loop"):
            g.edge("repo:o/hub", "owns", nid)
    g.edge("workflow:o/hub:pulse", "uses", "action:o/hub:cost")
    g.edge("workflow:o/hub:pulse", "publishes", "file:_data/usage.yml")
    g.edge("source:usage", "stored_at", "file:_data/usage.yml")
    g.edge("agent:ci:pulse", "reads", "source:usage")
    g.edge("agent:ci:pulse", "defined_in", "workflow:o/hub:pulse")
    g.edge("loop:hub/pulse", "runs", "workflow:o/hub:pulse")
    g.edge("loop:hub/pulse", "gated_by", "var:PULSE_ENABLED")
    return g


class ModelTests(unittest.TestCase):
    def test_the_vocabulary_is_closed(self):
        g = fg.Graph()
        with self.assertRaises(KeyError):
            g.node("widget:x")
        g.node("repo:a")
        g.node("repo:b")
        with self.assertRaises(KeyError):
            g.edge("repo:a", "likes", "repo:b")
        for rel, (_, dep) in fg.RELS.items():
            self.assertIn(dep, ("src", "dst", None), rel)

    def test_a_node_keeps_its_first_attributes_and_gains_later_ones(self):
        g = fg.Graph()
        g.node("workflow:o/r:x", "X", file=".github/workflows/x.yml")
        g.node("workflow:o/r:x", crons=["1 2 * * *"], model=None)
        n = g.nodes["workflow:o/r:x"]
        self.assertEqual((n["label"], n["attrs"]), ("X", {"file": ".github/workflows/x.yml", "crons": ["1 2 * * *"]}))

    def test_resolve_takes_an_id_a_unique_tail_or_says_what_is_ambiguous(self):
        g = tiny()
        self.assertEqual(g.resolve("agent:ci:pulse"), "agent:ci:pulse")
        self.assertEqual(g.resolve("usage.yml"), "file:_data/usage.yml")
        self.assertEqual(g.resolve("cost"), "action:o/hub:cost")
        with self.assertRaises(KeyError) as amb:
            g.resolve("pulse")
        self.assertIn("matches", str(amb.exception))
        with self.assertRaises(KeyError) as none:
            g.resolve("nothing-here")
        self.assertIn("no node matches", str(none.exception))

    def test_impact_follows_dependency_in_each_relations_own_direction(self):
        g = tiny()
        # the action breaks -> the workflow that uses it -> the file it publishes, the agent defined in it, the loop
        hit = {r["id"]: r["depth"] for r in g.walk("action:o/hub:cost", "impact", depth=4)["nodes"]}
        self.assertEqual(hit["workflow:o/hub:pulse"], 1)
        self.assertEqual((hit["file:_data/usage.yml"], hit["agent:ci:pulse"], hit["loop:hub/pulse"]), (2, 2, 2))
        self.assertEqual(hit["source:usage"], 3)
        # nothing is reached through containment: the repo owns everything and is never in an impact
        self.assertNotIn("repo:o/hub", hit)
        self.assertNotIn("workflow:o/hub:other", hit)
        self.assertNotIn("var:PULSE_ENABLED", hit)

    def test_lineage_is_the_reverse_walk(self):
        g = tiny()
        need = {r["id"] for r in g.walk("agent:ci:pulse", "lineage", depth=5)["nodes"]}
        self.assertEqual(need, {"source:usage", "file:_data/usage.yml", "workflow:o/hub:pulse", "action:o/hub:cost"})
        # the variable gates the loop, so the loop needs it; the agent does not
        self.assertIn("var:PULSE_ENABLED", {r["id"] for r in g.walk("loop:hub/pulse", "lineage")["nodes"]})

    def test_depth_limits_the_walk_and_each_row_names_how_it_was_reached(self):
        g = tiny()
        one = g.walk("action:o/hub:cost", "impact", depth=1)
        self.assertEqual([r["id"] for r in one["nodes"]], ["workflow:o/hub:pulse"])
        self.assertEqual(one["nodes"][0]["via"], {"rel": "uses", "from": "action:o/hub:cost"})
        self.assertEqual(one["by_kind"], {"workflow": 1})
        with self.assertRaises(ValueError):
            g.walk("action:o/hub:cost", "sideways")

    def test_a_path_avoids_containment_unless_nothing_else_connects(self):
        g = tiny()
        p = g.path("var:PULSE_ENABLED", "source:usage")
        self.assertEqual([h["rel"] for h in p["hops"]], ["gated_by", "runs", "publishes", "stored_at"])
        self.assertFalse(p["containment"])
        far = g.path("workflow:o/hub:other", "source:usage")
        self.assertTrue(far["containment"])
        self.assertEqual(far["hops"][0]["rel"], "owns")
        g.node("req:FR1")
        self.assertIsNone(g.path("req:FR1", "source:usage")["length"])

    def test_show_groups_edges_by_relation_and_export_is_sorted(self):
        g = tiny()
        doc = g.show("workflow:o/hub:pulse")
        self.assertEqual(sorted(doc["out"]), ["publishes", "uses"])
        self.assertEqual(sorted(doc["in"]), ["defined_in", "owns", "runs"])
        out = g.to_doc()
        self.assertEqual(out["schema"], "fleet-graph/v1")
        self.assertEqual([n["id"] for n in out["nodes"]], sorted(g.nodes))
        self.assertEqual(json.loads(json.dumps(out))["rels"]["uses"]["dependent"], "src")


class CheckTests(unittest.TestCase):
    def rules(self, g):
        return sorted({f["rule"] for f in fg.check(g)})

    def test_a_clean_tiny_graph_has_no_finding(self):
        self.assertEqual(fg.check(tiny()), [])

    def test_an_edge_to_an_undeclared_node_is_the_one_error(self):
        g = tiny()
        g.edge("agent:ci:pulse", "reads", "source:ghost")
        found = fg.check(g)
        self.assertEqual([(f["rule"], f["severity"], f["node"]) for f in found], [("dangling-edge", "error", "source:ghost")])
        self.assertEqual(fg.tally(found), {"error": 1, "warn": 0, "info": 0})

    def test_a_source_someone_reads_needs_a_writer_and_an_unread_one_does_not(self):
        g = tiny()
        g.node("source:orphan")  # nobody reads it: not a finding
        self.assertEqual(self.rules(g), [])
        g.node("source:stale")
        g.edge("agent:ci:pulse", "reads", "source:stale")
        self.assertEqual([f["node"] for f in fg.check(g)], ["source:stale"])

    def test_tiny_sources_carry_no_writer_yet_are_fine_only_when_declared(self):
        g = fg.Graph("o/hub")
        g.node("source:s")
        g.node("agent:a")
        g.edge("agent:a", "reads", "source:s")
        self.assertEqual(self.rules(g), ["source-without-writer"])

    def test_a_scheduled_hub_workflow_needs_a_loop_entry(self):
        g = fg.Graph("o/hub")
        g.node("workflow:o/hub:nightly", file=".github/workflows/nightly.yml", crons=["7 3 * * *"])
        g.node("workflow:o/other:nightly", file=".github/workflows/nightly.yml", crons=["7 3 * * *"])
        self.assertEqual([(f["rule"], f["node"]) for f in fg.check(g)], [("scheduled-without-loop", "workflow:o/hub:nightly")])
        g.node("loop:hub/nightly", repo="o/hub")
        g.edge("loop:hub/nightly", "runs", "workflow:o/hub:nightly")
        self.assertEqual(fg.check(g), [])

    def test_a_hub_loop_or_a_caller_that_names_a_missing_file_is_found(self):
        g = fg.Graph("o/hub")
        g.node("loop:hub/gone", repo="o/hub")
        g.node("workflow:o/hub:gone")  # declared by the switches map only: no `file`
        g.edge("loop:hub/gone", "runs", "workflow:o/hub:gone")
        g.node("workflow:o/hub:caller", file=".github/workflows/caller.yml")
        g.node("action:o/hub:missing")
        g.edge("workflow:o/hub:caller", "uses", "action:o/hub:missing")
        self.assertEqual(self.rules(g), ["loop-without-workflow", "uses-missing"])

    def test_route_exemptions_are_exact_unless_they_end_in_a_star(self):
        self.assertIsNotNone(fg.route_exempt("/api"))
        self.assertIsNone(fg.route_exempt("/api/work"))  # `/api` must not exempt everything under it
        self.assertIsNotNone(fg.route_exempt("/api/auth/credential"))
        self.assertIsNone(fg.route_exempt("/api/healthz"))
        g = fg.Graph()
        for path in ("/api/work", "/api/health", "/api/auth"):
            g.node(f"route:GET {path}", f"GET {path}")
        g.node("route:POST /api/jobs", "POST /api/jobs")  # only reads are owed a tool
        self.assertEqual([f["node"] for f in fg.check(g)], ["route:GET /api/work"])
        g.node("tool:work_board")
        g.edge("tool:work_board", "calls", "route:GET /api/work")
        self.assertEqual(fg.check(g), [])

    def test_a_command_with_no_operation_is_a_note_unless_exempt(self):
        g = fg.Graph()
        for c in ("agents", "console", "status"):
            g.node(f"cmd:{c}", f"dash {c}")
        g.node("op:status")
        g.edge("op:status", "runs", "cmd:status")
        found = fg.check(g)
        self.assertEqual([(f["rule"], f["severity"], f["node"]) for f in found],
                         [("command-without-operation", "info", "cmd:agents")])


LAYER = textwrap.dedent('''
    def build_server(c):
        def state():
            return c.get("/api/state")

        @mcp.tool(annotations=READ)
        def loops():
            return state().get("loops")

        @mcp.tool(annotations=READ)
        def job_log(job_id: str):
            def run():
                return c.get(f"/api/jobs/{job_id}")
            return run()

        @mcp.tool(annotations=READ)
        def code_search(mode: str):
            return c.get(f"/api/index/{mode}")

        @mcp.tool(annotations=READ)
        def alias():
            return loops()

        @mcp.tool(annotations=READ)
        def fleet_overview():
            return local("t_overview", {})

        if writes:
            @mcp.tool(annotations=WRITE)
            def run_op(op: str):
                return c.post("/api/jobs", {"op": op})

        def not_a_tool():
            return c.get("/api/secret")
''')


class SurfaceParserTests(unittest.TestCase):
    def test_tools_and_the_routes_they_reach_are_read_from_the_layers_source(self):
        tools = fg.mcp_tools(LAYER)
        self.assertEqual(sorted(tools), ["alias", "code_search", "fleet_overview", "job_log", "loops", "run_op"])
        self.assertEqual(tools["loops"], {"routes": ["/api/state"], "write": False})           # through a helper
        self.assertEqual(tools["alias"]["routes"], ["/api/state"])                             # through another tool
        self.assertEqual(tools["job_log"]["routes"], ["/api/jobs/{}"])                         # an f-string, nested def
        self.assertEqual(tools["fleet_overview"]["routes"], [])                                # reads the checkout
        self.assertEqual(tools["run_op"], {"routes": ["/api/jobs"], "write": True})            # registered under an `if`

    def test_route_shapes_match_segment_by_segment(self):
        self.assertTrue(fg._same_shape("/api/index/{}", "/api/index/search"))
        self.assertTrue(fg._same_shape("/api/data/deep_dive", "/api/data/{}"))
        self.assertFalse(fg._same_shape("/api/jobs/{}", "/api/jobs/{}/cancel"))
        self.assertFalse(fg._same_shape("/api/jobs", "/api/work"))
        self.assertEqual(fg._route_key("/api/jobs/{job_id}/cancel"), "/api/jobs/{}/cancel")

    def test_repo_urls_in_every_spelling_give_one_id(self):
        for url in ("https://github.com/Bamr87/Zer0-CMS", "https://github.com/Bamr87/Zer0-CMS.git",
                    "git@github.com:Bamr87/Zer0-CMS.git", "https://github.com/Bamr87/Zer0-CMS/"):
            self.assertEqual(fg.repo_id(fg.nwo_of(url)), "repo:bamr87/zer0-cms", url)
        self.assertIsNone(fg.nwo_of("https://example.com/x"))


def write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")


class BuilderTests(unittest.TestCase):
    """A fixture checkout with one of everything the hub-independent builders read."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write(self.root, "_data/fleet.yml", """
            hub: {repo: o/hub, owners: [o]}
            schedule: {nightly: "7 3 * * *"}
            switches:
              groups: {hub-loops: {state: "on"}}
              loops:
                hub/nightly:
                  repo: o/hub
                  workflow: .github/workflows/nightly.yml
                  group: hub-loops
                  gate: {kind: repo_variable, name: NIGHTLY_ENABLED, semantics: opt_out}
                  default: "on"
                  cron: "7 3 * * *"
        """)
        write(self.root, "_data/projects.yml", """
            - {name: site, repo_url: "https://github.com/o/Site", category: sites, status: active, auto_evolve: true}
            - {name: upstream, repo_url: "https://github.com/else/upstream", status: active}
        """)
        write(self.root, "_data/agents.yml", """
            sources:
              usage: {path: _data/usage.yml, writer: "nightly.yml (dash-gen usage)", slo_days: 3}
              lake: {path: .dash-lake/fleet.sqlite, writer: "local:review", slo: 2d}
              conformance: {path: _data/conformance.yml, writer: null, slo: 14d}
            agents:
              - id: ci:hub:nightly
                kind: ci-scheduled
                repo: o/hub
                where: .github/workflows/nightly.yml
                switch: {variable: NIGHTLY_ENABLED, loop: hub/nightly}
                reads: {usage: x, conformance: x}
                counterparts: [loop:nightly/step]
                gaps: ["R1:model"]
              - {id: "loop:nightly/step", kind: loop-step, repo: o/hub, where: tools/jev/steps/nightly/step.yml,
                 reads: {lake: x}}
              - {id: "local:review", kind: local-job, repo: o/hub, where: tools/install-review.sh}
              - {id: "ci:Site:claude", kind: ci-mention, repo: o/Site, where: .github/workflows/claude.yml}
        """)
        write(self.root, "_data/harness_registry.yml", """
            repos:
              - repo: site
                nwo: o/Site
                harnesses:
                  - {workflow: claude, path: .github/workflows/claude.yml, kind: mention-handler, crons: [],
                     switch: null, model: claude-x}
            schedule:
              - {repo: site, workflow: deploy, path: .github/workflows/deploy.yml, cron: "5 4 * * *", ai: false}
        """)
        write(self.root, "features/features.yml", """
            features:
              - {id: HUB-001, title: One, status: shipped, surface: ui, link: /work, docs: "docs/ONE.md#top",
                 prd: [FR1, NFR2, TBD], tests: [tools/test_one.py, {na: none yet}], scenarios: [verify/one.yml]}
              - {id: HUB-002, title: Two, status: planned, link: tools/two.py}
        """)
        write(self.root, "tools/two.py", "x = 1\n")
        write(self.root, "_data/roadmap.yml", """
            - {id: FF-0001, title: Idea, status: proposed, priority: P2, repo_url: "https://github.com/o/site",
               issue_url: "https://github.com/o/hub/issues/12"}
        """)
        write(self.root, "docs/adr/0001-first.md", """
            # ADR 0001 — The first decision

            - **Status**: accepted
            - **Tracking**: #77
        """)
        write(self.root, "docs/adr/0000-template.md", "# ADR NNNN — Title\n")
        write(self.root, "docs/amendments/0001-rule.md", """
            # 0001 — A rule

            - **Status:** ratified
            - **Affects:** constitution § 9; FR1; HUB-001; HUB-999
        """)
        self.g = fg.build(self.root, parts=("registry", "switches", "fleet", "agents", "governance"))

    def tearDown(self):
        self.tmp.cleanup()

    def edges(self, rel):
        return sorted((s, d) for (s, r, d) in self.g.edges if r == rel)

    def test_the_registry_gives_repos_under_one_spelling(self):
        self.assertEqual(self.edges("manages"), [("repo:o/hub", "repo:else/upstream"), ("repo:o/hub", "repo:o/site")])
        self.assertTrue(self.g.nodes["repo:else/upstream"]["attrs"]["external"])
        self.assertNotIn("external", self.g.nodes["repo:o/site"]["attrs"])
        # the registry says o/Site, the roadmap o/site, the agent o/Site: one node
        self.assertEqual([n for n in self.g.nodes if n.lower().startswith("repo:o/site")], ["repo:o/site"])

    def test_a_loop_joins_its_workflow_its_gate_and_its_group(self):
        self.assertEqual(self.edges("runs"), [("loop:hub/nightly", "workflow:o/hub:nightly")])
        self.assertIn(("loop:hub/nightly", "var:NIGHTLY_ENABLED"), self.edges("gated_by"))
        self.assertEqual(self.edges("in_group"), [("loop:hub/nightly", "group:hub-loops")])

    def test_agents_read_sources_and_sources_name_their_writers(self):
        self.assertEqual(self.edges("reads"), [("agent:ci:hub:nightly", "source:conformance"),
                                               ("agent:ci:hub:nightly", "source:usage"),
                                               ("agent:loop:nightly/step", "source:lake")])
        # a writer that is an agent id, and one that names a hub workflow file; `null` writes nothing
        self.assertEqual(self.edges("writes"), [("agent:local:review", "source:lake"),
                                                ("workflow:o/hub:nightly", "source:usage")])
        self.assertEqual(self.edges("twin_of"), [("agent:ci:hub:nightly", "agent:loop:nightly/step")])
        self.assertEqual(self.edges("part_of"), [("agent:ci:hub:nightly", "loop:hub/nightly")])
        self.assertIn(("agent:ci:Site:claude", "workflow:o/site:claude"), self.edges("defined_in"))
        self.assertIn(("agent:loop:nightly/step", "file:tools/jev/steps/nightly/step.yml"), self.edges("defined_in"))
        self.assertEqual(self.g.nodes["source:usage"]["attrs"]["slo"], "3d")

    def test_a_missing_writer_is_what_the_check_finds(self):
        found = [(f["rule"], f["node"]) for f in fg.check(self.g) if f["severity"] != "info"]
        self.assertIn(("source-without-writer", "source:conformance"), found)
        # features name three files this fixture does not have, and one it does
        missing = sorted(n for r, n in found if r == "feature-file-missing")
        self.assertEqual(missing, ["file:docs/ONE.md", "file:tools/test_one.py", "file:verify/one.yml"])
        self.assertFalse([f for f in fg.check(self.g) if f["severity"] == "error"])

    def test_the_fleet_scan_adds_other_repos_workflows(self):
        self.assertEqual(self.g.nodes["workflow:o/site:claude"]["attrs"]["models"], ["claude-x"])
        self.assertEqual(self.g.nodes["workflow:o/site:deploy"]["attrs"]["crons"], ["5 4 * * *"])
        self.assertIn(("repo:o/site", "workflow:o/site:deploy"), self.edges("owns"))

    def test_features_requirements_and_records_are_joined(self):
        self.assertEqual(self.edges("serves"), [("feature:HUB-001", "req:FR1"), ("feature:HUB-001", "req:NFR2")])
        self.assertEqual(self.edges("implemented_in"), [("feature:HUB-001", "page:/work"), ("feature:HUB-002", "file:tools/two.py")])
        self.assertEqual(self.edges("tested_by"), [("feature:HUB-001", "file:tools/test_one.py")])
        self.assertEqual(self.edges("targets"), [("roadmap:FF-0001", "repo:o/site")])
        self.assertEqual(self.edges("tracked_by"), [("adr:0001", "issue:o/hub#77"), ("roadmap:FF-0001", "issue:o/hub#12")])
        self.assertEqual(self.g.nodes["adr:0001"]["label"], "The first decision")
        self.assertNotIn("adr:0000", self.g.nodes)
        # an amendment governs what it names, when the hub has it
        self.assertEqual(self.edges("affects"), [("amendment:0001", "feature:HUB-001"), ("amendment:0001", "req:FR1")])

    def test_an_absent_or_broken_input_is_recorded_not_raised(self):
        (self.root / "_data/roadmap.yml").unlink()
        write(self.root, "_data/agents.yml", "agents: [unclosed\n")
        g = fg.build(self.root, parts=("registry", "agents", "governance"))
        inputs = {i["path"]: i for i in g.inputs}
        self.assertFalse(inputs["_data/roadmap.yml"]["present"])
        self.assertIn("unreadable", inputs["_data/agents.yml"]["problem"])
        self.assertEqual(len(g.problems), 1)
        with self.assertRaises(KeyError):
            fg.build(self.root, parts=("nonsense",))


class HubGraphTests(unittest.TestCase):
    """The hub's own graph: every input read, nothing dangling, the joins a reader relies on present."""

    @classmethod
    def setUpClass(cls):
        cls.g = fg.build(HUB)
        cls.findings = fg.check(cls.g)

    def test_every_input_is_read_without_a_problem(self):
        self.assertEqual(self.g.problems, [])
        self.assertEqual([i["path"] for i in self.g.inputs if not i["present"]], [])
        self.assertEqual([i["path"] for i in self.g.inputs if not i["count"]], [])

    def test_rebuilding_does_not_grow_the_import_path(self):
        before = len(sys.path)
        fg.build(HUB, parts=("workflows",))
        fg.build(HUB, parts=("workflows",))
        self.assertEqual(len(sys.path), before)

    def test_no_edge_dangles(self):
        self.assertEqual([f for f in self.findings if f["severity"] == "error"], [])

    def test_every_kind_and_most_relations_are_used(self):
        s = self.g.summary()
        self.assertEqual(sorted(set(fg.KINDS) - set(s["by_kind"])), [])
        self.assertGreater(s["nodes"], 800)
        for rel in ("uses", "runs", "reads", "writes", "serves", "calls", "gated_by", "publishes"):
            self.assertGreater(s["by_rel"].get(rel, 0), 0, rel)

    def test_the_pulse_loop_is_joined_end_to_end(self):
        out = dict((rel, dst) for rel, dst in self.g.out("loop:hub/fleet-pulse"))
        self.assertEqual(out["runs"], "workflow:bamr87/bamr87:fleet-pulse")
        self.assertEqual(out["gated_by"], "var:FLEET_PULSE_ENABLED")
        need = {r["id"] for r in self.g.walk("agent:ci:bamr87:fleet-pulse", "lineage", depth=2)["nodes"]}
        self.assertTrue({"action:bamr87/bamr87:claude-cost", "source:actions-usage", "file:_data/actions_usage.yml"} <= need)
        hit = {r["id"] for r in self.g.walk("action:bamr87/bamr87:claude-cost", "impact", depth=2)["nodes"]}
        self.assertIn("workflow:bamr87/bamr87:fleet-pulse", hit)
        self.assertIn("agent:ci:bamr87:fleet-pulse", hit)

    def test_every_operation_is_parsed_and_most_name_their_command(self):
        ops = [n for n in self.g.nodes if n.startswith("op:")]
        with_cmd = [o for o in ops if any(rel == "runs" for rel, _ in self.g.out(o))]
        self.assertGreater(len(ops), 50)
        self.assertGreater(len(with_cmd) / len(ops), 0.8)
        self.assertIn(("runs", "cmd:lake"), self.g.out("op:lake-sync"))

    def test_every_exemption_names_something_that_exists(self):
        routes = {n["label"].split(" ", 1)[1] for n in self.g.nodes.values() if n["kind"] == "route"}
        for key in fg.ROUTE_EXEMPT:
            stem = key.rstrip("*")
            self.assertTrue(any(r == stem or (key.endswith("*") and r.startswith(stem)) for r in routes), key)
        cmds = {n.split(":", 1)[1] for n in self.g.nodes if n.startswith("cmd:")}
        self.assertEqual(sorted(set(fg.COMMAND_EXEMPT) - cmds), [])

    def test_the_merged_fleet_tools_are_in_the_graph(self):
        for tool in ("fleet_overview", "fleet_work", "fleet_workflows", "workflow_lint", "work_board", "console_run"):
            self.assertIn(f"tool:{tool}", self.g.nodes)
        self.assertTrue(self.g.nodes["tool:console_run"]["attrs"].get("write"))
        self.assertIn(("calls", "route:GET /api/work"), self.g.out("tool:work_board"))


class CliTests(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = fg.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_summary_is_the_default_and_json_is_one_document(self):
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("fleet graph · "))
        code, out, _ = self.run_cli("--json", "summary")
        self.assertEqual((code, json.loads(out)["schema"]), (0, "fleet-graph/v1"))
        code, after, _ = self.run_cli("summary", "--json")          # the flag reads the same after the subcommand
        self.assertEqual((code, json.loads(after)["nodes"]), (0, json.loads(out)["nodes"]))

    def test_show_impact_and_path_read_one_node(self):
        code, out, _ = self.run_cli("show", "loop:hub/fleet-pulse")
        self.assertEqual(code, 0)
        self.assertIn("—runs→ 1", out)
        code, out, _ = self.run_cli("--json", "impact", "action:bamr87/bamr87:claude-cost", "--depth", "1")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["by_kind"].keys(), {"workflow"})
        code, out, _ = self.run_cli("path", "loop:hub/fleet-pulse", "source:actions-usage")
        self.assertEqual(code, 0)
        self.assertIn("source:actions-usage", out.splitlines()[-1])

    def test_an_unknown_or_ambiguous_node_exits_2_on_stderr(self):
        code, out, err = self.run_cli("show", "no-such-node-anywhere")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("no node matches", err)
        code, _, err = self.run_cli("show", "claude")
        self.assertEqual(code, 2)
        self.assertIn("matches", err)

    def test_check_passes_on_the_hub_and_a_rule_filter_counts_only_its_own(self):
        code, out, _ = self.run_cli("check")
        self.assertEqual(code, 0)
        self.assertIn("graph check: 0 error(s)", out.splitlines()[-1])
        code, out, _ = self.run_cli("--json", "check", "--rule", "dangling-edge")
        doc = json.loads(out)
        self.assertEqual((code, doc["findings"], doc["tally"]), (0, [], {"error": 0, "warn": 0, "info": 0}))

    def test_export_writes_the_whole_graph_only_when_asked(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "graph.json"
            code, out, _ = self.run_cli("export", "--out", str(target))
            self.assertEqual(code, 0)
            doc = json.loads(target.read_text())
            self.assertEqual(doc["schema"], "fleet-graph/v1")
            self.assertEqual(len(doc["nodes"]), len({n["id"] for n in doc["nodes"]}))
            ids = {n["id"] for n in doc["nodes"]}
            self.assertEqual([e for e in doc["edges"] if e["from"] not in ids or e["to"] not in ids], [])


if __name__ == "__main__":
    unittest.main()
