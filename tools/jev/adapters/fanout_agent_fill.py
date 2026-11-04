#!/usr/bin/env python3
"""
File: tools/jev/adapters/fanout_agent_fill.py
Description: The fan-out agent fill's agent steps (fanout.yml, job
             `agent-fill`, one step per kit: `fill-standardize`,
             `fill-schema`) on the JEV loop engine — step 3 of
             bamr87/bamr87#488 (ADR 0002 P3). The deterministic halves stay
             where CI runs them: the planner is `tools/dash-gen agent-fill
             --kit <kit>` (the fan-out's own target list, one item per
             repository at the kit's PR branch, the branch and the agent-pass
             dedupe checked online) and the filer is `tools/dash-gen
             agent-fill-file` (a complete dry run of CI's push step; its
             --apply is refused until #488's publish step lands). This module
             maps their JSON and holds the fill's local-only decisions:
             tier-0 reuse (same HEAD, same kit), the block on a target whose
             kit branch is missing or already filled, and what a valid dry-run
             output is — the patch the engine harvested from the clone
             (`local.harvest: patch`), touching only the files the kit's brief
             allows, with nothing of this machine in it. It imports nothing
             from dash-gen (ADR 0002) and has no GitHub write path of its own:
             the engine runs the spec-declared publish argv.
Author: bamr87
Created: 2026-11-03
Version: 0.1.0
Usage: registered as `fanout_agent_fill` in tools/jev/adapters/__init__.py
       REGISTRY; named by tools/jev/steps/fanout/agent-fill-*.yml `local.adapter`.
Dependencies: Python 3.12 stdlib.
"""
from __future__ import annotations

import hashlib
import json
import re
import tempfile

from ..common import JevError, is_nwo
from ..context import MAX_QUERY_CHARS, ContextRequest
from . import Adapter, Item, PlanResult, PublishPlan, Tier0, Triage, Verdict
from .common import last_json, leaks_private

PATCH = "changes.patch"
VALIDATED = "agent-fill.validated.json"
PATCH_COPY = "agent-fill.patch"
#: The kits with an agent pass: the branch fanout.yml's plan job resolves and
#: the commit subject its push step uses (held equal to dash-gen agent_fill.KITS
#: by tools/test_jev_adapter_fanout_agent_fill.py).
KITS: dict[str, dict[str, str]] = {
    "standardize": {"branch": "chore/standardize-baseline",
                    "subject": "docs(agent-context): fill CLAUDE.md scaffold (Claude agent pass)"},
    "schema": {"branch": "chore/schema-adoption",
               "subject": "docs(schema): fill scaffold purposes (Claude agent pass)"},
}
AGENT_PASS_MARK = "(Claude agent pass)"
NO_DEDUPE = "filing without the duplicate check"
APPLY_REFUSED = "agent-fill-file --apply is not implemented"
ROW_KEYS = ("key", "name", "nwo", "branch", "kit", "commit_subject", "branch_status", "dedupe")
#: what the kit's brief lets the agent touch, as the filer reads it too
QUERIES = {"standardize": ("CLAUDE.md description stack commands", "README install dev test lint"),
           "schema": ("SCHEMA.md purpose pattern generated terminal", "directory layout placement")}


_QUOTED_RX = re.compile(r'"((?:[^"\\]|\\.)*)"')
_C_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}


def _unquote(quoted: str) -> str:
    """git's C-style quoting (core.quotePath): `\\ooo` octal bytes and the
    `\\" \\\\ \\t \\n …` escapes; an escape or a byte sequence that does not
    read is a ValueError (the caller fails closed)."""
    out = bytearray()
    i = 0
    while i < len(quoted):
        ch = quoted[i]
        if ch != "\\":
            out += ch.encode("utf-8")
            i += 1
            continue
        nxt = quoted[i + 1:i + 2]
        if nxt and nxt in "01234567":
            octal = quoted[i + 1:i + 4]
            if len(octal) != 3 or any(c not in "01234567" for c in octal) or int(octal, 8) > 0xFF:
                raise ValueError(f"bad octal escape in {quoted!r}")
            out.append(int(octal, 8))
            i += 4
            continue
        if nxt in _C_ESCAPES:
            out.append(_C_ESCAPES[nxt])
            i += 2
            continue
        raise ValueError(f"bad escape in {quoted!r}")
    text = out.decode("utf-8")
    if "\x00" in text:
        raise ValueError(f"a NUL in a quoted path {quoted!r}")
    return text


def _quoted_or_rest(text: str) -> tuple[str | None, str]:
    """A leading quoted path (unquoted) and what follows it, or (None, text)."""
    if not text.startswith('"'):
        return None, text
    m = _QUOTED_RX.match(text)
    if m is None:
        raise ValueError(f"unterminated quoted path in {text!r}")
    return _unquote(m.group(1)), text[m.end():]


def diff_header_paths(line: str) -> tuple[str, str]:
    """`diff --git a/<old> b/<new>` → (old, new): git's quoted form (either
    side, both) and unquoted paths with spaces included. Raises ValueError for
    a header that cannot be read — the callers fail closed on it, since a
    path the check cannot see is a path the check cannot hold to the brief."""
    if not line.startswith("diff --git "):
        raise ValueError(f"not a diff header: {line!r}")
    rest = line[len("diff --git "):]
    first, tail = _quoted_or_rest(rest)
    if first is not None:
        if not tail.startswith(" "):
            raise ValueError(f"no second path in {line!r}")
        second, after = _quoted_or_rest(tail[1:])
        if second is None:
            second, after = tail[1:], ""
    else:
        quote = rest.find(' "')
        if quote != -1:
            first = rest[:quote]
            second, after = _quoted_or_rest(rest[quote + 1:])
        else:
            splits = [i for i in range(len(rest)) if rest.startswith(" b/", i)]
            if not splits:
                raise ValueError(f"no ` b/` in {line!r}")
            pairs = [(rest[:i], rest[i + 1:]) for i in splits]
            # the same path on both sides (every edit but a rename) decides an ambiguous split
            first, second = next(((a, b) for a, b in pairs if a[2:] == b[2:]), pairs[0])
            after = ""
    if after:
        raise ValueError(f"trailing text after the paths in {line!r}")
    if not (first.startswith("a/") and second.startswith("b/")):
        raise ValueError(f"paths without their a/ and b/ prefixes in {line!r}")
    return first[2:], second[2:]


def patch_files(patch: str) -> list[str]:
    """Every path a unified diff touches, from BOTH sides of each `diff --git`
    header, in order: a rename names its source and its destination, a
    deletion its file. Raises ValueError on a header that cannot be read."""
    seen: list[str] = []
    for line in patch.splitlines():
        if not line.startswith("diff --git "):
            continue
        for path in diff_header_paths(line):
            if path != "/dev/null" and path not in seen:
                seen.append(path)
    return seen


def allowed_file(kit: str, path: str) -> bool:
    """standardize edits CLAUDE.md alone; schema edits SCHEMA.md files (any
    directory, a deletion included), never a path that leaves the clone."""
    if kit == "standardize":
        return path == "CLAUDE.md"
    if kit == "schema":
        return path.rsplit("/", 1)[-1] == "SCHEMA.md" and ".." not in path.split("/")
    return False


class FanoutAgentFill(Adapter):
    name = "fanout_agent_fill"
    sources = (".github/scripts/dash-gen/agent_fill.py", ".github/scripts/dash-gen/agent_fill_file.py",
               "tools/fanout.sh")

    def items(self, ctx, plan: dict) -> PlanResult:
        """One item per target repository at the kit's branch. The prompt is
        the whole work order, so no row carries a brief. A row is refused
        (JevError) unless it names its key, an owner/repo, the kit's own
        branch and commit subject, and a branch and dedupe state."""
        kit_ok = ctx.spec.step.removeprefix("agent-fill-")
        items = []
        for r in plan.get("include") or []:
            missing = [k for k in ROW_KEYS if not isinstance(r.get(k), str) or not r.get(k)]
            if missing or not is_nwo(r["nwo"]) or r["key"] != r["nwo"]:
                raise JevError(f"plan row {r.get('name')!r}: needs {list(ROW_KEYS)} with key == an owner/repo nwo "
                               f"(missing {missing})")
            if r.get("brief") is not None:
                raise JevError(f"plan row {r['name']!r}: the agent fill has no brief (workspace.no_brief), "
                               f"got {r['brief']!r}")
            kit = KITS.get(r["kit"])
            if kit is None or r["kit"] != kit_ok:
                raise JevError(f"plan row {r['name']!r}: kit {r['kit']!r} is not this step's ({kit_ok})")
            if r["branch"] != kit["branch"] or r["commit_subject"] != kit["subject"]:
                raise JevError(f"plan row {r['name']!r}: branch/commit_subject are not the {r['kit']} kit's")
            if r["branch_status"] not in ("present", "missing", "unknown") or r["dedupe"] not in (
                    "clear", "filled", "unavailable", "offline"):
                raise JevError(f"plan row {r['name']!r}: unknown branch_status/dedupe "
                               f"{r['branch_status']!r}/{r['dedupe']!r}")
            items.append(Item(key=r["key"], name=r["name"], nwo=r["nwo"], branch=r["branch"], row=r, brief=None))
        return PlanResult(items=items, skipped=[dict(s) for s in plan.get("skipped") or []],
                          dropped=list(plan.get("dropped") or []),
                          meta={k: plan.get(k) for k in ("kit", "branch", "target", "offline")})

    def reuse_key(self, ctx, item: Item, head_sha: str | None) -> str | None:
        if not head_sha:
            return None
        digest = hashlib.sha256()
        for part in (ctx.spec.template_sha256, head_sha, str(item.row["kit"])):
            digest.update(part.encode("utf-8") + b"\0")
        return digest.hexdigest()

    def tier0(self, ctx, item: Item, head_sha: str | None) -> Tier0:
        if head_sha == "":
            return Tier0("skip", "the repository read as empty, nothing to clone")
        return super().tier0(ctx, item, head_sha)

    def classify(self, ctx, item: Item) -> Triage:
        row = item.row
        if row["branch_status"] == "missing":
            return Triage(True, f"no {row['branch']} on {item.nwo}: the fan-out has not pushed the {row['kit']} "
                                "kit branch (run fanout.yml with dry_run=false first)")
        if row["dedupe"] == "filled":
            return Triage(True, f"{row['branch']} already carries a {AGENT_PASS_MARK} commit")
        if ctx.opts.apply and row["dedupe"] != "clear":
            return Triage(True, "the plan could not read the kit branch (dedupe unavailable or offline): --apply "
                                "needs a live dedupe")
        return Triage(False, "one tier: agent_fill.model")

    def validate(self, ctx, item: Item, harvested: dict, outcome) -> Verdict:
        """The dry run's output: the engine's patch of the clone, held to the
        kit's brief (only the files it allows), as the document the filer reads."""
        h = harvested.get(PATCH)
        if h is None:
            return Verdict(False, [f"the engine harvested no {PATCH} (the spec's local.harvest is not patch?)"])
        if h.dest is None and h.reason != "absent":
            return Verdict(False, [f"{PATCH} refused: {h.reason}"])
        patch = h.dest.read_bytes() if h.dest is not None else b""
        if not patch.strip():
            return Verdict(False, ["the agent changed nothing (an empty patch): no scaffold TODO was filled"])
        text = patch.decode("utf-8", errors="replace")
        kit = str(item.row["kit"])
        try:
            files = patch_files(text)   # both sides of every header: a rename or a deletion names its source
        except ValueError as exc:
            return Verdict(False, [f"a `diff --git` header cannot be read, so the patch cannot be held to the "
                                   f"brief — withheld: {exc}"])
        if not files:
            return Verdict(False, ["the patch has no `diff --git` header"])
        outside = [f for f in files if not allowed_file(kit, f)]
        if outside:
            return Verdict(False, [f"the {kit} brief allows no edit to {', '.join(outside)} — the whole attempt is "
                                   "withheld (CI would have pushed it)"])
        # never put this machine's paths or its name in a public repository (the shared
        # matcher: paths as substrings, the host name only as a whole token)
        if leaks_private(text, ctx):
            return Verdict(False, ["the patch carries a local path or the host name — withheld"])
        out_dir = ctx.item_dir(item) / "outputs"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / PATCH_COPY).write_bytes(patch)
        doc = {"kit": kit, "repo": item.nwo, "key": item.key, "branch": item.row["branch"],
               "commit_subject": item.row["commit_subject"], "patch": PATCH_COPY, "files": files}
        validated = out_dir / VALIDATED
        validated.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        with tempfile.TemporaryDirectory(prefix="jev-agent-fill-dry-") as tmp:
            dry = ctx.dash_gen(["agent-fill-file", "--item", str(validated), "--bodies-dir", tmp, "--offline"])
        if not dry.ok:
            return Verdict(False, [f"agent-fill-file --offline exited {dry.code}: {dry.err.strip()[-300:]}"])
        try:
            res = last_json(dry.out)
        except ValueError as exc:
            return Verdict(False, [f"agent-fill-file --offline printed no result: {exc}"])
        if res.get("rejected"):
            return Verdict(False, [f"agent-fill-file: {r.get('reason')}" for r in res["rejected"]])
        return Verdict(True, publish_file=validated,
                       facts={"kit": kit, "repo": item.nwo, "branch": item.row["branch"], "files": files,
                              "patch_bytes": len(patch)})

    def publish(self, ctx, item: Item, verdict: Verdict, execute, *, apply: bool = False) -> PublishPlan:
        res = execute()   # the spec's publish argv; with --apply only after the gate (refused by the filer today)
        if not res.ok:
            why = res.err.strip()[-300:]
            blocker = (f"agent-fill-file --apply is refused in this release (bamr87/bamr87#488): {why}"
                       if APPLY_REFUSED in res.err else f"agent-fill-file exited {res.code}: {why}")
            return PublishPlan(False, [blocker], [], None)
        try:
            out = last_json(res.out)
        except ValueError as exc:
            return PublishPlan(False, [f"agent-fill-file printed no result: {exc}"], [], None)
        blockers = ["dedupe_unavailable"] if NO_DEDUPE in res.err else []
        blockers += [f"rejected: {r.get('reason')}" for r in out.get("rejected") or []]
        rows = [{"title": f.get("title"), "kind": f.get("kind"), "repo": f.get("repo"), "branch": f.get("branch"),
                 "files": f.get("files"), "url": f.get("url"), "body_file": f.get("body_file"),
                 "patch_file": f.get("patch_file")} for f in out.get("filed") or []]
        return PublishPlan(publishable=bool(rows) and not blockers, blockers=blockers, rows=rows,
                           bodies_dir=ctx.bodies_dir(item, apply=apply),
                           failures=[s.get("title", "?") for s in out.get("skipped") or []
                                     if "failed" in str(s.get("reason") or "")])

    def context_request(self, ctx, item: Item) -> ContextRequest:
        """The target and its registry name, with the kit's own queries (the
        spec keeps the pack off: with no brief there is nothing to point from)."""
        kit = str(item.row["kit"])
        queries = tuple(q[:MAX_QUERY_CHARS] for q in QUERIES.get(kit, ()))
        return ContextRequest(item.nwo, item.name, queries)

    def recheck(self, ctx, item: Item) -> str | None:
        plan = ctx.planner(target=item.key)   # live: the branch and the agent-pass dedupe, today
        rows = [r for r in plan.get("include") or [] if r.get("key") == item.key]
        if rows and rows[0].get("branch_status") == "present" and rows[0].get("dedupe") == "clear":
            return None
        if rows:
            return f"the kit branch reads {rows[0].get('branch_status')}/{rows[0].get('dedupe')} now"
        return next((s.get("reason") for s in plan.get("skipped") or [] if s.get("key") == item.key),
                    "no longer a target")


ADAPTER = FanoutAgentFill()
