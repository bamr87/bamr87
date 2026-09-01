#!/usr/bin/env python3
"""
evolution.py — the deterministic half of the weekly per-repo evolution loop.

`dash-gen targets` decides WHICH repositories get an AI improvement pass this
week and writes each one a BRIEF, before any model runs — the same split the
other loops use (`remediate` → fleet-pulse doctor, `issues` → issue-pipeline
tiers): a deterministic, capped, deduped, auditable plan feeds an agent that
acts on it and nothing else. Consumed by .github/workflows/repo-evolution.yml.

Selection — all four must hold:
  * the registry entry opted in with `auto_evolve: true`;
  * it is a submodule (`submodule_path` set) — the loop evolves the fleet, not
    every URL the registry happens to mention;
  * its upstream is owned by the hub's owner — an external mirror (the
    microsoft/skills fork) must never receive a pull request from us, the
    same guard tools/fanout.sh applies; and
  * it is not `status: archived` — a dead repo does not get a weekly PR.

Backpressure: a repo whose previous evolution PR is still open is skipped
(`evolution.skip_when_open_pr`). One unreviewed draft is a proposal; five
stacked up is noise, and the doctor loop already learned that a loop which
re-files every cycle turns a queue into spam. An open pass is recognised by its
branch prefix OR the hidden marker in its body, so a renamed branch cannot
fool it.

The brief (`evolution-workorders/evolution-workorder-<name>.md`):
  1. the hidden marker — first line, copied verbatim into the PR body by the
     workflow, which is how next week's run knows the pass is still open;
  2. repository facts from the registry;
  3. the fleet's CURRENT SIGNALS for the repo, read from the committed
     `_data/fleet_triage.yml`: attention level, failing workflows, open issues
     and PRs. These make the pass evidence-led instead of speculative, and
     they draw the lane boundary — failing workflows belong to the fleet
     doctor and open issues to the issue pipeline, so the agent is told where
     the repo hurts AND told not to collide with the loop already on it;
  4. the operator's focus for this run, if any;
  5. the goals + method template (.github/evolution/evolve-prompt.md) and the
     category emphasis (.github/evolution/categories/<category>.md).

Stdout is the plan as one JSON object — the matrix the workflow fans out
over, plus the knobs it wires into the agent (`max_parallel`, `max_turns`,
`branch_prefix`, `label`, `marker`) so `_data/fleet.yml` stays the one place
those values are stated. Everything human-readable goes to stderr.

Deliberately dependency-light: PyYAML only. `gh` is used solely for the
open-PR dedupe, and its absence degrades to "dedupe unavailable" — never to a
crash. Fixture tests: python3 test_evolution.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_DEFAULT = REPO_ROOT / "_data" / "projects.yml"
TRIAGE_DEFAULT = REPO_ROOT / "_data" / "fleet_triage.yml"
FLEET_DEFAULT = REPO_ROOT / "_data" / "fleet.yml"
PROMPT_DIR_DEFAULT = REPO_ROOT / ".github" / "evolution"
OUT_DIR_DEFAULT = REPO_ROOT / "evolution-workorders"

BRIEF_TEMPLATE = "evolve-prompt.md"
CATEGORY_DIR = "categories"

# Every value here is overridable from `evolution:` in _data/fleet.yml.
DEFAULTS: dict = {
    "enabled": True,
    "branch_prefix": "ai-evolution",   # PR branches; also how an open pass is recognised
    "marker": "repo-evolution",        # hidden dedupe marker, `<!-- repo-evolution key="owner/repo" -->`
    "label": "ai-evolution",           # created on demand in the target repo
    "max_targets": 6,                  # repos evolved per run; the rest are logged and dropped
    "max_parallel": 2,                 # concurrent Claude passes
    "max_turns": 120,                  # per repo — one repo per job; above the 63 observed in run #1
    "skip_when_open_pr": True,         # one open evolution PR per repo at a time
    "signals": {"max_issues": 8, "max_prs": 5},
}
DEFAULT_HUB_OWNER = "bamr87"


# --------------------------------------------------------------------------- #
# config + helpers
# --------------------------------------------------------------------------- #
def load_yaml(path: Path | str):
    with Path(path).open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_config(path: Path | str | None) -> dict:
    """`evolution:` from _data/fleet.yml merged OVER the defaults (nested `signals` too).

    Merging rather than replacing matters: a fleet.yml that sets one cap must
    not silently delete the others.
    """
    fleet: dict = {}
    if path and Path(path).exists():
        fleet = load_yaml(path) or {}
    raw = fleet.get("evolution") or {}
    cfg = {**DEFAULTS, **{k: v for k, v in raw.items() if k != "signals"}}
    cfg["signals"] = {**DEFAULTS["signals"], **(raw.get("signals") or {})}
    hub = (fleet.get("hub") or {}).get("repo") or ""
    cfg["hub_owner"] = hub.split("/")[0] if "/" in hub else DEFAULT_HUB_OWNER
    return cfg


def owner_repo(repo_url: str) -> str | None:
    """https://github.com/owner/repo[.git] -> owner/repo (None when not GitHub)."""
    if not repo_url or "github.com" not in repo_url:
        return None
    tail = repo_url.split("github.com", 1)[1].lstrip(":/")
    tail = tail.removesuffix(".git").strip("/")
    parts = tail.split("/")
    if len(parts) < 2 or not parts[0] or not parts[1]:
        return None
    return f"{parts[0]}/{parts[1]}"


def marker_line(cfg: dict, nwo: str) -> str:
    return f'<!-- {cfg["marker"]} key="{nwo}" -->'


def is_dependabot(author: str | None) -> bool:
    return (author or "").lower().startswith("dependabot")


def _gh_json(cmd: list[str]) -> list[dict] | None:
    """Run a `gh ... --json` command; None means "could not ask" (offline, no
    token, no gh) — distinct from an empty answer."""
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


# --------------------------------------------------------------------------- #
# selection
# --------------------------------------------------------------------------- #
def select_targets(registry: list[dict], cfg: dict, target: str = "all") -> tuple[list[dict], list[dict]]:
    """Registry entries → (selected, dropped). Every exclusion that matters is
    recorded with a reason: opted-in repos that fail a guard, an explicit
    `--target` that does not qualify, and anything cut by the cap. Repos that
    simply never opted in are not "dropped" — they are not enrolled."""
    wanted = None if target in (None, "", "all") else target
    selected: list[dict] = []
    dropped: list[dict] = []
    matched = False
    for p in registry:
        name = p.get("name") or "?"
        if wanted and name != wanted and p.get("slug") != wanted:
            continue
        matched = True
        nwo = owner_repo(p.get("repo_url") or "")
        reason = None
        if not p.get("auto_evolve"):
            reason = "not opted in (`auto_evolve: true` is not set)"
        elif not p.get("submodule_path"):
            reason = "not a submodule"
        elif not nwo:
            reason = "repo_url is not a GitHub repository"
        elif nwo.split("/")[0].lower() != str(cfg["hub_owner"]).lower():
            reason = f"external upstream ({nwo}) — never receives our pull requests"
        elif p.get("status") == "archived":
            reason = "archived"
        if reason:
            if wanted or p.get("auto_evolve"):
                dropped.append({"name": name, "reason": reason})
            continue
        selected.append({
            "name": name,
            "nwo": nwo,
            "branch": p.get("branch") or "main",
            "category": p.get("category") or "dev-tools",
            "stack": [str(s) for s in (p.get("stack") or [])],
            "status": p.get("status") or "",
            "description": (p.get("description") or "").strip(),
            "repo_url": p.get("repo_url") or "",
            "live_url": p.get("live_url"),
            "docs_url": p.get("docs_url"),
        })
    if wanted and not matched:
        dropped.append({"name": wanted, "reason": "not in the registry (_data/projects.yml)"})
    cap = int(cfg.get("max_targets") or 0)
    if cap > 0 and len(selected) > cap:
        for t in selected[cap:]:
            dropped.append({
                "name": t["name"],
                "reason": f"over evolution.max_targets ({cap}) — raise it in _data/fleet.yml or stagger opt-ins",
            })
        selected = selected[:cap]
    return selected, dropped


# --------------------------------------------------------------------------- #
# dedupe — one open evolution PR per repo
# --------------------------------------------------------------------------- #
def open_evolution_prs(nwo: str, cfg: dict, gh=_gh_json) -> list[dict] | None:
    """Open PRs in `nwo` that belong to this loop; None when gh cannot answer."""
    prs = gh(["gh", "pr", "list", "-R", nwo, "--state", "open", "--limit", "100",
              "--json", "number,headRefName,body,url"])
    if prs is None:
        return None
    prefix = str(cfg["branch_prefix"]).rstrip("/") + "/"
    marker = marker_line(cfg, nwo)
    return [p for p in prs
            if (p.get("headRefName") or "").startswith(prefix) or marker in (p.get("body") or "")]


def dedupe(selected: list[dict], cfg: dict, gh=_gh_json) -> tuple[list[dict], list[dict]]:
    kept: list[dict] = []
    skipped: list[dict] = []
    for t in selected:
        if not cfg.get("skip_when_open_pr", True):
            t["dedupe"] = "off"
            kept.append(t)
            continue
        found = open_evolution_prs(t["nwo"], cfg, gh)
        if found is None:
            # Cannot tell (no gh / no token). Proceed and say so — the workflow
            # has already probed the token, so this only happens offline.
            t["dedupe"] = "unavailable"
            kept.append(t)
        elif found:
            ref = found[0].get("url") or f"#{found[0].get('number')}"
            skipped.append({"name": t["name"], "reason": f"previous evolution PR is still open: {ref}"})
        else:
            t["dedupe"] = "clear"
            kept.append(t)
    return kept, skipped


# --------------------------------------------------------------------------- #
# signals + brief
# --------------------------------------------------------------------------- #
def find_signals(triage: dict | None, nwo: str) -> dict | None:
    if not triage:
        return None
    for rec in triage.get("by_repo") or []:
        if (rec.get("nwo") or "").lower() == nwo.lower():
            return rec
    return None


def render_signals(rec: dict | None, triage: dict | None, cfg: dict) -> str:
    if rec is None:
        if not triage:
            return ("No triage snapshot was available (`_data/fleet_triage.yml` missing) — "
                    "proceed from the repository itself.")
        return (f"The triage snapshot ({triage.get('generated_at', '?')}) has no entry for this "
                "repository — it may be unreachable to the fleet token, or newly registered. "
                "Proceed from the repository itself.")

    sig = cfg.get("signals") or {}
    max_issues = int(sig.get("max_issues", 8))
    max_prs = int(sig.get("max_prs", 5))
    att = rec.get("attention") or {}
    lines = [f"Snapshot: `_data/fleet_triage.yml`, generated {(triage or {}).get('generated_at', '?')}. "
             "Observations, not orders — see the lane rules in the workflow prompt.", ""]
    reasons = "; ".join(att.get("reasons") or []) or "nothing flagged"
    lines.append(f"- **Attention:** {att.get('level', '?')} (score {att.get('score', 0)}) — {reasons}")

    failing = (rec.get("workflows") or {}).get("failing") or []
    if failing:
        lines.append(f"- **Failing workflows ({len(failing)})** — the fleet doctor's lane. "
                     "Do not edit these workflow files; do read their logs if they explain a docs gap:")
        for f in failing[:6]:
            path = f.get("path") or f.get("workflow") or "?"
            lines.append(f"  - `{path}` — {f.get('workflow', '?')} ({f.get('conclusion', '?')}, "
                         f"{f.get('run_at', '?')}) {f.get('run_url', '')}".rstrip())
    else:
        lines.append("- **Workflows:** none failing")

    iss = rec.get("issues") or {}
    lines.append(f"- **Open issues:** {iss.get('open', 0)} ({iss.get('stale', 0)} stale, "
                 f"{iss.get('bugs', 0)} labelled bug) — the issue pipeline's lane. Do not implement "
                 "one; do read the ones that touch what you change:")
    items = list(iss.get("items") or [])
    items.sort(key=lambda x: (0 if any(str(l).lower() == "bug" for l in (x.get("labels") or [])) else 1,
                              x.get("idle_days") if x.get("idle_days") is not None else 10**6))
    for it in items[:max_issues]:
        labels = ", ".join(str(l) for l in (it.get("labels") or [])) or "unlabelled"
        lines.append(f"  - #{it.get('number', '?')} {it.get('title', '')} — {labels}, "
                     f"{it.get('age_days', '?')}d old {it.get('url', '')}".rstrip())
    if not items:
        lines.append("  - (none listed)")

    prs = rec.get("prs") or {}
    lines.append(f"- **Open PRs:** {prs.get('open', 0)} ({prs.get('draft', 0)} draft, "
                 f"{prs.get('stale', 0)} stale, {prs.get('dependabot', 0)} dependabot, "
                 f"{prs.get('ci_failing', 0)} with failing CI) — do not rebase, close, or duplicate them:")
    pitems = [x for x in (prs.get("items") or []) if not is_dependabot(x.get("author"))][:max_prs]
    for it in pitems:
        flags = []
        if it.get("draft"):
            flags.append("draft")
        if it.get("ci") == "fail":
            flags.append("CI failing")
        idle = it.get("idle_days")
        if isinstance(idle, int) and idle > 14:
            flags.append(f"idle {idle}d")
        lines.append(f"  - #{it.get('number', '?')} {it.get('title', '')} — "
                     f"{', '.join(flags) or 'open'} {it.get('url', '')}".rstrip())
    if not pitems:
        lines.append("  - (none listed beyond dependabot)")
    return "\n".join(lines)


def render_template(text: str, subs: dict[str, str]) -> str:
    for token, value in subs.items():
        text = text.replace(token, value)
    return text


def render_brief(t: dict, cfg: dict, triage: dict | None, prompt_dir: Path | str,
                 focus: str, now: str) -> str:
    prompt_dir = Path(prompt_dir)
    stack = ", ".join(t.get("stack") or []) or "unknown"
    subs = {
        "{{REPO_NAME}}": t["name"],
        "{{NWO}}": t["nwo"],
        "{{BRANCH}}": t["branch"],
        "{{CATEGORY}}": t["category"],
        "{{STACK}}": stack,
        "{{DESCRIPTION}}": t.get("description") or "(no description in the registry)",
        "{{STATUS}}": t.get("status") or "unknown",
    }
    base_path = prompt_dir / BRIEF_TEMPLATE
    base = render_template(base_path.read_text(encoding="utf-8"), subs) if base_path.exists() else (
        f"_Brief template `{base_path.name}` is missing from `{prompt_dir}` — improve documentation, "
        "clarity, and functionality, in that order, surgically._")
    cat_path = prompt_dir / CATEGORY_DIR / f"{t['category']}.md"
    cat = render_template(cat_path.read_text(encoding="utf-8"), subs) if cat_path.exists() else (
        f"_No category emphasis file for `{t['category']}` — apply the general goals._")

    facts = [
        f"- **Name:** {t['name']} · **Upstream:** {t['repo_url']} · **Branch:** `{t['branch']}`",
        f"- **Category:** {t['category']} · **Status:** {t.get('status') or 'unknown'} · **Stack:** {stack}",
        f"- **Description:** {subs['{{DESCRIPTION}}']}",
    ]
    if t.get("live_url"):
        facts.append(f"- **Live:** {t['live_url']}")
    if t.get("docs_url"):
        facts.append(f"- **Docs:** {t['docs_url']}")

    parts = [
        marker_line(cfg, t["nwo"]),
        f"# Evolution brief — {t['name']}",
        "",
        f"Prepared {now} by `dash-gen targets` for `{t['nwo']}` @ `{t['branch']}`. This file is the "
        "agent's complete brief — facts, signals, focus, goals, emphasis. The hard rules (draft-only, "
        "surgical, lanes) live in the workflow prompt and are not repeated here.",
        "",
        "## Repository (from the registry)",
        "",
        *facts,
        "",
        "## Signals (the fleet's current view of this repository)",
        "",
        render_signals(find_signals(triage, t["nwo"]), triage, cfg),
        "",
        "## Focus for this run",
        "",
        focus.strip() if focus and focus.strip() else
        "_No operator focus was given — let the signals above and the goals below choose._",
        "",
        base.rstrip(),
        "",
        cat.rstrip(),
        "",
    ]
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# plan
# --------------------------------------------------------------------------- #
def build_plan(registry: list[dict], cfg: dict, triage: dict | None, *, target: str = "all",
               focus: str = "", prompt_dir: Path | str = PROMPT_DIR_DEFAULT, gh=_gh_json,
               now: str | None = None) -> tuple[dict, dict[str, str]]:
    """The whole deterministic step: select → dedupe → brief. `gh=None` skips
    the open-PR check entirely (offline / `force`)."""
    now = now or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    selected, dropped = select_targets(registry, cfg, target)
    skipped: list[dict] = []
    if gh is not None:
        selected, skipped = dedupe(selected, cfg, gh)
    briefs: dict[str, str] = {}
    include: list[dict] = []
    for t in selected:
        fname = f"evolution-workorder-{t['name']}.md"
        briefs[fname] = render_brief(t, cfg, triage, prompt_dir, focus, now)
        include.append({
            "name": t["name"],
            "nwo": t["nwo"],
            "branch": t["branch"],
            "category": t["category"],
            "brief": fname,
            "marker": marker_line(cfg, t["nwo"]),
            "dedupe": t.get("dedupe", "off"),
        })
    plan = {
        "generated_at": now,
        "count": len(include),
        "include": include,
        "max_parallel": int(cfg["max_parallel"]),
        "max_turns": int(cfg["max_turns"]),
        "branch_prefix": str(cfg["branch_prefix"]),
        "label": str(cfg["label"]),
        "marker": str(cfg["marker"]),
        "focus": focus or "",
        "dropped": dropped,
        "skipped": skipped,
    }
    return plan, briefs


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target", default="all", metavar="NAME|all",
                        help="one registry name (or slug), or every opted-in submodule (default all)")
    parser.add_argument("--focus", default="", metavar="TEXT",
                        help="operator focus for this run, quoted into every brief")
    parser.add_argument("--out-dir", default=str(OUT_DIR_DEFAULT), metavar="DIR",
                        help="where the briefs are written (default evolution-workorders/, gitignored)")
    parser.add_argument("--registry", default=str(REGISTRY_DEFAULT), metavar="PATH",
                        help="project registry (default _data/projects.yml)")
    parser.add_argument("--triage", default=str(TRIAGE_DEFAULT), metavar="PATH",
                        help="fleet triage snapshot for the signals (default _data/fleet_triage.yml)")
    parser.add_argument("--config", default=str(FLEET_DEFAULT), metavar="PATH",
                        help="fleet config (default _data/fleet.yml)")
    parser.add_argument("--prompt-dir", default=str(PROMPT_DIR_DEFAULT), metavar="DIR",
                        help="brief template + category emphasis (default .github/evolution/)")
    parser.add_argument("--limit", type=int, default=None, metavar="N",
                        help="override evolution.max_targets")
    parser.add_argument("--no-dedupe", action="store_true",
                        help="skip the open-PR check (offline, or the workflow's `force` input)")
    parser.add_argument("--no-briefs", action="store_true",
                        help="plan only — print the JSON, write no files")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config))
    if args.limit is not None:
        cfg["max_targets"] = args.limit
    if not cfg.get("enabled", True):
        sys.stderr.write("repo evolution is disabled in _data/fleet.yml (evolution.enabled) — empty plan\n")
        print(json.dumps({"count": 0, "include": [], "dropped": [], "skipped": [], "disabled": True},
                         separators=(",", ":")))
        return 0

    registry = load_yaml(args.registry) or []
    triage = load_yaml(args.triage) if Path(args.triage).exists() else None
    plan, briefs = build_plan(registry, cfg, triage, target=args.target, focus=args.focus,
                              prompt_dir=Path(args.prompt_dir),
                              gh=None if args.no_dedupe else _gh_json)

    if not args.no_briefs and briefs:
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        for fname, text in briefs.items():
            (out / fname).write_text(text, encoding="utf-8")
        sys.stderr.write(f"Wrote {len(briefs)} brief(s) to {out}/\n")

    for t in plan["include"]:
        note = "" if t["dedupe"] in ("clear", "off") else f"  [dedupe {t['dedupe']}]"
        sys.stderr.write(f"  ▶ {t['name']}  {t['nwo']} @ {t['branch']}  ({t['category']}){note}\n")
    for d in plan["dropped"]:
        sys.stderr.write(f"  – {d['name']}: {d['reason']}\n")
    for s in plan["skipped"]:
        sys.stderr.write(f"  ⏭ {s['name']}: {s['reason']}\n")
    sys.stderr.write(f"Selected {plan['count']} target(s); {len(plan['dropped'])} dropped, "
                     f"{len(plan['skipped'])} skipped (open PR).\n")

    print(json.dumps(plan, separators=(",", ":")))
    # An explicit ask that yields nothing is an error the caller should see —
    # the dispatch path would otherwise "succeed" with no work.
    if args.target not in ("", "all") and plan["count"] == 0:
        return 1
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(p)
    raise SystemExit(run(p.parse_args()))
