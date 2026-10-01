#!/usr/bin/env python3
"""
steward — the deterministic half of the weekly fleet-steward loop
(.github/workflows/fleet-steward.yml, docs/STEWARD.md).

The loop reads EVERY open issue and pull request across the fleet, writes a
comprehensive, logged update, and acts on the single most critical, complex,
or harmonizing need. A Fable orchestrator does the reading and the choosing; a
Sonnet developer does the work. Everything that does not need a model lives
here, so it is reproducible and testable offline:

  plan      the fleet triage snapshot + the steward ledger -> a bounded brief
            (brief.md), the candidate list (candidates.json), and a JSON plan
            on stdout for the workflow. Every candidate carries the LANE that
            already owns it (issue pipeline, dependabot, held, work in flight),
            so the orchestrator acts only where no other loop does — and the
            brief surfaces cross-repo THEMES, because a need that recurs across
            the fleet is usually fixed once, at the hub, not N times.
  validate  the orchestrator's decision.json -> key=value lines for
            $GITHUB_OUTPUT. A decision that names a repo outside the fleet, an
            empty plan, or a non-GitHub reference is downgraded to "report
            only" — the developer never runs on a malformed brief.
  record    the report + the decision + the outcome -> _reports/steward/<date>.md
            (the LOG) and one row in _data/steward.yml (the TRACK).

Dependency-light: PyYAML only, no network — the workflow does the GitHub calls.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
FLEET_DEFAULT = REPO_ROOT / "_data" / "fleet.yml"
REGISTRY_DEFAULT = REPO_ROOT / "_data" / "projects.yml"
TRIAGE_DEFAULT = REPO_ROOT / "_data" / "fleet_triage.yml"

DEFAULTS = {
    "models": {"orchestrator": "claude-fable-5-1", "developer": "claude-sonnet-5"},
    "orchestrator_max_turns": 60,
    "developer_max_turns": 150,
    "max_candidates": 150,
    "max_themes": 12,
    "branch_prefix": "fleet-steward",
    "label": "fleet-steward",
    "marker": "<!-- fleet-steward key={key} -->",
    "report_dir": "_reports/steward",
    "ledger": "_data/steward.yml",
    "history": 52,
    "hub": "bamr87/bamr87",
}
# Labels that mean another loop (or a human) already owns the item.
PIPELINE_PREFIX = "agent:"
HELD_LABELS = {"agent:hold", "human-review", "blocked", "wontfix", "on-hold"}
CRITICAL_LABELS = {"critical", "p0", "priority:critical", "priority:high", "urgent", "security", "regression"}
BUG_LABELS = {"bug", "type:bug", "kind:bug", "defect"}
STOP = set("""a an and are as at be but by for from has have in into is it its of on or that the this to was
were will with without not no fix fixes fixed add adds added update updates updated bump bumps chore feat docs
doc ci test tests refactor build use uses using make makes when then than via per new old one all any can only
should need needs more less into onto over under after before still also from main repo repos issue issues
pr prs pull request requests version versions dependabot group""".split())


def load_yaml(path: Path | str):
    p = Path(path)
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


def load_config(path: Path | str | None = None) -> dict:
    fleet = load_yaml(path or FLEET_DEFAULT)
    cfg = {**DEFAULTS, **(fleet.get("steward") or {})}
    cfg["models"] = {**DEFAULTS["models"], **((fleet.get("steward") or {}).get("models") or {})}
    cfg["hub"] = (fleet.get("hub") or {}).get("repo") or DEFAULTS["hub"]
    return cfg


def owner_repo(url: str) -> str | None:
    if not url or "github.com/" not in url:
        return None
    tail = url.split("github.com/", 1)[1].rstrip("/").removesuffix(".git")
    return tail if tail.count("/") == 1 else None


# --------------------------------------------------------------------------- #
# plan
# --------------------------------------------------------------------------- #
def _items(block) -> list[dict]:
    if isinstance(block, dict):
        return list(block.get("items") or [])
    return list(block or [])


def lane_of(kind: str, item: dict) -> str:
    """Which loop (or person) already owns this item. `open` = nobody does."""
    labels = {str(x).lower() for x in item.get("labels") or []}
    if labels & HELD_LABELS:
        return "held"
    if any(lbl.startswith(PIPELINE_PREFIX) for lbl in labels):
        return "issue-pipeline"
    if kind == "pr" and item.get("dependabot"):
        return "dependabot"
    if kind == "pr":
        return "in-flight"
    return "open"


def priority(kind: str, item: dict) -> int:
    """Deterministic ORDER for the brief — not the pick. The orchestrator
    weighs criticality, complexity and harmony itself; this only decides what
    is shown first when the brief has to be cut."""
    labels = {str(x).lower() for x in item.get("labels") or []}
    score = 0
    if labels & CRITICAL_LABELS:
        score += 50
    if labels & BUG_LABELS:
        score += 30
    if kind == "pr" and str(item.get("ci") or "").lower() in ("failure", "failing", "red"):
        score += 35
    if kind == "pr" and item.get("dependabot"):
        score -= 20
    score += min(int(item.get("age_days") or 0), 120) // 4
    if int(item.get("idle_days") or 0) > 30:
        score += 10
    return score


def tokens(title: str) -> set[str]:
    t = re.sub(r"^[a-z]+(\([^)]*\))?!?:\s*", "", (title or "").lower())   # conventional-commit prefix
    return {w for w in re.findall(r"[a-z][a-z0-9.+-]{3,}", t) if w not in STOP}


def themes(cands: list[dict], min_repos: int = 3, limit: int = 12) -> list[dict]:
    """Cross-repo themes: a significant word that recurs in open items across
    at least `min_repos` repositories. A need that shows up across the fleet is
    the harmonizing kind — usually fixed once, at the hub, not N times."""
    by_token: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for c in cands:
        for tok in tokens(c["title"]):
            by_token[tok][c["repo"]].append(c)
    out = []
    for tok, repos in by_token.items():
        if len(repos) >= min_repos:
            refs = [c for items in repos.values() for c in items]
            out.append({"theme": tok, "repos": sorted(repos), "count": len(refs),
                        "examples": [c["url"] for c in sorted(refs, key=lambda c: -c["priority"])[:5]]})
    out.sort(key=lambda t: (-len(t["repos"]), -t["count"], t["theme"]))
    return out[:limit]


def candidates(triage: dict) -> list[dict]:
    out = []
    for r in triage.get("by_repo") or []:
        if r.get("external") or r.get("archived"):
            continue
        for kind, block in (("issue", r.get("issues")), ("pr", r.get("prs"))):
            for it in _items(block):
                c = {"repo": r.get("name"), "nwo": r.get("nwo"), "kind": kind,
                     "number": it.get("number"), "title": it.get("title") or "",
                     "labels": list(it.get("labels") or []), "age_days": it.get("age_days"),
                     "idle_days": it.get("idle_days"), "url": it.get("url"),
                     "ci": it.get("ci") or "", "draft": bool(it.get("draft")),
                     "dependabot": bool(it.get("dependabot"))}
                c["lane"] = lane_of(kind, c)
                c["priority"] = priority(kind, c)
                out.append(c)
    out.sort(key=lambda c: (-c["priority"], c["repo"] or "", c["number"] or 0))
    return out


def render_brief(triage: dict, cands: list[dict], themes_: list[dict], ledger: dict,
                 cfg: dict, focus: str, today: str) -> str:
    totals = triage.get("totals") or {}
    shown = cands[: int(cfg["max_candidates"])]
    lanes = defaultdict(int)
    for c in cands:
        lanes[c["lane"]] += 1
    L = [f"# Fleet steward brief — {today}", "",
         f"Snapshot: `_data/fleet_triage.yml` generated {triage.get('generated_at', '?')}, "
         f"{triage.get('repos_scanned', '?')} repos scanned, "
         f"{len(triage.get('repos_unreachable') or [])} unreachable "
         f"({', '.join(triage.get('repos_unreachable') or []) or 'none'}).", ""]
    if focus:
        L += ["## Operator focus", "", focus, ""]
    L += ["## Fleet totals", "", "| open issues | stale | bugs | open PRs | draft | stale PRs | CI failing | dependabot | failing workflows | red repos |",
          "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
          "| {} | {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(*(totals.get(k, "?") for k in (
              "open_issues", "stale_issues", "open_bugs", "open_prs", "draft_prs", "stale_prs",
              "prs_ci_failing", "dependabot_prs", "failing_workflows", "repos_red"))), "",
          "Who already owns what (lane → items): "
          + ", ".join(f"`{k}` {v}" for k, v in sorted(lanes.items())) + ".", ""]
    L += ["## Per repository", "", "| repo | attention | issues | bugs | stale | PRs | CI failing | dependabot | failing workflows |",
          "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for r in sorted(triage.get("by_repo") or [], key=lambda r: -((r.get("attention") or {}).get("score") or 0)):
        if r.get("external") or r.get("archived"):
            continue
        i, p, w, a = r.get("issues") or {}, r.get("prs") or {}, r.get("workflows") or {}, r.get("attention") or {}
        fails = len(w.get("failing") or []) if isinstance(w, dict) else 0
        L.append(f"| {r.get('name')} | {a.get('level', '')} {a.get('score', '')} | {i.get('open', 0)} | {i.get('bugs', 0)} "
                 f"| {i.get('stale', 0)} | {p.get('open', 0)} | {p.get('ci_failing', 0)} | {p.get('dependabot', 0)} | {fails} |")
    L += ["", "## Cross-repo themes (harmonizing candidates)", "",
          "A word that recurs in open items across three or more repositories. One fix at the hub "
          "(a kit, a template, a shared workflow) usually beats the same fix N times.", ""]
    if themes_:
        for t in themes_:
            L.append(f"- **{t['theme']}** — {t['count']} items in {len(t['repos'])} repos "
                     f"({', '.join(t['repos'][:8])}{' …' if len(t['repos']) > 8 else ''}): "
                     + " ".join(t["examples"]))
    else:
        L.append("_None this week._")
    L += ["", f"## Open items — top {len(shown)} of {len(cands)} by deterministic order", "",
          "`lane` names the loop that already owns an item: `issue-pipeline` (agent:* label — do NOT implement), "
          "`dependabot`, `in-flight` (someone's PR — do not redo it), `held` (a human said stop), `open` (nobody).", "",
          "| order | repo | kind | # | title | labels | age | idle | CI | lane |",
          "| ---: | --- | --- | ---: | --- | --- | ---: | ---: | --- | --- |"]
    for c in shown:
        title = c["title"].replace("|", "\\|")[:110]
        L.append(f"| {c['priority']} | {c['repo']} | {c['kind']} | [{c['number']}]({c['url']}) | {title} "
                 f"| {', '.join(c['labels'][:4])} | {c['age_days'] or ''} | {c['idle_days'] or ''} | {c['ci']} | {c['lane']} |")
    runs = (ledger.get("runs") or [])[-5:]
    L += ["", "## What this loop did recently", ""]
    if runs:
        for run in reversed(runs):
            L.append(f"- {run.get('date')}: {'acted on' if run.get('act') else 'reported only —'} "
                     f"{run.get('title') or '(no pick)'} → {run.get('pr_url') or 'no PR'}")
        L.append("")
        L.append("Do not pick a need a recent run already has an open PR for.")
    else:
        L.append("_First run._")
    return "\n".join(L) + "\n"


def build_plan(triage: dict, ledger: dict, cfg: dict, focus: str = "", today: str | None = None):
    today = today or dt.date.today().isoformat()
    cands = candidates(triage)
    th = themes([c for c in cands if c["lane"] in ("open", "in-flight")], limit=int(cfg["max_themes"]))
    brief = render_brief(triage, cands, th, ledger, cfg, focus, today)
    last = (ledger.get("runs") or [])[-1:] or [{}]
    plan = {
        "date": today,
        "candidates": len(cands),
        "actionable": sum(1 for c in cands if c["lane"] == "open"),
        "themes": len(th),
        "models": cfg["models"],
        "orchestrator_max_turns": int(cfg["orchestrator_max_turns"]),
        "developer_max_turns": int(cfg["developer_max_turns"]),
        "branch_prefix": cfg["branch_prefix"],
        "label": cfg["label"],
        "report_path": f"{cfg['report_dir']}/{today}.md",
        "last_pr_url": last[0].get("pr_url") or "",
    }
    return brief, cands, th, plan


# --------------------------------------------------------------------------- #
# validate
# --------------------------------------------------------------------------- #
def fleet_targets(registry: list, cfg: dict) -> dict[str, str]:
    """{owner/repo: default branch} for every repo the developer may touch:
    the hub and every non-archived registry repo the hub's owner owns."""
    owner = cfg["hub"].split("/")[0]
    out = {cfg["hub"]: "main"}
    for p in registry or []:
        nwo = owner_repo((p or {}).get("repo_url") or "")
        if nwo and nwo.split("/")[0] == owner and p.get("status") != "archived":
            out[nwo] = p.get("branch") or "main"
    return out


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:48] or "pick"


def validate(decision: dict, targets: dict[str, str], cfg: dict) -> dict:
    """The orchestrator's decision, checked. Anything malformed becomes
    act=false with the reason — the developer never runs on a bad brief."""
    out = {"act": "false", "target": "", "base": "", "title": "", "key": "", "risk": "", "reason": ""}
    if not isinstance(decision, dict):
        out["reason"] = "decision.json is not an object"
        return out
    out["title"] = str(decision.get("title") or "").strip().replace("\n", " ")[:120]
    if not decision.get("act"):
        out["reason"] = str(decision.get("why_not") or "the orchestrator chose to report only")[:300]
        return out
    target = str(decision.get("target") or "").strip()
    refs = decision.get("refs") or []
    problems = []
    if target not in targets:
        problems.append(f"target {target!r} is not the hub or a fleet repo")
    if not out["title"]:
        problems.append("no title")
    if len(str(decision.get("plan") or "").strip()) < 40:
        problems.append("the plan is empty or too thin to act on")
    if not isinstance(refs, list) or not all(isinstance(r, str) and r.startswith("https://github.com/") for r in refs):
        problems.append("refs must be a list of https://github.com/ URLs")
    risk = str(decision.get("risk") or "medium").lower()
    if risk not in ("low", "medium", "high"):
        problems.append(f"risk {risk!r} is not low/medium/high")
    if problems:
        out["reason"] = "; ".join(problems)
        return out
    out.update(act="true", target=target, base=targets[target], risk=risk,
               key=f"{target}:{slug(out['title'])}")
    return out


# --------------------------------------------------------------------------- #
# record
# --------------------------------------------------------------------------- #
def record(report: str, decision: dict, verdict: dict, outcome: dict, ledger: dict,
           cfg: dict, today: str) -> tuple[str, dict]:
    """(the logged report, the updated ledger)."""
    lines = [report.rstrip(), "", "---", "", "## This run", "",
             f"- **Pick:** {verdict.get('title') or '(none)'}"
             + (f" — `{verdict['target']}`, risk {verdict.get('risk')}" if verdict.get("act") == "true" else ""),
             f"- **Acted:** {'yes' if verdict.get('act') == 'true' else 'no — ' + (verdict.get('reason') or 'report only')}",
             f"- **Pull request:** {outcome.get('pr_url') or 'none'}",
             f"- **Spend:** orchestrator ${outcome.get('cost_orchestrate') or 0} ({cfg['models']['orchestrator']}), "
             f"developer ${outcome.get('cost_develop') or 0} ({cfg['models']['developer']}) — billed to the hub's ANTHROPIC_API_KEY",
             f"- **Run:** {outcome.get('run_url') or ''}", ""]
    row = {"date": today, "run_url": outcome.get("run_url") or "",
           "act": verdict.get("act") == "true", "target": verdict.get("target") or "",
           "title": verdict.get("title") or "", "kind": str((decision or {}).get("kind") or ""),
           "refs": list((decision or {}).get("refs") or [])[:10],
           "reason": verdict.get("reason") or "", "pr_url": outcome.get("pr_url") or "",
           "cost_orchestrate": float(outcome.get("cost_orchestrate") or 0),
           "cost_develop": float(outcome.get("cost_develop") or 0),
           "report": f"{cfg['report_dir']}/{today}.md"}
    runs = [r for r in (ledger.get("runs") or []) if r.get("run_url") != row["run_url"] or not row["run_url"]]
    runs.append(row)
    new = {"schema": "steward/v1", "updated": today, "models": cfg["models"],
           "runs": runs[-int(cfg["history"]):]}
    return "\n".join(lines) + "\n", new


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("action", choices=["plan", "validate", "record"])
    parser.add_argument("--config", default=str(FLEET_DEFAULT), metavar="PATH")
    parser.add_argument("--registry", default=str(REGISTRY_DEFAULT), metavar="PATH")
    parser.add_argument("--triage", default=str(TRIAGE_DEFAULT), metavar="PATH")
    parser.add_argument("--ledger", default=None, metavar="PATH", help="default: steward.ledger in fleet.yml")
    parser.add_argument("--out-dir", default="steward-brief", metavar="DIR", help="plan: where brief.md lands")
    parser.add_argument("--focus", default="", metavar="TEXT", help="plan: operator focus, quoted into the brief")
    parser.add_argument("--date", default=None, metavar="YYYY-MM-DD")
    parser.add_argument("--decision", default=None, metavar="PATH", help="validate/record: decision.json")
    parser.add_argument("--report", default=None, metavar="PATH", help="record: the orchestrator's report.md")
    parser.add_argument("--pr-url", default="", metavar="URL")
    parser.add_argument("--cost-orchestrate", default="0")
    parser.add_argument("--cost-develop", default="0")
    parser.add_argument("--run-url", default="")
    parser.set_defaults(func=run)


def _read_decision(path: str | None) -> dict | None:
    if not path or not Path(path).exists():
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def run(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    ledger_path = Path(args.ledger) if args.ledger else REPO_ROOT / cfg["ledger"]
    ledger = load_yaml(ledger_path)
    today = args.date or dt.date.today().isoformat()

    if args.action == "plan":
        triage = load_yaml(args.triage)
        if not triage.get("by_repo"):
            sys.stderr.write(f"no triage snapshot at {args.triage} — run `dash-gen triage` first\n")
            return 1
        brief, cands, th, plan = build_plan(triage, ledger, cfg, args.focus, today)
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "brief.md").write_text(brief, encoding="utf-8")
        (out / "candidates.json").write_text(json.dumps(cands, indent=1), encoding="utf-8")
        (out / "themes.json").write_text(json.dumps(th, indent=1), encoding="utf-8")
        sys.stderr.write(f"steward plan: {plan['candidates']} open items ({plan['actionable']} unowned), "
                         f"{plan['themes']} cross-repo themes → {out}/brief.md\n")
        print(json.dumps(plan))
        return 0

    registry = load_yaml(args.registry)
    registry = registry.get("projects", []) if isinstance(registry, dict) else registry
    targets = fleet_targets(registry, cfg)
    decision = _read_decision(args.decision)
    verdict = validate(decision if decision is not None else "missing", targets, cfg)
    if decision is None:
        verdict["reason"] = "the orchestrator produced no readable decision.json"

    if args.action == "validate":
        for k, v in verdict.items():
            print(f"{k}={str(v).replace(chr(10), ' ')}")
        return 0

    report = Path(args.report).read_text(encoding="utf-8") if args.report and Path(args.report).exists() \
        else "# Fleet steward\n\n_The orchestrator produced no report this run._\n"
    outcome = {"pr_url": args.pr_url, "cost_orchestrate": args.cost_orchestrate,
               "cost_develop": args.cost_develop, "run_url": args.run_url}
    text, new_ledger = record(report, decision or {}, verdict, outcome, ledger, cfg, today)
    rpath = REPO_ROOT / cfg["report_dir"] / f"{today}.md"
    rpath.parent.mkdir(parents=True, exist_ok=True)
    rpath.write_text(text, encoding="utf-8")
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text("# Generated by `dash-gen steward record` (fleet-steward.yml) — one row per run.\n"
                           + yaml.safe_dump(new_ledger, sort_keys=False, allow_unicode=True), encoding="utf-8")
    sys.stderr.write(f"steward record → {rpath.relative_to(REPO_ROOT)} + {ledger_path.relative_to(REPO_ROOT)}\n")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(prog="steward")
    add_arguments(p)
    a = p.parse_args()
    raise SystemExit(a.func(a))
