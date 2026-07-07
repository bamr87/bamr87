#!/usr/bin/env python3
"""SessionStart hook for the Future-Features pipeline.

Injects a short standing instruction into every Claude Code session so the
Future-Features workflow is active: Claude knows it can capture ideas with
`/future-features` and should run the `feature-scout` sub-agent at natural
stopping points to harvest feature ideas from the thread for human review.

Contract: prints SessionStart `additionalContext` JSON to stdout.
Fail-open: any error -> exit 0 with no output (never break a session).
Opt out : set FUTURE_FEATURES_AUTOSCOUT=0 (off/false/no) to silence the scout nudge.
"""
import json
import os
import sys

# The injected text below intentionally contains the self-markers
# ("future-features" / "feature-scout") that the Stop hook's SELF_MARKERS filter
# excludes from its scan, so this context never self-triggers the scout nudge.


def main() -> None:
    try:
        sys.stdin.read()  # consume stdin; not needed here
    except Exception:
        pass

    autoscout = os.environ.get("FUTURE_FEATURES_AUTOSCOUT", "1").strip().lower()
    scout_on = autoscout not in ("0", "off", "false", "no")

    context = (
        "Future-Features pipeline is active in this repo.\n"
        "- Capture a single idea anytime with `/future-features <idea>` — it drafts a "
        "full spec and, on your approval, adds it to `_data/roadmap.yml` for the right repo.\n"
        "- The backlog + schema live in `_data/roadmap.yml`; target repos come from "
        "`_data/projects.yml` (use `bamr87` for the monorepo/dash itself).\n"
    )
    if scout_on:
        context += (
            "- When this session has surfaced feature-worthy ideas (wishes, "
            '"it\'d be nice if…", repeated friction, automation opportunities, TODO '
            'asides), proactively invoke the `feature-scout` sub-agent (Task/Agent tool, '
            'subagent_type "feature-scout") to analyze the thread and author '
            "roadmap-ready specs. Present each for review; write only approved entries "
            "to `_data/roadmap.yml`. Never backlog without explicit human approval.\n"
            "- A Stop hook may also remind you once per session when such language appears."
        )

    out = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }
    print(json.dumps(out))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Fail open: a misbehaving hook must never block a session.
        sys.exit(0)
