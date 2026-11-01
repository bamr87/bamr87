#!/usr/bin/env python3
"""
repo_scout.py — the deterministic halves of the daily repo-scout loop.

The scout is the fleet's proactive *issue* loop: every day it visits a small
SAMPLE of repositories, has an agent read each one the way a new maintainer
would, and files a few well-formed issues there — features, fixes, updates —
for the issue pipeline (issue-pipeline.yml) to triage, implement and complete.
Consumed by .github/workflows/repo-scout.yml, which runs three jobs:

  plan   (this module, `dash-gen scout`)  WHICH repos today, with a BRIEF each.
  scout  (one agent per repo)             reads the brief + the repo, writes
                                          `.scout/proposals.json`. Never files,
                                          never edits, never pushes.
  file   (this module, `dash-gen scout-file`)  validates, dedupes, caps and
                                          files the proposals with FLEET_TOKEN.

Selection — all of these must hold for a registry entry:
  * its upstream is a GitHub repo owned by the hub's owner (an external mirror
    such as microsoft/skills never gets our issues — the fanout.sh guard);
  * its registry `status` is in `scout.statuses` (archived never qualifies);
  * it did not opt out with `scout: false`.

Rotation — deterministic, stateless: the eligible set is sorted by name and
walked `sample` repos per day from an offset derived from the calendar day, so
every repo is visited about every ceil(n / sample) days and two runs on the
same day pick the same repos. Backpressure then skips a repo that still
carries `max_open_per_repo` open scout issues (recognised by the loop's label
and its hidden marker) and takes the next one in the rotation instead.

Filing — the agent proposes; this module decides. A proposal is rejected when
its title or body is too short, its kind is unknown, or its title duplicates an
open issue (exact after normalisation, or a word-overlap Jaccard ≥ 0.6). The
survivors are capped at `max_issues_per_repo`, labelled from the issue
pipeline's own taxonomy (type / priority / size + the scout label), and filed
with the marker as the FIRST line of the body. Nothing merges, closes or
edits an existing issue — ever.

The agent's prompt — the HARD rules: propose-only, the lanes — is not here and
not in the workflow: it is the JEV step spec tools/jev/steps/repo-scout/
(scout.yml + scout.prompt.txt, docs/adr/0002). The plan renders it per leg
into include[].prompt, the matrix carries it to the agent step as
`prompt: ${{ matrix.prompt }}`, and the local loop engine renders the same
bytes from the same spec.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib
import json
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

import evolution

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_DEFAULT = REPO_ROOT / "_data" / "projects.yml"
TRIAGE_DEFAULT = REPO_ROOT / "_data" / "fleet_triage.yml"
CONFORMANCE_DEFAULT = REPO_ROOT / "_data" / "conformance.yml"
FLEET_DEFAULT = REPO_ROOT / "_data" / "fleet.yml"
PROMPT_DIR_DEFAULT = REPO_ROOT / ".github" / "scout"
CATEGORY_DIR_DEFAULT = REPO_ROOT / ".github" / "evolution" / "categories"
OUT_DIR_DEFAULT = REPO_ROOT / "scout-workorders"

BRIEF_TEMPLATE = "scout-prompt.md"
PROPOSALS_FILE = "proposals.json"
SCOUT_STEP = ("repo-scout", "scout")   # tools/jev/steps/<loop>/<step>.yml

# Every value here is overridable from `scout:` in _data/fleet.yml.
DEFAULTS: dict = {
    "enabled": True,
    "sample": 2,                  # repos visited per day
    "max_issues_per_repo": 3,     # proposals filed per visit
    "max_open_per_repo": 3,       # backpressure: skip a repo still carrying this many open scout issues
    "max_parallel": 2,
    "max_turns": 40,
    "model": "claude-sonnet-5-5",  # an exact id from fleet.yml ai_models.allowed (constitution § 13.3)
    "label": "ai-scout",          # every filed issue carries it; created on demand
    "marker": "repo-scout",       # `<!-- repo-scout key="owner/repo" -->`, first line of every body
    "kinds": ["feature", "fix", "update"],
    "statuses": ["active", "maintenance", "experiment"],
    "title_min": 8,
    "title_max": 120,
    "body_min": 80,
    "duplicate_jaccard": 0.6,
    "signals": {"max_issues": 10, "max_prs": 5},
}
KIND_TO_TYPE = {"feature": "feature", "fix": "bug", "update": "chore"}
DEFAULT_TAXONOMY = {
    "types": ["bug", "feature", "docs", "chore", "ci", "refactor", "test", "security", "question"],
    "priorities": ["P0", "P1", "P2", "P3"],
    "sizes": ["size:xs", "size:s", "size:m", "size:l", "size:xl"],
}
LABEL_COLOR = ("7057FF", "Filed by the fleet's repo scout (bamr87/bamr87 docs/SCOUT.md)")
STOPWORDS = {"a", "an", "the", "to", "of", "in", "on", "for", "and", "or", "with", "is", "are",
             "be", "as", "at", "by", "from", "that", "this", "it", "its", "into", "when", "add",
             "fix", "update", "make", "use"}
# Credential shapes a proposal must never carry. The filer posts agent text
# verbatim into public trackers, and the agent reads text anyone can write (open
# issue titles, the repository itself), so a prompt-injected "include your
# token" must stop here rather than in an issue body. GitHub tokens (classic,
# fine-grained, app/OAuth), Anthropic keys and OAuth tokens, private key blocks.
SECRET_RE = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-ant-[A-Za-z0-9_-]{20,})"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)


# --------------------------------------------------------------------------- #
# config + helpers
# --------------------------------------------------------------------------- #
def load_yaml(path: Path | str):
    # libyaml's SafeLoader when PyYAML has it: the plan reads ~350 KB of YAML
    # (fleet.yml, the registry, triage, conformance) on every run, and the pure
    # loader spends most of the plan's time parsing it. Same objects either way
    # (test_scout.py's test_loader holds them equal over _data/*.yml).
    with Path(path).open(encoding="utf-8") as fh:
        return yaml.load(fh, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))  # noqa: S506 - a SafeLoader


def load_config(path: Path | str | None) -> dict:
    """`scout:` from _data/fleet.yml merged OVER the defaults, plus the issue
    pipeline's label taxonomy (the filer labels from it, never its own list)."""
    fleet: dict = {}
    if path and Path(path).exists():
        fleet = load_yaml(path) or {}
    raw = fleet.get("scout") or {}
    cfg = {**DEFAULTS, **{k: v for k, v in raw.items() if k != "signals"}}
    cfg["signals"] = {**DEFAULTS["signals"], **(raw.get("signals") or {})}
    hub = (fleet.get("hub") or {}).get("repo") or ""
    cfg["hub_owner"] = hub.split("/")[0] if "/" in hub else evolution.DEFAULT_HUB_OWNER
    labels = ((fleet.get("issue_pipeline") or {}).get("labels") or {})
    cfg["taxonomy"] = {
        "types": [str(x) for x in (labels.get("types") or DEFAULT_TAXONOMY["types"])],
        "priorities": [str(x) for x in (labels.get("priorities") or DEFAULT_TAXONOMY["priorities"])],
        "sizes": [str(x) for x in (labels.get("sizes") or DEFAULT_TAXONOMY["sizes"])],
    }
    return cfg


def step_spec():
    """tools.jev.spec, the loader of the agent's step spec. Imported lazily with
    the hub root APPENDED to sys.path (tools/ is a namespace package), so this
    directory's own modules keep precedence."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.append(str(REPO_ROOT))
    return importlib.import_module("tools.jev.spec")


def marker_line(cfg: dict, nwo: str) -> str:
    return f'<!-- {cfg["marker"]} key="{nwo}" -->'


def _gh_json(cmd: list[str]) -> list[dict] | None:
    return evolution._gh_json(cmd)


def _gh_json_any(cmd: list[str]):
    """Like evolution._gh_json but keeps a dict answer (`gh repo view --json`
    returns an object, which the list-only helper discards as "could not ask")."""
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return None


def _gh_text(cmd: list[str]) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        sys.stderr.write(out.stderr.strip() + "\n")
        return None
    return out.stdout.strip()


# --------------------------------------------------------------------------- #
# selection + rotation
# --------------------------------------------------------------------------- #
def eligible(registry: list[dict], cfg: dict, target: str = "all") -> tuple[list[dict], list[dict]]:
    """Registry entries → (candidates, dropped). An explicit --target that does
    not qualify is reported with its reason; otherwise only opt-outs and
    archived/external entries are listed, so the plan summary explains itself."""
    wanted = None if target in (None, "", "all") else target
    candidates: list[dict] = []
    dropped: list[dict] = []
    matched = False
    statuses = {str(s) for s in (cfg.get("statuses") or [])}
    for p in registry:
        name = p.get("name") or "?"
        if wanted and name != wanted and p.get("slug") != wanted:
            continue
        matched = True
        nwo = evolution.owner_repo(p.get("repo_url") or "")
        reason = None
        if p.get("scout") is False:
            reason = "opted out (`scout: false` in the registry)"
        elif not nwo:
            reason = "repo_url is not a GitHub repository"
        elif nwo.split("/")[0].lower() != str(cfg["hub_owner"]).lower():
            reason = f"external upstream ({nwo}) — never receives our issues"
        elif p.get("status") == "archived" or p.get("github_archived"):
            reason = "archived"
        elif statuses and (p.get("status") or "") not in statuses:
            reason = f"status `{p.get('status')}` is not in scout.statuses"
        if reason:
            dropped.append({"name": name, "reason": reason})
            continue
        candidates.append({
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
    candidates.sort(key=lambda t: t["name"].lower())
    return candidates, dropped


def rotation_order(candidates: list[dict], sample: int, day: dt.date) -> list[dict]:
    """The eligible list rotated so that today's window comes first.

    Offset = (ordinal day × sample) mod n: consecutive days take consecutive
    windows, every repo is reached within ceil(n / sample) days, and the same
    day always yields the same order — no state file, nothing to drift."""
    n = len(candidates)
    if n == 0:
        return []
    sample = max(1, int(sample or 1))
    start = (day.toordinal() * sample) % n
    return candidates[start:] + candidates[:start]


def cycle_days(n: int, sample: int) -> int:
    return math.ceil(n / max(1, int(sample or 1))) if n else 0


# --------------------------------------------------------------------------- #
# GitHub state: open issues (for the brief + dedupe) and the loop's own issues
# --------------------------------------------------------------------------- #
def open_issues(nwo: str, limit: int, gh=_gh_json) -> list[dict] | None:
    rows = gh(["gh", "issue", "list", "-R", nwo, "--state", "open", "--limit", str(max(1, int(limit))),
               "--json", "number,title,url,labels,body"])
    if rows is None:
        return None
    return [{"number": r.get("number"), "title": r.get("title") or "", "url": r.get("url") or "",
             "labels": [(l.get("name") if isinstance(l, dict) else str(l)) for l in (r.get("labels") or [])],
             "body": r.get("body") or ""} for r in rows]


def has_issues(nwo: str, gh=_gh_json) -> bool | None:
    """Whether the repository accepts issues at all; None when gh cannot answer.
    amrchy had Issues switched off, which turned every proposal for it into a
    `gh issue create` failure — a plan step can know that for nothing."""
    out = gh(["gh", "repo", "view", nwo, "--json", "hasIssuesEnabled"])
    if out is None and gh is _gh_json:
        out = _gh_json_any(["gh", "repo", "view", nwo, "--json", "hasIssuesEnabled"])
    if out is None:
        return None
    if isinstance(out, list):
        out = out[0] if out else {}
    if not isinstance(out, dict) or "hasIssuesEnabled" not in out:
        return None
    return bool(out["hasIssuesEnabled"])


def scout_issues(issues: list[dict] | None, cfg: dict, nwo: str) -> list[dict]:
    """The subset of open issues this loop filed: carrying its label OR its marker."""
    if not issues:
        return []
    marker = marker_line(cfg, nwo)
    label = str(cfg["label"]).lower()
    return [i for i in issues if marker in (i.get("body") or "")
            or label in {str(l).lower() for l in (i.get("labels") or [])}]


# --------------------------------------------------------------------------- #
# brief
# --------------------------------------------------------------------------- #
def render_brief(t: dict, cfg: dict, triage: dict | None, conformance: dict | None,
                 prompt_dir: Path | str, category_dir: Path | str, focus: str, now: str,
                 issues: list[dict] | None, scout_open: list[dict]) -> str:
    prompt_dir, category_dir = Path(prompt_dir), Path(category_dir)
    stack = ", ".join(t.get("stack") or []) or "unknown"
    subs = {
        "{{REPO_NAME}}": t["name"], "{{NWO}}": t["nwo"], "{{BRANCH}}": t["branch"],
        "{{CATEGORY}}": t["category"], "{{STACK}}": stack,
        "{{DESCRIPTION}}": t.get("description") or "(no description in the registry)",
        "{{STATUS}}": t.get("status") or "unknown",
        "{{MAX_ISSUES}}": str(cfg["max_issues_per_repo"]),
        "{{KINDS}}": ", ".join(cfg["kinds"]),
        "{{TYPES}}": ", ".join(cfg["taxonomy"]["types"]),
        "{{PRIORITIES}}": ", ".join(cfg["taxonomy"]["priorities"]),
        "{{SIZES}}": ", ".join(cfg["taxonomy"]["sizes"]),
    }
    base_path = prompt_dir / BRIEF_TEMPLATE
    base = evolution.render_template(base_path.read_text(encoding="utf-8"), subs) if base_path.exists() else (
        f"_Brief template `{base_path.name}` is missing from `{prompt_dir}` — propose a few small, "
        "well-evidenced features, fixes and updates for the issue pipeline._")
    cat_path = category_dir / f"{t['category']}.md"
    cat = evolution.render_template(cat_path.read_text(encoding="utf-8"), subs) if cat_path.exists() else (
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

    if issues is None:
        # The agent holds no GitHub credential, so it cannot list them itself;
        # the filer still dedupes against the live list before anything is filed.
        open_block = ("_The open issues could not be listed when this brief was written. Propose from what "
                      "the repository shows; the filer drops anything that duplicates an open issue._")
    elif not issues:
        open_block = "_No open issues._"
    else:
        cap = int(cfg["signals"]["max_issues"])
        lines = [f"- #{i['number']} {i['title']}" + (f"  `{' '.join(i['labels'])}`" if i.get("labels") else "")
                 for i in issues[:cap]]
        if len(issues) > cap:
            lines.append(f"- … and {len(issues) - cap} more (the filer dedupes against every one of them)")
        open_block = "\n".join(lines)
    scout_block = ("_None — this is the first visit, or every earlier proposal has been closed._"
                   if not scout_open else
                   "\n".join(f"- #{i['number']} {i['title']}" for i in scout_open))

    parts = [
        marker_line(cfg, t["nwo"]),
        f"# Scout brief — {t['name']}",
        "",
        f"Prepared {now} by `dash-gen scout` for `{t['nwo']}` @ `{t['branch']}`. This file is the "
        "agent's complete brief — facts, signals, what is already filed, focus, goals, emphasis. The hard "
        "rules (propose-only, no edits, the lanes) live in the workflow prompt and are not repeated here.",
        "",
        "## Repository (from the registry)",
        "",
        *facts,
        "",
        "## Signals (the fleet's current view of this repository)",
        "",
        evolution.render_signals(evolution.find_signals(triage, t["nwo"]), triage, cfg),
        "",
        "## Conformance gaps (Universal Project Standard)",
        "",
        evolution.render_conformance(evolution.find_conformance(conformance, t["nwo"]), conformance, cfg),
        "",
        "## Open issues — do NOT propose any of these again",
        "",
        open_block,
        "",
        "## Proposals from earlier scout visits still open",
        "",
        scout_block,
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
def build_plan(registry: list[dict], cfg: dict, triage: dict | None, conformance: dict | None, *,
               day: dt.date | None = None, target: str = "all", focus: str = "",
               prompt_dir: Path | str = PROMPT_DIR_DEFAULT, category_dir: Path | str = CATEGORY_DIR_DEFAULT,
               gh=_gh_json, now: str | None = None, spec_root: Path | str | None = None
               ) -> tuple[dict, dict[str, str]]:
    """select → rotate → backpressure → brief → prompt. `gh=None` skips every
    GitHub read (offline): no backpressure, no open-issue list in the brief.
    Every leg carries the agent's prompt rendered from the step spec; a spec
    that does not load raises tools.jev.spec.StepSpecError before any leg."""
    jev = step_spec()
    spec = jev.load_spec(*SCOUT_STEP, root=Path(spec_root) if spec_root else jev.SPEC_ROOT)
    # The plan's --model and turn cap must be what the spec resolved (an exact
    # allowed id, constitution § 13.3); they can differ only under a non-default --config.
    if (str(cfg["model"]), int(cfg["max_turns"])) != (spec.resolved.model, spec.resolved.max_turns):
        raise jev.StepSpecError(f"scout config model/max_turns {cfg['model']!r}/{cfg['max_turns']} != the step "
                                f"spec's {spec.resolved.model!r}/{spec.resolved.max_turns} (_data/fleet.yml)")
    day = day or dt.datetime.now(dt.timezone.utc).date()
    now = now or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    wanted = target not in (None, "", "all")
    candidates, dropped = eligible(registry, cfg, target)
    order = candidates if wanted else rotation_order(candidates, int(cfg["sample"]), day)
    sample = len(order) if wanted else int(cfg["sample"])
    briefs: dict[str, str] = {}
    include: list[dict] = []
    skipped: list[dict] = []
    for t in order:
        if len(include) >= sample:
            break
        if gh is not None and has_issues(t["nwo"], gh) is False:
            skipped.append({"name": t["name"], "nwo": t["nwo"],
                            "reason": "issues are disabled on the repository — nothing can be filed"})
            continue
        issues = open_issues(t["nwo"], 200, gh) if gh is not None else None
        scout_open = scout_issues(issues, cfg, t["nwo"])
        if issues is not None and len(scout_open) >= int(cfg["max_open_per_repo"]):
            skipped.append({"name": t["name"], "nwo": t["nwo"],
                            "reason": f"{len(scout_open)} scout issue(s) still open (max_open_per_repo "
                                      f"{cfg['max_open_per_repo']}) — close or implement them first"})
            continue
        fname = f"scout-workorder-{t['name']}.md"
        briefs[fname] = render_brief(t, cfg, triage, conformance, prompt_dir, category_dir, focus, now,
                                     issues, scout_open)
        include.append({
            "name": t["name"], "nwo": t["nwo"], "branch": t["branch"], "category": t["category"],
            "brief": fname, "marker": marker_line(cfg, t["nwo"]),
            "open_issues": None if issues is None else len(issues),
            "scout_open": None if issues is None else len(scout_open),
            "dedupe": "unavailable" if issues is None else "clear",
        })
        # Last key: the rendered prompt is the bulk of the row (and of plan.json).
        include[-1]["prompt"] = jev.render_prompt(spec, jev.values_from(spec, include[-1]))
    plan = {
        "generated_at": now,
        "day": day.isoformat(),
        "count": len(include),
        "include": include,
        "eligible": len(candidates),
        "cycle_days": cycle_days(len(candidates), int(cfg["sample"])),
        "sample": int(cfg["sample"]),
        "max_parallel": int(cfg["max_parallel"]),
        "max_turns": int(cfg["max_turns"]),
        "max_issues_per_repo": int(cfg["max_issues_per_repo"]),
        "model": str(cfg["model"]),
        "label": str(cfg["label"]),
        "marker": str(cfg["marker"]),
        "focus": focus or "",
        "dropped": dropped,
        "skipped": skipped,
    }
    return plan, briefs


# --------------------------------------------------------------------------- #
# proposals → issues
# --------------------------------------------------------------------------- #
def normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", (title or "").lower())).strip()


def title_tokens(title: str) -> set[str]:
    return {w for w in normalize_title(title).split() if w not in STOPWORDS and len(w) > 1}


def is_duplicate(title: str, existing: list[str], threshold: float) -> str | None:
    """The existing title this one duplicates, or None."""
    norm = normalize_title(title)
    toks = title_tokens(title)
    for other in existing:
        if normalize_title(other) == norm:
            return other
        ot = title_tokens(other)
        if len(toks) >= 3 and len(ot) >= 3:
            j = len(toks & ot) / len(toks | ot)
            if j >= threshold:
                return other
    return None


def load_proposals(path: Path | str) -> tuple[list, str]:
    """The agent's file → (proposals, notes). Tolerates a bare list and a
    missing file (an agent that found nothing is a valid outcome)."""
    p = Path(path)
    if not p.exists():
        return [], ""
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"proposals file is not valid JSON ({exc}) — nothing filed\n")
        return [], ""
    if isinstance(data, list):
        return data, ""
    if isinstance(data, dict):
        return list(data.get("proposals") or []), str(data.get("notes") or "")
    return [], ""


def validate_proposals(raw: list, cfg: dict) -> tuple[list[dict], list[dict]]:
    tax = cfg["taxonomy"]
    kinds = [str(k) for k in cfg["kinds"]]
    ok: list[dict] = []
    rejected: list[dict] = []
    for i, p in enumerate(raw):
        if not isinstance(p, dict):
            rejected.append({"title": f"proposal {i + 1}", "reason": "not an object"})
            continue
        title = str(p.get("title") or "").strip()
        body = str(p.get("body") or "").strip()
        kind = str(p.get("kind") or "").strip().lower()
        if not (int(cfg["title_min"]) <= len(title) <= int(cfg["title_max"])):
            rejected.append({"title": title or f"proposal {i + 1}",
                             "reason": f"title must be {cfg['title_min']}–{cfg['title_max']} characters"})
            continue
        if len(body) < int(cfg["body_min"]):
            rejected.append({"title": title, "reason": f"body shorter than {cfg['body_min']} characters"})
            continue
        if kind not in kinds:
            rejected.append({"title": title, "reason": f"kind `{kind or '?'}` is not one of {', '.join(kinds)}"})
            continue
        if SECRET_RE.search(title) or SECRET_RE.search(body):
            # The reason is logged, so it names the shape and never echoes the match.
            rejected.append({"title": "proposal withheld", "reason": "carries a credential-shaped string"})
            continue
        typ =str(p.get("type") or KIND_TO_TYPE.get(kind, "chore")).strip().lower()
        if typ not in tax["types"]:
            typ = KIND_TO_TYPE.get(kind, "chore")
        prio = str(p.get("priority") or "P3").strip()
        if prio not in tax["priorities"]:
            prio = tax["priorities"][-1]
        size = str(p.get("size") or "size:s").strip().lower()
        if size not in tax["sizes"]:
            size = "size:s" if "size:s" in tax["sizes"] else tax["sizes"][0]
        ok.append({"title": title, "body": body, "kind": kind, "type": typ, "priority": prio, "size": size,
                   "labels": [str(cfg["label"]), typ, prio, size]})
    return ok, rejected


def issue_body(p: dict, cfg: dict, nwo: str, run_url: str) -> str:
    footer = (f"_Filed by the fleet's repo scout ({run_url or 'manual run'}; bamr87/bamr87 docs/SCOUT.md) "
              f"as a **{p['kind']}** proposal for the issue pipeline. Close it if it is wrong; label "
              "`agent:hold` to keep automation off it._")
    return f"{marker_line(cfg, nwo)}\n\n{p['body'].rstrip()}\n\n---\n{footer}\n"


def ensure_labels(nwo: str, labels: list[str], cfg: dict, gh=_gh_text) -> None:
    """Create (or refresh) the labels before filing — `gh issue create --label`
    refuses an unknown one, and a dropped label is an issue the pipeline never
    sees. Colours come from the pipeline's own catalogue so three loops never
    paint one label three ways."""
    try:
        import issue_pipeline  # noqa: WPS433 — sibling module, optional at import time
        catalogue = dict(getattr(issue_pipeline, "LABEL_COLORS", {}))
    except Exception:  # pragma: no cover — the filer must not die on an import
        catalogue = {}
    catalogue.setdefault(str(cfg["label"]), LABEL_COLOR)
    for name in labels:
        color, desc = catalogue.get(name, ("EDEDED", ""))
        gh(["gh", "label", "create", name, "-R", nwo, "--color", color, "--description", desc, "--force"])


def body_file_name(n: int, title: str) -> str:
    """`NN-<slug>.md` — the n-th (1-based) body a --bodies-dir run writes."""
    slug = "-".join(normalize_title(title).split())[:60].strip("-") or "proposal"
    return f"{n:02d}-{slug}.md"


#: why `--reviewed-bodies` withheld a proposal (tools/jev/adapters/repo_scout.py reads it)
NOT_REVIEWED = "not in the reviewed preview (its body is not byte-identical to a reviewed one)"


def file_proposals(nwo: str, proposals: list[dict], cfg: dict, *, existing_titles: list[str],
                   run_url: str = "", apply: bool = False, gh=_gh_text, bodies_dir: Path | str | None = None,
                   reviewed: set[str] | None = None) -> dict:
    """Dedupe, cap, (create labels,) file. Returns the record the run summary renders.

    `bodies_dir` (the local loop engine's; CI never passes it) also writes
    every would-file or filed issue's exact body there as `NN-<slug>.md`, so
    the human gate reads the bytes that would be filed. A dry run clears the
    directory's stale bodies first; an --apply never clears one (run_file
    refuses a non-empty one), so filing cannot destroy a reviewed preview.
    `reviewed` (sha256 hex digests, the engine's `--reviewed-bodies`) withholds
    every body that is not byte-identical to a reviewed one, before any label
    or issue is created for it."""
    cap = int(cfg["max_issues_per_repo"])
    filed: list[dict] = []
    skipped: list[dict] = []
    seen: list[str] = list(existing_titles)
    out_dir = Path(bodies_dir) if bodies_dir else None
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        for old in [] if apply else out_dir.glob("[0-9][0-9]-*.md"):
            old.unlink()   # a dry re-run never leaves a stale body beside the new ones
    for p in proposals:
        if len(filed) >= cap:
            skipped.append({"title": p["title"], "reason": f"over max_issues_per_repo ({cap})"})
            continue
        dup = is_duplicate(p["title"], seen, float(cfg["duplicate_jaccard"]))
        if dup:
            skipped.append({"title": p["title"], "reason": f"duplicates an open issue: {dup}"})
            continue
        body = issue_body(p, cfg, nwo, run_url)
        if reviewed is not None and hashlib.sha256(body.encode("utf-8")).hexdigest() not in reviewed:
            skipped.append({"title": p["title"], "reason": NOT_REVIEWED})
            continue
        seen.append(p["title"])
        rec = {"title": p["title"], "kind": p["kind"], "labels": p["labels"], "url": None}
        if apply:
            ensure_labels(nwo, p["labels"], cfg, gh)
            with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
                fh.write(body)
                body_path = fh.name
            url = gh(["gh", "issue", "create", "-R", nwo, "--title", p["title"], "--body-file", body_path,
                      "--label", ",".join(p["labels"])])
            if not url:
                skipped.append({"title": p["title"], "reason": "gh issue create failed"})
                continue
            rec["url"] = url.strip().splitlines()[-1]
        if out_dir is not None:
            rec["body_file"] = body_file_name(len(filed) + 1, p["title"])
            (out_dir / rec["body_file"]).write_text(body, encoding="utf-8")
        filed.append(rec)
    return {"nwo": nwo, "apply": apply, "filed": filed, "skipped": skipped}


# --------------------------------------------------------------------------- #
# CLI — `dash-gen scout` (plan) and `dash-gen scout-file` (file)
# --------------------------------------------------------------------------- #
def add_plan_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target", default="all", metavar="NAME|all",
                        help="one registry name (or slug) regardless of the rotation, or today's sample (default)")
    parser.add_argument("--day", default=None, metavar="YYYY-MM-DD",
                        help="the calendar day the rotation is computed for (default: today, UTC)")
    parser.add_argument("--focus", default="", metavar="TEXT",
                        help="operator focus for this run, quoted into every brief")
    parser.add_argument("--out-dir", default=str(OUT_DIR_DEFAULT), metavar="DIR",
                        help="where the briefs are written (default scout-workorders/, gitignored)")
    parser.add_argument("--registry", default=str(REGISTRY_DEFAULT), metavar="PATH")
    parser.add_argument("--triage", default=str(TRIAGE_DEFAULT), metavar="PATH")
    parser.add_argument("--conformance", default=str(CONFORMANCE_DEFAULT), metavar="PATH")
    parser.add_argument("--config", default=str(FLEET_DEFAULT), metavar="PATH")
    parser.add_argument("--prompt-dir", default=str(PROMPT_DIR_DEFAULT), metavar="DIR")
    parser.add_argument("--category-dir", default=str(CATEGORY_DIR_DEFAULT), metavar="DIR")
    parser.add_argument("--sample", type=int, default=None, metavar="N", help="override scout.sample")
    parser.add_argument("--offline", action="store_true",
                        help="no GitHub reads: no backpressure check, no open-issue list in the brief")
    parser.add_argument("--no-briefs", action="store_true", help="plan only — print the JSON, write no files")
    parser.set_defaults(func=run_plan)


def run_plan(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config))
    if args.sample is not None:
        cfg["sample"] = args.sample
    if not cfg.get("enabled", True):
        sys.stderr.write("repo scout is disabled in _data/fleet.yml (scout.enabled) — empty plan\n")
        print(json.dumps({"count": 0, "include": [], "dropped": [], "skipped": [], "disabled": True},
                         separators=(",", ":")))
        return 0
    day = dt.date.fromisoformat(args.day) if args.day else None
    registry = load_yaml(args.registry) or []
    triage = load_yaml(args.triage) if Path(args.triage).exists() else None
    conformance = load_yaml(args.conformance) if Path(args.conformance).exists() else None
    try:
        plan, briefs = build_plan(registry, cfg, triage, conformance, day=day, target=args.target,
                                  focus=args.focus, prompt_dir=Path(args.prompt_dir),
                                  category_dir=Path(args.category_dir), gh=None if args.offline else _gh_json)
    except step_spec().StepSpecError as exc:
        # Fail the plan, so no agent leg starts with a prompt nobody reviewed.
        sys.stderr.write(f"✗ {exc}\n")
        return 2
    if not args.no_briefs and briefs:
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        for fname, text in briefs.items():
            (out / fname).write_text(text, encoding="utf-8")
        (out / "plan.json").write_text(json.dumps(plan, indent=1), encoding="utf-8")
        sys.stderr.write(f"Wrote {len(briefs)} brief(s) + plan.json to {out}/\n")
    for t in plan["include"]:
        note = "" if t["dedupe"] == "clear" else f"  [dedupe {t['dedupe']}]"
        sys.stderr.write(f"  ▶ {t['name']}  {t['nwo']} @ {t['branch']}  ({t['category']}){note}\n")
    for s in plan["skipped"]:
        sys.stderr.write(f"  ⏭ {s['name']}: {s['reason']}\n")
    sys.stderr.write(f"Day {plan['day']}: {plan['count']} of {plan['eligible']} eligible repo(s) "
                     f"(sample {plan['sample']}, full cycle every {plan['cycle_days']} day(s)); "
                     f"{len(plan['dropped'])} ineligible, {len(plan['skipped'])} skipped (backpressure).\n")
    print(json.dumps(plan, separators=(",", ":")))
    if args.target not in ("", "all") and plan["count"] == 0:
        return 1
    return 0


def add_file_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--nwo", required=True, metavar="OWNER/REPO", help="the repository the proposals are for")
    parser.add_argument("--proposals", required=True, metavar="PATH", help="the agent's proposals.json")
    parser.add_argument("--run-url", default="", metavar="URL", help="the Actions run, quoted in every issue footer")
    parser.add_argument("--config", default=str(FLEET_DEFAULT), metavar="PATH")
    parser.add_argument("--apply", action="store_true", help="file the issues (default: dry run, print the plan)")
    parser.add_argument("--offline", action="store_true", help="do not list the repo's open issues for dedupe")
    parser.add_argument("--bodies-dir", default=None, metavar="DIR",
                        help="also write each would-file/filed issue body to DIR/NN-<slug>.md (the local loop "
                             "engine's human gate; CI does not pass it)")
    parser.add_argument("--reviewed-bodies", default=None, metavar="DIR",
                        help="with --apply: file only a body byte-identical to one of DIR's NN-<slug>.md files (a "
                             "reviewed preview), and file nothing (exit 3) when the open issues cannot be listed "
                             "(the local loop engine's apply; CI does not pass it)")
    parser.set_defaults(func=run_file)


def run_file(args: argparse.Namespace) -> int:
    if args.apply and args.bodies_dir and any(Path(args.bodies_dir).glob("[0-9][0-9]-*.md")):
        sys.stderr.write(f"--apply refuses a --bodies-dir that already holds bodies ({args.bodies_dir}): the apply "
                         "writes to its own directory, never over a reviewed preview\n")
        return 2
    cfg = load_config(Path(args.config))
    raw, notes = load_proposals(args.proposals)
    proposals, rejected = validate_proposals(raw, cfg)
    existing = None if args.offline else open_issues(args.nwo, 200, _gh_json)
    reviewed = None
    if args.apply and args.reviewed_bodies:
        if existing is None:
            # the reviewed preview was deduped: filing without the list could file what it dropped
            sys.stderr.write(f"could not list open issues of {args.nwo} — --reviewed-bodies files nothing without "
                             "the duplicate check\n")
            return 3
        reviewed = {hashlib.sha256(f.read_bytes()).hexdigest()
                    for f in Path(args.reviewed_bodies).glob("[0-9][0-9]-*.md") if f.is_file()}
    if existing is None and not args.offline:
        sys.stderr.write(f"could not list open issues of {args.nwo} — filing without the duplicate check\n")
    titles = [i["title"] for i in (existing or [])]
    result = file_proposals(args.nwo, proposals, cfg, existing_titles=titles, run_url=args.run_url,
                            apply=args.apply, bodies_dir=args.bodies_dir, reviewed=reviewed)
    result["rejected"] = rejected
    result["notes"] = notes
    verb = "filed" if args.apply else "would file"
    for f in result["filed"]:
        sys.stderr.write(f"  ✓ {verb}: {f['title']}  [{' '.join(f['labels'])}]  {f.get('url') or ''}\n")
    for s in result["skipped"] + rejected:
        sys.stderr.write(f"  – {s['title']}: {s['reason']}\n")
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    add_plan_arguments(sub.add_parser("plan", help="today's sample + briefs → JSON matrix"))
    add_file_arguments(sub.add_parser("file", help="validate, dedupe, cap and file an agent's proposals"))
    a = p.parse_args()
    raise SystemExit(a.func(a))
