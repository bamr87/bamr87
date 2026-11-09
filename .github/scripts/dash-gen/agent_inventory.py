#!/usr/bin/env python3
"""
agent_inventory — the ONE inventory of the fleet's AI agents, graded against
the agentic efficacy contract (amendment `agentic-efficacy-contract`,
constitution § 29; the efficacy model is ADR 0009).

An "agent" is anything that spends a model call, or runs a scheduled job an
agent depends on, without a person at the keyboard:

  ci-agent-step        an AI workflow (a claude-code-action or claude-run call
                       site): the hub's own, read from the checkout, and the
                       fleet's, read from the committed _data/harness_registry.yml
                       (the daily live scan; no PR reads the fleet)
  local-loop-step      a JEV loop step spec (tools/jev/steps/<loop>/<step>.yml),
                       run on a workstation by `tools/dash loop run`
  jev-tier             a rung of JEV's conflict ladder (_data/fleet.yml `jev:`)
  scheduled-local-job  a LaunchAgent a `tools/install-*.sh` installer puts on
                       the Mac, or one `harness.agents` declares before its
                       installer lands

Every entry carries what the contract's rule 1 asks for (owner, trigger, kill
switch, budget cap, model), the KPIs its kind declares (rule 3), the data
sources it reads with each source's writer (rule 4), where its run records
land (rule 2), whether those reach the reflector (rule 5) and its local entry
point (rule 6), plus the gaps against each rule. The KPI thresholds, the
source catalogue and the per-agent facts the code cannot show live in
_data/fleet.yml `harness.efficacy`, `harness.sources` and `harness.agents`,
and are validated here.

  tools/dash agents             write _data/agents.yml (offline, deterministic)
  tools/dash agents --check     drift check (p): fail when the committed file is
                                stale or an agent is not registered
  tools/dash agents --verbose   also list every contract gap

Contract gaps are WARNINGS while `harness.efficacy.enforce` is false (the
shadow period); a gated PR turns enforcement on after `shadow_until`, and even
then an agent first seen before `shadow_until` keeps its grace until
`grace_until`. Drift in the FLEET half (entries read from harness_registry.yml)
warns on a pull request, because no hub PR causes it; `--strict-fleet` (the
daily `--ci` run) fails on it. fleet-pulse.yml regenerates this file in the
same commit as harness_registry.yml.

Doc: docs/AGENT-EFFICACY.md. Tests: test_agent_inventory.py.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("agent_inventory requires PyYAML: pip install pyyaml\n")
    sys.exit(2)

import harness_registry as hr  # classify_workflow + describe_cron: one meaning of "AI workflow"

REPO_ROOT = Path(__file__).resolve().parents[3]
FLEET_DEFAULT = REPO_ROOT / "_data" / "fleet.yml"
REGISTRY_DEFAULT = REPO_ROOT / "_data" / "harness_registry.yml"
OUT_DEFAULT = REPO_ROOT / "_data" / "agents.yml"
SCHEMA_MARKER = "agents/v1"  # additive changes keep v1; a rename or removal bumps it

#: kind -> the contract's category (amendment `agentic-efficacy-contract`)
KINDS = {
    "ci-scheduled": "ci-agent-step",
    "ci-event": "ci-agent-step",
    "ci-mention": "ci-agent-step",
    "loop-step": "local-loop-step",
    "jev-tier": "jev-tier",
    "local-job": "scheduled-local-job",
}
CATEGORY_ORDER = ["ci-agent-step", "local-loop-step", "jev-tier", "scheduled-local-job"]
RULES = {
    "R1": "registered with owner, trigger, kill switch, budget cap and model",
    "R2": "one run record per model call, in the contract's schema",
    "R3": "efficacy KPIs and thresholds declared",
    "R4": "every data source read has a writer and a freshness SLO",
    "R5": "its run records reach the reflector",
    "R6": "a local entry point",
}
SLO_WORDS = ("on-change", "live")
BETTER = ("higher", "lower")
#: the context pack's providers (tools/jev/context.py) -> the source each reads
CONTEXT_SOURCES = {
    "history": "loop-runs",
    "library": "harness-library",
    "lake_issues": "lake",
    "lake_ci": "lake",
    "lake_agents": "lake",
    "index_code": "code-index",
    "telemetry_errors": "telemetry",
}
OVERLAY_KEYS = {"owner", "reads", "model", "model_from", "budget", "budget_from", "switch", "run_record",
                "reflector_via", "local_entry", "note", "declare"}
BUDGET_KEYS = ("per_run_usd", "monthly_usd")
DECLARE_KEYS = {"kind", "where", "trigger", "runs", "pending"}
CLAUDE_RUN_RX = re.compile(r"^\s*(?:-\s*)?uses:\s*\S*\.github/actions/claude-run\b", re.M)
LABEL_RX = re.compile(r'^LABEL="com\.bamr87\.([a-z0-9-]+)"', re.M)
HOURS_RX = re.compile(r"^HOURS=(\d+)", re.M)
HOUR_RX = re.compile(r"^HOUR=(\d+)", re.M)
AT_RX = re.compile(r'^AT="(\d{2}):(\d{2})"', re.M)
MINUTE_LITERAL_RX = re.compile(r"<key>Minute</key>\s*<integer>(\d+)</integer>")
RUN_LINE_RX = re.compile(r"^\s*(?:step\s+)?(tools/(?:dash|dash-gen|update-submodules\.sh)\b[^\n\"']*)", re.M)


class ContractError(Exception):
    """The contract in _data/fleet.yml does not validate."""


# --------------------------------------------------------------------------- #
# loading
# --------------------------------------------------------------------------- #
def load_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def dig(data: dict, dotted: str):
    cur = data
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _date(value, where: str, errors: list[str]) -> dt.date | None:
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError:
        errors.append(f"{where}: {value!r} is not a YYYY-MM-DD date")
        return None


def load_contract(fleet: dict) -> tuple[dict, list[str], list[str]]:
    """Validate `harness.efficacy`, `harness.sources` and `harness.agents`.

    Returns (contract, errors, warnings). An error is a malformed contract the
    PR's own author can fix (a typo, an unknown id); a warning is a gap the
    contract itself names — a source with no writer, a kind with no KPIs."""
    errors: list[str] = []
    warnings: list[str] = []
    harness = fleet.get("harness") if isinstance(fleet.get("harness"), dict) else {}
    eff = harness.get("efficacy")
    if not isinstance(eff, dict):
        raise ContractError("_data/fleet.yml harness.efficacy is missing: the contract has no numbers to hold agents to")
    where = "harness.efficacy"

    enforce = eff.get("enforce", False)
    if not isinstance(enforce, bool):
        errors.append(f"{where}.enforce must be true or false")
        enforce = False
    shadow = _date(eff.get("shadow_until"), f"{where}.shadow_until", errors)
    grace = _date(eff.get("grace_until"), f"{where}.grace_until", errors)
    if shadow and grace and grace < shadow:
        errors.append(f"{where}.grace_until {grace} is before shadow_until {shadow}")
    owner = eff.get("owner")
    if not isinstance(owner, str) or not owner:
        errors.append(f"{where}.owner names the accountable person (a GitHub login)")
        owner = None

    kpis = eff.get("kpis")
    if not isinstance(kpis, dict) or not kpis:
        errors.append(f"{where}.kpis is the KPI catalogue: id -> {{unit, better}}")
        kpis = {}
    for kid, spec in kpis.items():
        if not isinstance(spec, dict) or not spec.get("unit") or spec.get("better") not in BETTER:
            errors.append(f"{where}.kpis.{kid}: needs `unit` and `better: higher|lower`")

    rr = eff.get("run_record") if isinstance(eff.get("run_record"), dict) else {}
    fields = rr.get("fields") if isinstance(rr.get("fields"), list) else []
    if not fields:
        errors.append(f"{where}.run_record.fields lists the run record's required fields")
    stores = rr.get("stores") if isinstance(rr.get("stores"), dict) else {}
    for sid, spec in stores.items():
        missing = (spec or {}).get("missing") or []
        if not isinstance(spec, dict) or not spec.get("where") or not isinstance(missing, list):
            errors.append(f"{where}.run_record.stores.{sid}: needs `where` and a `missing` list")
            continue
        for f in missing:
            if f not in fields:
                errors.append(f"{where}.run_record.stores.{sid}.missing: {f!r} is not a run_record field")

    sources = harness.get("sources")
    if not isinstance(sources, dict) or not sources:
        errors.append("harness.sources is the data-source catalogue: id -> {path, writer, slo_days|slo}")
        sources = {}
    for sid, spec in sources.items():
        at = f"harness.sources.{sid}"
        if not isinstance(spec, dict) or not spec.get("path"):
            errors.append(f"{at}: needs a `path`")
            continue
        if "writer" not in spec:
            errors.append(f"{at}: declare `writer` (null when there is none — that is the defect rule 4 names)")
        elif spec["writer"] is not None and not isinstance(spec["writer"], str):
            errors.append(f"{at}.writer is a string or null")
        elif spec["writer"] is None:
            warnings.append(f"source {sid} ({spec['path']}) has no writer — a defect under rule 4")
        slo_days, slo = spec.get("slo_days"), spec.get("slo")
        if slo_days is None and slo is None:
            warnings.append(f"source {sid} declares no freshness SLO (slo_days, or slo: on-change|live)")
        elif slo_days is not None and (isinstance(slo_days, bool) or not isinstance(slo_days, int) or slo_days < 1):
            errors.append(f"{at}.slo_days is a whole number of days, 1 or more")
        elif slo is not None and slo not in SLO_WORDS:
            errors.append(f"{at}.slo is one of {', '.join(SLO_WORDS)}")

    reflector_inputs = eff.get("reflector_inputs") if isinstance(eff.get("reflector_inputs"), list) else []
    for rid in reflector_inputs:
        if rid not in sources:
            errors.append(f"{where}.reflector_inputs: {rid!r} is not a harness.sources id")

    kinds_raw = eff.get("kinds") if isinstance(eff.get("kinds"), dict) else {}
    kinds: dict[str, dict] = {}
    for kind in kinds_raw:
        if kind not in KINDS:
            errors.append(f"{where}.kinds.{kind}: unknown kind (one of {', '.join(KINDS)})")
    for kind in KINDS:
        spec = kinds_raw.get(kind)
        if not isinstance(spec, dict):
            warnings.append(f"{where}.kinds.{kind} is not declared — agents of that kind have no KPIs (rule 3)")
            kinds[kind] = {"kpis": {}, "reads": [], "run_record": None, "reflector_via": None}
            continue
        at = f"{where}.kinds.{kind}"
        kk = spec.get("kpis") if isinstance(spec.get("kpis"), dict) else {}
        for kid, thr in kk.items():
            if kid not in kpis:
                errors.append(f"{at}.kpis.{kid}: not in the KPI catalogue")
            elif thr is not None and (isinstance(thr, bool) or not isinstance(thr, (int, float))):
                errors.append(f"{at}.kpis.{kid}: a threshold is a number, or null (measured, not judged)")
        if not kk:
            warnings.append(f"{at} declares no KPIs (rule 3)")
        reads = spec.get("reads") if isinstance(spec.get("reads"), list) else []
        for sid in reads:
            if sid not in sources:
                errors.append(f"{at}.reads: {sid!r} is not a harness.sources id")
        store = spec.get("run_record")
        if store is not None and store not in stores:
            errors.append(f"{at}.run_record: {store!r} is not a run_record.stores id")
        via = spec.get("reflector_via")
        if via is not None and via not in reflector_inputs:
            errors.append(f"{at}.reflector_via: {via!r} is not one of reflector_inputs")
        for key in ("local_entry", "switch"):
            ex = spec.get(key)
            if ex is not None and not (isinstance(ex, dict) and set(ex) == {"exempt"}
                                       and isinstance(ex["exempt"], str)):
                errors.append(f"{at}.{key}: only `{{exempt: <reason>}}` is declared per kind")
        kinds[kind] = {"kpis": dict(kk), "reads": list(reads), "run_record": store, "reflector_via": via,
                       "local_entry": spec.get("local_entry"), "switch": spec.get("switch")}

    overlays_raw = harness.get("agents") if isinstance(harness.get("agents"), dict) else {}
    overlays: dict[str, dict] = {}
    for aid, spec in overlays_raw.items():
        at = f"harness.agents.{aid}"
        if not isinstance(spec, dict):
            errors.append(f"{at}: a mapping")
            continue
        unknown = set(spec) - OVERLAY_KEYS
        if unknown:
            errors.append(f"{at}: unknown key(s) {sorted(unknown)}")
        for sid in spec.get("reads") or []:
            if sid not in sources:
                errors.append(f"{at}.reads: {sid!r} is not a harness.sources id")
        store = spec.get("run_record")
        if store not in (None, "none") and store not in stores:
            errors.append(f"{at}.run_record: {store!r} is not a run_record.stores id (or none)")
        via = spec.get("reflector_via")
        if via is not None and via not in reflector_inputs:
            errors.append(f"{at}.reflector_via: {via!r} is not one of reflector_inputs")
        decl = spec.get("declare")
        if decl is not None:
            if not isinstance(decl, dict) or set(decl) - DECLARE_KEYS or decl.get("kind") not in KINDS:
                errors.append(f"{at}.declare: keys {sorted(DECLARE_KEYS)}, kind one of the known kinds")
        spec = dict(spec)
        # References, not copies (AGENTS.md: central configuration): a model or
        # a cap the overlay names is READ from fleet.yml, so a change there
        # reaches the inventory without a second edit.
        if "model_from" in spec:
            keys = spec.pop("model_from")
            keys = [keys] if isinstance(keys, str) else keys
            models = [dig(fleet, k) for k in keys or []]
            if not keys or not all(isinstance(m, str) and m for m in models):
                errors.append(f"{at}.model_from: every key must resolve to a model id in _data/fleet.yml")
            else:
                spec["model"] = models[0] if len(models) == 1 else models
        if "budget_from" in spec:
            refs = spec.pop("budget_from")
            budget = {}
            if not isinstance(refs, dict) or not refs or set(refs) - set(BUDGET_KEYS):
                errors.append(f"{at}.budget_from: a mapping of {', '.join(BUDGET_KEYS)} to dotted fleet.yml keys")
            else:
                for key in BUDGET_KEYS:
                    if key in refs:
                        val = dig(fleet, str(refs[key]))
                        if isinstance(val, bool) or not isinstance(val, (int, float)):
                            errors.append(f"{at}.budget_from.{key}: {refs[key]!r} is not a number in _data/fleet.yml")
                        else:
                            budget[key] = float(val)
                spec["budget"] = budget or None
        overlays[aid] = spec

    contract = {
        "enforce": enforce, "shadow_until": shadow, "grace_until": grace, "owner": owner,
        "kpis": kpis, "fields": fields, "stores": stores, "sources": sources,
        "reflector_inputs": reflector_inputs, "kinds": kinds, "overlays": overlays,
    }
    return contract, errors, warnings


# --------------------------------------------------------------------------- #
# discovery (pure over inputs; the CLI wires the hub's files in)
# --------------------------------------------------------------------------- #
def _stem(path: str) -> str:
    return Path(path).name.rsplit(".", 1)[0]


def _ci_kind(info: dict) -> str:
    if info.get("crons"):
        return "ci-scheduled"
    if info.get("mention_handler") or info.get("kind") == "mention-handler":
        return "ci-mention"
    return "ci-event"


def _trigger(triggers: list[str], crons: list[str]) -> str:
    parts = [f"schedule {hr.describe_cron(c)}" for c in crons]
    parts += [t for t in triggers if t != "schedule"]
    return "; ".join(parts) if parts else None


def hub_workflows(workflows_dir: Path, hub_nwo: str) -> list[dict]:
    """Every AI workflow in the hub checkout: a claude-code-action step (the
    harness registry's own test) or a claude-run step. Read from the tree, so a
    pull request that adds one is caught before it merges."""
    out = []
    if not workflows_dir.is_dir():
        return out
    for path in sorted(list(workflows_dir.glob("*.yml")) + list(workflows_dir.glob("*.yaml"))):
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = f".github/workflows/{path.name}"
        info = hr.classify_workflow(rel, text)
        claude_run = bool(CLAUDE_RUN_RX.search(text))
        if not (info["ai"] or claude_run):
            continue
        if not info["ai"]:  # claude-run only: the same facts, read the same way
            m = hr.MODEL_RX.search(text)
            info["model"] = m.group(1) if m and "${{" not in m.group(1) else None
            m = hr.MAX_BUDGET_RX.search(text)
            info["max_budget_usd"] = float(m.group(1)) if m else None
        out.append({
            "repo": hub_nwo, "name": hub_nwo.split("/", 1)[-1], "path": rel,
            "triggers": info["triggers"], "crons": info["crons"], "kind": _ci_kind(info),
            "model": info.get("model"), "max_budget_usd": info.get("max_budget_usd"),
            "switch": info.get("switch"), "archived": False,
        })
    return out


def fleet_workflows(registry: dict, hub_nwo: str) -> list[dict]:
    """The fleet's AI workflows from the committed live scan. The hub's own row
    is skipped: the checkout is fresher for it, and authoritative on a PR."""
    out = []
    for repo in registry.get("repos") or []:
        if not isinstance(repo, dict) or repo.get("nwo") == hub_nwo:
            continue
        for h in repo.get("harnesses") or []:
            if not isinstance(h, dict) or not h.get("path"):
                continue
            out.append({
                "repo": repo.get("nwo") or repo.get("repo"), "name": repo.get("repo"), "path": h["path"],
                "triggers": list(h.get("triggers") or []), "crons": list(h.get("crons") or []),
                "kind": _ci_kind(h), "model": h.get("model"), "max_budget_usd": h.get("max_budget_usd"),
                "switch": h.get("switch"), "archived": bool(repo.get("archived")),
            })
    return out


def load_steps(fleet: dict, root: Path | None = None) -> list[dict]:
    """The loop step specs, read through tools/jev/spec.py (the only reader the
    spec README allows). Imported lazily with the hub root appended to sys.path,
    as repo_scout.py does."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.append(str(REPO_ROOT))
    S = importlib.import_module("tools.jev.spec")
    specs = S.discover(root or S.SPEC_ROOT, fleet=fleet)
    out = []
    for s in specs:
        local = s.local
        out.append({
            "loop": s.loop, "step": s.step, "call_site": s.call_site, "workflow": s.workflow_file,
            "model": s.resolved.model, "max_budget_usd": s.resolved.max_budget_usd,
            "local": local is not None,
            "switch": ({"config": local.switch.config, "variable": local.switch.variable,
                        "default": local.switch.default} if local and local.switch else None),
            "providers": list(local.context.providers) if local and local.context
            and local.context.mode != "off" else [],
        })
    return out


def parse_installer(path: Path) -> dict | None:
    """One `tools/install-*.sh` that installs a LaunchAgent -> its facts, or
    None when it installs something else (a git hook)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    m = LABEL_RX.search(text)
    if not m or "<key>Label</key>" not in text:
        return None
    sched = None
    if "<key>StartInterval</key>" in text:
        h = HOURS_RX.search(text)
        sched = f"every {h.group(1)}h" if h else "on an interval"
    elif "<key>StartCalendarInterval</key>" in text:
        at, hour, minute = AT_RX.search(text), HOUR_RX.search(text), MINUTE_LITERAL_RX.search(text)
        if at:
            sched = f"daily {at.group(1)}:{at.group(2)} local"
        elif hour:
            sched = f"daily {int(hour.group(1)):02d}:{int(minute.group(1)) if minute else 0:02d} local"
        else:
            sched = "on a calendar"
    if sched and "<key>RunAtLoad</key>" in text:
        sched += " and at login"
    runs = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        r = RUN_LINE_RX.match(line)
        if r and r.group(1).strip() not in runs:
            runs.append(r.group(1).strip())
    rel = f"tools/{path.name}"
    return {
        "name": m.group(1), "installer": rel, "schedule": sched, "runs": runs,
        "uninstall": f"{rel} --uninstall" if "--uninstall" in text else None,
    }


def discover_installers(tools_dir: Path) -> list[dict]:
    out = []
    for path in sorted(tools_dir.glob("install-*.sh")):
        facts = parse_installer(path)
        if facts:
            out.append(facts)
    return out


# --------------------------------------------------------------------------- #
# assembly
# --------------------------------------------------------------------------- #
def _switch_loops(fleet: dict) -> dict[tuple[str, str], tuple[str, dict]]:
    loops = dig(fleet, "switches.loops") or {}
    out = {}
    for lid, spec in loops.items():
        if isinstance(spec, dict) and spec.get("repo") and spec.get("workflow"):
            out[(spec["repo"], spec["workflow"])] = (lid, spec)
    return out


def _budget_from_call_sites(fleet: dict, workflow_file: str) -> dict | None:
    sites = dig(fleet, "budget.call_sites") or {}
    mine = {k: float(v) for k, v in sites.items()
            if isinstance(k, str) and k.split(":", 1)[0] == workflow_file and isinstance(v, (int, float))}
    if not mine:
        return None
    return {"per_run_usd": max(mine.values()), "call_sites": dict(sorted(mine.items()))}


def build_entries(fleet: dict, contract: dict, hub_nwo: str, hub_wfs: list[dict], fleet_wfs: list[dict],
                  steps: list[dict], installers: list[dict]) -> tuple[list[dict], list[str]]:
    """Every discovered agent, before overlays and grading. Returns (entries, notes)."""
    notes: list[str] = []
    entries: list[dict] = []
    switch_map = _switch_loops(fleet)
    step_by_workflow: dict[str, list[dict]] = {}
    for s in steps:
        step_by_workflow.setdefault(s["workflow"], []).append(s)

    for w in hub_wfs + fleet_wfs:
        hub = w["repo"] == hub_nwo
        aid = f"ci:{w['name']}:{_stem(w['path'])}"
        wf_file = Path(w["path"]).name
        loop = switch_map.get((w["repo"], w["path"]))
        # A `switches:` entry whose gate is `kind: none` records the § 17 gap,
        # not a switch, so it never satisfies rule 1 on its own.
        switch = {}
        if w.get("switch"):
            switch["variable"] = w["switch"]
        gate = (loop[1].get("gate") or {}) if loop else {}
        if loop and gate.get("kind") not in (None, "none"):
            switch["loop"] = loop[0]
            if gate.get("kind") == "fleet_config" and gate.get("name"):
                switch["config"] = gate["name"]
        switch = switch or None
        budget = _budget_from_call_sites(fleet, wf_file) if hub else None
        if budget is None and w.get("max_budget_usd") is not None:
            budget = {"per_run_usd": float(w["max_budget_usd"])}
        model = w.get("model")
        twins = step_by_workflow.get(wf_file, []) if hub else []
        if model is None and twins:
            models = sorted({t["model"] for t in twins})
            model = models[0] if len(models) == 1 else models
        entry = {
            "id": aid, "kind": w["kind"], "repo": w["repo"], "where": w["path"],
            "owner": (loop[1].get("owner") if loop else None),
            "trigger": _trigger(w["triggers"], w["crons"]),
            "switch": switch, "budget": budget, "model": model,
        }
        if twins:
            entry["local_entry"] = "; ".join(f"tools/dash loop run {t['loop']} {t['step']}"
                                             for t in twins if t["local"]) or None
            entry["counterparts"] = [f"loop:{t['loop']}/{t['step']}" for t in twins]
        if w.get("archived"):
            entry["status"] = "archived"
        entry["_scope"] = "hub" if hub else "fleet"
        entries.append(entry)

    hub_ci_ids = {e["id"] for e in entries if e["_scope"] == "hub"}
    for s in steps:
        ci_id = f"ci:{hub_nwo.split('/', 1)[-1]}:{_stem(s['workflow'])}"
        cap = {"per_run_usd": float(s["max_budget_usd"]), "call_sites": {s["call_site"]: float(s["max_budget_usd"])}}
        monthly = dig(fleet, "budget.loops.monthly_usd")
        if isinstance(monthly, (int, float)):
            cap["monthly_usd"] = float(monthly)
        switch = dict(s["switch"]) if s["switch"] else None
        reads = sorted({CONTEXT_SOURCES[p] for p in s["providers"] if p in CONTEXT_SOURCES})
        entries.append({
            "id": f"loop:{s['loop']}/{s['step']}", "kind": "loop-step", "repo": hub_nwo,
            "where": f"tools/jev/steps/{s['loop']}/{s['step']}.yml", "owner": None,
            "trigger": (f"manual (tools/dash loop run {s['loop']} {s['step']}); --scheduled reads "
                        f"vars.{s['switch']['variable']}") if s["switch"] else
                       f"manual (tools/dash loop run {s['loop']} {s['step']})",
            "switch": switch, "budget": cap, "model": s["model"],
            "local_entry": f"tools/dash loop run {s['loop']} {s['step']}" if s["local"] else None,
            "counterparts": [ci_id] if ci_id in hub_ci_ids else [],
            "_reads": reads, "_ci_overlay": ci_id, "_scope": "hub",
        })

    jev = fleet.get("jev") if isinstance(fleet.get("jev"), dict) else {}
    bjev = dig(fleet, "budget.jev") or {}
    tiers = jev.get("tiers") if isinstance(jev.get("tiers"), dict) else {}
    auto, ci_tiers = list(jev.get("auto_tiers") or []), list(jev.get("ci_tiers") or [])
    sched = dig(fleet, "schedule.jev_conflicts")
    for tier in ["tier0", *sorted(tiers)]:
        where_runs = []
        if tier in ci_tiers:
            where_runs.append(f"CI jev-conflicts.yml ({hr.describe_cron(sched)})" if sched else "CI jev-conflicts.yml")
        if tier in auto:
            where_runs.append("local tools/dash conflicts sweep (com.bamr87.conflict-sweep)")
        spec = tiers.get(tier) or {}
        if tier == "tier0":
            model, budget = "none", {"per_run_usd": 0.0}
        else:
            model = spec.get("model")
            per = bjev.get(f"{tier}_usd")
            budget = {"per_run_usd": float(per)} if isinstance(per, (int, float)) else None
            if budget is not None and isinstance(bjev.get("monthly_usd"), (int, float)):
                budget["monthly_usd"] = float(bjev["monthly_usd"])
        switch = {"config": "jev.enabled", "tiers": "jev.auto_tiers"}
        if tier in ci_tiers:
            switch["variable"] = "JEV_CONFLICTS_ENABLED"
        entries.append({
            "id": f"jev:{tier}", "kind": "jev-tier", "repo": hub_nwo, "where": "tools/jev/conflicts.py",
            "owner": None, "trigger": "; ".join(where_runs) or "not in jev.auto_tiers (idle)",
            "switch": switch, "budget": budget, "model": model,
            "local_entry": "tools/dash conflicts sweep", "_scope": "hub",
        })

    declared = {aid: o["declare"] for aid, o in contract["overlays"].items() if isinstance(o.get("declare"), dict)}
    for inst in installers:
        aid = f"local:{inst['name']}"
        if aid in declared:
            # The declaration keeps winning until a PR drops it, so the
            # installer's own merge never changes the committed inventory
            # under an unrelated PR; the drop is that later PR's diff.
            notes.append(f"{aid}: its installer {inst['installer']} is in the tree now — drop "
                         f"harness.agents.{aid}.declare and regenerate, so its discovered facts are used")
            continue
        entries.append({
            "id": aid, "kind": "local-job", "repo": hub_nwo, "where": inst["installer"], "owner": None,
            "trigger": f"launchd com.bamr87.{inst['name']}: {inst['schedule']}" if inst["schedule"] else None,
            "switch": {"uninstall": inst["uninstall"]} if inst["uninstall"] else None,
            "budget": None, "model": None, "runs": inst["runs"], "_scope": "hub",
        })
    for aid, decl in sorted(declared.items()):
        entries.append({
            "id": aid, "kind": decl["kind"], "repo": hub_nwo, "where": decl.get("where"), "owner": None,
            "trigger": decl.get("trigger"), "switch": None, "budget": None, "model": None,
            "runs": list(decl.get("runs") or []), "pending": decl.get("pending"), "_scope": "hub",
        })
    return entries, notes


def _writer_status(sid: str, contract: dict, entry_ids: dict[str, dict]) -> tuple[str | None, str | None]:
    """(writer, gap) for one source an agent reads."""
    src = contract["sources"].get(sid) or {}
    writer = src.get("writer")
    if writer is None:
        return None, f"R4:no-writer:{sid}"
    if src.get("slo_days") is None and src.get("slo") is None:
        return writer, f"R4:no-slo:{sid}"
    agent = entry_ids.get(writer)
    if agent is not None and agent.get("pending"):
        return writer, f"R4:writer-pending:{sid}"
    return writer, None


def apply_contract(entries: list[dict], contract: dict) -> list[dict]:
    """Overlays, kind defaults, KPIs, the reflector and the gaps — in place,
    returning the final entries in the committed order."""
    overlays = contract["overlays"]
    by_id = {e["id"]: e for e in entries}
    for e in entries:
        kind = contract["kinds"].get(e["kind"]) or {}
        ov = overlays.get(e["id"]) or {}
        ci_ov = overlays.get(e.get("_ci_overlay") or "") or {}
        e["category"] = KINDS[e["kind"]]
        e["owner"] = ov.get("owner") or e.get("owner") or contract["owner"]
        for key in ("model", "budget", "switch"):
            if key in ov:
                e[key] = ov[key]
        if e.get("switch") is None and kind.get("switch"):
            e["switch"] = dict(kind["switch"])
        if "local_entry" in ov:
            e["local_entry"] = ov["local_entry"]
        elif not e.get("local_entry") and kind.get("local_entry"):
            e["local_entry"] = dict(kind["local_entry"])
        e.setdefault("local_entry", None)
        reads = set(kind.get("reads") or []) | set(e.pop("_reads", [])) | set(ov.get("reads") or []) \
            | set(ci_ov.get("reads") or [])
        e["kpis"] = dict(kind.get("kpis") or {})
        store = ov["run_record"] if "run_record" in ov else kind.get("run_record")
        e["run_record"] = None if store == "none" else store
        via = ov["reflector_via"] if "reflector_via" in ov else kind.get("reflector_via")
        e["feeds_reflector"] = bool(via) and via in contract["reflector_inputs"]
        e["_reads_set"] = reads
        if ov.get("note"):
            e["note"] = ov["note"]

    for e in entries:
        reads_out, gaps = {}, []
        for sid in sorted(e.pop("_reads_set")):
            writer, gap = _writer_status(sid, contract, by_id)
            reads_out[sid] = writer
            if gap:
                gaps.append(gap)
        e["reads"] = reads_out
        archived = e.get("status") == "archived"
        no_model = e.get("model") == "none"
        if not archived:
            for field, label in (("owner", "owner"), ("trigger", "trigger"), ("switch", "switch"),
                                 ("budget", "budget"), ("model", "model")):
                if not e.get(field):
                    gaps.insert(0, f"R1:{label}")
            if not no_model:
                store = e.get("run_record")
                if store is None:
                    gaps.append("R2:no-record")
                else:
                    missing = (contract["stores"].get(store) or {}).get("missing") or []
                    if missing:
                        gaps.append(f"R2:missing:{','.join(missing)}")
                if not e["feeds_reflector"]:
                    gaps.append("R5:no-reflector")
            if not e["kpis"]:
                gaps.append("R3:no-kpis")
            if not e["reads"]:
                gaps.append("R4:no-sources")
            if not e.get("local_entry"):
                gaps.append("R6:no-local-entry")
        else:
            gaps = []
        e["gaps"] = sorted(set(gaps), key=lambda g: (g[:2], g))

    order = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    entries.sort(key=lambda e: (order[e["category"]], e["_scope"] != "hub", e["id"]))
    return entries


FIELD_ORDER = ["id", "kind", "category", "repo", "where", "status", "pending", "owner", "trigger", "runs",
               "switch", "budget", "model", "kpis", "reads", "run_record", "feeds_reflector", "local_entry",
               "counterparts", "first_seen", "gaps", "note"]


def _ordered(e: dict) -> dict:
    out = {k: e[k] for k in FIELD_ORDER if k in e and not (k in ("status", "pending", "runs", "counterparts", "note")
                                                           and not e[k])}
    return out


def render(contract: dict, entries: list[dict], prior: dict, today: dt.date) -> dict:
    """The committed document. `first_seen` is carried forward from `prior`
    (the committed file), so regenerating is deterministic for every agent the
    inventory already holds."""
    seen = {a.get("id"): a.get("first_seen") for a in prior.get("agents") or [] if isinstance(a, dict)}
    agents = []
    for e in entries:
        e = dict(e)
        e["first_seen"] = str(seen.get(e["id"]) or today.isoformat())
        e.pop("_scope", None)
        e.pop("_ci_overlay", None)
        agents.append(_ordered(e))
    by_kind: dict[str, int] = {}
    by_cat: dict[str, int] = {}
    by_rule = {r: 0 for r in RULES}
    for a in agents:
        by_kind[a["kind"]] = by_kind.get(a["kind"], 0) + 1
        by_cat[a["category"]] = by_cat.get(a["category"], 0) + 1
        for r in {g[:2] for g in a["gaps"]}:
            by_rule[r] += 1
    sources_out = {}
    for sid, spec in contract["sources"].items():
        sources_out[sid] = {"path": spec.get("path"), "writer": spec.get("writer"),
                            "slo": f"{spec['slo_days']}d" if spec.get("slo_days") else spec.get("slo")}
    return {
        "schema": SCHEMA_MARKER,
        "contract": {
            "amendment": "agentic-efficacy-contract (constitution § 29)",
            "adr": "docs/adr/0009-agentic-efficacy-model.md",
            "enforce": contract["enforce"],
            "shadow_until": contract["shadow_until"].isoformat() if contract["shadow_until"] else None,
            "grace_until": contract["grace_until"].isoformat() if contract["grace_until"] else None,
            "rules": dict(RULES),
        },
        "totals": {
            "agents": len(agents),
            "by_category": {c: by_cat.get(c, 0) for c in CATEGORY_ORDER},
            "by_kind": {k: by_kind.get(k, 0) for k in KINDS},
            "with_gaps": sum(1 for a in agents if a["gaps"]),
            "gaps_by_rule": by_rule,
        },
        "kpis": {k: dict(v) for k, v in contract["kpis"].items()},
        "kinds": {k: {"category": KINDS[k], "kpis": v["kpis"]} for k, v in contract["kinds"].items()},
        "run_record": {"fields": list(contract["fields"]),
                       "stores": {k: dict(v) for k, v in contract["stores"].items()}},
        "sources": sources_out,
        "agents": agents,
        "note": (
            "The fleet's agent inventory under the agentic efficacy contract (constitution § 29, "
            "docs/AGENT-EFFICACY.md). Generated offline by `tools/dash agents` from the hub's workflows, "
            "the JEV step specs, the conflict tiers, the tools/install-*.sh installers and the committed "
            "harness_registry.yml (the fleet half), graded against _data/fleet.yml harness.efficacy / "
            "sources / agents. Drift check (p) holds it current; fleet-pulse.yml refreshes it daily. "
            "`schema` is the compatibility marker: additive changes are free, renames bump it."
        ),
    }


def generate(fleet: dict, registry: dict, hub_wfs: list[dict], steps: list[dict], installers: list[dict],
             prior: dict, today: dt.date) -> tuple[dict, list[str], list[str]]:
    """(document, errors, warnings) — pure over its inputs."""
    contract, errors, warnings = load_contract(fleet)
    hub_nwo = dig(fleet, "hub.repo") or "bamr87/bamr87"
    fleet_wfs = fleet_workflows(registry, hub_nwo)
    entries, notes = build_entries(fleet, contract, hub_nwo, hub_wfs, fleet_wfs, steps, installers)
    warnings += notes
    ids = [e["id"] for e in entries]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        errors.append(f"two agents share an id: {', '.join(dupes)}")
    for aid, ov in contract["overlays"].items():
        if aid not in ids:
            warnings.append(f"harness.agents.{aid} describes no discovered or declared agent")
    scopes = {e["id"]: e["_scope"] for e in entries}
    entries = apply_contract(entries, contract)
    for e in entries:
        for sid in e["reads"]:
            if sid not in contract["sources"]:
                errors.append(f"{e['id']} reads {sid!r}, which harness.sources does not declare")
    doc = render(contract, entries, prior, today)
    doc["_scopes"] = scopes  # stripped before writing; --check reads them
    doc["_hub"] = hub_nwo
    return doc, errors, warnings


# --------------------------------------------------------------------------- #
# check
# --------------------------------------------------------------------------- #
def compare(fresh: dict, committed: dict, *, strict_fleet: bool) -> tuple[list[str], list[str]]:
    """(failures, warnings) between a fresh build and the committed file."""
    fails: list[str] = []
    warns: list[str] = []
    if not committed:
        return ["_data/agents.yml is missing — run `tools/dash agents`"], []
    if committed.get("schema") != SCHEMA_MARKER:
        return [f"_data/agents.yml schema is {committed.get('schema')!r}, not {SCHEMA_MARKER} — run `tools/dash agents`"], []
    scopes = fresh.get("_scopes") or {}
    hub = fresh.get("_hub")
    new = {a["id"]: a for a in fresh["agents"]}
    old = {a.get("id"): a for a in committed.get("agents") or [] if isinstance(a, dict)}

    def scope(aid: str, entry: dict | None) -> str:
        if aid in scopes:
            return scopes[aid]
        return "fleet" if entry and str(aid).startswith("ci:") and entry.get("repo") != hub else "hub"

    buckets = {"hub": {"unregistered": [], "removed": [], "stale": []},
               "fleet": {"unregistered": [], "removed": [], "stale": []}}
    for aid in sorted(set(new) - set(old)):
        buckets[scope(aid, new[aid])]["unregistered"].append(aid)
    for aid in sorted(set(old) - set(new)):
        buckets[scope(aid, old[aid])]["removed"].append(aid)
    for aid in sorted(set(new) & set(old)):
        if new[aid] != old[aid]:
            buckets[scope(aid, new[aid])]["stale"].append(aid)
    fix = "run `tools/dash agents` and commit _data/agents.yml"
    for name, ids in buckets["hub"].items():
        if ids:
            what = {"unregistered": "agent(s) not registered in _data/agents.yml",
                    "removed": "registered agent(s) no longer found",
                    "stale": "registered agent(s) whose entry is stale"}[name]
            fails.append(f"{len(ids)} {what}: {', '.join(ids[:8])}{' …' if len(ids) > 8 else ''} — {fix}")
    for key in ("contract", "kpis", "kinds", "run_record", "sources"):
        if fresh.get(key) != committed.get(key):
            fails.append(f"_data/agents.yml `{key}:` is stale against _data/fleet.yml harness: — {fix}")
    fleet_ids = [i for ids in buckets["fleet"].values() for i in ids]
    if fleet_ids:
        msg = (f"{len(fleet_ids)} fleet agent(s) differ from the committed harness_registry.yml scan: "
               f"{', '.join(fleet_ids[:6])}{' …' if len(fleet_ids) > 6 else ''} — fleet-pulse.yml refreshes "
               f"both daily; {fix} to refresh now")
        (fails if strict_fleet else warns).append(msg)
    if not fails and not fleet_ids:
        body = {k: v for k, v in fresh.items() if not k.startswith("_")}
        if body != committed:
            fails.append(f"_data/agents.yml differs from a fresh build (edited by hand?) — {fix}")
    return fails, warns


def gap_verdicts(doc: dict, contract_dates: dict, today: dt.date) -> tuple[list[str], list[str]]:
    """(failures, warnings) for contract gaps. Failures only once enforcement
    is on, and then only for an agent past its grace."""
    agents = doc["agents"]
    gapped = [a for a in agents if a["gaps"]]
    if not gapped:
        return [], []
    enforce = contract_dates["enforce"]
    shadow, grace = contract_dates["shadow_until"], contract_dates["grace_until"]
    by_rule = doc["totals"]["gaps_by_rule"]
    summary = " · ".join(f"{r} {n}" for r, n in by_rule.items() if n)
    no_kpis = [a["id"] for a in agents if any(g.startswith("R3:") for g in a["gaps"])]
    no_writer = sorted({g.split(":", 2)[2] for a in agents for g in a["gaps"] if g.startswith("R4:no-writer:")})
    pending = sorted({g.split(":", 2)[2] for a in agents for g in a["gaps"] if g.startswith("R4:writer-pending:")})
    warns, fails = [], []
    if not enforce:
        warns.append(f"contract gaps (shadow: enforce is false, shadow until {shadow}): {len(gapped)} of "
                     f"{len(agents)} agents — {summary} (`tools/dash agents --verbose` lists them)")
        if no_kpis:
            warns.append(f"{len(no_kpis)} agent(s) declare no KPIs: {', '.join(no_kpis[:6])}")
        if no_writer:
            warns.append(f"agents read source(s) with no writer (rule 4 defect): {', '.join(no_writer)}")
        if pending:
            warns.append(f"source(s) whose writer is not installed yet: {', '.join(pending)}")
        return fails, warns
    for a in gapped:
        first = dt.date.fromisoformat(a["first_seen"])
        grandfathered = shadow is not None and first < shadow
        if grandfathered and grace is not None and today <= grace:
            continue
        fails.append(f"{a['id']}: {', '.join(a['gaps'])}")
    held = len(gapped) - len(fails)
    if held:
        warns.append(f"{held} agent(s) with contract gaps are in their grace period until {grace}")
    return fails, warns


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def _dump(doc: dict) -> str:
    body = {k: v for k, v in doc.items() if not k.startswith("_")}
    head = ("# GENERATED by .github/scripts/dash-gen (agent_inventory) — `tools/dash agents`; refreshed daily\n"
            "# by fleet-pulse.yml. Edit the generator or _data/fleet.yml harness:, not this file.\n")
    return head + yaml.safe_dump(body, sort_keys=False, allow_unicode=True, width=120)


def run(args: argparse.Namespace) -> int:
    today = dt.date.fromisoformat(args.today) if args.today else dt.datetime.now(dt.timezone.utc).date()
    fleet = load_yaml(Path(args.fleet))
    registry = load_yaml(Path(args.registry))
    out_path = Path(args.out)
    prior = load_yaml(out_path)
    hub_nwo = dig(fleet, "hub.repo") or "bamr87/bamr87"
    root = Path(args.root)
    try:
        steps = load_steps(fleet)
    except Exception as exc:  # a spec that does not load is reported, not hidden
        print(f"  ✗ loop step specs do not load: {exc}")
        return 1
    hub_wfs = hub_workflows(root / ".github" / "workflows", hub_nwo)
    installers = discover_installers(root / "tools")
    try:
        doc, errors, warnings = generate(fleet, registry, hub_wfs, steps, installers, prior, today)
    except ContractError as exc:
        print(f"  ✗ {exc}")
        return 1
    contract_dates = load_contract(fleet)[0]
    if errors:
        for e in errors:
            print(f"  ✗ {e}")
        return 1

    if args.check:
        fails, warns = compare(doc, prior, strict_fleet=args.strict_fleet)
        gfails, gwarns = gap_verdicts(doc, contract_dates, today)
        if contract_dates["enforce"] and contract_dates["shadow_until"] and today < contract_dates["shadow_until"]:
            fails.append(f"harness.efficacy.enforce is true before shadow_until {contract_dates['shadow_until']}"
                         " — the checks run in shadow first")
        for w in warnings + warns + gwarns:
            print(f"  ! {w}")
        if args.verbose:
            for a in doc["agents"]:
                if a["gaps"]:
                    print(f"      {a['id']}: {', '.join(a['gaps'])}")
        for f in fails + gfails:
            print(f"  ✗ {f}")
        if not (fails or gfails):
            t = doc["totals"]
            kinds = ", ".join(f"{k} {n}" for k, n in t["by_kind"].items() if n)
            print(f"  ✓ _data/agents.yml is current: {t['agents']} agents ({kinds})")
        return 1 if (fails or gfails) else 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_dump(doc), encoding="utf-8")
    if not args.quiet:
        t = doc["totals"]
        sys.stderr.write(f"Wrote {out_path} — {t['agents']} agents "
                         f"({', '.join(f'{k} {n}' for k, n in t['by_category'].items())}); "
                         f"{t['with_gaps']} with contract gaps\n")
        for w in warnings:
            sys.stderr.write(f"  ! {w}\n")
        if args.verbose:
            for a in doc["agents"]:
                if a["gaps"]:
                    sys.stderr.write(f"      {a['id']}: {', '.join(a['gaps'])}\n")
    return 0


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--fleet", default=str(FLEET_DEFAULT), help="fleet.yml (harness: the contract)")
    parser.add_argument("--registry", default=str(REGISTRY_DEFAULT),
                        help="harness_registry.yml (the fleet's AI workflows, from the daily scan)")
    parser.add_argument("--root", default=str(REPO_ROOT), help="the hub checkout (workflows, installers)")
    parser.add_argument("--out", default=str(OUT_DEFAULT), help="output path, and the committed file --check reads")
    parser.add_argument("--check", action="store_true",
                        help="drift check (p): fail when the committed file is stale; write nothing")
    parser.add_argument("--strict-fleet", action="store_true",
                        help="with --check: drift in the fleet half fails too (the daily --ci run)")
    parser.add_argument("--verbose", action="store_true", help="list every agent's contract gaps")
    parser.add_argument("--today", default=None, metavar="YYYY-MM-DD",
                        help="the date a newly seen agent is stamped with, and grace is judged on (tests)")
    parser.add_argument("--quiet", action="store_true", help="suppress the summary lines")
    parser.set_defaults(func=run)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(ap)
    raise SystemExit(run(ap.parse_args()))
