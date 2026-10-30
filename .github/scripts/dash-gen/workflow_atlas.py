#!/usr/bin/env python3
"""
workflow_atlas — the hub's GitHub Actions as ONE model: every workflow and
composite action, the standards they are held to, why their runs failed, and a
scaffold that writes a new one already inside those standards.

The 2026-10-27 overhaul (bamr87/bamr87#422) found the same three things over
and over: facts about the workflows were copied by hand into five places (the
console's dispatch allowlist refused the inputs of four workflows because its
copy had drifted), the standards lived only as prose, and most red runs were
not defects (a spent Claude window, a repo setting) but read the same as one.
This module is the single reading of `.github/` that the console, the CLI and
the `fleet` MCP server share instead of copying.

Four halves, all pure and offline except `lake_health`, which reads the local
data lake (`tools/dash lake sync`):

  model     scan(root) → workflows (triggers, crons and their fleet.yml key,
            dispatch/call inputs, permissions, concurrency, jobs, the actions
            and reusable workflows they use, secrets, vars, kill switch,
            Claude call sites with budget and usage-limit mode, published
            paths) + composite actions (inputs, outputs, used-by) + the
            README's purpose rows and retirement table + dependency edges.
  lint      RULES — the README `## Standards` and AGENTS.md standing rules as
            checks, each with the incident behind it. Rules that mirror an
            existing gate name it (`gate:`); the gate stays authoritative.
  health    classify_failure() reads a failed run's error lines into a cause
            and a class (capacity · config · transient · dependency · defect);
            lake_health() rolls the lake's runs up per workflow, with ghosts
            (runs whose workflow file is gone) and green runs that were really
            a usage-limit skip.
  scaffold  scaffold(kind, id) → a workflow that passes every rule by
            construction, plus the companion edits it needs (fleet.yml
            schedule key, budget call site, README row). Writes nothing
            unless the CLI is given --write.

CLI (tools/dash workflows …):
  list                    one line per workflow
  show <id>               one workflow or action, as JSON
  lint [--json] [--strict]  findings; exit 1 on an error (on a warning too with --strict)
  health [--days N] [--json]  run health + failure causes from the lake
  new --kind K --id ID [--name N] [--cron C] [--purpose P] [--write]
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import re
import shlex
import sys
import textwrap
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("workflow_atlas requires PyYAML: pip install pyyaml\n")
    sys.exit(2)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness_registry as hr  # noqa: E402  cron math + the shared regexes

ROOT_DEFAULT = Path(__file__).resolve().parents[3]
SCHEMA = "workflow-atlas/v1"   # bump on a breaking (non-additive) change
HUB_DEFAULT = "bamr87/bamr87"
README_DOC = ".github/workflows/README.md"
STANDARDS_DOC = f"{README_DOC}#standards"

# --------------------------------------------------------------------------- #
# The rules. `gate` names the check that already enforces a rule in CI; the
# atlas reports it so the console can show it, and the gate stays the source
# of truth. A rule without a gate is enforced by test_workflow_atlas.py at
# error level (the live tree must carry no error).
# --------------------------------------------------------------------------- #
RULES: list[dict] = [
    dict(id="parse-error", severity="error", title="The file parses",
         why="An unparseable workflow is invisible to every reader here and to GitHub.",
         fix="Run actionlint on the file.", doc=README_DOC, gate="actionlint (drift-check)"),
    dict(id="permissions", severity="warn", title="Least-privilege token",
         why="Without a top-level `permissions:` the job token gets the repository default, which can be write-all.",
         fix="Add `permissions: contents: read` at the top and elevate per job.", doc=STANDARDS_DOC, gate=None),
    dict(id="timeout", severity="warn", title="Every job has a timeout",
         why="A hung job holds its runner for the 360-minute default; a timeout bounds the waste.",
         fix="Set `timeout-minutes:` on the job.", doc=STANDARDS_DOC, gate=None),
    dict(id="concurrency", severity="warn", title="Writers are serialized",
         why="Two overlapping runs of a loop that writes publish twice or open duplicate PRs.",
         fix="Add a `concurrency:` group (cancel-in-progress: false for loops).", doc=STANDARDS_DOC, gate=None),
    dict(id="sha-pin", severity="error", title="Actions ride major tags",
         why="SHA pins stop Dependabot moving majors; the fleet policy is always-latest.",
         fix="Use the major tag, e.g. `actions/checkout@v7`.", doc="docs/DEPENDENCIES.md", gate="check-drift (j)"),
    dict(id="cron-declared", severity="error", title="Every cron is declared in fleet.yml",
         why="`_data/fleet.yml` `schedule:` is the one calendar the Schedules page and the collision check read.",
         fix="Add the cron under `schedule:` in `_data/fleet.yml`.", doc="_data/fleet.yml", gate="test_schedule.py"),
    dict(id="cron-on-hour", severity="error", title="No hub cron fires on the hour",
         why="GitHub delays and drops `:00` runs under load; the hub uses :07 for housekeeping and :37 for agents.",
         fix="Move the minute off zero (:07 or :37).", doc="AGENTS.md", gate="test_schedule.py"),
    dict(id="kill-switch", severity="error", title="Scheduled agents have a kill switch",
         why="A scheduled Claude loop without a `vars.*_ENABLED` gate can only be stopped by a commit.",
         fix="Gate the job: `if: github.event_name != 'schedule' || vars.<NAME>_ENABLED != 'false'`.",
         doc="AGENTS.md", gate=None),
    dict(id="ai-budget", severity="error", title="Every Claude call site has a dollar cap",
         why="`--max-turns` bounds iterations, not spend; the cap must equal `budget.call_sites` in fleet.yml.",
         fix="Pass `--max-budget-usd N` and declare `<file>:<job>: N` under `budget.call_sites`.",
         doc="docs/AI-INTEGRATION.md#spend-guardrails", gate="test_ai_budget.py"),
    dict(id="usage-limit", severity="error", title="A spent Claude window is capacity, not a defect",
         why="Thirteen red runs in October were HTTP 429s, not bugs. The agent step must be `continue-on-error` "
             "and its cost step `usage-limit: skip` — the two only work as a pair.",
         fix="Add `continue-on-error: true` to the agent step and `usage-limit: skip` to its claude-cost step.",
         doc=STANDARDS_DOC, gate="test_ai_budget.py"),
    dict(id="null-input", severity="error", title="Dispatch inputs are empty on other triggers",
         why="On a cron or push run `inputs.x` is null, and GitHub compares null and false as equal: "
             "`inputs.apply != false` skipped every scheduled schema-vendor run.",
         fix="Guard it: `github.event_name != 'workflow_dispatch' || inputs.x`.", doc=STANDARDS_DOC, gate=None),
    dict(id="workflow-run", severity="warn", title="Prefer `needs:` over `workflow_run`",
         why="A `workflow_run` follower couples by display name and is silently skipped when the upstream fails.",
         fix="Make it a job with `needs:` in the same workflow.", doc=STANDARDS_DOC, gate=None),
    dict(id="pr-token", severity="warn", title="CI-bearing PRs are opened with FLEET_TOKEN",
         why="GitHub fires no workflow events for a PR opened with GITHUB_TOKEN, so its checks never run.",
         fix="Probe FLEET_TOKEN with resolve-fleet-token and open the PR with that.",
         doc="docs/ISSUE-PIPELINE.md", gate=None),
    dict(id="bare-push", severity="warn", title="Never a bare push to the default branch",
         why="A ruleset change froze the fleet's data for three weeks when every loop ended in `git push`.",
         fix="Publish through `.github/actions/utilities/publish-data`.", doc=STANDARDS_DOC, gate=None),
    dict(id="undocumented", severity="warn", title="Listed in its README",
         why="The README tables are the inventory people read; a file missing there is a file nobody owns.",
         fix="Add a row to the README table (or remove the stale row).", doc=README_DOC, gate=None),
    dict(id="action-description-expr", severity="error", title="No expression in an action's description",
         why="A manifest is a template: `${{ github.token }}` in prose killed token-rotation before any step ran.",
         fix="Name the context in plain backticks.", doc=".github/actions/README.md", gate="check-drift (l)"),
    dict(id="action-unused", severity="warn", title="Every action has a caller",
         why="An action with no caller is deleted, not kept for later (seven were, 3,500 lines).",
         fix="Delete it, or call it.", doc=".github/actions/README.md", gate=None),
]
RULE_BY_ID = {r["id"]: r for r in RULES}
SEVERITIES = ("error", "warn", "info")

LOCAL_ACTION_RX = re.compile(r"^(?:\./(?:\.fleet-hub/)?|(?P<owner>[\w.-]+/[\w.-]+)/)\.github/actions/(?P<id>[\w./-]+?)/?(?:@(?P<ver>\S+))?$")
WORKFLOW_REF_RX = re.compile(r"^(?:\./|(?P<owner>[\w.-]+/[\w.-]+)/)\.github/workflows/(?P<id>[\w.-]+?)\.ya?ml(?:@(?P<ver>\S+))?$")
EXTERNAL_RX = re.compile(r"^(?P<repo>[\w.-]+/[\w.-]+)(?P<path>/[\w./-]+)?@(?P<ver>\S+)$")
SHA_RX = re.compile(r"^[0-9a-f]{40}$")
SECRET_RX = re.compile(r"\bsecrets\.([A-Za-z_][A-Za-z0-9_]*)")
VAR_RX = re.compile(r"\bvars\.([A-Za-z_][A-Za-z0-9_]*)")
EXPR_RX = re.compile(r"\$\{\{(.*?)\}\}", re.S)
INPUT_REF_RX = re.compile(r"\$\{\{\s*inputs\.([\w-]+)\s*\}\}")
# `inputs.x == false`, `inputs.x != false` and `!inputs.x`: each reads a null
# (a run that is not a dispatch) the same as false.
NULL_CMP_RX = re.compile(r"inputs\.([\w-]+)\s*[!=]=\s*false\b|\bfalse\s*[!=]=\s*inputs\.([\w-]+)"
                         r"|!\s*inputs\.([\w-]+)(?!\s*[!=]=)")
# A guard that keeps a non-dispatch run away from the input names the event.
EVENT_GUARD_RX = re.compile(r"github\.event_name\s*[!=]=\s*'(?:workflow_dispatch|schedule)'")
ONLY_JOB_TOKEN_RX = re.compile(r"^\s*(?:\$\{\{\s*)?(?:github\.token|secrets\.GITHUB_TOKEN)(?:\s*\}\})?\s*$")
DEFAULT_BRANCHES = ("main", "master")
CLAUDE_ACTION = "anthropics/claude-code-action"
ID_RX = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
NAME_RX = re.compile(r"^(?![-\s])[^\n\r\"'`$\\]{1,80}$")
# A draft that expands past this many YAML nodes is refused before anything
# walks it: an alias chain of a few hundred bytes otherwise expands into hours.
MAX_NODES = 50_000


class _Loader(yaml.SafeLoader):
    """GitHub reads workflows as YAML 1.2, where only true/false are booleans:
    `on:` stays a key and a choice option `yes` stays "yes" (PyYAML's YAML 1.1
    default turns both into True)."""


_Loader.yaml_implicit_resolvers = {
    ch: [(tag, rx) for tag, rx in rs if tag != "tag:yaml.org,2002:bool"]
    for ch, rs in yaml.SafeLoader.yaml_implicit_resolvers.items()}
_Loader.add_implicit_resolver("tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
                              list("tTfF"))


def is_claude_run(uses: str) -> bool:
    return re.search(r"(^\./|^bamr87/bamr87/)\.github/actions/claude-run(@|$)", uses) is not None


def is_claude_cost(uses: str) -> bool:
    return re.search(r"(^\./(\.fleet-hub/)?|^bamr87/bamr87/)\.github/actions/claude-cost(@|$)", uses) is not None


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _code(text: str) -> str:
    """The file without its comment lines — prose about `secrets.X` is not a use."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _line_of(text: str, pattern: str, flags: int = re.M) -> int | None:
    m = re.search(pattern, text, flags)
    return text.count("\n", 0, m.start()) + 1 if m else None


def _job_line(text: str, job_id: str) -> int | None:
    return _line_of(text, rf"^\s{{2,4}}{re.escape(job_id)}:\s*(#.*)?$")


def _list(value) -> list:
    if value is None:
        return []
    return [str(v) for v in value] if isinstance(value, list) else [str(value)]


def _truthy(value) -> bool:
    return value is True or str(value).strip().lower() == "true"


def _coe(value) -> bool | str:
    """`continue-on-error`: True, False, or "expression" when it is decided at run time."""
    if value is None or value is False or str(value).strip().lower() == "false":
        return False
    return True if _truthy(value) else "expression"


def _oversized(data, limit: int = MAX_NODES) -> str | None:
    """Why a parsed document must not be walked: a cycle, or more than `limit`
    nodes once aliases are expanded (each shared node is sized once)."""
    memo: dict[int, int] = {}
    active: set[int] = set()

    def size(node) -> int:
        if not isinstance(node, (dict, list)):
            return 1
        key = id(node)
        if key in active:
            raise ValueError("a YAML alias refers to itself")
        if key in memo:
            return memo[key]
        active.add(key)
        total = 1
        for item in (list(node.keys()) + list(node.values())) if isinstance(node, dict) else node:
            total += size(item)
            if total > limit:
                break
        active.discard(key)
        memo[key] = total
        return total

    try:
        return f"expands past {limit:,} nodes through YAML aliases" if size(data) > limit else None
    except ValueError as exc:
        return str(exc)
    except RecursionError:
        return "nested too deeply"


def _load(text: str):
    """(document, None) or (None, why it cannot be read)."""
    try:
        data = yaml.load(text, Loader=_Loader)  # noqa: S506 — a SafeLoader subclass
    except yaml.YAMLError as exc:
        return None, str(exc).splitlines()[0][:200]
    except RecursionError:
        return None, "nested too deeply"
    why = _oversized(data)
    return (None, why) if why else (data, None)


def _on(data: dict) -> dict:
    on = data.get("on", data.get(True))
    if isinstance(on, str):
        return {on: None}
    if isinstance(on, list):
        return {str(k): None for k in on}
    return on if isinstance(on, dict) else {}


def _plain(md: str) -> str:
    """Markdown cell → plain text (links to their label, no emphasis or code ticks)."""
    out = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", md or "")
    return re.sub(r"[*`]", "", out).strip()


def header_comment(text: str) -> str:
    """The comment block that opens a workflow (before `on:`), as plain text."""
    out: list[str] = []
    started = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            started = True
            out.append(re.sub(r"^#\s?", "", s))
        elif not s or (s.startswith("name:") and not started):
            if started:
                out.append("")
            continue
        else:
            break
    return "\n".join(out).strip()


def _inputs(block) -> list[dict]:
    inputs = block.get("inputs") if isinstance(block, dict) else None
    if not isinstance(inputs, dict):
        return []
    out = []
    for name, spec in inputs.items():
        spec = spec if isinstance(spec, dict) else {}
        options = spec.get("options")
        out.append({"name": str(name), "type": str(spec.get("type") or "string"),
                    "default": spec.get("default"), "required": bool(spec.get("required")),
                    "description": str(spec.get("description") or "").strip(),
                    "options": [str(o) for o in options] if isinstance(options, list) else []})
    return out


def _ref(uses: str) -> dict:
    uses = uses.strip()
    if uses.startswith("docker://"):
        return {"ref": uses, "kind": "docker", "target": uses[9:], "version": None}
    m = WORKFLOW_REF_RX.match(uses)
    if m:
        return {"ref": uses, "kind": "workflow", "target": m.group("id"), "version": m.group("ver"),
                "owner": m.group("owner")}
    m = LOCAL_ACTION_RX.match(uses)
    if m:
        return {"ref": uses, "kind": "action", "target": m.group("id"), "version": m.group("ver"),
                "owner": m.group("owner")}
    m = EXTERNAL_RX.match(uses)
    if m:
        return {"ref": uses, "kind": "external", "target": m.group("repo") + (m.group("path") or ""),
                "version": m.group("ver")}
    return {"ref": uses, "kind": "unknown", "target": uses, "version": None}


def _local(ref: dict, hub: str) -> bool:
    return ref["kind"] in ("action", "workflow") and ref.get("owner") in (None, hub)


# --------------------------------------------------------------------------- #
# the README: purpose rows by group, and the retirement table
# --------------------------------------------------------------------------- #
GROUP_HEADINGS = (("retired", "retired"), ("reusable", "reusable"), ("fan-out", "fanout"),
                  ("gate", "gate"), ("loop", "loop"))


def parse_readme(text: str) -> dict:
    rows: dict[str, dict] = {}
    retired: list[dict] = []
    group = None
    for line in text.splitlines():
        if line.startswith("## "):
            head = line[3:].lower()
            group = next((g for key, g in GROUP_HEADINGS if key in head), None)
            continue
        if not line.startswith("|") or set(line.replace("|", "").strip()) <= {"-", " "}:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        if group == "retired":
            if cells[0].lower() == "date":
                continue
            retired.append({"date": cells[0], "removed": _plain(cells[1]), "why": cells[2],
                            "files": re.findall(r"`([\w.-]+)`", cells[1])})
            continue
        m = re.fullmatch(r"`([\w.-]+\.ya?ml)`", cells[0])
        if m:   # a row under a heading no group matches still documents the file
            rows[m.group(1)] = {"group": group, "when": _plain(cells[1]), "purpose": cells[2]}
    return {"rows": rows, "retired": retired}


def parse_actions_readme(text: str) -> set[str]:
    return set(re.findall(r"^\|\s*`([\w./-]+)`\s*\|", text, re.M))


# --------------------------------------------------------------------------- #
# MODEL — one workflow file
# --------------------------------------------------------------------------- #
def _resolve_inputs(args: str, inputs: list[dict]) -> str:
    """`${{ inputs.x }}` → x's declared default; one with no default stays as written."""
    defaults = {i["name"]: i["default"] for i in inputs if i["default"] is not None}
    return INPUT_REF_RX.sub(lambda m: str(defaults.get(m.group(1), m.group(0))), args)


def parse_workflow(rel: str, text: str, hub: str = HUB_DEFAULT) -> dict:
    stem = Path(rel).stem
    wf: dict = {
        "id": stem, "file": rel, "name": stem, "lines": text.count("\n") + 1, "parse_error": None,
        "header": header_comment(text), "triggers": [], "events": [], "crons": [],
        "dispatch_inputs": [], "call_inputs": [], "call_secrets": [], "permissions": None,
        "concurrency": None, "jobs": [], "uses": [], "secrets": [], "vars": [], "switch": None,
        "switches": [], "ai_sites": [], "publishes": [], "opens_prs": False, "env": {},
    }
    data, why = _load(text)
    if why:
        wf["parse_error"] = why
        return wf
    if not isinstance(data, dict):
        wf["parse_error"] = "not a YAML mapping"
        return wf
    if not isinstance(data.get("jobs") or {}, dict):
        wf["parse_error"] = "`jobs:` must be a mapping of job ids"
        return wf
    wf["name"] = str(data.get("name") or stem)
    on = _on(data)
    wf["triggers"] = [str(k) for k in on]
    for trig, spec in on.items():
        spec = spec if isinstance(spec, dict) else {}
        if trig == "schedule":
            continue
        ev = {"name": str(trig)}
        for key in ("branches", "paths", "types", "tags", "workflows"):
            if spec.get(key):
                ev[key] = _list(spec[key])
        wf["events"].append(ev)
    sched = on.get("schedule")
    for entry in sched if isinstance(sched, list) else []:
        if isinstance(entry, dict) and entry.get("cron"):
            cron = str(entry["cron"]).strip()
            parsed = hr.parse_cron(cron)
            wf["crons"].append({"cron": cron, "human": hr.describe_cron(cron),
                                "per_day": hr.cron_fires_per_day(cron),
                                "on_hour": bool(parsed and 0 in parsed["minutes"]),
                                "schedule_key": None})
    wf["dispatch_inputs"] = _inputs(on.get("workflow_dispatch"))
    call = on.get("workflow_call")
    wf["call_inputs"] = _inputs(call)
    secrets = call.get("secrets") if isinstance(call, dict) else None
    wf["call_secrets"] = sorted(str(k) for k in secrets) if isinstance(secrets, dict) else []
    perms = data.get("permissions")
    wf["permissions"] = perms if isinstance(perms, (dict, str)) else None
    conc = data.get("concurrency")
    if isinstance(conc, str):
        wf["concurrency"] = {"group": conc, "cancel_in_progress": False}
    elif isinstance(conc, dict):
        wf["concurrency"] = {"group": str(conc.get("group") or ""), "cancel_in_progress": conc.get("cancel-in-progress", False)}
    wf["env"] = {str(k): str(v) for k, v in (data.get("env") or {}).items()} if isinstance(data.get("env"), dict) else {}

    code = _code(text)
    wf["secrets"] = sorted(set(SECRET_RX.findall(code)))
    wf["vars"] = sorted(set(VAR_RX.findall(code)))
    wf["switches"] = sorted(set(hr.SWITCH_RX.findall(code)))
    wf["switch"] = wf["switches"][0] if wf["switches"] else None

    refs: dict[str, dict] = {}
    for jid, job in (data.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        steps = [s for s in job.get("steps") or [] if isinstance(s, dict)] if isinstance(job.get("steps"), list) else []
        jperms = job.get("permissions")
        jrow = {"id": str(jid), "name": str(job.get("name") or jid), "line": _job_line(text, str(jid)),
                "runs_on": str(job.get("runs-on")) if job.get("runs-on") is not None else None,
                "timeout": job.get("timeout-minutes"), "needs": _list(job.get("needs")),
                "if": str(job["if"]).strip() if job.get("if") is not None else None,
                "uses": str(job["uses"]) if job.get("uses") else None,
                "permissions": jperms if isinstance(jperms, (dict, str)) else None,
                "concurrency": "concurrency" in job, "steps": len(steps),
                "matrix": bool(isinstance(job.get("strategy"), dict) and job["strategy"].get("matrix")),
                "env": {str(k): str(v) for k, v in (job.get("env") or {}).items()} if isinstance(job.get("env"), dict) else {}}
        wf["jobs"].append(jrow)
        if jrow["uses"]:
            r = _ref(jrow["uses"])
            refs.setdefault(r["ref"], {**r, "jobs": []})["jobs"].append(str(jid))
        cost = next((s for s in steps if is_claude_cost(str(s.get("uses") or ""))), None)
        for step in steps:
            uses = str(step.get("uses") or "")
            with_ = step.get("with") if isinstance(step.get("with"), dict) else {}
            if uses:
                r = _ref(uses)
                hit = refs.setdefault(r["ref"], {**r, "jobs": []})
                if str(jid) not in hit["jobs"]:
                    hit["jobs"].append(str(jid))
                if r["kind"] == "action" and r["target"] == "utilities/publish-data":
                    wf["publishes"] += str(with_.get("paths") or "").split()
            run = str(step.get("run") or "")
            if "gh pr create" in run or "tools/fanout.sh" in run or "create-pull-request" in uses:
                wf["opens_prs"] = True
            if CLAUDE_ACTION in uses:
                kind, args = "claude-code-action", str(with_.get("claude_args") or "")
            elif is_claude_run(uses):
                kind = "claude-run"
                args = " ".join(f"--{k} {with_[k]}" for k in ("max-turns", "max-budget-usd") if str(with_.get(k, "")).strip())
            else:
                continue
            args = _resolve_inputs(args, wf["call_inputs"] + wf["dispatch_inputs"])
            budget = hr.MAX_BUDGET_RX.search(args)
            model = hr.MODEL_RX.search(args)
            turns = hr.MAX_TURNS_RX.search(args)
            cost_with = (cost or {}).get("with") if isinstance((cost or {}).get("with"), dict) else {}
            wf["ai_sites"].append({
                "site": f"{Path(rel).name}:{jid}", "job": str(jid), "kind": kind,
                "step": str(step.get("name") or step.get("id") or uses),
                "continue_on_error": _coe(step.get("continue-on-error")),
                "max_budget_usd": float(budget.group(1)) if budget else None,
                # a cap passed through an input with no default: present, but not checkable here
                "budget_from_input": not budget and re.search(r"max-budget-usd\s+\$\{\{", args) is not None,
                "max_turns": int(turns.group(1)) if turns else None,
                "model": model.group(1) if model else (str(with_.get("model")) if with_.get("model") else None),
                "cost_step": bool(cost),
                "usage_limit": str(cost_with.get("usage-limit") or "fail") if cost else None,
                "declared_usd": None,
            })
    wf["uses"] = sorted(refs.values(), key=lambda r: (r["kind"], r["target"]))
    wf["publishes"] = sorted(set(wf["publishes"]))
    return wf


def parse_action(rel: str, text: str) -> dict:
    act = {"id": str(Path(rel).parent.relative_to(".github/actions").as_posix()), "file": rel,
           "name": None, "description": "", "using": None, "inputs": [], "outputs": [], "steps": 0,
           "uses": [], "lines": text.count("\n") + 1, "parse_error": None, "used_by": [], "description_exprs": []}
    data, why = _load(text)
    if why:
        act["parse_error"] = why
        return act
    if not isinstance(data, dict):
        act["parse_error"] = "not a YAML mapping"
        return act
    act["name"] = str(data.get("name") or act["id"])
    act["description"] = str(data.get("description") or "").strip()
    runs = data.get("runs") if isinstance(data.get("runs"), dict) else {}
    act["using"] = str(runs.get("using") or "") or None
    act["inputs"] = _inputs({"inputs": data.get("inputs")})
    outputs = data.get("outputs") if isinstance(data.get("outputs"), dict) else {}
    act["outputs"] = sorted(str(k) for k in outputs)
    # GitHub evaluates `${{` in any description of a manifest (check-drift (l)).
    act["description_exprs"] = (["description"] if "${{" in act["description"] else []) + [
        f"{kind}.{name}.description"
        for kind, block in (("inputs", data.get("inputs")), ("outputs", outputs)) if isinstance(block, dict)
        for name, spec in block.items()
        if isinstance(spec, dict) and "${{" in str(spec.get("description") or "")]
    steps = [s for s in runs.get("steps") or [] if isinstance(s, dict)] if isinstance(runs.get("steps"), list) else []
    act["steps"] = len(steps)
    act["uses"] = sorted({_ref(str(s["uses"]))["ref"] for s in steps if s.get("uses")})
    return act


# --------------------------------------------------------------------------- #
# MODEL — the repository
# --------------------------------------------------------------------------- #
def load_fleet(root: Path) -> dict:
    try:
        return yaml.safe_load((root / "_data" / "fleet.yml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def scan(root: Path | str = ROOT_DEFAULT, fleet: dict | None = None, hub: str | None = None) -> dict:
    """The atlas of one repository's `.github/` (the hub by default)."""
    root = Path(root)
    fleet = load_fleet(root) if fleet is None else fleet
    hub = hub or str(((fleet.get("hub") or {}).get("repo")) or HUB_DEFAULT)
    wf_dir, act_dir = root / ".github" / "workflows", root / ".github" / "actions"
    readme_path = wf_dir / "README.md"
    readme = parse_readme(readme_path.read_text(encoding="utf-8")) if readme_path.is_file() else {"rows": {}, "retired": []}
    act_readme_path = act_dir / "README.md"
    act_listed = parse_actions_readme(act_readme_path.read_text(encoding="utf-8")) if act_readme_path.is_file() else None
    texts: dict[str, str] = {}
    workflows = []
    for p in sorted(list(wf_dir.glob("*.yml")) + list(wf_dir.glob("*.yaml"))):
        rel = p.relative_to(root).as_posix()
        texts[rel] = p.read_text(encoding="utf-8", errors="replace")
        try:
            wf = parse_workflow(rel, texts[rel], hub)
        except Exception as exc:  # the atlas reports a file it cannot read; it never dies on one
            wf = parse_workflow(rel, "", hub) | {"parse_error": f"{exc.__class__.__name__}: {exc}"[:200]}
        row = readme["rows"].get(p.name)
        wf["documented"] = row is not None
        wf["group"] = (row or {}).get("group") or derive_group(wf)
        wf["when"] = row["when"] if row else None
        wf["purpose"] = row["purpose"] if row else None
        wf["purpose_text"] = _plain(row["purpose"]) if row else (wf["header"].split("\n\n")[0].replace("\n", " ")[:300] or None)
        workflows.append(wf)
    actions = []
    if act_dir.is_dir():
        for p in sorted(act_dir.rglob("action.y*ml")):
            rel = p.relative_to(root).as_posix()
            texts[rel] = p.read_text(encoding="utf-8", errors="replace")
            try:
                act = parse_action(rel, texts[rel])
            except Exception as exc:
                act = parse_action(rel, "") | {"parse_error": f"{exc.__class__.__name__}: {exc}"[:200]}
            act["documented"] = act_listed is None or act["id"] in act_listed
            act["readme"] = (p.parent / "README.md").is_file()
            actions.append(act)
    join(workflows, actions, fleet, hub)
    atlas = {
        "schema": SCHEMA, "hub": hub, "workflows": workflows, "actions": actions,
        "retired": readme["retired"], "rules": RULES,
        "readme_orphans": sorted(f for f in readme["rows"] if not (wf_dir / f).is_file()),
    }
    atlas["findings"] = lint(atlas, fleet, texts, hub_rules=True)
    for wf in workflows:
        wf["findings"] = _tally(f for f in atlas["findings"] if f["kind"] == "workflow" and f["target"] == wf["id"])
    for act in actions:
        act["findings"] = _tally(f for f in atlas["findings"] if f["kind"] == "action" and f["target"] == act["id"])
    atlas["edges"] = edges(workflows, actions)
    atlas["summary"] = summarize(atlas)
    return atlas


def derive_group(wf: dict) -> str:
    t = set(wf["triggers"])
    if "workflow_call" in t:
        return "reusable"
    if "schedule" in t:
        return "loop"
    if t & {"pull_request", "push", "pull_request_target", "merge_group"}:
        return "gate"
    if t & {"issue_comment", "issues", "pull_request_review", "pull_request_review_comment"}:
        return "agent"
    return "manual"


# workflow stem → its fleet.yml `schedule:` key is the stem with underscores;
# token-rotation is the one irregular name (test_schedule.py reads the same).
SCHEDULE_KEY_OVERRIDES = {"token-rotation": "rotate_tokens"}


def schedule_key_for(stem: str) -> str:
    return SCHEDULE_KEY_OVERRIDES.get(stem, re.sub(r"[^a-z0-9]+", "_", stem.lower()).strip("_"))


def join(workflows: list[dict], actions: list[dict], fleet: dict, hub: str) -> None:
    """Cross-references: each cron's fleet.yml key (set only when the declared
    cron is this one), each Claude site's declared cap, and each action's callers."""
    schedule = {str(k): str(v).strip() for k, v in ((fleet.get("schedule") or {}).items()) if v}
    sites = ((fleet.get("budget") or {}).get("call_sites") or {})
    by_id = {a["id"]: a for a in actions}
    for wf in workflows:
        key = schedule_key_for(wf["id"])
        for c in wf["crons"]:
            c["schedule_key"] = key if schedule.get(key) == c["cron"] else None
            c["expected_key"] = key
        for s in wf["ai_sites"]:
            v = sites.get(s["site"])
            s["declared_usd"] = float(v) if isinstance(v, (int, float)) else None
        for r in wf["uses"]:
            if r["kind"] == "action" and _local(r, hub) and r["target"] in by_id:
                by_id[r["target"]]["used_by"].append(wf["id"])
    for act in actions:
        for ref in act["uses"]:
            r = _ref(ref)
            if r["kind"] == "action" and _local(r, hub) and r["target"] in by_id:
                by_id[r["target"]]["used_by"].append(f"action:{act['id']}")
    for act in actions:
        act["used_by"] = sorted(set(act["used_by"]))


def edges(workflows: list[dict], actions: list[dict]) -> list[dict]:
    out = []
    for wf in workflows:
        for r in wf["uses"]:
            if r["kind"] in ("action", "workflow"):
                out.append({"from": f"workflow:{wf['id']}", "to": f"{r['kind']}:{r['target']}", "kind": "uses"})
        for path in wf["publishes"]:
            out.append({"from": f"workflow:{wf['id']}", "to": f"data:{path}", "kind": "publishes"})
    for act in actions:
        for ref in act["uses"]:
            r = _ref(ref)
            if r["kind"] == "action":
                out.append({"from": f"action:{act['id']}", "to": f"action:{r['target']}", "kind": "uses"})
    return out


def _tally(findings) -> dict:
    out = {s: 0 for s in SEVERITIES}
    for f in findings:
        out[f["severity"]] += 1
    return out


def summarize(atlas: dict) -> dict:
    wfs, acts = atlas["workflows"], atlas["actions"]
    ext: dict[str, set] = {}
    for wf in wfs:
        for r in wf["uses"]:
            if r["kind"] == "external":
                ext.setdefault(r["target"], set()).add(str(r["version"]))
    groups: dict[str, int] = {}
    for wf in wfs:
        groups[wf["group"]] = groups.get(wf["group"], 0) + 1
    return {
        "workflows": len(wfs), "actions": len(acts),
        "lines": sum(w["lines"] for w in wfs), "action_lines": sum(a["lines"] for a in acts),
        "groups": groups,
        "scheduled": sum(1 for w in wfs if w["crons"]),
        "ai": sum(1 for w in wfs if w["ai_sites"]),
        "ai_sites": sum(len(w["ai_sites"]) for w in wfs),
        "kill_switches": sum(1 for w in wfs if w["switch"]),
        "dispatchable": sum(1 for w in wfs if "workflow_dispatch" in w["triggers"]),
        "jobs": sum(len(w["jobs"]) for w in wfs),
        "findings": _tally(atlas["findings"]),
        "external_actions": [{"action": k, "versions": sorted(v)} for k, v in sorted(ext.items())],
        "secrets": sorted({s for w in wfs for s in w["secrets"]}),
        "vars": sorted({v for w in wfs for v in w["vars"]}),
        "retired": len(atlas["retired"]),
    }


# --------------------------------------------------------------------------- #
# LINT
# --------------------------------------------------------------------------- #
def _finding(rule: str, kind: str, target: str, file: str, message: str,
             line: int | None = None, job: str | None = None) -> dict:
    return {"rule": rule, "severity": RULE_BY_ID[rule]["severity"], "kind": kind, "target": target,
            "file": file, "line": line, "job": job, "message": message}


def _expressions(node, key: str | None = None):
    """Every expression in a parsed workflow: whole `if:` values and every
    `${{ … }}` inside any other string."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _expressions(v, str(k))
    elif isinstance(node, list):
        for v in node:
            yield from _expressions(v, key)
    elif isinstance(node, str):
        if key == "if":
            yield node
        else:
            yield from (m.group(1) for m in EXPR_RX.finditer(node))
    elif isinstance(node, bool) and key == "if":
        return


PUSH_VALUE_OPTS = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}


def _pushes(run: str) -> list[tuple[str, str]]:
    """Each `git … push` in a script that lands on the default branch:
    (the line, "to `main`") when a refspec names it, (the line, "with no
    branch") when it names none or only HEAD — which, on a run that checked
    out the default branch, pushes straight to it."""
    out = []
    for line in run.splitlines():
        for seg in re.split(r"&&|\|\||[;|&]", line.split(" #")[0]):
            try:
                toks = shlex.split(seg)
            except ValueError:
                toks = seg.split()
            if "git" not in toks:
                continue
            rest = toks[toks.index("git") + 1:]
            if "push" not in rest:
                continue
            args, skip = [], False
            for t in rest[rest.index("push") + 1:]:
                if skip:
                    skip = False
                elif t in PUSH_VALUE_OPTS:
                    skip = True
                elif not t.startswith("-"):
                    args.append(t)
            dests = [r.split(":")[-1].lstrip("+").removeprefix("refs/heads/") for r in args[1:]]
            if any(d in DEFAULT_BRANCHES for d in dests):
                out.append((line.strip(), f"to `{next(d for d in dests if d in DEFAULT_BRANCHES)}`"))
            elif not dests or dests == ["HEAD"]:
                out.append((line.strip(), "with no branch"))
    return out


def _token_of(*envs: dict) -> str:
    """The token `gh` would use: GH_TOKEN, else GITHUB_TOKEN, innermost env first."""
    for env in envs:
        for name in ("GH_TOKEN", "GITHUB_TOKEN"):
            if env.get(name):
                return str(env[name])
    return ""


def lint_workflow(wf: dict, text: str, fleet: dict, hub_rules: bool = True) -> list[dict]:
    out: list[dict] = []
    wid, file = wf["id"], wf["file"]
    if wf["parse_error"]:
        return [_finding("parse-error", "workflow", wid, file, wf["parse_error"])]
    data, _ = _load(text)
    data = data if isinstance(data, dict) else {}
    triggers = set(wf["triggers"])
    reusable_only = triggers <= {"workflow_call"}
    jobs = wf["jobs"]
    if not reusable_only and wf["permissions"] is None and not (jobs and all(j["permissions"] is not None for j in jobs)):
        out.append(_finding("permissions", "workflow", wid, file,
                            "No top-level `permissions:` block, and not every job declares its own.", 1))
    elif wf["permissions"] in ("write-all",):
        out.append(_finding("permissions", "workflow", wid, file, "`permissions: write-all`.",
                            _line_of(text, r"^permissions:")))
    for job in jobs:
        if not job["uses"] and job["timeout"] is None:
            out.append(_finding("timeout", "workflow", wid, file, f"Job `{job['id']}` has no `timeout-minutes`.",
                                job["line"], job["id"]))

    def writes(p) -> bool:
        return p is not None and "write" in json.dumps(p)
    writers = [j for j in jobs if writes(j["permissions"]) or (j["permissions"] is None and writes(wf["permissions"]))]
    if (triggers & {"schedule", "workflow_dispatch"} and writers and wf["concurrency"] is None
            and not all(j["concurrency"] for j in writers)):
        names = ", ".join(f"`{j['id']}`" for j in writers)
        out.append(_finding("concurrency", "workflow", wid, file,
                            f"Writes on a schedule or dispatch without a `concurrency:` group (on the workflow, or on {names}).", 1))
    for r in wf["uses"]:
        if r["kind"] in ("external", "action", "workflow") and r.get("version") and SHA_RX.match(str(r["version"])):
            out.append(_finding("sha-pin", "workflow", wid, file, f"`{r['ref']}` is pinned to a SHA.",
                                _line_of(text, re.escape(r["ref"]))))
    if hub_rules:
        for c in wf["crons"]:
            line = _line_of(text, r"cron:\s*['\"]?" + re.escape(c["cron"]))
            if c["schedule_key"] is None:
                declared = ((fleet.get("schedule") or {}).get(c["expected_key"]))
                out.append(_finding("cron-declared", "workflow", wid, file,
                                    f"Cron `{c['cron']}` is not `schedule.{c['expected_key']}` in _data/fleet.yml"
                                    + (f" (which says `{declared}`)." if declared else "."), line))
            if c["on_hour"]:
                out.append(_finding("cron-on-hour", "workflow", wid, file, f"Cron `{c['cron']}` fires on the hour.", line))
    scheduled = "schedule" in triggers
    if scheduled and wf["ai_sites"] and not wf["switch"]:
        out.append(_finding("kill-switch", "workflow", wid, file,
                            "Scheduled Claude loop with no `vars.*_ENABLED` kill switch.", 1))
    for s in wf["ai_sites"]:
        line = _job_line(text, s["job"])
        if s["max_budget_usd"] is None and not s.get("budget_from_input"):
            out.append(_finding("ai-budget", "workflow", wid, file, f"`{s['site']}` passes no `--max-budget-usd`.", line, s["job"]))
        elif s["max_budget_usd"] is None:
            pass  # the cap comes from an input with no default: test_ai_budget.py owns that case
        elif hub_rules and s["declared_usd"] is None:
            out.append(_finding("ai-budget", "workflow", wid, file,
                                f"`{s['site']}` is not declared under `budget.call_sites` in _data/fleet.yml.", line, s["job"]))
        elif hub_rules and s["declared_usd"] != s["max_budget_usd"]:
            out.append(_finding("ai-budget", "workflow", wid, file,
                                f"`{s['site']}` caps at ${s['max_budget_usd']:g} but fleet.yml declares ${s['declared_usd']:g}.",
                                line, s["job"]))
        if scheduled and s["kind"] == "claude-code-action" and s["continue_on_error"] != "expression":
            skip = s["usage_limit"] == "skip"
            if s["continue_on_error"] != skip or not s["cost_step"]:
                half = ("no claude-cost step" if not s["cost_step"]
                        else "`continue-on-error` without `usage-limit: skip`" if s["continue_on_error"]
                        else "`usage-limit: skip` without `continue-on-error`" if skip
                        else "neither `continue-on-error` nor `usage-limit: skip`")
                out.append(_finding("usage-limit", "workflow", wid, file, f"`{s['site']}`: {half}.", line, s["job"]))
    # A null input reads as false. That only changes behaviour when the input
    # defaults to true: then a cron run and a default dispatch disagree.
    truthy = {i["name"] for i in wf["dispatch_inputs"] if _truthy(i["default"])}
    others = triggers - {"workflow_dispatch", "workflow_call"}
    if truthy and others:
        seen: set[str] = set()
        for expr in _expressions(data.get("jobs") or {}):
            if EVENT_GUARD_RX.search(expr):
                continue
            for m in NULL_CMP_RX.finditer(expr):
                name = m.group(1) or m.group(2) or m.group(3)
                if name in truthy and expr not in seen:
                    seen.add(expr)
                    out.append(_finding("null-input", "workflow", wid, file,
                                        f"`{m.group(0).strip()}` — `inputs.{name}` defaults to true, but on "
                                        f"{', '.join(sorted(others))} runs it is null, which reads as false.",
                                        _line_of(text, re.escape(m.group(0)))))
    if "workflow_run" in triggers:
        out.append(_finding("workflow-run", "workflow", wid, file, "Triggered by `workflow_run`.",
                            _line_of(text, r"^\s+workflow_run:")))
    wf_env = data.get("env") if isinstance(data.get("env"), dict) else {}
    for jid, job in (data.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        job_env = job.get("env") if isinstance(job.get("env"), dict) else {}
        for step in job.get("steps") if isinstance(job.get("steps"), list) else []:
            if not isinstance(step, dict):
                continue
            run = _code(str(step.get("run") or ""))
            env = step.get("env") if isinstance(step.get("env"), dict) else {}
            uses = str(step.get("uses") or "")
            with_ = step.get("with") if isinstance(step.get("with"), dict) else {}
            token = (_token_of(env, job_env, wf_env) if "gh pr create" in run
                     else str(with_.get("token") or "${{ github.token }}") if "create-pull-request" in uses else None)
            if token is not None and ONLY_JOB_TOKEN_RX.match(token):
                out.append(_finding("pr-token", "workflow", wid, file,
                                    f"Job `{jid}` opens a PR with GITHUB_TOKEN; its CI will not run.",
                                    _job_line(text, str(jid)), str(jid)))
            if reusable_only:
                continue
            for line, how in _pushes(run):
                out.append(_finding("bare-push", "workflow", wid, file,
                                    f"Job `{jid}` pushes {how} instead of publishing through publish-data: `{line[:120]}`",
                                    _line_of(text, re.escape(line)), str(jid)))
    if hub_rules and not wf.get("documented", True):
        out.append(_finding("undocumented", "workflow", wid, file, f"`{Path(file).name}` has no row in {README_DOC}."))
    return out


def lint_action(act: dict) -> list[dict]:
    out = []
    if act["parse_error"]:
        return [_finding("parse-error", "action", act["id"], act["file"], act["parse_error"])]
    for field in act.get("description_exprs") or []:
        out.append(_finding("action-description-expr", "action", act["id"], act["file"],
                            f"`{field}` contains `${{{{`; the manifest fails to load."))
    if not act["used_by"]:
        out.append(_finding("action-unused", "action", act["id"], act["file"], "No workflow or action calls it."))
    if not act.get("documented", True):
        out.append(_finding("undocumented", "action", act["id"], act["file"],
                            f"`{act['id']}` has no row in .github/actions/README.md."))
    return out


def lint(atlas: dict, fleet: dict, texts: dict[str, str], hub_rules: bool = True) -> list[dict]:
    out: list[dict] = []
    for wf in atlas["workflows"]:
        try:
            out += lint_workflow(wf, texts.get(wf["file"], ""), fleet, hub_rules)
        except Exception as exc:  # a rule that cannot read a file reports it, never takes the atlas down
            out.append(_finding("parse-error", "workflow", wf["id"], wf["file"], f"{exc.__class__.__name__}: {exc}"[:200]))
    for act in atlas["actions"]:
        out += lint_action(act)
    for orphan in atlas.get("readme_orphans") or []:
        out.append(_finding("undocumented", "workflow", Path(orphan).stem, README_DOC,
                            f"{README_DOC} lists `{orphan}`, which does not exist."))
    order = {s: i for i, s in enumerate(SEVERITIES)}
    return sorted(out, key=lambda f: (order[f["severity"]], f["rule"], f["target"]))


def lint_text(text: str, fleet: dict | None = None, file: str = ".github/workflows/draft.yml",
              hub: str = HUB_DEFAULT) -> dict:
    """Lint one draft workflow (the console's designer, an agent's draft).
    Repo-level rules (README rows, unused actions) do not apply to a draft."""
    fleet = fleet or {}
    wf = parse_workflow(file, text, hub)
    join([wf], [], fleet, hub)
    try:
        findings = lint_workflow(wf, text, fleet, hub_rules=bool(fleet))
    except Exception as exc:
        findings = [_finding("parse-error", "workflow", wf["id"], file, f"{exc.__class__.__name__}: {exc}"[:200])]
    return {"workflow": wf, "findings": findings, "tally": _tally(findings)}


# --------------------------------------------------------------------------- #
# HEALTH — why runs failed
# --------------------------------------------------------------------------- #
CLASSES = {
    "capacity": "Not a defect: a shared limit (the Claude usage window, a call's dollar or turn cap) was spent. "
                "It clears on its own; scheduled sites should be in usage-limit skip mode.",
    "config": "A setting or credential, not the code: fix the repo setting or rotate the secret, then re-run.",
    "transient": "Re-run it. If it repeats, it is not transient.",
    "dependency": "Upstream: a package or Dependabot update. Override, pin the range, or wait for a release.",
    "defect": "The workflow or the code it checks is wrong. Open the log and fix it.",
}
# Order is priority: the 429 run also prints "is_error:true", which must not
# win, and a push rejected by a ruleset says "failed", which must not read as
# a test. Each pattern is matched against one log line.
CAUSES: list[tuple[str, str, re.Pattern]] = [
    ("usage-limit", "capacity", re.compile(
        r"usage limit hit|hit your (?:weekly|session|5-hour|daily|monthly) limit|rate_limit_error|Claude AI usage limit"
        r"|Claude[^\n]*\b429\b|\b429\b[^\n]*Claude", re.I)),
    ("budget-cap", "capacity", re.compile(r"max-budget-usd|budget (?:cap )?(?:hit|exceeded)|exceeded (?:its|the) budget", re.I)),
    ("turn-limit", "capacity", re.compile(r"error_max_turns|reached (?:the )?max(?:imum)? (?:number of )?turns", re.I)),
    ("actions-permission", "config", re.compile(
        r"not permitted to create or approve pull requests|Resource not accessible by (?:integration|personal access token)"
        r"|refusing to allow a GitHub App to create or update workflow", re.I)),
    ("push-rejected", "config", re.compile(
        r"failed to push some refs|\bGH0(?:06|13)\b|protected branch|Changes must be made through a pull request"
        r"|Permission to \S+ denied", re.I)),
    ("auth", "config", re.compile(
        r"Bad credentials|\bHTTP 401\b|\b401 Unauthorized\b|status(?: code)?:? 401\b|\bUnauthorized\b"
        r"|token (?:has )?expired|expired token|credential was REJECTED|expired or revoked|Invalid API key"
        r"|invalid x-api-key|authentication_error|Requires authentication|could not read Username|refused credential"
        r"|\bToken required\b",
        re.I)),
    ("api-rate-limit", "transient", re.compile(
        r"API rate limit exceeded|secondary rate limit|abuse detection|submitted too quickly", re.I)),
    ("missing-ref", "config", re.compile(
        r"Unable to resolve action|unable to find version|Can't find 'action\.ya?ml'|Unrecognized named-value"
        r"|Invalid workflow file|couldn't find remote ref|did not match any file\(s\) known to git", re.I)),
    ("dependabot", "dependency", re.compile(r"Dependabot encountered an error", re.I)),
    ("deps-install", "dependency", re.compile(
        r"npm (?:ERR!|error) code E[A-Z]+|\bEUSAGE\b|\bERESOLVE\b|ResolutionImpossible|No matching distribution found"
        r"|Could not find a version that satisfies|Bundler could not find|Missing: \S+ from lock file", re.I)),
    ("infra", "transient", re.compile(
        r"runner has received a shutdown signal|lost communication with the server|hosted runner encountered an error"
        r"|No space left on device|was not acquired by Runner|\bECONNRESET\b|\bETIMEDOUT\b|Could not resolve host"
        r"|HTTP 50[234]\b", re.I)),
    ("timeout", "transient", re.compile(r"exceeded the maximum execution time|has timed out", re.I)),
    ("agent-error", "defect", re.compile(r"Claude execution failed|is_error:\s*true", re.I)),
    ("code", "defect", re.compile(r"error TS\d+|\b\w*(?:Syntax|Type|Name|Import|Reference|Attribute|Key|Value|Index)Error\b"
                                  r"|ModuleNotFoundError")),
    ("test", "defect", re.compile(r"\bFAILED\b|AssertionError|\b[1-9]\d* (?:failed|failing)\b|(?i:\btests? failed\b|\bfailing tests?\b)")),
    ("gate", "defect", re.compile(r"\bgate failed\b|\bdrifts? from\b|has drifted|\bis stale\b|out of date|not up to date|!= ?manifest"
                                  r"|would reformat|needs regenerat", re.I)),
]
CAUSE_CLASS = {c: k for c, k, _ in CAUSES} | {"timeout": "transient", "startup": "config", "exit-code": "defect"}
TS_RX = re.compile(r"^\ufeff?\d{4}-\d\d-\d\dT[\d:.]+Z\s?")
# GitHub echoes each step before running it — the script in bold cyan and its
# `with:` / `env:` inside a `##[group]Run …` block. A step that PRINTS "usage
# limit hit", or a prompt that mentions it, is not a run that hit it.
ECHO_RX = re.compile(r"\[36;1m|^shell: |^env:$")
GENERIC_RX = re.compile(r"^Process completed with exit code \d+\.?$|^The operation was canceled\.?$"
                        r"|complete log of this run|^npm (?:ERR!|error)\s*$")
# What an error looks like in plain output: a keyword, or a `SomethingError:` / `…Exception:` line.
# A line about a retry is a symptom the step survived, not the reason it failed.
RETRY_RX = re.compile(r"(?i)\bretrying\b|\bwill retry\b")
TAIL_RX = re.compile(r"(?i)\b(?:error|fatal|failed|failure|denied|refused|exceeded|timed out|no space)\b"
                     r"|\b\w*(?:Error|Exception)\b")


def _error_lines(texts) -> tuple[list[str], list[str], list[str]]:
    """(error annotations, error-looking lines from the end of each log entry,
    warning annotations), with GitHub's echo of each step left out. Each entry
    (one per job) is read on its own, so a later job's output cannot push the
    failing job's lines out of the tail."""
    errors, tail, warnings = [], [], []
    for text in ([texts] if isinstance(texts, str) else texts or []):
        kept, echo = [], False
        for raw in (text or "").splitlines():
            line = TS_RX.sub("", raw).strip()
            if line.startswith("##[group]Run "):
                echo = True
            elif line.startswith("##[endgroup]"):
                echo = False
            elif not echo and not ECHO_RX.search(line):
                kept.append(line)
        for line in kept:
            if "##[error]" in line:
                errors.append(line.split("##[error]", 1)[1].strip())
            elif "##[warning]" in line:
                warnings.append(line.split("##[warning]", 1)[1].strip())
        tail += [line for line in kept[-300:] if "##[" not in line and not RETRY_RX.search(line)
                 and (TAIL_RX.search(line) or any(rx.search(line) for _, _, rx in CAUSES))]
    return errors, tail, warnings


def classify_failure(texts, conclusion: str | None = None, failed_step: str | None = None) -> dict:
    """One failed run's log (a text, or one text per job) → {cause, class,
    evidence, hint}. Error annotations are read first, the error-looking tail
    of each job second, warnings last — a cache warning or another job's
    usage-limit skip must not explain a failure."""
    if conclusion == "startup_failure":
        cause, evidence = "startup", "The workflow failed before any job started (invalid file or action manifest)."
    else:
        cause, evidence = None, ""
        errors, tail, warnings = _error_lines(texts)
        for pool in (errors, tail, warnings):
            for name, _cls, rx in CAUSES:
                hit = next((line for line in pool if rx.search(line)), None)
                if hit:
                    cause, evidence = name, hit
                    break
            if cause:
                break
        if not cause:
            cause = "timeout" if conclusion == "timed_out" else "exit-code"
            specific = [e for e in errors if not GENERIC_RX.search(e)]
            plain = [t for t in tail[-20:] if not GENERIC_RX.search(t)]
            evidence = (specific or plain or errors or tail or [""])[0]
    cls = CAUSE_CLASS[cause]
    return {"cause": cause, "class": cls, "evidence": evidence[:300], "hint": CLASSES[cls],
            "failed_step": failed_step}


FAILED = ("failure", "timed_out", "startup_failure")
USAGE_SKIP_RX = re.compile(r"usage limit hit|HTTP 429|hit your (?:weekly|session|5-hour) limit", re.I)


def run_health(runs: list[dict], logs: dict, failed_steps: dict[int, str],
               known: set[str], now: dt.datetime | None = None) -> dict:
    """Roll runs up per workflow file. Pure: rows in, document out.

    runs: dicts with id, workflow_path, event, status, conclusion, created_at,
    run_started_at, updated_at, html_url. logs: run id → its log, one text per
    job (or one text), for any subset. known: the workflow files that exist,
    so the rest are ghosts."""
    per: dict[str, dict] = {}
    for r in sorted(runs, key=lambda x: str(x.get("created_at") or ""), reverse=True):
        path = str(r.get("workflow_path") or "")
        w = per.setdefault(path, {"path": path, "runs": 0, "success": 0, "failure": 0, "cancelled": 0,
                                  "skipped": 0, "other": 0, "events": {}, "causes": {}, "classes": {},
                                  "capacity_skips": 0, "durations": [], "last": None, "last_failure": None,
                                  "failures": []})
        w["runs"] += 1
        concl = str(r.get("conclusion") or "")
        key = ("failure" if concl in FAILED else concl if concl in ("success", "cancelled", "skipped") else "other")
        w[key] += 1
        w["events"][str(r.get("event"))] = w["events"].get(str(r.get("event")), 0) + 1
        start, end = _ts(r.get("run_started_at") or r.get("created_at")), _ts(r.get("updated_at"))
        if start and end and concl not in ("skipped", ""):
            w["durations"].append(max(0.0, (end - start).total_seconds() / 60))
        brief = {k: r.get(k) for k in ("id", "event", "conclusion", "status", "created_at", "html_url", "head_branch")}
        if w["last"] is None and r.get("status") == "completed":
            w["last"] = brief
        if concl in FAILED:
            c = classify_failure(logs.get(r["id"]) or [], concl, failed_steps.get(r["id"]))
            w["causes"][c["cause"]] = w["causes"].get(c["cause"], 0) + 1
            w["classes"][c["class"]] = w["classes"].get(c["class"], 0) + 1
            row = {**brief, **c}
            w["failures"].append(row)
            if w["last_failure"] is None:
                w["last_failure"] = row
        elif concl == "success":
            errors, _, warnings = _error_lines(logs.get(r["id"]) or [])
            if any(USAGE_SKIP_RX.search(e) for e in errors + warnings):
                w["capacity_skips"] += 1
    rows = []
    for w in per.values():
        d = sorted(w.pop("durations"))
        w["p50_min"] = round(d[len(d) // 2], 1) if d else None
        decided = w["success"] + w["failure"]
        w["success_rate"] = round(100 * w["success"] / decided, 1) if decided else None
        w["failures"] = w["failures"][:10]
        last = (w["last"] or {}).get("conclusion")
        w["verdict"] = ("skipping" if w["runs"] and w["skipped"] == w["runs"]
                        else (w["last_failure"] or {}).get("class", "defect") if last in FAILED
                        else "healthy" if last == "success" else last or "idle")
        w["ghost"] = w["path"].startswith(".github/workflows/") and w["path"] not in known
        rows.append(w)
    rows.sort(key=lambda w: (w["path"] not in known, w["path"]))
    totals = {k: sum(w[k] for w in rows) for k in ("runs", "success", "failure", "cancelled", "skipped", "capacity_skips")}
    classes: dict[str, int] = {}
    for w in rows:
        for k, v in w["classes"].items():
            classes[k] = classes.get(k, 0) + v
    return {"workflows": rows, "totals": totals, "classes": classes,
            "ghosts": [w["path"] for w in rows if w["ghost"]], "class_hints": CLASSES}


def _ts(value) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def lake_health(lake_dir: Path | str | None = None, nwo: str = HUB_DEFAULT, days: int = 30,
                root: Path | str = ROOT_DEFAULT) -> dict:
    """run_health over the local lake's runs of one repo (the hub by default)."""
    import fleet_lake  # noqa: WPS433 — the lake is optional; only this function needs it

    d, db = fleet_lake.lake_paths(lake_dir)
    base = {"present": False, "nwo": nwo, "days": days, "workflows": [], "totals": {}, "classes": {},
            "ghosts": [], "class_hints": CLASSES, "synced_at": None}
    if not db.exists():
        return base | {"error": "No lake yet — run `tools/dash lake sync`."}
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=max(1, min(int(days), 365)))).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = fleet_lake.connect(d, create=False)
    try:
        runs = [dict(r) for r in conn.execute(
            "SELECT id, workflow_path, workflow_name, event, status, conclusion, head_branch, created_at, "
            "run_started_at, updated_at, html_url FROM runs WHERE nwo=? AND created_at>=? "
            "ORDER BY created_at DESC LIMIT 5000", (nwo, since))]
        ids = [r["id"] for r in runs if r["conclusion"] in FAILED or r["conclusion"] == "success"]
        logs: dict[int, list[str]] = {}
        steps: dict[int, str] = {}
        for chunk in (ids[i:i + 400] for i in range(0, len(ids), 400)):
            marks = ",".join("?" * len(chunk))
            for rid, text in conn.execute(
                    f"SELECT run_id, text FROM logs WHERE run_id IN ({marks}) ORDER BY run_id, entry", chunk):
                logs.setdefault(rid, []).append(text or "")
            for rid, job, step in conn.execute(
                    f"SELECT j.run_id, j.name, s.name FROM jobs j JOIN steps s ON s.job_id=j.id "
                    f"WHERE j.run_id IN ({marks}) AND s.conclusion='failure' ORDER BY s.number", chunk):
                steps.setdefault(rid, f"{job} › {step}")
        synced = conn.execute("SELECT MAX(finished_at) FROM syncs").fetchone()[0]
    finally:
        conn.close()
    known = {p.relative_to(Path(root)).as_posix() for p in (Path(root) / ".github" / "workflows").glob("*.y*ml")}
    return base | {"present": True, "synced_at": synced, "logs": len(logs)} | run_health(runs, logs, steps, known)


# --------------------------------------------------------------------------- #
# SCAFFOLD — a new workflow inside the standards by construction
# --------------------------------------------------------------------------- #
KINDS = {
    "loop": "Scheduled loop that refreshes committed data (housekeeping slot :07).",
    "agent-loop": "Scheduled Claude loop: kill switch, dollar cap, usage-limit skip (agent slot :37).",
    "gate": "A check on the hub's own pull requests and pushes to main.",
    "reusable": "A workflow member repos call by reference (workflow_call).",
    "dispatch": "A manual tool: workflow_dispatch only, dry run by default.",
}
SCHEDULED_KINDS = ("loop", "agent-loop")


def suggest_cron(kind: str, taken: list[str]) -> str:
    """The first free hour for the kind's minute slot (:07 housekeeping, :37
    agents), skipping hours any existing cron already uses at that minute."""
    minute = 37 if kind == "agent-loop" else 7
    busy: set[int] = set()
    for cron in taken:
        p = hr.parse_cron(cron)
        if p and minute in p["minutes"]:
            busy |= p["hours"]
    hours = range(11, 24) if kind == "agent-loop" else range(1, 24)
    hour = next((h for h in hours if h not in busy), hours[0])
    return f"{minute} {hour} * * *"


def _switch_name(wid: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", wid.upper()).strip("_") + "_ENABLED"


def _template(kind: str, wid: str, name: str, cron: str | None, purpose: str, budget: int) -> str:
    name = json.dumps(name, ensure_ascii=False)   # a JSON string is a valid YAML double-quoted scalar
    purpose = purpose.strip() or "TODO: say what this workflow is for, and what would be lost without it."
    head = "\n".join(f"# {line}".rstrip() for para in purpose.splitlines()
                     for line in (textwrap.wrap(para, 76) or [""]))
    switch = _switch_name(wid)
    if kind == "loop":
        return f"""name: {name}

{head}
#
# Publishes through utilities/publish-data (direct push, else a stable-branch
# PR); the commit carries [skip ci].

on:
  schedule:
    - cron: '{cron}'   # _data/fleet.yml schedule.{schedule_key_for(wid)}
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: {wid}
  cancel-in-progress: false

jobs:
  run:
    name: {name}
    runs-on: ubuntu-latest
    timeout-minutes: 15
    permissions:
      contents: write         # publish the refreshed data
      pull-requests: write    # …via a PR when a direct push is refused
    steps:
      - uses: actions/checkout@v7

      - uses: ./.github/actions/setup/dash-gen

      - name: Generate
        run: |
          echo "TODO - write the data this loop owns under _data/"

      - name: Publish
        uses: ./.github/actions/utilities/publish-data
        with:
          paths: "_data/"
          message: "chore(data): {wid} refresh [skip ci]"
          token: ${{{{ github.token }}}}
"""
    if kind == "agent-loop":
        return f"""name: {name}

{head}
#
# Kill switch: a scheduled firing runs only while the repo variable
# {switch} is 'true' — a new loop starts default-OFF, so set it once a
# dispatched run looks right. A manual dispatch always runs.
# Spend: the agent step is continue-on-error and the cost step owns the
# verdict (usage-limit: skip), so a spent Claude window is a warning.

on:
  schedule:
    - cron: '{cron}'   # _data/fleet.yml schedule.{schedule_key_for(wid)}
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: {wid}
  cancel-in-progress: false

jobs:
  agent:
    name: {name}
    if: ${{{{ github.event_name != 'schedule' || vars.{switch} == 'true' }}}}
    runs-on: ubuntu-latest
    timeout-minutes: 45
    permissions:
      contents: read
      issues: write
      id-token: write         # OIDC for claude-code-action OAuth
    env:
      HAS_CLAUDE_AUTH: ${{{{ secrets.CLAUDE_CODE_OAUTH_TOKEN != '' || secrets.ANTHROPIC_API_KEY != '' }}}}
    steps:
      - uses: actions/checkout@v7

      - name: Choose the Claude credential (ai_auth order)
        id: claude-auth
        if: ${{{{ env.HAS_CLAUDE_AUTH == 'true' }}}}
        uses: ./.github/actions/claude-auth
        with:
          order: ${{{{ vars.CLAUDE_AUTH_ORDER }}}}
          has-oauth: ${{{{ secrets.CLAUDE_CODE_OAUTH_TOKEN != '' }}}}
          api-key: ${{{{ secrets.ANTHROPIC_API_KEY }}}}

      - name: Run the agent
        id: agent
        if: ${{{{ env.HAS_CLAUDE_AUTH == 'true' }}}}
        # continue-on-error: the cost step below owns this job's verdict.
        continue-on-error: true
        uses: anthropics/claude-code-action@v1
        with:
          claude_code_oauth_token: ${{{{ steps.claude-auth.outputs.method == 'oauth' && secrets.CLAUDE_CODE_OAUTH_TOKEN || '' }}}}
          anthropic_api_key: ${{{{ steps.claude-auth.outputs.method == 'api_key' && secrets.ANTHROPIC_API_KEY || '' }}}}
          claude_args: >-
            --model sonnet
            --max-turns 40
            --max-budget-usd {budget}
            --allowedTools "Read,Grep,Glob"
          prompt: |
            TODO: the task, the files to read first, and what done looks like.

      - name: Report Claude run cost
        id: cost
        if: ${{{{ !cancelled() && env.HAS_CLAUDE_AUTH == 'true' }}}}
        uses: ./.github/actions/claude-cost
        with:
          tier: {name}
          budget-usd: "{budget}"
          outcome: ${{{{ steps.agent.outcome }}}}
          usage-limit: skip
"""
    if kind == "gate":
        return f"""name: {name}

{head}

on:
  pull_request:
    paths:
      - '.github/workflows/{wid}.yml'
      - 'TODO/**'
  push:
    branches: [main]
    paths:
      - '.github/workflows/{wid}.yml'
      - 'TODO/**'

permissions:
  contents: read

concurrency:
  group: {wid}-${{{{ github.ref }}}}
  cancel-in-progress: true

jobs:
  check:
    name: {name}
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v7

      - name: Check
        run: |
          echo "TODO - the one command that fails when the change is wrong"
"""
    if kind == "reusable":
        return f"""name: {name}

{head}
#
# Called by reference at a major tag (bamr87/bamr87/.github/workflows/{wid}.yml@v2;
# docs/WORKFLOW-VERSIONING.md). Permissions are not declared: a called
# workflow inherits the caller job's and can only narrow them. A new required
# input, permission or failure condition is a major.

on:
  workflow_call:
    inputs:
      working-directory:
        description: "Directory to run in"
        type: string
        default: "."

jobs:
  run:
    name: {name}
    runs-on: ubuntu-latest
    timeout-minutes: 15
    defaults:
      run:
        working-directory: ${{{{ inputs.working-directory }}}}
    steps:
      - uses: actions/checkout@v7

      - name: Run
        run: |
          echo "TODO"
"""
    return f"""name: {name}

{head}

on:
  workflow_dispatch:
    inputs:
      dry_run:
        description: "Preview only; nothing is written"
        type: boolean
        default: true

permissions:
  contents: read

concurrency:
  group: {wid}
  cancel-in-progress: false

jobs:
  run:
    name: {name}
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v7

      - name: Run
        env:
          DRY_RUN: ${{{{ inputs.dry_run }}}}
        run: |
          echo "TODO - dry run is $DRY_RUN"
"""


def scaffold(kind: str, wid: str, name: str | None = None, cron: str | None = None, purpose: str = "",
             root: Path | str = ROOT_DEFAULT, fleet: dict | None = None) -> dict:
    """A new workflow that passes every rule, and the edits that go with it.
    Raises ValueError on a bad kind, id, name or cron."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    if not ID_RX.match(wid or ""):
        raise ValueError("id must be lowercase letters, digits and dashes (2–41 chars), starting with a letter")
    name = (name or wid.replace("-", " ").title()).strip()
    if not NAME_RX.match(name):
        raise ValueError("name must be one line without quotes, backticks, `$` or backslashes")
    purpose = (purpose or "").replace("\r\n", "\n").replace("\r", "\n")
    if len(purpose) > 2000 or re.search(r"[\x00-\x08\x0b-\x1f\x7f]", purpose):
        raise ValueError("purpose is plain text, at most 2000 characters")
    root = Path(root)
    fleet = load_fleet(root) if fleet is None else fleet
    file = f".github/workflows/{wid}.yml"
    exists = (root / file).exists()
    schedule = dict(fleet.get("schedule") or {})
    key, site = schedule_key_for(wid), f"{wid}.yml:agent"
    if kind in SCHEDULED_KINDS and key in schedule:
        raise ValueError(f"schedule.{key} is already declared in _data/fleet.yml (`{schedule[key]}`) — choose another id")
    if kind == "agent-loop" and site in (((fleet.get("budget") or {}).get("call_sites")) or {}):
        raise ValueError(f"budget.call_sites already declares {site} — choose another id")
    if kind in SCHEDULED_KINDS:
        cron = (cron or "").strip() or suggest_cron(kind, [str(v) for v in schedule.values()])
        p = hr.parse_cron(cron)
        if p is None:
            raise ValueError(f"`{cron}` is not a 5-field numeric cron")
        if 0 in p["minutes"]:
            raise ValueError("no hub cron fires on the hour — use :07 (housekeeping) or :37 (agents)")
    else:
        cron = None
    budget = int(((fleet.get("budget") or {}).get("default_usd")) or 10)
    text = _template(kind, wid, name, cron, purpose, budget)
    switch = _switch_name(wid)
    companion = []
    after = copy.deepcopy(fleet)
    if cron:
        companion.append({"file": "_data/fleet.yml", "where": "schedule:",
                          "snippet": f'  {key}: "{cron}"', "why": "every hub cron is declared here (test_schedule.py)"})
        after.setdefault("schedule", {})[key] = cron
    if kind == "agent-loop":
        companion.append({"file": "_data/fleet.yml", "where": "budget.call_sites:",
                          "snippet": f"    {site}: {budget}", "why": "the dollar cap is declared per call site (test_ai_budget.py)"})
        after.setdefault("budget", {}).setdefault("call_sites", {})[site] = budget
    if kind == "agent-loop":
        companion.append({"file": "repository variables", "where": "Settings → Variables",
                          "snippet": f"{switch}=true",
                          "why": "the agent loop starts default-OFF: set it after a dispatched run looks right"})
    group = {"loop": "Daily and weekly loops", "agent-loop": "Daily and weekly loops", "gate": "Gates on the hub's own changes",
             "reusable": "Reusable workflows", "dispatch": "Fan-outs"}[kind]
    when = {"loop": hr.describe_cron(cron) if cron else "", "agent-loop": hr.describe_cron(cron) if cron else "",
            "gate": "PR, push `main`", "reusable": "`workflow_call`", "dispatch": "dispatch"}[kind]
    companion.append({"file": README_DOC, "where": f"## {group}",
                      "snippet": f"| `{wid}.yml` | {when} | {_plain(purpose).splitlines()[0] if purpose.strip() else 'TODO'} |",
                      "why": "the inventory people read (the `undocumented` rule)"})
    if kind in SCHEDULED_KINDS:
        companion.append({"file": "AGENTS.md", "where": "## The loops and surfaces",
                          "snippet": f"| `{wid}.yml` | … | … |", "why": "the loop table agents read first"})
    result = lint_text(text, after, file)
    return {"kind": kind, "id": wid, "name": name, "file": file, "exists": exists, "cron": cron,
            "cron_human": hr.describe_cron(cron) if cron else None,
            "switch": switch if kind == "agent-loop" else None, "text": text,
            "companion": companion, "findings": result["findings"], "kinds": KINDS}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _print_findings(findings: list[dict]) -> None:
    mark = {"error": "✖", "warn": "⚠", "info": "·"}
    for f in findings:
        where = f"{f['file']}:{f['line']}" if f.get("line") else f["file"]
        print(f"  {mark[f['severity']]} {f['severity']:<5} {f['rule']:<24} {where}  {f['message']}")


def cmd_list(args: argparse.Namespace) -> int:
    atlas = scan(args.root)
    s = atlas["summary"]
    print(f"{s['workflows']} workflows ({s['lines']} lines) · {s['actions']} composite actions · "
          f"{s['scheduled']} scheduled · {s['ai']} with Claude · findings "
          + " ".join(f"{k}={v}" for k, v in s["findings"].items()))
    for wf in atlas["workflows"]:
        cron = ", ".join(c["human"] for c in wf["crons"]) or ""
        f = wf["findings"]
        flag = f"✖{f['error']}" if f["error"] else f"⚠{f['warn']}" if f["warn"] else ""
        print(f"  {wf['group']:<9} {wf['id']:<26} {','.join(wf['triggers'])[:44]:<44} {cron[:24]:<24} {flag}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    atlas = scan(args.root)
    hit = next((w for w in atlas["workflows"] if w["id"] == args.id), None) or \
        next((a for a in atlas["actions"] if a["id"] == args.id), None)
    if hit is None:
        sys.stderr.write(f"no workflow or action called {args.id!r}\n")
        return 1
    print(json.dumps(hit, indent=2, default=str))
    return 0


def cmd_lint(args: argparse.Namespace) -> int:
    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
        findings = lint_text(text, load_fleet(Path(args.root)), args.file)["findings"]
    else:
        findings = scan(args.root)["findings"]
    if args.json:
        print(json.dumps(findings, indent=2))
    else:
        _print_findings(findings)
        t = _tally(findings)
        print(f"{t['error']} error(s), {t['warn']} warning(s), {t['info']} note(s)")
    t = _tally(findings)
    return 1 if t["error"] or (args.strict and t["warn"]) else 0


def cmd_health(args: argparse.Namespace) -> int:
    doc = lake_health(args.lake, args.repo, args.days, args.root)
    if args.json:
        print(json.dumps(doc, indent=2, default=str))
        return 0
    if not doc["present"]:
        print(doc.get("error"))
        return 0
    t = doc["totals"]
    print(f"{doc['nwo']} · last {doc['days']}d · {t['runs']} runs · {t['failure']} failed · "
          f"{t['capacity_skips']} green-but-429 · classes "
          + (" ".join(f"{k}={v}" for k, v in doc["classes"].items()) or "none"))
    for w in doc["workflows"]:
        lf = w["last_failure"] or {}
        rate = f"{w['success_rate']:.0f}%" if w["success_rate"] is not None else "—"
        print(f"  {'👻' if w['ghost'] else '  '} {Path(w['path']).name:<30} {w['runs']:>4} runs {rate:>5}  "
              f"{w['verdict']:<10} {lf.get('cause', '')}: {lf.get('evidence', '')[:70]}")
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    try:
        out = scaffold(args.kind, args.id, args.name, args.cron, args.purpose or "", args.root)
    except ValueError as exc:
        sys.stderr.write(f"workflows new: {exc}\n")
        return 2
    if args.json:
        print(json.dumps(out, indent=2))
        return 0
    if not args.write:
        print(out["text"])
    print(f"\n# lint: {len(out['findings'])} finding(s) once the companion edits below are made", file=sys.stderr)
    _print_findings(out["findings"])
    for c in out["companion"]:
        print(f"# {c['file']} ({c['where']}): {c['snippet']}   — {c['why']}", file=sys.stderr)
    if args.write:
        if any(f["rule"] == "parse-error" for f in out["findings"]):
            sys.stderr.write("workflows new: the scaffold does not parse; nothing written\n")
            return 1
        target = Path(args.root) / out["file"]
        try:
            # "x": create only — refuses any existing path, a dangling symlink included
            with open(target, "x", encoding="utf-8") as fh:
                fh.write(out["text"])
        except FileExistsError:
            sys.stderr.write(f"workflows new: {out['file']} already exists; not overwriting\n")
            return 1
        print(f"wrote {out['file']} — make the companion edits above, then `tools/dash workflows lint`.", file=sys.stderr)
    return 0


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default=str(ROOT_DEFAULT), help="repository root (default: the hub)")
    sub = parser.add_subparsers(dest="workflows_cmd", required=True)
    p = sub.add_parser("list", help="one line per workflow, with its group, triggers, cron and findings")
    p.set_defaults(func=cmd_list)
    p = sub.add_parser("show", help="one workflow or composite action as JSON")
    p.add_argument("id")
    p.set_defaults(func=cmd_show)
    p = sub.add_parser("lint", help="the standards as checks; exit 1 on an error")
    p.add_argument("--file", help="lint one draft workflow file instead of the tree")
    p.add_argument("--json", action="store_true")
    p.add_argument("--strict", action="store_true", help="exit 1 on a warning too")
    p.set_defaults(func=cmd_lint)
    p = sub.add_parser("health", help="run health + failure causes per workflow, from the lake")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--repo", default=HUB_DEFAULT, help="owner/name in the lake (default: the hub)")
    p.add_argument("--lake", default=None, help="lake directory (DASH_LAKE_DIR)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_health)
    p = sub.add_parser("new", help="scaffold a workflow inside the standards (prints it; --write creates it)")
    p.add_argument("--kind", required=True, choices=list(KINDS))
    p.add_argument("--id", required=True, help="file stem, e.g. nightly-audit")
    p.add_argument("--name", default=None)
    p.add_argument("--cron", default=None, help="scheduled kinds: default is the first free :07 / :37 slot")
    p.add_argument("--purpose", default="", help="the header comment: what it is for")
    p.add_argument("--json", action="store_true")
    p.add_argument("--write", action="store_true", help="create the file (never overwrites)")
    p.set_defaults(func=cmd_new)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="workflow_atlas", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(ap)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
