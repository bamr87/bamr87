#!/usr/bin/env python3
"""
fleet_compose — make ~24 independent compose files into one runnable fleet.

THE PROBLEM THIS SOLVES, precisely. The fleet cannot be one compose project:
compose's `include:` does not namespace service names, and five submodules
define a service called `jekyll`. Compose merges them by name and silently
keeps ONE, discarding the rest — no error, no warning (verified 2026-09-22).
Meanwhile 17 host ports are claimed by more than one project, Postgres appears
8 times and Redis 5.

So each repo stays its own compose project and three things make them compose:
one shared network, one of each backing service, and one port map. This module
generates the per-project override files that carry the first and third.

WHAT IT NEVER DOES: write into a submodule. A submodule is a separate git repo
and the hub only writes to it through a fan-out PR. Overrides land in the HUB's
own tree (`.fleet/compose/`, gitignored) and are applied with a second `-f`.

  pure     allocate_ports / render_override / render_db_init / validate
  i/o      reading each project's compose, writing the override files

Contract: _data/fleet.yml `containers:`   Full doc: docs/CONTAINERS.md
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
FLEET_DEFAULT = REPO_ROOT / "_data" / "fleet.yml"
REGISTRY_DEFAULT = REPO_ROOT / "_data" / "projects.yml"

# Host ports the hub itself binds. A generated port that lands on one of these
# is a container that never binds, reported as a crash long after the cause.
HUB_PORTS = {
    4000: "hub Jekyll dash", 4001: "Harness Console", 3000: "wiki",
    5050: "pgAdmin", 5432: "shared Postgres", 6379: "shared Redis",
    6006: "Phoenix UI", 4317: "Phoenix OTLP", 8001: "MkDocs",
    9200: "Elasticsearch", 5601: "Kibana", 3001: "Grafana",
    5044: "Logstash beats", 8088: "Logstash http", 9600: "Logstash API",
}

# Images that ARE one of the hub's shared services. A project listing the
# matching name in `shared_services:` has had its app pointed at the hub's
# copy, so its own may be switched off.
SHARED_IMAGE_RX = {
    "postgres": re.compile(r"(^|/)(postgres|timescaledb)", re.I),
    "redis": re.compile(r"(^|/)redis", re.I),
    "phoenix": re.compile(r"phoenix", re.I),
}

# Container ports in this band are livereload sidecars. They are allocated from
# their own range rather than sequentially, because Jekyll embeds the livereload
# port in the served page — remapping it into the middle of a site's port block
# silently breaks reload while the site itself looks fine.
LIVERELOAD_BAND = range(35700, 35800)

# A bind address may itself be a variable — djangoerp writes
# `${BIND_HOST:-127.0.0.1}:${POSTGRES_PORT:-5433}:5432`. Before this matched,
# those five mappings fell through to "kept as-is" and were never remapped,
# which is a collision the map cannot see.
_VAR = r"\$\{[A-Za-z_][A-Za-z0-9_]*(?::-[^}]*)?\}"
PORT_RX = re.compile(
    rf"^(?:(?P<host_ip>\[?[0-9a-fA-F:.]+\]?|{_VAR}):)?"
    rf"(?P<host>{_VAR}|\d+)"
    r"(?:-(?P<host_hi>\d+))?"
    r":(?P<cont>\d+)(?:-(?P<cont_hi>\d+))?"
    r"(?:/(?P<proto>tcp|udp))?$")


# --------------------------------------------------------------------------- #
# contract
# --------------------------------------------------------------------------- #
def load_contract(fleet_path: Path | str | None = None) -> dict:
    path = Path(fleet_path) if fleet_path else FLEET_DEFAULT
    doc = yaml.safe_load(path.read_text()) or {}
    c = dict(doc.get("containers") or {})
    c.setdefault("network", "fleet")
    c.setdefault("overrides", ".fleet/compose")
    c.setdefault("ports", {})
    c.setdefault("groups", {})
    c.setdefault("shared", {})
    c.setdefault("max_projects", 8)
    return c


def load_projects(registry_path: Path | str | None = None) -> list[dict]:
    path = Path(registry_path) if registry_path else REGISTRY_DEFAULT
    return yaml.safe_load(path.read_text()) or []


def fleet_projects(registry: list[dict], contract: dict, root: Path | None = None) -> list[dict]:
    """Registry rows that are checked-out submodules with a compose file.

    Keyed on `submodule_path`, never on `name`: the registry calls one project
    `zer0-CMS` and its directory is `projects/zer0-cms`, so matching on name
    drops it.
    """
    root = root or REPO_ROOT
    out = []
    for p in registry:
        sub = p.get("submodule_path")
        if not sub:
            continue
        d = root / sub
        compose = next((d / n for n in ("docker-compose.yml", "compose.yml",
                                        "docker-compose.yaml", "compose.yaml")
                        if (d / n).exists()), None)
        if compose is None:
            continue
        out.append({**p, "dir": d, "compose": compose, "slug": Path(sub).name})
    return out


# --------------------------------------------------------------------------- #
# pure: the port map
# --------------------------------------------------------------------------- #
def parse_port(spec) -> dict | None:
    """One compose port mapping -> its parts, or None when it publishes nothing.

    A bare `"5432"` or `"5432/tcp"` exposes without publishing a fixed host
    port, so there is nothing to remap and nothing that can collide.
    """
    m = PORT_RX.match(str(spec).strip())
    if not m:
        return None
    return {"host_ip": m.group("host_ip"), "host": m.group("host"),
            "host_hi": m.group("host_hi"), "cont": int(m.group("cont")),
            "cont_hi": m.group("cont_hi"), "proto": m.group("proto")}


def _kind_low(project: dict, contract: dict) -> int:
    """The low end of the port range `dev_port` falls in (its own value when
    it falls in none, which makes the offset zero rather than nonsense)."""
    base = int(project["dev_port"])
    for kind, (lo, hi) in (contract.get("ports") or {}).items():
        if kind != "livereload" and lo <= base <= hi:
            return lo
    return base


def allocate_ports(project: dict, services: dict, contract: dict) -> tuple[dict, list[str]]:
    """Remap every published HOST port, preserving container ports.

    Returns ({service: [new mapping, …]}, notes). Deterministic: services in
    compose-file order, mappings in their declared order, so a regenerate does
    not reshuffle the map under someone's bookmarks.
    """
    base = int(project["dev_port"])
    lr_lo, lr_hi = contract["ports"].get("livereload", [35730, 35759])
    # Livereload ports are derived from dev_port's OFFSET IN ITS RANGE, not
    # counted from lr_lo. Counting restarts at lr_lo for every project, so
    # every Jekyll site is handed 35730 and only the first one binds — the
    # generator's own validator caught exactly that. An offset is unique
    # wherever dev_port is, and stable when an unrelated project is added.
    kind_lo = _kind_low(project, contract)
    nxt, nxt_lr = base, lr_lo + (base - kind_lo)
    out, notes = {}, []
    for name, svc in services.items():
        svc = svc or {}
        mapped = []
        for spec in (svc.get("ports") or []):
            p = parse_port(spec)
            if p is None:
                # Either it publishes nothing (`"5432"`, `"5432/tcp"`) or it is
                # a shape this does not understand. Both are left exactly as
                # written — but say which, because "as-is" on a port that DOES
                # publish is a collision waiting to be blamed on something else.
                why = ("exposes without publishing" if ":" not in str(spec)
                       else "UNRECOGNISED mapping — check it by hand")
                notes.append(f"{name}: kept {spec!r} as-is ({why})")
                mapped.append(str(spec))
                continue
            if p["host_hi"] or p["cont_hi"]:
                notes.append(f"{name}: kept range {spec!r} as-is — ranges are not remapped")
                mapped.append(str(spec))
                continue
            if p["cont"] in LIVERELOAD_BAND:
                host, nxt_lr = nxt_lr, nxt_lr + 1
                if host > lr_hi:
                    raise ValueError(f"{project['slug']}: livereload range exhausted")
            else:
                host, nxt = nxt, nxt + 1
            proto = f"/{p['proto']}" if p["proto"] else ""
            mapped.append(f"127.0.0.1:{host}:{p['cont']}{proto}")
        if mapped:
            out[name] = mapped
    return out, notes


def disabled_services(project: dict, services: dict) -> dict[str, str]:
    """Services this project may switch off because the hub runs one.

    Opt-in per project via `shared_services:` in the registry, because using the
    hub's Postgres means the app's DATABASE_URL points at `db` — a change that
    lives in the project, not here. Absent the opt-in the project keeps its own,
    just on a port that no longer collides.
    """
    wanted = project.get("shared_services") or []
    if not wanted:
        return {}
    out = {}
    for name, svc in (services or {}).items():
        img = str((svc or {}).get("image") or "")
        for kind in wanted:
            rx = SHARED_IMAGE_RX.get(kind)
            if rx and img and rx.search(img):
                out[name] = kind
    return out


def render_override(project: dict, services: dict, contract: dict) -> str:
    """The override file for one project: ports remapped, fleet network joined."""
    ports, notes = allocate_ports(project, services, contract)
    off = disabled_services(project, services)
    net = contract["network"]
    shared = contract.get("shared") or {}

    L = [
        "# GENERATED by .github/scripts/dash-gen (fleet_compose) — do not edit.",
        f"# Regenerate with: tools/dash gen compose",
        "#",
        f"# Project : {project['name']}  ({project['slug']})",
        f"# Base    : {project['compose'].relative_to(REPO_ROOT)}",
        f"# dev_port: {project['dev_port']}  (_data/projects.yml)",
        "#",
        "# Applied as a SECOND compose file so the project's own stays untouched:",
        f"#   docker compose -p {project['slug']} \\",
        f"#     --project-directory {project['dir'].relative_to(REPO_ROOT)} \\",
        f"#     -f {project['compose'].relative_to(REPO_ROOT)} \\",
        f"#     -f {contract['overrides']}/{project['slug']}.yml up -d",
        "#",
        "# `!override` replaces the port list rather than appending to it —",
        "# without it compose merges the two and the original colliding port",
        "# comes back alongside the new one.",
        "",
        "services:",
    ]
    for name in services:
        body = []
        if name in ports:
            body.append("    ports: !override")
            body += [f"      - \"{m}\"" for m in ports[name]]
        if name in off:
            body.append(f"    # the hub runs the fleet's {off[name]} ({shared.get(off[name], {}).get('host', off[name])}); "
                        "this one is switched")
            body.append("    # off by a profile nothing activates.")
            body.append("    profiles: !override [\"disabled\"]")
        # Every service joins the shared network, preserving any of its own.
        own = (services[name] or {}).get("networks") or []
        own = list(own) if not isinstance(own, dict) else list(own)
        joined = [n for n in own if n != net] + [net]
        body.append("    networks: !override")
        body += [f"      - {n}" for n in joined]
        if body:
            L.append(f"  {name}:")
            L += body
    L += [
        "",
        "networks:",
        f"  {net}:",
        f"    name: {net}",
        "    # external: the hub's compose creates it. A project brought up",
        "    # without the hub fails here with a clear message instead of",
        "    # quietly creating a second, empty network of its own.",
        "    external: true",
    ]
    for n in {n for name in services
              for n in ((services[name] or {}).get("networks") or []) if n != net}:
        L += [f"  {n}:", "    # the project's own internal network, left as it was"]
    if notes:
        L += ["", "# Notes:"] + [f"#   {n}" for n in notes]
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------- #
# pure: the shared database
# --------------------------------------------------------------------------- #
def render_db_init(projects: list[dict], contract: dict) -> str:
    """One database + role per project that asks for one.

    Runs from /docker-entrypoint-initdb.d on a FRESH volume, and is re-applied
    idempotently by `dash up` so a volume that predates it catches up. Every
    statement is guarded, so running it twice is a no-op rather than an error.
    """
    wants = [p for p in projects if p.get("database")]
    L = [
        "#!/usr/bin/env bash",
        "# GENERATED by .github/scripts/dash-gen (fleet_compose) — do not edit.",
        "# Regenerate with: tools/dash gen compose",
        "#",
        "# One database and one role per project that declares `database: true`",
        "# in _data/projects.yml. This is what replaces the eight separate",
        "# Postgres containers the fleet used to run.",
        "#",
        "# Idempotent on purpose: Postgres runs this directory ONCE, on an empty",
        "# data dir, so a volume created before a project was added would never",
        "# see it. `dash up` pipes the same script through psql on every start,",
        "# and every statement below is guarded.",
        "set -euo pipefail",
        "",
        'PW="${FLEET_DB_PASSWORD:-fleetdev}"',
        'SUPER="${POSTGRES_USER:-postgres}"',
        "",
        "ensure() {  # $1 = database, $2 = role",
        '  psql -v ON_ERROR_STOP=1 --username "$SUPER" --dbname postgres <<-SQL',
        "\tSELECT 'CREATE ROLE \"$2\" LOGIN PASSWORD ''$PW'''",
        "\t WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$2')\\gexec",
        "\tSELECT 'CREATE DATABASE \"$1\" OWNER \"$2\"'",
        "\t WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$1')\\gexec",
        "\tGRANT ALL PRIVILEGES ON DATABASE \"$1\" TO \"$2\";",
        "\tSQL",
        '  echo "  fleet-db: ensured $1 (owner $2)"',
        "}",
        "",
    ]
    if not wants:
        L.append('echo "  fleet-db: no project declares database: true — nothing to create"')
    for p in wants:
        db = re.sub(r"[^a-z0-9_]", "_", p["slug"].lower())
        L.append(f'ensure "{db}" "{db}"')
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------- #
# pure: validation
# --------------------------------------------------------------------------- #
def validate(allocations: dict[str, dict], contract: dict) -> list[str]:
    """Every way the port map can be wrong, before anything is written.

    A port collision does not raise at `docker compose up` — the second binder
    fails and the container restarts, so the symptom is a flapping service and
    the cause is three layers away.
    """
    errs: list[str] = []
    seen: dict[int, str] = {}
    ranges = contract.get("ports") or {}
    for slug, info in sorted(allocations.items()):
        base, kind = info["dev_port"], info.get("kind")
        if kind and kind in ranges:
            lo, hi = ranges[kind]
            if not lo <= base <= hi:
                errs.append(f"{slug}: dev_port {base} is outside the {kind} range {lo}-{hi}")
        for svc, mappings in info["ports"].items():
            for m in mappings:
                pp = parse_port(m)
                if not pp or not str(pp["host"]).isdigit():
                    continue
                host = int(pp["host"])
                if host in HUB_PORTS:
                    errs.append(f"{slug}/{svc}: host port {host} is the hub's {HUB_PORTS[host]}")
                if host in seen:
                    errs.append(f"{slug}/{svc}: host port {host} already taken by {seen[host]}")
                seen[host] = f"{slug}/{svc}"
    return errs


# --------------------------------------------------------------------------- #
# command
# --------------------------------------------------------------------------- #
def kind_of(project: dict, contract: dict) -> str | None:
    base = int(project["dev_port"])
    for kind, (lo, hi) in (contract.get("ports") or {}).items():
        if kind != "livereload" and lo <= base <= hi:
            return kind
    return None


def build(contract: dict, projects: list[dict]) -> tuple[dict, dict, list[str]]:
    """Render every override. Returns (files, allocations, notes)."""
    files, allocs, notes = {}, {}, []
    for p in projects:
        if not p.get("dev_port"):
            continue
        try:
            doc = yaml.safe_load(p["compose"].read_text()) or {}
        except Exception as exc:
            notes.append(f"{p['slug']}: unreadable compose ({exc.__class__.__name__}) — skipped")
            continue
        services = doc.get("services") or {}
        if not services:
            notes.append(f"{p['slug']}: compose declares no services — skipped")
            continue
        ports, n = allocate_ports(p, services, contract)
        notes += [f"{p['slug']}: {x}" for x in n]
        allocs[p["slug"]] = {"dev_port": p["dev_port"], "kind": kind_of(p, contract), "ports": ports}
        files[f"{p['slug']}.yml"] = render_override(p, services, contract)
    return files, allocs, notes


def resolve_targets(projects: list[dict], contract: dict, names: list[str],
                    group: str | None, want_all: bool) -> tuple[list[dict], list[str]]:
    """Which projects a `dash up` invocation means. Returns (targets, problems)."""
    by_slug = {p["slug"]: p for p in projects if p.get("dev_port")}
    problems: list[str] = []
    if want_all:
        chosen = list(by_slug)
    elif group:
        chosen = list((contract.get("groups") or {}).get(group) or [])
        if not chosen:
            problems.append(f"no such group '{group}' — have: "
                            f"{', '.join(sorted(contract.get('groups') or {})) or 'none'}")
    else:
        chosen = list(names)

    out = []
    for n in chosen:
        p = by_slug.get(n)
        if p is None:
            # A group may name a project that is not checked out or has no
            # dev_port; that is a skip with a reason, not a failure.
            problems.append(f"{n}: not a registered project with a compose file and a dev_port")
            continue
        out.append(p)
    return out, problems


def cmd_resolve(args) -> int:
    contract = load_contract(args.fleet)
    projects = fleet_projects(load_projects(args.registry), contract)
    targets, problems = resolve_targets(projects, contract, args.names, args.group, args.all)
    cap = int(contract.get("max_projects") or 8)
    for msg in problems:
        print(f"skip: {msg}", file=sys.stderr)
    if args.all and len(targets) > cap and not args.force:
        print(f"refusing --all: {len(targets)} projects exceeds containers.max_projects ({cap}).\n"
              f"This bench OOM-killed Elasticsearch at a 1 GB heap with five extra containers.\n"
              f"Name the ones you want, use --group, or pass --force.", file=sys.stderr)
        return 1
    overrides = contract["overrides"]
    for p in targets:
        # slug <TAB> project-dir <TAB> base compose <TAB> override
        print(f"{p['slug']}\t{p['dir'].relative_to(REPO_ROOT)}\t"
              f"{p['compose'].relative_to(REPO_ROOT)}\t{overrides}/{p['slug']}.yml")
    return 0


def run(args) -> int:
    if args.resolve:
        return cmd_resolve(args)
    contract = load_contract(args.fleet)
    projects = fleet_projects(load_projects(args.registry), contract)
    files, allocs, notes = build(contract, projects)

    errs = validate(allocs, contract)
    if errs:
        print("port map is invalid:", file=sys.stderr)
        for e in errs:
            print(f"  ✗ {e}", file=sys.stderr)
        return 1

    out_dir = REPO_ROOT / contract["overrides"]
    db_init = REPO_ROOT / "tools" / "fleet" / "db-init" / "10-fleet-databases.sh"
    if args.check:
        drift = 0
        for name, text in files.items():
            cur = (out_dir / name).read_text() if (out_dir / name).exists() else ""
            if cur != text:
                drift += 1
                print(f"  DRIFT {contract['overrides']}/{name}")
        want_db = render_db_init(projects, contract)
        if (db_init.read_text() if db_init.exists() else "") != want_db:
            drift += 1
            print(f"  DRIFT {db_init.relative_to(REPO_ROOT)}")
        if drift:
            print(f"\n{drift} file(s) stale — run: tools/dash gen compose", file=sys.stderr)
            return 1
        print(f"  ok  {len(files)} override(s) and the db init match the registry")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.yml"):
        if stale.name not in files:
            stale.unlink()
            print(f"  removed {contract['overrides']}/{stale.name} (no longer registered)")
    for name, text in sorted(files.items()):
        (out_dir / name).write_text(text)
    db_init.parent.mkdir(parents=True, exist_ok=True)
    db_init.write_text(render_db_init(projects, contract))
    db_init.chmod(0o755)

    print(f"  wrote {len(files)} override(s) to {contract['overrides']}/")
    print(f"  wrote {db_init.relative_to(REPO_ROOT)}")
    for n in notes:
        print(f"  note: {n}")
    print()
    for slug, info in sorted(allocs.items(), key=lambda kv: kv[1]["dev_port"]):
        flat = [m for ms in info["ports"].values() for m in ms]
        print(f"  {info['dev_port']:<6} {slug:<24} {len(flat)} published port(s)")
    return 0


def add_arguments(parser) -> None:
    parser.add_argument("--fleet", default=None, help="path to _data/fleet.yml")
    parser.add_argument("--registry", default=None, help="path to _data/projects.yml")
    parser.add_argument("--check", action="store_true",
                        help="verify the generated files match the registry; write nothing")
    parser.add_argument("--resolve", action="store_true",
                        help="print the compose invocation parts for the named targets (used by `dash up`)")
    parser.add_argument("--group", default=None, help="with --resolve: a group from containers.groups")
    parser.add_argument("--all", action="store_true", help="with --resolve: every registered project")
    parser.add_argument("--force", action="store_true", help="with --resolve --all: ignore max_projects")
    parser.add_argument("names", nargs="*", help="with --resolve: explicit project slugs")
    parser.set_defaults(func=run)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(prog="fleet_compose", description=__doc__)
    add_arguments(ap)
    raise SystemExit(ap.parse_args().func(ap.parse_args()) or 0)
