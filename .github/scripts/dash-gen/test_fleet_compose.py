#!/usr/bin/env python3
"""
Fixture tests for the fleet's container plane — the port map and the overrides.

Offline: no docker, no network, no submodule checkout. Every test is a sensor
for a way this can fail WITHOUT an error message, which is the whole failure
mode of container orchestration:

  * a port collision does not raise at `docker compose up` — the second binder
    fails, the container restarts, and the symptom is a flapping service three
    layers from the cause;
  * a generated override that appends instead of replacing brings the original
    colliding port back alongside the new one;
  * a livereload port remapped into the middle of a site's block leaves the
    site working and reload silently dead;
  * and a project matched by `name` instead of `submodule_path` is simply
    absent from the fleet — `zer0-CMS` lives in `projects/zer0-cms`.

    python3 .github/scripts/dash-gen/test_fleet_compose.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fleet_compose as fc  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT = fc.load_contract()
REGISTRY = fc.load_projects()


def _project(slug="demo", port=4010):
    return {"name": slug, "slug": slug, "dev_port": port,
            "dir": REPO_ROOT / "projects" / slug,
            "compose": REPO_ROOT / "projects" / slug / "docker-compose.yml"}


# --------------------------------------------------------------------------- #
# parsing what a compose file actually wrote
# --------------------------------------------------------------------------- #
def test_every_port_shape_the_fleet_actually_uses_parses():
    cases = {
        "4000:4000": (None, "4000", 4000),
        "127.0.0.1:4000:4000": ("127.0.0.1", "4000", 4000),
        "${JEKYLL_PORT:-4000}:4000": (None, "${JEKYLL_PORT:-4000}", 4000),
        # djangoerp writes a VARIABLE bind address. Before this parsed, its five
        # mappings fell through unremapped — a collision the map cannot see.
        "${BIND_HOST:-127.0.0.1}:${POSTGRES_PORT:-5433}:5432":
            ("${BIND_HOST:-127.0.0.1}", "${POSTGRES_PORT:-5433}", 5432),
        "127.0.0.1:6379:6379/tcp": ("127.0.0.1", "6379", 6379),
    }
    for spec, (ip, host, cont) in cases.items():
        p = fc.parse_port(spec)
        assert p, f"failed to parse {spec!r}"
        assert p["host_ip"] == ip and p["host"] == host and p["cont"] == cont, (spec, p)


def test_a_port_that_publishes_nothing_is_left_alone():
    # `"5432"` exposes without publishing; there is nothing to remap and
    # nothing that can collide.
    assert fc.parse_port("5432") is None
    assert fc.parse_port("5432/tcp") is None


# --------------------------------------------------------------------------- #
# the allocation
# --------------------------------------------------------------------------- #
def test_host_ports_are_remapped_and_container_ports_are_not():
    services = {"site": {"ports": ["4000:4000", "35729:35729"]}}
    ports, _ = fc.allocate_ports(_project("zer0-pages", 4012), services, CONTRACT)
    assert ports["site"] == ["127.0.0.1:4012:4000", "127.0.0.1:35732:35729"], ports
    # The container port is the app's own config; changing it would break the
    # app rather than free a port.
    for m in ports["site"]:
        assert m.endswith((":4000", ":35729"))


def test_livereload_is_allocated_from_its_own_range_not_the_sequence():
    """Jekyll embeds the livereload port in the page it serves.

    Allocating it sequentially would put it inside the site's port block, and
    the site would look fine while reload quietly stopped working.
    """
    services = {"site": {"ports": ["4000:4000", "35729:35729"]}}
    ports, _ = fc.allocate_ports(_project("x", 4012), services, CONTRACT)
    lr_lo, lr_hi = CONTRACT["ports"]["livereload"]
    lr = int(ports["site"][1].split(":")[1])
    assert lr_lo <= lr <= lr_hi, f"{lr} outside the livereload range"


def test_livereload_ports_are_unique_across_projects():
    """The regression that the generator's own validator caught.

    Counting livereload from the low end of the range restarts at that number
    for every project, so all six Jekyll sites were handed 35730 and only the
    first would ever bind. Deriving it from dev_port's offset makes it unique
    wherever dev_port is.
    """
    services = {"s": {"ports": ["4000:4000", "35729:35729"]}}
    seen = set()
    for slug, port in (("a", 4010), ("b", 4012), ("c", 4014), ("d", 4016), ("e", 4018)):
        ports, _ = fc.allocate_ports(_project(slug, port), services, CONTRACT)
        lr = ports["s"][1]
        assert lr not in seen, f"{slug} reuses livereload {lr}"
        seen.add(lr)


def test_allocation_is_stable_across_runs():
    # A regenerate that reshuffles the map invalidates every bookmark and every
    # launch config that referenced it.
    services = {"a": {"ports": ["3000:3000"]}, "b": {"ports": ["8000:8000", "9000:9000"]}}
    first, _ = fc.allocate_ports(_project("p", 8010), services, CONTRACT)
    second, _ = fc.allocate_ports(_project("p", 8010), services, CONTRACT)
    assert first == second


def test_multiple_services_share_one_project_block_in_order():
    services = {"web": {"ports": ["3000:3000"]}, "api": {"ports": ["3001:3001"]}}
    ports, _ = fc.allocate_ports(_project("ai-seed", 3014), services, CONTRACT)
    assert ports["web"] == ["127.0.0.1:3014:3000"]
    assert ports["api"] == ["127.0.0.1:3015:3001"]


# --------------------------------------------------------------------------- #
# validation — the part that runs before anything is written
# --------------------------------------------------------------------------- #
def test_a_collision_between_projects_is_an_error_not_a_warning():
    allocs = {
        "a": {"dev_port": 4010, "kind": "jekyll", "ports": {"s": ["127.0.0.1:4010:4000"]}},
        "b": {"dev_port": 4012, "kind": "jekyll", "ports": {"s": ["127.0.0.1:4010:4000"]}},
    }
    errs = fc.validate(allocs, CONTRACT)
    assert any("already taken" in e for e in errs), errs


def test_landing_on_a_hub_port_is_an_error():
    allocs = {"a": {"dev_port": 4010, "kind": "jekyll",
                    "ports": {"s": ["127.0.0.1:4001:4000"]}}}   # the console
    errs = fc.validate(allocs, CONTRACT)
    assert any("Harness Console" in e for e in errs), errs


def test_a_dev_port_outside_its_kind_range_is_an_error():
    allocs = {"a": {"dev_port": 9999, "kind": "jekyll", "ports": {}}}
    assert any("outside the jekyll range" in e for e in fc.validate(allocs, CONTRACT)), \
        "a port outside its range would collide with another kind's block"


def test_the_committed_registry_validates_clean():
    """The real map, not a fixture. This is the test that fails when someone
    adds a project and picks a port by eye."""
    ports = [(p["dev_port"], p["name"]) for p in REGISTRY if p.get("dev_port")]
    assert ports, "no project declares dev_port"
    nums = [n for n, _ in ports]
    dupes = {n for n in nums if nums.count(n) > 1}
    assert not dupes, f"duplicate dev_port in the registry: {dupes}"
    for n, name in ports:
        assert n not in fc.HUB_PORTS, f"{name}: dev_port {n} is the hub's {fc.HUB_PORTS[n]}"
        kinds = [k for k, (lo, hi) in CONTRACT["ports"].items()
                 if k != "livereload" and lo <= n <= hi]
        assert kinds, f"{name}: dev_port {n} is in no declared range"


# --------------------------------------------------------------------------- #
# the override document
# --------------------------------------------------------------------------- #
def test_the_override_replaces_ports_rather_than_appending():
    """`!override` is load-bearing.

    Without it compose MERGES the two port lists, so the original colliding
    port comes back alongside the new one and the project still refuses to
    start — with a conflict on a port the override appears to have changed.
    """
    services = {"site": {"ports": ["4000:4000"]}}
    text = fc.render_override(_project("zer0-pages", 4012), services, CONTRACT)
    assert "ports: !override" in text
    assert "networks: !override" in text


def test_the_override_is_valid_yaml_once_the_compose_tags_are_known():
    services = {"site": {"ports": ["4000:4000", "35729:35729"]},
                "db": {"image": "postgres:15-alpine", "ports": ["5432:5432"]}}
    text = fc.render_override(_project("p", 8010), services, CONTRACT)

    class L(yaml.SafeLoader):
        pass
    L.add_constructor("!override", lambda ldr, node:
                      ldr.construct_sequence(node) if isinstance(node, yaml.SequenceNode)
                      else ldr.construct_scalar(node))
    doc = yaml.load(text, Loader=L)
    assert set(doc["services"]) == {"site", "db"}
    assert doc["networks"][CONTRACT["network"]]["external"] is True
    assert doc["networks"][CONTRACT["network"]]["name"] == CONTRACT["network"]


def test_every_service_joins_the_shared_network_keeping_its_own():
    services = {"web": {"networks": ["barody-network"], "ports": ["8000:8000"]}}
    text = fc.render_override(_project("barodybroject", 4020), services, CONTRACT)
    assert "barody-network" in text, "a project's internal network must survive"
    assert CONTRACT["network"] in text


def test_a_shared_service_is_only_disabled_when_the_project_opted_in():
    services = {"postgres": {"image": "postgres:16-alpine"}}
    # No opt-in: the project keeps its own Postgres, just on a free port.
    assert fc.disabled_services(_project("law-ai", 8010), services) == {}
    # Opt-in: its app has been repointed at the hub's `db`, so its own is off.
    p = dict(_project("law-ai", 8010), shared_services=["postgres"])
    assert fc.disabled_services(p, services) == {"postgres": "postgres"}


def test_disabling_uses_a_profile_nothing_activates():
    services = {"postgres": {"image": "postgres:16-alpine", "ports": ["5432:5432"]}}
    p = dict(_project("law-ai", 8010), shared_services=["postgres"])
    text = fc.render_override(p, services, CONTRACT)
    assert 'profiles: !override ["disabled"]' in text


# --------------------------------------------------------------------------- #
# the shared database
# --------------------------------------------------------------------------- #
def test_db_init_creates_one_database_per_opted_in_project():
    projects = [{"slug": "law-ai", "database": True}, {"slug": "aieo", "database": True},
                {"slug": "it-journey"}]
    sh = fc.render_db_init(projects, CONTRACT)
    assert 'ensure "law_ai" "law_ai"' in sh, "a hyphen is not legal in an unquoted identifier"
    assert 'ensure "aieo" "aieo"' in sh
    assert "it_journey" not in sh, "a project that did not ask for a database must not get one"


def test_db_init_is_idempotent_by_construction():
    """Postgres runs /docker-entrypoint-initdb.d ONCE, on an empty data dir.

    A volume created before a project was registered would never see it, so
    `dash up` re-pipes the same script on every start — which is only safe if
    every statement is guarded.
    """
    sh = fc.render_db_init([{"slug": "x", "database": True}], CONTRACT)
    assert "WHERE NOT EXISTS" in sh
    assert sh.count("WHERE NOT EXISTS") >= 2, "both the role and the database need the guard"
    assert "set -euo pipefail" in sh


# --------------------------------------------------------------------------- #
# target resolution
# --------------------------------------------------------------------------- #
def test_groups_resolve_to_registered_projects():
    projects = [{"slug": s, "dev_port": 4010 + i}
                for i, s in enumerate(["it-journey", "zer0-pages"])]
    targets, problems = fc.resolve_targets(projects, CONTRACT, [], "jekyll", False)
    assert {t["slug"] for t in targets} == {"it-journey", "zer0-pages"}
    # The rest of the group is not checked out here — reported, never fatal.
    assert all("not a registered project" in p for p in problems)


def test_an_unknown_group_is_reported_with_the_list():
    _, problems = fc.resolve_targets([], CONTRACT, [], "nope", False)
    assert any("no such group" in p for p in problems), problems


def test_every_group_member_exists_in_the_registry():
    """A typo in a group name silently drops a project from `--group`."""
    known = {Path(p["submodule_path"]).name for p in REGISTRY if p.get("submodule_path")}
    for group, members in (CONTRACT.get("groups") or {}).items():
        for m in members:
            assert m in known, f"containers.groups.{group} names '{m}', which is not a submodule"


# --------------------------------------------------------------------------- #
# the two port spaces
# --------------------------------------------------------------------------- #
def test_workspace_ranges_never_overlap_the_fleet_ranges():
    """Nine projects have no compose file and still run inside `devenv`.

    devenv publishes a block for them, and the fleet map publishes one per
    project. If the two overlap, an F5 in the workspace and a `dash up` want
    the same host port — and the loser does not error, it just never binds.
    """
    ranges = CONTRACT["ports"]
    ws = {k: v for k, v in ranges.items() if k.startswith("workspace")}
    fleet = {k: v for k, v in ranges.items()
             if not k.startswith("workspace") and k != "livereload"}
    assert ws, "no workspace range declared, but devenv still publishes one"
    for wk, (wlo, whi) in ws.items():
        for fk, (flo, fhi) in fleet.items():
            assert whi < flo or wlo > fhi, \
                f"{wk} {wlo}-{whi} overlaps {fk} {flo}-{fhi}"


def test_devenv_publishes_only_declared_workspace_ports():
    """The compose file and the contract have to agree about which ports the
    workspace owns, or the block drifts back into being hand-maintained."""
    import re
    dc = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text())
    published = []
    for spec in dc["services"]["devenv"]["ports"]:
        m = re.search(r"127\.0\.0\.1:(\d+)-(\d+):", str(spec))
        if m:
            published.append((int(m.group(1)), int(m.group(2))))
    assert published, "devenv publishes no ranges"
    ws = [v for k, v in CONTRACT["ports"].items() if k.startswith("workspace")]
    for lo, hi in published:
        assert any(wlo <= lo and hi <= whi for wlo, whi in ws), \
            f"devenv publishes {lo}-{hi}, which no containers.ports.workspace* range covers"


def test_no_project_dev_port_lands_in_the_workspace_block():
    ws = [v for k, v in CONTRACT["ports"].items() if k.startswith("workspace")]
    for p in REGISTRY:
        n = p.get("dev_port")
        if not n:
            continue
        for lo, hi in ws:
            assert not lo <= n <= hi, \
                f"{p['name']}: dev_port {n} is inside devenv's workspace block {lo}-{hi}"


# --------------------------------------------------------------------------- #
def main() -> int:
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ✓ {name}")
            except AssertionError as exc:
                failures += 1
                print(f"  ✗ {name}: {exc}")
    print("OK — container plane tests" if not failures else f"FAIL — {failures} test(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
