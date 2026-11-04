#!/usr/bin/env python3
"""
File: tools/jev/adapters/common.py
Description: What every adapter reads the same way — the engine's redacted
             trace (the session's final result text), a filer's last-line JSON,
             the strings that must never reach a public tracker (this machine's
             home, host name and work root), the wording a sandboxed, offline
             shell leaves behind (flagged for the reviewer, never a reason to
             reject), the fleet's lockfile policy (`_data/fleet.yml`
             `dependencies.lockfile_patterns`, the one list CI's publish steps
             and the local previews both apply) and a `diff --git` header
             parser that reads a path with a space or git's quoted form.
             Lifted out of repo_scout.py, fleet_pulse_doctor.py and
             repo_evolution_evolve.py, which carried three copies (the #641
             review); behaviour is unchanged but for one widening: the
             local-artefact wording now includes Claude Code's own `dontAsk`
             refusal for every adapter (scout's copy lacked it).
Author: bamr87
Created: 2026-11-04
Version: 0.1.0
Usage: `from .common import last_json, result_text, private_strings, LOCAL_ARTEFACT_RX, …`
Dependencies: Python 3.12 stdlib. No dash-gen import (SCHEMA.md).
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping

#: the final `result` text is clipped to this many characters
RESULT_MAX_CHARS = 20_000
#: what a sandboxed, offline shell says when it is refused — flagged for the
#: reviewer, never a reason to reject: a repo about sandboxes may legitimately
#: say it, and an agent must not diagnose from it
LOCAL_ARTEFACT_RX = re.compile(r"EAI_AGAIN|ENOTFOUND|Could not resolve host|getaddrinfo|"
                               r"Operation not permitted|sandbox-exec|Network is unreachable|"
                               r"has been denied because Claude Code is running in don't ask mode")
#: the fleet's lockfile policy when `_data/fleet.yml` cannot be read: the same
#: list `dependencies.lockfile_patterns` carries (test_evolution.py holds CI's
#: publish step to it; test_jev_adapter_repo_evolution_evolve.py holds this one)
DEFAULT_LOCKFILE_PATTERNS = ("package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock",
                             "Gemfile.lock", "poetry.lock", "Pipfile.lock", "uv.lock", "composer.lock")
_DIFF_HEADER = "diff --git "
_C_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "a": "\a", "b": "\b", "f": "\f", "v": "\v"}


def last_json(text: str) -> dict:
    """A filer's result: the last non-empty line of its stdout, a JSON object."""
    lines = [ln for ln in (text or "").strip().splitlines() if ln.strip()]
    if not lines:
        raise ValueError("no output")
    out = json.loads(lines[-1])
    if not isinstance(out, dict):
        raise ValueError("not a JSON object")
    return out


def result_text(events: Iterable[dict], limit: int = RESULT_MAX_CHARS) -> str:
    """The session's final `result` text (ai-run's trace is redacted), clipped."""
    for e in reversed(list(events)):
        if e.get("type") == "result":
            return str(e.get("result") or "")[:limit]
    return ""


def private_strings(ctx) -> list[str]:
    """What must never reach a public tracker: this machine's home, host name
    and work root (the short or empty ones dropped, so nothing matches by accident)."""
    return [s for s in (str(ctx.home), ctx.hostname, str(ctx.work_root)) if s and len(s) > 3]


#: what may sit next to a host name without making it part of a longer word:
#: a `(` after it is a call (`main()`), a `/` on either side a path component
#: (`blob/main/docs`); a leaked home path is caught by the home's own substring
_TOKEN_BEFORE = r"[A-Za-z0-9_/-]"
_TOKEN_AFTER = r"[A-Za-z0-9_(/-]"


def private_pattern(ctx) -> re.Pattern | None:
    """One regex for everything `private_strings` names: a path (the home, the
    work root) matches as a substring, since an absolute path is never a
    common word; the HOST NAME matches only as a whole token (not inside
    `workflow`, `def main`, `homepage`, `minimal`, `blob/main/docs` for a Mac
    called `work`, `main`, `home` or `mini`), as a hostname is often a word.
    None when nothing is long enough to match."""
    parts = []
    host = str(getattr(ctx, "hostname", "") or "")
    for s in private_strings(ctx):
        if s == host:
            parts.append(rf"(?i:(?<!{_TOKEN_BEFORE}){re.escape(s)}(?!{_TOKEN_AFTER}))")
        else:
            parts.append(re.escape(s))
    return re.compile("|".join(parts)) if parts else None


def leaks_private(text: str, ctx) -> bool:
    """Whether `text` carries this machine's home, work root or host name."""
    rx = private_pattern(ctx)
    return bool(rx and rx.search(text))


#: a verb that publishes, at the start of a command segment; `git` may carry
#: its global options first (`git -C dir push`, `git --git-dir=.git commit`)
PUBLISH_VERB_RX = re.compile(
    r"^(?:git(?:\s+(?:-C\s+\S+|-c\s+\S+|--[A-Za-z][\w-]*(?:=\S+)?))*\s+(?:push|checkout\s+-b|commit|tag)|gh\s+pr\s+create)\b")
_SEGMENT_SPLIT_RX = re.compile(r"\s*(?:&&|\|\||;|\||\n)\s*")
_LEADING_ENV_RX = re.compile(r"^(?:(?:env|sudo|nohup|time|exec)\s+|[A-Za-z_][A-Za-z0-9_]*=(?:'[^']*'|\"[^\"]*\"|\S*)\s+)+")


def command_segments(command: str) -> list[str]:
    """The simple commands of a shell line, in order: split on `&&`, `||`, `;`,
    `|` and newlines, a leading `( ` / `{ ` dropped, leading variable
    assignments and `env` / `sudo` / `nohup` / `time` / `exec` prefixes
    stripped — so a publishing verb hidden behind `cd pkg &&`, an `env
    GIT_DIR=.git` prefix or a `|` is seen where the segment starts."""
    out = []
    for raw in _SEGMENT_SPLIT_RX.split(command or ""):
        seg = raw.strip().lstrip("({ ").rstrip(")} ").strip()
        seg = _LEADING_ENV_RX.sub("", seg)
        if seg:
            out.append(seg)
    return out


def publishing_commands(command: str) -> list[str]:
    """The segments of `command` that start with a publishing verb."""
    return [seg for seg in command_segments(command) if PUBLISH_VERB_RX.match(seg)]


def lockfile_patterns(fleet: Mapping | None) -> tuple[str, ...]:
    """`dependencies.lockfile_patterns` from the fleet document (the engine's
    `ctx.fleet`), else the defaults — never an empty policy."""
    deps = (fleet or {}).get("dependencies") if isinstance(fleet, Mapping) else None
    raw = deps.get("lockfile_patterns") if isinstance(deps, Mapping) else None
    pats = tuple(str(p) for p in raw if isinstance(p, str) and p.strip()) if isinstance(raw, list) else ()
    return pats or DEFAULT_LOCKFILE_PATTERNS


def lockfile_regex(patterns: Iterable[str]) -> re.Pattern:
    """A path matcher for the policy's basenames (anchored at a path boundary)."""
    alts = "|".join(re.escape(p) for p in patterns)
    return re.compile(rf"(^|/)(?:{alts})$")


def _unquote(s: str) -> str:
    """git's quoted path (core.quotePath): C escapes and \\ooo octal bytes."""
    out = bytearray()
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            octal = s[i + 1:i + 4]
            if len(octal) == 3 and all(c in "01234567" for c in octal):
                out += bytes([int(octal, 8)])
                i += 4
                continue
            if nxt in _C_ESCAPES:
                out += _C_ESCAPES[nxt].encode("utf-8")
                i += 2
                continue
        out += ch.encode("utf-8", errors="surrogateescape")
        i += 1
    return out.decode("utf-8", errors="surrogateescape")


def diff_header_paths(line: str) -> tuple[str, str] | None:
    """The two paths of a `diff --git a/<old> b/<new>` line, or None. git
    prints a path with a space unquoted (`a/new file.txt b/new file.txt`) and
    an unusual one quoted (`"a/\\303\\274.txt" "b/\\303\\274.txt"`); both read."""
    if not line.startswith(_DIFF_HEADER):
        return None
    rest = line[len(_DIFF_HEADER):].rstrip("\r\n")
    if rest.startswith('"'):
        m = re.fullmatch(r'"((?:[^"\\]|\\.)*)" "((?:[^"\\]|\\.)*)"', rest)
        if not m:
            return None
        a, b = _unquote(m.group(1)), _unquote(m.group(2))
    else:
        # unquoted: the old and the new path are equal for every diff the engine harvests
        # (no renames), so the split is at the middle ` b/` that leaves two equal halves
        parts = rest.split(" b/")
        a = b = None
        for k in range(1, len(parts)):
            left, right = " b/".join(parts[:k]), " b/".join(parts[k:])
            if left.startswith("a/") and left[2:] == right:
                a, b = left, "b/" + right
                break
        if a is None:
            if len(parts) != 2 or not parts[0].startswith("a/"):
                return None
            a, b = parts[0], "b/" + parts[1]
    if not (a.startswith("a/") and b.startswith("b/")):
        return None
    return a[2:], b[2:]


def diff_sections(text: str) -> tuple[str, list[tuple[str, str, bool]]]:
    """A unified diff split on its `diff --git` headers: the preamble, then
    (path, section, is_new) per file — `is_new` when the section creates the
    file (`new file mode` or `--- /dev/null` in its header), which is how an
    untracked file the engine harvested (`git diff --no-index /dev/null …`) reads."""
    lines = text.splitlines(keepends=True)
    starts = [i for i, ln in enumerate(lines) if diff_header_paths(ln) is not None]
    if not starts:
        return text, []
    pre = "".join(lines[:starts[0]])
    out = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(lines)
        section = "".join(lines[start:end])
        path = diff_header_paths(lines[start])[1]
        head = lines[start:min(end, start + 6)]
        is_new = any(ln.startswith("new file mode") or ln.startswith("--- /dev/null") for ln in head)
        out.append((path, section, is_new))
    return pre, out
