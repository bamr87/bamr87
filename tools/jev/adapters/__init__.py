#!/usr/bin/env python3
"""
File: tools/jev/adapters/__init__.py
Description: The loop engine's adapter contract (#486, ADR 0002 P1). An
             adapter maps one loop's deterministic halves — its planner's JSON
             and its filer's JSON — onto the engine's items and verdicts, and
             holds that loop's own decisions (what makes two attempts the same,
             what blocks an item, what a valid output is). The ENGINE owns
             everything security-relevant: the workspace, the argv, the
             environment, the settings, the run record, the gate and running
             the spec-declared publish argv. An adapter can widen none of them.
             A spec names its adapter by a key of REGISTRY, a vetted name →
             module map, so a spec can never cause an arbitrary import.
Author: bamr87
Created: 2026-10-31
Version: 0.1.0
Usage: `adapters.get(spec.local.adapter)` from tools/jev/loop.py.
Dependencies: Python 3.12 stdlib, tools/jev/context.py (ContextRequest). No
              dash-gen import.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ..context import ContextRequest

#: name → module; a module exposes ADAPTER, an Adapter instance. Adding one is a
#: reviewed change here plus `tools/test_jev_adapter_<name>.py` (SCHEMA.md).
REGISTRY: dict[str, str] = {"repo_scout": "tools.jev.adapters.repo_scout"}
#: How long a completed attempt can stand in for a new one at tier 0.
REUSE_DAYS = 7


def get(name: str) -> Adapter:
    if name not in REGISTRY:
        raise KeyError(f"no loop adapter {name!r} (one of {sorted(REGISTRY)})")
    adapter = importlib.import_module(REGISTRY[name]).ADAPTER
    if not isinstance(adapter, Adapter):
        raise TypeError(f"{REGISTRY[name]}.ADAPTER is not an Adapter")
    return adapter


@dataclass
class Item:
    """One unit of agent work: one repo for scout."""

    key: str             # the run-wide id (scout: the nwo); its directory is workspace.item_dirname(key)
    name: str            # the planner's name for it (scout: the registry name)
    nwo: str
    branch: str
    row: dict            # the planner row; carries every spec.inputs key
    brief: Path | None   # the brief file in the run's plan directory


@dataclass
class PlanResult:
    items: list[Item]
    skipped: list[dict] = field(default_factory=list)   # planner-skipped rows (backpressure, …)
    dropped: list[dict] = field(default_factory=list)   # ineligible rows
    meta: dict = field(default_factory=dict)


@dataclass
class Tier0:
    """The $0 decision before any workspace exists."""

    action: Literal["continue", "skip", "reuse"]
    reason: str = ""
    reuse_from: Path | None = None


@dataclass
class Triage:
    blocked: bool = False
    reason: str = ""


@dataclass
class Verdict:
    ok: bool
    problems: list[str] = field(default_factory=list)
    #: shown to the reviewer, never a reason to reject on their own
    flags: list[str] = field(default_factory=list)
    #: the validated copy to publish — never the raw agent output
    publish_file: Path | None = None
    facts: dict = field(default_factory=dict)


@dataclass
class PublishPlan:
    publishable: bool
    blockers: list[str]
    rows: list[dict]
    bodies_dir: Path | None
    failures: list[str] = field(default_factory=list)


class Adapter:
    """Defaults for every hook; a loop overrides what it needs.

    `ctx` is the engine's RunContext (tools/jev/loop.py): it carries the spec,
    the options, the run directory, the history and the two subprocess seams
    (`dash_gen`, `planner`). Hooks read only harvested copies, never the agent's
    workspace, and reach GitHub only through the `execute` the engine hands to
    `publish`.
    """

    name = "base"
    #: hub paths this adapter's behaviour depends on besides tools/jev/ — the
    #: engine records whether they were dirty when a run started
    sources: tuple[str, ...] = ()

    def items(self, ctx, plan: dict) -> PlanResult:
        raise NotImplementedError

    def reuse_key(self, ctx, item: Item, head_sha: str | None) -> str | None:
        """What makes two attempts identical, for tier 0; None = never reuse."""
        return None

    def tier0(self, ctx, item: Item, head_sha: str | None) -> Tier0:
        key = self.reuse_key(ctx, item, head_sha)
        if key is None or ctx.opts.fresh:
            return Tier0("continue")
        prior = ctx.history.completed(ctx.spec, item.key, key, within_days=REUSE_DAYS)
        if prior is None:
            return Tier0("continue")
        if prior["published"]:
            return Tier0("skip", f"unchanged since the attempt of {prior['date']} (same HEAD and brief), $0")
        return Tier0("reuse", f"same HEAD and brief as run {prior['run_id']}: its validated outputs are reused at $0",
                     Path(prior["item_dir"]))

    def classify(self, ctx, item: Item) -> Triage:
        return Triage()

    def validate(self, ctx, item: Item, harvested: dict, outcome) -> Verdict:
        missing = [h.rel for h in harvested.values() if h.dest is None]
        return Verdict(not missing, [f"{m}: missing or refused" for m in missing])

    def publish(self, ctx, item: Item, verdict: Verdict, execute, *, apply: bool = False) -> PublishPlan:
        """Run `execute()` (the spec's publish argv: the dry preview, or with
        `apply` the write) and read its result; `bodies_dir` is
        `ctx.bodies_dir(item, apply=apply)`, the phase's own directory."""
        raise NotImplementedError

    def recheck(self, ctx, item: Item) -> str | None:
        """Live state re-read just before an applied write; a reason cancels it."""
        return None

    def context_request(self, ctx, item: Item) -> ContextRequest | None:
        """What the host-built context pack is for (tools/jev/context.py): the
        repository and its checkout name, plus up to three code-index queries
        a loop derives from its own item. None = no pack for this item (the
        engine then places nothing, whatever the mode). The engine sets the
        window (`days`) from the spec's `local.context`."""
        return ContextRequest(item.nwo, item.name)
