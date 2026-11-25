#!/usr/bin/env python3
"""switches — the fleet's loop kill switches, read live and flipped through the map (constitution § 17).

`_data/fleet.yml` `switches:` (schema `switches/v1`) is the one source of truth for every loop's kill
switch; a repository variable such as `CONTENT_FACTORY_ENABLED` is a projection of it (§ 17.2). This
module is the console's, the CLI's and the MCP layer's one implementation of that projection
(HUB-057, FR54, amendment 0014):

  document  every `switches.loops` record grouped by repository, with its live variable (ONE paginated
            list call per repository, through the console's token source; a 403 or 404 reads as
            "unreadable", never as "off"), the effective state the loop runs with (the most restrictive
            of the global, group, repo and loop levels, then the gate: `tools/weekly/prepare.py`
            `switch_state`, and a code-level `hold:` on top), the map's own state, drift between the two,
            and whether the console could flip it.
  plan      a scope (one loop, every loop of a repo, a group, or everything), a target (on | off) and a
            required reason → per loop the variable's current → new value (opt_in and opt_out alike: on
            writes 'true', off writes 'false', and a variable that already reads as the target is left
            alone), and the exact `_data/fleet.yml` diff the apply would write (state, verified: true,
            reason, set_by = the token's GitHub login, set_at = today in UTC). Deterministic plan id; the
            plan is kept under .fleet/switches/plans/. Writes nothing else (§ 17.3: the diff by default).
  apply     `tools/dash switches apply --plan-id X [--apply]` — the console's `switches-apply` operation,
            remote and confirm-gated (§ 11.8). The plan is made again from live state and refused when its
            id differs; without --apply it says only whether the preview still matches. With --apply: only
            while the console's GitHub writes are on (DASH_CONSOLE_GITHUB_WRITES / DASH_CONSOLE_AUTH) and
            only for repositories the hub owns (github_link.fleet_repos), each variable is set (PATCH, or
            POST when it does not exist) and read back; the records whose variable reads back right are
            spliced into _data/fleet.yml with a ruamel round trip confined to those records, so the rest of
            the file stays byte-identical; each flip is emitted to the fleet activity log
            (tools/fleet_activity.py: who, what, scope, reason, old and new, § 17.4) and appended to the
            JSONL audit file. Committing the map change stays with the operator.

Never (§ 17.8): reads, prints or changes a secret — only `actions/variables`, whose values are plain
text by GitHub's design; the token is used, never shown. Docs: docs/AI-INTEGRATION.md "Loop switches".
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import hashlib
import io
import json
import os
import re
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (ROOT / "tools", ROOT, HERE):            # tools/console first: `core` is the console's
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import core  # noqa: E402  (the console's core: paths, scrub; PyYAML only)
import github_link as ghl  # noqa: E402  (the token source, the REST client, the fleet allowlist)
import fleet_activity  # noqa: E402  (tools/fleet_activity.py — the § 17.4 activity log's producer)
from gh_projects_write import _audit  # noqa: E402  (the redacting JSONL audit writer)
from tools.weekly.prepare import switch_state  # noqa: E402  (the one reading of a loop's switch)

DOC_SCHEMA = "switches-console/v1"
PLAN_SCHEMA = "switches-plan/v1"
MAP_SCHEMA = "switches/v1"
SCOPES = ("loop", "repo", "group", "all")
TARGETS = ("on", "off")
REASON_MIN, REASON_MAX = 3, 300
MAX_ITEMS = 120
VARIABLES_PAGE = 30          # GitHub's ceiling for actions/variables
MAX_PAGES = 10
LIVE_TTL_S = 30.0
BOT_ID = "console-switches"
PLAN_ID_RX = re.compile(r"^[0-9a-f]{16}$")
KEY_RX = re.compile(r"^[A-Za-z0-9._/-]{1,120}$")
NWO_RX = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
VAR_RX = re.compile(r"^[A-Z][A-Z0-9_]*$")
TOKEN_RX = re.compile(r"(gh[pousr]_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{8,}|sk-[A-Za-z0-9_-]{8,}|AKIA[0-9A-Z]{12,})")
FLEET_REL = "_data/fleet.yml"

Api = Callable[..., Any]


class Refused(Exception):
    """An apply that must not write: the plan moved, writes are off, or the plan is unknown."""

    def __init__(self, message: str, code: int = 3):
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------- #
# Files
# --------------------------------------------------------------------------- #
def state_dir(root: Path = ROOT) -> Path:
    p = os.environ.get("DASH_SWITCHES_DIR")
    return Path(p).expanduser() if p else root / ".fleet" / "switches"


def audit_path(root: Path = ROOT) -> Path:
    """The JSONL audit file: HARNESS_PROJECTS_AUDIT when the operator keeps one audit for every harness
    write (§ 11.6), else .fleet/switches/github-writes.jsonl (gitignored), like projects_backfill.py's."""
    p = os.environ.get("HARNESS_PROJECTS_AUDIT")
    if p:
        path = Path(p).expanduser()
        return path if path.is_absolute() else root / path
    return state_dir(root) / "github-writes.jsonl"


def activity_queue(root: Path = ROOT) -> Path:
    """The fleet activity log's local spool (§ 17.4): FLEET_ACTIVITY_QUEUE, else beside the audit."""
    return Path(os.environ["FLEET_ACTIVITY_QUEUE"]) if os.environ.get("FLEET_ACTIVITY_QUEUE") \
        else state_dir(root) / "activity.jsonl"


def _write_json(path: Path, doc: Any) -> None:
    """Owner-only and atomic: a plan names repositories and the operator's login."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True, default=str), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def fleet_path(root: Path = ROOT) -> Path:
    return root / FLEET_REL


def load_fleet(root: Path = ROOT) -> dict:
    doc = yaml.safe_load(fleet_path(root).read_text(encoding="utf-8")) or {}
    return doc if isinstance(doc, dict) else {}


def load_map(fleet: dict) -> dict:
    sw = fleet.get("switches")
    if not isinstance(sw, dict) or sw.get("schema") != MAP_SCHEMA:
        raise ValueError(f"_data/fleet.yml has no `switches:` map of schema {MAP_SCHEMA}")
    return sw


def loops_of(sw: dict) -> dict[str, dict]:
    return {str(k): v for k, v in (sw.get("loops") or {}).items() if isinstance(v, dict)}


# --------------------------------------------------------------------------- #
# GitHub — through the console's own client and token source, never a secret
# --------------------------------------------------------------------------- #
def _api(api: Api | None) -> Api:
    return api or ghl.api


def fetch_variables(repo: str, api: Api | None = None) -> dict:
    """One repository's Actions variables: name → {value, updated_at}. Paginated (30 a page), so it is
    one call for every repository the map names today. A 403 or 404 is `unreadable` — the token cannot
    see them — and never `unset`, which would read as off (or on) for every loop of the repository."""
    call = _api(api)
    out: dict[str, dict] = {}
    try:
        for page in range(1, MAX_PAGES + 1):
            data = call("GET", f"/repos/{repo}/actions/variables?per_page={VARIABLES_PAGE}&page={page}") or {}
            batch = data.get("variables") or []
            for v in batch:
                if isinstance(v, dict) and v.get("name"):
                    out[str(v["name"])] = {"value": str(v.get("value") if v.get("value") is not None else ""),
                                           "updated_at": v.get("updated_at")}
            if len(batch) < VARIABLES_PAGE or len(out) >= int(data.get("total_count") or 0):
                break
    except ghl.GitHubError as exc:
        return {"readable": False, "status": exc.status, "error": core._scrub(str(exc))[:200], "variables": {}}
    return {"readable": True, "status": 200, "error": None, "variables": out}


_LIVE: dict = {"at": 0.0, "key": None, "data": None}
_LIVE_LOCK = threading.Lock()


def live_variables(repos: list[str], api: Api | None = None, refresh: bool = False) -> dict[str, dict]:
    """Every named repository's variables, side by side; cached LIVE_TTL_S for the console's own client
    (a test's `api` is never cached)."""
    key = tuple(sorted(repos))
    if api is None and not refresh:
        with _LIVE_LOCK:
            if _LIVE["key"] == key and time.time() - _LIVE["at"] < LIVE_TTL_S:
                return _LIVE["data"]
    with ThreadPoolExecutor(max(1, min(6, len(key)))) as pool:
        data = dict(zip(key, pool.map(lambda r: fetch_variables(r, api), key)))
    if api is None:
        with _LIVE_LOCK:
            _LIVE.update(at=time.time(), key=key, data=data)
    return data


_LOGIN: dict = {"at": 0.0, "login": None}


def gh_login(api: Api | None = None) -> str | None:
    """The authenticated account's login (set_by), or None when there is no working token."""
    if api is None and _LOGIN["login"] and time.time() - _LOGIN["at"] < 300:
        return _LOGIN["login"]
    try:
        login = str((_api(api)("GET", "/user") or {}).get("login") or "") or None
    except ghl.GitHubError:
        login = None
    if api is None and login:
        _LOGIN.update(at=time.time(), login=login)
    return login


def writes_state() -> dict:
    """Whether the console may write variables at all (the same two switches as every GitHub write)."""
    on = bool(ghl.GITHUB_WRITES and core.AUTH_WRITES)
    return {"enabled": on, "why": None if on else
            "GitHub writes are switched off in this console (DASH_CONSOLE_GITHUB_WRITES / DASH_CONSOLE_AUTH)"}


def writable_repos() -> set[str]:
    """owner/name (lowercased) of the repositories the hub owns — the only ones the console writes to."""
    return set(ghl.fleet_repos())


def set_variable(repo: str, name: str, value: str, api: Api | None = None) -> dict:
    """PATCH the variable, or POST it when it does not exist; then read it back. Returns
    {ok, method, value (read back), error}."""
    call = _api(api)
    quoted = urllib.parse.quote(name, safe="")
    method = "PATCH"
    try:
        try:
            call("PATCH", f"/repos/{repo}/actions/variables/{quoted}", {"name": name, "value": value})
        except ghl.GitHubError as exc:
            if exc.status != 404:
                raise
            method = "POST"
            call("POST", f"/repos/{repo}/actions/variables", {"name": name, "value": value})
        back = call("GET", f"/repos/{repo}/actions/variables/{quoted}") or {}
    except ghl.GitHubError as exc:
        return {"ok": False, "method": method, "value": None, "error": core._scrub(str(exc))[:200]}
    got = str(back.get("value") if back.get("value") is not None else "")
    ok = got == value
    return {"ok": ok, "method": method, "value": got, "updated_at": back.get("updated_at"),
            "error": None if ok else f"read back {got!r}, expected {value!r}"}


# --------------------------------------------------------------------------- #
# One loop's row
# --------------------------------------------------------------------------- #
def _is_off(level: Any) -> bool:
    state = level.get("state") if isinstance(level, dict) else None
    return state is False or (isinstance(state, str) and state.strip().lower() == "off")


def _levels(sw: dict, entry: dict) -> list[tuple[str, dict]]:
    return [("global", sw.get("global") or {}),
            (f"group {entry.get('group')}", (sw.get("groups") or {}).get(entry.get("group")) or {}),
            (f"repo {entry.get('repo')}", (sw.get("repos") or {}).get(entry.get("repo")) or {})]


def variable_on(semantics: str, value: str | None) -> bool | None:
    """What a variable's value means to its loop: opt_in runs only on exactly 'true' (unset = off),
    opt_out runs unless exactly 'false' (unset = on). None when it could not be read."""
    if value is None:
        return None
    return value == "true" if semantics == "opt_in" else value != "false"


def target_value(target: str) -> str:
    """The value that makes a loop on or off, under either semantics."""
    return "true" if target == "on" else "false"


def loop_row(key: str, entry: dict, sw: dict, fleet: dict, live: dict[str, dict], writable: set[str]) -> dict:
    gate = entry.get("gate") if isinstance(entry.get("gate"), dict) else {}
    repo = str(entry.get("repo") or "")
    kind = gate.get("kind")
    name = str(gate.get("name") or "") if kind == "repo_variable" else ""
    semantics = str(gate.get("semantics") or "") if kind == "repo_variable" else ""
    rl = live.get(repo) or {}
    raw: str | None = None
    live_state = "n/a"
    updated_at = None
    if name:
        if rl.get("readable"):
            v = (rl.get("variables") or {}).get(name)
            raw = v["value"] if v else ""
            updated_at = v.get("updated_at") if v else None
            live_state = "set" if v else "unset"
        else:
            live_state = "unreadable"

    def read(r: str, n: str) -> tuple[str | None, str | None]:
        if not (live.get(r) or {}).get("readable"):
            return None, f"its variables could not be read ({(live.get(r) or {}).get('error') or 'no read'})"
        v = ((live.get(r) or {}).get("variables") or {}).get(n)
        return (v["value"] if v else ""), None

    eff = switch_state(entry, sw, fleet, read if name else None)
    effective: bool | None = eff.get("on")
    why = str(eff.get("why") or "")
    hold = entry.get("hold") if isinstance(entry.get("hold"), dict) else None
    if hold:
        held = f"held by {hold.get('kind') or 'code'} {hold.get('name')}={hold.get('value')!r}"
        why = f"{held} ({hold.get('source') or 'see the record'}), whatever the variable says; " + why
        effective = False
    var_on = variable_on(semantics, raw) if name else None
    map_state = str(entry.get("state") or "unverified")
    level_off = next((n for n, lv in _levels(sw, entry) if _is_off(lv)), None)
    map_says = "off" if level_off else (map_state if map_state in TARGETS else None)
    drift = None
    if name and var_on is not None and map_says is not None:
        drift = (map_says == "on") != var_on
    flippable, not_why, _code = can_flip(entry, fleet, live, writable)
    return {
        "key": key, "repo": repo, "workflow": entry.get("workflow"), "group": entry.get("group"),
        "owner": entry.get("owner"), "scope": entry.get("scope"), "gate": kind, "variable": name or gate.get("name"),
        "semantics": semantics or None, "default": entry.get("default"),
        "live": {"value": raw, "state": live_state, "updated_at": updated_at, "on": var_on},
        "effective": {"on": effective, "why": why, "verified": bool(eff.get("verified"))},
        "map": {"state": map_state, "verified": bool(entry.get("verified")), "says": map_says, "level_off": level_off,
                "reason": entry.get("reason"), "set_by": entry.get("set_by"), "set_at": entry.get("set_at"),
                "expires": entry.get("expires")},
        "drift": drift, "hold": hold, "note": entry.get("note"),
        "flippable": flippable, "not_flippable": not_why,
    }


def can_flip(entry: dict, fleet: dict, live: dict[str, dict], writable: set[str]) -> tuple[bool, str | None, str]:
    """Whether the console can set this loop's variable at all: (ok, why not, code). Only `not-owned` is
    soft — a record whose variable already reads as the target can still be recorded, which writes
    nothing to GitHub."""
    gate = entry.get("gate") if isinstance(entry.get("gate"), dict) else {}
    repo = str(entry.get("repo") or "")
    if gate.get("kind") != "repo_variable" or not gate.get("name"):
        return False, (f"no variable switch (gate kind {gate.get('kind')!r}): " + str(entry.get("flip") or "record a flip by hand")), "gate"
    if not VAR_RX.match(str(gate["name"])) or not NWO_RX.match(repo):
        return False, "the record's repo or variable name is malformed", "malformed"
    if str(gate["name"]) in (fleet.get("variables") or {}):
        return False, (f"{gate['name']} is a canonical variable (_data/fleet.yml variables:): `tools/dash config sync` "
                       "projects it fleet-wide, so keep one repo off with variable_overrides: instead"), "canonical"
    if not (live.get(repo) or {}).get("readable"):
        return False, (f"{repo}'s variables could not be read ({(live.get(repo) or {}).get('error') or 'no read'}): "
                       "nothing is written blind"), "unreadable"
    if repo.lower() not in writable:
        return False, f"{repo} is not a repository the hub owns — the console reads it but will not write to it", "not-owned"
    return True, None, "ok"


# --------------------------------------------------------------------------- #
# The document
# --------------------------------------------------------------------------- #
def document(root: Path = ROOT, api: Api | None = None, refresh: bool = False) -> dict:
    """Every loop record grouped by repository, with its live and effective state (GET /api/switches)."""
    fleet = load_fleet(root)
    sw = load_map(fleet)
    loops = loops_of(sw)
    repos = sorted({str(e.get("repo") or "") for e in loops.values() if e.get("repo")})
    live = live_variables(repos, api, refresh=refresh)
    writable = writable_repos()
    rows = [loop_row(k, e, sw, fleet, live, writable) for k, e in loops.items()]
    by_repo = []
    for repo in repos:
        mine = [r for r in rows if r["repo"] == repo]
        rl = live.get(repo) or {}
        by_repo.append({
            "repo": repo, "writable": repo.lower() in writable, "readable": bool(rl.get("readable")),
            "error": rl.get("error"), "level": (sw.get("repos") or {}).get(repo),
            "loops": mine,
            "counts": {"loops": len(mine), "on": sum(r["effective"]["on"] is True for r in mine),
                       "off": sum(r["effective"]["on"] is False for r in mine),
                       "unknown": sum(r["effective"]["on"] is None for r in mine),
                       "drift": sum(r["drift"] is True for r in mine), "flippable": sum(r["flippable"] for r in mine)},
        })
    return {
        "schema": DOC_SCHEMA, "map_schema": MAP_SCHEMA, "generated_at": _iso(_now()),
        "writes": writes_state(), "login": gh_login(api),
        "global": sw.get("global"), "groups": sw.get("groups") or {}, "levels": sw.get("repos") or {},
        "repos": by_repo,
        "counts": {"repos": len(by_repo), "loops": len(rows), "drift": sum(r["drift"] is True for r in rows),
                   "on": sum(r["effective"]["on"] is True for r in rows), "off": sum(r["effective"]["on"] is False for r in rows),
                   "unreadable": sum(1 for r in by_repo if not r["readable"]), "flippable": sum(r["flippable"] for r in rows)},
        "commit": "the console never commits: an apply edits _data/fleet.yml in the working tree; commit it in a PR",
    }


# --------------------------------------------------------------------------- #
# The map splice — ruamel, confined to the touched loop records
# --------------------------------------------------------------------------- #
def _ruamel():
    try:
        from ruamel.yaml import YAML
        from ruamel.yaml.scalarstring import SingleQuotedScalarString as SQ
    except ImportError:
        raise RuntimeError("previewing or applying a flip needs ruamel.yaml (pip install ruamel.yaml), which the "
                           "console's own virtualenv has: run it from the console, or `.venv-console/bin/python`") from None
    yml = YAML(typ="rt")
    yml.preserve_quotes = True
    yml.width = 4096
    yml.indent(mapping=2, sequence=4, offset=2)     # fleet.yml's own layout (core_config.update_config)
    yml.representer.add_representer(type(None), lambda r, _d: r.represent_scalar("tag:yaml.org,2002:null", "null"))
    return yml, SQ


def _record_span(lines: list[str], key: str) -> tuple[int, int] | None:
    """[start, end) of `switches.loops.<key>` in a fleet.yml's lines — the record's own lines and nothing
    after its last one (a trailing blank or the next record's comment stays outside)."""
    top = next((i for i, ln in enumerate(lines) if ln.startswith("switches:")), None)
    if top is None:
        return None
    loops = None
    for i in range(top + 1, len(lines)):
        ln = lines[i]
        if ln.strip() and not ln.startswith((" ", "#")):
            return None
        if ln.rstrip("\r\n") == "  loops:":
            loops = i
            break
    if loops is None:
        return None
    head = f"    {key}:"
    start, end = None, len(lines)
    for i in range(loops + 1, len(lines)):
        ln = lines[i].rstrip("\r\n")
        indent = len(ln) - len(ln.lstrip(" "))
        if start is None:
            if ln.strip() and indent <= 2:
                return None                         # left `loops:` without finding it
            if ln == head:
                start = i
            continue
        if ln.strip() and indent <= 4:              # the next record, a comment before it, or `repos:`
            end = i
            break
    if start is None:
        return None
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    return start, end


def _styled_login(login: str, SQ):
    return SQ(login) if re.fullmatch(r"(?i)(-?\d+(\.\d+)?|true|false|yes|no|on|off|null|~)", login) else login


def splice_records(text: str, updates: dict[str, dict]) -> str:
    """`text` with each `switches.loops.<key>` record updated by `updates[key]` (state, verified, reason,
    set_by, set_at), through a ruamel round trip whose output is spliced back record by record: every
    other byte of the file is the original's. Raises ValueError when a record cannot be found."""
    if not updates:
        return text
    yml, SQ = _ruamel()
    doc = yml.load(text)
    loops = doc["switches"]["loops"]
    for key, up in updates.items():
        if key not in loops:
            raise ValueError(f"switches.loops has no record {key!r}")
        rec = loops[key]
        for field in ("state", "verified", "reason", "set_by", "set_at"):
            if field not in up:
                continue
            value = up[field]
            if field in ("state", "reason", "set_at"):
                value = SQ(str(value))
            elif field == "set_by":
                value = _styled_login(str(value), SQ)
            if field in rec:
                rec[field] = value
            else:                                   # after flip / reason / set_by, as the lifehacker records keep them
                after = [k for k in ("flip", "reason", "set_by") if k in rec]
                pos = (list(rec).index(after[-1]) + 1) if after else len(rec)
                rec.insert(pos, field, value)
    buf = io.StringIO()
    yml.dump(doc, buf)
    src = text.splitlines(keepends=True)
    dst = buf.getvalue().splitlines(keepends=True)
    spans = []
    for key in updates:
        a, b = _record_span(src, key), _record_span(dst, key)
        if not a or not b:
            raise ValueError(f"cannot find switches.loops.{key} in _data/fleet.yml's text to splice it")
        spans.append((a, dst[b[0]:b[1]]))
    for (s, e), new in sorted(spans, key=lambda x: x[0][0], reverse=True):
        src[s:e] = new
    out = "".join(src)
    # the splice is checked, not trusted: the data is the original's with exactly these fields changed
    want = yaml.safe_load(text)
    for key, up in updates.items():
        want["switches"]["loops"][key].update(up)
    if yaml.safe_load(out) != want:
        raise ValueError("the spliced _data/fleet.yml does not read back as the intended change; nothing written")
    return out


def unified(before: str, after: str, n: int = 3) -> str:
    """A unified diff of fleet.yml, as git would show it. difflib.unified_diff's matcher treats a line
    that recurs through a long file (`set_by: bamr87`) as junk and shows it removed and re-added, so
    this is its loop over a matcher with autojunk off."""
    a, b = before.splitlines(keepends=True), after.splitlines(keepends=True)

    def span(start: int, stop: int) -> str:
        length = stop - start
        return f"{start + (1 if length else 0)}" + ("" if length == 1 else f",{length}")

    out: list[str] = []
    for group in difflib.SequenceMatcher(None, a, b, autojunk=False).get_grouped_opcodes(n):
        if not out:
            out += [f"--- a/{FLEET_REL}\n", f"+++ b/{FLEET_REL}\n"]
        out.append(f"@@ -{span(group[0][1], group[-1][2])} +{span(group[0][3], group[-1][4])} @@\n")
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                out += [" " + ln for ln in a[i1:i2]]
                continue
            out += ["-" + ln for ln in a[i1:i2]] if tag in ("replace", "delete") else []
            out += ["+" + ln for ln in b[j1:j2]] if tag in ("replace", "insert") else []
    return "".join(ln if ln.endswith("\n") else ln + "\n\\ No newline at end of file\n" for ln in out)


# --------------------------------------------------------------------------- #
# Plan
# --------------------------------------------------------------------------- #
def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def check_reason(reason: Any) -> str:
    text = " ".join(str(reason or "").split())
    if not REASON_MIN <= len(text) <= REASON_MAX:
        raise ValueError(f"a reason is required: {REASON_MIN}–{REASON_MAX} characters saying why (§ 17.4)")
    if TOKEN_RX.search(text):
        raise ValueError("the reason looks like it carries a credential; switches never hold a secret (§ 17.8)")
    return text


def select(sw: dict, scope: str, key: str) -> list[str]:
    """The loop keys a scope names: one loop, every loop of a repo, every loop of a group, or every loop."""
    loops = loops_of(sw)
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {', '.join(SCOPES)}")
    if scope == "all":
        keys = list(loops)
    else:
        if not KEY_RX.match(key or ""):
            raise ValueError(f"{scope} must be named ({KEY_RX.pattern})")
        if scope == "loop":
            if key not in loops:
                raise ValueError(f"no loop {key!r} in switches.loops")
            keys = [key]
        elif scope == "repo":
            keys = [k for k, e in loops.items() if str(e.get("repo") or "").lower() == key.lower()]
        else:
            if key not in (sw.get("groups") or {}):
                raise ValueError(f"no group {key!r} in switches.groups")
            keys = [k for k, e in loops.items() if e.get("group") == key]
        if not keys:
            raise ValueError(f"no loop record in {scope} {key!r}")
    if len(keys) > MAX_ITEMS:
        raise ValueError(f"{len(keys)} loops is past the cap of {MAX_ITEMS} per plan")
    return keys


def _record_sha(text: str, key: str) -> str:
    lines = text.splitlines(keepends=True)
    span = _record_span(lines, key)
    return hashlib.sha256("".join(lines[span[0]:span[1]]).encode() if span else b"").hexdigest()[:12]


def plan_id_of(head: dict, items: list[dict]) -> str:
    keep = ("key", "repo", "variable", "current", "new", "write_variable", "write_map", "do", "skip", "record_sha")
    blob = json.dumps({"head": head, "items": [{k: i.get(k) for k in keep} for i in items]}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def plan(scope: str, key: str, target: str, reason: str, *, root: Path = ROOT, api: Api | None = None,
         save: bool = True, today: str | None = None, login: str | None = None, refresh: bool = True) -> dict:
    """The preview of one flip: per loop current → new, and the exact fleet.yml diff. Writes only the plan file."""
    if target not in TARGETS:
        raise ValueError("target must be on or off")
    reason = check_reason(reason)
    text = fleet_path(root).read_text(encoding="utf-8")
    fleet = yaml.safe_load(text) or {}
    sw = load_map(fleet)
    keys = select(sw, scope, key)
    loops = loops_of(sw)
    repos = sorted({str(loops[k].get("repo") or "") for k in keys if loops[k].get("repo")})
    live = live_variables(repos, api, refresh=refresh)
    writable = writable_repos()
    login = login or gh_login(api)
    writes = writes_state()
    set_at = today or _now().strftime("%Y-%m-%d")
    items: list[dict] = []
    updates: dict[str, dict] = {}
    for k in keys:
        e = loops[k]
        row = loop_row(k, e, sw, fleet, live, writable)
        item = {"key": k, "repo": row["repo"], "workflow": row["workflow"], "variable": row["variable"],
                "semantics": row["semantics"], "current": row["live"]["value"], "current_state": row["live"]["state"],
                "current_on": row["live"]["on"], "new": None, "write_variable": False, "write_map": False,
                "map_before": {"state": row["map"]["state"], "verified": row["map"]["verified"]},
                "map_after": None, "do": False, "skip": None, "record_sha": _record_sha(text, k),
                "effective_before": row["effective"]["on"], "warnings": []}
        ok, why, code = can_flip(e, fleet, live, writable)
        hold = row["hold"]
        if hold and target == "on":
            ok, why, code = False, (f"held by {hold.get('name')}={hold.get('value')!r}: "
                                    f"{hold.get('lift') or 'lift the hold first'}"), "held"
        if code == "not-owned" and row["live"]["on"] == (target == "on"):
            # the variable already reads as the target: only the map is recorded, which is no GitHub write
            ok, why = True, None
        if target == "on" and row["map"]["level_off"]:
            item["warnings"].append(f"{row['map']['level_off']} is off in the map: the loop stays off until it is on")
        if ok:
            want = target_value(target)
            item["write_variable"] = row["live"]["on"] != (target == "on")
            item["new"] = want if item["write_variable"] else item["current"]
            item["write_map"] = (row["map"]["state"] != target or not row["map"]["verified"]
                                 or item["write_variable"])
            if not item["write_variable"] and not item["write_map"]:
                item["skip"] = f"already {target}: {row['variable']} is {_shown(item['current'])} and the map agrees"
            else:
                item["do"] = True
                item["map_after"] = {"state": target, "verified": True}
                updates[k] = {"state": target, "verified": True, "reason": reason, "set_by": login or "unknown",
                              "set_at": set_at}
        else:
            item["skip"] = why
        items.append(item)
    diff, error = "", None
    try:
        diff = unified(text, splice_records(text, updates)) if updates else ""
    except (RuntimeError, ValueError) as exc:
        error = str(exc)
    head = {"scope": scope, "key": key if scope != "all" else "", "target": target, "reason": reason,
            "set_by": login, "set_at": set_at}
    doc = {
        "schema": PLAN_SCHEMA, "plan_id": plan_id_of(head, items), **head, "created_at": _iso(_now()),
        "op": "switches-apply", "writes": writes, "login_known": bool(login), "items": items, "diff": diff,
        "diff_error": error,
        "counts": {"do": sum(i["do"] for i in items), "skip": sum(not i["do"] for i in items),
                   "variables": sum(i["write_variable"] for i in items if i["do"]),
                   "records": sum(i["write_map"] for i in items if i["do"])},
        "commit": "apply edits _data/fleet.yml in the working tree; commit it yourself in a PR the same day (§ 17.2)",
    }
    if save:
        _write_json(state_dir(root) / "plans" / f"{doc['plan_id']}.json", doc)
    return doc


def _shown(value: str | None) -> str:
    return "unreadable" if value is None else ("unset" if value == "" else repr(value))


def stored_plan(plan_id: str, root: Path = ROOT) -> dict | None:
    """A saved plan by its id. The path is one the folder lists, never one built from the request."""
    if not PLAN_ID_RX.match(plan_id or ""):
        raise ValueError("plan_id is 16 hex characters")
    try:
        files = {p.name: p for p in (state_dir(root) / "plans").iterdir()}
    except OSError:
        return None
    path = files.get(f"{plan_id}.json")
    doc = _read_json(path) if path else None
    return doc if isinstance(doc, dict) and doc.get("schema") == PLAN_SCHEMA else None


# --------------------------------------------------------------------------- #
# Apply
# --------------------------------------------------------------------------- #
def apply(plan_id: str, *, do_apply: bool = False, root: Path = ROOT, api: Api | None = None,
          out: Callable[[str], None] = print, today: str | None = None) -> dict:
    """Re-plan from live state and refuse a plan that moved; with do_apply, write it (see the module doc)."""
    stored = stored_plan(plan_id, root)
    if stored is None:
        raise Refused(f"no stored plan {plan_id}: preview it first (the Switches page, or `tools/dash switches plan`)", 2)
    day = today or _now().strftime("%Y-%m-%d")
    if stored.get("set_at") != day:
        raise Refused(f"plan {plan_id} was previewed on {stored.get('set_at')}, so the map would record the wrong day "
                      "— preview it again", 4)
    fresh = plan(stored["scope"], stored.get("key") or "", stored["target"], stored["reason"], root=root, api=api,
                 save=False, today=day, login=None)
    if fresh["plan_id"] != plan_id:
        moved = []
        for a, b in zip(stored["items"], fresh["items"]):
            what = [x for x in (
                f"{b['variable']} {_shown(a.get('current'))} → {_shown(b.get('current'))}" if a.get("current") != b.get("current") else "",
                "its fleet.yml record changed" if a.get("record_sha") != b.get("record_sha") else "",
                f"{'do' if a['do'] else 'skip'} → {'do' if b['do'] else 'skip (' + str(b.get('skip')) + ')'}" if a["do"] != b["do"] else "",
            ) if x]
            if what:
                moved.append(f"  {b['key']}: " + "; ".join(what))
        if fresh.get("set_by") != stored.get("set_by"):
            moved.append(f"  the GitHub login is {fresh.get('set_by')!r}, not {stored.get('set_by')!r}")
        raise Refused("the switches or the map changed since the preview, so this plan is not applied — preview it again:\n"
                      + ("\n".join(moved) or "  the plan's inputs changed"), 4)
    todo = [i for i in fresh["items"] if i["do"]]
    if not do_apply:
        out(f"plan {plan_id} still matches: {len(todo)} to do ({fresh['counts']['variables']} variable(s), "
            f"{fresh['counts']['records']} map record(s)), {fresh['counts']['skip']} skipped. Nothing written (dry run); "
            "--apply writes it.")
        return {"plan_id": plan_id, "applied": False, "matches": True}
    needs_github = [i for i in todo if i["write_variable"]]
    if needs_github and not fresh["writes"]["enabled"]:
        raise Refused(str(fresh["writes"]["why"]))
    if not fresh.get("set_by"):
        raise Refused("no GitHub login: connect the console (or `gh auth login`) so the flip records who made it")
    writable = writable_repos()
    for i in needs_github:
        if i["repo"].lower() not in writable:
            raise Refused(f"{i['repo']} is not a repository the hub owns — the console will not write to it")
    try:  # the map splice is proved on the whole plan BEFORE any variable is written, never discovered after
        splice_records(fleet_path(root).read_text(encoding="utf-8"),
                       {i["key"]: {"state": fresh["target"], "verified": True, "reason": fresh["reason"],
                                   "set_by": fresh["set_by"], "set_at": fresh["set_at"]} for i in todo if i["write_map"]})
    except (RuntimeError, ValueError) as exc:
        raise Refused(f"the map could not be spliced, so nothing is written: {exc}") from None
    out(f"applying plan {plan_id}: {fresh['target']} for {fresh['scope']} {fresh.get('key') or 'everything'} — "
        f"{len(needs_github)} variable(s), {sum(i['write_map'] for i in todo)} map record(s)")
    act = fleet_activity.Activity(BOT_ID, queue=activity_queue(root), dry_run=False, run_id=plan_id)
    results, updates = [], {}
    audit = audit_path(root)
    for i in todo:
        res = {"key": i["key"], "repo": i["repo"], "variable": i["variable"], "old": i["current"], "new": i["new"],
               "wrote": False, "ok": True, "error": None}
        if i["write_variable"]:
            w = set_variable(i["repo"], str(i["variable"]), str(i["new"]), api)
            res.update(wrote=True, ok=w["ok"], error=w["error"], method=w["method"], read_back=w["value"])
        if res["ok"] and i["write_map"]:
            updates[i["key"]] = {"state": fresh["target"], "verified": True, "reason": fresh["reason"],
                                 "set_by": fresh["set_by"], "set_at": fresh["set_at"]}
        record = {"ts": time.time(), "actor": fresh["set_by"], "via": "console switches-apply", "plan_id": plan_id,
                  "op": "variable.set" if i["write_variable"] else "switch.record", "target": f"{i['repo']} {i['variable']}",
                  "loop": i["key"], "scope": f"{fresh['scope']} {fresh.get('key') or ''}".strip(), "reason": fresh["reason"],
                  "before": {"value": i["current"], "map": i["map_before"]},
                  "after": {"value": res.get("read_back", i["new"]), "map": i["map_after"]},
                  "result": "set" if res["ok"] and i["write_variable"] else "recorded" if res["ok"] else "failed",
                  "error": res["error"]}
        _audit(audit, record)
        act.emit("finish", repo=i["repo"], task_ref=f"switch:{i['key']}",
                 decision=f"{i['variable']} {_shown(i['current'])} → {_shown(res.get('read_back', i['new']))} "
                          f"(loop {fresh['target']})",
                 outcome="success" if res["ok"] else "failure", standard=MAP_SCHEMA, standard_source=FLEET_REL,
                 detail={"who": fresh["set_by"], "what": f"{i['key']} {fresh['target']}", "scope": record["scope"],
                         "reason": fresh["reason"], "old": {"value": i["current"], "map": i["map_before"]},
                         "new": {"value": res.get("read_back", i["new"]), "map": i["map_after"]},
                         "plan_id": plan_id, "variable": i["variable"], "error": res["error"]},
                 amendments=[{"amendment": "0014", "relation": "followed"}])
        results.append(res)
        out(f"  {'ok  ' if res['ok'] else 'FAIL'} {i['key']}: {i['variable']} "
            f"{_shown(i['current'])} → {_shown(res.get('read_back', i['new']))}"
            + ("" if i["write_variable"] else " (variable already right; map recorded)")
            + (f" — {res['error']}" if res["error"] else ""))
    for i in fresh["items"]:
        if not i["do"]:
            out(f"  skip {i['key']}: {i['skip']}")
    path = fleet_path(root)
    before = path.read_text(encoding="utf-8")
    after = splice_records(before, updates) if updates else before
    if after != before:
        path.write_text(after, encoding="utf-8")
    diff = unified(before, after)
    flushed = act.flush()
    doc = {"plan_id": plan_id, "applied": True, "applied_at": _iso(_now()), "target": fresh["target"],
           "scope": fresh["scope"], "key": fresh.get("key"), "reason": fresh["reason"], "set_by": fresh["set_by"],
           "ok": sum(r["ok"] for r in results), "failed": sum(not r["ok"] for r in results), "results": results,
           "skipped": [{"key": i["key"], "why": i["skip"]} for i in fresh["items"] if not i["do"]],
           "diff": diff, "activity": {"queue": str(act.queue), "emitted": act.emitted, "flush": flushed, "errors": act.errors},
           "audit": str(audit.relative_to(root)) if audit.is_relative_to(root) else audit.name}
    _write_json(state_dir(root) / "results" / f"{plan_id}.json", doc)
    if diff:
        out("\n" + diff.rstrip("\n"))
    out(f"done: {doc['ok']} ok, {doc['failed']} failed, {len(doc['skipped'])} skipped. _data/fleet.yml is edited in the "
        "working tree, not committed: commit it in a PR the same day (§ 17.2).")
    return doc


# --------------------------------------------------------------------------- #
# The CLI (tools/dash switches)
# --------------------------------------------------------------------------- #
def _badge(on: bool | None) -> str:
    return "on " if on is True else "OFF" if on is False else " ? "


def render(doc: dict, repo: str = "") -> str:
    w = doc["writes"]
    out = [f"loop switches ({doc['map_schema']}): {doc['counts']['loops']} loops in {doc['counts']['repos']} repos · "
           f"{doc['counts']['on']} on · {doc['counts']['off']} off · {doc['counts']['drift']} drift · "
           f"writes {'on' if w['enabled'] else 'OFF'} · login {doc.get('login') or 'none'}"]
    if not w["enabled"]:
        out.append(f"  {w['why']}")
    for r in doc["repos"]:
        if repo and r["repo"].lower() != repo.lower():
            continue
        out.append(f"\n{r['repo']}  ({'writable' if r['writable'] else 'read-only: not a hub-owned repo'}"
                   f"{'' if r['readable'] else '; variables unreadable: ' + str(r['error'])})")
        for x in r["loops"]:
            flags = " ".join(f for f in ("DRIFT" if x["drift"] else "", "held" if x["hold"] else "") if f)
            var = f"{x['variable']}={_shown(x['live']['value'])}" if x["gate"] == "repo_variable" else f"({x['gate']})"
            out.append(f"  {_badge(x['effective']['on'])} {x['key']:<44} {var:<40} map {x['map']['state']:<10} {flags}")
    return "\n".join(out)


def render_plan(doc: dict) -> str:
    out = [f"plan {doc['plan_id']}: turn {doc['scope']} {doc.get('key') or 'everything'} {doc['target']}  "
           f"(reason: {doc['reason']}; set_by {doc.get('set_by') or 'unknown'}; set_at {doc['set_at']})"]
    if not doc["writes"]["enabled"]:
        out.append(f"  ! {doc['writes']['why']}: apply will refuse a variable write")
    for i in doc["items"]:
        if i["do"]:
            var = f"{i['variable']} {_shown(i['current'])} → {_shown(i['new'])}" if i["write_variable"] \
                else f"{i['variable']} stays {_shown(i['current'])}"
            out.append(f"  do   {i['key']}: {var}; map {i['map_before']['state']} → {i['map_after']['state']}")
        else:
            out.append(f"  skip {i['key']}: {i['skip']}")
    if doc.get("diff_error"):
        out.append(f"  ! the fleet.yml diff could not be made: {doc['diff_error']}")
    if doc.get("diff"):
        out.append("\n" + doc["diff"].rstrip("\n"))
    if doc["counts"]["do"]:
        out.append(f"\napply: tools/dash switches apply --plan-id {doc['plan_id']} --apply   (the console: the "
                   "switches-apply operation, behind its confirm)")
    else:
        out.append("\nnothing to apply")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools/dash switches", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    ls = sub.add_parser("list", help="every loop's switch, live vs the map (the default); read-only")
    ls.add_argument("--repo", default="", help="owner/name: one repository's loops")
    ls.add_argument("--json", action="store_true")
    p = sub.add_parser("plan", help="preview a flip: per loop current → new and the fleet.yml diff; writes only the plan file")
    who = p.add_mutually_exclusive_group(required=True)
    who.add_argument("--loop", help="one switches.loops key")
    who.add_argument("--repo", dest="prepo", help="every loop of owner/name")
    who.add_argument("--group", help="every loop of a switches.groups group")
    who.add_argument("--all", action="store_true", help="every loop in the map")
    p.add_argument("--to", required=True, choices=TARGETS)
    p.add_argument("--reason", required=True, help="why (recorded in the map and the activity log)")
    p.add_argument("--json", action="store_true")
    a = sub.add_parser("apply", help="re-plan, refuse a plan that moved, then (--apply) write it")
    a.add_argument("--plan-id", required=True)
    a.add_argument("--apply", action="store_true", help="write: the variables, then the map records (the yes, § 11.8)")
    a.add_argument("--json", action="store_true")
    args = ap.parse_args(list(argv or []) or ["list"])
    try:
        if args.cmd in ("list", None):
            doc = document(ROOT, refresh=True)
            if getattr(args, "repo", ""):
                doc["repos"] = [r for r in doc["repos"] if r["repo"].lower() == args.repo.lower()]
            print(json.dumps(doc, indent=1, default=str) if args.json else render(doc))
            return 0
        if args.cmd == "plan":
            scope, key = (("loop", args.loop) if args.loop else ("repo", args.prepo) if args.prepo
                          else ("group", args.group) if args.group else ("all", ""))
            doc = plan(scope, key, args.to, args.reason, root=ROOT)
            print(json.dumps(doc, indent=1, default=str) if args.json else render_plan(doc))
            return 0
        if args.cmd == "apply":
            quiet = args.json
            doc = apply(args.plan_id, do_apply=args.apply, root=ROOT, out=(lambda _s: None) if quiet else print)
            if quiet:
                print(json.dumps(doc, indent=1, default=str))
            return 0 if not doc.get("failed") else 1
    except Refused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return exc.code
    except (ValueError, LookupError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
