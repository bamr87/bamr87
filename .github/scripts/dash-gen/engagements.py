#!/usr/bin/env python3
"""
engagements — the dash's client-engagement layer: deterministic estimates,
plans, and estimate-vs-actual accounting per registry project (the dash's
delivery-finance backbone; see docs/ESTIMATION.md).

Every registry project is treated as a CLIENT. A work item (a GitHub issue)
analyzed by `estimate` becomes an ENGAGEMENT: a statement of work whose cost
decomposes along the AI-era division of labor —

  ai        the implementation, performed by the agent (sessions/turns/tokens
            priced at Anthropic API list rates via ai_activity.PRICING)
  human     the broker: builds context and environment, defines goals and
            acceptance, guides, validates (hours x rate-card rate)
  platform  CI execution (minutes x Actions runner rate)

plus a confidence-based contingency, and a `traditional` comparison — what the
same scope would have cost at pre-AI consulting hours — whose ratio to the
estimate is the engagement's LEVERAGE.

  estimate  read work items from the committed fleet triage snapshot
            (_data/fleet_triage.yml, offline) or one live issue (`gh api`),
            classify each deterministically (estimator-v1: labels + title +
            rate-card tiers + per-repo calibration from _data/ai_usage.yml),
            and append draft engagements (status: estimated) to
            _data/engagements.yml. Estimates are PROPOSALS — a human approves
            by moving status to `approved` (the broker's signature).
  ledger    accrue ACTUALS from auditable evidence — claude-code-action CI
            runs, Claude-attributed commits/PRs from _data/ai_usage.yml, and
            (locally) the ai-activity ledger — into each approved/in-progress/
            delivered engagement, dedup by URL, then recompute variance and
            the per-client + fleet rollups. Also drives status transitions
            (--set-status) and broker time entry (--broker).

Both subcommands are idempotent: re-runs without new facts leave the file
byte-identical (updated_at only moves when content moves).

The register (_data/engagements.yml) is COMMITTED and public site data — no
secrets. Humans own: status, plan.*, actuals.broker_hours, and estimate
overrides (set estimate.method: manual). The generator owns: estimate fields
it wrote, actuals.entries and derived totals, variance, summary, clients.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("dash-gen requires PyYAML: pip install pyyaml\n")
    sys.exit(2)

import ai_activity  # PRICING + cache multipliers + (locally) the machine ledger

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY = REPO_ROOT / "_data" / "projects.yml"
RATES_DEFAULT = REPO_ROOT / "_data" / "engagement_rates.yml"
TRIAGE_DEFAULT = REPO_ROOT / "_data" / "fleet_triage.yml"
USAGE_DEFAULT = REPO_ROOT / "_data" / "ai_usage.yml"
OUT_DEFAULT = REPO_ROOT / "_data" / "engagements.yml"

HEADER = (
    "# =============================================================================\n"
    "# _data/engagements.yml — THE ENGAGEMENT LEDGER (client work register)\n"
    "# =============================================================================\n"
    "# Every registry project is a client; every entry is a statement of work with\n"
    "# a deterministic estimate (estimator-v1; rate card: _data/engagement_rates.yml)\n"
    "# and evidence-accrued actuals. Rendered at /engagements/; see docs/ESTIMATION.md.\n"
    "#\n"
    "# Managed by .github/scripts/dash-gen/engagements.py:\n"
    "#   tools/dash estimate   append/update draft estimates (status: estimated)\n"
    "#   tools/dash ledger     accrue actuals evidence + recompute rollups/variance\n"
    "#\n"
    "# HUMANS own (the broker's controls):\n"
    "#   status     estimated -> approved -> in_progress -> delivered -> reconciled\n"
    "#              (cancelled from any pre-reconciled state); edit here or use\n"
    "#              `tools/dash ledger --set-status ENG-NNNN=<status>`\n"
    "#   plan.*     approach / deliverables / acceptance — refine before approving\n"
    "#   actuals.broker_hours   validated human time (priced at the rate card)\n"
    "#   estimate.* overrides   set estimate.method: manual to protect from re-runs\n"
    "#\n"
    "# The GENERATOR owns: computed estimate fields, actuals.entries + derived\n"
    "# totals, variance, summary, clients. No secrets — this is public site data.\n"
    "# =============================================================================\n"
)

STATUSES = ("estimated", "approved", "in_progress", "delivered", "reconciled", "cancelled")
ACCRUING = ("approved", "in_progress", "delivered")
TRANSITIONS = {
    "estimated": {"approved", "cancelled"},
    "approved": {"in_progress", "cancelled", "estimated"},
    "in_progress": {"delivered", "cancelled", "approved"},
    "delivered": {"reconciled", "in_progress", "cancelled"},
    "reconciled": set(),
    "cancelled": {"estimated"},
}

TIER_ORDER = ["xs", "s", "m", "l", "xl"]
CONFIDENCE_ORDER = ["high", "medium", "low"]

# estimator-v1 classification: first match wins (order matters, deterministic).
LABEL_TYPES = [
    (("dependencies", "dependabot", "deps"), "deps"),
    (("security",), "security"),
    (("epic",), "epic"),
    (("bug", "defect", "deployment"), "bug"),
    (("documentation", "docs"), "docs"),
    (("ci", "github_actions", "workflow"), "ci"),
    (("feature-request", "enhancement", "feature"), "feature"),
    (("question",), "question"),
    (("chore", "maintenance"), "chore"),
]
TITLE_TYPES = [
    (re.compile(r"\b(bump|upgrade|update)\b.*\b(dependenc|version|\d+\.\d+)", re.I), "deps"),
    (re.compile(r"\b(vulnerab|cve-|security)\b", re.I), "security"),
    (re.compile(r"\b(fail(ure|ing|s)?|error|broken|fix|crash|regression)\b", re.I), "bug"),
    (re.compile(r"\b(doc(s|umentation)?|readme|typo)\b", re.I), "docs"),
    (re.compile(r"\b(ci|workflow|pipeline|action|deploy(ment)?)\b", re.I), "ci"),
    (re.compile(r"\[feature request\]|\b(feature|enhanc|add support|implement|integrat)", re.I), "feature"),
    (re.compile(r"\?\s*$|\bhow (do|to|can)\b", re.I), "question"),
]
BIG_SCOPE = re.compile(
    r"\b(integrat|migrat|refactor|redesign|rewrite|overhaul|architecture|platform|framework|end.to.end)\b",
    re.I,
)


# --------------------------------------------------------------------------- #
# shared helpers
# --------------------------------------------------------------------------- #
def now_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def today_iso() -> str:
    return dt.date.today().isoformat()


def owner_repo(repo_url: str) -> str | None:
    """https://github.com/owner/repo[.git] -> owner/repo"""
    if "github.com/" not in (repo_url or ""):
        return None
    tail = repo_url.split("github.com/", 1)[1].removesuffix(".git").strip("/")
    parts = tail.split("/")
    return f"{parts[0]}/{parts[1]}" if len(parts) >= 2 else None


def load_yaml(path: Path, what: str) -> object | None:
    try:
        with path.open() as fh:
            return yaml.safe_load(fh)
    except FileNotFoundError:
        sys.stderr.write(f"  no {what} at {path}\n")
        return None
    except yaml.YAMLError as exc:
        sys.stderr.write(f"ERROR: {what} at {path} is not valid YAML: {exc}\n")
        return None


def load_registry_clients() -> dict[str, dict]:
    """registry name -> entry, plus the hub itself as client 'bamr87'."""
    reg = load_yaml(REGISTRY, "project registry") or []
    clients = {p["name"]: p for p in reg if p.get("name")}
    clients.setdefault(
        "bamr87",
        {"name": "bamr87", "repo_url": "https://github.com/bamr87/bamr87", "category": "dash"},
    )
    return clients


def load_book(path: Path) -> dict:
    """Load engagements.yml, or a fresh empty book."""
    book = load_yaml(path, "engagement ledger")
    if not isinstance(book, dict):
        book = {}
    book.setdefault("version", 1)
    book.setdefault("summary", {})
    book.setdefault("clients", [])
    book.setdefault("engagements", [])
    return book


def write_book(path: Path, book: dict, prior_raw: str | None) -> bool:
    """Write the ledger only when content (minus updated_at) changed.

    Returns True when the file was (re)written.
    """
    def canonical(b: dict) -> str:
        c = copy.deepcopy(b)
        c.get("summary", {}).pop("updated_at", None)
        return yaml.safe_dump(c, sort_keys=False, allow_unicode=True)

    if prior_raw is not None:
        try:
            prior = yaml.safe_load(prior_raw)
        except yaml.YAMLError:
            prior = None
        if isinstance(prior, dict) and canonical(prior) == canonical(book):
            return False

    book["summary"]["updated_at"] = now_stamp()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        fh.write(HEADER)
        yaml.safe_dump(book, fh, sort_keys=False, allow_unicode=True)
    return True


def next_id(book: dict) -> str:
    top = 0
    for e in book["engagements"]:
        m = re.fullmatch(r"ENG-(\d+)", str(e.get("id", "")))
        if m:
            top = max(top, int(m.group(1)))
    return f"ENG-{top + 1:04d}"


def usd(x: float) -> float:
    return round(x + 1e-9, 2)


# --------------------------------------------------------------------------- #
# rate card
# --------------------------------------------------------------------------- #
def load_rates(path: Path) -> dict | None:
    rates = load_yaml(path, "rate card")
    if not isinstance(rates, dict):
        sys.stderr.write(
            f"ERROR: rate card missing/invalid at {path} — it is required "
            "(see _data/engagement_rates.yml).\n"
        )
        return None
    for key in ("human", "platform", "ai", "tiers", "contingency_pct", "types"):
        if key not in rates:
            sys.stderr.write(f"ERROR: rate card is missing '{key}'.\n")
            return None
    return rates


def ai_cost_from_tier(rates: dict, tier_row: dict) -> tuple[float, str]:
    """Price a tier's token profile at API list rates; returns (usd, model)."""
    model = rates["ai"].get("default_model", "claude-opus-4-8")
    p = ai_activity.PRICING.get(model)
    if not p:
        # unknown model in the rate card: price at the most expensive known row
        model_alt = max(ai_activity.PRICING, key=lambda m: ai_activity.PRICING[m]["out"])
        p, model = ai_activity.PRICING[model_alt], model_alt
    out_tok = float(tier_row.get("output_ktok", 0)) * 1000
    in_tok = float(tier_row.get("input_ktok", 0)) * 1000
    share = float(rates["ai"].get("cache_read_share_pct", 80)) / 100.0
    fresh, cached = in_tok * (1 - share), in_tok * share
    cost = (
        out_tok * p["out"]
        + fresh * p["in"] * ai_activity.CACHE_5M_MULT
        + cached * p["in"] * ai_activity.CACHE_READ_MULT
    ) / 1_000_000
    return cost, model


# --------------------------------------------------------------------------- #
# estimator-v1
# --------------------------------------------------------------------------- #
def classify(labels: list[str], title: str) -> tuple[str, list[str]]:
    lab = [str(l).lower() for l in (labels or [])]
    for keys, etype in LABEL_TYPES:
        for k in keys:
            if any(k in l for l in lab):
                return etype, [f"label:{k}"]
    for rx, etype in TITLE_TYPES:
        if rx.search(title or ""):
            return etype, [f"title:{etype}"]
    return "unknown", ["no classification signal"]


def shift(seq: list[str], value: str, steps: int) -> str:
    idx = max(0, min(len(seq) - 1, seq.index(value) + steps))
    return seq[idx]


def estimate_item(
    item: dict, client: str, nwo: str, rates: dict, calib: dict[str, float]
) -> dict:
    """Deterministic estimator-v1: work-item facts + rate card -> estimate."""
    title = item.get("title") or ""
    labels = item.get("labels") or []
    age = item.get("age_days")
    body = item.get("body") or ""

    etype, drivers = classify(labels, title)
    tconf = rates["types"].get(etype, rates["types"].get("unknown", {}))
    tier = tconf.get("base_tier", "m")
    confidence = tconf.get("confidence", "low")
    drivers.append(f"type:{etype} -> tier {tier}")

    if BIG_SCOPE.search(title) or len(title) >= 90:
        tier = shift(TIER_ORDER, tier, +1)
        drivers.append(f"broad scope in title -> tier {tier}")
    if any("good first issue" in str(l).lower() for l in labels):
        tier = shift(TIER_ORDER, tier, -1)
        drivers.append(f"good-first-issue -> tier {tier}")
    if body:  # live mode only — the triage snapshot carries no bodies
        if len(body) >= 2000 or body.count("- [ ]") >= 4:
            tier = shift(TIER_ORDER, tier, +1)
            drivers.append(f"detailed body/checklist -> tier {tier}")
    if isinstance(age, int) and age > 365:
        confidence = shift(CONFIDENCE_ORDER, confidence, +1)
        drivers.append(f"stale ({age}d) -> confidence {confidence}")

    trow = rates["tiers"][tier]
    ai_cost, model = ai_cost_from_tier(rates, trow)
    if client in calib and ai_cost > 0:
        expect = calib[client] * float(trow.get("ai_sessions", 1))
        if expect > ai_cost:
            drivers.append(
                f"calibration: {client} avg ${calib[client]:.2f}/run x "
                f"{trow.get('ai_sessions', 1)} sessions"
            )
            ai_cost = expect

    rate = float(rates["human"]["broker_rate_usd_hr"])
    broker_hours = float(trow.get("broker_hours", 0))
    ci_min = float(trow.get("ci_minutes", 0))
    # round each published component first, then derive the sums from the
    # rounded lines — the register's arithmetic always adds up to the cent
    ai_cost = usd(ai_cost)
    human_cost = usd(broker_hours * rate)
    ci_cost = usd(ci_min * float(rates["platform"]["ci_usd_per_min"]))
    subtotal = usd(ai_cost + human_cost + ci_cost)
    cont_pct = int(rates["contingency_pct"].get(confidence, 25))
    contingency = usd(subtotal * cont_pct / 100.0)
    total = usd(subtotal + contingency)

    trad_rate = float(rates["human"].get("traditional_rate_usd_hr", rate))
    trad_hours = float(trow.get("traditional_hours", 0))
    trad_cost = usd(trad_hours * trad_rate)

    return {
        "method": "estimator-v1",
        "model": model,
        "tier": tier,
        "confidence": confidence,
        "drivers": drivers,
        "ai": {
            "sessions": trow.get("ai_sessions"),
            "turns": trow.get("ai_turns"),
            "input_ktok": trow.get("input_ktok"),
            "output_ktok": trow.get("output_ktok"),
            "cost_usd": ai_cost,
        },
        "human": {
            "broker_hours": broker_hours,
            "rate_usd_hr": rate,
            "cost_usd": human_cost,
        },
        "platform": {"ci_minutes": ci_min, "cost_usd": ci_cost},
        "subtotal_usd": subtotal,
        "contingency_pct": cont_pct,
        "contingency_usd": contingency,
        "total_usd": total,
        "traditional": {
            "hours": trad_hours,
            "rate_usd_hr": trad_rate,
            "cost_usd": trad_cost,
        },
        "leverage": round(trad_cost / total, 1) if total > 0 else None,
    }


PLAN_TEMPLATES = {
    "bug": ("Reproduce, isolate root cause, fix, add a regression check.",
            ["root-cause note", "fix PR", "regression test/check"],
            ["failure no longer reproduces", "CI green", "no unrelated changes"]),
    "feature": ("Clarify scope with the broker, implement behind the smallest surface, document.",
                ["scoped implementation PR", "docs/README update", "tests"],
                ["acceptance criteria met", "CI green", "docs updated"]),
    "docs": ("Write/update the documentation in place.",
             ["docs PR"], ["accurate, linked from the relevant index", "CI green"]),
    "deps": ("Bump, run the suite, adapt call sites if the changelog demands.",
             ["dependency bump PR"], ["build + tests green on the new version"]),
    "ci": ("Diagnose the failing workflow from run logs, patch the pipeline.",
           ["workflow fix PR"], ["workflow completes green on the default branch"]),
    "security": ("Assess exposure, apply the patched version or mitigation.",
                 ["remediation PR", "impact note"], ["alert closed", "CI green"]),
    "epic": ("Broker decomposes into child engagements; estimate each separately.",
             ["decomposition into child work items"], ["children estimated individually"]),
    "chore": ("Do the maintenance task exactly as scoped.",
              ["chore PR"], ["CI green"]),
    "question": ("Answer with evidence from the codebase; convert to work item if needed.",
                 ["written answer on the issue"], ["asker unblocked or follow-up filed"]),
    "unknown": ("Broker triages: clarify intent, then re-estimate.",
                ["triage note"], ["item classified and re-estimated"]),
}


def make_engagement(eid: str, client: str, nwo: str, item: dict, est: dict) -> dict:
    etype = _plan_key(est)
    approach, deliverables, acceptance = PLAN_TEMPLATES.get(etype, PLAN_TEMPLATES["unknown"])
    return {
        "id": eid,
        "client": client,
        "nwo": nwo,
        "title": (item.get("title") or "")[:140],
        "type": etype,
        "status": "estimated",
        "opened": today_iso(),
        "delivered": None,
        "source": {
            "kind": "issue",
            "number": item.get("number"),
            "url": item.get("url"),
            "labels": (item.get("labels") or [])[:6],
            "age_days": item.get("age_days"),
        },
        "estimate": est,
        "plan": {
            "approach": approach,
            "deliverables": list(deliverables),
            "acceptance": list(acceptance),
        },
        "actuals": _zero_actuals(),
    }


def _plan_key(est: dict) -> str:
    # engagement type rides in drivers[0..] via classify(); estimate carries it
    # only implicitly, so re-derive from the recorded driver tag.
    for d in est.get("drivers", []):
        m = re.match(r"type:(\w+)", d)
        if m:
            return m.group(1)
    return "unknown"


def _zero_actuals() -> dict:
    return {
        "entries": [],
        "broker_hours": 0.0,
        "ai_cost_usd": 0.0,
        "human_cost_usd": 0.0,
        "platform_cost_usd": 0.0,
        "total_usd": 0.0,
        "turns": 0,
        "ci_minutes": 0.0,
        "commits": 0,
        "prs": 0,
        "first": None,
        "last": None,
    }


# --------------------------------------------------------------------------- #
# estimate subcommand
# --------------------------------------------------------------------------- #
def load_calibration(usage_path: Path) -> dict[str, float]:
    """repo name -> average priced cost per claude CI run (evidence history)."""
    usage = load_yaml(usage_path, "AI usage ledger")
    calib: dict[str, float] = {}
    if isinstance(usage, dict):
        for row in usage.get("by_repo", []):
            runs = (row.get("runs") or 0) - (row.get("unpriced_runs") or 0)
            cost = row.get("cost_usd") or 0.0
            if runs > 0 and cost > 0:
                calib[row["repo"]] = cost / runs
    return calib


def triage_items(triage: dict, repo_filter: str | None, include_stale: bool) -> list[tuple[str, str, dict]]:
    """(client, nwo, item) for every estimable open issue in the snapshot."""
    out: list[tuple[str, str, dict]] = []
    for r in triage.get("by_repo", []):
        if r.get("external") or r.get("archived"):
            continue
        if repo_filter and r.get("name") != repo_filter:
            continue
        for item in (r.get("issues", {}) or {}).get("items", []):
            age = item.get("idle_days")
            if not include_stale and isinstance(age, int) and age > 365:
                continue
            out.append((r["name"], r.get("nwo") or "", item))
    return out


def fetch_live_issue(nwo: str, number: int) -> dict | None:
    """One issue via `gh api` — the only network path in this module."""
    try:
        proc = subprocess.run(
            ["gh", "api", f"repos/{nwo}/issues/{number}",
             "-H", "Accept: application/vnd.github+json"],
            capture_output=True, text=True, timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        raw = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    if "pull_request" in raw:
        return None
    created = raw.get("created_at") or ""
    age = None
    try:
        age = (dt.datetime.now(dt.timezone.utc)
               - dt.datetime.fromisoformat(created.replace("Z", "+00:00"))).days
    except ValueError:
        pass
    return {
        "number": raw.get("number"),
        "title": raw.get("title") or "",
        "labels": [l.get("name") for l in raw.get("labels", []) if isinstance(l, dict)],
        "url": raw.get("html_url"),
        "age_days": age,
        "body": raw.get("body") or "",
    }


TYPE_PRIORITY = {"security": 0, "bug": 1, "ci": 2, "feature": 3, "deps": 4,
                 "docs": 5, "chore": 6, "epic": 7, "question": 8, "unknown": 9}


def run_estimate(args: argparse.Namespace) -> int:
    rates = load_rates(Path(args.rates))
    if rates is None:
        return 2
    clients = load_registry_clients()
    calib = load_calibration(Path(args.usage))
    out_path = Path(args.out)
    prior_raw = out_path.read_text() if out_path.exists() else None
    book = load_book(out_path)
    by_source = {e.get("source", {}).get("url"): e for e in book["engagements"]}

    candidates: list[tuple[str, str, dict]] = []
    if args.issue is not None:
        if not args.repo:
            sys.stderr.write("--issue requires --repo <registry name>\n")
            return 2
        client = clients.get(args.repo)
        if not client:
            sys.stderr.write(f"'{args.repo}' is not in the registry — clients must be registered projects.\n")
            return 2
        nwo = owner_repo(client.get("repo_url", "")) or ""
        item = None
        triage = load_yaml(Path(args.triage), "fleet triage snapshot")
        if isinstance(triage, dict):
            for c, n, it in triage_items(triage, args.repo, include_stale=True):
                if it.get("number") == args.issue:
                    item, nwo = it, n or nwo
                    break
        if item is None:
            sys.stderr.write(f"  #{args.issue} not in the triage snapshot; trying live via gh …\n")
            item = fetch_live_issue(nwo, args.issue)
        if item is None:
            sys.stderr.write(f"ERROR: could not load {nwo}#{args.issue} (snapshot or gh).\n")
            return 1
        candidates = [(args.repo, nwo, item)]
    else:
        triage = load_yaml(Path(args.triage), "fleet triage snapshot")
        if not isinstance(triage, dict):
            sys.stderr.write("ERROR: no triage snapshot — run `tools/dash triage` first (or pass --issue).\n")
            return 1
        candidates = triage_items(triage, args.repo, args.include_stale)
        # deterministic order: severity of type, freshest first, then repo/number;
        # then interleave clients round-robin so one repo's pile of near-identical
        # items can't consume the whole sweep.
        def key(t):
            etype, _ = classify(t[2].get("labels") or [], t[2].get("title") or "")
            return (TYPE_PRIORITY.get(etype, 9), t[2].get("age_days") or 0, t[0], t[2].get("number") or 0)
        candidates.sort(key=key)
        queues: dict[str, list] = {}
        for c in candidates:
            queues.setdefault(c[0], []).append(c)
        order = sorted(queues, key=lambda n: key(queues[n][0]))
        interleaved: list = []
        while any(queues.values()):
            for name in order:
                if queues[name]:
                    interleaved.append(queues[name].pop(0))
        candidates = interleaved

    # The sweep window is the first --limit candidates in deterministic order:
    # a re-run with the same snapshot is a no-op; raise --limit to go deeper.
    if args.issue is None:
        candidates = candidates[: args.limit]

    created = updated = skipped = 0
    for client, nwo, item in candidates:
        url = item.get("url")
        existing = by_source.get(url)
        if existing is not None and not args.re_estimate:
            skipped += 1
            continue
        est = estimate_item(item, client, nwo, rates, calib)
        if existing is None:
            eng = make_engagement(next_id(book), client, nwo, item, est)
            book["engagements"].append(eng)
            by_source[url] = eng
            created += 1
            sys.stderr.write(
                f"  + {eng['id']} {client:<20} {est['tier']:>2}/{est['confidence']:<6} "
                f"${est['total_usd']:>8,.2f}  {eng['title'][:60]}\n"
            )
        else:
            # only estimator-v1's own numbers are re-estimable; manual and
            # agent-refined estimates are protected from mechanical re-runs
            if existing.get("estimate", {}).get("method") != "estimator-v1":
                skipped += 1
                continue
            if existing.get("status") in ("estimated", "approved"):
                existing["estimate"] = est
                updated += 1
            else:
                skipped += 1

    recompute_rollups(book, rates)
    changed = write_book(out_path, book, prior_raw)
    sys.stderr.write(
        f"estimate: {created} new, {updated} re-estimated, {skipped} skipped "
        f"-> {out_path if changed else '(no change)'}\n"
    )
    return 0


# --------------------------------------------------------------------------- #
# ledger subcommand
# --------------------------------------------------------------------------- #
def evidence_rows(usage: dict) -> list[dict]:
    """Normalize ai_usage.yml ledgers into attributable evidence rows."""
    rows: list[dict] = []
    for e in usage.get("ci_ledger", []):
        # skipped gates and other no-op runs carry no spend and no work —
        # keep only runs that concluded (success/failure) or left cost/turns
        if e.get("conclusion") not in ("success", "failure") and not (
            e.get("cost_usd") or e.get("turns")
        ):
            continue
        rows.append({
            "kind": "ci_run",
            "repo": e.get("repo"),
            "day": e.get("day"),
            "cost_usd": e.get("cost_usd"),
            "turns": e.get("turns") or 0,
            "minutes": e.get("duration_min") or 0.0,
            "url": e.get("url"),
            "note": e.get("workflow"),
        })
    for c in usage.get("commit_ledger", []):
        rows.append({"kind": "commit", "repo": c.get("repo"), "day": c.get("day"),
                     "url": c.get("url"), "note": c.get("title")})
    for p in usage.get("pr_ledger", []):
        rows.append({"kind": "pr", "repo": p.get("repo"), "day": p.get("day"),
                     "url": p.get("url"), "note": p.get("title")})
    return rows


def local_evidence() -> list[dict]:
    """Per-(day, repo) shadow-priced session costs from this machine's ledger."""
    rows: list[dict] = []
    ledger_path = ai_activity.LEDGER_DEFAULT
    if not ledger_path.exists():
        return rows
    try:
        with ledger_path.open() as fh:
            ledger = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return rows
    per: dict[tuple[str, str, str], dict] = {}
    for key, row in (ledger.get("usage") or {}).items():
        try:
            machine, day, repo, model = key.split("|", 3)
        except ValueError:
            continue
        b = per.setdefault((machine, day, repo), {"cost": 0.0, "turns": 0})
        b["cost"] += ai_activity.cost_usd(model, row)
        b["turns"] += row.get("turns", 0)
    for (machine, day, repo), b in sorted(per.items()):
        if b["cost"] <= 0:
            continue
        rows.append({
            "kind": "local_day",
            "repo": repo,
            "day": day,
            "cost_usd": usd(b["cost"]),
            "turns": b["turns"],
            "minutes": 0.0,
            "url": f"local:{machine}:{day}:{repo}",
            "note": "shadow-priced local sessions",
        })
    return rows


def attribute(book: dict, rows: list[dict]) -> tuple[int, int]:
    """Accrue evidence into the oldest eligible engagement per (client, day).

    Attribution is deterministic and documented: an evidence row for repo R on
    day D goes to the engagement for client R whose status is accruing, whose
    window [opened, delivered||today] covers D, with the earliest `opened`
    (ties: lowest id). Dedup is by URL across the WHOLE register — evidence
    booked into an engagement stays booked there even after its books close
    (reconciled/cancelled), never re-attributed, never double-counted. Rows
    already booked into a still-accruing engagement are refreshed grow-only
    (ledger snapshots only grow within a day — e.g. the local machine ledger).

    Returns (added, refreshed).
    """
    added = refreshed = 0
    engs = sorted(
        (e for e in book["engagements"] if e.get("status") in ACCRUING),
        key=lambda e: (str(e.get("opened") or "9999"), str(e.get("id"))),
    )
    frozen: set[str] = set()          # urls booked in closed-book engagements
    live: dict[str, dict] = {}        # url -> entry in an accruing engagement
    for e in book["engagements"]:
        entries = (e.get("actuals") or {}).get("entries", []) or []
        if e.get("status") in ACCRUING:
            for en in entries:
                if en.get("url"):
                    live[en["url"]] = en
        else:
            for en in entries:
                if en.get("url"):
                    frozen.add(en["url"])

    for row in rows:
        day, repo, url = row.get("day"), row.get("repo"), row.get("url")
        if not day or not repo or not url or url in frozen:
            continue
        if url in live:
            en = live[url]
            grew = False
            for f in ("cost_usd", "turns", "minutes"):
                new = row.get(f)
                if new is not None and new > (en.get(f) or 0):
                    en[f] = new
                    grew = True
            refreshed += 1 if grew else 0
            continue
        target = None
        for e in engs:
            if e.get("client") != repo:
                continue
            if str(e.get("opened") or "") > day:
                continue
            end = e.get("delivered") or "9999-12-31"
            if day > str(end):
                continue
            target = e
            break
        if target is None:
            continue
        entry = {k: v for k, v in row.items() if k != "repo" and v is not None}
        target.setdefault("actuals", _zero_actuals())["entries"].append(entry)
        live[url] = entry
        added += 1
    return added, refreshed


def recompute_actuals(book: dict, rates: dict) -> None:
    rate = float(rates["human"]["broker_rate_usd_hr"])
    ci_rate = float(rates["platform"]["ci_usd_per_min"])
    for e in book["engagements"]:
        if e.get("status") in ("reconciled", "cancelled"):
            continue  # closed books are never restated (rate changes included)
        a = e.setdefault("actuals", _zero_actuals())
        entries = sorted(a.get("entries", []), key=lambda r: (str(r.get("day")), str(r.get("url"))))
        a["entries"] = entries
        a["ai_cost_usd"] = usd(sum(r.get("cost_usd") or 0 for r in entries))
        a["turns"] = sum(r.get("turns") or 0 for r in entries)
        a["ci_minutes"] = round(sum(r.get("minutes") or 0 for r in entries), 1)
        a["commits"] = sum(1 for r in entries if r.get("kind") == "commit")
        a["prs"] = sum(1 for r in entries if r.get("kind") == "pr")
        a["first"] = entries[0].get("day") if entries else None
        a["last"] = entries[-1].get("day") if entries else None
        a["human_cost_usd"] = usd(float(a.get("broker_hours") or 0) * rate)
        a["platform_cost_usd"] = usd(a["ci_minutes"] * ci_rate)
        a["total_usd"] = usd(a["ai_cost_usd"] + a["human_cost_usd"] + a["platform_cost_usd"])

        est_total = (e.get("estimate") or {}).get("total_usd") or 0
        if a["total_usd"] > 0 or e.get("status") == "delivered":
            diff = usd(a["total_usd"] - est_total)
            pct = round(100 * diff / est_total, 1) if est_total else None
            # no estimate to compare against -> no band, not a fake "on"
            band = None
            if pct is not None:
                band = "under" if pct < -10 else ("over" if pct > 10 else "on")
            e["variance"] = {"usd": diff, "pct": pct, "band": band}
            trad = (e.get("estimate") or {}).get("traditional", {}).get("cost_usd")
            if trad and a["total_usd"] > 0:
                e["variance"]["leverage_actual"] = round(trad / a["total_usd"], 1)
        else:
            e.pop("variance", None)


def recompute_rollups(book: dict, rates: dict) -> None:
    recompute_actuals(book, rates)
    engs = book["engagements"]
    counts = {s: 0 for s in STATUSES}
    for e in engs:
        counts[e.get("status", "estimated")] = counts.get(e.get("status", "estimated"), 0) + 1

    def est(e):
        return (e.get("estimate") or {}).get("total_usd") or 0

    def act(e):
        return (e.get("actuals") or {}).get("total_usd") or 0

    delivered = [e for e in engs if e.get("status") in ("delivered", "reconciled")]
    levs = [e["estimate"]["leverage"] for e in engs
            if (e.get("estimate") or {}).get("leverage")]
    book["summary"] = {
        "updated_at": book.get("summary", {}).get("updated_at"),
        "engagements": len(engs),
        "counts": counts,
        "pipeline_usd": usd(sum(est(e) for e in engs if e.get("status") in ("estimated", "approved"))),
        "in_flight_usd": usd(sum(est(e) for e in engs if e.get("status") == "in_progress")),
        "delivered_est_usd": usd(sum(est(e) for e in delivered)),
        "delivered_actual_usd": usd(sum(act(e) for e in delivered)),
        "actual_usd": usd(sum(act(e) for e in engs)),
        "avg_leverage_est": round(sum(levs) / len(levs), 1) if levs else None,
        "clients": len({e.get("client") for e in engs}),
    }

    per: dict[str, dict] = {}
    for e in engs:
        c = per.setdefault(e.get("client"), {
            "name": e.get("client"), "nwo": e.get("nwo"),
            "engagements": 0, "open": 0, "delivered": 0,
            "est_usd": 0.0, "actual_usd": 0.0,
        })
        c["engagements"] += 1
        if e.get("status") in ("estimated", "approved", "in_progress"):
            c["open"] += 1
        if e.get("status") in ("delivered", "reconciled"):
            c["delivered"] += 1
        c["est_usd"] = usd(c["est_usd"] + est(e))
        c["actual_usd"] = usd(c["actual_usd"] + act(e))
    book["clients"] = sorted(per.values(), key=lambda c: (-c["est_usd"], c["name"] or ""))


def apply_status(book: dict, spec: str) -> bool:
    try:
        eid, new = spec.split("=", 1)
    except ValueError:
        sys.stderr.write(f"--set-status wants ENG-NNNN=<status>, got '{spec}'\n")
        return False
    new = new.strip()
    if new not in STATUSES:
        sys.stderr.write(f"unknown status '{new}' (want one of {', '.join(STATUSES)})\n")
        return False
    for e in book["engagements"]:
        if e.get("id") == eid.strip():
            cur = e.get("status", "estimated")
            if new not in TRANSITIONS.get(cur, set()):
                sys.stderr.write(f"{eid}: illegal transition {cur} -> {new}\n")
                return False
            e["status"] = new
            if new == "delivered" and not e.get("delivered"):
                e["delivered"] = today_iso()
            if new in ("estimated", "approved", "in_progress"):
                e["delivered"] = None
            sys.stderr.write(f"  {eid}: {cur} -> {new}\n")
            return True
    sys.stderr.write(f"{eid}: not found\n")
    return False


def apply_broker(book: dict, spec: str) -> bool:
    try:
        eid, hours = spec.split("=", 1)
        hours_f = float(hours)
    except ValueError:
        sys.stderr.write(f"--broker wants ENG-NNNN=<hours>, got '{spec}'\n")
        return False
    for e in book["engagements"]:
        if e.get("id") == eid.strip():
            if e.get("status") in ("reconciled", "cancelled"):
                sys.stderr.write(
                    f"{eid}: books are closed ({e['status']}) — broker hours refused\n"
                )
                return False
            e.setdefault("actuals", _zero_actuals())["broker_hours"] = hours_f
            sys.stderr.write(f"  {eid}: broker_hours = {hours_f}\n")
            return True
    sys.stderr.write(f"{eid}: not found\n")
    return False


def run_ledger(args: argparse.Namespace) -> int:
    rates = load_rates(Path(args.rates))
    if rates is None:
        return 2
    out_path = Path(args.out)
    prior_raw = out_path.read_text() if out_path.exists() else None
    book = load_book(out_path)
    if not book["engagements"]:
        sys.stderr.write("ledger: no engagements yet — run `tools/dash estimate` first.\n")

    ok = True
    for spec in args.set_status or []:
        ok = apply_status(book, spec) and ok
    for spec in args.broker or []:
        ok = apply_broker(book, spec) and ok
    if not ok:
        return 1

    rows: list[dict] = []
    usage = load_yaml(Path(args.usage), "AI usage ledger")
    if isinstance(usage, dict):
        rows.extend(evidence_rows(usage))
    if not args.no_local:
        rows.extend(local_evidence())
    added, refreshed = attribute(book, rows)

    recompute_rollups(book, rates)
    changed = write_book(out_path, book, prior_raw)

    s = book["summary"]
    sys.stderr.write(
        f"ledger: +{added} evidence entries, {refreshed} refreshed "
        f"-> {out_path if changed else '(no change)'}\n"
        f"  {s['engagements']} engagements across {s['clients']} clients · "
        f"pipeline ${s['pipeline_usd']:,.2f} · in-flight ${s['in_flight_usd']:,.2f} · "
        f"actuals ${s['actual_usd']:,.2f}\n"
    )
    for e in book["engagements"]:
        v = e.get("variance")
        if v and e.get("status") in ("delivered", "reconciled"):
            sys.stderr.write(
                f"  {e['id']} {e.get('client', ''):<20} est ${est_total(e):>8,.2f} "
                f"actual ${e['actuals']['total_usd']:>8,.2f}  {v['band']}"
                f"{' x' + str(v['leverage_actual']) if v.get('leverage_actual') else ''}\n"
            )
    return 0


def est_total(e: dict) -> float:
    return (e.get("estimate") or {}).get("total_usd") or 0.0


# --------------------------------------------------------------------------- #
# CLI wiring
# --------------------------------------------------------------------------- #
def add_estimate_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", metavar="NAME",
                        help="limit to one client (registry `name`)")
    parser.add_argument("--issue", type=int, metavar="N",
                        help="estimate a single issue (requires --repo; falls back to `gh api` if not in the snapshot)")
    parser.add_argument("--limit", type=int, default=10, metavar="N",
                        help="sweep window: examine only the first N candidates in "
                             "deterministic order (default: 10) — already-estimated "
                             "items count toward the window, so raise N to reach "
                             "deeper into the backlog")
    parser.add_argument("--include-stale", action="store_true",
                        help="also sweep issues idle > 365d (skipped by default)")
    parser.add_argument("--re-estimate", action="store_true",
                        help="refresh existing estimated/approved entries (non-estimator-v1 methods are never touched)")
    parser.add_argument("--rates", default=str(RATES_DEFAULT), metavar="PATH",
                        help=f"rate card (default: {RATES_DEFAULT})")
    parser.add_argument("--triage", default=str(TRIAGE_DEFAULT), metavar="PATH",
                        help=f"fleet triage snapshot (default: {TRIAGE_DEFAULT})")
    parser.add_argument("--usage", default=str(USAGE_DEFAULT), metavar="PATH",
                        help=f"AI usage ledger for calibration (default: {USAGE_DEFAULT})")
    parser.add_argument("--out", default=str(OUT_DEFAULT), metavar="PATH",
                        help=f"engagement ledger (default: {OUT_DEFAULT})")
    parser.set_defaults(func=run_estimate)


def add_ledger_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--set-status", action="append", metavar="ENG-NNNN=STATUS",
                        help="transition an engagement (validated; repeatable)")
    parser.add_argument("--broker", action="append", metavar="ENG-NNNN=HOURS",
                        help="record validated broker hours (repeatable)")
    parser.add_argument("--no-local", action="store_true",
                        help="skip this machine's ai-activity ledger evidence")
    parser.add_argument("--rates", default=str(RATES_DEFAULT), metavar="PATH",
                        help=f"rate card (default: {RATES_DEFAULT})")
    parser.add_argument("--usage", default=str(USAGE_DEFAULT), metavar="PATH",
                        help=f"AI usage ledger evidence (default: {USAGE_DEFAULT})")
    parser.add_argument("--out", default=str(OUT_DEFAULT), metavar="PATH",
                        help=f"engagement ledger (default: {OUT_DEFAULT})")
    parser.set_defaults(func=run_ledger)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="engagements", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    add_estimate_arguments(sub.add_parser("estimate", help="draft estimates from work items"))
    add_ledger_arguments(sub.add_parser("ledger", help="accrue actuals + recompute rollups"))
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
