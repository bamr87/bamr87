#!/usr/bin/env python3
"""Live Docker inventory from the container host (forge via `ssh://forge`).

The registry stays `_data/projects.yml`. This only attaches running-container
state. Bind-mount compose files must be started ON the host (its filesystem);
the Mac talks to the daemon over SSH, it does not mount /Users into forge.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from fleet import AppRow


@dataclass
class Container:
    name: str
    state: str
    status: str
    project: str = ""
    ports: str = ""
    labels: dict[str, str] = field(default_factory=dict)

    @property
    def running(self) -> bool:
        return self.state.lower() == "running"


def docker_host() -> str:
    return os.environ.get("DASH_DOCKER_HOST", "").strip()


def _parse_labels(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in (raw or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def list_containers(host: str, timeout: int = 8) -> tuple[list[Container], str | None]:
    """Return (containers, error). error is set when docker is unreachable."""
    if not host:
        return [], None
    try:
        r = subprocess.run(
            ["docker", "-H", host, "ps", "-a", "--format", "{{json .}}"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], str(exc)
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "docker ps failed").strip()
        return [], err[-400:]
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
                project=labels.get("com.docker.compose.project")
                or labels.get("bamr87.project")
                or "",
                ports=row.get("Ports") or "",
                labels=labels,
            )
        )
    return boxes, None


def _keys(row: AppRow) -> set[str]:
    keys = {row.name.lower()}
    if row.submodule_path:
        keys.add(Path(row.submodule_path).name.lower())
    return {k for k in keys if len(k) >= 3}


def match_container(row: AppRow, containers: list[Container]) -> Container | None:
    keys = _keys(row)
    hits: list[Container] = []
    for c in containers:
        name = c.name.lower()
        proj = c.project.lower()
        label = (c.labels.get("bamr87.project") or "").lower()
        for k in keys:
            if label == k or proj == k or name == k or name.startswith(k + "-"):
                hits.append(c)
                break
    hits.sort(key=lambda c: (not c.running, c.name))
    return hits[0] if hits else None


def attach(rows: list[AppRow], containers: list[Container]) -> None:
    for row in rows:
        hit = match_container(row, containers)
        row.docker_name = hit.name if hit else None
        row.docker_status = hit.status if hit else None
        row.docker_running = bool(hit and hit.running)
