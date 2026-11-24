#!/usr/bin/env python3
"""
File: tools/jev/loop_publish.py
Description: The loop runner's publishing (tools/jev/loop.py; #486, ADR 0002
             P1; § 13.6): the publish token and its probe (`gh api user`, a
             read, before anything spends or files), the dry-run preview
             (`preview`: the spec's publish argv without its apply flag, the
             exact bodies, publish-plan.json and publish-plan.md), what a
             live dry run must match before a filing (`review_gap`), and the
             filing itself (`apply_item`: refused when already applied or
             changed since the preview, the live recheck, publish-result.json
             claimed with O_EXCL, then the write with GH_TOKEN in that
             subprocess only). Moved here from loop.py unchanged but for two
             qualifications in `apply_item`: `_fresh_dry` and `dash_gen` are
             seams tests replace, so they stay in loop.py and the filing
             reaches them as `engine._fresh_dry` and `engine.dash_gen`.
             loop.py re-exports every name.
Author: bamr87
Created: 2026-11-22
Version: 0.1.0
Usage: imported by tools/jev/loop.py. Callers outside the engine import these
       names from tools.jev.loop (tools/voices.py: `probe_publish_token`).
Dependencies: Python 3.12 stdlib; gh for the token probe; the filer only as
              the spec's `tools/dash-gen` publish argv, through the engine.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from . import headless
from . import workspace as wsp
from .adapters import Item, PublishPlan, Verdict
from .common import HUB, JevError, dotenv_values, gh
from .loop_common import EXIT, _sha, deterministic_env, iso, read_json, write_json
from .loop_runs import RunDir
from .spec import PUBLISH_REVIEWED_FLAGS, StepSpec, render_argv

if TYPE_CHECKING:   # annotations only: the engine imports this module, never the reverse
    from .loop import RunContext

PUBLISH_PLAN_SCHEMA = "jev-loop-publish-plan/v1"
PUBLISH_RESULT_SCHEMA = "jev-loop-publish-result/v1"


def publish_tier(spec: StepSpec) -> str | None:
    pub = spec.local.publish if spec.local else None
    if pub is None or not spec.risk:
        return None
    return str((spec.risk.get(pub.risk) or {}).get("tier"))


# --------------------------------------------------------------------------- #
# the publish token
# --------------------------------------------------------------------------- #
def publish_token() -> tuple[str | None, str]:
    """The token a filing runs with: FLEET_TOKEN from the environment, then from
    the hub .env (that one name only, never sourced), else the ambient gh
    login. Value and source; the value is never printed or recorded."""
    if os.environ.get("FLEET_TOKEN"):
        return os.environ["FLEET_TOKEN"], "env FLEET_TOKEN"
    dotenv = dotenv_values(("FLEET_TOKEN",), Path(os.environ.get("JEV_DOTENV") or HUB / ".env"))
    if dotenv.get("FLEET_TOKEN"):
        return dotenv["FLEET_TOKEN"], ".env FLEET_TOKEN"
    return None, "the ambient gh login"


def publish_env(token: str | None) -> dict[str, str]:
    """The filer's environment for an applied write: the deterministic one,
    plus GH_TOKEN in this subprocess only when a FLEET_TOKEN was chosen."""
    env = deterministic_env()
    if token:
        env["GH_TOKEN"] = token
    return env


def probe_publish_token() -> tuple[dict[str, str] | None, str]:
    """Probe the publish token with `gh api user` (a read) BEFORE anything
    spends or files — a token's presence proves nothing (AGENTS.md). Returns
    the apply environment and who it is, or None and why."""
    token, source = publish_token()
    res = gh(["api", "user", "--jq", ".login"], env={"GH_TOKEN": token} if token else None, timeout=60)
    login = res.out.strip()
    if not res.ok or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}(\[bot\])?", login):
        said = headless.Redactor(os.environ, {"FLEET_TOKEN": token or ""}).text((res.err or res.out).strip())[-200:]
        return None, f"the publish token ({source}) was refused by `gh api user`: {said or f'exit {res.code}'}"
    return publish_env(token), f"{login} ({source})"


# --------------------------------------------------------------------------- #
# an item's argv tokens and the hashes a preview is held to
# --------------------------------------------------------------------------- #
def item_values(ctx: RunContext, item: Item, *, validated: Path | str | None = None,
                apply: bool = False) -> dict[str, str]:
    """The argv tokens for one item. `{validated}` is the adapter's
    `Verdict.publish_file` (the engine never names an output file), so a
    publish without a verdict leaves it unfilled and render_argv refuses it."""
    out = {"plan_dir": str(ctx.plan_dir), "nwo": item.nwo, "name": item.name, "branch": item.branch,
           "item_dir": str(ctx.item_dir(item)), "bodies_dir": str(ctx.bodies_dir(item, apply=apply)),
           "run_ref": ctx.run_ref()}
    if validated is not None:
        out["validated"] = str(validated)
    return out


def _file_sha(p: Path) -> str | None:
    try:
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()
    except OSError:
        return None


def _bodies(d: Path) -> dict[str, str]:
    """name → sha256 of every body file a publish phase wrote in `d`."""
    return {p.name: _file_sha(p) or "" for p in sorted(d.glob("*.md"))} if d.is_dir() else {}


# --------------------------------------------------------------------------- #
# publishing: the dry-run preview, then (with --apply) the filing
# --------------------------------------------------------------------------- #
def publish_phase(ctx: RunContext, item: Item, verdict: Verdict, report: dict, row: dict) -> dict:
    """The preview always; the filing only with --apply (the maintainer's
    § 13.6 yes, typed on this command line) and only when the preview is
    publishable."""
    if ctx.spec.local.publish is None:
        report.update(status="validated")
        return report
    doc = preview(ctx, item, verdict)
    report.update(status="previewed", plan_id=doc["plan_id"], publishable=doc["publishable"],
                  would_file=len(doc["rows"]), reason=report.get("reason") or "; ".join(doc["blockers"]) or
                  ("nothing to file" if not doc["rows"] else f"{len(doc['rows'])} issue(s) previewed"))
    ctx.run.append_attempt({**row, "decision": "publish-preview", "plan_id": doc["plan_id"],
                            "publishable": doc["publishable"], "would_file": len(doc["rows"]), "cost_usd": 0.0,
                            "cost_source": "no-spend"})
    if not ctx.opts.apply:
        return report
    if not doc["publishable"]:
        report["reason"] = f"--apply: nothing filed — {report['reason']}"
        return report
    result = apply_item(ctx, item, doc)
    report.update(status=result["status"], reason=result["reason"], code=result["code"],
                  published=result.get("published", 0), urls=result.get("urls", []))
    return report


def publish_values(ctx: RunContext, item: Item, validated: Path, *, apply: bool,
                   bodies_dir: Path | None = None, reviewed: Path | None = None) -> list[str]:
    """The publish argv; with `apply`, the filer's apply flag and its reviewed
    flag naming `reviewed` (the preview's bodies), so the filing itself files
    no byte nobody reviewed and nothing it cannot dedupe."""
    pub = ctx.spec.local.publish
    values = item_values(ctx, item, validated=validated, apply=apply)
    if bodies_dir is not None:
        values["bodies_dir"] = str(bodies_dir)
    argv = render_argv(pub.argv, values)
    if not apply:
        return argv
    if reviewed is None:
        raise JevError("internal: an apply argv without the reviewed bodies")
    return [*argv, pub.apply_flag, PUBLISH_REVIEWED_FLAGS[argv[0]], str(reviewed)]


def preview(ctx: RunContext, item: Item, verdict: Verdict) -> dict:
    """The spec's publish argv WITHOUT its apply flag (a live dedupe read with
    the user's gh auth), into `items/<dir>/bodies/`: the exact bytes --apply
    would file, written down as publish-plan.json and publish-plan.md."""
    d = ctx.item_dir(item)
    argv = publish_values(ctx, item, verdict.publish_file, apply=False)
    plan = ctx.adapter.publish(ctx, item, verdict, lambda: ctx.dash_gen(argv))
    bodies = _bodies(ctx.bodies_dir(item, apply=False))
    vsha = _file_sha(verdict.publish_file)
    plan_id = _sha(json.dumps({"nwo": item.nwo, "validated_sha256": vsha, "argv": argv, "bodies": bodies},
                              sort_keys=True))[:16]
    labels = sorted({lab for r in plan.rows for lab in (r.get("labels") or [])})
    doc = {"schema": PUBLISH_PLAN_SCHEMA, "run_id": ctx.run.run_id, "plan_id": plan_id,
           "item": {"key": item.key, "name": item.name, "nwo": item.nwo, "branch": item.branch},
           "risk": ctx.spec.local.publish.risk, "tier": publish_tier(ctx.spec),
           "validated_rel": str(verdict.publish_file.relative_to(d)), "validated_sha256": vsha,
           "argv": argv, "apply_flag": ctx.spec.local.publish.apply_flag, "bodies": bodies,
           "rows": plan.rows, "blockers": plan.blockers, "failures": plan.failures,
           "publishable": plan.publishable and bool(bodies), "labels": labels,
           "apply_steps": ctx.adapter.apply_steps(ctx, item, plan),
           "flags": verdict.flags, "facts": verdict.facts, "created": iso()}
    write_json(d / "publish-plan.json", doc)
    (d / "publish-plan.md").write_text(_plan_md(doc, ctx.bodies_dir(item, apply=False)), encoding="utf-8")
    return doc


def _plan_md(doc: dict, bodies_dir: Path) -> str:
    item = doc["item"]
    lines = [f"# Publish plan {doc['plan_id']} — {item['nwo']}", "",
             f"- run: `{doc['run_id']}` · item `{item['key']}` · risk `{doc['risk']}` (tier {doc['tier']})",
             f"- validated file: `{doc['validated_rel']}` (sha256 {doc['validated_sha256']})",
             f"- publishable: {'yes' if doc['publishable'] else 'no'}"
             + (f" — blockers: {', '.join(doc['blockers'])}" if doc["blockers"] else ""), "",
             "## What `--apply` does", ""]
    steps = doc.get("apply_steps")
    if isinstance(steps, list) and steps:
        lines += [f"{n}. {step}" for n, step in enumerate(steps, 1)]
    elif doc["labels"]:
        lines.append(f"1. `gh label create <name> -R {item['nwo']} --force` for {', '.join(doc['labels'])} — this "
                     "can refresh an existing label's colour and description.")
        lines.append(f"2. `gh issue create -R {item['nwo']}` once per body below, after a live recheck "
                     "(backpressure, the open-issue dedupe, the token probe); nothing else is written.")
    else:
        lines.append("Nothing: no proposal would be filed.")
    for f in doc["flags"]:
        lines.append(f"- flag: {f}")
    lines += ["", f"Publish this preview later: `tools/dash loop publish {doc['run_id']} --item {item['key']} "
              "--apply`", ""]
    for r in doc["rows"]:
        name = r.get("body_file") or ""
        body = (bodies_dir / name).read_text(encoding="utf-8") if name and (bodies_dir / name).is_file() else ""
        lines += [f"## {r.get('title')}", "", f"labels: {', '.join(r.get('labels') or [])} · body `{name}`", "",
                  "~~~~markdown", body.rstrip("\n"), "~~~~", ""]
    return "\n".join(lines) + "\n"


def review_gap(ctx: RunContext, item: Item, doc: dict, fresh: PublishPlan, fresh_bodies: dict[str, str],
               validated: Path) -> str | None:
    """Why a live dry run would NOT file exactly what the preview showed, or
    None: a body whose hash is not among the reviewed ones, a title or label
    set nobody reviewed (labels come from `_data/fleet.yml` at filing time), a
    publish argv that is not the reviewed one, or bodies that cannot be
    compared. A live dedupe that only drops a reviewed issue is no gap."""
    unreviewed = sorted(n for n, s in fresh_bodies.items() if s not in set(doc["bodies"].values()))
    if unreviewed:
        return (f"a live dry run would file {len(unreviewed)} body(ies) that were not in the reviewed preview — run "
                "again and review the new preview")
    if fresh.rows and len(fresh_bodies) != len(fresh.rows):
        return (f"the live dry run wrote {len(fresh_bodies)} body file(s) for {len(fresh.rows)} issue(s), so the "
                "bytes cannot be compared")
    reviewed = {(r.get("title"), tuple(r.get("labels") or [])) for r in doc.get("rows") or []}
    moved = [str(r.get("title")) for r in fresh.rows if (r.get("title"), tuple(r.get("labels") or [])) not in reviewed]
    if moved:
        return f"a live dry run would file {moved[:3]} under a title or labels that were not reviewed"
    if publish_values(ctx, item, validated, apply=False) != doc.get("argv"):
        return "the publish argv is not the reviewed one (the spec or the run changed since the preview)"
    return None


#: The way on from an apply that filed nothing: its publish-result.json still
#: refuses a second apply of that preview, but it is not a publish, so tier 0
#: reuses the validated copy in a new run and previews it again.
NOTHING_FILED_RETRY = ("nothing was filed: run the loop again to retry (tier 0 reuses the validated copy at $0 "
                       "while HEAD and the brief are unchanged, and writes a new preview to apply)")


def _already_applied(result_path: Path) -> str:
    """Why a claimed publish-result.json refuses this apply — with the way on
    when the earlier apply filed nothing."""
    try:
        prior = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        prior = None
    if isinstance(prior, dict) and prior.get("status") == "publish-failed" and not prior.get("urls"):
        return f"already applied ({result_path.name} exists) and {NOTHING_FILED_RETRY}"
    return f"already applied ({result_path.name} exists) — a second apply is refused"


def apply_item(ctx: RunContext, item: Item, doc: dict) -> dict:
    """File a preview's bytes. Refused (exit 2) when it was already applied
    (here, or in another run that filed the same validated bytes), when the
    validated file or the reviewed bodies changed since the preview, or when a
    live dry run would now file anything that was not reviewed (`review_gap`); then
    the live recheck (the planner for this one target: issues enabled,
    backpressure); then the write, with GH_TOKEN in that subprocess only;
    then per-issue failure detection. publish-result.json is claimed with
    O_EXCL before the write, so a second or concurrent apply is refused."""
    from . import loop as engine   # lazily: loop imports this module, and holds the seams tests replace
    d = ctx.item_dir(item)
    result_path = d / "publish-result.json"

    def refused(why: str) -> dict:
        return {"status": "publish-refused", "reason": why, "code": EXIT["usage"]}

    if ctx.publish_env is None:
        return refused("no probed publish token (internal: --apply without the token probe)")
    if result_path.exists():
        return refused(_already_applied(result_path))
    elsewhere = ctx.history.published_run(ctx.spec, item.key, str(doc.get("validated_sha256")))
    if elsewhere:
        return refused(f"already published in run {elsewhere} (the same validated bytes) — a second apply is refused")
    if not doc.get("publishable"):
        return refused("the preview is not publishable: " + ("; ".join(doc.get("blockers") or []) or "nothing to file"))
    validated = d / doc["validated_rel"]
    if validated.is_symlink() or _file_sha(validated) != doc["validated_sha256"]:
        return refused("the validated file changed since the preview")
    if _bodies(ctx.bodies_dir(item, apply=False)) != doc["bodies"]:
        return refused("the reviewed bodies changed since the preview")
    why = ctx.adapter.recheck(ctx, item)
    if why:
        return {"status": "publish-skipped", "reason": f"live recheck: {why}", "code": EXIT["attention"]}
    verdict = Verdict(True, publish_file=validated)
    fresh, fresh_bodies = engine._fresh_dry(ctx, item, validated)
    if fresh.blockers:
        return {"status": "publish-skipped", "reason": f"live recheck: {', '.join(fresh.blockers)}",
                "code": EXIT["attention"]}
    gap = review_gap(ctx, item, doc, fresh, fresh_bodies, validated)
    if gap:
        return refused(f"changed since the preview: {gap}")
    if not fresh.rows:
        return {"status": "publish-skipped", "reason": "nothing left to file after the live dedupe", "code": EXIT["ok"]}
    try:
        fd = os.open(result_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return refused("already applied (a concurrent apply claimed it)")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"schema": PUBLISH_RESULT_SCHEMA, "status": "applying", "plan_id": doc["plan_id"], "at": iso()}, fh)
    apply_argv = publish_values(ctx, item, validated, apply=True, reviewed=ctx.bodies_dir(item, apply=False))
    env = ctx.publish_env
    filed = ctx.adapter.publish(ctx, item, verdict, lambda: engine.dash_gen(apply_argv, env=env), apply=True)
    urls = [r["url"] for r in filed.rows if r.get("url")]
    stray = sorted(n for n, s in _bodies(ctx.bodies_dir(item, apply=True)).items()
                   if s not in set(doc["bodies"].values()))
    status = ("published" if urls and not filed.failures and not filed.blockers
              else "partial" if urls else "publish-failed")
    reason = (f"filed {len(urls)} issue(s)" + (f"; FAILED: {', '.join(filed.failures)}" if filed.failures else "")
              + (f"; {', '.join(filed.blockers)}" if filed.blockers else "")
              + (f"; filed bodies not in the preview: {stray}" if stray else "")
              + (f"; {NOTHING_FILED_RETRY}" if status == "publish-failed" else ""))
    write_json(result_path, {"schema": PUBLISH_RESULT_SCHEMA, "status": status, "plan_id": doc["plan_id"],
                             "validated_sha256": doc["validated_sha256"], "urls": urls, "failures": filed.failures,
                             "blockers": filed.blockers, "stray_bodies": stray, "at": iso()})
    ctx.run.append_attempt({"run_id": ctx.run.run_id, "loop": ctx.spec.loop, "step": ctx.spec.step,
                            "call_site": ctx.spec.call_site, "item": item.key, "dir": wsp.item_dirname(item.key),
                            "nwo": item.nwo, "decision": "publish-apply", "plan_id": doc["plan_id"],
                            "validated_sha256": doc["validated_sha256"], "published": bool(urls),
                            "filed": len(urls), "failures": filed.failures, "status": status,
                            "cost_usd": 0.0, "cost_source": "no-spend"})
    return {"status": status, "reason": reason, "code": EXIT["ok"] if status == "published" else EXIT["attention"],
            "published": len(urls), "urls": urls}


def apply_refusal(spec: StepSpec) -> str | None:
    """Why `--apply` cannot run for this step at all — its filer takes the flag
    only to refuse it (bamr87/bamr87#488's publish step is not built) — or
    None. Checked before any clone, any spend and any token probe, so a run
    that could never file never pays for an attempt."""
    pub = spec.local.publish
    if pub is None:
        return f"{spec.loop}/{spec.step} declares no publish step: nothing to apply"
    if pub.can_apply:
        return None
    return (f"--apply is refused for {spec.loop}/{spec.step}: its filer `{pub.argv[0]}` cannot file yet "
            "(bamr87/bamr87#488's publish step) — run the dry run without --apply (`python3 -m tools.jev loop run "
            f"{spec.loop} {spec.step} --target <item>`) and review .fleet/runs/<run_id>/")


# --------------------------------------------------------------------------- #
# `loop publish`: the preview a run left
# --------------------------------------------------------------------------- #
def _publish_target(rd: RunDir, record: dict, key: str | None) -> tuple[dict | None, Item | None, str]:
    """The preview to publish, and its item rebuilt from the run's own plan."""
    plans: dict[str, dict] = {}
    for p in sorted((rd.path / "items").glob("*/publish-plan.json")):
        doc = read_json(p)
        if doc.get("schema") == PUBLISH_PLAN_SCHEMA and doc.get("run_id") == rd.run_id:
            plans[str((doc.get("item") or {}).get("key"))] = doc
    if key is None and len(plans) != 1:
        return None, None, (f"run {rd.run_id} has {len(plans)} preview(s)"
                            + (f" — name one with --item ({', '.join(sorted(plans))})" if plans else ""))
    doc = plans.get(key) if key is not None else next(iter(plans.values()))
    if doc is None:
        return None, None, f"run {rd.run_id} has no preview for {key!r} ({', '.join(sorted(plans)) or 'none'})"
    meta = doc["item"]
    rows = [r for r in read_json(rd.path / "plan" / "plan.json").get("include") or [] if r.get("nwo") == meta["nwo"]]
    item = Item(key=meta["key"], name=meta["name"], nwo=meta["nwo"], branch=meta["branch"],
                row=rows[0] if rows else {}, brief=None)
    return doc, item, ""
