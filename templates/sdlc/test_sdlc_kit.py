#!/usr/bin/env python3
"""Fixture tests for the SDLC kit (templates/sdlc/).

    python3 templates/sdlc/test_sdlc_kit.py                 # test the kit
    python3 templates/sdlc/test_sdlc_kit.py --target <repo> # validate a repo's .github/sdlc.yml

Stdlib + PyYAML. JSON Schema validation uses `jsonschema` when it is installed
and falls back to a built-in check of the same rules otherwise. Where the hub
carries specs/WORK.contract.yml, its regexes are used, so the kit is tested
against the same contract the conformance checker reads.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

KIT = Path(__file__).resolve().parent
HUB = KIT.parent.parent
TOKENS = {"__PROJECT_NAME__", "__DEFAULT_BRANCH__", "__KIT_VERSION__"}
FAILS: list[str] = []

_contract = HUB / "specs" / "WORK.contract.yml"
DEFS = (yaml.safe_load(_contract.read_text(encoding="utf-8")) or {}).get("definitions", {}) if _contract.is_file() else {}
PINNED_REF = re.compile(DEFS.get("pinned_ref_re", r"^(v\d+|v\d+\.\d+\.\d+|[0-9a-f]{40})$"))
# Structured keys from the contract (UPS-AGENT-07/08/09, UPS-REPO-21), with the same values as fallbacks.
AGENT_HEADINGS = DEFS.get("agents_required_headings") or ["What this repo is", "Stack & commands", "Layout",
                                                          "Conventions", "Fleet context", "Standard deviations"]
CLAUDE_MAX = int(DEFS.get("claude_max_nonblank_lines", 20))
CLAUDE_POINTER_RE = re.compile(DEFS.get("claude_pointer_re", r"^@AGENTS\.md[ \t]*$"), re.M)
STAMP_RE = re.compile((DEFS.get("kit_stamp") or {}).get("re", r"<!--\s*kit:\s*(sdlc|agent-context)\s+v(\d+\.\d+\.\d+)\b"))
RELEASE_TYPES_BY_TYPE = DEFS.get("release_types") or {
    "app": ["node", "python", "ruby", "simple"], "library": ["node", "python", "ruby", "simple"], "site": ["simple"],
    "docs": ["simple"], "demo": ["simple"], "control-plane": ["simple"], "fork": []}
RELEASE_TYPES = ["simple", "node", "python", "ruby"]
TYPE_KINDS = DEFS.get("type_kinds") or {"app": ["app"], "library": ["lib"], "site": ["site"], "docs": ["content"],
                                         "demo": ["site"], "control-plane": ["site", "hub"], "fork": ["fork"]}


def check(cond: bool, msg: str) -> None:
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        FAILS.append(msg)


def kit_files() -> list[Path]:
    skip = {"README.md", "VERSION", Path(__file__).name}
    return sorted(p for p in KIT.rglob("*") if p.is_file() and not (p.parent == KIT and p.name in skip)
                  and "archive" not in p.relative_to(KIT).parts and "__pycache__" not in p.parts)


def read(rel: str) -> str:
    return (KIT / rel).read_text(encoding="utf-8")


def schema() -> dict:
    return json.loads(read("sdlc.schema.json"))


# --- schema validation -------------------------------------------------------
def _fallback_errors(doc, sch) -> list[str]:
    """The schema's rules, hand-coded, for hosts without `jsonschema`."""
    errs, props = [], sch["properties"]
    if not isinstance(doc, dict):
        return ["not a mapping"]
    errs += [f"unknown key {k}" for k in doc if k not in props]
    errs += [f"missing {k}" for k in sch["required"] if k not in doc]
    if doc.get("schema") != "sdlc/v1":
        errs.append("schema != sdlc/v1")
    for key in ("type", "tier"):
        if key in doc and doc[key] not in props[key]["enum"]:
            errs.append(f"{key} {doc[key]!r} not allowed")
    if doc.get("type") != "fork" and "release" not in doc:
        errs.append("missing release")
    kinds = doc.get("kinds")
    if kinds is not None and (not isinstance(kinds, list) or not kinds or
                              any(k not in props["kinds"]["items"]["enum"] for k in kinds)):
        errs.append("bad kinds")
    b = doc.get("backlog") or {}
    if not isinstance(b, dict) or b.get("mode") not in ("issues", "file"):
        errs.append("bad backlog.mode")
    elif b.get("mode") == "file" and b.get("file") not in ("BACKLOG.md", "_data/backlog.yml"):
        errs.append("file mode needs backlog.file")
    elif b.get("mode") == "issues" and ("file" in b or b.get("mirror_to_issues") is True):
        errs.append("issues mode takes no file/mirror")
    m = doc.get("modules")
    if not isinstance(m, dict):
        errs.append("modules must be a map")
    else:
        errs += [f"bad module {k}" for k, v in m.items() if k not in props["modules"]["properties"] or not isinstance(v, bool)]
    rel = doc.get("release")
    if rel is not None and (not isinstance(rel, dict) or rel.get("type") not in RELEASE_TYPES):
        errs.append("bad release.type")
    for d in doc.get("deviations") or []:
        if not (isinstance(d, dict) and re.match(r"^UPS-[A-Z]+-\d{2,}$", str(d.get("id", ""))) and d.get("reason")):
            errs.append(f"bad deviation {d}")
        elif "until" in d and not (isinstance(d["until"], str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d["until"])):
            errs.append(f"deviation until must be a quoted YYYY-MM-DD string, got {d['until']!r}")
    return errs


def validate(doc) -> list[str]:
    try:
        import jsonschema  # type: ignore
    except ImportError:
        return _fallback_errors(doc, schema())
    v = jsonschema.Draft202012Validator(schema())
    return [f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in v.iter_errors(doc)]


# --- tests -------------------------------------------------------------------
def t_version() -> None:
    print("VERSION `files:` matches the kit")
    meta = yaml.safe_load(read("VERSION"))
    listed = {f.strip() for f in str(meta["files"]).split(",")}
    actual = {str(p.relative_to(KIT)) for p in kit_files()}
    check(listed == actual, f"listed == on disk (missing {sorted(actual - listed)}, stale {sorted(listed - actual)})")
    check(re.fullmatch(r"\d+\.\d+\.\d+", str(meta["version"])) is not None, "version is semver")


def t_placeholders() -> None:
    print("only fan-out tokens; no {{…}} scaffolds")
    for p in kit_files():
        t = p.read_text(encoding="utf-8")
        found = set(re.findall(r"__[A-Z][A-Z_]*__", t))
        check(found <= TOKENS and re.search(r"(?<!\$)\{\{", t) is None, f"{p.relative_to(KIT)} ({sorted(found - TOKENS) or 'clean'})")


def t_schema_and_profile() -> None:
    print("sdlc.yml validates against sdlc.schema.json (UPS-WORK-01)")
    sch = schema()
    check(sch.get("$schema", "").endswith("2020-12/schema"), "schema is JSON Schema 2020-12")
    check(set(sch["properties"]["type"]["enum"]) == set(TYPE_KINDS), "type enum == D6 types")
    doc = yaml.safe_load(read("sdlc.yml"))
    errs = validate(doc)
    check(not errs, f"kit sdlc.yml is valid {errs or ''}")
    check(set(doc) == set(sch["properties"]), "kit sdlc.yml shows every schema key")
    check(doc["kinds"] == TYPE_KINDS[doc["type"]], "kit kinds == the type's default kinds")
    base = dict(doc)
    bad = {
        "unknown key": {**base, "kind": "app"},
        "modules as a list": {**base, "modules": ["adr"]},
        "file mode without file": {**base, "backlog": {"mode": "file"}},
        "issues mode with a file": {**base, "backlog": {"mode": "issues", "file": "BACKLOG.md"}},
        "demo as a kind": {**base, "kinds": ["demo"]},
        "unknown release type": {**base, "release": {"type": "go"}},
        "non-fork without release": {k: v for k, v in base.items() if k != "release"},
        "bad deviation id": {**base, "deviations": [{"id": "WORK-7", "reason": "x"}]},
        "wrong schema tag": {**base, "schema": "sdlc/v2"},
    }
    for name, d in bad.items():
        check(bool(validate(d)), f"rejects: {name}")
    good = {
        "file backlog": {**base, "backlog": {"mode": "file", "file": "BACKLOG.md", "mirror_to_issues": True}},
        "fork without release": {**{k: v for k, v in base.items() if k != "release"}, "type": "fork", "kinds": ["fork"]},
        "lineage adr_path": {**base, "adr_path": "lineage/decisions"},
        "deviation": {**base, "deviations": [{"id": "UPS-WORK-07", "reason": "x", "until": "2027-01-01"}]},
    }
    for name, d in good.items():
        check(not validate(d), f"accepts: {name} {validate(d) or ''}")
    # The commented deviation example, uncommented: `until` must stay a quoted string.
    ex = re.search(r"^deviations: \[\]\s*#\s*(- \{.*\})", read("sdlc.yml"), re.M)
    check(ex is not None and '"2027-01-01"' in ex.group(1), "sdlc.yml deviation example quotes until")
    if ex:
        devs = yaml.safe_load(ex.group(1))
        check(isinstance(devs[0].get("until"), str), "the example's until parses as a string")
        check(not validate({**base, "deviations": devs}), "the uncommented example validates")
        unquoted = yaml.safe_load(ex.group(1).replace('"2027-01-01"', "2027-01-01"))
        check(bool(validate({**base, "deviations": unquoted})), "an unquoted until (a YAML date) is rejected")
    # Release types per repo type (contract release_types, UPS-REPO-21).
    check(set(RELEASE_TYPES_BY_TYPE) == set(TYPE_KINDS), "release_types covers every repo type")
    enum = set(sch["properties"]["release"]["properties"]["type"]["enum"])
    check(set().union(*map(set, RELEASE_TYPES_BY_TYPE.values())) <= enum, "every allowed release type is in the schema enum")
    check(RELEASE_TYPES_BY_TYPE["fork"] == [], "fork has no release type")
    check(doc["release"]["type"] in RELEASE_TYPES_BY_TYPE[doc["type"]], "kit sdlc.yml release.type is allowed for its type")


def _sections(text: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"^##\s+(.+)$", text, re.M)]


def t_agents_and_claude() -> None:
    print("AGENTS.md canonical, CLAUDE.md pointer (decision D4)")
    a = read("AGENTS.template.md")
    have = {h.lower() for h in _sections(a)}
    missing = [h for h in AGENT_HEADINGS if h.lower() not in have]
    check(not missing, f"AGENTS has the six required headings, any order (UPS-AGENT-07); missing {missing}")
    check(_sections(a) == AGENT_HEADINGS, "kit template keeps the canonical heading order (a kit choice; AGENT-07 allows any)")
    stamped = a.replace("__KIT_VERSION__", "0.1.0")
    m = STAMP_RE.search(stamped)
    check(m is not None and m.group(1) == "sdlc", "kit stamp matches kit_stamp.re after fan-out (UPS-AGENT-09)")
    check("TODO:" in a, "scaffold has TODO: markers to fill (AGENT-07 fails until they are gone)")
    conv = a.split("## Conventions", 1)[1].split("\n## ", 1)[0]
    doc = yaml.safe_load(read("sdlc.yml"))
    check(re.search(r"backlog", conv, re.I) is not None, "Conventions names the backlog of record (UPS-WORK-12)")
    check(re.search(r"Definition of Done|pull_request_template", conv) is not None, "Conventions names the DoD location")
    check(doc["adr_path"] in conv, f"Conventions names adr_path `{doc['adr_path']}`")
    for word in ("lockfiles", "secrets", "type errors", "exception handlers", "generated files"):
        check(word in conv, f"do-not present: {word} (UPS-AGENT-04)")
    c = read("CLAUDE.template.md")
    nonblank = [l for l in c.splitlines() if l.strip()]
    check(CLAUDE_POINTER_RE.search(c) is not None, "CLAUDE.md imports @AGENTS.md (UPS-AGENT-08)")
    check(not {h.lower() for h in _sections(c)} & {h.lower() for h in AGENT_HEADINGS}, "CLAUDE.md carries no AGENT-07 headings")
    check(len(nonblank) <= CLAUDE_MAX, f"CLAUDE.md at most {CLAUDE_MAX} non-blank lines ({len(nonblank)})")


def t_changelog() -> None:
    print("CHANGELOG seeds a release-please-friendly file (UPS-REPO-21, UPS-WORK-05)")
    t = read("CHANGELOG.template.md")
    check(len(re.findall(r"^##\s*\[?unreleased\b", t, re.I | re.M)) <= 1, "at most one [Unreleased]")
    check(re.search(r"\n###? v?[0-9[]", t) is not None, "has a version heading release-please inserts above")
    m = re.search(r"^##\s*\[?v?(\d+\.\d+\.\d+)", t, re.M)
    manifest = json.loads(read("release/.release-please-manifest.json"))
    check(m is not None and manifest == {".": m.group(1)}, f"baseline heading == manifest version ({manifest})")
    check(t.startswith("# Changelog\n"), "title is `# Changelog` (release-please's own header)")


def t_release() -> None:
    print("release caller + configs (decision D5)")
    wf = yaml.safe_load(read("release/release.yml"))
    on = wf.get(True) or wf.get("on")
    check(on["push"]["branches"] == ["__DEFAULT_BRANCH__"], "runs on push to the default branch")
    job = wf["jobs"]["release"]
    path, _, ref = job["uses"].partition("@")
    check(path == "bamr87/bamr87/.github/workflows/release-please.yml", "calls the hub's reusable release-please.yml")
    check(ref == "v1" and PINNED_REF.fullmatch(ref) is not None, f"pinned @v1 (UPS-WORK-10), got @{ref}")
    check(job.get("permissions") == {"contents": "write", "pull-requests": "write"}, "job grants contents+pull-requests write")
    check(wf.get("permissions") == {"contents": "read"}, "top-level permissions are read-only")
    check(job.get("secrets") == "inherit", "secrets: inherit (optional RELEASE_PLEASE_TOKEN)")
    sections = None
    for t in RELEASE_TYPES:
        cfg = json.loads(read(f"release/release-please-config.{t}.json"))
        pkg = cfg["packages"]["."]
        check(pkg["release-type"] == t, f"{t}: release-type matches the file name")
        check(pkg["changelog-path"] == "CHANGELOG.md", f"{t}: writes CHANGELOG.md")
        docs = next(s for s in pkg["changelog-sections"] if s["type"] == "docs")
        check(docs.get("hidden", False) is (t != "simple"), f"{t}: docs visible only for simple (content releases)")
        chore = next(s for s in pkg["changelog-sections"] if s["type"] == "chore")
        check(chore.get("hidden") is True, f"{t}: chore hidden")
        shape = [(s["type"], s["section"]) for s in pkg["changelog-sections"]]
        sections = sections or shape
        check(shape == sections, f"{t}: same section map as the others")
        check(("version-file" in pkg) is (t == "ruby"), f"{t}: version-file only for ruby")


def t_adr() -> None:
    print("ADR log in law-ai format (UPS-WORK-04, decision D2)")
    d = KIT / "docs" / "adr"
    names = sorted(p.name for p in d.glob("*.md") if p.name != "README.md")
    check(all(re.fullmatch(r"\d{4}-[a-z0-9][a-z0-9-]*\.md", n) for n in names), f"NNNN-slug names: {names}")
    real = [n for n in names if not n.startswith("0000-")]
    check(len(real) >= 1, "≥1 real ADR besides the template")
    idx = (d / "README.md").read_text(encoding="utf-8")
    check(all(n in idx for n in real), "README index links every ADR")
    for n in names:
        secs = _sections((d / n).read_text(encoding="utf-8"))
        want = ["Context", "Decision", "Consequences", "Alternatives considered", "Supersedes / Superseded by"]
        check(secs == want, f"{n}: sections {secs}")
        check("**Status**" in (d / n).read_text(encoding="utf-8"), f"{n}: Status line")


def t_content_queue() -> None:
    print("content queue (module content_queue)")
    doc = yaml.safe_load(read("content-queue/backlog.yml"))
    check(doc["schema"] == "content-queue/v1", "schema tag")
    for it in doc["backlog"]:
        check(it["status"] in ("todo", "drafting", "done") and re.fullmatch(r"P[0-3]", it["priority"]) is not None,
              f"{it['id']}: status + fleet priority")


def target(repo: Path) -> int:
    f = repo / ".github" / "sdlc.yml"
    if not f.is_file():
        print(f"FAIL  {f} not found")
        return 1
    errs = validate(yaml.safe_load(f.read_text(encoding="utf-8")))
    for e in errs:
        print(f"FAIL  {e}")
    print("OK" if not errs else f"FAILED ({len(errs)})")
    return 1 if errs else 0


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "--target":
        return target(Path(argv[1]))
    for t in (t_version, t_placeholders, t_schema_and_profile, t_agents_and_claude, t_changelog, t_release, t_adr,
              t_content_queue):
        t()
    if FAILS:
        print(f"\nFAILED ({len(FAILS)})")
        return 1
    print("\nOK — sdlc kit")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
