#!/usr/bin/env python3
"""
Fixture tests for schema_vendor.py — the hub's re-vendor loop for bamr87/SCHEMA.

Guards the invariant the design rests on, the same shape reconcile.py has:
`--apply` writes what is mechanical and must NEVER touch what carries local
judgement. The hub's copies of the seed template and the protocol snippet are
deliberately reflowed to house style; an overwrite would throw that away every
week, silently, and the fleet's own prose gate would then fight the re-vendor.

Deliberately dependency-light — upstream is a dict and a lambda, so this needs
only PyYAML and runs on a bare interpreter:

    python3 .github/scripts/dash-gen/test_schema_vendor.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import schema_vendor as sv  # noqa: E402

LINTER = 'SPEC_VERSION = "0.1"\n\ndef check():\n    return 0\n'
TEMPLATE = '---\nschema: "0.1"\n---\n\n| entry | kind |\n|---|---|\n'
SNIPPET = "Read `./SCHEMA.md` first.\nThen follow the nearest schema.\n"

VERSION_FIXTURE = """\
source: pyramid-schema (https://github.com/bamr87/SCHEMA)
upstream-commit: aaaaaaa
spec: "0.1"
vendored: 2026-01-01
verified: 2026-01-01
files: tools/schema_lint.py, templates/schema/SCHEMA.template.md
reinvest: improvements go upstream first, then re-vendor.
notes: |
  A long hand-written note that must survive a restamp, because it is the
  only record of WHY the local copies are adapted.
"""


def upstream(**overrides: str) -> tuple[dict, object]:
    """A manifest plus a fetcher, built from in-memory upstream contents."""
    files = {"tools/schema_lint.py": LINTER,
             "templates/SCHEMA.template.md": TEMPLATE,
             "protocol/CLAUDE.snippet.md": SNIPPET}
    files.update(overrides)
    payload = []
    for path, parity in (("tools/schema_lint.py", "strict"),
                         ("templates/SCHEMA.template.md", "text"),
                         ("protocol/CLAUDE.snippet.md", "text")):
        raw, text = sv.digests(files[path].encode())
        payload.append({"path": path, "parity": parity,
                        "sha256": raw, "sha256_text": text})
    manifest = {"schema": "distribution/v1", "spec": "0.1", "payload": payload}
    return manifest, (lambda p: files[p].encode())


def hub(tmp: Path, **overrides: str) -> Path:
    """A hub checkout carrying the kit, adapted exactly as the real one is."""
    root = tmp / "hub"
    (root / "tools").mkdir(parents=True, exist_ok=True)
    (root / "templates" / "schema").mkdir(parents=True, exist_ok=True)
    files = {
        "tools/schema_lint.py": LINTER,
        # reflowed + requoted, the way the real hub carries them
        "templates/schema/SCHEMA.template.md": TEMPLATE.replace(
            '"0.1"', "'0.1'").replace("|---|---|", "| --- | --- |"),
        "templates/schema/CLAUDE.snippet.md": SNIPPET.replace("\n", " ").strip() + "\n",
        "templates/schema/VERSION": VERSION_FIXTURE,
    }
    files.update(overrides)
    for rel, body in files.items():
        (root / rel).write_text(body, encoding="utf-8")
    return root


def kinds(plan: sv.Plan) -> dict[str, str]:
    return {f.local or f.upstream: f.kind for f in plan.findings}


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    failures: list[str] = []

    def check(label: str, cond: bool) -> None:
        print(f"  {'PASS' if cond else 'FAIL'}  {label}")
        if not cond:
            failures.append(label)

    # --- detection ---------------------------------------------------------
    print("detection:")
    manifest, fetch = upstream()
    root = hub(tmp)
    plan = sv.build_plan(root, manifest, fetch, commit="bbbbbbb")
    k = kinds(plan)
    check("byte-identical linter reads current",
          k["tools/schema_lint.py"] == "current")
    check("requoted + re-tabulated template is NOT drift",
          k["templates/schema/SCHEMA.template.md"] == "current")
    check("reflowed snippet is NOT drift",
          k["templates/schema/CLAUDE.snippet.md"] == "current")
    check("a behind stamp is reported", "pin-stale" in k.values())
    check("a behind stamp alone is not actionable", plan.actionable == [])

    shutil.rmtree(tmp / "hub")
    root = hub(tmp, **{"tools/schema_lint.py": LINTER + "# local fork\n"})
    plan = sv.build_plan(root, manifest, fetch, commit="bbbbbbb")
    check("a forked linter is drift-strict",
          kinds(plan)["tools/schema_lint.py"] == "drift-strict")
    check("a forked linter is actionable", len(plan.actionable) == 1)

    shutil.rmtree(tmp / "hub")
    root = hub(tmp, **{"templates/schema/CLAUDE.snippet.md":
                       SNIPPET.replace("Read", "Never read")})
    plan = sv.build_plan(root, manifest, fetch)
    check("a reworded snippet is drift-text",
          kinds(plan)["templates/schema/CLAUDE.snippet.md"] == "drift-text")

    shutil.rmtree(tmp / "hub")
    root = hub(tmp)
    (root / "templates" / "schema" / "SCHEMA.template.md").unlink()
    plan = sv.build_plan(root, manifest, fetch)
    check("an absent kit file is missing-local",
          kinds(plan)["templates/schema/SCHEMA.template.md"] == "missing-local")

    # upstream widening its interface must never be silently ignored
    shutil.rmtree(tmp / "hub")
    root = hub(tmp)
    wide = dict(manifest)
    wide["payload"] = manifest["payload"] + [
        {"path": "protocol/AGENTS.snippet.md", "parity": "text",
         "sha256": "x", "sha256_text": "y"}]
    plan = sv.build_plan(root, wide, fetch)
    check("a new upstream payload file is reported as unmapped",
          kinds(plan)["protocol/AGENTS.snippet.md"] == "unmapped")

    # --- apply safety ------------------------------------------------------
    print("apply:")
    shutil.rmtree(tmp / "hub")
    adapted_snippet = SNIPPET.replace("Read", "Never read")
    root = hub(tmp, **{"tools/schema_lint.py": LINTER + "# local fork\n",
                       "templates/schema/CLAUDE.snippet.md": adapted_snippet})
    plan = sv.build_plan(root, manifest, fetch, commit="bbbbbbb")
    written = sv.apply_plan(root, plan, fetch, today="2026-09-03")
    check("strict drift is re-vendored",
          (root / "tools/schema_lint.py").read_text() == LINTER)
    check("text drift is NEVER overwritten",
          (root / "templates/schema/CLAUDE.snippet.md").read_text() == adapted_snippet)
    check("the VERSION file is restamped", sv.VERSION_FILE in written)

    version = (root / sv.VERSION_FILE).read_text()
    check("restamp updates upstream-commit", "upstream-commit: bbbbbbb" in version)
    check("restamp updates both dates", version.count("2026-09-03") == 2)
    check("restamp preserves the hand-written notes",
          "only record of WHY" in version)
    check("restamp preserves every other line",
          len(version.splitlines()) == len(VERSION_FIXTURE.splitlines()))

    shutil.rmtree(tmp / "hub")
    root = hub(tmp)
    (root / "templates" / "schema" / "SCHEMA.template.md").unlink()
    plan = sv.build_plan(root, manifest, fetch)
    sv.apply_plan(root, plan, fetch, today="2026-09-03")
    check("an absent kit file IS seeded (no adaptation to lose)",
          (root / "templates/schema/SCHEMA.template.md").read_text() == TEMPLATE)

    shutil.rmtree(tmp / "hub")
    root = hub(tmp)
    plan = sv.build_plan(root, manifest, fetch, commit="bbbbbbb")
    before = (root / sv.VERSION_FILE).read_text()
    sv.apply_plan(root, plan, fetch, today="2026-09-03")
    check("nothing to re-vendor leaves VERSION alone",
          (root / sv.VERSION_FILE).read_text() == before)

    # --- normalization parity with upstream's schema_dist -------------------
    print("normalization:")
    check("whitespace is removed, not collapsed",
          sv.normalize_text("|---|") == sv.normalize_text("| --- |"))
    check("quote style is ignored",
          sv.normalize_text("schema: '0.1'") == sv.normalize_text('schema: "0.1"'))
    check("wording changes are not ignored",
          sv.normalize_text("never do this") != sv.normalize_text("always do this"))

    # --- manifest guards ----------------------------------------------------
    print("manifest:")
    for bad, label in ((b"not: a manifest\n", "a yaml doc without payload"),
                       (b"- 1\n- 2\n", "a yaml list")):
        try:
            sv.load_manifest(lambda _p, b=bad: b)
            ok = False
        except RuntimeError:
            ok = True
        check(f"{label} is rejected", ok)

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
