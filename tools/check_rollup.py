#!/usr/bin/env python3
# ============================================================================
# File:          tools/check_rollup.py
# Description:   One rule for reading a commit's checks, shared by every reducer that calls a pull
#                request green or red: tools/weekly/closeout.py (`checks_green`, the live merge
#                gate), tools/console/decision_index.py (failing / ready to merge) and
#                tools/pm_review.py (the Fleet project's CI field and `pr_ci_red`).
#                The rule: a CANCELLED check run is set aside when a later run of the same check
#                (same workflow name, same check name) on the same commit exists. That run is the
#                check's verdict, and it is still judged. Every other row is judged as it stands:
#                a later pass never hides a failure, only a cancellation.
#                Why: a workflow that cancels in progress on every `labeled` event (verify kit
#                0.1.0, zer0-mistakes' evidence gate) leaves one CANCELLED row per label burst in
#                the rollup, and GitHub's own rollup state counts each one as a FAILURE. On
#                2026-11-15, 25 fleet pull requests read red this way; the real run had passed.
# Usage:         import check_rollup            (with tools/ on sys.path)
#                from tools import check_rollup (with the repo root on sys.path)
# Never:         reads GitHub. Pure functions over rows another module fetched.
# ============================================================================
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

#: What GraphQL must select inside `statusCheckRollup{ … }` for `corrected_state` to look past
#: GitHub's state: every context, each check run with its workflow, and whether the page was all.
ROLLUP_FIELDS = ("state contexts(first:100){ pageInfo{ hasNextPage } nodes{ __typename "
                 "... on CheckRun{ name status conclusion startedAt completedAt "
                 "checkSuite{ workflowRun{ workflow{ name } } } } "
                 "... on StatusContext{ context state } } }")
#: Check-run conclusions that do not fail a commit, as on GitHub.
PASSING = ("SUCCESS", "SKIPPED", "NEUTRAL")
#: A check run in one of these states has not started, so it can only start after a run that has.
NOT_STARTED = ("QUEUED", "REQUESTED", "WAITING", "PENDING")


def _up(value: Any) -> str:
    return str(value or "").upper()


def is_status(row: dict) -> bool:
    """A commit status (a context with a state), not a check run. `gh pr view` flattens the rollup and
    drops the type name on some rows, so a row with a state and no conclusion is a status too."""
    return row.get("__typename") == "StatusContext" or ("state" in row and "conclusion" not in row)


def workflow(row: dict) -> str:
    """The workflow a check run belongs to: `workflowName` as `gh pr view` flattens it, or the GraphQL
    path. Empty for a check run no workflow made (a third-party app), which is never set aside."""
    name = row.get("workflowName")
    if not name:
        node: Any = row
        for key in ("checkSuite", "workflowRun", "workflow"):
            node = node.get(key) if isinstance(node, dict) else None
        name = node.get("name") if isinstance(node, dict) else None
    return name if isinstance(name, str) else ""


def _stamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _later(row: dict, than: dict) -> bool:
    """Did `row` start after `than`? Ordered by `startedAt`, then `completedAt` within the same second
    (GitHub stamps whole seconds, and a label burst starts several runs in one). A row that cannot be
    placed is never later, so an unreadable timestamp keeps the cancelled row in the verdict."""
    began = _stamp(than.get("startedAt"))
    if began is None:
        return False
    start = _stamp(row.get("startedAt"))
    if start is None:
        return _up(row.get("status")) in NOT_STARTED
    if start != began:
        return start > began
    ended, end = _stamp(than.get("completedAt")), _stamp(row.get("completedAt"))
    if ended is None:
        return False
    if end is None:
        return _up(row.get("status")) not in ("COMPLETED", "")
    return end > ended


def current(rows: Iterable[Any]) -> tuple[list[dict], list[dict]]:
    """(the rows that speak for the commit, the cancelled runs set aside). A CANCELLED check run is set
    aside when a later run of the same check, by workflow and name, is in the rollup; the latest run
    of a check is never set aside, so no check drops out of the verdict. Order is kept."""
    rows = [r for r in rows or [] if isinstance(r, dict)]
    runs: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        if not is_status(r) and workflow(r) and isinstance(r.get("name"), str) and r["name"]:
            runs.setdefault((workflow(r), r["name"]), []).append(r)
    aside = [r for r in rows
             if not is_status(r) and _up(r.get("conclusion")) == "CANCELLED"
             and any(o is not r and _later(o, r) for o in runs.get((workflow(r), r.get("name")), []))]
    return [r for r in rows if not any(r is a for a in aside)], aside


def verdict(rows: Iterable[dict]) -> str | None:
    """A rollup state from rows already judged current: FAILURE when one failed, PENDING when one is
    still running or waiting, SUCCESS when every one finished without failing, None for no rows."""
    rows = [r for r in rows if isinstance(r, dict)]
    if not rows:
        return None
    pending = False
    for r in rows:
        if is_status(r):
            state = _up(r.get("state"))
            if state in ("PENDING", "EXPECTED"):
                pending = True
            elif state != "SUCCESS":
                return "FAILURE"
        elif _up(r.get("status")) != "COMPLETED":
            pending = True
        elif _up(r.get("conclusion")) not in PASSING:
            return "FAILURE"
    return "PENDING" if pending else "SUCCESS"


def corrected_state(rollup: Any) -> str | None:
    """GitHub's rollup state for a commit (`statusCheckRollup` read with ROLLUP_FIELDS), less the
    cancelled runs a later run of the same check superseded: FAILURE or ERROR becomes SUCCESS or
    PENDING when those runs were all that failed. Any other state is GitHub's, unchanged, and so is
    any state whose contexts were not read in full (a second page, or no contexts at all): this
    function only ever takes back a red it can prove was a superseded cancellation."""
    if not isinstance(rollup, dict):
        return None
    state = rollup.get("state")
    if state not in ("FAILURE", "ERROR"):
        return state
    contexts = rollup.get("contexts")
    if not isinstance(contexts, dict) or (contexts.get("pageInfo") or {}).get("hasNextPage") is not False:
        return state
    nodes = contexts.get("nodes")
    if not isinstance(nodes, list):
        return state
    keep, aside = current(nodes)
    if not aside:
        return state
    judged = verdict(keep)
    return state if judged in (None, "FAILURE") else judged
