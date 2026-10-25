#!/usr/bin/env python3
"""
File: tools/backlog_fanout.py
Purpose: the BACKLOG FAN-OUT routine (HUB-025, PRD FR16/FR17).

Reads the hub's pending backlog, maps each item to the fleet repos it applies
to, and opens or updates ONE tracking PR per (item, repo) through the existing
fan-out engine (tools/fanout.sh --kit backlog). Never merges. Dry run by
default. Doc: docs/BACKLOG-FANOUT.md.

Pending backlog (three sources):
  issue-<n>      open issues in bamr87/bamr87
  req-<FRn>      PRD requirements (PRD.md § 5) no shipped feature serves
  feat-<ID>      features/features.yml entries whose status is not shipped

Mapping (applies_to), first match wins per source — see the doc:
  issues        label `repo:<name>` / `applies-to:<name>`, a body line
                `applies_to: a, b` (or `all`), else a title starting with a
                fan-out target name ("godotgo Release: …")
  features      `applies_to: [names] | all` on the feature entry
  requirements  `requirements:` in _data/backlog_fanout.yml

Every decision is emitted to the fleet activity log (tools/fleet_activity.py):
fanned out → finish/success, skipped → declined (reason), failed → retry per
attempt then finish/failure. In dry run, events go to the local queue only.

Usage:
  python3 tools/backlog_fanout.py                     # dry run (default)
  python3 tools/backlog_fanout.py --apply             # open/update PRs (needs FLEET_TOKEN)
  python3 tools/backlog_fanout.py --cadence weekly --force --report r.json --summary s.md
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

HUB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUB / "tools"))
import fleet_activity  # noqa: E402

HUB_REPO = "bamr87/bamr87"
BOT_ID = "backlog-fanout"
SHIPPED = {"shipped", "deprecated"}
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
REQ_RX = re.compile(r"^-\s+((?:N?FR)\d+)(?:\s*[–-]\s*((?:N?FR)?\d+))?\b[^:]*:\s*(.*)$")
FEAT_RX = re.compile(r"\b([A-Z][A-Z0-9]{1,9}-\d{3})\b")
APPLIES_RX = re.compile(r"^\s*applies[_-]to\s*:\s*(.+)$", re.I | re.M)


# ---------------------------------------------------------------- gh adapter
class Gh:
    """All GitHub I/O in one place so tests can stub it. Reads only, except
    through tools/fanout.sh in apply mode."""

    def run(self, *args: str) -> str:
        return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout

    def open_issues(self, repo: str) -> list[dict]:
        out = self.run("issue", "list", "--repo", repo, "--state", "open", "--limit", "500",
                       "--json", "number,title,labels,body,url")
        return json.loads(out or "[]")

    def open_pr(self, slug: str, branch: str) -> dict | None:
        try:
            out = self.run("pr", "list", "--repo", slug, "--head", branch, "--state", "open",
                           "--json", "number,url")
            prs = json.loads(out or "[]")
            return prs[0] if prs else None
        except Exception:
            return None

    def agents_md(self, slug: str) -> str | None:
        try:
            return self.run("api", f"repos/{slug}/contents/AGENTS.md",
                            "-H", "Accept: application/vnd.github.raw")
        except Exception:
            return None


# ------------------------------------------------------------------- loaders
def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) if path.exists() else {}


def load_targets(hub: Path) -> dict[str, dict]:
    """Fan-out targets: registry submodules owned by a fleet owner, not archived.
    Key = the name tools/fanout.sh --target takes (basename of submodule_path)."""
    reg = load_yaml(hub / "_data" / "projects.yml")
    owners = set(((load_yaml(hub / "_data" / "fleet.yml").get("hub") or {}).get("owners")) or ["bamr87"])
    projects = reg.get("projects", reg) if isinstance(reg, dict) else reg
    out: dict[str, dict] = {}
    for p in projects or []:
        if not isinstance(p, dict) or not p.get("submodule_path"):
            continue
        url = (p.get("repo_url") or "").rstrip("/").removesuffix(".git")
        m = re.search(r"github\.com[/:]([^/]+)/([^/]+)$", url)
        if not m:
            continue
        target = Path(p["submodule_path"]).name
        out[target] = {
            "target": target, "name": p.get("name") or target,
            "slug": f"{m.group(1)}/{m.group(2)}", "owned": m.group(1) in owners,
            "archived": p.get("status") == "archived",
        }
    return out


def parse_prd(text: str) -> dict[str, str]:
    """{FRn|NFRn: text} from the PRD requirement bullets; ranges FR7–FR15 expand."""
    reqs: dict[str, str] = {}
    for line in text.splitlines():
        m = REQ_RX.match(line.strip())
        if not m:
            continue
        first, last, body = m.group(1), m.group(2), m.group(3).strip()
        if last:
            prefix = re.match(r"[A-Z]+", first).group(0)
            lo, hi = int(first[len(prefix):]), int(re.sub(r"\D", "", last))
            for n in range(lo, hi + 1):
                reqs[f"{prefix}{n}"] = body
        else:
            reqs[first] = body
    return reqs


def feature_status(f: dict) -> str:
    if f.get("status"):
        return str(f["status"])
    return "shipped" if f.get("implemented") else "planned"


def as_list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [s.strip() for s in re.split(r"[,\s]+", v) if s.strip()]
    return [str(s) for s in v]


# ------------------------------------------------------------------ backlog
def collect(hub: Path, cfg: dict, gh: Gh) -> tuple[list[dict], dict]:
    feats = (load_yaml(hub / "features" / "features.yml").get("features")) or []
    prd_path = hub / "PRD.md"
    reqs = parse_prd(prd_path.read_text()) if prd_path.exists() else {}
    feat_ids = {f.get("id") for f in feats}
    served: dict[str, list[str]] = {}
    for f in feats:
        for r in as_list(f.get("prd")):
            served.setdefault(r, []).append(f["id"])
    shipped_for = {r: [fid for fid in ids
                       if feature_status(next(x for x in feats if x["id"] == fid)) in SHIPPED]
                   for r, ids in served.items()}
    src = cfg.get("sources") or {}
    items: list[dict] = []

    if src.get("issues", True):
        for i in gh.open_issues(HUB_REPO):
            body = i.get("body") or ""
            labels = [l["name"] if isinstance(l, dict) else str(l) for l in i.get("labels") or []]
            fids = sorted({x for x in FEAT_RX.findall(f"{i['title']} {body}") if x in feat_ids})
            items.append({
                "id": f"issue-{i['number']}", "kind": "issue", "title": i["title"],
                "ref": f"{HUB_REPO}#{i['number']}", "url": i.get("url", ""),
                "labels": labels, "body": body, "features": fids,
                "requirements": sorted({r for fid in fids for r in as_list(
                    next(f for f in feats if f["id"] == fid).get("prd")) if r != "TBD"}),
            })
    if src.get("requirements", True):
        for rid, text in reqs.items():
            if shipped_for.get(rid):
                continue
            items.append({
                "id": f"req-{rid}", "kind": "requirement", "title": f"{rid}: {text}",
                "ref": f"PRD.md {rid}", "url": f"https://github.com/{HUB_REPO}/blob/main/PRD.md",
                "labels": [], "body": text, "features": served.get(rid, []), "requirements": [rid],
            })
    if src.get("features", True):
        for f in feats:
            if feature_status(f) in SHIPPED:
                continue
            items.append({
                "id": f"feat-{f['id']}", "kind": "feature", "title": f"{f['id']}: {f.get('title', '')}",
                "ref": f"features/features.yml {f['id']}",
                "url": f"https://github.com/{HUB_REPO}/blob/main/features/features.yml",
                "labels": [], "body": f.get("description", ""), "features": [f["id"]],
                "requirements": [r for r in as_list(f.get("prd")) if r != "TBD"],
                "applies_to": as_list(f.get("applies_to")),
            })
    return items, reqs


def applies_to(item: dict, cfg: dict, targets: dict[str, dict]) -> tuple[list[str], str]:
    """(target names, how it was mapped). Empty list ⇒ unmapped."""
    names = set(targets)

    def expand(vals: list[str]) -> list[str]:
        if any(v.lower() == "all" for v in vals):
            return sorted(n for n, t in targets.items() if t["owned"] and not t["archived"])
        return sorted({v for v in vals if v in names})

    if item["kind"] == "issue":
        lab = [l.split(":", 1)[1] for l in item["labels"]
               if l.lower().startswith(("repo:", "applies-to:", "applies_to:"))]
        if lab:
            return expand(lab), "label"
        m = APPLIES_RX.search(item["body"])
        if m:
            return expand(as_list(m.group(1))), "body"
        first = (item["title"].split() or [""])[0].rstrip(":")
        if first in names:
            return [first], "title"
        return [], "unmapped"
    if item["kind"] == "feature":
        return (expand(item.get("applies_to", [])), "applies_to") if item.get("applies_to") else ([], "unmapped")
    vals = as_list((cfg.get("requirements") or {}).get(item["requirements"][0]))
    return (expand(vals), "config") if vals else ([], "unmapped")


def branch_for(item: dict) -> str:
    return "backlog/" + re.sub(r"[^a-z0-9-]+", "-", item["id"].lower()).strip("-")


def render_body(item: dict, reqs: dict[str, str], target: dict) -> str:
    feats = ", ".join(f"`{f}`" for f in item["features"]) or "none yet (TBD)"
    rows = "\n".join(f"| `{f}` | " + (", ".join(f"`{r}`" for r in item["requirements"]) or "TBD") + " |"
                     for f in (item["features"] or ["TBD"]))
    req_lines = "\n".join(f"- `{r}`: {reqs.get(r, 'TBD')}" for r in item["requirements"]) or "- TBD"
    return (
        f"Automated by bamr87 backlog-fanout (tools/backlog_fanout.py → tools/fanout.sh --kit backlog): "
        f"fans out one pending hub backlog item to `{target['slug']}` as a tracking PR. "
        f"Additive-only: seeds `.fleet/backlog/{item['id']}.md` describing the item; the work itself is "
        f"done on this branch by a human or agent before merge. Re-runs update this PR (stable branch "
        f"`{branch_for(item)}`); the routine never merges.\n\n"
        f"**Source:** [{item['ref']}]({item['url']}) — {item['title']}\n\n"
        f"**Features:** {feats}\n\n| Feature | PRD requirements |\n| --- | --- |\n{rows}\n\n"
        f"**Requirements**\n\n{req_lines}\n\n"
        f"See bamr87/bamr87 docs/BACKLOG-FANOUT.md (HUB-025, FR16/FR17). Activity-log events follow the schema proposed in bamr87/bamr87#409 (dependency, HUB-024)."
    )


def render_file(item: dict, reqs: dict[str, str]) -> str:
    req_lines = "\n".join(f"- {r}: {reqs.get(r, 'TBD')}" for r in item["requirements"]) or "- TBD"
    body = (item["body"] or "").strip() or "TBD"
    return (
        f"<!-- generated by bamr87/bamr87 tools/backlog_fanout.py — regenerated on every run -->\n"
        f"# {item['title']}\n\n- Source: [{item['ref']}]({item['url']})\n"
        f"- Features: {', '.join(item['features']) or 'TBD'}\n\n## Requirements\n\n{req_lines}\n\n"
        f"## Description\n\n{body}\n"
    )


# --------------------------------------------------------------------- run
def cadence_due(cfg: dict, cadence: str, now: datetime) -> bool:
    cad = cfg.get("cadence", "daily") if cadence in ("", "config") else cadence
    if cad == "daily":
        return True
    return DAYS[now.weekday()] == str(cfg.get("weekly_day", "monday")).lower()


def apply_one(item, target, body, content, attempts: int = 2, runner=None) -> tuple[bool, str, int]:
    """Run fanout.sh --kit backlog --apply for one (item, target). Returns
    (ok, last log line, attempts used)."""
    runner = runner or subprocess.run
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
        fh.write(content)
    env = dict(os.environ, FANOUT_BRANCH=branch_for(item), FANOUT_BASE_BRANCH=branch_for(item),
               FANOUT_BACKLOG_FILE=fh.name, FANOUT_BACKLOG_PATH=f".fleet/backlog/{item['id']}.md",
               FANOUT_PR_TITLE=f"chore(backlog): {item['title'][:90]}", FANOUT_BACKLOG_BODY=body,
               FANOUT_PR_UPDATE="1")
    last = ""
    for n in range(1, attempts + 1):
        r = runner([str(HUB / "tools" / "fanout.sh"), "--kit", "backlog", "--target", target["target"], "--apply"],
                   env=env, capture_output=True, text=True)
        out = (r.stdout or "") + (r.stderr or "")
        last = (out.strip().splitlines() or [""])[-1]
        if r.returncode == 0 and "clone failed" not in out:
            return True, last, n
    return False, last, attempts


def run(args, gh: Gh | None = None, now: datetime | None = None, runner=None) -> dict:
    gh = gh or Gh()
    now = now or datetime.now(timezone.utc)
    hub = Path(args.hub)
    cfg = load_yaml(hub / "_data" / "backlog_fanout.yml")
    dry = not args.apply
    act = fleet_activity.Activity(BOT_ID, queue=args.queue, dry_run=dry)
    hub_std = fleet_activity.standard_version((hub / "AGENTS.md").read_text() if (hub / "AGENTS.md").exists() else None)
    report = {"generated": now.isoformat(timespec="seconds"), "dry_run": dry, "cadence": cfg.get("cadence", "daily"),
              "items": 0, "planned": [], "succeeded": [], "failed": [], "skipped": [], "cadence_skip": False}
    if not args.force and not cadence_due(cfg, args.cadence, now):
        report["cadence_skip"] = True
        act.emit("declined", repo=HUB_REPO, task_ref="run", decision="cadence skip", outcome="skipped",
                 standard=hub_std, standard_source="AGENTS.md",
                 detail={"reason": "policy", "reason_text": f"cadence weekly, today {DAYS[now.weekday()]}"})
        report["activity"] = {"queue": str(act.queue), "emitted": act.emitted, "flush": act.flush(), "errors": act.errors}
        return report

    targets = load_targets(hub)
    items, reqs = collect(hub, cfg, gh)
    report["items"] = len(items)
    skip_labels = {s.lower() for s in cfg.get("skip_labels") or []}
    cap = int(args.max_prs if args.max_prs is not None else cfg.get("max_prs_per_run", 10))
    std_cache: dict[str, tuple[str, str]] = {}
    used = 0
    for item in items:
        def decline(repo, reason, text):
            report["skipped"].append({"item": item["id"], "repo": repo, "reason": text})
            act.emit("declined", repo=repo, task_ref=item["ref"], decision=f"skip {item['id']}", outcome="skipped",
                     standard=hub_std, standard_source="AGENTS.md",
                     detail={"reason": reason, "reason_text": text, "features": item["features"],
                             "requirements": item["requirements"]})
        hit = skip_labels.intersection(l.lower() for l in item["labels"])
        if hit:
            decline(HUB_REPO, "policy", f"skip label {sorted(hit)[0]}")
            continue
        names, how = applies_to(item, cfg, targets)
        if not names:
            decline(HUB_REPO, "insufficient_info", "unmapped: no applies_to target")
            continue
        for name in names:
            t = targets[name]
            if not t["owned"] or t["archived"]:
                decline(t["slug"], "out_of_scope", "external upstream" if not t["owned"] else "archived")
                continue
            if used >= cap:
                decline(t["slug"], "policy", f"per-run cap {cap} reached")
                continue
            used += 1
            if t["slug"] not in std_cache:
                txt = gh.agents_md(t["slug"]) if not args.no_stamp else None
                std_cache[t["slug"]] = (fleet_activity.standard_version(txt), f"{t['slug']}:AGENTS.md")
            std, std_src = std_cache[t["slug"]]
            branch = branch_for(item)
            existing = gh.open_pr(t["slug"], branch)
            action = f"update PR #{existing['number']}" if existing else "open PR"
            entry = {"item": item["id"], "repo": t["slug"], "branch": branch, "action": action, "mapped_by": how,
                     "features": item["features"], "requirements": item["requirements"], "standard": std}
            body = render_body(item, reqs, t)
            if dry:
                report["planned"].append(entry)
                act.emit("finish", repo=t["slug"], task_ref=item["ref"], decision=f"would {action} on {branch}",
                         outcome="pending", standard=std, standard_source=std_src, detail=entry)
                continue
            ok, last, n = apply_one(item, t, body, render_file(item, reqs), runner=runner)
            for a in range(1, n):
                act.emit("retry", repo=t["slug"], task_ref=item["ref"], decision=f"retry {action}", outcome="failure",
                         standard=std, standard_source=std_src,
                         detail={"attempt": a, "max_attempts": 2, "cause": last,
                                 "final_outcome": "success" if ok else "gave_up"})
            entry["log"] = last
            (report["succeeded"] if ok else report["failed"]).append(entry)
            act.emit("finish", repo=t["slug"], task_ref=item["ref"], decision=f"{action} on {branch}",
                     outcome="success" if ok else "failure", standard=std, standard_source=std_src, detail=entry)
    report["activity"] = {"queue": str(act.queue), "emitted": act.emitted, "flush": act.flush(), "errors": act.errors}
    return report


def summary_md(r: dict) -> str:
    mode = "DRY RUN — nothing pushed or opened" if r["dry_run"] else "APPLY"
    lines = [f"## Backlog fan-out — {mode}", ""]
    if r["cadence_skip"]:
        return "\n".join(lines + [f"Cadence `{r['cadence']}`: not due today — nothing read or fanned out.", ""])
    lines += [f"- Pending items read: **{r['items']}**",
              f"- Planned (dry run): **{len(r['planned'])}** · Succeeded: **{len(r['succeeded'])}** · "
              f"Failed: **{len(r['failed'])}** · Skipped: **{len(r['skipped'])}**",
              f"- Activity log: {r['activity']['emitted']} events → `{r['activity']['queue']}` "
              f"(flush: {r['activity']['flush']}, emit errors: {r['activity']['errors']})", ""]
    for title, key in (("Planned", "planned"), ("Succeeded", "succeeded"), ("Failed", "failed")):
        if r[key]:
            lines += [f"### {title}", "", "| Item | Repo | Action | Features | Requirements |", "| --- | --- | --- | --- | --- |"]
            lines += [f"| {e['item']} | {e['repo']} | {e['action']} | {', '.join(e['features']) or 'TBD'} | "
                      f"{', '.join(e['requirements']) or 'TBD'} |" for e in r[key]]
            lines.append("")
    if r["skipped"]:
        counts: dict[str, int] = {}
        for s in r["skipped"]:
            counts[s["reason"]] = counts.get(s["reason"], 0) + 1
        lines += ["### Skipped (by reason)", ""] + [f"- {k}: {v}" for k, v in sorted(counts.items())] + [""]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--hub", default=str(HUB))
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="plan only (the default)")
    g.add_argument("--apply", action="store_true", help="open/update PRs via tools/fanout.sh")
    ap.add_argument("--cadence", default="config", choices=["config", "daily", "weekly"])
    ap.add_argument("--force", action="store_true", help="ignore the cadence day check")
    ap.add_argument("--max-prs", type=int, default=None)
    ap.add_argument("--no-stamp", action="store_true", help="skip reading target AGENTS.md versions")
    ap.add_argument("--queue", default=None, help="activity-log JSONL queue (FLEET_ACTIVITY_QUEUE)")
    ap.add_argument("--report", default=None, help="write the JSON report here")
    ap.add_argument("--summary", default=None, help="write the markdown summary here")
    args = ap.parse_args(argv)
    r = run(args)
    md = summary_md(r)
    print(md)
    if args.report:
        Path(args.report).write_text(json.dumps(r, indent=2) + "\n")
    if args.summary:
        Path(args.summary).write_text(md + "\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as fh:
            fh.write(md + "\n")
    return 1 if r["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
