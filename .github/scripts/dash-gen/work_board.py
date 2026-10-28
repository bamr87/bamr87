#!/usr/bin/env python3
"""
work_board — every open piece of fleet work on one board, in the order the
loops will take it, with what each loop can take per run.

The fleet's work lives in five places, each with its own state machine:

    issues      GitHub labels           _data/issue_pipeline.yml (the pipeline's sweep)
    PRs         the pull request        _data/fleet_triage.yml (every open PR)
    roadmap     status: in the file     _data/roadmap.yml (FF-NNNN specs)
    specs       - **Status**: in spec   projects/<repo>/specs/NNN-slug/ (spec-driven repos)
    backlog     the BACKLOG.md section  projects/<repo>/BACKLOG.md (BL-YYYYMMDD-NN)

This module joins them into one list of work items on six lanes (triage →
ready → in flight → review, plus blocked and hold), applies the human's order
and priority overrides from _data/work_queue.yml (work_queue.py), and asks the
issue pipeline's OWN queue builder which items its next run will take — so
the board's cut line is the pipeline's, not an imitation of it. It also says
what each loop can drain per run and how long each lane takes at that rate.

A board change is a PLAN (`resolve_plan`): a drag becomes a label move for an
issue, a status edit in _data/roadmap.yml for a roadmap spec, or an order /
priority entry in _data/work_queue.yml. `build(inputs, plan)` previews one
without writing anything; the Harness Console applies it (tools/console/core.py).

Specs and BACKLOG.md items come from submodule CHECKOUTS, so only a local run
sees them; the published snapshot says so instead (`local=False`). Parsing is
the spec-driven kit's own (templates/spec-driven/tools/spec_validator.py and
pick_backlog_item.py), so a spec reads here exactly as the gate reads it.

Pure apart from `load_inputs` / `scan_local` (file reads). Stdlib + PyYAML.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
import sys
from pathlib import Path

import yaml

import issue_pipeline as ip
import work_queue as wq

REPO_ROOT = Path(__file__).resolve().parents[3]
KIT_TOOLS = REPO_ROOT / "templates" / "spec-driven" / "tools"
SCHEMA = "work-board/v1"

LANES = [
    {"id": "triage", "label": "Triage", "hint": "needs shaping before an agent can act"},
    {"id": "ready", "label": "Ready", "hint": "an agent can pick it up"},
    {"id": "doing", "label": "In flight", "hint": "a branch, a draft PR or a claimed spec exists"},
    {"id": "review", "label": "Review", "hint": "a pull request is waiting for a human"},
    {"id": "blocked", "label": "Blocked", "hint": "a gap only a human can close"},
    {"id": "hold", "label": "On hold", "hint": "parked: no loop touches it"},
]
LANE_IDS = [lane["id"] for lane in LANES]
PRIO_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}

# issue stage (labels) ↔ lane
ISSUE_LANE = {"intake": "triage", "ready": "ready", "in-pr": "doing", "blocked": "blocked", "hold": "hold"}
LANE_ISSUE_STAGE = {"triage": "intake", "ready": "ready", "blocked": "blocked", "hold": "hold"}
# roadmap status ↔ lane; shipped / declined leave the board
ROADMAP_LANE = {"proposed": "triage", "approved": "ready", "backlog": "ready", "in-progress": "doing"}
LANE_ROADMAP_STATUS = {"triage": "proposed", "ready": "approved", "doing": "in-progress"}
ROADMAP_STATUSES = ("proposed", "approved", "backlog", "in-progress", "shipped", "declined")
# spec status ↔ lane; shipped / superseded leave the board
SPEC_LANE = {"draft": "triage", "clarified": "ready", "planned": "ready", "tasked": "ready",
             "in-progress": "doing", "implementing": "doing", "blocked": "blocked"}
SPEC_DONE = {"shipped", "superseded"}
SEVERITY_PRIO = {"high": "P1", "med": "P2", "low": "P3"}

LOOP_LABEL = {
    "t1": "Issue pipeline · T1 intake",
    "t2": "Issue pipeline · T2 implement",
    "t3": "Issue pipeline · T3 complete",
    "evolve": "Spec-driven /evolve",
    "human": "You",
    "none": "Nobody (parked)",
}

PLAN_KEYS = {"stage", "priority", "pins", "unpin", "notes", "roadmap_status", "roadmap_reason"}


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _load_yaml(path: Path):
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):
        return None


def _stamp(value) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    if not isinstance(value, str):
        return None
    for fmt in ("%Y-%m-%d %H:%M UTC", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            ts = dt.datetime.strptime(value, fmt)
        except ValueError:
            continue
        return ts if ts.tzinfo else ts.replace(tzinfo=dt.timezone.utc)
    return None


def _days_since(value, now: dt.datetime) -> int | None:
    ts = _stamp(str(value)) if value is not None else None
    return max(0, (now - ts).days) if ts else None


def _cron_field(field: str, lo: int, hi: int) -> int:
    """How many values a cron field matches."""
    if field == "*":
        return hi - lo + 1
    total = 0
    for part in field.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/", 1)
            step = max(1, int(s))
        if part in ("*", ""):
            a, b = lo, hi
        elif "-" in part:
            a, b = (int(x) for x in part.split("-", 1))
        else:
            a = b = int(part)
        total += len(range(a, b + 1, step))
    return total


def runs_per_week(cron: str | None) -> float:
    """A five-field cron's firings per week (day-of-month is treated as daily)."""
    try:
        minute, hour, dom, _month, dow = str(cron or "").split()
        per_day = _cron_field(minute, 0, 59) * _cron_field(hour, 0, 23)
        days = 7 if dow == "*" else min(7, _cron_field(dow.replace("7", "0"), 0, 6))
        if dom != "*" and dow == "*":
            days = min(7, _cron_field(dom, 1, 31) * 7 / 30)
        return float(per_day * days)
    except (ValueError, TypeError):
        return 0.0


def _kit():
    """The spec-driven kit's own parsers (spec gate + /evolve picker)."""
    if str(KIT_TOOLS) not in sys.path:
        sys.path.insert(0, str(KIT_TOOLS))
    import pick_backlog_item as pb  # noqa: WPS433
    import spec_validator as sv  # noqa: WPS433
    return sv, pb


def _name_by_nwo(registry: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in registry:
        m = re.match(r"https?://github\.com/([^/]+/[^/#?]+)", str(p.get("repo_url") or ""))
        if m and p.get("name"):
            out[m.group(1).removesuffix(".git").lower()] = p["name"]
    return out


# --------------------------------------------------------------------------- #
# specs + BACKLOG.md (local checkouts)
# --------------------------------------------------------------------------- #
TASK_HEAD_RX = re.compile(r"^##\s+(T-\d+)\s*[—–-]\s*(.+?)\s*$")
TASK_INLINE_RX = re.compile(r"^- \[([ x~])\]\s+\*\*(T-\d+)\*\*\s*[—–-]?\s*(.*)$")
TASK_STATUS_RX = re.compile(r"^- \*\*Status\*\*:\s*`\[([ x~])\]`")
FIELD_RX = re.compile(r"^- \*\*(ID|Status|Owner|Created)\*\*:\s*(.+?)\s*$", re.M)
TITLE_RX = re.compile(r"^#\s+(?:Spec:\s*)?(.+?)\s*$", re.M)
FOLLOWUP_RX = re.compile(r"^- (?:\*\*)?(BL-\d{8}-\d{2})", re.M)
SECTION_RX = re.compile(r"^## (Open|Claimed|Done)\b")
CLAIMED_RX = re.compile(r"claimed-by:\s*(specs/\d{3}-[a-z0-9-]+)")
SURFACED_RX = re.compile(r"_Surfaced in:_\s*(.+?)(?:\s+_[A-Z][^_]*:_|$)")


def tasks_of(text: str) -> list[dict]:
    """Every task in a tasks.md, in both of the kit's formats."""
    out: list[dict] = []
    current: dict | None = None
    for line in (text or "").splitlines():
        m = TASK_HEAD_RX.match(line)
        if m:
            current = {"id": m.group(1), "title": m.group(2)[:160], "status": " "}
            out.append(current)
            continue
        m = TASK_STATUS_RX.match(line)
        if m and current is not None:
            current["status"] = m.group(1)
            current = None
            continue
        m = TASK_INLINE_RX.match(line)
        if m:
            out.append({"id": m.group(2), "title": m.group(3)[:160], "status": m.group(1)})
    for t in out:
        t["state"] = {"x": "done", "~": "doing"}.get(t.pop("status"), "todo")
    return out


def summarize_spec(slug: str, spec_md: str, tasks_md: str = "", plan_md: str = "") -> dict:
    """One spec package as the board sees it — the same regexes as the gate."""
    sv, _pb = _kit()
    fields = {k.lower(): v for k, v in FIELD_RX.findall(spec_md or "")}
    status_m = sv.STATUS_RE.search(spec_md or "")
    status = (status_m.group(1).lower() if status_m else "unknown")
    if "superseded" in str(fields.get("status", "")).lower():
        status = "superseded"
    title_m = TITLE_RX.search(spec_md or "")
    ids = sorted(sv.ID_RE.findall(spec_md or ""))
    covered = set(sv.ID_RE.findall(tasks_md or ""))
    tasks = tasks_of(tasks_md)
    follow = tasks_md.split("## Follow-ups Discovered", 1)[1] if "## Follow-ups Discovered" in (tasks_md or "") else ""
    open_q = sorted(set(sv.OPEN_Q_RE.findall(spec_md or "") + sv.OPEN_Q_RE.findall(plan_md or "")))
    reqs = sorted(set(ids))
    return {
        "slug": slug,
        "number": slug[:3],
        "title": (title_m.group(1) if title_m else slug)[:160],
        "status": status,
        "owner": fields.get("owner"),
        "created": fields.get("created"),
        "files": {"spec": bool(spec_md), "plan": bool(plan_md), "tasks": bool(tasks_md)},
        "requirements": {
            "FR": sum(1 for i in reqs if i.startswith("FR-")),
            "NFR": sum(1 for i in reqs if i.startswith("NFR-")),
            "AC": sum(1 for i in reqs if i.startswith("AC-")),
            "uncovered": [i for i in reqs if i not in covered] if tasks_md else [],
        },
        "tasks": {
            "total": len(tasks),
            "done": sum(1 for t in tasks if t["state"] == "done"),
            "doing": sum(1 for t in tasks if t["state"] == "doing"),
        },
        "open_questions": [q.upper().replace("OPEN QUESTION ", "") for q in open_q],
        "followups": sorted(set(FOLLOWUP_RX.findall(follow))),
    }


def parse_backlog(text: str) -> list[dict]:
    """Open + Claimed items of a BACKLOG.md (Done leaves the board), in file order."""
    _sv, pb = _kit()
    open_ids = {i["id"] for i in pb.open_items(text or "")}
    out: list[dict] = []
    section = None
    for line in (text or "").splitlines():
        m = SECTION_RX.match(line)
        if m:
            section = m.group(1)
            continue
        if line.startswith("## "):
            section = None
            continue
        if section not in ("Open", "Claimed"):
            continue
        m = pb._BULLET.match(line)  # noqa: SLF001 — the kit's own bullet grammar
        if not m:
            continue
        d = m.groupdict()
        if section == "Open" and d["id"] not in open_ids:
            continue  # left in Open but resolved — the picker skips it too
        claimed = CLAIMED_RX.search(d["text"])
        surfaced = SURFACED_RX.search(d["text"])
        title = pb._TAIL.sub("", CLAIMED_RX.sub("", d["text"])).strip(" —-")  # noqa: SLF001
        out.append({
            "id": d["id"], "kind": d["kind"], "severity": d["sev"], "section": section,
            "title": title[:200], "text": d["text"][:4000],
            "claimed_by": claimed.group(1) if claimed else None,
            "surfaced_in": surfaced.group(1).strip()[:200] if surfaced else None,
        })
    return out


def scan_local(root: Path, registry: list[dict]) -> dict:
    """Spec packages and BACKLOG.md items in every checked-out registry repo."""
    _sv, pb = _kit()
    specs: list[dict] = []
    backlog: list[dict] = []
    repos: list[dict] = []
    for p in registry:
        rel = p.get("submodule_path")
        if not rel:
            continue
        base = root / rel
        sdir = base / "specs"
        bl = base / "BACKLOG.md"
        if not sdir.is_dir() and not bl.is_file():
            continue
        rec = {"repo": p["name"], "path": rel, "specs": 0, "specs_open": 0, "backlog_open": 0,
               "repo_url": p.get("repo_url"), "branch": p.get("branch") or "main", "evolve_pick": None,
               "auto_evolve": bool(p.get("auto_evolve"))}
        if sdir.is_dir():
            for d in sorted(sdir.iterdir()):
                if not d.is_dir() or not re.match(r"^\d{3}-[a-z0-9][a-z0-9-]*$", d.name):
                    continue
                texts = [(d / n).read_text(encoding="utf-8", errors="replace") if (d / n).is_file() else ""
                         for n in ("spec.md", "tasks.md", "plan.md")]
                s = summarize_spec(d.name, *texts)
                s.update(repo=p["name"], path=f"{rel}/specs/{d.name}")
                rec["specs"] += 1
                if s["status"] not in SPEC_DONE:
                    rec["specs_open"] += 1
                specs.append(s)
        if bl.is_file():
            text = bl.read_text(encoding="utf-8", errors="replace")
            items = parse_backlog(text)
            for i in items:
                i["repo"] = p["name"]
            backlog.extend(items)
            rec["backlog_open"] = sum(1 for i in items if i["section"] == "Open")
            pick = pb.pick(text)
            rec["evolve_pick"] = pick["id"] if pick else None
        repos.append(rec)
    return {"scanned": True, "repos": repos, "specs": specs, "backlog": backlog}


def spec_detail(root: Path, rel_path: str) -> dict:
    """The drill-down for one spec package: the summary, the tasks, the text."""
    d = (root / rel_path).resolve()
    if not str(d).startswith(str(root.resolve())) or not d.is_dir():
        raise ValueError("no such spec package")

    def read(n: str, cap: int = 60_000) -> str:
        f = d / n
        return f.read_text(encoding="utf-8", errors="replace")[:cap] if f.is_file() else ""

    spec_md, tasks_md, plan_md = read("spec.md"), read("tasks.md"), read("plan.md")
    out = summarize_spec(d.name, spec_md, tasks_md, plan_md)
    out["task_list"] = tasks_of(tasks_md)
    lines = (spec_md + "\n" + plan_md).splitlines()
    out["open_question_lines"] = [ln.strip().lstrip(">*- ").strip()[:300] for ln in lines
                                  if re.search(r"OPEN QUESTION\s+OQ-\d+", ln, re.I)][:20]
    out["markdown"] = spec_md
    return out


# --------------------------------------------------------------------------- #
# inputs
# --------------------------------------------------------------------------- #
def load_inputs(root: Path = REPO_ROOT, *, local: bool = True, queue_path: Path | None = None,
                roadmap_path: Path | None = None, moves: dict | None = None,
                now: dt.datetime | None = None) -> dict:
    data = root / "_data"
    registry = [p for p in (_load_yaml(data / "projects.yml") or []) if isinstance(p, dict) and p.get("name")]
    fleet = _load_yaml(data / "fleet.yml") or {}
    queue, problems = wq.load(queue_path or (data / "work_queue.yml"))
    roadmap = _load_yaml(roadmap_path or (data / "roadmap.yml"))
    return {
        "root": root,
        "now": now or _now(),
        "registry": registry,
        "cfg": ip.load_config(data / "fleet.yml"),
        "schedule": fleet.get("schedule") or {},
        "evolution": fleet.get("evolution") or {},
        "pipeline": _load_yaml(data / "issue_pipeline.yml") or {},
        "triage": _load_yaml(data / "fleet_triage.yml") or {},
        "roadmap": roadmap if isinstance(roadmap, list) else [],
        "queue": queue,
        "queue_problems": problems,
        "local": scan_local(root, registry) if local else None,
        "moves": moves or {},
    }


# --------------------------------------------------------------------------- #
# items
# --------------------------------------------------------------------------- #
def label_move(stage: str, lane: str, state: dict) -> tuple[list[str], list[str]]:
    """The labels that move an issue from its stage into a lane."""
    ready, blocked, hold = state["ready"], state["blocked"], state["hold"]
    if lane == "hold":
        return [hold], []
    leave = [hold] if stage == "hold" else []
    if lane == "triage":
        return [], [ready, blocked, *leave]
    if lane == "ready":
        return [ready], [blocked, *leave]
    if lane == "blocked":
        return [blocked], [ready, *leave]
    raise ValueError(f"an issue cannot be moved to {lane}")


def _issue_movable(stage: str) -> list[str]:
    if stage == "in-pr":
        return ["hold"]
    return [lane for lane in ("triage", "ready", "blocked", "hold") if lane != ISSUE_LANE.get(stage)]


def _label_priority(labels: list[str]) -> str | None:
    for lb in labels:
        m = re.fullmatch(r"(?:priority:)?(P[0-3])", str(lb), re.I)
        if m:
            return m.group(1).upper()
    return None


def _issue_rows(inp: dict) -> tuple[list[dict], bool]:
    """Every open issue: the pipeline's full list when its snapshot carries one,
    else its capped queues plus the triage snapshot's label-only view."""
    pipe = inp["pipeline"] or {}
    if isinstance(pipe.get("backlog"), list):
        return [dict(r) for r in pipe["backlog"]], True
    cfg = inp["cfg"]
    rows: dict[str, dict] = {}
    for q in ("intake", "implement"):
        for r in (pipe.get("queues") or {}).get(q) or []:
            rows[r["key"]] = dict(r)
    for repo in (inp["triage"] or {}).get("by_repo") or []:
        if repo.get("external") or repo.get("archived") or repo.get("private"):
            continue
        for it in (repo.get("issues") or {}).get("items") or []:
            key = f"{repo['nwo']}#{it['number']}"
            if key in rows:
                continue
            labels = [str(x) for x in it.get("labels") or []]
            itype = ip.detect_type(it.get("title") or "", "", labels, cfg["labels"]["types"])
            size = next((lb for lb in labels if lb in cfg["labels"]["sizes"]), "size:s")
            prio = _label_priority(labels)
            rows[key] = {
                "number": it["number"], "key": key, "title": it.get("title") or "", "url": it.get("url"),
                "labels": labels, "assignees": [], "comments": 0, "age_days": it.get("age_days"),
                "idle_days": it.get("idle_days"), "stage": ip.classify_stage(labels, cfg, has_open_pr=False),
                "type": itype, "priority": prio or "P2", "priority_auto": prio or "P2",
                "priority_source": "label" if prio else "default", "priority_score": None,
                "size": size, "readiness": 0, "owner": None, "pr": None, "gaps": [],
                "nwo": repo["nwo"], "repo": repo.get("name"), "_derived": True,
            }
    return list(rows.values()), False


def _weight(item: dict) -> float:
    """Within one priority, each kind keeps its own loop's order (higher first)."""
    k = item["kind"]
    if k == "issue":
        return (item.get("readiness") or 0) * 10_000 + min(item.get("age_days") or 0, 9_999)
    if k == "pr":
        d = item["detail"]
        return ((900 if d.get("ci") == "fail" else 0) + (50 if d.get("draft") else 0)
                + min(item.get("idle_days") or 0, 49))
    if k == "backlog":
        d = item["detail"]
        debt = 100 if d.get("kind") in ("tech-debt", "test-gap") else 0
        # the /evolve picker's order: debt kinds first, then the oldest id
        return debt + (99_999_999 - int(item["ref"][3:11])) / 1e8 + (99 - int(item["ref"][12:14])) / 1e10
    if k == "spec":
        t = item.get("progress") or {}
        return 100 * (t.get("done", 0) / t["total"]) if t.get("total") else 0
    return 1000 - int(re.sub(r"\D", "", item["ref"]) or 0) / 10  # roadmap: oldest FF first


def sort_key(item: dict):
    # Ties within a priority fall back to the loop's own queue position, so a
    # lane lists its next-run picks in the order the loop takes them.
    rank = item.get("rank")
    return (0 if rank is not None else 1, rank if rank is not None else 0,
            PRIO_ORDER.get(item["priority"], 9), -_weight(item), item.get("next_run") or 10_000, item["key"])


def _items(inp: dict, queue: dict, stage_over: dict[str, str],
           roadmap_over: dict[str, dict]) -> tuple[list[dict], dict]:
    cfg = inp["cfg"]
    state = cfg["labels"]["state"]
    names = _name_by_nwo(inp["registry"])
    hub = cfg["hub"].lower()
    ranks = wq.ranks(queue)
    pipe = inp["pipeline"] or {}
    pipe_at = _stamp(pipe.get("generated_at"))
    items: list[dict] = []

    def repo_name(nwo: str) -> str:
        if nwo.lower() == hub:
            return names.get(hub, nwo.split("/")[-1])
        return names.get(nwo.lower(), nwo.split("/")[-1])

    def prio(key: str, auto: str, source: str) -> tuple[str, str]:
        eff, src = wq.priority_for(queue, key, auto)
        return eff, (src if src == "override" else source)

    # --- issues ---------------------------------------------------------------
    rows, full = _issue_rows(inp)
    for r in rows:
        nwo = r.get("nwo") or r["key"].split("#")[0]
        key = f"issue:{r['key']}"
        stage = r.get("stage") or "intake"
        labels = list(r.get("labels") or [])
        moved = None
        mv = (inp.get("moves") or {}).get(key)
        if mv and (pipe_at is None or (_stamp(mv.get("at")) or pipe_at) > pipe_at):
            moved = {"lane": mv["lane"], "at": mv.get("at"), "pending": False}
        if key in stage_over:
            moved = {"lane": stage_over[key], "at": None, "pending": True}
        if moved:
            add, remove = label_move(stage, moved["lane"], state)
            labels = [lb for lb in labels if lb not in remove] + [lb for lb in add if lb not in labels]
            stage = ip.classify_stage(labels, cfg, has_open_pr=bool(r.get("pr")))
        lane = ISSUE_LANE.get(stage)
        if lane is None:
            continue
        auto = r.get("priority_auto") or r.get("priority") or "P2"
        src = r.get("priority_source") if r.get("priority_source") in ("label", "default") else "computed"
        eff, src = prio(key, auto, src)
        autonomy, why = ip.decide_autonomy(itype=r.get("type") or "bug", size=r.get("size") or "size:s",
                                           prio=eff, labels=labels, cfg=cfg)
        items.append({
            "key": key, "kind": "issue", "ref": f"#{r['number']}", "title": r.get("title") or "",
            "url": r.get("url"), "repo": repo_name(nwo), "nwo": nwo, "lane": lane, "stage": stage,
            "priority": eff, "priority_auto": auto, "priority_source": src, "rank": ranks.get(key),
            "size": r.get("size"), "age_days": r.get("age_days"), "idle_days": r.get("idle_days"),
            "readiness": r.get("readiness"), "autonomy": autonomy, "autonomy_reason": why,
            "labels": labels, "movable": _issue_movable(stage), "moved": moved,
            "progress": None, "note": (queue.get("notes") or {}).get(key),
            "detail": {"number": r["number"], "type": r.get("type"), "score": r.get("priority_score"),
                       "gaps": r.get("gaps") or [], "owner": r.get("owner"), "pr": r.get("pr"),
                       "comments": r.get("comments"), "derived": bool(r.get("_derived"))},
        })

    # --- pull requests ---------------------------------------------------------
    pipeline_prs: dict[str, dict] = {}
    for p in (pipe.get("pipeline_prs") or (pipe.get("queues") or {}).get("complete") or []):
        if p.get("nwo"):
            pipeline_prs[f"{p['nwo']}#{p['number']}"] = p
    for repo in (inp["triage"] or {}).get("by_repo") or []:
        if repo.get("external") or repo.get("archived") or repo.get("private"):
            continue
        for p in (repo.get("prs") or {}).get("items") or []:
            ref = f"{repo['nwo']}#{p['number']}"
            key = f"pr:{ref}"
            pp = pipeline_prs.get(ref)
            ci = (pp or {}).get("ci") or p.get("ci") or ""
            dependabot = bool(p.get("dependabot"))
            auto = "P1" if ci == "fail" else ("P3" if dependabot else "P2")
            eff, src = prio(key, auto, "derived")
            items.append({
                "key": key, "kind": "pr", "ref": f"#{p['number']}", "title": p.get("title") or "",
                "url": p.get("url"), "repo": repo_name(repo["nwo"]), "nwo": repo["nwo"],
                "lane": "doing" if p.get("draft") else "review", "stage": "draft" if p.get("draft") else "open",
                "priority": eff, "priority_auto": auto, "priority_source": src, "rank": ranks.get(key),
                "size": None, "age_days": p.get("age_days"), "idle_days": p.get("idle_days"),
                "readiness": None, "autonomy": None, "autonomy_reason": None, "labels": (pp or {}).get("labels") or [],
                "movable": [], "moved": None, "progress": None, "note": (queue.get("notes") or {}).get(key),
                "detail": {"number": p["number"], "draft": bool(p.get("draft")), "ci": ci, "author": p.get("author"),
                           "dependabot": dependabot, "pipeline": pp is not None,
                           "branch": (pp or {}).get("branch"), "linked_issues": (pp or {}).get("linked_issues") or [],
                           "mergeable_state": (pp or {}).get("mergeable_state"),
                           "human_review": bool((pp or {}).get("human_review"))},
            })

    # --- roadmap specs ---------------------------------------------------------
    for e in inp["roadmap"]:
        if not isinstance(e, dict) or not e.get("id"):
            continue
        key = f"roadmap:{e['id']}"
        over = roadmap_over.get(e["id"]) or {}
        status = over.get("status") or e.get("status") or "proposed"
        lane = ROADMAP_LANE.get(status)
        if lane is None:
            continue
        p = over.get("priority") or e.get("priority") or "P2"
        project = e.get("project") or "bamr87"
        items.append({
            "key": key, "kind": "roadmap", "ref": e["id"], "title": e.get("title") or "",
            "url": e.get("issue_url"), "repo": project, "nwo": None, "lane": lane, "stage": status,
            "priority": p, "priority_auto": e.get("priority") or "P2", "priority_source": "roadmap",
            "rank": ranks.get(key), "size": e.get("effort"), "age_days": _days_since(e.get("created"), inp["now"]),
            "idle_days": None, "readiness": None, "autonomy": None, "autonomy_reason": None, "labels": [],
            "movable": [x for x in ("triage", "ready", "doing") if x != lane],
            "moved": {"lane": lane, "at": None, "pending": True} if over.get("status") else None,
            "progress": None, "note": (queue.get("notes") or {}).get(key),
            "detail": {"category": e.get("category"), "problem": e.get("problem"),
                       "acceptance": len(e.get("acceptance") or []), "source": e.get("source"),
                       "issue_url": e.get("issue_url"), "created": str(e.get("created") or "")},
        })

    # --- spec packages + BACKLOG.md (local checkouts only) ----------------------
    local = inp.get("local") or {}
    repo_meta = {r["repo"]: r for r in local.get("repos") or []}
    for s in local.get("specs") or []:
        if s["status"] in SPEC_DONE:
            continue
        key = f"spec:{s['repo']}/{s['slug']}"
        lane = SPEC_LANE.get(s["status"], "triage")
        auto = "P1" if s["status"] in ("in-progress", "implementing") else "P2"
        eff, src = prio(key, auto, "default")
        meta = repo_meta.get(s["repo"]) or {}
        items.append({
            "key": key, "kind": "spec", "ref": s["number"], "title": s["title"],
            "url": f"{str(meta.get('repo_url') or '').rstrip('/')}/tree/{meta.get('branch', 'main')}/specs/{s['slug']}"
                   if meta.get("repo_url") else None,
            "repo": s["repo"], "nwo": None, "lane": lane, "stage": s["status"],
            "priority": eff, "priority_auto": auto, "priority_source": src, "rank": ranks.get(key),
            "size": None, "age_days": _days_since(s.get("created"), inp["now"]), "idle_days": None,
            "readiness": None, "autonomy": None, "autonomy_reason": None, "labels": [], "movable": [],
            "moved": None, "progress": {"done": s["tasks"]["done"], "total": s["tasks"]["total"]},
            "note": (queue.get("notes") or {}).get(key),
            "detail": {"slug": s["slug"], "path": s["path"], "open_questions": s["open_questions"],
                       "requirements": s["requirements"], "tasks": s["tasks"], "followups": len(s["followups"]),
                       "owner": s.get("owner")},
        })
    for b in local.get("backlog") or []:
        key = f"backlog:{b['repo']}/{b['id']}"
        lane = "triage" if b["section"] == "Open" else "doing"
        auto = SEVERITY_PRIO.get(b["severity"], "P2")
        eff, src = prio(key, auto, "severity")
        meta = repo_meta.get(b["repo"]) or {}
        items.append({
            "key": key, "kind": "backlog", "ref": b["id"], "title": b["title"],
            "url": f"{str(meta.get('repo_url') or '').rstrip('/')}/blob/{meta.get('branch', 'main')}/BACKLOG.md"
                   if meta.get("repo_url") else None,
            "repo": b["repo"], "nwo": None, "lane": lane, "stage": b["section"].lower(),
            "priority": eff, "priority_auto": auto, "priority_source": src, "rank": ranks.get(key),
            "size": None, "age_days": _days_since(f"{b['id'][3:7]}-{b['id'][7:9]}-{b['id'][9:11]}", inp["now"]),
            "idle_days": None, "readiness": None, "autonomy": None, "autonomy_reason": None, "labels": [],
            "movable": [], "moved": None, "progress": None, "note": (queue.get("notes") or {}).get(key),
            "detail": {"kind": b["kind"], "severity": b["severity"], "section": b["section"],
                       "claimed_by": b.get("claimed_by"), "surfaced_in": b.get("surfaced_in"),
                       "evolve_pick": meta.get("evolve_pick") == b["id"]},
        })

    return items, {"issues_full": full}


# --------------------------------------------------------------------------- #
# loops: who drains what, at what rate
# --------------------------------------------------------------------------- #
def _simulate(items: list[dict], inp: dict) -> dict[str, list[str]]:
    """Ask the issue pipeline's own queue builder what its next run takes."""
    by_nwo: dict[str, dict] = {}
    for it in items:
        if it["kind"] not in ("issue", "pr") or not it.get("nwo"):
            continue
        r = by_nwo.setdefault(it["nwo"], {
            "nwo": it["nwo"], "name": it["repo"], "repo_url": f"https://github.com/{it['nwo']}",
            "category": "", "status": "", "stack": [], "private": False, "default_branch": "main",
            "issues": [], "prs": []})
        if it["kind"] == "issue":
            # A label-only issue (a snapshot without the full backlog) was not
            # scored by the pipeline, which ranked the scored ones above it, so
            # it only fills what the scored ones leave — unless a human set it.
            derived = it["detail"]["derived"] and it["priority_source"] != "override"
            r["issues"].append({"key": it["key"], "number": it["detail"]["number"], "stage": it["stage"],
                                "autonomy": it["autonomy"], "priority": "unscored" if derived else it["priority"],
                                "readiness": it.get("readiness") or 0, "age_days": it.get("age_days") or 0,
                                "rank": it.get("rank")})
        elif it["detail"].get("pipeline"):
            r["prs"].append({"key": it["key"], "number": it["detail"]["number"], "pipeline": True,
                             "draft": it["detail"]["draft"], "ci": it["detail"]["ci"],
                             "idle_days": it.get("idle_days") or 0, "rank": it.get("rank")})
    q = ip.build_queues(list(by_nwo.values()), inp["cfg"])
    return {"t1": [c["key"] for c in q["intake"]], "t2": [c["key"] for c in q["implement"]],
            "t3": [c["key"] for c in q["complete"]]}


def _assign_loops(items: list[dict], picks: dict[str, list[str]], local: dict | None) -> None:
    order = {k: (loop, i) for loop, keys in picks.items() for i, k in enumerate(keys)}
    for it in items:
        it["next_run"] = None
        if it["key"] in order:
            loop, i = order[it["key"]]
            it["loop"], it["next_run"] = loop, i + 1
            continue
        k, lane = it["kind"], it["lane"]
        if lane == "hold":
            it["loop"] = "none"
        elif k == "issue":
            it["loop"] = {"triage": "t1", "ready": "t2", "doing": "t3"}.get(lane, "human")
            if it["autonomy"] == "blocked" and lane in ("triage", "ready"):
                it["loop"] = "human"
        elif k == "pr":
            it["loop"] = "t3" if it["detail"].get("pipeline") else "human"
        elif k in ("spec", "backlog"):
            it["loop"] = "human" if (k == "spec" and lane == "triage") else "evolve"
            if k == "backlog" and it["detail"].get("evolve_pick"):
                it["next_run"] = 1
        else:
            it["loop"] = "human"


def _drain(eligible: int, cap: int, rpw: float) -> tuple[int | None, float | None]:
    if not eligible:
        return 0, 0.0
    if not cap or not rpw:
        return None, None
    runs = math.ceil(eligible / cap)
    return runs, round(runs * 7 / rpw, 1)


def _loops(items: list[dict], picks: dict[str, list[str]], inp: dict) -> list[dict]:
    cfg, sched = inp["cfg"], inp["schedule"]
    tiers = cfg["tiers"]
    hub = cfg["hub"].lower()
    rpw = runs_per_week(sched.get("issue_pipeline"))
    by_loop: dict[str, list[dict]] = {}
    for it in items:
        by_loop.setdefault(it["loop"], []).append(it)

    def per_repo(rows: list[dict], loop: str) -> list[dict]:
        out: dict[str, dict] = {}
        for it in rows:
            r = out.setdefault(it["repo"], {"repo": it["repo"], "eligible": 0, "picked": 0})
            r["eligible"] += 1
            r["picked"] += 1 if it.get("next_run") and it["loop"] == loop else 0
        return sorted(out.values(), key=lambda r: (-r["eligible"], r["repo"]))

    loops = []
    t1 = [i for i in by_loop.get("t1", []) if i["kind"] == "issue"]
    per = int(tiers["intake"]["max_per_repo"])
    runs, days = _drain(len(t1), int(tiers["intake"]["max_issues"]), rpw)
    rep = per_repo(t1, "t1")
    if runs is not None and rep and per:
        runs = max(runs, max(math.ceil(r["eligible"] / per) for r in rep))
        days = round(runs * 7 / rpw, 1) if rpw else None
    loops.append({"id": "t1", "label": LOOP_LABEL["t1"], "lane": "triage", "kind": "issue",
                  "schedule": sched.get("issue_pipeline"), "runs_per_week": rpw,
                  "cap": int(tiers["intake"]["max_issues"]), "sub_cap": {"label": "per repo", "value": per},
                  "eligible": len(t1), "next_run": len(picks["t1"]), "drain_runs": runs, "drain_days": days,
                  "by_repo": rep, "config": "issue_pipeline"})

    t2 = [i for i in by_loop.get("t2", []) if i["kind"] == "issue"]
    cross = int(tiers["implement"]["max_cross_repo"])
    runs, days = _drain(len(t2), int(tiers["implement"]["max_issues"]), rpw)
    away = sum(1 for i in t2 if (i.get("nwo") or "").lower() != hub)
    if runs is not None and away and cross:
        runs = max(runs, math.ceil(away / cross))
        days = round(runs * 7 / rpw, 1) if rpw else None
    loops.append({"id": "t2", "label": LOOP_LABEL["t2"], "lane": "ready", "kind": "issue",
                  "schedule": sched.get("issue_pipeline"), "runs_per_week": rpw,
                  "cap": int(tiers["implement"]["max_issues"]), "sub_cap": {"label": "outside the hub", "value": cross},
                  "eligible": len(t2), "next_run": len(picks["t2"]), "drain_runs": runs, "drain_days": days,
                  "by_repo": per_repo(t2, "t2"), "config": "issue_pipeline"})

    t3 = [i for i in by_loop.get("t3", []) if i["kind"] == "pr"]
    runs, days = _drain(len(t3), int(tiers["complete"]["max_prs"]), rpw)
    loops.append({"id": "t3", "label": LOOP_LABEL["t3"], "lane": "doing", "kind": "pr",
                  "schedule": sched.get("issue_pipeline"), "runs_per_week": rpw,
                  "cap": int(tiers["complete"]["max_prs"]), "sub_cap": None,
                  "eligible": len(t3), "next_run": len(picks["t3"]), "drain_runs": runs, "drain_days": days,
                  "by_repo": per_repo(t3, "t3"), "config": "issue_pipeline"})

    ev = by_loop.get("evolve", [])
    local = inp.get("local") or {}
    auto = [r["repo"] for r in local.get("repos") or [] if r.get("auto_evolve")]
    ev_rpw = runs_per_week(sched.get("repo_evolution")) if auto else 0.0
    loops.append({"id": "evolve", "label": LOOP_LABEL["evolve"], "lane": "triage", "kind": "backlog",
                  "schedule": sched.get("repo_evolution") if auto else None, "runs_per_week": ev_rpw,
                  "cap": len(auto) or None, "sub_cap": {"label": "per repo", "value": 1} if auto else None,
                  "eligible": len(ev), "next_run": sum(1 for i in ev if i.get("next_run")),
                  "drain_runs": None, "drain_days": None, "by_repo": per_repo(ev, "evolve"),
                  "on_demand": not auto, "config": "evolution",
                  "note": ("user-invoked per repo (/spec-driven:evolve): it takes the top Open item by "
                           "severity, kind and age"
                           + (f"; repo-evolution also runs weekly on {', '.join(auto)}" if auto else ""))})

    hu = by_loop.get("human", [])
    loops.append({"id": "human", "label": LOOP_LABEL["human"], "lane": "review", "kind": None,
                  "schedule": None, "runs_per_week": None, "cap": None, "sub_cap": None,
                  "eligible": len(hu), "next_run": 0, "drain_runs": None, "drain_days": None,
                  "by_repo": per_repo(hu, "human"), "config": None,
                  "breakdown": {
                      "reviews": sum(1 for i in hu if i["kind"] == "pr"),
                      "blocked": sum(1 for i in hu if i["lane"] == "blocked"),
                      "approvals": sum(1 for i in hu if i["kind"] == "roadmap" and i["lane"] == "triage"),
                      "scoping": sum(1 for i in hu if i["kind"] == "roadmap" and i["lane"] != "triage"),
                      "clarify": sum(1 for i in hu if i["kind"] == "spec"),
                      "gated": sum(1 for i in hu if i["kind"] == "issue" and i["lane"] in ("triage", "ready")),
                  }})
    return loops


def _hints(items: list[dict], loops: list[dict], inp: dict, sources: dict) -> list[dict]:
    out: list[dict] = []
    lp = {loop["id"]: loop for loop in loops}
    t1, t2 = lp["t1"], lp["t2"]
    if t1["by_repo"] and t1["sub_cap"]["value"]:
        top = t1["by_repo"][0]
        if top["eligible"] > t1["sub_cap"]["value"] * 3:
            out.append({"tone": "warn", "lever": "config:issue_pipeline",
                        "text": f"{top['repo']} has {top['eligible']} issues waiting for intake but takes at most "
                                f"{t1['sub_cap']['value']} slots a run, so clearing it takes "
                                f"{math.ceil(top['eligible'] / t1['sub_cap']['value'])} runs. Pin the ones that "
                                f"matter, or raise intake.max_per_repo."})
    if t2["eligible"] and t2["sub_cap"]["value"]:
        hub = inp["cfg"]["hub"].lower()
        away = sum(1 for i in items if i.get("loop") == "t2" and (i.get("nwo") or "").lower() != hub)
        if away > t2["sub_cap"]["value"]:
            out.append({"tone": "info", "lever": "config:issue_pipeline",
                        "text": f"{away} ready issues outside the hub share {t2['sub_cap']['value']} cross-repo "
                                f"implement slots a run. Pin the order you want them opened in."})
    blocked = [i for i in items if i["lane"] == "blocked"]
    if blocked and len(blocked) >= max(10, len(items) // 5):
        out.append({"tone": "warn", "lever": "lane:blocked",
                    "text": f"{len(blocked)} items are blocked on a gap only a human can close, and no loop "
                            f"drains that lane. Move the ones you have answered back to Ready."})
    reviews = [i for i in items if i["lane"] == "review"]
    stale = [i for i in reviews if (i.get("idle_days") or 0) > 14]
    if stale:
        out.append({"tone": "info", "lever": "lane:review",
                    "text": f"{len(stale)} of {len(reviews)} open pull requests have been idle for more than "
                            f"14 days."})
    gone = sources["work_queue"]["stale_keys"]
    if gone:
        out.append({"tone": "info", "lever": "apply",
                    "text": f"{len(gone)} pinned or overridden keys no longer match an open item (closed, "
                            f"merged or shipped). The next apply prunes them."})
    age = sources["issue_pipeline"]["age_days"]
    if age is not None and age > 2:
        out.append({"tone": "warn", "lever": "op:issues",
                    "text": f"The issue pipeline snapshot is {age} days old. Refresh it before rebalancing."})
    if not sources["issue_pipeline"]["full"]:
        out.append({"tone": "info", "lever": "op:issues",
                    "text": "This issue snapshot predates the full backlog list, so issues outside the capped "
                            "queues carry label-only priorities and the next-run cut line is approximate. The "
                            "next issue-pipeline run (or Refresh) adds scores for every issue."})
    for line in inp.get("queue_problems") or []:
        out.append({"tone": "warn", "lever": None, "text": line})
    return out


# --------------------------------------------------------------------------- #
# plans
# --------------------------------------------------------------------------- #
def resolve_plan(items: list[dict], plan: dict | None, queue: dict, state: dict) -> dict:
    """Validate a board plan against the board and split it by where each change lands.

    Raises ValueError naming the first change the board cannot make."""
    plan = plan or {}
    extra = set(plan) - PLAN_KEYS
    if extra:
        raise ValueError(f"unknown plan field(s): {sorted(extra)}")
    by_key = {it["key"]: it for it in items}
    known = (set(by_key) | set(queue.get("order") or []) | set(queue.get("priority") or {})
             | set(queue.get("notes") or {}))
    out = {"labels": [], "roadmap": {}, "queue": {"pins": {}, "unpin": [], "priority": {}, "notes": {}},
           "stage": {}, "changes": []}

    for key, lane in (plan.get("stage") or {}).items():
        it = by_key.get(key)
        if it is None:
            raise ValueError(f"{key} is not on the board")
        if lane == it["lane"]:
            continue
        if lane not in it["movable"]:
            where = {"pr": "its pull request", "spec": "its spec.md",
                     "backlog": "its BACKLOG.md"}.get(it["kind"], "its source")
            raise ValueError(f"{key} cannot move to {lane}: its state lives in {where}")
        out["stage"][key] = lane
        if it["kind"] == "issue":
            add, remove = label_move(it["stage"], lane, state)
            out["labels"].append({"key": key, "nwo": it["nwo"], "number": it["detail"]["number"],
                                  "from": it["lane"], "to": lane, "add": add, "remove": remove})
            out["changes"].append({"key": key, "target": "github",
                                   "what": f"{it['repo']} {it['ref']}: {it['lane']} → {lane}"
                                           + (f" (+{', +'.join(add)})" if add else "")
                                           + (f" (−{', −'.join(remove)})" if remove else "")})
        elif it["kind"] == "roadmap":
            status = LANE_ROADMAP_STATUS[lane]
            out["roadmap"].setdefault(it["ref"], {})["status"] = status
            out["changes"].append({"key": key, "target": "roadmap",
                                   "what": f"{it['ref']}: status {it['stage']} → {status}"})

    for key, value in (plan.get("priority") or {}).items():
        it = by_key.get(key)
        if it is None and key not in known:
            raise ValueError(f"{key} is not on the board")
        if value not in (None, "", *wq.PRIORITIES):
            raise ValueError(f"{key}: priority must be one of {wq.PRIORITIES}")
        if wq.kind_of(key) == "roadmap":
            if not value:
                raise ValueError(f"{key}: a roadmap spec always has a priority")
            out["roadmap"].setdefault(key.split(":", 1)[1], {})["priority"] = value
            out["changes"].append({"key": key, "target": "roadmap",
                                   "what": f"{key.split(':', 1)[1]}: priority "
                                           f"{it['priority'] if it else '?'} → {value}"})
            continue
        out["queue"]["priority"][key] = value or None
        label = f"{it['repo']} {it['ref']}" if it else key
        out["changes"].append({"key": key, "target": "work_queue",
                               "what": f"{label}: priority → {value} (override)" if value
                               else f"{label}: priority override cleared "
                                    f"(back to {it['priority_auto'] if it else 'computed'})"})

    # A status no lane stands for (backlog, shipped, declined) — the drill-down's select.
    roadmap_ids = {it["ref"] for it in items if it["kind"] == "roadmap"}
    for ff, status in (plan.get("roadmap_status") or {}).items():
        if ff not in roadmap_ids:
            raise ValueError(f"roadmap:{ff} is not on the board")
        it = by_key[f"roadmap:{ff}"]
        if status == it["stage"]:
            continue
        out["roadmap"].setdefault(ff, {})["status"] = status
        out["changes"].append({"key": it["key"], "target": "roadmap",
                               "what": f"{ff}: status {it['stage']} → {status}"})
    for ff, text in (plan.get("roadmap_reason") or {}).items():
        if text:
            out["roadmap"].setdefault(ff, {})["reason"] = str(text).strip()[:500]

    lanes_now = {}
    for it in items:
        lane = out["stage"].get(it["key"], it["lane"])
        lanes_now.setdefault(lane, set()).add(it["key"])
    for lane, keys in (plan.get("pins") or {}).items():
        if lane not in LANE_IDS:
            raise ValueError(f"no lane {lane!r}")
        keys = list(dict.fromkeys(keys or []))
        bad = [k for k in keys if k not in by_key]
        if bad:
            raise ValueError(f"{bad[0]} is not on the board")
        wrong = [k for k in keys if out["stage"].get(k, by_key[k]["lane"]) != lane]
        if wrong:
            raise ValueError(f"{wrong[0]} is not in lane {lane}")
        out["queue"]["pins"][lane] = keys
        out["changes"].append({"key": None, "target": "work_queue",
                               "what": f"{next(x['label'] for x in LANES if x['id'] == lane)}: manual order "
                                       + _order_text([by_key[k] for k in keys])})
    out["queue"]["lane_members"] = lanes_now
    for key in plan.get("unpin") or []:
        if key not in known:
            raise ValueError(f"{key} is not on the board")
        out["queue"]["unpin"].append(key)
        it = by_key.get(key)
        out["changes"].append({"key": key, "target": "work_queue",
                               "what": f"{(it['repo'] + ' ' + it['ref']) if it else key}: unpinned"})
    for key, text in (plan.get("notes") or {}).items():
        if key not in known:
            raise ValueError(f"{key} is not on the board")
        out["queue"]["notes"][key] = text or None
        out["changes"].append({"key": key, "target": "work_queue",
                               "what": f"{key}: note {'set' if text else 'cleared'}"})
    for ff, fields in out["roadmap"].items():
        if fields.get("status") and fields["status"] not in ROADMAP_STATUSES:
            raise ValueError(f"{ff}: status must be one of {ROADMAP_STATUSES}")
        if fields.get("status") == "declined" and not fields.get("reason"):
            raise ValueError(f"{ff}: declining a roadmap spec needs a reason")
    return out


def _order_text(items: list[dict]) -> str:
    if not items:
        return "cleared"
    text = " → ".join(f"{it['repo']} {it['ref']}" for it in items[:4])
    return text + (f" … (+{len(items) - 4})" if len(items) > 4 else "")


def preview_queue(queue: dict, resolved: dict) -> dict:
    q = resolved["queue"]
    if not (q["pins"] or q["unpin"] or q["priority"] or q["notes"]):
        return queue
    return wq.apply_changes(queue, pins=q["pins"], lane_members=q["lane_members"], unpin=q["unpin"],
                            priority=q["priority"], notes=q["notes"])


def edit_roadmap(text: str, ff_id: str, *, status: str | None = None, priority: str | None = None,
                 reason: str | None = None) -> str:
    """Change one entry's status / priority (/ reason) in place, every other
    byte of _data/roadmap.yml — its long header, the folded prose — kept."""
    if not re.fullmatch(r"FF-\d{4,6}", ff_id or ""):
        raise ValueError("not a roadmap id")
    lines = text.splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if re.match(rf"^- id:\s*{re.escape(ff_id)}\s*$", ln)), None)
    if start is None:
        raise ValueError(f"{ff_id} is not in _data/roadmap.yml")
    end = next((j for j in range(start + 1, len(lines)) if re.match(r"^- id:\s", lines[j])), len(lines))

    def put(field: str, value: str, after: str | None = None) -> None:
        nonlocal end
        for j in range(start, end):
            if re.match(rf"^  {field}:(\s|$)", lines[j]):
                lines[j] = f"  {field}: {value}\n"
                return
        if after is None:
            raise ValueError(f"{ff_id} has no {field}: line")
        at = next(j for j in range(start, end) if re.match(rf"^  {after}:(\s|$)", lines[j]))
        lines.insert(at + 1, f"  {field}: {value}\n")
        end += 1

    if status is not None:
        if status not in ROADMAP_STATUSES:
            raise ValueError(f"status must be one of {ROADMAP_STATUSES}")
        put("status", status)
    if priority is not None:
        if priority not in wq.PRIORITIES:
            raise ValueError(f"priority must be one of {wq.PRIORITIES}")
        put("priority", priority)
    if reason:
        put("reason", json.dumps(str(reason)[:500], ensure_ascii=False), after="status")
    new = "".join(lines)
    parsed = yaml.safe_load(new)
    entry = next((e for e in parsed if isinstance(e, dict) and e.get("id") == ff_id), None)
    if entry is None or (status and entry.get("status") != status) or (priority and entry.get("priority") != priority):
        raise ValueError(f"editing {ff_id} did not round-trip — _data/roadmap.yml left untouched")
    return new


# --------------------------------------------------------------------------- #
# the board
# --------------------------------------------------------------------------- #
def build(inp: dict, plan: dict | None = None) -> dict:
    """The board document; with a plan, the board as it would be (nothing written)."""
    queue = inp["queue"]
    base, meta = _items(inp, queue, {}, {})
    resolved = resolve_plan(base, plan, queue, inp["cfg"]["labels"]["state"]) if plan else None
    if resolved:
        queue = preview_queue(queue, resolved)
        items, meta = _items(inp, queue, resolved["stage"], resolved["roadmap"])
    else:
        items = base
    picks = _simulate(items, inp)
    _assign_loops(items, picks, inp.get("local"))
    items.sort(key=lambda it: (LANE_IDS.index(it["lane"]), sort_key(it)))
    loops = _loops(items, picks, inp)

    live = {it["key"] for it in items}
    pipe = inp["pipeline"] or {}
    pipe_at = _stamp(pipe.get("generated_at"))
    local = inp.get("local")
    # A key is stale only when its source was seen WHOLE: the triage snapshot
    # caps issues per repo, and a submodule that is not checked out has no
    # specs — neither is evidence that the item closed, so neither may cost
    # a human's pin when the next apply prunes.
    scanned = {r["repo"] for r in (local or {}).get("repos") or []}
    capped_prs = any((r.get("prs") or {}).get("capped") for r in (inp["triage"] or {}).get("by_repo") or [])

    def judged(key: str) -> bool:
        kind = wq.kind_of(key)
        if kind == "issue":
            return meta["issues_full"]
        if kind == "pr":
            return not capped_prs
        if kind in ("spec", "backlog"):
            return key.split(":", 1)[1].split("/", 1)[0] in scanned
        return True

    stale_keys = sorted(k for k in ({*(queue.get("order") or []), *(queue.get("priority") or {}),
                                     *(queue.get("notes") or {})} - live) if judged(k))
    sources = {
        "issue_pipeline": {"generated_at": pipe.get("generated_at"), "full": meta["issues_full"],
                           "age_days": (inp["now"] - pipe_at).days if pipe_at else None,
                           "private_omitted": pipe.get("backlog_private_omitted", 0)},
        "fleet_triage": {"generated_at": (inp["triage"] or {}).get("generated_at")},
        "roadmap": {"entries": len(inp["roadmap"])},
        "local": ({"scanned": True, "repos": local.get("repos") or []} if local
                  else {"scanned": False, "repos": [],
                        "reason": "spec packages and BACKLOG.md items are read from submodule checkouts, "
                                  "so only a running console shows them"}),
        "work_queue": {"updated_at": queue.get("updated_at"), "pinned": len(queue.get("order") or []),
                       "priority_overrides": len(queue.get("priority") or {}), "stale_keys": stale_keys},
    }
    lanes = []
    for lane in LANES:
        rows = [it for it in items if it["lane"] == lane["id"]]
        lanes.append({**lane, "count": len(rows), "pinned": sum(1 for it in rows if it.get("rank") is not None),
                      "loops": sorted({it["loop"] for it in rows})})
    repos: dict[str, dict] = {}
    for it in items:
        r = repos.setdefault(it["repo"], {"repo": it["repo"], "total": 0, "next_run": 0,
                                          **{lane: 0 for lane in LANE_IDS}})
        r["total"] += 1
        r[it["lane"]] += 1
        r["next_run"] += 1 if it.get("next_run") and it["loop"] in ("t1", "t2", "t3") else 0
    totals = {"items": len(items), "next_run": sum(len(v) for v in picks.values()),
              "by_kind": {k: sum(1 for it in items if it["kind"] == k) for k in wq.KINDS},
              "by_priority": {p: sum(1 for it in items if it["priority"] == p) for p in wq.PRIORITIES}}
    doc = {
        "schema": SCHEMA,
        "generated_at": inp["now"].strftime("%Y-%m-%d %H:%M UTC"),
        "preview": bool(resolved),
        "lanes": lanes,
        "items": items,
        "loops": loops,
        "repos": sorted(repos.values(), key=lambda r: (-r["total"], r["repo"])),
        "totals": totals,
        "sources": sources,
        "labels": inp["cfg"]["labels"]["state"],
        "priorities": list(wq.PRIORITIES),
        "roadmap_statuses": list(ROADMAP_STATUSES),
    }
    doc["hints"] = _hints(items, loops, inp, sources)
    if resolved:
        doc["changes"] = resolved["changes"]
    return doc


def item_detail(inp: dict, key: str) -> dict:
    """One item with everything its drill-down shows."""
    if not wq.valid_key(key):
        raise ValueError("not a work key")
    board = build(inp)
    it = next((x for x in board["items"] if x["key"] == key), None)
    if it is None:
        raise ValueError(f"{key} is not on the board")
    out = {"item": it, "loop": next((lp for lp in board["loops"] if lp["id"] == it["loop"]), None)}
    if it["kind"] == "roadmap":
        out["entry"] = next((e for e in inp["roadmap"] if isinstance(e, dict) and e.get("id") == it["ref"]), None)
    elif it["kind"] == "spec" and inp.get("local"):
        out["spec"] = spec_detail(inp["root"], it["detail"]["path"])
    elif it["kind"] == "backlog" and inp.get("local"):
        out["backlog"] = next((b for b in inp["local"]["backlog"]
                               if b["repo"] == it["repo"] and b["id"] == it["ref"]), None)
    elif it["kind"] == "pr":
        text = f"{it['title']} {it['detail'].get('branch') or ''}"
        out["mentions"] = sorted(set(re.findall(r"specs/(\d{3}-[a-z0-9-]+)", text)))
    return out
