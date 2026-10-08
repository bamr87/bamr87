#!/usr/bin/env python3
"""Serve the console on its TCP port AND a Unix socket — one process, one job manager.

uvicorn's CLI binds one address. The terminal dash in its own container needs
to reach the SAME runtime the browser uses (so a job started in either shows in
both), and the socket is how it does that without widening the console's
DNS-rebinding allowlist or sharing a secret: the socket lives in a volume only
the `tui` service also mounts, so reaching the file is the authorization —
the same model as docker.sock. Requests on it arrive with `Host: localhost`.

    CONSOLE_HOST / CONSOLE_PORT   the TCP listener (as run.sh)
    CONSOLE_UDS                   path of the extra Unix socket
"""
from __future__ import annotations

import os
import socket
import stat
from pathlib import Path

import uvicorn


def unix_socket(path: str) -> socket.socket:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        if not stat.S_ISSOCK(p.stat().st_mode):
            raise SystemExit(f"console: {path} exists and is not a socket — refusing to replace it")
        p.unlink()  # a stale socket from the last run
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(path)
    os.chmod(path, 0o660)
    return sock


def main() -> None:
    config = uvicorn.Config("app:app", host=os.environ.get("CONSOLE_HOST", "127.0.0.1"),
                            port=int(os.environ.get("CONSOLE_PORT", "4001")))
    sockets = [config.bind_socket()]
    if uds := os.environ.get("CONSOLE_UDS"):
        sockets.append(unix_socket(uds))
        print(f"console: also listening on unix://{uds}", flush=True)
    uvicorn.Server(config).run(sockets=sockets)


if __name__ == "__main__":
    main()
