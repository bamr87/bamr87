#!/usr/bin/env python3
"""
ai_usage_collector — the COMMITTED Claude Code usage ledger across the fleet
(the dash's AI-transparency layer; see docs/AI-INTEGRATION.md → "Usage dashboard").

Where ai_activity.py shadow-prices LOCAL sessions and stays gitignored, this
module builds the publishable picture: every Claude Code touchpoint the fleet
leaves in public infrastructure, aggregated into _data/ai_usage.yml for the
/ai-usage/ dash page. Three sources, all harvested without touching any
submodule repo:

  ci      workflow runs of any fleet workflow that invokes
          anthropics/claude-code-action (detected by reading the workflow file
          content once per distinct path with runs in the window). For each
          run, the run log is scanned for the action's result JSON — cost
          (total_cost_usd), token breakdown, and turn count. Runs whose logs
          carry no usage (skipped gates, incident-era holes) still count as
          runs with usage nulled and are surfaced as `unpriced_runs`.
  vcs     Claude-attributed version control: commits whose message carries a
          "Co-Authored-By: Claude" trailer, and PRs whose body carries the
          "Generated with [Claude Code]" marker, counted per repo in-window
          with sample provenance links.
  local   an optional locally-published section: when the machine's
          ai-activity ledger exists (never in CI), its windowed aggregate is
          folded in under `local`; when absent, any previously committed
          `local` block is PRESERVED verbatim so the daily CI refresh never
          erases a deliberate local publish. Publishing local spend remains an
          explicit opt-in (run `tools/dash-gen ai-usage` on your machine and
          commit) — CI alone never adds it.

Output: _data/ai_usage.yml — committed, refreshed daily by
.github/workflows/ai-usage.yml, rendered at /ai-usage/. Auditability comes
from the per-run ledger entries (run URLs, PR/commit links) rather than
aggregate claims.
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import re
import sys
import time
import zipfile
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("dash-gen requires PyYAML: pip install pyyaml\n")
    sys.exit(2)

import actions_analytics  # registry loading + owner_repo + gh auth conventions

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DEFAULT = REPO_ROOT / "_data" / "ai_usage.yml"

CLAUDE_ACTION_MARKER = "anthropics/claude-code-action"
COMMIT_TRAILER = re.compile(r"co-authored-by:.*claude", re.IGNORECASE)
PR_MARKER = "Generated with [Claude Code]"

# The action streams its final result JSON into the job log; these fields are
# scraped tolerantly (last occurrence wins — retries overwrite earlier turns).
LOG_FIELDS = {
    "cost_usd": re.compile(r'"total_cost_usd"\s*:\s*([0-9.]+)'),
    "input_tokens": re.compile(r'"input_tokens"\s*:\s*([0-9]+)'),
    "output_tokens": re.compile(r'"output_tokens"\s*:\s*([0-9]+)'),
    "cache_read_tokens": re.compile(r'"cache_read_input_tokens"\s*:\s*([0-9]+)'),
    "cache_write_tokens": re.compile(r'"cache_creation_input_tokens"\s*:\s*([0-9]+)'),
    "turns": re.compile(r'"num_turns"\s*:\s*([0-9]+)'),
}


# --------------------------------------------------------------------------- #
# CI runs
# --------------------------------------------------------------------------- #
def _workflow_uses_claude(repo, path: str, cache: dict) -> bool:
    if path in cache:
        return cache[path]
    uses = False
    try:
        blob = repo.get_contents(path)
        uses = CLAUDE_ACTION_MARKER in blob.decoded_content.decode("utf-8", "replace")
    except Exception:
        pass
    cache[path] = uses
    return uses


def _scan_log_for_usage(gh_session, url: str) -> dict:
    """Download a run's log zip and scrape the claude-code-action result."""
    out: dict = {}
    try:
        resp = gh_session.get(url, timeout=60)
        if resp.status_code != 200:
            return out
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            for name in zf.namelist():
                if not name.endswith(".txt"):
                    continue
                text = zf.read(name).decode("utf-8", "replace")
                if CLAUDE_ACTION_MARKER not in text and "total_cost_usd" not in text:
                    continue
                for key, rx in LOG_FIELDS.items():
                    hits = rx.findall(text)
                    if hits:
                        val = float(hits[-1]) if key == "cost_usd" else int(hits[-1])
                        out[key] = max(out.get(key, 0), val) if key != "cost_usd" else val
    except Exception:
        pass
    return out


def collect_ci(gh, gh_session, registry: list[dict], window_start: dt.datetime,
               max_runs: int) -> list[dict]:
    entries: list[dict] = []
    for project in registry:
        nwo = actions_analytics.owner_repo(project.get("repo_url", ""))
        if not nwo:
            continue
        sys.stderr.write(f"  ci · {nwo}\n")
        try:
            repo = gh.get_repo(nwo)
            runs = repo.get_workflow_runs()
        except Exception:
            continue
        claude_paths: dict[str, bool] = {}
        seen = 0
        for run in runs:
            if seen >= max_runs:
                break
            seen += 1
            created = run.created_at.replace(tzinfo=None)
            if created < window_start:
                break  # newest-first
            if not _workflow_uses_claude(repo, run.path, claude_paths):
                continue
            usage = {}
            if run.conclusion in ("success", "failure"):
                usage = _scan_log_for_usage(gh_session, run.logs_url)
            entries.append({
                "repo": project["name"],
                "workflow": run.name,
                "path": run.path,
                "event": run.event,
                "conclusion": run.conclusion,
                "day": created.strftime("%Y-%m-%d"),
                "url": run.html_url,
                "duration_min": round(
                    max(0, (run.updated_at - run.created_at).total_seconds()) / 60, 1),
                **{k: usage.get(k) for k in LOG_FIELDS},
            })
    return entries


# --------------------------------------------------------------------------- #
# commits + PRs
# --------------------------------------------------------------------------- #
def collect_vcs(gh, registry: list[dict], window_start: dt.datetime,
                commit_cap: int) -> tuple[list[dict], list[dict]]:
    commits: list[dict] = []
    prs: list[dict] = []
    since_date = window_start.strftime("%Y-%m-%d")
    for project in registry:
        nwo = actions_analytics.owner_repo(project.get("repo_url", ""))
        if not nwo:
            continue
        sys.stderr.write(f"  vcs · {nwo}\n")
        try:
            repo = gh.get_repo(nwo)
            n = 0
            for c in repo.get_commits(since=window_start):
                n += 1
                if n > commit_cap:
                    break
                msg = c.commit.message or ""
                if COMMIT_TRAILER.search(msg):
                    commits.append({
                        "repo": project["name"],
                        "sha": c.sha[:9],
                        "day": c.commit.author.date.strftime("%Y-%m-%d"),
                        "title": msg.splitlines()[0][:90],
                        "url": c.html_url,
                    })
        except Exception:
            pass
        try:
            q = f'repo:{nwo} is:pr created:>={since_date} "{PR_MARKER}" in:body'
            for issue in gh.search_issues(q):
                prs.append({
                    "repo": project["name"],
                    "number": issue.number,
                    "day": issue.created_at.strftime("%Y-%m-%d"),
                    "state": issue.state,
                    "title": issue.title[:90],
                    "url": issue.html_url,
                })
            time.sleep(2.2)  # search API: 30 req/min
        except Exception:
            pass
    return commits, prs


# --------------------------------------------------------------------------- #
# local section (opt-in publish, preserved across CI refreshes)
# --------------------------------------------------------------------------- #
def local_section(out_path: Path, window_days: int) -> dict | None:
    try:
        import ai_activity
        ledger_path = ai_activity.LEDGER_DEFAULT
        if ledger_path.exists():
            ledger = ai_activity.merge_ledger(ledger_path, {}, {})
            report = ai_activity.build_report(
                ledger, machine=ai_activity.platform.node(), window_days=window_days)
            return {
                "published": dt.date.today().isoformat(),
                "window_days": window_days,
                "totals": report.get("totals"),
                "by_repo": report.get("by_repo", [])[:20],
            }
    except Exception as exc:  # pragma: no cover
        sys.stderr.write(f"  local ledger unavailable ({exc}); preserving prior section\n")
    if out_path.exists():
        try:
            prior = yaml.safe_load(out_path.read_text()) or {}
            return prior.get("local")
        except Exception:
            pass
    return None


# --------------------------------------------------------------------------- #
# aggregation
# --------------------------------------------------------------------------- #
def _rollup(rows: list[dict], key) -> dict[str, dict]:
    agg: dict[str, dict] = {}
    for r in rows:
        k = key(r)
        b = agg.setdefault(k, {
            "runs": 0, "cost_usd": 0.0, "turns": 0, "minutes": 0.0,
            "input_tokens": 0, "output_tokens": 0, "unpriced_runs": 0,
        })
        b["runs"] += 1
        if r.get("cost_usd") is None:
            b["unpriced_runs"] += 1
        else:
            b["cost_usd"] = round(b["cost_usd"] + r["cost_usd"], 4)
        b["turns"] += r.get("turns") or 0
        b["minutes"] = round(b["minutes"] + (r.get("duration_min") or 0), 1)
        # NOTE: current claude-code-action result JSON carries no token
        # breakdown in CI logs — these stay 0 unless a future version (or a
        # usage-artifact step) provides them; token truth lives in the local
        # ledger section.
        for t in ("input_tokens", "output_tokens"):
            b[t] += r.get(t) or 0
    return agg


def build(gh, gh_session, registry: list[dict], window_days: int, max_runs: int,
          commit_cap: int, out_path: Path) -> dict:
    now = dt.datetime.utcnow()
    window_start = now - dt.timedelta(days=window_days)
    cat_of = {p["name"]: p.get("category", "uncategorized") for p in registry}

    ci = collect_ci(gh, gh_session, registry, window_start, max_runs)
    commits, prs = collect_vcs(gh, registry, window_start, commit_cap)
    local = local_section(out_path, window_days)

    by_repo = _rollup(ci, lambda r: r["repo"])
    for c in commits:
        by_repo.setdefault(c["repo"], {"runs": 0, "cost_usd": 0.0, "input_tokens": 0,
                                       "output_tokens": 0, "cache_read_tokens": 0,
                                       "cache_write_tokens": 0, "unpriced_runs": 0})
        by_repo[c["repo"]].setdefault("commits", 0)
        by_repo[c["repo"]]["commits"] = by_repo[c["repo"]].get("commits", 0) + 1
    for p in prs:
        by_repo.setdefault(p["repo"], {"runs": 0, "cost_usd": 0.0, "input_tokens": 0,
                                       "output_tokens": 0, "cache_read_tokens": 0,
                                       "cache_write_tokens": 0, "unpriced_runs": 0})
        by_repo[p["repo"]]["prs"] = by_repo[p["repo"]].get("prs", 0) + 1

    total_cost = round(sum(r["cost_usd"] for r in ci if r.get("cost_usd")), 2)
    report = {
        "generated": now.strftime("%Y-%m-%d %H:%M UTC"),
        "window_days": window_days,
        "totals": {
            "ci_runs": len(ci),
            "ci_cost_usd": total_cost,
            "ci_unpriced_runs": sum(1 for r in ci if r.get("cost_usd") is None),
            "turns": sum(r.get("turns") or 0 for r in ci),
            "ci_minutes": round(sum(r.get("duration_min") or 0 for r in ci), 1),
            "commits": len(commits),
            "prs": len(prs),
            "repos_active": len(by_repo),
        },
        "by_repo": [
            {"repo": k, "category": cat_of.get(k, "uncategorized"), **v}
            for k, v in sorted(by_repo.items(),
                               key=lambda kv: (-kv[1]["cost_usd"], -kv[1]["runs"]))
        ],
        "by_workflow": [
            {"workflow": k, **v}
            for k, v in sorted(_rollup(ci, lambda r: f'{r["repo"]}/{r["workflow"]}').items(),
                               key=lambda kv: (-kv[1]["cost_usd"], -kv[1]["runs"]))
        ],
        "by_category": [
            {"category": k, **v}
            for k, v in sorted(_rollup(ci, lambda r: cat_of.get(r["repo"], "uncategorized")).items(),
                               key=lambda kv: -kv[1]["cost_usd"])
        ],
        "by_day": [
            {"day": k, **v}
            for k, v in sorted(_rollup(ci, lambda r: r["day"]).items())
        ],
        "ci_ledger": sorted(ci, key=lambda r: (r["day"], r["repo"]), reverse=True)[:200],
        "commit_ledger": sorted(commits, key=lambda c: c["day"], reverse=True)[:100],
        "pr_ledger": sorted(prs, key=lambda p: p["day"], reverse=True)[:100],
    }
    if local:
        report["local"] = local
    return report


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def run(args: argparse.Namespace) -> int:
    try:
        from github import Github, Auth
        import requests
    except ImportError:
        sys.stderr.write("ai-usage requires PyGithub: pip install PyGithub\n")
        return 2

    token = actions_analytics.resolve_token()
    if not token:
        sys.stderr.write("No GitHub token (set GH_TOKEN/GITHUB_TOKEN or run `gh auth login`).\n")
        return 2
    gh = Github(auth=Auth.Token(token), per_page=100)
    # a raw session for log-zip downloads, sharing the client's token
    gh_session = requests.Session()
    gh_session.headers["Authorization"] = f"token {token}"

    with actions_analytics.REGISTRY.open() as fh:
        registry = yaml.safe_load(fh) or []
    sys.stderr.write(f"Collecting Claude usage for {len(registry)} repos (last {args.days}d)…\n")
    out = Path(args.out)
    report = build(gh, gh_session, registry, args.days, args.max_runs,
                   args.commit_cap, out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as fh:
        fh.write("# GENERATED by .github/scripts/dash-gen (ai_usage_collector) — "
                 "refreshed daily by ai-usage.yml. Edit the generator, not this file.\n")
        yaml.safe_dump(report, fh, sort_keys=False, allow_unicode=True)
    t = report["totals"]
    sys.stderr.write(
        f"ai-usage: {t['ci_runs']} CI runs (${t['ci_cost_usd']}, "
        f"{t['ci_unpriced_runs']} unpriced) · {t['commits']} commits · "
        f"{t['prs']} PRs -> {out}\n")
    return 0


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--days", type=int, default=14, help="analysis window (default 14)")
    parser.add_argument("--max-runs", type=int, default=300,
                        help="max runs examined per repo (default 300)")
    parser.add_argument("--commit-cap", type=int, default=150,
                        help="max commits scanned per repo (default 150)")
    parser.add_argument("--out", default=str(OUT_DEFAULT))
    parser.set_defaults(func=run)
