#!/usr/bin/env python3
"""
remediation — the fleet-doctor work-order builder.

ONE ranked queue of workflows that need fixing, merged from the two signals the
dash already collects but previously acted on in two disconnected loops:

  FAILING   _data/fleet_triage.yml  → by_repo[].workflows.failing[]
            Every workflow whose latest completed run is red. This is STANDING
            state, not "something failed yesterday" — a workflow that has been
            broken for three weeks stays on the queue until it is fixed, which
            is exactly the class of failure the prior-day-only scan missed.

  EXPENSIVE _data/actions_usage.yml → workflows[]
            Cost / effectiveness / waste per workflow, with flags for slow,
            flaky, high-cost-low-value, cancel-heavy, cron-heavy.

Merging matters: the worst offenders are usually BOTH — a workflow that is red
AND burning 77 minutes a run is one problem, and filing two issues about it (as
the old split loops did — actions-review filed one, daily-repo-analysis filed
another) is how a queue turns into noise. Candidates are keyed on
`owner/repo:workflow-path`, so both signals land on a single entry with a single
marker.

Each candidate is classified by where its fix must happen:

  hub        the failing workflow lives in the control-plane repo → the agent
             edits it in the checkout and opens a draft PR directly.
  submodule  it lives in another bamr87 repo → the agent clones that repo and
             opens a draft PR THERE (needs a token with contents+workflows
             write). This is the part that makes the loop actually FIX things
             rather than describe them.
  external   an upstream mirror (microsoft/skills et al) → never touched.

Deterministic on purpose: selection, merging, dedupe, ranking, and caps all
happen HERE, in code. The AI step only does root-cause analysis and authoring on
a pre-vetted, capped list — it cannot spam the fleet.

Exit status is 0 even with zero candidates (a healthy fleet is normal). With
GITHUB_OUTPUT set it emits `has_candidates`, `candidate_count`, and
`cross_repo_count` for the workflow to branch on.
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
    sys.stderr.write("remediation requires PyYAML: pip install pyyaml\n")
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parents[3]
USAGE_DEFAULT = REPO_ROOT / "_data" / "actions_usage.yml"
TRIAGE_DEFAULT = REPO_ROOT / "_data" / "fleet_triage.yml"
FLEET_DEFAULT = REPO_ROOT / "_data" / "fleet.yml"
OUT_DEFAULT = REPO_ROOT / "remediation-workorder.md"

# Markers written by THIS loop, plus the two retired loops whose issues may still
# be open. All three are honoured for dedupe so the migration doesn't re-file
# work that already has a ticket.
MARKER_RE = re.compile(
    r'<!-- (?:fleet-doctor|actions-review|daily-analysis) key="([^"]+)" -->'
)

DEFAULT_SEVERITY = {
    "failing": 100,
    "high-cost-low-value": 80,
    "flaky": 60,
    "slow": 40,
    "cancel-heavy": 20,
    "cron-heavy": 10,
}


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open() as fh:
        return yaml.safe_load(fh) or {}


def load_config(path: Path) -> dict:
    cfg = load_yaml(path).get("remediation") or {}
    sev = {**DEFAULT_SEVERITY, **(cfg.get("severity") or {})}
    return {
        "max_candidates": cfg.get("max_candidates", 6),
        "max_cross_repo": cfg.get("max_cross_repo", 3),
        "min_runs": cfg.get("min_runs", 3),
        "min_priority": cfg.get("min_priority", 10.0),
        "slow_avg_min": cfg.get("slow_avg_min", 10),
        "slow_p95_min": cfg.get("slow_p95_min", 20),
        "severity": sev,
    }


# --------------------------------------------------------------------------- #
# identity / dedupe
# --------------------------------------------------------------------------- #
def marker_key(nwo: str, path: str, workflow: str = "") -> str:
    """Stable identity for a workflow: owner/repo + its file path.

    Falls back to the display name when the path is unknown (some runs report a
    dynamic path, e.g. Codespaces prebuilds), because a name is still a more
    stable key than nothing — without it every run would look like a new problem.
    """
    tail = path or workflow or "?"
    return f"{nwo}:{tail}"


def doctor_marker(key: str) -> str:
    return f'<!-- fleet-doctor key="{key}" -->'


def _gh_json(cmd: list[str]) -> list[dict] | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return None


def open_markers(repo_slug: str) -> set[str]:
    """Keys already covered by an OPEN issue or PR in the hub.

    PRs count as well as issues: the loop opens draft PRs for hub-fixable
    problems, and an open fix PR means the work is done and awaiting review —
    re-filing it every morning would be the single loudest failure mode of a
    daily loop.
    """
    markers: set[str] = set()
    sources = [
        ["gh", "issue", "list", "-R", repo_slug, "--state", "open",
         "--json", "body", "--limit", "200"],
        ["gh", "pr", "list", "-R", repo_slug, "--state", "open",
         "--json", "body", "--limit", "200"],
    ]
    for cmd in sources:
        for item in _gh_json(cmd) or []:
            markers.update(MARKER_RE.findall(item.get("body") or ""))
    return markers


def cross_repo_open_markers(nwos: list[str]) -> set[str]:
    """Keys with an open fix PR in the TARGET repo.

    A submodule fix lands as a PR in the submodule, not the hub, so the hub-side
    dedupe above cannot see it. Without this a still-unmerged fix PR in
    bamr87/it-journey would be reopened every single day.
    """
    markers: set[str] = set()
    for nwo in nwos:
        items = _gh_json(["gh", "pr", "list", "-R", nwo, "--state", "open",
                          "--json", "body", "--limit", "50"])
        for item in items or []:
            markers.update(MARKER_RE.findall(item.get("body") or ""))
    return markers


# --------------------------------------------------------------------------- #
# signal 1 — standing failures (fleet_triage.yml)
# --------------------------------------------------------------------------- #
def failing_candidates(triage: dict, owner: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for repo in triage.get("by_repo", []):
        if repo.get("external") or repo.get("archived"):
            continue
        nwo = repo.get("nwo") or ""
        # Same derived-ownership guard as the usage side, so a triage snapshot
        # written before `external` existed can't leak a mirror into the queue.
        if not nwo or not nwo.startswith(f"{owner}/"):
            continue
        for wf in (repo.get("workflows") or {}).get("failing", []) or []:
            path = wf.get("path") or ""
            # Dynamic, non-file "workflows" (Codespaces prebuilds and friends)
            # have no source to edit — there is nothing an agent could fix.
            if not path.startswith(".github/workflows/"):
                continue
            key = marker_key(nwo, path, wf.get("workflow", ""))
            cand = out.setdefault(key, {
                "key": key,
                "nwo": nwo,
                "repo": repo.get("name") or nwo.split("/")[-1],
                "repo_url": repo.get("repo_url") or f"https://github.com/{nwo}",
                "workflow": wf.get("workflow") or path,
                "path": path,
                "private": bool(repo.get("private")),
                "signals": set(),
                "failing_runs": [],
                "usage": None,
            })
            cand["signals"].add("failing")
            cand["failing_runs"].append({
                "conclusion": wf.get("conclusion") or "failure",
                "url": wf.get("run_url") or "",
                "at": wf.get("run_at") or "?",
            })
    return out


# --------------------------------------------------------------------------- #
# signal 2 — cost / slowness (actions_usage.yml)
# --------------------------------------------------------------------------- #
def is_long_running(w: dict, cfg: dict) -> bool:
    return ((w.get("avg_min") or 0) >= cfg["slow_avg_min"]
            or (w.get("p95_min") or 0) >= cfg["slow_p95_min"])


def usage_candidates(usage: dict, cfg: dict, owner: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    severity = cfg["severity"]
    for w in usage.get("workflows", []):
        if (w.get("runs") or 0) < cfg["min_runs"]:
            continue
        nwo = actions_analytics.owner_repo(w.get("repo_url") or "")
        path = w.get("path") or ""
        if not nwo or not path.startswith(".github/workflows/"):
            continue
        # Externality is DERIVED from the owner, not read from `w["external"]`.
        # That flag is absent from analytics data generated before it was added,
        # and `.get()` on a missing key is falsey — so trusting it silently lets
        # upstream mirrors (microsoft/skills) into a queue whose whole job is to
        # open PRs. Deriving it cannot go stale with the data schema.
        if not nwo.startswith(f"{owner}/"):
            continue

        signals = {f for f in (w.get("flags") or []) if f in severity}
        # The analytics module flags `slow` relative to the fleet; the fleet
        # config sets an ABSOLUTE bar too, so "long-running" means the same
        # thing here as it does to a human reading the dash.
        if is_long_running(w, cfg):
            signals.add("slow")
        if not signals and (w.get("priority") or 0) < cfg["min_priority"]:
            continue

        key = marker_key(nwo, path, w.get("workflow", ""))
        out[key] = {
            "key": key,
            "nwo": nwo,
            "repo": w.get("repo") or nwo.split("/")[-1],
            "repo_url": w.get("repo_url") or f"https://github.com/{nwo}",
            "workflow": w.get("workflow") or path,
            "path": path,
            "private": False,
            "signals": signals,
            "failing_runs": [],
            "usage": {
                "runs": w.get("runs"),
                "total_min": w.get("total_min"),
                "avg_min": w.get("avg_min"),
                "p95_min": w.get("p95_min"),
                "waste_min": w.get("waste_min"),
                "effectiveness_pct": w.get("effectiveness_pct"),
                "success_rate_pct": w.get("success_rate_pct"),
                "runs_per_week": w.get("runs_per_week"),
                "sched_pct": w.get("sched_pct"),
                "type": w.get("type"),
            },
        }
    return out


# --------------------------------------------------------------------------- #
# merge + rank
# --------------------------------------------------------------------------- #
def merge(failing: dict[str, dict], expensive: dict[str, dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for key, cand in failing.items():
        merged[key] = cand
    for key, cand in expensive.items():
        if key in merged:
            merged[key]["signals"] |= cand["signals"]
            merged[key]["usage"] = cand["usage"]
        else:
            merged[key] = cand
    return list(merged.values())


def score(cand: dict, cfg: dict) -> float:
    """Rank by strongest signal, tie-broken by wasted minutes then total spend.

    Wasted minutes come second on purpose: a red workflow that runs twice a week
    matters more than a green one that is merely expensive, because the red one
    is also blocking whatever it gates.
    """
    severity = cfg["severity"]
    strongest = max((severity.get(s, 0) for s in cand["signals"]), default=0)
    usage = cand.get("usage") or {}
    return (strongest * 1000.0
            + float(usage.get("waste_min") or 0) * 2.0
            + float(usage.get("total_min") or 0) * 0.1)


def classify(cand: dict, hub: str) -> str:
    return "hub" if cand["nwo"] == hub else "submodule"


def fix_angle(signals: set[str]) -> str:
    tips = []
    if "failing" in signals:
        tips.append("read the failing run's log, find the specific failing step, and fix "
                    "the root cause (a missing dependency, a moved path, an expired "
                    "action version) — do not paper over it with `continue-on-error`")
    if "flaky" in signals:
        tips.append("identify what makes it non-deterministic (network, timing, ordering) "
                    "and pin or isolate it rather than adding blanket retries")
    if "slow" in signals:
        tips.append("profile the slowest run's step timings, then add dependency caching, "
                    "`concurrency: cancel-in-progress`, `paths:`/branch filters, a "
                    "`timeout-minutes` ceiling, or trim the matrix")
    if "high-cost-low-value" in signals:
        tips.append("most of its minutes end in non-success — either fix the root failure "
                    "or gate the triggers so the spend stops")
    if "cancel-heavy" in signals:
        tips.append("check whether `cancel-in-progress: true` is ALREADY set — if so the "
                    "cancellations are correct and the fix is to start fewer runs "
                    "(narrower `paths:`/branch filters, a job-level `if:` guard), not to "
                    "add more cancelling")
    if "cron-heavy" in signals:
        tips.append("reduce the `schedule` cadence or convert it to an event-driven trigger")
    return "; ".join(tips) or "review triggers, caching, and job structure for waste"


# --------------------------------------------------------------------------- #
# work order
# --------------------------------------------------------------------------- #
def render(cands: list[dict], cfg: dict, hub: str, usage: dict, triage: dict,
           stats: dict) -> str:
    L: list[str] = []
    L.append("# Fleet doctor — remediation work order")
    L.append("")
    L.append(f"Signals: `_data/fleet_triage.yml` ({triage.get('generated_at', '?')}) "
             f"+ `_data/actions_usage.yml` ({usage.get('generated_at', '?')}, "
             f"{usage.get('window_days', '?')}d window)")
    t = triage.get("totals", {}) or {}
    u = usage.get("totals", {}) or {}
    L.append(f"Fleet: **{t.get('failing_workflows', '?')} failing workflow(s)** across "
             f"{t.get('repos_red', '?')} red repo(s) · "
             f"{u.get('total_hours', '?')}h of Actions consumed · "
             f"{u.get('waste_hours', '?')}h wasted · "
             f"{u.get('effectiveness_pct', '?')}% effective")
    L.append("")
    L.append(f"Triage: {stats['total']} problem workflow(s) detected · "
             f"{stats['deduped']} already have an open issue/PR · "
             f"{len(cands)} on this run's queue "
             f"(cap {cfg['max_candidates']}, of which ≤{cfg['max_cross_repo']} cross-repo).")
    L.append("")

    if not cands:
        L.append("**Nothing to do.** Every failing or expensive workflow already has an "
                 "open issue or fix PR, or none crossed the thresholds. This is the "
                 "healthy steady state — do not invent work.")
        L.append("")
        return "\n".join(L)

    for i, c in enumerate(cands, 1):
        sig = ", ".join(sorted(c["signals"])) or "priority"
        where = c["_where"]
        L.append("---")
        L.append("")
        L.append(f"## {i}. {c['repo']}/{c['workflow']}  `[{sig}]`")
        L.append("")
        L.append(f"- **Fix location:** `{where}` — "
                 + ("edit it in this checkout and open a draft PR here."
                    if where == "hub" else
                    f"the fix belongs in **{c['nwo']}**; clone that repo and open a "
                    f"draft PR there."))
        L.append(f"- **Repo:** {c['nwo']} — {c['repo_url']}"
                 + ("  _(private — the token may not reach it)_" if c.get("private") else ""))
        L.append(f"- **Workflow file:** `{c['path']}`")
        L.append("- **MARKER** — the FIRST line of the PR/issue body must be exactly this, "
                 "verbatim (no bullet, no backticks), or tomorrow's run re-files it:")
        L.append("")
        L.append(doctor_marker(c["key"]))
        L.append("")

        if c["failing_runs"]:
            L.append(f"- **Currently failing** ({len(c['failing_runs'])} recorded):")
            for r in c["failing_runs"][:4]:
                L.append(f"    - `{r['conclusion']}` · {r['at']} · {r['url']}")
            first = c["failing_runs"][0]["url"]
            run_id = first.rstrip("/").split("/")[-1] if first else "<run_id>"
            L.append(f"- **Read the log:** `gh run view -R {c['nwo']} {run_id} --log-failed` "
                     f"(fall back to `gh run view -R {c['nwo']} {run_id}` if logs 404).")

        usage_rec = c.get("usage")
        if usage_rec:
            L.append(f"- **Cost signal ({usage.get('window_days', '?')}d):** "
                     f"{usage_rec.get('runs')} runs · {usage_rec.get('total_min')}m total · "
                     f"{usage_rec.get('avg_min')}m avg · {usage_rec.get('p95_min')}m p95 · "
                     f"{usage_rec.get('waste_min')}m wasted · "
                     f"{usage_rec.get('effectiveness_pct')}% effective · "
                     f"{usage_rec.get('success_rate_pct')}% success · "
                     f"{usage_rec.get('runs_per_week')}/wk · "
                     f"{usage_rec.get('sched_pct')}% scheduled")
        L.append(f"- **Read the workflow:** "
                 f"`gh api repos/{c['nwo']}/contents/{c['path']} "
                 f'-H "Accept: application/vnd.github.raw"`')
        L.append(f"- **Suggested angle:** {fix_angle(c['signals'])}")
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
    cfg = load_config(Path(args.config))
    if args.limit is not None:
        cfg["max_candidates"] = args.limit
    if args.max_cross_repo is not None:
        cfg["max_cross_repo"] = args.max_cross_repo

    usage = load_yaml(Path(args.usage))
    triage = load_yaml(Path(args.triage))
    if not usage and not triage:
        sys.stderr.write(
            f"No signals: neither {args.usage} nor {args.triage} exists — "
            "run `dash-gen actions` and `dash-gen triage` first.\n")
        Path(args.out).write_text(render([], cfg, args.hub, {}, {},
                                         {"total": 0, "deduped": 0}))
        emit_output("has_candidates", "false")
        emit_output("candidate_count", 0)
        emit_output("cross_repo_count", 0)
        return 0

    owner = args.hub.split("/", 1)[0]
    cands = merge(failing_candidates(triage, owner),
                  usage_candidates(usage, cfg, owner))
    cands.sort(key=lambda c: score(c, cfg), reverse=True)
    total = len(cands)

    seen: set[str] = set()
    if not args.no_dedupe:
        seen = open_markers(args.hub)
        # Only ask the target repos that actually have a candidate — one gh call
        # per repo, so the queue's shape bounds the cost.
        targets = sorted({c["nwo"] for c in cands if c["nwo"] != args.hub})
        seen |= cross_repo_open_markers(targets[: args.max_repo_lookups])
    fresh = [c for c in cands if c["key"] not in seen]
    deduped = total - len(fresh)

    # Apply the cross-repo sub-cap while filling the overall cap, so a burst of
    # submodule failures can't consume the whole queue and starve hub fixes the
    # agent could actually land today.
    selected: list[dict] = []
    cross = 0
    for c in fresh:
        where = classify(c, args.hub)
        if where == "submodule":
            if cross >= cfg["max_cross_repo"]:
                continue
            cross += 1
        c["_where"] = where
        selected.append(c)
        if len(selected) >= cfg["max_candidates"]:
            break

    stats = {"total": total, "deduped": deduped}
    Path(args.out).write_text(render(selected, cfg, args.hub, usage, triage, stats))

    emit_output("has_candidates", "true" if selected else "false")
    emit_output("candidate_count", len(selected))
    emit_output("cross_repo_count", cross)

    sys.stderr.write(
        f"fleet-doctor: {total} problem workflow(s), {deduped} already tracked, "
        f"{len(selected)} queued ({cross} cross-repo) → {args.out}\n")
    for c in selected:
        sys.stderr.write(f"  · [{c['_where']}] {c['nwo']}/{c['workflow']} "
                         f"[{', '.join(sorted(c['signals']))}]\n")
    return 0


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--usage", default=str(USAGE_DEFAULT), metavar="PATH",
                        help="Actions analytics data (default _data/actions_usage.yml)")
    parser.add_argument("--triage", default=str(TRIAGE_DEFAULT), metavar="PATH",
                        help="fleet triage snapshot (default _data/fleet_triage.yml)")
    parser.add_argument("--config", default=str(FLEET_DEFAULT), metavar="PATH",
                        help="fleet config (default _data/fleet.yml)")
    parser.add_argument("--out", default=str(OUT_DEFAULT), metavar="PATH",
                        help="work-order output (default remediation-workorder.md)")
    parser.add_argument("--limit", type=int, default=None, metavar="N",
                        help="override remediation.max_candidates")
    parser.add_argument("--max-cross-repo", type=int, default=None, metavar="N",
                        help="override remediation.max_cross_repo")
    parser.add_argument("--hub", default="bamr87/bamr87", metavar="OWNER/REPO",
                        help="control-plane repo (default bamr87/bamr87)")
    parser.add_argument("--max-repo-lookups", type=int, default=25, metavar="N",
                        help="max target repos queried for existing fix PRs (default 25)")
    parser.add_argument("--no-dedupe", action="store_true",
                        help="skip the open-issue/PR dedupe (offline / debugging)")
    parser.set_defaults(func=run)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="remediation", description=__doc__)
    add_arguments(parser)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
