#!/usr/bin/env python3
"""Fixture tests for the community kit (templates/community/).

The kit's files are inherited fleet-wide (bamr87/.github and the org .github
repos), so a broken form or a label the pipeline does not know costs every repo
at once. These checks are the contract a conformance check can also lint
against (see README.md § Contract).

    python3 templates/community/test_community_kit.py

Stdlib + PyYAML only; exits non-zero on the first failing assertion group.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

KIT = Path(__file__).resolve().parent
HUB = KIT.parent.parent
TOKENS = {"__PROJECT_NAME__", "__DEFAULT_BRANCH__", "__KIT_VERSION__"}
FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        FAILS.append(msg)


def kit_files() -> list[Path]:
    skip = {"README.md", "VERSION", Path(__file__).name}
    return sorted(p for p in KIT.rglob("*") if p.is_file() and p.name not in skip
                  and "archive" not in p.relative_to(KIT).parts and "__pycache__" not in p.parts)


def labels() -> dict:
    return yaml.safe_load((KIT / "labels.yml").read_text(encoding="utf-8"))


def label_names(doc: dict, families=("state", "type", "priority", "size", "optional")) -> set[str]:
    return {item["name"] for fam in families for item in doc.get(fam) or []}


def t_version_lists_every_file() -> None:
    print("VERSION `files:` matches the kit")
    meta = yaml.safe_load((KIT / "VERSION").read_text(encoding="utf-8"))
    listed = {f.strip() for f in str(meta["files"]).split(",")}
    actual = {str(p.relative_to(KIT)) for p in kit_files()}
    check(listed == actual, f"listed == on disk (missing: {sorted(actual - listed)}, stale: {sorted(listed - actual)})")
    check(re.fullmatch(r"\d+\.\d+\.\d+", str(meta["version"])) is not None, "version is semver")


def t_placeholders() -> None:
    print("only fan-out tokens are used as placeholders")
    for p in kit_files():
        found = set(re.findall(r"__[A-Z][A-Z_]*__", p.read_text(encoding="utf-8")))
        check(found <= TOKENS, f"{p.relative_to(KIT)}: {sorted(found - TOKENS) or 'clean'}")
        check("{{" not in p.read_text(encoding="utf-8"), f"{p.relative_to(KIT)}: no {{{{…}}}} scaffold placeholders")


def t_labels_match_fleet_config() -> None:
    print("labels.yml names == _data/fleet.yml issue_pipeline.labels")
    fleet = yaml.safe_load((HUB / "_data" / "fleet.yml").read_text(encoding="utf-8"))
    tax = fleet["issue_pipeline"]["labels"]
    doc = labels()
    check({i["name"] for i in doc["state"]} == set(tax["state"].values()), "state family")
    check({i["name"] for i in doc["type"]} == set(tax["types"]), "type family")
    check({i["name"] for i in doc["priority"]} == set(tax["priorities"]), "priority family")
    check({i["name"] for i in doc["size"]} == set(tax["sizes"]), "size family")
    names = label_names(doc)
    for fam in ("state", "type", "priority", "size", "optional"):
        for item in doc[fam]:
            check(re.fullmatch(r"[0-9a-f]{6}", item.get("color", "")) is not None, f"{item['name']}: 6-hex colour")
            for old in item.get("renames") or []:
                check(old not in names, f"rename source {old!r} is not itself a canonical label")
    mapped = set()
    for table in doc["mapping"].values():
        mapped |= set(table.values())
    check(mapped <= names, f"mapping targets are labels ({sorted(mapped - names) or 'all'})")


def t_issue_forms() -> None:
    print("issue forms: valid, fleet type label + agent:queued (UPS-REPO-18)")
    names = label_names(labels())
    types = {i["name"] for i in labels()["type"]}
    forms = sorted((KIT / ".github" / "ISSUE_TEMPLATE").glob("*.yml"))
    want = {"bug_report.yml", "feature_request.yml", "documentation.yml", "config.yml"}
    check({f.name for f in forms} == want, f"forms present: {sorted(f.name for f in forms)}")
    for f in forms:
        doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        if f.name == "config.yml":
            check(doc.get("blank_issues_enabled") is False, "config.yml: blank issues off")
            continue
        for key in ("name", "description", "labels", "body"):
            check(key in doc, f"{f.name}: has {key}")
        lab = set(doc.get("labels") or [])
        check(lab <= names, f"{f.name}: labels exist in the taxonomy ({sorted(lab - names) or 'all'})")
        check("agent:queued" in lab, f"{f.name}: enters triage as agent:queued")
        check(len(lab & types) == 1, f"{f.name}: exactly one type label")
        check("enhancement" not in lab, f"{f.name}: no GitHub-default `enhancement`")
        ids = [b.get("id") for b in doc["body"] if b.get("type") != "markdown"]
        check(len(ids) == len(set(ids)) and all(ids), f"{f.name}: unique field ids")
        check(any((b.get("validations") or {}).get("required") for b in doc["body"]), f"{f.name}: ≥1 required field")


DOD_RE = re.compile(r"<!-- fleet-dod:start v(\d+) -->\n(.*?)<!-- fleet-dod:end -->", re.S)


def t_pr_template_dod() -> None:
    print("PR template carries the fleet Definition of Done (UPS-WORK-03, UPS-REPO-19)")
    text = (KIT / ".github" / "pull_request_template.md").read_text(encoding="utf-8")
    m = DOD_RE.search(text)
    check(m is not None, "fleet-dod markers present")
    if not m:
        return
    boxes = re.findall(r"^- \[ \] \*\*(.+?)\*\*", m.group(2), re.M)
    want = ["Title", "CI is green", "Tests", "Docs", "Agent instructions", "Decision recorded",
            "Backlog of record", "Clean diff"]
    check(boxes == want, f"the eight DoD boxes, in order: {boxes}")
    for needle in ("Conventional Commit", "CHANGELOG.md", "AGENTS.md", "docs/adr/", "SCHEMA.md",
                   "features/features.yml", "README"):
        check(needle in m.group(2), f"DoD mentions {needle}")
    check("Closes #" in text, "links the issue (backlog of record = Issues)")


def t_dependabot() -> None:
    print("dependabot: github-actions only, weekly, grouped, ci prefix (UPS-QA-41)")
    doc = yaml.safe_load((KIT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    ups = doc["updates"]
    check([u["package-ecosystem"] for u in ups] == ["github-actions"], "only github-actions")
    u = ups[0]
    check(u["schedule"]["interval"] == "weekly", "weekly")
    check(u["commit-message"]["prefix"] == "ci", "ci prefix")
    check(bool(u.get("groups")), "grouped")


def t_security_and_contributing() -> None:
    print("SECURITY (UPS-REPO-14) and CONTRIBUTING (UPS-REPO-15) contracts")
    sec = (KIT / "SECURITY.md").read_text(encoding="utf-8")
    for h in ("## Supported versions", "## Reporting a vulnerability", "## Response window"):
        check(h in sec, f"SECURITY.md has {h!r}")
    check("7 days" in sec, "SECURITY.md states the 7-day window")
    con = (KIT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    for needle in ("Branch", "Conventional Commits", "Run the gates locally", "Definition of Done",
                   "Submodule rule", "AGENTS.md", "agent:ready", "CHANGELOG.md", "docs/adr/"):
        check(needle in con, f"CONTRIBUTING.md covers {needle!r}")
    check("bamr87/.github/blob/main/.github/workflows/ci.yml" not in con,
          "CONTRIBUTING does not cite the retired bamr87/.github ci.yml gate (decision D3)")


def t_codeowners() -> None:
    print("CODEOWNERS soft default (UPS-REPO-16)")
    lines = [l for l in (KIT / ".github" / "CODEOWNERS").read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.lstrip().startswith("#")]
    check(lines == ["* @bamr87"], f"exactly `* @bamr87` ({lines})")


def main() -> int:
    for t in (t_version_lists_every_file, t_placeholders, t_labels_match_fleet_config, t_issue_forms,
              t_pr_template_dod, t_dependabot, t_security_and_contributing, t_codeowners):
        t()
    if FAILS:
        print(f"\nFAILED ({len(FAILS)})")
        return 1
    print("\nOK — community kit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
