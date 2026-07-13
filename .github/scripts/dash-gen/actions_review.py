#!/usr/bin/env python3
"""
actions_review — reviewer work-order builder for GitHub Actions optimization.

This is the TRIAGE layer that feeds the Opus Claude Code reviewer
(.github/workflows/actions-review.yml). The daily actions_analytics pass writes
_data/actions_usage.yml (cost / effectiveness / waste per workflow). This module:

  1. selects the worst-offending workflows (failing / flaky / slow /
     high-cost-low-value / cancel-heavy, or high raw priority),
  2. drops any already covered by an OPEN `actions-review` issue in the dash repo
     (dedupe by a hidden marker embedded in the issue body),
  3. best-effort enriches each survivor with links to the specific problem runs
     (failed runs for failing candidates, slowest runs for slow ones), and
  4. emits a compact Markdown *work order* the reviewer consumes to file exactly
     ONE actionable issue per candidate.

Deterministic on purpose: candidate selection + dedupe happen HERE (in code), so
the non-deterministic AI step only does root-cause analysis + issue authoring on a
pre-vetted, de-duplicated, capped list — it cannot spam.

Exit status is 0 even with zero candidates (a quiet day is normal). When
GITHUB_OUTPUT is set it emits `has_candidates=true|false` and `candidate_count=N`
for the workflow to branch on.

Auth (for dedupe + enrichment): a token from GH_TOKEN / GITHUB_TOKEN, else
`gh auth token`. Failures degrade gracefully — no token just means no enrichment
and an empty dedupe set (the reviewer still double-checks before filing).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import actions_analytics

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("actions_review requires PyYAML: pip install pyyaml\n")
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DEFAULT = REPO_ROOT / "_data" / "actions_usage.yml"
OUT_DEFAULT = REPO_ROOT / "actions-review-workorder.md"

# Flags that make a workflow worth a reviewer's time (see actions_analytics).
SERIOUS_FLAGS = {"failing", "flaky", "slow", "high-cost-low-value", "cancel-heavy"}
# Which candidates want failing-run evidence vs slow-run evidence.
FAILING_FLAGS = {"failing", "flaky", "cancel-heavy", "high-cost-low-value"}


# --------------------------------------------------------------------------- #
# marker / dedupe
# --------------------------------------------------------------------------- #
def marker_key(cand: dict) -> str:
    """Stable, ascii-safe identity for a workflow (repo + file path)."""
    tail = cand.get("path") or cand.get("workflow") or "?"
    return f'{cand.get("repo", "?")}:{tail}'


def issue_marker(key: str) -> str:
    return f'<!-- actions-review key="{key}" -->'


def open_review_markers(repo_slug: str, label: str) -> set[str]:
    """Marker keys of currently-open review issues, so we never re-file one."""
    def _list(cmd: list[str]) -> list[dict] | None:
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
        if out.returncode != 0:
            return None
        try:
            return json.loads(out.stdout)
        except json.JSONDecodeError:
            return None

    base = ["gh", "issue", "list", "-R", repo_slug, "--state", "open",
            "--json", "number,title,body", "--limit", "200"]
    # Prefer the label filter; fall back to a body search if the label doesn't
    # exist yet (first run) so early dupes are still caught.
    items = _list(base + ["--label", label])
    if items is None:
        items = _list(base + ["--search", "actions-review in:body"])
    if not items:
        return set()

    markers: set[str] = set()
    for it in items:
        for m in re.findall(r'key="([^"]+)"', it.get("body", "") or ""):
            markers.add(m)
    return markers


# --------------------------------------------------------------------------- #
# selection
# --------------------------------------------------------------------------- #
def load_report(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open() as fh:
        return yaml.safe_load(fh) or {}


def select(report: dict, min_priority: float, min_runs: int) -> list[dict]:
    """Worst-offending workflows worth a deeper look, most-severe first."""
    cands = []
    for w in report.get("workflows", []):
        if w.get("runs", 0) < min_runs:
            continue
        flags = set(w.get("flags", []))
        if (flags & SERIOUS_FLAGS) or w.get("priority", 0) >= min_priority:
            cands.append(w)
    cands.sort(key=lambda w: (w.get("priority", 0), w.get("total_min", 0)), reverse=True)
    return cands


# --------------------------------------------------------------------------- #
# enrichment (best-effort: attach the specific runs the reviewer should read)
# --------------------------------------------------------------------------- #
def enrich(gh, cand: dict, max_lookup: int) -> None:
    if gh is None:
        return
    from github.GithubException import GithubException

    nwo = actions_analytics.owner_repo(cand.get("repo_url", "") or "")
    path = cand.get("path") or ""
    if not nwo or not path:
        return
    try:
        repo = gh.get_repo(nwo)
        wf = repo.get_workflow(os.path.basename(path))
    except GithubException:
        return

    scanned = []
    try:
        for run in wf.get_runs():
            if run.status != "completed":
                continue
            scanned.append(run)
            if len(scanned) >= max_lookup:
                break
    except GithubException:
        return

    flags = set(cand.get("flags", []))
    picked: list = []
    if flags & FAILING_FLAGS:
        picked = [r for r in scanned
                  if (r.conclusion or "") in actions_analytics.WASTE_CONCLUSIONS][:3]
    if "slow" in flags and len(picked) < 3:
        for r in sorted(scanned, key=lambda r: actions_analytics.duration_min(r) or 0,
                        reverse=True):
            if r not in picked:
                picked.append(r)
            if len(picked) >= 3:
                break
    if not picked:
        picked = scanned[:2]

    cand["problem_runs"] = [{
        "id": r.id,
        "conclusion": r.conclusion or "?",
        "minutes": round(actions_analytics.duration_min(r) or 0, 1),
        "created": (actions_analytics.as_utc(r.created_at).date().isoformat()
                    if r.created_at else "?"),
        "url": r.html_url,
    } for r in picked]


# --------------------------------------------------------------------------- #
# work order rendering
# --------------------------------------------------------------------------- #
def angle(flags: list[str]) -> str:
    f = set(flags)
    tips = []
    if f & {"failing", "flaky"}:
        tips.append("read `--log-failed` for the listed runs and fix or quarantine the "
                    "failing step (don't just add retries to mask real flakiness)")
    if "slow" in f:
        tips.append("profile the slowest run's steps; add dependency caching, "
                    "`concurrency: cancel-in-progress`, `paths:`/branch filters, "
                    "`timeout-minutes`, or trim the matrix")
    if "high-cost-low-value" in f:
        tips.append("most minutes end in non-success — gate the triggers or fix the "
                    "root failure so the spend produces value")
    if "cancel-heavy" in f:
        tips.append("add `concurrency: {group, cancel-in-progress: true}` and/or narrower "
                    "triggers so runs aren't superseded mid-flight")
    if "cron-heavy" in f:
        tips.append("reduce the `schedule` cadence or convert to event-driven triggers")
    return "; ".join(tips) or "review triggers, caching, and job structure for waste"


def render_workorder(cands: list[dict], report: dict, cap: int) -> str:
    t = report.get("totals", {})
    L = []
    L.append("# GitHub Actions optimization — reviewer work order")
    L.append("")
    L.append(f"Source: `_data/actions_usage.yml` · window {report.get('window_days','?')}d "
             f"· generated {report.get('generated_at','?')}")
    L.append(f"Fleet: {t.get('runs','?')} runs · {t.get('total_hours','?')}h consumed · "
             f"{t.get('waste_hours','?')}h wasted "
             f"({round(100 - t.get('effectiveness_pct', 100), 0)}% of minutes) · "
             f"{t.get('success_rate_pct','?')}% success")
    L.append("")
    if not cands:
        L.append("**No candidates** — nothing crossed the failing/slow/high-cost "
                 "thresholds, or every offender already has an open `actions-review` "
                 "issue. No action needed.")
        L.append("")
        return "\n".join(L)

    L.append(f"**{len(cands)} candidate workflow(s)** to review (cap: {cap} issues this "
             f"run). File exactly ONE issue per candidate in `bamr87/bamr87`. Paste each "
             f"MARKER line verbatim so future runs dedupe.")
    L.append("")
    for i, c in enumerate(cands, 1):
        flags = c.get("flags", [])
        flagstr = f"  `[{', '.join(flags)}]`" if flags else ""
        L.append("---")
        L.append("")
        L.append(f"## {i}. {c.get('repo')}/{c.get('workflow')}{flagstr}")
        L.append("")
        L.append(f"- **Submodule / repo:** {c.get('repo')} — {c.get('repo_url')}")
        L.append(f"- **Workflow file:** `{c.get('path') or '(unknown path)'}`")
        L.append(f"- **Type:** {c.get('type')}")
        L.append(f"- **MARKER (first line of the issue body):** `{issue_marker(marker_key(c))}`")
        L.append(f"- **Signal (last {report.get('window_days','?')}d):** "
                 f"{c.get('runs')} runs · {c.get('total_min')}m total · "
                 f"{c.get('avg_min')}m avg · {c.get('p95_min')}m p95 · "
                 f"{c.get('waste_min')}m wasted · {c.get('effectiveness_pct')}% effective · "
                 f"{c.get('success_rate_pct')}% success · {c.get('runs_per_week')}/wk · "
                 f"{c.get('sched_pct')}% scheduled")
        runs = c.get("problem_runs") or []
        if runs:
            L.append("- **Problem runs to inspect:**")
            for r in runs:
                L.append(f"    - {r['conclusion']} · {r['minutes']}m · {r['created']} · "
                         f"run `{r['id']}` · {r['url']}")
        else:
            L.append("- **Problem runs:** _(not pre-fetched — list them with "
                     f"`gh run list -R {actions_analytics.owner_repo(c.get('repo_url','') or '') or '<owner>/<repo>'} "
                     f"--workflow '{os.path.basename(c.get('path') or '')}'`)_")
        L.append(f"- **Suggested angle:** {angle(flags)}")
        L.append("")
    return "\n".join(L)


# --------------------------------------------------------------------------- #
# entry points
# --------------------------------------------------------------------------- #
def emit_output(key: str, value) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as fh:
            fh.write(f"{key}={value}\n")


def run(args: argparse.Namespace) -> int:
    report = load_report(Path(args.data))
    if not report:
        sys.stderr.write(f"No analytics data at {args.data} — run `dash-gen actions` first.\n")
        Path(args.out).write_text(render_workorder([], {}, args.limit))
        emit_output("has_candidates", "false")
        emit_output("candidate_count", 0)
        return 0

    cands = select(report, args.min_priority, args.min_runs)

    open_markers = open_review_markers(args.repo, args.label)
    fresh = [c for c in cands if marker_key(c) not in open_markers]
    skipped = len(cands) - len(fresh)
    fresh = fresh[: args.limit]

    if fresh and not args.no_enrich:
        gh = None
        token = actions_analytics.resolve_token()
        if token:
            try:
                from github import Github, Auth
                gh = Github(auth=Auth.Token(token), per_page=50)
            except ImportError:
                gh = None
        for c in fresh:
            enrich(gh, c, args.max_lookup)

    Path(args.out).write_text(render_workorder(fresh, report, args.limit))

    emit_output("has_candidates", "true" if fresh else "false")
    emit_output("candidate_count", len(fresh))
    sys.stderr.write(
        f"actions-review: {len(cands)} flagged, {skipped} already-open (skipped), "
        f"{len(fresh)} in work order → {args.out}\n"
    )
    for c in fresh:
        sys.stderr.write(f"  · {c.get('repo')}/{c.get('workflow')} "
                         f"[{', '.join(c.get('flags', [])) or 'priority'}]\n")
    return 0


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--data", default=str(DATA_DEFAULT), metavar="PATH",
                        help="analytics data file (default _data/actions_usage.yml)")
    parser.add_argument("--out", default=str(OUT_DEFAULT), metavar="PATH",
                        help="work-order output (default actions-review-workorder.md)")
    parser.add_argument("--limit", type=int, default=4, metavar="N",
                        help="max candidates / issues per run (default 4)")
    parser.add_argument("--min-priority", type=float, default=10.0, metavar="P",
                        help="include unflagged workflows at/above this priority (default 10)")
    parser.add_argument("--min-runs", type=int, default=3, metavar="N",
                        help="ignore workflows with fewer runs in the window (default 3)")
    parser.add_argument("--repo", default="bamr87/bamr87", metavar="OWNER/REPO",
                        help="repo whose open issues are checked for dedupe (default bamr87/bamr87)")
    parser.add_argument("--label", default="actions-review", metavar="LABEL",
                        help="label marking reviewer issues (default actions-review)")
    parser.add_argument("--max-lookup", type=int, default=40, metavar="N",
                        help="runs scanned per candidate when picking problem runs (default 40)")
    parser.add_argument("--no-enrich", action="store_true",
                        help="skip fetching problem-run links (faster, offline)")
    parser.set_defaults(func=run)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="actions-review", description=__doc__)
    add_arguments(parser)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
