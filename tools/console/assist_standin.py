#!/usr/bin/env python3
"""
assist_standin — a scripted stand-in for the `claude` CLI, for $0 end-to-end checks of the docked assistant.

It is NOT a model and never calls one. Put on a test console's PATH under the name `claude`, it accepts the
flags `dash-gen ai-run` passes, reads the prompt on stdin, starts the ONE MCP server named in --mcp-config
exactly as Claude Code would (stdio, that file's command and environment), calls a few page tools chosen by
keywords in the question, and prints the stream-json records ai-run parses. The dock, the job, ai-run, the
MCP layer, the page bridge and the browser are then all real; only the reasoning is canned, and every answer
says so. It exists because a real assistant message spends, and that yes is the maintainer's
(constitution § 13.6): this proves the plumbing without asking for it.

    mkdir -p /tmp/standin && ln -sf "$PWD/tools/console/assist_standin.py" /tmp/standin/claude
    PATH="/tmp/standin:$PATH" DASH_AI_LEDGER=/tmp/standin/ledger.json DASH_CONSOLE_JOBS=/tmp/standin/jobs \\
      CONSOLE_PORT=4014 DASH_CONSOLE_URL=http://127.0.0.1:4014 tools/console/run.sh

What it understands: "take me to / go to / open <a page's name>" navigates; "where / show me / point" rings
one control; "click / run" clicks the first button (so a confirming dialog can be reached and the refusal to
answer it seen); anything else is answered from one page_snapshot.

It refuses to run unless DASH_AI_LEDGER names a ledger of its own: ai-run records every run, and a stand-in's
row in the real ledger (~/.claude/ai-activity-ledger.json) would read as a session that never happened.
"""
from __future__ import annotations

import json
import os
import re
import sys
import uuid
from pathlib import Path

VERSION_LINE = "2.1.308 (Claude Code)"   # the CLI version the hub's local runner is proven against (docs/JEV.md)
NOTE = "This answer is from a scripted stand-in for the model: nothing was spent."


def _mcp_python() -> str | None:
    """A Python that has the `mcp` package: HARNESS_MCP_VENV, else the repo's .venv-mcp (tools/console/mcp.sh)."""
    root = Path(__file__).resolve().parents[2]
    for venv in (os.environ.get("HARNESS_MCP_VENV"), root / ".venv-mcp"):
        if venv and (Path(venv) / "bin" / "python").is_file():
            return str(Path(venv) / "bin" / "python")
    return None


def val(args: list[str], flag: str, default: str | None = None) -> str | None:
    return args[args.index(flag) + 1] if flag in args and args.index(flag) + 1 < len(args) else default


def out(record: dict) -> None:
    print(json.dumps(record), flush=True)


def page_path(pages: list[str], want: str) -> str | None:
    """The in-app path of the console page a person named, from a snapshot's `pages` lines."""
    for line in pages:
        for label, path in re.findall(r"([A-Za-z][A-Za-z &-]*?) (/[a-z0-9/_-]*)(?:,|$)", line.split(": ", 1)[-1]):
            if label.lower().strip() == want or want in label.lower():
                return path
    return None


async def converse(args: list[str], question: str, session: str, model: str) -> tuple[str, int]:
    from mcp import Client, StdioServerParameters  # noqa: PLC0415 — only a real run needs the package
    cfg = json.loads(Path(val(args, "--mcp-config") or "").read_text(encoding="utf-8"))["mcpServers"]["fleet"]
    params = StdioServerParameters(command=cfg["command"], args=cfg.get("args") or [],
                                   env={**os.environ, **(cfg.get("env") or {})})
    turns = 0
    async with Client(params) as cl:
        names = sorted(t.name for t in (await cl.list_tools()).tools)
        out({"type": "system", "subtype": "init", "model": model, "tools": [f"mcp__fleet__{n}" for n in names],
             "permissionMode": val(args, "--permission-mode"), "session_id": session})

        async def use(tool: str, arguments: dict) -> tuple[dict | None, str]:
            nonlocal turns
            turns += 1
            tid = f"toolu_{turns:02d}"
            out({"type": "assistant", "session_id": session, "message": {"content": [
                {"type": "tool_use", "id": tid, "name": f"mcp__fleet__{tool}", "input": arguments}]}})
            res = await cl.call_tool(tool, arguments)
            text = "".join(getattr(b, "text", "") for b in res.content)
            failed = bool(getattr(res, "is_error", False) or getattr(res, "isError", False))
            out({"type": "user", "session_id": session, "message": {"content": [
                {"type": "tool_result", "tool_use_id": tid, "is_error": failed, "content": text[:4000]}]}})
            if failed:
                return None, text
            try:
                doc = json.loads(text)
            except ValueError:
                return None, text
            return (doc if isinstance(doc, dict) else {"value": doc}), ""

        if "page_snapshot" not in names:
            return f"No page is attached to this session, so there is nothing for me to look at. _{NOTE}_", turns
        low, did = question.lower(), []
        snap, err = await use("page_snapshot", {})
        if snap is None:
            return f"I could not read the page: {err} _{NOTE}_", turns
        go = re.search(r"(?:take me to|go to|open)\s+(?:the\s+)?([a-z /-]+?)(?:\s+page)?(?:[.,?!]|\s+and\b|$)", low)
        if go:
            path = page_path(snap.get("pages") or [], go.group(1).strip())
            if path:
                moved, err = await use("page_navigate", {"path": path})
                did.append(f"went to `{path}`" if moved else f"did not go to `{path}`: {err}")
                snap = (await use("page_snapshot", {}))[0] or snap
            else:
                did.append(f"found no console page called “{go.group(1).strip()}”")
        outline = str(snap.get("outline") or "")
        heads = [h.strip("# ").strip() for h in re.findall(r"^\s*#+ .+$", outline, re.M)][:6]
        refs = re.findall(r"\[(e\d+)\] ([a-z][a-z ]*?) \"([^\"]{1,60})", outline)
        if re.search(r"where|show me|point", low) and refs:
            stop = {"where", "show", "point", "that", "this", "page", "take", "what", "there", "looking"}
            words = [w for w in re.findall(r"[a-z]{4,}", low) if w not in stop]
            pick = max(refs, key=lambda r: sum(w in r[2].lower() for w in words))   # the first of the best matches
            shown, err = await use("page_highlight", {"ref": pick[0], "note": "here"})
            did.append(f"pointed at the {pick[1]} “{pick[2]}”" if shown else f"could not point at it: {err}")
        if re.search(r"\bclick\b|\brun\b", low) and refs:
            pick = next((r for r in refs if r[1] == "button"), refs[0])
            done, err = await use("page_click", {"ref": pick[0]})
            did.append(f"clicked the {pick[1]} “{pick[2]}”" if done else f"did not click “{pick[2]}”: {err}")
        lines = [f"You are on **{snap.get('title', '?')}** (`{snap.get('route', '?')}`), and the dock is in "
                 f"**{snap.get('mode', '?')}** mode.", ""]
        if heads:
            lines += ["On the page:", *[f"- {h}" for h in heads], ""]
        lines.append(f"It has {snap.get('refs', 0)} controls I can name"
                     + (f" and {len(snap['dialogs'])} open dialog(s)" if snap.get("dialogs") else "") + ".")
        if did:
            lines += ["", "What I did on the page:", *[f"- {d}" for d in did]]
        lines += ["", f"_Source: `page_snapshot`. {NOTE}_"]
        return "\n".join(lines), turns


def main(argv: list[str]) -> int:
    if "--version" in argv:
        print(VERSION_LINE)
        return 0
    ledger = os.environ.get("DASH_AI_LEDGER") or ""
    if not ledger or Path(ledger).expanduser() == Path("~/.claude/ai-activity-ledger.json").expanduser():
        sys.stderr.write("assist_standin: refusing to run — set DASH_AI_LEDGER to a scratch file first, so this "
                         "stand-in's runs never land in the real AI ledger\n")
        return 2
    try:
        import anyio  # noqa: PLC0415
        import mcp  # noqa: F401, PLC0415
    except ModuleNotFoundError:
        python = _mcp_python()
        if python is None or os.environ.get("ASSIST_STANDIN_REEXEC"):
            sys.stderr.write("assist_standin: needs the `mcp` package — run tools/console/mcp.sh --list-tools once "
                             "to create .venv-mcp, or set HARNESS_MCP_VENV\n")
            return 2
        os.environ["ASSIST_STANDIN_REEXEC"] = "1"
        os.execv(python, [python, str(Path(__file__).resolve()), *argv])
    prompt = sys.stdin.read()
    question = prompt.split("# THE QUESTION", 1)[-1].split("# THE PAGE", 1)[0].strip()
    session = val(argv, "--session-id") or str(uuid.uuid4())
    model = val(argv, "--model") or "stand-in"
    answer, turns = anyio.run(converse, argv, question, session, model)
    out({"type": "assistant", "session_id": session, "message": {"content": [{"type": "text", "text": answer}]}})
    out({"type": "result", "subtype": "success", "is_error": False, "result": answer, "num_turns": turns + 1,
         "total_cost_usd": 0.0, "duration_ms": 1, "session_id": session, "modelUsage": {model: {"costUSD": 0.0}},
         "permission_denials": []})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
