#!/usr/bin/env python3
"""
File: tools/jev/number.py
Description: ASSIGN AT MERGE. The compiler that turns the fragments a pull
             request writes — `features/features.d/<slug>.yml`,
             `changelog.d/<slug>.md`, `docs/amendments/proposed/<slug>.md` —
             into the numbered, compiled files on the default branch:
             `features/features.yml`, `CHANGELOG.md`, `docs/amendments/NNNN-*.md`
             and the PRD's requirement list. A pull request never picks the next
             sequential number; it writes `HUB-NEW` / `FR-NEW:<key>` /
             `number: NEW` and references other new things by slug. This program
             is the only thing that resolves those, it runs serialized on the
             default branch, and an id it has assigned is never reused.
Author: bamr87
Created: 2026-10-29
Version: 0.1.0
Usage:
  python3 -m tools.jev number plan   [--repo .]            what would be assigned
  python3 -m tools.jev number apply  [--repo .]            assign, compile, consume
  python3 -m tools.jev number next   [--repo .]            the next free id per series
  python3 -m tools.jev number lint   [--repo .] [--base origin/main]
                                                           reject a hand-picked number
Exit: 0 clean, 1 a problem the caller must fix, 2 usage.
Dependencies: PyYAML; `git` for `lint --base`.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .common import git

FEATURES = "features/features.yml"
FEATURES_D = "features/features.d"
CHANGELOG = "CHANGELOG.md"
CHANGELOG_D = "changelog.d"
AMENDMENTS = "docs/amendments"
AMENDMENTS_PROPOSED = "docs/amendments/proposed"
AMEND_INDEX = "docs/amendments/README.md"
PRD = "PRD.md"

#: The placeholder a pull request writes instead of a number, and the shape of
#: a reference to something else that is also unnumbered yet.
NEW = "NEW"
SLUG_REF = re.compile(r"\b(HUB|FR|NFR|AMEND)-NEW:([a-z0-9][a-z0-9-]*)\b")
FEATURE_ID = re.compile(r"\bHUB-(\d{3,})\b")
REQ_ID = re.compile(r"(?<![\w-])(N?FR)(\d+)(?![\w-])")
AMEND_FILE = re.compile(r"^(\d{4})-([a-z0-9][a-z0-9-]*)\.md$")
UNRELEASED = re.compile(r"^## \[Unreleased\]\s*$", re.M)
CHANGELOG_SECTION = re.compile(r"^### (.+?)\s*$", re.M)

#: Every `###` group Keep a Changelog defines, in the order it defines them, so
#: a compiled changelog reads the same whatever order the fragments arrived in.
KAC_ORDER = ("Added", "Changed", "Deprecated", "Removed", "Fixed", "Security")


class NumberingError(RuntimeError):
    """A fragment that cannot be compiled without a human deciding something."""


# --------------------------------------------------------------------------- #
# reading what already exists
# --------------------------------------------------------------------------- #
@dataclass
class Series:
    """One id series and where its next free number comes from."""

    prefix: str
    width: int
    highest: int = 0

    def nth(self, n: int) -> str:
        return f"{self.prefix}{n:0{self.width}d}" if self.prefix else f"{n:0{self.width}d}"

    def take(self) -> str:
        self.highest += 1
        return self.nth(self.highest)


def feature_ids(repo: Path) -> list[str]:
    f = repo / FEATURES
    if not f.is_file():
        return []
    data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    return [str(e.get("id")) for e in (data.get("features") or []) if isinstance(e, dict) and e.get("id")]


def highest_feature(repo: Path) -> int:
    """Highest HUB number ever seen — in the catalog AND in the compiled history.

    Reading the catalog alone would reuse the id of a feature that was removed,
    and an id that has ever been published is spent: the PRD, an amendment's
    `Affects:` line, an issue or a commit message may still name it.
    """
    nums = [int(m.group(1)) for fid in feature_ids(repo) for m in [FEATURE_ID.search(fid)] if m]
    for path in (repo / PRD, repo / CHANGELOG):
        if path.is_file():
            nums += [int(m.group(1)) for m in FEATURE_ID.finditer(path.read_text(encoding="utf-8"))]
    adir = repo / AMENDMENTS
    if adir.is_dir():
        for rec in adir.glob("[0-9][0-9][0-9][0-9]-*.md"):
            nums += [int(m.group(1)) for m in FEATURE_ID.finditer(rec.read_text(encoding="utf-8"))]
    return max(nums or [0])


def highest_requirements(repo: Path) -> tuple[int, int]:
    """(highest FR, highest NFR) over the PRD — generated block excluded.

    The generated Feature catalog block repeats every requirement id, so
    counting it is harmless; stripping it keeps the number derived from the
    requirement LIST, which is the thing that is actually authoritative.
    """
    prd = repo / PRD
    if not prd.is_file():
        return 0, 0
    text = prd.read_text(encoding="utf-8")
    start, end = text.find("<!-- features:start"), text.find("<!-- features:end -->")
    if 0 <= start < end:
        text = text[:start] + text[end:]
    fr = nfr = 0
    for m in REQ_ID.finditer(text):
        if m.group(1) == "FR":
            fr = max(fr, int(m.group(2)))
        else:
            nfr = max(nfr, int(m.group(2)))
    return fr, nfr


def highest_amendment(repo: Path) -> int:
    adir = repo / AMENDMENTS
    if not adir.is_dir():
        return 0
    return max([int(m.group(1)) for p in adir.glob("*.md")
                for m in [AMEND_FILE.match(p.name)] if m] or [0])


def next_ids(repo: Path) -> dict[str, str]:
    fr, nfr = highest_requirements(repo)
    return {
        "HUB": f"HUB-{highest_feature(repo) + 1:03d}",
        "FR": f"FR{fr + 1}",
        "NFR": f"NFR{nfr + 1}",
        "amendment": f"{highest_amendment(repo) + 1:04d}",
    }


# --------------------------------------------------------------------------- #
# fragments
# --------------------------------------------------------------------------- #
@dataclass
class Plan:
    """What one compile pass would assign and change. The dry run prints this."""

    assignments: dict[str, str] = field(default_factory=dict)   # slug ref -> id
    features: list[str] = field(default_factory=list)           # fragment paths
    amendments: list[str] = field(default_factory=list)
    changelog: list[str] = field(default_factory=list)
    requirements: list[tuple[str, str, str]] = field(default_factory=list)  # (id, kind, text)
    errors: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.features or self.amendments or self.changelog)

    def to_json(self) -> str:
        return json.dumps({
            "assignments": self.assignments,
            "features": self.features,
            "amendments": self.amendments,
            "changelog": self.changelog,
            "requirements": [{"id": i, "kind": k, "text": t} for i, k, t in self.requirements],
            "errors": self.errors,
        }, indent=2)


def _fragments(repo: Path, rel: str, suffix: str) -> list[Path]:
    d = repo / rel
    if not d.is_dir():
        return []
    return sorted(p for p in d.glob(f"*{suffix}")
                  if p.name not in ("README.md", "SCHEMA.md") and not p.name.startswith("."))


def rewrite_refs(text: str, assignments: dict[str, str]) -> str:
    """Turn every `KIND-NEW:<slug>` into the id that slug was assigned.

    An unresolved reference is left verbatim rather than blanked: the compile
    reports it as an error and the text still says which slug was meant, so
    the fix is obvious in the diff instead of being a hole.
    """
    return SLUG_REF.sub(lambda m: assignments.get(m.group(0), m.group(0)), text)


def unresolved_refs(text: str) -> list[str]:
    return sorted({m.group(0) for m in SLUG_REF.finditer(text)})


def unresolved_error(rel: str, left: list[str]) -> str:
    """The error for a fragment whose slug references this run cannot resolve.

    A slug resolves only against the fragments compiled in the SAME run: the
    compiled entry keeps no slug. A reference to a key an earlier run already
    numbered (FR-NEW:central-loop-switches after it became FR54, 45ede64) can
    never resolve, so the message says to write the assigned id instead.
    """
    return (f"{rel}: unresolved reference(s) {', '.join(left)} — no pending fragment defines that key; it may "
            f"already have been compiled in an earlier run, so reference its assigned id instead (look it up in "
            f"{FEATURES} or {PRD})")


def plan(repo: Path) -> Plan:
    """Read every fragment and decide which id each new thing gets.

    Assignment order is the fragments' sorted filename order, so two runs over
    the same tree assign the same numbers — the property that makes a failed
    compile safe to re-run.
    """
    p = Plan()
    hub = Series("HUB-", 3, highest_feature(repo))
    fr_n, nfr_n = highest_requirements(repo)
    fr, nfr = Series("FR", 1, fr_n), Series("NFR", 1, nfr_n)
    amend = Series("", 4, highest_amendment(repo))

    for frag in _fragments(repo, FEATURES_D, ".yml"):
        try:
            entry = yaml.safe_load(frag.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            p.errors.append(f"{frag.name}: YAML parse error: {str(exc).splitlines()[0]}")
            continue
        if not isinstance(entry, dict):
            p.errors.append(f"{frag.name}: a feature fragment is ONE mapping (one entry per file)")
            continue
        slug = str(entry.get("slug") or frag.stem)
        if str(entry.get("id") or "") not in (f"HUB-{NEW}", ""):
            p.errors.append(f"{frag.name}: a fragment carries `id: HUB-NEW`, never a number "
                            f"({entry.get('id')}) — numbers are assigned here")
            continue
        p.assignments[f"HUB-{NEW}:{slug}"] = hub.take()
        for req in (entry.get("prd_new") or []):
            kind = str((req or {}).get("kind") or "FR").upper()
            key = str((req or {}).get("key") or slug)
            text = str((req or {}).get("text") or "").strip()
            if not text:
                p.errors.append(f"{frag.name}: prd_new entry {key!r} has no `text:`")
                continue
            new_id = (fr if kind == "FR" else nfr).take()
            p.assignments[f"{kind}-{NEW}:{key}"] = new_id
            p.requirements.append((new_id, kind, text))
        p.features.append(frag.relative_to(repo).as_posix())

    for frag in _fragments(repo, AMENDMENTS_PROPOSED, ".md"):
        p.assignments[f"AMEND-{NEW}:{frag.stem}"] = amend.take()
        p.amendments.append(frag.relative_to(repo).as_posix())

    p.changelog = [f.relative_to(repo).as_posix() for f in _fragments(repo, CHANGELOG_D, ".md")]

    # A reference nothing in this run defines fails the plan, so `number plan`
    # (and the PR-side dry run) reports it before `apply` consumes anything.
    for rel in p.features + p.amendments:
        left = unresolved_refs(rewrite_refs((repo / rel).read_text(encoding="utf-8"), p.assignments))
        if left:
            p.errors.append(unresolved_error(rel, left))
    return p


# --------------------------------------------------------------------------- #
# compiling
# --------------------------------------------------------------------------- #
def _append_feature(repo: Path, entry: dict) -> None:
    """Append one compiled entry to features.yml as TEXT.

    A YAML round-trip would reformat the whole catalog and delete its comment
    header, which is most of what the file is for. The catalog is append-ordered
    anyway, so appending the rendered block is both the smaller diff and the
    one a human can review.
    """
    path = repo / FEATURES
    body = yaml.safe_dump([entry], sort_keys=False, width=100, allow_unicode=True,
                          default_flow_style=False)
    block = "\n".join(("  " + line) if line.strip() else line for line in body.splitlines())
    text = path.read_text(encoding="utf-8").rstrip("\n")
    path.write_text(f"{text}\n{block}\n", encoding="utf-8")


def _insert_requirement(repo: Path, req_id: str, kind: str, text: str) -> None:
    """Append a requirement bullet to the PRD's Functional / Non-functional list.

    Appended at the END of its list, never inserted: the list is read as a
    history as much as a specification, and renumbering is exactly what this
    whole scheme exists to avoid.
    """
    prd = repo / PRD
    lines = prd.read_text(encoding="utf-8").split("\n")
    heading = "**Functional**" if kind == "FR" else "**Non-functional**"
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == heading)
    except StopIteration as exc:
        raise NumberingError(f"{PRD}: no `{heading}` list to append {req_id} to") from exc
    end = start + 1
    last = start
    while end < len(lines):
        stripped = lines[end].strip()
        if stripped.startswith(("- ", "* ")):
            last = end
        elif stripped.startswith(("**", "## ")):
            break
        end += 1
    lines.insert(last + 1, f"- {req_id}: {text}")
    prd.write_text("\n".join(lines), encoding="utf-8")


def _merge_changelog(repo: Path, fragments: list[Path]) -> None:
    """Fold every changelog fragment into the one `## [Unreleased]` section.

    Fragments are grouped by their Keep a Changelog heading and emitted in the
    specification's order, so two pull requests that both added an `### Added`
    bullet produce one section with two bullets — the shape a hand-merge would
    have produced, without the hand-merge.
    """
    path = repo / CHANGELOG
    text = path.read_text(encoding="utf-8")
    match = UNRELEASED.search(text)
    if not match:
        raise NumberingError(f"{CHANGELOG}: no `## [Unreleased]` heading to compile into")
    nxt = re.search(r"^## ", text[match.end():], re.M)
    head, tail = text[:match.end()], text[match.end():]
    section, rest = (tail[:nxt.start()], tail[nxt.start():]) if nxt else (tail, "")

    groups: dict[str, list[str]] = {}
    for name, body in _changelog_groups(section):
        groups.setdefault(name, []).extend(body)
    for frag in fragments:
        for name, body in _changelog_groups(frag.read_text(encoding="utf-8")):
            groups.setdefault(name, []).extend(body)

    ordered = [g for g in KAC_ORDER if g in groups] + [g for g in groups if g not in KAC_ORDER]
    out = [""]
    for name in ordered:
        bullets = [b for b in dict.fromkeys(groups[name]) if b.strip()]
        if not bullets:
            continue
        out += [f"### {name}", "", *bullets, ""]
    path.write_text(head + "\n".join(out).rstrip("\n") + "\n\n" + rest.lstrip("\n"), encoding="utf-8")


def _changelog_groups(text: str) -> list[tuple[str, list[str]]]:
    """[(heading, [bullet, …]), …] for one changelog section or fragment."""
    out: list[tuple[str, list[str]]] = []
    current: str | None = None
    bullets: list[str] = []
    for line in text.split("\n"):
        m = CHANGELOG_SECTION.match(line)
        if m:
            if current:
                out.append((current, bullets))
            current, bullets = m.group(1).strip(), []
        elif current and line.strip().startswith("- "):
            bullets.append(line.rstrip())
    if current:
        out.append((current, bullets))
    return out


def _amend_index_row(repo: Path, number: str, slug: str, title: str, status: str, affects: str) -> None:
    """Append the record's row to the amendment index table.

    The table is append-only and its order carries no meaning beyond the number
    already in column one, which is why `.gitattributes` may safely give this
    file `merge=union`.
    """
    path = repo / AMEND_INDEX
    if not path.is_file():
        return
    row = f"| [{number}]({number}-{slug}.md) | {title} | {status} | {affects} |"
    text = path.read_text(encoding="utf-8").rstrip("\n")
    if row in text:
        return
    path.write_text(f"{text}\n{row}\n", encoding="utf-8")


def _amend_field(text: str, name: str) -> str:
    m = re.search(rf"^\s*[-*]?\s*\*\*{re.escape(name)}:?\*\*:?\s*(.+?)\s*$", text, re.M | re.I)
    return m.group(1) if m else ""


def apply(repo: Path, *, write: bool = True) -> Plan:
    """Assign, compile, and CONSUME the fragments. Idempotent on an empty tree.

    Consuming (deleting) a fragment is what makes the scheme safe to run on
    every push: a compiled fragment leaves no second copy to compile again,
    and the compiled file is the only place the entry lives afterwards.
    """
    p = plan(repo)
    if p.errors or not write:
        return p

    for rel in p.features:
        frag = repo / rel
        entry = yaml.safe_load(rewrite_refs(frag.read_text(encoding="utf-8"), p.assignments)) or {}
        slug = str(entry.pop("slug", None) or frag.stem)
        entry["id"] = p.assignments[f"HUB-{NEW}:{slug}"]
        entry.pop("prd_new", None)
        ordered = {"id": entry.pop("id")}
        ordered.update(entry)
        left = unresolved_refs(yaml.safe_dump(ordered))
        if left:
            p.errors.append(unresolved_error(rel, left))
            continue
        _append_feature(repo, ordered)
        frag.unlink()

    for req_id, kind, text in p.requirements:
        _insert_requirement(repo, req_id, kind, rewrite_refs(text, p.assignments))

    for rel in p.amendments:
        frag = repo / rel
        number = p.assignments[f"AMEND-{NEW}:{frag.stem}"]
        body = rewrite_refs(frag.read_text(encoding="utf-8"), p.assignments)
        body = re.sub(rf"^#\s+{NEW}\b", f"# {number}", body, count=1, flags=re.M)
        body = re.sub(rf"^(\s*[-*]?\s*\*\*Number:?\*\*:?\s*){NEW}\s*$", rf"\g<1>{number}",
                      body, count=1, flags=re.M)
        left = unresolved_refs(body)
        if left:
            p.errors.append(unresolved_error(rel, left))
            continue
        (repo / AMENDMENTS / f"{number}-{frag.stem}.md").write_text(body, encoding="utf-8")
        title = (re.search(r"^#\s+\S+\s+—\s+(.+)$", body, re.M) or re.search(r"^#\s+(.+)$", body, re.M))
        _amend_index_row(repo, number, frag.stem,
                         (title.group(1).strip() if title else frag.stem),
                         _amend_field(body, "Status") or "proposed",
                         _amend_field(body, "Affects") or "none")
        frag.unlink()

    if p.changelog:
        _merge_changelog(repo, [repo / rel for rel in p.changelog])
        for rel in p.changelog:
            (repo / rel).unlink()
    return p


# --------------------------------------------------------------------------- #
# the lint: a pull request must not pick a number
# --------------------------------------------------------------------------- #
def lint_diff(diff: str) -> list[str]:
    """Problems in a unified diff: a newly hand-written sequential id.

    Only ADDED lines are read, and only in the compiled files — a fragment is
    allowed to mention an existing id (that is how it references one), and a
    doc that quotes `HUB-001` is not assigning anything. The signal this looks
    for is narrow on purpose: a new `id: HUB-NNN` row in the catalog, a new
    `FRn:` / `NFRn:` requirement bullet in the PRD, or a new numbered amendment
    file. Those are exactly the three races the scheme removes. A numbered
    amendment counts only when it is ADDED (its `--- ` side is /dev/null): a
    ratification-record PR modifies a numbered record's Status line, which
    assigns nothing (tools/jev/ratify.py).
    """
    problems: list[str] = []
    current = ""
    old_side = ""
    for line in diff.split("\n"):
        if line.startswith("--- "):
            old_side = line[4:].strip()
            continue
        if line.startswith("+++ b/"):
            current = line[6:].strip()
            added, old_side = old_side == "/dev/null", ""
            if added and AMEND_FILE.match(current.rsplit("/", 1)[-1]) and current.startswith(AMENDMENTS):
                problems.append(f"{current}: a new amendment is proposed as "
                                f"{AMENDMENTS_PROPOSED}/<slug>.md; the number is assigned at merge")
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        body = line[1:]
        if current == FEATURES and re.match(r"\s*-?\s*id:\s*HUB-\d+\s*$", body):
            problems.append(f"{FEATURES}: `{body.strip()}` — a new feature is a "
                            f"{FEATURES_D}/<slug>.yml fragment with `id: HUB-NEW`")
        if current == PRD and re.match(r"\s*[-*]\s+N?FR\d+:", body):
            problems.append(f"{PRD}: `{body.strip()[:60]}` — a new requirement is declared in the "
                            f"feature fragment's `prd_new:` and numbered at merge")
    return problems


def lint(repo: Path, base: str = "origin/main") -> list[str]:
    res = git(["diff", "--unified=0", f"{base}...HEAD"], cwd=repo)
    if not res.ok:
        return [f"could not diff against {base}: {res.err.strip() or 'unknown error'}"]
    return lint_diff(res.out)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def add_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("action", choices=("plan", "apply", "next", "lint"))
    ap.add_argument("--repo", default=".", help="repository root (default: .)")
    ap.add_argument("--base", default="origin/main", help="lint: the base ref to diff against")
    ap.add_argument("--json", action="store_true")


def main(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    if args.action == "next":
        ids = next_ids(repo)
        print(json.dumps(ids, indent=2) if args.json
              else "\n".join(f"{k}: {v}" for k, v in ids.items()))
        return 0
    if args.action == "lint":
        problems = lint(repo, args.base)
        if args.json:
            print(json.dumps(problems, indent=2))
        else:
            for pr in problems:
                print(f"  error: {pr}")
            print("numbering lint: clean" if not problems else
                  f"numbering lint: {len(problems)} hand-picked number(s)")
        return 1 if problems else 0

    p = apply(repo, write=args.action == "apply")
    if args.json:
        print(p.to_json())
    else:
        if p.empty:
            print("no pending fragments")
        for ref, assigned in p.assignments.items():
            print(f"  {ref} -> {assigned}")
        for req_id, kind, text in p.requirements:
            print(f"  {kind} {req_id}: {text[:70]}")
        for err in p.errors:
            print(f"  error: {err}", file=sys.stderr)
        if args.action == "apply" and not p.empty and not p.errors:
            print(f"compiled {len(p.features)} feature(s), {len(p.amendments)} amendment(s), "
                  f"{len(p.changelog)} changelog fragment(s)")
    return 1 if p.errors else 0
