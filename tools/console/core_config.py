"""
core_config — the console's editor for _data/fleet.yml: a section of core's
logic, in its own file.

  CONFIG     a comment-preserving editor for _data/fleet.yml (ruamel
             round-trip), limited to the declared knobs of CONFIG_SECTIONS and
             spliced back one top-level block at a time so the diff covers only
             what the form touched. It edits the working tree and shows the git
             diff; the commit stays with the human — git is the database and
             the review gate, here as everywhere else in the dash.

core.py loads this module at its end and re-exports every name in it, so callers
keep writing `core.<name>`. What core owns (its paths, constants and helpers, the
OPS table, and every name a test or tools/evals.py rebinds) is read here as
`core.<name>` at the moment of the call, never copied, so rebinding one on core
reaches this code as it did when this was a section of core.py. To replace a
name DEFINED here, patch it on this module: this file calls its own names directly.
"""
from __future__ import annotations

import io
import math
import re
import sys
from pathlib import Path

if "core" not in sys.modules:  # the order is a rule, not luck: core loads this module at its end
    raise ImportError("core_config is a section of core: import core, which loads it and re-exports its names")
import core  # noqa: E402


# --------------------------------------------------------------------------- #
# CONFIG — comment-preserving edits to _data/fleet.yml
# --------------------------------------------------------------------------- #
# The contract is the control plane's own settings, so the console edits it the
# way the fleet edits anything else: an ALLOWLIST of declared knobs, validated
# by type, written back through a round trip that keeps every comment, and
# spliced so the diff covers only the blocks the form touched. Anything not
# listed here (structure, comments, the token contract, policy keys the file
# itself calls non-negotiable) stays a text-editor-and-PR change.
CRON_RX = re.compile(r"^[\d*/,\-]{1,24}( +[\dA-Za-z*/,\-]{1,24}){4}$")
VERSION_RX = re.compile(r"^[0-9][0-9A-Za-z.+\-]{0,31}$")
VALUE_RX = re.compile(r"^[A-Za-z0-9._/@:+\- ]{1,120}$")   # canonical variable values
SLUG_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/\-]{0,63}$")


def _f(kind: str, help: str = "", choices: tuple[str, ...] | None = None) -> dict:
    return {"kind": kind, "help": help, "choices": list(choices) if choices else None}


# Sections of _data/fleet.yml the console may edit, in file order. Each field's
# path is relative to its section; the fully qualified key (`section.a.b`) is
# what the API accepts.
CONFIG_SECTIONS: list[dict] = [
    {"key": "toolchain", "title": "Toolchain", "doc": "docs/DASH.md",
     "blurb": "Language versions reusable CI falls back to (caller input → repo vars.* → these).",
     "fields": {
         "node": _f("version", "Node major used by the reusable workflows"),
         "python": _f("version", "Python version"),
         "ruby": _f("version", "Ruby version"),
     }},
    {"key": "schedule", "title": "Schedule (UTC)", "doc": "docs/DAILY-ANALYSIS.md",
     "blurb": "Cron cadence of each control-plane loop. Editing here changes the CONTRACT — "
              "the workflow's own `on: schedule:` is what GitHub obeys, so change both.",
     "fields": {k: _f("cron", d) for k, d in (
         ("fleet_pulse", "gather → publish → remediate"),
         ("build_dash", "republish the Pages site after the data lands"),
         ("issue_pipeline", "intake → implement → complete"),
         ("reconcile_registry", "registry ↔ GitHub reconciliation"),
         ("update_submodules", "daily submodule pointer bump (published directly)"),
         ("rotate_tokens", "weekly credential rotation"),
         ("repo_evolution", "weekly proactive per-repo improvement pass"),
         ("repo_scout", "daily proactive issue proposals — a sample of repos a day"),
         ("weekly_closeout", "Friday 13:17 Denver — close out open PRs, branches and clones"),
         ("weekly_gather", "Saturday 10:17 Denver — draft next week's plan"),
         ("weekly_finalize", "Sunday 16:17 Denver — week-ahead brief"),
     )}},
    {"key": "remediation", "title": "Remediation — the doctor's guardrails", "doc": "docs/DAILY-ANALYSIS.md",
     "blurb": "Blast radius and eligibility of the daily auto-fix loop. Raising max_candidates "
              "without raising the doctor's --max-turns loses the whole day's queue.",
     "fields": {
         "max_candidates": _f("int", "candidates acted on per run"),
         "max_cross_repo": _f("int", "of those, how many may become submodule PRs"),
         "min_runs": _f("int", "ignore workflows with fewer runs in the window"),
         "min_priority": _f("float", "unflagged workflows at/above this are eligible"),
         "slow_avg_min": _f("int", "avg minutes/run that counts as long-running"),
         "slow_p95_min": _f("int", "p95 minutes/run that counts as long-running"),
         "window_days": _f("int", "analytics window"),
         "supersede_on_success": _f("bool", "latest green run drops a failing/flaky flag"),
         "interactive_dispatch_pct": _f("int", "≥ this % hand-dispatched ⇒ cost signals don't apply"),
         "stale_after_days": _f("int", "latest run older than this sorts below live candidates (0 = off)"),
         "min_cost_waste_min": _f("float", "wasted job-min below this ⇒ high-cost-low-value / cancel-heavy don't queue (0 = off)"),
     }},
    {"key": "issue_pipeline", "title": "Issue pipeline — the three tiers", "doc": "docs/ISSUE-PIPELINE.md",
     "blurb": "Per-tier caps, the evidence budget, and the autonomy default. `never_merge` is "
              "deliberately absent: no tier may ever merge.",
     "fields": {
         "enabled": _f("bool", "run the pipeline at all"),
         "tiers.intake.max_issues": _f("int", "issues enriched per run, fleet-wide"),
         "tiers.intake.max_per_repo": _f("int", "…so one noisy backlog can't consume the run"),
         "tiers.implement.max_issues": _f("int", "draft PRs opened per run"),
         "tiers.implement.max_cross_repo": _f("int", "of those, how many land outside the hub"),
         "tiers.complete.max_prs": _f("int", "pipeline PRs driven toward mergeable per run"),
         "evidence.enabled": _f("bool", "build evidence bundles in the virtual environment"),
         "evidence.max_runs": _f("int", "evidence bundles built per run"),
         "evidence.ttl_days": _f("int", "a bundle newer than this is reused"),
         "evidence.timeout_minutes": _f("int", "per phase (clone/install/lint/test/build)"),
         "evidence.screenshots": _f("bool", "capture a page screenshot for web stacks"),
         "readiness.min_score": _f("int", "below this T1 must not pass an issue on"),
         "autonomy.default": _f("choice", "what may proceed unattended", ("auto", "assisted")),
     }},
    {"key": "evolution", "title": "Repo evolution — the weekly proactive loop", "doc": "docs/EVOLUTION.md",
     "blurb": "One Opus agent and one draft PR per target. The model and the turn cap are not edited "
              "here: the step spec (tools/jev/steps/repo-evolution/evolve.yml) references evolution.model and "
              "evolution.max_turns, and the workflow carries both as literals that `python3 -m tools.jev steps "
              "check` holds equal, so a change is a pull request that moves fleet.yml and the workflow together.",
     "fields": {
         "enabled": _f("bool", "run the weekly pass"),
         "skip_when_open_pr": _f("bool", "one open evolution PR per repo is the backpressure"),
         "max_targets": _f("int", "repos evolved per run"),
         "max_parallel": _f("int", "concurrent agents (one OAuth account's rate limit)"),
         "signals.max_issues": _f("int", "issues quoted into each brief"),
         "signals.max_prs": _f("int", "PRs quoted into each brief"),
     }},
    {"key": "harness", "title": "Harness health — scorecard + trip wires", "doc": "docs/HARNESS.md",
     "blurb": "The hub watching itself: pass/fail lines, the aggregate-drift alarms and the "
              "agentic layer's wires that `dash harness` computes offline from the committed "
              "signals. The agentic thresholds are a gated change (constitution § 29.8).",
     "fields": {
         "scorecard.completion_rate_min_pct": _f("float", "fleet workflow success rate floor"),
         "scorecard.effectiveness_min_pct": _f("float", "minutes ending in success, as a share of all minutes"),
         "trip_wires.stale_data_days": _f("int", "a signal older than this is an alarm"),
         "trip_wires.conformance_stale_days": _f("int", "conformance.yml older than this is an alarm"),
         "trip_wires.pass_rate_floor_pct": _f("float", "fleet-wide quality regression"),
         "trip_wires.waste_ceiling_pct": _f("float", "non-success minutes / total minutes"),
         "trip_wires.cost_spike_multiplier": _f("float", "× the fleet MEDIAN run time = runaway"),
         "trip_wires.cost_spike_min_runs": _f("int", "ignore workflows with fewer runs"),
         "trip_wires.cost_spike_min_avg_min": _f("float", "…and anything cheaper than this on average"),
         "trip_wires.standing_failures_max": _f("int", "red-workflow backlog the doctor can't drain"),
         "trip_wires.credential_grace_days": _f("int", "past max_age + this, a credential is an alarm"),
         "agentic.shadow_days": _f("int", "days a new agentic wire reports before it can count as tripped"),
         "agentic.parity_tolerance_pct": _f("float", "a derived total further than this from its source is a gap"),
         "agentic.unknown_cost_max_pct": _f("float", "agent runs whose cost can't be read, as a share of runs that spent"),
     }},
    {"key": "harnesses", "title": "Harnesses — the fleet deployment contract", "doc": "docs/HARNESS-OPS.md",
     "blurb": "What every owned repo must carry, how much scheduled agent work the fleet may "
              "commit to, and what the projected spend may grow to before somebody is told.",
     "fields": {
         "baseline.require_mention_handler": _f("bool", "a claude-code-action workflow answering @claude"),
         "baseline.require_agent_context": _f("bool", "CLAUDE.md / AGENTS.md / copilot-instructions / .cursorrules"),
         "baseline.require_oauth_secret": _f("bool", "CLAUDE_CODE_OAUTH_TOKEN present per the rotation ledger"),
         "exempt": _f("list", "repo names excused from the baseline"),
         "throughput.max_scheduled_ai_per_day_fleet": _f("int", "estimated cron-driven AI runs/day, fleet-wide"),
         "throughput.max_scheduled_ai_per_day_repo": _f("int", "the same per repo"),
         "throughput.max_ai_crons_per_utc_hour": _f("int", "AI crons sharing one UTC hour"),
         "budget.monthly_ai_usd": _f("float", "projected monthly Claude CI spend ceiling"),
         "budget.monthly_actions_minutes": _f("int", "projected monthly Actions minutes ceiling"),
         "budget.trend_warn_pct": _f("float", "week-over-week growth beyond this is flagged"),
         "inventory.max_workflow_files": _f("int", "workflow files parsed per repo"),
         "inventory.schedule_limit": _f("int", "rows in the fleet schedule calendar"),
         "attention_max": _f("int", "findings surfaced per run"),
     }},
    {"key": "observability", "title": "Observability — the local planes and the code index", "doc": "docs/OBSERVABILITY.md",
     "blurb": "Retention, disk budget and the portal's pinned dashboards. Changing retention or "
              "rollover here changes only the CONTRACT — re-render and re-install with "
              "`dash observe verify --write` then `dash observe up`, or the cluster keeps expiring "
              "on the old schedule.",
     "fields": {
         "logs.retention_days.actions": _f("int", "days of GitHub Actions log lines"),
         "logs.retention_days.container": _f("int", "days of raw container stdout"),
         "logs.retention_days.app": _f("int", "days of UPS-OPS-10 structured lines"),
         "logs.rollover.max_primary_shard_size": _f("version", "roll an index over at this size"),
         "logs.rollover.max_age": _f("version", "…or this age, whichever comes first"),
         "logs.disk_budget_gb": _f("int", "`observe status` warns past this (ES stops writing at 95% disk)"),
         "logs.ship.batch": _f("int", "documents per bulk POST to Logstash"),
         "logs.ship.logs": _f("choice", "which runs to ship", ("all", "ai", "none")),
         "portal.embed": _f("bool", "embed Kibana + Grafana in the Observe tab, or link out only"),
     }},
    {"key": "ai_auth", "title": "AI auth order — which Claude credential each repo tries first",
     "doc": "docs/AI-INTEGRATION.md",
     "blurb": "The fleet-wide DEFAULT order. Groups and per-repo overrides are structure, so they "
              "are edited in the file by PR; `ai-auth` below shows what every repo resolves to. "
              "Saving here changes only the contract — project it with `ai-auth-sync`.",
     "fields": {
         "default": _f("choice", "tried in turn; the first present (and, for a key, accepted) wins",
                       ("oauth,api_key", "api_key,oauth", "oauth", "api_key")),
     }},
    {"key": "rotation", "title": "Token rotation", "doc": "docs/TOKEN-ROTATION.md",
     "blurb": "The weekly credential loop. `hub_first` is not offered here — the file calls it "
              "non-negotiable, and it is the rule that keeps a bad credential an incident "
              "rather than an outage.",
     "fields": {
         "enabled": _f("bool", "run the weekly pass"),
         "only_stale": _f("bool", "rewrite only what is missing or past max_age_days"),
         "max_repos": _f("int", "0 = no cap (fleet-wide consistency is the point)"),
         "max_failures": _f("int", "abort the remaining writes past this many failures"),
         "fail_on_unreachable": _f("bool", "treat a repo the token cannot see as fatal"),
         "variables.enabled": _f("bool", "propagate canonical repo variables in the same pass"),
         "variables.warn_on_fallback": _f("bool", "say so when the hub lacks a declared variable"),
     }},
    {"key": "variables", "title": "Canonical repository variables", "doc": "docs/TOKEN-ROTATION.md",
     "blurb": "The FALLBACK values (bamr87/bamr87's live settings are authoritative). "
              "Project them with `dash config sync --apply` or the weekly rotation.",
     "fields": {
         "NODE_VERSION": _f("value", "vars.NODE_VERSION"),
         "PYTHON_VERSION": _f("value", "vars.PYTHON_VERSION"),
         "RUBY_VERSION": _f("value", "vars.RUBY_VERSION"),
         "FLEET_HUB": _f("value", "owner/repo of the hub"),
     }},
]

# fully qualified key → field spec
CONFIG_FIELDS: dict[str, dict] = {
    f"{section['key']}.{path}": spec
    for section in CONFIG_SECTIONS for path, spec in section["fields"].items()
}

# Back-compat: the harnesses-relative knobs the Contract API has always taken.
EDITABLE = {path: spec["kind"] for path, spec in
            next(s for s in CONFIG_SECTIONS if s["key"] == "harnesses")["fields"].items()}


def _dig(node, parts: list[str]):
    """Walk a dotted path, returning (parent, leaf, present)."""
    for part in parts[:-1]:
        if not isinstance(node, dict) or part not in node:
            return None, parts[-1], False
        node = node[part]
    if not isinstance(node, dict) or parts[-1] not in node:
        return None, parts[-1], False
    return node, parts[-1], True


def read_config(fleet_path: Path = core.DATA / "fleet.yml") -> dict:
    """Every editable knob with its current value — the Config tab's document."""
    fleet = core.load_yaml(fleet_path) or {}
    sections = []
    for section in CONFIG_SECTIONS:
        block = fleet.get(section["key"])
        fields = []
        for path, spec in section["fields"].items():
            parent, leaf, present = _dig(block, path.split("."))
            fields.append({
                "path": path, "key": f"{section['key']}.{path}", "kind": spec["kind"],
                "help": spec["help"], "choices": spec["choices"],
                "value": parent[leaf] if present else None, "present": present,
            })
        sections.append({k: section[k] for k in ("key", "title", "blurb", "doc")} |
                        {"present": isinstance(block, dict), "fields": fields})
    return {"path": str(fleet_path.relative_to(core.REPO_ROOT)) if fleet_path.is_relative_to(core.REPO_ROOT)
            else str(fleet_path),
            "sections": sections, "editable": sorted(CONFIG_FIELDS)}


def read_contract(fleet_path: Path = core.DATA / "fleet.yml") -> dict:
    """The harnesses: block alone, in the shape the Contract API has always returned."""
    fleet = core.load_yaml(fleet_path) or {}
    return {"harnesses": fleet.get("harnesses") or {}, "editable": sorted(EDITABLE)}


def _coerce(key: str, value):
    """Validate one value against its declared kind. `key` is fully qualified,
    or harnesses-relative (the Contract API's older shape)."""
    spec = CONFIG_FIELDS.get(key) or CONFIG_FIELDS.get(f"harnesses.{key}")
    if spec is None:
        raise ValueError(key)
    kind = spec["kind"]
    if kind == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return value.lower() == "true"
        raise ValueError(f"{key} must be true/false")
    if kind == "int":
        try:
            n = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be an integer")
        if n < 0:
            raise ValueError(f"{key} must be >= 0")
        return n
    if kind == "float":
        try:
            f = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a number")
        if not math.isfinite(f):     # "inf" and "nan" parse; a .inf ceiling bounds nothing
            raise ValueError(f"{key} must be a finite number")
        if f < 0:
            raise ValueError(f"{key} must be >= 0")
        return int(f) if f.is_integer() else f
    if kind == "list":
        if isinstance(value, str):
            value = [v.strip() for v in value.split(",") if v.strip()]
        if not isinstance(value, list) or not all(isinstance(v, str) and core.NAME_RX.match(v) for v in value):
            raise ValueError(f"{key} must be a list of repo names")
        return _flow_seq(value)
    if kind == "choice":
        v = str(value).strip()
        if v not in (spec["choices"] or []):
            raise ValueError(f"{key} must be one of {spec['choices']}")
        return v
    if kind in ("cron", "version", "value", "slug"):
        v = str(value).strip()
        rx = {"cron": CRON_RX, "version": VERSION_RX, "value": VALUE_RX, "slug": SLUG_RX}[kind]
        if not rx.match(v):
            raise ValueError(f"{key} must match {rx.pattern}")
        return v
    raise ValueError(key)


def _flow_seq(items: list):
    """A list written inline (`exempt: [a, b]`), matching fleet.yml's own style.

    Not cosmetic: these keys carry a trailing `# comment`, and ruamel emits a
    BLOCK sequence's items after the comment paragraph that follows the key —
    so `exempt:` and its entries end up separated by the next section's
    comment. Still valid YAML, but it reads as though the comment owns the
    list. A flow sequence cannot be split from its key.
    """
    try:
        from ruamel.yaml.comments import CommentedSeq
    except ImportError:                       # pragma: no cover - plain list still works
        return items
    seq = CommentedSeq(items)
    seq.fa.set_flow_style()
    return seq


_AMBIGUOUS_SCALAR_RX = re.compile(
    r"^(-?\d+(\.\d+)?|true|false|yes|no|on|off|null|~)$", re.IGNORECASE)


def _styled(old, value: str):
    """Write a string back in the quoting style the file already used.

    `node: "20"` must not come back as `node: '20'` (a needless diff line) and a
    plain `FLEET_HUB: bamr87/bamr87` must not gain quotes it never had. A value
    YAML would read back as a number or a bool is quoted whatever the old style
    was — that is correctness, not cosmetics.
    """
    try:
        from ruamel.yaml.scalarstring import DoubleQuotedScalarString as DQ
        from ruamel.yaml.scalarstring import SingleQuotedScalarString as SQ
    except ImportError:                       # pragma: no cover
        return value
    if isinstance(old, DQ):
        return DQ(value)
    if isinstance(old, SQ):
        return SQ(value)
    return DQ(value) if _AMBIGUOUS_SCALAR_RX.match(value) else value


def update_config(changes: dict, fleet_path: Path = core.DATA / "fleet.yml") -> dict:
    """Apply validated changes to fleet.yml, preserving every comment (ruamel
    round-trip) and splicing back only the top-level blocks that changed.

    Keys are fully qualified (`remediation.max_candidates`); a bare key is read
    as harnesses-relative, which is what the older Contract API sends.
    """
    try:
        from ruamel.yaml import YAML
    except ImportError:
        raise RuntimeError("config editing needs ruamel.yaml (pip install ruamel.yaml)")
    resolved: dict[str, str] = {}
    for key in changes:
        if key in CONFIG_FIELDS:
            resolved[key] = key
        elif f"harnesses.{key}" in CONFIG_FIELDS:
            resolved[key] = f"harnesses.{key}"
        else:
            raise ValueError(f"not editable from the console: {key}")
    yml = YAML(typ="rt")
    yml.preserve_quotes = True
    yml.width = 4096
    # Match fleet.yml's own layout, or the round trip "fixes" the whole file:
    # ruamel's default puts a block sequence's dash at the parent's indent,
    # while this file indents it (`tokens:` / `  - name:`), so a one-field edit
    # came back as a 188-line reindent of every list in the document.
    yml.indent(mapping=2, sequence=4, offset=2)
    original = fleet_path.read_text()
    doc = yml.load(original)
    applied: dict[str, object] = {}
    touched: list[str] = []
    for key, full in resolved.items():
        coerced = _coerce(full, changes[key])
        parts = full.split(".")
        if parts[0] not in doc:
            raise ValueError(f"fleet.yml has no {parts[0]}: block")
        parent, leaf, present = _dig(doc[parts[0]], parts[1:])
        if not present:
            raise ValueError(f"fleet.yml {full} is not declared; add it by hand first")
        if isinstance(coerced, str):
            coerced = _styled(parent[leaf], coerced)
        if parent[leaf] != coerced:
            parent[leaf] = coerced
            applied[key] = str(coerced) if isinstance(coerced, str) else coerced
            if parts[0] not in touched:
                touched.append(parts[0])
    if applied:
        buf = io.StringIO()
        yml.dump(doc, buf)
        rewritten = buf.getvalue()
        text = original
        for block_key in touched:
            spliced = _splice_block(text, rewritten, block_key)
            if spliced is None:               # a shape we don't recognise
                text = rewritten
                break
            text = spliced
        fleet_path.write_text(text)
    rc, diff = core.run_quiet(["git", "diff", "--no-color", "--", str(fleet_path)])
    return {"applied": applied, "sections": touched, "diff": diff if rc == 0 else ""}


def update_contract(changes: dict, fleet_path: Path = core.DATA / "fleet.yml") -> dict:
    """The harnesses-scoped half of update_config (the Contract API's shape)."""
    unknown = sorted(k for k in changes if f"harnesses.{k}" not in CONFIG_FIELDS)
    if unknown:
        raise ValueError(f"not editable from the console: {', '.join(unknown)}")
    result = update_config({f"harnesses.{k}": v for k, v in changes.items()}, fleet_path)
    return {"applied": {k.split(".", 1)[1]: v for k, v in result["applied"].items()},
            "diff": result["diff"]}


def _top_level_block(text: str, key: str) -> tuple[int, int] | None:
    """Line span [start, end) of a top-level `key:` block, its comments included."""
    lines = text.splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if ln.startswith(f"{key}:")), None)
    if start is None:
        return None
    for i in range(start + 1, len(lines)):
        # the next top-level key ends the block; blanks and indented lines don't
        if lines[i][:1] not in (" ", "\t", "\n", "#") and lines[i].strip():
            return start, i
    return start, len(lines)


def _splice_block(original: str, rewritten: str, key: str) -> str | None:
    """Put only `key:`'s block from the rewritten document back into the original.

    Even correctly configured, a ruamel round trip renormalises things it was
    never asked to touch — here it re-joined two hand-wrapped `used_by:` flow
    lists in the read-only `tokens:` block. The console's promise is that saving
    shows you a diff you can read and commit, so the write is confined to the
    blocks the form edited; everything else stays byte-identical. Returns None
    when either document's shape isn't recognisable, so the caller can fall
    back to the whole round trip rather than guess.
    """
    a, b = _top_level_block(original, key), _top_level_block(rewritten, key)
    if not a or not b:
        return None
    src, dst = original.splitlines(keepends=True), rewritten.splitlines(keepends=True)
    return "".join(src[:a[0]] + dst[b[0]:b[1]] + src[a[1]:])
