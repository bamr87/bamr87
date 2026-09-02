#!/usr/bin/env python3
"""
Fixture + contract tests for the weekly repo-evolution loop: evolution.py (the
deterministic planner) and the .github/workflows/repo-evolution.yml that
consumes its plan.

Guards the invariants that decide whether a scheduled AI loop is a proposal
machine or a nuisance:

  * only OWNED, non-archived SUBMODULES that opted in are selected — an external
    mirror must never receive a pull request from us, whatever the registry says;
  * a repo whose previous pass is still open is skipped, whether recognised by
    branch prefix or by the hidden marker — one draft is a proposal, a stack of
    them is spam;
  * the cap holds and what it drops is REPORTED, never silently truncated;
  * the brief carries the marker first, the fleet's signals, the focus, the
    goals, and the category emphasis — and degrades cleanly without a snapshot;
  * the workflow and _data/fleet.yml agree: the cron matches the declared
    cadence, the caps are wired from the plan (stated once), every command the
    prompt requires is on the allowlist and no publishing command is, the
    checkout keeps no credentials, the PR is a draft with the marker first, and
    no lockfile the fleet policy forbids can ride along.

Deliberately dependency-light — no network, no gh, no pytest. Needs only PyYAML:

    python3 .github/scripts/dash-gen/test_evolution.py
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import evolution as ev  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "repo-evolution.yml"
FLEET = REPO_ROOT / "_data" / "fleet.yml"
REGISTRY = REPO_ROOT / "_data" / "projects.yml"
PROMPT_DIR = REPO_ROOT / ".github" / "evolution"

CHECKS: list[tuple[str, bool]] = []


def check(label: str, ok: bool) -> None:
    CHECKS.append((label, bool(ok)))


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
def entry(name, *, owner="bamr87", auto=True, sub=True, status="active",
          category="dev-tools", stack=("bash",), branch="main") -> dict:
    return {
        "name": name, "slug": name,
        "submodule_path": f"projects/{name}" if sub else None,
        "branch": branch, "repo_url": f"https://github.com/{owner}/{name}",
        "description": f"{name} does things", "stack": list(stack),
        "category": category, "status": status, "auto_evolve": auto,
    }


REGISTRY_FIX = [
    entry("alpha"),
    entry("beta", category="docs", stack=("python", "mkdocs")),
    entry("skills", owner="microsoft"),          # external upstream, opted in by mistake
    entry("old", status="archived"),             # opted in, archived
    entry("nosub", sub=False),                   # opted in, not a submodule
    entry("quiet", auto=False),                  # never opted in
]

CONF_FIX = {
    "generated_at": "2026-09-01T00:00:00Z", "spec_version": "1.0", "checker_version": "0.1.0",
    "repos": [{
        "name": "alpha", "nwo": "bamr87/alpha", "kinds": ["cli"], "tier": "active",
        "checked": 20, "passed": 17, "must_failed": 2, "should_failed": 1, "manual": 40,
        "failing": [
            {"id": "UPS-REPO-16", "level": "SHOULD", "detail": "no CODEOWNERS", "spec": "specs/REPOSITORY.md"},
            {"id": "UPS-REPO-14", "level": "MUST", "detail": "no SECURITY.md", "spec": "specs/REPOSITORY.md"},
            {"id": "UPS-AGENT-03", "level": "MUST", "detail": "CLAUDE.md lacks the kit stamp", "spec": "specs/AGENT-CONTEXT.md"},
        ],
    }],
}

TRIAGE_FIX = {
    "generated_at": "2026-08-25 06:00 UTC",
    "by_repo": [{
        "name": "alpha", "nwo": "bamr87/alpha",
        "attention": {"score": 31, "level": "red", "reasons": ["1 failing workflow(s)", "2 stale PR(s)"]},
        "workflows": {"active": 3, "failing": [
            {"workflow": "CI", "path": ".github/workflows/ci.yml", "conclusion": "failure",
             "run_url": "https://github.com/bamr87/alpha/actions/runs/1", "run_at": "2026-08-24 01:00 UTC"}]},
        "issues": {"open": 2, "stale": 1, "bugs": 1, "items": [
            {"number": 7, "title": "Docs say --foo, CLI has --bar", "labels": ["docs"],
             "age_days": 3, "idle_days": 1, "url": "https://github.com/bamr87/alpha/issues/7"},
            {"number": 9, "title": "Crash on empty input", "labels": ["bug"],
             "age_days": 40, "idle_days": 30, "url": "https://github.com/bamr87/alpha/issues/9"}]},
        "prs": {"open": 2, "draft": 0, "stale": 2, "dependabot": 1, "ci_failing": 1, "items": [
            {"number": 11, "title": "Bump lodash", "author": "dependabot[bot]", "draft": False,
             "ci": "", "idle_days": 20, "url": "https://github.com/bamr87/alpha/pull/11"},
            {"number": 12, "title": "Refactor parser", "author": "someone", "draft": False,
             "ci": "fail", "idle_days": 21, "url": "https://github.com/bamr87/alpha/pull/12"}]},
    }],
}

CFG = ev.load_config(None)  # pure defaults, hub owner bamr87


def fake_gh(answers: dict[str, list[dict] | None]):
    """gh stub keyed on the -R argument."""
    def _gh(cmd):
        nwo = cmd[cmd.index("-R") + 1]
        return answers.get(nwo, [])
    return _gh


def temp_prompt_dir(with_category=True) -> Path:
    d = Path(tempfile.mkdtemp(prefix="evo-prompts-"))
    (d / "evolve-prompt.md").write_text("## Goals\nImprove {{REPO_NAME}} ({{NWO}} @ {{BRANCH}}), "
                                        "{{CATEGORY}}, {{STACK}}, {{STATUS}}: {{DESCRIPTION}}\n")
    if with_category:
        (d / "categories").mkdir()
        (d / "categories" / "dev-tools.md").write_text("## Category emphasis: dev-tools for {{REPO_NAME}}\n")
    return d


# --------------------------------------------------------------------------- #
# selection
# --------------------------------------------------------------------------- #
def test_selection() -> None:
    print("\nselection")
    sel, dropped = ev.select_targets(REGISTRY_FIX, CFG)
    names = [t["name"] for t in sel]
    check("opted-in owned submodules are selected", names == ["alpha", "beta"])
    reasons = {d["name"]: d["reason"] for d in dropped}
    check("external upstream is refused even when opted in", "external" in reasons.get("skills", ""))
    check("archived repo is refused", reasons.get("old") == "archived")
    check("non-submodule is refused", "submodule" in reasons.get("nosub", ""))
    check("a repo that never opted in is not reported as dropped", "quiet" not in reasons)
    check("selected entries carry nwo/branch/category/stack",
          sel[0]["nwo"] == "bamr87/alpha" and sel[0]["branch"] == "main"
          and sel[1]["category"] == "docs" and sel[1]["stack"] == ["python", "mkdocs"])

    capped, dropped = ev.select_targets(REGISTRY_FIX, {**CFG, "max_targets": 1})
    check("cap holds", [t["name"] for t in capped] == ["alpha"])
    check("what the cap drops is reported, not silently truncated",
          any(d["name"] == "beta" and "max_targets" in d["reason"] for d in dropped))

    one, _ = ev.select_targets(REGISTRY_FIX, CFG, target="beta")
    check("--target narrows to one repo", [t["name"] for t in one] == ["beta"])
    none, dropped = ev.select_targets(REGISTRY_FIX, CFG, target="quiet")
    check("--target on a repo that never opted in says so",
          not none and any("not opted in" in d["reason"] for d in dropped))
    none, dropped = ev.select_targets(REGISTRY_FIX, CFG, target="nope")
    check("--target on an unknown name says 'not in the registry'",
          not none and any("not in the registry" in d["reason"] for d in dropped))

    other_owner = {**CFG, "hub_owner": "microsoft"}
    sel, _ = ev.select_targets(REGISTRY_FIX, other_owner)
    check("the owner guard follows hub.repo, not a hardcoded name", [t["name"] for t in sel] == ["skills"])


# --------------------------------------------------------------------------- #
# dedupe
# --------------------------------------------------------------------------- #
def test_dedupe() -> None:
    print("\ndedupe")
    sel, _ = ev.select_targets(REGISTRY_FIX, CFG)
    marker = ev.marker_line(CFG, "bamr87/beta")
    gh = fake_gh({
        "bamr87/alpha": [{"number": 3, "headRefName": "ai-evolution/20260818-1",
                          "body": "no marker", "url": "https://github.com/bamr87/alpha/pull/3"}],
        "bamr87/beta": [{"number": 4, "headRefName": "feature/renamed",
                         "body": f"{marker}\n\nsummary", "url": "https://github.com/bamr87/beta/pull/4"}],
    })
    kept, skipped = ev.dedupe([dict(t) for t in sel], CFG, gh)
    check("an open PR on the branch prefix skips the repo", any(s["name"] == "alpha" for s in skipped))
    check("an open PR recognised by its marker skips the repo even on a renamed branch",
          any(s["name"] == "beta" for s in skipped))
    check("skip reasons name the open PR", all("pull/" in s["reason"] for s in skipped))
    check("nothing left when every target has an open pass", kept == [])

    kept, skipped = ev.dedupe([dict(t) for t in sel], CFG, fake_gh({}))
    check("no open pass → kept, marked clear", [t["name"] for t in kept] == ["alpha", "beta"]
          and all(t["dedupe"] == "clear" for t in kept))

    kept, skipped = ev.dedupe([dict(t) for t in sel], CFG, lambda cmd: None)
    check("gh unavailable → kept and SAID so, never a crash",
          len(kept) == 2 and all(t["dedupe"] == "unavailable" for t in kept) and not skipped)

    kept, skipped = ev.dedupe([dict(t) for t in sel], {**CFG, "skip_when_open_pr": False}, gh)
    check("skip_when_open_pr: false disables the check", len(kept) == 2 and not skipped)


# --------------------------------------------------------------------------- #
# brief
# --------------------------------------------------------------------------- #
def test_brief() -> None:
    print("\nbrief")
    sel, _ = ev.select_targets(REGISTRY_FIX, CFG)
    alpha = sel[0]
    pdir = temp_prompt_dir()
    text = ev.render_brief(alpha, CFG, TRIAGE_FIX, pdir, focus="tighten the CLI docs", now="t")
    lines = text.splitlines()
    check("the hidden marker is the FIRST line", lines[0] == '<!-- repo-evolution key="bamr87/alpha" -->')
    check("registry facts are rendered", "https://github.com/bamr87/alpha" in text and "dev-tools" in text)
    check("attention level + reasons are in the signals", "red" in text and "1 failing workflow(s)" in text)
    check("failing workflow is listed with its path and handed to the doctor's lane",
          ".github/workflows/ci.yml" in text and "fleet doctor" in text)
    check("bug issues are listed before non-bugs",
          text.index("#9 Crash on empty input") < text.index("#7 Docs say --foo"))
    check("dependabot PRs are filtered out of the PR list", "Bump lodash" not in text)
    check("a failing-CI, idle PR is flagged", "#12 Refactor parser" in text and "CI failing" in text)
    check("the operator focus is quoted", "tighten the CLI docs" in text)
    check("placeholders are rendered into the goals template",
          "Improve alpha (bamr87/alpha @ main), dev-tools, bash, active: alpha does things" in text
          and "{{" not in text)
    check("the category emphasis is appended and rendered", "emphasis: dev-tools for alpha" in text)

    no_focus = ev.render_brief(alpha, CFG, TRIAGE_FIX, pdir, focus="", now="t")
    check("no focus → says so instead of leaving a blank", "No operator focus" in no_focus)

    beta = sel[1]  # category docs — no file in the temp dir
    t2 = ev.render_brief(beta, CFG, TRIAGE_FIX, pdir, focus="", now="t")
    check("missing category file degrades to a note, not an error", "No category emphasis file" in t2)
    check("a repo absent from the snapshot is told so", "has no entry for this repository" in t2)

    t3 = ev.render_brief(alpha, CFG, None, pdir, focus="", now="t")
    check("no snapshot at all degrades to a note", "No triage snapshot" in t3)

    t4 = ev.render_brief(alpha, CFG, TRIAGE_FIX, temp_prompt_dir(with_category=False) / "missing", "", "t")
    check("a missing template dir still yields a usable brief", "Brief template" in t4 and lines[0] in t4)

    # Conformance gaps — the Universal Project Standard adoption lane
    check("no conformance snapshot degrades to a note that points at `dash spec check`",
          "No conformance snapshot" in text and "dash spec check" in text)
    t5 = ev.render_brief(alpha, CFG, TRIAGE_FIX, pdir, focus="", now="t", conformance=CONF_FIX)
    check("the conformance section is rendered with the snapshot provenance",
          "## Conformance gaps" in t5 and "_data/conformance.yml" in t5 and "UPS 1.0" in t5)
    check("MUST rows come before SHOULD rows", t5.index("UPS-AGENT-03") < t5.index("UPS-REPO-14") < t5.index("UPS-REPO-16"))
    check("each failing row names its spec file", "`specs/AGENT-CONTEXT.md`" in t5 and "no SECURITY.md" in t5)
    check("the section is declared the agent's own lane (unlike the triage signals)",
          "YOUR lane" in t5 and "_data/references.yml" in t5)
    check("the conformance section sits between signals and focus",
          t5.index("## Signals") < t5.index("## Conformance gaps") < t5.index("## Focus for this run"))
    t6 = ev.render_brief(beta, CFG, TRIAGE_FIX, pdir, focus="", now="t", conformance=CONF_FIX)
    check("a repo absent from the conformance snapshot is told so", "has no entry for this repository — run" in t6)
    plan6, briefs6 = ev.build_plan(REGISTRY_FIX, CFG, TRIAGE_FIX, prompt_dir=pdir, gh=None, now="t", conformance=CONF_FIX)
    check("build_plan threads the snapshot into every brief", any("UPS-AGENT-03" in b for b in briefs6.values()))


# --------------------------------------------------------------------------- #
# plan + config
# --------------------------------------------------------------------------- #
def test_plan_and_config() -> None:
    print("\nplan + config")
    pdir = temp_prompt_dir()
    plan, briefs = ev.build_plan(REGISTRY_FIX, CFG, TRIAGE_FIX, target="all", focus="f",
                                 prompt_dir=pdir, gh=fake_gh({}), now="t")
    check("plan counts the selected targets", plan["count"] == 2 and len(plan["include"]) == 2)
    check("every matrix entry names its brief and marker",
          all(e["brief"] == f"evolution-workorder-{e['name']}.md" and e["marker"].startswith("<!-- repo-evolution")
              for e in plan["include"]))
    check("briefs are keyed by the matrix entry's brief filename",
          set(briefs) == {e["brief"] for e in plan["include"]})
    check("the plan carries the knobs the workflow wires (stated once, in fleet.yml)",
          {"max_parallel", "max_turns", "branch_prefix", "label", "marker"} <= set(plan))
    check("dropped + skipped are reported in the plan", "dropped" in plan and "skipped" in plan)
    json.dumps(plan)
    check("the plan is JSON-serialisable", True)

    plan, briefs = ev.build_plan(REGISTRY_FIX, CFG, TRIAGE_FIX, target="all", prompt_dir=pdir, gh=None, now="t")
    check("gh=None (--no-dedupe / force) skips the open-PR check entirely",
          all(e["dedupe"] == "off" for e in plan["include"]))

    d = Path(tempfile.mkdtemp(prefix="evo-cfg-"))
    (d / "fleet.yml").write_text("hub:\n  repo: acme/hub\nevolution:\n  max_targets: 2\n  signals:\n    max_prs: 1\n")
    cfg = ev.load_config(d / "fleet.yml")
    check("an override MERGES with the defaults", cfg["max_targets"] == 2 and cfg["max_parallel"] == ev.DEFAULTS["max_parallel"])
    check("nested signals merge too", cfg["signals"] == {"max_issues": 8, "max_prs": 1})
    check("hub owner comes from hub.repo", cfg["hub_owner"] == "acme")
    check("a missing config file yields the defaults", ev.load_config(d / "nope.yml")["max_turns"] == ev.DEFAULTS["max_turns"])

    check("owner_repo parses https/.git/ssh forms",
          ev.owner_repo("https://github.com/a/b.git") == "a/b"
          and ev.owner_repo("git@github.com:a/b.git") == "a/b"
          and ev.owner_repo("https://gitlab.com/a/b") is None)


# --------------------------------------------------------------------------- #
# shipped data + prompt material
# --------------------------------------------------------------------------- #
def test_shipped() -> None:
    print("\nshipped registry, fleet.yml, prompt dir")
    cfg = ev.load_config(FLEET)
    fleet = yaml.safe_load(FLEET.read_text(encoding="utf-8"))
    check("_data/fleet.yml declares an `evolution:` block", isinstance(fleet.get("evolution"), dict))
    check("_data/fleet.yml declares schedule.repo_evolution", bool((fleet.get("schedule") or {}).get("repo_evolution")))
    check("caps are sane", cfg["max_targets"] >= 1 and cfg["max_parallel"] >= 1 and cfg["max_turns"] >= 30)
    for tok in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"):
        used = next((t.get("used_by") or [] for t in fleet["tokens"] if t["name"] == tok), [])
        check(f"token contract lists repo-evolution.yml under {tok}", "repo-evolution.yml" in used)

    registry = yaml.safe_load(REGISTRY.read_text(encoding="utf-8")) or []
    sel, dropped = ev.select_targets(registry, cfg)
    check("the shipped registry selects at least one target", len(sel) >= 1)
    check("every shipped target is an owned submodule on a named branch",
          all(t["nwo"].startswith(cfg["hub_owner"] + "/") and t["branch"] for t in sel))
    check("no shipped opt-in is silently refused (dropped list is empty)", dropped == [])

    check("brief template exists", (PROMPT_DIR / ev.BRIEF_TEMPLATE).exists())
    tpl = (PROMPT_DIR / ev.BRIEF_TEMPLATE).read_text(encoding="utf-8")
    check("brief template uses the rendered placeholders", "{{REPO_NAME}}" in tpl and "{{NWO}}" in tpl)
    for t in sel:
        check(f"category emphasis file exists for `{t['category']}`",
              (PROMPT_DIR / ev.CATEGORY_DIR / f"{t['category']}.md").exists())


# --------------------------------------------------------------------------- #
# workflow ↔ fleet.yml contract
# --------------------------------------------------------------------------- #
REQUIRED_COMMANDS = ["git status", "git diff", "gh issue view", "gh pr view",
                     "cat", "ls", "grep", "head", "tail", "npm", "pytest", "shellcheck", "make"]
FORBIDDEN_ALLOWS = ["Bash(git:*)", "Bash(gh:*)", "Bash(git push:*)", "Bash(git checkout:*)",
                    "Bash(gh pr create:*)", "Bash(gh pr merge:*)", "Bash(gh api:*)", "Bash(bash:*)", "Bash(sh:*)"]


def step(job: dict, name: str) -> dict:
    for s in job["steps"]:
        if s.get("name") == name:
            return s
    raise AssertionError(f"repo-evolution.yml: no step named {name!r}")


def test_workflow_contract() -> None:
    print("\nworkflow ↔ fleet.yml")
    raw = WORKFLOW.read_text(encoding="utf-8")
    wf = yaml.safe_load(raw)
    fleet = yaml.safe_load(FLEET.read_text(encoding="utf-8"))
    on = wf.get("on") or wf.get(True)  # PyYAML parses a bare `on:` key as True
    cron = (on.get("schedule") or [{}])[0].get("cron")
    check("cron matches _data/fleet.yml schedule.repo_evolution", cron == fleet["schedule"]["repo_evolution"])
    check("write-capable scheduled workflow has a concurrency group", bool((wf.get("concurrency") or {}).get("group")))

    plan, evolve = wf["jobs"]["plan"], wf["jobs"]["evolve"]
    check("every job sets timeout-minutes", plan.get("timeout-minutes") and evolve.get("timeout-minutes"))
    check("evolve needs plan (needs:, not workflow_run)", evolve.get("needs") == "plan")
    check("plan probes the fleet token for real (gh api user)", "gh api user" in step(plan, "Probe fleet write token")["run"])
    check("plan fails loudly without Claude auth", "exit 1" in step(plan, "Require Claude auth")["run"])
    check("plan builds the matrix with dash-gen targets", "targets" in step(plan, "Build the plan")["run"])
    check("dispatch inputs reach the script via env, not inline expressions",
          "$TARGET" in step(plan, "Build the plan")["run"] and "$FOCUS" in step(plan, "Build the plan")["run"])

    strat = evolve["strategy"]
    check("fail-fast is off (one repo cannot strand the rest)", strat.get("fail-fast") is False)
    check("max-parallel is wired from the plan (fleet.yml stated once)",
          "needs.plan.outputs.max_parallel" in str(strat.get("max-parallel")))
    check("matrix is wired from the plan", "needs.plan.outputs.matrix" in str(strat.get("matrix")))

    co = next(s for s in evolve["steps"] if str(s.get("uses", "")).startswith("actions/checkout"))
    check("target checkout keeps no credentials (the agent structurally cannot push)",
          co["with"].get("persist-credentials") is False)
    check("target checkout is the matrix repo on the matrix branch",
          "matrix.nwo" in str(co["with"].get("repository")) and "matrix.branch" in str(co["with"].get("ref")))
    check("the brief is hidden from git in the target checkout", ".git/info/exclude" in step(evolve, "Hide the brief from git")["run"])

    ev_step = step(evolve, "Evolve")
    args = ev_step["with"]["claude_args"]
    # The prompt is a YAML block scalar: phrases wrap across lines, so compare
    # on whitespace-normalised text.
    prompt = " ".join(ev_step["with"]["prompt"].split())
    check("OAuth-first Claude auth with the API-key fallback expression",
          "claude_code_oauth_token" in ev_step["with"]
          and "secrets.CLAUDE_CODE_OAUTH_TOKEN == '' && secrets.ANTHROPIC_API_KEY || ''" in ev_step["with"]["anthropic_api_key"])
    check("--max-turns is wired from the plan", "--max-turns ${{ needs.plan.outputs.max_turns }}" in args)
    m = re.search(r'--allowedTools\s+"([^"]+)"', args)
    check("claude_args declares --allowedTools", bool(m))
    allowed = {t.strip() for t in m.group(1).split(",")} if m else set()
    for cmd in REQUIRED_COMMANDS:
        check(f"allowlist permits `{cmd}` (the prompt needs it)", f"Bash({cmd}:*)" in allowed)
    for tool in ("Read", "Grep", "Glob", "Edit", "Write"):
        check(f"allowlist permits the {tool} tool", tool in allowed)
    for bad in FORBIDDEN_ALLOWS:
        check(f"allowlist does NOT grant `{bad}` (publishing is the workflow's job)", bad not in allowed)
    check("prompt tells the agent to read its brief", ".evolution/${{ matrix.brief }}" in prompt)
    check("prompt states the lanes (doctor / issue pipeline / open PRs)",
          "fleet doctor" in prompt and "issue pipeline" in prompt and "open pr" in prompt.lower())
    check("prompt says the agent never pushes and the workflow opens a DRAFT",
          "never commit" in prompt and "DRAFT" in prompt)
    check("prompt carries the always-latest / no-lockfile rule", "lockfile" in prompt)
    check("prompt carries the SCHEMA.md rule", "SCHEMA.md" in prompt)

    check("the credential-rejected classifier is present", "modelUsage" in step(evolve, "Diagnose Claude failure")["run"])

    pub = step(evolve, "Open draft PR")
    run = pub["run"]
    check("publish step is skipped on dry runs", "inputs.dry_run != true" in str(pub.get("if")))
    check("the PR is opened as a DRAFT", "gh pr create" in run and "--draft" in run)
    check("the workflow never merges", "gh pr merge" not in raw and "--auto" not in raw)
    check("the marker is the FIRST line of the PR body", run.index('echo "$MARKER"') < run.index('echo "$summary"'))
    check("labels are created on demand before use", run.index("gh label create") < run.index("gh pr create -R"))
    check("the branch prefix and label come from the plan (fleet.yml)",
          "needs.plan.outputs.branch_prefix" in str(pub["env"].get("PREFIX"))
          and "needs.plan.outputs.label" in str(pub["env"].get("LABEL")))
    check("a moved HEAD refuses to publish", "git rev-parse --abbrev-ref HEAD" in run and "exit 1" in run)
    # The `Evolve` action derives its repository from `github.repository` (the
    # hub) and revokes its own token inside the step, so it leaves the checkout
    # pointing at bamr87/bamr87 with a dead credential. Run #1's `scripts` job
    # pushed there and failed; a push that SUCCEEDED would have put a
    # submodule's changes on the hub. The publish step must re-derive the
    # remote from $NWO and refuse anything else. (bamr87/bamr87#214)
    check("the publish remote is re-derived from $NWO, never the inherited origin",
          'git remote set-url origin "$REMOTE"' in run and 'REMOTE="${SERVER}/${NWO}"' in run)
    check("an auth header left by the agent step is cleared before pushing",
          ".extraheader" in run)
    check("a publish remote that is not $NWO refuses to push",
          "git remote get-url origin" in run
          and 'refusing to push' in run)
    check("the push targets the explicit URL, not the remote name",
          'git push -q "$REMOTE"' in run and "git push -q -u origin" not in run)

    # A turn count that overshoots --max-turns fails the step even when the
    # agent reported success, which skipped `Open draft PR` and discarded
    # finished, billed work on run #1's README job.
    # Tolerant lookup, unlike step(): a missing step must be reported as a
    # failed check alongside the others, not abort the run before they print.
    salv = next((s for s in evolve["steps"] if s.get("name") == "Salvage a successful overshoot"), {})
    check("a successful result that overshot the turn cap is detected",
          "steps.evolve.outcome == 'failure'" in str(salv.get("if"))
          and ".subtype" in salv["run"] and ".is_error" in salv["run"])
    check("a salvaged success still reaches the publish step",
          "steps.salvage.outputs.succeeded == 'true'" in str(pub.get("if")))
    check("max_turns is above the ceiling observed in run #1 (63 turns)",
          int(fleet["evolution"]["max_turns"]) > 63)
    check("commits as the bot identity", "bamr87-bot" in run and "10567847+bamr87@users.noreply.github.com" in run)
    for pat in (fleet.get("dependencies") or {}).get("lockfile_patterns") or []:
        # The step greps the literal filename with only the dot escaped; re.escape
        # would also escape `-`, which the script does not.
        check(f"publish step drops an untracked `{pat}` (fleet.yml lockfile policy)", pat.replace(".", r"\.") in run)


def main() -> int:
    test_selection()
    test_dedupe()
    test_brief()
    test_plan_and_config()
    test_shipped()
    test_workflow_contract()
    failed = [label for label, ok in CHECKS if not ok]
    print()
    for label, ok in CHECKS:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    print()
    if failed:
        print(f"FAILED ({len(failed)}/{len(CHECKS)})")
        return 1
    print(f"OK ({len(CHECKS)} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
