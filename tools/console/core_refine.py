"""
core_refine — the Refine and Assist pages' documents: sections of core's
logic, in their own file.

  ASSIST job view    what an `assist` job did and answered, from the files
                     ai-run wrote (assist_activity, assist_job_fields)
  REFINE documents   /api/refine (the surface check, the fleet sweep, the plans,
                     the library, the evidence trees, the review queue),
                     /api/assist and the assistant's activity

The refine and assist OPERATIONS (their argv builders, the assistant's
configuration and its conversation records) stay in core.py beside the OPS
table that names them.

core.py loads this module at its end and re-exports every name in it, so callers
keep writing `core.<name>`. What core owns (its paths, constants and helpers, the
OPS table, and every name a test or tools/evals.py rebinds) is read here as
`core.<name>` at the moment of the call, never copied, so rebinding one on core
reaches this code as it did when this was a section of core.py. To replace a
name DEFINED here, patch it on this module: this file calls its own names directly.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

if "core" not in sys.modules:  # the order is a rule, not luck: core loads this module at its end
    raise ImportError("core_refine is a section of core: import core, which loads it and re-exports its names")
import core  # noqa: E402
from fleetcore import assistlog  # noqa: E402  (core put tools/ on sys.path)


# --------------------------------------------------------------------------- #
# ASSIST job view — what an `assist` job did and answered (JobManager.tail, the dock)
# --------------------------------------------------------------------------- #
def _argv_value(argv: list[str], flag: str) -> str | None:
    try:
        return argv[argv.index(flag) + 1]
    except (ValueError, IndexError):
        return None


_ACTIVITY_RX = re.compile(r"^  (?P<mark>[▸◂✗]) (?P<rest>.*)$")


def assist_activity(log_path: Path | None) -> list[dict]:
    """What a session did, from the condensed tee ai-run writes to the job's log (tools/jev/headless.py
    `condensed`, already redacted there): each tool call (`▸ name {args}`), each thing it said along the
    way (`◂ text`) and each denial (`✗ denied …`), in order, the newest ASSIST_ACTIVITY_MAX. The dock
    shows it while the session runs; the job page keeps the raw log."""
    if log_path is None:
        return []
    try:
        with log_path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 200_000))
            text = fh.read().decode("utf-8", "replace")
    except OSError:
        return []
    out: list[dict] = []
    for line in text.splitlines():
        m = _ACTIVITY_RX.match(line)
        if not m:
            continue
        mark, rest = m.group("mark"), m.group("rest").strip()
        if mark == "▸":
            name, _, detail = rest.partition(" ")
            out.append({"kind": "tool", "name": name.removeprefix("mcp__fleet__"), "detail": detail[:300]})
        elif mark == "◂":
            out.append({"kind": "said", "name": "", "detail": rest[:300]})
        else:
            out.append({"kind": "denied", "name": "", "detail": rest[:300]})
    return out[-core.ASSIST_ACTIVITY_MAX:]


def assist_job_fields(job: "Job") -> dict:
    """The structured view of an `assist` job: the question, the page context, and once the session
    ended its answer (the CLI's result text), turns, models and cost (API-equivalent (estimate)) from
    the result and outcome files ai-run wrote. Read defensively: a session that died leaves neither."""
    out = {"schema": "assist-job/v1", "question": str((job.params or {}).get("question") or ""),
           "context": str((job.params or {}).get("context") or ""), "answer": None, "turns": None,
           "cost_usd": None, "cost_source": None, "cost_label": core.COST_LABEL, "models": [], "outcome": None,
           "subtype": None, "conversation": str((job.params or {}).get("conversation") or "") or None,
           "page": bool((job.params or {}).get("page")), "activity": assist_activity(job.log_path)}
    result_path = _argv_value(job.argv, "--result-file")
    outcome_path = _argv_value(job.argv, "--outcome-file")
    for label, path in (("result", result_path), ("outcome", outcome_path)):
        if not path:
            continue
        try:
            doc = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict):
            continue
        if label == "result":
            out["answer"] = str(doc.get("result") or "") or None
            out["turns"] = doc.get("num_turns")
            out["subtype"] = doc.get("subtype")
            usage = doc.get("modelUsage")
            if isinstance(usage, dict):
                out["models"] = sorted(str(m) for m in usage)
            if isinstance(doc.get("total_cost_usd"), (int, float)):
                out["cost_usd"] = round(float(doc["total_cost_usd"]), 6)
        else:
            out["outcome"] = doc.get("kind")
            if isinstance(doc.get("cost_usd"), (int, float)):
                out["cost_usd"] = round(float(doc["cost_usd"]), 6)
            out["cost_source"] = doc.get("cost_source")
    return out


# --------------------------------------------------------------------------- #
# REFINE documents — /api/refine, /api/refine/evidence/…, /api/refine/library, /api/assist
# --------------------------------------------------------------------------- #
def _rel(path, base: Path = core.REPO_ROOT) -> str:
    """A path as hub-relative text; an outside one by name only (never a local absolute path in a document)."""
    try:
        return str(Path(path).resolve().relative_to(base.resolve()))
    except (ValueError, OSError):
        return Path(str(path)).name


def _runs_dir() -> Path:
    return Path(os.environ.get("JEV_RUNS_DIR") or core.REPO_ROOT / ".fleet" / "runs")


def _refine_dir() -> Path:
    return Path(os.environ.get("JEV_REFINE_DIR") or core.REPO_ROOT / ".fleet" / "refine")


def _load_json(path: Path):
    """A JSON file's document, or None (missing, unreadable, not JSON)."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _jsonable(obj):
    """dataclasses and Paths in a plan → JSON values."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return _jsonable(dataclasses.asdict(obj))
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, Path):
        return _rel(obj)
    return obj


def refine_surface_hub(fleet: dict) -> dict:
    _R, Sf, _L, _SP = core._jev()
    rep = Sf.check(core.REPO_ROOT, fleet=fleet)
    return {"root": "bamr87/bamr87", **rep.to_dict()}


def refine_fleet_surface(fleet: dict, *, max_age_s: float = 300.0) -> dict:
    """`refine surface fleet` over every checked-out submodule, cached (it reads ~45 trees)."""
    now = time.time()
    if core._REFINE_CACHE["fleet"] is not None and now - core._REFINE_CACHE["fleet_at"] < max_age_s:
        return core._REFINE_CACHE["fleet"]
    R, _Sf, _L, _SP = core._jev()
    try:
        doc = R.fleet_surfaces(fleet=fleet)
    except Exception as exc:  # noqa: BLE001 — a sweep that fails is reported, never raised into the page
        doc = {"schema": "jev-fleet-surface/v1", "repos": [], "totals": {}, "error": f"{type(exc).__name__}: {exc}"}
    core._REFINE_CACHE.update(fleet_at=now, fleet=doc)
    return doc


def refine_plans(fleet: dict, *, budget: bool) -> list[dict]:
    """One k=1 plan per loop with a local agent step, in the configured mode; a loop whose plan fails
    is a row with its error, never a missing page."""
    R, _Sf, _L, _SP = core._jev()
    rows = []
    for st in core.agent_steps():
        loop, step = st["loop"], st["step"]
        try:
            p = R.plan(loop, step=step, k=1, budget=budget, fleet=fleet)
            lib = dict(p["library"])
            lib["root"] = _rel(lib.get("root", ""))
            rows.append({"loop": loop, "step": p["step"], "call_site": p["call_site"], "k": p["k"], "mode": p["mode"],
                         "identity": p["identity"], "cost": p["cost"], "budget": p["budget"] if budget else {"available": False},
                         "tunable": p["tunable"], "hard_rules": p["hard_rules"], "library": lib,
                         "proposer": p["proposer"], "model_backed": p["model_backed"], "steps": p["steps"],
                         "finals": p["finals"], "error": None})
        except Exception as exc:  # noqa: BLE001
            rows.append({"loop": loop, "step": step, "error": f"{type(exc).__name__}: {exc}"[:400]})
    return rows


def refine_library(fleet: dict, *, local: bool) -> dict:
    R, _Sf, L, _SP = core._jev()
    root = L.root(fleet)
    entries = []
    problems: list[str] = []
    try:
        for loop, domain, e in L.all_entries(root):
            entries.append({"loop": loop, "domain": domain, **e.to_dict(),
                            "has_diff": (L.Library(root, loop, domain).entry_dir(e.id) / L.DIFF_FILE).is_file()})
    except Exception as exc:  # noqa: BLE001
        problems.append(f"{type(exc).__name__}: {exc}"[:300])
    uncommitted: list[str] = []
    if local:
        code, out = core.run_quiet(["git", "status", "--porcelain", "--", _rel(root)], timeout=20)
        if code == 0:
            uncommitted = [line[3:].strip() for line in out.splitlines() if line.strip()]
    return {"root": _rel(root), "entries": entries, "count": len(entries), "problems": problems,
            "uncommitted": uncommitted, "schema": L.SCHEMA_ID}


def refine_evidence_list() -> list[dict]:
    """Every evidence tree under .fleet/refine, newest first, by its manifest (never a local path)."""
    base = _refine_dir()
    rows = []
    if not base.is_dir():
        return rows
    for d in sorted((p for p in base.iterdir() if p.is_dir() and core.STAMP_RX.match(p.name)), reverse=True):
        m = _load_json(d / "evidence.json")
        if not isinstance(m, dict):
            continue
        rows.append({"stamp": d.name, "loop": m.get("loop"), "step": m.get("step"), "item": m.get("item"),
                     "domain": m.get("domain"), "stage": m.get("stage"), "k": m.get("k"),
                     "generated_at": m.get("generated_at"), "files": len(m.get("files") or {}),
                     "rollouts": [r.get("label") for r in (m.get("rollouts") or []) if isinstance(r, dict)],
                     "library_entries": m.get("library_entries"), "redacted": m.get("redacted")})
    return rows


def refine_reviews(*, local: bool) -> list[dict]:
    """The review queue: every local loop-run attempt whose dry-run preview (`publish-plan.md`) has not
    been filed — what `loop-run` with run_id + apply would file after a person reads it. From
    .fleet/runs (local only): run.json's items and attempts.jsonl's publish-apply rows."""
    if not local:
        return []
    base = _runs_dir()
    if not base.is_dir():
        return []
    steps = {(s["loop"], s["step"]): s for s in core.agent_steps()}
    published: set[tuple[str, str, str, str]] = set()
    runs: list[tuple[str, dict, list[dict]]] = []
    for d in sorted((p for p in base.iterdir() if p.is_dir() and (p / "run.json").is_file()), reverse=True):
        meta = _load_json(d / "run.json")
        if not isinstance(meta, dict):
            continue
        rows: list[dict] = []
        try:
            for line in (d / "attempts.jsonl").read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if isinstance(r, dict):
                    rows.append(r)
        except OSError:
            pass
        for r in rows:
            if r.get("decision") == "publish-apply" and r.get("published") and r.get("validated_sha256"):
                published.add((str(r.get("loop")), str(r.get("step")), str(r.get("item")), str(r["validated_sha256"])))
        runs.append((d.name, meta, rows))
    out = []
    for run_id, meta, rows in runs:
        loop, step = str(meta.get("loop") or ""), str(meta.get("step") or "")
        for it in meta.get("items") or []:
            if not isinstance(it, dict) or it.get("status") != "previewed" or not it.get("publishable"):
                continue
            key = str(it.get("key") or "")
            attempt = next((r for r in rows if r.get("decision") == "attempt" and r.get("item") == key), {})
            sha = str(attempt.get("validated_sha256") or "")
            if sha and (loop, step, key, sha) in published:
                continue
            item_dir = str(it.get("dir") or "")
            bodies_dir = base / run_id / "items" / item_dir / "bodies"
            bodies = []
            if item_dir and bodies_dir.is_dir():
                for b in sorted(bodies_dir.glob("*.md")):
                    # the filer names each body by its issue title's slug (NN-<slug>.md)
                    title = re.sub(r"^\d+-", "", b.stem).replace("-", " ").strip()
                    bodies.append({"file": b.name, "title": title[:160]})
            st = steps.get((loop, step)) or {}
            out.append({"run_id": run_id, "loop": loop, "step": step, "item": key, "name": it.get("name"),
                        "dir": item_dir, "status": it.get("status"), "reason": it.get("reason"),
                        "would_file": (it.get("facts") or {}).get("would_file") if isinstance(it.get("facts"), dict) else None,
                        "plan_id": it.get("plan_id"), "cost_usd": it.get("cost_usd"), "cost_label": core.COST_LABEL,
                        "finished": meta.get("finished"), "head_sha": attempt.get("head_sha"),
                        "can_apply": bool(st.get("can_apply")), "publish_tier": st.get("publish_tier"),
                        "bodies": bodies, "preview": f"items/{item_dir}/publish-plan.md" if item_dir else None})
    return out


REVIEW_FILE_RX = re.compile(r"^(?:summary\.md|items/[A-Za-z0-9._-]+/(?:publish-plan\.md|bodies/[A-Za-z0-9._-]+\.md))$")
MAX_TEXT_CHARS = 200_000


def refine_review_file(run_id: str, rel: str) -> dict:
    """A reviewed preview's text: the run's summary, an item's publish-plan.md or one body (local only)."""
    if not core.RUN_ID_RX.fullmatch(run_id or ""):
        raise ValueError("run_id is not a run id")
    if not REVIEW_FILE_RX.match(rel or ""):
        raise ValueError("path must be summary.md, items/<dir>/publish-plan.md or items/<dir>/bodies/<name>.md")
    p = _runs_dir() / run_id / rel
    if p.is_symlink() or not p.is_file():
        raise ValueError(f"no {rel} in run {run_id}")
    text = p.read_text(encoding="utf-8", errors="replace")
    return {"run_id": run_id, "path": rel, "text": text[:MAX_TEXT_CHARS], "truncated": len(text) > MAX_TEXT_CHARS}


def refine_evidence_doc(stamp: str) -> dict:
    if not core.STAMP_RX.match(stamp or ""):
        raise ValueError("stamp is not an evidence tree id")
    d = _refine_dir() / stamp
    m = _load_json(d / "evidence.json")
    if not d.is_dir() or not isinstance(m, dict):
        raise ValueError(f"no evidence tree {stamp}")
    files = sorted(m.get("files") or {})
    return {"stamp": stamp, "manifest": {k: v for k, v in m.items() if k != "files"}, "files": files,
            "bytes": {k: (m["files"][k] or {}).get("bytes") for k in files}}


def refine_evidence_file(stamp: str, rel: str) -> dict:
    doc = refine_evidence_doc(stamp)
    if rel not in doc["files"]:
        raise ValueError(f"{rel} is not a file of evidence tree {stamp}")
    p = _refine_dir() / stamp / rel
    if p.is_symlink() or not p.is_file():
        raise ValueError(f"{rel} is gone from evidence tree {stamp}")
    text = p.read_text(encoding="utf-8", errors="replace")
    return {"stamp": stamp, "path": rel, "text": text[:MAX_TEXT_CHARS], "truncated": len(text) > MAX_TEXT_CHARS}


def refine_library_add(payload: dict) -> dict:
    """Write one experience entry on the working tree (the human-gated inbox): validated and
    leak-checked by tools.jev.library, never committed from here."""
    R, _Sf, L, SP = core._jev()
    if not isinstance(payload, dict):
        raise ValueError("a JSON object")
    fields = {k: str(payload.get(k) or "").strip() for k in ("loop", "step", "domain", "item", "run_id", "adopted",
                                                               "date", "source", "cue", "lesson", "evidence",
                                                               "confidence", "notes")}
    edits = payload.get("edits") or []
    if not isinstance(edits, list):
        raise ValueError("edits must be a list")
    entry = L.Entry(loop=fields["loop"], step=fields["step"], domain=L.domain_dir(fields["domain"]), item=fields["item"],
                    run_id=fields["run_id"], adopted=fields["adopted"],
                    date=fields["date"] or dt.date.today().isoformat(), source=fields["source"] or "human",
                    cue=fields["cue"], lesson=fields["lesson"], evidence=fields["evidence"],
                    confidence=fields["confidence"], notes=fields["notes"],
                    edits=[L.Edit.from_dict(e) for e in edits if isinstance(e, dict)])
    diff = payload.get("diff")
    if diff is not None and not isinstance(diff, str):
        raise ValueError("diff must be text")
    fleet = SP.load_fleet()
    root = L.root(fleet)
    if str(core.REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(core.REPO_ROOT))
    from tools.jev import loop as jev_loop  # noqa: PLC0415
    try:
        d = L.Library(root, entry.loop, entry.domain).add(entry, diff=diff or None, ctx=jev_loop.host_ctx())
    except L.LibraryError as exc:
        raise ValueError(str(exc)) from exc
    return {"path": _rel(d), "entry": entry.to_dict(), "uncommitted": True,
            "next": "review it, then commit on a branch: a lesson reaches main by a pull request"}


def refine_doc(*, local: bool = True, max_age_s: float = 60.0) -> dict:
    """The Refine page's document: the hub's surface check, the fleet sweep, one plan per loop, the
    library, the evidence trees and the review queue. Local paths never appear; the public snapshot
    gets no evidence, reviews or ledger position."""
    now = time.time()
    if local and core._REFINE_CACHE["doc"] is not None and now - core._REFINE_CACHE["at"] < max_age_s:
        return core._REFINE_CACHE["doc"]
    R, _Sf, _L, SP = core._jev()
    fleet = SP.load_fleet()
    try:
        cfg = _jsonable(R.config(fleet))
        cfg_error = None
    except Exception as exc:  # noqa: BLE001
        cfg, cfg_error = None, f"{type(exc).__name__}: {exc}"[:300]
    doc = {
        "schema": "refine-doc/v1", "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "local": local, "config": cfg, "config_error": cfg_error,
        "surface": refine_surface_hub(fleet),
        "fleet_surface": refine_fleet_surface(fleet),
        "plans": refine_plans(fleet, budget=local),
        "library": refine_library(fleet, local=local),
        "evidence": refine_evidence_list() if local else [],
        "reviews": refine_reviews(local=local),
        "missions": {name: R.mission_sha256(name)[:12] for name in R.MISSIONS},
        "stages": list(core.REFINE_STAGES), "modes": list(core.REFINE_MODES), "cost_label": core.COST_LABEL,
    }
    doc = _jsonable(doc)
    if local:
        core._REFINE_CACHE.update(at=now, doc=doc)
    return doc


def assist_doc(*, local: bool = True) -> dict:
    """The Assist page's document: the assistant's configuration and why it cannot run here, if it cannot."""
    try:
        cfg = dict(core.assistant_config())
        error = None
    except ValueError as exc:
        cfg, error = None, str(exc)
    import page_bridge  # noqa: PLC0415 — stdlib only
    prompts = b"".join(p.read_bytes() for p in (core.ASSIST_PROMPT, core.ASSIST_PAGE_PROMPT) if p.is_file())
    # Why no session starts here, as a kind the dock can lay out: the missing CLI is the ordinary case (the
    # Docker console) and has two ways forward, so it is not shown as a fault.
    kind = None
    if local:
        kind = ("no_cli" if core.claude_unavailable() else "config" if error
                else "off" if cfg is not None and not cfg["enabled"] else None)
    return {"schema": "assist-doc/v1", "config": cfg, "config_error": error, "cost_label": core.COST_LABEL,
            "unavailable": (core.assist_unavailable() if local else "The assistant runs on the operator's machine."),
            "unavailable_kind": kind, "host_command": core.ASSIST_HOST_COMMAND,
            "mcp_server": "fleet", "allowed_tools": list(core.ASSIST_ALLOWED), "denied_tools": list(core.ASSIST_DENIED),
            "prompt_sha256": hashlib.sha256(prompts).hexdigest()[:12] if core.ASSIST_PROMPT.is_file() else None,
            "max_question_chars": core.ASSIST_MAX_CHARS, "local": local,
            # The page bridge (page_bridge.py): the ceiling on what a session may do to an open page, and
            # the two tiers of page tools. It serves a paired Claude Code session too, so it is reported
            # apart from `unavailable`, which is only about the session this console can start itself.
            "page": {"access": (core.assistant_page_access() if local else "off"), "look": list(page_bridge.LOOK),
                     "act": list(page_bridge.ACT), "modes": list(page_bridge.MODES),
                     "approval_s": int(page_bridge.APPROVAL_S)},
            # Pages of the fleet's other sites and apps that carry the kit's payload (templates/assistant):
            # their ceiling, and which of them share themselves with this console right now. No session id.
            "fleet_pages": {"access": (core.assistant_fleet_pages() if local else "off"), "kit": "templates/assistant",
                            "sessions": ([s for s in page_bridge.BRIDGE.sessions() if s["kind"] == "fleet"]
                                         if local else [])}}


def page_audit_path() -> Path:
    """Where this console's page bridge writes its audit: `.fleet/assist/page-audit.jsonl` in the hub checkout
    (DASH_CONSOLE_PAGE_AUDIT overrides it). In the checkout, not the job directory: a restart keeps it, and
    the lake and a terminal on the host read the same file (fleetcore.assistlog)."""
    return assistlog.audit_path(core.REPO_ROOT)


def assist_agent() -> dict | None:
    """The assistant's entry in the agent inventory (_data/agents.yml, constitution § 29): who owns it, its
    switch, cap and model, the KPIs its kind declares, where its run records land and its contract gaps.
    None while the inventory has no such entry. Committed, public data: the published build shows it too."""
    doc = core.load_yaml(core.DATA / "agents.yml")
    for entry in (doc.get("agents") if isinstance(doc, dict) else None) or []:
        if isinstance(entry, dict) and entry.get("id") == assistlog.AGENT:
            keys = ("id", "kind", "category", "owner", "trigger", "switch", "budget", "model", "kpis", "reads",
                    "run_record", "feeds_reflector", "local_entry", "gaps")
            return {k: entry.get(k) for k in keys}
    return None


def _shown(path: str | None) -> str | None:
    """A path for a person: relative to the hub checkout, or to the home directory, never the bare absolute."""
    if not path:
        return None
    p = Path(path)
    for base, prefix in ((core.REPO_ROOT, ""), (Path.home(), "~/")):
        try:
            return prefix + str(p.relative_to(base))
        except ValueError:
            continue
    return str(p)


def assist_activity_doc(days: int = assistlog.DAYS_DEFAULT, limit: int = assistlog.RECENT_DEFAULT, *,
                        local: bool = True) -> dict:
    """How the assistant is observed, in one document (`assist-activity/v1`, fleetcore.assistlog): its messages
    from the AI ledger, what its sessions did to pages from the page audit, the fleet pages sharing
    themselves with this console right now, and its entry in the agent inventory. The published build
    carries the inventory entry only: activity is one machine's record, not the fleet's."""
    import page_bridge  # noqa: PLC0415 — stdlib only
    doc = assistlog.activity(core.REPO_ROOT, days=days, limit=limit) if local else assistlog.blank(days)
    doc["page_audit"]["path"] = _shown(doc["page_audit"]["path"])
    doc["messages"]["ledger"] = _shown(doc["messages"]["ledger"])
    doc["local"] = local
    doc["agent_entry"] = assist_agent()
    # No session id: a row is named by its first eight characters, which is what End sends back
    doc["shared_pages"] = {"access": (core.assistant_fleet_pages() if local else "off"),
                           "setting": "assistant.fleet_pages", "cap": page_bridge.MAX_FLEET_SESSIONS,
                           "sessions": ([x for x in page_bridge.BRIDGE.sessions() if x["kind"] == "fleet"]
                                        if local else [])}
    return doc
