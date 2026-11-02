#!/usr/bin/env python3
"""
tools/deep_dive.py — the daily repo deep-dive tracker (HUB-029; PRD FR24–FR25).

A daily routine deep-dives ONE bamr87 repo per day (review, analysis, docs,
issues, feature requests, UI/UX — everything it files is labelled `deep-dive`),
so the whole fleet is covered once per cycle. Each repo it processes also
gets a Quest Log showcase (an article, two LinkedIn drafts and a presentation
PR; docs/SHOWCASE.md), recorded on the same row. This tool owns the tracker:

  _data/deep-dive.yml   the hand-and-routine-edited ledger (docs/DEEP-DIVE.md)
  _data/deep_dive.json  its generated projection for the Harness Console
                        (/deep-dive), with the cycle summary precomputed

Commands (all offline except `init --from-github` and `refresh`):

  today   [--date D] [--json]          the repo scheduled for D (default today);
                                       --json adds the showcase slug and the
                                       done repos still missing a showcase
  record  REPO [--status S] [--issue URL]... [--pr URL]... [--findings T]
          [--score N] [--next-focus T] [--date D]
          [--article URL] [--linkedin-personal URL] [--linkedin-company URL]
          [--presentation-pr URL]... [--showcase-note T]
                                       record a run (status defaults to done)
                                       and/or its showcase; showcase flags
                                       alone leave the run's status alone
  refresh [--dry-run]                  count open `deep-dive` issues/PRs per
                                       repo from the GitHub search API (GH_TOKEN)
  json    [--write | --check]          emit / write / check the frontend JSON
  init    [--from-github] [--start D] [--force]
                                       (re)build the rotation from the repo list
  rollover [--force]                   start the next cycle (statuses reset)

Every write rewrites both files. Stdlib + PyYAML; never prints a token.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "_data" / "deep-dive.yml"
JSON_OUT = ROOT / "_data" / "deep_dive.json"
SCHEMA = "deep-dive/v1"
STATUSES = ("pending", "in_progress", "done", "skipped")
API = "https://api.github.com"
# The optional per-repo `showcase` mapping (docs/SHOWCASE.md), in the order it
# is written. A row without one has not been showcased; ledgers from before
# the field existed load unchanged.
SHOWCASE_KEYS = ("cycle", "date", "article", "linkedin_personal", "linkedin_company",
                 "presentation_prs", "note")
SHOWCASE_LINKS = ("article", "linkedin_personal", "linkedin_company")


# --------------------------------------------------------------------------- #
# Load / save
# --------------------------------------------------------------------------- #
def _date(v) -> dt.date | None:
    if v in (None, ""):
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return dt.date.fromisoformat(str(v)[:10])


def load(path: Path = DATA) -> dict:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    validate(doc)
    return doc


def validate(doc: dict) -> None:
    if doc.get("schema") != SCHEMA:
        raise ValueError(f"deep-dive: schema must be {SCHEMA!r}")
    _date(doc.get("cycle_start"))
    repos = doc.get("repos") or []
    names = [r.get("repo") for r in repos]
    if len(set(names)) != len(names):
        raise ValueError("deep-dive: a repo appears twice in the rotation")
    if int(doc.get("cycle_days", 0)) < len(repos):
        raise ValueError("deep-dive: cycle_days is shorter than the rotation")
    for i, r in enumerate(repos, 1):
        if r.get("day") != i:
            raise ValueError(f"deep-dive: {r.get('repo')} has day {r.get('day')}, expected {i}")
        if r.get("status") not in STATUSES:
            raise ValueError(f"deep-dive: {r.get('repo')} status {r.get('status')!r} not in {STATUSES}")
        s = r.get("score")
        if s is not None and not (0 <= float(s) <= 100):
            raise ValueError(f"deep-dive: {r.get('repo')} score must be 0-100")
        if r.get("showcase") is not None:
            validate_showcase(r["repo"], r["showcase"])


def validate_showcase(repo: str, sc) -> None:
    """A row's optional `showcase` mapping: known keys only, so a typo fails loudly."""
    if not isinstance(sc, dict):
        raise ValueError(f"deep-dive: {repo} showcase must be a mapping")
    unknown = sorted(set(sc) - set(SHOWCASE_KEYS))
    if unknown:
        raise ValueError(f"deep-dive: {repo} showcase has unknown keys {unknown}")
    c = sc.get("cycle")
    if not isinstance(c, int) or isinstance(c, bool) or c < 1:
        raise ValueError(f"deep-dive: {repo} showcase cycle must be a positive int")
    if _date(sc.get("date")) is None:
        raise ValueError(f"deep-dive: {repo} showcase needs a date")
    for key in SHOWCASE_LINKS:
        if sc.get(key) is not None and not isinstance(sc[key], str):
            raise ValueError(f"deep-dive: {repo} showcase {key} must be a URL string")
    prs = sc.get("presentation_prs", [])
    if not isinstance(prs, list) or not all(isinstance(u, str) for u in prs):
        raise ValueError(f"deep-dive: {repo} showcase presentation_prs must be a list of URLs")
    if not isinstance(sc.get("note", ""), str):
        raise ValueError(f"deep-dive: {repo} showcase note must be text")


def _plain(v):
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_plain(x) for x in v]
    return v


HEADER = """\
# Daily repo deep-dive tracker — one repo per day, every repo once per cycle.
# Schema and workflow: docs/DEEP-DIVE.md (HUB-029, PRD FR24-FR25).
# Edited by tools/deep_dive.py (record / refresh / rollover); the frontend
# reads the generated projection _data/deep_dive.json. Never holds a secret.
"""


def save(doc: dict, path: Path = DATA, json_path: Path | None = JSON_OUT) -> None:
    validate(doc)
    path.write_text(HEADER + yaml.safe_dump(_plain(doc), sort_keys=False, allow_unicode=True, width=1000),
                    encoding="utf-8")
    if json_path is not None:
        json_path.write_text(render_json(doc) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# Schedule
# --------------------------------------------------------------------------- #
def entry(day: int, repo: str, start: dt.date, cycle: int) -> dict:
    return {
        "day": day, "repo": repo, "scheduled": (start + dt.timedelta(days=day - 1)).isoformat(),
        "status": "pending", "last_processed": None, "cycle": cycle,
        "issues": [], "prs": [], "open_issues": 0, "open_prs": 0,
        "findings": "", "score": None, "next_focus": "",
    }


def build(repos: list[str], start: dt.date, cycle: int = 1, cycle_days: int = 42, owner: str = "bamr87") -> dict:
    return {
        "schema": SCHEMA, "owner": owner, "label": "deep-dive", "cycle": cycle,
        "cycle_start": start.isoformat(), "cycle_days": max(cycle_days, len(repos)),
        "refreshed_at": None,
        "repos": [entry(i, r, start, cycle) for i, r in enumerate(repos, 1)],
    }


def day_index(doc: dict, on: dt.date) -> int:
    """1-based day of the cycle for `on` (0 before the cycle starts, >cycle_days after it)."""
    delta = (on - _date(doc["cycle_start"])).days
    return delta + 1 if delta >= 0 else 0


def today(doc: dict, on: dt.date) -> dict:
    """What the routine should work on `on`."""
    repos = doc["repos"]
    day = day_index(doc, on)
    days = int(doc["cycle_days"])
    base = {"date": on.isoformat(), "cycle": doc["cycle"], "day": day, "cycle_days": days}
    if day == 0:
        return {**base, "kind": "not_started", "repo": repos[0]["repo"] if repos else None}
    if day > days:
        return {**base, "kind": "cycle_over", "repo": None}
    if day <= len(repos):
        return {**base, "kind": "scheduled", "repo": repos[day - 1]["repo"]}
    # Catch-up slot: the earliest repo whose day has passed without being done.
    late = [r for r in repos if r["status"] in ("pending", "skipped", "in_progress") and r["day"] < day]
    return {**base, "kind": "catch_up", "repo": late[0]["repo"] if late else None}


def record(doc: dict, repo: str, on: dt.date, status: str | None = "done", issues=(), prs=(),
           findings: str | None = None, score: float | None = None, next_focus: str | None = None,
           *, article: str | None = None, linkedin_personal: str | None = None,
           linkedin_company: str | None = None, presentation_prs=(), showcase_note: str | None = None) -> dict:
    """Record a run and/or its showcase. `status=None` leaves the run (status,
    cycle, last_processed) as it is, for recording a showcase on its own."""
    if status is not None and status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    row = next((r for r in doc["repos"] if r["repo"] == repo), None)
    if row is None:
        raise KeyError(f"{repo} is not in the rotation")
    if status is not None:
        row["status"] = status
        row["cycle"] = doc["cycle"]
        if status in ("done", "in_progress"):
            row["last_processed"] = on.isoformat()
    if any(v is not None for v in (article, linkedin_personal, linkedin_company, showcase_note)) or presentation_prs:
        record_showcase(row, int(doc["cycle"]), on, article=article, linkedin_personal=linkedin_personal,
                        linkedin_company=linkedin_company, presentation_prs=presentation_prs,
                        note=showcase_note)
    for key, urls in (("issues", issues), ("prs", prs)):
        for u in urls:
            if u not in row[key]:
                row[key].append(u)
    if findings is not None:
        row["findings"] = findings
    if score is not None:
        row["score"] = round(float(score), 1)
    if next_focus is not None:
        row["next_focus"] = next_focus
    return row


def record_showcase(row: dict, cycle: int, on: dt.date, *, article=None, linkedin_personal=None,
                    linkedin_company=None, presentation_prs=(), note=None) -> dict:
    """Set the row's showcase. A showcase from an earlier cycle is replaced, not
    merged; within a cycle a link given again replaces the old one (a draft PR
    becomes the post's URL) and presentation PRs accumulate, deduplicated."""
    old = row.get("showcase")
    fresh = {"cycle": cycle, "date": on.isoformat(), "article": None, "linkedin_personal": None,
             "linkedin_company": None, "presentation_prs": [], "note": ""}
    # A hand-written mapping may leave keys out; fill them so it saves valid.
    sc = {**fresh, **old} if isinstance(old, dict) and old.get("cycle") == cycle else fresh
    sc["date"] = on.isoformat()
    for key, value in (("article", article), ("linkedin_personal", linkedin_personal),
                       ("linkedin_company", linkedin_company)):
        if value is not None:
            sc[key] = value
    prs = list(sc.get("presentation_prs") or [])
    for u in presentation_prs:
        if u not in prs:
            prs.append(u)
    sc["presentation_prs"] = prs
    if note is not None:
        sc["note"] = note
    row["showcase"] = {k: sc.get(k) for k in SHOWCASE_KEYS}
    return row["showcase"]


def showcase_slug(repo: str) -> str:
    """The Quest Log slug: `quest-log-` + the repo name lowercased, dots as hyphens
    (`bamr87.github.io` → `quest-log-bamr87-github-io`, `.github` → `quest-log-github`)."""
    name = "-".join(p for p in repo.lower().replace(".", "-").split("-") if p)
    return f"quest-log-{name}"


def showcased(row: dict, cycle: int) -> bool:
    """Showcased this cycle: a showcase recorded in `cycle` that names its article."""
    sc = row.get("showcase")
    return isinstance(sc, dict) and sc.get("cycle") == cycle and bool(sc.get("article"))


def showcase_missed(doc: dict, on: dt.date) -> list[str]:
    """Repos whose deep dive is done this cycle, whose day is before `on`'s, and
    that have no showcase yet — what a catch-up showcase takes, earliest first."""
    day, cycle = day_index(doc, on), int(doc["cycle"])
    return [r["repo"] for r in doc["repos"]
            if r["status"] == "done" and r.get("cycle") == cycle and r["day"] < day
            and not showcased(r, cycle)]


def rollover(doc: dict, force: bool = False) -> dict:
    left = [r["repo"] for r in doc["repos"] if r["status"] in ("pending", "in_progress")]
    if left and not force:
        raise ValueError(f"cycle {doc['cycle']} still has {len(left)} unfinished repos (use --force)")
    start = _date(doc["cycle_start"]) + dt.timedelta(days=int(doc["cycle_days"]))
    doc["cycle"] = int(doc["cycle"]) + 1
    doc["cycle_start"] = start.isoformat()
    for r in doc["repos"]:
        r["scheduled"] = (start + dt.timedelta(days=r["day"] - 1)).isoformat()
        r["status"] = "pending"
        # last_processed, links, findings, score, next_focus and showcase carry
        # over: the next pass starts from them. A showcase stamped with the old
        # cycle no longer counts as showcased, and the next one replaces it.
    return doc


# --------------------------------------------------------------------------- #
# Frontend projection
# --------------------------------------------------------------------------- #
def summary(doc: dict, on: dt.date) -> dict:
    repos = doc["repos"]
    counts = {s: sum(1 for r in repos if r["status"] == s) for s in STATUSES}
    done = sorted((r for r in repos if r.get("last_processed") and r["status"] == "done"),
                  key=lambda r: (str(r["last_processed"]), r["day"]))
    t = today(doc, on)
    nxt = today(doc, on + dt.timedelta(days=1))
    scores = [float(r["score"]) for r in repos if r.get("score") is not None]
    start = _date(doc["cycle_start"])
    out = {
        "as_of": on.isoformat(), "cycle": doc["cycle"], "cycle_start": start.isoformat(),
        "cycle_end": (start + dt.timedelta(days=int(doc["cycle_days"]) - 1)).isoformat(),
        "cycle_days": int(doc["cycle_days"]), "total": len(repos), "day": t["day"],
        "processed": counts["done"], "counts": counts,
        "progress": round(counts["done"] / len(repos), 4) if repos else 0.0,
        "today": t, "next": nxt, "last": done[-1]["repo"] if done else None,
        "last_date": str(done[-1]["last_processed"]) if done else None,
        "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
        "open_issues": sum(int(r.get("open_issues") or 0) for r in repos),
        "open_prs": sum(int(r.get("open_prs") or 0) for r in repos),
    }
    # Only once a showcase exists, so a ledger from before the field projects
    # byte-for-byte as it did and `json --check` holds without a regeneration
    # (the projection is written by the deep-dive loop's own PRs; amendment 0004).
    if any(r.get("showcase") is not None for r in repos):
        out["showcased"] = sum(1 for r in repos if showcased(r, int(doc["cycle"])))
    return out


def render_json(doc: dict, on: dt.date | None = None) -> str:
    # The projection is pinned to refreshed_at (or the cycle start) so it is
    # deterministic and --check never fails just because the calendar moved;
    # the page recomputes "today" from the viewer's clock.
    if on is None:
        on = _date(doc.get("refreshed_at")) or _date(doc["cycle_start"])
    out = {"schema": SCHEMA, "owner": doc.get("owner"), "label": doc.get("label"),
           "refreshed_at": _plain(doc.get("refreshed_at")), "summary": summary(doc, on),
           "repos": _plain(doc["repos"])}
    return json.dumps(out, indent=2, sort_keys=False)


# --------------------------------------------------------------------------- #
# GitHub
# --------------------------------------------------------------------------- #
def _get(url: str, token: str | None):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "X-GitHub-Api-Version": "2022-11-28"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as res:  # noqa: S310 (fixed https host)
        return json.load(res)


def search_open(owner: str, label: str, kind: str, token: str | None, get=_get) -> list[dict]:
    """Every open item of `kind` (issue|pr) labelled `label` across the owner's repos."""
    q = urllib.parse.quote(f'user:{owner} label:"{label}" is:open is:{kind}')
    items, page = [], 1
    while True:
        doc = get(f"{API}/search/issues?q={q}&per_page=100&page={page}", token)
        batch = doc.get("items") or []
        items += batch
        if len(batch) < 100 or len(items) >= int(doc.get("total_count") or 0) or page >= 10:
            return items
        page += 1


def refresh(doc: dict, token: str | None, now: dt.datetime, get=_get) -> dict[str, tuple[int, int]]:
    owner, label = doc.get("owner") or "bamr87", doc.get("label") or "deep-dive"
    counts: dict[str, list[int]] = {r["repo"]: [0, 0] for r in doc["repos"]}
    links: dict[str, dict[str, list[str]]] = {r["repo"]: {"issues": [], "prs": []} for r in doc["repos"]}
    for col, kind, key in ((0, "issue", "issues"), (1, "pr", "prs")):
        for it in search_open(owner, label, kind, token, get):
            repo = str(it.get("repository_url", "")).rsplit("/", 1)[-1]
            if repo in counts:
                counts[repo][col] += 1
                links[repo][key].append(it.get("html_url"))
    for r in doc["repos"]:
        r["open_issues"], r["open_prs"] = counts[r["repo"]]
        for key in ("issues", "prs"):
            for u in links[r["repo"]][key]:
                if u and u not in r[key]:
                    r[key].append(u)
    doc["refreshed_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    return {k: tuple(v) for k, v in counts.items()}


def github_repos(owner: str, token: str | None, get=_get) -> list[str]:
    """Non-archived repos owned by `owner` (forks included), oldest first (a stable rotation order)."""
    out, page = [], 1
    while True:
        batch = get(f"{API}/users/{owner}/repos?type=owner&sort=created&direction=asc&per_page=100&page={page}", token)
        out += [r["name"] for r in batch if not r.get("archived")]
        if len(batch) < 100:
            return out
        page += 1


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _today_local() -> dt.date:
    return dt.date.today()


def main(argv: list[str] | None = None, data: Path = DATA, json_path: Path = JSON_OUT) -> int:
    ap = argparse.ArgumentParser(prog="deep_dive.py", description=__doc__.split("\n\n")[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("today"); p.add_argument("--date"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("record"); p.add_argument("repo"); p.add_argument("--status", choices=STATUSES)
    p.add_argument("--issue", action="append", default=[]); p.add_argument("--pr", action="append", default=[])
    p.add_argument("--findings"); p.add_argument("--score", type=float); p.add_argument("--next-focus"); p.add_argument("--date")
    # The Quest Log showcase (docs/SHOWCASE.md).
    p.add_argument("--article"); p.add_argument("--linkedin-personal"); p.add_argument("--linkedin-company")
    p.add_argument("--presentation-pr", action="append", default=[]); p.add_argument("--showcase-note")
    p = sub.add_parser("refresh"); p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("json"); g = p.add_mutually_exclusive_group(); g.add_argument("--write", action="store_true"); g.add_argument("--check", action="store_true")
    p = sub.add_parser("init"); p.add_argument("--from-github", action="store_true"); p.add_argument("--start", default="2026-10-30")
    p.add_argument("--cycle-days", type=int, default=42); p.add_argument("--repo", action="append", default=[]); p.add_argument("--force", action="store_true")
    p = sub.add_parser("rollover"); p.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")

    if a.cmd == "init":
        if data.exists() and not a.force:
            print(f"deep-dive: {data.name} exists (use --force to rebuild)", file=sys.stderr)
            return 1
        repos = github_repos("bamr87", token) if a.from_github else a.repo
        if not repos:
            print("deep-dive: no repos (pass --from-github or --repo)", file=sys.stderr)
            return 2
        save(build(repos, _date(a.start), cycle_days=a.cycle_days), data, json_path)
        print(f"deep-dive: {len(repos)} repos from {a.start}")
        return 0

    doc = load(data)
    if a.cmd == "today":
        on = _date(a.date) or _today_local()
        t = today(doc, on)
        if a.json:
            # The showcase keys ride on the CLI only: today() itself is part of
            # the projection's summary, which must not change shape.
            print(json.dumps({**t, "showcase_slug": showcase_slug(t["repo"]) if t["repo"] else None,
                              "showcase_missed": showcase_missed(doc, on)}))
        else:
            print(f"{t['date']}  cycle {t['cycle']} day {t['day']}/{t['cycle_days']}  {t['kind']}: {t['repo'] or '—'}")
        return 0
    if a.cmd == "record":
        showcase_given = (any(v is not None for v in (a.article, a.linkedin_personal, a.linkedin_company,
                                                      a.showcase_note)) or bool(a.presentation_pr))
        run_given = bool(a.issue or a.pr) or any(v is not None for v in (a.findings, a.score, a.next_focus))
        # Showcase flags alone record the showcase and leave the run alone;
        # anything else is a run, which defaults to done as it always has.
        status = a.status or (None if showcase_given and not run_given else "done")
        try:
            row = record(doc, a.repo, _date(a.date) or _today_local(), status, a.issue, a.pr,
                         a.findings, a.score, a.next_focus, article=a.article,
                         linkedin_personal=a.linkedin_personal, linkedin_company=a.linkedin_company,
                         presentation_prs=a.presentation_pr, showcase_note=a.showcase_note)
        except (KeyError, ValueError) as e:
            print(f"deep-dive: {e}", file=sys.stderr)
            return 2
        save(doc, data, json_path)
        print(f"deep-dive: {row['repo']} → {row['status']}"
              + (f", showcase recorded (cycle {row['showcase']['cycle']})" if showcase_given else ""))
        return 0
    if a.cmd == "refresh":
        counts = refresh(doc, token, dt.datetime.now(dt.timezone.utc))
        for repo, (i, pr) in counts.items():
            if i or pr:
                print(f"  {repo}: {i} issues, {pr} PRs")
        if a.dry_run:
            print("deep-dive: dry run — nothing written")
            return 0
        save(doc, data, json_path)
        print(f"deep-dive: refreshed {len(counts)} repos")
        return 0
    if a.cmd == "json":
        text = render_json(doc) + "\n"
        if a.check:
            current = json_path.read_text(encoding="utf-8") if json_path.exists() else ""
            if current != text:
                print(f"deep-dive: {json_path.name} is stale — run tools/deep_dive.py json --write", file=sys.stderr)
                return 1
            return 0
        if a.write:
            json_path.write_text(text, encoding="utf-8")
            return 0
        sys.stdout.write(text)
        return 0
    if a.cmd == "rollover":
        try:
            rollover(doc, a.force)
        except ValueError as e:
            print(f"deep-dive: {e}", file=sys.stderr)
            return 2
        save(doc, data, json_path)
        print(f"deep-dive: cycle {doc['cycle']} starts {doc['cycle_start']}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
