#!/usr/bin/env python3
"""
File: tools/sprint_record.py
Description: The live expedite-sprint record (constitution § 27.7, docs/EXPEDITE-SPRINTS.md).
             One committed state document per sprint, `_data/sprints/<slug>.yml`
             (schema `sprint/v1`), modelled on the SRE live incident document:
             the appetite, the three gates with who passed them and when, the
             phase, the items and pull requests, spend against the cap, the
             trip wires, a DORA snapshot and the retro. `lint` holds every
             record to the standard (drift check (r)); `show` prints the
             document the console's /sprints page reads (`/api/sprints`).
             Static, offline, stdlib + PyYAML, and read-only: a record changes
             only by a reviewed pull request, and nothing here writes one.
Usage: python3 tools/sprint_record.py lint [--dir DIR] [--fleet FILE] [--queue FILE] [--json]
       python3 tools/sprint_record.py show [--dir DIR] [--fleet FILE] [--queue FILE]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import sys
from pathlib import Path

import yaml

HUB = Path(__file__).resolve().parent.parent
SPRINTS_DIR = HUB / "_data" / "sprints"
FLEET = HUB / "_data" / "fleet.yml"
WORK_QUEUE = HUB / "_data" / "work_queue.yml"

SCHEMA = "sprint/v1"
DOC_SCHEMA = "sprint-records/v1"
COST_LABEL = "API-equivalent (estimate)"
STANDARD = "docs/EXPEDITE-SPRINTS.md"
# The phases of docs/EXPEDITE-SPRINTS.md, by number (3b, the JEV conflict tier, belongs to test).
PHASES = ("intake", "scope", "build", "test", "deploy", "monitor", "retro")
# The three gates, in the only order they can pass (§ 27.2), and the first phase each one opens:
# the declaration opens scope, spec approval opens build, the merge opens deploy.
GATES = ("declaration", "spec", "merge")
GATE_OPENS = {"declaration": 1, "spec": 2, "merge": 4}
GATE_KEYS = ("by", "at", "ref")
STATES = ("proposed", "active", "stopped", "demoted", "done")
STOP_REASONS = ("cap", "time-box", "kill-switch", "demoted", "owner")
TRIP_STATES = ("armed", "tripped", "cleared")
ITEM_STATES = {"issue": ("open", "closed"), "pr": ("draft", "open", "merged", "closed")}

TOP_REQUIRED = ("schema", "slug", "title", "item", "state", "phase", "appetite", "gates", "spend")
TOP_OPTIONAL = ("target_repo", "updated_at", "items", "trip_wires", "dora", "retro", "stop", "notes")
APPETITE_KEYS = ("hours", "usd", "label", "ends_at")
SPEND_KEYS = ("usd", "cap_usd", "label", "updated_at", "source")
ITEM_KEYS = ("ref", "kind", "title", "state", "phase")
TRIP_KEYS = ("id", "rule", "state", "at")
RETRO_KEYS = ("lessons", "debt")
STOP_KEYS = ("at", "reason", "by", "filed", "note")

SLUG_RX = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
REF_RX = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[1-9][0-9]*$")
REPO_RX = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
# A key that names a credential has no place in a public record, whatever it holds.
SECRET_KEY_RX = re.compile(r"(?i)(token|secret|passw(?:or)?d|api[_-]?key|credential|private[_-]?key|authorization|cookie)")
# The credential shapes the planes redact (tools/jev/context.py): a record holding one is refused.
SECRET_VALUE_RX = (
    re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{16,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAIza[A-Za-z0-9_\-]{20,}"),
    re.compile(r"\bnpm_[A-Za-z0-9]{36}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=\-]{12,}"),
    re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/@:'\"`]+:[^\s/@'\"`]+@"),
)
# A money field (`usd`, `cap_usd`, …) and a dollar figure written in prose.
MONEY_KEY_RX = re.compile(r"(?:^|_)usd$")
MONEY_TEXT_RX = re.compile(r"(?i)(\$\s?\d|\b\d[\d,.]*\s?(?:usd|dollars?)\b)")


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _when(value) -> dt.datetime | None:
    """A timestamp as an aware UTC datetime: YAML's own datetime or date, or an ISO 8601 string."""
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    if isinstance(value, dt.date):
        return dt.datetime(value.year, value.month, value.day, tzinfo=dt.timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
    return None


def _iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _num(value) -> float | None:
    """A finite number (never a bool), else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def plain(obj):
    """The record as JSON can carry it: timestamps as ISO 8601 strings."""
    if isinstance(obj, dict):
        return {str(k): plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [plain(v) for v in obj]
    if isinstance(obj, (dt.datetime, dt.date)):
        return _iso(_when(obj))
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def maintainer(fleet: dict) -> str:
    """The one login that passes a gate (§ 27.2): the owner of the hub repository."""
    repo = str(((fleet or {}).get("hub") or {}).get("repo") or "bamr87/bamr87")
    return repo.split("/", 1)[0]


def gate_passed(gate) -> bool:
    return isinstance(gate, dict) and bool(gate.get("by")) and _when(gate.get("at")) is not None


def _walk(obj, path: str = ""):
    """Every (path, key, value) in a nested record, keys included."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            here = f"{path}.{k}" if path else str(k)
            yield here, k, v
            yield from _walk(v, here)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            here = f"{path}[{i}]"
            yield here, None, v
            yield from _walk(v, here)


def secret_findings(record) -> list[str]:
    """Where a record holds something credential-shaped. The value itself is never repeated."""
    out = []
    for path, key, value in _walk(record):
        if key is not None and SECRET_KEY_RX.search(str(key)):
            out.append(f"`{path}`: a key that names a credential — a public record holds no secrets")
        if isinstance(value, str) and any(rx.search(value) for rx in SECRET_VALUE_RX):
            out.append(f"`{path}`: a secret-looking value — a public record holds no secrets (the value is not repeated here)")
    return out


def money_findings(record) -> list[str]:
    """Every dollar figure is labelled API-equivalent (estimate) (§ 10.7, § 27.4)."""
    out = []
    for path, key, value in _walk(record):
        if isinstance(value, dict):
            for k, v in value.items():
                if not MONEY_KEY_RX.search(str(k)):
                    continue
                where = f"{path}.{k}" if path else str(k)
                n = _num(v)
                if n is None or n < 0:
                    out.append(f"`{where}`: a USD figure must be a finite number ≥ 0")
                if value.get("label") != COST_LABEL:
                    out.append(f"`{where}`: an unlabelled USD figure — its mapping needs `label: {COST_LABEL}`")
        elif isinstance(value, str) and MONEY_TEXT_RX.search(value) and COST_LABEL not in value:
            out.append(f"`{path}`: a dollar figure in text without `{COST_LABEL}`")
    if isinstance(record, dict):
        for k, v in record.items():  # a top-level money key has no mapping to carry a label
            if MONEY_KEY_RX.search(str(k)):
                out.append(f"`{k}`: an unlabelled USD figure — money lives in `appetite:` or `spend:` with its label")
    return out


# --------------------------------------------------------------------------- #
# one record
# --------------------------------------------------------------------------- #
def _keys(where: str, value, allowed, required=()) -> list[str]:
    if not isinstance(value, dict):
        return [f"`{where}` must be a mapping"]
    out = [f"`{where}.{k}`: unknown key (allowed: {', '.join(allowed)})" for k in value if k not in allowed]
    out += [f"`{where}.{k}` is required" for k in required if value.get(k) in (None, "")]
    return out


def lint_record(record, *, name: str | None = None, fleet: dict | None = None,
                queue_order: list | None = None, now: dt.datetime | None = None) -> tuple[list[str], list[str]]:
    """(errors, warnings) for one `sprint/v1` record. `name` is its file stem, when it has one."""
    fleet = fleet or {}
    now = now or dt.datetime.now(dt.timezone.utc)
    if not isinstance(record, dict):
        return ["a record is a mapping (one sprint per file)"], []
    secrets = secret_findings(record)
    if secrets:
        # Nothing else is checked: every other finding may quote a field, and the
        # field may be the secret. The record is fixed first, then linted again.
        return secrets + ["the other checks wait until the secret is removed (and rotated)"], []
    errors: list[str] = []
    warnings: list[str] = []
    errors += money_findings(record)

    for k in record:
        if k not in TOP_REQUIRED and k not in TOP_OPTIONAL:
            errors.append(f"`{k}`: unknown key (sprint/v1 has {', '.join(TOP_REQUIRED + TOP_OPTIONAL)})")
    for k in TOP_REQUIRED:
        if record.get(k) in (None, ""):
            errors.append(f"`{k}` is required")
    if record.get("schema") not in (None, SCHEMA):
        errors.append(f"`schema` must be `{SCHEMA}`")
    slug = record.get("slug")
    if slug is not None and not (isinstance(slug, str) and SLUG_RX.match(slug)):
        errors.append("`slug` must be lowercase letters, digits and dashes (at most 64)")
    elif name is not None and slug is not None and slug != name:
        errors.append(f"`slug` is `{slug}` but the file is `{name}.yml` — they must agree")
    if record.get("title") is not None and not (isinstance(record["title"], str) and record["title"].strip()):
        errors.append("`title` must be text")
    item = record.get("item")
    if item is not None and not (isinstance(item, str) and REF_RX.match(item)):
        errors.append("`item` must be an issue reference `owner/repo#n`")
    target = record.get("target_repo")
    if target is not None and not (isinstance(target, str) and REPO_RX.match(target)):
        errors.append("`target_repo` must be `owner/repo`")
    if record.get("updated_at") is not None and _when(record["updated_at"]) is None:
        errors.append("`updated_at` must be an ISO 8601 timestamp")

    state = record.get("state")
    if state is not None and state not in STATES:
        errors.append(f"`state` must be one of {', '.join(STATES)}")
    phase = record.get("phase")
    phase_ok = isinstance(phase, int) and not isinstance(phase, bool) and 0 <= phase < len(PHASES)
    if phase is not None and not phase_ok:
        errors.append(f"`phase` must be 0–{len(PHASES) - 1} ({', '.join(f'{i} {p}' for i, p in enumerate(PHASES))})")

    # appetite and spend: the ceiling, and the spend against it
    appetite = record.get("appetite")
    hours = cap = None
    if appetite is not None:
        errors += _keys("appetite", appetite, APPETITE_KEYS, ("hours", "usd", "label"))
        if isinstance(appetite, dict):
            hours = _num(appetite.get("hours"))
            if appetite.get("hours") is not None and (hours is None or hours <= 0):
                errors.append("`appetite.hours` must be a number > 0")
            if appetite.get("ends_at") is not None and _when(appetite["ends_at"]) is None:
                errors.append("`appetite.ends_at` must be an ISO 8601 timestamp")
    spend = record.get("spend")
    if spend is not None:
        errors += _keys("spend", spend, SPEND_KEYS, ("usd", "cap_usd", "label"))
        if isinstance(spend, dict):
            cap = _num(spend.get("cap_usd"))
            if spend.get("updated_at") is not None and _when(spend["updated_at"]) is None:
                errors.append("`spend.updated_at` must be an ISO 8601 timestamp")
    if isinstance(appetite, dict) and cap is not None:
        want = _num(appetite.get("usd"))
        if want is not None and abs(want - cap) > 1e-9:
            errors.append(f"`spend.cap_usd` ({cap:g}) must equal `appetite.usd` ({want:g}): the appetite is the ceiling")
    ceilings = ((fleet.get("budget") or {}).get("sprints") or {}) if isinstance(fleet.get("budget"), dict) else {}
    budget = ceilings.get(slug) if isinstance(ceilings, dict) and isinstance(slug, str) else None
    if isinstance(budget, dict):
        declared = _num(budget.get("usd", budget.get("cap_usd")))
        if declared is not None and cap is not None and abs(declared - cap) > 1e-9:
            errors.append(f"`spend.cap_usd` ({cap:g}) differs from `_data/fleet.yml` budget.sprints.{slug} ({declared:g})")
        if _num(budget.get("hours")) is not None and hours is not None and abs(_num(budget["hours"]) - hours) > 1e-9:
            errors.append(f"`appetite.hours` ({hours:g}) differs from `_data/fleet.yml` budget.sprints.{slug}.hours")
        declared_item = budget.get("item")
        if isinstance(declared_item, str) and isinstance(item, str) and declared_item not in (item, f"issue:{item}"):
            errors.append(f"`item` is `{item}` but `_data/fleet.yml` budget.sprints.{slug}.item is `{declared_item}`")
        ends, declared_ends = _when((appetite or {}).get("ends_at") if isinstance(appetite, dict) else None), _when(budget.get("ends"))
        if ends is not None and declared_ends is not None and ends != declared_ends:
            errors.append(f"`appetite.ends_at` ({_iso(ends)}) differs from `_data/fleet.yml` "
                          f"budget.sprints.{slug}.ends ({_iso(declared_ends)})")
    elif isinstance(ceilings, dict) and ceilings and state == "active":
        warnings.append(f"`_data/fleet.yml` budget.sprints declares no ceiling for `{slug}`")

    # the gates: Amr's, in order, each with its evidence
    gates = record.get("gates")
    passed: dict[str, bool] = {}
    if gates is not None:
        if not isinstance(gates, dict):
            errors.append("`gates` must be a mapping of declaration, spec and merge")
        else:
            for k in gates:
                if k not in GATES:
                    errors.append(f"`gates.{k}`: unknown gate (the gates are {', '.join(GATES)})")
            who = maintainer(fleet)
            for g in GATES:
                if g not in gates:
                    errors.append(f"`gates.{g}` is missing — write `{g}: null` until it passes")
                    continue
                gate = gates[g]
                if gate is None:
                    passed[g] = False
                    continue
                errors += _keys(f"gates.{g}", gate, GATE_KEYS, GATE_KEYS)
                if isinstance(gate, dict):
                    if gate.get("at") is not None and _when(gate["at"]) is None:
                        errors.append(f"`gates.{g}.at` must be an ISO 8601 timestamp")
                    by = str(gate.get("by") or "")
                    if by and by.lower() != who.lower():
                        errors.append(f"`gates.{g}.by` is `{by}`: every gate is passed by `{who}` alone (§ 27.2) — "
                                      "an agent never declares, approves or merges its own sprint")
                passed[g] = gate_passed(gate)
            for i, g in enumerate(GATES[1:], start=1):
                prev = GATES[i - 1]
                if passed.get(g) and not passed.get(prev):
                    errors.append(f"the {g} gate passed before the {prev} gate (§ 27.2: declaration → spec → merge)")
                elif passed.get(g) and passed.get(prev):
                    at, before = _when(gates[g]["at"]), _when(gates[prev]["at"])
                    if at and before and at < before:
                        errors.append(f"the {g} gate is dated {_iso(at)}, before the {prev} gate ({_iso(before)})")
            if phase_ok:
                for g in GATES:
                    if phase >= GATE_OPENS[g] and not passed.get(g):
                        errors.append(f"phase {phase} ({PHASES[phase]}) needs the {g} gate — "
                                      f"{PHASES[GATE_OPENS[g]]} starts only after it passes")

    # the lifecycle
    stop = record.get("stop")
    retro = record.get("retro")
    if state == "proposed":
        if passed.get("declaration"):
            errors.append("a declared sprint is `active` (or ended), not `proposed`")
        if phase_ok and phase != 0:
            errors.append("a proposed sprint is in phase 0 (intake)")
    if state in ("active", "stopped", "demoted", "done") and gates is not None and not passed.get("declaration"):
        errors.append(f"a sprint in state `{state}` needs the declaration gate (Amr commits it to _data/work_queue.yml `order:`)")
    if state in ("proposed", "active") and stop is not None:
        errors.append(f"a sprint in state `{state}` has no `stop:` record — the stop ends it")
    if state in ("stopped", "demoted") and stop is None:
        errors.append(f"a sprint in state `{state}` records its stop (`stop: {{at, reason}}`)")
    if state == "demoted" and isinstance(stop, dict) and stop.get("reason") != "demoted":
        errors.append("a demoted sprint's stop reason is `demoted`")
    if state == "done":
        if not passed.get("merge"):
            errors.append("a `done` sprint needs the merge gate (§ 27.2 c)")
        if phase_ok and phase != len(PHASES) - 1:
            errors.append(f"a `done` sprint ends in phase {len(PHASES) - 1} (retro)")
        if not (isinstance(retro, dict) and retro.get("lessons")):
            errors.append("a `done` sprint ends with a retro: `retro.lessons` (§ 27.8)")
    if state == "active" and cap is not None and isinstance(spend, dict):
        used = _num(spend.get("usd"))
        if used is not None and used >= cap:
            errors.append(f"spend {used:g} has reached the cap {cap:g} ({COST_LABEL}) while `active`: the circuit "
                          "breaker stops it — record `stop:` with reason `cap` and set `state: stopped` (§ 27.3)")
    if state == "active" and isinstance(appetite, dict):
        ends = _when(appetite.get("ends_at"))
        if ends is not None and ends < now:
            warnings.append(f"the time box ended {_iso(ends)}: the circuit breaker stops the sprint — record `stop:` "
                            "with reason `time-box` (no automatic extension, § 27.3)")
    if state == "active" and queue_order is not None and isinstance(item, str):
        if f"issue:{item}" not in queue_order:
            errors.append(f"`issue:{item}` is not in _data/work_queue.yml `order:` — the declaration is Amr "
                          "committing the item there (§ 27.2 a)")

    if stop is not None:
        errors += _keys("stop", stop, STOP_KEYS, ("at", "reason"))
        if isinstance(stop, dict):
            if stop.get("reason") is not None and stop["reason"] not in STOP_REASONS:
                errors.append(f"`stop.reason` must be one of {', '.join(STOP_REASONS)}")
            if stop.get("at") is not None and _when(stop["at"]) is None:
                errors.append("`stop.at` must be an ISO 8601 timestamp")
            errors += _refs("stop.filed", stop.get("filed"))
    if retro is not None:
        errors += _keys("retro", retro, RETRO_KEYS)
        if isinstance(retro, dict):
            lessons = retro.get("lessons")
            if lessons is not None and not (isinstance(lessons, list) and all(isinstance(x, str) and x.strip() for x in lessons)):
                errors.append("`retro.lessons` must be a list of text")
            errors += _refs("retro.debt", retro.get("debt"))

    items = record.get("items")
    if items is not None:
        if not isinstance(items, list):
            errors.append("`items` must be a list")
        else:
            for i, it in enumerate(items):
                where = f"items[{i}]"
                errors += _keys(where, it, ITEM_KEYS, ("ref", "kind"))
                if not isinstance(it, dict):
                    continue
                if it.get("ref") is not None and not (isinstance(it["ref"], str) and REF_RX.match(it["ref"])):
                    errors.append(f"`{where}.ref` must be `owner/repo#n`")
                kind = it.get("kind")
                if kind is not None and kind not in ITEM_STATES:
                    errors.append(f"`{where}.kind` must be one of {', '.join(ITEM_STATES)}")
                elif kind and it.get("state") is not None and it["state"] not in ITEM_STATES[kind]:
                    errors.append(f"`{where}.state` of an {kind} must be one of {', '.join(ITEM_STATES[kind])}")
                p = it.get("phase")
                if p is not None and not (isinstance(p, int) and not isinstance(p, bool) and 0 <= p < len(PHASES)):
                    errors.append(f"`{where}.phase` must be 0–{len(PHASES) - 1}")

    wires = record.get("trip_wires")
    if wires is not None:
        if not isinstance(wires, list):
            errors.append("`trip_wires` must be a list")
        else:
            seen: set[str] = set()
            for i, w in enumerate(wires):
                where = f"trip_wires[{i}]"
                errors += _keys(where, w, TRIP_KEYS, ("id", "rule", "state"))
                if not isinstance(w, dict):
                    continue
                wid = w.get("id")
                if isinstance(wid, str) and wid in seen:
                    errors.append(f"`{where}.id` `{wid}` is listed twice")
                seen.add(str(wid))
                if w.get("state") is not None and w["state"] not in TRIP_STATES:
                    errors.append(f"`{where}.state` must be one of {', '.join(TRIP_STATES)}")
                if w.get("state") == "tripped" and _when(w.get("at")) is None:
                    errors.append(f"`{where}`: a tripped wire records when (`at`)")

    dora = record.get("dora")
    if dora is not None and not isinstance(dora, dict):
        errors.append("`dora` is a mapping (the snapshot of #690's projection) or null until it lands")
    return errors, warnings


def _refs(where: str, value) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        return [f"`{where}` must be a list of `owner/repo#n`"]
    return [f"`{where}[{i}]` must be `owner/repo#n`" for i, v in enumerate(value)
            if not (isinstance(v, str) and REF_RX.match(v))]


# --------------------------------------------------------------------------- #
# every record
# --------------------------------------------------------------------------- #
def _load_yaml(path: Path):
    if not path.is_file():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(HUB))
    except ValueError:
        return path.name


def lint_dir(directory: Path = SPRINTS_DIR, fleet_path: Path = FLEET, queue_path: Path = WORK_QUEUE,
             now: dt.datetime | None = None) -> dict:
    """Every record in `directory`, linted alone and together (WIP 1)."""
    fleet = _load_yaml(fleet_path) or {}
    queue = _load_yaml(queue_path) or {}
    order = [str(k) for k in (queue.get("order") or [])] if isinstance(queue, dict) else []
    records = []
    errors: list[str] = []
    warnings: list[str] = []
    paths = sorted(directory.glob("*.yml")) if directory.is_dir() else []
    for path in paths:
        name = path.stem
        try:
            record = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            where = f" (line {mark.line + 1})" if mark is not None else ""
            errs, warns, record = [f"not valid YAML{where}"], [], None
        else:
            errs, warns = lint_record(record, name=name, fleet=fleet, queue_order=order, now=now)
        records.append({"path": path, "name": name, "record": record, "errors": errs, "warnings": warns})
        errors += [f"{name}: {e}" for e in errs]
        warnings += [f"{name}: {w}" for w in warns]
    active = [r["name"] for r in records if isinstance(r["record"], dict) and r["record"].get("state") == "active"]
    if len(active) > 1:
        errors.append(f"{len(active)} active expedite sprints ({', '.join(active)}): at most one is active "
                      "fleet-wide (WIP 1, § 27.1) — end or demote one first")
    return {"records": records, "active": active, "errors": errors, "warnings": warnings,
            "maintainer": maintainer(fleet), "dir": directory}


def document(directory: Path = SPRINTS_DIR, fleet_path: Path = FLEET, queue_path: Path = WORK_QUEUE,
             now: dt.datetime | None = None) -> dict:
    """The /api/sprints document: every record as JSON, with the lint's findings beside it.

    A record that failed the secret check is withheld whole — the console and the
    public snapshot both serve this document, so nothing credential-shaped leaves it.
    """
    res = lint_dir(directory, fleet_path, queue_path, now)
    sprints = []
    for r in res["records"]:
        rec = r["record"]
        withheld = not isinstance(rec, dict) or bool(secret_findings(rec))
        base = {"path": _rel(r["path"]), "findings": r["errors"], "warnings": r["warnings"], "withheld": withheld}
        if withheld:
            sprints.append({"slug": r["name"], "title": r["name"], **base})
            continue
        doc = plain(rec)
        phase = doc.get("phase")
        gates = doc.get("gates") if isinstance(doc.get("gates"), dict) else {}
        spend = doc.get("spend") if isinstance(doc.get("spend"), dict) else {}
        used, cap = _num(spend.get("usd")), _num(spend.get("cap_usd"))
        doc.update(base)
        doc["phase_name"] = PHASES[phase] if isinstance(phase, int) and 0 <= phase < len(PHASES) else None
        doc["gates_passed"] = sum(1 for g in GATES if gate_passed(gates.get(g)))
        doc["spend_ratio"] = (used / cap) if used is not None and cap else None
        sprints.append(doc)

    def order(s: dict):
        rank = {"active": 0, "proposed": 1}.get(str(s.get("state")), 2)
        declared = ((s.get("gates") or {}).get("declaration") or {}) if isinstance(s.get("gates"), dict) else {}
        at = _when(declared.get("at") if isinstance(declared, dict) else None)
        return (rank, -(at.timestamp() if at else 0.0), str(s.get("slug")))

    sprints.sort(key=order)
    return {
        "schema": DOC_SCHEMA,
        "generated_at": _iso(now or dt.datetime.now(dt.timezone.utc)),
        "dir": _rel(res["dir"]),
        "standard": STANDARD,
        "cost_label": COST_LABEL,
        "maintainer": res["maintainer"],
        "phases": list(PHASES),
        "gates": list(GATES),
        "active": res["active"][0] if len(res["active"]) == 1 else None,
        "count": len(sprints),
        "sprints": sprints,
        "errors": res["errors"],
        "warnings": res["warnings"],
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Lint and show the live expedite-sprint records (sprint/v1).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, text in (("lint", "hold every record to the standard (drift check (r))"),
                       ("show", "print the /api/sprints document as JSON")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--dir", type=Path, default=SPRINTS_DIR, help="the records (default: _data/sprints)")
        p.add_argument("--fleet", type=Path, default=FLEET, help="_data/fleet.yml (budget.sprints, hub.repo)")
        p.add_argument("--queue", type=Path, default=WORK_QUEUE, help="_data/work_queue.yml (the declaration)")
        if name == "lint":
            p.add_argument("--json", action="store_true", help="print the findings as JSON")
    args = ap.parse_args(argv)
    if args.cmd == "show":
        print(json.dumps(document(args.dir, args.fleet, args.queue), indent=2))
        return 0
    res = lint_dir(args.dir, args.fleet, args.queue)
    if args.json:
        print(json.dumps({"records": [r["name"] for r in res["records"]], "active": res["active"],
                          "errors": res["errors"], "warnings": res["warnings"]}, indent=2))
        return 1 if res["errors"] else 0
    for e in res["errors"]:
        print(f"  ✗ {e}")
    for w in res["warnings"]:
        print(f"  ! {w}")
    n, act = len(res["records"]), len(res["active"])
    verdict = f"{len(res['errors'])} error(s)" if res["errors"] else "clean"
    print(f"sprint records: {n} record(s), {act} active (WIP 1) — {verdict}")
    return 1 if res["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
