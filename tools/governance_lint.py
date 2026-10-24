#!/usr/bin/env python3
"""
File: tools/governance_lint.py
Description: The fleet GOVERNANCE check: validate, and keep in sync, the chain
             an agent follows before it changes a repo —

               docs/constitution.md   the rules every change must satisfy
               docs/amendments/       numbered records of how those rules changed
               PRD.md                 what the product must do (requirement ids)
               features/features.yml  what it does today (feature ids, schema features/v1)

             Links run both ways: each feature names the PRD requirements it
             serves (`prd: [FR1]`), and the PRD carries a generated
             "Feature catalog" block listing every feature id with a link to the
             catalog, plus a requirement → feature trace. Amendment records name
             the PRD requirements / feature ids they affect.

             Kit: templates/governance/ · spec: specs/WORK.md UPS-WORK-15, UPS-WORK-16
             · doc: templates/governance/README.md
Author: bamr87
Created: 2026-10-21
Version: 0.1.0
Usage:
  python3 tools/governance_lint.py check <repo> [--json] [--werror]
  python3 tools/governance_lint.py prd-sync <repo> [--write]   regenerate the PRD feature block
  python3 tools/governance_lint.py prd-ids <repo> [--write]    tag untagged PRD requirement bullets FRn / NFRn
  python3 tools/governance_lint.py fleet [--json]              check every checked-out projects/* submodule
Exit: 0 clean (warnings allowed unless --werror), 1 errors, 2 usage.
Dependencies: PyYAML only (no network).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import yaml

HUB = Path(__file__).resolve().parent.parent
VERSION = "0.1.0"
FEATURE_FILES = ("features/features.yml", "_data/features.yml")
PRD_FILES = ("PRD.md", "docs/PRD.md")
CONSTITUTION_FILES = ("docs/constitution.md", "CONSTITUTION.md")
AMEND_DIRS = ("docs/amendments", "amendments")
STATUSES = ("shipped", "partial", "planned", "deprecated", "tbd")
AMEND_STATUSES = ("proposed", "ratified", "rejected", "superseded", "withdrawn")
BLOCK_START = "<!-- features:start v1"
BLOCK_END = "<!-- features:end -->"
AMEND_RE = re.compile(r"^(\d{4})-[a-z0-9][a-z0-9-]*\.md$")
FIELD_RE = r"^\s*[-*]?\s*\*\*{name}:?\*\*:?\s*(.+?)\s*$"


# --------------------------------------------------------------------------- #
# discovery
# --------------------------------------------------------------------------- #
def _first(repo: Path, cands) -> Path | None:
    for c in cands:
        if (repo / c).exists():
            return repo / c
    return None


def find_prd(repo: Path) -> Path | None:
    """The file the catalog's top-level `prd:` key names, else PRD.md / docs/PRD.md."""
    f = _first(repo, FEATURE_FILES)
    if f:
        try:
            d = yaml.safe_load(f.read_text()) or {}
            rel = d.get("prd") if isinstance(d, dict) else None
            if isinstance(rel, str) and (repo / rel).exists():
                return repo / rel
        except yaml.YAMLError:
            pass
    return _first(repo, PRD_FILES)


def load_features(repo: Path) -> tuple[Path | None, list[dict], list[str]]:
    f = _first(repo, FEATURE_FILES)
    if not f:
        return None, [], []
    try:
        d = yaml.safe_load(f.read_text()) or {}
    except yaml.YAMLError as e:
        return f, [], [f"{f.relative_to(repo)}: YAML parse error: {str(e).splitlines()[0]}"]
    feats = d.get("features") if isinstance(d, dict) else d
    if not isinstance(feats, list):
        return f, [], [f"{f.relative_to(repo)}: no `features:` list"]
    return f, [x for x in feats if isinstance(x, dict)], []


def feature_status(f: dict) -> str:
    s = str(f.get("status") or "").lower()
    if s:
        return s
    return "shipped" if f.get("implemented") is True else "planned" if f.get("implemented") is False else "tbd"


def _refs(f: dict) -> list[str]:
    v = f.get("prd")
    if v is None:
        return []
    return [str(x) for x in (v if isinstance(v, list) else [v])]


def strip_block(text: str) -> str:
    s, e = text.find(BLOCK_START), text.find(BLOCK_END)
    return text if s < 0 or e < 0 else text[:s] + text[e + len(BLOCK_END):]


def ref_exists(prd_text: str, ref: str) -> bool:
    body = strip_block(prd_text)
    if ref.startswith("§"):
        num = re.escape(ref[1:].rstrip("."))
        return bool(re.search(rf"^#+\s+(?:\S+\s+)?{num}[.)\s]", body, re.M))
    if ref.startswith("#"):
        return True  # heading anchors are not resolvable offline without a renderer; accept
    return bool(re.search(rf"(?<![\w-]){re.escape(ref)}(?![\w-])", body))


# --------------------------------------------------------------------------- #
# PRD block rendering
# --------------------------------------------------------------------------- #
def _rel(from_file: Path, to: Path) -> str:
    return os.path.relpath(to, from_file.parent).replace(os.sep, "/")


def _where(repo: Path, prd: Path, f: dict) -> str:
    out = []
    for key in ("link", "docs"):
        v = f.get(key)
        if not v or not isinstance(v, str):
            continue
        if re.match(r"^https?://", v):
            out.append(f"[{key}]({v})")
        elif v.startswith("/") and not (repo / v.lstrip("/")).exists():
            out.append(f"route `{v}`")
        elif (repo / v.lstrip("/")).exists():
            out.append(f"[`{v.lstrip('/')}`]({_rel(prd, repo / v.lstrip('/'))})")
        else:
            out.append(f"`{v}`")
    return " · ".join(dict.fromkeys(out)) or "TBD"


def render_block(repo: Path, prd: Path, ffile: Path, feats: list[dict]) -> str:
    cat = _rel(prd, ffile)
    lines = [
        f"{BLOCK_START} · generated by bamr87/bamr87 tools/governance_lint.py prd-sync from {ffile.relative_to(repo).as_posix()} — edit the catalog, then re-run; do not edit this table by hand -->",
        f"Every user-facing capability has a stable id in the feature catalog [`{ffile.relative_to(repo).as_posix()}`]({cat}). "
        "Each entry names the PRD requirements it serves (`prd:`); the trace below is the reverse view.",
        "",
        "| ID | Feature | Status | Where | Requirements |",
        "| --- | --- | --- | --- | --- |",
    ]
    trace: dict[str, list[str]] = {}
    for f in feats:
        fid = str(f.get("id", "?"))
        refs = _refs(f)
        for r in refs:
            trace.setdefault(r, []).append(fid)
        title = str(f.get("title", "")).replace("|", "\\|")
        lines.append(f"| [{fid}]({cat}) | {title} | {feature_status(f)} | {_where(repo, prd, f)} | {', '.join(refs) or 'TBD'} |")
    if not feats:
        lines.append("| — | No features catalogued yet | tbd | — | — |")
    lines += ["", "**Requirement → feature trace**", ""]
    if trace:
        lines += ["| Requirement | Features |", "| --- | --- |"]
        lines += [f"| {r} | {', '.join(ids)} |" for r, ids in trace.items()]
    else:
        lines.append("_No feature names a requirement yet (TBD)._")
    lines.append(BLOCK_END)
    return "\n".join(lines)


SECTION_TITLE = "## Feature catalog"


def sync_prd_text(text: str, block: str) -> str:
    s, e = text.find(BLOCK_START), text.find(BLOCK_END)
    if s >= 0 and e >= 0:
        return text[:s] + block + text[e + len(BLOCK_END):]
    section = f"{SECTION_TITLE}\n\n{block}\n\n"
    heads = [(m.start(), m.group(0)) for m in re.finditer(r"^## .*$", text, re.M)]
    # after the first features section; else before success/roadmap/links; else at end
    for i, (pos, h) in enumerate(heads):
        if re.search(r"feature", h, re.I):
            nxt = heads[i + 1][0] if i + 1 < len(heads) else len(text)
            return text[:nxt].rstrip("\n") + "\n\n" + section + text[nxt:]
    for pos, h in heads:
        if re.search(r"success|roadmap|links|milestone|out of scope|oos|open question", h, re.I):
            return text[:pos] + section + text[pos:]
    return text.rstrip("\n") + "\n\n" + section.rstrip("\n") + "\n"


def tag_requirements(text: str) -> tuple[str, int]:
    """Prefix untagged bullets under **Functional** / **Non-functional** inside a
    `## N. Requirements` section with FRn: / NFRn: (continuing existing numbers)."""
    lines = text.split("\n")
    in_req, kind, n = False, None, {"FR": 0, "NFR": 0}
    for ln in lines:
        for m in re.finditer(r"(?<![\w-])(N?FR)(\d+)(?![\w-])", ln):
            n[m.group(1)] = max(n[m.group(1)], int(m.group(2)))
    changed = 0
    for i, ln in enumerate(lines):
        if ln.startswith("## "):
            in_req, kind = bool(re.match(r"^## (\d+\.\s*)?(Functional |Non-functional )?requirements\b", ln, re.I)), None
            continue
        if not in_req:
            continue
        low = ln.strip().lower().strip("*:")
        if re.match(r"^\*\*functional", ln.strip(), re.I) or low == "functional":
            kind = "FR"; continue
        if re.match(r"^\*\*non-?functional", ln.strip(), re.I) or low in ("non-functional", "nonfunctional"):
            kind = "NFR"; continue
        m = re.match(r"^(\s*[-*]\s+)(.*)$", ln)
        if kind and m and not re.match(r"^\*{0,2}N?FR\d+", m.group(2)):
            n[kind] += 1
            lines[i] = f"{m.group(1)}{kind}{n[kind]}: {m.group(2)}"
            changed += 1
    return "\n".join(lines), changed


# --------------------------------------------------------------------------- #
# checks
# --------------------------------------------------------------------------- #
def _field(text: str, name: str) -> str | None:
    m = re.search(FIELD_RE.format(name=re.escape(name)), text, re.M | re.I)
    return m.group(1) if m else None


def check(repo: Path) -> dict:
    res = {"repo": str(repo), "errors": [], "warnings": [], "prd": None, "features": None,
           "constitution": None, "amendments": []}
    E, W = res["errors"].append, res["warnings"].append
    ffile, feats, ferr = load_features(repo)
    for e in ferr:
        E(e)
    prd = find_prd(repo)
    res["prd"] = str(prd.relative_to(repo)) if prd else None
    res["features"] = str(ffile.relative_to(repo)) if ffile else None
    ids = {str(f.get("id")) for f in feats}
    prd_text = prd.read_text() if prd else ""

    # --- UPS-WORK-15: PRD <-> feature catalog ---------------------------------
    if not ffile:
        E("no feature catalog (features/features.yml) — seed it with tools/fanout.sh --kit governance")
    if ffile and any(str(f.get("id", "")).startswith("TODO-") for f in feats):
        E(f"{res['features']}: still carries the kit placeholder TODO-001 — replace it with real features")
    for f in feats:
        fid = f.get("id", "?")
        st = str(f.get("status") or "")
        if st and st.lower() not in STATUSES:
            E(f"{fid}: status must be one of {', '.join(STATUSES)}")
        if not f.get("description"):
            E(f"{fid}: missing description")
        for r in _refs(f):
            if prd and r.upper() != "TBD" and not ref_exists(prd_text, r):
                E(f"{fid}: prd ref {r!r} not found in {res['prd']}")
        if prd and not _refs(f):
            W(f"{fid}: names no PRD requirement (`prd: [TBD]` if unknown)")
    if not prd:
        W("no PRD (PRD.md, docs/PRD.md, or .github/sdlc.yml governance.prd)")
    elif ffile:
        s, e = prd_text.find(BLOCK_START), prd_text.find(BLOCK_END)
        if s < 0 or e < 0:
            E(f"{res['prd']}: no generated feature block — run governance_lint.py prd-sync --write")
        else:
            want = render_block(repo, prd, ffile, feats)
            if prd_text[s:e + len(BLOCK_END)] != want:
                E(f"{res['prd']}: feature block is stale — run governance_lint.py prd-sync --write")

    # --- UPS-WORK-16: constitution + amendments --------------------------------
    con = _first(repo, CONSTITUTION_FILES)
    res["constitution"] = str(con.relative_to(repo)) if con else None
    adir = _first(repo, AMEND_DIRS)
    if not con:
        E("no constitution (docs/constitution.md) — seed it with tools/fanout.sh --kit governance")
    else:
        ct = con.read_text()
        if "TODO:" in ct:
            W(f"{res['constitution']}: has unfilled TODO: lines")
        if not re.search(r"^#+ .*amend", ct, re.I | re.M):
            E(f"{res['constitution']}: no Amendments section")
        if adir and adir.name not in ct:
            W(f"{res['constitution']}: does not link the amendment log ({adir.relative_to(repo)})")
    if not adir:
        E("no amendment log (docs/amendments/) — seed it with tools/fanout.sh --kit governance")
    else:
        if not (adir / "README.md").exists():
            W(f"{adir.relative_to(repo)}/README.md missing (the index)")
        seen: dict[str, str] = {}
        records = sorted(p for p in adir.glob("*.md") if p.name not in ("README.md", "SCHEMA.md"))
        for p in records:
            m = AMEND_RE.match(p.name)
            rel = p.relative_to(repo).as_posix()
            if not m:
                E(f"{rel}: amendment files are NNNN-kebab-slug.md"); continue
            if m.group(1) in seen:
                E(f"{rel}: duplicate amendment number {m.group(1)} (also {seen[m.group(1)]})")
            seen[m.group(1)] = p.name
            if m.group(1) == "0000":
                continue  # the template
            t = p.read_text()
            st = (_field(t, "Status") or "").lower().split()[0:1]
            st = st[0].strip("*_`.,") if st else ""
            if st not in AMEND_STATUSES:
                E(f"{rel}: **Status:** must be one of {', '.join(AMEND_STATUSES)}")
            if not re.match(r"\d{4}-\d{2}-\d{2}", _field(t, "Date") or ""):
                E(f"{rel}: **Date:** YYYY-MM-DD missing")
            if st == "ratified" and not _field(t, "Ratified by"):
                E(f"{rel}: ratified record needs **Ratified by:** (the merged PR)")
            aff = _field(t, "Affects")
            if aff is None:
                E(f"{rel}: **Affects:** missing (constitution §, PRD refs, feature ids, or 'none')")
            else:
                for tok in re.findall(r"(?<![\w-])[A-Z][A-Z0-9-]*-\d+(?![\w-])", aff):
                    if tok.startswith("UPS-"):
                        continue  # fleet spec row ids, not repo refs
                    if ids and tok not in ids and not ref_exists(prd_text, tok):
                        W(f"{rel}: Affects names {tok}, which is neither a feature id nor a PRD ref")
            res["amendments"].append({"file": rel, "status": st})
        if not [a for a in res["amendments"]]:
            E(f"{adir.relative_to(repo)}: no amendment records (0001 is the ratification record)")
    agent = next((repo / a for a in ("AGENTS.md", "CLAUDE.md") if (repo / a).exists()), None)
    if agent is None:
        W("no AGENTS.md / CLAUDE.md to point agents at the constitution")
    elif con and "constitution" not in agent.read_text().lower():
        E(f"{agent.name}: does not reference the constitution ({res['constitution']})")
    res["ok"] = not res["errors"]
    return res


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _print(res: dict) -> None:
    print(f"{res['repo']}: {'ok' if res['ok'] else 'FAIL'} "
          f"(prd={res['prd']}, features={res['features']}, constitution={res['constitution']}, "
          f"amendments={len(res['amendments'])})")
    for e in res["errors"]:
        print(f"  error: {e}")
    for w in res["warnings"]:
        print(f"  warn:  {w}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("Usage:")[0].strip(), formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "prd-sync", "prd-ids"):
        p = sub.add_parser(name)
        p.add_argument("repo", nargs="?", default=".")
        p.add_argument("--json", action="store_true")
        p.add_argument("--write", action="store_true")
        p.add_argument("--werror", action="store_true")
    f = sub.add_parser("fleet")
    f.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "fleet":
        out = [check(p) for p in sorted((HUB / "projects").iterdir()) if (p / ".git").exists()]
        out.insert(0, check(HUB))
        if a.json:
            print(json.dumps(out, indent=2))
        else:
            for r in out:
                _print(r)
            print(f"\n{sum(r['ok'] for r in out)}/{len(out)} repos clean")
        return 0
    repo = Path(a.repo).resolve()
    if a.cmd == "check":
        res = check(repo)
        print(json.dumps(res, indent=2)) if a.json else _print(res)
        return 0 if res["ok"] and not (a.werror and res["warnings"]) else 1
    prd = find_prd(repo)
    if not prd:
        print("no PRD found", file=sys.stderr); return 1
    text = prd.read_text()
    if a.cmd == "prd-ids":
        new, n = tag_requirements(text)
        print(f"{prd.relative_to(repo)}: {n} requirement bullet(s) {'tagged' if a.write else 'would be tagged'}")
    else:
        ffile, feats, err = load_features(repo)
        if not ffile or err:
            print("; ".join(err) or "no feature catalog", file=sys.stderr); return 1
        new = sync_prd_text(text, render_block(repo, prd, ffile, feats))
        print(f"{prd.relative_to(repo)}: feature block {'unchanged' if new == text else ('written' if a.write else 'stale (use --write)')}")
    if a.write and new != text:
        prd.write_text(new)
    return 0


if __name__ == "__main__":
    sys.exit(main())
