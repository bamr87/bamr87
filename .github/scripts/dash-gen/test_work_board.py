#!/usr/bin/env python3
"""
Fixture tests for work_queue.py + work_board.py — the Work board and the file
the loops read the human's order from.

Guards the invariants that make reprioritising on the board mean something:

  * a pinned issue goes ahead of every unpinned one in the issue pipeline's
    queues, whatever its score, and a human's priority replaces the computed
    one (and so the label T1 applies) — otherwise a drag on the board changes
    a picture and nothing the loop does;
  * the board's "next run" cut line IS issue_pipeline.build_queues' answer for
    the same items, never a re-implementation that can drift from it;
  * a preview writes nothing; a plan that names an item whose state lives
    elsewhere (a PR, a spec.md, a BACKLOG.md) is refused rather than silently
    ignored;
  * an issue's lane move is exactly the label change the pipeline's state
    machine reads back as that lane;
  * a roadmap edit changes one line of _data/roadmap.yml and every other byte
    — its long header, the folded prose — survives;
  * a hand-edited work_queue.yml with junk in it costs the junk, not the run;
  * specs and BACKLOG.md items are parsed with the spec-driven kit's own rules,
    and only a local run (submodule checkouts) carries them;
  * the evolution brief lists only the repo's own pins.

No network, no gh, no pytest. Needs only PyYAML:

    python3 .github/scripts/dash-gen/test_work_board.py
"""
from __future__ import annotations

import datetime as dt
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import evolution as ev  # noqa: E402
import issue_pipeline as ip  # noqa: E402
import work_board as wb  # noqa: E402
import work_queue as wq  # noqa: E402

FAILURES: list[str] = []
HUB = "bamr87/bamr87"
NOW = dt.datetime(2026, 10, 27, 12, 0, tzinfo=dt.timezone.utc)


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ok   {name}")
    else:
        FAILURES.append(f"{name}{': ' + detail if detail else ''}")
        print(f"  FAIL {name}{': ' + detail if detail else ''}")


def raises(fn, needle: str = "") -> bool:
    try:
        fn()
    except ValueError as exc:
        return needle in str(exc)
    return False


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
def issue(nwo: str, n: int, *, stage="intake", priority="P2", readiness=60, age=5, labels=(),
          itype="bug", size="size:s") -> dict:
    return {"number": n, "key": f"{nwo}#{n}", "title": f"issue {n}", "url": f"https://github.com/{nwo}/issues/{n}",
            "labels": list(labels), "assignees": [], "comments": 0, "age_days": age, "idle_days": age,
            "stage": stage, "type": itype, "priority": priority, "priority_auto": priority,
            "priority_source": "computed", "priority_score": 50, "rank": None, "size": size,
            "autonomy": "auto", "autonomy_reason": "no gate matched", "owner": "bamr87", "pr": None,
            "readiness": readiness, "gaps": [{"id": "no-acceptance", "by": "agent", "what": "no acceptance"}],
            "nwo": nwo, "repo": nwo.split("/")[-1]}


ROADMAP = """\
# =============================================================================
# _data/roadmap.yml — header that must survive every edit
# =============================================================================

- id: FF-0001
  title: First
  project: bamr87
  repo_url: https://github.com/bamr87/bamr87
  status: proposed
  priority: P2
  effort: M
  category: feature
  problem: >-
    A folded paragraph that
    spans two lines.
  proposal: Do it.
  acceptance:
    - "It is done."
  source: manual
  created: 2026-10-01
  issue_url: null

- id: FF-0002
  title: Second
  project: demo
  repo_url: https://github.com/bamr87/demo
  status: in-progress
  priority: P1
  effort: S
  category: fix
  problem: p
  proposal: q
  acceptance: []
  source: manual
  created: 2026-10-02
  issue_url: null

- id: FF-0003
  title: Shipped one
  project: bamr87
  repo_url: https://github.com/bamr87/bamr87
  status: shipped
  priority: P2
  effort: S
  category: fix
  problem: p
  proposal: q
  acceptance: []
  source: manual
  created: 2026-09-02
  issue_url: null
"""

SPEC = """\
# Spec: Demo widget

- **ID**: 001-demo-widget
- **Status**: in-progress
- **Owner**: @bamr87
- **Created**: 2026-10-10

## 1. Problem

FR-1 the widget renders. FR-2 the widget saves. AC-1 a user sees it.

OPEN QUESTION OQ-1: which colour?
"""

TASKS = """\
# Tasks: Demo widget

## T-001 — Render it
- **Status**: `[x]`
Covers FR-1, AC-1.

## T-002 — Save it
- **Status**: `[~]`
Covers FR-2.

- [ ] **T-003** — Document it

## Follow-ups Discovered

- BL-20261011-01 — feature, low — later
"""

BACKLOG = """\
# Demo — Backlog

## Open

- **BL-20261011-01** — *feature, low* — Later work. _Surfaced in:_ specs/001-demo-widget.
- **BL-20261001-02** — *test-gap, high* — Missing test for the saver.
- **BL-20261002-03** — *feature, med* — ~~Already done~~ (resolved in #4)

## Claimed

- **BL-20260901-01** — *feature, med* — claimed-by:specs/001-demo-widget — The widget itself.

## Done

- **BL-20260801-01** — *infra, low* — Old.
"""


def fixture_root(*, with_backlog_list: bool = True, queue: dict | None = None) -> Path:
    root = Path(tempfile.mkdtemp(prefix="work-board-"))
    data = root / "_data"
    data.mkdir()
    (data / "projects.yml").write_text(yaml.safe_dump([
        {"name": "bamr87", "repo_url": f"https://github.com/{HUB}", "branch": "main"},
        {"name": "demo", "repo_url": "https://github.com/bamr87/demo", "branch": "main",
         "submodule_path": "projects/demo"},
        {"name": "noisy", "repo_url": "https://github.com/bamr87/noisy", "branch": "main"},
    ]))
    (data / "fleet.yml").write_text(yaml.safe_dump({
        "schedule": {"issue_pipeline": "37 7 * * *", "repo_evolution": "37 10 * * 1"},
        "issue_pipeline": {"tiers": {"intake": {"max_issues": 3, "max_per_repo": 2},
                                     "implement": {"max_issues": 2, "max_cross_repo": 1},
                                     "complete": {"max_prs": 2}}},
    }))
    issues = ([issue("bamr87/noisy", n, priority="P1", readiness=90 - n) for n in range(1, 6)]
              + [issue(HUB, 10, priority="P3", readiness=20), issue(HUB, 11, stage="ready", priority="P2"),
                 issue("bamr87/demo", 12, stage="ready", priority="P1"),
                 issue("bamr87/demo", 13, stage="blocked", labels=["agent:blocked"]),
                 issue(HUB, 14, stage="in-pr", priority="P2")])
    issues[-1]["pr"] = {"number": 99, "url": "u"}
    pipe = {"generated_at": "2026-10-27 07:52 UTC", "queues": {"intake": [], "implement": [], "complete": []},
            "pipeline_prs": [{"number": 99, "nwo": HUB, "repo": "bamr87", "draft": True, "ci": "fail",
                              "idle_days": 1, "pipeline": True, "branch": "agent/issue-14", "linked_issues": [14],
                              "labels": ["agent:in-pr"], "human_review": False, "mergeable_state": "unstable"}]}
    if with_backlog_list:
        pipe["backlog"] = issues
    else:
        pipe["queues"]["intake"] = [i for i in issues if i["stage"] == "intake"][:3]
    (data / "issue_pipeline.yml").write_text(yaml.safe_dump(pipe))
    (data / "fleet_triage.yml").write_text(yaml.safe_dump({"generated_at": "2026-10-27 06:00 UTC", "by_repo": [
        {"name": "bamr87 (hub)", "nwo": HUB, "external": False, "archived": False, "private": False,
         "issues": {"items": [{"number": 15, "title": "label-only", "labels": ["P1"], "age_days": 3,
                               "idle_days": 1, "url": "u"}]},
         "prs": {"items": [{"number": 99, "title": "fix: 14", "draft": True, "ci": "fail", "age_days": 2,
                            "idle_days": 1, "url": "u", "author": "bamr87", "dependabot": False},
                           {"number": 100, "title": "docs: x", "draft": False, "ci": "pass", "age_days": 30,
                            "idle_days": 20, "url": "u", "author": "bamr87", "dependabot": False}]}},
        {"name": "ext", "nwo": "microsoft/skills", "external": True, "issues": {"items": [
            {"number": 1, "title": "never on the board", "labels": [], "url": "u"}]}, "prs": {"items": []}},
    ]}))
    (data / "roadmap.yml").write_text(ROADMAP)
    if queue is not None:
        wq.save(data / "work_queue.yml", queue)
    spec = root / "projects" / "demo" / "specs" / "001-demo-widget"
    spec.mkdir(parents=True)
    (spec / "spec.md").write_text(SPEC)
    (spec / "tasks.md").write_text(TASKS)
    shipped = root / "projects" / "demo" / "specs" / "002-old"
    shipped.mkdir()
    (shipped / "spec.md").write_text("# Spec: Old\n\n- **Status**: shipped\n")
    (root / "projects" / "demo" / "specs" / "_template").mkdir()
    (root / "projects" / "demo" / "BACKLOG.md").write_text(BACKLOG)
    return root


def board(root: Path, *, local=True, plan=None, moves=None) -> dict:
    return wb.build(wb.load_inputs(root, local=local, moves=moves, now=NOW), plan)


def by_key(doc: dict) -> dict[str, dict]:
    return {it["key"]: it for it in doc["items"]}


# --------------------------------------------------------------------------- #
# work_queue.py
# --------------------------------------------------------------------------- #
def test_work_queue_file():
    print("\nwork_queue.yml: parse, normalise, apply, prune")
    doc, problems = wq.normalize({
        "schema": wq.SCHEMA,
        "order": ["issue:bamr87/a#1", "not a key", "issue:bamr87/a#1", "backlog:demo/BL-20261001-02"],
        "priority": {"issue:bamr87/a#1": "P0", "roadmap:FF-0001": "P1", "pr:bamr87/a#2": "P9"},
        "notes": {"issue:bamr87/a#1": "  ship first  ", "junk": "x"},
    })
    check("junk keys are dropped, not fatal", doc["order"] == ["issue:bamr87/a#1", "backlog:demo/BL-20261001-02"],
          str(doc["order"]))
    check("a duplicate order entry keeps the first", doc["order"].count("issue:bamr87/a#1") == 1)
    check("a roadmap priority override is refused (roadmap.yml owns it)", "roadmap:FF-0001" not in doc["priority"])
    check("an invalid priority is dropped", "pr:bamr87/a#2" not in doc["priority"])
    check("every drop is reported", len(problems) >= 5, str(problems))
    check("notes are trimmed", doc["notes"] == {"issue:bamr87/a#1": "ship first"})
    check("a non-mapping file reads as empty", wq.normalize(["x"])[0] == wq.empty())

    base = {**wq.empty(), "order": ["issue:o/r#1", "issue:o/r#2", "issue:o/r#9"]}
    lane = {"issue:o/r#1", "issue:o/r#2", "issue:o/r#3"}
    out = wq.apply_changes(base, pins={"ready": ["issue:o/r#3", "issue:o/r#1"]}, lane_members={"ready": lane},
                           today="2026-10-27")
    check("a lane's new pins replace its old ones", out["order"] == ["issue:o/r#9", "issue:o/r#3", "issue:o/r#1"],
          str(out["order"]))
    check("another lane's pins are untouched", "issue:o/r#9" in out["order"])
    check("apply stamps updated_at", out["updated_at"] == "2026-10-27")
    check("apply is pure", base["order"] == ["issue:o/r#1", "issue:o/r#2", "issue:o/r#9"])
    out = wq.apply_changes(out, unpin=["issue:o/r#3"], priority={"issue:o/r#1": "P0"})
    check("unpin removes the key", "issue:o/r#3" not in out["order"])
    check("a priority override is recorded", out["priority"] == {"issue:o/r#1": "P0"})
    out = wq.apply_changes(out, priority={"issue:o/r#1": None})
    check("a null priority clears the override", out["priority"] == {})
    check("a roadmap priority cannot be written here",
          raises(lambda: wq.apply_changes(base, priority={"roadmap:FF-0001": "P1"}), "roadmap.yml"))
    pruned, gone = wq.prune({**base, "priority": {"issue:o/r#2": "P1"}}, {"issue:o/r#1"})
    check("prune drops keys for items that are gone", gone == ["issue:o/r#2", "issue:o/r#9"]
          and pruned["order"] == ["issue:o/r#1"] and pruned["priority"] == {}, str(gone))

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "work_queue.yml"
        wq.save(path, {**base, "priority": {"issue:o/r#2": "P1"}, "notes": {"issue:o/r#2": "why"}})
        text = path.read_text()
        again, problems = wq.load(path)
        check("save → load round-trips", again["order"] == base["order"] and again["priority"] == {"issue:o/r#2": "P1"}
              and not problems, str(problems))
        check("the written file carries its header", text.startswith("# ====") and "work-queue/v1" in text)
        check("a missing file loads as empty", wq.load(Path(tmp) / "nope.yml") == (wq.empty(), []))


# --------------------------------------------------------------------------- #
# issue_pipeline.py honours the file
# --------------------------------------------------------------------------- #
def test_pipeline_honours_order():
    print("\nissue pipeline: the human's order and priority win")
    cfg = ip.deep_merge(ip.DEFAULT_CONFIG, {"tiers": {"intake": {"max_issues": 2, "max_per_repo": 2},
                                                      "implement": {"max_issues": 3, "max_cross_repo": 3}}})
    hi = issue(HUB, 1, priority="P0", readiness=99)
    lo = issue(HUB, 2, priority="P3", readiness=5)
    mid = issue(HUB, 3, priority="P1", readiness=50)
    lo["rank"] = 0
    repo = {"nwo": HUB, "name": "bamr87", "repo_url": "u", "category": "", "status": "", "stack": [],
            "private": False, "default_branch": "main", "issues": [hi, lo, mid], "prs": []}
    q = ip.build_queues([repo], cfg)
    check("a pinned P3 goes ahead of an unpinned P0", [c["number"] for c in q["intake"]] == [2, 1],
          str([c["number"] for c in q["intake"]]))
    mid["rank"], lo["rank"] = 0, 1
    q = ip.build_queues([repo], cfg)
    check("pins keep their own order", [c["number"] for c in q["intake"]] == [3, 2])

    prs = [{"number": n, "pipeline": True, "draft": True, "ci": ci, "idle_days": 1, "rank": rank}
           for n, ci, rank in ((1, "fail", None), (2, "pass", 0))]
    q = ip.build_queues([{**repo, "issues": [], "prs": prs}], cfg)
    check("a pinned PR goes ahead of a red one at T3", [p["number"] for p in q["complete"]] == [2, 1])

    eff, src = wq.priority_for({"priority": {"issue:o/r#1": "P0"}}, "issue:o/r#1", "P2")
    check("priority_for returns the override and says so", (eff, src) == ("P0", "override"))
    check("collect_repo takes the override document", "queue" in ip.collect_repo.__code__.co_varnames)

    item = {**issue(HUB, 7, priority="P0"), "priority_auto": "P2", "priority_source": "override", "rank": 0,
            "author": "a", "body_chars": 0, "has_images": False, "category": "dash", "status": "active",
            "stack": [], "default_branch": "main", "needs_evidence": False, "tiers_seen": [], "gaps": []}
    t1 = ip.render_t1([item], ip.DEFAULT_CONFIG, {"repos": 1, "open_issues": 1})
    check("the T1 work order says a human set the priority", "set by a human" in t1 and "`P2`" in t1)
    check("the T1 work order names the pin", "pinned #1" in t1)

    priv = {"nwo": "bamr87/secret", "name": "secret", "private": True, "issues": [issue("bamr87/secret", 1)],
            "prs": []}
    pub = {"nwo": HUB, "name": "bamr87", "private": False, "issues": [issue(HUB, 2)], "prs": []}
    rows, omitted = ip.backlog_list([priv, pub])
    check("the public backlog list omits private repos' issues", [r["key"] for r in rows] == [f"{HUB}#2"]
          and omitted == 1)
    check("the backlog list keeps gap ids but not the long `how`",
          rows[0]["gaps"] == [{"id": "no-acceptance", "by": "agent", "what": "no acceptance"}])


# --------------------------------------------------------------------------- #
# work_board.py
# --------------------------------------------------------------------------- #
def test_board_lanes_and_sources():
    print("\nboard: every source on one board")
    root = fixture_root()
    doc = board(root)
    items = by_key(doc)
    check("issues come from the pipeline's full list", f"issue:{HUB}#10" in items and doc["sources"]["issue_pipeline"]["full"])
    check("an external mirror's issues never reach the board", not any("microsoft/skills" in k for k in items))
    check("lanes follow the label stages", items["issue:bamr87/demo#12"]["lane"] == "ready"
          and items["issue:bamr87/demo#13"]["lane"] == "blocked" and items[f"issue:{HUB}#14"]["lane"] == "doing")
    check("a draft PR is in flight, an open one waits for review",
          items[f"pr:{HUB}#99"]["lane"] == "doing" and items[f"pr:{HUB}#100"]["lane"] == "review")
    check("a pipeline PR is T3's", items[f"pr:{HUB}#99"]["loop"] == "t3" and items[f"pr:{HUB}#100"]["loop"] == "human")
    check("a red PR derives P1", items[f"pr:{HUB}#99"]["priority"] == "P1")
    check("roadmap statuses map to lanes; shipped leaves the board",
          items["roadmap:FF-0001"]["lane"] == "triage" and items["roadmap:FF-0002"]["lane"] == "doing"
          and "roadmap:FF-0003" not in items)
    check("the hub's display name is its registry name", items[f"issue:{HUB}#10"]["repo"] == "bamr87")

    spec = items.get("spec:demo/001-demo-widget")
    check("an in-progress spec is in flight", spec and spec["lane"] == "doing", str(spec and spec["lane"]))
    check("a shipped spec and the template dir are not on the board",
          "spec:demo/002-old" not in items and not any("_template" in k for k in items))
    check("spec task progress uses both kit formats", spec and spec["progress"] == {"done": 1, "total": 3},
          str(spec and spec["progress"]))
    check("an unresolved open question is surfaced", spec and spec["detail"]["open_questions"] == ["OQ-1"])
    check("requirement ids are counted", spec and spec["detail"]["requirements"]["FR"] == 2
          and spec["detail"]["requirements"]["AC"] == 1)
    bl = {k: v for k, v in items.items() if k.startswith("backlog:")}
    check("Open and Claimed BACKLOG items are on the board; Done and resolved are not",
          set(bl) == {"backlog:demo/BL-20261011-01", "backlog:demo/BL-20261001-02", "backlog:demo/BL-20260901-01"},
          str(sorted(bl)))
    check("a claimed item is in flight", bl["backlog:demo/BL-20260901-01"]["lane"] == "doing")
    check("severity maps to priority", bl["backlog:demo/BL-20261001-02"]["priority"] == "P1"
          and bl["backlog:demo/BL-20261011-01"]["priority"] == "P3")
    check("the /evolve pick is marked (the kit's own picker)",
          bl["backlog:demo/BL-20261001-02"]["detail"]["evolve_pick"]
          and bl["backlog:demo/BL-20261001-02"]["next_run"] == 1)
    check("the surfaced-in tail is split off the title",
          bl["backlog:demo/BL-20261011-01"]["title"] == "Later work."
          and bl["backlog:demo/BL-20261011-01"]["detail"]["surfaced_in"] == "specs/001-demo-widget.")

    snap = board(root, local=False)
    check("the published board carries no spec or BACKLOG item",
          not any(k.startswith(("spec:", "backlog:")) for k in by_key(snap)))
    check("and says why", snap["sources"]["local"]["scanned"] is False and "checkouts" in snap["sources"]["local"]["reason"])


def test_board_cut_line_is_the_pipelines():
    print("\nboard: the next-run cut line is the pipeline's own")
    root = fixture_root()
    inp = wb.load_inputs(root, local=False, now=NOW)
    doc = wb.build(inp)
    picks_board = [it["key"] for it in sorted((i for i in doc["items"] if i["loop"] == "t1" and i["next_run"]),
                                              key=lambda i: i["next_run"])]
    repos: dict[str, dict] = {}
    for r in inp["pipeline"]["backlog"]:
        rec = repos.setdefault(r["nwo"], {"nwo": r["nwo"], "name": r["repo"], "repo_url": "", "category": "",
                                          "status": "", "stack": [], "private": False, "default_branch": "main",
                                          "issues": [], "prs": []})
        rec["issues"].append({**r, "key": f"issue:{r['key']}"})
    want = [c["key"] for c in ip.build_queues(list(repos.values()), inp["cfg"])["intake"]]
    check("board T1 picks == issue_pipeline.build_queues", picks_board == want, f"{picks_board} != {want}")
    t1 = next(lp for lp in doc["loops"] if lp["id"] == "t1")
    check("the per-repo cap holds on the board", sum(1 for k in picks_board if "noisy" in k) <= 2)
    check("T1 drain accounts for the per-repo cap (5 noisy at 2/run = 3 runs)", t1["drain_runs"] == 3,
          str(t1["drain_runs"]))
    check("a daily cron is 7 runs a week", t1["runs_per_week"] == 7.0 and wb.runs_per_week("37 10 * * 1") == 1.0)
    t2 = next(lp for lp in doc["loops"] if lp["id"] == "t2")
    check("T2 respects the cross-repo sub-cap", t2["next_run"] == 2
          and sum(1 for it in doc["items"] if it["loop"] == "t2" and it["next_run"]
                  and it["nwo"] != HUB) == 1)

    # The point of the board: pin the P3 and it takes a slot.
    plan = {"pins": {"triage": [f"issue:{HUB}#10"]}}
    pre = wb.build(inp, plan)
    p_items = by_key(pre)
    check("pinning a P3 puts it in the next run", p_items[f"issue:{HUB}#10"]["next_run"] == 1,
          str(p_items[f"issue:{HUB}#10"]["next_run"]))
    check("the preview lists the change", pre["preview"] and any("manual order" in c["what"] for c in pre["changes"]))
    check("a preview writes nothing", not (root / "_data" / "work_queue.yml").exists())

    plan = {"priority": {"issue:bamr87/noisy#5": "P0"}}
    pre = by_key(wb.build(inp, plan))
    check("a P0 override lifts an issue into the next run", pre["issue:bamr87/noisy#5"]["next_run"] == 1
          and pre["issue:bamr87/noisy#5"]["priority_source"] == "override")

    plan = {"stage": {"issue:bamr87/demo#13": "ready"}}
    pre = wb.build(inp, plan)
    moved = by_key(pre)["issue:bamr87/demo#13"]
    check("moving a blocked issue to Ready previews it in Ready", moved["lane"] == "ready" and moved["moved"]["pending"])
    check("…as the label change the state machine reads back",
          "agent:ready" in moved["labels"] and "agent:blocked" not in moved["labels"])

    queued = wq.apply_changes(wq.empty(), pins={"triage": [f"issue:{HUB}#10"]}, lane_members={"triage": set()})
    saved = fixture_root(queue=queued)
    items = by_key(board(saved, local=False))
    check("a committed pin reaches the board", items[f"issue:{HUB}#10"]["rank"] == 0
          and items[f"issue:{HUB}#10"]["next_run"] == 1)


def test_plans_refuse_what_they_cannot_do():
    print("\nplans: validated, split by destination")
    root = fixture_root()
    inp = wb.load_inputs(root, local=True, now=NOW)
    items = wb.build(inp)["items"]
    state = inp["cfg"]["labels"]["state"]

    def resolve(plan):
        return wb.resolve_plan(items, plan, inp["queue"], state)

    check("a PR cannot be dragged to another lane",
          raises(lambda: resolve({"stage": {f"pr:{HUB}#100": "ready"}}), "its pull request"))
    check("a spec cannot be dragged (its status is spec.md's)",
          raises(lambda: resolve({"stage": {"spec:demo/001-demo-widget": "ready"}}), "spec.md"))
    check("a BACKLOG item cannot be dragged",
          raises(lambda: resolve({"stage": {"backlog:demo/BL-20261001-02": "ready"}}), "BACKLOG.md"))
    check("an issue with an open PR can only be parked",
          raises(lambda: resolve({"stage": {f"issue:{HUB}#14": "ready"}}), "cannot move"))
    check("an unknown key is refused", raises(lambda: resolve({"priority": {"issue:x/y#1": "P0"}}), "not on the board"))
    check("an unknown plan field is refused", raises(lambda: resolve({"merge": True}), "unknown plan"))
    check("a pin outside its lane is refused",
          raises(lambda: resolve({"pins": {"ready": [f"issue:{HUB}#10"]}}), "not in lane"))
    check("a roadmap spec always keeps a priority",
          raises(lambda: resolve({"priority": {"roadmap:FF-0001": None}}), "always has a priority"))
    check("declining a roadmap spec needs a reason",
          raises(lambda: resolve({"roadmap_status": {"FF-0001": "declined"}}), "reason"))

    r = resolve({"stage": {"issue:bamr87/demo#13": "ready", "roadmap:FF-0001": "ready"},
                 "priority": {"roadmap:FF-0002": "P0", "backlog:demo/BL-20261011-01": "P1"},
                 "pins": {"ready": ["issue:bamr87/demo#13"]}})
    check("an issue move is a label change", r["labels"] == [{
        "key": "issue:bamr87/demo#13", "nwo": "bamr87/demo", "number": 13, "from": "blocked", "to": "ready",
        "add": ["agent:ready"], "remove": ["agent:blocked"]}], str(r["labels"]))
    check("a roadmap move and priority land in roadmap.yml",
          r["roadmap"] == {"FF-0001": {"status": "approved"}, "FF-0002": {"priority": "P0"}}, str(r["roadmap"]))
    check("a BACKLOG priority lands in work_queue.yml", r["queue"]["priority"] == {"backlog:demo/BL-20261011-01": "P1"})
    check("a moved issue can be pinned in its new lane", r["queue"]["pins"] == {"ready": ["issue:bamr87/demo#13"]})
    check("every change is described", len(r["changes"]) == 5, str([c["what"] for c in r["changes"]]))

    for stage, lane, add, remove in (("intake", "ready", ["agent:ready"], ["agent:blocked"]),
                                     ("blocked", "triage", [], ["agent:ready", "agent:blocked"]),
                                     ("ready", "hold", ["agent:hold"], []),
                                     ("hold", "ready", ["agent:ready"], ["agent:blocked", "agent:hold"])):
        a, rm = wb.label_move(stage, lane, state)
        labels = [lb for lb in ({"intake": [], "ready": ["agent:ready"], "blocked": ["agent:blocked"],
                                 "hold": ["agent:hold"]}[stage]) if lb not in rm] + a
        check(f"{stage} → {lane}: +{a} −{rm} reads back as {lane}",
              (a, rm) == (add, remove) and wb.ISSUE_LANE[ip.classify_stage(labels, inp["cfg"], has_open_pr=False)] == lane)


def test_roadmap_edit():
    print("\n_data/roadmap.yml: one line changes, every other byte survives")
    new = wb.edit_roadmap(ROADMAP, "FF-0001", status="approved", priority="P0")
    changed = [(a, b) for a, b in zip(ROADMAP.splitlines(), new.splitlines()) if a != b]
    check("exactly the two lines change", changed == [("  status: proposed", "  status: approved"),
                                                      ("  priority: P2", "  priority: P0")], str(changed))
    check("the header and the folded prose survive", new.startswith("# ====") and "    spans two lines." in new)
    other = [e for e in yaml.safe_load(new) if e["id"] == "FF-0002"][0]
    check("the next entry is untouched", other["status"] == "in-progress" and other["priority"] == "P1")
    declined = wb.edit_roadmap(ROADMAP, "FF-0002", status="declined", reason='not now: "later"')
    entry = [e for e in yaml.safe_load(declined) if e["id"] == "FF-0002"][0]
    check("declining writes a quoted reason under status", entry["reason"] == 'not now: "later"'
          and entry["status"] == "declined")
    check("an unknown id is refused", raises(lambda: wb.edit_roadmap(ROADMAP, "FF-0099", status="approved"), "not in"))
    check("an unknown status is refused", raises(lambda: wb.edit_roadmap(ROADMAP, "FF-0001", status="done"), "status"))


def test_degraded_inputs():
    print("\nboard: degraded inputs")
    root = fixture_root(with_backlog_list=False)
    doc = board(root, local=False)
    items = by_key(doc)
    check("without the full list, triage-only issues still appear", f"issue:{HUB}#15" in items)
    check("…with their label priority, said to be from a label",
          items[f"issue:{HUB}#15"]["priority"] == "P1" and items[f"issue:{HUB}#15"]["priority_source"] == "label")
    check("…and the board says the cut line is approximate",
          not doc["sources"]["issue_pipeline"]["full"] and any("approximate" in h["text"] for h in doc["hints"]))
    picks = sorted((it for it in doc["items"] if it["loop"] == "t1" and it["next_run"]), key=lambda it: it["next_run"])
    derived = [it["detail"]["derived"] for it in picks]
    check("an unscored issue only fills slots the scored ones leave",
          derived == sorted(derived) and any(derived), str([(it["key"], it["next_run"]) for it in picks]))

    empty = Path(tempfile.mkdtemp(prefix="work-board-empty-"))
    (empty / "_data").mkdir()
    doc = board(empty, local=True)
    check("a hub with no data files builds an empty board", doc["totals"]["items"] == 0 and len(doc["lanes"]) == 6)

    moved_at = "2026-10-27T12:00:00+00:00"
    doc = board(fixture_root(), local=False, moves={"issue:bamr87/demo#13": {"lane": "ready", "at": moved_at}})
    it = by_key(doc)["issue:bamr87/demo#13"]
    check("a label move newer than the snapshot shows in its new lane", it["lane"] == "ready" and not it["moved"]["pending"])
    old = board(fixture_root(), local=False,
                moves={"issue:bamr87/demo#13": {"lane": "ready", "at": "2026-10-01T00:00:00+00:00"}})
    check("…and one older than the snapshot does not", by_key(old)["issue:bamr87/demo#13"]["lane"] == "blocked")

    bad = fixture_root()
    (bad / "_data" / "work_queue.yml").write_text("order: [1, 'issue:bamr87/noisy#1']\npriority: {x: P0}\n")
    doc = board(bad, local=False)
    check("a hand-edited queue with junk still builds", by_key(doc)["issue:bamr87/noisy#1"]["rank"] == 0)
    check("…and reports the junk", any("dropped" in h["text"] for h in doc["hints"]))


def test_item_detail():
    print("\ndrill-down")
    root = fixture_root()
    inp = wb.load_inputs(root, local=True, now=NOW)
    d = wb.item_detail(inp, "spec:demo/001-demo-widget")
    check("a spec's drill-down carries its task list and text",
          [t["state"] for t in d["spec"]["task_list"]] == ["done", "doing", "todo"] and "# Spec:" in d["spec"]["markdown"])
    check("…its open-question line", d["spec"]["open_question_lines"] == ["OPEN QUESTION OQ-1: which colour?"])
    d = wb.item_detail(inp, "roadmap:FF-0001")
    check("a roadmap drill-down carries the whole entry", d["entry"]["proposal"] == "Do it.")
    d = wb.item_detail(inp, "backlog:demo/BL-20260901-01")
    check("a backlog drill-down names the claiming spec", d["backlog"]["claimed_by"] == "specs/001-demo-widget")
    check("an unknown key is refused", raises(lambda: wb.item_detail(inp, "issue:a/b#1"), "not on the board"))
    check("a malformed key is refused", raises(lambda: wb.item_detail(inp, "../etc"), "not a work key"))
    check("a spec path outside the root is refused", raises(lambda: wb.spec_detail(root, "../../etc"), "no such"))


def test_evolution_brief():
    print("\nrepo-evolution: the brief carries the repo's own pins")
    queue = {**wq.empty(), "updated_at": "2026-10-27",
             "order": ["backlog:demo/BL-20261001-02", "issue:bamr87/other#3", "issue:bamr87/demo#12"],
             "priority": {"spec:demo/001-demo-widget": "P0"}, "notes": {"backlog:demo/BL-20261001-02": "tests first"}}
    text = ev.render_hub_order(queue, {"nwo": "bamr87/demo", "name": "demo"})
    check("the repo's pins, in order, with the note",
          text.index("BL-20261001-02") < text.index("bamr87/demo#12") and "tests first" in text)
    check("another repo's pin is not listed", "bamr87/other#3" not in text)
    check("an override without a pin is listed", "spec:demo/001-demo-widget` · priority P0" in text)
    check("issues stay the pipeline's lane", "do not implement it" in text)
    check("nothing pinned says so", "has not pinned" in ev.render_hub_order(wq.empty(), {"nwo": "a/b", "name": "b"}))


def main() -> int:
    print("work_board / work_queue fixture tests")
    test_work_queue_file()
    test_pipeline_honours_order()
    test_board_lanes_and_sources()
    test_board_cut_line_is_the_pipelines()
    test_plans_refuse_what_they_cannot_do()
    test_roadmap_edit()
    test_degraded_inputs()
    test_item_detail()
    test_evolution_brief()
    print()
    if FAILURES:
        print(f"FAILED — {len(FAILURES)} check(s):")
        for f in FAILURES:
            print(f"  · {f}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
