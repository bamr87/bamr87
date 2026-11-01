#!/usr/bin/env python3
"""
fleet_context — the read-only planes behind the loop runner's context pack.

JEV's local loop runner seals its agent: no network, an empty MCP config, a
Seatbelt sandbox (constitution 13.8, "both layers"). A sealed agent cannot ask
the lake what CI said last week, the code index where a pattern already lives,
or the telemetry which commands keep failing in this repo. The HOST can. This
module is the host's half of that: one bounded, read-only pass over the local
planes that prints ONE JSON document (`fleet-context/v1`), which the engine
renders as `<brief_dir>/context.md` beside the brief in the throwaway clone.
The pack is DATA the agent may read, never instructions it must follow. A live
MCP for the agent is out of scope: it would need its own 13.8 analysis.

Five sections, each stamped with its source, its freshness and its status:

  lake_issues       issues and PRs of the repo CLOSED in the window (the open
                    ones are already in the brief), the scout's flagged
  lake_ci           per workflow on the tracked branch: runs, failures, the
                    failure streak, the failing job / step where recorded
  lake_agents       CI agent runs, local Claude Code sessions, and the Bash
                    commands that failed in them — by command HEAD (an
                    allowlist that never reaches an option's value), never
                    the command, the prompt, the cwd or the branch
  index_code        the Kilo code index (Qdrant + native Ollama) for up to
                    three queries; code only from the hub and the target —
                    the registry has no visibility field and a sibling may be
                    private, so a sibling's hit is a pointer with no code —
                    and only from a file still as indexed: the target's hits
                    checked against the agent's clone (--target-dir), the
                    hub's against this checkout
  telemetry_errors  Claude Code's own OTel events in Elasticsearch: failed tool
                    results by tool and command head, plus the API errors

The rules it keeps (constitution § 10: new tools are read-only, with
allowlists, caps, time limits and redaction):

  read-only   the lake is opened `mode=ro` + `query_only`, never through
              fleet_lake.connect (which creates and migrates); HTTP is an
              allowlist of read routes on the configured planes, whose URL
              must be scheme://host:port (a path or query is refused), with
              no proxy and no redirect; --target-dir is only read (lstat,
              no link followed); nothing here talks to GitHub
  bounded     in wall-clock time: every request <= 5 s and everything under
              --deadline-s, a plane that trickles bytes included; a plane
              that is down, slow or missing becomes a section saying so with
              its remedy, and the command still prints the document, exit 0
  capped      rows per section, lines and characters per snippet, queries
  redacted    $HOME -> ~, the host name -> <host>, temp dirs -> <tmp>,
              addresses -> <email>, credential shapes masked, control
              characters stripped — over the WHOLE document, once every
              section is in, before printing (credentials also before every
              clip, so a token cut in half cannot survive as its first half)

Exit codes: 0 with a document (whatever the planes said), 2 for a usage
error. Fixture tests (no network beyond in-process loopback stubs):
`python3 test_fleet_context.py`.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import functools
import hashlib
import http.client
import json
import os
import platform
import re
import shlex
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.parse
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("fleet_context requires PyYAML: pip install pyyaml\n")
    sys.exit(2)

import fleet_index
import fleet_lake
import fleet_observe

REPO_ROOT = Path(__file__).resolve().parents[3]
FLEET_DEFAULT = REPO_ROOT / "_data" / "fleet.yml"
REGISTRY_DEFAULT = REPO_ROOT / "_data" / "projects.yml"

SCHEMA = "fleet-context/v1"
SECTIONS = ("lake_issues", "lake_ci", "lake_agents", "index_code", "telemetry_errors")
SOURCES = {"lake_issues": "lake", "lake_ci": "lake", "lake_agents": "lake",
           "index_code": "qdrant", "telemetry_errors": "elasticsearch"}
STATUSES = ("ok", "empty", "stale", "unavailable")
#: the document's own words: its schema id, section keys, statuses and sources,
#: every field name the planes write (the document's, a section's, a row's) and
#: every row kind. `Scrubber.obj` never rewrites a string that IS one of them
#: (one that contains one is masked as ever): a host called `stale`, `rows`,
#: `note`, `name` or `path` would turn a status, a key or a field into `<host>`,
#: and the engine would read the section as malformed, so mode require would
#: block an item whose planes all answered. tools/jev/context.SCHEMA_WORDS, the
#: engine's twin, holds every one of them (tools/test_jev_context.py checks).
DOC_WORDS = frozenset({
    SCHEMA, *SECTIONS, *SOURCES.values(), *STATUSES,
    # the document and a section
    "schema", "generated_at", "nwo", "name", "window_days", "queries", "sections", "target_dir",
    "status", "source", "as_of", "age_hours", "note", "elapsed_ms", "truncated", "rows",
    # a row's fields, section by section
    "number", "kind", "title", "labels", "closed_at", "scout",
    "workflow", "path", "runs", "failures", "last_conclusion", "last_at", "fail_streak", "failing_steps",
    "count", "errors", "permission_denials", "turns", "cost_usd", "models", "tool_calls", "tool_errors", "head",
    "query", "project", "start_line", "end_line", "score", "snippet", "withheld", "tool",
    # a row's kinds, and the hub's project name in a code hit
    "issue", "pr", "ci_agent_runs", "local_sessions", "failing_command", "tool_error", "api_errors", fleet_index.HUB,
})

DAYS_DEFAULT = 30
MAX_DAYS = 365
DEADLINE_DEFAULT_S = 20.0
MAX_DEADLINE_S = 300.0
REQUEST_TIMEOUT_S = 5.0
STALE_AFTER_H = 72.0
MAX_BODY_BYTES = 16 * 1024 * 1024

MAX_QUERIES = 3
MAX_QUERY_CHARS = 300
CAP_ISSUES = 25
CAP_LABELS = 10
CAP_WORKFLOWS = 15
CAP_FAILING_STEPS = 5
FAILED_RUNS_SCANNED = 20      # per workflow, newest first, for its failing steps
CAP_COMMANDS = 10
COMMAND_SAMPLE = 2000         # newest failed Bash calls read from the lake
CAP_HITS = 4                  # per query
SEARCH_LIMIT = 12             # asked per query; the hits past CAP_HITS are counted as truncated
CAP_TELEMETRY = 10
TELEMETRY_SAMPLE = 500        # newest failed tool results read from Elasticsearch
SNIPPET_LINES = 12
SNIPPET_CHARS = 600
TITLE_CHARS = 140
LABEL_CHARS = 50
NAME_CHARS = 80               # workflow, job, step and tool names
HEAD_CHARS = 60
HEAD_TOKENS = 3
CAP_MODELS = 6                # per ci_agent_runs row; the rest fold into "(other)"
#: untrusted text is cut to its clip plus this BEFORE the credential masks run
#: over it (longer than any credential shape but a key block, whose pattern
#: masks to the end of what is left), so a 100 KB title costs a 652-char scan
CLIP_SLACK = 512
HEAD_SCAN_CHARS = 8192        # of a command, read for its head
LAKE_TEXT_CHARS = 1024        # of a lake text column, read at all (SQL substr)

SCOUT_LABEL_DEFAULT = "ai-scout"   # repo_scout.DEFAULTS["label"]; fleet.yml `scout.label` overrides
ERROR_CONCLUSIONS = tuple(fleet_lake.ERROR_CONCLUSIONS)
# A run with no verdict says nothing about the workflow's health: a skipped run
# was gated off, a cancelled one superseded by its concurrency group.
NO_VERDICT = ("skipped", "cancelled")
# fleet_triage.PR_EVENTS: a red pull-request run is the gate doing its job, not
# a standing failure, and reporting it as one sends an agent to "fix" a
# workflow that is green on the tracked branch (bamr87/bamr87#205).
PR_EVENTS = ("pull_request", "pull_request_target")

REMEDY_LAKE = "run `tools/dash lake sync`"
REMEDY_SESSIONS = "run `tools/dash lake sessions`"
REMEDY_LOCKED = "retry; a `lake sync` may hold the lock"
REMEDY_PLANES = "start the planes with `tools/dash observe up`"
REMEDY_OLLAMA = "start native Ollama (`ollama serve`, model `ollama pull nomic-embed-text`)"
REMEDY_TELEMETRY = "point Claude Code at the collector with `tools/dash observe claude enable --apply`"
REMEDY_DEADLINE = "raise --deadline-s"
REMEDY_INDEX = "let Kilo re-scan (kilo.jsonc `indexing`)"
#: the target's hits checked against the agent's clone (--target-dir) and behind it: Kilo scanned the hub's
#: checkout of the target, which can lag the branch head the clone holds, and `{how}` brings it there
REMEDY_INDEX_CLONE = "{how}, then let Kilo re-scan"
#: no --target-dir, and the hub running the planes holds no checkout of the target to check its hits against
REMEDY_CHECKOUT = "`git submodule update --init projects/{dir}`, or pass --target-dir (a loop run passes its clone)"

#: The hub's copies of the registry: the registry itself and the projections
#: generated from it. A hit there repeats what the brief already says about
#: the repository (its description, category and stack), so the search leaves
#: them out.
INDEX_EXCLUDED = ("_data/projects.yml", "_data/cv_portfolio.json", "projects/SCHEMA.md")
#: a file larger than this is not read to check a hit against the checkout
FRESH_MAX_BYTES = 4 * 1024 * 1024

NWO_RX = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
NAME_RX = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
COLLECTION_RX = re.compile(r"^[\w.-]{1,128}$")


# --------------------------------------------------------------------------- #
# errors + the clock
# --------------------------------------------------------------------------- #
class Unavailable(Exception):
    """A plane that cannot answer: one line of reason, one of remedy."""

    def __init__(self, reason: str, remedy: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.remedy = remedy

    def note(self) -> str:
        return f"{self.reason} — {self.remedy}" if self.remedy else self.reason


class RouteRefused(Exception):
    """A request outside READ_ROUTES. Raised before any socket opens."""


class Deadline:
    """The overall --deadline-s every plane shares, and the per-request cap under it."""

    def __init__(self, seconds: float, clock=time.monotonic):
        self.seconds = float(seconds)
        self._clock = clock
        self._end = clock() + self.seconds

    def left(self) -> float:
        return self._end - self._clock()

    def expired(self) -> bool:
        return self.left() <= 0

    def check(self) -> None:
        if self.expired():
            raise Unavailable(f"skipped: the --deadline-s {self.seconds:g} budget was spent before this "
                              f"plane was asked", REMEDY_DEADLINE)

    def timeout(self, cap: float = REQUEST_TIMEOUT_S) -> float:
        self.check()
        return max(0.05, min(cap, self.left()))

    def within(self, what: str) -> None:
        """Mid-section, per row: past the budget the section stops and says so.
        The SQLite progress handler only reaches inside a query; the Python
        work on each row is bounded here."""
        if self.expired():
            raise Unavailable(f"cut off: the --deadline-s {self.seconds:g} budget ran out while reading {what}",
                              REMEDY_DEADLINE)


def _within(deadline: Deadline | None, what: str) -> None:
    if deadline is not None:
        deadline.within(what)


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_z(value) -> str | None:
    """Any stamp the planes emit (7-digit .NET ticks, +00:00, ms) -> YYYY-MM-DDTHH:MM:SSZ."""
    ts = value if isinstance(value, dt.datetime) else fleet_lake.parse_iso(value)
    return fleet_lake.iso(ts) if ts else None


def age_hours(as_of: str | None, now: dt.datetime) -> float | None:
    ts = fleet_lake.parse_iso(as_of)
    if ts is None:
        return None
    return round(max(0.0, (now - ts).total_seconds() / 3600.0), 1)


# --------------------------------------------------------------------------- #
# pure: redaction
# --------------------------------------------------------------------------- #
# C0/C1 controls (newline and tab survive in a snippet), U+2028/U+2029 (a line
# end to str.splitlines, not to CommonMark) and every Unicode format (Cf)
# character: zero-width and BOM, the bidi marks and overrides a "Trojan Source"
# title would use to read one way and run another, the word joiner and the
# invisible operators, the soft hyphen, and the tag characters, which spell text
# a model reads but a person reviewing the pack cannot see. Titles and snippets
# are untrusted text; this strips, never interprets. tools/jev/context.py
# carries the same pattern (tools/test_jev_context.py holds the two equal).
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\xad\u0600-\u0605\u061c\u06dd\u070f\u0890\u0891"
                   r"\u08e2\u180e\u200b-\u200f\u2028-\u202e\u2060-\u206f\ufeff\ufff9-\ufffb\U000110bd"
                   r"\U000110cd\U00013430-\U0001343f\U0001bca0-\U0001bca3\U0001d173-\U0001d17a"
                   r"\U000e0000-\U000e007f]")
_BREAKS = re.compile(r"[\t\n\r]+")
# What fleet_observe.REDACTIONS does not already cover: a whole private-key
# block (FIRST, so nothing else takes only its marker), the shorter and the
# user-to-server GitHub shapes, npm tokens, Authorization and API-key headers,
# a bare bearer/token value (one with a digit, so "token authentication" stays
# English), URL userinfo, AWS and Slack keys, and a secret-named variable
# assigned inline in a command. tools/jev/context.py carries this list
# verbatim (it cannot import dash-gen); tools/test_jev_context.py holds the two
# equal, so engine-only text is masked exactly as the planes mask theirs.
EXTRA_REDACTIONS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)"),
     "[REDACTED PRIVATE KEY]"),
    (re.compile(r"\b(gh[pousr])_[A-Za-z0-9]{16,}"), r"\1_[REDACTED]"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{16,}"), "github_pat_[REDACTED]"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{8,}"), "sk-ant-[REDACTED]"),
    (re.compile(r"\bnpm_[A-Za-z0-9]{36}\b"), "npm_[REDACTED]"),
    (re.compile(r"(?i)\b((?:proxy-)?authorization\s*:\s*(?:(?:bearer|token|basic|digest)\s+)?)"
                r"[A-Za-z0-9._~+/=\-]{8,}"), r"\1[REDACTED]"),
    (re.compile(r"(?i)\b((?:x-)?(?:api[-_]?key|auth[-_]?token|access[-_]?token|private[-_]?token)['\"]?"
                r"\s*[:=]\s*['\"]?)[A-Za-z0-9._~+/=\-]{8,}"), r"\1[REDACTED]"),
    (re.compile(r"(?i)\b(bearer|token)(\s+)(?=[A-Za-z0-9._~+/=\-]*\d)[A-Za-z0-9._~+/=\-]{12,}"),
     r"\1\2[REDACTED]"),
    (re.compile(r"\b([a-z][a-z0-9+.-]*://)[^\s/@:'\"`]+:[^\s/@'\"`]+@"), r"\1[REDACTED]@"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AKIA[REDACTED]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "xox-[REDACTED]"),
    (re.compile(r"\b([A-Z][A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|APIKEY|PRIVATE_KEY)[A-Z0-9_]*)"
                r"=(['\"]?)[^\s'\"$]{8,}\2"), r"\1=[REDACTED]"),
]
# A temp path is a session's scratchpad or a clone: the whole path goes, not
# only its prefix, because the tail names this machine's session ids.
_TMP = re.compile(r"(?:(?<=file://)|(?<![\w.~/-]))(?:/private)?(?:/tmp|/var/folders)(?:/[^\s'\"`<>|;&()\[\]{}]*)?")
# Any macOS home, not only this operator's: a transcript can carry another
# account's path (a shared box, a copied log) and it is just as local.
_MAC_HOME = re.compile(r"(?:(?<=file://)|(?<![\w.~/-]))/Users/[^/\s'\"`<>|;&()]+")
# The same home `%2F`-encoded (a URL's query) or `\/`-escaped (a JSON writer's).
_MAC_HOME_ENCODED = re.compile(r"(?:%2[Ff]|\\/)Users(?:%2[Ff]|\\/)[^/\\%\s'\"`<>|;&()]+")
# Claude Code names a project's directory after its path with `/` and `.` as
# `-` (~/.claude/projects/-Users-alice-proj, and the temp dirs under it): the
# same home, in a form no `/Users/` rule sees. Any account's, as for _MAC_HOME.
_DASHED_HOME = re.compile(r"(?<![\w-])-Users-[A-Za-z0-9_]+")


def dashed(path: str) -> str:
    """A path in Claude Code's project-directory form: `/` and `.` as `-`."""
    return path.replace("/", "-").replace(".", "-")


# An address is a person: a `git -c user.email=…` head would otherwise carry one.
_EMAIL = re.compile(r"(?<![\w.%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")


def encoded(path: str) -> set[str]:
    """A path as written, `%2F`-encoded (a URL's query) and `\\/`-escaped (a JSON writer's)."""
    return {path, path.replace("/", "%2F"), path.replace("/", "\\/")}


#: macOS's other names for this machine (`scutil --get`): the Bonjour name, which
#: is also reachable as `<name>.local`, and the "Computer Name" people see
MAC_NAME_KEYS = ("LocalHostName", "ComputerName")


@functools.lru_cache(maxsize=1)
def machine_names() -> tuple[str, ...]:
    """Every name this machine answers to: `platform.node()`,
    `socket.gethostname()`, their first labels, and on macOS the
    LocalHostName (bare and with `.local`) and the ComputerName. `scutil` is
    a local configd read, never the network; a name it cannot give is left
    out (tools/jev/common.machine_names is the engine's twin)."""
    names = [platform.node(), socket.gethostname()]
    names += [h.split(".")[0] for h in names]
    if sys.platform == "darwin" and shutil.which("scutil"):
        for key in MAC_NAME_KEYS:
            try:
                res = subprocess.run(["scutil", "--get", key], capture_output=True, text=True, timeout=5,
                                     stdin=subprocess.DEVNULL, check=False)
            except (OSError, subprocess.SubprocessError) as exc:
                sys.stderr.write(f"fleet_context: scutil --get {key}: {exc}\n")
                continue
            value = res.stdout.strip() if res.returncode == 0 else ""
            if value and "\n" not in value:
                names += [value, f"{value}.local"] if key == "LocalHostName" else [value]
    return tuple(n for n in names if n)


def mask_credentials(s: str) -> str:
    """Every credential shape, masked. Runs BEFORE any clip as well as over the
    whole document: a token cut in half by a 140-character title clip is too
    short for its own pattern, and its first half would otherwise survive."""
    s = fleet_observe.redact(s)
    for rx, repl in EXTRA_REDACTIONS:
        s = rx.sub(repl, s)
    return s


class Scrubber:
    """Masks this machine out of everything the document carries.

    Host names of three characters or fewer are not masked as bare words — the
    same floor the scout adapter uses for its own withhold check, because a
    short name ("mac") is an ordinary word in code and titles. The fully
    qualified name always is.
    """

    def __init__(self, home: str | None = None, hosts: list[str] | None = None,
                 paths: list[str] | None = None):
        homes = [home] if home is not None else [os.environ.get("HOME") or "", str(Path.home())]
        if hosts is None:
            hosts = list(machine_names())
        if paths is None:
            paths = [os.environ.get("JEV_WORK_ROOT") or ""]
        # applied longest first and ignoring case: APFS paths are case-insensitive
        work = {e for p in paths if p and len(p.rstrip("/")) > 1 for e in encoded(p.rstrip("/"))}
        mine = {h.rstrip("/") for h in homes if h and len(h.rstrip("/")) > 1}
        home_forms = {e for h in mine for f in ((h, dashed(h)) if len(h) > 5 else (h,)) for e in encoded(f)}
        self._paths = [re.compile(re.escape(p), re.I) for p in sorted(work, key=len, reverse=True)]
        self._homes = [re.compile(re.escape(h), re.I) for h in sorted(home_forms, key=len, reverse=True)]
        names = sorted({h for h in hosts if h and len(h) > 3 and h.lower() != "localhost"},
                       key=len, reverse=True)
        self._hosts = [re.compile(r"(?<![\w.-])" + re.escape(h) + r"(?![\w-])", re.I) for h in names]

    def text(self, s: str, *, oneline: bool = False) -> str:
        if not s:
            return s
        s = _CTRL.sub("", s)
        if oneline:
            s = _BREAKS.sub(" ", s).strip()
        s = mask_credentials(s)
        for rx in self._paths:
            s = rx.sub("<work>", s)
        for rx in self._homes:
            s = rx.sub("~", s)
        s = _MAC_HOME.sub("~", s)
        s = _MAC_HOME_ENCODED.sub("~", s)
        s = _TMP.sub("<tmp>", s)
        s = _DASHED_HOME.sub("~", s)
        s = _EMAIL.sub("<email>", s)
        for rx in self._hosts:
            s = rx.sub("<host>", s)
        return s

    def obj(self, o):
        """`text` over every string of a JSON-shaped value, keys included, but
        a DOC_WORDS word, which is the document's own and is kept."""
        if isinstance(o, str):
            return o if o in DOC_WORDS else self.text(o)
        if isinstance(o, list):
            return [self.obj(x) for x in o]
        if isinstance(o, dict):
            return {(self.obj(k) if isinstance(k, str) else k): self.obj(v) for k, v in o.items()}
        return o


def clean_line(s, limit: int) -> str:
    """An untrusted one-line field (title, label, name): cut to the clip plus
    CLIP_SLACK, controls out, credentials masked, clipped."""
    s = _BREAKS.sub(" ", _CTRL.sub("", str(s or "")[: limit + CLIP_SLACK])).strip()
    return mask_credentials(s)[:limit]


def snippet_of(chunk) -> str:
    """At most SNIPPET_LINES lines and SNIPPET_CHARS characters of a code chunk
    (cut to SNIPPET_CHARS + CLIP_SLACK before it is masked)."""
    text = _CTRL.sub("", str(chunk or "")[: SNIPPET_CHARS + CLIP_SLACK]).replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(mask_credentials(text).split("\n")[:SNIPPET_LINES])[:SNIPPET_CHARS]


# --------------------------------------------------------------------------- #
# pure: the command head
# --------------------------------------------------------------------------- #
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\+?=")
_REDIR_ALONE = re.compile(r"^\d*(?:>>?|<|&>>?|>&|<&|>\|)$")
_REDIR_ATTACHED = re.compile(r"^\d*(?:>>?|<|&>>?|>&|<&)\S")
# Claude Code's telemetry clips a long tool input as `…[N chars]`; what follows
# the marker is the JSON's next field, not the command.
_CLIP_MARK = re.compile(r"\u2026\[\d+ chars\].*$")
_SKIP_HEADS = {"cd", "pushd", "popd", "export", "unset", "set"}
# A segment that is shell structure, not a command: the loop header, the closers.
_NOT_COMMANDS = {"for", "select", "case", "done", "fi", "esac", "}", ")", "function"}
# Words that lead a command without being it: `if grep -q`, `do wc -l`, `! test`.
_LEADERS = {"if", "elif", "while", "until", "then", "do", "else", "!", "time", "exec", "{", "("}
_SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
_SHELL_C = re.compile(r"^-[a-z]*c$")   # -c, -lc, -ec
_ENV_ARG_OPTS = {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}


def _segments(line: str) -> list[str]:
    """Split one shell line on && || | ; & outside quotes. `2>&1` and `&>` stay whole."""
    out, buf, quote, i = [], [], None, 0
    while i < len(line):
        ch = line[i]
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            elif ch == "\\" and quote == '"' and i + 1 < len(line):
                buf.append(line[i + 1])
                i += 1
        elif ch in "'\"":
            quote = ch
            buf.append(ch)
        elif ch == "\\" and i + 1 < len(line):
            buf.extend((ch, line[i + 1]))
            i += 1
        elif ch in ";|&":
            if ch == "&" and ((buf and buf[-1] in "<>") or line[i + 1:i + 2] == ">"):
                buf.append(ch)
            else:
                out.append("".join(buf))
                buf = []
                if line[i + 1:i + 2] == ch:   # && || ;;
                    i += 1
        else:
            buf.append(ch)
        i += 1
    out.append("".join(buf))
    return [s.strip() for s in out if s.strip()]


def _split(segment: str) -> list[str]:
    """shlex, closing a quote the first line (or the telemetry clip) left open."""
    for tail in ("", "'", '"', "\"'", "'\""):
        try:
            return shlex.split(segment + tail, posix=True)
        except ValueError:
            continue
    return segment.split()


def _words(segment: str) -> list[str]:
    """A segment's words: quotes gone, heredoc markers and redirections dropped."""
    words, skip = [], False
    for tok in _split(segment):
        if skip:
            skip = False
            continue
        if tok.startswith("#"):
            break
        if tok in ("<<", "<<-", "<<<") or _REDIR_ALONE.match(tok):
            skip = True   # the marker or the redirection's target is the next word
            continue
        if tok.startswith("<<") or _REDIR_ATTACHED.match(tok):
            continue
        if not words and " " not in tok:
            tok = tok.lstrip("({")   # `(which ruff`, `{ make`
        tok = tok.replace('"', "").replace("'", "").replace("`", "")
        if tok:
            words.append(tok)
    return words


def _command_words(words: list[str]) -> list[str]:
    """Drop what leads a command without being it: keywords, `env` and its options, VAR=value."""
    while True:
        if words and words[0] in _LEADERS:
            words = words[1:]
        elif words and words[0] == "env":
            words = words[1:]
            while words and words[0].startswith("-"):
                opt = words.pop(0)
                if opt in _ENV_ARG_OPTS and words:
                    words.pop(0)
        elif words and _ASSIGN.match(words[0]):
            words = words[1:]
        else:
            return words


def _basename(tok: str) -> str:
    if "/" not in tok:
        return tok
    return tok.rstrip("/").rsplit("/", 1)[-1] or tok


# The words a head may carry after the command word. An ALLOWLIST: a word that
# fits none of these ends the head, because the first words of a command are
# exactly where `curl -u user:pass`, `mysql -pSECRET`, `-H 'X-Api-Key: …'`
# and `redis-cli -a PASSWORD` put their secrets.
#: the command word itself (its basename): a name, or `[` / `[[` — never `^X=`
#: that a `tok=$(grep '^X=' …)` leaves behind once its assignment is dropped
_COMMAND_WORD = re.compile(r"^(?:\[\[?|[A-Za-z0-9_.+-]+)$")
#: a subcommand or a file's basename (`exec`, `status`, `x.py`): lower case, short
_HEAD_WORD = re.compile(r"^[a-z][a-z0-9._+-]{0,30}$")
#: a short flag cluster (`-rn`, `-j4`) or a long flag (`--short`), nothing attached
_HEAD_FLAG = re.compile(r"^(?:-[A-Za-z][A-Za-z0-9]{0,2}|--[a-z][a-z0-9-]{1,30})$")
#: options whose value is a credential, a header, a body or an environment: the
#: head keeps the option and stops, so its value — next word or attached — is never read
_VALUE_FLAGS = frozenset({
    "-u", "--user", "-U", "--proxy-user", "-p", "--pass", "--password", "-a", "--auth", "-H", "--header",
    "-d", "--data", "--data-raw", "--data-binary", "--data-urlencode", "-F", "--form", "-b", "--cookie",
    "-K", "--config", "-e", "--env", "--token", "--secret", "--body", "--key", "--api-key",
})
#: `python -m <module>`: the one value a head keeps, and only as a module name
_MODULE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,40}$")
#: commands whose every argument is data (`echo <secret> | docker login
#: --password-stdin`): the head is the command word alone
_DATA_COMMANDS = frozenset({"echo", "printf", "print", "yes"})


def _secretish(word: str) -> bool:
    """A long word thick with digits reads as an id or a password, not a subcommand."""
    return len(word) >= 12 and sum(c.isdigit() for c in word) >= 3


def _head_words(words: list[str]) -> list[str]:
    """The command word, then — at most HEAD_TOKENS words in all — subcommand
    words and flags, never an option's value: a positional after a flag ends
    the head (`grep -q`, not `grep -q <pattern>`), except python's `-m <module>`."""
    if not words:
        return []
    if _basename(words[0]) in _DATA_COMMANDS:
        return [_basename(words[0])]
    out, flagged = [_basename(words[0])], False
    for w in words[1:]:
        if len(out) >= HEAD_TOKENS:
            break
        if w.startswith("-") and w != "-":
            name = w.split("=", 1)[0] if w.startswith("--") else w
            short = name if name.startswith("--") else name[:2]
            if short in _VALUE_FLAGS:
                out.append(short)   # `-pSECRET`, `--password=x`, `-H <header>`: the option, never the value
                break
            if "=" in w or not _HEAD_FLAG.match(w):
                break
            out.append(w)
            flagged = True
            continue
        if flagged:
            if out[-1] == "-m" and _MODULE.match(w):
                out.append(w)
                continue
            break
        word = w if w == "-" else _basename(w)
        if word != "-" and (not _HEAD_WORD.match(word) or _secretish(word)):
            break
        out.append(word)
    return out


HEAD_LINES = 5   # a first line with no command (`set -e`, `cd x`) reads on, this far


def _unclip(line: str) -> str:
    """The line up to a telemetry clip marker, less the word the clip cut in half."""
    m = _CLIP_MARK.search(line)
    if not m:
        return line
    kept = line[:m.start()]
    return kept if not kept or kept[-1].isspace() else re.sub(r"\S+$", "", kept)


def _head(text: str, depth: int) -> tuple[str, bool]:
    """(head, found). found is False when only the fallback (a bare `cd`, say) stood."""
    fallback = ""
    for line in text.strip().splitlines()[:HEAD_LINES]:
        line = mask_credentials(_unclip(_CTRL.sub("", line)))
        head, found, feeds_shell = _line_head(line, depth)
        if found:
            return head, True
        fallback = fallback or head
        # A heredoc's body is data (python, a commit message), never the next
        # command — unless the heredoc feeds a shell (`bash <<'EOF'`), whose
        # body is exactly the commands.
        if "<<" in line and not feeds_shell:
            break
    if not fallback and _CLIP_MARK.search(text):
        fallback = "(clipped)"   # the command was past the telemetry's clip
    return fallback, False


def _line_head(first: str, depth: int) -> tuple[str, bool, bool]:
    """(head, found, feeds_shell) for one line."""
    fallback: list[str] = []
    feeds_shell = False
    for seg in _segments(first):
        words = _command_words(_words(seg))
        if not words or words[0] in _NOT_COMMANDS or not _COMMAND_WORD.match(_basename(words[0])):
            continue
        shell = _basename(words[0]) in _SHELLS
        if shell and len(words) == 1 and "<<" in seg:
            feeds_shell = True
            fallback = fallback or words
            continue
        # `bash -c '<script>'`: the script is the command, one level down (two at
        # most). Even its fallback (`cd theme`) says more than `bash -c`.
        if shell and len(words) > 2 and _SHELL_C.match(words[1]) and depth < 2:
            inner, found = _head(words[2], depth + 1)
            if inner:
                return inner, found, False
        if words[0] in _SKIP_HEADS:
            # `export PATH=…` stands as `export`: the value is not the command
            fallback = fallback or [words[0]] + [w for w in words[1:] if not _ASSIGN.match(w)]
            continue
        fallback = fallback or words
        return " ".join(_head_words(words))[:HEAD_CHARS], True, False
    return " ".join(_head_words(fallback))[:HEAD_CHARS], False, feeds_shell


def command_head(command) -> str:
    """What a failing Bash call was trying to run, without what it ran it on.

    The first line (reading on, five lines at most, only while a line holds no
    command, and never into a heredoc's body), cut at a telemetry clip marker;
    split on && ; | (and || &) outside quotes; the first segment that is a
    command — not a bare `cd`/`pushd`, an env assignment or `export`, a
    `set -…`, a loop header or a closer; leading keywords (`if`, `do`, `!`…),
    `env` with its options and VAR=value words dropped; a `bash -c '<script>'`
    read through to its script; heredoc markers, redirections and quotes
    dropped. Of that segment, at most three words by ALLOWLIST (_head_words):
    the command word (a path cut to its basename), then lower-case subcommand
    words and bare flags. An option that takes a credential, header or body
    (`-u`, `-p`, `-H`, `--password`, `-d`…) is kept and ends the head, so its
    value never appears, attached (`-pSECRET`) or not; any other word — a
    positional after a flag, a word with `:`, `@`, `=` or upper case, one
    over 31 characters or thick with digits — ends it too. Clipped to 60
    characters. Absent any such segment, the first segment's words stand (a
    failing `cd` is still a `cd`).
    """
    return _head(str(command or "")[:HEAD_SCAN_CHARS], 0)[0]


_COMMAND_FIELD = re.compile(r'"(?:command|full_command)"\s*:\s*"((?:[^"\\]|\\.)*)')


def command_of(raw) -> str:
    """The `command` of a Bash tool input: a dict, a JSON string, or one clipped mid-string."""
    if isinstance(raw, dict):
        return str(raw.get("command") or raw.get("full_command") or "")
    text = str(raw or "")
    try:
        doc = json.loads(text)
    except ValueError:
        doc = None
    if isinstance(doc, dict):
        return str(doc.get("command") or doc.get("full_command") or "")
    m = _COMMAND_FIELD.search(text)
    if not m:
        return ""
    body = m.group(1)
    for candidate in (body, body.rstrip("\\")):
        try:
            return json.loads(f'"{candidate}"')
        except ValueError:
            continue
    return body.replace("\\n", "\n").replace('\\"', '"')


# --------------------------------------------------------------------------- #
# i/o: the read routes
# --------------------------------------------------------------------------- #
#: (method, path) a plane may be asked. Anything else is refused before a socket
#: opens: the same planes take writes (Qdrant upserts, an Elasticsearch _bulk,
#: an Ollama pull), and a read-only tool must not be one typo away from them.
READ_ROUTES: dict[str, tuple[tuple[str, re.Pattern], ...]] = {
    "qdrant": (("GET", re.compile(r"/collections")),
               ("GET", re.compile(r"/collections/[\w.-]+")),
               ("POST", re.compile(r"/collections/[\w.-]+/points/(?:search|count)"))),
    "ollama": (("POST", re.compile(r"/api/embed")),),
    "elasticsearch": (("POST", re.compile(r"/logs-[\w.*-]+/_search")),),
}
PLANE_LABEL = {"qdrant": "Qdrant", "ollama": "the embedder (Ollama)", "elasticsearch": "Elasticsearch"}


REMEDY_URL = "set it to scheme://host:port in _data/fleet.yml `observability:` (or its env override)"


def plane_origin(plane: str, base: str) -> tuple[str, str, int | None, str]:
    """(scheme, host, port, origin) of a plane's configured URL, which must be
    scheme://host[:port] and nothing more. A path, query, fragment or userinfo
    is refused, not appended to: `<base>/_delete_by_query?…&_=` + a read path
    would otherwise send a read body to a write endpoint."""
    label = PLANE_LABEL.get(plane, plane)
    raw = (base or "").strip()
    try:
        parts = urllib.parse.urlsplit(raw)
        port = parts.port
    except ValueError:
        raise Unavailable(f"{label}'s URL is not a URL", REMEDY_URL) from None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        shown = clean_line(raw.rsplit("@", 1)[-1], 80) or "none"
        raise Unavailable(f"{label} has no http(s) URL in the contract ({shown})", REMEDY_URL)
    if parts.path not in ("", "/") or parts.query or parts.fragment or "@" in parts.netloc:
        raise Unavailable(f"{label}'s URL carries a path, query, fragment or credentials; only "
                          "scheme://host:port is accepted", REMEDY_URL)
    host = parts.hostname
    origin = f"{parts.scheme}://{f'[{host}]' if ':' in host else host}" + (f":{port}" if port else "")
    return parts.scheme, host, port, origin


def _exchange(scheme: str, host: str, port: int | None, method: str, path: str, data: bytes | None,
              end: float, box: dict) -> None:
    """One HTTP exchange, on a worker thread. http.client, not urllib: no
    proxy is ever consulted and no redirect followed. Each recv is bounded by
    what is left of `end`; the caller's join bounds the whole of it (the
    connect, the name lookup and a header phase that trickles)."""
    conn = None
    try:
        cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
        conn = cls(host, port, timeout=max(0.05, end - time.monotonic()))
        conn.connect()
        sock = conn.sock
        box["sock"] = sock
        conn.request(method, path, body=data,
                     headers={"Content-Type": "application/json", "Accept": "application/json"})
        sock.settimeout(max(0.05, end - time.monotonic()))
        resp = conn.getresponse()
        box["status"] = resp.status
        if not 200 <= resp.status < 300:
            return
        chunks, size = [], 0
        while not resp.isclosed():   # the read that completes the body closes it
            left = end - time.monotonic()
            if left <= 0:
                raise TimeoutError("the per-request budget ran out mid-body")
            sock.settimeout(left)
            chunk = resp.read1(65536)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_BODY_BYTES:
                box["too_big"] = True
                return
            chunks.append(chunk)
        box["body"] = b"".join(chunks)
    except Exception as exc:   # handed back to the caller, which names it in the section
        box["exc"] = exc
    finally:
        if conn is not None:
            conn.close()


def http_json(plane: str, base: str, method: str, path: str, payload=None, *,
              deadline: Deadline, remedy: str = REMEDY_PLANES):
    """One read request to one plane, bounded in WALL-CLOCK time by the
    per-request cap and the overall deadline, whichever ends first: a plane
    that trickles a byte at a time is cut off there, not after every byte
    has made its own timeout. Raises Unavailable (RouteRefused for a route
    that is not a read, before any socket opens)."""
    if not any(m == method and rx.fullmatch(path) for m, rx in READ_ROUTES.get(plane, ())):
        raise RouteRefused(f"{method} {path} is not a read route of {plane}")
    label = PLANE_LABEL.get(plane, plane)
    scheme, host, port, origin = plane_origin(plane, base)
    budget = deadline.timeout()
    end = time.monotonic() + budget
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    box: dict = {}
    worker = threading.Thread(target=_exchange, args=(scheme, host, port, method, path, data, end, box),
                              name=f"fleet-context-{plane}", daemon=True)
    worker.start()
    worker.join(max(0.0, end - time.monotonic()) + 0.05)
    if worker.is_alive():
        sock = box.get("sock")
        if sock is not None:   # wake the worker's recv; it closes its own connection
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)
        raise Unavailable(f"{label} at {origin} did not answer within {budget:.1f} s", remedy)
    exc = box.get("exc")
    if exc is not None:
        if isinstance(exc, TimeoutError):
            why = f"did not answer within {budget:.1f} s"
        elif isinstance(exc, ConnectionRefusedError):
            why = "refused the connection"
        else:
            why = f"is not reachable ({clean_line(f'{type(exc).__name__}: {exc}', 120)})"
        raise Unavailable(f"{label} at {origin} {why}", remedy)
    status = box.get("status")
    if status is not None and not 200 <= status < 300:
        raise Unavailable(f"{label} at {origin} answered HTTP {status} to {method} {path}", remedy)
    if box.get("too_big"):
        raise Unavailable(f"{label} at {origin} answered more than {MAX_BODY_BYTES} bytes", remedy)
    try:
        return json.loads((box.get("body") or b"").decode("utf-8"))
    except ValueError:
        raise Unavailable(f"{label} at {origin} answered something that is not JSON", remedy) from None


# --------------------------------------------------------------------------- #
# i/o: the lake, read-only
# --------------------------------------------------------------------------- #
def open_ro(db: Path, timeout: float = REQUEST_TIMEOUT_S) -> sqlite3.Connection:
    """The lake as a reader: `mode=ro` at the VFS, `query_only` above it.

    Never fleet_lake.connect: that one creates the directory, runs the schema
    DDL and stamps `meta`, which is a write on every open.
    """
    uri = f"file:{urllib.parse.quote(str(db))}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _need(tables: set[str], *names: str, remedy: str = REMEDY_LAKE) -> None:
    missing = [n for n in names if n not in tables]
    if missing:
        raise Unavailable(f"the lake has no {', '.join(missing)} table", remedy)


def _scalar(conn: sqlite3.Connection, sql: str, params=()):
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


def sync_as_of(conn: sqlite3.Connection, tables: set[str]) -> str | None:
    if "syncs" not in tables:
        return None
    return iso_z(_scalar(conn, "SELECT MAX(finished_at) FROM syncs WHERE finished_at IS NOT NULL"))


def github_freshness(conn: sqlite3.Connection, tables: set[str], nwo: str, now: dt.datetime,
                     what: str = "the lake's GitHub sync") -> tuple[str | None, bool, str]:
    """(as_of, stale, note) for THIS repo's GitHub data in the lake.

    `lake sync` stamps `repos.synced_at` for each repo it reaches (a repo it
    skips keeps its old stamp) and writes one `syncs` row when the whole pass
    finishes. The repo's stamp is the older of the two: a fresh `lake sync
    --repo OTHER` must not vouch for this repo's twelve-day-old rows, and an
    interrupted pass must not vouch for a repo it stamped before it died. A
    repo with no `repos` row has never been synced, which is stale, not empty.
    """
    remedy = f"run `tools/dash lake sync --repo {nwo}`"
    global_as_of = sync_as_of(conn, tables)
    if "repos" not in tables:   # an older lake: the lake-wide stamp is all there is
        stale, note = freshness(global_as_of, now, what, REMEDY_LAKE)
        return global_as_of, stale, note
    row = conn.execute("SELECT synced_at FROM repos WHERE nwo = ? COLLATE NOCASE", (nwo,)).fetchone()
    own = iso_z(row[0]) if row else None
    if own is None:
        return None, True, f"the lake has never synced {nwo} — {remedy}"
    stamps = [t for t in (own, global_as_of) if t]
    as_of = min(stamps, key=fleet_lake.parse_iso) if global_as_of else None
    stale, note = freshness(as_of, now, what, remedy)
    return as_of, stale, note


def sessions_as_of(conn: sqlite3.Connection, tables: set[str]) -> str | None:
    """Lake-wide on purpose: a default `lake sessions` scans every transcript
    on the machine and re-stamps only the changed ones, so the newest stamp is
    the last import, and a repo with no new session since is fresh, not stale.
    A `--repo` or `--limit` import advances the stamp too while reading only
    part of the machine, so it can vouch for transcripts it never read; a
    per-repo stamp needs an import ledger in fleet_lake."""
    if "sessions" not in tables:
        return None
    return iso_z(_scalar(conn, "SELECT MAX(synced_at) FROM sessions"))


def freshness(as_of: str | None, now: dt.datetime, what: str, remedy: str) -> tuple[bool, str]:
    """(stale, note). Never synced is stale too: an empty answer from it means nothing."""
    age = age_hours(as_of, now)
    if age is None:
        return True, f"{what} has never been refreshed — {remedy}"
    if age > STALE_AFTER_H:
        return True, f"{what} last refreshed {age:.0f} h ago (over {STALE_AFTER_H:g} h) — {remedy}"
    return False, ""


def _labels(raw) -> list[str]:
    try:
        items = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except ValueError:
        items = []
    out = []
    for item in items if isinstance(items, list) else []:
        name = item.get("name") if isinstance(item, dict) else item
        if name:
            out.append(clean_line(name, LABEL_CHARS))
    return out


def lake_issues(conn, tables, nwo: str, since: str, now: dt.datetime, scout_label: str,
                deadline: Deadline | None = None) -> dict:
    _need(tables, "issues")
    as_of, stale, note = github_freshness(conn, tables, nwo, now)
    where = "nwo = ? COLLATE NOCASE AND state = 'closed' AND closed_at IS NOT NULL AND closed_at >= ?"
    total = int(_scalar(conn, f"SELECT COUNT(*) FROM issues WHERE {where}", (nwo, since)) or 0)
    rows = []
    for r in conn.execute(f"SELECT number, is_pr, substr(title, 1, {LAKE_TEXT_CHARS}) AS title, labels, "
                          f"closed_at FROM issues WHERE {where} ORDER BY closed_at DESC, number DESC LIMIT ?",
                          (nwo, since, CAP_ISSUES)):
        _within(deadline, "the lake's issues")
        labels = _labels(r["labels"])
        rows.append({"number": r["number"], "kind": "pr" if r["is_pr"] else "issue",
                     "title": clean_line(r["title"], TITLE_CHARS), "labels": labels[:CAP_LABELS],
                     "closed_at": iso_z(r["closed_at"]), "scout": scout_label in labels})
    scope = f"closed since {since[:10]}, newest first; the open ones are in the brief"
    return _done("lake_issues", rows, as_of, now, stale, f"{note}; {scope}" if note else scope,
                 max(0, total - len(rows)))


def tracked_branch(conn, tables, nwo: str, registry: dict) -> str:
    """The registry's declared branch, else the lake's default_branch, else main."""
    row = registry.get(nwo.lower()) or {}
    declared = str(row.get("branch") or "").strip()
    if declared:
        return declared
    if "repos" in tables:
        found = _scalar(conn, "SELECT default_branch FROM repos WHERE nwo = ? COLLATE NOCASE", (nwo,))
        if found:
            return str(found)
    return "main"


def lake_ci(conn, tables, nwo: str, since: str, now: dt.datetime, branch: str,
            deadline: Deadline | None = None) -> dict:
    _need(tables, "runs")
    as_of, stale, note = github_freshness(conn, tables, nwo, now)
    groups: dict[str, list] = {}
    # Fail open, as fleet_triage does: a run missing head_branch or event is kept.
    for r in conn.execute(
            f"SELECT id, substr(workflow_path, 1, {LAKE_TEXT_CHARS}) AS workflow_path, "
            f"substr(workflow_name, 1, {LAKE_TEXT_CHARS}) AS workflow_name, event, status, "
            "substr(conclusion, 1, 40) AS conclusion, head_branch, created_at "
            "FROM runs WHERE nwo = ? COLLATE NOCASE AND created_at >= ? "
            "AND (head_branch IS NULL OR head_branch = ?) "
            f"AND (event IS NULL OR event NOT IN ({','.join('?' * len(PR_EVENTS))})) "
            "ORDER BY created_at DESC, id DESC LIMIT 5000", (nwo, since, branch, *PR_EVENTS)):
        _within(deadline, "the lake's runs")
        groups.setdefault(r["workflow_path"] or r["workflow_name"] or "?", []).append(r)
    rows, failed_ids = [], {}
    for path, runs in groups.items():
        _within(deadline, "the lake's runs")
        verdicts = [r for r in runs if r["conclusion"] and r["conclusion"] not in NO_VERDICT]
        completed = [r for r in runs if r["conclusion"]]
        last = verdicts[0] if verdicts else (completed[0] if completed else runs[0])
        streak = 0
        for r in verdicts:
            if r["conclusion"] not in ERROR_CONCLUSIONS:
                break
            streak += 1
        failed = [r["id"] for r in runs if r["conclusion"] in ERROR_CONCLUSIONS]
        failed_ids[path] = failed[:FAILED_RUNS_SCANNED]
        rows.append({"workflow": clean_line(runs[0]["workflow_name"] or path, NAME_CHARS),
                     "path": clean_line(path, 200), "runs": len(runs), "failures": len(failed),
                     "last_conclusion": last["conclusion"], "last_at": iso_z(last["created_at"]),
                     "fail_streak": streak, "failing_steps": []})
    rows.sort(key=lambda w: (0 if w["fail_streak"] else 1 if w["failures"] else 2,
                             -w["fail_streak"], -w["failures"], w["workflow"].lower()))
    kept = rows[:CAP_WORKFLOWS]
    if "jobs" in tables:
        _failing_steps(conn, tables, kept, failed_ids, deadline)
    scope = f"runs on {clean_line(branch, NAME_CHARS)}, pull-request runs excluded"
    return _done("lake_ci", kept, as_of, now, stale, f"{note}; {scope}" if note else scope,
                 len(rows) - len(kept))


def _failing_steps(conn, tables, kept: list[dict], failed_ids: dict[str, list[int]],
                   deadline: Deadline | None = None) -> None:
    """`job / step` for each kept workflow's failed runs, newest first — where the lake has them."""
    wanted = [i for w in kept for i in failed_ids.get(w["path"], [])]
    if not wanted:
        return
    marks = ",".join("?" * len(wanted))
    errs = ",".join("?" * len(ERROR_CONCLUSIONS))
    by_run: dict[int, list[str]] = {}
    if "steps" in tables:
        sql = (f"SELECT j.run_id, substr(j.name, 1, {LAKE_TEXT_CHARS}) AS job, j.conclusion AS jc, "
               f"substr(s.name, 1, {LAKE_TEXT_CHARS}) AS step, s.number "
               f"FROM jobs j LEFT JOIN steps s ON s.job_id = j.id AND s.conclusion IN ({errs}) "
               f"WHERE j.run_id IN ({marks}) ORDER BY j.run_id, j.id, s.number")
        params = (*ERROR_CONCLUSIONS, *wanted)
    else:
        sql = (f"SELECT run_id, substr(name, 1, {LAKE_TEXT_CHARS}) AS job, conclusion AS jc, NULL AS step, "
               f"NULL AS number FROM jobs "
               f"WHERE run_id IN ({marks}) ORDER BY run_id, id")
        params = tuple(wanted)
    for r in conn.execute(sql, params):
        _within(deadline, "the lake's jobs")
        job = clean_line(r["job"], NAME_CHARS)
        if r["step"]:
            by_run.setdefault(r["run_id"], []).append(f"{job} / {clean_line(r['step'], NAME_CHARS)}")
        elif r["jc"] in ERROR_CONCLUSIONS:
            by_run.setdefault(r["run_id"], []).append(job)
    for w in kept:
        seen: list[str] = []
        for run_id in failed_ids.get(w["path"], []):
            for label in by_run.get(run_id, []):
                if label not in seen:
                    seen.append(label)
        w["failing_steps"] = seen[:CAP_FAILING_STEPS]


def lake_agents(conn, tables, nwo: str, name: str, since: str, now: dt.datetime,
                deadline: Deadline | None = None, home: str | None = None) -> dict:
    """CI agent runs, local sessions and their failing commands. A session
    whose cwd IS the home directory is nobody's repo: ai_activity.repo_for
    falls back to the cwd's basename, which for $HOME is the user name, and
    the hub's checkout is named after the user too."""
    if "agent_runs" not in tables and "sessions" not in tables:
        _need(tables, "agent_runs", "sessions")
    rows, notes, stamps, stale_any, truncated = [], [], [], False, 0
    if "agent_runs" in tables:
        as_of, stale, note = github_freshness(conn, tables, nwo, now, "CI agent runs (the lake's GitHub sync)")
        if "runs" in tables:
            sql = ("SELECT substr(a.model, 1, 200) AS model, a.num_turns, a.cost_usd, a.permission_denials, "
                   "a.is_error, "
                   "COALESCE(a.started_at, r.created_at) AS at FROM agent_runs a "
                   "LEFT JOIN runs r ON r.id = a.run_id WHERE a.nwo = ? COLLATE NOCASE "
                   "AND COALESCE(a.started_at, r.created_at) >= ?")
        else:
            sql = ("SELECT substr(model, 1, 200) AS model, num_turns, cost_usd, permission_denials, is_error, "
                   "started_at AS at "
                   "FROM agent_runs WHERE nwo = ? COLLATE NOCASE AND started_at >= ?")
        agg = {"kind": "ci_agent_runs", "count": 0, "errors": 0, "permission_denials": 0, "turns": 0,
               "cost_usd": 0.0, "models": {}, "last_at": None, "as_of": as_of}
        last = None
        for r in conn.execute(sql, (nwo, since)):
            _within(deadline, "the lake's agent runs")
            agg["count"] += 1
            agg["errors"] += 1 if r["is_error"] else 0
            agg["permission_denials"] += int(r["permission_denials"] or 0)
            agg["turns"] += int(r["num_turns"] or 0)
            agg["cost_usd"] += float(r["cost_usd"] or 0)
            model = clean_line(r["model"] or "unknown", NAME_CHARS)
            agg["models"][model] = agg["models"].get(model, 0) + 1
            at = fleet_lake.parse_iso(r["at"])
            if at and (last is None or at > last):
                last = at
        if agg["count"]:
            agg["cost_usd"] = round(agg["cost_usd"], 4)
            agg["last_at"] = iso_z(last)
            agg["models"], folded = top_models(agg["models"])
            truncated += folded
            rows.append(agg)
        stale_any |= stale
        notes += [note] if note else []
        stamps.append(as_of)
    if "sessions" in tables:
        as_of = sessions_as_of(conn, tables)
        r = conn.execute("SELECT COUNT(*) AS n, SUM(tool_calls) AS calls, SUM(tool_errors) AS errs, "
                         "MAX(COALESCE(ended_at, started_at)) AS last FROM sessions "
                         "WHERE repo = ? COLLATE NOCASE AND started_at >= ? "
                         "AND (cwd IS NULL OR cwd NOT IN (?, ?))", (name, since, *_home_cwds(home))).fetchone()
        if r and r["n"]:
            rows.append({"kind": "local_sessions", "count": int(r["n"]), "tool_calls": int(r["calls"] or 0),
                         "tool_errors": int(r["errs"] or 0), "last_at": iso_z(r["last"]), "as_of": as_of})
        if "session_tools" in tables:
            commands, dropped = failing_commands(conn, name, since, deadline, home)
            rows += commands
            truncated += dropped
        stale, note = freshness(as_of, now, "local sessions", REMEDY_SESSIONS)
        stale_any |= stale
        notes += [note] if note else []
        stamps.append(as_of)
    else:
        notes.append(f"the lake has no sessions table — {REMEDY_SESSIONS}")
    if "agent_runs" not in tables:
        notes.append(f"the lake has no agent_runs table — {REMEDY_LAKE}")
    if any(r["kind"] == "ci_agent_runs" for r in rows):
        notes.append("cost_usd is API-equivalent (estimate)")
    # The OLDER stamp speaks for the section: a fresh half must not vouch for a
    # stale one. Each aggregate row carries its own as_of beside it.
    known = [s for s in stamps if s]
    as_of = min(known, key=fleet_lake.parse_iso) if known and len(known) == len(stamps) else None
    return _done("lake_agents", rows, as_of, now, stale_any, "; ".join(notes), truncated)


def top_models(models: dict[str, int]) -> tuple[dict[str, int], int]:
    """At most CAP_MODELS keys, most used first: past that, the top
    CAP_MODELS - 1 and an "(other)" count. Returns (models, how many folded)."""
    ranked = sorted(models.items(), key=lambda kv: (-kv[1], kv[0]))
    if len(ranked) <= CAP_MODELS:
        return dict(ranked), 0
    kept, rest = ranked[: CAP_MODELS - 1], ranked[CAP_MODELS - 1:]
    return {**dict(kept), "(other)": sum(n for _m, n in rest)}, len(rest)


def _home_cwds(home: str | None) -> tuple[str, str]:
    h = (home if home is not None else (os.environ.get("HOME") or str(Path.home()))).rstrip("/") or "/"
    return h, h + "/"


def failing_commands(conn, name: str, since: str, deadline: Deadline | None = None,
                     home: str | None = None) -> tuple[list[dict], int]:
    """Failed Bash calls in this repo's local sessions, by command head. Never the command itself."""
    heads: dict[str, dict] = {}
    for r in conn.execute(
            f"SELECT substr(t.input, 1, {HEAD_SCAN_CHARS}) AS input, COALESCE(t.started_at, s.started_at) AS at "
            "FROM session_tools t "
            "JOIN sessions s ON s.key = t.key WHERE s.repo = ? COLLATE NOCASE AND t.is_error = 1 "
            "AND t.name = 'Bash' AND COALESCE(t.started_at, s.started_at) >= ? "
            "AND (s.cwd IS NULL OR s.cwd NOT IN (?, ?)) "
            "ORDER BY at DESC LIMIT ?", (name, since, *_home_cwds(home), COMMAND_SAMPLE)):
        _within(deadline, "the lake's session tools")
        head = command_head(command_of(r["input"])) or "(unparsed)"
        row = heads.setdefault(head, {"kind": "failing_command", "head": head, "count": 0, "last_at": None})
        row["count"] += 1
        row["last_at"] = row["last_at"] or iso_z(r["at"])
    ranked = sorted(heads.values(), key=lambda h: (-h["count"], h["head"]))
    return ranked[:CAP_COMMANDS], max(0, len(ranked) - CAP_COMMANDS)


def _done(key: str, rows: list, as_of, now, stale: bool, note: str, truncated: int) -> dict:
    status = "stale" if stale else ("ok" if rows else "empty")
    return section(key, status, rows, as_of=as_of, now=now, note=note, truncated=truncated)


# --------------------------------------------------------------------------- #
# i/o: the code index (Qdrant + Ollama)
# --------------------------------------------------------------------------- #
def resolve_collection(qdrant: str, deadline: Deadline) -> str:
    """fleet_index's choice (env override, then `ws-`, then the fullest), asked under the deadline."""
    override = fleet_index.collection_env()
    listed = http_json("qdrant", qdrant, "GET", "/collections", deadline=deadline)
    names = [c.get("name") for c in ((listed or {}).get("result") or {}).get("collections") or []
             if isinstance(c, dict) and c.get("name")]
    if not names and not override:
        raise Unavailable(f"Qdrant at {qdrant} holds no collection",
                          "the Kilo workspace scan has not written one (kilo.jsonc `indexing`)")
    counts: dict[str, int] = {}
    pool = [n for n in names if n.startswith(fleet_index.WORKSPACE_PREFIX)] or names
    if not override and len(pool) > 1:
        for n in pool[:5]:
            if COLLECTION_RX.match(n):
                detail = http_json("qdrant", qdrant, "GET", f"/collections/{n}", deadline=deadline) or {}
                counts[n] = int((detail.get("result") or {}).get("points_count") or 0)
    name = fleet_index.pick_collection(names, counts, override)
    if not name or not COLLECTION_RX.match(name):
        raise Unavailable(f"the collection name {name!r} is not a plain name",
                          f"fix {fleet_index.COLLECTION_ENV}")
    return name


def embed_all(embedder: str, model: str, queries: list[str], deadline: Deadline) -> list[list[float]]:
    doc = http_json("ollama", embedder, "POST", "/api/embed", {"model": model, "input": list(queries)},
                    deadline=deadline, remedy=REMEDY_OLLAMA) or {}
    vectors = doc.get("embeddings") or ([doc["embedding"]] if doc.get("embedding") else [])
    if len(vectors) != len(queries) or not all(isinstance(v, list) and v for v in vectors):
        raise Unavailable(f"the embedder at {embedder} returned {len(vectors)} embedding(s) for "
                          f"{len(queries)} quer{'y' if len(queries) == 1 else 'ies'}",
                          f"check `ollama pull {model}`")
    return vectors


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


_FILE_HASH = re.compile(r"[0-9a-f]{64}")


def file_freshness(path: str, file_hash, root: Path, deadline: Deadline | None = None) -> str | None:
    """Whether the tree at `root` still holds the file a hit was cut from:
    'fresh' (its sha256 is the index's `fileHash`), 'changed', 'missing', or
    None when it cannot be told (no hash, an unsafe path, a link anywhere
    below `root`, a file over FRESH_MAX_BYTES, the deadline spent). Every
    directory on the way is lstat-ed and the file is opened O_NOFOLLOW:
    the agent's clone (--target-dir) is the target's own content, so no link
    in it is followed out of it."""
    if not isinstance(file_hash, str) or not _FILE_HASH.fullmatch(file_hash):
        return None
    parts = Path(path).parts
    if not parts or Path(path).is_absolute() or ".." in parts or (deadline is not None and deadline.expired()):
        return None
    node = Path(root)
    for i, part in enumerate(parts):
        node = node / part
        try:
            st = os.lstat(node)
        except FileNotFoundError:
            return "missing"
        except OSError:
            return None
        if stat.S_ISLNK(st.st_mode):
            return None
        if i < len(parts) - 1 and not stat.S_ISDIR(st.st_mode):
            return "missing"   # a file where the index saw a directory: the hit's file is gone
    if not stat.S_ISREG(st.st_mode) or st.st_size > FRESH_MAX_BYTES:
        return None
    try:
        with os.fdopen(os.open(node, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)), "rb") as fh:
            data = fh.read(FRESH_MAX_BYTES + 1)
    except OSError:
        return None
    return "fresh" if hashlib.sha256(data).hexdigest() == file_hash else "changed"


def checked_out(root: Path, checkout: str) -> bool:
    """Whether the hub checkout at `root` holds projects/<checkout>: a real
    directory with an entry in it (a submodule a fresh clone or a worktree
    never initialised is an empty one)."""
    node = Path(root) / "projects" / checkout
    try:
        if not stat.S_ISDIR(os.lstat(node).st_mode):
            return False
        with os.scandir(node) as entries:
            return next(entries, None) is not None
    except OSError:
        return False


def target_dir_problem(path) -> str | None:
    """Why `path` cannot be --target-dir — the agent's clone of the target,
    whose files the target's code-index hits are checked against — or None:
    absolute, no `..`, no control character, and no symlink anywhere in it
    (it is its own realpath), naming a real directory. Only read."""
    s = str(path or "")
    if not s or _has_control(s):
        return "must be a non-empty path with no control character"
    if not os.path.isabs(s) or ".." in Path(s).parts:
        return f"must be an absolute path with no '..', got {s!r}"
    try:
        st = os.lstat(s)
    except OSError:
        return f"{s!r} does not exist"
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        return f"{s!r} is not a real directory"
    if os.path.realpath(s) != os.path.normpath(s):
        return f"{s!r} has a symlink in its path; pass its realpath"
    return None


def index_code(queries: list[str], name: str, is_hub: bool, deadline: Deadline, now: dt.datetime,
               cfg: dict | None = None, *, checkout: str | None = None, root: Path | str | None = None,
               target_dir: Path | str | None = None) -> dict:
    """Up to CAP_HITS distinct hits per query (a path and line range once,
    across queries), never from the hub's copies of the registry
    (INDEX_EXCLUDED). `checkout` is the target's directory under projects/
    (the registry's submodule_path; default `name`). A hit whose code would
    be shown is checked against the files the agent reads: the target's own
    hits against `target_dir` (its clone, --target-dir) when given, the
    rest — and the target's without one — against the hub checkout at
    `root` (default the hub's). From a file that changed since the index
    scanned it, or that is not there, its code is withheld and the section
    is 'stale'. Without `target_dir`, a target whose projects/<checkout> is
    not checked out at `root` (a worktree, a fresh clone) cannot be checked:
    its hits' code is withheld, the note says so with the remedy
    (REMEDY_CHECKOUT), and that alone never makes the section stale."""
    if not queries:
        return section("index_code", "empty", now=now,
                       note="no --query given: the code index is asked only what the step names")
    cfg = cfg or fleet_index.analysis_config()
    qdrant, embedder = (cfg.get("qdrant") or "").rstrip("/"), (cfg.get("embedder") or "").rstrip("/")
    model, floor = cfg.get("model") or "nomic-embed-text", float(cfg.get("min_score") or 0)
    checkout = checkout or name
    root = Path(root) if root is not None else REPO_ROOT
    clone = Path(target_dir) if target_dir else None
    own = {name.lower(), checkout.lower()}
    here = is_hub or clone is not None or checked_out(root, checkout)
    collection = resolve_collection(qdrant, deadline)
    vectors = embed_all(embedder, model, queries, deadline)
    # Code only from what is certainly public or certainly the agent's own: the
    # hub and the target. A sibling may be private — the registry cannot say.
    allowed = {fleet_index.HUB, name.lower(), checkout.lower()}
    rows, truncated, seen = [], 0, set()
    unchecked = 0
    # [changed, missing] hits per tree they were checked against: the agent's clone
    # (the target's, with --target-dir) and the hub checkout at `root` (the rest)
    behind = {"clone": [0, 0], "checkout": [0, 0]}
    for query, vector in zip(queries, vectors):
        found = http_json("qdrant", qdrant, "POST", f"/collections/{collection}/points/search",
                          {"vector": vector, "limit": SEARCH_LIMIT, "score_threshold": floor,
                           "filter": {"must_not": [{"key": "filePath", "match": {"any": list(INDEX_EXCLUDED)}}]},
                           "with_payload": ["filePath", "startLine", "endLine", "codeChunk", "fileHash"],
                           "with_vector": False}, deadline=deadline) or {}
        hits = []
        for hit in found.get("result") or []:
            payload = hit.get("payload") or {}
            score = float(hit.get("score") or 0)
            if score >= floor and payload.get("filePath") and str(payload["filePath"]) not in INDEX_EXCLUDED:
                hits.append((score, payload))
        hits.sort(key=lambda h: -h[0])
        unique = []
        for score, payload in hits:   # the index can hold one range twice; a range one query showed is shown once
            where = (str(payload.get("filePath")), _int(payload.get("startLine")), _int(payload.get("endLine")))
            if where not in seen:
                seen.add(where)
                unique.append((score, payload))
        truncated += max(0, len(unique) - CAP_HITS)
        for score, payload in unique[:CAP_HITS]:
            path = str(payload.get("filePath"))
            project = fleet_index.project_of(path)
            row = {"query": query, "project": project, "path": clean_line(path, 300),
                   "start_line": _int(payload.get("startLine")), "end_line": _int(payload.get("endLine")),
                   "score": round(score, 3), "snippet": None}
            if project.lower() not in allowed:
                row["withheld"] = "sibling repo, visibility unknown"
            else:
                file_hash = payload.get("fileHash")
                target = project == fleet_index.HUB if is_hub else project.lower() in own
                tree = "clone" if target and clone is not None else "checkout"
                if tree == "clone":   # the clone's root is the repository's: no projects/<dir>/
                    fresh = file_freshness(path if is_hub else "/".join(Path(path).parts[2:]), file_hash, clone,
                                           deadline)
                elif target and not here:
                    fresh = "unchecked" if isinstance(file_hash, str) and _FILE_HASH.fullmatch(file_hash) else None
                else:
                    fresh = file_freshness(path, file_hash, root, deadline)
                if fresh == "changed":
                    behind[tree][0] += 1
                    row.update(stale=True, withheld="the file changed since the index scanned it; read it in the "
                                                    "repository")
                elif fresh == "missing":
                    behind[tree][1] += 1
                    where = "the agent's clone" if tree == "clone" else "this checkout"
                    row.update(stale=True, withheld=f"the file is not in {where} (deleted since the index scanned it)")
                elif fresh == "unchecked":
                    unchecked += 1
                    row["withheld"] = (f"projects/{checkout} is not checked out here, so the hit cannot be checked; "
                                       "read it in the repository")
                else:
                    row["snippet"] = snippet_of(payload.get("codeChunk"))
            rows.append(row)
    note = f"collection {collection}; floor {floor:g}"
    note += _chunk_note(qdrant, collection, name, is_hub, deadline, checkout)
    if not rows:
        note = f"no hit at or above min_score {floor:g}; {note}"
    if clone is not None and not any(behind["clone"]):
        note += "; the target's hits checked against its clone (--target-dir)"
    if unchecked:
        note = (f"projects/{checkout} is not checked out here: {unchecked} hit(s) from {name} not checked (code "
                f"withheld) — {REMEDY_CHECKOUT.format(dir=checkout)}; {note}")
    # each tree with its own counts and remedy: the target's hits were checked against the clone, the rest
    # (the hub's, with --target-dir) against the hub checkout. The clauses lead the note, short enough that both
    # fit the engine's 300-character note clip (tools/jev/context.NOTE_CHARS) for a directory name of up to 40
    # characters, so neither remedy is cut off; each row says why its own code is withheld
    clauses = []
    changed, missing = behind["clone"]
    if changed or missing:
        how = "`git pull`" if is_hub else f"`tools/update-submodules.sh --no-commit {checkout}`"
        clauses.append(f"index behind the agent's clone: {changed} changed, {missing} missing hit(s) (code withheld) "
                       f"— {REMEDY_INDEX_CLONE.format(how=how)}")
    changed, missing = behind["checkout"]
    if changed or missing:
        clauses.append(f"index behind the checkout: {changed} changed, {missing} missing hit(s) (code withheld) — "
                       f"{REMEDY_INDEX}")
    if clauses:
        note = "; ".join([*clauses, note])
    status = "stale" if clauses else ("ok" if rows else "empty")
    return section("index_code", status, rows, now=now, note=note, truncated=truncated)


def _chunk_note(qdrant: str, collection: str, name: str, is_hub: bool, deadline: Deadline,
                checkout: str | None = None) -> str:
    """How much of the target the index can see, counted under its checkout
    directory (the index's own key, `projects/<dir>/…`, which can differ
    from the registry name in case). Best effort: one count, never the
    reason to fail."""
    if deadline.left() < 0.5:
        return ""
    if is_hub:
        filt = {"must_not": [{"key": "pathSegments.0", "match": {"value": "projects"}}]}
    else:
        filt = {"must": [{"key": "pathSegments.0", "match": {"value": "projects"}},
                         {"key": "pathSegments.1", "match": {"value": checkout or name}}]}
    try:
        doc = http_json("qdrant", qdrant, "POST", f"/collections/{collection}/points/count",
                        {"filter": filt, "exact": False}, deadline=deadline) or {}
    except Unavailable:
        return "; chunk count unavailable"
    n = int((doc.get("result") or {}).get("count") or 0)
    who = "the hub" if is_hub else name
    if n == 0:
        return f"; the index holds no chunks for {who} (submodule not checked out, or not scanned)"
    return f"; {who} has ~{n} chunks"


# --------------------------------------------------------------------------- #
# i/o: Claude Code telemetry (Elasticsearch)
# --------------------------------------------------------------------------- #
def _src(src: dict, dotted: str):
    """A field of a _source that may come back nested or flattened (logsdb synthesises it)."""
    if dotted in src:
        return src[dotted]
    cur = src
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def telemetry_errors(nwo: str, since: str, deadline: Deadline, now: dt.datetime,
                     contract: dict | None = None) -> dict:
    contract = contract or fleet_observe.load_contract()
    logs = contract["logs"]
    es = fleet_observe.probe_url("elasticsearch", logs.get("elasticsearch") or "")
    pattern = f"logs-{logs['datasets']['claude']}-*"
    repo = {"term": {"fleet.repo": {"value": nwo, "case_insensitive": True}}}
    window = {"range": {"@timestamp": {"gte": since}}}
    body = {
        "size": TELEMETRY_SAMPLE, "track_total_hits": True, "timeout": "4s",
        "_source": ["@timestamp", "claude.tool_name", "claude.tool_input", "claude.tool_parameters"],
        "sort": [{"@timestamp": {"order": "desc"}}],
        "query": {"bool": {"filter": [{"term": {"claude.event_name": "tool_result"}},
                                      {"term": {"claude.success": "false"}}, repo, window]}},
        # `global` escapes the query: the newest event in the WHOLE stream is the
        # plane's freshness, and the API errors are a different event name.
        "aggs": {"all": {"global": {}, "aggs": {
            "newest": {"max": {"field": "@timestamp"}},
            "api_errors": {"filter": {"bool": {"filter": [{"term": {"claude.event_name": "api_error"}},
                                                          repo, window]}}}}}},
    }
    doc = http_json("elasticsearch", es, "POST", f"/{pattern}/_search", body, deadline=deadline) or {}
    aggs = (doc.get("aggregations") or {}).get("all") or {}
    newest = aggs.get("newest") or {}
    as_of = iso_z(newest.get("value_as_string")) if newest.get("value") is not None else None
    hits = (doc.get("hits") or {}).get("hits") or []
    total = ((doc.get("hits") or {}).get("total") or {})
    total = int(total.get("value") or 0) if isinstance(total, dict) else int(total or 0)
    groups: dict[tuple, dict] = {}
    for hit in hits:
        deadline.within("the telemetry hits")
        src = hit.get("_source") or {}
        tool = clean_line(_src(src, "claude.tool_name") or "unknown", NAME_CHARS)
        head = None
        if tool == "Bash":
            raw = _src(src, "claude.tool_input") or _src(src, "claude.tool_parameters")
            head = command_head(command_of(raw)) or "(unparsed)"
        row = groups.setdefault((tool, head), {"kind": "tool_error", "tool": tool, "head": head,
                                               "count": 0, "last_at": None})
        row["count"] += 1
        row["last_at"] = row["last_at"] or iso_z(_src(src, "@timestamp"))
    ranked = sorted(groups.values(), key=lambda g: (-g["count"], g["tool"], g["head"] or ""))
    rows = ranked[:CAP_TELEMETRY]
    dropped = len(ranked) - len(rows)
    api_errors = int(((aggs.get("api_errors") or {}).get("doc_count")) or 0)
    if api_errors:
        rows.append({"kind": "api_errors", "count": api_errors})
    if as_of is None:   # the stream holds nothing at all: telemetry was never pointed here
        return section("telemetry_errors", "empty", rows, now=now, truncated=dropped,
                       note=f"no Claude Code telemetry in {pattern} — {REMEDY_TELEMETRY}")
    notes = [f"{pattern}, fleet.repo {nwo}"]
    if total > len(hits):
        notes.append(f"the newest {len(hits)} of {total} failed tool results were read")
    stale, note = freshness(as_of, now, "Claude Code telemetry", f"is the OTel collector up? {REMEDY_PLANES}")
    return _done("telemetry_errors", rows, as_of, now, stale, "; ".join(([note] if note else []) + notes),
                 dropped)


# --------------------------------------------------------------------------- #
# the document
# --------------------------------------------------------------------------- #
def section(key: str, status: str, rows=None, *, as_of: str | None = None, now: dt.datetime | None = None,
            note: str = "", truncated: int = 0, elapsed_ms: int = 0) -> dict:
    assert status in STATUSES, status
    return {"status": status, "source": SOURCES[key], "as_of": as_of,
            "age_hours": age_hours(as_of, now or utcnow()), "note": note,
            "elapsed_ms": int(elapsed_ms), "truncated": int(max(0, truncated)), "rows": list(rows or [])}


def unavailable(key: str, exc: Unavailable, now: dt.datetime) -> dict:
    return section(key, "unavailable", now=now, note=exc.note())


def _load_yaml(path: Path | str | None):
    try:
        with Path(path).open(encoding="utf-8") as fh:
            return yaml.load(fh, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))  # noqa: S506 - a SafeLoader
    except (OSError, yaml.YAMLError, TypeError):
        return None


def registry_branches(path: Path | str | None) -> dict:
    """lower(nwo) -> registry row, for the tracked branch."""
    out = {}
    for row in _load_yaml(path or REGISTRY_DEFAULT) or []:
        url = str((row or {}).get("repo_url") or "").rstrip("/").removesuffix(".git")
        if "github.com/" in url:
            out[url.split("github.com/", 1)[1].lower()] = row
    return out


def checkout_dir(registry_path: Path | str | None, nwo: str, name: str) -> str:
    """The target's directory under projects/ — the code index's key for it —
    from the registry's submodule_path (zer0-CMS is checked out as
    projects/zer0-cms), else `name`."""
    row = registry_branches(registry_path).get(nwo.lower()) or {}
    sub = Path(str(row.get("submodule_path") or ""))
    return sub.name if len(sub.parts) == 2 and sub.parts[0] == "projects" and NAME_RX.match(sub.name) else name


def _open_lake(lake_dir, deadline: Deadline) -> tuple[sqlite3.Connection, set[str]]:
    _, db = fleet_lake.lake_paths(lake_dir)
    if not Path(db).is_file():
        raise Unavailable(f"no lake at {db}", f"{REMEDY_LAKE} (or point DASH_LAKE_DIR at one)")
    conn = None
    try:
        conn = open_ro(Path(db), timeout=deadline.timeout())
        # The deadline reaches inside a query too: past it, sqlite interrupts.
        conn.set_progress_handler(lambda: 1 if deadline.expired() else 0, 2000)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    except sqlite3.Error as exc:
        if conn is not None:
            conn.close()
        # A lock is usually the sync itself, mid-write: telling the operator to
        # run another one is wrong. A missing or corrupt lake is a sync's job.
        said = str(exc).lower()
        locked = isinstance(exc, sqlite3.OperationalError) and ("locked" in said or "busy" in said)
        raise Unavailable(f"the lake could not be read: {clean_line(exc, 160)}",
                          REMEDY_LOCKED if locked else REMEDY_LAKE) from None
    return conn, tables


def _run(key: str, fn, now: dt.datetime, deadline: Deadline) -> dict:
    """One section, timed; whatever it raises becomes the section, never the document's end."""
    started = time.monotonic()
    try:
        deadline.check()
        doc = fn()
    except Unavailable as exc:
        doc = unavailable(key, exc, now)
    except sqlite3.OperationalError as exc:
        if "interrupt" in str(exc).lower():
            doc = unavailable(key, Unavailable("the lake read was cut off by the --deadline-s budget",
                                               REMEDY_DEADLINE), now)
        else:
            doc = unavailable(key, Unavailable(f"the lake read failed: {clean_line(exc, 160)}",
                                               REMEDY_LOCKED), now)
    except sqlite3.Error as exc:
        doc = unavailable(key, Unavailable(f"the lake read failed: {clean_line(exc, 160)}", REMEDY_LAKE), now)
    except Exception as exc:   # a bug here (RouteRefused included) costs one section, and says so
        doc = unavailable(key, Unavailable(f"internal error: {type(exc).__name__}: {clean_line(exc, 160)}",
                                           "report it; the other sections stand"), now)
    doc["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    return doc


def build(nwo: str, name: str, *, queries: list[str] | None = None, days: int = DAYS_DEFAULT,
          sections: list[str] | tuple[str, ...] = SECTIONS, deadline_s: float = DEADLINE_DEFAULT_S,
          lake_dir: Path | str | None = None, fleet_path: Path | str | None = None,
          registry_path: Path | str | None = None, now: dt.datetime | None = None,
          scrubber: Scrubber | None = None, index_cfg: dict | None = None,
          contract: dict | None = None, home: str | None = None, index_root: Path | str | None = None,
          target_dir: Path | str | None = None) -> dict:
    """The whole fleet-context/v1 document. Never raises for a plane; usage is checked by the caller.
    `target_dir` (--target-dir) is the agent's clone of the target, which its code-index hits are checked
    against; it is recorded in the document (redacted like the rest) when given."""
    now = now or utcnow()
    deadline = Deadline(deadline_s)
    queries = list(queries or [])
    since = fleet_lake.iso(now - dt.timedelta(days=days))
    fleet = _load_yaml(fleet_path or FLEET_DEFAULT) or {}
    hub = str(((fleet.get("hub") or {}).get("repo")) or "")
    is_hub = bool(hub) and hub.lower() == nwo.lower()
    scout_label = str(((fleet.get("scout") or {}).get("label")) or SCOUT_LABEL_DEFAULT)
    wanted = [k for k in SECTIONS if k in sections]
    out: dict[str, dict] = {}

    lake_keys = [k for k in wanted if SOURCES[k] == "lake"]
    if lake_keys:
        opened = time.monotonic()
        try:
            conn, tables = _open_lake(lake_dir, deadline)
        except Unavailable as exc:
            conn, tables = None, set()
            for k in lake_keys:
                out[k] = unavailable(k, exc, now)
                out[k]["elapsed_ms"] = int((time.monotonic() - opened) * 1000)
        if conn is not None:
            open_ms = int((time.monotonic() - opened) * 1000)
            registry = registry_branches(registry_path) if "lake_ci" in lake_keys else {}
            jobs = {
                "lake_issues": lambda: lake_issues(conn, tables, nwo, since, now, scout_label, deadline),
                "lake_ci": lambda: lake_ci(conn, tables, nwo, since, now,
                                           tracked_branch(conn, tables, nwo, registry), deadline),
                "lake_agents": lambda: lake_agents(conn, tables, nwo, name, since, now, deadline, home),
            }
            try:
                for k in lake_keys:
                    out[k] = _run(k, jobs[k], now, deadline)
                out[lake_keys[0]]["elapsed_ms"] += open_ms   # opening the lake is the first section's cost
            finally:
                conn.close()

    # Elasticsearch before Qdrant: one request, where the index needs several.
    if "telemetry_errors" in wanted:
        out["telemetry_errors"] = _run("telemetry_errors",
                                       lambda: telemetry_errors(nwo, since, deadline, now, contract),
                                       now, deadline)
    if "index_code" in wanted:
        checkout = checkout_dir(registry_path, nwo, name)
        out["index_code"] = _run("index_code",
                                 lambda: index_code(queries, name, is_hub, deadline, now, index_cfg,
                                                    checkout=checkout, root=index_root, target_dir=target_dir),
                                 now, deadline)

    doc = {"schema": SCHEMA, "generated_at": fleet_lake.iso(now), "nwo": nwo, "name": name,
           "window_days": int(days), "queries": queries, "sections": {k: out[k] for k in wanted}}
    if target_dir:
        doc["target_dir"] = str(target_dir)
    return (scrubber or Scrubber()).obj(doc)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _has_control(text: str) -> bool:
    return any(unicodedata.category(c) == "Cc" for c in text) or bool(_CTRL.search(text))


def usage_problems(args: argparse.Namespace) -> list[str]:
    """Everything that makes the request itself wrong. Any of these exits 2."""
    problems = []
    nwo, name = args.nwo or "", args.name or ""
    if not NWO_RX.match(nwo) or nwo.split("/")[1] in (".", ".."):
        problems.append(f"--nwo must be OWNER/REPO, got {nwo!r}")
    if not NAME_RX.match(name) or name in (".", ".."):
        problems.append(f"--name must be a checkout directory name ([A-Za-z0-9._-], no slash), got {name!r}")
    queries = args.query or []
    if len(queries) > MAX_QUERIES:
        problems.append(f"at most {MAX_QUERIES} --query, got {len(queries)}")
    for q in queries:
        if not q.strip():
            problems.append("--query is empty")
        elif len(q) > MAX_QUERY_CHARS:
            problems.append(f"--query is over {MAX_QUERY_CHARS} characters ({len(q)})")
        elif _has_control(q):
            problems.append("--query carries a control character")
    if not 1 <= args.days <= MAX_DAYS:
        problems.append(f"--days must be 1..{MAX_DAYS}, got {args.days}")
    if not 0 < args.deadline_s <= MAX_DEADLINE_S:
        problems.append(f"--deadline-s must be in (0, {MAX_DEADLINE_S:g}], got {args.deadline_s:g}")
    unknown = [s for s in parse_sections(args.sections) if s not in SECTIONS]
    if unknown:
        problems.append(f"unknown section(s) {', '.join(unknown)}; known: {', '.join(SECTIONS)}")
    why = None if args.target_dir is None else target_dir_problem(args.target_dir)
    if why:
        problems.append(f"--target-dir {why}")
    return problems


def parse_sections(raw: str | None) -> list[str]:
    picked = [s.strip() for s in (raw or "").split(",") if s.strip()]
    return picked or list(SECTIONS)


def summary(doc: dict) -> str:
    lines = [f"context {doc['nwo']} ({doc['name']}), {doc['window_days']} d window"]
    for key, sec in doc["sections"].items():
        age = f" ({sec['age_hours']:g} h old)" if sec.get("age_hours") is not None else ""
        lines.append(f"  {key:<17} {sec['status']:<12} {len(sec['rows']):>3} rows  "
                     f"{sec['elapsed_ms']:>5} ms{age}  {sec['note'][:110]}")
    return "\n".join(lines) + "\n"


def cmd_context(args: argparse.Namespace) -> int:
    problems = usage_problems(args)
    if problems:
        for p in problems:
            sys.stderr.write(f"dash-gen context: {p}\n")
        return 2
    doc = build(args.nwo, args.name, queries=[q.strip() for q in args.query or []], days=args.days,
                sections=parse_sections(args.sections), deadline_s=args.deadline_s, lake_dir=args.lake_dir,
                target_dir=os.path.normpath(args.target_dir) if args.target_dir is not None else None)
    sys.stdout.write(json.dumps(doc, indent=2, ensure_ascii=True) + "\n")
    if not args.json:
        sys.stderr.write(summary(doc))
    return 0


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--nwo", required=True, help="OWNER/REPO the pack is for")
    parser.add_argument("--name", required=True,
                        help="the repo's checkout directory name (the lake's sessions.repo, the index's project)")
    parser.add_argument("--query", action="append", default=[], metavar="TEXT",
                        help=f"a code-index query (repeatable, at most {MAX_QUERIES}, {MAX_QUERY_CHARS} chars)")
    parser.add_argument("--days", type=int, default=DAYS_DEFAULT, help=f"window (default {DAYS_DEFAULT})")
    parser.add_argument("--sections", default="", help=f"comma list of {','.join(SECTIONS)} (default all)")
    parser.add_argument("--deadline-s", type=float, default=DEADLINE_DEFAULT_S,
                        help=f"overall time budget in seconds (default {DEADLINE_DEFAULT_S:g}; "
                             f"each request is also capped at {REQUEST_TIMEOUT_S:g} s)")
    parser.add_argument("--lake-dir", default=None,
                        help="lake directory (DASH_LAKE_DIR; default .dash-lake/ at the repo root)")
    parser.add_argument("--target-dir", default=None, metavar="PATH",
                        help="the agent's clone of the target (absolute, a real directory, no symlink in it): the "
                             "target's code-index hits are checked against its files instead of projects/<dir> "
                             "in this checkout; only read"),
    parser.add_argument("--json", action="store_true",
                        help="stdout only (the document is always on stdout; without this a summary goes to stderr)")
    parser.set_defaults(func=cmd_context)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dash-gen context", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(parser)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
