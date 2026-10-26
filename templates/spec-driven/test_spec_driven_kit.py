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
SKILLS = ["specify", "clarify", "plan", "tasks", "implement", "evolve"]
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
    for rel in [*(f"tools/{t}" for t in TOOLS), "tools/evolve_audit.py", "hooks/gate-check.sh", "hooks/hooks.json",
                ".claude-plugin/plugin.json", *(f"skills/{s}/SKILL.md" for s in SKILLS), "agents/backlog-triager.md",
                "fleet-kit.sh", "workflows/spec-gate.yml", "specs/_template/spec.md",
                "specs/_template/plan.md", "specs/_template/tasks.md", "BACKLOG.template.md",
                "constitution.template.md", "review-questions.example.json", "VERSION", "README.md"]:
        check((KIT / rel).is_file(), f"{rel} exists")
    check(os.access(KIT / "fleet-kit.sh", os.X_OK) and os.access(KIT / "hooks" / "gate-check.sh", os.X_OK), "resolver and hook are executable")
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
    check("CLAUDE_PLUGIN_ROOT" in hook, "hook prefers the plugin's tools")
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


def test_plugin() -> None:
    print("plugin + marketplace")
    version = re.search(r"^version: (\S+)$", (KIT / "VERSION").read_text(encoding="utf-8"), re.MULTILINE).group(1)
    manifest = json.loads((KIT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    check(manifest.get("name") == "spec-driven", "plugin.json name is spec-driven")
    check(manifest.get("version") == version, f"plugin.json version == VERSION ({manifest.get('version')} vs {version})")
    check(isinstance(manifest.get("author"), dict) and manifest["author"].get("name"), "plugin.json author is an object with a name")
    mp = HUB / ".claude-plugin" / "marketplace.json"
    check(mp.is_file(), "hub root has .claude-plugin/marketplace.json")
    if mp.is_file():
        market = json.loads(mp.read_text(encoding="utf-8"))
        check(market.get("name") == "bamr87" and isinstance(market.get("owner"), dict), "marketplace is named bamr87 with an owner object")
        entry = next((p for p in market.get("plugins", []) if p.get("name") == "spec-driven"), None)
        check(entry is not None and entry.get("source") == "./templates/spec-driven", "marketplace lists spec-driven at ./templates/spec-driven")
        check(entry is not None and "version" not in entry, "marketplace entry carries no version (plugin.json owns it)")
    hooks = json.loads((KIT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    post = (hooks.get("hooks") or {}).get("PostToolUse") or []
    cmd = post[0]["hooks"][0]["command"] if post and post[0].get("hooks") else ""
    check(bool(post) and post[0].get("matcher") == "Write|Edit", "hooks.json wires PostToolUse on Write|Edit under the `hooks` wrapper")
    check("${CLAUDE_PLUGIN_ROOT}/hooks/gate-check.sh" in cmd, "hooks.json runs the kit's gate-check.sh from the plugin root")
    for s in SKILLS:
        text = (KIT / "skills" / s / "SKILL.md").read_text(encoding="utf-8")
        fm = text.split("---", 2)[1] if text.startswith("---") else ""
        check(re.search(rf"^name: {s}$", fm, re.MULTILINE) is not None, f"skills/{s} frontmatter name")
        check("description:" in fm, f"skills/{s} has a description")
        check(f"/spec-driven:" in text, f"skills/{s} refers to the namespaced commands")
    evolve = (KIT / "skills" / "evolve" / "SKILL.md").read_text(encoding="utf-8")
    check("disable-model-invocation: true" in evolve, "evolve is user-invoked only")
    for tool in ("spec_validator.py", "backlog_lint.py", "next_backlog_id.py", "pick_backlog_item.py", "evolve_audit.py"):
        used = any(tool in (KIT / "skills" / s / "SKILL.md").read_text(encoding="utf-8") for s in SKILLS)
        check(used, f"a skill runs tools/{tool} via ${{CLAUDE_PLUGIN_ROOT}}")
    agent = (KIT / "agents" / "backlog-triager.md").read_text(encoding="utf-8")
    check(agent.startswith("---") and "name: backlog-triager" in agent, "agents/backlog-triager.md has frontmatter")
    caller = (KIT / "workflows" / "spec-gate.yml").read_text(encoding="utf-8")
    check("uses: bamr87/bamr87/.github/workflows/spec-gate.yml@v" in caller, "caller pins the reusable gate to a major tag")
    check((HUB / ".github" / "workflows" / "spec-gate.yml").is_file(), "hub has the reusable spec-gate.yml")


def test_resolver_and_audit() -> None:
    print("resolver + discovery audit (temp hub)")
    with tempfile.TemporaryDirectory() as tmp:
        hub = Path(tmp) / "hub"
        (hub / "templates").mkdir(parents=True)
        shutil.copytree(KIT, hub / "templates" / "spec-driven", ignore=shutil.ignore_patterns("__pycache__", "archive"))
        leaf = hub / "projects" / "leaf"
        leaf.mkdir(parents=True)
        run(["git", "init", "-q"], leaf)
        shutil.copy2(KIT / "fleet-kit.sh", leaf / "fleet-kit.sh")
        r = run(["bash", "fleet-kit.sh"], leaf)
        check(r.returncode == 0 and Path(r.stdout.strip()).resolve() == (hub / "templates" / "spec-driven").resolve(), f"resolver finds the parent hub checkout ({r.stdout.strip()} {r.stderr.strip()[:80]})")
        r = run(["bash", "fleet-kit.sh"], leaf, {"FLEET_KIT_DIR": str(KIT)})
        check(r.returncode == 0 and r.stdout.strip() == str(KIT), "FLEET_KIT_DIR wins")
        r = run(["bash", "fleet-kit.sh"], leaf, {"FLEET_HUB": str(hub)})
        check(r.returncode == 0 and r.stdout.strip().endswith("templates/spec-driven"), "FLEET_HUB wins")
        r = run(["bash", "fleet-kit.sh"], leaf, {"FLEET_KIT_DIR": str(Path(tmp) / "nope")})
        check(r.returncode != 0, "a bad FLEET_KIT_DIR fails loudly")
        # discovery audit: a TODO and a missing doc become bullets; dry-run writes nothing.
        seed(leaf)
        (leaf / "AGENTS.md").write_text("# leaf\n\nRead docs/architecture.md first.\n", encoding="utf-8")
        (leaf / "src").mkdir()
        (leaf / "src" / "a.py").write_text("x = 1  # TODO: make this configurable\n", encoding="utf-8")
        run(["git", "add", "-A"], leaf)
        before = (leaf / "BACKLOG.md").read_text(encoding="utf-8")
        py = sys.executable
        r = run([py, str(KIT / "tools" / "evolve_audit.py"), "--root", str(leaf), "--dry-run"], HUB)
        check(r.returncode == 0 and "Resolve TODO in src/a.py" in r.stdout and "docs/architecture.md" in r.stdout, f"audit finds the TODO and the missing doc ({last(r)})")
        check((leaf / "BACKLOG.md").read_text(encoding="utf-8") == before, "--dry-run leaves BACKLOG.md alone")
        r = run([py, str(KIT / "tools" / "evolve_audit.py"), "--root", str(leaf)], HUB)
        after = (leaf / "BACKLOG.md").read_text(encoding="utf-8")
        check(r.returncode == 0 and "Resolve TODO in src/a.py" in after and "docs/architecture.md" in after and after.count("- **BL-") - before.count("- **BL-") >= 2, f"audit appends the planted items ({r.stdout.splitlines()[0] if r.stdout else r.stderr[:80]})")
        check(run([py, str(KIT / "tools" / "backlog_lint.py"), "--root", str(leaf)], HUB).returncode == 0, "appended items pass backlog_lint")
        r = run([py, str(KIT / "tools" / "evolve_audit.py"), "--root", str(leaf)], HUB)
        check("already in BACKLOG" in r.stdout and (leaf / "BACKLOG.md").read_text(encoding="utf-8") == after, "a second run is idempotent")
        # plugin-mode hook: tools resolved from CLAUDE_PLUGIN_ROOT, none in the repo.
        shutil.rmtree(leaf / "tools")
        env = {"CLAUDE_PROJECT_DIR": str(leaf), "CLAUDE_PLUGIN_ROOT": str(KIT)}
        payload = json.dumps({"tool_input": {"file_path": str(leaf / "BACKLOG.md")}})
        r = run(["bash", str(KIT / "hooks" / "gate-check.sh")], leaf, env, payload)
        check(r.returncode == 0 and r.stdout.strip() == "", f"plugin-mode hook is silent when green ({r.stdout.strip()[:80]})")
        with (leaf / "BACKLOG.md").open("a", encoding="utf-8") as fh:
            fh.write("- **BL-20261003-99** — *feature, low* — dup.\n- **BL-20261003-99** — *feature, low* — dup. _Surfaced in:_ x.\n")
        r = run(["bash", str(KIT / "hooks" / "gate-check.sh")], leaf, env, payload)
        out = r.stdout.strip()
        check(out.startswith("{") and json.loads(out).get("decision") == "block", "plugin-mode hook blocks on a failing gate")


def target_report(repo: Path) -> int:
    print(f"UPS-WORK-07: {repo}")
    tracked = run(["git", "ls-files"], repo).stdout.split()
    hits = [p for p in tracked if Path(p).name in TOOLS]
    for p in hits:
        same = (repo / p).read_bytes() == (KIT / "tools" / Path(p).name).read_bytes()
        archived = [a.name for a in (KIT / "archive").glob(f"{Path(p).stem}-*") if a.read_bytes() == (repo / p).read_bytes()]
        check(same, f"{p} == kit" + (f" (matches {archived[0]})" if archived and not same else ""))
    resolver = [p for p in tracked if Path(p).name == "fleet-kit.sh"]
    for p in resolver:
        check((repo / p).read_bytes() == (KIT / "fleet-kit.sh").read_bytes(), f"{p} == kit")
    wf = "".join((repo / p).read_text(encoding="utf-8", errors="ignore") for p in tracked if p.startswith(".github/workflows/"))
    by_ref = "bamr87/bamr87/.github/workflows/spec-gate.yml@" in wf
    settings = repo / ".claude" / "settings.json"
    plugin = settings.is_file() and "spec-driven@bamr87" in settings.read_text(encoding="utf-8", errors="ignore")
    check(bool(hits) or (by_ref and bool(resolver)), "vendored tools, or the reusable gate + resolver (by reference)")
    print(f"  mode: {'vendored' if hits else 'by reference' if by_ref else 'none'}; spec-gate.yml caller: {by_ref}; plugin enabled: {plugin}")
    check((repo / "BACKLOG.md").is_file(), "BACKLOG.md exists")
    check(any(repo.glob("specs/[0-9][0-9][0-9]-*/spec.md")), ">= 1 spec package")
    return 1 if FAILS else 0


def main(argv: list[str]) -> int:
    if "--target" in argv:
        return target_report(Path(argv[argv.index("--target") + 1]).resolve())
    test_layout()
    test_plugin()
    test_round_trip()
    test_resolver_and_audit()
    print(f"\n{'FAIL' if FAILS else 'PASS'}: {len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
