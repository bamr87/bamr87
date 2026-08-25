#!/usr/bin/env python3
"""Stop hook for the Future-Features pipeline.

When a session is winding down and feature-signal language has appeared in the
USER's messages, nudge the main agent — at most ONCE per session — to run the
`feature-scout` sub-agent before stopping, so feature ideas are captured for
review instead of lost.

Contract:
  stdin  : JSON with `transcript_path`, `session_id`, `stop_hook_active`, ...
  stdout : on a nudge, JSON `{"decision": "block", "reason": "..."}` — the Stop
           hook continuation that asks Claude to keep going and run the scout;
           otherwise nothing (the session stops normally).
Fail-open: any error / missing data -> exit 0 silently.
Opt out  : FUTURE_FEATURES_AUTOSCOUT in {0,off,false,no} disables it.
Throttle : one nudge per session (marker file under the system temp dir).
"""
import hashlib
import json
import os
import re
import sys
import tempfile

SIGNALS = [
    r"it'?d be nice", r"it would be nice", r"would be nice", r"nice to have",
    r"feature request", r"feature idea", r"new feature", r"future feature",
    r"we should add", r"should support", r"could add", r"ought to support",
    r"would be (?:great|cool|handy|useful)", r"\bi wish\b", r"\bwish ?list\b",
    r"down the (?:road|line)", r"in the future", r"\beventually\b",
    r"stretch goal", r"\bbacklog\b", r"\broadmap\b", r"enhancement",
    r"would love (?:to|a|an|if|having)", r"what if we", r"automate this",
]
SIGNAL_RE = re.compile("|".join(SIGNALS), re.IGNORECASE)
MIN_USER_TURNS = 2

# Texts containing these markers are our own injected pipeline context — skip
# them so the scanner never self-triggers.
SELF_MARKERS = ("future-features", "feature-scout")


def read_stdin_json() -> dict:
    try:
        return json.loads(sys.stdin.read() or "{}")
    except Exception:
        return {}


def user_texts(transcript_path: str) -> list:
    """Return the text of user-authored messages from the JSONL transcript.

    Only `text` blocks of user-role messages are collected — tool results and
    assistant output are deliberately excluded.
    """
    texts = []
    try:
        with open(transcript_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                if ev.get("type") != "user":
                    continue
                content = (ev.get("message") or {}).get("content")
                if isinstance(content, str):
                    texts.append(content)
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            texts.append(block.get("text", ""))
                        elif isinstance(block, str):
                            texts.append(block)
    except Exception:
        return []
    return texts


def main() -> None:
    autoscout = os.environ.get("FUTURE_FEATURES_AUTOSCOUT", "1").strip().lower()
    if autoscout in ("0", "off", "false", "no"):
        sys.exit(0)

    data = read_stdin_json()
    if data.get("stop_hook_active"):  # already inside a stop-hook continuation
        sys.exit(0)

    session_id = str(data.get("session_id") or "unknown")
    transcript = data.get("transcript_path") or ""
    if not transcript or not os.path.exists(transcript):
        sys.exit(0)

    # Throttle: one nudge per session.
    key = hashlib.sha1(session_id.encode("utf-8")).hexdigest()[:16]
    state_dir = os.path.join(tempfile.gettempdir(), "claude-future-features")
    marker = os.path.join(state_dir, key + ".nudged")
    if os.path.exists(marker):
        sys.exit(0)

    texts = user_texts(transcript)
    if len([t for t in texts if t.strip()]) < MIN_USER_TURNS:
        sys.exit(0)  # trivial session — nothing worth scouting

    scan = "\n".join(
        t for t in texts if not any(m in t.lower() for m in SELF_MARKERS)
    )
    hits = sorted({m.group(0).lower() for m in SIGNAL_RE.finditer(scan)})
    if not hits:
        sys.exit(0)  # no marker written — a later turn can still trigger

    # Record the nudge so it fires at most once per session.
    try:
        os.makedirs(state_dir, exist_ok=True)
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write(session_id)
    except Exception:
        pass

    reason = (
        "Future-Features: this session surfaced possible feature ideas (signals: "
        + ", ".join(hits[:8])
        + '). Before you stop, invoke the `feature-scout` sub-agent (Task/Agent tool, '
        'subagent_type "feature-scout") to analyze the whole thread and author '
        "roadmap-ready specs. Present each proposed spec for the user's "
        "review/approval; append only approved entries to `_data/roadmap.yml` "
        "(route each to the right repo via `_data/projects.yml`, or `bamr87` for the "
        "monorepo). If, on reflection, nothing rises to a genuine feature request, say "
        "so in one line and stop. (Fires at most once per session; disable with "
        "FUTURE_FEATURES_AUTOSCOUT=0.)"
    )
    print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Fail open: a misbehaving hook must never block a session.
        sys.exit(0)
