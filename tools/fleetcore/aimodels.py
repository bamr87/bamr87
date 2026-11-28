#!/usr/bin/env python3
"""Fleet AI models: which model each kind of AI work runs on, every place that is
written, and what a switch would take (ADR 0019, docs/AI-MODELS.md).

AI-agnostic means a provider can be switched easily and nothing gets worse when
it is. This module turns both halves into numbers, from files already on disk:

  easy    a switch is easy when the model behind a kind of work is written ONCE.
          `_data/fleet.yml` `ai_models.classes` is that one place: a class (the
          kind of work) bound to one allowed model. Every other place that names
          a model is a BINDING the switch must also edit: a setting elsewhere in
          the settings, a literal in a workflow, an action, a tool, a kit or a
          step spec, a literal in a fleet repo's own workflows, the model an
          eval set is pinned to. `bindings()` finds them all; the count is the
          cost of a switch, and the goal is zero.
  safe    a switch is safe when the evals of the work it moves have passed on
          the target. `tools/evals.py run <role> --model M --record` writes one
          row per run to `_data/eval_runs.yml`; `eval_state()` reads a row as
          proven only when it ran the whole set, nothing failed, and the set is
          the one in the tree today.

  load_model()     `ai_models:` checked for shape: providers and their allowed
                   models, the classes, which agents each eval set covers
  bindings()       every place a model is named, with its file and line
  status_doc()     THE document (`fleet-ai-models/v1`): classes with their
                   counts, bindings, eval sets with their recorded runs, findings
  switch_plan()    what moving one class to another model takes: the edits, the
                   agents it moves, which of them are proven, and why it is or
                   is not ready

The code names no provider and no model: every id it looks for comes from
`ai_models.allowed`, and tools/test_fleetcore_aimodels.py holds that.

Read-only (constitution § 10.6): no network, no subprocess, no model call, and
nothing is written. The one writer of `_data/eval_runs.yml` is tools/evals.py.

    python3 -m fleetcore.aimodels [models|bindings|switch|json] [--instance DIR]
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import yaml

from . import clouds, yamlio

HUB = Path(__file__).resolve().parents[2]
SCHEMA = "fleet-ai-models/v1"
RUNS_SCHEMA = "eval-runs/v1"
RUNS_FILE = Path("_data") / "eval_runs.yml"
AGENTS_FILE = Path("_data") / "agents.yml"
SETTINGS_FILE = Path("_data") / "fleet.yml"
EVALS_DIR = Path("evals")
WORKFLOW_DIR = Path(".github") / "workflows"
MAX_BYTES = 1024 * 1024

# Where a model can be named in a control plane's own tree, and what each place
# is: (class of binding, directory, whether to descend, file suffixes).
AREAS = (
    ("workflow", WORKFLOW_DIR, False, (".yml", ".yaml")),
    ("action", Path(".github") / "actions", True, (".yml", ".yaml", ".sh", ".py")),
    ("generator", Path(".github") / "scripts", True, (".py", ".sh")),
    ("step", Path("tools") / "jev" / "steps", True, (".yml", ".yaml")),
    ("tool", Path("tools"), True, (".py", ".sh", ".yml", ".yaml")),
    ("kit", Path("templates"), True, (".yml", ".yaml", ".sh", ".py", ".template")),
)
# A binding in one of these is an edit a switch owes. `pin` (the model an eval
# set was last held to) and `table` (a price or an alias per model) are listed
# and counted apart: a pin moves when the set is re-run, a table gains a row.
EDIT_CLASSES = ("setting", "workflow", "action", "generator", "step", "tool", "kit", "fleet-workflow")
SKIP_PARTS = {"tests", "test", "fixtures", "archive", "node_modules", "dist", "build", "__pycache__", "evidence"}
# A recorded run that ran every case. Anything else is a sample, never proof.
WHOLE_SET = "all"
# States of one eval set on one model, best first.
STATES = ("proven", "partial", "stale", "failed", "unproven")

_FLAG = re.compile(r"--model[ =]+([A-Za-z0-9][A-Za-z0-9._:/-]*)")
_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class ModelError(ValueError):
    """`ai_models:` is not the shape this module reads; the message lists every problem."""


def _load(path: Path):
    try:
        return yamlio.load(path)
    except (OSError, yaml.YAMLError):
        return None


def _strs(value) -> list[str]:
    if value is None:
        return []
    return [str(v) for v in (value if isinstance(value, list) else [value]) if str(v).strip()]


# --------------------------------------------------------------------------- #
# The model
# --------------------------------------------------------------------------- #
def model_problems(block) -> list[str]:
    """Every reason `ai_models:` cannot be read, as sentences. Empty means it can."""
    if not isinstance(block, dict):
        return ["`ai_models:` must be a mapping"]
    allowed = block.get("allowed")
    if not isinstance(allowed, dict) or not allowed:
        return ["`ai_models.allowed` must map each provider to its allowed model ids"]
    out: list[str] = []
    owner: dict[str, str] = {}
    for provider, ids in allowed.items():
        if not isinstance(ids, list) or not all(isinstance(m, str) and m.strip() for m in ids):
            out.append(f"ai_models.allowed.{provider} must be a list of model ids")
            continue
        for mid in ids:
            if mid in owner and owner[mid] != str(provider):
                out.append(f"ai_models.allowed: {mid} is listed under {owner[mid]} and {provider}; a model has one provider")
            owner[mid] = str(provider)
    classes = block.get("classes")
    if not isinstance(classes, dict) or not classes:
        out.append("`ai_models.classes` must bind at least one class of work to a model")
    else:
        for name, mid in classes.items():
            if not _ID.match(str(name)):
                out.append(f"ai_models.classes.{name}: a class name is lowercase letters, digits and hyphens")
            if not isinstance(mid, str) or mid not in owner:
                out.append(f"ai_models.classes.{name}: {mid!r} is not in ai_models.allowed (constitution § 13.3)")
    evals = block.get("evals")
    if evals is not None and not isinstance(evals, dict):
        out.append("`ai_models.evals` must map an eval role to the agents it covers")
    for role, spec in (evals or {}).items() if isinstance(evals, dict) else []:
        if not isinstance(spec, dict) or not _strs(spec.get("agents")):
            out.append(f"ai_models.evals.{role} needs `agents`: the agent ids its set covers")
    scan = block.get("scan")
    if scan is not None and not isinstance(scan, dict):
        out.append("`ai_models.scan` must be a mapping")
    return out


def normalize(block: dict) -> dict:
    providers = {str(p): [str(m) for m in ids] for p, ids in block["allowed"].items()}
    return {
        "providers": providers,
        "provider_of": {m: p for p, ids in providers.items() for m in ids},
        "classes": {str(k): str(v) for k, v in block["classes"].items()},
        "evals": {str(r): {"agents": _strs(s.get("agents")), "covers": str(s.get("covers") or "")}
                  for r, s in (block.get("evals") or {}).items()},
        "tables": set(_strs((block.get("scan") or {}).get("tables"))),
    }


def load_model(instance: Path = HUB, framework: Path = HUB) -> dict:
    """`ai_models:` as this module reads it: the framework's block laid under the
    instance's (ADR 0011), so an instance that declares only what differs still reads whole."""
    base = (_load(framework / SETTINGS_FILE) or {}).get("ai_models")
    over = None
    if instance.resolve() != framework.resolve():
        over = (_load(instance / SETTINGS_FILE) or {}).get("ai_models")
    block = clouds._merge(base, over) if base is not None else over
    problems = model_problems(block)
    if problems:
        raise ModelError("; ".join(problems))
    return normalize(block)


def provider_of(model: dict, mid: str) -> str | None:
    """The provider an allowed model belongs to, or None for a model the fleet does not allow."""
    return model["provider_of"].get(mid)


def classes_of(model: dict, mid: str) -> list[str]:
    return [name for name, bound in model["classes"].items() if bound == mid]


# --------------------------------------------------------------------------- #
# Bindings: every place a model is named
# --------------------------------------------------------------------------- #
def _finder(model: dict) -> re.Pattern | None:
    """Matches any allowed model id as a whole token, the longest id first."""
    ids = sorted(model["provider_of"], key=len, reverse=True)
    if not ids:
        return None
    return re.compile(r"(?<![A-Za-z0-9._-])(" + "|".join(re.escape(i) for i in ids) + r")(?![A-Za-z0-9_-])")


def _skipped(below: Path) -> bool:
    """A file under an area that is not part of what runs: a test, a fixture, an archived
    copy, generated output, or anything in a hidden directory. `below` is relative to the area."""
    name = below.name
    return (any(p in SKIP_PARTS or p.startswith(".") for p in below.parts[:-1])
            or name.startswith("test_") or name.endswith("_test.py") or ".test." in name)


def _lines(path: Path):
    """(line number, text) for every line that is not a comment; nothing for a file that cannot be read."""
    try:
        if path.stat().st_size > MAX_BYTES:
            return
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for n, line in enumerate(text.splitlines(), 1):
        if not line.lstrip().startswith("#"):
            yield n, line


def _scan_file(path: Path, rel: str, kind: str, repo: str, finder: re.Pattern, model: dict) -> tuple[list[dict], list[dict]]:
    found, unlisted = [], []
    for n, line in _lines(path):
        for mid in dict.fromkeys(finder.findall(line)):
            found.append({"class": kind, "repo": repo, "file": rel, "line": n, "model": mid,
                          "provider": model["provider_of"][mid]})
        if kind in ("workflow", "fleet-workflow"):
            for value in _FLAG.findall(line):
                if value not in model["provider_of"]:
                    unlisted.append({"repo": repo, "file": rel, "line": n, "model": value})
    return found, unlisted


def _files(root: Path, base: Path, descend: bool, suffixes: tuple[str, ...]):
    top = root / base
    if not top.is_dir():
        return
    if not descend:
        for p in sorted(top.iterdir()):
            if p.is_file() and p.suffix in suffixes:
                yield p
        return
    for cur, dirs, names in os.walk(top):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIP_PARTS)
        for name in sorted(names):
            if Path(name).suffix in suffixes:
                yield Path(cur) / name


def _settings(instance: Path, repo: str, model: dict) -> list[dict]:
    """Every key of the settings, outside `ai_models:` itself, whose value is an allowed model."""
    doc = _load(instance / SETTINGS_FILE) or {}
    out: list[dict] = []

    def walk(node, path: tuple[str, ...]):
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, path + (str(key),))
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, path + (str(i),))
        elif isinstance(node, str) and node in model["provider_of"]:
            out.append({"class": "setting", "repo": repo, "file": str(SETTINGS_FILE), "key": ".".join(path), "line": None,
                        "model": node, "provider": model["provider_of"][node]})

    for key, value in doc.items() if isinstance(doc, dict) else []:
        if key != "ai_models":
            walk(value, (str(key),))
    return out


def bindings(instance: Path, model: dict) -> tuple[list[dict], list[dict], dict]:
    """(every place a model is named, every `--model` a workflow passes that is not allowed, what was read)."""
    finder = _finder(model)
    read, unread, external, hub = clouds.targets(instance)
    found: list[dict] = _settings(instance, hub, model)
    unlisted: list[dict] = []
    seen: set[str] = set()
    if finder:
        for kind, base, descend, suffixes in AREAS:
            for path in _files(instance, base, descend, suffixes):
                rel = path.relative_to(instance)
                if str(rel) in seen or _skipped(path.relative_to(instance / base)):
                    continue
                seen.add(str(rel))  # a step spec under tools/ is a step, not also a tool
                got, extra = _scan_file(path, str(rel), "table" if str(rel) in model["tables"] else kind, hub, finder, model)
                found += got
                unlisted += extra
        for path in sorted((instance / EVALS_DIR).glob("*/cases.yml")) if (instance / EVALS_DIR).is_dir() else []:
            pin = (_load(path) or {}).get("model")
            if isinstance(pin, str) and pin in model["provider_of"]:
                found.append({"class": "pin", "repo": hub, "file": str(path.relative_to(instance)), "line": None,
                              "model": pin, "provider": model["provider_of"][pin]})
        for target in read:
            if target["status"] == "hub":
                continue
            for path in _files(target["path"], WORKFLOW_DIR, False, (".yml", ".yaml")):
                got, extra = _scan_file(path, str(path.relative_to(target["path"])), "fleet-workflow",
                                        target["repo"] or target["name"], finder, model)
                found += got
                unlisted += extra
    return found, unlisted, {"repos": len(read), "unread": [{"name": u["name"], "why": u["why"]} for u in unread],
                             "external": external, "hub": hub}


# --------------------------------------------------------------------------- #
# Agents and evals
# --------------------------------------------------------------------------- #
def agents(instance: Path) -> list[dict]:
    """The agent inventory's rows that run a model: [{id, repo, kind, models}]."""
    doc = _load(instance / AGENTS_FILE) or {}
    out = []
    for row in doc.get("agents") or [] if isinstance(doc, dict) else []:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        models = [m for m in _strs(row.get("model")) if m.lower() != "none"]
        out.append({"id": str(row["id"]), "repo": str(row.get("repo") or ""), "kind": str(row.get("kind") or ""),
                    "models": models})
    return out


def set_hash(path: Path) -> str | None:
    try:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def eval_sets(instance: Path, model: dict) -> list[dict]:
    """Every eval set in the tree: its mode, the model it is pinned to, its hash and the agents it covers."""
    out = []
    top = instance / EVALS_DIR
    for path in sorted(top.glob("*/cases.yml")) if top.is_dir() else []:
        doc = _load(path) or {}
        role = path.parent.name
        cover = model["evals"].get(role, {})
        out.append({"role": role, "mode": str(doc.get("mode") or "unknown"), "pin": doc.get("model") or None,
                    "set": set_hash(path), "cases": len(doc.get("cases") or []) if isinstance(doc.get("cases"), list) else 0,
                    "agents": cover.get("agents", []), "covers": cover.get("covers", "")})
    return out


def eval_runs(instance: Path) -> list[dict]:
    doc = _load(instance / RUNS_FILE) or {}
    return [r for r in doc.get("runs") or [] if isinstance(r, dict)] if isinstance(doc, dict) else []


def run_record(role: str, mid: str, provider: str | None, passed: int, failed: int, scope: str, set_digest: str | None,
               cost_usd: float, date: str) -> dict:
    """One row of `_data/eval_runs.yml`: the shape its writer (tools/evals.py) and this reader share."""
    return {"role": role, "model": mid, "provider": provider, "date": date, "scope": scope, "passed": int(passed),
            "failed": int(failed), "set": set_digest, "cost_usd": round(float(cost_usd), 4),
            "cost_label": "API-equivalent (estimate)"}


def eval_state(runs: list[dict], eval_set: dict, mid: str) -> dict:
    """How one eval set stands on one model: the latest recorded run decides, and a run is proof
    only when it ran the whole set, nothing failed, and the set is the one in the tree."""
    mine = [r for r in runs if r.get("role") == eval_set["role"] and r.get("model") == mid]
    if not mine:
        return {"state": "unproven", "date": None, "why": "no run on this model is recorded"}
    last = mine[-1]
    base = {"date": last.get("date"), "passed": last.get("passed"), "failed": last.get("failed")}
    if last.get("failed"):
        return {**base, "state": "failed", "why": f"{last.get('failed')} case(s) failed"}
    if last.get("set") != eval_set["set"]:
        return {**base, "state": "stale", "why": "the set changed after the run"}
    if last.get("scope") != WHOLE_SET:
        return {**base, "state": "partial", "why": f"the run took a sample ({last.get('scope')}), not the whole set"}
    return {**base, "state": "proven", "why": "the whole set passed on this model"}


def agent_state(agent_id: str, sets: list[dict], runs: list[dict], mid: str) -> dict:
    """One agent on one model: proven only when every model-backed set that covers it is proven
    and none covers just a part of it."""
    covering = [s for s in sets if agent_id in s["agents"] and s["mode"] == "model"]
    if not covering:
        return {"state": "no-evals", "roles": [], "why": "no eval set covers this agent"}
    rows = [{"role": s["role"], "covers": s["covers"], **eval_state(runs, s, mid)} for s in covering]
    worst = max((r["state"] for r in rows), key=STATES.index)
    if worst == "proven" and any(r["covers"] for r in rows):
        return {"state": "partial", "roles": rows, "why": "its eval set covers only part of it: " + "; ".join(r["covers"] for r in rows if r["covers"])}
    return {"state": worst, "roles": rows, "why": next(r["why"] for r in rows if r["state"] == worst)}


# --------------------------------------------------------------------------- #
# The document and the plan
# --------------------------------------------------------------------------- #
def _count(rows: list[dict], kinds: tuple[str, ...] | str) -> int:
    kinds = (kinds,) if isinstance(kinds, str) else kinds
    return sum(1 for r in rows if r["class"] in kinds)


def status_doc(instance: Path = HUB, framework: Path = HUB, now: dt.datetime | None = None) -> dict:
    """THE document every surface reads (`fleet-ai-models/v1`)."""
    model = load_model(instance, framework)
    found, unlisted, read = bindings(instance, model)
    sets = eval_sets(instance, model)
    runs = eval_runs(instance)
    roster = agents(instance)
    classes = []
    for name, mid in model["classes"].items():
        mine = [b for b in found if b["model"] == mid]
        on = [a for a in roster if mid in a["models"]]
        states = [agent_state(a["id"], sets, runs, mid)["state"] for a in on]
        classes.append({
            "id": name, "model": mid, "provider": model["provider_of"][mid],
            "settings": _count(mine, "setting"),
            "literals": _count(mine, ("workflow", "action", "generator", "step", "tool", "kit")),
            "fleet_literals": _count(mine, "fleet-workflow"), "pins": _count(mine, "pin"),
            "edits": _count(mine, EDIT_CLASSES),
            "agents": len(on), "proven": states.count("proven"), "no_evals": states.count("no-evals")})
    findings = []
    for u in unlisted:
        findings.append({"rule": "unlisted-model", "level": "note", "repo": u["repo"], "file": u["file"], "line": u["line"],
                         "message": f"{u['repo']} {u['file']}:{u['line']} passes --model {u['model']}, which ai_models.allowed does not list: "
                                    f"if an agent runs on it, it belongs there (constitution § 13.3); a product's own model does not"})
    bound = set(model["classes"].values())
    for mid in sorted({b["model"] for b in found if b["class"] in EDIT_CLASSES} - bound):
        n = sum(1 for b in found if b["model"] == mid and b["class"] in EDIT_CLASSES)
        findings.append({"rule": "classless-model", "level": "note", "repo": read["hub"], "file": None, "line": None,
                         "message": f"{mid} is named in {n} place(s) and no class in ai_models.classes is bound to it, so no switch plan covers those places"})
    for mid in sorted(bound):
        names = classes_of(model, mid)
        if len(names) > 1:
            findings.append({"rule": "shared-model", "level": "note", "repo": read["hub"], "file": None, "line": None,
                             "message": f"{mid} is bound to {' and '.join(names)}: until a place names its class and not a model, "
                                        f"a place that names {mid} cannot be told to one of them, and both count it"})
    for s in sets:
        if s["mode"] == "model" and not s["agents"]:
            findings.append({"rule": "uncovered-set", "level": "note", "repo": read["hub"], "file": f"evals/{s['role']}/cases.yml", "line": None,
                             "message": f"the eval set {s['role']} is mapped to no agent in ai_models.evals, so it proves nothing about a switch"})
    covered = {a for s in sets if s["mode"] == "model" for a in s["agents"]}
    with_model = [a for a in roster if a["models"]]
    return {
        "schema": SCHEMA,
        "generated_at": (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hub": read["hub"],
        "providers": [{"id": p, "models": ids, "bindings": sum(1 for b in found if b["provider"] == p and b["class"] in EDIT_CLASSES)}
                      for p, ids in model["providers"].items()],
        "classes": classes,
        "bindings": found,
        "evals": [{**s, "runs": {mid: eval_state(runs, s, mid)["state"] for mid in model["provider_of"]} if s["mode"] == "model" else {}}
                  for s in sets],
        "agents": {"total": len(roster), "with_model": len(with_model),
                   "covered": sum(1 for a in with_model if a["id"] in covered),
                   "by_model": {mid: sum(1 for a in roster if mid in a["models"]) for mid in model["provider_of"]}},
        "findings": findings,
        "read": read,
        "summary": {
            "classes": len(classes), "providers": len(model["providers"]),
            # What a switch of every class would have to edit beyond the class lines themselves. The goal is 0.
            "edits": _count(found, EDIT_CLASSES),
            "settings": _count(found, "setting"), "literals": _count(found, ("workflow", "action", "generator", "step", "tool", "kit")),
            "fleet_literals": _count(found, "fleet-workflow"), "pins": _count(found, "pin"), "tables": _count(found, "table"),
            "eval_runs": len(runs),
            "findings": {lvl: sum(1 for f in findings if f["level"] == lvl) for lvl in ("warn", "note")}},
    }


def switch_plan(instance: Path, new: str, cls: str | None = None, old: str | None = None,
                framework: Path = HUB) -> dict:
    """What moving one class of work (or every place that names `old`) to `new` takes.
    A plan only: it reads, and names every edit and every proof the switch owes."""
    model = load_model(instance, framework)
    if cls is not None:
        if cls not in model["classes"]:
            raise ModelError(f"no class {cls!r} in ai_models.classes (known: {', '.join(model['classes'])})")
        old = model["classes"][cls]
    if not old:
        raise ModelError("name the class to switch, or the model to switch from")
    found, _, read = bindings(instance, model)
    sets, runs, roster = eval_sets(instance, model), eval_runs(instance), agents(instance)
    mine = [b for b in found if b["model"] == old]
    shared = [c for c in classes_of(model, old) if c != cls]
    moved = []
    for agent in (a for a in roster if old in a["models"]):
        moved.append({"id": agent["id"], "repo": agent["repo"], **agent_state(agent["id"], sets, runs, new)})
    order = {"failed": 0, "stale": 1, "unproven": 2, "partial": 3, "no-evals": 4, "proven": 5}
    moved.sort(key=lambda a: (order[a["state"]], a["repo"].lower(), a["id"]))
    was, now = model["provider_of"].get(old), model["provider_of"].get(new)
    edits = [b for b in mine if b["class"] in EDIT_CLASSES]
    counts = {state: sum(1 for a in moved if a["state"] == state) for state in order}
    reasons = []
    if now is None:
        reasons.append(f"{new} is not in ai_models.allowed: adding it is a gated change (constitution § 12.3 and § 13.3)")
    elif now != was:
        reasons.append(f"the provider changes ({was} to {now}): the runner that reaches {now} has to pass the same "
                       f"conformance suite as today's first (ADR 0019, P2), and none is recorded")
    if shared:
        reasons.append(f"{old} is also bound to {', '.join(shared)}: its places cannot be told apart from this class's until they name a class")
    if edits:
        reasons.append(f"{len(edits)} place(s) besides the class line name {old} and would have to be edited by hand")
    unsafe = len(moved) - counts["proven"]
    if unsafe:
        reasons.append(f"{unsafe} of {len(moved)} agent(s) on {old} are not proven on {new}: "
                       + ", ".join(f"{n} {s}" for s, n in counts.items() if n and s != "proven"))
    notes = []
    also = [c for c in classes_of(model, new) if c != cls]
    if also and now is not None:
        notes.append(f"{new} is already bound to {', '.join(also)}: after this switch the places of both classes name one model, "
                     f"and the next switch of either cannot tell them apart until they name a class")
    return {
        "schema": SCHEMA, "class": cls, "from": old, "to": new,
        "provider": {"from": was, "to": now, "changes": now is not None and now != was, "allowed": now is not None},
        "easy": {"class_lines": 1 if cls else len(classes_of(model, old)), "settings": [b for b in mine if b["class"] == "setting"],
                 "literals": [b for b in mine if b["class"] in ("workflow", "action", "generator", "step", "tool", "kit")],
                 "fleet_literals": [b for b in mine if b["class"] == "fleet-workflow"],
                 "pins": [b for b in mine if b["class"] == "pin"], "edits": len(edits)},
        "safe": {"agents": moved, "counts": {s: n for s, n in counts.items() if n}, "total": len(moved)},
        "ready": not reasons, "reasons": reasons, "notes": notes, "read": read,
    }


# --------------------------------------------------------------------------- #
# The CLI
# --------------------------------------------------------------------------- #
def _table(rows: list[list[str]], head: list[str]) -> str:
    widths = [max(len(str(r[i])) for r in [head] + rows) for i in range(len(head))]
    line = lambda r: "  ".join(str(c).ljust(w) for c, w in zip(r, widths)).rstrip()  # noqa: E731
    return "\n".join([line(head), line(["-" * w for w in widths])] + [line(r) for r in rows])


def _where(b: dict) -> str:
    place = b.get("key") or (f"{b['file']}:{b['line']}" if b.get("line") else b["file"])
    return place if b["class"] != "fleet-workflow" else f"{b['repo']} {place}"


def classes_table(doc: dict) -> str:
    rows = [[c["id"], c["model"], c["provider"], str(c["settings"]), str(c["literals"]), str(c["fleet_literals"]),
             str(c["pins"]), str(c["agents"]), f"{c['proven']} of {c['agents']}"] for c in doc["classes"]]
    return _table(rows, ["CLASS", "MODEL", "PROVIDER", "SETTINGS", "HUB LITERALS", "FLEET LITERALS", "EVAL PINS", "AGENTS", "PROVEN"])


def read_line(read: dict) -> str:
    text = f"read {read['repos']} checkout(s)"
    if read["unread"]:
        text += f" · NOT read: {len(read['unread'])} ({', '.join(u['name'] for u in read['unread'][:6])}{'…' if len(read['unread']) > 6 else ''})"
    return text


def plan_text(plan: dict, limit: int) -> str:
    easy, safe, prov = plan["easy"], plan["safe"], plan["provider"]
    head = f"switch {plan['class'] or 'every place'}: {plan['from']} → {plan['to']}"
    lines = [head, ""]
    lines.append("TARGET  " + (f"{plan['to']} is allowed ({prov['to']})" + (f", a different provider from {prov['from']}" if prov["changes"] else "")
                               if prov["allowed"] else f"{plan['to']} is NOT in ai_models.allowed"))
    lines.append(f"EASY    {easy['class_lines']} class line(s) + {len(easy['settings'])} setting(s) + {len(easy['literals'])} literal(s) in the hub"
                 f" + {len(easy['fleet_literals'])} in fleet repos' workflows; {len(easy['pins'])} eval pin(s) move when their set is re-run")
    counts = ", ".join(f"{n} {s}" for s, n in safe["counts"].items()) or "none"
    lines.append(f"SAFE    {safe['total']} agent(s) run on {plan['from']}: {counts}")
    lines.append("")
    lines.append("READY: one line switches it, and every agent it moves is proven." if plan["ready"]
                 else "NOT READY:\n" + "\n".join(f"  - {r}" for r in plan["reasons"]))
    lines += [f"note: {n}" for n in plan["notes"]]
    for title, rows in (("settings", easy["settings"]), ("literals in the hub", easy["literals"]),
                        ("literals in fleet repos", easy["fleet_literals"]), ("eval pins", easy["pins"])):
        if rows:
            lines += ["", f"{title} ({len(rows)}):"] + [f"  {_where(b)}" for b in rows[:limit]]
            if len(rows) > limit:
                lines.append(f"  … {len(rows) - limit} more (--all)")
    if safe["agents"]:
        lines += ["", f"agents ({safe['total']}):"]
        lines += [f"  {a['state']:<9} {a['id']}  ({a['why']})" for a in safe["agents"][:limit]]
        if safe["total"] > limit:
            lines.append(f"  … {safe['total'] - limit} more (--all)")
    lines += ["", read_line(plan["read"])]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dash ai", description="Which model each kind of AI work runs on, where that is written, "
                                                               "and what a switch would take.")
    where = "the control plane whose settings and checkouts are read (default: FLEET_HOME, else this checkout)"
    ap.add_argument("--instance", default=os.environ.get("FLEET_HOME") or str(HUB), help=where)
    # The same flag after the subcommand, where people type it; unset there, the one above stands.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--instance", default=argparse.SUPPRESS, help=where)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("models", parents=[common],
                   help="the classes, the model each is bound to, and what a switch of each would cost (the default)")
    sub.add_parser("json", parents=[common], help="the document (fleet-ai-models/v1)")
    b = sub.add_parser("bindings", parents=[common], help="every place a model is named")
    b.add_argument("--model", help="only this model")
    b.add_argument("--class", dest="kind", help="only this class of binding (setting, workflow, tool, kit, fleet-workflow, pin, …)")
    s = sub.add_parser("switch", parents=[common], help="plan moving one class of work to another model; reads only")
    s.add_argument("cls", nargs="?", metavar="CLASS", help="the class to switch (ai_models.classes)")
    s.add_argument("--from", dest="old", help="instead of a class: every place that names this model")
    s.add_argument("--to", dest="new", required=True, help="the model to switch to")
    s.add_argument("--all", action="store_true", help="list every edit and every agent")
    s.add_argument("--json", action="store_true", help="the plan as JSON")
    s.add_argument("--strict", action="store_true", help="exit 1 when the switch is not ready")
    a = ap.parse_args(argv)
    root = Path(a.instance).expanduser()
    try:
        if a.cmd == "switch":
            if bool(a.cls) == bool(a.old):
                ap.error("name one class, or pass --from MODEL")
            plan = switch_plan(root, a.new, cls=a.cls, old=a.old, framework=HUB)
            print(json.dumps(plan, indent=2) if a.json else plan_text(plan, 10_000 if a.all else 12))
            return 1 if a.strict and not plan["ready"] else 0
        doc = status_doc(root, HUB)
    except ModelError as exc:
        print(f"dash ai: {exc}", file=sys.stderr)
        return 2
    if a.cmd == "json":
        print(json.dumps(doc, indent=2))
        return 0
    if a.cmd == "bindings":
        rows = [x for x in doc["bindings"] if (not a.model or x["model"] == a.model) and (not a.kind or x["class"] == a.kind)]
        print(_table([[x["class"], x["model"], _where(x)] for x in rows], ["CLASS", "MODEL", "WHERE"]) if rows else "no binding found")
        print(f"\n{len(rows)} binding(s) · {read_line(doc['read'])}")
        return 0
    sm, ag = doc["summary"], doc["agents"]
    print(classes_table(doc))
    others = doc["read"]["repos"] - 1
    print(f"\nA switch should be ONE line (the class). Today it is also {sm['edits']} more: {sm['settings']} setting(s), "
          f"{sm['literals']} literal(s) in the hub and {sm['fleet_literals']} in the workflows of the {others} fleet repo(s) read.")
    print(f"{ag['covered']} of {ag['with_model']} agent(s) that run a model are covered by an eval set · "
          f"{sm['eval_runs']} eval run(s) recorded · {sm['findings']['warn']} warning(s), {sm['findings']['note']} note(s)")
    for f in doc["findings"]:
        print(f"{f['level']:<4}  {f['rule']:<16}  {f['message']}")
    print(read_line(doc["read"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
