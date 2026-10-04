#!/usr/bin/env python3
"""
File: tools/test_quality_contract.py
Description: Tests specs/QUALITY.contract.yml against _data/specs.yml and every tool that reads it.
               1. Every rule (and related row) states `applies` / `applies_notes`
                  exactly as tools/gen-specs-data.py writes them, the same check
                  tools/test_work_contract.py (bamr87/bamr87#327) makes for
                  specs/WORK.contract.yml; fold the two together once #327 lands.
               2. UPS-QA-60..63 bind through `binds_when` (unbound = pass), never
                  a "does not apply" result; rollout markers are `warn`.
               3. The hub-only UPS-QA-40/41 exception (`sanctioned_lockfiles`,
                  `sanctioned_dependabot`) is well-formed: under .github/, never
                  under templates/, a reusable workflow's runtime, exact pins, a
                  committed lockfile, a matching Dependabot entry, the generated
                  .gitignore block, and never fanned out.
               4. tools/conformance.py (UPS-QA-40) and tools/unpin-deps.sh honour
                  the exception in the hub and nowhere else (throwaway repos).
Author: bamr87
Created: 2026-10-04
Last Modified: 2026-10-04
Version: 0.1.0
Usage: python3 tools/test_quality_contract.py     # needs PyYAML and git; no network
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

HUB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HUB / "tools"))
FAILS: list[str] = []
LOCKS = {"package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock", "Gemfile.lock",
         "poetry.lock", "Pipfile.lock", "uv.lock", "composer.lock"}


def check(cond: bool, msg: str) -> None:
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        FAILS.append(msg)


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout


def t_applies(contract: dict, specs: dict) -> None:
    print("applies / applies_notes == _data/specs.yml")
    for rid, rule in {**contract["rules"], **(contract.get("related") or {})}.items():
        row = specs.get(rid)
        check(row is not None, f"{rid} is in _data/specs.yml")
        if row is None:
            continue
        check(rule.get("applies") == row.get("applies"), f"{rid} applies {rule.get('applies')} == {row.get('applies')}")
        check(rule.get("applies_notes") == row.get("applies_notes"),
              f"{rid} applies_notes {rule.get('applies_notes')} == {row.get('applies_notes')}")


def t_binds(contract: dict, specs: dict) -> None:
    print("binds_when (unbound = pass) and rollout markers")
    text = (HUB / "specs" / "QUALITY.contract.yml").read_text(encoding="utf-8")
    check("does not apply" not in text, "no rule reports a 'does not apply' result")
    for rid, rule in contract["rules"].items():
        bw = str(rule.get("binds_when") or "")
        check("jekyll_marker" in bw and "otherwise the rule passes" in bw, f"{rid} binds_when names jekyll_marker and passes when unbound")
        check(rule.get("rollout") == "warn", f"{rid} rollout is `warn`")
        check(specs.get(rid, {}).get("level") not in (None, "retired"), f"{rid} is a live row")
    for rid, rule in (contract.get("related") or {}).items():
        check("rollout" not in rule, f"related {rid} carries no rollout marker (a live MUST row)")


def t_sanctioned(d: dict) -> None:
    print("sanctioned_lockfiles / sanctioned_dependabot (UPS-QA-40/41, hub only)")
    entries = d.get("sanctioned_lockfiles") or []
    check(bool(entries), "sanctioned_lockfiles is a non-empty list")
    dep = yaml.safe_load((HUB / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    present = {(u.get("package-ecosystem"), str(u.get("directory", "")).rstrip("/")) for u in dep.get("updates") or []}
    declared = {(e.get("package-ecosystem"), str(e.get("directory", "")).rstrip("/")) for e in d.get("sanctioned_dependabot") or []}
    check(declared <= present, f"every sanctioned_dependabot entry is in .github/dependabot.yml {sorted(declared - present) or ''}")
    tracked = set(git(HUB, "ls-files").splitlines())
    fanout = (HUB / "tools" / "fanout.sh").read_text(encoding="utf-8")
    gi = (HUB / ".gitignore").read_text(encoding="utf-8").splitlines()
    start = next((i for i, line in enumerate(gi) if line.startswith("# BEGIN sanctioned_lockfiles")), -1)
    end = gi.index("# END sanctioned_lockfiles") if "# END sanctioned_lockfiles" in gi else -1
    block = {line[1:] for line in gi[start:end] if line.startswith("!")} if start >= 0 else set()
    check(block == {e.get("lockfile") for e in entries}, f".gitignore block == sanctioned lockfiles {sorted(block)}")
    for e in entries:
        tag = e.get("lockfile", "?")
        paths = [e.get(k, "") for k in ("dir", "lockfile", "manifest", "workflow")]
        check(all(p.startswith(".github/") for p in paths) and not any("templates/" in p for p in paths),
              f"{tag}: every path under .github/, none under templates/")
        check(e["lockfile"].startswith(e["dir"] + "/") and e["manifest"].startswith(e["dir"] + "/"), f"{tag}: lockfile + manifest live in dir")
        check(e["lockfile"] in tracked, f"{tag}: lockfile is committed")
        wf = yaml.safe_load((HUB / e["workflow"]).read_text(encoding="utf-8"))
        on = wf.get("on") or wf.get(True) or {}
        check("workflow_call" in on, f"{tag}: {e['workflow']} is a reusable workflow (on: workflow_call)")
        check(e["dir"] in (HUB / e["workflow"]).read_text(encoding="utf-8"), f"{tag}: the workflow runs the runtime in {e['dir']}")
        pkg = json.loads((HUB / e["manifest"]).read_text(encoding="utf-8"))
        loose = {k: v for s in ("dependencies", "devDependencies") for k, v in (pkg.get(s) or {}).items()
                 if not re.fullmatch(r"\d+\.\d+\.\d+", str(v))}
        check(not loose, f"{tag}: the manifest pins every dependency exactly {loose or ''}")
        check(("npm", "/" + e["dir"]) in declared, f"{tag}: sanctioned_dependabot has npm /{e['dir']}")
        # `.github/site-quality.yml` (the caller's config) is fine; the runtime dir is not.
        check(re.search(re.escape(e["dir"]) + r"(?![\w.-])", fanout) is None, f"{tag}: tools/fanout.sh never copies {e['dir']}")
    stray = sorted(t for t in tracked if t.startswith("templates/") and Path(t).name in LOCKS)
    check(not stray, f"no lockfile under templates/ {stray or ''}")


def mini_hub(root: Path, with_dependabot: bool = True) -> Path:
    """A throwaway repo shaped like the hub: the real contract, a sanctioned
    runtime, an unsanctioned tool with its own lockfile, a workflow using npm ci."""
    root.mkdir(parents=True)
    (root / "specs").mkdir()
    shutil.copy(HUB / "specs" / "QUALITY.contract.yml", root / "specs" / "QUALITY.contract.yml")
    qdefs = yaml.safe_load((root / "specs" / "QUALITY.contract.yml").read_text())["definitions"]
    e = qdefs["sanctioned_lockfiles"][0]
    for rel in (e["lockfile"], e["manifest"], e["workflow"]):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(HUB / rel, root / rel)
    updates = [{"package-ecosystem": "github-actions", "directory": "/"}]
    if with_dependabot:
        updates += [dict(x) for x in qdefs["sanctioned_dependabot"]]
    (root / ".github" / "dependabot.yml").write_text(yaml.safe_dump({"version": 2, "updates": updates}))
    (root / "tools").mkdir()
    (root / "tools" / "package.json").write_text(json.dumps({"dependencies": {"left-pad": "1.3.0"}}))
    (root / "tools" / "package-lock.json").write_text("{}")
    git(root, "init", "-q")
    git(root, "add", "-A", "-f")
    return root


def t_conformance(tmp: Path) -> None:
    print("tools/conformance.py UPS-QA-40 honours the exception in the hub only")
    import conformance as c
    qa40 = c._always_latest
    hub = mini_hub(tmp / "hub")
    git(hub, "rm", "-q", "--cached", "tools/package-lock.json")
    res, detail = qa40(c.Repo(hub, hub), ["site"])
    check(res is True, f"hub with its sanctioned lockfile + Dependabot entry passes {detail!r}")
    nodep = mini_hub(tmp / "hub-nodep", with_dependabot=False)
    git(nodep, "rm", "-q", "--cached", "tools/package-lock.json")
    res, detail = qa40(c.Repo(nodep, nodep), ["site"])
    check(res is False and "Dependabot" in detail, f"hub without the Dependabot entry fails ({detail})")
    other = mini_hub(tmp / "hub-other")
    res, detail = qa40(c.Repo(other, other), ["site"])
    check(res is False and "committed lockfile" in detail, f"an unsanctioned lockfile in the hub still fails ({detail})")
    member = mini_hub(tmp / "member")
    git(member, "rm", "-q", "--cached", "tools/package-lock.json")
    res, detail = qa40(c.Repo(member, hub), ["site"])
    check(res is False and "committed lockfile" in detail, f"a member repo with the same paths fails ({detail})")


def t_unpin(tmp: Path) -> None:
    print("tools/unpin-deps.sh keeps the sanctioned runtime in the hub only")
    script = HUB / "tools" / "unpin-deps.sh"
    hub = mini_hub(tmp / "unpin-hub")
    e = yaml.safe_load((hub / "specs" / "QUALITY.contract.yml").read_text())["definitions"]["sanctioned_lockfiles"][0]
    before_pkg = (hub / e["manifest"]).read_text()
    before_wf = (hub / e["workflow"]).read_text()
    out = subprocess.run(["bash", str(script), str(hub)], capture_output=True, text=True)
    check(out.returncode == 0, f"unpin-deps.sh exits 0 on the hub {out.stderr.strip()[-200:]!r}")
    tracked = set(git(hub, "ls-files").splitlines())
    check(e["lockfile"] in tracked, "hub: sanctioned lockfile kept")
    check((hub / e["manifest"]).read_text() == before_pkg, "hub: sanctioned manifest keeps its exact pins")
    check((hub / e["workflow"]).read_text() == before_wf, "hub: sanctioned workflow keeps `npm ci` and its lockfile cache")
    check("tools/package-lock.json" not in tracked, "hub: an unsanctioned lockfile is still removed")
    check(json.loads((hub / "tools/package.json").read_text())["dependencies"]["left-pad"] == "*", "hub: an unsanctioned manifest is still unpinned")
    gi = (hub / ".gitignore").read_text().splitlines()
    check(bool(gi) and gi[-1] == "!" + e["lockfile"], "hub: .gitignore re-allows the sanctioned lockfile after the patterns")
    member = mini_hub(tmp / "unpin-member")
    git(member, "rm", "-q", "--cached", "specs/QUALITY.contract.yml")
    (member / "specs" / "QUALITY.contract.yml").unlink()
    out = subprocess.run(["bash", str(script), str(member)], capture_output=True, text=True)
    tracked = set(git(member, "ls-files").splitlines())
    check(out.returncode == 0 and e["lockfile"] not in tracked, "member repo: the same lockfile is removed")
    check(json.loads((member / e["manifest"]).read_text())["dependencies"].get("axe-core") == "*", "member repo: the same manifest is unpinned")
    check("npm ci" not in (member / e["workflow"]).read_text(), "member repo: npm ci becomes npm install")


def main() -> int:
    contract = yaml.safe_load((HUB / "specs" / "QUALITY.contract.yml").read_text(encoding="utf-8"))
    specs = {r["id"]: r for r in yaml.safe_load((HUB / "_data" / "specs.yml").read_text(encoding="utf-8"))["requirements"]}
    t_applies(contract, specs)
    t_binds(contract, specs)
    t_sanctioned(contract["definitions"])
    with tempfile.TemporaryDirectory() as tmp:
        t_conformance(Path(tmp))
        t_unpin(Path(tmp))
    print(f"\n{'FAIL' if FAILS else 'PASS'}: {len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
