#!/usr/bin/env python3
"""
File: tools/jev/spec.py
Description: JEV capability two — loop STEP SPECS. One file pair per agent step
             a loop runs (`tools/jev/steps/<loop>/<step>.yml` + its
             `<step>.prompt.txt`): the hard-rules prompt, the caller-filled
             inputs, the tool allowlist, the wall clock, the workspace contract
             and the § 13.6 risk tags. Model, turns and dollars are never
             copied here: the spec REFERENCES `_data/fleet.yml` and this module
             resolves them, refusing a model that is not an exact id in
             `ai_models.allowed` (constitution § 13.3).
             CI renders the prompt from it (repo_scout.build_plan → the matrix)
             and the local loop engine (P1, #484) renders the same bytes, so a
             local run is the CI run. `parity_errors` holds the workflow's
             literals — caps, allowlist, timeout, artifact paths, the token-free
             agent env — equal to the resolved spec, and lints the prompt
             against its own grant (bamr87/bamr87#89). The agent step pins the
             spec pair's content hash as `env: JEV_STEP_SHA256`, so an edit to
             the hard rules is also an edit to the workflow file — the
             `workflow`-scope barrier GITHUB_TOKEN and the Claude App cannot
             cross. Decision: docs/adr/0002.
             `loop-step/v1` evolves like harness-registry/v1: an optional key
             added with its loader support keeps v1; a removal, rename, new
             required key or changed meaning bumps the id. The loader stays
             strict (an unknown key is refused), and consumers read specs
             through this module, never the YAML.
             The optional `local:` block (P1, #486) says how `python3 -m
             tools.jev loop` runs the step on a workstation: the adapter, the
             kill switch (held equal to the workflow's gating `if:`), the
             planner and publish argv templates and the budget-hit rule. CI and
             every P0 consumer ignore it.
Author: bamr87
Created: 2026-10-30
Version: 0.1.0
Usage: python3 -m tools.jev steps check
       python3 -m tools.jev steps render <loop> <step> --set TOKEN=value …
Dependencies: PyYAML. No dash-gen import: the two cap regexes are inlined below.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TypeGuard

import yaml

from .common import FLEET_YML, HUB, JevError, is_clone_relpath, is_nwo

SPEC_ROOT = HUB / "tools" / "jev" / "steps"
WORKFLOWS_DIR = HUB / ".github" / "workflows"
SCHEMA_ID = "loop-step/v1"

#: `{{UPPER_SNAKE}}` — the brief templates' token syntax (.github/scout/README.md),
#: rendered here in ONE pass so a value is never re-scanned for tokens.
TOKEN_RX = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")
BRACE_RX = re.compile(r"\{\{|\}\}")
NAME_RX = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
ROW_KEY_RX = re.compile(r"[a-z_][a-z0-9_]*")
CALL_SITE_RX = re.compile(r"[\w.-]+\.yml:[\w-]+")
DOTTED_RX = re.compile(r"[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)+")
# Inlined from .github/scripts/dash-gen/harness_registry.py:87 and :91-92 so
# tools/jev never imports dash-gen; keep them equal to those.
MAX_TURNS_RX = re.compile(r"--max-turns\s+(\d+)")
MAX_BUDGET_RX = re.compile(
    r"(?:--max-budget-usd[= ]\s*|max-budget-usd:\s*['\"]?)([0-9]+(?:\.[0-9]+)?)")
MODEL_EXPR_RX = re.compile(r"--model\s+\$\{\{")
#: The one expression form parity accepts: the plan job's output, which the plan
#: fills from the same fleet.yml key the spec resolves. No vars./inputs./fallback.
MODEL_PLAN_RX = re.compile(r"--model\s+\$\{\{\s*needs\.[\w-]+\.outputs\.model\s*\}\}")
MODEL_LITERAL_RX = re.compile(r"--model\s+([\w.@-]+)")
ALLOWED_TOOLS_RX = re.compile(r'--allowedTools\s+"([^"]*)"')
#: How a prompt orders a tool by name ("Read … with the Read tool"). Every tool
#: named this way must be granted — #89 ordered a Read it never granted.
TOOL_ORDER_RX = re.compile(r"\b(?:with|use|using) the ([A-Z][A-Za-z]+) tool\b")
CLAUDE_ACTION = "anthropics/claude-code-action"
#: The agent step's env key holding StepSpec.content_sha256 (a runtime no-op).
STEP_SHA_ENV = "JEV_STEP_SHA256"
COST_ACTION = "/.github/actions/claude-cost"
#: A GitHub credential in an env value: `github.token`, or any secret except the
#: two Claude credentials (the job's HAS_CLAUDE_AUTH probe names those).
GITHUB_CRED_RX = re.compile(
    r"\bgithub\.token\b|\bsecrets\.(?!(?:CLAUDE_CODE_OAUTH_TOKEN|ANTHROPIC_API_KEY)\b)[A-Za-z_]\w*")
#: An earlier step exporting a token to every later step (a heuristic).
GITHUB_ENV_EXPORT_RX = re.compile(r"\b(?:GH_TOKEN|GITHUB_TOKEN)=[^\n]*\bGITHUB_ENV\b")
#: The agent step's own inputs that legitimately carry a Claude credential, and
#: the prompt (parity holds it equal to the spec, which cannot hold `${{`).
CREDENTIAL_SCAN_SKIP = frozenset({"claude_code_oauth_token", "anthropic_api_key", "prompt"})

REQUIRED_KEYS = frozenset({"schema", "loop", "step", "call_site", "step_id", "prompt", "inputs",
                           "model_from", "max_turns_from", "timeout_minutes", "allowed_tools",
                           "workspace"})
OPTIONAL_KEYS = frozenset({"risk", "evals", "local"})
WORKSPACE_KEYS = frozenset({"cwd", "brief_dir", "outputs", "github_credential"})
WORKSPACE_OPTIONAL = frozenset({"exceptions"})
#: v1 knows one credential posture; a step that holds a token (P3: doctor,
#: issue-pipeline) extends this set in its own PR, with the parity it needs.
GITHUB_CREDENTIALS = frozenset({"none"})
#: What claude-code-action does outside the step's `env:`, breaking a
#: `github_credential: none` contract. Parity reports each one the workflow
#: leaves open; a spec may declare one as a known exception
#: (`workspace.exceptions.<gap>: why`) until the workflow closes it (ADR 0002).
ACTION_GAPS = {
    "app-token": "with no `github_token` input the action mints its GitHub App token (contents, issues and "
                 "pull requests: write) over OIDC and exports it as GH_TOKEN/GITHUB_TOKEN to Claude's "
                 "subprocesses, unless CLAUDE_CODE_SUBPROCESS_ENV_SCRUB is set",
    "setting-sources": "without `--setting-sources` the action loads the checkout's own .claude/ settings "
                       "(permissions.allow and hooks) on top of `--allowedTools`",
}
RISK_TAGS = frozenset({"reversible", "external", "money"})
RISK_TIERS = ("low", "medium", "high")
RISK_KEYS = frozenset({"what", "tags", "tier"})
FORBIDDEN_TEMPLATE_CHARS = {"\r": "CR", "\t": "tab", "\x00": "NUL", "﻿": "BOM"}
# `local:` (P1). Every sub-key has a consumer in tools/jev/loop.py; P3 adds more
# (tiers, workspace kinds, rounds) as optional sub-keys, which keeps v1.
LOCAL_KEYS = frozenset({"adapter", "switch", "planner", "publish", "on_budget_hit"})
LOCAL_REQUIRED = frozenset({"adapter", "planner"})
SWITCH_KEYS = frozenset({"config", "variable", "default"})
PLANNER_KEYS = frozenset({"argv", "flags"})
#: engine option → the planner's own flag (`--target NAME` is passed as `--target=NAME`)
PLANNER_FLAGS = frozenset({"target", "focus", "day", "offline", "no_files"})
PUBLISH_KEYS = frozenset({"argv", "apply_flag", "risk"})
#: JEV's rule: a budget-hit attempt is discarded. P3 adds `publish-flagged` (evolve).
ON_BUDGET_HIT = frozenset({"discard"})
#: The `{token}`s an argv template may carry; the engine fills them, one pass.
#: `bodies_dir` is the publish phase's own directory (the dry preview's and the
#: apply's differ, so filing never overwrites the bodies a person reviewed).
ARG_TOKENS = frozenset({"plan_dir", "nwo", "name", "branch", "item_dir", "validated", "run_ref", "bodies_dir"})
ARG_TOKEN_RX = re.compile(r"\{([a-z_]+)\}")
SUBCOMMAND_RX = re.compile(r"[a-z][a-z0-9-]*")
#: The `tools/dash-gen` subcommands a `local:` argv may run. A planner only
#: reads (`loop plan` runs it, documented $0 and write-free); a filer writes
#: only behind its apply flag, which the engine adds after the § 13.6 gate.
#: Adding one is a reviewed change here (ai-run, or any writer, is never a planner).
#: A filer is pinned with its own apply flag: a spec's `apply_flag` must be it.
PLANNER_COMMANDS = frozenset({"scout"})
PUBLISH_COMMANDS = {"scout-file": "--apply"}
#: the write flag no planner may carry, whatever the spec's publish block says
APPLY_FLAG = "--apply"
FLAG_RX = re.compile(r"--[a-z][a-z0-9-]*")
SWITCH_VAR_RX = re.compile(r"[A-Z][A-Z0-9_]*_ENABLED")


class StepSpecError(JevError):
    """A spec that does not load, resolve or render. Names the file and field."""


# --------------------------------------------------------------------------- #
# the spec
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Resolved:
    """The values a spec references in `_data/fleet.yml`, resolved."""

    model: str
    max_turns: int
    max_budget_usd: float


@dataclass(frozen=True)
class Workspace:
    """What a runner must reproduce around the agent (validated by the loader)."""

    cwd: str
    brief_dir: str
    outputs: tuple[str, ...]
    github_credential: str
    #: ACTION_GAPS key → why it is still open; empty when the workflow closes them all.
    exceptions: Mapping[str, str]


@dataclass(frozen=True)
class Switch:
    """The step's kill switch: a `_data/fleet.yml` bool honoured on every run,
    and the repo variable a SCHEDULED local run reads, with its default."""

    config: str
    variable: str
    default: str  # 'on' | 'off'


@dataclass(frozen=True)
class ArgvTemplate:
    """A `tools/dash-gen` command line with `{token}` placeholders."""

    argv: tuple[str, ...]
    #: planner only: engine option → the planner's flag
    flags: Mapping[str, str]
    #: publish only: the flag that turns the dry run into the write
    apply_flag: str = ""
    #: publish only: the `risk.<action>` whose tier governs the write
    risk: str = ""


@dataclass(frozen=True)
class LocalSpec:
    """How the local loop engine runs this step (`local:`; ADR 0002, P1)."""

    adapter: str
    planner: ArgvTemplate
    switch: Switch | None = None
    publish: ArgvTemplate | None = None
    on_budget_hit: str = "discard"


@dataclass(frozen=True)
class StepSpec:
    path: Path
    loop: str
    step: str
    call_site: str
    step_id: str
    prompt_file: Path
    template: str
    inputs: dict[str, str]
    model_from: str
    max_turns_from: str
    timeout_minutes: int
    allowed_tools: tuple[str, ...]
    workspace: Workspace
    risk: Mapping[str, Mapping[str, object]] | None
    evals: str | None
    resolved: Resolved
    #: sha256 of <step>.yml's bytes, a NUL, then <step>.prompt.txt's bytes —
    #: what the workflow pins as STEP_SHA_ENV.
    content_sha256: str
    #: the optional `local:` block; None for a step with no local runner yet
    local: LocalSpec | None = None

    @property
    def workflow_file(self) -> str:
        return self.call_site.split(":", 1)[0]

    @property
    def job(self) -> str:
        return self.call_site.split(":", 1)[1]

    @property
    def template_sha256(self) -> str:
        """The prompt template's content hash — what a § 13.5 trace pins."""
        return hashlib.sha256(self.template.encode("utf-8")).hexdigest()

    def allowed_tools_arg(self) -> str:
        """The `--allowedTools` value, in spec order."""
        return ",".join(self.allowed_tools)


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that refuses a duplicate mapping key (YAML keeps the last one)."""


def _construct_unique(loader: _UniqueKeyLoader, node: yaml.MappingNode) -> dict:
    seen: set = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node)
        if key in seen:
            raise yaml.constructor.ConstructorError(None, None, f"duplicate key {key!r}", key_node.start_mark)
        seen.add(key)
    return loader.construct_mapping(node)


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique)


def spec_path(loop: str, step: str, root: Path = SPEC_ROOT) -> Path:
    for label, value in (("loop", loop), ("step", step)):
        if not isinstance(value, str) or not NAME_RX.fullmatch(value):
            raise StepSpecError(f"{label} id {value!r} must match {NAME_RX.pattern}")
    return Path(root) / loop / f"{step}.yml"


def load_fleet(path: Path = FLEET_YML) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def fleet_value(fleet: Mapping, dotted: str) -> object:
    """`a.b.c` in `_data/fleet.yml`; raises when any segment is absent."""
    node: object = fleet
    for part in dotted.split("."):
        if not isinstance(node, Mapping) or part not in node:
            raise StepSpecError(f"_data/fleet.yml has no `{dotted}`")
        node = node[part]
    return node


def allowed_models(fleet: Mapping) -> set[str]:
    """Every id under `ai_models.allowed`, whichever provider list it is in."""
    allowed = (fleet.get("ai_models") or {}).get("allowed")
    lists = allowed.values() if isinstance(allowed, Mapping) else [allowed or []]
    return {str(m) for ids in lists for m in (ids or [])}


def _positive_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _positive_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def resolve(fleet: Mapping, *, model_from: str, max_turns_from: str, call_site: str,
            where: str = "spec") -> Resolved:
    """Model, turns and the call-site dollar cap from `_data/fleet.yml`."""
    model = fleet_value(fleet, model_from)
    allowed = allowed_models(fleet)
    if not isinstance(model, str) or model not in allowed:
        raise StepSpecError(
            f"{where}: model {model!r} ({model_from}) is not an exact id in _data/fleet.yml "
            f"ai_models.allowed {sorted(allowed)} — an alias is refused (constitution § 13.3)")
    turns = fleet_value(fleet, max_turns_from)
    if not _positive_int(turns):
        raise StepSpecError(f"{where}: {max_turns_from} = {turns!r} is not a positive integer")
    sites = ((fleet.get("budget") or {}).get("call_sites") or {})
    if call_site not in sites:
        raise StepSpecError(f"{where}: _data/fleet.yml budget.call_sites has no `{call_site}`")
    usd = sites[call_site]
    if not _positive_number(usd):
        raise StepSpecError(f"{where}: budget.call_sites[{call_site}] = {usd!r} is not a positive number")
    return Resolved(model=model, max_turns=turns, max_budget_usd=float(usd))


def _check_template(text: str, inputs: Mapping[str, str], where: str) -> None:
    for ch, label in FORBIDDEN_TEMPLATE_CHARS.items():
        if ch in text:
            raise StepSpecError(f"{where}: the prompt contains a {label} (LF-only UTF-8, no BOM)")
    if not text.endswith("\n") or text.endswith("\n\n"):
        raise StepSpecError(f"{where}: the prompt must end in exactly one newline")
    for n, line in enumerate(text.split("\n"), 1):
        if line != line.rstrip(" "):
            raise StepSpecError(f"{where}:{n}: trailing whitespace")
    if "${{" in text:
        raise StepSpecError(f"{where}: `${{{{` in a prompt reaches the agent verbatim — use a {{{{TOKEN}}}} input")
    tokens = TOKEN_RX.findall(text)
    if len(BRACE_RX.findall(text)) != 2 * len(tokens):
        raise StepSpecError(f"{where}: a `{{{{` or `}}}}` that is not a {{{{UPPER_SNAKE}}}} token")
    used, declared = set(tokens), set(inputs)
    if used - declared:
        raise StepSpecError(f"{where}: token(s) {sorted(used - declared)} are not declared in inputs")
    if declared - used:
        raise StepSpecError(f"{where}: input(s) {sorted(declared - used)} are declared but never used")


def _check_risk(risk: object, where: str) -> None:
    if not isinstance(risk, Mapping) or not risk:
        raise StepSpecError(f"{where}: risk must map action name → {{what, tags, tier}}")
    for action, entry in risk.items():
        at = f"{where}: risk.{action}"
        if not isinstance(action, str) or not NAME_RX.fullmatch(action):
            raise StepSpecError(f"{at}: action name must match {NAME_RX.pattern}")
        if not isinstance(entry, Mapping) or set(entry) != RISK_KEYS:
            raise StepSpecError(f"{at}: needs exactly {sorted(RISK_KEYS)}")
        if not isinstance(entry["what"], str) or not entry["what"].strip():
            raise StepSpecError(f"{at}.what: say what the action does")
        tags = entry["tags"]
        if (not isinstance(tags, list) or not tags or not all(isinstance(t, str) for t in tags)
                or len(set(tags)) != len(tags) or not set(tags) <= RISK_TAGS):
            raise StepSpecError(f"{at}.tags: a non-empty list from {sorted(RISK_TAGS)}")
        if entry["tier"] not in RISK_TIERS:
            raise StepSpecError(f"{at}.tier: one of {list(RISK_TIERS)}")
        # § 13.6: irreversible, external or money actions START high. Earned
        # autonomy (§ 13.7) lowers a tier only on a recorded approval streak,
        # which this format does not carry yet — so v1 holds them at high.
        if ({"external", "money"} & set(tags) or "reversible" not in tags) and entry["tier"] != "high":
            raise StepSpecError(f"{at}.tier: an irreversible, external or money action starts high (§ 13.6)")


def _check_evals(evals: object, where: str) -> None:
    if evals is None:
        return
    if not isinstance(evals, str) or not evals or evals.startswith("/") or ".." in Path(evals).parts:
        raise StepSpecError(f"{where}: evals is null or a hub-relative path to the eval set")
    if not (HUB / evals).exists():
        raise StepSpecError(f"{where}: evals path {evals} does not exist")


def _spells_flag(arg: str, flag: str) -> bool:
    """True when argparse would read `arg` as `flag`: the flag itself, `flag=…`,
    or any prefix of it (dash-gen's parsers take an unambiguous prefix, so
    `--appl` is `--apply`)."""
    name = arg.split("=", 1)[0]
    return arg.startswith("--") and len(name) > 2 and flag.startswith(name)


def _argv_template(raw: object, at: str, commands: Collection[str], refused_flags: tuple[str, ...]
                   ) -> tuple[str, ...]:
    if (not isinstance(raw, list) or not raw or not all(isinstance(a, str) and a for a in raw)):
        raise StepSpecError(f"{at}: a non-empty list of strings (a `tools/dash-gen` command line)")
    if not SUBCOMMAND_RX.fullmatch(raw[0]):
        raise StepSpecError(f"{at}[0]: {raw[0]!r} is not a dash-gen subcommand name")
    if raw[0] not in commands:
        raise StepSpecError(f"{at}[0]: {raw[0]!r} is not one of the dash-gen subcommands this role may run "
                            f"({sorted(commands)}, tools/jev/spec.py)")
    for arg in raw[1:]:
        if arg == "--":
            raise StepSpecError(f"{at}: carries `--` (a passthrough to another program)")
        hit = next((f for f in refused_flags if _spells_flag(arg, f)), None)
        if hit:
            raise StepSpecError(f"{at}: {arg!r} spells {hit} — the engine adds it after the gate, never a template")
    for arg in raw:
        unknown = sorted(set(ARG_TOKEN_RX.findall(arg)) - ARG_TOKENS)
        if unknown:
            raise StepSpecError(f"{at}: unknown token(s) {unknown} (one of {sorted(ARG_TOKENS)})")
        if "{" in ARG_TOKEN_RX.sub("", arg) or "}" in ARG_TOKEN_RX.sub("", arg):
            raise StepSpecError(f"{at}: {arg!r} has a brace that is not a {{token}}")
    return tuple(raw)


def _check_local(raw: object, risk: Mapping | None, fleet: Mapping, where: str) -> LocalSpec:
    """The `local:` block, validated. Unknown sub-keys are refused like unknown keys."""
    at = f"{where}: local"
    if not isinstance(raw, Mapping):
        raise StepSpecError(f"{at}: a mapping of {sorted(LOCAL_KEYS)}")
    missing, unknown = LOCAL_REQUIRED - set(raw), set(raw) - LOCAL_KEYS
    if missing or unknown:
        raise StepSpecError(f"{at}: missing {sorted(missing)} / unknown {sorted(unknown)} key(s)")
    from .adapters import REGISTRY  # lazy: importing spec.py stays side-effect free
    if raw["adapter"] not in REGISTRY:
        raise StepSpecError(f"{at}.adapter: {raw['adapter']!r} is not in tools/jev/adapters REGISTRY "
                            f"{sorted(REGISTRY)}")

    switch = None
    if "switch" in raw:
        sw = raw["switch"]
        if not isinstance(sw, Mapping) or set(sw) != SWITCH_KEYS:
            raise StepSpecError(f"{at}.switch: needs exactly {sorted(SWITCH_KEYS)}")
        if not isinstance(sw["config"], str) or not DOTTED_RX.fullmatch(sw["config"]):
            raise StepSpecError(f"{at}.switch.config: a dotted _data/fleet.yml key, not {sw['config']!r}")
        if not isinstance(fleet_value(fleet, sw["config"]), bool):
            raise StepSpecError(f"{at}.switch.config: _data/fleet.yml {sw['config']} is not a boolean")
        if not isinstance(sw["variable"], str) or not SWITCH_VAR_RX.fullmatch(sw["variable"]):
            raise StepSpecError(f"{at}.switch.variable: {sw['variable']!r} must match {SWITCH_VAR_RX.pattern}")
        if sw["default"] not in ("on", "off"):
            # a bare `off` is a YAML 1.1 boolean, so the value must be quoted
            raise StepSpecError(f"{at}.switch.default: the quoted string 'on' or 'off', not {sw['default']!r}")
        switch = Switch(config=sw["config"], variable=sw["variable"], default=sw["default"])

    pl = raw["planner"]
    if not isinstance(pl, Mapping) or "argv" not in pl or set(pl) - PLANNER_KEYS:
        raise StepSpecError(f"{at}.planner: needs argv (optional flags), nothing else")
    flags = pl.get("flags") or {}
    if not isinstance(flags, Mapping) or set(flags) - PLANNER_FLAGS:
        raise StepSpecError(f"{at}.planner.flags: keys from {sorted(PLANNER_FLAGS)}")
    bad = [f for f in flags.values() if not isinstance(f, str) or not FLAG_RX.fullmatch(f)]
    if bad:
        raise StepSpecError(f"{at}.planner.flags: {bad} are not --long-flags")
    pb = raw.get("publish")
    apply_flag = pb.get("apply_flag") if isinstance(pb, Mapping) else None
    refused = tuple(dict.fromkeys(f for f in (APPLY_FLAG, apply_flag) if isinstance(f, str) and f))
    spelled = [f for f in flags.values() if any(_spells_flag(f, r) for r in refused)]
    if spelled:
        raise StepSpecError(f"{at}.planner.flags: {spelled} spell a write flag — a planner only reads")
    planner = ArgvTemplate(argv=_argv_template(pl["argv"], f"{at}.planner.argv", PLANNER_COMMANDS, refused),
                           flags=dict(flags))

    publish = None
    if "publish" in raw:
        if not isinstance(pb, Mapping) or set(pb) != PUBLISH_KEYS:
            raise StepSpecError(f"{at}.publish: needs exactly {sorted(PUBLISH_KEYS)}")
        if not isinstance(pb["apply_flag"], str) or not FLAG_RX.fullmatch(pb["apply_flag"]):
            raise StepSpecError(f"{at}.publish.apply_flag: a --long-flag, not {pb['apply_flag']!r}")
        argv = _argv_template(pb["argv"], f"{at}.publish.argv", PUBLISH_COMMANDS, refused)
        if pb["apply_flag"] != PUBLISH_COMMANDS[argv[0]]:
            raise StepSpecError(f"{at}.publish.apply_flag: {pb['apply_flag']!r} is not {argv[0]}'s apply flag "
                                f"({PUBLISH_COMMANDS[argv[0]]}, tools/jev/spec.py PUBLISH_COMMANDS)")
        if not isinstance(risk, Mapping) or pb["risk"] not in risk:
            raise StepSpecError(f"{at}.publish.risk: {pb['risk']!r} names no action in this spec's risk block")
        publish = ArgvTemplate(argv=argv, flags={}, apply_flag=pb["apply_flag"], risk=pb["risk"])

    on_hit = raw.get("on_budget_hit", "discard")
    if on_hit not in ON_BUDGET_HIT:
        raise StepSpecError(f"{at}.on_budget_hit: one of {sorted(ON_BUDGET_HIT)}, not {on_hit!r}")
    return LocalSpec(adapter=raw["adapter"], planner=planner, switch=switch, publish=publish,
                     on_budget_hit=on_hit)


def load_spec(loop: str, step: str, *, root: Path = SPEC_ROOT, fleet: Mapping | None = None) -> StepSpec:
    """Load, validate and resolve one spec. `fleet=None` reads the hub's `_data/fleet.yml`."""
    path = spec_path(loop, step, root)
    where = str(path)
    if not path.is_file():
        raise StepSpecError(f"{where}: no such spec")
    spec_bytes = path.read_bytes()
    try:
        data = yaml.load(spec_bytes.decode("utf-8"), Loader=_UniqueKeyLoader)  # noqa: S506 - SafeLoader subclass
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        raise StepSpecError(f"{where}: {exc}") from exc
    if not isinstance(data, dict):
        raise StepSpecError(f"{where}: a spec is a mapping")
    if data.get("schema") != SCHEMA_ID:
        raise StepSpecError(f"{where}: schema must be {SCHEMA_ID!r}, not {data.get('schema')!r}")
    missing, unknown = REQUIRED_KEYS - set(data), set(data) - REQUIRED_KEYS - OPTIONAL_KEYS
    if missing or unknown:
        raise StepSpecError(f"{where}: missing {sorted(missing)} / unknown {sorted(unknown)} key(s)")
    if data["loop"] != loop or data["step"] != step:
        raise StepSpecError(f"{where}: loop/step {data['loop']!r}/{data['step']!r} disagree with the path")
    call_site = data["call_site"]
    if not isinstance(call_site, str) or not CALL_SITE_RX.fullmatch(call_site):
        raise StepSpecError(f"{where}: call_site must be `<workflow>.yml:<job>`, not {call_site!r}")
    if call_site.split(":", 1)[0].removesuffix(".yml") != loop:
        raise StepSpecError(f"{where}: call_site {call_site} is not in workflow {loop}.yml (loop = workflow stem)")
    if not isinstance(data["step_id"], str) or not data["step_id"]:
        raise StepSpecError(f"{where}: step_id names the agent step's `id:`")
    for key in ("model_from", "max_turns_from"):
        if not isinstance(data[key], str) or not DOTTED_RX.fullmatch(data[key]):
            raise StepSpecError(f"{where}: {key} is a dotted _data/fleet.yml key, not {data[key]!r}")
    if not _positive_int(data["timeout_minutes"]):
        raise StepSpecError(f"{where}: timeout_minutes must be a positive integer")

    tools = data["allowed_tools"]
    if not isinstance(tools, list) or not tools or not all(isinstance(t, str) and t for t in tools):
        raise StepSpecError(f"{where}: allowed_tools is a non-empty list of tool names")
    if len(set(tools)) != len(tools):
        raise StepSpecError(f"{where}: allowed_tools has duplicates")
    bad = [t for t in tools if "," in t or '"' in t]
    if bad:
        raise StepSpecError(f"{where}: allowed_tools entries cannot contain ',' or '\"': {bad}")

    inputs = data["inputs"]
    if (not isinstance(inputs, dict) or not inputs
            or not all(isinstance(k, str) and TOKEN_RX.fullmatch("{{%s}}" % k) for k in inputs)
            or not all(isinstance(v, str) and ROW_KEY_RX.fullmatch(v) for v in inputs.values())):
        raise StepSpecError(f"{where}: inputs maps UPPER_SNAKE token → caller row key")

    ws = data["workspace"]
    if (not isinstance(ws, dict) or not WORKSPACE_KEYS <= set(ws)
            or set(ws) - WORKSPACE_KEYS - WORKSPACE_OPTIONAL):
        raise StepSpecError(f"{where}: workspace needs exactly {sorted(WORKSPACE_KEYS)} "
                            f"(optional {sorted(WORKSPACE_OPTIONAL)})")
    outputs = ws["outputs"]
    if (not isinstance(ws["cwd"], str) or not isinstance(ws["brief_dir"], str)
            or not isinstance(outputs, list) or not all(isinstance(o, str) and o for o in outputs)):
        raise StepSpecError(f"{where}: workspace cwd/brief_dir are strings, outputs a list of paths")
    if not is_clone_relpath(ws["brief_dir"]):
        raise StepSpecError(f"{where}: workspace.brief_dir {ws['brief_dir']!r} is a relative path inside the clone "
                            "(no '..', '.' or '.git' part)")
    if ws["github_credential"] not in GITHUB_CREDENTIALS:
        raise StepSpecError(f"{where}: workspace.github_credential must be one of {sorted(GITHUB_CREDENTIALS)}")
    exceptions = ws.get("exceptions", {})
    if (not isinstance(exceptions, dict) or not set(exceptions) <= set(ACTION_GAPS)
            or not all(isinstance(v, str) and v.strip() for v in exceptions.values())):
        raise StepSpecError(f"{where}: workspace.exceptions maps a known gap {sorted(ACTION_GAPS)} → why it is open")
    workspace = Workspace(cwd=ws["cwd"], brief_dir=ws["brief_dir"], outputs=tuple(outputs),
                          github_credential=ws["github_credential"], exceptions=dict(exceptions))

    if "risk" in data:
        _check_risk(data["risk"], where)
    _check_evals(data.get("evals"), where)

    prompt = data["prompt"]
    if prompt != f"{step}.prompt.txt":
        raise StepSpecError(f"{where}: prompt must be `{step}.prompt.txt` beside the spec (never .md)")
    prompt_file = path.parent / prompt
    if prompt_file.is_symlink() or not prompt_file.is_file():
        raise StepSpecError(f"{prompt_file}: missing, or a symlink")
    real_root = Path(root).resolve()
    for p in (path, prompt_file):
        if path.parent.is_symlink() or path.is_symlink() or not p.resolve().is_relative_to(real_root):
            raise StepSpecError(f"{p}: resolves outside {root} (a symlinked loop directory or spec)")
    prompt_bytes = prompt_file.read_bytes()
    try:
        template = prompt_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise StepSpecError(f"{prompt_file}: not UTF-8 ({exc})") from exc
    _check_template(template, inputs, str(prompt_file))

    fleet = load_fleet() if fleet is None else fleet
    resolved = resolve(fleet, model_from=data["model_from"],
                       max_turns_from=data["max_turns_from"], call_site=call_site, where=where)
    local = _check_local(data["local"], data.get("risk"), fleet, where) if "local" in data else None
    return StepSpec(path=path, loop=loop, step=step, call_site=call_site, step_id=data["step_id"],
                    prompt_file=prompt_file, template=template, inputs=dict(inputs),
                    model_from=data["model_from"], max_turns_from=data["max_turns_from"],
                    timeout_minutes=data["timeout_minutes"], allowed_tools=tuple(tools),
                    workspace=workspace, risk=data.get("risk"), evals=data.get("evals"),
                    resolved=resolved,
                    content_sha256=hashlib.sha256(spec_bytes + b"\0" + prompt_bytes).hexdigest(),
                    local=local)


def spec_files(root: Path = SPEC_ROOT) -> list[Path]:
    return sorted(Path(root).glob("*/*.yml"))


def discover(root: Path = SPEC_ROOT, *, fleet: Mapping | None = None) -> list[StepSpec]:
    """Every spec under `root`, sorted. One bad spec raises."""
    fleet = load_fleet() if fleet is None else fleet
    return [load_spec(p.parent.name, p.stem, root=root, fleet=fleet) for p in spec_files(root)]


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
def render_prompt(spec: StepSpec, values: Mapping[str, str]) -> str:
    """The prompt with every token filled, in ONE pass — a value is never re-scanned."""
    keys, declared = set(values), set(spec.inputs)
    if keys != declared:
        raise StepSpecError(f"{spec.loop}/{spec.step}: missing {sorted(declared - keys)} / "
                            f"undeclared {sorted(keys - declared)} input(s)")
    for tok, val in values.items():
        if not isinstance(val, str) or not val or "\n" in val or "\r" in val:
            raise StepSpecError(f"{spec.loop}/{spec.step}: {tok} must be a non-empty single-line string")
    return TOKEN_RX.sub(lambda m: values[m.group(1)], spec.template)


def values_from(spec: StepSpec, row: Mapping[str, object]) -> dict[str, str]:
    """A caller's row (a plan.json include[] entry) → render input. The one place
    that mapping happens, for CI and for the local engine."""
    missing = [key for key in spec.inputs.values() if key not in row]
    if missing:
        raise StepSpecError(f"{spec.loop}/{spec.step}: the row has no {missing}")
    values: dict[str, str] = {}
    for tok, key in spec.inputs.items():
        val = row[key]
        if not isinstance(val, str):
            raise StepSpecError(f"{spec.loop}/{spec.step}: row[{key!r}] is {type(val).__name__}, not a string")
        values[tok] = val
    return values


def matrix_expressions(spec: StepSpec) -> dict[str, str]:
    """Each token as the Actions expression the matrix row fills it with.
    Rendering with these reproduces the inline prompt the spec replaced."""
    return {tok: "${{ matrix.%s }}" % key for tok, key in spec.inputs.items()}


def render_argv(template: tuple[str, ...] | list[str], values: Mapping[str, str]) -> list[str]:
    """An argv template with every `{token}` filled, in ONE pass.

    Refused: a token without a value, a value that starts with `-` (it would
    read as an option), a value carrying NUL, CR or LF, and an `nwo` that is not
    an `owner/repo` slug. The template itself was validated by the loader."""
    for tok, val in values.items():
        if tok not in ARG_TOKENS:
            raise StepSpecError(f"argv value for unknown token {tok!r}")
        if not isinstance(val, str) or not val or val.startswith("-") or any(c in val for c in "\0\r\n"):
            raise StepSpecError(f"argv token {tok}: {val!r} is empty, starts with '-' or holds a control character")
    if "nwo" in values and not is_nwo(values["nwo"]):
        raise StepSpecError(f"argv token nwo: {values['nwo']!r} is not owner/repo")

    def fill(m: re.Match) -> str:
        if m.group(1) not in values:
            raise StepSpecError(f"argv token {{{m.group(1)}}} has no value")
        return values[m.group(1)]

    return [ARG_TOKEN_RX.sub(fill, arg) for arg in template]


# --------------------------------------------------------------------------- #
# parity — the spec against its workflow and _data/fleet.yml
# --------------------------------------------------------------------------- #
def switch_errors(spec: StepSpec, workflow: Mapping) -> list[str]:
    """`local.switch` against the workflow's gating `if:` — [] when they agree.

    Default off needs some job gated on `vars.<VARIABLE> == 'true'` (a new loop
    is armed by setting it); default on needs `vars.<VARIABLE> != 'false'` (a
    switch added to a loop already in service). The other form anywhere is an
    error too, so a local scheduled run reads the variable exactly as CI does."""
    sw = spec.local.switch if spec.local else None
    if sw is None:
        return []
    me = f"{spec.loop}/{spec.step}"
    gates = " ".join(str(j.get("if") or "") for j in (workflow.get("jobs") or {}).values() if isinstance(j, Mapping))
    var = re.escape(sw.variable)
    on_rx = re.compile(rf"vars\.{var}\s*!=\s*'false'")
    off_rx = re.compile(rf"vars\.{var}\s*==\s*'true'")
    want, other = (off_rx, on_rx) if sw.default == "off" else (on_rx, off_rx)
    form = {"off": f"vars.{sw.variable} == 'true'", "on": f"vars.{sw.variable} != 'false'"}
    errs = []
    if not want.search(gates):
        errs.append(f"{me}: local.switch default {sw.default!r} ({spec.path.name}) needs a job in "
                    f"{spec.workflow_file} gated on `{form[sw.default]}`")
    if other.search(gates):
        errs.append(f"{me}: {spec.workflow_file} gates on `{form['on' if sw.default == 'off' else 'off']}`, the "
                    f"opposite of local.switch default {sw.default!r} ({spec.path.name})")
    return errs


def grant_errors(spec: StepSpec) -> list[str]:
    """The #89 lint: every tool the prompt orders by name is in allowed_tools."""
    ordered = sorted(set(TOOL_ORDER_RX.findall(spec.template)))
    return [f"{spec.loop}/{spec.step}: the prompt orders the {t} tool ({spec.prompt_file.name}) but "
            f"allowed_tools does not grant it ({spec.path.name}) — bamr87/bamr87#89"
            for t in ordered if t not in spec.allowed_tools]


def _effective_env(workflow: Mapping, job: Mapping, step: Mapping) -> dict:
    """The env the step runs with: workflow, then job, then step (Actions order)."""
    return {**(workflow.get("env") or {}), **(job.get("env") or {}), **(step.get("env") or {})}


def agent_credentials(workflow: Mapping, job: Mapping, step: Mapping) -> list[str]:
    """Where a GitHub credential reaches the agent step: its effective env (keys
    and values), its own inputs, or an earlier step's export. [] when none."""
    found: list[str] = []
    for key, val in _effective_env(workflow, job, step).items():
        if key in ("GH_TOKEN", "GITHUB_TOKEN") or GITHUB_CRED_RX.search(str(val)) or "FLEET_TOKEN" in str(val):
            found.append(f"env {key}")
    with_ = step.get("with") or {}
    if with_.get("github_token"):
        found.append("with.github_token")
    scanned = {k: v for k, v in with_.items() if k not in CREDENTIAL_SCAN_SKIP and k != "github_token"}
    dumped = yaml.safe_dump(scanned)
    if "FLEET_TOKEN" in dumped or GITHUB_CRED_RX.search(dumped):
        found.append("with: (a secret or github.token)")
    steps = list(job.get("steps") or [])
    for earlier in steps[:next((i for i, s in enumerate(steps) if s is step), len(steps))]:
        if not isinstance(earlier, Mapping):
            continue
        label = earlier.get("id") or earlier.get("name") or earlier.get("uses")
        if str(earlier.get("uses", "")).endswith("/resolve-fleet-token"):
            found.append(f"earlier step `{label}` (resolve-fleet-token)")
        elif GITHUB_ENV_EXPORT_RX.search(str(earlier.get("run", ""))):
            found.append(f"earlier step `{label}` (exports a token to $GITHUB_ENV)")
    return found


def action_gaps(workflow: Mapping, job: Mapping, step: Mapping) -> list[str]:
    """The ACTION_GAPS the workflow leaves open on the agent step, in key order."""
    with_ = step.get("with") or {}
    scrub = str(_effective_env(workflow, job, step).get("CLAUDE_CODE_SUBPROCESS_ENV_SCRUB", "")).strip()
    open_ = {
        "app-token": not with_.get("github_token") and scrub.lower() not in ("1", "true"),
        "setting-sources": "--setting-sources" not in str(with_.get("claude_args") or ""),
    }
    return [gap for gap in ACTION_GAPS if open_[gap]]


def parity_errors(spec: StepSpec, workflow: Mapping, fleet: Mapping) -> list[str]:
    """[] when the workflow's literals agree with the resolved spec. Pure."""
    me = f"{spec.loop}/{spec.step}"
    wf = spec.workflow_file
    errs = grant_errors(spec) + switch_errors(spec, workflow)
    try:
        res = resolve(fleet, model_from=spec.model_from, max_turns_from=spec.max_turns_from,
                      call_site=spec.call_site, where=me)
    except StepSpecError as exc:
        return [*errs, str(exc)]
    job = ((workflow.get("jobs") or {}).get(spec.job))
    if not isinstance(job, Mapping):
        return [*errs, f"{me}: {wf} has no job `{spec.job}`"]
    steps = [s for s in (job.get("steps") or []) if isinstance(s, Mapping)]
    agent = [s for s in steps if s.get("id") == spec.step_id and CLAUDE_ACTION in str(s.get("uses", ""))]
    if len(agent) != 1:
        return [*errs, f"{me}: {wf} job `{spec.job}` needs exactly one {CLAUDE_ACTION} step with "
                       f"id `{spec.step_id}`, found {len(agent)}"]
    step = agent[0]
    with_ = step.get("with") or {}
    args = str(with_.get("claude_args") or "")

    def differ(field: str, a: object, a_at: str, b: object, b_at: str) -> None:
        if a != b:
            errs.append(f"{me}: {field} {a!r} ({a_at}) != {b!r} ({b_at})")

    turns = MAX_TURNS_RX.findall(args)
    differ("--max-turns", [int(t) for t in turns], f"{wf} claude_args",
           [res.max_turns], f"_data/fleet.yml {spec.max_turns_from}")
    usd = MAX_BUDGET_RX.findall(args)
    differ("--max-budget-usd", [float(u) for u in usd], f"{wf} claude_args",
           [res.max_budget_usd], f"_data/fleet.yml budget.call_sites[{spec.call_site}]")
    cost = next((s for s in steps if str(s.get("uses", "")).endswith(COST_ACTION)), None)
    if cost is None:
        errs.append(f"{me}: {wf} job `{spec.job}` has no claude-cost step")
    else:
        raw = (cost.get("with") or {}).get("budget-usd")
        try:
            cost_usd: object = float(raw) if isinstance(raw, (int, float, str)) else raw
        except ValueError:
            cost_usd = raw
        differ("claude-cost budget-usd", cost_usd, f"{wf} job `{spec.job}`",
               res.max_budget_usd, f"_data/fleet.yml budget.call_sites[{spec.call_site}]")
    tools = ALLOWED_TOOLS_RX.findall(args)
    differ("--allowedTools", tools, f"{wf} claude_args", [spec.allowed_tools_arg()], f"{spec.path.name} allowed_tools")
    literal = MODEL_LITERAL_RX.findall(args)
    exprs = MODEL_EXPR_RX.findall(args)
    if len(literal) + len(exprs) != 1:
        errs.append(f"{me}: {wf} claude_args needs exactly one --model, found {len(literal) + len(exprs)}")
    elif literal:
        differ("--model", literal[0], f"{wf} claude_args", res.model, f"_data/fleet.yml {spec.model_from}")
    elif not MODEL_PLAN_RX.search(args):
        errs.append(f"{me}: {wf} --model expression must be exactly `${{{{ needs.<job>.outputs.model }}}}` "
                    f"(filled from _data/fleet.yml {spec.model_from}) — no vars., inputs. or fallback")
    differ("timeout-minutes", job.get("timeout-minutes"), f"{wf} job `{spec.job}`",
           spec.timeout_minutes, f"{spec.path.name}")

    def artifact_paths(action: str) -> list[str]:
        return [str((s.get("with") or {}).get("path", "")).rstrip("/") for s in steps
                if str(s.get("uses", "")).startswith(action)]

    downloads = artifact_paths("actions/download-artifact")
    if spec.workspace.brief_dir.rstrip("/") not in downloads:
        errs.append(f"{me}: workspace.brief_dir {spec.workspace.brief_dir!r} ({spec.path.name}) is not a "
                    f"download-artifact path in {wf} job `{spec.job}` {downloads}")
    uploads = artifact_paths("actions/upload-artifact")
    for out in spec.workspace.outputs:
        if out not in uploads:
            errs.append(f"{me}: workspace.outputs {out!r} ({spec.path.name}) is not an upload-artifact "
                        f"path in {wf} job `{spec.job}` {uploads}")
    if spec.workspace.github_credential == "none":
        held = agent_credentials(workflow, job, step)
        if held:
            errs.append(f"{me}: workspace.github_credential is none ({spec.path.name}) but the agent step in "
                        f"{wf} inherits or carries a GitHub credential: {held}")
        gaps = action_gaps(workflow, job, step)
        for gap in gaps:
            if gap not in spec.workspace.exceptions:
                errs.append(f"{me}: workspace.github_credential is none ({spec.path.name}) but {ACTION_GAPS[gap]} "
                            f"({wf} step `{spec.step_id}`) — close it in the workflow, or declare "
                            f"workspace.exceptions.{gap} with the reason")
        for gap in spec.workspace.exceptions:
            if gap not in gaps:
                errs.append(f"{me}: workspace.exceptions.{gap} ({spec.path.name}) is stale — {wf} step "
                            f"`{spec.step_id}` closes it; remove the exception")
    pinned = (step.get("env") or {}).get(STEP_SHA_ENV)
    if pinned != spec.content_sha256:
        errs.append(f"{me}: {wf} step `{spec.step_id}` env {STEP_SHA_ENV} {pinned!r} != {spec.content_sha256} "
                    f"(sha256 of {spec.path.name}, NUL, {spec.prompt_file.name}) — a change to the spec pair "
                    f"also changes the workflow file (ADR 0002, governance trade-off)")
    prompt = with_.get("prompt")
    if prompt != "${{ matrix.prompt }}" and prompt != render_prompt(spec, matrix_expressions(spec)):
        errs.append(f"{me}: {wf} step `{spec.step_id}` prompt is neither `${{{{ matrix.prompt }}}}` nor "
                    f"byte-equal to {spec.prompt_file.name} rendered with matrix expressions")
    return errs


def check_all(root: Path = SPEC_ROOT, *, workflows: Path = WORKFLOWS_DIR,
              fleet: Mapping | None = None) -> tuple[list[StepSpec], list[str]]:
    """Every discovered spec, loaded and held against its workflow. (specs, errors)."""
    fleet = load_fleet() if fleet is None else fleet
    specs: list[StepSpec] = []
    errors: list[str] = []
    for p in spec_files(root):
        try:
            spec = load_spec(p.parent.name, p.stem, root=root, fleet=fleet)
        except StepSpecError as exc:
            errors.append(str(exc))
            continue
        specs.append(spec)
        wf_path = Path(workflows) / spec.workflow_file
        if not wf_path.is_file():
            errors.append(f"{spec.loop}/{spec.step}: no workflow {wf_path}")
            continue
        errors.extend(parity_errors(spec, yaml.safe_load(wf_path.read_text(encoding="utf-8")) or {}, fleet))
    return specs, errors


# --------------------------------------------------------------------------- #
# CLI — `python3 -m tools.jev steps check|render`
# --------------------------------------------------------------------------- #
def add_arguments(ap: argparse.ArgumentParser) -> None:
    sub = ap.add_subparsers(dest="action", required=True)
    sub.add_parser("check", help="every spec loads, resolves, and agrees with its workflow")
    r = sub.add_parser("render", help="print one step's prompt, byte-exact")
    r.add_argument("loop")
    r.add_argument("step")
    r.add_argument("--set", action="append", default=[], metavar="TOKEN=value", dest="values",
                   help="fill one input (repeat for each)")


def main(args: argparse.Namespace) -> int:
    if args.action == "check":
        specs, errors = check_all()
        for e in errors:
            print(f"ERROR: {e}")
        if errors:
            print(f"{len(errors)} problem(s) — fix the spec, the workflow or _data/fleet.yml until they agree")
            return 1
        for s in specs:
            print(f"ok   {s.loop}/{s.step}  {s.call_site}  model {s.resolved.model}  "
                  f"turns {s.resolved.max_turns}  ${s.resolved.max_budget_usd:g}  "
                  f"{len(s.allowed_tools)} tools  prompt sha256 {s.template_sha256[:12]}")
            for gap, why in s.workspace.exceptions.items():
                print(f"     known exception {gap}: {why}")
        print(f"ok: {len(specs)} step spec(s) agree with their workflows and _data/fleet.yml")
        return 0
    values: dict[str, str] = {}
    for item in args.values:
        tok, sep, val = item.partition("=")
        if not sep or tok in values:
            raise StepSpecError(f"--set {item!r}: expected TOKEN=value, once per token")
        values[tok] = val
    text = render_prompt(load_spec(args.loop, args.step), values)
    sys.stdout.flush()
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.flush()
    return 0
