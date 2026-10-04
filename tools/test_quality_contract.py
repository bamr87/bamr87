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
               3. The hub-only UPS-QA-40/41 + UPS-REPO-07 exception (`sanctioned_lockfiles`,
                  `sanctioned_dependabot`) is well-formed: under .github/, never
                  under templates/, a reusable workflow's runtime, exact pins, a
                  committed lockfile, a matching Dependabot entry, the generated
                  .gitignore block, and never fanned out.
               4. tools/conformance.py (UPS-QA-40, UPS-REPO-07, UPS-QA-41) and
                  tools/unpin-deps.sh honour the exception in the hub and nowhere
                  else, including fleet-conformance's layout (repo at `.`, hub at
                  `.fleet-hub`), on throwaway repos.
               5. `rollout: warn` in QUALITY.contract.yml reaches run_checks().
               6. tools/sanctioned_lockfiles.py, the one parser, reports malformed
                  YAML/JSON as messages, and every caller goes through it.
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


HUB_ORIGIN = "https://github.com/bamr87/bamr87"


def mini_hub(root: Path, with_dependabot: bool = True, origin: str | None = HUB_ORIGIN) -> Path:
    """A throwaway repo shaped like the hub: the real contract, a sanctioned
    runtime, an unsanctioned tool with its own lockfile, a workflow using npm ci,
    and (by default) the hub's origin remote, which is what makes it the hub."""
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
    if origin:
        git(root, "remote", "add", "origin", origin)
    git(root, "add", "-A", "-f")
    return root


def separate_hub(root: Path, contract: str | None = None) -> Path:
    """A hub checkout at a different path, as fleet-conformance's `.fleet-hub`.
    Its contract is deliberately NOT the checked repo's: the list must come from
    the checked repo."""
    (root / "specs").mkdir(parents=True)
    if contract is not None:
        (root / "specs" / "QUALITY.contract.yml").write_text(contract)
    return root


def lock_rules(c, repo: Path, hub: Path) -> dict:
    r = c.Repo(repo, hub)
    return {rid: c.CHECKS[rid](r, ["site"]) for rid in ("UPS-QA-40", "UPS-REPO-07", "UPS-QA-41")}


def t_conformance(tmp: Path) -> None:
    print("tools/conformance.py: QA-40 / REPO-07 / QA-41 honour the exception in the hub only (CI layout)")
    import conformance as c
    fleet_hub = separate_hub(tmp / "fleet-hub", contract="definitions: {}\n")

    hub = mini_hub(tmp / "hub")
    git(hub, "rm", "-q", "--cached", "tools/package-lock.json")
    res = lock_rules(c, hub, fleet_hub)
    for rid in ("UPS-QA-40", "UPS-REPO-07", "UPS-QA-41"):
        check(res[rid][0] is True, f"hub at . with the hub checkout elsewhere: {rid} passes {res[rid][1]!r}")
    res = lock_rules(c, hub, hub)
    check(all(v[0] is True for v in res.values()), "hub checking itself in place (path == hub): all three pass")

    nodep = mini_hub(tmp / "hub-nodep", with_dependabot=False)
    git(nodep, "rm", "-q", "--cached", "tools/package-lock.json")
    res = lock_rules(c, nodep, fleet_hub)
    check(res["UPS-QA-40"][0] is False and "committed lockfile" in res["UPS-QA-40"][1], f"hub without the Dependabot entry: QA-40 fails ({res['UPS-QA-40'][1]})")
    check(res["UPS-REPO-07"][0] is False, f"hub without the Dependabot entry: REPO-07 fails ({res['UPS-REPO-07'][1]})")
    check(res["UPS-QA-41"][0] is False and "sanctioned_dependabot" in res["UPS-QA-41"][1], f"hub without the Dependabot entry: QA-41 names it ({res['UPS-QA-41'][1]})")

    other = mini_hub(tmp / "hub-other")
    res = lock_rules(c, other, fleet_hub)
    check(res["UPS-QA-40"][0] is False and res["UPS-REPO-07"][0] is False,
          f"an unsanctioned lockfile in the hub still fails QA-40 and REPO-07 ({res['UPS-QA-40'][1]}; {res['UPS-REPO-07'][1]})")

    member = mini_hub(tmp / "member", origin="https://github.com/bamr87/some-site.git")
    git(member, "rm", "-q", "--cached", "tools/package-lock.json")
    res = lock_rules(c, member, fleet_hub)
    check(res["UPS-QA-40"][0] is False and res["UPS-REPO-07"][0] is False,
          "a member repo with a copy of the contract and the same paths fails QA-40 and REPO-07")
    check(res["UPS-QA-41"][0] is True, "a member repo's QA-41 is not judged on the hub exception")

    bad = mini_hub(tmp / "hub-bad-contract")
    git(bad, "rm", "-q", "--cached", "tools/package-lock.json")
    (bad / "specs" / "QUALITY.contract.yml").write_text("definitions:\n  sanctioned_lockfiles: [\n")
    res = lock_rules(c, bad, fleet_hub)
    check(res["UPS-QA-40"][0] is False, "a malformed contract grants nothing (QA-40 fails)")
    check(res["UPS-QA-41"][0] is False and "not valid YAML" in res["UPS-QA-41"][1], f"a malformed contract is named by QA-41 ({res['UPS-QA-41'][1]})")

    # The real CLI in fleet-conformance's layout: the repo at `.`, the hub nested at
    # `.fleet-hub` (untracked), `check . --hub .fleet-hub`.
    cli = mini_hub(tmp / "cli")
    git(cli, "rm", "-q", "--cached", "tools/package-lock.json")
    (cli / ".fleet-hub").symlink_to(HUB, target_is_directory=True)
    out = subprocess.run([sys.executable, str(HUB / "tools" / "conformance.py"), "check", ".", "--hub", ".fleet-hub",
                          "--tier", "active", "--kinds", "site", "--json"], cwd=cli, capture_output=True, text=True)
    try:
        failing = {f["id"]: f["detail"] for f in json.loads(out.stdout)["failing"]}
    except (json.JSONDecodeError, KeyError):
        failing = {"<no json>": out.stderr[-300:]}
    check("<no json>" not in failing, f"conformance.py check . --hub .fleet-hub runs {failing.get('<no json>', '')!r}")
    for rid in ("UPS-QA-40", "UPS-REPO-07", "UPS-QA-41"):
        check(rid not in failing, f"CI layout: {rid} not failing {failing.get(rid, '')!r}")


def t_rollout(tmp: Path) -> None:
    print("tools/conformance.py: `rollout: warn` in QUALITY.contract.yml softens a fail to a warning")
    import conformance as c
    hub = separate_hub(tmp / "rollout-hub", contract=yaml.safe_dump({"rules": {"UPS-QA-60": {"rollout": "warn"}, "UPS-QA-61": {}}}))
    repo = tmp / "rollout-repo"
    repo.mkdir()
    git(repo, "init", "-q")
    r = c.Repo(repo, hub)
    marks = c.quality_warn_only(r)
    check(set(marks) == {"UPS-QA-60"}, f"quality_warn_only reads the QUALITY contract's markers {sorted(marks)}")
    check("QUALITY.contract.yml" in marks.get("UPS-QA-60", ""), "the warning names QUALITY.contract.yml")
    saved = {k: c.CHECKS.get(k) for k in ("UPS-QA-60", "UPS-QA-61")}
    try:
        c.CHECKS["UPS-QA-60"] = c.CHECKS["UPS-QA-61"] = lambda r, k: (False, "synthetic fail")
        specs = {"requirements": [{"id": rid, "level": "SHOULD", "applies": ["site"], "area": "QA"} for rid in ("UPS-QA-60", "UPS-QA-61")]}
        res = c.run_checks(r, ["site"], "active", specs)
    finally:
        for k, v in saved.items():
            if v is None:
                c.CHECKS.pop(k, None)
            else:
                c.CHECKS[k] = v
    check([w["id"] for w in res["warnings"]] == ["UPS-QA-60"], f"the marked rule is reported as a warning {[w['id'] for w in res['warnings']]}")
    check([f["id"] for f in res["failing"]] == ["UPS-QA-61"], f"an unmarked rule still fails {[f['id'] for f in res['failing']]}")
    src = (HUB / "tools" / "conformance.py").read_text(encoding="utf-8")
    body = src[src.index("def quality_warn_only"):src.index("def run_checks")]
    check(re.search(r"\b(?:d|defs)(?:\[|\.get\()", body) is None, "the QUALITY reader never uses the WORK names `d`/`defs` (#328 guard)")


def t_helper(tmp: Path) -> None:
    print("tools/sanctioned_lockfiles.py: malformed inputs give one clear message, never a traceback")
    import sanctioned_lockfiles as sl
    base = mini_hub(tmp / "helper")
    check(sl.drift_problems(base) == [".gitignore: no `# BEGIN sanctioned_lockfiles` … `# END sanctioned_lockfiles` block for the lockfiles in specs/QUALITY.contract.yml"],
          f"a mini hub without the .gitignore block reports exactly that {sl.drift_problems(base)}")
    cases = {
        "specs/QUALITY.contract.yml": ("definitions: [unclosed\n", "not valid YAML"),
        ".github/dependabot.yml": ("updates:\n  - {package-ecosystem: npm\n", "not valid YAML"),
        ".github/site-quality/package.json": ('{"dependencies": {"axe-core": "4.13.0",}}', "not valid JSON"),
    }
    for rel, (text, want) in cases.items():
        root = tmp / ("helper-" + rel.replace("/", "_"))
        shutil.copytree(base, root)
        (root / rel).write_text(text)
        probs = sl.drift_problems(root)
        check(any(p.startswith(rel) and want in p for p in probs), f"malformed {rel}: {probs}")
        out = subprocess.run([sys.executable, str(HUB / "tools" / "sanctioned_lockfiles.py"), "check", str(root)], capture_output=True, text=True)
        check(out.returncode == 1 and "Traceback" not in out.stderr, f"`sanctioned_lockfiles.py check` on malformed {rel}: exit 1, no traceback")
    root = tmp / "helper-loose"
    shutil.copytree(base, root)
    (root / ".github/site-quality/package.json").write_text('{"dependencies": {"axe-core": "^4.13.0"}}')
    check(any("loose: axe-core@^4.13.0" in p for p in sl.drift_problems(root)), "a loose pin in the sanctioned manifest is reported")
    root = tmp / "helper-templates"
    shutil.copytree(base, root)
    cp = root / "specs/QUALITY.contract.yml"
    cp.write_text(cp.read_text().replace("lockfile: .github/site-quality/package-lock.json", "lockfile: templates/x/package-lock.json"))
    check(any("never under templates/" in p for p in sl.drift_problems(root)), "an entry under templates/ is reported")
    out = subprocess.run([sys.executable, str(HUB / "tools" / "sanctioned_lockfiles.py"), "paths", str(base / "specs")], capture_output=True, text=True)
    check(out.returncode == 0, "`paths` on a directory without a contract prints nothing and exits 0")
    drift = (HUB / "tools" / "check-drift.sh").read_text(encoding="utf-8")
    unpin = (HUB / "tools" / "unpin-deps.sh").read_text(encoding="utf-8")
    conf = (HUB / "tools" / "conformance.py").read_text(encoding="utf-8")
    check("import sanctioned_lockfiles" in drift and "sanctioned_lockfiles.py\" paths" in unpin and "import sanctioned_lockfiles" in conf,
          "check-drift (j), unpin-deps.sh and conformance.py all go through tools/sanctioned_lockfiles.py")
    check("import yaml" not in unpin and "qdefs" not in unpin + drift and 'open(os.path.join(root, "specs/QUALITY.contract.yml")' not in drift,
          "neither shell tool parses the contract on its own any more")


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
    member = mini_hub(tmp / "unpin-member", origin="https://github.com/bamr87/some-site")
    out = subprocess.run(["bash", str(script), str(member)], capture_output=True, text=True)
    tracked = set(git(member, "ls-files").splitlines())
    check(out.returncode == 0 and e["lockfile"] not in tracked, "member repo (even with a copy of the contract): the same lockfile is removed")
    check(json.loads((member / e["manifest"]).read_text())["dependencies"].get("axe-core") == "*", "member repo: the same manifest is unpinned")
    check("npm ci" not in (member / e["workflow"]).read_text(), "member repo: npm ci becomes npm install")
    bad = mini_hub(tmp / "unpin-bad")
    (bad / "specs" / "QUALITY.contract.yml").write_text("definitions: [\n")
    out = subprocess.run(["bash", str(script), str(bad)], capture_output=True, text=True)
    tracked = set(git(bad, "ls-files").splitlines())
    check(out.returncode == 2 and e["lockfile"] in tracked and "not valid YAML" in out.stderr,
          f"hub with a malformed contract: unpin-deps stops (exit 2) and removes nothing ({out.returncode}, {out.stderr.strip()[-120:]!r})")


def main() -> int:
    contract = yaml.safe_load((HUB / "specs" / "QUALITY.contract.yml").read_text(encoding="utf-8"))
    specs = {r["id"]: r for r in yaml.safe_load((HUB / "_data" / "specs.yml").read_text(encoding="utf-8"))["requirements"]}
    t_applies(contract, specs)
    t_binds(contract, specs)
    t_sanctioned(contract["definitions"])
    with tempfile.TemporaryDirectory() as tmp:
        t_conformance(Path(tmp))
        t_rollout(Path(tmp))
        t_helper(Path(tmp))
        t_unpin(Path(tmp))
    print(f"\n{'FAIL' if FAILS else 'PASS'}: {len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
