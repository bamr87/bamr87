#!/usr/bin/env python3
"""SessionStart hook: the starred-repo radar brief (docs/STARGAZER.md).

Every local Claude Code session starts knowing which of the account's GitHub
stars bear on the project at hand, what was starred lately and what is rising
in the fleet's topics, so a starred repo is considered before something is
built from scratch. The text is `tools/fleetcore/stars.py` `brief()` over the
committed `_data/stars.json`; the project is the session's working directory:
a submodule by its path, the hub itself, or (outside the hub) the fleet repo
whose GitHub remote the checkout has.

Contract: prints SessionStart `additionalContext` JSON to stdout.
Fast    : standard library only, one JSON read; it never parses fleet.yml and
          never touches the network.
Fail-open: any error -> exit 0 with no output (never break a session).
Opt out : STARS_SESSION_BRIEF=0 (off/false/no).
--user  : the form `tools/dash stars hook --install --yes` writes into
          ~/.claude/settings.json for sessions outside the hub. It stays quiet
          where the project already runs this hook from its own settings
          (the hub and its worktrees), so a session never gets it twice.
"""
import json
import os
import sys
from pathlib import Path

HUB = Path(__file__).resolve().parents[2]


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        payload = {}
    if os.environ.get("STARS_SESSION_BRIEF", "1").strip().lower() in ("0", "off", "false", "no"):
        return
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd())
    if "--user" in sys.argv[1:] and (project_dir / ".claude" / "hooks" / "stars_session_start.py").is_file():
        return  # the project's own settings run it
    sys.path.insert(0, str(HUB / "tools"))
    from fleetcore import stars  # standard library only

    doc = stars.load(HUB / "_data" / "stars.json")
    if not doc:
        return
    cwd = payload.get("cwd") or str(project_dir)
    project = stars.project_for(cwd, doc.get("fleet") or [], HUB)
    text = stars.brief(doc, project)
    if not text:
        return
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # fail open: a misbehaving hook must never block a session
    sys.exit(0)
