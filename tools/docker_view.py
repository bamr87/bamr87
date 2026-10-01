#!/usr/bin/env python3
# ============================================================================
# File:          tools/docker_view.py
# Description:   Merges every Docker signal the hub already owns — the port
#                registry, the image contract, the live smoke recording, the
#                harmonization audit and the debug attach points — into ONE
#                committed view, _data/docker.yml, rendered at /docker/.
# Author:        bamr87
# Created:       2026-09-22
# Last Modified: 2026-09-22
# Version:       1.0.0
# Usage:
#   tools/docker_view.py            # print the console summary
#   tools/docker_view.py --write    # regenerate _data/docker.yml
#   tools/docker_view.py --json     # emit the document on stdout
#   tools/dash docker view [--write]
# ============================================================================
#
# WHY A GENERATED FILE AND NOT LIQUID OVER THE RAW REGISTRIES
#
# The facts are already in version control — _data/ports.yml (allocation),
# _data/fleet.yml `images:` (version contract), _data/smoke.yml (what actually
# answered), .vscode/launch.json (attach points) — but they are keyed four
# different ways, and the join is what a person actually wants: "what is this
# service, what is its URL, is it up, what image is it on, is that the version
# we said, and how do I attach a debugger to it?" Liquid can render a table; it
# cannot do a four-way join across nested maps. So the join happens here, once,
# deterministically, and the page stays a rendering.
#
# LOCAL-FIRST, LIKE THE SIGNALS IT READS
#
# Two of the inputs only exist on a machine that runs the fleet: the smoke
# recording (needs the containers) and the conformance audit (needs the
# submodules checked out). So this runs on the operator's machine, not in CI —
# same posture as `dash ai`. The published page renders the last committed
# view and says how old it is.
#
# ABSENCE IS NOT CONFORMANCE
#
# A submodule that is not checked out has NO Docker findings, which is a
# different thing from having none. Writing that as "clean" is exactly the bug
# that made `fleet-compose.py sync` delete fifteen committed overrides in a
# tree without submodules. Here a missing checkout carries the PREVIOUS
# conformance block forward, marked `stale`, and the page renders it greyed.

import argparse
import datetime
import json
import os
import re
import sys

try:
    import yaml
except ImportError:                                          # pragma: no cover
    sys.stderr.write("docker_view: PyYAML is required (pip install pyyaml)\n")
    raise SystemExit(2)

HUB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HUB, "tools"))
import docker_harmonize as dh                                # noqa: E402

OUT = os.path.join(HUB, "_data", "docker.yml")

# Bands whose allocation is something you can open in a browser. Everything
# else gets a connect command instead of a dead link — a `psql://` href helps
# nobody, and a debug port answers to a debugger, not to GET /.
WEB_BANDS = {"hub", "jekyll", "frontend", "api", "docs"}
BAND_KIND = {"database": "db", "cache": "cache", "debug": "debug", "livereload": "livereload"}


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
def load_yaml(rel):
    path = os.path.join(HUB, rel)
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        return yaml.safe_load(fh) or {}


def load_launch():
    """port -> {attach, start}: the VS Code configurations that reach that port.

    Two ways a configuration names a port, and both matter. A debugger ATTACH
    declares it structurally (`connect.port`), which is exact. Everything else
    — the Jekyll and Vite servers a human starts inside devenv, the MkDocs
    serves — is a task launcher that only carries the port in its LABEL
    ("Jekyll: wargames (:4015, devenv)"). Matching the label is what lets a
    devenv-hosted allocation, which has no container to interrogate, still tell
    you how to bring it up.

    launch.json is JSONC: VS Code tolerates comments, json.loads does not. The
    file is ours and its comments are line comments, so stripping those is
    enough — no attempt at a general JSONC parser.
    """
    path = os.path.join(HUB, ".vscode", "launch.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        text = re.sub(r"^\s*//.*$", "", fh.read(), flags=re.M)
    try:
        doc = json.loads(text)
    except ValueError:
        return {}
    out = {}
    for cfg in doc.get("configurations") or []:
        name = cfg.get("name", "")
        port = (cfg.get("connect") or {}).get("port") or cfg.get("port")
        if port:
            out.setdefault(int(port), {}).setdefault("attach", name)
        m = re.search(r":(\d{4,5})\b", name)
        if m:
            out.setdefault(int(m.group(1)), {}).setdefault("start", name)
    return out


def smoke_index(smoke):
    """(project, service) -> the recorded entry, flattened for rendering."""
    idx = {}
    for entry in (smoke or {}).get("services") or []:
        flat = {
            "verdict": entry.get("verdict"),
            "state": entry.get("state"),
            "health": entry.get("health"),
            "container": entry.get("container"),
            "image": entry.get("image"),
            "profiles": entry.get("profiles") or [],
        }
        for probe in entry.get("probes") or []:
            kind = probe.get("kind")
            if kind == "http":
                flat["http"] = {k: probe.get(k) for k in
                                ("status", "status_class", "content_type", "title", "ms", "error")
                                if probe.get(k) is not None}
            elif kind in ("postgres", "redis"):
                flat["version"] = probe.get("server_version") or probe.get("redis_version")
                flat["major"] = probe.get("major")
                if probe.get("databases"):
                    flat["databases"] = probe["databases"]
            elif kind == "exec":
                flat["user"] = probe.get("user")
            elif kind == "tcp":
                flat["tcp"] = bool(probe.get("ok"))
        idx[(entry.get("project"), entry.get("service"))] = flat
    return idx


# ---------------------------------------------------------------------------
# Per-service projection
# ---------------------------------------------------------------------------
def service_row(project, name, spec, live, launch, kind=None, on_demand=False):
    band = spec.get("band") or ""
    kind = kind or BAND_KIND.get(band, "web" if band in WEB_BANDS else "other")
    port = spec.get("port")
    cfgs = launch.get(port) or {}
    row = {
        "service": name,
        "band": band,
        "kind": kind,
        "port": port,
        "var": spec.get("var"),
    }
    if spec.get("served_by"):
        row["served_by"] = spec["served_by"]
    if spec.get("livereload"):
        row["livereload"] = spec["livereload"]
    if spec.get("shared") is not None:
        row["shared"] = spec["shared"]
    if cfgs.get("start"):
        row["launch"] = cfgs["start"]

    if kind == "web":
        row["url"] = "http://127.0.0.1:%s/" % port
    elif kind == "debug":
        row["attach"] = cfgs.get("attach") or "(no launch.json configuration)"
        row["kind_detail"] = spec.get("kind")
        if spec.get("local"):
            row["path_mapping"] = "%s -> %s" % (spec["local"], spec.get("remote", ""))
    row["address"] = "127.0.0.1:%s" % port

    if live:
        row.update({k: v for k, v in live.items() if v not in (None, [], {})})
        # A connect command is only honest once we know the container's name,
        # and reading the credential from the container's own env is the only
        # form that is right for every project — POSTGRES_USER differs per repo.
        if kind == "db" and live.get("container"):
            row["connect"] = "docker exec -it %s sh -lc 'psql -U \"$POSTGRES_USER\"'" % live["container"]
        elif kind == "cache" and live.get("container"):
            row["connect"] = "docker exec -it %s redis-cli" % live["container"]
    elif on_demand:
        # Served from inside the shared devenv container by a command a human
        # starts — there is no container of its own, so the smoke recording
        # skips it by design (tools/fleet_smoke.py). Recording that as
        # "unknown" would make eleven working sites look like a gap in the
        # data; they are simply not running until someone runs them.
        row["verdict"] = "on-demand"
    else:
        row["verdict"] = "unknown"
    return row


def project_rows(ports, smoke_idx, launch):
    out = []
    for name, spec in (ports.get("projects") or {}).items():
        host = spec.get("host", "compose")
        compose = spec.get("compose")
        present = True
        if host == "compose" and compose:
            present = os.path.exists(os.path.join(HUB, compose))
        override = os.path.join("compose", "overrides", "hub.yml" if name == "bamr87" else "%s.yml" % name)
        proj = {
            "name": name,
            "host": host,
            "present": present,
            "compose": compose,
            "override": override if os.path.exists(os.path.join(HUB, override)) else None,
            "up": "tools/dash dev up %s" % name if host != "devenv" else None,
            "notes": spec.get("notes"),
            "services": [],
            "debug": [],
        }
        for sname, sspec in (spec.get("services") or {}).items():
            demand = host == "devenv" or (sspec or {}).get("served_by") == "devenv"
            proj["services"].append(
                service_row(name, sname, sspec, smoke_idx.get((name, sname)), launch,
                            on_demand=demand))
        for dname, dspec in (spec.get("debug") or {}).items():
            proj["debug"].append(
                service_row(name, dname, dspec, smoke_idx.get((name, dname)), launch, kind="debug"))
        proj["services"].sort(key=lambda r: (r["band"], r["port"]))
        proj["debug"].sort(key=lambda r: r["port"])
        if spec.get("unique"):
            proj["unique"] = {k: list(v) for k, v in spec["unique"].items()}
        if spec.get("exclude"):
            proj["excluded"] = dict(spec["exclude"])
        if spec.get("prefix"):
            proj["prefix"] = spec["prefix"]

        verdicts = [r.get("verdict") for r in proj["services"]]
        proj["counts"] = {v: verdicts.count(v) for v in sorted(set(verdicts)) if v}
        out.append(proj)
    out.sort(key=lambda p: (p["host"] != "hub", p["host"] != "compose", p["name"]))
    return out


# ---------------------------------------------------------------------------
# Conformance — what `dash docker check` would still change, per repo
# ---------------------------------------------------------------------------
def conformance(projects, previous, scan=True):
    """project -> {changes, rules, advisories, pinned, files}.

    Runs the same transformer as `dash docker audit`, read-only. A repo with no
    checkout keeps whatever the previous view recorded, flagged `stale` — see
    the header: absence is not conformance.
    """
    prev = {p["name"]: p.get("conformance") for p in (previous or {}).get("projects") or []}
    out = {}
    for proj in projects:
        name = proj["name"]
        root = HUB if proj["host"] == "hub" else os.path.join(HUB, "projects", name)
        if not scan or not os.path.isdir(root):
            carried = prev.get(name)
            if carried:
                carried = dict(carried, stale=True)
            out[name] = carried
            continue
        repo = dh.Repo(root, name)
        if not repo.compose and not repo.dockerfiles:
            out[name] = None
            continue
        res, pins = dh.run(root, name, write=False)
        rules, advisories = {}, {}
        for c in res.changes:
            rules[c.rule] = rules.get(c.rule, 0) + 1
        for f in res.findings:
            advisories[f.kind] = advisories.get(f.kind, 0) + 1
        out[name] = {
            "changes": len(res.changes),
            "rules": dict(sorted(rules.items())),
            "advisories": dict(sorted(advisories.items())),
            "pinned": pins,
            "compose_files": [repo.rel(f) for f in repo.compose],
            "dockerfiles": [repo.rel(f) for f in repo.dockerfiles],
            "held": [{"image": i, "version": v, "reason": w} for i, (v, w) in sorted(repo.held.items())],
        }
    return out


STAGE_AS = re.compile(r"^\s*FROM\s+\S+\s+AS\s+(?P<name>[A-Za-z0-9_.-]+)", re.I)


def file_images(path):
    """Every real image reference in one file, as (image, tag).

    Two things that look like image references are not:
      * a PARAMETERIZED ref — `${RUBY_VERSION}`, `$RUBY_VERSION`, a
        `{{RUBY_VERSION}}` kit placeholder. Its version lives wherever the
        variable is defined; recording the literal would put `$RUBY_VERSION`
        in the census as though it were a tag.
      * an internal STAGE name — `FROM base`, `FROM build`. Multi-stage
        Dockerfiles refer to their own earlier stages by name, and those are
        not images at all. This is what put `base`, `build` and `lawmode` in
        the first run's unmanaged-image list.
    """
    stages, out = set(), []
    for line in dh.read_lines(path):
        m = STAGE_AS.match(line)
        if m:
            stages.add(m.group("name").lower())
        ref = dh.image_ref_of(line, path)
        if not ref or "$" in ref or "{{" in ref or ref.lower() == "scratch":
            continue
        image, tag = dh.split_ref(dh.norm_image(ref))
        if image.lower() in stages:
            continue
        out.append((image, tag or "latest"))
    return out


def declared_images(projects, scan=True):
    """family -> {tag: [project…]} across every checked-out repo's compose + Dockerfiles.

    The census the version contract is supposed to govern.
    """
    census = {}
    if not scan:
        return census
    for proj in projects:
        name = proj["name"]
        root = HUB if proj["host"] == "hub" else os.path.join(HUB, "projects", name)
        if not os.path.isdir(root):
            continue
        repo = dh.Repo(root, name)
        for path in repo.compose + repo.dockerfiles:
            for image, tag in file_images(path):
                census.setdefault(image, {}).setdefault(tag, [])
                if name not in census[image][tag]:
                    census[image][tag].append(name)
    return census


def compare(tag, want):
    """(label, behind?) for a tag against the contract, AT THE CONTRACT'S PRECISION.

    Comparing majors only is wrong for half the families: the contract says
    python 3.14 and ruby 3.4, so `python:3.11` and `ruby:3.1` are behind even
    though their major matches — the first run reported python as conforming
    while five repos sat on 3.11/3.12. A tag with no digits at all (`alpine`,
    `latest`) is FLOATING: not behind, not conforming, reported separately,
    because what it resolves to is a fact about the registry today.
    """
    w, t = dh.ver_tuple(want), dh.ver_tuple(tag)
    if not w or not t:
        return None, None
    n = len(w)
    padded = (t + (0,) * n)[:n]
    return ".".join(str(x) for x in padded), padded < w[:n]


def image_contract(projects, census, smoke_idx, conf):
    """The version contract, each family joined to what is declared and running.

    Three reasons a repo can sit below the contract and NOT be drift, and the
    view has to tell them apart or it cries wolf on exactly the decisions that
    were made most carefully:

      * a deliberate PIN (`# pinned` / `# fleet-pin:` in the file, surfaced by
        the harmonizer as a frozen family). The hub's own Postgres is 15
        because Wiki.js content lives in a volume that major wrote.
      * a fleet.yml `image_overrides:` CEILING, which is a different contract
        for that repo, not a violation of this one — law-ai's Python is 3.13
        because crewai publishes nothing for 3.14.
      * a FLOATING tag (`alpine`, `latest`), which declares no version to be
        behind. Reported, never counted.

    Only what is left over is drift.
    """
    contract = dh.load_images()
    overrides = dh.load_overrides()
    pinned_by = {name: set((c or {}).get("pinned") or []) for name, c in conf.items()}

    running = {}
    for (proj, _svc), live in smoke_idx.items():
        image = live.get("image") or ""
        major = live.get("major")
        if not major:
            continue
        family = dh.norm_image(image).split(":")[0] if ":" in image else None
        if family:
            running.setdefault(family, {}).setdefault(str(major), [])
            if proj not in running[family][str(major)]:
                running[family][str(major)].append(proj)

    rows = []
    for family, want in sorted(contract.items()):
        declared = census.get(family, {})
        behind, pins, ceilings, floating = {}, [], [], []
        for tag, repos in declared.items():
            for repo in repos:
                over = (overrides.get(repo) or {}).get(family)
                effective = (over[0] if over and over[0] else want)
                label, is_behind = compare(tag, effective)
                if label is None:
                    if tag not in floating:
                        floating.append(tag)
                    continue
                if not is_behind:
                    continue
                if family in pinned_by.get(repo, ()):
                    pins.append({"project": repo, "version": label, "tag": tag})
                elif over:
                    ceilings.append({"project": repo, "version": label, "tag": tag,
                                     "ceiling": over[0], "reason": over[1]})
                else:
                    behind.setdefault(label, [])
                    if repo not in behind[label]:
                        behind[label].append(repo)
        rows.append({
            "family": family,
            "contract": want,
            "declared": {t: sorted(p) for t, p in sorted(declared.items())},
            "running": {m: sorted(p) for m, p in sorted(running.get(family, {}).items())},
            "behind": {k: sorted(v) for k, v in sorted(behind.items())},
            "pinned": sorted(pins, key=lambda r: r["project"]),
            "ceilings": sorted(ceilings, key=lambda r: r["project"]),
            "floating": sorted(floating),
            "conforming": not behind,
        })
    unmanaged = sorted(f for f in census if f not in contract)
    over = []
    for proj, imgs in sorted(overrides.items()):
        for family, (ver, why) in sorted(imgs.items()):
            over.append({"project": proj, "family": family, "version": ver, "reason": why})
    return rows, over, unmanaged


VAR_DEFAULT = re.compile(r"^\$\{(?P<var>[A-Za-z_][A-Za-z0-9_]*)(?::-(?P<default>\d+))?\}$")
NON_HTTP_TARGETS = {"3306", "4317", "5432", "5678", "5679", "6379", "7687", "9000", "27017"}


def published_ports(path):
    """[(service, spec, port, var, target)] for every host port a compose file publishes.

    Deliberately NOT dh._ports_of: that one skips a parameterized publication
    (`${WIKI_PORT:-3000}`) because the harmonizer has nothing left to do to it.
    Here the parameterized form is the INTERESTING case — it is what a
    harmonized service looks like, and its default is the port a person will
    actually open. A range (`4010-4020`) is kept as a range: the devenv
    container publishes one so the eleven Jekyll sites it hosts are reachable,
    and expanding it into eleven rows would say the hub publishes eleven
    services it does not.
    """
    lines = dh.read_lines(path)
    out = []
    for span in dh.service_spans(lines):
        name = span[0]
        _, items = dh.block(lines, span, "ports")
        for j in items:
            m = re.match(r"^\s*-\s*['\"]?(?P<spec>[^'\"#\s]+)['\"]?", lines[j])
            if not m or lines[j].lstrip().startswith("#"):
                continue
            published, target, _proto = dh.parse_port(m.group("spec"))
            if not published:
                continue
            # The trailing comment is often the only place the intent is
            # written down — docker-compose.yml's 8080 says "gitnexus (npm run
            # dev)", which is what makes an unregistered port legible instead
            # of merely anomalous.
            _, _, tail = lines[j].partition("#")
            comment = tail.strip() or None
            var = None
            vm = VAR_DEFAULT.match(published)
            if vm:
                var, published = vm.group("var"), vm.group("default")
            if published is None:
                continue
            if "-" in published:                                  # a published range
                lo, _, hi = published.partition("-")
                if lo.isdigit() and hi.isdigit():
                    out.append({"service": name, "spec": m.group("spec"), "range": [int(lo), int(hi)],
                                "var": var, "target": target, "comment": comment})
                continue
            if not published.isdigit():
                continue
            out.append({"service": name, "spec": m.group("spec"), "port": int(published),
                        "var": var, "target": target, "comment": comment})
    return out


def hub_services(projects, ports, smoke, smoke_idx, scan=True):
    """The hub's OWN compose services and the host ports they publish.

    Scoped to the hub on purpose. A submodule's compose file is not what the
    fleet stack runs: `dash dev up <project>` layers the generated
    compose/overrides/<project>.yml on top, and the override's ports come from
    _data/ports.yml by construction — so auditing the submodule's own `ports:`
    reports the pre-override numbers as though they were live, and drags in
    every alternate stack (docker-compose.debug.yml, .observability.yml,
    .gpu.yml) that nothing in the fleet loads. An early cut of this did exactly
    that and produced 76 "unregistered" ports, none of which were real.

    The hub has no override layer, so what its compose declares IS what runs —
    and four of its services (Wiki.js, pgAdmin, Postgres, Redis) are
    grandfathered outside the bands and appear nowhere in _data/ports.yml. They
    are working sites; a view of "everything docker" that omitted them would be
    wrong in the way that matters.
    """
    if not scan:
        return []
    hub = next((p for p in projects if p["host"] == "hub"), None)
    if hub is None:
        return []
    shared_ports = set()
    for spec in (ports.get("shared") or {}).values():
        shared_ports |= {int(v) for v in (spec.get("ports") or {}).values()}
    # The devenv container publishes the allocations of every devenv-HOSTED
    # project as well as the hub's own — cv-builder-pro's 5000 is published by
    # the hub's compose but allocated to cv-builder-pro, and checking only the
    # hub's own entries reported it as unregistered.
    allocated = shared_ports | {r["port"] for r in hub["services"] + hub["debug"]}
    for proj in projects:
        for r in proj["services"] + proj["debug"]:
            if proj["host"] == "devenv" or r.get("served_by") == "devenv":
                allocated.add(r["port"])
                if r.get("livereload"):
                    allocated.add(r["livereload"])

    live = {}
    for c in (smoke or {}).get("unallocated_containers") or []:
        if c.get("project") == hub["name"]:
            live[c.get("service")] = c
    for (proj, svc), rec in smoke_idx.items():
        if proj == hub["name"]:
            live.setdefault(svc, rec)

    repo = dh.Repo(HUB, hub["name"])
    rows = []
    for path in repo.compose:
        rel = repo.rel(path)
        for hit in published_ports(path):
            row = {"service": hit["service"], "file": rel, "spec": hit["spec"],
                   "var": hit.get("var"), "target": hit.get("target"),
                   "comment": hit.get("comment")}
            if "range" in hit:
                lo, hi = hit["range"]
                row.update({"range": "%d-%d" % (lo, hi), "kind": "range",
                            "registered": any(lo <= a <= hi for a in allocated),
                            "note": "one publication covering the devenv-hosted allocations"})
            else:
                port = hit["port"]
                row.update({"port": port, "kind": "port", "registered": port in allocated,
                            "address": "127.0.0.1:%d" % port})
                if hit.get("target") not in NON_HTTP_TARGETS:
                    row["url"] = "http://127.0.0.1:%d/" % port
            rec = live.get(hit["service"])
            if rec:
                for k in ("state", "health", "container", "image"):
                    if rec.get(k):
                        row[k] = rec[k]
            rows.append(row)
    rows.sort(key=lambda r: (r.get("port") or 10 ** 6, r["service"]))
    return rows


def unregistered_repos(projects, scan=True):
    """Checked-out repos that carry Docker files but hold no port allocation.

    The counterpart to `unallocated` (a running container with no allocation):
    a repo whose stack the fleet has simply never been told about. It is
    invisible to the port gate, to the smoke harness, and to `dash dev up` —
    which is how the compose `mkdocs` service's 8001 went unregistered until
    the first smoke recording tripped over it.
    """
    if not scan:
        return []
    known = {p["name"] for p in projects}
    root = os.path.join(HUB, "projects")
    out = []
    for name in sorted(os.listdir(root) if os.path.isdir(root) else []):
        d = os.path.join(root, name)
        if name in known or not os.path.isdir(d):
            continue
        repo = dh.Repo(d, name)
        if not repo.compose and not repo.dockerfiles:
            continue
        res, _ = dh.run(d, name, write=False)
        out.append({
            "name": name,
            "compose_files": [repo.rel(f) for f in repo.compose],
            "dockerfiles": [repo.rel(f) for f in repo.dockerfiles],
            "changes": len(res.changes),
        })
    return out


def band_rows(ports, projects):
    used = {}
    for proj in projects:
        for row in proj["services"] + proj["debug"]:
            used.setdefault(row["band"], []).append(row["port"])
            if row.get("livereload"):
                used.setdefault("livereload", []).append(row["livereload"])
    rows = []
    for name, spec in (ports.get("bands") or {}).items():
        lo, hi = spec["range"]
        ports_used = sorted(set(used.get(name, [])))
        rows.append({
            "band": name,
            "from": lo,
            "to": hi,
            "size": hi - lo + 1,
            "used": len(ports_used),
            "free": (hi - lo + 1) - len(ports_used),
            "pct": round(100.0 * len(ports_used) / (hi - lo + 1)),
            "purpose": spec.get("purpose", ""),
            "ports": ports_used,
        })
    return rows


def shared_rows(ports):
    rows = []
    for name, spec in (ports.get("shared") or {}).items():
        ui = (spec.get("ports") or {}).get("ui")
        rows.append({
            "name": name,
            "alias": spec.get("host"),
            "default": bool(spec.get("default")),
            "ports": dict(spec.get("ports") or {}),
            "image": spec.get("image"),
            "url": "http://127.0.0.1:%s/" % ui if ui else None,
            "rationale": (spec.get("rationale") or "").strip(),
        })
    return rows


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
def build(scan=True):
    ports = load_yaml("_data/ports.yml") or {}
    smoke = load_yaml("_data/smoke.yml")
    previous = load_yaml("_data/docker.yml")
    launch = load_launch()
    idx = smoke_index(smoke)

    projects = project_rows(ports, idx, launch)
    conf = conformance(projects, previous, scan=scan)
    census = declared_images(projects, scan=scan)
    unregistered = unregistered_repos(projects, scan=scan)
    published = hub_services(projects, ports, smoke, idx, scan=scan)
    extra = [r for r in published if not r["registered"] and r["kind"] == "port"]
    images, overrides, unmanaged = image_contract(projects, census, idx, conf)
    for proj in projects:
        proj["conformance"] = conf.get(proj["name"])

    shared = shared_rows(ports)
    # Containers the recording saw but no allocation names — where the hub's own
    # phoenix/wiki/db live, since `shared:` and the grandfathered ports are not
    # `services:` entries.
    unalloc = {(c.get("project"), c.get("service")): c
               for c in (smoke or {}).get("unallocated_containers") or []}
    endpoints = []
    for proj in projects:
        for row in proj["services"]:
            if row["kind"] != "web":
                continue
            endpoints.append(dict(row, project=proj["name"], host=proj["host"],
                                  present=proj["present"]))
    for row in extra:
        if not row.get("url"):
            continue
        ep = {
            "project": "bamr87", "service": row["service"], "band": "hub-extra",
            "kind": "web", "port": row["port"], "var": row.get("var"), "url": row["url"],
            "address": "127.0.0.1:%d" % row["port"], "host": "hub", "present": True,
            "registered": False, "comment": row.get("comment"),
            # NOT "ok". The smoke harness takes its topology from
            # _data/ports.yml, so it never probed this port — all that is known
            # is whether the container is up. Claiming a verdict the recording
            # does not support is how a dashboard starts lying: devenv's 8080
            # is "running" whether or not anyone has started gitnexus behind it.
            "verdict": "unprobed" if row.get("state") == "running" else "not-running",
        }
        for k in ("state", "health", "container", "image"):
            if row.get(k):
                ep[k] = row[k]
        endpoints.append({k: v for k, v in ep.items() if v is not None})
    for sh in shared:
        if not sh.get("url"):
            continue
        live = idx.get(("bamr87", sh["name"])) or unalloc.get(("bamr87", sh["name"])) or {}
        endpoints.append({k: v for k, v in {
            "project": "shared", "service": sh["name"], "band": "shared", "kind": "web",
            "port": sh["ports"].get("ui"), "url": sh["url"],
            "address": "127.0.0.1:%s" % sh["ports"].get("ui"), "host": "hub", "present": True,
            "alias": sh["alias"], "state": live.get("state"), "container": live.get("container"),
            "image": live.get("image"),
            "verdict": "unprobed" if live.get("state") == "running" else "not-running",
        }.items() if v is not None})
    endpoints.sort(key=lambda r: r["port"])

    verdicts = [r.get("verdict") for p in projects for r in p["services"]]
    pending = sum((c or {}).get("changes", 0) for c in conf.values())
    advisories = sum(sum((c or {}).get("advisories", {}).values()) for c in conf.values())

    recorded = (smoke or {}).get("recorded_at")
    age_h = None
    if recorded:
        try:
            then = datetime.datetime.strptime(recorded, "%Y-%m-%dT%H:%M:%SZ")
            age_h = round((datetime.datetime.utcnow() - then).total_seconds() / 3600, 1)
        except ValueError:
            pass

    doc = {
        "schema": "fleet-docker/v1",
        "generated_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": (
            "The consolidated Docker view: _data/ports.yml (allocation) joined to "
            "_data/fleet.yml `images:` (version contract), _data/smoke.yml (what actually "
            "answered), .vscode/launch.json (attach points) and the read-only "
            "tools/docker_harmonize.py audit. Generated by tools/docker_view.py --write; "
            "rendered at /docker/. Local-first: two of the inputs only exist on a machine "
            "that runs the fleet."
        ),
        "sources": {
            "ports": {"present": bool(ports), "allocations": len(verdicts)},
            "smoke": {"present": bool(smoke), "recorded_at": recorded, "age_hours": age_h},
            "launch": {"present": bool(launch), "attach_points": len(launch)},
            "conformance": {"scanned": sum(1 for c in conf.values() if c and not c.get("stale")),
                            "carried_forward": sum(1 for c in conf.values() if c and c.get("stale"))},
        },
        "summary": {
            "projects": len(projects),
            "stacks": sum(1 for p in projects if p["host"] == "compose"),
            "devenv_hosted": sum(1 for p in projects if p["host"] == "devenv"),
            "services": len(verdicts),
            "endpoints": len(endpoints),
            "ok": verdicts.count("ok"),
            "broken": verdicts.count("broken"),
            "optional": verdicts.count("optional"),
            "absent": verdicts.count("absent"),
            "unknown": verdicts.count("unknown"),
            "pending_changes": pending,
            "advisories": advisories,
            "families_behind": sum(1 for i in images if not i["conforming"]),
            "unregistered_repos": len(unregistered),
            "hub_services": sum(1 for r in published if r["kind"] == "port"),
            "hub_unregistered": len(extra),
            "unallocated_containers": len((smoke or {}).get("unallocated_containers") or []),
        },
        "images": images,
        "image_overrides": overrides,
        "unmanaged_images": unmanaged,
        "bands": band_rows(ports, projects),
        "shared": shared,
        "endpoints": endpoints,
        "projects": projects,
        "unallocated": (smoke or {}).get("unallocated_containers") or [],
        "unregistered_repos": unregistered,
        "hub_stack": published,
        "hub_unregistered": extra,
        "missing_checkouts": sorted(p["name"] for p in projects
                                    if p["host"] == "compose" and not p["present"]),
        "commands": [
            {"cmd": "tools/dash dev up <project> [--debug]", "does": "launch (and debug) any submodule from the hub"},
            {"cmd": "tools/dash dev ps", "does": "what is running, with its URLs"},
            {"cmd": "tools/dash dev ports", "does": "the allocation table"},
            {"cmd": "tools/dash dev smoke check", "does": "re-run the recorded baseline; exit 1 on regression"},
            {"cmd": "tools/dash dev db-upgrade <project> --yes", "does": "migrate a Postgres major without data loss"},
            {"cmd": "tools/dash docker audit|apply|check|fleet", "does": "converge a repo to the image contract"},
            {"cmd": "tools/dash docker view --write", "does": "regenerate this view"},
        ],
    }
    return doc


def print_summary(doc):
    s, src = doc["summary"], doc["sources"]
    print("docker view — %s" % doc["generated_at"])
    print("  projects      : %d  (%d compose stacks, %d devenv-hosted)"
          % (s["projects"], s["stacks"], s["devenv_hosted"]))
    print("  services      : %d  (%d web endpoints)" % (s["services"], s["endpoints"]))
    print("  live          : %d ok, %d broken, %d optional, %d absent, %d unknown"
          % (s["ok"], s["broken"], s["optional"], s["absent"], s["unknown"]))
    print("  smoke         : %s" % (("recorded %s (%sh ago)" % (src["smoke"]["recorded_at"], src["smoke"]["age_hours"]))
                                    if src["smoke"]["present"] else "no recording — run `dash dev smoke record`"))
    print("  conformance   : %d pending change(s), %d advisory finding(s) over %d scanned repo(s)"
          % (s["pending_changes"], s["advisories"], src["conformance"]["scanned"]))
    if src["conformance"]["carried_forward"]:
        print("                  %d repo(s) not checked out — previous audit carried forward, marked stale"
              % src["conformance"]["carried_forward"])
    behind = [i for i in doc["images"] if not i["conforming"]]
    if behind:
        print("  version drift :")
        for i in behind:
            for ver, repos in sorted(i["behind"].items()):
                print("    %-9s contract %-5s  still on %-7s %s"
                      % (i["family"], i["contract"], ver, ", ".join(repos)))
    else:
        print("  version drift : none — every managed family is at or above the contract")
    if doc["hub_unregistered"]:
        print("  hub ports outside the registry (grandfathered, still linkable):")
        for r in doc["hub_unregistered"]:
            print("    %-5s %-10s %-24s %s" % (r["port"], r["service"], r.get("var") or "-",
                                               r.get("comment") or r["file"]))
    if doc["unregistered_repos"]:
        print("  unregistered  : %s  (docker files, no _data/ports.yml allocation)"
              % ", ".join(r["name"] for r in doc["unregistered_repos"]))
    if doc["unallocated"]:
        print("  unallocated   : %d running/exited container(s) with no allocation" % len(doc["unallocated"]))


def main():
    ap = argparse.ArgumentParser(description="Consolidated Docker view for the hub dash")
    ap.add_argument("--write", action="store_true", help="write _data/docker.yml")
    ap.add_argument("--json", action="store_true", help="emit the document on stdout")
    ap.add_argument("--quick", action="store_true",
                    help="skip the per-repo conformance scan (carries the previous audit forward)")
    args = ap.parse_args()

    doc = build(scan=not args.quick)
    if args.json:
        print(json.dumps(doc, indent=2))
        return 0
    if args.write:
        with open(OUT, "w") as fh:
            fh.write("---\n")
            yaml.safe_dump(doc, fh, sort_keys=False, default_flow_style=False, width=100)
        print("wrote %s" % os.path.relpath(OUT, HUB))
    print_summary(doc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
