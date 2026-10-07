#!/usr/bin/env python3
"""Fixture tests for the spec-driven kit (templates/spec-driven/).

    python3 templates/spec-driven/test_spec_driven_kit.py                 # test the kit
    python3 templates/spec-driven/test_spec_driven_kit.py --target <repo> # report a repo's UPS-WORK-07 byte-identity

Stdlib only. The round trip runs in a temp git repo: seed the kit, both gates
pass, a duplicate id fails the lint, the hook blocks, a review question warns.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parent
HUB = KIT.parent.parent
TOOLS = ["spec_validator.py", "backlog_lint.py", "next_backlog_id.py", "pick_backlog_item.py"]
CACHES = {"__pycache__", ".ruff_cache", ".pytest_cache", ".mypy_cache"}
FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        FAILS.append(msg)


def run(args: list[str], cwd: Path, env: dict | None = None, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, input=stdin, capture_output=True, text=True, check=False,
                          env={**os.environ, **(env or {})}, timeout=120)


def last(r: subprocess.CompletedProcess) -> str:
    lines = r.stdout.strip().splitlines()
    return lines[-1][-80:] if lines else ""


def contract_tools() -> list[str]:
    """spec_driven_tools from specs/WORK.contract.yml, when the hub carries it (no YAML dependency)."""
    c = HUB / "specs" / "WORK.contract.yml"
    if not c.is_file():
        return TOOLS
    m = re.search(r"^\s*spec_driven_tools:\s*\[([^\]]*)\]", c.read_text(encoding="utf-8"), re.MULTILINE)
    return [t.strip() for t in m.group(1).split(",")] if m else TOOLS


def test_layout() -> None:
    print("layout")
    for rel in [*(f"tools/{t}" for t in TOOLS), "hooks/gate-check.sh", "specs/_template/spec.md",
                "specs/_template/plan.md", "specs/_template/tasks.md", "BACKLOG.template.md",
                "constitution.template.md", "review-questions.example.json", "VERSION", "README.md"]:
        check((KIT / rel).is_file(), f"{rel} exists")
    check(sorted(contract_tools()) == sorted(TOOLS), "contract spec_driven_tools == the kit's four tools")
    version = (KIT / "VERSION").read_text(encoding="utf-8")
    check(re.search(r"^kit: spec-driven$", version, re.MULTILINE) is not None, "VERSION names the kit")
    check(re.search(r"^version: \d+\.\d+\.\d+$", version, re.MULTILINE) is not None, "VERSION has a semver")
    files = re.search(r"^files: (.*)$", version, re.MULTILINE).group(1)
    for p in KIT.rglob("*"):
        rel = p.relative_to(KIT).as_posix()
        if p.is_file() and not CACHES & set(p.relative_to(KIT).parts) and not rel.startswith("archive/") and p.name not in {"VERSION", "README.md", Path(__file__).name}:
            check(rel in files, f"VERSION files: lists {rel}")
    for origin in ("law-ai", "gitorio"):
        for t in TOOLS:
            stem = t[:-3]
            check((KIT / "archive" / f"{stem}-0.0.0-{origin}.py").is_file(), f"archive has {stem}-0.0.0-{origin}.py")
        check((KIT / "archive" / f"gate-check-0.0.0-{origin}.sh").is_file(), f"archive has gate-check-0.0.0-{origin}.sh")
    readme = (KIT / "README.md").read_text(encoding="utf-8")
    for t in TOOLS:
        check(f"`tools/{t}`" in readme, f"README names {t}")
    for p in [*(KIT / "tools").glob("*.py")]:
        src = p.read_text(encoding="utf-8")
        check("templates/spec-driven/tools/" in src, f"{p.name} names its fleet copy")
        check("--root" in src, f"{p.name} takes --root")
    hook = (KIT / "hooks" / "gate-check.sh").read_text(encoding="utf-8")
    check(hook.startswith("#!/usr/bin/env bash"), "hook has a bash shebang")
    check("scripts" in hook and "tools" in hook, "hook finds tools/ or scripts/")
    backlog = (KIT / "BACKLOG.template.md").read_text(encoding="utf-8")
    for h in ("## Open", "## Claimed", "## Done"):
        check(re.search(rf"^{h}$", backlog, re.MULTILINE) is not None, f"BACKLOG template has {h}")
    check("{{" not in backlog, "BACKLOG template has no {{ placeholders")
    data = json.loads((KIT / "review-questions.example.json").read_text(encoding="utf-8"))
    q = data["questions"][0]
    check(q["answer_marker"] == "who is the stronger", "example review question is law-ai §13")
    check(len(q["hint_groups"]) == 2 and all(q["hint_groups"]), "example has two non-empty hint groups")


SPEC = """# Spec: Demo

- **ID**: 001-demo
- **Status**: {status}

## 2. Users

{users}

## Requirements

- **FR-1**: does a thing.
- **AC-1**: the thing is done.
"""
TASKS = """# Tasks

- [ ] T1 implement FR-1 and check AC-1

## Follow-ups Discovered

_none — justified: fixture_
"""


def seed(root: Path) -> None:
    for t in TOOLS:
        (root / "tools").mkdir(exist_ok=True)
        shutil.copy2(KIT / "tools" / t, root / "tools" / t)
    (root / ".claude" / "hooks").mkdir(parents=True)
    shutil.copy2(KIT / "hooks" / "gate-check.sh", root / ".claude" / "hooks" / "gate-check.sh")
    shutil.copytree(KIT / "specs" / "_template", root / "specs" / "_template")
    (root / "BACKLOG.md").write_text((KIT / "BACKLOG.template.md").read_text(encoding="utf-8").replace("__PROJECT_NAME__", "demo"), encoding="utf-8")


def test_round_trip() -> None:
    print("round trip (temp repo)")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run(["git", "init", "-q"], root)
        seed(root)
        py = sys.executable
        r = run([py, "tools/spec_validator.py"], root)
        check(r.returncode == 0, f"validator passes on a fresh seed (rc={r.returncode} {last(r)})")
        r = run([py, "tools/backlog_lint.py"], root)
        check(r.returncode == 0, f"backlog lint passes on the seeded BACKLOG.md ({last(r)})")
        r = run([py, "tools/next_backlog_id.py", "--date", "20261003"], root)
        check(r.stdout.strip() == "BL-20261003-01", f"id minter starts at -01 ({r.stdout.strip()})")
        bl = (root / "BACKLOG.md").read_text(encoding="utf-8")
        items = ("- **BL-20261003-01** — *feature, low* — a feature. _Surfaced in:_ fixture.\n"
                 "- **BL-20261003-02** — *tech-debt, high* — the debt. _Surfaced in:_ fixture.\n")
        (root / "BACKLOG.md").write_text(bl.replace("## Open\n", "## Open\n\n" + items, 1), encoding="utf-8")
        r = run([py, "tools/backlog_lint.py"], root)
        check(r.returncode == 0, f"lint passes with two items ({last(r)})")
        r = run([py, "tools/next_backlog_id.py", "--date", "20261003"], root)
        check(r.stdout.strip() == "BL-20261003-03", f"id minter skips used ids ({r.stdout.strip()})")
        r = run([py, "tools/pick_backlog_item.py", "--id-only"], root)
        check(r.stdout.strip() == "BL-20261003-02", f"picker takes high tech-debt first ({r.stdout.strip()})")
        r = run([py, str(KIT / "tools" / "pick_backlog_item.py"), "--id-only", "--root", str(root)], HUB)
        check(r.stdout.strip() == "BL-20261003-02", "picker --root works from another cwd")
        run(["git", "add", "-A"], root)
        run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "seed"], root)

        # A spec package; a question file makes a ranking spec warn until it answers.
        spec = root / "specs" / "001-demo"
        spec.mkdir()
        (spec / "plan.md").write_text("# Plan\n\nFR-1\n", encoding="utf-8")
        (spec / "tasks.md").write_text(TASKS, encoding="utf-8")
        (spec / "spec.md").write_text(SPEC.format(status="draft", users="Lawyers rank case law by authority."), encoding="utf-8")
        r = run([py, "tools/spec_validator.py"], root)
        check(r.returncode == 0 and "WARN" not in r.stdout, "no question file: no warning")
        shutil.copy2(KIT / "review-questions.example.json", root / "specs" / "_review_questions.json")
        r = run([py, "tools/spec_validator.py"], root)
        check(r.returncode == 0 and "WARN" in r.stdout, "question file: ranking spec warns, rc 0")
        r = run([py, "tools/spec_validator.py", "--strict"], root)
        check(r.returncode != 0, "--strict makes the warning fatal")
        (spec / "spec.md").write_text(SPEC.format(status="draft", users="Lawyers rank case law by authority; who is the stronger party here: the client."), encoding="utf-8")
        r = run([py, "tools/spec_validator.py", "--strict"], root)
        check(r.returncode == 0, f"answered question passes --strict ({last(r)})")
        r = run([py, str(KIT / "tools" / "spec_validator.py"), "--root", str(root)], HUB)
        check(r.returncode == 0 and "001-demo" in r.stdout, "validator --root works from another cwd")
        (spec / "tasks.md").write_text("# Tasks\n\n- [ ] T1 FR-1\n", encoding="utf-8")
        r = run([py, "tools/spec_validator.py"], root)
        check(r.returncode != 0, "missing AC reference / follow-ups section fails the validator")
        (spec / "tasks.md").write_text(TASKS, encoding="utf-8")

        # Hook: quiet when green, blocks on a duplicate id, ignores files outside the repo.
        hook = ["bash", ".claude/hooks/gate-check.sh"]
        env = {"CLAUDE_PROJECT_DIR": str(root)}
        payload = json.dumps({"tool_input": {"file_path": str(root / "BACKLOG.md")}})
        r = run(hook, root, env, payload)
        check(r.returncode == 0 and r.stdout.strip() == "", "hook is silent when the gates pass")
        with (root / "BACKLOG.md").open("a", encoding="utf-8") as fh:
            fh.write("- **BL-20261003-01** — *feature, low* — duplicate. _Surfaced in:_ fixture.\n")
        r = run([py, "tools/backlog_lint.py"], root)
        check(r.returncode != 0, "duplicate id fails the lint")
        r = run(hook, root, env, payload)
        out = r.stdout.strip()
        check(r.returncode == 0 and out.startswith("{") and json.loads(out).get("decision") == "block", "hook blocks on a failing gate")
        other = json.dumps({"tool_input": {"file_path": "/elsewhere/BACKLOG.md"}})
        check(run(hook, root, env, other).stdout.strip() == "", "hook ignores files outside the project")
        (root / "BACKLOG.md").write_text(bl, encoding="utf-8")
        r = run([py, "tools/backlog_lint.py"], root)
        check(r.returncode != 0, "deleting committed items fails the append-only check")

        # scripts/ layout (law-ai): the hook still finds the tools.
        shutil.move(str(root / "tools"), str(root / "scripts"))
        r = run(hook, root, env, payload)
        check(r.stdout.strip().startswith("{"), "hook finds tools under scripts/")


def target_report(repo: Path) -> int:
    print(f"UPS-WORK-07 byte-identity: {repo}")
    tracked = run(["git", "ls-files"], repo).stdout.split()
    hits = [p for p in tracked if Path(p).name in TOOLS]
    for p in hits:
        same = (repo / p).read_bytes() == (KIT / "tools" / Path(p).name).read_bytes()
        archived = [a.name for a in (KIT / "archive").glob(f"{Path(p).stem}-*") if a.read_bytes() == (repo / p).read_bytes()]
        check(same, f"{p} == kit" + (f" (matches {archived[0]})" if archived and not same else ""))
    check(bool(hits), "repo tracks the spec-driven tools")
    check((repo / "BACKLOG.md").is_file(), "BACKLOG.md exists")
    check(any(repo.glob("specs/[0-9][0-9][0-9]-*/spec.md")), ">= 1 spec package")
    return 1 if FAILS else 0


def main(argv: list[str]) -> int:
    if "--target" in argv:
        return target_report(Path(argv[argv.index("--target") + 1]).resolve())
    test_layout()
    test_round_trip()
    print(f"\n{'FAIL' if FAILS else 'PASS'}: {len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
