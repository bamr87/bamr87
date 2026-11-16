#!/usr/bin/env python3
"""
Fixture tests for issue_pipeline.py — the three-tier issue pipeline's queue builder.

Guards the invariants that decide whether the pipeline is useful or a nuisance:

  * an issue with an OPEN pipeline PR is at tier 3, never tier 1 — otherwise the
    intake tier re-triages work that is already in review, every single run;
  * `agent:hold` and `human-review` must be honoured everywhere, because they are
    the only brakes a human has and they must not need tooling to pull;
  * a green, non-draft pipeline PR must leave the tier-3 queue, or the loop never
    converges and re-reviews the same PR forever;
  * the caps must hold, and the cross-repo sub-cap must not starve hub work;
  * gap detection must distinguish gaps an AGENT can close (evidence, labels,
    scope) from gaps only a HUMAN can (ambiguous intent) — that distinction is
    the whole difference between `agent:ready` and `agent:blocked`;
  * the per-repo sweep must survive a repo with NO open pull requests — slicing
    an empty PyGithub PaginatedList raises IndexError, which silently dropped
    such repos (and every open issue they held) from the pipeline entirely;
  * a config override in _data/fleet.yml must MERGE with the defaults, not
    replace them: a fleet.yml that sets one cap must not silently delete the
    label taxonomy the agents apply.

Deliberately dependency-light — no network, no gh, no pytest. Needs only PyYAML:

    python3 .github/scripts/dash-gen/test_issue_pipeline.py
"""

from __future__ import annotations

import inspect
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import issue_pipeline as ip  # noqa: E402

HUB = "bamr87/bamr87"
CFG = ip.DEFAULT_CONFIG
STATE = CFG["labels"]["state"]


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
def issue(number, *, title="Something is broken", body="", labels=(), stage=None,
          itype="bug", priority="P2", size="size:s", autonomy="auto",
          readiness=80, age=5, assignees=()):
    return {
        "number": number, "key": f"x#{number}", "title": title, "url": "u",
        "author": "a", "labels": list(labels), "assignees": list(assignees),
        "comments": 0, "age_days": age, "idle_days": age, "body_chars": len(body),
        "has_images": False, "stage": stage or "intake", "type": itype,
        "priority": priority, "priority_score": 50, "size": size,
        "autonomy": autonomy, "autonomy_reason": "test", "owner": "bamr87",
        "pr": None, "evidence": None, "gaps": [], "readiness": readiness,
        "_body": body,
    }


def pr(number, *, pipeline=True, draft=True, ci="fail", linked=(), labels=(),
       idle=1):
    return {
        "number": number, "title": f"fix: thing {number}", "url": "u",
        "draft": draft, "branch": f"agent/issue-{number}", "labels": list(labels),
        "linked_issues": list(linked), "pipeline": pipeline,
        "human_review": STATE["human_review"] in labels,
        "age_days": 3, "idle_days": idle, "ci": ci, "mergeable_state": "clean",
        "head_sha": "deadbee",
    }


def repo(nwo, *, issues=(), prs=(), category="dev-tools", status="active"):
    counts = {"intake": 0, "ready": 0, "in-pr": 0, "blocked": 0, "done": 0, "hold": 0}
    for i in issues:
        counts[i["stage"]] = counts.get(i["stage"], 0) + 1
    return {
        "nwo": nwo, "name": nwo.split("/")[-1],
        "repo_url": f"https://github.com/{nwo}", "category": category,
        "status": status, "default_branch": "main", "private": False,
        "stack": ["python"], "issues": list(issues), "prs": list(prs),
        "counts": counts,
    }


FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ok   {name}")
    else:
        FAILURES.append(f"{name}{': ' + detail if detail else ''}")
        print(f"  FAIL {name}{': ' + detail if detail else ''}")


# --------------------------------------------------------------------------- #
# stage classification — the label state machine
# --------------------------------------------------------------------------- #
def test_stages():
    print("\nstage classification")
    check("bare issue starts at intake",
          ip.classify_stage([], CFG, has_open_pr=False) == "intake")
    check("agent:ready moves to tier 2",
          ip.classify_stage([STATE["ready"]], CFG, has_open_pr=False) == "ready")
    check("agent:blocked leaves the agent queues",
          ip.classify_stage([STATE["blocked"]], CFG, has_open_pr=False) == "blocked")
    check("agent:hold wins over every other label",
          ip.classify_stage([STATE["hold"], STATE["ready"]], CFG,
                            has_open_pr=False) == "hold")
    check("agent:done is terminal",
          ip.classify_stage([STATE["done"]], CFG, has_open_pr=False) == "done")

    # The one that matters most: an open PR outranks a stale `agent:ready`
    # label. Without this the intake tier re-triages issues already in review.
    check("an open PR moves the issue to tier 3 even if still labelled ready",
          ip.classify_stage([STATE["ready"]], CFG, has_open_pr=True) == "in-pr")
    check("case-insensitive label match",
          ip.classify_stage(["Agent:Ready"], CFG, has_open_pr=False) == "ready")


# --------------------------------------------------------------------------- #
# type / priority / size
# --------------------------------------------------------------------------- #
def test_classification():
    print("\ntype / priority / size")
    types = CFG["labels"]["types"]
    check("an existing type label wins over keywords",
          ip.detect_type("add a feature", "", ["docs"], types) == "docs")
    check("'enhancement' maps to feature",
          ip.detect_type("x", "", ["enhancement"], types) == "feature")
    check("security outranks bug when both match",
          ip.detect_type("crash leaks the API token", "", [], types) == "security")
    check("bug outranks feature when both match",
          ip.detect_type("add retry: the upload fails with a 500", "", [], types)
          == "bug")
    check("a workflow failure is typed ci, not bug",
          ip.detect_type("fix(repo/ci): the release workflow fails on tags", "",
                         [], types) == "ci")

    # Regression: a 6 KB body quoting workflow YAML must not retype the issue.
    # Matching over title+body concatenated made every fleet-doctor ticket that
    # mentioned `secrets.FLEET_TOKEN` a P0 security issue needing human review.
    noisy_body = (
        "The Translate job discards good output.\n\n```yaml\n"
        "  env:\n    KEY: ${{ secrets.FLEET_TOKEN }}\n"
        "    OTHER: ${{ secrets.ANTHROPIC_API_KEY }}\n```\n"
        "Credentials are fine; the validation step is the problem.\n" * 20)
    check("a body quoting secrets does not make it a security issue",
          ip.detect_type("Translate discards 49 good translations when 1 page "
                         "fails validation", noisy_body, [], types) != "security",
          ip.detect_type("Translate discards 49 good translations when 1 page "
                         "fails validation", noisy_body, [], types))
    check("a genuine leak report is still security",
          ip.detect_type("CI log leaked the deploy token", "", [], types)
          == "security")
    check("the body still decides when the title is uninformative",
          ip.detect_type("follow-up", "the docs are out of date", [], types)
          == "docs")
    check("questions are detected",
          ip.detect_type("How do I run the dash locally?", "", [], types) == "question")

    prios = CFG["labels"]["priorities"]
    urgent = ip.score_priority(itype="security", title="production data loss",
                               body="", age=1, comments=4, reactions=3,
                               repo_status="active", repo_red=True)
    trivial = ip.score_priority(itype="chore", title="bump a dev dep", body="",
                                age=1, comments=0, reactions=0,
                                repo_status="experiment", repo_red=False)
    check("a security outage scores P0", ip.priority_label(urgent, prios) == "P0",
          f"score={urgent}")
    check("a chore on an experiment scores P3",
          ip.priority_label(trivial, prios) == "P3", f"score={trivial}")
    check("priority is bounded to 0..100", 0 <= urgent <= 100)
    check("a red repo raises a bug's priority",
          ip.score_priority(itype="bug", title="t", body="", age=1, comments=0,
                            reactions=0, repo_status="active", repo_red=True)
          > ip.score_priority(itype="bug", title="t", body="", age=1, comments=0,
                              reactions=0, repo_status="active", repo_red=False))

    sizes = CFG["labels"]["sizes"]
    check("a typo is xs",
          ip.estimate_size(title="fix typo in README", body="", itype="docs",
                           sizes=sizes) == "size:xs")
    check("a fleet-wide rewrite is xl",
          ip.estimate_size(
              title="rewrite the fleet-wide auth layer",
              body="migrate every repo: tools/a.py tools/b.py tools/c.py "
                   "tools/d.py tools/e.py tools/f.py",
              itype="refactor", sizes=sizes) == "size:xl")
    check("size never falls off the taxonomy",
          ip.estimate_size(title="rewrite everything", body="x" * 5000,
                           itype="feature", sizes=sizes) in sizes)


# --------------------------------------------------------------------------- #
# gaps — what T1 must close, and who can close it
# --------------------------------------------------------------------------- #
GOOD_BUG = """
## Steps to reproduce
1. Run `tools/dash triage`
2. Observe the traceback

```
Traceback (most recent call last):
  File "tools/dash", line 12
ERROR: boom
```

Expected: the snapshot is written.
Actual: it raises instead.

Environment: python 3.12.1 on ubuntu 24.04, commit abc1234.

## Acceptance criteria
- [ ] `tools/dash triage` exits 0
- [ ] a regression test covers it

See https://example.com/docs and `.github/scripts/dash-gen/fleet_triage.py`.
"""


def test_gaps():
    print("\ngap detection")
    gaps = ip.detect_gaps(title="dash triage crashes", body=GOOD_BUG,
                          labels=["bug", "P1", "size:s"], itype="bug",
                          has_assignee=True, has_evidence=True, cfg=CFG)
    ids = {g["id"] for g in gaps}
    check("a complete bug report has no content gaps",
          not (ids - {"no-evidence"}), f"unexpected: {sorted(ids)}")
    check("a complete report is ready", ip.readiness(gaps) >= CFG["readiness"]["min_score"],
          f"readiness={ip.readiness(gaps)}")

    empty = ip.detect_gaps(title="broken", body="", labels=[], itype="bug",
                           has_assignee=False, has_evidence=False, cfg=CFG)
    eids = {g["id"] for g in empty}
    for expected in ("no-body", "no-repro", "no-acceptance", "no-scope",
                     "no-type-label", "no-priority-label", "no-evidence"):
        check(f"an empty report reports {expected}", expected in eids)
    check("an empty report is not ready",
          ip.readiness(empty) < CFG["readiness"]["min_score"],
          f"readiness={ip.readiness(empty)}")
    check("a one-word title with no body needs a human",
          any(g["by"] == "human" for g in empty))

    # A thin body with a descriptive title is the agent's problem, not a human's:
    # it can read the code and the evidence run and write the spec itself.
    thin = ip.detect_gaps(
        title="tools/dash triage exits 1 when _data/fleet_triage.yml is absent",
        body="", labels=[], itype="bug", has_assignee=False,
        has_evidence=False, cfg=CFG)
    check("a descriptive title makes the missing body agent-closable",
          all(g["by"] == "agent" for g in thin),
          f"human gaps: {[g['id'] for g in thin if g['by'] == 'human']}")

    check("every gap says who closes it and how",
          all(g["by"] in ("agent", "human") and g["what"] and g["how"]
              for g in empty))
    check("readiness is clamped at 0", ip.readiness(empty) >= 0)


# --------------------------------------------------------------------------- #
# autonomy
# --------------------------------------------------------------------------- #
def test_autonomy():
    print("\nautonomy gates")
    a, _ = ip.decide_autonomy(itype="bug", size="size:s", prio="P2",
                              labels=[], cfg=CFG)
    check("an ordinary bug is autonomous", a == "auto")
    a, why = ip.decide_autonomy(itype="bug", size="size:s", prio="P2",
                                labels=[STATE["human_review"]], cfg=CFG)
    check("the human-review tag downgrades to assisted", a == "assisted", why)
    a, _ = ip.decide_autonomy(itype="bug", size="size:s", prio="P2",
                              labels=[STATE["hold"]], cfg=CFG)
    check("agent:hold blocks entirely", a == "blocked")
    a, _ = ip.decide_autonomy(itype="security", size="size:s", prio="P1",
                              labels=[], cfg=CFG)
    check("security never lands unattended", a == "assisted")
    a, _ = ip.decide_autonomy(itype="feature", size="size:xl", prio="P2",
                              labels=[], cfg=CFG)
    check("an xl issue never lands unattended", a == "assisted")


# --------------------------------------------------------------------------- #
# queue construction and caps
# --------------------------------------------------------------------------- #
def test_queues():
    print("\nqueue selection and caps")
    cfg = ip.deep_merge(CFG, {"tiers": {
        "intake": {"max_issues": 4, "max_per_repo": 2},
        "implement": {"max_issues": 3, "max_cross_repo": 1},
        "complete": {"max_prs": 2}}})

    noisy = repo("bamr87/noisy", issues=[issue(n) for n in range(1, 9)])
    quiet = repo("bamr87/quiet", issues=[issue(20), issue(21)])
    q = ip.build_queues([noisy, quiet], cfg)
    check("intake respects the global cap", len(q["intake"]) == 4,
          str(len(q["intake"])))
    per_repo = sum(1 for c in q["intake"] if c["nwo"] == "bamr87/noisy")
    check("intake respects the per-repo cap", per_repo == 2, str(per_repo))
    check("the per-repo cap leaves room for other repos",
          {c["nwo"] for c in q["intake"]} == {"bamr87/noisy", "bamr87/quiet"})

    # Cross-repo sub-cap: a burst of submodule work must not starve hub work.
    hub = repo(HUB, issues=[issue(n, stage="ready") for n in (1, 2)])
    subs = [repo(f"bamr87/s{i}", issues=[issue(9, stage="ready")]) for i in range(4)]
    q = ip.build_queues([*subs, hub], cfg)
    impl = q["implement"]
    check("implement respects the global cap", len(impl) <= 3, str(len(impl)))
    check("implement respects the cross-repo sub-cap",
          sum(1 for c in impl if c["nwo"] != HUB) == 1)
    check("hub work is not starved by a submodule burst",
          sum(1 for c in impl if c["nwo"] == HUB) == 2)

    # Priority ordering, then readiness. Staged in the HUB repo so the
    # cross-repo sub-cap (which counts PRs opened outside the hub, not repos)
    # doesn't truncate the queue being ordered.
    mixed = repo(HUB, issues=[
        issue(1, stage="ready", priority="P3", readiness=99),
        issue(2, stage="ready", priority="P0", readiness=40),
        issue(3, stage="ready", priority="P1", readiness=90),
    ])
    order = [c["number"] for c in ip.build_queues([mixed], cfg)["implement"]]
    check("queues are ordered by priority first", order == [2, 3, 1], str(order))
    hi_lo = repo(HUB, issues=[
        issue(1, stage="ready", priority="P1", readiness=30),
        issue(2, stage="ready", priority="P1", readiness=95),
    ])
    order = [c["number"] for c in ip.build_queues([hi_lo], cfg)["implement"]]
    check("readiness breaks priority ties", order == [2, 1], str(order))

    # Blocked / hold / done never reach an agent queue.
    parked = repo("bamr87/p", issues=[
        issue(1, stage="blocked"), issue(2, stage="hold"), issue(3, stage="done"),
        issue(4, stage="intake", autonomy="blocked"),
    ])
    q = ip.build_queues([parked], cfg)
    check("parked issues never reach a queue",
          not q["intake"] and not q["implement"],
          f"{q['intake']} {q['implement']}")


def dep_issue(nwo, number, **kw):
    """An issue fixture keyed like collect_repo keys it (owner/repo#n)."""
    i = issue(number, **kw)
    i["key"] = ip.issue_key(nwo, number)
    i["blocked_by"] = ip.parse_dependency_refs(i["_body"], nwo)
    return i


def test_dependencies():
    print("\ndependencies — prerequisites before dependents")
    # (f) parsing
    body = ("Blocked by #12\nDEPENDS ON bamr87/other#3, #4 and bamr87/x#5\n"
            "depends on: #12\n\n```\nBlocked by #99\n```\n~~~\ndepends on #98\n~~~\n"
            "Mentions #77 without a phrase.")
    refs = ip.parse_dependency_refs(body, "bamr87/x")
    check("(f) Blocked by / Depends on accept #n and owner/repo#n, any case; dupes dropped",
          refs == ["bamr87/x#12", "bamr87/other#3", "bamr87/x#4", "bamr87/x#5"], str(refs))
    check("(f) refs inside code fences are ignored",
          "bamr87/x#99" not in refs and "bamr87/x#98" not in refs, str(refs))
    check("(f) a bare mention is not a dependency", "bamr87/x#77" not in refs)

    cfg = ip.deep_merge(CFG, {"tiers": {"implement": {"max_issues": 5, "max_cross_repo": 5}}})

    # (a) open blocker keeps a ready issue off T2, with the reason
    blocker = dep_issue(HUB, 12, stage="intake", priority="P2")
    dependent = dep_issue(HUB, 13, stage="ready", priority="P1", readiness=99,
                          body="Blocked by #12")
    r = repo(HUB, issues=[blocker, dependent])
    summary = ip.resolve_dependencies([r], cfg)
    impl = [c["number"] for c in ip.build_queues([r], cfg)["implement"]]
    check("(a) an issue with an open blocker is not on the T2 ready queue", 13 not in impl, str(impl))
    check("(a) …and carries the reason",
          dependent["deps_reason"] == f"blocked by {HUB}#12", str(dependent["deps_reason"]))
    check("(a) the blocker counts its open dependent",
          blocker["open_dependents"] == 1 and blocker["dep_boost"] == 1)
    check("(a) the run summary counts the held issue", summary["blocked"] == 1, str(summary))

    # (b) prerequisite sorts ahead of a same-priority, same-readiness peer
    prereq = dep_issue(HUB, 20, stage="ready", priority="P2", readiness=80, age=1)
    peer = dep_issue(HUB, 21, stage="ready", priority="P2", readiness=80, age=50)
    waiting = dep_issue(HUB, 22, stage="intake", body="Depends on #20")
    r = repo(HUB, issues=[peer, prereq, waiting])
    ip.resolve_dependencies([r], cfg)
    impl = [c["number"] for c in ip.build_queues([r], cfg)["implement"]]
    check("(b) a prerequisite sorts ahead of a same-priority peer (despite being younger)",
          impl[:2] == [20, 21], str(impl))
    hi = dep_issue(HUB, 23, stage="ready", priority="P1", readiness=80)
    r = repo(HUB, issues=[peer, prereq, waiting, hi])
    ip.resolve_dependencies([r], cfg)
    impl = [c["number"] for c in ip.build_queues([r], cfg)["implement"]]
    check("(b) the boost never crosses a priority band", impl[0] == 23, str(impl))
    many = [dep_issue(HUB, 100 + n, stage="intake", body="blocked by #20") for n in range(9)]
    r = repo(HUB, issues=[prereq, *many])
    ip.resolve_dependencies([r], ip.deep_merge(cfg, {"dependencies": {"boost_cap": 2}}))
    check("(b) the boost is bounded by dependencies.boost_cap",
          prereq["open_dependents"] == 9 and prereq["dep_boost"] == 2,
          f"{prereq['open_dependents']} / {prereq['dep_boost']}")

    # (c) a pinned rank still sorts first
    pinned = dep_issue(HUB, 30, stage="ready", priority="P3", readiness=10)
    pinned["rank"] = 0
    r = repo(HUB, issues=[peer, prereq, waiting, pinned])
    ip.resolve_dependencies([r], cfg)
    impl = [c["number"] for c in ip.build_queues([r], cfg)["implement"]]
    check("(c) a pinned rank still sorts first", impl[0] == 30, str(impl))

    # (d) a 2-cycle is detected, reported, terminates, and both stay off T2
    a = dep_issue(HUB, 40, stage="ready", body="Blocked by #41")
    b = dep_issue(HUB, 41, stage="ready", body="Blocked by #40")
    r = repo(HUB, issues=[a, b])
    summary = ip.resolve_dependencies([r], cfg)
    impl = [c["number"] for c in ip.build_queues([r], cfg)["implement"]]
    check("(d) a 2-cycle is reported", len(summary["cycles"]) == 1
          and set(summary["cycles"][0]) == {f"{HUB}#40", f"{HUB}#41"}, str(summary["cycles"]))
    check("(d) both cycle members say so",
          all((x["deps_reason"] or "").startswith("dependency cycle:") for x in (a, b)),
          f"{a['deps_reason']} / {b['deps_reason']}")
    check("(d) both cycle members stay off the T2 ready queue", 40 not in impl and 41 not in impl, str(impl))
    self_ref = dep_issue(HUB, 42, stage="ready", body="Blocked by #42")
    ip.resolve_dependencies([repo(HUB, issues=[self_ref])], cfg)
    check("(d) a self-reference is ignored, not a cycle", not self_ref["open_blockers"])

    # (e) a closed blocker does not block
    closed_dep = dep_issue(HUB, 50, stage="ready", body="Blocked by #49")   # #49 not open in a scanned repo
    ext_dep = dep_issue(HUB, 51, stage="ready", body="Blocked by bamr87/elsewhere#7")
    asked: list[str] = []

    def lookup(key):
        asked.append(key)
        return "closed"
    r = repo(HUB, issues=[closed_dep, ext_dep])
    summary = ip.resolve_dependencies([r], cfg, lookup=lookup)
    impl = [c["number"] for c in ip.build_queues([r], cfg)["implement"]]
    check("(e) a closed blocker in a scanned repo does not block (and costs no request)",
          50 in impl and f"{HUB}#49" not in asked, f"{impl} {asked}")
    check("(e) a ref outside the sweep is looked up, and closed does not block",
          asked == ["bamr87/elsewhere#7"] and 51 in impl, f"{asked} {impl}")
    unk = dep_issue(HUB, 52, stage="ready", body="Blocked by bamr87/elsewhere#8")
    summary = ip.resolve_dependencies([repo(HUB, issues=[unk])],
                                      ip.deep_merge(cfg, {"dependencies": {"max_lookups": 0}}),
                                      lookup=lookup)
    check("lookups stop at dependencies.max_lookups; an unresolved ref never blocks",
          not unk["open_blockers"] and summary["unresolved"] == ["bamr87/elsewhere#8"]
          and summary["lookups"] == 0, str(summary))

    # native GitHub links: only fetched when the payload counts some; errors degrade to body refs
    nat = dep_issue(HUB, 60, stage="ready")
    nat["_native_blocked"] = 1
    plain = dep_issue(HUB, 61, stage="ready", body="Blocked by #62")
    plain["_native_blocked"] = 1
    other = dep_issue(HUB, 62, stage="intake")
    fetched: list[str] = []

    def native(key):
        fetched.append(key)
        if key.endswith("#61"):
            raise RuntimeError("404")
        return [("bamr87/elsewhere#9", "open")]
    r = repo(HUB, issues=[nat, plain, other])
    ip.resolve_dependencies([r], cfg, native=native)
    check("a native blocked-by link holds the issue back",
          nat["open_blockers"] == ["bamr87/elsewhere#9"], str(nat["open_blockers"]))
    check("a failed native fetch keeps the body refs",
          plain["open_blockers"] == [f"{HUB}#62"], str(plain["open_blockers"]))
    check("native links are only fetched for issues whose payload counts some",
          sorted(fetched) == [f"{HUB}#60", f"{HUB}#61"], str(fetched))
    off = dep_issue(HUB, 70, stage="ready", body="Blocked by #71")
    ip.resolve_dependencies([repo(HUB, issues=[off, dep_issue(HUB, 71)])],
                            ip.deep_merge(cfg, {"dependencies": {"enabled": False}}))
    check("dependencies.enabled: false turns the hold off", not off["open_blockers"])

    row = ip.backlog_list([repo(HUB, issues=[dependent, blocker])])[0]
    check("the backlog snapshot carries the dependency fields",
          all(k in row[0] for k in ("blocked_by", "open_blockers", "open_dependents", "deps_reason")))


def test_tier3_queue():
    print("\ntier 3 queue")
    cfg = ip.deep_merge(CFG, {"tiers": {"complete": {"max_prs": 3}}})
    r = repo("bamr87/x", prs=[
        pr(1, ci="fail", draft=True, linked=[10]),
        pr(2, ci="pass", draft=False, linked=[11]),        # finished
        pr(3, ci="pass", draft=True, linked=[12]),         # green but still draft
        pr(4, pipeline=False, ci="fail", draft=False),     # not ours
        pr(5, ci="pending", draft=True, idle=9),
    ])
    q = ip.build_queues([r], cfg)["complete"]
    nums = [p["number"] for p in q]
    check("a green non-draft PR leaves the queue (the loop converges)",
          2 not in nums, str(nums))
    check("a PR the pipeline did not open is never touched", 4 not in nums, str(nums))
    check("a green draft still needs finishing", 3 in nums, str(nums))
    check("red CI sorts first", nums and nums[0] == 1, str(nums))
    check("tier 3 respects its cap", len(q) <= 3, str(len(q)))


# --------------------------------------------------------------------------- #
# an expedite sprint's tier gate (tools/jev/sprints.py, #689)
# --------------------------------------------------------------------------- #
SPRINT_REPO = "bash-365/bash-365.com"
SITES = {"issue-pipeline.yml:tier1": 40, "issue-pipeline.yml:tier2": 60, "issue-pipeline.yml:tier3": 60}


def sprint_fleet(usd: float, *, declared: str = "2026-11-20T15:00:00Z", hours: float = 72) -> dict:
    return {"budget": {"call_sites": dict(SITES), "sprints": {"pilot": {
                "item": f"issue:{SPRINT_REPO}#1", "usd": usd, "hours": hours, "declared": declared}}},
            "harnesses": {"budget": {"monthly_ai_usd": 200}}}


def sprint_gate(usd: float, spent: float, *, env: dict | None = None, scheduled: bool = False,
                now: str = "2026-11-20T18:00:00+00:00", run_tiers: str = "123", grant: str | None = None,
                record_run: str = "", carried: list | None = None, **kw):
    sp = ip.jev_module("sprints")
    doc = sprint_fleet(usd, **kw)
    hold = ip.SprintHold(sp, sp.load_sprints(doc), caps=dict(SITES), now=ip.dt.datetime.fromisoformat(now),
                         switch=sp.once(lambda: sp.read_switch(scheduled=scheduled, env=env or {})),
                         spend_of=lambda s: sp.Spend(spent_usd=spent), run_tiers=run_tiers, grant=grant,
                         record_run=record_run)
    hold.carried = list(carried or [])
    return hold


def sprint_repos():
    """The sprint's repo with one issue at each tier, and a repo outside it."""
    def sissue(n, stage):
        i = issue(n, stage=stage)
        i["key"] = f"{SPRINT_REPO}#{n}"
        return i
    inside = repo(SPRINT_REPO, issues=[sissue(1, "ready"), sissue(2, "intake")], prs=[pr(3)])
    outside = repo("bamr87/quiet", issues=[issue(20, stage="ready"), issue(21)], prs=[pr(22)])
    return [inside, outside]


def test_sprint_gate():
    print("\nexpedite sprint tier gate")
    cfg = ip.deep_merge(CFG, {"hub": HUB})

    def keys(q):
        return {k: sorted(f"{c['nwo']}#{c['number']}" for c in v) for k, v in q.items()}

    roomy = sprint_gate(usd=180, spent=0)
    q = ip.build_queues(sprint_repos(), cfg, roomy)
    check("inside its ceiling every sprint item is queued",
          f"{SPRINT_REPO}#1" in keys(q)["implement"] and f"{SPRINT_REPO}#2" in keys(q)["intake"]
          and f"{SPRINT_REPO}#3" in keys(q)["complete"], str(keys(q)))
    check("each tier with a sprint item reserves its full cap once", roomy.reserved == 160.0, str(roomy.reserved))

    capped = sprint_gate(usd=30, spent=22.5)
    q = ip.build_queues(sprint_repos(), cfg, capped)
    flat = sum(keys(q).values(), [])
    check("a sprint at its cap queues none of its items (budget-skip)",
          not [k for k in flat if k.startswith(SPRINT_REPO)], str(flat))
    check("…and the rest of the fleet is untouched",
          {"bamr87/quiet#20", "bamr87/quiet#21", "bamr87/quiet#22"} <= set(flat), str(flat))
    check("every held item says budget-skip",
          capped.held and {h["decision"] for h in capped.held} == {"budget-skip"}, str(capped.held))
    check("the circuit breaker is recorded once, as a stop event",
          [e["event"] for e in capped.events] == ["sprint-stop"] and capped.events[0]["cap_usd"] == 30.0,
          str(capped.events))
    rep = capped.report()
    check("the snapshot carries the sprint, its spend and what it held",
          rep["active"]["slug"] == "pilot" and rep["spent_usd"] == 22.5 and len(rep["held"]) == 3
          and "API-equivalent" in rep["label"], str(rep))

    tight = sprint_gate(usd=90, spent=0)
    q = ip.build_queues(sprint_repos(), cfg, tight)
    check("tiers reserve in order: T1's $40 fits $90, then T2's $60 does not",
          f"{SPRINT_REPO}#2" in keys(q)["intake"] and f"{SPRINT_REPO}#1" not in keys(q)["implement"]
          and f"{SPRINT_REPO}#3" not in keys(q)["complete"] and tight.reserved == 40.0,
          f"{keys(q)} reserved={tight.reserved}")

    off = sprint_gate(usd=180, spent=0, scheduled=True, env={"EXPEDITE_SPRINT_ENABLED": "false"})
    q = ip.build_queues(sprint_repos(), cfg, off)
    flat = sum(keys(q).values(), [])
    check("the sprint switch holds every sprint item on a schedule (sprint-off)",
          not [k for k in flat if k.startswith(SPRINT_REPO)] and {h["decision"] for h in off.held} == {"sprint-off"},
          f"{flat} {off.held}")
    check("…and a held item takes no slot", off.reserved == 0 and "bamr87/quiet#20" in flat, str(flat))
    manual = sprint_gate(usd=180, spent=0, scheduled=False, env={"EXPEDITE_SPRINT_ENABLED": "false"})
    q = ip.build_queues(sprint_repos(), cfg, manual)
    check("a dispatch or a hand run bypasses the switch", f"{SPRINT_REPO}#1" in keys(q)["implement"], str(keys(q)))

    closed = sprint_gate(usd=180, spent=0, now="2026-11-24T00:00:00+00:00")
    q = ip.build_queues(sprint_repos(), cfg, closed)
    flat = sum(keys(q).values(), [])
    check("after the time box the declared item stays held, the repo's other work runs",
          f"{SPRINT_REPO}#1" not in flat and f"{SPRINT_REPO}#2" in flat and closed.reserved == 0
          and [h["key"] for h in closed.held] == [f"issue:{SPRINT_REPO}#1"], f"{flat} {closed.held}")

    check("no declared sprint, no gate (nothing under tools/jev is imported)",
          ip.sprint_hold({"budget": {"sprints": {}}}, cfg, now=ip.now_utc(), scheduled=True) is None)
    try:
        ip.sprint_hold(sprint_fleet(float("inf")), cfg, now=ip.now_utc(), scheduled=True)
        refused = False
    except RuntimeError as exc:
        refused = "budget.sprints.pilot.usd" in str(exc)
    check("a declaration that bounds nothing stops the scan", refused)


def one_sprint_issue(stage: str) -> list[dict]:
    """The sprint's repo with its declared issue, #1, at `stage`."""
    i = issue(1, stage=stage)
    i["key"] = f"{SPRINT_REPO}#1"
    return [repo(SPRINT_REPO, issues=[i], prs=[])]


def queued(q: dict) -> list[str]:
    return sorted(f"{c['nwo']}#{c['number']}" for v in q.values() for c in v)


def test_sprint_run():
    """One workflow run (the scan, then tier 2's re-scan in a new process), and
    the run after it: the reservations add up across both (review of #895)."""
    print("\nexpedite sprint: a whole run, then the next")
    cfg = ip.deep_merge(CFG, {"hub": HUB})
    sp = ip.jev_module("sprints")
    item = f"{SPRINT_REPO}#1"

    # The scan sees the issue at intake; tier 1 marks it agent:ready; tier 2's re-scan sees it ready.
    for usd, runs_in_tier2 in ((60, False), (99, False), (100, True), (160, True)):
        scan = sprint_gate(usd=usd, spent=0, record_run="77.1")
        ip.build_queues(one_sprint_issue("intake"), cfg, scan)
        out = scan.outputs()
        refresh = sprint_gate(usd=usd, spent=0, grant=out["sprint_t2_usd"])
        q = ip.build_queues(one_sprint_issue("ready"), cfg, refresh)
        ran = scan.by_tier.get("intake", 0.0) + scan.by_tier.get("complete", 0.0) + refresh.reserved
        check(f"${usd} ceiling: the scan at intake then the re-scan at ready reserve ${ran:g} in all, inside it",
              ran <= usd and scan.reserved <= usd and refresh.reserved <= float(out["sprint_t2_usd"]),
              f"scan={scan.by_tier} refresh={refresh.reserved}")
        check(f"${usd} ceiling: tier 2 {'runs' if runs_in_tier2 else 'holds'} the item tier 1 just made ready",
              (item in queued(q)) == runs_in_tier2
              and ([h["decision"] for h in refresh.held] == ([] if runs_in_tier2 else ["budget-skip"])),
              f"{queued(q)} {refresh.held}")
    check("the scan reserves tier 2's room for a sprint issue tier 1 is about to triage, and says so",
          out == {"sprint_reserved_usd": "100", "sprint_t1_usd": "40", "sprint_t2_usd": "60", "sprint_t3_usd": "0"},
          str(out))
    check("…which is the whole run's reservation", scan.reserved == 100.0, str(scan.reserved))
    refresh = sprint_gate(usd=180, spent=0, grant="60")
    q = ip.build_queues(sprint_repos(), cfg, refresh)
    check("the re-scan settles only tier 2: intake and tier 3 do not run again from it",
          refresh.by_tier == {"implement": 60.0} and f"{SPRINT_REPO}#2" in queued(q) and f"{SPRINT_REPO}#3" in queued(q),
          f"{refresh.by_tier} {queued(q)}")
    for bad in ("", "abc", "-1", "nan", "inf"):
        r = sprint_gate(usd=180, spent=0, grant=bad)
        q = ip.build_queues(one_sprint_issue("ready"), cfg, r)
        check(f"a re-scan handed {bad!r} runs no sprint item", item not in queued(q)
              and [h["decision"] for h in r.held] == ["budget-skip"], f"{queued(q)} {r.held}")

    dry = sprint_gate(usd=180, spent=0, run_tiers="", record_run="78.1")
    q = ip.build_queues(sprint_repos(), cfg, dry)
    check("a dry run starts no tier job, so it reserves and records nothing",
          dry.reserved == 0 and dry.records() == [] and set(dry.outputs().values()) == {"0"}
          and not dry.held, f"{dry.by_tier} {dry.records()}")
    only2 = sprint_gate(usd=180, spent=0, run_tiers="2")
    ip.build_queues(sprint_repos(), cfg, only2)
    check("a run of tier 2 alone reserves only tier 2", only2.by_tier == {"implement": 60.0}, str(only2.by_tier))

    # The record: the next run, and every other loop, counts what this run reserved.
    first = sprint_gate(usd=200, spent=0, record_run="77.1")
    ip.build_queues(one_sprint_issue("intake"), cfg, first)
    rows = first.records()
    check("a run that reserved records one row, an estimate under this declaration",
          len(rows) == 1 and rows[0]["run"] == "77.1" and rows[0]["usd"] == 100.0 and rows[0]["sprint"] == "pilot"
          and rows[0]["tiers"] == {"intake": 40.0, "implement": 60.0} and rows[0]["declared"] == "2026-11-20T15:00:00Z"
          and "API-equivalent" in rows[0]["label"], str(rows))
    text = ip.GENERATED_HEADER + ip.yaml.safe_dump({"sprint": first.report()}, sort_keys=False)
    back = sp.pipeline_rows(text=text, where="test")
    check("the published snapshot reads back as the same rows", back == rows, str(back))
    second = sprint_gate(usd=200, spent=0, record_run="78.1", carried=back, now="2026-11-21T18:00:00+00:00")
    q = ip.build_queues(one_sprint_issue("intake"), cfg, second)
    rep = second.report()
    check("the next run counts it as estimated spend, then reserves on top of it",
          rep["spent_usd"] == 100.0 and rep["estimated_usd"] == 100.0 and second.reserved == 100.0
          and item in queued(q), str(rep))
    third = sprint_gate(usd=200, spent=0, record_run="79.1", carried=second.records(),
                        now="2026-11-22T18:00:00+00:00")
    q = ip.build_queues(one_sprint_issue("intake"), cfg, third)
    check("two runs' reservations fill a $200 ceiling: the third run holds the item (budget-skip)",
          item not in queued(q) and [h["decision"] for h in third.held] == ["budget-skip"]
          and "$200.00 (200.00 estimated) of $200.00" in third.held[0]["reason"] and third.records() == second.records(),
          f"{third.held} {third.records()}")
    check("…and the stop is the run's circuit-breaker event", [e["event"] for e in third.events] == ["sprint-stop"],
          str(third.events))

    stale = dict(rows[0], sprint="retired")
    redeclared = dict(rows[0], run="70.1", declared="2026-11-01T00:00:00Z")
    tidy = sprint_gate(usd=200, spent=0, carried=[rows[0], dict(rows[0]), stale, redeclared])
    s = sp.active(tidy.sprints, tidy.now)
    check("one row per run of a declaration still in force is counted and carried on",
          [r["run"] for r in tidy.records()] == ["77.1"] and tidy.spent(s).spent_usd == 100.0,
          f"{tidy.records()} {tidy.spent(s).as_dict()}")
    late = sprint_gate(usd=200, spent=0, carried=rows, now="2026-11-24T00:00:00+00:00")
    check("a closed sprint's rows stay on record while it is declared", late.records() == rows, str(late.records()))
    bad = sprint_gate(usd=200, spent=0, carried=[dict(rows[0], usd=float("inf"))])
    q = ip.build_queues(one_sprint_issue("intake"), cfg, bad)
    check("a row that cannot be read holds the sprint's items rather than count it as $0",
          item not in queued(q) and "cannot be judged" in bad.held[0]["reason"], f"{bad.held}")

    with tempfile.TemporaryDirectory() as d:
        out_path = Path(d) / "issue_pipeline.yml"
        out_path.write_text(text)
        other = dict(rows[0], run="76.1")
        calls: list = []

        def fetch(hub, path, ref):
            calls.append((hub, path, ref))
            return {None: ip.yaml.safe_dump({"sprint": {"reservations": [rows[0], other]}}),
                    ip.PUBLISH_BRANCH: None}[ref]
        got = ip.sprint_records(out_path, hub=HUB, fetch=fetch)
        check("a scan reads the record from its checkout, the hub's default branch and the publish fallback branch",
              calls == [(HUB, "_data/issue_pipeline.yml", None), (HUB, "_data/issue_pipeline.yml", ip.PUBLISH_BRANCH)]
              and sorted(r["run"] for r in got) == ["76.1", "77.1", "77.1"], f"{calls} {got}")
        check("…and without a client, from its checkout alone",
              [r["run"] for r in ip.sprint_records(out_path)] == ["77.1"])

        def broken(hub, path, ref):
            raise OSError("HTTP Error 502")
        try:
            ip.sprint_records(out_path, hub=HUB, fetch=broken)
            raised = False
        except OSError:
            raised = True
        check("a branch that cannot be read raises (the scan stops), never reads as no rows", raised)
    check("the step outputs are all \"0\" when nothing is declared", set(ip.sprint_outputs().values()) == {"0"}
          and set(ip.sprint_outputs()) == {"sprint_reserved_usd", "sprint_t1_usd", "sprint_t2_usd", "sprint_t3_usd"})
    check("--sprint-grant never rewrites the snapshot (it reads no record to carry on)",
          ip.main(["--sprint-grant", "60"]) == 2)
    check("--run-tiers takes tier numbers", ip.main(["--no-snapshot", "--run-tiers", "all"]) == 2)


def test_sprint_workflow():
    """issue-pipeline.yml hands the scan's reservation to every tier that spends it."""
    print("\nexpedite sprint: the workflow's wiring")
    jobs = ip.yaml.safe_load((ip.REPO_ROOT / ".github/workflows/issue-pipeline.yml").read_text())["jobs"]
    steps = {s.get("id"): s for s in jobs["scan"]["steps"] if s.get("id")}
    check("the fallback branch a scan reads is the one it publishes to",
          steps["publish"]["with"]["branch"] == ip.PUBLISH_BRANCH, steps["publish"]["with"].get("branch"))
    check("the scan records its run attempt and the tiers it starts (none on a dry run)",
          "--record-run" in steps["queues"]["run"] and "GITHUB_RUN_ATTEMPT" in steps["queues"]["run"]
          and "--run-tiers" in steps["queues"]["run"] and "inputs.dry_run != true" in steps["queues"]["env"]["RUN_TIERS"])
    check("every sprint output the script emits leaves the scan job",
          set(ip.sprint_outputs()) | {"sprint_record"} <= set(jobs["scan"]["outputs"]), str(jobs["scan"]["outputs"]))
    gate = steps["sprint"]
    check("the record gate reads the publish route and runs even after a failed step",
          "steps.publish.outputs.mode" in gate["env"]["MODE"] and "cancelled()" in gate["if"]
          and "record=lost" in gate["run"] and "GITHUB_RUN_ATTEMPT" in gate["run"])
    refresh = next(s for s in jobs["tier2"]["steps"] if s.get("id") == "queue")
    check("tier 2's re-scan is handed the room the scan recorded for it, in this attempt only",
          '--sprint-grant "$SPRINT_GRANT"' in refresh["run"] and "--no-snapshot" in refresh["run"]
          and "needs.scan.outputs.sprint_t2_usd" in refresh["env"]["SPRINT_GRANT"]
          and "needs.scan.outputs.sprint_record == github.run_attempt" in refresh["env"]["SPRINT_GRANT"])
    for job, out in (("tier1", "sprint_t1_usd"), ("tier3", "sprint_t3_usd")):
        check(f"{job} runs a sprint item only in the attempt whose reservation is on record",
              f"needs.scan.outputs.{out} == '0'" in jobs[job]["if"]
              and "needs.scan.outputs.sprint_record == github.run_attempt" in jobs[job]["if"], jobs[job]["if"])


# --------------------------------------------------------------------------- #
# markers, links, config
# --------------------------------------------------------------------------- #
def test_markers_and_config():
    print("\nmarkers, links, config")
    m = ip.marker(2, "bamr87/x#7")
    found = ip.MARKER_RE.findall(f"{m}\n\nsome body text")
    check("a marker round-trips", found == [("2", "bamr87/x#7")], str(found))
    check("a marker is invisible in rendered markdown",
          m.startswith("<!--") and m.endswith("-->"))

    body = "Closes #12\nAlso fixes #13 and resolves #14. Mentions #99 only."
    check("Closes/fixes/resolves are linked, bare mentions are not",
          ip.linked_issue_numbers(body) == {12, 13, 14},
          str(ip.linked_issue_numbers(body)))

    merged = ip.deep_merge(CFG, {"tiers": {"intake": {"max_issues": 1}}})
    check("a partial override keeps sibling caps",
          merged["tiers"]["intake"]["max_per_repo"]
          == CFG["tiers"]["intake"]["max_per_repo"])
    check("a partial override keeps the label taxonomy",
          merged["labels"]["types"] == CFG["labels"]["types"])
    check("a partial override keeps other tiers",
          merged["tiers"]["complete"] == CFG["tiers"]["complete"])

    check("every taxonomy label has a colour and description",
          all(n in ip.LABEL_COLORS for n in [
              *CFG["labels"]["state"].values(), *CFG["labels"]["types"],
              *CFG["labels"]["priorities"], *CFG["labels"]["sizes"]]))


def test_real_fleet_config():
    """The shipped _data/fleet.yml must actually parse into a usable config."""
    print("\nshipped fleet.yml")
    cfg = ip.load_config(ip.FLEET)
    check("_data/fleet.yml declares the pipeline", cfg["enabled"] in (True, False))
    for tier, key in (("intake", "max_issues"), ("implement", "max_issues"),
                      ("complete", "max_prs")):
        check(f"tier {tier} has a numeric cap",
              isinstance(cfg["tiers"][tier][key], int) and cfg["tiers"][tier][key] > 0)
    check("state labels are complete",
          set(cfg["labels"]["state"]) == set(ip.DEFAULT_STATE_LABELS))
    check("every configured label has a colour",
          all(n in ip.LABEL_COLORS for n in [
              *cfg["labels"]["state"].values(), *cfg["labels"]["types"],
              *cfg["labels"]["priorities"], *cfg["labels"]["sizes"]]))
    check("the hub is the control-plane repo", cfg["hub"] == HUB, cfg["hub"])
    raw = (ip.load_yaml(ip.FLEET).get("issue_pipeline") or {}).get("dependencies") or {}
    check("_data/fleet.yml declares the dependency caps (not literals)",
          all(isinstance(raw.get(k), int) and raw[k] >= 0 for k in ("boost_cap", "max_lookups")),
          str(raw))


# --------------------------------------------------------------------------- #
# rendering — the work orders must never lie about an empty queue
# --------------------------------------------------------------------------- #
def test_render():
    print("\nwork-order rendering")
    counts = {"repos": 3, "open_issues": 9}
    for name, fn in (("T1", ip.render_t1), ("T2", ip.render_t2), ("T3", ip.render_t3)):
        empty = fn([], CFG, counts)
        check(f"{name} says plainly when there is nothing to do",
              "Nothing to" in empty and "Do not" in empty)

    c = issue(7, title="dash triage crashes", body=GOOD_BUG)
    c.update({"nwo": "bamr87/x", "repo": "x", "repo_url": "u", "category": "dash",
              "status": "active", "stack": ["python"], "private": False,
              "default_branch": "main", "needs_evidence": True,
              "gaps": ip.detect_gaps(title=c["title"], body=GOOD_BUG, labels=[],
                                     itype="bug", has_assignee=False,
                                     has_evidence=False, cfg=CFG)})
    out = ip.render_t1([c], CFG, counts)
    check("T1 embeds the verbatim marker", ip.marker(1, c["key"]) in out)
    check("T1 emits a runnable evidence command",
          "tools/issue-evidence.sh --repo bamr87/x --issue 7" in out)
    check("T1 states the ready/blocked exit condition",
          STATE["ready"] in out and STATE["blocked"] in out)

    c2 = dict(c, autonomy="assisted", autonomy_reason="human-review label")
    out2 = ip.render_t2([c2], CFG, counts)
    check("T2 requires the closing keyword", "Closes #7" in out2)
    check("T2 warns when a PR must not auto-advance", "Assisted" in out2)

    p = pr(4, linked=[7], labels=[STATE["human_review"]])
    p.update({"nwo": "bamr87/x", "repo": "x", "repo_url": "u",
              "default_branch": "main"})
    out3 = ip.render_t3([p], CFG, counts)
    check("T3 honours human-review in the prompt it hands the agent",
          "Do NOT mark it ready" in out3)
    check("T3 never instructs a merge", "gh pr merge" not in out3)


class FakePaginatedList:
    """The part of PyGithub's PaginatedList that matters here.

    Reproduces the trap: slicing returns a lazy `_Slice` that indexes element 0
    before the first page is fetched, so an EMPTY result set raises IndexError
    rather than yielding nothing. Iterating it plainly is safe.
    """

    def __init__(self, items):
        self._items = list(items)

    def __iter__(self):
        return iter(self._items)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return FakePaginatedList(self._items)._slice_iter()
        return self._items[index]  # IndexError when empty — the real bug

    def _slice_iter(self):
        # _Slice.__iter__ optimistically indexes 0 on a not-yet-fetched list.
        yield self[0]


def test_pagination_bound():
    """first_n must survive an empty PaginatedList and still honour its bound."""
    check("slicing an empty PaginatedList is the trap we are avoiding",
          _raises_index_error(lambda: list(FakePaginatedList([])[:60])))
    check("first_n yields nothing for a repo with no open PRs",
          list(ip.first_n(FakePaginatedList([]), 60)) == [])
    check("first_n passes short result sets through untouched",
          list(ip.first_n(FakePaginatedList([1, 2, 3]), 60)) == [1, 2, 3])
    check("first_n stops at the bound",
          list(ip.first_n(FakePaginatedList(range(200)), 60)) == list(range(60)))
    check("collect_repo bounds its PR sweep with first_n, never a slice",
          "first_n(repo.get_pulls(" in _source_of(ip.collect_repo)
          and "get_pulls(state=\"open\", sort=\"updated\", direction=\"desc\")[:"
              not in _source_of(ip.collect_repo))


def _raises_index_error(fn) -> bool:
    try:
        fn()
    except IndexError:
        return True
    return False


def _source_of(fn) -> str:
    return inspect.getsource(fn)


def main() -> int:
    print("issue_pipeline fixture tests")
    test_pagination_bound()
    test_stages()
    test_classification()
    test_gaps()
    test_autonomy()
    test_queues()
    test_dependencies()
    test_tier3_queue()
    test_sprint_gate()
    test_sprint_run()
    test_sprint_workflow()
    test_markers_and_config()
    test_real_fleet_config()
    test_render()
    print()
    if FAILURES:
        print(f"FAILED — {len(FAILURES)} check(s):")
        for f in FAILURES:
            print(f"  · {f}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
