#!/usr/bin/env python3
"""The fleet graph — everything the control plane manages and how it relates, as ONE model.

The hub already keeps a dozen partial maps: the registry (repos), the workflow
atlas (workflows → actions → published data), the switches map (loops → kill
switches), the agent inventory (agents → the sources they read → who writes
them), the feature index (features → requirements → tests), the roadmap, the
ADR and amendment logs, and four operator surfaces (the dash CLI, the console's
operations and API routes, the MCP tools, the console's pages). Each answers
its own question. None answers a question that crosses two of them: "what
depends on this file", "which loops read a source nobody writes", "what can a
person do in the terminal that an agent cannot do over MCP".

This module joins them. It reads only committed files and the checkout — no
network, no model, no write, no subprocess — so it gives the same answer in CI,
in the console and in an agent's MCP host (ADR 0010, docs/FLEET-GRAPH.md).

  build(root)        every node and edge, from the parts in PARTS
  Graph.show(id)     one node with its edges, grouped by relation
  Graph.walk(id, …)  impact (what depends on it) or lineage (what it depends on)
  Graph.path(a, b)   the shortest chain of relations between two nodes
  check(graph)       findings: dangling edges, sources nobody writes, loops with
                     no workflow, scheduled workflows with no switch entry, and
                     the surface-parity gaps (an API route no MCP tool reaches,
                     a dash command no console operation runs)

  python3 -m fleetcore.graph [summary|find|show|impact|lineage|path|check|export]   (tools/dash graph)

A node id is `<kind>:<key>` and is stable across builds; KINDS and RELS below
are the whole vocabulary, and a builder that needs a new one adds it there.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter, deque
from pathlib import Path

import yaml

SCHEMA = "fleet-graph/v1"  # bump on a breaking (non-additive) change
ROOT_DEFAULT = Path(__file__).resolve().parents[2]
HUB_DEFAULT = "bamr87/bamr87"

# kind (the id prefix) -> what a node of that kind is
KINDS = {
    "repo": "a repository: the hub or a registry project",
    "workflow": "a GitHub Actions workflow file in a repo",
    "action": "a composite action the hub provides",
    "ext": "an action or reusable workflow from outside the hub",
    "loop": "a switched loop (fleet.yml switches.loops)",
    "group": "a switch group (fleet.yml switches.groups)",
    "var": "a repository variable, by name",
    "secret": "a secret, by name only — never a value",
    "file": "a file in the hub checkout",
    "source": "a data source an agent reads (fleet.yml harness.sources)",
    "agent": "an AI agent (the inventory, _data/agents.yml)",
    "feature": "a user-facing feature (features/features.yml)",
    "req": "a PRD requirement (FRn / NFRn)",
    "roadmap": "a roadmap entry (_data/roadmap.yml)",
    "adr": "an architecture decision record",
    "amendment": "a constitution amendment",
    "issue": "a GitHub issue named by a record, by number only",
    "cmd": "a tools/dash subcommand",
    "op": "a console operation (the job allowlist)",
    "route": "a console HTTP API route",
    "tool": "an MCP tool the console's layer serves",
    "page": "a console page",
}

# rel -> (what it says, which end depends on the other). "src": the source of
# the edge breaks when its target does; "dst": the target is produced or
# governed by the source; None: containment or reference, never traversed for
# impact (everything is owned by a repo, so following it would reach everything).
RELS: dict[str, tuple[str, str | None]] = {
    "manages": ("the hub manages a registry repo", None),
    "owns": ("a repo holds a workflow, action, loop or agent", None),
    "uses": ("a workflow or action calls an action or reusable workflow", "src"),
    "publishes": ("a workflow writes a committed data file", "dst"),
    "reads_var": ("a workflow reads a repository variable", "src"),
    "reads_secret": ("a workflow reads a secret", "src"),
    "runs": ("a loop runs a workflow; a console operation runs a dash command", "src"),
    "gated_by": ("a loop or workflow is switched by a repository variable", "src"),
    "in_group": ("a loop belongs to a switch group", "src"),
    "defined_in": ("an agent is defined by a workflow or a file", "src"),
    "part_of": ("an agent runs as part of a loop", "src"),
    "twin_of": ("a CI agent step and the local loop step that does the same work", None),
    "reads": ("an agent reads a data source", "src"),
    "writes": ("a workflow or agent is the declared writer of a data source", "dst"),
    "stored_at": ("a data source lives in a file", "src"),
    "serves": ("a feature serves a requirement", "dst"),
    "implemented_in": ("a feature's code", "src"),
    "documented_in": ("a feature's operator doc", None),
    "tested_by": ("a feature's test", None),
    "verified_by": ("a feature's user scenario", None),
    "targets": ("a roadmap entry is for a repo", None),
    "tracked_by": ("a roadmap entry or decision is delivered by an issue", None),
    "affects": ("an amendment or decision governs a feature or requirement", "dst"),
    "calls": ("an MCP tool calls a console API route", "src"),
}

PARTS = ("registry", "workflows", "switches", "fleet", "agents", "governance", "surfaces")

NWO_RX = re.compile(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?/?$")
ISSUE_URL_RX = re.compile(r"github\.com/([\w.-]+/[\w.-]+)/(?:issues|pull)/(\d+)")
WORKFLOW_FILE_RX = re.compile(r"^\.github/workflows/([\w.-]+)\.ya?ml$")
WRITER_WORKFLOW_RX = re.compile(r"\b([a-z][a-z0-9-]+)\.ya?ml\b")
REQ_RX = re.compile(r"^N?FR\d+$")
FEATURE_REF_RX = re.compile(r"\bHUB-\d{3}\b")
REQ_REF_RX = re.compile(r"\bN?FR\d+\b")
# `- **Status**: x` (ADRs) and `- **Status:** x` (amendments)
HEADER_RX = re.compile(r"^- \*\*([A-Za-z ]+):?\*\*:?\s*(.*)$")


class Graph:
    """Nodes by id and edges by (src, rel, dst). Mutated only by the builders."""

    def __init__(self, hub: str = HUB_DEFAULT) -> None:
        self.hub = hub
        self.nodes: dict[str, dict] = {}
        self.edges: dict[tuple[str, str, str], dict] = {}
        self.inputs: list[dict] = []
        self.problems: list[str] = []
        self._out: dict[str, list[tuple[str, str]]] | None = None
        self._in: dict[str, list[tuple[str, str]]] | None = None

    # ------------------------------------------------------------- building
    def node(self, nid: str, label: str | None = None, **attrs) -> str:
        kind = nid.split(":", 1)[0]
        if kind not in KINDS:
            raise KeyError(f"unknown node kind in {nid!r}")
        n = self.nodes.get(nid)
        if n is None:
            n = self.nodes[nid] = {"id": nid, "kind": kind, "label": nid.split(":", 1)[1], "attrs": {}}
        if label:
            n["label"] = str(label)
        n["attrs"].update({k: v for k, v in attrs.items() if v not in (None, "", [], {})})
        return nid

    def edge(self, src: str, rel: str, dst: str, **attrs) -> None:
        if rel not in RELS:
            raise KeyError(f"unknown relation {rel!r}")
        self.edges.setdefault((src, rel, dst), {}).update({k: v for k, v in attrs.items() if v not in (None, "")})
        self._out = self._in = None

    def note_input(self, path: str, present: bool, count: int | None = None, why: str | None = None) -> None:
        self.inputs.append({"path": path, "present": present, "count": count, "problem": why})
        if why:
            self.problems.append(f"{path}: {why}")

    # -------------------------------------------------------------- reading
    def _index(self) -> None:
        if self._out is not None:
            return
        self._out, self._in = {}, {}
        for (s, rel, d) in sorted(self.edges):
            self._out.setdefault(s, []).append((rel, d))
            self._in.setdefault(d, []).append((rel, s))

    def out(self, nid: str) -> list[tuple[str, str]]:
        self._index()
        return self._out.get(nid, [])

    def into(self, nid: str) -> list[tuple[str, str]]:
        self._index()
        return self._in.get(nid, [])

    def brief(self, nid: str) -> dict:
        n = self.nodes.get(nid)
        return {"id": nid, "kind": nid.split(":", 1)[0], "label": n["label"] if n else nid.split(":", 1)[1]}

    def resolve(self, ref: str) -> str:
        """An id, or the one node whose id ends with the text given (`fleet-pulse`, `agents.yml`)."""
        if ref in self.nodes:
            return ref
        tail = [n for n in self.nodes if n.endswith(":" + ref) or n.endswith("/" + ref)]
        if len(tail) == 1:
            return tail[0]
        hits = tail or [n for n in self.nodes if ref.lower() in n.lower()]
        if len(hits) == 1:
            return hits[0]
        if not hits:
            raise KeyError(f"no node matches {ref!r}")
        more = " …" if len(hits) > 8 else ""
        raise KeyError(f"{ref!r} matches {len(hits)} nodes: {', '.join(sorted(hits)[:8])}{more}")

    def find(self, text: str = "", kind: str | None = None, limit: int = 50) -> dict:
        t = text.lower()
        hits = [n for n in self.nodes.values() if (not kind or n["kind"] == kind)
                and (not t or t in n["id"].lower() or t in n["label"].lower())]
        hits.sort(key=lambda n: n["id"])
        return {"count": len(hits), "nodes": [self.brief(n["id"]) for n in hits[:limit]]}

    def show(self, ref: str) -> dict:
        nid = self.resolve(ref)
        out: dict[str, list] = {}
        for rel, dst in self.out(nid):
            out.setdefault(rel, []).append(self.brief(dst) | self.edges[(nid, rel, dst)])
        inn: dict[str, list] = {}
        for rel, src in self.into(nid):
            inn.setdefault(rel, []).append(self.brief(src) | self.edges[(src, rel, nid)])
        return {"node": self.nodes[nid], "out": out, "in": inn}

    def walk(self, ref: str, mode: str = "impact", depth: int = 3, limit: int = 500) -> dict:
        """Impact: what breaks, goes stale or loses its ground when this node does.
        Lineage: what this node needs. Both follow only relations that carry a
        dependency (RELS), each in its own direction."""
        if mode not in ("impact", "lineage"):
            raise ValueError("mode must be impact or lineage")
        start = self.resolve(ref)
        seen = {start: 0}
        via: dict[str, dict] = {}
        queue = deque([start])
        while queue:
            cur = queue.popleft()
            if seen[cur] >= depth:
                continue
            steps = [(rel, other, "src") for rel, other in self.into(cur)]
            steps += [(rel, other, "dst") for rel, other in self.out(cur)]
            for rel, other, other_is in steps:
                dep = RELS[rel][1]
                if dep is None:
                    continue
                # the other end depends on `cur` when it is the end RELS names as dependent
                depends_on_cur = dep == other_is
                if depends_on_cur != (mode == "impact") or other in seen:
                    continue
                seen[other] = seen[cur] + 1
                via[other] = {"rel": rel, "from": cur}
                queue.append(other)
        rows = [self.brief(n) | {"depth": d, "via": via[n]} for n, d in seen.items() if n != start]
        rows.sort(key=lambda r: (r["depth"], r["kind"], r["id"]))
        by_kind = Counter(r["kind"] for r in rows)
        return {"node": self.brief(start), "mode": mode, "depth": depth, "count": len(rows),
                "by_kind": dict(sorted(by_kind.items())), "nodes": rows[:limit], "truncated": len(rows) > limit}

    def path(self, a: str, b: str) -> dict:
        """The shortest chain between two nodes, ignoring direction; containment
        (`owns`, `manages`) is used only when nothing else connects them."""
        src, dst = self.resolve(a), self.resolve(b)
        for skip in ({"owns", "manages"}, set()):
            prev: dict[str, tuple[str, str, str]] = {}
            queue, seen = deque([src]), {src}
            while queue and dst not in seen:
                cur = queue.popleft()
                steps = [(rel, o, "->") for rel, o in self.out(cur)] + [(rel, o, "<-") for rel, o in self.into(cur)]
                for rel, other, arrow in steps:
                    if rel in skip or other in seen:
                        continue
                    seen.add(other)
                    prev[other] = (cur, rel, arrow)
                    queue.append(other)
            if dst in seen:
                hops, cur = [], dst
                while cur != src:
                    p, rel, arrow = prev[cur]
                    hops.append({"from": p, "rel": rel, "direction": arrow, "to": cur})
                    cur = p
                return {"from": src, "to": dst, "length": len(hops), "hops": hops[::-1], "containment": not skip}
        return {"from": src, "to": dst, "length": None, "hops": [], "containment": False}

    def summary(self) -> dict:
        kinds = Counter(n["kind"] for n in self.nodes.values())
        rels = Counter(rel for (_, rel, _) in self.edges)
        return {"schema": SCHEMA, "hub": self.hub, "nodes": len(self.nodes), "edges": len(self.edges),
                "by_kind": dict(sorted(kinds.items())), "by_rel": dict(sorted(rels.items())),
                "inputs": self.inputs, "problems": self.problems}

    def to_doc(self) -> dict:
        return {"schema": SCHEMA, "hub": self.hub, "kinds": KINDS,
                "rels": {r: {"means": m, "dependent": d} for r, (m, d) in RELS.items()},
                "nodes": [self.nodes[k] for k in sorted(self.nodes)],
                "edges": [{"from": s, "rel": r, "to": d} | self.edges[(s, r, d)] for (s, r, d) in sorted(self.edges)],
                "inputs": self.inputs, "problems": self.problems}


# --------------------------------------------------------------------------- #
# inputs
# --------------------------------------------------------------------------- #
def _yaml(g: Graph, root: Path, rel: str):
    p = root / rel
    if not p.is_file():
        g.note_input(rel, False)
        return None
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        g.note_input(rel, True, why=f"unreadable ({exc.__class__.__name__})")
        return None
    return doc


def _text(g: Graph, root: Path, rel: str) -> str | None:
    p = root / rel
    if not p.is_file():
        g.note_input(rel, False)
        return None
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        g.note_input(rel, True, why=f"unreadable ({exc.__class__.__name__})")
        return None


def nwo_of(url: str) -> str | None:
    m = NWO_RX.search(str(url or "").strip())
    return m.group(1) if m else None


def repo_id(nwo: str) -> str:
    return f"repo:{nwo.lower()}"


def workflow_id(nwo: str, stem: str) -> str:
    return f"workflow:{nwo.lower()}:{stem}"


def _file(g: Graph, root: Path, rel: str) -> str:
    rel = str(rel).strip()
    rel = rel[2:] if rel.startswith("./") else rel
    return g.node(f"file:{rel}", rel, exists=(root / rel).exists())


# --------------------------------------------------------------------------- #
# builders — one per part, each tolerant of a missing input
# --------------------------------------------------------------------------- #
def build_registry(g: Graph, root: Path, fleet: dict) -> None:
    hub = repo_id(g.hub)
    g.node(hub, g.hub, hub=True)
    rows = _yaml(g, root, "_data/projects.yml")
    if not isinstance(rows, list):
        return
    owners = {str(o).lower() for o in ((fleet.get("hub") or {}).get("owners") or [g.hub.split("/")[0]])}
    n = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        nwo = nwo_of(row.get("repo_url")) or f"{g.hub.split('/')[0]}/{row.get('name')}"
        rid = g.node(repo_id(nwo), nwo, name=row.get("name"), category=row.get("category"), status=row.get("status"),
                     branch=row.get("branch"), path=row.get("submodule_path"),
                     auto_evolve=bool(row.get("auto_evolve")) or None,
                     external=(nwo.split("/")[0].lower() not in owners) or None)
        g.edge(hub, "manages", rid)
        n += 1
    g.note_input("_data/projects.yml", True, n)


def _atlas(root: Path):
    gen = str(root / ".github" / "scripts" / "dash-gen")
    if gen not in sys.path:  # once: a console that rebuilds the graph must not grow sys.path each time
        sys.path.insert(0, gen)
    import workflow_atlas  # noqa: WPS433 — dash-gen's own module, only when asked
    return workflow_atlas


def build_workflows(g: Graph, root: Path, fleet: dict) -> None:
    """The hub's `.github/`, through the workflow atlas's own parser."""
    try:
        atlas = _atlas(root).scan(root, fleet, g.hub)
    except Exception as exc:  # noqa: BLE001 — the atlas failing is reported as a missing part, not raised
        g.note_input(".github/workflows", (root / ".github" / "workflows").is_dir(),
                     why=f"workflow atlas failed ({exc.__class__.__name__}: {exc})"[:200])
        return
    hub = repo_id(g.hub)
    for act in atlas["actions"]:
        aid = g.node(f"action:{g.hub.lower()}:{act['id']}", act.get("name") or act["id"], file=act["file"])
        g.edge(hub, "owns", aid)
    for wf in atlas["workflows"]:
        wid = g.node(workflow_id(g.hub, wf["id"]), wf.get("name") or wf["id"], file=wf["file"], group=wf.get("group"),
                     triggers=wf.get("triggers"), crons=[c["cron"] for c in wf.get("crons") or []],
                     ai=bool(wf.get("ai_sites")) or None, opens_prs=wf.get("opens_prs") or None,
                     models=sorted({s["model"] for s in wf.get("ai_sites") or [] if s.get("model")}))
        g.edge(hub, "owns", wid)
        for ref in wf.get("uses") or []:
            g.edge(wid, "uses", _use_target(g, ref), ver=ref.get("ver"))
        for path in wf.get("publishes") or []:
            g.edge(wid, "publishes", _file(g, root, path))
        for name in wf.get("vars") or []:
            g.edge(wid, "reads_var", g.node(f"var:{name}"))
        for name in wf.get("secrets") or []:
            g.edge(wid, "reads_secret", g.node(f"secret:{name}"))
        for name in wf.get("switches") or []:
            g.edge(wid, "gated_by", g.node(f"var:{name}"))
    wa = _atlas(root)
    for act in atlas["actions"]:
        for raw in act.get("uses") or []:
            g.edge(f"action:{g.hub.lower()}:{act['id']}", "uses", _use_target(g, wa._ref(raw)))
    g.note_input(".github/workflows", True, len(atlas["workflows"]))
    g.note_input(".github/actions", True, len(atlas["actions"]))


def _use_target(g: Graph, ref: dict) -> str:
    """A `uses:` reference as a node: a hub action or workflow, or an external one."""
    owner = (ref.get("owner") or g.hub).lower()
    if ref.get("kind") == "action" and owner == g.hub.lower():
        return g.node(f"action:{owner}:{ref['target']}")
    if ref.get("kind") == "workflow" and owner == g.hub.lower():
        return g.node(workflow_id(owner, ref["target"]))
    if ref.get("kind") in ("action", "workflow"):
        return g.node(f"ext:{owner}/{ref['target']}", external=True)
    target = str(ref.get("target") or ref.get("ref") or "unknown").split("@", 1)[0]
    return g.node(f"ext:{target}", external=True)


def build_switches(g: Graph, root: Path, fleet: dict) -> None:
    sw = fleet.get("switches") if isinstance(fleet.get("switches"), dict) else {}
    for name, spec in (sw.get("groups") or {}).items():
        g.node(f"group:{name}", name, state=(spec or {}).get("state"))
    loops = sw.get("loops") or {}
    for lid, spec in loops.items():
        if not isinstance(spec, dict):
            continue
        gate = spec.get("gate") if isinstance(spec.get("gate"), dict) else {}
        nid = g.node(f"loop:{lid}", lid, repo=spec.get("repo"), default=spec.get("default"), state=spec.get("state"),
                     cron=spec.get("cron"), semantics=gate.get("semantics"), scope=spec.get("scope"))
        nwo = str(spec.get("repo") or g.hub)
        g.edge(g.node(repo_id(nwo), nwo), "owns", nid)
        m = WORKFLOW_FILE_RX.match(str(spec.get("workflow") or ""))
        if m:
            g.edge(nid, "runs", g.node(workflow_id(nwo, m.group(1))))
        if gate.get("name"):
            g.edge(nid, "gated_by", g.node(f"var:{gate['name']}"), kind=gate.get("kind"))
        if spec.get("group"):
            g.edge(nid, "in_group", g.node(f"group:{spec['group']}"))
    for key, cron in (fleet.get("schedule") or {}).items():
        stem = str(key).replace("_", "-")
        stem = {"rotate-tokens": "token-rotation"}.get(stem, stem)
        wid = workflow_id(g.hub, stem)
        if wid in g.nodes:
            g.node(wid, schedule_key=str(key), declared_cron=str(cron))
    g.note_input("_data/fleet.yml switches.loops", bool(loops), len(loops))


def build_fleet(g: Graph, root: Path, fleet: dict) -> None:
    """Every other repo's AI workflows and crons, from the committed scan."""
    reg = _yaml(g, root, "_data/harness_registry.yml")
    if not isinstance(reg, dict):
        return
    n = 0
    for repo in reg.get("repos") or []:
        nwo = str(repo.get("nwo") or "")
        if not nwo or nwo.lower() == g.hub.lower():
            continue
        rid = g.node(repo_id(nwo), nwo, archived=repo.get("archived") or None, scanned=repo.get("scanned"))
        for h in repo.get("harnesses") or []:
            m = WORKFLOW_FILE_RX.match(str(h.get("path") or ""))
            if not m:
                continue
            wid = g.node(workflow_id(nwo, m.group(1)), h.get("workflow"), file=h.get("path"), ai=True,
                         agent_kind=h.get("kind"), triggers=h.get("triggers"), crons=h.get("crons"),
                         models=[h["model"]] if h.get("model") else None, kit=h.get("kit"))
            g.edge(rid, "owns", wid)
            if h.get("switch"):
                g.edge(wid, "gated_by", g.node(f"var:{h['switch']}"))
            n += 1
    for row in reg.get("schedule") or []:
        owner = next((r.get("nwo") for r in reg.get("repos") or [] if r.get("repo") == row.get("repo")), None)
        m = WORKFLOW_FILE_RX.match(str(row.get("path") or ""))
        if not owner or not m or owner.lower() == g.hub.lower():
            continue
        wid = g.node(workflow_id(owner, m.group(1)), row.get("workflow"), file=row.get("path"),
                     ai=row.get("ai") or None)
        crons = sorted(set((g.nodes[wid]["attrs"].get("crons") or []) + [str(row.get("cron"))]))
        g.node(wid, crons=crons)
        g.edge(g.node(repo_id(owner), owner), "owns", wid)
    g.note_input("_data/harness_registry.yml", True, n)


def build_agents(g: Graph, root: Path, fleet: dict) -> None:
    doc = _yaml(g, root, "_data/agents.yml")
    if not isinstance(doc, dict):
        return
    agents = [a for a in doc.get("agents") or [] if isinstance(a, dict) and a.get("id")]
    ids = {a["id"] for a in agents}
    for sid, spec in (doc.get("sources") or {}).items():
        spec = spec if isinstance(spec, dict) else {}
        writer = spec.get("writer")
        snode = g.node(f"source:{sid}", sid, path=spec.get("path"), writer=writer,
                       slo=spec.get("slo") or (f"{spec['slo_days']}d" if spec.get("slo_days") else None))
        for path in re.findall(r"[\w./-]+\.(?:ya?ml|sqlite|json)", str(spec.get("path") or "")):
            g.edge(snode, "stored_at", _file(g, root, path))
        if isinstance(writer, str) and writer in ids:
            g.edge(g.node(f"agent:{writer}"), "writes", snode)
        elif isinstance(writer, str):
            for stem in WRITER_WORKFLOW_RX.findall(writer):
                wid = workflow_id(g.hub, stem)
                if wid in g.nodes:
                    g.edge(wid, "writes", snode)
    for a in agents:
        nwo = str(a.get("repo") or g.hub)
        aid = g.node(f"agent:{a['id']}", a["id"], agent_kind=a.get("kind"), category=a.get("category"),
                     model=a.get("model"), trigger=a.get("trigger"), where=a.get("where"),
                     per_run_usd=(a.get("budget") or {}).get("per_run_usd"), run_record=a.get("run_record"),
                     gaps=a.get("gaps"), local_entry=a.get("local_entry"))
        g.edge(g.node(repo_id(nwo), nwo), "owns", aid)
        where = str(a.get("where") or "")
        m = WORKFLOW_FILE_RX.match(where)
        if m:
            g.edge(aid, "defined_in", g.node(workflow_id(nwo, m.group(1))))
        elif where and nwo.lower() == g.hub.lower():
            g.edge(aid, "defined_in", _file(g, root, where))
        for sid in (a.get("reads") or {}):
            g.edge(aid, "reads", g.node(f"source:{sid}"))
        switch = a.get("switch") if isinstance(a.get("switch"), dict) else {}
        if switch.get("loop"):
            g.edge(aid, "part_of", g.node(f"loop:{switch['loop']}"))
        if switch.get("variable"):
            g.edge(aid, "gated_by", g.node(f"var:{switch['variable']}"))
        for other in a.get("counterparts") or []:
            if other in ids:
                g.edge(aid, "twin_of", g.node(f"agent:{other}"))
    g.note_input("_data/agents.yml", True, len(agents))


def _headers(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines()[:30]:
        m = HEADER_RX.match(line)
        if m:
            out[m.group(1).strip().lower()] = m.group(2).strip()
    return out


def build_governance(g: Graph, root: Path, fleet: dict) -> None:
    feats = _yaml(g, root, "features/features.yml")
    rows = feats.get("features") if isinstance(feats, dict) else feats
    n = 0
    for f in rows if isinstance(rows, list) else []:
        if not isinstance(f, dict) or not f.get("id"):
            continue
        fid = g.node(f"feature:{f['id']}", f.get("title"), status=f.get("status"), surface=f.get("surface"))
        for req in f.get("prd") or []:
            if REQ_RX.match(str(req)):
                g.edge(fid, "serves", g.node(f"req:{req}"))
        link = f.get("link")
        if isinstance(link, str) and link.startswith("/"):  # a ui feature's link is its console page
            g.edge(fid, "implemented_in", g.node(f"page:/{link.strip('/')}"))
        elif isinstance(link, str) and link and not link.startswith("http"):
            g.edge(fid, "implemented_in", _file(g, root, link))
        if isinstance(f.get("docs"), str) and not f["docs"].startswith("http"):
            g.edge(fid, "documented_in", _file(g, root, f["docs"].split("#", 1)[0]))
        for rel, key in (("tested_by", "tests"), ("verified_by", "scenarios")):
            for path in f.get(key) or []:
                if isinstance(path, str):  # `{na: reason}` records why a feature has none
                    g.edge(fid, rel, _file(g, root, path))
        n += 1
    if rows is not None:
        g.note_input("features/features.yml", True, n)

    road = _yaml(g, root, "_data/roadmap.yml")
    n = 0
    for r in road if isinstance(road, list) else []:
        if not isinstance(r, dict) or not r.get("id"):
            continue
        rid = g.node(f"roadmap:{r['id']}", r.get("title"), status=r.get("status"), priority=r.get("priority"))
        nwo = nwo_of(r.get("repo_url"))
        if nwo:
            g.edge(rid, "targets", g.node(repo_id(nwo), nwo))
        m = ISSUE_URL_RX.search(str(r.get("issue_url") or ""))
        if m:
            g.edge(rid, "tracked_by", g.node(f"issue:{m.group(1).lower()}#{m.group(2)}"))
        n += 1
    if road is not None:
        g.note_input("_data/roadmap.yml", True, n)

    for kind, folder in (("adr", "docs/adr"), ("amendment", "docs/amendments")):
        d = root / folder
        files = sorted(d.glob("[0-9][0-9][0-9][0-9]-*.md")) if d.is_dir() else []
        n = 0
        for p in files:
            if p.name.startswith("0000-"):
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            head = _headers(text)
            title = re.sub(r"^#\s*(?:ADR\s+)?\d{4}\s*[—-]\s*", "", text.split("\n", 1)[0]).strip()
            nid = g.node(f"{kind}:{p.name[:4]}", title[:160], status=head.get("status"),
                         file=p.relative_to(root).as_posix())
            m = re.search(r"#(\d+)", head.get("tracking", ""))
            if m:
                g.edge(nid, "tracked_by", g.node(f"issue:{g.hub.lower()}#{m.group(1)}"))
            refs = head.get("affects", "") if kind == "amendment" else ""
            for fid in sorted(set(FEATURE_REF_RX.findall(refs))):
                if f"feature:{fid}" in g.nodes:
                    g.edge(nid, "affects", f"feature:{fid}")
            for req in sorted(set(REQ_REF_RX.findall(refs))):
                if f"req:{req}" in g.nodes:
                    g.edge(nid, "affects", f"req:{req}")
            n += 1
        g.note_input(folder, d.is_dir(), n)


# ------------------------------------------------------------------ surfaces
CMD_RX = re.compile(r"^\s{4}([a-z][a-z0-9-]*)(?:\|[-a-z]+)*\)\s+cmd_\w+", re.M)
ROUTE_RX = re.compile(r"^@app\.(get|post|put|delete|patch|websocket)\(\s*\"([^\"]+)\"", re.M)
OP_CMD_RX = re.compile(r"(?:DASH_GEN|DASH|TOOLS\s*/\s*\"dash\"\))\s*,\s*\"([a-z][a-z0-9-]*)\"")
# dash-gen subcommands that are spelled differently from the `tools/dash` command that runs them
GEN_TO_CMD = {"harnesses": "harnesses", "ai-usage": "gen", "health": "monitor", "targets": "gen", "readme": "gen",
              "scout": "scout", "issues": "issues", "ai-run": "ai"}


def _dict_literal(tree: ast.Module, name: str) -> ast.Dict | None:
    for node in tree.body:
        target = None
        if isinstance(node, ast.AnnAssign):
            target = node.target
        elif isinstance(node, ast.Assign):
            target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == name and isinstance(node.value, ast.Dict):
            return node.value
    return None


def _op_command(src: str, tree: ast.Module, value: ast.AST, cmds: set[str]) -> str | None:
    """The dash command an operation's argv runs, read from its source."""
    seg = ast.get_source_segment(src, value) or ""
    if isinstance(value, ast.Name):
        fn = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == value.id), None)
        seg = ast.get_source_segment(src, fn) or "" if fn else ""
    elif not isinstance(value, ast.Lambda):
        return None
    for word in OP_CMD_RX.findall(seg):
        word = word if word in cmds else GEN_TO_CMD.get(word)
        if word in cmds:
            return word
    return None


def _route_key(path: str) -> str:
    return re.sub(r"\{[^}]*\}", "{}", path.split("?", 1)[0]).rstrip("/") or "/"


def _same_shape(a: str, b: str) -> bool:
    """Two route keys name one route when they match segment by segment, `{}` standing for any one segment."""
    xs, ys = a.split("/"), b.split("/")
    return len(xs) == len(ys) and all(x == y or "{}" in (x, y) for x, y in zip(xs, ys))


def _literals(fn: ast.AST) -> set[str]:
    """Every `/api/…` path a function names, f-string placeholders as `{}`."""
    out = set()
    parts: set[int] = set()  # the constant pieces of an f-string are not paths of their own
    for node in ast.walk(fn):
        if isinstance(node, ast.JoinedStr):
            parts.update(id(v) for v in node.values)
            text = "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in node.values)
            if text.startswith("/api/"):
                out.add(_route_key(text))
    for node in ast.walk(fn):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in parts \
                and node.value.startswith("/api/"):
            out.add(_route_key(node.value))
    return out


def _is_tool(fn: ast.FunctionDef) -> bool:
    for dec in fn.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Attribute) and target.attr == "tool":
            return True
    return False


def mcp_tools(src: str) -> dict[str, dict]:
    """tool name -> {routes, write} from the layer's source: the `/api/` paths
    each tool's body names, following calls to helpers and to other tools."""
    tree = ast.parse(src)
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    direct = {name: _literals(fn) for name, fn in fns.items()}
    calls = {name: {c.func.id for c in ast.walk(fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                    and c.func.id in fns and c.func.id != name} for name, fn in fns.items()}
    for _ in range(4):  # helpers of helpers; the layer nests two deep
        for name in fns:
            for callee in calls[name]:
                direct[name] |= direct[callee]
    writes = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            for sub in ast.walk(node):
                if isinstance(sub, ast.FunctionDef) and _is_tool(sub):
                    writes.add(sub.name)
    return {name: {"routes": sorted(direct[name]), "write": name in writes} for name, fn in fns.items() if _is_tool(fn)}


def build_surfaces(g: Graph, root: Path, fleet: dict) -> None:
    dash = _text(g, root, "tools/dash")
    cmds = set(CMD_RX.findall(dash or ""))
    for c in sorted(cmds):
        g.node(f"cmd:{c}", f"dash {c}")
    if dash is not None:
        g.note_input("tools/dash", True, len(cmds))

    core = _text(g, root, "tools/console/core.py")
    if core is not None:
        try:
            tree = ast.parse(core)
            ops = _dict_literal(tree, "OPS")
        except SyntaxError as exc:
            tree, ops = None, None
            g.note_input("tools/console/core.py", True, why=f"unparseable ({exc.msg})")
        n = 0
        for key, value in zip(ops.keys, ops.values) if ops else []:
            if not (isinstance(key, ast.Constant) and isinstance(value, ast.Call)):
                continue
            kw = {k.arg: k.value for k in value.keywords}
            title = kw["title"].value if isinstance(kw.get("title"), ast.Constant) else None
            group = kw["group"].value if isinstance(kw.get("group"), ast.Constant) else None
            oid = g.node(f"op:{key.value}", title, group=group, confirm=("remote" in kw or "confirm" in kw) or None)
            cmd = _op_command(core, tree, kw.get("argv"), cmds)
            if cmd:
                g.edge(oid, "runs", f"cmd:{cmd}")
            n += 1
        if ops:
            g.note_input("tools/console/core.py OPS", True, n)

    app = _text(g, root, "tools/console/app.py")
    routes: dict[str, list[str]] = {}
    for method, path in ROUTE_RX.findall(app or ""):
        nid = g.node(f"route:{method.upper()} {path}", f"{method.upper()} {path}")
        routes.setdefault(_route_key(path), []).append(nid)
    if app is not None:
        g.note_input("tools/console/app.py", True, sum(len(v) for v in routes.values()))

    layer = _text(g, root, "tools/console/mcp_layer/server.py")
    if layer is not None:
        try:
            tools = mcp_tools(layer)
        except SyntaxError as exc:
            tools = {}
            g.note_input("tools/console/mcp_layer/server.py", True, why=f"unparseable ({exc.msg})")
        for name, info in sorted(tools.items()):
            tid = g.node(f"tool:{name}", name, write=info["write"] or None)
            for key in info["routes"]:
                # a write tool reaches the route's writing methods, a read tool its GET; a path the tool
                # builds (`/api/index/{mode}`) reaches every route of that shape
                for rkey, rids in routes.items():
                    if rkey != key and not _same_shape(key, rkey):
                        continue
                    for rid in rids:
                        if info["write"] or rid.startswith("route:GET "):
                            g.edge(tid, "calls", rid)
        if tools:
            g.note_input("tools/console/mcp_layer/server.py", True, len(tools))

    snap = _text(g, root, "tools/console/snapshot.py")
    if snap is not None:
        try:
            pages = _dict_literal(ast.parse(snap), "STATIC_ROUTES")
        except SyntaxError:
            pages = None
        n = 0
        for key, value in zip(pages.keys, pages.values) if pages else []:
            title = value.elts[0] if isinstance(value, ast.Tuple) and value.elts else None
            if isinstance(key, ast.Constant) and isinstance(title, ast.Constant):
                g.node(f"page:/{key.value}", title.value)
                n += 1
        g.note_input("tools/console/snapshot.py STATIC_ROUTES", bool(pages), n)


BUILDERS = {"registry": build_registry, "workflows": build_workflows, "switches": build_switches,
            "fleet": build_fleet, "agents": build_agents, "governance": build_governance, "surfaces": build_surfaces}


def load_fleet(root: Path) -> dict:
    try:
        return yaml.safe_load((root / "_data" / "fleet.yml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def build(root: Path | str = ROOT_DEFAULT, parts: tuple[str, ...] = PARTS) -> Graph:
    root = Path(root)
    fleet = load_fleet(root)
    g = Graph(str(((fleet.get("hub") or {}).get("repo")) or HUB_DEFAULT))
    for part in parts:
        if part not in BUILDERS:
            raise KeyError(f"unknown part {part!r} (known: {', '.join(PARTS)})")
        BUILDERS[part](g, root, fleet)
    return g


# --------------------------------------------------------------------------- #
# checks
# --------------------------------------------------------------------------- #
# id -> (severity, what it means, the fix)
RULES: dict[str, tuple[str, str, str]] = {
    "dangling-edge": (
        "error", "an edge names a node that no builder declared",
        "a builder bug: declare the node where the edge is added"),
    "source-without-writer": (
        "warn", "an agent reads a data source that nothing is declared to write",
        "give it a writer in _data/fleet.yml harness.sources, or stop reading it (constitution § 29.4)"),
    "loop-without-workflow": (
        "warn", "a switched hub loop names a workflow file the hub does not have",
        "fix the `workflow:` path in _data/fleet.yml switches.loops, or remove the entry"),
    "scheduled-without-loop": (
        "warn", "a hub workflow runs on a cron and no entry of the switches map runs it",
        "add it to _data/fleet.yml switches.loops (constitution § 17.1), or record its exemption there"),
    "uses-missing": (
        "warn", "a workflow or action calls a hub action or workflow that does not exist",
        "fix the `uses:` path"),
    "feature-file-missing": (
        "warn", "a feature names code, a doc, a test or a scenario that is not in the checkout",
        "fix the path in features/features.yml"),
    "route-without-tool": (
        "info", "a console API route that returns data has no MCP tool that calls it",
        "add a read tool over it in tools/console/mcp_layer/server.py, or list it in ROUTE_EXEMPT with the reason"),
    "command-without-operation": (
        "info", "a dash command no console operation runs: the browser and an agent over MCP cannot start it",
        "add an operation to tools/console/core.py OPS, or list it in COMMAND_EXEMPT with the reason"),
}

# Routes a person's browser needs and an agent does not, with why. A key ending
# in `*` is a prefix; any other is the exact path.
ROUTE_EXEMPT = {
    "/api": "the route index",
    "/api/health": "liveness; console_overview reports it",
    "/api/keys": "the page's key bindings",
    "/api/theme": "the page's colours",
    "/api/capabilities": "which tools this host has; console_overview and ops_list cover it",
    "/api/auth*": "credentials stay out of an agent's reach (§ 11.7)",
    "/api/github/oauth*": "a person's sign-in flow",
    "/api/github/status": "a person's sign-in state",
    "/api/tui*": "the terminal page's pty",
    "/api/site*": "the public profile pages' content",
    "/api/live/stream": "a server-sent-event stream; live_snapshot reads the same state",
    "/api/workflows*": "fleet_workflows and workflow_lint read the same atlas from the checkout, with no console",
    "/api/graph": "fleet_graph serves the same view from the checkout, with no console",
    "/api/learn": "fleet_learning serves the same view from the lake, with no console",
}


def route_exempt(path: str) -> str | None:
    for key, why in ROUTE_EXEMPT.items():
        if path == key or (key.endswith("*") and path.startswith(key[:-1])):
            return why
    return None


# Commands that are a surface themselves, or act on this machine, with why.
COMMAND_EXEMPT = {
    "console": "starts the console itself", "serve": "starts the console's static build",
    "tui": "starts the terminal surface", "mcp": "starts the MCP server",
    "gen": "the generic generator runner; each generator has its own operation",
    "foreach": "runs an arbitrary shell command in every submodule", "run": "runs a script from the scripts submodule",
    "host": "changes the forge host", "infra": "changes infrastructure (OpenTofu); needs --yes at a terminal",
    "up": "starts this machine's containers", "down": "stops this machine's containers",
    "protect": "changes branch protection, which § 11.2 keeps off every surface",
    "new": "scaffolds a new project interactively", "sync": "moves submodule pointers in this checkout",
    "ops": "runs the console's operations from a terminal: it is that surface (tools/console/ops_cli.py)",
}


def _finding(rule: str, node: str, message: str) -> dict:
    return {"rule": rule, "severity": RULES[rule][0], "node": node, "message": message}


def check(g: Graph) -> list[dict]:
    out: list[dict] = []

    def add(rule: str, node: str, message: str) -> None:
        out.append(_finding(rule, node, message))

    def tail(nid: str) -> str:
        return nid.split(":", 2)[-1]

    for (s, rel, d) in sorted(g.edges):
        for end in (s, d):
            if end not in g.nodes:
                add("dangling-edge", end, f"{s} —{rel}→ {d}")
    hub = g.hub.lower()
    for n in sorted(g.nodes.values(), key=lambda n: n["id"]):
        nid, kind, attrs, label = n["id"], n["kind"], n["attrs"], n["label"]
        sources = [(rel, src) for rel, src in g.into(nid)]
        if kind == "source" and not attrs.get("writer"):
            readers = sum(1 for rel, _ in sources if rel == "reads")
            if readers:
                add("source-without-writer", nid, f"{label} is read by {readers} agent(s) and has no writer")
        if kind == "loop" and str(attrs.get("repo") or "").lower() == hub:
            for rel, dst in g.out(nid):
                if rel == "runs" and "file" not in g.nodes[dst]["attrs"]:
                    add("loop-without-workflow", nid, f"{label} runs {tail(dst)}.yml, which the hub does not have")
        if kind == "workflow" and nid.startswith(f"workflow:{hub}:") and attrs.get("crons"):
            if not any(rel == "runs" and src.startswith("loop:") for rel, src in sources):
                crons = ", ".join(attrs["crons"])
                add("scheduled-without-loop", nid, f"{attrs.get('file')} runs on {crons} with no switches.loops entry")
        if kind in ("workflow", "action") and nid.split(":")[1] == hub and "file" not in attrs:
            callers = sorted(tail(src) for rel, src in sources if rel == "uses")
            if callers:
                add("uses-missing", nid, f"called by {', '.join(callers[:4])} and not in the hub")
        if kind == "file" and attrs.get("exists") is False:
            feats = sorted({tail(src) for _, src in sources if src.startswith("feature:")})
            if feats:
                add("feature-file-missing", nid, f"{label} is named by {', '.join(feats[:4])}")
        if kind == "route" and label.startswith("GET /api") and not sources:
            if route_exempt(label.split(" ", 1)[1]) is None:
                add("route-without-tool", nid, f"{label} is served to the page and reachable by no MCP tool")
        if kind == "cmd" and not sources and tail(nid) not in COMMAND_EXEMPT:
            add("command-without-operation", nid, f"`tools/{label}` has no console operation")
    return out


def tally(findings: list[dict]) -> dict:
    out = {"error": 0, "warn": 0, "info": 0}
    for f in findings:
        out[f["severity"]] += 1
    return out


def check_doc(g: Graph) -> dict:
    findings = check(g)
    by_rule = Counter(f["rule"] for f in findings)
    return {"tally": tally(findings), "by_rule": dict(sorted(by_rule.items())), "findings": findings,
            "rules": [{"id": r, "severity": s, "means": m, "fix": fx} for r, (s, m, fx) in RULES.items()]}


# --------------------------------------------------------------------------- #
# the view every surface serves: /api/graph, the MCP's fleet_graph, the page
# --------------------------------------------------------------------------- #
ACTIONS = ("summary", "find", "show", "impact", "lineage", "path", "check")
_CACHE: dict[str, tuple[float, Graph]] = {}
CACHE_S = 30.0  # the console polls; the checkout does not change that fast


def cached(root: Path | str = ROOT_DEFAULT, now: float | None = None) -> Graph:
    import time
    now = time.monotonic() if now is None else now
    key = str(Path(root).resolve())
    hit = _CACHE.get(key)
    if hit is None or now - hit[0] > CACHE_S:
        hit = _CACHE[key] = (now, build(root))
    return hit[1]


def view(root: Path | str = ROOT_DEFAULT, action: str = "summary", node: str = "", to: str = "", text: str = "",
         kind: str = "", depth: int = 3, limit: int = 40, graph: Graph | None = None) -> dict:
    """One question of the graph as one document. Raises KeyError for a node
    that does not resolve and ValueError for a bad argument; the caller turns
    those into its own kind of refusal."""
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {', '.join(ACTIONS)}")
    if kind and kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(sorted(KINDS))}")
    depth, limit = max(1, min(int(depth), 6)), max(1, min(int(limit), 500))
    g = graph or cached(root)
    if action == "summary":
        s = g.summary()
        return s | {"kinds": KINDS, "rels": {r: {"means": m, "dependent": d} for r, (m, d) in RELS.items()},
                    "check": check_doc(g)["tally"]}
    if action == "find":
        return g.find(text, kind or None, limit)
    if action == "check":
        doc = check_doc(g)
        doc["findings"] = doc["findings"][:limit] if limit < len(doc["findings"]) else doc["findings"]
        return doc
    if not node:
        raise ValueError(f"`{action}` needs a node")
    if action == "show":
        doc = g.show(node)
        for side in ("out", "in"):
            doc[side] = {rel: {"count": len(rows), "nodes": rows[:limit]} for rel, rows in doc[side].items()}
        return doc
    if action == "path":
        if not to:
            raise ValueError("`path` needs `to`")
        return g.path(node, to)
    return g.walk(node, action, depth, limit)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _print_rows(rows: list[dict]) -> None:
    for r in rows:
        extra = f"  depth {r['depth']} via {r['via']['rel']}" if "depth" in r else ""
        print(f"  {r['id']:<64} {r['label'][:60] if r['label'] != r['id'].split(':', 1)[1] else ''}{extra}".rstrip())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="dash graph",
        description="The fleet graph: one model of what the control plane manages and how it relates. "
                    "Reads the checkout; writes nothing unless --out is given.")
    ap.add_argument("--root", default=str(ROOT_DEFAULT), help=argparse.SUPPRESS)
    ap.add_argument("--json", action="store_true", help="print JSON")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("summary", help="node and edge counts by kind, and the inputs read (the default)")
    p = sub.add_parser("find", help="nodes whose id or label contains the text")
    p.add_argument("text", nargs="?", default="")
    p.add_argument("--kind", choices=sorted(KINDS))
    p.add_argument("--limit", type=int, default=50)
    p = sub.add_parser("show", help="one node with every edge in and out")
    p.add_argument("node")
    for name, text in (("impact", "what depends on a node: what breaks or goes stale when it changes"),
                       ("lineage", "what a node depends on")):
        p = sub.add_parser(name, help=text)
        p.add_argument("node")
        p.add_argument("--depth", type=int, default=3)
    p = sub.add_parser("path", help="the shortest chain of relations between two nodes")
    p.add_argument("a")
    p.add_argument("b")
    p = sub.add_parser("check", help="findings; exits 1 on an error, or on a warning with --strict")
    p.add_argument("--strict", action="store_true")
    p.add_argument("--rule", choices=sorted(RULES))
    p = sub.add_parser("export", help="the whole graph as JSON, to stdout or --out FILE")
    p.add_argument("--out")
    for name, parser in sub.choices.items():  # `--json` reads the same before or after the subcommand
        parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="print JSON")
    a = ap.parse_args(argv)
    g = build(a.root)
    cmd = a.cmd or "summary"
    try:
        if cmd == "summary":
            doc = g.summary()
            if not a.json:
                print(f"fleet graph · {doc['nodes']} nodes · {doc['edges']} edges · hub {doc['hub']}")
                print("  nodes  " + " · ".join(f"{k} {v}" for k, v in doc["by_kind"].items()))
                print("  edges  " + " · ".join(f"{k} {v}" for k, v in doc["by_rel"].items()))
                for i in doc["inputs"]:
                    state = "missing" if not i["present"] else (i["problem"] or f"{i['count']} read")
                    print(f"  input  {i['path']}: {state}")
                return 0
        elif cmd == "find":
            doc = g.find(a.text, a.kind, a.limit)
            if not a.json:
                print(f"{doc['count']} node(s)")
                _print_rows(doc["nodes"])
                return 0
        elif cmd == "show":
            doc = g.show(a.node)
            if not a.json:
                n = doc["node"]
                print(f"{n['id']} — {n['label']}")
                for k, v in sorted(n["attrs"].items()):
                    print(f"  {k}: {v}")
                for title, side in (("out", doc["out"]), ("in", doc["in"])):
                    for rel, rows in sorted(side.items()):
                        arrow = f"—{rel}→" if title == "out" else f"←{rel}—"
                        print(f"  {arrow} {len(rows)}")
                        for r in rows[:25]:
                            print(f"      {r['id']}")
                        if len(rows) > 25:
                            print(f"      … {len(rows) - 25} more (--json for all)")
                return 0
        elif cmd in ("impact", "lineage"):
            doc = g.walk(a.node, cmd, a.depth)
            if not a.json:
                verb = "depend on" if cmd == "impact" else "are needed by"
                print(f"{doc['count']} node(s) {verb} {doc['node']['id']} within {a.depth} step(s): "
                      + " · ".join(f"{k} {v}" for k, v in doc["by_kind"].items()))
                _print_rows(doc["nodes"])
                return 0
        elif cmd == "path":
            doc = g.path(a.a, a.b)
            if not a.json:
                if doc["length"] is None:
                    print(f"no path between {doc['from']} and {doc['to']}")
                    return 1
                print(doc["from"])
                for h in doc["hops"]:
                    arrow = f"—{h['rel']}→" if h["direction"] == "->" else f"←{h['rel']}—"
                    print(f"  {arrow} {h['to']}")
                return 0
        elif cmd == "check":
            doc = check_doc(g)
            if a.rule:
                doc["findings"] = [f for f in doc["findings"] if f["rule"] == a.rule]
                doc["tally"] = tally(doc["findings"])
                doc["by_rule"] = {a.rule: len(doc["findings"])}
            t = doc["tally"]
            failed = t["error"] > 0 or (a.strict and t["warn"] > 0)
            if not a.json:
                for f in doc["findings"]:
                    print(f"  {f['severity']:<5} {f['rule']:<26} {f['message']}")
                print(f"graph check: {t['error']} error(s), {t['warn']} warning(s), {t['info']} note(s)")
                return 1 if failed else 0
            print(json.dumps(doc, indent=1, default=str))
            return 1 if failed else 0
        elif cmd == "export":
            text = json.dumps(g.to_doc(), indent=1, default=str)
            if a.out:
                Path(a.out).write_text(text + "\n", encoding="utf-8")
                print(f"wrote {a.out} ({len(g.nodes)} nodes, {len(g.edges)} edges)")
            else:
                print(text)
            return 0
    except (KeyError, ValueError) as exc:
        print(f"dash graph: {exc.args[0] if exc.args else exc}", file=sys.stderr)
        return 2
    print(json.dumps(doc, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
