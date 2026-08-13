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
  * a config override in _data/fleet.yml must MERGE with the defaults, not
    replace them: a fleet.yml that sets one cap must not silently delete the
    label taxonomy the agents apply.

Deliberately dependency-light — no network, no gh, no pytest. Needs only PyYAML:

    python3 .github/scripts/dash-gen/test_issue_pipeline.py
"""

from __future__ import annotations

import sys
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


def main() -> int:
    print("issue_pipeline fixture tests")
    test_stages()
    test_classification()
    test_gaps()
    test_autonomy()
    test_queues()
    test_tier3_queue()
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
