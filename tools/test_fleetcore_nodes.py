#!/usr/bin/env python3
"""
Fixture tests for tools/fleetcore/nodes.py — where each hub workload runs
(ADR 0003, docs/PLATFORM.md).

  * published host ports are read at their .env-silent defaults, ranges
    expanded, container-only ports ignored;
  * a service's facts: named volumes, the services it calls (depends_on,
    `name:port` in env / command / mounted repo config — never submodule
    content), edge-bound binds (the tree, the user's home) vs node-agent binds
    (the Docker socket) vs portable repo files;
  * resolution refuses an edge-bound service off the edge, a workload service
    that calls back to the edge, a durable volume on a node without a backup,
    a link port that collides, an unknown service, node or runtime — and a
    disabled node keeps everything on the edge;
  * the overlays park what runs elsewhere and take the workload node's network
    and volumes as external; `docker compose config` accepts them when the
    CLI is present;
  * the link key may open exactly the forwarded ports and is refused when
    there are none; `infra apply` refuses without --yes and a current plan;
  * the status document (status_doc — what `dash node status --json`, GET
    /api/nodes and the MCP's fleet_nodes return) has one shape; a node that is
    not enabled is never probed (no `ssh`, no `docker -H` in any argv) unless
    --assume-enabled asks; an unreachable node is `unknown` within the probe's
    time limit and nothing is probed after it; `probe=False` runs nothing; an
    unreadable model is a problem in the document, not an exception; drift is
    what runs where it is not placed, measured only on the nodes whose
    containers were read (`drift_read`) and None — not read, never a zero —
    when none was; the TUI's host → node map probes nothing;
  * the COMMITTED fleet.yml + docker-compose.yml resolve cleanly, enabled or not.

No Docker daemon, no network, no OpenTofu (a stub `tofu` records its argv, a
stub subprocess.run answers the probes and records theirs):

    python3 tools/test_fleetcore_nodes.py
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fleetcore import nodes as n  # noqa: E402


def fleet(**over) -> dict:
    doc = {
        "containers": {"project": "fleet", "network": "fleet"},
        "nodes": {
            "edge": "mac",
            "hosts": {
                "mac": {"role": "edge", "docker": "local"},
                "forge": {"role": "workload", "enabled": False, "ssh": "forge", "docker": "ssh://forge",
                          "backup": None},
            },
            "link": {"key": "~/.ssh/fleet_node_link"},
            "services": {"es": "forge", "kibana": "forge", "shipper": "every"},
            "durable_volumes": ["db-data"],
            "infra": {"tool": "tofu", "dir": "infra/node", "state_dir": "~/.local/state/bamr87-infra"},
        },
    }
    for key, value in over.items():
        doc["nodes"][key] = value
    return doc


COMPOSE = {
    "services": {
        "console": {"volumes": [".:/workspace", "${CLAUDE_HOME:-~/.claude}:/home/vscode/.claude:ro"],
                    "environment": ["ES_URL=http://es:9200"], "ports": ["127.0.0.1:${CONSOLE_PORT:-4001}:4001"]},
        "es": {"profiles": ["elk"], "volumes": ["es-data:/usr/share/es"], "ports": ["127.0.0.1:${ES_PORT:-9200}:9200"]},
        "kibana": {"profiles": ["elk"], "depends_on": ["es"], "ports": ["127.0.0.1:5601:5601"]},
        "shipper": {"volumes": ["./tools/shipper.yml:/etc/shipper.yml:ro", "/var/run/docker.sock:/var/run/docker.sock:ro",
                                "shipper-data:/data"]},
        "db": {"volumes": ["db-data:/var/lib/postgresql/data"], "ports": ["127.0.0.1:5432:5432"]},
        "docs": {"volumes": ["./projects/README:/docs:ro"], "command": ["serve", "--dev-addr", "0.0.0.0:8000"]},
    },
    "volumes": {"es-data": {"driver": "local"}, "shipper-data": {"driver": "local"}, "db-data": {"driver": "local"}},
}


def fixture_root() -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "tools").mkdir()
    (root / "tools" / "shipper.yml").write_text("output:\n  hosts: ['es:9200']\n")
    (root / "projects" / "README").mkdir(parents=True)
    (root / "projects" / "README" / "page.md").write_text("talks about db:5432 but is not hub config\n")
    return root


def facts():
    return n.compose_facts(COMPOSE, root=fixture_root())


def test_published_ports():
    assert n.published_ports("127.0.0.1:${ES_PORT:-9200}:9200") == [9200]
    assert n.published_ports("${X:-8001}:8000") == [8001]
    assert n.published_ports("127.0.0.1:4040-4042:4040-4042") == [4040, 4041, 4042]
    assert n.published_ports("8080") == [] and n.published_ports("127.0.0.1:${UNSET}:80") == []
    assert n.published_ports("127.0.0.1:514:514/udp") == [514]
    assert n.published_ports({"target": 80, "published": "8088"}) == [8088]
    assert n.published_ports({"target": 80}) == []


def test_service_facts():
    f = facts()
    assert f["console"].edge_bound and "working tree" in f["console"].edge_bound and "~/.claude" in f["console"].edge_bound
    assert f["console"].deps == {"es"}, f["console"].deps  # from its environment
    assert f["kibana"].deps == {"es"} and f["kibana"].edge_bound is None
    assert f["shipper"].agent and f["shipper"].edge_bound is None, "the Docker socket makes an agent, not an edge pin"
    assert f["shipper"].deps == {"es"}, "a mounted repo config file is scanned for name:port"
    assert f["shipper"].requires == ["tools/shipper.yml"] and f["shipper"].volumes == ["shipper-data"]
    assert f["docs"].deps == set(), "submodule content under projects/ is never scanned"
    assert f["docs"].requires == ["projects/README"]
    assert f["es"].ports == [9200] and f["es"].profiles == ["elk"] and f["es"].volumes == ["es-data"]


def test_disabled_node_keeps_everything_on_the_edge():
    res = n.resolve(n.load_model(fleet()), facts())
    assert res.errors == [] and res.active == ["mac"] and res.forwards == []
    assert res.placements["es"].nodes == ["mac"] and res.placements["es"].deferred
    assert res.placements["shipper"].nodes == ["mac"]


def test_enabled_node_moves_its_services_and_forwards_their_ports():
    res = n.resolve(n.load_model(fleet()), facts(), assume_enabled=True)
    assert res.errors == [], res.errors
    assert res.active == ["mac", "forge"]
    assert res.placements["es"].nodes == ["forge"] and res.placements["kibana"].nodes == ["forge"]
    assert res.placements["shipper"].nodes == ["mac", "forge"], "an `every` agent runs on each active node"
    assert [(x.port, x.node, x.service) for x in res.forwards] == [(5601, "forge", "kibana"), (9200, "forge", "es")]


def test_refusals():
    f = facts()
    # an edge-bound service off the edge
    res = n.resolve(n.load_model(fleet(services={"console": "forge"})), f, assume_enabled=True)
    assert any("console" in e and "only run on the edge" in e for e in res.errors), res.errors
    # a workload service calling back to the edge
    res = n.resolve(n.load_model(fleet(services={"kibana": "forge"})), f, assume_enabled=True)
    assert any("kibana on forge calls es" in e for e in res.errors), res.errors
    # a durable volume on a node without a backup target, then with one
    res = n.resolve(n.load_model(fleet(services={"db": "forge"})), f, assume_enabled=True)
    assert any("durable volume db-data" in e for e in res.errors), res.errors
    doc = fleet(services={"db": "forge"})
    doc["nodes"]["hosts"]["forge"]["backup"] = "sftp:backup-box:/restic/forge"
    assert n.resolve(n.load_model(doc), f, assume_enabled=True).errors == []
    # unknown service, unknown node, unavailable runtime
    assert any("no such service" in e for e in n.resolve(n.load_model(fleet(services={"ghost": "forge"})), f).errors)
    assert any("not a node" in e for e in n.resolve(n.load_model(fleet(services={"es": "cloud"})), f).errors)
    doc = fleet()
    doc["nodes"]["hosts"]["forge"]["runtime"] = "kubernetes"
    assert any("runtime 'kubernetes'" in e for e in n.load_model(doc).errors)


def test_link_port_collisions():
    f = facts()
    f["db"].ports = [9200]  # an edge service already publishes the port the link needs
    res = n.resolve(n.load_model(fleet()), f, assume_enabled=True)
    assert any("9200" in e and "already published on the edge by db" in e for e in res.errors), res.errors
    f = facts()
    f["kibana"].ports = [9200]
    res = n.resolve(n.load_model(fleet()), f, assume_enabled=True)
    assert any("published by both es and kibana" in e for e in res.errors), res.errors


def test_overlays_and_tfvars():
    model, f = n.load_model(fleet()), facts()
    res = n.resolve(model, f, assume_enabled=True)
    edge = yaml.load(n.overlay_text(model, f, res, "mac"), Loader=n._ComposeLoader)
    assert set(edge["services"]) == {"es", "kibana"} and edge["services"]["es"]["profiles"] == [n.PARKED]
    assert "networks" not in edge, "the edge keeps its own network and volumes"
    work = yaml.load(n.overlay_text(model, f, res, "forge"), Loader=n._ComposeLoader)
    assert set(work["services"]) == {"console", "db", "docs", "es", "kibana"}
    assert work["services"]["console"]["profiles"] == [n.PARKED] and work["services"]["es"]["profiles"] == []
    assert "shipper" not in work["services"], "an agent with no profile needs no entry"
    assert work["networks"]["fleet"]["external"] is True
    assert work["volumes"] == {"es-data": {"external": True, "name": "fleet_es-data", "driver": None},
                               "shipper-data": {"external": True, "name": "fleet_shipper-data", "driver": None}}
    assert n.tfvars(model, f, res, "forge") == {"node": "forge", "docker_host": "ssh://forge", "network": "fleet",
                                                "durable_volumes": [],
                                                "rebuildable_volumes": ["fleet_es-data", "fleet_shipper-data"]}
    assert n.overlay_text(model, f, n.resolve(model, f), "mac").endswith("services:\n  {}\n")


def test_overlays_pass_docker_compose_config():
    if not shutil.which("docker"):
        return
    try:
        if subprocess.run(["docker", "compose", "version"], capture_output=True, timeout=20).returncode != 0:
            return
    except (OSError, subprocess.TimeoutExpired):
        return
    root = fixture_root()
    base = {"name": "fleet",
            "services": {k: {"image": "alpine:3", "networks": ["fleet"], **v} for k, v in COMPOSE["services"].items()},
            "volumes": COMPOSE["volumes"], "networks": {"fleet": {"name": "fleet", "driver": "bridge"}}}
    (root / "docker-compose.yml").write_text(yaml.safe_dump(base))
    model, f = n.load_model(fleet()), facts()
    res = n.resolve(model, f, assume_enabled=True)
    for node in ("mac", "forge"):
        (root / f"{node}.yml").write_text(n.overlay_text(model, f, res, node))
        r = subprocess.run(["docker", "compose", "-f", "docker-compose.yml", "-f", f"{node}.yml", "config"],
                           cwd=root, capture_output=True, text=True, timeout=60,
                           env=dict(os.environ, CLAUDE_HOME=str(root)))
        assert r.returncode == 0, f"{node}: {r.stderr[-400:]}"
        cfg = yaml.safe_load(r.stdout)
        if node == "forge":
            assert cfg["networks"]["fleet"].get("external") is True and "driver" not in cfg["networks"]["fleet"]
            assert cfg["volumes"]["es-data"] == {"name": "fleet_es-data", "external": True}
            assert cfg["services"]["es"].get("profiles") in (None, []), "a placed service starts without its profile"


def test_ansible_inventory_lists_workload_nodes_only():
    doc = fleet()
    doc["nodes"]["hosts"]["forge"]["lan_cidr"] = "192.168.4.0/22"
    inv = n.inventory(n.load_model(doc))
    hosts = inv["all"]["children"]["workload"]["hosts"]
    assert set(hosts) == {"forge"}, "the edge is never managed (§ 10.5)"
    forge = hosts["forge"]
    assert forge["ansible_host"] == "forge", "the ssh alias, so ~/.ssh/config resolves it"
    assert forge["fleet_enabled"] is False, "a disabled node is listed: it is bootstrapped before it is enabled"
    assert forge["fleet_docker"] == "ssh://forge" and forge["fleet_lan_cidr"] == "192.168.4.0/22"
    assert "fleet_wol_broadcast" not in forge, "absent host fields stay absent"


def test_key_line():
    res = n.resolve(n.load_model(fleet()), facts(), assume_enabled=True)
    line = n.key_line(res, "ssh-ed25519 AAAAC3Nz fleet-node-link\n")
    assert line.startswith('restrict,port-forwarding,command="/bin/false",permitopen="127.0.0.1:5601",'
                           'permitopen="127.0.0.1:9200" ssh-ed25519 AAAAC3Nz fleet-node-link'), line
    try:
        n.key_line(n.resolve(n.load_model(fleet()), facts()), "ssh-ed25519 AAAA x")
    except ValueError:
        pass
    else:
        raise AssertionError("a link key without permitopen could forward anywhere")


def test_plan_rows():
    res = n.resolve(n.load_model(fleet()), facts(), assume_enabled=True)
    rows = {r["service"]: r for r in n.plan_rows(res, {"es": {"mac"}, "kibana": {"forge"}, "console": {"mac"}})}
    assert rows["es"]["action"] == "stop on mac · start on forge"
    assert rows["kibana"]["action"] == "in place" and rows["console"]["action"] == "in place"
    assert rows["shipper"]["action"] == "start on forge" and rows["db"]["action"] == "—"


class Sandbox:
    """Point the module at a temp hub: fleet.yml, compose, .fleet/nodes and a state dir."""

    def __init__(self, doc: dict):
        self.root = fixture_root()
        (self.root / "_data").mkdir()
        (self.root / "_data" / "fleet.yml").write_text(yaml.safe_dump(doc))
        (self.root / "docker-compose.yml").write_text(yaml.safe_dump(COMPOSE))
        doc["nodes"]["infra"]["state_dir"] = str(self.root / "state")
        (self.root / "_data" / "fleet.yml").write_text(yaml.safe_dump(doc))
        self.saved = {}

    def __enter__(self):
        for attr, value in (("ROOT", self.root), ("FLEET_YML", self.root / "_data" / "fleet.yml"),
                            ("COMPOSE_YML", self.root / "docker-compose.yml"),
                            ("OUT_DIR", self.root / ".fleet" / "nodes")):
            self.saved[attr] = getattr(n, attr)
            setattr(n, attr, value)
        return self

    def __exit__(self, *exc):
        for attr, value in self.saved.items():
            setattr(n, attr, value)
        shutil.rmtree(self.root, ignore_errors=True)


def stub_tofu(root: Path) -> str:
    d = root / "bin"
    d.mkdir()
    p = d / "tofu"
    p.write_text(f'#!/usr/bin/env bash\necho "$TF_DATA_DIR|$*" >> {root}/tofu.log\n'
                 'for a in "$@"; do case "$a" in -out=*) : > "${a#-out=}";; esac; done\n')
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return f"{d}{os.pathsep}{os.environ.get('PATH', '')}"


def test_gen_writes_overlays_and_check_detects_staleness():
    with Sandbox(fleet()) as sb:
        args = SimpleNamespace(assume_enabled=True, check=False, json=False)
        assert n.cmd_gen(args) == 0
        out = sb.root / ".fleet" / "nodes"
        assert {p.name for p in out.iterdir()} == {"mac.yml", "forge.yml", "forge.tfvars.json", "inventory.yml"}
        assert n.cmd_gen(SimpleNamespace(assume_enabled=True, check=True, json=False)) == 0
        (out / "forge.yml").write_text("# hand edit\n")
        assert n.cmd_gen(SimpleNamespace(assume_enabled=True, check=True, json=False)) == 1


def test_infra_plan_and_the_apply_gate():
    with Sandbox(fleet()) as sb:
        saved_path = os.environ.get("PATH", "")
        os.environ["PATH"] = stub_tofu(sb.root)
        try:
            refuse = n.cmd_infra(SimpleNamespace(action="apply", node="forge", yes=False))
            assert refuse == 2 and not (sb.root / "tofu.log").exists(), "apply without --yes ran tofu"
            no_plan = n.cmd_infra(SimpleNamespace(action="apply", node="forge", yes=True))
            assert no_plan == 2 and not (sb.root / "tofu.log").exists(), "apply without a saved plan ran tofu"
            assert n.cmd_infra(SimpleNamespace(action="plan", node="forge", yes=False)) == 0
            calls = (sb.root / "tofu.log").read_text().splitlines()
            assert len(calls) == 2 and all(c.startswith(str(sb.root / "state" / "forge" / ".terraform")) for c in calls)
            assert " init -input=false -upgrade -backend-config=path=" in calls[0] and "forge.tfstate" in calls[0]
            assert " plan -input=false -var-file=" in calls[1] and "forge.tfvars.json" in calls[1]
            tv = json.loads((sb.root / ".fleet" / "nodes" / "forge.tfvars.json").read_text())
            assert tv["rebuildable_volumes"] == ["fleet_es-data", "fleet_shipper-data"]
            assert n.cmd_infra(SimpleNamespace(action="apply", node="forge", yes=True)) == 0
            assert (sb.root / "tofu.log").read_text().splitlines()[-1].endswith("forge.tfplan")
            assert n.cmd_infra(SimpleNamespace(action="plan", node="mac", yes=False)) == 2, "the edge has no infra"
        finally:
            os.environ["PATH"] = saved_path


# --------------------------------------------------------------------------- #
# The status document
# --------------------------------------------------------------------------- #
DOC_KEYS = {"schema", "generated_at", "edge", "probed", "nodes", "services", "drift", "drift_read", "problems"}
NODE_KEYS = {"name", "role", "runtime", "docker", "enabled", "probed", "status", "reachable", "detail",
             "docker_error", "capacity", "declared", "containers", "placed", "deferred"}


def _box(service: str, project: str = "fleet", state: str = "running") -> str:
    return json.dumps({"Names": f"{project}-{service}-1", "State": state, "Status": "Up 1h", "Ports": "",
                       "Labels": f"com.docker.compose.project={project},com.docker.compose.service={service}"})


class Probes:
    """subprocess.run, stubbed for every probe nodes.py and fleetcore.host make:
    records each argv and its time limit, answers from `answers` (first word of
    the matching argv prefix), and fails anything it does not know."""

    def __init__(self, answers: dict | None = None):
        self.calls: list[tuple[list[str], float]] = []
        self.answers = answers or {}

    def __call__(self, argv, **kw):
        self.calls.append((list(argv), kw.get("timeout")))
        for prefix, answer in self.answers.items():
            if " ".join(argv).startswith(prefix):
                if isinstance(answer, BaseException):
                    raise answer
                rc, out = answer
                return subprocess.CompletedProcess(argv, rc, out, "" if rc == 0 else out)
        return subprocess.CompletedProcess(argv, 255, "", f"unexpected probe: {argv[0]}")

    def __enter__(self):
        self.real = subprocess.run
        subprocess.run = self
        return self

    def __exit__(self, *exc):
        subprocess.run = self.real

    def argvs(self) -> list[str]:
        return [" ".join(a) for a, _ in self.calls]


EDGE_OK = {"docker ps": (0, "\n".join([_box("console"), _box("db"), _box("other", project="zer0")])),
           "docker info": (0, json.dumps({"NCPU": 8, "MemTotal": 8 * 2**30, "ContainersRunning": 3,
                                          "ServerVersion": "29.0"}))}


def _status(doc=None, **kw):
    return n.status_doc(fleet=doc or fleet(), compose=COMPOSE, root=fixture_root(), **kw)


def test_status_doc_has_one_shape_and_never_probes_a_disabled_node():
    with Probes(EDGE_OK) as p:
        doc = _status(timeout=3)
    assert set(doc) == DOC_KEYS and doc["schema"] == n.SCHEMA and doc["edge"] == "mac" and doc["probed"] is True
    nodes = {x["name"]: x for x in doc["nodes"]}
    assert all(set(x) == NODE_KEYS for x in doc["nodes"]), [set(x) ^ NODE_KEYS for x in doc["nodes"]]
    assert all(x["status"] in n.STATES for x in doc["nodes"])
    assert not [a for a in p.argvs() if a.startswith("ssh") or " -H " in a], p.argvs()
    assert p.argvs() == ["docker ps -a --format {{json .}}", "docker info --format {{json .}}"], p.argvs()
    assert all(t == 3 for _, t in p.calls), "every probe carries the time limit it was given"
    forge = nodes["forge"]
    assert (forge["status"], forge["enabled"], forge["probed"], forge["reachable"]) == ("off", False, False, None)
    assert forge["containers"] is None and forge["capacity"] is None and forge["detail"] == n.OFF_DETAIL
    assert forge["deferred"] == ["es", "kibana"] and forge["placed"] == [], "placed there once it is enabled"
    mac = nodes["mac"]
    assert (mac["status"], mac["enabled"], mac["reachable"], mac["containers"]) == ("up", True, True, 2)
    assert mac["capacity"] == {"via": "engine", "cpus": 8, "mem_total": 8 * 2**30, "containers_running": 3,
                               "server_version": "29.0"}
    assert "es" in mac["placed"] and doc["drift"] == [] and doc["drift_read"] == ["mac"] and doc["problems"] == []
    json.dumps(doc)  # the API hands it to a JSON encoder as it is


def test_drift_is_not_read_when_no_node_s_containers_were_read():
    """The default compose console has no Docker socket: the edge is local, so
    it is `up`, but `docker ps` (and `docker info`) cannot reach the engine.
    Drift was never measured, so it is None with no node in drift_read — not
    `[]`, which every surface would show as a green zero."""
    no_socket = (1, "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. "
                    "Is the docker daemon running?")
    answers = {"docker ps": no_socket, "docker info": no_socket}
    with Probes(answers):
        doc = _status(timeout=5)
    mac = next(x for x in doc["nodes"] if x["name"] == "mac")
    assert doc["probed"] is True and mac["probed"] is True and mac["status"] == "up", mac
    assert mac["containers"] is None and "Cannot connect" in mac["docker_error"], mac
    assert doc["drift"] is None and doc["drift_read"] == [], (doc["drift"], doc["drift_read"])
    assert all(r["now"] == [] for r in doc["services"])
    json.dumps(doc)
    import contextlib
    import io
    text = io.StringIO()
    with Sandbox(fleet()), Probes(answers), contextlib.redirect_stdout(text):
        n.cmd_status(SimpleNamespace(assume_enabled=False, json=False))
    assert "placement drift: not read" in text.getvalue() and "placement drift: 0" not in text.getvalue(), \
        text.getvalue()


def test_assume_enabled_probes_the_node_and_drift_is_what_runs_off_its_placement():
    answers = {**EDGE_OK, "docker ps": (0, "\n".join([_box("es"), _box("console")])),
               "ssh -o BatchMode=yes -o ConnectTimeout=3 forge true": (0, ""),
               "ssh -o BatchMode=yes -o ConnectTimeout=3 forge nproc": (0, f"16\n{64 * 2**30} {40 * 2**30}\n"
                                                                          f"{900 * 2**30} {500 * 2**30}\n"),
               "docker -H ssh://forge ps": (0, _box("kibana"))}
    with Probes(answers) as p:
        doc = _status(assume_enabled=True, timeout=3)
    forge = next(x for x in doc["nodes"] if x["name"] == "forge")
    assert (forge["status"], forge["probed"], forge["containers"]) == ("up", True, 1), forge
    assert forge["capacity"]["via"] == "ssh" and forge["capacity"]["cpus"] == 16
    assert forge["enabled"] is False, "assume_enabled previews; it does not turn the node on"
    assert any(a.startswith("docker -H ssh://forge ps") for a in p.argvs())
    # es runs on the edge but is placed on forge; shipper is not running yet, which is a start, not drift
    assert doc["drift"] == [{"service": "es", "now": ["mac"], "runs_on": ["forge"]}], doc["drift"]
    assert sorted(doc["drift_read"]) == ["forge", "mac"], doc["drift_read"]


def test_an_unreachable_node_is_unknown_within_the_time_limit_and_nothing_follows():
    doc = fleet()
    doc["nodes"]["hosts"]["forge"]["enabled"] = True
    answers = {**EDGE_OK, "ssh": subprocess.TimeoutExpired(["ssh"], 5)}
    with Probes(answers) as p:
        out = _status(doc, timeout=3)
    forge = next(x for x in out["nodes"] if x["name"] == "forge")
    assert (forge["status"], forge["reachable"], forge["containers"], forge["capacity"]) == ("unknown", False, None, None)
    assert forge["enabled"] is True and forge["probed"] is True and forge["detail"]
    ssh = [(a, t) for a, t in p.calls if a[0] == "ssh"]
    assert len(ssh) == 1 and ssh[0][1] <= 3 + 2, "one SSH attempt, inside the limit"
    assert not [a for a in p.argvs() if " -H " in a], "no docker -H after the SSH probe failed"
    assert out["problems"] == [], out["problems"]
    assert out["drift"] == [], "an unread node's containers are unknown, not drift"
    assert out["drift_read"] == ["mac"], "the drift covers the edge, which was read, and not forge"


def test_probe_false_runs_nothing_and_says_so():
    with Probes() as p:
        doc = _status(probe=False)
    assert p.calls == [] and doc["probed"] is False
    nodes = {x["name"]: x for x in doc["nodes"]}
    assert nodes["mac"]["status"] == "unprobed" and nodes["mac"]["detail"] == n.UNPROBED_DETAIL
    assert nodes["forge"]["status"] == "off" and all(x["containers"] is None for x in doc["nodes"])
    assert doc["drift"] is None and doc["drift_read"] == [], "nothing was read, so drift is not read, not zero"


def test_an_unreadable_model_is_a_problem_not_an_exception():
    with Sandbox(fleet()) as sb, Probes() as p:
        (sb.root / "_data" / "fleet.yml").write_text("nodes: [unclosed\n")
        doc = n.status_doc()
    assert set(doc) == DOC_KEYS and doc["nodes"] == [] and p.calls == []
    assert len(doc["problems"]) == 1 and "cannot be read" in doc["problems"][0], doc["problems"]


def test_cli_json_is_the_status_doc():
    import contextlib
    import io
    with Sandbox(fleet()), Probes(EDGE_OK):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = n.cmd_status(SimpleNamespace(assume_enabled=False, json=True))
        printed = json.loads(buf.getvalue())
        direct = n.status_doc()
        text = io.StringIO()
        with contextlib.redirect_stdout(text):
            n.cmd_status(SimpleNamespace(assume_enabled=False, json=False))
    assert rc == 0 and set(printed) == set(direct) == DOC_KEYS
    assert [set(x) for x in printed["nodes"]] == [set(x) for x in direct["nodes"]] == [NODE_KEYS, NODE_KEYS]
    assert printed["nodes"] == direct["nodes"] and printed["services"] == direct["services"]
    lines = text.getvalue()
    assert "forge" in lines and "never probed" in lines and "placement drift: 0 service(s), read on mac" in lines, lines


def test_host_nodes_maps_docker_hosts_without_probing():
    with Probes() as p:
        root = fixture_root()
        assert n.host_nodes(root) == {}, "no fleet.yml: no map, no error"
        (root / "_data").mkdir()
        (root / "_data" / "fleet.yml").write_text(yaml.safe_dump(fleet()))
        assert n.host_nodes(root) == {"local": {"node": "mac", "role": "edge", "enabled": True},
                                      "forge": {"node": "forge", "role": "workload", "enabled": False}}
    assert p.calls == []


def test_committed_model_resolves_cleanly():
    model = n.load_model()
    f = n.compose_facts()
    assert model.errors == [], model.errors
    for flag in (False, True):
        res = n.resolve(model, f, assume_enabled=flag)
        assert res.errors == [], res.errors
    off = n.resolve(model, f)
    if not any(h.enabled for h in model.workload()):
        assert off.forwards == [], "a disabled workload node must not need the link"
    edge_bound = {s for s, x in f.items() if x.edge_bound}
    assert {"devenv", "console", "tui", "mcp"} <= edge_bound, edge_bound
    assert f["filebeat"].agent, "filebeat reads its host's containers: a node agent"


def main() -> int:
    failed = 0
    cases = [(name, fn) for name, fn in sorted(globals().items()) if name.startswith("test_") and callable(fn)]
    for name, fn in cases:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {name}: {exc}")
    print(f"{len(cases) - failed}/{len(cases)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
