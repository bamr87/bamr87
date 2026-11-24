#!/usr/bin/env python3
"""The fleet's branch model as code: classify a branch name, and plan, apply or audit the
default branch's protection as ONE named ruleset per repo.

    python3 tools/branch_policy.py classify NAME...             work | session | automation | default | unknown
    python3 tools/branch_policy.py protect REPO [--apply] ...    plan the fleet ruleset; --apply writes it
    python3 tools/branch_policy.py check REPO...                 audit the live protection, read-only

The policy is `_data/fleet.yml` `branches:` (docs/BRANCHING.md, ADR 0015). `tools/protect-branch.sh`
and `tools/dash protect` call `protect`, and `check` with `--check`.

Why a ruleset and not classic branch protection: a ruleset's pull-request rule can name the merge
methods it allows, so constitution § 12.2 (a merge commit, never squash or rebase) is enforced by
GitHub itself; a named ruleset is created or updated in place and never clobbers protection a
person set by hand, where the classic API's PUT replaced the whole thing; and the rules that apply
to a branch from every source can be read back in one call (`rules/branches/{branch}`), so the
audit sees what GitHub enforces rather than what one API reports.

Every GitHub call is `gh api`. Without `--apply` only GETs are made. Only the maintainer applies a
ruleset (constitution § 4: an agent never changes branch protection); an agent may plan and audit.
Exit codes: 0 done (or nothing to do), 1 refused or an error finding, 2 usage or a read failure.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import yaml

ROOT = Path(__file__).resolve().parent.parent
FLEET = ROOT / "_data" / "fleet.yml"
REGISTRY = ROOT / "_data" / "projects.yml"
ADMIN_ROLE_ID = 5  # GitHub's built-in repository admin role, as a ruleset bypass actor
KINDS = ("default", "work", "session", "automation", "unknown")
METHODS = ("merge", "squash", "rebase")


class PolicyError(ValueError):
    """The `branches:` block is missing or contradicts the constitution."""


class GhError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Policy:
    default: str
    merge_method: str
    work: tuple[str, ...]
    sessions: tuple[str, ...]
    automation: tuple[str, ...]
    ruleset: str
    approvals: int
    strict: bool
    admin_bypass: bool
    block_force_push: bool
    block_deletion: bool


def _prefixes(raw, where: str) -> tuple[str, ...]:
    out = []
    for item in raw or []:
        p = item.get("prefix") if isinstance(item, dict) else item
        if not isinstance(p, str) or not p or p.strip() != p:
            raise PolicyError(f"branches.{where}: {item!r} is not a prefix")
        out.append(p)
    return tuple(out)


def policy_from(doc: dict) -> Policy:
    b = (doc or {}).get("branches")
    if not isinstance(b, dict):
        raise PolicyError("_data/fleet.yml has no `branches:` block")
    prot = b.get("protection") or {}
    method = b.get("merge_method")
    if method not in METHODS:
        raise PolicyError(f"branches.merge_method must be one of {METHODS}, not {method!r}")
    if prot.get("linear_history"):
        raise PolicyError("branches.protection.linear_history must be false: it forbids the merge commit § 12.2 requires")
    approvals = prot.get("approvals", 0)
    if not isinstance(approvals, int) or isinstance(approvals, bool) or not 0 <= approvals <= 10:
        raise PolicyError("branches.protection.approvals must be an integer from 0 to 10")
    if not prot.get("ruleset"):
        raise PolicyError("branches.protection.ruleset names the one ruleset this tool owns")
    p = Policy(default=str(b.get("default") or "main"), merge_method=method,
               work=_prefixes(b.get("work"), "work"), sessions=_prefixes(b.get("sessions"), "sessions"),
               automation=_prefixes(b.get("automation"), "automation"), ruleset=str(prot["ruleset"]),
               approvals=approvals, strict=bool(prot.get("strict", False)),
               admin_bypass=bool(prot.get("admin_bypass", True)),
               block_force_push=bool(prot.get("block_force_push", True)),
               block_deletion=bool(prot.get("block_deletion", True)))
    seen: dict[str, str] = {}
    for kind, prefixes in (("work", p.work), ("sessions", p.sessions), ("automation", p.automation)):
        for pre in prefixes:
            if pre in seen:
                raise PolicyError(f"branch prefix {pre!r} is declared twice ({seen[pre]} and {kind})")
            seen[pre] = kind
    return p


def load_policy(path: Path = FLEET) -> Policy:
    return policy_from(yaml.safe_load(path.read_text(encoding="utf-8")))


# --------------------------------------------------------------------------- #
# Branch names
# --------------------------------------------------------------------------- #
def classify(name: str, policy: Policy) -> tuple[str, str]:
    """(kind, matched prefix). The longest declared prefix wins, so `chore/jev-ratify` is
    automation although `chore/` is a work prefix. A bare prefix (`fix/`) names nothing."""
    name = name.removeprefix("refs/heads/")
    if name == policy.default:
        return "default", ""
    best = ("unknown", "")
    for kind, prefixes in (("work", policy.work), ("session", policy.sessions), ("automation", policy.automation)):
        for pre in prefixes:
            if name.startswith(pre) and len(name) > len(pre) and len(pre) > len(best[1]):
                best = (kind, pre)
    return best


# --------------------------------------------------------------------------- #
# The ruleset the policy asks for
# --------------------------------------------------------------------------- #
def desired_ruleset(policy: Policy, *, checks: list[str], approvals: int, strict: bool, admin_bypass: bool) -> dict:
    rules: list[dict] = []
    if policy.block_deletion:
        rules.append({"type": "deletion"})
    if policy.block_force_push:
        rules.append({"type": "non_fast_forward"})
    rules.append({"type": "pull_request", "parameters": {
        "allowed_merge_methods": [policy.merge_method],
        "dismiss_stale_reviews_on_push": False,
        "require_code_owner_review": False,
        "require_last_push_approval": False,
        "required_approving_review_count": approvals,
        "required_review_thread_resolution": False,
    }})
    if checks:
        rules.append({"type": "required_status_checks", "parameters": {
            "do_not_enforce_on_create": False,
            "strict_required_status_checks_policy": strict,
            "required_status_checks": [{"context": c} for c in checks],
        }})
    bypass = [{"actor_id": ADMIN_ROLE_ID, "actor_type": "RepositoryRole", "bypass_mode": "always"}] if admin_bypass else []
    return {"name": policy.ruleset, "target": "branch", "enforcement": "active",
            "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
            "bypass_actors": bypass, "rules": rules}


def _norm_rule(rule: dict) -> tuple[str, str]:
    """A rule reduced to what the policy controls, so a live rule with extra defaults compares equal."""
    t = rule.get("type", "")
    p = rule.get("parameters") or {}
    if t == "pull_request":
        keys = ("dismiss_stale_reviews_on_push", "require_code_owner_review", "require_last_push_approval",
                "required_approving_review_count", "required_review_thread_resolution")
        keep = {k: p.get(k) for k in keys}
        keep["allowed_merge_methods"] = sorted(p.get("allowed_merge_methods") or METHODS)
        return t, json.dumps(keep, sort_keys=True)
    if t == "required_status_checks":
        keep = {"strict": bool(p.get("strict_required_status_checks_policy")),
                "checks": sorted(c.get("context", "") for c in p.get("required_status_checks") or [])}
        return t, json.dumps(keep, sort_keys=True)
    return t, json.dumps(p, sort_keys=True)


def diff_ruleset(live: dict | None, want: dict) -> list[str]:
    """What applying `want` changes, one line each; empty when the live ruleset already matches."""
    if not live:
        return [f"create ruleset {want['name']!r}: " + ", ".join(r["type"] for r in want["rules"])]
    out = []
    for key in ("enforcement", "target"):
        if live.get(key) != want[key]:
            out.append(f"{key}: {live.get(key)} -> {want[key]}")
    if (live.get("conditions") or {}).get("ref_name", {}).get("include") != want["conditions"]["ref_name"]["include"]:
        out.append(f"targets: {(live.get('conditions') or {}).get('ref_name')} -> the default branch")

    def actors(rs):
        return sorted((a.get("actor_type"), a.get("actor_id"), a.get("bypass_mode", "always")) for a in rs or [])
    if actors(live.get("bypass_actors")) != actors(want["bypass_actors"]):
        out.append(f"bypass: {actors(live.get('bypass_actors')) or 'none'} -> {actors(want['bypass_actors']) or 'none'}")
    have = dict(_norm_rule(r) for r in live.get("rules") or [])
    need = dict(_norm_rule(r) for r in want["rules"])
    for t in need:
        if t not in have:
            out.append(f"add rule {t}")
        elif have[t] != need[t]:
            out.append(f"change rule {t}: {have[t]} -> {need[t]}")
    for t in have:
        if t not in need:
            out.append(f"remove rule {t}")
    return out


# --------------------------------------------------------------------------- #
# GitHub
# --------------------------------------------------------------------------- #
Runner = Callable[[list[str], "str | None"], subprocess.CompletedProcess]


def run(argv: list[str], stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=60, check=False)


class Gh:
    def __init__(self, runner: Runner = run):
        self.runner = runner
        self.writes: list[str] = []

    def call(self, path: str, method: str = "GET", body: dict | None = None):
        argv = ["gh", "api", "-H", "Accept: application/vnd.github+json", "-X", method, path]
        if body is not None:
            argv += ["--input", "-"]
        if method != "GET":
            self.writes.append(f"{method} {path}")
        r = self.runner(argv, json.dumps(body) if body is not None else None)
        if r.returncode != 0:
            m = re.search(r"HTTP (\d{3})", r.stderr or "")
            raise GhError(int(m.group(1)) if m else 0, (r.stderr or "gh api failed").strip()[:300])
        return json.loads(r.stdout) if (r.stdout or "").strip() else None


def resolve_repo(arg: str, owner: str | None, registry: Path = REGISTRY) -> str:
    """`owner/name`, or a registry name or `projects/<dir>` resolved through its repo_url, else --owner."""
    name = arg.removeprefix("projects/").strip("/")
    if "/" in name or owner:
        return name if "/" in name else f"{owner}/{name}"
    try:
        rows = yaml.safe_load(registry.read_text(encoding="utf-8")) or []
    except (OSError, yaml.YAMLError):
        rows = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and name in (row.get("name"), row.get("slug")):
            m = re.match(r"https://github\.com/([^/]+/[^/]+?)(?:\.git)?/?$", str(row.get("repo_url") or ""))
            if m:
                return m.group(1)
    return f"bamr87/{name}"


def read_state(gh: Gh, slug: str, policy: Policy) -> dict:
    """Everything the plan and the audit need, from GETs only."""
    repo = gh.call(f"repos/{slug}")
    branch = repo.get("default_branch") or policy.default
    b = quote(branch, safe="")
    st = {"slug": slug, "branch": branch, "private": repo.get("private"),
          "admin": (repo.get("permissions") or {}).get("admin"),
          "methods": {m: repo.get(f"allow_{m}_merge" if m != "merge" else "allow_merge_commit") for m in METHODS},
          "ruleset": None, "effective": None, "classic": None, "classic_note": "", "seen": [], "head": None, "notes": []}
    try:
        for rs in gh.call(f"repos/{slug}/rulesets?includes_parents=false&per_page=100") or []:
            if rs.get("name") == policy.ruleset:
                st["ruleset"] = gh.call(f"repos/{slug}/rulesets/{rs['id']}")
    except GhError as e:
        st["notes"].append(f"rulesets could not be read ({e.status or 'error'}): a private repo needs GitHub Pro for rulesets")
    try:
        st["effective"] = gh.call(f"repos/{slug}/rules/branches/{b}?per_page=100") or []
    except GhError as e:
        st["notes"].append(f"the rules on {branch} could not be read ({e.status or 'error'})")
    try:
        st["classic"] = gh.call(f"repos/{slug}/branches/{b}/protection")
    except GhError as e:
        if e.status == 404 and st["admin"]:
            st["classic_note"] = "none"
        else:
            st["classic_note"] = "unreadable without admin" if e.status in (403, 404) else f"unreadable ({e.status})"
    try:
        runs = gh.call(f"repos/{slug}/commits/{b}/check-runs?per_page=100") or {}
        status = gh.call(f"repos/{slug}/commits/{b}/status") or {}
        st["head"] = status.get("sha") or next((r.get("head_sha") for r in runs.get("check_runs") or []), None)
        st["seen"] = sorted({r.get("name") for r in runs.get("check_runs") or [] if r.get("name")}
                            | {s.get("context") for s in status.get("statuses") or [] if s.get("context")})
    except GhError as e:
        st["notes"].append(f"the checks on {branch} could not be read ({e.status or 'error'})")
    return st


# --------------------------------------------------------------------------- #
# The audit
# --------------------------------------------------------------------------- #
def _rule_checks(rule: dict) -> list[str]:
    return [c.get("context", "") for c in (rule.get("parameters") or {}).get("required_status_checks") or []]


def findings(policy: Policy, st: dict) -> list[dict]:
    """What blocks the fleet's merge flow on this repo, each with its severity and the fix."""
    slug, branch, out = st["slug"], st["branch"], []
    head = f"{branch}@{(st['head'] or '?')[:7]}"
    seen = set(st["seen"])

    def add(sev, text, fix=""):
        out.append({"severity": sev, "text": text, "fix": fix})

    def unseen(ctxs, where):
        for c in ctxs:
            if c and c not in seen:
                add("error", f"{where} requires the check {c!r}, which has not reported on {head}: every pull request waits on it"
                    + (f" (seen there: {', '.join(sorted(seen))})" if seen else ""),
                    f"tools/dash protect {slug} --checks '<a name from the seen list>' --apply")

    if branch != policy.default:
        add("warn", f"the default branch is {branch!r}, not {policy.default!r} (UPS-QA-35)")
    if st["methods"].get(policy.merge_method) is False:
        add("error", f"the repo does not allow a {policy.merge_method} commit, which § 12.2 gives every agent merge",
            f"gh api -X PATCH repos/{slug} -F allow_merge_commit=true   # a setting: the maintainer's")
    c = st["classic"]
    if c:
        if (c.get("required_linear_history") or {}).get("enabled"):
            add("error", "classic protection requires linear history, which forbids the merge commit § 12.2 requires",
                f"tools/dash protect {slug} --apply --drop-classic")
        n = (c.get("required_pull_request_reviews") or {}).get("required_approving_review_count") or 0
        if n:
            add("warn", f"classic protection requires {n} approval(s); a pull request opened with the maintainer's token "
                "cannot be approved by its author, so each one waits on an admin bypass",
                f"tools/dash protect {slug} --apply --drop-classic")
        if (c.get("allow_force_pushes") or {}).get("enabled"):
            add("warn", "classic protection allows force pushes to the default branch")
        unseen((c.get("required_status_checks") or {}).get("contexts") or [], "classic protection")
    for rule in st["effective"] or []:
        src = rule.get("ruleset_source") or "a ruleset"
        t, p = rule.get("type"), rule.get("parameters") or {}
        if t == "required_linear_history":
            add("error", f"{src} requires linear history (ruleset {rule.get('ruleset_id')}), which forbids the merge commit § 12.2 requires")
        elif t == "pull_request":
            allowed = p.get("allowed_merge_methods") or list(METHODS)
            if policy.merge_method not in allowed:
                add("error", f"ruleset {rule.get('ruleset_id')} allows only {', '.join(allowed)}; § 12.2 needs {policy.merge_method}")
            if (p.get("required_approving_review_count") or 0) > policy.approvals:
                add("warn", f"ruleset {rule.get('ruleset_id')} requires {p['required_approving_review_count']} approval(s); "
                    "keep it only where the repo's own constitution asks for a review (§ 12.4)")
        elif t == "required_status_checks":
            unseen(_rule_checks(rule), f"ruleset {rule.get('ruleset_id')}")
    if st["ruleset"] is None:
        add("warn", f"the fleet ruleset {policy.ruleset!r} is not applied (UPS-QA-36)",
            f"tools/dash protect {slug}   # the plan; add --apply")
    gated = any(r.get("type") == "required_status_checks" for r in st["effective"] or []) or \
        bool(((c or {}).get("required_status_checks") or {}).get("contexts"))
    if not gated:
        add("warn", "no required status check guards the default branch (UPS-QA-24)",
            f"tools/dash protect {slug} --checks '<the CI gate>'" + (f"   # seen on {head}: {', '.join(sorted(seen))}" if seen else ""))
    return out


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def plan(policy: Policy, st: dict, args) -> dict:
    live = st["ruleset"]
    live_rules = {r.get("type"): r for r in (live or {}).get("rules") or []}
    if args.checks is not None:
        checks, checks_from = [c.strip() for c in args.checks.split(",") if c.strip()], "--checks"
    elif "required_status_checks" in live_rules:
        checks, checks_from = _rule_checks(live_rules["required_status_checks"]), "the live ruleset"
    else:
        checks, checks_from = [], "none named"
    if args.approvals is not None:
        approvals, approvals_from = args.approvals, "--approvals"
    elif "pull_request" in live_rules:
        approvals = (live_rules["pull_request"].get("parameters") or {}).get("required_approving_review_count") or 0
        approvals_from = "the live ruleset"
    else:
        approvals, approvals_from = policy.approvals, "the policy"
    want = desired_ruleset(policy, checks=checks, approvals=approvals, strict=args.strict or policy.strict,
                           admin_bypass=policy.admin_bypass and not args.enforce_admins)
    refusals = []
    missing = [c for c in checks if c not in set(st["seen"])]
    if missing and not args.allow_unseen:
        refusals.append(f"{', '.join(map(repr, missing))} has not reported on {st['branch']}@{(st['head'] or '?')[:7]}, so "
                        "requiring it would hold every pull request; name a check from the seen list, or pass "
                        "--allow-unseen for one that runs only on pull requests")
    if st["methods"].get(policy.merge_method) is False:
        refusals.append(f"the repo does not allow a {policy.merge_method} commit: the ruleset would leave no way to merge "
                        f"(gh api -X PATCH repos/{st['slug']} -F allow_merge_commit=true, the maintainer's setting)")
    changes = diff_ruleset(live, want)
    drop = bool(args.drop_classic and st["classic"])
    return {"repo": st["slug"], "branch": st["branch"], "ruleset": want, "changes": changes, "drop_classic": drop,
            "refusals": refusals, "checks": checks, "checks_from": checks_from, "approvals": approvals,
            "approvals_from": approvals_from, "admin_bypass": bool(want["bypass_actors"]), "seen": st["seen"],
            "head": st["head"], "findings": findings(policy, st), "notes": st["notes"],
            "classic": st["classic_note"] or "present"}


def apply(gh: Gh, st: dict, p: dict) -> list[str]:
    """Write the plan: the ruleset first, so the branch is never left with neither."""
    done = []
    slug, live = st["slug"], st["ruleset"]
    if p["changes"]:
        if live:
            gh.call(f"repos/{slug}/rulesets/{live['id']}", "PUT", p["ruleset"])
            done.append(f"updated ruleset {p['ruleset']['name']!r} ({live['id']})")
        else:
            made = gh.call(f"repos/{slug}/rulesets", "POST", p["ruleset"]) or {}
            done.append(f"created ruleset {p['ruleset']['name']!r} ({made.get('id', '?')})")
    if p["drop_classic"]:
        gh.call(f"repos/{slug}/branches/{quote(st['branch'], safe='')}/protection", "DELETE")
        done.append(f"deleted the classic protection on {st['branch']}")
    return done


def _print_findings(fs: list[dict]) -> None:
    icon = {"error": "✗", "warn": "!", "info": "·"}
    for f in fs:
        print(f"  {icon.get(f['severity'], '·')} {f['text']}")
        if f["fix"]:
            print(f"      fix: {f['fix']}")


def cmd_classify(args, policy: Policy) -> int:
    rc = 0
    for name in args.names:
        kind, pre = classify(name, policy)
        print(f"{name}\t{kind}" + (f"\t{pre}" if pre else ""))
        if kind == "unknown":
            rc = 1 if args.strict else rc
            if args.github:
                print(f"::warning title=Branch name (UPS-QA-35)::{name!r} matches no declared prefix; "
                      f"use a work prefix ({' '.join(policy.work)}) or declare the loop's prefix in _data/fleet.yml "
                      "branches: (docs/BRANCHING.md)")
    return rc


def cmd_protect(args, policy: Policy, gh: Gh) -> int:
    slug = resolve_repo(args.repo, args.owner)
    try:
        st = read_state(gh, slug, policy)
    except GhError as e:
        print(f"✗ {slug}: {e}", file=sys.stderr)
        return 2
    p = plan(policy, st, args)
    if args.json:
        print(json.dumps(p, indent=2))
    else:
        mode = "apply" if args.apply else "plan (dry run: nothing is written; add --apply)"
        print(f"▸ {slug}@{st['branch']} — ruleset {policy.ruleset!r}, {mode}")
        print(f"  required checks: {', '.join(p['checks']) or 'none'} (from {p['checks_from']}); "
              f"approvals: {p['approvals']} (from {p['approvals_from']}); merge method: {policy.merge_method} only; "
              f"admin bypass: {'yes' if p['admin_bypass'] else 'no'}; classic protection: {p['classic']}")
        print(f"  checks seen on {st['branch']}@{(st['head'] or '?')[:7]}: {', '.join(st['seen']) or 'none'}")
        lines = p["changes"] + ([f"delete the classic protection on {st['branch']} (the ruleset replaces it)"]
                                if p["drop_classic"] else [])
        for line in lines or ["no change: the live ruleset already matches"]:
            print(f"  → {line}")
        for n in p["notes"]:
            print(f"  · {n}")
        if p["findings"]:
            print("  audit:")
            _print_findings(p["findings"])
        for r in p["refusals"]:
            print(f"  ✗ refused: {r}")
    if p["refusals"]:
        return 1
    if args.apply and (p["changes"] or p["drop_classic"]):
        try:
            for line in apply(gh, st, p):
                print(f"✓ {line}")
        except GhError as e:
            print(f"✗ {slug}: {e}" + (" (applying a ruleset needs admin on the repo)" if e.status in (403, 404) else ""),
                  file=sys.stderr)
            return 1
        print(f"✓ verify: tools/dash protect {slug} --check")
    return 0


def cmd_check(args, policy: Policy, gh: Gh) -> int:
    worst, report = 0, []
    for repo in args.repos:
        slug = resolve_repo(repo, args.owner)
        try:
            st = read_state(gh, slug, policy)
        except GhError as e:
            report.append({"repo": slug, "error": str(e)})
            print(f"✗ {slug}: {e}", file=sys.stderr)
            worst = max(worst, 2)
            continue
        fs = findings(policy, st)
        report.append({"repo": slug, "branch": st["branch"], "findings": fs, "notes": st["notes"], "seen": st["seen"]})
        if not args.json:
            errors = sum(f["severity"] == "error" for f in fs)
            print(f"{'✗' if errors else '✓'} {slug}@{st['branch']}: {errors} error(s), "
                  f"{sum(f['severity'] == 'warn' for f in fs)} warning(s); classic protection: {st['classic_note'] or 'present'}")
            _print_findings(fs)
            for n in st["notes"]:
                print(f"  · {n}")
        if any(f["severity"] == "error" for f in fs):
            worst = max(worst, 1)
    if args.json:
        print(json.dumps(report, indent=2))
    return worst


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="branch_policy.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("classify", help="which declared prefix a branch name falls under")
    c.add_argument("names", nargs="+")
    c.add_argument("--strict", action="store_true", help="exit 1 when a name matches no declared prefix")
    c.add_argument("--github", action="store_true", help="also emit a GitHub Actions warning per unknown name")
    p = sub.add_parser("protect", help="plan (or with --apply, write) the fleet ruleset on a repo's default branch")
    p.add_argument("repo", help="owner/name, a registry name, or projects/<dir>")
    p.add_argument("--owner", help="owner for a bare name not in the registry (default bamr87)")
    p.add_argument("--checks", help="comma list of required check names; omitted, the live ruleset's are kept")
    p.add_argument("--approvals", type=int, choices=range(11), metavar="N",
                   help="required approvals (default: the live ruleset's, else the policy's 0)")
    p.add_argument("--strict", action="store_true", help="require the head to be up to date with the base")
    p.add_argument("--enforce-admins", action="store_true", help="no admin bypass")
    p.add_argument("--allow-unseen", action="store_true", help="allow a check that has not reported on the default branch")
    p.add_argument("--drop-classic", action="store_true", help="with --apply, delete the classic protection the ruleset replaces")
    p.add_argument("--apply", action="store_true", help="write the plan (needs admin; the maintainer's)")
    p.add_argument("--json", action="store_true")
    k = sub.add_parser("check", help="audit the live protection of one or more repos, read-only")
    k.add_argument("repos", nargs="+")
    k.add_argument("--owner")
    k.add_argument("--json", action="store_true")
    return ap


def main(argv: list[str] | None = None, runner: Runner = run) -> int:
    args = parser().parse_args(argv)
    try:
        policy = load_policy()
    except (OSError, PolicyError, yaml.YAMLError) as e:
        print(f"✗ branch policy: {e}", file=sys.stderr)
        return 2
    if args.cmd == "classify":
        return cmd_classify(args, policy)
    gh = Gh(runner)
    return cmd_protect(args, policy, gh) if args.cmd == "protect" else cmd_check(args, policy, gh)


if __name__ == "__main__":
    sys.exit(main())
