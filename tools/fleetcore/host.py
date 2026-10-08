#!/usr/bin/env python3
"""Live Docker inventory from the container hosts, matched onto registry rows.

The registry stays `_data/projects.yml`. This only attaches running-container
state. `DASH_DOCKER_HOST` is a comma-separated list of endpoints: `local` is
this machine's current Docker context (where `tools/dash up` runs the shared
core), anything else is passed to `docker -H` (`ssh://forge`, the LAN host —
docs/FORGE-HOST.md). Bind-mount compose files must be started ON the host that
runs them; the Mac talks to forge's daemon over SSH, it does not mount /Users
into forge.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .fleet import AppRow

LOCAL = "local"
# UPS-OPS-17 (specs/OPERATIONS.md) labels every compose service with
# com.bamr87.fleet.project; `bamr87.project` is the label docs/FORGE-HOST.md
# recommended before the standard existed. An explicit label is authoritative:
# a labelled container whose project is not in the registry (the hub's own
# services say `bamr87`) is attributed to nothing rather than guessed at.
PROJECT_LABELS = ("com.bamr87.fleet.project", "bamr87.project")


@dataclass
class Container:
    name: str
    state: str
    status: str
    project: str = ""
    ports: str = ""
    labels: dict[str, str] = field(default_factory=dict)
    host: str = LOCAL
    owner: str | None = None  # registry row name, set by attach()

    @property
    def running(self) -> bool:
        return self.state.lower() == "running"

    @property
    def fleet_project(self) -> str:
        return next((self.labels[k] for k in PROJECT_LABELS if self.labels.get(k)), "")


DEFAULT_HOSTS = "local,ssh://forge"  # this Mac's Docker + the forge host (docs/FORGE-HOST.md)


def docker_hosts() -> list[str]:
    """DASH_DOCKER_HOST as a list. Unset means DEFAULT_HOSTS for every surface
    (it used to be applied by tui/run.sh alone, so the console and the MCP
    server polled nothing); an empty string still turns polling off."""
    raw = os.environ.get("DASH_DOCKER_HOST", DEFAULT_HOSTS)
    hosts: list[str] = []
    for h in raw.split(","):
        h = h.strip()
        if h and h not in hosts:
            hosts.append(h)
    return hosts


def docker_host() -> str:
    """First configured endpoint ('' when none) — kept for single-host callers."""
    hosts = docker_hosts()
    return hosts[0] if hosts else ""


def host_label(host: str) -> str:
    if host == LOCAL:
        return LOCAL
    return host.split("://", 1)[-1] or host


def _parse_labels(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in (raw or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _command(host: str) -> list[str]:
    base = ["docker"] if host == LOCAL else ["docker", "-H", host]
    return [*base, "ps", "-a", "--format", "{{json .}}"]


def list_containers(host: str, timeout: int = 8) -> tuple[list[Container], str | None]:
    """Return (containers, error). error is set when docker is unreachable."""
    if not host:
        return [], None
    try:
        # start_new_session: no controlling terminal, so an ssh:// host that
        # wants a password or a host-key answer fails fast instead of drawing
        # its prompt over the TUI and reading the user's keys.
        r = subprocess.run(_command(host), capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL, start_new_session=True)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], str(exc)
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "docker ps failed").strip()
        return [], err[-400:]
    label = host_label(host)
    boxes: list[Container] = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        labels = _parse_labels(row.get("Labels") or "")
        name = (row.get("Names") or "").lstrip("/")
        boxes.append(
            Container(
                name=name,
                state=row.get("State") or "",
                status=row.get("Status") or "",
                project=labels.get("com.docker.compose.project") or "",
                ports=row.get("Ports") or "",
                labels=labels,
                host=label,
            )
        )
    return boxes, None


def list_all(hosts: list[str], timeout: int = 8) -> tuple[list[Container], dict[str, str]]:
    """Every host's containers, and an error per host that could not be reached."""
    boxes: list[Container] = []
    errors: dict[str, str] = {}
    for h in hosts:
        found, err = list_containers(h, timeout=timeout)
        boxes.extend(found)
        if err:
            errors[host_label(h)] = err
    return boxes, errors


def _keys(row: AppRow, min_len: int = 1) -> set[str]:
    keys = {row.name.lower()}
    if row.submodule_path:
        keys.add(Path(row.submodule_path).name.lower())
    return {k for k in keys if len(k) >= min_len}


def _strength(c: Container, key: str) -> int:
    """How strongly container `c` claims to belong to a project named `key`."""
    name, proj = c.name.lower(), c.project.lower()
    if proj == key:
        return 3
    if name == key:
        return 2
    if name.startswith((key + "-", key + "_")):
        return 1
    return 0


def owner(c: Container, rows: list[AppRow]) -> AppRow | None:
    """The single registry row a container belongs to.

    Strongest evidence wins, then the LONGEST key: `cv-builder-pro-web-1`
    prefix-matches both `cv` and `cv-builder-pro`, and only the second is right
    (the registry has several such pairs: zer0-pages / zer0-pages-remote).
    """
    explicit = c.fleet_project.lower()
    if explicit:
        return next((r for r in rows if explicit in _keys(r)), None)
    best: tuple[int, int] = (0, 0)
    hit: AppRow | None = None
    for r in rows:
        # Heuristics need two characters (the registry has `cv`); a prefix
        # match also needs the separator, so `cv-app-1` but never `cvs-1`.
        for k in _keys(r, min_len=2):
            score = (_strength(c, k), len(k))
            if score[0] and score > best:
                best, hit = score, r
    return hit


def match_container(row: AppRow, containers: list[Container]) -> Container | None:
    """The best container for one row (running first) — among those it owns."""
    mine = [c for c in containers if owner(c, [row]) is row]
    mine.sort(key=lambda c: (not c.running, c.name))
    return mine[0] if mine else None


def attach(rows: list[AppRow], containers: list[Container]) -> None:
    by_row: dict[str, list[Container]] = {}
    for c in containers:
        r = owner(c, rows)
        c.owner = r.name if r else None
        if r:
            by_row.setdefault(r.name, []).append(c)
    for row in rows:
        mine = sorted(by_row.get(row.name, []), key=lambda c: (not c.running, c.name))
        hit = mine[0] if mine else None
        row.docker_name = hit.name if hit else None
        row.docker_status = hit.status if hit else None
        row.docker_running = bool(hit and hit.running)
        row.docker_up = sum(1 for c in mine if c.running)
        row.docker_total = len(mine)
