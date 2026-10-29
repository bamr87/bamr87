#!/usr/bin/env python3
"""Host-side collector for the console's /live page.

The console runs in Docker and cannot see host processes, so this script runs
on the HOST, lists Claude Code processes (Claude Desktop's embedded CLI, the VS
Code extension, `claude` / `claude -p`) and writes <repo>/.dash-live/sessions.json,
which the container reads through the repo bind mount. Read-only: it never
signals a process, and it records no command-line arguments (they can carry
prompts or secrets) — only the origin, pid, cpu, rss, age and cwd.

    python3 tools/console/live_collector.py          # loop every 5 s
    python3 tools/console/live_collector.py --once   # write once and exit
"""
from __future__ import annotations

import json, os, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / ".dash-live" / "sessions.json"
ACTIVE_CPU = 1.0
INTERVAL = float(os.environ.get("LIVE_INTERVAL", "5"))


def etime_s(et: str) -> int:
    days, _, rest = et.partition("-") if "-" in et else ("0", "", et)
    parts = [int(p) for p in rest.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts
    return int(days) * 86400 + h * 3600 + m * 60 + s


def origin(cmd: str) -> str:
    if "/Claude.app/" in cmd or "Application Support/Claude/" in cmd:
        return "claude-desktop"
    if ".vscode" in cmd or "/Code.app/" in cmd or ".cursor/extensions" in cmd:
        return "vscode"
    args = cmd.split()
    if "-p" in args or "--print" in args:
        return "claude -p"
    return "cli"


def cwd_of(pid: int) -> str | None:
    try:
        out = subprocess.run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
                             capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return None
    for line in out.splitlines():
        if line.startswith("n"):
            return line[1:]
    return None


def collect() -> dict:
    out = subprocess.run(["ps", "-axo", "pid=,ppid=,pcpu=,rss=,etime=,command="],
                         capture_output=True, text=True, timeout=10).stdout
    sessions = []
    for line in out.splitlines():
        f = line.split(None, 5)
        if len(f) < 6:
            continue
        pid, ppid, cpu, rss, et, cmd = f
        exe = cmd.split(" --")[0].split(" -p")[0].strip()
        if os.path.basename(exe) != "claude" and cmd.split()[0] != "claude":
            continue
        cpu_f = float(cpu)
        sessions.append({
            "pid": int(pid), "ppid": int(ppid), "origin": origin(cmd),
            "cpu": cpu_f, "rss_mb": round(int(rss) / 1024, 1),
            "age_s": etime_s(et), "cwd": cwd_of(int(pid)),
            "state": "active" if cpu_f >= ACTIVE_CPU else "idle",
        })
    sessions.sort(key=lambda s: (-s["cpu"], s["age_s"]))
    return {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "host": os.uname().nodename, "sessions": sessions}


def write(doc: dict) -> None:
    OUT.parent.mkdir(exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1))
    tmp.replace(OUT)


def main() -> None:
    once = "--once" in sys.argv
    while True:
        try:
            write(collect())
        except Exception as exc:  # keep looping; the page shows staleness
            print(f"live_collector: {exc}", file=sys.stderr)
        if once:
            return
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
