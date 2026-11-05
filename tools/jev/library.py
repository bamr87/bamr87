#!/usr/bin/env python3
"""
File: tools/jev/library.py
Description: JEV capability three, part two — the EXPERIENCE LIBRARY, the
             hub's "improvement harness" (Harness²'s harnessing-level
             recursion): what earlier refinements in a domain adopted and
             the one evidence-supported lesson each one left. One entry per
             (loop, domain, item, run): `experience.yml` with the cue (the
             shape of situation the lesson fires on), the lesson (an
             operation on a harness, naming its component), the evidence
             (the edit rows and the execution contrast it rests on), a
             confidence, and the per-edit verdicts — plus the adopted edits
             as `harness.diff`. Entries are committed data under
             `_data/harness_library/<loop>/<domain>/<entry>/`, written only
             on a branch (the human-gated inbox the production harnesses
             converged on: Gemini CLI's /memory inbox, Codex's git-baselined
             memories — Barbaste et al. 2026 § 9), and read back by the loop
             runner's context pack (`library` provider) and the refinement
             evidence tree, so the next task in the domain starts from what
             the last one learned. Nothing here calls a model.
Author: bamr87
Created: 2026-11-04
Version: 0.1.0
Usage: python3 -m tools.jev refine library list|show|add|check|index …
Dependencies: Python 3.12 stdlib + PyYAML; tools/jev/context.py (redaction),
              tools/jev/headless.py (SECRET_RE). No dash-gen import.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import headless
from .common import HUB, REGISTRY_YML, JevError, is_nwo

SCHEMA_ID = "jev-experience/v1"
ENTRY_FILE = "experience.yml"
DIFF_FILE = "harness.diff"
CONFIDENCES = ("high", "medium", "low")
VERDICTS = ("helped", "hurt", "no observed effect", "confounded")
SOURCES = ("human", "reflector")
DEFAULT_DIR = "_data/harness_library"
DOMAIN_RX = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
LOOP_RX = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
ENTRY_ID_RX = re.compile(r"\d{8}-[A-Za-z0-9._-]{1,48}-[0-9a-f]{8}")
#: per-field size caps: a lesson is an operation, not an essay
FIELD_MAX = {"cue": 400, "lesson": 800, "evidence": 1200, "item": 200, "adopted": 64, "run_id": 128}
EDIT_FIELD_MAX = 600
MAX_EDITS = 24
MAX_DIFF_BYTES = 256 * 1024
UNKNOWN_DOMAIN = "unknown"


class LibraryError(JevError):
    """An entry that cannot be written or read as what it claims to be."""


def root(fleet: Mapping | None = None) -> Path:
    """`JEV_LIBRARY_DIR`, else `_data/fleet.yml` `harness_refinement.library_dir`
    (hub-relative), else `_data/harness_library` in the hub."""
    env = os.environ.get("JEV_LIBRARY_DIR")
    if env:
        return Path(env).expanduser()
    cfg = (fleet or {}).get("harness_refinement") if isinstance(fleet, Mapping) else None
    rel = cfg.get("library_dir") if isinstance(cfg, Mapping) else None
    if rel is not None and (not isinstance(rel, str) or not rel or rel.startswith("/") or ".." in Path(rel).parts):
        raise LibraryError(f"_data/fleet.yml harness_refinement.library_dir {rel!r} is not a hub-relative path")
    return HUB / (rel or DEFAULT_DIR)


def domain_dir(domain: str) -> str:
    """One directory name for a domain, never a path."""
    d = re.sub(r"\s*[/\\]\s*", "__", str(domain or "")).strip().lower()
    return d if DOMAIN_RX.fullmatch(d) else UNKNOWN_DOMAIN


def domain_of(nwo: str, registry: Path | str = REGISTRY_YML) -> str:
    """The registry category of a repository (the grouping unit a lesson
    transfers within, as a brief's category emphasis already is), or
    `unknown` for a repository the registry does not list."""
    if not is_nwo(nwo):
        return UNKNOWN_DOMAIN
    try:
        data = yaml.safe_load(Path(registry).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return UNKNOWN_DOMAIN
    projects = data.get("projects") if isinstance(data, dict) else data
    if not isinstance(projects, list):
        return UNKNOWN_DOMAIN
    want = nwo.lower()
    repo = want.split("/", 1)[1]
    by_name = None
    for p in projects:
        if not isinstance(p, dict):
            continue
        url = str(p.get("repo_url") or "").lower().rstrip("/").removesuffix(".git")
        if url.endswith("/" + want):
            return domain_dir(str(p.get("category") or UNKNOWN_DOMAIN))
        if by_name is None and str(p.get("name") or "").lower() == repo:
            by_name = domain_dir(str(p.get("category") or UNKNOWN_DOMAIN))
    return by_name or UNKNOWN_DOMAIN


def _slug(text: str, limit: int = 40) -> str:
    return (re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._-")[:limit] or "item")


def _sha8(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8", errors="replace"))
        h.update(b"\0")
    return h.hexdigest()[:8]


@dataclass
class Edit:
    """What one harness edit did, as the reflector records it (one row per
    changed component; `confounded` is the honest verdict when several
    components changed at once or one rollout is all that stands behind it)."""

    component: str
    candidates: list[str]
    change: str
    observed: str
    verdict: str

    def to_dict(self) -> dict:
        return {"component": self.component, "candidates": list(self.candidates), "change": self.change,
                "observed": self.observed, "verdict": self.verdict}

    @classmethod
    def from_dict(cls, d: Mapping) -> Edit:
        cands = d.get("candidates")
        return cls(component=str(d.get("component") or ""),
                   candidates=[str(c) for c in cands] if isinstance(cands, list) else [],
                   change=str(d.get("change") or ""), observed=str(d.get("observed") or ""),
                   verdict=str(d.get("verdict") or ""))

    def problems(self, at: str) -> list[str]:
        out = []
        for name in ("component", "change", "observed"):
            v = getattr(self, name)
            if not v.strip():
                out.append(f"{at}.{name}: empty")
            elif len(v) > EDIT_FIELD_MAX:
                out.append(f"{at}.{name}: over {EDIT_FIELD_MAX} characters")
        if not self.candidates or not all(c.strip() for c in self.candidates):
            out.append(f"{at}.candidates: a non-empty list of labels")
        if self.verdict not in VERDICTS:
            out.append(f"{at}.verdict: one of {', '.join(VERDICTS)}, not {self.verdict!r}")
        return out


@dataclass
class Entry:
    """One adopted harness and the lesson it left."""

    loop: str
    step: str
    domain: str
    item: str
    run_id: str
    adopted: str
    date: str
    source: str
    cue: str
    lesson: str
    evidence: str
    confidence: str
    edits: list[Edit] = field(default_factory=list)
    components: dict = field(default_factory=dict)
    notes: str = ""

    @property
    def id(self) -> str:
        day = self.date.replace("-", "")[:8]
        return f"{day}-{_slug(self.item)}-{_sha8(self.loop, self.domain, self.item, self.run_id, self.adopted, self.cue)}"

    def to_dict(self) -> dict:
        out = {"schema": SCHEMA_ID, "id": self.id, "loop": self.loop, "step": self.step, "domain": self.domain,
               "item": self.item, "run_id": self.run_id, "adopted": self.adopted, "date": self.date,
               "source": self.source, "cue": self.cue, "lesson": self.lesson, "evidence": self.evidence,
               "confidence": self.confidence, "edits": [e.to_dict() for e in self.edits],
               "components": dict(self.components)}
        if self.notes:
            out["notes"] = self.notes
        return out

    @classmethod
    def from_dict(cls, d: Mapping) -> Entry:
        if not isinstance(d, Mapping):
            raise LibraryError("an entry is a mapping")
        if d.get("schema") != SCHEMA_ID:
            raise LibraryError(f"schema must be {SCHEMA_ID!r}, not {d.get('schema')!r}")
        edits = d.get("edits") or []
        if not isinstance(edits, list):
            raise LibraryError("edits must be a list")
        comps = d.get("components") or {}
        return cls(loop=str(d.get("loop") or ""), step=str(d.get("step") or ""), domain=str(d.get("domain") or ""),
                   item=str(d.get("item") or ""), run_id=str(d.get("run_id") or ""),
                   adopted=str(d.get("adopted") or ""), date=str(d.get("date") or ""),
                   source=str(d.get("source") or ""), cue=str(d.get("cue") or ""),
                   lesson=str(d.get("lesson") or ""), evidence=str(d.get("evidence") or ""),
                   confidence=str(d.get("confidence") or ""),
                   edits=[Edit.from_dict(e) if isinstance(e, Mapping) else Edit("", [], "", "", "") for e in edits],
                   components=dict(comps) if isinstance(comps, Mapping) else {},
                   notes=str(d.get("notes") or ""))

    def problems(self) -> list[str]:
        out: list[str] = []
        if not LOOP_RX.fullmatch(self.loop):
            out.append(f"loop {self.loop!r} is not a workflow stem")
        if not LOOP_RX.fullmatch(self.step):
            out.append(f"step {self.step!r} is not a step name")
        if domain_dir(self.domain) != self.domain:
            out.append(f"domain {self.domain!r} is not a directory name (use {domain_dir(self.domain)!r})")
        for name, cap in FIELD_MAX.items():
            v = getattr(self, name)
            if not str(v).strip():
                out.append(f"{name}: empty")
            elif len(str(v)) > cap:
                out.append(f"{name}: over {cap} characters")
        try:
            dt.date.fromisoformat(self.date)
        except ValueError:
            out.append(f"date {self.date!r} is not YYYY-MM-DD")
        if self.source not in SOURCES:
            out.append(f"source: one of {', '.join(SOURCES)}, not {self.source!r}")
        if self.confidence not in CONFIDENCES:
            out.append(f"confidence: one of {', '.join(CONFIDENCES)}, not {self.confidence!r}")
        if "\n" in self.cue:
            out.append("cue: one line (it is the index line)")
        if len(self.edits) > MAX_EDITS:
            out.append(f"edits: more than {MAX_EDITS}")
        for i, e in enumerate(self.edits):
            out.extend(e.problems(f"edits[{i}]"))
        if self.confidence == "high" and self.edits and all(e.verdict == "confounded" for e in self.edits):
            out.append("confidence high rests only on confounded edit rows — narrow it, or lower the confidence")
        return out


# --------------------------------------------------------------------------- #
# leaks: nothing private reaches a committed entry
# --------------------------------------------------------------------------- #
def leak_problems(text: str, ctx) -> list[str]:
    """Why `text` may not be committed: a credential shape, or anything the
    context pack's redaction would rewrite (this machine's home, work root,
    host name, a temp path, an address). `ctx` carries home / work_root /
    hostname (loop.host_ctx()); None checks the credential shapes only."""
    from . import context as cpack  # lazy: context imports workspace and headless
    out: list[str] = []
    if headless.SECRET_RE.search(text or ""):
        out.append("a credential shape")
    if ctx is not None and cpack.redact(text or "", ctx) != (text or ""):
        out.append("a private path, host name, temp path or address (the context pack's redaction would rewrite it)")
    return out


def _dump(entry: Entry) -> str:
    return yaml.safe_dump(entry.to_dict(), sort_keys=False, allow_unicode=True, width=100)


# --------------------------------------------------------------------------- #
# the library of one (loop, domain)
# --------------------------------------------------------------------------- #
@dataclass
class Library:
    """One (loop, domain) library: read before a refinement, appended by one."""

    root: Path
    loop: str
    domain: str

    @property
    def dir(self) -> Path:
        return Path(self.root) / self.loop / domain_dir(self.domain)

    def entry_dir(self, entry_id: str) -> Path:
        if not ENTRY_ID_RX.fullmatch(entry_id or ""):
            raise LibraryError(f"{entry_id!r} is not an entry id")
        return self.dir / entry_id

    def ids(self) -> list[str]:
        d = self.dir
        if d.is_symlink() or not d.is_dir():
            return []
        return sorted((p.name for p in d.iterdir() if p.is_dir() and not p.is_symlink()
                       and ENTRY_ID_RX.fullmatch(p.name) and (p / ENTRY_FILE).is_file()), reverse=True)

    def load(self, entry_id: str) -> Entry:
        p = self.entry_dir(entry_id) / ENTRY_FILE
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise LibraryError(f"{p}: {exc}") from exc
        entry = Entry.from_dict(data)
        if entry.id != entry_id:
            raise LibraryError(f"{p}: the entry's id {entry.id} is not its directory {entry_id}")
        return entry

    def entries(self) -> list[Entry]:
        """Newest first; an unreadable entry raises (the library is reviewed data)."""
        return [self.load(i) for i in self.ids()]

    def diff_of(self, entry_id: str) -> str | None:
        p = self.entry_dir(entry_id) / DIFF_FILE
        return p.read_text(encoding="utf-8", errors="replace") if p.is_file() and not p.is_symlink() else None

    def add(self, entry: Entry, *, diff: str | None = None, ctx=None) -> Path:
        """Write one entry (refused when it exists, is malformed, or carries
        anything private); returns its directory. The diff is the adopted
        edits against the base harness, as `harness.diff`."""
        if entry.loop != self.loop or domain_dir(entry.domain) != domain_dir(self.domain):
            raise LibraryError(f"entry is for {entry.loop}/{entry.domain}, this library is {self.loop}/{self.domain}")
        problems = entry.problems()
        if problems:
            raise LibraryError("entry refused: " + "; ".join(problems))
        text = _dump(entry)
        leaks = leak_problems(text, ctx)
        if diff is not None:
            if len(diff.encode("utf-8")) > MAX_DIFF_BYTES:
                raise LibraryError(f"harness.diff is over {MAX_DIFF_BYTES} bytes")
            leaks += [f"harness.diff: {p}" for p in leak_problems(diff, ctx)]
        if leaks:
            raise LibraryError("entry refused, it carries " + "; ".join(leaks))
        d = self.entry_dir(entry.id)
        d.parent.mkdir(parents=True, exist_ok=True)
        try:
            d.mkdir()
        except FileExistsError as exc:
            raise LibraryError(f"{d} already exists") from exc
        (d / ENTRY_FILE).write_text(text, encoding="utf-8")
        if diff is not None:
            (d / DIFF_FILE).write_text(diff if diff.endswith("\n") else diff + "\n", encoding="utf-8")
        return d

    def forget(self, entry_id: str) -> bool:
        d = self.entry_dir(entry_id)
        if not d.is_dir():
            return False
        for p in sorted(d.iterdir()):
            p.unlink()
        d.rmdir()
        return True

    def index_md(self) -> str:
        """The INDEX.md a proposer browses first: one line per entry, the cue
        leading, then where the full record and the adopted diff are."""
        rows = [f"# Library — {self.loop} / {self.domain}", "",
                "Each entry is an earlier refinement in THIS domain: the harness that was adopted (its edits as "
                "`harness.diff`), why, and the one lesson that transfers. Browse this index, then open the "
                "entries whose cue matches the situation in front of you. A lesson is a hypothesis here, not a "
                "fact: re-verify it against the rollouts you have.", ""]
        entries = self.entries()
        if not entries:
            rows.append("_(empty — this is the first refinement in this domain)_")
        for e in entries:
            rows += [f"## `{e.id}/`", f"- cue: {e.cue}", f"- lesson: {e.lesson.splitlines()[0] if e.lesson else ''}",
                     f"- confidence: {e.confidence} · adopted `{e.adopted}` on {e.date} ({e.item}, {e.source})",
                     f"- record: `{e.id}/{ENTRY_FILE}`" + (f" · edits: `{e.id}/{DIFF_FILE}`"
                                                           if (self.entry_dir(e.id) / DIFF_FILE).is_file() else ""),
                     ""]
        return "\n".join(rows).rstrip("\n") + "\n"


def all_entries(lib_root: Path | str) -> list[tuple[str, str, Entry]]:
    """Every (loop, domain, entry) under a library root, newest first per library."""
    out: list[tuple[str, str, Entry]] = []
    base = Path(lib_root)
    if not base.is_dir():
        return out
    for loop_dir in sorted(p for p in base.iterdir() if p.is_dir() and not p.is_symlink()):
        for dom_dir in sorted(p for p in loop_dir.iterdir() if p.is_dir() and not p.is_symlink()):
            lib = Library(base, loop_dir.name, dom_dir.name)
            out.extend((loop_dir.name, dom_dir.name, e) for e in lib.entries())
    return out


def check_all(lib_root: Path | str, ctx=None) -> list[str]:
    """Every problem under a library root: a stray file, an entry whose id,
    loop or domain disagrees with its directory, a malformed record, a leak."""
    problems: list[str] = []
    base = Path(lib_root)
    if not base.is_dir():
        return problems
    skip = {"README.md", "SCHEMA.md", ".gitkeep"}
    for loop_dir in sorted(base.iterdir()):
        if loop_dir.name in skip:
            continue
        if not loop_dir.is_dir() or loop_dir.is_symlink() or not LOOP_RX.fullmatch(loop_dir.name):
            problems.append(f"{loop_dir.relative_to(base)}: not a loop directory")
            continue
        for dom_dir in sorted(loop_dir.iterdir()):
            if not dom_dir.is_dir() or dom_dir.is_symlink() or domain_dir(dom_dir.name) != dom_dir.name:
                problems.append(f"{dom_dir.relative_to(base)}: not a domain directory")
                continue
            lib = Library(base, loop_dir.name, dom_dir.name)
            for ent in sorted(dom_dir.iterdir()):
                rel = ent.relative_to(base)
                if not ent.is_dir() or ent.is_symlink() or not ENTRY_ID_RX.fullmatch(ent.name):
                    problems.append(f"{rel}: not an entry directory")
                    continue
                extra = sorted(p.name for p in ent.iterdir() if p.name not in (ENTRY_FILE, DIFF_FILE))
                if extra:
                    problems.append(f"{rel}: stray file(s) {extra}")
                # leaks first: they matter whatever the record says of itself
                for fname in (ENTRY_FILE, DIFF_FILE):
                    f = ent / fname
                    if f.is_file() and not f.is_symlink():
                        problems.extend(f"{rel}/{fname}: carries {p}"
                                        for p in leak_problems(f.read_text(encoding="utf-8", errors="replace"), ctx))
                    elif f.is_symlink():
                        problems.append(f"{rel}/{fname}: a symlink")
                try:
                    e = lib.load(ent.name)
                except LibraryError as exc:
                    problems.append(f"{rel}: {exc}")
                    continue
                if e.loop != loop_dir.name or domain_dir(e.domain) != dom_dir.name:
                    problems.append(f"{rel}: the entry says {e.loop}/{e.domain}, the directory {loop_dir.name}/"
                                    f"{dom_dir.name}")
                problems.extend(f"{rel}: {p}" for p in e.problems())
    return problems
