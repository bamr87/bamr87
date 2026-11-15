#!/usr/bin/env python3
"""ops_cli — the Harness Console's operation allowlist, from a terminal.

`tools/dash ops` is how a terminal, a script and a Claude Code slash command run
a console operation: the SAME allowlist (`core.OPS`), the same parameter
validation (each op's own argv builder), and the same confirm gate as the
console's Operations page, the terminal dash and the MCP layer. It adds a
surface, never a code path: every operation is a `tools/` entrypoint the CLI
and CI already run.

  tools/dash ops list [--group G] [--json]
  tools/dash ops show <op> [--json]
  tools/dash ops run <op> [key=value ...] [--confirm] [--explain] [--here | --console]
  tools/dash ops jobs [<job-id>]
  tools/dash ops loops [--json]

Where a run goes (`run`):

  auto (default)  the console that is running, when it serves THIS checkout and
                  can run the operation there: the job then shows on the
                  console's Jobs page, in the terminal dash and over MCP, and the
                  console enforces its locks (one GitHub write at a time, one
                  lake writer, one local run per loop). Otherwise the operation
                  runs here, in the foreground, with the same argv.
  --here          always in the foreground, here
  --console       only through the console; fails when none answers

A parameter is `key=value`; the dispatch op's workflow inputs are
`fields.<input>=<value>`. A key the operation does not declare is refused, so a
typo never runs the default.

An operation that writes to GitHub, destroys local data or spends Claude
budget runs only with `--confirm` — exactly where the console asks first. A
slash command asks the person, then passes it. `--explain` prints what would
run and which gates it passes, and runs nothing.

Exit codes: the command's own when it ran here; 0 a console job succeeded and 1
one did not; 2 a usage or parameter error; 3 the operation needs --confirm; 4
it cannot run here (no docker, no claude, switched off); 5 --console and no
console answered; 6 the console holds the lock this operation needs.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import core  # noqa: E402  (the allowlist; PyYAML only)

try:  # the same stdlib client the terminal dash uses to join the console's runtime
    from fleetcore.client import ConsoleClient, ConsoleError  # noqa: E402
except ImportError:  # pragma: no cover - fleetcore ships beside this file
    ConsoleClient, ConsoleError = None, RuntimeError

EXIT_FAILED, EXIT_USAGE, EXIT_CONFIRM, EXIT_UNAVAILABLE, EXIT_NO_CONSOLE, EXIT_CONFLICT = 1, 2, 3, 4, 5, 6
POLL_S = 1.0


class UsageError(ValueError):
    pass


# --------------------------------------------------------------------------- #
# parameters
# --------------------------------------------------------------------------- #
def parse_params(op_id: str, pairs: list[str]) -> dict:
    """`key=value` words → the params dict the console's API takes. Keys are
    the operation's declared params; `fields.<input>=<v>` builds the dispatch
    op's `fields` object. Values stay strings: every argv builder already reads
    "true"/"false" (`_flag`) and numbers from strings, as the page sends them."""
    if op_id not in core.OPS:
        raise UsageError(f"unknown operation '{op_id}' (tools/dash ops list)")
    declared = list(core.OPS[op_id].get("params") or [])
    params: dict = {}
    for word in pairs:
        key, sep, value = word.partition("=")
        if not sep or not key:
            raise UsageError(f"'{word}' is not key=value")
        if key.startswith("fields."):
            if "fields" not in declared:
                raise UsageError(f"'{op_id}' takes no fields")
            name = key[len("fields."):]
            if not name:
                raise UsageError(f"'{word}' names no field")
            params.setdefault("fields", {})[name] = value
            continue
        if key not in declared:
            known = ", ".join(declared) or "none"
            raise UsageError(f"'{op_id}' has no parameter '{key}' (its parameters: {known})")
        if key in params:
            raise UsageError(f"'{key}' is given twice")
        params[key] = value
    return params


def resolve(op_id: str, params: dict) -> tuple[list[str], bool]:
    """The argv and whether it is gated, from the op's own builder — the one
    the console's job manager calls, so a refusal here is the same refusal."""
    try:
        return core.build_argv(op_id, params)
    except ValueError as exc:
        raise UsageError(str(exc)) from exc


def gate_of(op_id: str, params: dict, remote: bool) -> str | None:
    """What the confirm gate guards for this call: a GitHub write, Claude
    spend, or nothing. Worded as the console's Jobs page words it."""
    if not remote:
        return None
    if core._flag(params, "apply"):
        return "write"
    return core.OPS[op_id].get("confirm", "write")


# --------------------------------------------------------------------------- #
# the console
# --------------------------------------------------------------------------- #
def same_checkout(health: dict) -> bool:
    root = str((health or {}).get("repo_root") or "")
    try:
        return bool(root) and Path(root).resolve() == core.REPO_ROOT.resolve()
    except OSError:
        return False


def console_for(op_id: str, mode: str, out=None):
    """The console client to submit to, or None to run here. In `auto` a
    console is used only when it answers, serves this checkout and can run the
    operation itself (the console's container has no `claude` and no docker
    socket, so loop runs and the observe stack run on the host)."""
    out = out or sys.stderr
    if mode == "here" or ConsoleClient is None:
        return None
    client = ConsoleClient.from_env()
    if not client.enabled:
        if mode == "console":
            raise ConnectionError("no console configured (DASH_CONSOLE_URL is empty)")
        return None
    try:
        health = client.health()
    except ConsoleError as exc:
        if mode == "console":
            raise ConnectionError(str(exc)) from exc
        return None
    if mode == "console":
        return client
    if not same_checkout(health):
        print(f"[ops] the console at {client.url} serves {health.get('repo_root')}, not this checkout "
              f"({core.REPO_ROOT}) — running here", file=out)
        return None
    try:
        listed = {o["id"]: o for o in client.ops()}
    except ConsoleError as exc:
        print(f"[ops] the console at {client.url} answered but refused the operation list ({exc}) — "
              "running here (set DASH_CONSOLE_TOKEN to share its job list)", file=out)
        return None
    why = (listed.get(op_id) or {}).get("unavailable")
    if op_id not in listed or why:
        print(f"[ops] the console cannot run '{op_id}' ({why or 'it does not list it'}) — running here", file=out)
        return None
    return client


def held_by_console(op_id: str, params: dict) -> dict | None:
    """A live console job that holds the lock this run would need, when the
    run goes here while a console is up (the console cannot see this process,
    so two lake writers would otherwise collide on "database is locked")."""
    key = core._exclusive_key(op_id, params)
    if not key or ConsoleClient is None:
        return None
    client = ConsoleClient.from_env()
    if not client.enabled:
        return None
    try:
        jobs = client.jobs()
    except ConsoleError:
        return None
    return next((j for j in jobs or [] if j.get("exclusive") == key and j.get("status") in ("queued", "running")),
                None)


def follow(client, job: dict, out=None) -> int:
    """Stream a console job's log until it finishes; its outcome is the exit."""
    out = out or sys.stdout
    jid, offset = job["id"], 0
    while True:
        doc = client.tail(jid, offset)
        text = doc.get("text") or ""
        if text:
            out.write(text)
            out.flush()
        offset = doc.get("offset", offset)
        if doc.get("done"):
            final = doc.get("job") or {}
            status = final.get("status")
            print(f"\n[ops] job {jid} {status} (exit {final.get('exit_code')}) — "
                  f"{client.url}/jobs/{jid}", file=sys.stderr)
            return 0 if status == "succeeded" else EXIT_FAILED
        time.sleep(POLL_S)


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #
def op_row(op_id: str) -> dict:
    row = next(o for o in core.list_ops() if o["id"] == op_id)
    return row


def gates_text(row: dict) -> str:
    bits = []
    if row.get("confirm"):
        bits.append(f"confirm:{row['confirm']}")
    if row.get("needs_token"):
        bits.append("token")
    if row.get("exclusive"):
        bits.append(f"lock:{row['exclusive']}")
    if row.get("unavailable"):
        bits.append("unavailable")
    return " ".join(bits) or "-"


def cmd_list(args) -> int:
    rows = [r for r in core.list_ops() if not args.group or r["group"] == args.group]
    if args.group and not rows:
        groups = sorted({r["group"] for r in core.list_ops()})
        print(f"no group '{args.group}' (groups: {', '.join(groups)})", file=sys.stderr)
        return EXIT_USAGE
    if args.json:
        print(json.dumps([{k: r[k] for k in ("id", "group", "title", "params", "needs_token", "confirm",
                                              "exclusive", "unavailable")} for r in rows], indent=1))
        return 0
    group = None
    for r in rows:
        if r["group"] != group:
            group = r["group"]
            print(f"\n{group}")
        params = " ".join(f"{p}=" for p in r["params"])
        print(f"  {r['id']:<22} {gates_text(r):<28} {r['title']}" + (f"  [{params}]" if params else ""))
    print("\nrun one: tools/dash ops run <op> [key=value ...]   (confirm-gated ops need --confirm)")
    return 0


def cmd_show(args) -> int:
    if args.op not in core.OPS:
        print(f"unknown operation '{args.op}' (tools/dash ops list)", file=sys.stderr)
        return EXIT_USAGE
    row = op_row(args.op)
    if args.json:
        print(json.dumps({k: v for k, v in row.items()}, indent=1, default=str))
        return 0
    print(f"{row['id']} — {row['title']}  ({row['group']})")
    print(f"  gates:  {gates_text(row)}")
    print(f"  params: {', '.join(row['params']) or 'none'}")
    if row.get("unavailable"):
        print(f"  here:   unavailable — {row['unavailable']}")
    print(f"\n{row['desc']}")
    return 0


def cmd_run(args) -> int:
    mode = "here" if args.here else "console" if args.console else "auto"
    try:
        params = parse_params(args.op, args.params)
        argv, remote = resolve(args.op, params)
    except UsageError as exc:
        print(f"[ops] {exc}", file=sys.stderr)
        return EXIT_USAGE
    gate = gate_of(args.op, params, remote)
    why = core.op_unavailable(args.op)
    if args.explain:
        print(f"operation: {args.op} — {core.OPS[args.op]['title']}")
        print(f"argv:      {' '.join(argv)}")
        print(f"gate:      {('confirm (' + gate + ')') if gate else 'none: runs without asking'}")
        print(f"here:      {'unavailable — ' + why if why else 'can run'}")
        return 0
    if gate and not args.confirm:
        what = "Claude spend (API-equivalent, an estimate)" if gate == "spend" else \
            "a write to GitHub, or to local data that cannot be restored"
        print(f"[ops] '{args.op}' with these parameters is {what}; it runs only with --confirm.\n"
              f"[ops] it would run: {' '.join(argv)}", file=sys.stderr)
        return EXIT_CONFIRM
    try:
        client = console_for(args.op, mode)
    except ConnectionError as exc:
        print(f"[ops] --console: {exc}", file=sys.stderr)
        return EXIT_NO_CONSOLE
    if client is not None:
        try:
            job = client.submit(args.op, params, confirm=bool(args.confirm))
        except ConsoleError as exc:
            msg = str(exc)
            print(f"[ops] the console refused '{args.op}': {msg}", file=sys.stderr)
            return EXIT_CONFLICT if "already" in msg else EXIT_UNAVAILABLE if "cannot run" in msg else EXIT_USAGE
        print(f"[ops] console job {job['id']} — {job['title']}", file=sys.stderr)
        return follow(client, job)
    if why:
        print(f"[ops] '{args.op}' cannot run here: {why}", file=sys.stderr)
        return EXIT_UNAVAILABLE
    holder = held_by_console(args.op, params)
    if holder:
        print(f"[ops] console job {holder['id']} ('{holder['op']}') holds {holder['exclusive']} — wait for it, "
              f"then run '{args.op}'", file=sys.stderr)
        return EXIT_CONFLICT
    print(f"$ {' '.join(argv)}", file=sys.stderr)
    sys.stderr.flush()
    try:
        return subprocess.run(argv, cwd=str(core.REPO_ROOT), env=core.job_env()).returncode
    except FileNotFoundError as exc:
        print(f"[ops] cannot start: {exc}", file=sys.stderr)
        return 127


COMMANDS_DIR = core.REPO_ROOT / ".claude" / "commands"


def frontmatter(text: str) -> dict:
    """A command file's YAML frontmatter, or {} when it has none or it does not parse."""
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    try:
        doc = core.yaml.safe_load(text[4:end])
    except core.yaml.YAMLError:
        return {}
    return doc if isinstance(doc, dict) else {}


def slash_commands(root: Path = COMMANDS_DIR) -> list[dict]:
    """Every Claude Code slash command the hub ships: its name as typed
    (`.claude/commands/loops/scout.md` is `/loops:scout`), its frontmatter, and
    the console operations and loops it declares in `metadata` — the map the
    console's loops table and `tools/dash ops loops` are held equal to."""
    out = []
    for path in sorted(root.rglob("*.md")) if root.is_dir() else []:
        rel = path.relative_to(root)
        fm = frontmatter(path.read_text(encoding="utf-8"))
        meta = fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {}
        out.append({"name": "/" + ":".join(rel.with_suffix("").parts), "path": str(path.relative_to(core.REPO_ROOT)),
                    "frontmatter": fm, "ops": list(meta.get("ops") or []), "loops": list(meta.get("loops") or [])})
    return out


def loop_rows() -> list[dict]:
    """The console's loops table (core.LOOPS) joined to the schedule, the
    loop's local agent steps, its CI dispatch and the slash command that runs
    each of its stages."""
    fleet = core.load_yaml(core.DATA / "fleet.yml") or {}
    schedule = fleet.get("schedule") or {}
    steps = core.agent_steps()
    commands: dict[str, list[str]] = {}
    for c in slash_commands():
        for loop in c["loops"]:
            commands.setdefault(loop, []).append(c["name"])
    rows = []
    for loop in core.LOOPS:
        cron = schedule.get(loop["schedule_key"]) if loop["schedule_key"] else None
        rows.append({
            "id": loop["id"], "title": loop["title"], "workflow": f"{loop['workflow']}.yml",
            "schedule": core.describe_cron(cron) if cron else "dispatch only",
            "local_ops": list(loop["local_ops"]),
            "agent_steps": [f"{s['loop']}/{s['step']}" for s in steps if s["loop"] == loop["workflow"]],
            "dispatch": loop["workflow"] in core.DISPATCH_WORKFLOWS,
            "commands": commands.get(loop["id"], []),
        })
    return rows


def cmd_loops(args) -> int:
    rows = loop_rows()
    if args.json:
        print(json.dumps(rows, indent=1))
        return 0
    for r in rows:
        print(f"{r['id']}  —  {r['title']}")
        print(f"    {r['workflow']} · {r['schedule']}")
        print(f"    slash: {', '.join(r['commands']) or 'none'}")
        if r["local_ops"]:
            print(f"    ops:   {', '.join(r['local_ops'])}")
        if r["agent_steps"]:
            print(f"    agent: {', '.join(r['agent_steps'])} (loop-run)")
        if r["dispatch"]:
            print(f"    ci:    dispatch workflow={r['workflow'][:-4]}")
    return 0


def cmd_jobs(args) -> int:
    if ConsoleClient is None:
        return EXIT_NO_CONSOLE
    client = ConsoleClient.from_env()
    try:
        if args.job:
            return follow(client, {"id": args.job})
        jobs = client.jobs() or []
    except ConsoleError as exc:
        print(f"[ops] {exc}", file=sys.stderr)
        return EXIT_NO_CONSOLE
    for j in jobs[: args.limit]:
        print(f"{j['id']}  {j.get('status', ''):<11} {j.get('op', ''):<20} {j.get('created', '')[:19]}  "
              f"{j.get('title', '')}")
    if not jobs:
        print("no jobs on this console")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="dash ops", description=__doc__.split("\n\n")[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("list", help="every allowlisted operation, by group, with its gates")
    p.add_argument("--group")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("show", help="one operation: what it runs, its parameters and gates")
    p.add_argument("op")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("run", help="run one operation (through the console when it can)")
    p.add_argument("op")
    p.add_argument("params", nargs="*", metavar="key=value")
    p.add_argument("--confirm", action="store_true", help="the person approved a GitHub write or Claude spend")
    p.add_argument("--explain", action="store_true", help="print the argv and the gates; run nothing")
    where = p.add_mutually_exclusive_group()
    where.add_argument("--here", action="store_true", help="run in the foreground here, never the console")
    where.add_argument("--console", action="store_true", help="run only through the console")
    p = sub.add_parser("loops", help="every loop the console knows, its stages' operations and slash command")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("jobs", help="the console's recent jobs, or follow one")
    p.add_argument("job", nargs="?")
    p.add_argument("--limit", type=int, default=20)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd is None:
        args = build_parser().parse_args(["list"])
    return {"list": cmd_list, "show": cmd_show, "run": cmd_run, "jobs": cmd_jobs, "loops": cmd_loops}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
