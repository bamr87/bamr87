#!/usr/bin/env python3
"""Fleet nodes: WHERE each hub workload runs (ADR 0003, docs/PLATFORM.md).

The model is `_data/fleet.yml` `nodes:`. The edge node (the Mac) holds the
working tree and every service that bind-mounts it; workload nodes (forge)
carry the always-on planes and the batch work. This module is the one
implementation the CLI, the console and the MCP server share:

  load_model()      the `nodes:` block, checked for shape
  compose_facts()   docker-compose.yml reduced to what placement needs: each
                    service's profiles, published ports, named volumes, bind
                    mounts and the services it calls (depends_on, `name:port`
                    in its environment and command, and in the repo config
                    files it mounts)
  resolve()         service -> nodes, refusing an edge-bound service off the
                    edge, a workload service that calls back to the edge, a
                    durable volume on a node without a backup target, and a
                    link port that collides
  plan_rows()       the resolution joined with the containers running now
  overlay_text() /  what `gen` writes per node: a compose overlay that parks
  tfvars() /        every service placed elsewhere, OpenTofu's inputs, and
  inventory()       the Ansible inventory of the workload nodes

Read-only by default (constitution § 10.6): status and plan probe with fixed
argv and time limits, `gen` writes only .fleet/nodes/ (gitignored), and
`infra apply` refuses without --yes and a saved plan made from the current
inputs. Nothing here ever starts, stops or deletes a container.

    python3 -m fleetcore.nodes status|plan|gen|key [--assume-enabled] [--json]
    python3 -m fleetcore.nodes infra plan|apply [node] [--yes]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from . import host as dockerhost

ROOT = Path(__file__).resolve().parents[2]
FLEET_YML = ROOT / "_data" / "fleet.yml"
COMPOSE_YML = ROOT / "docker-compose.yml"
OUT_DIR = ROOT / ".fleet" / "nodes"

EVERY = "every"
# The profile a service placed on another node is parked under: compose never
# starts it unless someone names that profile on purpose.
PARKED = "elsewhere"
# A bind of these makes a service a node AGENT (it reads the host it runs on),
# not an edge-bound one: Filebeat on forge ships forge's containers.
AGENT_MOUNTS = ("/var/run/docker.sock", "/var/lib/docker/containers")
# Repo paths whose files are scanned for `service:port` references. The
# submodules' content is not hub configuration, and `.` is the whole tree.
SCAN_LIMIT_FILES, SCAN_LIMIT_BYTES = 200, 256 * 1024

_VAR = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*(?::?-([^}]*))?\}")
_NAMED_VOLUME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _defaults(text: str) -> str:
    """`${VAR:-default}` -> `default` (and `${VAR}` -> ''): what compose uses when .env is silent."""
    return _VAR.sub(lambda m: m.group(1) or "", text)


class _ComposeLoader(yaml.SafeLoader):
    """docker-compose.yml with compose's merge tags, read as plain values."""


def _tagged(loader: yaml.SafeLoader, node: yaml.Node):
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    return None if node.value in ("", "null", "~", "Null", "NULL") else loader.construct_scalar(node)


_ComposeLoader.add_constructor("!override", _tagged)
_ComposeLoader.add_constructor("!reset", _tagged)


# --------------------------------------------------------------------------- #
# The model
# --------------------------------------------------------------------------- #
@dataclass
class Host:
    name: str
    role: str
    docker: str
    enabled: bool = False
    ssh: str | None = None
    checkout: str | None = None
    backup: str | None = None
    runtime: str = "compose"
    raw: dict = field(default_factory=dict)


# What a node runs its services with. `kubernetes` (a cluster context, the
# services rendered from the same compose file) is the scale-out target of
# ADR 0003's phase 10; until it exists a node that asks for it is refused.
RUNTIMES = ("compose",)


@dataclass
class Model:
    edge: str
    hosts: dict[str, Host]
    services: dict[str, str]
    durable: set[str]
    link: dict
    infra: dict
    project: str = "fleet"
    network: str = "fleet"
    errors: list[str] = field(default_factory=list)

    def workload(self) -> list[Host]:
        return [h for h in self.hosts.values() if h.name != self.edge]


def load_model(fleet: dict | None = None) -> Model:
    """`nodes:` from fleet.yml (or the dict given). Shape problems are collected
    in `.errors`, never raised, so `status` can still show what it can."""
    if fleet is None:
        fleet = yaml.safe_load(FLEET_YML.read_text(encoding="utf-8")) or {}
    raw = fleet.get("nodes") or {}
    containers = fleet.get("containers") or {}
    errors: list[str] = []
    hosts: dict[str, Host] = {}
    for name, h in (raw.get("hosts") or {}).items():
        h = h or {}
        hosts[name] = Host(name=name, role=str(h.get("role") or ""), docker=str(h.get("docker") or ""),
                           enabled=bool(h.get("enabled", h.get("role") == "edge")), ssh=h.get("ssh"),
                           checkout=h.get("checkout"), backup=h.get("backup"),
                           runtime=str(h.get("runtime") or "compose"), raw=dict(h))
        if hosts[name].runtime not in RUNTIMES:
            errors.append(f"nodes.hosts.{name}: runtime {hosts[name].runtime!r} is not available yet "
                          f"(today: {', '.join(RUNTIMES)}; kubernetes is ADR 0003 phase 10)")
    edge = str(raw.get("edge") or "")
    if edge not in hosts:
        errors.append(f"nodes.edge {edge!r} is not one of nodes.hosts ({', '.join(hosts) or 'none'})")
    for h in hosts.values():
        if (h.role == "edge") != (h.name == edge):
            errors.append(f"nodes.hosts.{h.name}: role {h.role!r}, but nodes.edge is {edge!r} — exactly one edge")
        if not h.docker:
            errors.append(f"nodes.hosts.{h.name}: no `docker:` endpoint")
        if h.name != edge and not h.ssh:
            errors.append(f"nodes.hosts.{h.name}: a workload node needs an `ssh:` alias (SSH is the only API)")
    services = {str(k): str(v) for k, v in (raw.get("services") or {}).items()}
    for svc, node in services.items():
        if node != EVERY and node not in hosts:
            errors.append(f"nodes.services.{svc}: {node!r} is not a node (or `{EVERY}`)")
    return Model(edge=edge, hosts=hosts, services=services, durable=set(raw.get("durable_volumes") or []),
                 link=raw.get("link") or {}, infra=raw.get("infra") or {},
                 project=str(containers.get("project") or "fleet"),
                 network=str(containers.get("network") or "fleet"), errors=errors)


# --------------------------------------------------------------------------- #
# What docker-compose.yml says about each service
# --------------------------------------------------------------------------- #
@dataclass
class Service:
    name: str
    profiles: list[str]
    ports: list[int]
    volumes: list[str]
    deps: set[str]
    edge_bound: str | None  # why it can never leave the edge, else None
    agent: bool  # mounts the Docker socket / containers dir of its host
    requires: list[str]  # repo paths a node's checkout must hold


def published_ports(spec) -> list[int]:
    """Host ports a `ports:` entry publishes, at their .env-silent defaults."""
    if isinstance(spec, dict):
        published = spec.get("published")
        if published is None:
            return []
        text = _defaults(str(published))
    else:
        parts = _defaults(str(spec)).split("/")[0].split(":")
        if len(parts) < 2:
            return []  # a container-only port: Docker picks the host side
        text = parts[-2]
    if "-" in text:
        lo, _, hi = text.partition("-")
        return list(range(int(lo), int(hi) + 1)) if lo.isdigit() and hi.isdigit() else []
    return [int(text)] if text.isdigit() else []


def _mount(spec, declared: set[str]) -> tuple[str, str]:
    """(kind, source) for one `volumes:` entry: kind is volume|tree|repo|agent|host."""
    if isinstance(spec, dict):
        source = _defaults(str(spec.get("source") or ""))
        if spec.get("type") == "volume":
            return "volume", source
    else:
        source = _defaults(str(spec)).split(":")[0]
    if source in declared or (_NAMED_VOLUME.match(source) and "/" not in source and source not in (".", "..")):
        return "volume", source
    if source in (".", "./"):
        return "tree", "."
    if source in AGENT_MOUNTS:
        return "agent", source
    if source.startswith(("/", "~", "$")):
        return "host", source
    return "repo", source[2:] if source.startswith("./") else source


def _mentions(text: str, names: set[str], self_name: str) -> set[str]:
    return {n for n in names if n != self_name and re.search(rf"(?<![\w.-]){re.escape(n)}:\d", text)}


def _config_text(rel: str, root: Path) -> str:
    """The text of a mounted repo config file or directory, bounded."""
    if rel.split("/")[0] == "projects":
        return ""
    path = root / rel
    files = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())[:SCAN_LIMIT_FILES] \
        if path.is_dir() else []
    chunks = []
    for f in files:
        try:
            if f.stat().st_size <= SCAN_LIMIT_BYTES:
                chunks.append(f.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n".join(chunks)


def compose_facts(compose: dict | None = None, root: Path | None = None) -> dict[str, Service]:
    root = root or ROOT
    if compose is None:
        compose = yaml.load(COMPOSE_YML.read_text(encoding="utf-8"), Loader=_ComposeLoader) or {}
    services = compose.get("services") or {}
    declared = set((compose.get("volumes") or {}).keys())
    names = set(services)
    facts: dict[str, Service] = {}
    for name, s in services.items():
        s = s or {}
        deps_raw = s.get("depends_on") or []
        deps = set(deps_raw if isinstance(deps_raw, list) else deps_raw.keys())
        env = s.get("environment") or []
        text = " ".join(env if isinstance(env, list) else [f"{k}={v}" for k, v in env.items()])
        command = s.get("command") or ""
        text += " " + (" ".join(map(str, command)) if isinstance(command, list) else str(command))
        volumes, requires, why = [], [], []
        agent = False
        for spec in s.get("volumes") or []:
            kind, source = _mount(spec, declared)
            if kind == "volume":
                volumes.append(source)
            elif kind == "tree":
                why.append("bind-mounts the working tree (.)")
            elif kind == "host":
                why.append(f"bind-mounts {source} from the edge host")
            elif kind == "agent":
                agent = True
            else:
                requires.append(source)
                text += "\n" + _config_text(source, root)
        deps |= _mentions(text, names, name)
        ports = sorted({p for spec in s.get("ports") or [] for p in published_ports(spec)})
        facts[name] = Service(name=name, profiles=list(s.get("profiles") or []), ports=ports, volumes=volumes,
                              deps=deps & names, edge_bound="; ".join(why) or None, agent=agent,
                              requires=sorted(set(requires)))
    return facts


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #
@dataclass
class Placement:
    service: str
    wants: str  # what fleet.yml asks: a node, `every`, or the edge by default
    nodes: list[str]  # where it runs once resolved
    reason: str
    deferred: bool = False  # wanted a node that is not enabled


@dataclass
class Forward:
    port: int
    node: str
    service: str


@dataclass
class Resolution:
    placements: dict[str, Placement]
    forwards: list[Forward]
    active: list[str]
    errors: list[str]


def resolve(model: Model, facts: dict[str, Service], assume_enabled: bool = False) -> Resolution:
    errors = list(model.errors)
    for svc in model.services:
        if svc not in facts:
            errors.append(f"nodes.services.{svc}: no such service in docker-compose.yml")
    active = [model.edge] + sorted(h.name for h in model.workload() if h.enabled or assume_enabled)
    placements: dict[str, Placement] = {}
    for name in sorted(facts):
        f = facts[name]
        wants = model.services.get(name, model.edge)
        if wants == EVERY:
            p = Placement(name, wants, list(active), "node agent: one copy on every active node")
        elif wants not in model.hosts:
            p = Placement(name, wants, [model.edge], "unknown node — stays on the edge")
        elif wants not in active:
            p = Placement(name, wants, [model.edge], f"placed on {wants}, which is not enabled", deferred=True)
        elif wants == model.edge:
            p = Placement(name, wants, [model.edge], f.edge_bound or "edge (default)")
        else:
            p = Placement(name, wants, [wants], "placed by nodes.services")
        if f.edge_bound and p.nodes != [model.edge]:
            errors.append(f"{name}: {f.edge_bound} — it can only run on the edge ({model.edge}), "
                          f"not {', '.join(n for n in p.nodes if n != model.edge)}")
        placements[name] = p
    for name, p in placements.items():
        for node in p.nodes:
            if node == model.edge:
                continue  # the edge may call anything, through the link
            for dep in sorted(facts[name].deps):
                if node not in placements[dep].nodes:
                    errors.append(f"{name} on {node} calls {dep}, which runs on {', '.join(placements[dep].nodes)}: "
                                  f"a workload node never calls back to the edge — place {dep} on {node} too")
            for vol in facts[name].volumes:
                if vol in model.durable and not model.hosts[node].backup:
                    errors.append(f"{name} on {node} mounts durable volume {vol}: set nodes.hosts.{node}.backup "
                                  f"(an off-box restic target) before it moves")
    forwards: list[Forward] = []
    edge_ports: dict[int, str] = {}
    for name, p in placements.items():
        if model.edge in p.nodes:
            for port in facts[name].ports:
                edge_ports.setdefault(port, name)
    seen: dict[int, str] = {}
    for name, p in sorted(placements.items()):
        remote = [n for n in p.nodes if n != model.edge]
        if model.edge in p.nodes or not remote:
            continue
        for port in facts[name].ports:
            if port in seen:
                errors.append(f"link: 127.0.0.1:{port} is published by both {seen[port]} and {name}")
            elif port in edge_ports:
                errors.append(f"link: 127.0.0.1:{port} for {name} is already published on the edge by "
                              f"{edge_ports[port]}")
            seen[port] = name
            forwards.append(Forward(port, remote[0], name))
    return Resolution(placements, sorted(forwards, key=lambda f: f.port), active, errors)


def volumes_on(model: Model, facts: dict[str, Service], res: Resolution, node: str) -> tuple[list[str], list[str]]:
    """(durable, rebuildable) full Docker volume names the node holds."""
    names = sorted({v for s, p in res.placements.items() if node in p.nodes for v in facts[s].volumes})
    full = [f"{model.project}_{v}" for v in names]
    return ([f for v, f in zip(names, full) if v in model.durable],
            [f for v, f in zip(names, full) if v not in model.durable])


# --------------------------------------------------------------------------- #
# What `gen` writes
# --------------------------------------------------------------------------- #
GENERATED = "# GENERATED by `tools/dash node gen` from _data/fleet.yml `nodes:` — do not edit (docs/PLATFORM.md)"


def overlay_text(model: Model, facts: dict[str, Service], res: Resolution, node: str) -> str:
    """The compose overlay for one node. On the edge it parks every service
    placed elsewhere; on a workload node it parks everything else, starts the
    placed services without their opt-in profiles, and takes the network and
    the volumes as external — they are OpenTofu's, so `down -v` cannot drop them."""
    lines = [GENERATED, f"# node: {node} ({model.hosts[node].role})", "services:"]
    body = []
    for name in sorted(facts):
        here = node in res.placements[name].nodes
        if not here:
            body += [f"  {name}:", f"    profiles: !override [{PARKED}]"]
        elif node != model.edge and facts[name].profiles:
            body += [f"  {name}:", "    profiles: !reset []"]
    lines += body or ["  {}"]
    if node != model.edge:
        # Compose refuses an external resource that still carries `driver`,
        # which the base file sets, so the overlay resets it.
        durable, rebuildable = volumes_on(model, facts, res, node)
        lines += ["networks:", f"  {model.network}:", "    external: true", f"    name: {model.network}",
                  "    driver: !reset null"]
        if durable or rebuildable:
            lines.append("volumes:")
            for full in sorted(durable + rebuildable):
                short = full[len(model.project) + 1:]
                lines += [f"  {short}:", "    external: true", f"    name: {full}", "    driver: !reset null"]
    return "\n".join(lines) + "\n"


def tfvars(model: Model, facts: dict[str, Service], res: Resolution, node: str) -> dict:
    durable, rebuildable = volumes_on(model, facts, res, node)
    return {"node": node, "docker_host": model.hosts[node].docker, "network": model.network,
            "durable_volumes": durable, "rebuildable_volumes": rebuildable}


def inventory(model: Model) -> dict:
    """The Ansible inventory of the fleet's workload nodes, generated from
    `nodes:` so the host list has one source. Ansible bootstraps a node and
    runs every ordered deploy step on it (ADR 0003); Salt then holds the steady
    state. The edge is not in it: nothing manages the Mac (§ 10.5). A disabled
    node is listed, because it is bootstrapped before it is enabled."""
    hosts = {}
    for h in model.workload():
        hv = {"ansible_host": h.ssh, "fleet_node": h.name, "fleet_enabled": h.enabled, "fleet_runtime": h.runtime,
              "fleet_docker": h.docker, "fleet_checkout": h.checkout, "fleet_backup": h.backup}
        for key in ("capacity", "lan_cidr", "wol_broadcast"):
            if key in h.raw:
                hv[f"fleet_{key}"] = h.raw[key]
        hosts[h.name] = hv
    return {"all": {"children": {"workload": {"hosts": hosts}}}}


def key_line(res: Resolution, public_key: str) -> str:
    """The authorized_keys line for the link key on a workload node: it may open
    exactly the forwarded loopback ports, and nothing else — no shell, no pty.
    Without a permitopen, `port-forwarding` would allow ANY target, so an empty
    forward list is refused rather than rendered."""
    if not res.forwards:
        raise ValueError("no forwarded ports: a link key without permitopen could forward anywhere")
    opts = ["restrict", "port-forwarding", 'command="/bin/false"']
    opts += [f'permitopen="127.0.0.1:{f.port}"' for f in res.forwards]
    return ",".join(opts) + " " + public_key.strip()


# --------------------------------------------------------------------------- #
# Probes (read-only, fixed argv, time-limited)
# --------------------------------------------------------------------------- #
def _run(argv: list[str], timeout: int) -> tuple[int, str]:
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                           start_new_session=True)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 124, str(exc)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def reach(h: Host, timeout: int = 8) -> tuple[bool, str]:
    """Can this node be driven? The edge is local; a workload node answers SSH."""
    if not h.ssh:
        return True, "local"
    rc, out = _run(["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={timeout}", h.ssh, "true"], timeout + 2)
    return rc == 0, "reachable" if rc == 0 else (out.strip().splitlines() or ["unreachable"])[-1][:200]


CAPACITY_PROBE = "nproc; free -b | awk '/^Mem:/{print $2, $7}'; df -PB1 \"$HOME\" | awk 'NR==2{print $2, $4}'"


def capacity(h: Host, timeout: int = 10) -> dict | None:
    """CPUs, memory total/available and home-disk size/free on a workload node."""
    if not h.ssh:
        return None
    rc, out = _run(["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={timeout}", h.ssh, CAPACITY_PROBE],
                   timeout + 2)
    rows = [r.split() for r in out.strip().splitlines()] if rc == 0 else []
    try:
        return {"cpus": int(rows[0][0]), "mem_total": int(rows[1][0]), "mem_available": int(rows[1][1]),
                "disk_total": int(rows[2][0]), "disk_free": int(rows[2][1])}
    except (IndexError, ValueError):
        return None


def running(model: Model, timeout: int = 8) -> tuple[dict[str, set[str]], dict[str, str]]:
    """Where each hub service has a running container now, by node, and an
    error per node that could not be read."""
    where: dict[str, set[str]] = {}
    errors: dict[str, str] = {}
    for h in model.hosts.values():
        boxes, err = dockerhost.list_containers(h.docker, timeout=timeout)
        if err:
            errors[h.name] = err.strip().splitlines()[-1][:200] if err.strip() else "unreachable"
        for b in boxes:
            if b.running and b.labels.get("com.docker.compose.project") == model.project:
                svc = b.labels.get("com.docker.compose.service")
                if svc:
                    where.setdefault(svc, set()).add(h.name)
    return where, errors


def plan_rows(res: Resolution, now: dict[str, set[str]]) -> list[dict]:
    rows = []
    for name, p in sorted(res.placements.items()):
        planned, current = set(p.nodes), now.get(name, set())
        if not current:
            action = "—" if planned == {p.nodes[0]} and p.nodes[0] in res.active[:1] else \
                f"start on {', '.join(sorted(planned - {res.active[0]})) or res.active[0]}"
        elif current == planned:
            action = "in place"
        else:
            parts = []
            if current - planned:
                parts.append(f"stop on {', '.join(sorted(current - planned))}")
            if planned - current:
                parts.append(f"start on {', '.join(sorted(planned - current))}")
            action = " · ".join(parts)
        rows.append({"service": name, "wants": p.wants, "runs_on": p.nodes, "now": sorted(current),
                     "action": action, "reason": p.reason, "deferred": p.deferred})
    return rows


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _gib(n: int | None) -> str:
    return "?" if n is None else f"{n / 2**30:.1f} GiB"


def _context(assume_enabled: bool) -> tuple[Model, dict[str, Service], Resolution]:
    model = load_model()
    facts = compose_facts()
    return model, facts, resolve(model, facts, assume_enabled=assume_enabled)


def cmd_status(args) -> int:
    model, facts, res = _context(args.assume_enabled)
    now, docker_errors = running(model)
    doc = {"edge": model.edge, "nodes": [], "services": plan_rows(res, now), "problems": res.errors}
    for h in model.hosts.values():
        ok, detail = reach(h)
        entry = {"name": h.name, "role": h.role, "docker": h.docker, "enabled": h.enabled or h.name == model.edge,
                 "reachable": ok, "detail": detail, "docker_error": docker_errors.get(h.name),
                 "containers": sum(1 for s in now.values() if h.name in s)}
        if ok and h.ssh:
            entry["capacity"] = capacity(h)
        doc["nodes"].append(entry)
    if args.json:
        print(json.dumps(doc, indent=2, default=list))
        return 0
    print("Fleet nodes — status")
    for n in doc["nodes"]:
        state = n["detail"] if n["reachable"] else f"UNREACHABLE: {n['detail']}"
        cap = n.get("capacity")
        extra = (f" · {cap['cpus']} CPUs, {_gib(cap['mem_available'])} of {_gib(cap['mem_total'])} RAM free, "
                 f"{_gib(cap['disk_free'])} disk free") if cap else ""
        print(f"  {n['name']:<7} {n['role']:<9} {'on ' if n['enabled'] else 'off'}  {n['docker']:<14} {state}"
              f" · {n['containers']} hub services{extra}")
    drift = [r for r in doc["services"] if r["now"] and set(r["now"]) != set(r["runs_on"])]
    print(f"  placement drift: {len(drift)} service(s)" + "".join(
        f"\n    {r['service']}: runs on {', '.join(r['now'])}, placed on {', '.join(r['runs_on'])}" for r in drift))
    for p in res.errors:
        print(f"  ✗ {p}")
    return 1 if res.errors else 0


def cmd_plan(args) -> int:
    model, facts, res = _context(args.assume_enabled)
    now, docker_errors = running(model) if not args.offline else ({}, {})
    rows = plan_rows(res, now)
    infra = {h.name: tfvars(model, facts, res, h.name) for h in model.workload() if h.name in res.active}
    requires = {h.name: sorted({r for s, p in res.placements.items() if h.name in p.nodes for r in facts[s].requires})
                for h in model.workload() if h.name in res.active}
    doc = {"active": res.active, "services": rows, "link": [asdict(f) for f in res.forwards], "infra": infra,
           "checkout_requires": requires, "docker_errors": docker_errors, "problems": res.errors}
    if args.json:
        print(json.dumps(doc, indent=2, default=list))
        return 1 if res.errors else 0
    off = [h.name for h in model.workload() if not h.enabled]
    head = "Fleet nodes — placement plan"
    if off and not args.assume_enabled:
        head += f"  ({', '.join(off)} not enabled: --assume-enabled previews the move)"
    print(head)
    print(f"  {'service':<15} {'wants':<7} {'runs on':<12} {'now':<12} action")
    for r in rows:
        print(f"  {r['service']:<15} {r['wants']:<7} {','.join(r['runs_on']):<12} {','.join(r['now']) or '—':<12} "
              f"{r['action']}" + (f"  ({r['reason']})" if r["deferred"] or r["wants"] == model.edge and
                                  facts[r['service']].edge_bound else ""))
    if res.forwards:
        print(f"  link {model.edge} → " + ", ".join(sorted({f.node for f in res.forwards})) + ": 127.0.0.1 " +
              " ".join(str(f.port) for f in res.forwards))
    for node, tv in infra.items():
        print(f"  infra ({node}, OpenTofu): network {tv['network']} · durable volumes "
              f"{', '.join(tv['durable_volumes']) or 'none'} · rebuildable {len(tv['rebuildable_volumes'])}")
        if requires.get(node):
            print(f"  {node}'s checkout must hold: {', '.join(requires[node])}")
    for node, err in docker_errors.items():
        print(f"  ! {node}: containers unread — {err}")
    for p in res.errors:
        print(f"  ✗ {p}")
    return 1 if res.errors else 0


def cmd_gen(args) -> int:
    model, facts, res = _context(args.assume_enabled)
    if res.errors:
        for p in res.errors:
            print(f"✗ {p}", file=sys.stderr)
        return 1
    files: dict[Path, str] = {OUT_DIR / "inventory.yml": GENERATED + "\n" + yaml.safe_dump(inventory(model),
                                                                                         sort_keys=False)}
    for node in res.active:
        files[OUT_DIR / f"{node}.yml"] = overlay_text(model, facts, res, node)
        if node != model.edge:
            files[OUT_DIR / f"{node}.tfvars.json"] = json.dumps(tfvars(model, facts, res, node), indent=2) + "\n"
    stale = [p for p, text in files.items() if not p.exists() or p.read_text(encoding="utf-8") != text]
    if args.check:
        for p in stale:
            print(f"stale: {p.relative_to(ROOT)}")
        return 1 if stale else 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for p, text in files.items():
        p.write_text(text, encoding="utf-8")
        print(f"wrote {p.relative_to(ROOT)}")
    return 0


def cmd_key(args) -> int:
    model, _, res = _context(True)  # the key is installed BEFORE the node is enabled
    if res.errors:
        for p in res.errors:
            print(f"✗ {p}", file=sys.stderr)
        return 1
    path = Path(os.path.expanduser(str(model.link.get("key") or "~/.ssh/fleet_node_link")))
    pub = path.with_name(path.name + ".pub")
    if not pub.exists():
        print(f"no {pub} yet — create the link key (no passphrase; it can only forward these ports):\n"
              f"  ssh-keygen -t ed25519 -N '' -C fleet-node-link -f {path}", file=sys.stderr)
        return 2
    try:
        print(key_line(res, pub.read_text(encoding="utf-8")))
    except ValueError as exc:
        print(f"✗ {exc} — place a service on a workload node first", file=sys.stderr)
        return 1
    return 0


# --------------------------------------------------------------------------- #
# infra: the OpenTofu layer (infra/node)
# --------------------------------------------------------------------------- #
def infra_paths(model: Model, node: str) -> dict[str, Path]:
    state = Path(os.path.expanduser(str(model.infra.get("state_dir") or "~/.local/state/bamr87-infra")))
    return {"state_dir": state, "state": state / f"{node}.tfstate", "plan": state / f"{node}.tfplan",
            "data_dir": state / node / ".terraform", "vars": OUT_DIR / f"{node}.tfvars.json",
            "module": ROOT / str(model.infra.get("dir") or "infra/node")}


def infra_argv(model: Model, node: str, action: str) -> list[list[str]]:
    """The tofu invocations for an action, as argv lists (never a shell)."""
    tool = str(model.infra.get("tool") or "tofu")
    p = infra_paths(model, node)
    chdir = f"-chdir={p['module']}"
    init = [tool, chdir, "init", "-input=false", "-upgrade", f"-backend-config=path={p['state']}"]
    if action == "plan":
        return [init, [tool, chdir, "plan", "-input=false", f"-var-file={p['vars']}", f"-out={p['plan']}"]]
    if action == "apply":
        return [init, [tool, chdir, "apply", "-input=false", str(p["plan"])]]
    raise ValueError(action)


def cmd_infra(args) -> int:
    model, facts, res = _context(True)  # infrastructure precedes enabling the node
    nodes = [h.name for h in model.workload()]
    node = args.node or (nodes[0] if nodes else "")
    if node not in nodes:
        print(f"infra: {node!r} is not a workload node ({', '.join(nodes) or 'none'})", file=sys.stderr)
        return 2
    if res.errors:
        for p in res.errors:
            print(f"✗ {p}", file=sys.stderr)
        return 1
    tool = str(model.infra.get("tool") or "tofu")
    if not shutil.which(tool):
        print(f"infra: `{tool}` not found — install OpenTofu ≥ {model.infra.get('min_version', '1.8')} "
              f"(brew install opentofu; https://opentofu.org/docs/intro/install/)", file=sys.stderr)
        return 2
    p = infra_paths(model, node)
    want = json.dumps(tfvars(model, facts, res, node), indent=2) + "\n"
    if args.action == "apply":
        if not args.yes:
            print(f"infra apply changes {node} (constitution § 10.5): run `dash infra plan {node}`, read it, "
                  f"then `dash infra apply {node} --yes`", file=sys.stderr)
            return 2
        if not p["plan"].exists() or not p["vars"].exists() or p["vars"].read_text(encoding="utf-8") != want \
                or p["plan"].stat().st_mtime < p["vars"].stat().st_mtime:
            print(f"infra apply: no saved plan for the current inputs — run `dash infra plan {node}` first",
                  file=sys.stderr)
            return 2
    else:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        p["vars"].write_text(want, encoding="utf-8")
    p["state_dir"].mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, TF_DATA_DIR=str(p["data_dir"]), TF_IN_AUTOMATION="1")
    for argv in infra_argv(model, node, args.action):
        rc = subprocess.run(argv, env=env).returncode
        if rc != 0:
            return rc
    if args.action == "plan":
        print(f"saved plan: {p['plan']}  — apply it with: tools/dash infra apply {node} --yes")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dash node", description="Where hub workloads run (docs/PLATFORM.md)")
    sub = ap.add_subparsers(dest="cmd")
    for name, fn, hlp in (("status", cmd_status, "reachability, capacity and placement drift (read-only)"),
                          ("plan", cmd_plan, "what runs where, what would move, the link and the infra (read-only)"),
                          ("gen", cmd_gen, "write .fleet/nodes/<node>.yml + <node>.tfvars.json"),
                          ("key", cmd_key, "print the forwarding-only authorized_keys line for the link key")):
        sp = sub.add_parser(name, help=hlp)
        sp.add_argument("--assume-enabled", action="store_true", help="resolve as if every workload node were on")
        sp.add_argument("--json", action="store_true")
        sp.set_defaults(fn=fn)
        if name == "plan":
            sp.add_argument("--offline", action="store_true", help="skip reading the running containers")
        if name == "gen":
            sp.add_argument("--check", action="store_true", help="exit 1 when a generated file is stale")
    ip = sub.add_parser("infra", help="OpenTofu for a workload node: plan (read-only) | apply --yes")
    ip.add_argument("action", choices=("plan", "apply"))
    ip.add_argument("node", nargs="?")
    ip.add_argument("--yes", action="store_true")
    ip.set_defaults(fn=cmd_infra)
    args = ap.parse_args(argv)
    if not getattr(args, "fn", None):
        args = ap.parse_args(["status", *(argv or [])])
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
