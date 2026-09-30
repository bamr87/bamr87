#!/usr/bin/env python3
"""
fleet-config — read, audit, and project the fleet's central configuration.

`_data/fleet.yml` declares what every repo in the fleet is supposed to have:
toolchain versions, the token contract (which secret does what, and where it
must exist), and the canonical repository variables. This tool is the half that
makes the declaration real.

  show    Print the resolved config, or one value for a shell/workflow to read.
  audit   Per-repo matrix of which declared secrets and variables actually
          exist on GitHub. Secret VALUES are never read — `gh secret list`
          returns names only, which is all an audit needs and all it should see.
  sync    Project the canonical `variables:` block onto the fleet. Dry-run by
          default; `--apply` writes.
  auth    The per-repo AI auth order (`ai_auth:`): which Claude credential each
          repo tries first. `auth` shows the resolution, where each order came
          from, and what each repo holds; `auth sync --apply` projects it as the
          CLAUDE_AUTH_ORDER variable. The secret writers below honour it: a repo
          is only sent the credentials its order uses.
  keys    Anthropic Console API keys per workspace (`api_keys:`). The Admin API
          can list keys and disable them but cannot CREATE one, so rotation is
          assisted: paste the new Console keys into .env under any
          ANTHROPIC_API_KEY* name; `keys` matches each to its Console record,
          `keys verify` proves each with one cheap call, and `keys rotate
          --apply` writes each workspace's key to the repos it serves, hub
          first, then disables the key it replaced.
  sync-secrets
          Project the declared token contract onto the fleet. Values are read
          ONLY from the environment (export the secret under its own name);
          they are never stored in, or read from, any file. Dry-run by
          default; `--apply` writes; already-set secrets are left alone unless
          `--rotate`.
  push    The operator's rotation path: read the token contract's names out
          of a local dotenv file (default: the hub's gitignored .env), write
          each to the HUB first, then fan every `scope: fleet` secret out to
          the fleet — aborting a secret's fan-out if the hub refuses it. The
          file is PARSED, never exported, so its other keys (a local
          GITHUB_TOKEN above all, which would swap the credential `gh` writes
          with) never reach a subprocess. Dry-run by default; `--apply`
          writes; `--hub-only` stops at the hub and leaves the fan-out to the
          weekly `rotate`.
  rotate  The weekly loop that brings the fleet into line with the HUB, for
          both halves of the contract:
            secrets   audit every repo's AGE from GitHub's own `updated_at`,
                      mint where the contract says one can be minted
                      unattended, and propagate hub-first. Values reach this
                      tool only through the environment, because GitHub never
                      returns a secret's value to anyone.
            variables the API DOES return these, so the hub's live settings are
                      the source of truth and repos are compared by VALUE, not
                      by age. `--no-variables` skips this half.
          Dry-run by default; `--apply` writes. See `rotation:` in
          _data/fleet.yml.
  rotation-plan
          The read-only half of `rotate`: the per-repo age matrix, what is
          stale, and what the next run would do. Writes the values-free ledger
          with `--ledger`.

WHY THIS EXISTS
---------------
`bamr87` is a personal account, not an organization, so GitHub's org-level
secrets, variables, and shared rulesets — the normal way to centralize this —
are unavailable. There is no server-side place to put fleet-wide config. The
workable substitute is to declare the contract in version control and use
tooling to project it outward and audit the result. That is what this is.

Auth: the `gh` CLI (inherits `gh auth login` locally, GH_TOKEN/GITHUB_TOKEN in
CI). Reading another repo's secret NAMES requires admin on that repo; repos the
token can't reach are reported as `?` rather than as a missing secret, because
"I cannot see it" and "it is not there" are different findings and conflating
them would send you chasing secrets that are already set.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("fleet-config requires PyYAML: pip install pyyaml\n")
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parents[1]
FLEET = REPO_ROOT / "_data" / "fleet.yml"
REGISTRY = REPO_ROOT / "_data" / "projects.yml"

OK, MISSING, UNKNOWN, EXTRA = "✅", "❌", "❔", "➕"


# --------------------------------------------------------------------------- #
# loading
# --------------------------------------------------------------------------- #
def load(path: Path) -> dict | list:
    if not path.exists():
        sys.stderr.write(f"missing: {path}\n")
        sys.exit(2)
    with path.open() as fh:
        return yaml.safe_load(fh) or {}


def owner_repo(url: str) -> str | None:
    if not url or "github.com/" not in url:
        return None
    tail = url.split("github.com/", 1)[1].removesuffix(".git").strip("/")
    return tail if tail.count("/") == 1 else None


def fleet_repos(cfg: dict, registry: list) -> list[dict]:
    """Registry repos owned by the hub owner — external mirrors excluded.

    A mirror's secrets are not ours to audit and its variables are not ours to
    set, so including them would produce findings nobody can act on.
    """
    hub_nwo = cfg.get("hub", {}).get("repo") or "bamr87/bamr87"
    owner = hub_nwo.split("/", 1)[0]
    # The hub is the control plane, not one of its own registry entries — but it
    # holds every hub-scoped secret, so auditing it is the whole point. Seed it
    # explicitly rather than hoping it appears in projects.yml.
    out = [{"name": hub_nwo.split("/")[-1], "nwo": hub_nwo}]
    for p in registry:
        nwo = owner_repo(p.get("repo_url") or "")
        if not nwo or not nwo.startswith(f"{owner}/"):
            continue
        if p.get("status") == "archived":
            continue
        out.append({"name": p.get("name") or nwo.split("/")[-1], "nwo": nwo})
    # A repo can appear twice in the registry under different names; dedupe on
    # the slug so it is audited once.
    seen, uniq = set(), []
    for r in sorted(out, key=lambda r: r["nwo"]):
        if r["nwo"] in seen:
            continue
        seen.add(r["nwo"])
        uniq.append(r)
    return uniq


# --------------------------------------------------------------------------- #
# gh helpers
# --------------------------------------------------------------------------- #
def gh_json(args: list[str]) -> list | dict | None:
    try:
        out = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return None


def repo_secret_meta(nwo: str) -> dict[str, str] | None:
    """name -> ISO-8601 `updated_at`, or None when the repo can't be read.

    GitHub's secrets API returns names and timestamps but never values, which is
    exactly the shape an age audit needs: `updated_at` is when the secret was
    last WRITTEN, so it is the rotation clock without anyone having to keep a
    separate one. A repo we lack admin on returns None, and the caller must keep
    reporting that as "cannot see" rather than "missing".
    """
    data = gh_json(["api", f"repos/{nwo}/actions/secrets",
                    "--jq", "[.secrets[] | {name, updated_at}]"])
    if not isinstance(data, list):
        return None
    return {s["name"]: s.get("updated_at") or "" for s in data}


def repo_secret_names(nwo: str) -> set[str] | None:
    meta = repo_secret_meta(nwo)
    return set(meta) if meta is not None else None


def repo_variables(nwo: str) -> dict[str, str] | None:
    data = gh_json(["api", f"repos/{nwo}/actions/variables",
                    "--jq", "[.variables[] | {name, value}]"])
    if not isinstance(data, list):
        return None
    return {v["name"]: v["value"] for v in data}


# --------------------------------------------------------------------------- #
# AI auth order — `ai_auth:` in _data/fleet.yml
#
# Which Claude credential each repo tries first. Resolved per repo (`repos:`
# beats `groups:` beats `default:`), projected onto the repo as a variable the
# call sites read, and consulted by every secret writer so a repo is only sent
# the credentials its order actually uses.
# --------------------------------------------------------------------------- #
AUTH_METHODS_DEFAULT = {"oauth": "CLAUDE_CODE_OAUTH_TOKEN", "api_key": "ANTHROPIC_API_KEY"}
AUTH_ORDER_DEFAULT = ["oauth", "api_key"]


def parse_order(value) -> list[str]:
    """`oauth,api_key` or `[oauth, api_key]` → ['oauth', 'api_key'], deduped."""
    items = value if isinstance(value, list) else str(value or "").split(",")
    out: list[str] = []
    for item in items:
        m = str(item).strip()
        if m and m not in out:
            out.append(m)
    return out


def auth_config(cfg: dict) -> dict:
    a = cfg.get("ai_auth") or {}
    return {
        "declared": bool(cfg.get("ai_auth")),
        "variable": a.get("variable") or "CLAUDE_AUTH_ORDER",
        "methods": dict(a.get("methods") or AUTH_METHODS_DEFAULT),
        "default": parse_order(a.get("default")) or list(AUTH_ORDER_DEFAULT),
        "groups": a.get("groups") or {},
        "repos": a.get("repos") or {},
    }


def _repo_key_matches(key: str, repo: dict) -> bool:
    key = str(key).strip()
    return key in (repo["name"], repo["nwo"], repo["nwo"].split("/")[-1])


def resolve_auth(cfg: dict, registry: list) -> tuple[dict[str, dict], list[str]]:
    """({nwo: {name, nwo, order, source}}, errors) for every fleet repo + the hub.

    Errors are returned, not raised: `dash config auth` shows them next to the
    resolution so the operator sees the whole picture in one place, and every
    writer refuses to act while any exist.
    """
    ac = auth_config(cfg)
    methods = set(ac["methods"])
    errors: list[str] = []
    categories = {owner_repo(p.get("repo_url") or ""): p.get("category")
                  for p in registry if isinstance(p, dict)}
    repos = fleet_repos(cfg, registry)

    def check(order: list[str], where: str) -> list[str]:
        if not order:
            errors.append(f"{where}: empty order")
        for m in order:
            if m not in methods:
                errors.append(f"{where}: unknown method {m!r} (one of {', '.join(sorted(methods))})")
        return order

    default = check(ac["default"], "ai_auth.default")
    group_orders: dict[str, list[str]] = {}
    for g, spec in ac["groups"].items():
        spec = spec or {}
        group_orders[g] = check(parse_order(spec.get("order")), f"ai_auth.groups.{g}")
        if not spec.get("repos") and not spec.get("categories"):
            errors.append(f"ai_auth.groups.{g}: names neither repos nor categories")
    repo_orders = {str(k): check(parse_order(v), f"ai_auth.repos.{k}")
                   for k, v in ac["repos"].items()}

    known = [k for g in ac["groups"].values() for k in ((g or {}).get("repos") or [])] + list(repo_orders)
    for key in known:
        if not any(_repo_key_matches(key, r) for r in repos):
            errors.append(f"ai_auth: {key!r} is not a fleet repo (registry name or owner/repo)")

    out: dict[str, dict] = {}
    for r in repos:
        order, source = default, "default"
        hits = []
        for g, spec in ac["groups"].items():
            spec = spec or {}
            if (any(_repo_key_matches(k, r) for k in spec.get("repos") or [])
                    or categories.get(r["nwo"]) in (spec.get("categories") or [])):
                hits.append(g)
        if hits:
            distinct = {",".join(group_orders[g]) for g in hits}
            if len(distinct) > 1:
                errors.append(f"{r['nwo']}: in groups {', '.join(hits)} with different orders")
            order, source = group_orders[hits[0]], f"group:{hits[0]}"
        for k, o in repo_orders.items():
            if _repo_key_matches(k, r):
                order, source = o, "repo"
        out[r["nwo"]] = {**r, "order": order, "source": source}
    return out, errors


def auth_method_of(cfg: dict, secret: str) -> str | None:
    """The auth method a secret implements, or None for a non-auth secret."""
    return next((m for m, s in auth_config(cfg)["methods"].items() if s == secret), None)


def secret_wanted(cfg: dict, resolved: dict[str, dict], nwo: str, secret: str,
                  hub_nwo: str) -> bool:
    """Does `nwo` need `secret`? The hub always does — it is the master copy."""
    method = auth_method_of(cfg, secret)
    if method is None or nwo == hub_nwo or nwo not in resolved:
        return True
    return method in resolved[nwo]["order"]


def auth_variables(cfg: dict, registry: list) -> dict[str, dict[str, str]]:
    """{nwo: {VAR: 'oauth,api_key'}} — the per-repo half of the variables pass.
    Empty unless `ai_auth:` is declared, so an unconfigured fleet is untouched."""
    ac = auth_config(cfg)
    if not ac["declared"]:
        return {}
    resolved, errors = resolve_auth(cfg, registry)
    if errors:
        return {}
    return {nwo: {ac["variable"]: ",".join(r["order"])} for nwo, r in resolved.items()}


def cmd_auth(args: argparse.Namespace) -> int:
    cfg = load(FLEET)
    registry = load(REGISTRY)
    ac = auth_config(cfg)
    hub_nwo = cfg.get("hub", {}).get("repo") or "bamr87/bamr87"
    resolved, errors = resolve_auth(cfg, registry)
    rows = list(resolved.values())
    if args.repo:
        rows = [r for r in rows if args.repo in (r["name"], r["nwo"])]
        if not rows:
            sys.stderr.write(f"no fleet repo matching {args.repo!r}\n")
            return 1
    var = ac["variable"]
    sync = args.action == "sync"
    live = not args.offline or sync

    if args.json and not sync:
        print(json.dumps({"variable": var, "methods": ac["methods"],
                          "default": ac["default"], "errors": errors,
                          "repos": [{"name": r["name"], "nwo": r["nwo"],
                                     "order": r["order"], "source": r["source"]}
                                    for r in rows]}, indent=2))
        return 1 if errors else 0

    mode = ("APPLY" if args.apply else "DRY-RUN") if sync else "resolved"
    print(f"\n\033[1mAI auth order\033[0m [{mode}] — variable {var}, "
          f"default {','.join(ac['default'])}\n")
    if errors:
        for e in errors:
            print(f"  {MISSING} {e}")
        print("\n  Fix ai_auth in _data/fleet.yml — nothing is written while it has errors.\n")
        if sync:
            return 1

    method_cols = list(ac["methods"].items())
    changed = failed = skipped = 0
    for r in rows:
        order = ",".join(r["order"])
        line = f"  {r['nwo'][:32]:32} {order:18} {r['source']:18}"
        if live:
            secrets = repo_secret_names(r["nwo"])
            current = repo_variables(r["nwo"])
            for m, secret in method_cols:
                wanted = secret_wanted(cfg, resolved, r["nwo"], secret, hub_nwo)
                mark = (UNKNOWN if secrets is None else
                        OK if secret in secrets else (MISSING if wanted else "·"))
                line += f" {m}:{mark}"
            have = None if current is None else current.get(var)
            if current is None:
                line += f"  var:{UNKNOWN}"
                skipped += sync
            elif have == order:
                line += f"  var:{OK}"
            else:
                line += f"  var:{have or '—'}→{order}"
                if sync and not errors:
                    if not args.apply:
                        changed += 1
                    else:
                        proc = subprocess.run(["gh", "variable", "set", var, "--body", order,
                                               "-R", r["nwo"]], capture_output=True, text=True)
                        if proc.returncode == 0:
                            changed += 1
                            line += " (set)"
                        else:
                            failed += 1
                            err = (proc.stderr or "").strip().splitlines()
                            line += f" FAILED: {err[0] if err else '?'}"
        print(line)

    print(f"\n  \033[2morder = methods tried in turn · source = where the order came from · "
          f"{OK} secret present  {MISSING} needed but missing  · not used by this order  "
          f"{UNKNOWN} unreachable\033[0m")
    if sync:
        verb = "applied" if args.apply else "pending"
        print(f"\n  {changed} variable write(s) {verb} · {skipped} unreachable · {failed} failed")
        if not args.apply and changed:
            print("  Re-run with --apply to write. Secrets follow the order on the next "
                  "`dash secrets push|rotate`.\n")
    return 1 if (failed or errors) else 0


# --------------------------------------------------------------------------- #
# show
# --------------------------------------------------------------------------- #
def cmd_show(args: argparse.Namespace) -> int:
    cfg = load(FLEET)
    if args.key:
        node = cfg
        for part in args.key.split("."):
            if not isinstance(node, dict) or part not in node:
                sys.stderr.write(f"no such key: {args.key}\n")
                return 1
            node = node[part]
        print(node if not isinstance(node, (dict, list))
              else json.dumps(node, indent=2, default=str))
        return 0
    print(json.dumps(cfg, indent=2, default=str) if args.json
          else yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
    return 0


# --------------------------------------------------------------------------- #
# audit
# --------------------------------------------------------------------------- #
def cmd_audit(args: argparse.Namespace) -> int:
    cfg = load(FLEET)
    registry = load(REGISTRY)
    repos = fleet_repos(cfg, registry)
    if args.repo:
        repos = [r for r in repos if args.repo in (r["name"], r["nwo"])]
        if not repos:
            sys.stderr.write(f"no fleet repo matching {args.repo!r}\n")
            return 1

    tokens = cfg.get("tokens") or []
    fleet_secrets = [t for t in tokens
                     if t.get("scope") == "fleet" and not t.get("deprecated")]
    hub_secrets = [t for t in tokens
                   if t.get("scope") == "hub" and not t.get("deprecated")]
    canonical_vars = cfg.get("variables") or {}
    hub_nwo = cfg.get("hub", {}).get("repo") or "bamr87/bamr87"

    resolved, _ = resolve_auth(cfg, registry)
    rows, unreachable = [], []
    for r in repos:
        secrets = repo_secret_names(r["nwo"])
        variables = repo_variables(r["nwo"])
        if secrets is None and variables is None:
            unreachable.append(r["nwo"])
        rows.append({**r, "secrets": secrets, "variables": variables})

    if args.json:
        print(json.dumps({
            "hub": hub_nwo,
            "required_fleet_secrets": [t["name"] for t in fleet_secrets],
            "required_hub_secrets": [t["name"] for t in hub_secrets],
            "canonical_variables": canonical_vars,
            "repos": [{
                "name": r["name"], "nwo": r["nwo"],
                "reachable": r["secrets"] is not None or r["variables"] is not None,
                "secrets": sorted(r["secrets"]) if r["secrets"] is not None else None,
                "variables": r["variables"],
            } for r in rows],
        }, indent=2))
        return 0

    def cell(present: set | dict | None, key: str) -> str:
        if present is None:
            return UNKNOWN
        return OK if key in present else MISSING

    secret_cols = [t["name"] for t in fleet_secrets]
    var_cols = list(canonical_vars)

    print(f"\n\033[1mFleet secret & variable audit\033[0m — {len(rows)} repo(s), "
          f"hub {hub_nwo}\n")
    if secret_cols or var_cols:
        # Full secret/variable names are far too wide to head a column (and
        # truncating them to `CLAUDE_CODE_OA` helps nobody), so columns are
        # numbered S1..Sn / V1..Vn and expanded in a legend underneath.
        codes = ([(f"S{i}", n) for i, n in enumerate(secret_cols, 1)]
                 + [(f"V{i}", n) for i, n in enumerate(var_cols, 1)])
        head = f"{'repo':30}" + "".join(f" {code:>4}" for code, _ in codes)
        print(f"\033[2m{head}\033[0m")
        for r in rows:
            line = f"{r['nwo'][:30]:30}"
            for c in secret_cols:
                mark = cell(r["secrets"], c)
                if mark == MISSING and not secret_wanted(cfg, resolved, r["nwo"], c, hub_nwo):
                    mark = "·"
                line += f" {mark:>4}"
            for c in var_cols:
                if r["variables"] is None:
                    mark = UNKNOWN
                elif c not in r["variables"]:
                    mark = MISSING
                elif str(r["variables"][c]) != str(canonical_vars[c]):
                    mark = "≠"
                else:
                    mark = OK
                line += f" {mark:>4}"
            print(line)
        print()
        for code, name in codes:
            kind = "secret" if code.startswith("S") else f"var = {canonical_vars[name]!r}"
            print(f"\033[2m  {code:>4}  {name:28} {kind}\033[0m")

    # hub-scoped secrets are a single-repo question, so they get their own block
    hub_row = next((r for r in rows if r["nwo"] == hub_nwo), None)
    if hub_secrets:
        print(f"\n\033[1mHub secrets\033[0m ({hub_nwo})")
        hub_present = hub_row["secrets"] if hub_row else None
        for t in hub_secrets:
            mark = cell(hub_present, t["name"])
            req = "required" if t.get("required") else "optional"
            print(f"  {mark} {t['name']:26} {req:9} {(t.get('purpose') or '').splitlines()[0][:70]}")

    deprecated = [t for t in tokens if t.get("deprecated")]
    if deprecated and hub_row and hub_row["secrets"] is not None:
        still = [t["name"] for t in deprecated if t["name"] in hub_row["secrets"]]
        if still:
            print(f"\n\033[2mDeprecated secrets still present on {hub_nwo}: "
                  f"{', '.join(still)}\n  (superseded by FLEET_TOKEN — remove once it is "
                  f"provisioned and a fleet-pulse run is green)\033[0m")

    if unreachable:
        print(f"\n\033[2m{UNKNOWN} unreachable ({len(unreachable)}): "
              f"{', '.join(unreachable[:8])}"
              f"{' …' if len(unreachable) > 8 else ''}"
              f"\n  Listing secrets requires admin on the repo — these are 'cannot see', "
              f"not 'not set'.\033[0m")

    print(f"\n  {OK} set   {MISSING} missing   · not used by the repo's ai_auth order   "
          f"≠ differs from canonical   {UNKNOWN} unreachable\n")

    if args.gate:
        gaps = sum(1 for r in rows if r["secrets"] is not None
                   for t in fleet_secrets
                   if t.get("required") and t["name"] not in r["secrets"])
        if gaps:
            sys.stderr.write(f"::error::{gaps} required fleet secret(s) missing.\n")
            return 1
    return 0


# --------------------------------------------------------------------------- #
# sync
# --------------------------------------------------------------------------- #
def cmd_sync(args: argparse.Namespace) -> int:
    cfg = load(FLEET)
    registry = load(REGISTRY)
    canonical = cfg.get("variables") or {}
    if not canonical:
        print("No `variables:` declared in _data/fleet.yml — nothing to sync.")
        return 0

    repos = fleet_repos(cfg, registry)
    if args.repo:
        repos = [r for r in repos if args.repo in (r["name"], r["nwo"])]
        if not repos:
            sys.stderr.write(f"no fleet repo matching {args.repo!r}\n")
            return 1

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"\n\033[1mSync canonical variables\033[0m [{mode}] → {len(repos)} repo(s)\n")
    changed = skipped = failed = 0
    per_repo = auth_variables(cfg, registry)

    for r in repos:
        current = repo_variables(r["nwo"])
        if current is None:
            print(f"  {UNKNOWN} {r['nwo']:30} unreachable (needs admin) — skipped")
            skipped += 1
            continue
        want = {**canonical, **per_repo.get(r["nwo"], {})}
        diffs = {k: v for k, v in want.items()
                 if str(current.get(k, "\0")) != str(v)}
        if not diffs:
            print(f"  {OK} {r['nwo']:30} up to date")
            continue
        for key, value in diffs.items():
            was = current.get(key)
            label = f"{key}={value}" + (f"  (was {was})" if was is not None else "  (new)")
            if not args.apply:
                print(f"  {EXTRA} {r['nwo']:30} would set {label}")
                changed += 1
                continue
            proc = subprocess.run(
                ["gh", "variable", "set", key, "--body", str(value), "-R", r["nwo"]],
                capture_output=True, text=True)
            if proc.returncode == 0:
                print(f"  {EXTRA} {r['nwo']:30} set {label}")
                changed += 1
            else:
                # `.splitlines()[:1]` is a LIST, and an f-string renders it as
                # `['permission denied']` — brackets, quotes and all. Index it.
                err = (proc.stderr or "").strip().splitlines()
                print(f"  {MISSING} {r['nwo']:30} FAILED {key}: "
                      f"{err[0] if err else '(no error output)'}")
                failed += 1

    verb = "applied" if args.apply else "pending"
    print(f"\n  {changed} change(s) {verb} · {skipped} unreachable · {failed} failed")
    if not args.apply and changed:
        print("  Re-run with --apply to write.\n")
    return 1 if failed else 0


# --------------------------------------------------------------------------- #
# sync-secrets
# --------------------------------------------------------------------------- #
def cmd_sync_secrets(args: argparse.Namespace) -> int:
    """Project the token contract onto the fleet, values supplied via env.

    Secrets are write-only on GitHub, so unlike variables there is no way to
    copy one repo's secret to another — the value must come from the operator.
    The ONLY accepted channel is an environment variable named after the
    secret (e.g. `CLAUDE_CODE_OAUTH_TOKEN=... dash secrets sync --apply`).
    Values are never echoed, logged, or written to disk by this tool.
    """
    import os

    cfg = load(FLEET)
    registry = load(REGISTRY)
    managed = {t["name"]: t["managed_by"] for t in (cfg.get("tokens") or []) if t.get("managed_by")}
    for name, owner in managed.items():
        print(f"  \033[2m{name}: managed by `dash {owner}` — not written here\033[0m")
    tokens = [t for t in (cfg.get("tokens") or [])
              if not t.get("deprecated") and not t.get("managed_by")]
    if args.only:
        tokens = [t for t in tokens if t["name"] in args.only]
        missing = set(args.only) - {t["name"] for t in tokens}
        if missing:
            sys.stderr.write(f"not in the token contract: {', '.join(sorted(missing))}\n")
            return 1

    hub_nwo = cfg.get("hub", {}).get("repo") or "bamr87/bamr87"
    repos = fleet_repos(cfg, registry)
    if args.repo:
        repos = [r for r in repos if args.repo in (r["name"], r["nwo"])]
        if not repos:
            sys.stderr.write(f"no fleet repo matching {args.repo!r}\n")
            return 1

    resolved, auth_errors = resolve_auth(cfg, registry)
    if auth_errors:
        sys.stderr.write("ai_auth has errors — run `dash config auth` first:\n  "
                         + "\n  ".join(auth_errors) + "\n")
        return 1
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"\n\033[1mSync token contract\033[0m [{mode}]\n")
    changed = skipped = failed = 0

    for t in tokens:
        name = t["name"]
        value = os.environ.get(name)
        targets = [r for r in repos
                   if secret_wanted(cfg, resolved, r["nwo"], name, hub_nwo)] \
            if t.get("scope") == "fleet" else [r for r in repos if r["nwo"] == hub_nwo]
        if not value:
            print(f"  \033[2m{name}: no value in env — export {name}=… to provision "
                  f"({len(targets)} target repo(s))\033[0m")
            continue
        for r in targets:
            present = repo_secret_names(r["nwo"])
            if present is None:
                print(f"  {UNKNOWN} {r['nwo']:30} unreachable — skipped {name}")
                skipped += 1
                continue
            if name in present and not args.rotate:
                print(f"  {OK} {r['nwo']:30} {name} already set")
                continue
            verb = "rotate" if name in present else "set"
            if not args.apply:
                print(f"  {EXTRA} {r['nwo']:30} would {verb} {name}")
                changed += 1
                continue
            proc = subprocess.run(
                ["gh", "secret", "set", name, "-R", r["nwo"]],
                input=value, capture_output=True, text=True)
            if proc.returncode == 0:
                print(f"  {EXTRA} {r['nwo']:30} {verb} {name}")
                changed += 1
            else:
                err = (proc.stderr or "").strip().splitlines()
                print(f"  {MISSING} {r['nwo']:30} FAILED {name}: "
                      f"{err[0] if err else '(no error output)'}")
                failed += 1

    verb = "applied" if args.apply else "pending"
    print(f"\n  {changed} change(s) {verb} · {skipped} unreachable · {failed} failed")
    if not args.apply and changed:
        print("  Re-run with --apply to write.\n")
    return 1 if failed else 0


# --------------------------------------------------------------------------- #
# push — the operator's .env → the hub → the fleet
#
# `sync-secrets` takes values from the environment, which in practice meant
# `set -a; source .env` — and the hub's .env also carries a GITHUB_TOKEN for
# local tools, so sourcing it swapped the credential `gh` writes secrets WITH
# for one that usually lacks secrets:write. `push` reads the file as data
# instead: only contract names are taken, values leave only on `gh secret
# set`'s stdin, and nothing is exported.
# --------------------------------------------------------------------------- #
DEFAULT_ENV_FILE = REPO_ROOT / ".env"
ENV_NAME_RX = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def read_env_file(path: Path) -> dict[str, str]:
    """Parse a dotenv file into {name: value} without exporting anything."""
    out: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        name, sep, value = line.partition("=")
        name = name.strip()
        if not sep or not ENV_NAME_RX.match(name):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        out[name] = value
    return out


def push_plan(tokens: list[dict], values: dict[str, str],
              only: list[str] | None = None) -> dict:
    """Which contract secrets the file can supply — names only, never values."""
    managed = {t["name"] for t in tokens if t.get("managed_by") and not t.get("deprecated")}
    contract = {t["name"]: t for t in tokens if not t.get("deprecated") and not t.get("managed_by")}
    unknown = sorted(set(only or []) - set(contract)
                     - {t["name"] for t in tokens if t.get("managed_by")})
    names = [n for n in contract if not only or n in only]
    return {
        "push": [n for n in names if values.get(n)],
        "absent": [n for n in names if not values.get(n)],
        "ignored": sorted(set(values) - set(contract) - managed),
        "managed": sorted(managed & set(values)),
        "unknown": unknown,
        "scope": {n: contract[n].get("scope") for n in names},
    }


def _put_secret(name: str, value: str, nwo: str, verb: str, apply: bool) -> bool:
    if not apply:
        print(f"  {EXTRA} {nwo:34} would {verb} {name}")
        return True
    proc = subprocess.run(["gh", "secret", "set", name, "-R", nwo],
                          input=value, capture_output=True, text=True)
    if proc.returncode == 0:
        print(f"  {EXTRA} {nwo:34} {verb} {name}")
        return True
    err = (proc.stderr or "").strip().splitlines()
    print(f"  {MISSING} {nwo:34} FAILED {name}: {err[0] if err else '(no error output)'}")
    return False


def cmd_push(args: argparse.Namespace) -> int:
    cfg = load(FLEET)
    registry = load(REGISTRY)
    path = Path(args.env_file) if args.env_file else DEFAULT_ENV_FILE
    if not path.is_file():
        sys.stderr.write(f"no env file at {path}\n")
        return 2
    values = read_env_file(path)
    plan = push_plan(cfg.get("tokens") or [], values, args.only)
    if plan["unknown"]:
        sys.stderr.write(f"not in the token contract: {', '.join(plan['unknown'])}\n")
        return 1

    hub_nwo = cfg.get("hub", {}).get("repo") or "bamr87/bamr87"
    resolved, auth_errors = resolve_auth(cfg, registry)
    if auth_errors:
        sys.stderr.write("ai_auth has errors — run `dash config auth` first:\n  "
                         + "\n  ".join(auth_errors) + "\n")
        return 1
    others = [r for r in fleet_repos(cfg, registry) if r["nwo"] != hub_nwo]
    if args.repo:
        others = [r for r in others if args.repo in (r["name"], r["nwo"])]
        if not others:
            sys.stderr.write(f"no fleet repo matching {args.repo!r}\n")
            return 1

    mode = "APPLY" if args.apply else "DRY-RUN"
    try:
        shown = path.relative_to(REPO_ROOT)
    except ValueError:
        shown = path
    print(f"\n\033[1mPush {shown} → {hub_nwo} → fleet\033[0m [{mode}]\n")
    print(f"  from the file : {', '.join(plan['push']) or '(no contract secret)'}")
    if plan["absent"]:
        print(f"  \033[2mnot in the file: {', '.join(plan['absent'])}\033[0m")
    if plan["managed"]:
        print(f"  \033[2mmanaged elsewhere (see `dash keys`): {', '.join(plan['managed'])}\033[0m")
    if plan["ignored"]:
        print(f"  \033[2mignored (not in the token contract, never sent): "
              f"{', '.join(plan['ignored'])}\033[0m")
    print()
    if not plan["push"]:
        print("  nothing to push.\n")
        return 0

    present_cache: dict[str, set[str] | None] = {}

    def present(nwo: str) -> set[str] | None:
        if nwo not in present_cache:
            present_cache[nwo] = repo_secret_names(nwo)
        return present_cache[nwo]

    changed = skipped = failed = 0
    for name in plan["push"]:
        value = values[name]
        mask(value)
        hub_has = present(hub_nwo)
        verb = "rotate" if hub_has and name in hub_has else "set"
        # Hub first, and a refusal there stops this secret: a bad value on one
        # repo is an incident, on the whole fleet an outage (docs/TOKEN-ROTATION.md).
        if not _put_secret(name, value, hub_nwo, verb, args.apply):
            failed += 1
            print(f"    \033[2m{name}: the hub refused it — fan-out aborted\033[0m")
            continue
        changed += 1
        if plan["scope"].get(name) != "fleet":
            continue
        if args.hub_only:
            print(f"    \033[2m{name}: hub only — token-rotation.yml propagates it, "
                  f"since the hub's copy is now the newest\033[0m")
            continue
        skipped_by_order = [r["nwo"] for r in others
                            if not secret_wanted(cfg, resolved, r["nwo"], name, hub_nwo)]
        if skipped_by_order:
            print(f"    \033[2m{name}: not sent to {len(skipped_by_order)} repo(s) whose "
                  f"ai_auth order leaves it out\033[0m")
        for r in others:
            if r["nwo"] in skipped_by_order:
                continue
            have = present(r["nwo"])
            if have is None:
                print(f"  {UNKNOWN} {r['nwo']:34} unreachable — skipped {name}")
                skipped += 1
                continue
            verb = "rotate" if name in have else "set"
            if _put_secret(name, value, r["nwo"], verb, args.apply):
                changed += 1
            else:
                failed += 1

    verb = "applied" if args.apply else "pending"
    print(f"\n  {changed} write(s) {verb} · {skipped} unreachable · {failed} failed")
    if not args.apply and changed:
        print("  Re-run with --apply to write.\n")
    return 1 if failed else 0


# --------------------------------------------------------------------------- #
# keys — Anthropic Console API keys → the repos each workspace pays for
#
# The Admin API can LIST keys (with `expires_at`) and DISABLE them, but it
# cannot create one: a key — and its expiry — is minted in the Claude Console.
# So rotation is assisted: a human creates the new keys and pastes them into
# .env under any `ANTHROPIC_API_KEY*` name; this command does everything else.
# It matches each value to its Console key by the key's partial hint, reads the
# workspace from the key's scope, takes the newest active key per workspace,
# refuses one that outlives the lifetime policy, proves it with one cheap call,
# writes it hub-first to the repos its workspace serves (`api_keys:` in
# _data/fleet.yml; every unclaimed repo gets the Default Workspace's key), and
# only then disables the key it replaced — and only a key THIS tool deployed
# (the ledger), never one someone is using by hand.
# --------------------------------------------------------------------------- #
KEY_LEDGER_DEFAULT = "_data/api_keys.yml"
DEFAULT_SLOT = "default"


def api_keys_config(cfg: dict) -> dict:
    a = cfg.get("api_keys") or {}
    return {
        "declared": bool(cfg.get("api_keys")),
        "secret": a.get("secret") or "ANTHROPIC_API_KEY",
        "env_prefix": a.get("env_prefix") or "ANTHROPIC_API_KEY",
        "admin_credential": a.get("admin_credential") or "CLAUDE_CONSOLE_TOKEN",
        "lifetime_days": int(a.get("lifetime_days") or 7),
        "renew_before_days": int(a.get("renew_before_days") or 2),
        "workspaces": a.get("workspaces") or {},
        "verify": {"model": "claude-opus-5", "max_tokens": 16, **(a.get("verify") or {})},
        "ledger": a.get("ledger") or KEY_LEDGER_DEFAULT,
    }


def key_targets(cfg: dict, registry: list) -> tuple[dict[str, dict], list[str]]:
    """({nwo: {name, nwo, slot, skip}}, errors) — which workspace's key each repo gets.

    A workspace claims repos by registry name, by explicit owner/repo (which may
    sit outside the registry, e.g. a content site in another org), or by GitHub
    owner. Every fleet repo nobody claims gets the Default Workspace's key.
    """
    kc = api_keys_config(cfg)
    hub_nwo = cfg.get("hub", {}).get("repo") or "bamr87/bamr87"
    errors: list[str] = []
    fleet = {r["nwo"]: r for r in fleet_repos(cfg, registry)}
    by_name = {}
    for p in registry:
        nwo = owner_repo((p or {}).get("repo_url") or "") if isinstance(p, dict) else None
        if nwo:
            by_name[str(p.get("name"))] = nwo
    by_name[hub_nwo.split("/")[-1]] = hub_nwo
    claims: dict[str, str] = {}
    for slot, spec in kc["workspaces"].items():
        if slot == DEFAULT_SLOT:
            errors.append(f"api_keys.workspaces: '{DEFAULT_SLOT}' is implicit — every unclaimed repo")
            continue
        spec = spec or {}
        wanted = []
        for entry in spec.get("repos") or []:
            entry = str(entry).strip()
            if "/" in entry:
                wanted.append(entry)
            elif entry in by_name:
                wanted.append(by_name[entry])
            else:
                errors.append(f"api_keys.workspaces.{slot}: {entry!r} is not a registry repo "
                              "(use owner/repo for one outside the registry)")
        for owner in spec.get("owners") or []:
            owned = [nwo for nwo in set(by_name.values()) if nwo.split("/")[0] == owner]
            if not owned:
                errors.append(f"api_keys.workspaces.{slot}: no registry repo is owned by {owner!r}")
            wanted += owned
        if not wanted:
            errors.append(f"api_keys.workspaces.{slot}: claims no repos")
        for nwo in wanted:
            if claims.get(nwo, slot) != slot:
                errors.append(f"{nwo}: claimed by workspaces {claims[nwo]} and {slot}")
            claims[nwo] = slot
    resolved, auth_errors = resolve_auth(cfg, registry)
    errors += auth_errors
    out: dict[str, dict] = {}
    for nwo in sorted(set(fleet) | set(claims)):
        name = fleet[nwo]["name"] if nwo in fleet else nwo.split("/")[-1]
        skip = None
        if not secret_wanted(cfg, resolved, nwo, kc["secret"], hub_nwo):
            skip = "ai_auth order leaves api_key out"
        out[nwo] = {"name": name, "nwo": nwo, "slot": claims.get(nwo, DEFAULT_SLOT), "skip": skip}
    return out, errors


def hint_matches(hint: str | None, value: str) -> bool:
    """A Console key's `partial_key_hint` is `<prefix>...<suffix>` of its secret."""
    if not hint or "..." not in hint or not value:
        return False
    pre, suf = hint.split("...", 1)
    return bool(pre) and bool(suf) and value.startswith(pre) and value.endswith(suf)


def key_candidates(values: dict[str, str], prefix: str) -> dict[str, str]:
    """{env name: value} for everything that could be an inference key — never an
    admin key or an OAuth token, whatever it is called."""
    return {n: v for n, v in values.items()
            if n.startswith(prefix) and v.startswith("sk-ant-")
            and not v.startswith(("sk-ant-admin", "sk-ant-oat", "sk-ant-ort"))}


def _ts(v) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return parse_ts(str(v))


def plan_keys(slots: list[str], workspaces: dict[str, str], keys: list[dict],
              values: dict[str, str], policy: dict, now: datetime | None = None) -> dict[str, dict]:
    """Per slot: the newest ACTIVE Console key whose value is in `values`, its
    remaining life, and what is wrong with it. Pure — the tests drive it.

    `workspaces` maps workspace name → id; `keys` are Console key records
    (id, name, status, created_at, expires_at, partial_key_hint, scope_workspace_id).
    A key whose workspace is not a named workspace belongs to the Default one.
    """
    now = now or datetime.now(timezone.utc)
    named_ids = set(workspaces.values())
    out: dict[str, dict] = {}
    for slot in slots:
        ws_id = workspaces.get(slot)
        mine = [k for k in keys
                if (k.get("scope_workspace_id") == ws_id if slot != DEFAULT_SLOT
                    else (k.get("scope_workspace_id") and k.get("scope_workspace_id") not in named_ids))]
        have = []
        for k in mine:
            env = next((n for n, v in values.items() if hint_matches(k.get("partial_key_hint"), v)), None)
            if env:
                have.append({**k, "env": env})
        active = sorted((k for k in have if k.get("status") == "active"),
                        key=lambda k: _ts(k.get("created_at")) or now, reverse=True)
        chosen = active[0] if active else None
        issues: list[str] = []
        if slot != DEFAULT_SLOT and ws_id is None:
            issues.append("no-workspace")
        if not chosen:
            issues.append("expired-in-env" if any(k.get("status") == "expired" for k in have)
                          else "no-key-in-env")
        days_left = lifetime = None
        if chosen:
            exp, created = _ts(chosen.get("expires_at")), _ts(chosen.get("created_at"))
            if exp is None:
                issues.append("never-expires")
            else:
                days_left = round((exp - now).total_seconds() / 86400, 1)
                if created:
                    lifetime = round((exp - created).total_seconds() / 86400, 1)
                if lifetime is not None and lifetime > policy["lifetime_days"] + 0.5:
                    issues.append("lifetime-too-long")
                if days_left <= 0:
                    issues.append("expired")
                elif days_left <= policy["renew_before_days"]:
                    issues.append("renew-soon")
        out[slot] = {"slot": slot, "workspace_id": ws_id, "key": chosen,
                     "days_left": days_left, "lifetime_days": lifetime, "issues": issues,
                     "others_active": [k["id"] for k in mine if k.get("status") == "active"
                                       and (not chosen or k["id"] != chosen["id"])]}
    return out


def watch_plan(slots: list[str], ledger: dict, keys: list[dict], values: dict[str, str],
               policy: dict, now: datetime | None = None) -> dict[str, dict]:
    """Per slot: the key the LEDGER says is deployed, judged by what the Admin
    API says about it now. This is the daily check's view — CI never holds the
    new values, so `.env` cannot be the source of truth there."""
    now = now or datetime.now(timezone.utc)
    by_id = {k["id"]: k for k in keys}
    deployed = ledger.get("slots") or {}
    out: dict[str, dict] = {}
    for slot in slots:
        entry = deployed.get(slot) or {}
        k = by_id.get(entry.get("key_id")) if entry else None
        issues: list[str] = []
        days_left = lifetime = None
        if not entry:
            issues.append("not-deployed")
        elif not k or k.get("status") in ("inactive", "archived"):
            issues.append("disabled")
        if k:
            env = next((n for n, v in values.items() if hint_matches(k.get("partial_key_hint"), v)), None)
            k = {**k, "env": env}
            exp, created = _ts(k.get("expires_at")), _ts(k.get("created_at"))
            if k.get("status") == "expired" or (exp and exp <= now):
                issues.append("expired")
            elif exp is None:
                issues.append("never-expires")
            else:
                days_left = round((exp - now).total_seconds() / 86400, 1)
                lifetime = round((exp - created).total_seconds() / 86400, 1) if created else None
                if lifetime is not None and lifetime > policy["lifetime_days"] + 0.5:
                    issues.append("lifetime-too-long")
                if days_left <= policy["renew_before_days"]:
                    issues.append("renew-soon")
        out[slot] = {"slot": slot, "workspace_id": entry.get("workspace_id"), "key": k,
                     "days_left": days_left, "lifetime_days": lifetime, "issues": issues,
                     "others_active": []}
    return out


KEY_ISSUE_TEXT = {
    "not-deployed": "never rotated by `dash keys` — its repos hold whatever was pushed by hand",
    "disabled": "the deployed key was disabled or deleted in the Console — its repos are failing",
    "no-workspace": "no Console workspace has this name",
    "no-key-in-env": "no key for this workspace in .env — create one in the Console and paste it",
    "expired-in-env": "the key in .env has EXPIRED — create a new one in the Console",
    "never-expires": "the key never expires — policy is a {lifetime}-day key (set at creation)",
    "lifetime-too-long": "the key lives longer than the {lifetime}-day policy",
    "expired": "EXPIRED — repos using it are failing now",
    "renew-soon": "expires within {renew} day(s) — create its replacement",
}
BLOCKING = {"no-workspace", "no-key-in-env", "expired-in-env", "expired",
            "never-expires", "lifetime-too-long"}


def _admin_client(kc: dict, values: dict[str, str]):
    try:
        import anthropic
    except ImportError:
        sys.stderr.write("dash keys needs the anthropic SDK: pip install anthropic "
                         "(it is in .github/scripts/dash-gen/requirements.txt)\n")
        sys.exit(2)
    cred = os.environ.get(kc["admin_credential"]) or values.get(kc["admin_credential"])
    if not cred:
        sys.stderr.write(f"{kc['admin_credential']} is not in the environment or .env — the Admin "
                         "API credential (an admin key, or a service-account key not scoped to a "
                         "workspace)\n")
        sys.exit(2)
    mask(cred)
    return anthropic, anthropic.Anthropic(api_key=cred)


def console_inventory(admin) -> tuple[dict[str, str], list[dict]]:
    """(workspace name → id, key records) from the Admin API. No secret is ever
    returned by these endpoints — only names, ids, statuses and hints."""
    workspaces = {w.name: w.id for w in admin.beta.organization.workspaces.list(limit=100)}
    keys = []
    for k in admin.beta.organization.api_keys.list(limit=100):
        scope = getattr(k, "scope", None)
        keys.append({
            "id": k.id, "name": k.name, "status": k.status,
            "created_at": k.created_at, "expires_at": k.expires_at,
            "partial_key_hint": getattr(k, "partial_key_hint", None),
            "scope_workspace_id": getattr(scope, "workspace_id", None) or k.workspace_id,
        })
    return workspaces, keys


def verify_key(anthropic_mod, value: str, spec: dict) -> dict:
    """The cheap test: ONE minimal Messages call, exactly as a repo's CI makes it
    (no workspace header — a key that needs one fails here, not in CI).
    Costs a fraction of a cent; `ok` is what matters, the usage is reported."""
    client = anthropic_mod.Anthropic(api_key=value, max_retries=1, timeout=60)
    try:
        msg = client.messages.create(
            model=spec["model"], max_tokens=int(spec["max_tokens"]),
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": "Reply with the single word OK."}])
        u = msg.usage
        return {"ok": True, "model": msg.model, "input_tokens": u.input_tokens,
                "output_tokens": u.output_tokens, "stop_reason": msg.stop_reason}
    except anthropic_mod.AuthenticationError as exc:
        return {"ok": False, "error": "authentication", "detail": str(exc)[:160]}
    except anthropic_mod.PermissionDeniedError as exc:
        return {"ok": False, "error": "permission", "detail": str(exc)[:160]}
    except anthropic_mod.RateLimitError as exc:
        return {"ok": False, "error": "rate-limit", "detail": str(exc)[:160]}
    except anthropic_mod.BadRequestError as exc:
        return {"ok": False, "error": "bad-request", "detail": str(exc)[:160]}
    except anthropic_mod.APIStatusError as exc:
        return {"ok": False, "error": f"http-{exc.status_code}", "detail": str(exc)[:160]}
    except anthropic_mod.APIConnectionError as exc:
        return {"ok": False, "error": "connection", "detail": str(exc)[:160]}


def _read_key_ledger(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def cmd_keys(args: argparse.Namespace) -> int:
    cfg = load(FLEET)
    registry = load(REGISTRY)
    kc = api_keys_config(cfg)
    if not kc["declared"]:
        sys.stderr.write("no `api_keys:` block in _data/fleet.yml\n")
        return 2
    hub_nwo = cfg.get("hub", {}).get("repo") or "bamr87/bamr87"
    env_file = Path(args.env_file) if args.env_file else DEFAULT_ENV_FILE
    values = read_env_file(env_file) if env_file.is_file() else {}
    # the process environment wins (CI hands secrets in that way)
    values.update({n: v for n, v in os.environ.items() if n.startswith(kc["env_prefix"])})
    candidates = key_candidates(values, kc["env_prefix"])
    for v in candidates.values():
        mask(v)

    targets, errors = key_targets(cfg, registry)
    anthropic_mod, admin = _admin_client(kc, values)
    workspaces, keys = console_inventory(admin)
    slots = [DEFAULT_SLOT] + list(kc["workspaces"])
    policy_fmt = {"lifetime": kc["lifetime_days"], "renew": kc["renew_before_days"]}
    ledger_path = REPO_ROOT / kc["ledger"]
    ledger = _read_key_ledger(ledger_path)
    action = args.action
    plan = (watch_plan(slots, ledger, keys, candidates, kc) if action == "watch"
            else plan_keys(slots, workspaces, keys, candidates, kc))

    print(f"\n\033[1mAnthropic API keys\033[0m [{action}{' APPLY' if action == 'rotate' and args.apply else ''}]"
          f" — policy: {kc['lifetime_days']}-day keys, renew {kc['renew_before_days']} day(s) ahead\n")
    for e in errors:
        print(f"  {MISSING} {e}")
    if errors:
        print("\n  Fix api_keys / ai_auth in _data/fleet.yml — nothing is written while it has errors.\n")

    verified: dict[str, dict] = {}
    rows = []
    for slot in slots:
        p = plan[slot]
        k = p["key"]
        served = [t for t in targets.values() if t["slot"] == slot and not t["skip"]]
        label = (f"{k['name']} ({k['id']})" if k else "—")
        life = (f"{p['days_left']:.1f}d left of {p['lifetime_days']:.0f}d" if p["days_left"] is not None
                else "never expires" if k else "")
        mark = MISSING if set(p["issues"]) & BLOCKING else (UNKNOWN if p["issues"] else OK)
        print(f"  {mark} {slot:15} {label:52} {life:22} → {len(served)} repo(s)")
        for issue in p["issues"]:
            print(f"      \033[2m{KEY_ISSUE_TEXT[issue].format(**policy_fmt)}\033[0m")
        if action in ("verify", "rotate", "watch") and k and k.get("env"):
            res = verify_key(anthropic_mod, candidates[k["env"]], kc["verify"])
            verified[slot] = res
            if res["ok"]:
                print(f"      {OK} cheap test: {res['model']} answered "
                      f"({res['input_tokens']} in / {res['output_tokens']} out tokens)")
            else:
                print(f"      {MISSING} cheap test FAILED: {res['error']} — {res['detail']}")
        rows.append({"slot": slot, **{x: p[x] for x in ("workspace_id", "days_left", "lifetime_days", "issues")},
                     "key_id": k["id"] if k else None, "key_name": k["name"] if k else None,
                     "expires_at": str(k["expires_at"]) if k and k["expires_at"] else None,
                     "repos": sorted(t["nwo"] for t in served),
                     "verified": verified.get(slot, {}).get("ok")})

    skipped = [t for t in targets.values() if t["skip"]]
    if skipped:
        print(f"\n  \033[2mnot sent a key ({len(skipped)}): "
              f"{', '.join(t['name'] for t in skipped)} — {skipped[0]['skip']}\033[0m")

    attention = [r for r in rows if r["issues"] or r["verified"] is False]
    if args.attention_file:
        lines = ["## Anthropic API keys need attention", "",
                 f"Policy: {kc['lifetime_days']}-day keys, replaced {kc['renew_before_days']} day(s) before expiry. "
                 "The Admin API cannot create keys — create each in the Claude Console "
                 "(Settings → API keys → Create key, scoped to the workspace below, expiry "
                 f"{kc['lifetime_days']} days), paste it into the hub's `.env` under any "
                 f"`{kc['env_prefix']}*` name, then run `dash keys rotate --apply` "
                 "(or the console's Auth tab).", "",
                 "| Workspace | Key | Expires | Repos | Needs |", "| --- | --- | --- | --- | --- |"]
        for r in attention:
            needs = "; ".join(KEY_ISSUE_TEXT[i].format(**policy_fmt) for i in r["issues"])
            if r["verified"] is False:
                needs = (needs + "; " if needs else "") + "the cheap test failed"
            lines.append(f"| `{r['slot']}` | {r['key_name'] or '—'} | {r['expires_at'] or '—'} "
                         f"| {len(r['repos'])} | {needs} |")
        Path(args.attention_file).write_text("\n".join(lines) + "\n", encoding="utf-8")
    set_output({"attention": bool(attention),
                "slots_blocked": ",".join(r["slot"] for r in rows if set(r["issues"]) & BLOCKING)})

    if args.json:
        print(json.dumps({"slots": rows, "targets": list(targets.values())}, indent=2, default=str))

    if action != "rotate":
        return 1 if (errors or any(v["ok"] is False for v in verified.values())) else 0

    # ---- rotate ---------------------------------------------------------------
    if errors:
        return 1
    deployable = [s for s in slots if plan[s]["key"] and verified.get(s, {}).get("ok")
                  and not (set(plan[s]["issues"]) & BLOCKING - ({"never-expires", "lifetime-too-long"}
                                                                  if args.allow_long_lived else set()))]
    held = [s for s in slots if s not in deployable]
    if held:
        print(f"\n  \033[2mnot rotated: {', '.join(held)} (see above)\033[0m")
    if args.only:
        deployable = [s for s in deployable if s in args.only]
    # the hub's slot first — the hub's own automation is what would clean up a bad write
    hub_slot = targets.get(hub_nwo, {}).get("slot")
    deployable.sort(key=lambda s: s != hub_slot)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ledger_slots = dict((ledger.get("slots") or {}))
    retired = list(ledger.get("retired") or [])
    failed_total = written_total = pending_total = 0
    for slot in deployable:
        k = plan[slot]["key"]
        value = candidates[k["env"]]
        prev = (ledger_slots.get(slot) or {})
        order = sorted((t for t in targets.values() if t["slot"] == slot and not t["skip"]),
                       key=lambda t: t["nwo"] != hub_nwo)
        if args.repo:
            order = [t for t in order if args.repo in (t["name"], t["nwo"])]
        print(f"\n  \033[1m{slot}\033[0m → {k['name']} ({k['id']}) to {len(order)} repo(s)")
        failed = []
        for t in order:
            same = prev.get("key_id") == k["id"] and t["nwo"] in (prev.get("repos") or [])
            if same and not args.force:
                print(f"    {OK} {t['nwo']:34} already holds this key")
                continue
            if not args.apply:
                pending_total += 1
                print(f"    {EXTRA} {t['nwo']:34} would set {kc['secret']}")
                continue
            proc = subprocess.run(["gh", "secret", "set", kc["secret"], "-R", t["nwo"]],
                                  input=value, capture_output=True, text=True)
            if proc.returncode == 0:
                written_total += 1
                print(f"    {EXTRA} {t['nwo']:34} set {kc['secret']}")
            else:
                err = (proc.stderr or "").strip().splitlines()
                print(f"    {MISSING} {t['nwo']:34} FAILED: {err[0] if err else '?'}")
                failed.append(t["nwo"])
                if t["nwo"] == hub_nwo:
                    print("    \033[31maborting this workspace: the hub refused the key\033[0m")
                    break
        failed_total += len(failed)
        if not args.apply:
            continue
        ledger_slots[slot] = {"key_id": k["id"], "key_name": k["name"], "workspace_id": plan[slot]["workspace_id"],
                              "expires_at": str(k["expires_at"]) if k["expires_at"] else None,
                              "deployed_at": now_iso, "verified_at": now_iso,
                              "repos": sorted(t["nwo"] for t in order if t["nwo"] not in failed),
                              "failed": failed}
        # Retire the key this tool deployed before — only when every repo took
        # the new one, so nothing is left holding a disabled credential.
        old = prev.get("key_id")
        if old and old != k["id"] and not failed and not args.keep_old:
            try:
                admin.beta.organization.api_keys.update(old, status="inactive")
                retired.append({"key_id": old, "slot": slot, "retired_at": now_iso})
                print(f"    {OK} disabled the key it replaced ({old})")
            except anthropic_mod.APIError as exc:
                print(f"    {UNKNOWN} could not disable {old}: {str(exc)[:120]}")
        elif old and old != k["id"] and failed:
            print(f"    {UNKNOWN} kept {old} active — {len(failed)} repo(s) still hold it")

    if args.apply:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        doc = {"schema": "api-keys/v1", "generated_at": now_iso,
               "policy": {"lifetime_days": kc["lifetime_days"], "renew_before_days": kc["renew_before_days"]},
               "slots": ledger_slots, "retired": retired[-50:]}
        ledger_path.write_text(
            "# Generated by `dash keys rotate` — key ids, names and dates only; no key\n"
            "# value is ever recorded (the Admin API never returns one).\n"
            + yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
        print(f"\n  ledger → {kc['ledger']}")
    if args.apply:
        print(f"\n  {written_total} secret write(s) · {failed_total} failed\n")
    else:
        print(f"\n  {pending_total} secret write(s) pending — dry run, add --apply\n")
    return 1 if failed_total else 0


# --------------------------------------------------------------------------- #
# rotation — the weekly credential loop
#
# Three jobs, only two of which can run unattended (see `rotation:` in
# _data/fleet.yml for the full reasoning):
#
#   PROPAGATE  write the canonical value to every fleet repo whose copy is
#              missing or older than the token's `max_age_days`
#   AUDIT      record each repo's secret age from GitHub's `updated_at`
#   RE-MINT    obtain a genuinely new credential — only when the optional
#              OAuth refresh grant is provisioned; otherwise the run reports
#              that a human has to do it and keeps propagating meanwhile
#
# Nothing here ever reads a secret VALUE from GitHub (the API does not expose
# one) or writes one to disk. The only channel a value travels is an
# environment variable in, and `gh secret set`'s stdin out.
# --------------------------------------------------------------------------- #
ROTATION_DEFAULTS = {
    "enabled": True,
    "hub_first": True,
    "only_stale": True,
    "max_repos": 0,
    "max_failures": 5,
    "fail_on_unreachable": False,
    "ledger": "_data/token_rotation.yml",
}
TOKEN_ROTATION_DEFAULTS = {
    "enabled": False,
    "max_age_days": 45,
    "lifetime_days": 365,
    "renew_before_days": 30,
    "value_prefixes": [],
}

# States a repo's copy of a rotating secret can be in. `unreachable` is
# deliberately distinct from `missing`: "I cannot see it" and "it is not there"
# are different findings, and conflating them sends you chasing secrets that are
# already set.
S_OK, S_STALE, S_MISSING, S_UNREACHABLE = "ok", "stale", "missing", "unreachable"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def age_days(ts: str | None) -> int | None:
    dt = parse_ts(ts)
    return None if dt is None else max(0, (utcnow() - dt).days)


def rotation_config(cfg: dict) -> dict:
    return {**ROTATION_DEFAULTS, **(cfg.get("rotation") or {})}


def token_rotation_policy(token: dict) -> dict:
    return {**TOKEN_ROTATION_DEFAULTS, **(token.get("rotation") or {})}


def rotating_tokens(cfg: dict, only: list[str] | None = None) -> list[dict]:
    """Contract entries the rotation loop owns, newest policy merged in."""
    out = []
    for t in cfg.get("tokens") or []:
        if t.get("deprecated") or t.get("managed_by"):
            # managed_by: another command owns this secret's values (e.g. the
            # per-workspace ANTHROPIC_API_KEY → `dash keys`); propagating the
            # hub's one copy would overwrite every repo's workspace key.
            continue
        if only and t["name"] not in only:
            continue
        pol = token_rotation_policy(t)
        if not only and not pol.get("enabled"):
            continue
        out.append({**t, "_rotation": pol})
    return out


# --------------------------------------------------------------------------- #
# GitHub Actions plumbing
# --------------------------------------------------------------------------- #
def mask(value: str) -> None:
    """Register a value with the Actions log scrubber.

    This tool never prints a credential, but a `gh` failure or a traceback from
    somewhere below might. Masking costs one line and removes that whole class
    of accident; outside Actions it is a no-op.
    """
    if value and os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::add-mask::{value}", flush=True)


def set_output(pairs: dict[str, object]) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        for k, v in pairs.items():
            if isinstance(v, bool):
                v = "true" if v else "false"
            fh.write(f"{k}={v}\n")


# --------------------------------------------------------------------------- #
# minting
# --------------------------------------------------------------------------- #
def oauth_refresh(policy: dict, refresh_token: str) -> tuple[dict | None, str]:
    """Exchange an OAuth refresh token for a fresh access token.

    UNOFFICIAL. Anthropic documents no programmatic way to re-mint what
    `claude setup-token` produces; this grant is the one the CLI's own login
    flow uses and it can change without notice. Every caller therefore treats a
    failure as "ask a human", never as a hard error — a fleet that cannot
    re-mint this week is fine, a fleet that halted its propagation because it
    could not is not.

    Returns ({access_token, refresh_token, expires_in, endpoint}, "") or
    (None, reason). The response body is never logged: it carries the
    credential.
    """
    endpoints = policy.get("endpoints") or []
    client_id = policy.get("client_id") or ""
    if not endpoints or not client_id:
        return None, "refresh policy is missing endpoints or client_id"

    payload = json.dumps({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }).encode()

    problems = []
    for url in endpoints:
        req = urllib.request.Request(
            url, data=payload, method="POST",
            headers={"Content-Type": "application/json",
                     "Accept": "application/json",
                     "User-Agent": "bamr87-dash/token-rotation"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            problems.append(f"{url} → HTTP {exc.code}")
            continue
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            problems.append(f"{url} → {type(exc).__name__}")
            continue
        access = body.get("access_token")
        if not access:
            problems.append(f"{url} → 200 but no access_token in response")
            continue
        mask(access)
        new_refresh = body.get("refresh_token")
        if new_refresh:
            mask(new_refresh)
        return {"access_token": access, "refresh_token": new_refresh,
                "expires_in": body.get("expires_in"), "endpoint": url}, ""
    return None, "; ".join(problems) or "no endpoint responded"


def value_looks_right(value: str, prefixes: list[str]) -> bool:
    """Refuse to distribute something that isn't shaped like the credential.

    The fleet has ~41 call sites reading this one secret. A malformed value
    breaks all of them simultaneously and the repo that would have to fix it is
    the hub, whose own agent needs the same credential. Cheap prefix check,
    very expensive failure mode.
    """
    if not value or value.strip() != value:
        return False
    return not prefixes or any(value.startswith(p) for p in prefixes)


# --------------------------------------------------------------------------- #
# planning
# --------------------------------------------------------------------------- #
def rotation_targets(cfg: dict, registry: list, token: dict,
                     repo_filter: str | None = None) -> list[dict]:
    hub_nwo = cfg.get("hub", {}).get("repo") or "bamr87/bamr87"
    repos = fleet_repos(cfg, registry)
    if token.get("scope") != "fleet":
        repos = [r for r in repos if r["nwo"] == hub_nwo]
    elif auth_method_of(cfg, token["name"]):
        resolved, _ = resolve_auth(cfg, registry)
        repos = [r for r in repos
                 if secret_wanted(cfg, resolved, r["nwo"], token["name"], hub_nwo)]
    if repo_filter:
        repos = [r for r in repos if repo_filter in (r["name"], r["nwo"])]
    return repos


def survey(token: dict, repos: list[dict],
           cache: dict[str, dict[str, str] | None],
           hub_nwo: str | None = None) -> list[dict]:
    """Per-repo state of one secret. `cache` is shared so a repo whose secrets
    were already listed for another token is not fetched twice.

    A repo is stale for either of two reasons, and the second one matters more:

      age        its copy is older than `max_age_days` — the propagation
                 heartbeat, which is all age can tell you.
      behind hub its copy was written BEFORE the hub's was. The hub is the
                 master copy, so this says plainly "the hub holds something you
                 do not", whatever the age.

    Without the second rule a human updating the hub's secret would reach only
    the repos that happened to be missing or old: every repo written inside the
    heartbeat window would keep the OLD credential and the fleet would end up
    split across two — the exact outcome `hub_first` exists to prevent. Both
    timestamps come from the same API call, so this costs nothing.
    """
    pol = token["_rotation"]
    max_age = int(pol.get("max_age_days") or 0)

    def meta_for(nwo):
        if nwo not in cache:
            cache[nwo] = repo_secret_meta(nwo)
        return cache[nwo]

    hub_dt = None
    if hub_nwo:
        hub_meta = meta_for(hub_nwo)
        if hub_meta:
            hub_dt = parse_ts(hub_meta.get(token["name"]))

    rows = []
    for r in repos:
        meta = meta_for(r["nwo"])
        if meta is None:
            rows.append({**r, "state": S_UNREACHABLE, "age_days": None,
                         "updated_at": None, "behind_hub": False})
            continue
        if token["name"] not in meta:
            rows.append({**r, "state": S_MISSING, "age_days": None,
                         "updated_at": None, "behind_hub": False})
            continue
        updated = meta[token["name"]]
        age = age_days(updated)
        aged_out = max_age > 0 and age is not None and age >= max_age
        behind_hub = False
        if hub_dt is not None and r["nwo"] != hub_nwo:
            rdt = parse_ts(updated)
            behind_hub = bool(rdt and rdt < hub_dt)
        rows.append({**r, "state": S_STALE if (aged_out or behind_hub) else S_OK,
                     "age_days": age, "updated_at": updated,
                     "behind_hub": behind_hub})
    return rows


def hub_row(rows: list[dict], hub_nwo: str) -> dict | None:
    return next((r for r in rows if r["nwo"] == hub_nwo), None)


def needs_human_mint(rows: list[dict], pol: dict, hub_nwo: str,
                     required: bool = True) -> bool:
    """True when a human has to go mint a credential.

    The hub's `updated_at` is the best available proxy for when the credential
    was minted — nothing else in the system records it, and the secrets API
    offers no expiry field.

    Two conditions reach this answer, and they are not the same question:

      aging    the hub HOLDS a credential and it is nearing the end of its
               one-year life. Worth flagging whatever the contract says, since
               an expired credential breaks every repo holding a copy.
      absent   the hub holds NO credential. Worth flagging only when the
               contract marks the secret required. ANTHROPIC_API_KEY is the
               fallback nobody has provisioned, and its absence is the intended
               state — asking for it every week is how a weekly report gets
               skimmed and then ignored. Same reasoning as the `needs-seed`
               guard in cmd_rotate, which this mirrors.
    """
    lifetime = int(pol.get("lifetime_days") or 0)
    renew_before = int(pol.get("renew_before_days") or 0)
    if lifetime <= 0:
        return False
    row = hub_row(rows, hub_nwo)
    if row is None or row["age_days"] is None:
        return required and row is not None and row["state"] == S_MISSING
    return row["age_days"] >= max(0, lifetime - renew_before)


# --------------------------------------------------------------------------- #
# ledger
# --------------------------------------------------------------------------- #
def write_ledger(path: Path, mode: str, entries: list[dict],
                 variables: dict | None = None) -> None:
    """Values-free record of what the loop saw and did.

    Published like every other generated signal (`_data/` is public site data),
    so it carries names, ages, and outcomes — never a credential, and never
    anything from which one could be reconstructed.
    """
    doc = {
        "generated_at": utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "mode": mode,
        "tokens": entries,
    }
    if variables:
        doc["variables"] = variables
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write("# GENERATED by tools/fleet-config.py (rotate) — refreshed weekly by "
                 "token-rotation.yml.\n")
        fh.write("# Secret NAMES, AGES, and outcomes only; never a credential value.\n")
        fh.write("# Variables are not secret, so their VALUES are recorded — this is the\n")
        fh.write("# only committed record of what the fleet is meant to hold.\n")
        yaml.safe_dump(doc, fh, sort_keys=False, allow_unicode=True, width=100)


def ledger_entry(token: dict, rows: list[dict], source: str, minted: bool,
                 written: list[str], failed: list[str], attention: list[str]) -> dict:
    pol = token["_rotation"]
    ages = [r["age_days"] for r in rows if r["age_days"] is not None]
    by_state = {s: [r["nwo"] for r in rows if r["state"] == s]
                for s in (S_OK, S_STALE, S_MISSING, S_UNREACHABLE)}
    return {
        "name": token["name"],
        "scope": token.get("scope", "fleet"),
        "source": source,
        "minted": minted,
        "max_age_days": pol.get("max_age_days"),
        "lifetime_days": pol.get("lifetime_days"),
        "oldest_age_days": max(ages) if ages else None,
        "attention": attention,
        "counts": {
            "repos": len(rows),
            "ok": len(by_state[S_OK]),
            "stale": len(by_state[S_STALE]),
            "missing": len(by_state[S_MISSING]),
            "unreachable": len(by_state[S_UNREACHABLE]),
            "written": len(written),
            "failed": len(failed),
        },
        "repos": [{
            "nwo": r["nwo"],
            "state": r["state"],
            "age_days": r["age_days"],
            "updated_at": r["updated_at"],
            # true = the hub holds a NEWER copy than this repo, which is a
            # stronger signal than age and the reason a human's hub update
            # reaches repos that are otherwise well inside the heartbeat.
            "behind_hub": r.get("behind_hub", False),
            "action": ("failed" if r["nwo"] in failed
                       else "written" if r["nwo"] in written else "none"),
        } for r in rows],
    }


# --------------------------------------------------------------------------- #
# variables — the half of the contract that can be read back
#
# Secrets are write-only: GitHub never returns a value, so the only way the hub's
# secret can reach a fleet repo is for the hub's own workflow to hand it over
# from `${ secrets.* }`. Variables are different — the API returns the value —
# so the hub's live settings ARE the source of truth here, and the fleet can be
# compared against them exactly rather than by age. That is why this half writes
# on VALUE DIFFERENCE and the secrets half writes on AGE.
# --------------------------------------------------------------------------- #
def resolve_hub_variables(cfg: dict, hub_nwo: str) -> tuple[dict, dict, list]:
    """(values, origin, unreachable) for the canonical variable names.

    `variables:` in _data/fleet.yml declares WHICH names are canonical and
    carries a fallback for each; the hub holds the authoritative value. Same
    split as the token contract — the contract is in version control, the values
    are in the hub — so a value is fixed in one place and lands everywhere.
    """
    canonical = cfg.get("variables") or {}
    live = repo_variables(hub_nwo)
    if live is None:                       # cannot see the hub's variables
        return ({k: str(v) for k, v in canonical.items()},
                {k: "declared" for k in canonical}, [hub_nwo])
    values, origin = {}, {}
    for name, declared in canonical.items():
        if name in live:
            values[name], origin[name] = str(live[name]), "hub"
        else:
            values[name], origin[name] = str(declared), "declared"
    return values, origin, []


def rotate_variables(cfg: dict, registry: list, rot: dict,
                     args: argparse.Namespace) -> tuple[dict, int]:
    """Propagate the hub's variables to the fleet. Returns (ledger entry, rc)."""
    vcfg = {"enabled": True, "source": "hub", "warn_on_fallback": True,
            **(rot.get("variables") or {})}
    hub_nwo = cfg.get("hub", {}).get("repo") or "bamr87/bamr87"
    canonical = cfg.get("variables") or {}
    if not canonical:
        return {}, 0

    values, origin, unreachable_hub = resolve_hub_variables(cfg, hub_nwo)
    print(f"\n\033[1mVariables\033[0m — {len(values)} canonical name(s), "
          f"values from {hub_nwo}")
    if unreachable_hub:
        print(f"  {UNKNOWN} could not read {hub_nwo}'s variables — falling back "
              f"to the values declared in _data/fleet.yml")
    fell_back = [k for k, o in origin.items() if o == "declared"]
    if fell_back and vcfg.get("warn_on_fallback") and not unreachable_hub:
        print(f"  \033[33m{', '.join(fell_back)} not set on {hub_nwo} — using "
              f"the declared fallback; set it on the hub to make it "
              f"authoritative\033[0m")

    repos = fleet_repos(cfg, registry)
    if args.repo:
        repos = [r for r in repos if args.repo in (r["name"], r["nwo"])]
    # The auth order is per REPO and comes from the contract, not the hub's own
    # value — the hub's CLAUDE_AUTH_ORDER is just the hub's order.
    per_repo = auth_variables(cfg, registry)

    rows, written, failed, exit_code = [], [], [], 0
    for r in repos:
        current = repo_variables(r["nwo"])
        if current is None:
            rows.append({"nwo": r["nwo"], "state": S_UNREACHABLE,
                         "differing": None, "action": "none"})
            continue
        # Compare by VALUE. Age is meaningless for something readable: a
        # variable that still matches the hub is correct however old it is.
        want = {**values, **per_repo.get(r["nwo"], {})}
        diffs = {k: v for k, v in want.items() if current.get(k) != v}
        if not diffs:
            rows.append({"nwo": r["nwo"], "state": S_OK,
                         "differing": [], "action": "none"})
            continue
        state = S_MISSING if not any(k in current for k in values) else S_STALE
        if not args.apply:
            print(f"  {EXTRA} {r['nwo']:34} would set {', '.join(sorted(diffs))}")
            written.append(r["nwo"])
            rows.append({"nwo": r["nwo"], "state": state,
                         "differing": sorted(diffs), "action": "written"})
            continue
        wrote_all = True
        for key, value in diffs.items():
            proc = subprocess.run(
                ["gh", "variable", "set", key, "--body", value, "-R", r["nwo"]],
                capture_output=True, text=True)
            if proc.returncode != 0:
                err = (proc.stderr or "").strip().splitlines()
                print(f"  {MISSING} {r['nwo']:34} FAILED {key}: "
                      f"{err[0] if err else '(no error output)'}")
                wrote_all = False
        if wrote_all:
            print(f"  {EXTRA} {r['nwo']:34} set {', '.join(sorted(diffs))}")
            written.append(r["nwo"])
            rows.append({"nwo": r["nwo"], "state": state,
                         "differing": sorted(diffs), "action": "written"})
        else:
            failed.append(r["nwo"])
            exit_code = 1
            rows.append({"nwo": r["nwo"], "state": state,
                         "differing": sorted(diffs), "action": "failed"})

    by = lambda st: sum(1 for r in rows if r["state"] == st)  # noqa: E731
    entry = {
        "source": f"hub:{hub_nwo}",
        "canonical": sorted(values),
        "from_hub": sorted(k for k, o in origin.items() if o == "hub"),
        "from_declared_fallback": sorted(fell_back),
        # Variables are not secret — recording the values is the point, since
        # this is the only committed record of what the fleet is meant to hold.
        "values": values,
        "auth_order": {nwo: v for nwo, d in per_repo.items() for v in d.values()},
        "counts": {"repos": len(rows), "ok": by(S_OK), "stale": by(S_STALE),
                   "missing": by(S_MISSING), "unreachable": by(S_UNREACHABLE),
                   "written": len(written), "failed": len(failed)},
        "repos": rows,
    }
    print(f"  {len(written)} repo(s) {'written' if args.apply else 'pending'} · "
          f"{by(S_OK)} already match · {by(S_UNREACHABLE)} unreachable · "
          f"{len(failed)} failed")
    return entry, exit_code


# --------------------------------------------------------------------------- #
# rotation-plan
# --------------------------------------------------------------------------- #
def cmd_rotation_plan(args: argparse.Namespace) -> int:
    cfg = load(FLEET)
    registry = load(REGISTRY)
    hub_nwo = cfg.get("hub", {}).get("repo") or "bamr87/bamr87"
    tokens = rotating_tokens(cfg, args.only)
    if not tokens:
        sys.stderr.write("no token in the contract has rotation enabled\n")
        return 1

    cache: dict[str, dict[str, str] | None] = {}
    entries = []
    for t in tokens:
        repos = rotation_targets(cfg, registry, t, args.repo)
        rows = survey(t, repos, cache, hub_nwo)
        attention = []
        if needs_human_mint(rows, t["_rotation"], hub_nwo,
                            bool(t.get("required"))):
            attention.append("needs-mint")
        if any(r["state"] in (S_STALE, S_MISSING) for r in rows):
            attention.append("needs-propagate")
        entries.append(ledger_entry(t, rows, "n/a", False, [], [], attention))

    if args.json:
        print(json.dumps({"mode": "plan", "tokens": entries}, indent=2))
    else:
        render_rotation(entries)
    if args.ledger:
        write_ledger(REPO_ROOT / args.ledger, "plan", entries)
        print(f"\n  ledger → {args.ledger}")
    return 0


def render_rotation(entries: list[dict]) -> None:
    for e in entries:
        c = e["counts"]
        print(f"\n\033[1m{e['name']}\033[0m  ({e['scope']}-scoped, "
              f"max age {e['max_age_days']}d)")
        print(f"  {c['repos']} repo(s): {OK} {c['ok']} current · "
              f"⏳ {c['stale']} stale · {MISSING} {c['missing']} missing · "
              f"{UNKNOWN} {c['unreachable']} unreachable")
        if e["oldest_age_days"] is not None:
            print(f"  oldest copy: {e['oldest_age_days']}d")
        for r in e["repos"]:
            if r["state"] == S_OK and r["action"] == "none":
                continue
            age = f"{r['age_days']}d" if r["age_days"] is not None else "—"
            print(f"    {r['nwo']:34} {r['state']:12} {age:>6}  {r['action']}")
        if e["attention"]:
            print(f"  \033[33mattention: {', '.join(e['attention'])}\033[0m")


# --------------------------------------------------------------------------- #
# rotate
# --------------------------------------------------------------------------- #
def cmd_rotate(args: argparse.Namespace) -> int:
    cfg = load(FLEET)
    registry = load(REGISTRY)
    rot = rotation_config(cfg)
    hub_nwo = cfg.get("hub", {}).get("repo") or "bamr87/bamr87"

    if not rot.get("enabled") and not args.force:
        print("rotation is disabled in _data/fleet.yml (rotation.enabled: false)")
        return 0

    tokens = rotating_tokens(cfg, args.only)
    if not tokens:
        sys.stderr.write("no token in the contract has rotation enabled\n")
        return 1

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"\n\033[1mRotate fleet credentials\033[0m [{mode}]")

    cache: dict[str, dict[str, str] | None] = {}
    entries, exit_code = [], 0
    minted_any = attention_any = False

    for t in tokens:
        name = t["name"]
        pol = t["_rotation"]
        repos = rotation_targets(cfg, registry, t, args.repo)
        rows = survey(t, repos, cache, hub_nwo)
        print(f"\n\033[1m{name}\033[0m — {len(rows)} target repo(s)")

        # --- where does this run's value come from? -------------------------
        value, source, minted, note = resolve_value(t, pol, args.source)
        if note:
            print(f"  \033[2m{note}\033[0m")
        minted_any = minted_any or minted

        attention = []
        if needs_human_mint(rows, pol, hub_nwo,
                            bool(t.get("required"))) and not minted:
            attention.append("needs-mint")
        # Only a REQUIRED secret missing its value is worth anyone's attention.
        # ANTHROPIC_API_KEY is the fallback nobody has provisioned; flagging its
        # absence every week would train the reader to ignore the report.
        if (value is None and t.get("required")
                and any(r["state"] in (S_STALE, S_MISSING) for r in rows)):
            attention.append("needs-seed")
        # A repo we cannot see is not a repo we know is fine. Off by default —
        # this fleet legitimately contains repos the control-plane token has no
        # admin on — but a run that silently skipped a third of the fleet should
        # be able to say so loudly when an operator wants that.
        unreachable = [r["nwo"] for r in rows if r["state"] == S_UNREACHABLE]
        if unreachable and rot.get("fail_on_unreachable"):
            attention.append("unreachable")
            exit_code = 1

        if value is None:
            print(f"  {UNKNOWN} nothing to write — no value available this run")
            entries.append(ledger_entry(t, rows, source, minted, [], [], attention))
            attention_any = attention_any or bool(attention)
            continue

        if not value_looks_right(value, pol.get("value_prefixes") or []):
            # Fail this token, not the whole run: another token in the contract
            # may still be rotatable, and half a rotation beats none.
            print(f"  {MISSING} refusing to distribute {name}: value does not match "
                  f"the contract's expected shape "
                  f"({', '.join(pol.get('value_prefixes') or []) or 'non-empty'})")
            attention.append("bad-value")
            entries.append(ledger_entry(t, rows, source, minted, [], [], attention))
            attention_any = True
            exit_code = 1
            continue

        # --- who gets written? ---------------------------------------------
        # A freshly MINTED credential must reach EVERY reachable repo: the old
        # one is being replaced, and a fleet split across two credentials is
        # worse than one that was never rotated. A merely re-seeded value only
        # needs to fill the gaps.
        if minted or args.force or not rot.get("only_stale", True):
            targets = [r for r in rows if r["state"] != S_UNREACHABLE]
            why = "fresh credential — writing every reachable repo"
        else:
            targets = [r for r in rows if r["state"] in (S_STALE, S_MISSING)]
            why = "propagating to missing / stale copies only"
        cap = int(rot.get("max_repos") or 0)
        if cap > 0 and len(targets) > cap:
            print(f"  \033[2mcapping {len(targets)} target(s) at rotation.max_repos={cap}"
                  f" — {len(targets) - cap} deferred to the next run\033[0m")
            targets = targets[:cap]
        print(f"  {why}: {len(targets)} repo(s)")

        # Hub first, always. If the hub cannot take the new credential, the
        # fleet must not either: the hub is the repo whose own automation would
        # have to clean up a half-applied rotation.
        if rot.get("hub_first", True):
            targets.sort(key=lambda r: r["nwo"] != hub_nwo)

        written, failed = [], []
        for r in targets:
            if not args.apply:
                verb = "rotate" if r["state"] in (S_OK, S_STALE) else "set"
                print(f"  {EXTRA} {r['nwo']:34} would {verb} {name}")
                written.append(r["nwo"])
                continue
            proc = subprocess.run(["gh", "secret", "set", name, "-R", r["nwo"]],
                                  input=value, capture_output=True, text=True)
            if proc.returncode == 0:
                print(f"  {EXTRA} {r['nwo']:34} wrote {name}")
                written.append(r["nwo"])
                continue
            err = (proc.stderr or "").strip().splitlines()
            print(f"  {MISSING} {r['nwo']:34} FAILED {name}: "
                  f"{err[0] if err else '(no error output)'}")
            failed.append(r["nwo"])
            if r["nwo"] == hub_nwo and rot.get("hub_first", True):
                print("  \033[31maborting: the hub write failed, so the fleet is left "
                      "on the credential it already has\033[0m")
                exit_code = 1
                break
            if len(failed) >= int(rot.get("max_failures") or 5):
                print(f"  \033[31maborting: {len(failed)} failures "
                      f"(rotation.max_failures)\033[0m")
                exit_code = 1
                break

        if failed:
            exit_code = 1
            attention.append("write-failures")

        # --- the refresh token rotates itself -------------------------------
        # The grant returns a NEW refresh token and invalidates the one we sent.
        # Failing to store it would strand the loop: next week's run would
        # present a dead credential and silently fall back to propagate-only.
        if minted and t.get("_new_refresh"):
            store = (pol.get("refresh") or {}).get("secret")
            if store:
                ok = store_refresh(store, t["_new_refresh"], hub_nwo, args.apply)
                if not ok:
                    attention.append("refresh-store-failed")
                    exit_code = 1

        entries.append(ledger_entry(t, rows, source, minted, written, failed, attention))
        attention_any = attention_any or bool(attention)

    # --- variables ------------------------------------------------------
    # Same weekly pass, because they are the same question — "does the fleet
    # match the hub?" — asked of the half of the contract that can be read back.
    var_entry = {}
    vcfg = rot.get("variables") or {}
    if vcfg.get("enabled", True) and not args.no_variables and not args.only:
        var_entry, var_rc = rotate_variables(cfg, registry, rot, args)
        if var_rc:
            exit_code = 1

    ledger = args.ledger or rot.get("ledger")
    if ledger:
        write_ledger(REPO_ROOT / ledger, "apply" if args.apply else "dry-run",
                     entries, var_entry)
        print(f"\n  ledger → {ledger}")

    if args.json:
        print(json.dumps({"mode": "apply" if args.apply else "dry-run",
                          "tokens": entries}, indent=2))

    total_written = sum(e["counts"]["written"] for e in entries)
    total_failed = sum(e["counts"]["failed"] for e in entries)
    print(f"\n  {total_written} write(s) {'applied' if args.apply else 'pending'} · "
          f"{total_failed} failed · attention: "
          f"{'yes' if attention_any else 'no'}")
    if not args.apply and total_written:
        print("  Re-run with --apply to write.\n")

    set_output({
        "variables_written": (var_entry.get("counts", {}) or {}).get("written", 0),
        "variables_failed": (var_entry.get("counts", {}) or {}).get("failed", 0),
        "written": total_written,
        "failed": total_failed,
        "minted": minted_any,
        "attention": attention_any,
        "reasons": ",".join(sorted({a for e in entries for a in e["attention"]})),
    })
    if args.attention_file:
        Path(args.attention_file).write_text(attention_report(entries), encoding="utf-8")
    return exit_code


def resolve_value(token: dict, pol: dict, source: str) -> tuple[str | None, str, bool, str]:
    """Where this run's credential comes from: (value, source, minted, note).

    `refresh` mints a genuinely new credential; `env` re-seeds the one an
    operator exported (a `claude setup-token` mint, or the hub's current copy
    handed in by the workflow). Anything that fails falls THROUGH to the next
    source rather than aborting — propagate-and-alert is a useful run, and it
    is the only run available when the refresh grant is not provisioned.
    """
    name = token["name"]
    refresh_pol = pol.get("refresh") or {}
    refresh_secret = refresh_pol.get("secret")
    want_refresh = source in ("auto", "refresh") and refresh_secret

    if want_refresh:
        refresh_value = os.environ.get(refresh_secret, "").strip()
        if refresh_value:
            mask(refresh_value)
            result, why = oauth_refresh(refresh_pol, refresh_value)
            if result:
                token["_new_refresh"] = result.get("refresh_token") or ""
                exp = result.get("expires_in")
                return (result["access_token"], "refresh", True,
                        f"minted a fresh credential via {result['endpoint']}"
                        + (f" (expires in {exp}s)" if exp else ""))
            if source == "refresh":
                return None, "refresh", False, f"refresh grant failed: {why}"
            print(f"  \033[2mrefresh grant unavailable ({why}) — "
                  f"falling back to the seeded value\033[0m")
        elif source == "refresh":
            return None, "refresh", False, (
                f"{refresh_secret} is not in the environment — nothing to refresh with")

    if source in ("auto", "env"):
        seeded = os.environ.get(name, "").strip()
        if seeded:
            mask(seeded)
            return seeded, "seed", False, "using the seeded value from the environment"
        return None, "none", False, (
            f"no value available: export {name}=… to propagate, or provision "
            f"{refresh_secret or 'a refresh credential'} to mint one")

    return None, "none", False, "source 'none' — auditing only"


def store_refresh(secret: str, value: str, hub_nwo: str, apply: bool) -> bool:
    if not apply:
        print(f"  {EXTRA} {hub_nwo:34} would store the new {secret}")
        return True
    proc = subprocess.run(["gh", "secret", "set", secret, "-R", hub_nwo],
                          input=value, capture_output=True, text=True)
    if proc.returncode == 0:
        print(f"  {EXTRA} {hub_nwo:34} stored the new {secret}")
        return True
    err = (proc.stderr or "").strip().splitlines()
    print(f"  {MISSING} {hub_nwo:34} FAILED to store {secret}: "
          f"{err[0] if err else '(no error output)'} — next week's run will fall back "
          f"to propagate-only")
    return False


REASON_TEXT = {
    "needs-mint": ("A human has to mint a new credential",
                   "The stored credential is approaching the end of its one-year life and "
                   "this fleet has no unattended way to re-mint it. Run `claude setup-token` "
                   "and re-seed it (see docs/TOKEN-ROTATION.md)."),
    "needs-seed": ("No value was available to propagate",
                   "Repos are missing or holding a stale copy, but neither a refresh "
                   "credential nor a seeded value was present this run."),
    "bad-value":  ("The candidate value was refused",
                   "It did not match the shape the token contract declares, so nothing was "
                   "written. This is the guard working, not a bug."),
    "write-failures": ("Some repos rejected the write",
                       "Writing an Actions secret needs admin on the repo — check that "
                       "FLEET_TOKEN still carries secrets:write across the fleet."),
    "unreachable":    ("Some repos could not be read at all",
                       "Listing a repo's secrets needs admin on it. These were neither "
                       "confirmed current nor written — `rotation.fail_on_unreachable` is on, "
                       "so the run reports them as a failure rather than skipping quietly."),
    "refresh-store-failed": ("The new refresh token could not be stored",
                             "The grant consumed the old refresh token, so the loop will "
                             "fall back to propagate-only until it is re-seeded."),
}


def attention_report(entries: list[dict]) -> str:
    """Markdown the workflow turns into a tracking issue. Names only."""
    L = ["## Fleet credential rotation needs attention", ""]
    for e in entries:
        if not e["attention"]:
            continue
        c = e["counts"]
        L.append(f"### `{e['name']}`")
        L.append("")
        L.append(f"- Scope: `{e['scope']}` · oldest copy: "
                 f"{e['oldest_age_days'] if e['oldest_age_days'] is not None else '—'}d "
                 f"(rotate at {e['max_age_days']}d)")
        L.append(f"- Repos: {c['ok']} current, {c['stale']} stale, {c['missing']} missing, "
                 f"{c['unreachable']} unreachable, {c['failed']} write failures")
        L.append("")
        for reason in e["attention"]:
            title, detail = REASON_TEXT.get(reason, (reason, ""))
            L.append(f"**{title}** — {detail}")
            L.append("")
        interesting = (S_STALE, S_MISSING) + ((S_UNREACHABLE,)
                                              if "unreachable" in e["attention"] else ())
        offenders = [r for r in e["repos"]
                     if r["state"] in interesting or r["action"] == "failed"]
        if offenders:
            L.append("| Repo | State | Age | Action |")
            L.append("| --- | --- | --- | --- |")
            for r in offenders[:30]:
                age = f"{r['age_days']}d" if r["age_days"] is not None else "—"
                L.append(f"| `{r['nwo']}` | {r['state']} | {age} | {r['action']} |")
            if len(offenders) > 30:
                L.append(f"| … | {len(offenders) - 30} more | | |")
            L.append("")
    L.append("---")
    L.append("")
    L.append("Rotation runs weekly (`.github/workflows/token-rotation.yml`). "
             "Re-run it after fixing, or `dash secrets rotate --apply` locally. "
             "Full doc: [`docs/TOKEN-ROTATION.md`](../blob/main/docs/TOKEN-ROTATION.md).")
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fleet-config", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_show = sub.add_parser("show", help="print the resolved fleet config")
    p_show.add_argument("key", nargs="?", help="dotted key, e.g. toolchain.node")
    p_show.add_argument("--json", action="store_true")
    p_show.set_defaults(func=cmd_show)

    p_audit = sub.add_parser("audit", help="per-repo secret + variable matrix")
    p_audit.add_argument("--repo", metavar="NAME", help="audit one repo")
    p_audit.add_argument("--json", action="store_true")
    p_audit.add_argument("--gate", action="store_true",
                         help="exit non-zero when a required fleet secret is missing")
    p_audit.set_defaults(func=cmd_audit)

    p_sync = sub.add_parser("sync", help="project canonical variables onto the fleet")
    p_sync.add_argument("--repo", metavar="NAME", help="sync one repo")
    p_sync.add_argument("--apply", action="store_true", help="write (default: dry-run)")
    p_sync.set_defaults(func=cmd_sync)

    p_ss = sub.add_parser("sync-secrets",
                          help="project the token contract onto the fleet "
                               "(values from env, never from files)")
    p_ss.add_argument("--repo", metavar="NAME", help="sync one repo")
    p_ss.add_argument("--only", metavar="SECRET", action="append",
                      help="limit to this contract secret (repeatable)")
    p_ss.add_argument("--rotate", action="store_true",
                      help="overwrite secrets that are already set")
    p_ss.add_argument("--apply", action="store_true", help="write (default: dry-run)")
    p_ss.set_defaults(func=cmd_sync_secrets)

    p_keys = sub.add_parser("keys", help="Anthropic Console API keys per workspace (api_keys:) — "
                                         "status, cheap verification, assisted rotation")
    p_keys.add_argument("action", nargs="?", choices=["status", "verify", "rotate", "watch"], default="status",
                        help="status/verify/rotate judge the keys in .env; watch judges the DEPLOYED keys "
                             "(the ledger) — the daily check")
    p_keys.add_argument("--env-file", metavar="PATH", help="dotenv file holding the new keys (default: .env)")
    p_keys.add_argument("--only", metavar="WORKSPACE", action="append", help="rotate: limit to this workspace slot")
    p_keys.add_argument("--repo", metavar="NAME", help="rotate: limit the writes to one repo")
    p_keys.add_argument("--force", action="store_true", help="rotate: rewrite repos the ledger says already hold the key")
    p_keys.add_argument("--keep-old", action="store_true", help="rotate: do not disable the key being replaced")
    p_keys.add_argument("--allow-long-lived", action="store_true",
                        help="rotate: deploy a key that outlives the lifetime policy")
    p_keys.add_argument("--attention-file", metavar="PATH", help="write the markdown attention report")
    p_keys.add_argument("--json", action="store_true")
    p_keys.add_argument("--apply", action="store_true", help="rotate: write (default: dry-run)")
    p_keys.set_defaults(func=cmd_keys)

    p_auth = sub.add_parser("auth", help="per-repo AI auth order (ai_auth:) — resolve, "
                                         "inspect, and project CLAUDE_AUTH_ORDER")
    p_auth.add_argument("action", nargs="?", choices=["show", "sync"], default="show")
    p_auth.add_argument("--repo", metavar="NAME", help="one repo")
    p_auth.add_argument("--offline", action="store_true",
                        help="show the resolution only — no GitHub calls")
    p_auth.add_argument("--json", action="store_true")
    p_auth.add_argument("--apply", action="store_true", help="sync: write (default: dry-run)")
    p_auth.set_defaults(func=cmd_auth)

    p_push = sub.add_parser("push",
                            help="the operator's .env → the hub → the fleet, hub-first "
                                 "(the file is parsed, never exported)")
    p_push.add_argument("--env-file", metavar="PATH",
                        help=f"dotenv file to read (default: {DEFAULT_ENV_FILE.name} at the hub root)")
    p_push.add_argument("--only", metavar="SECRET", action="append",
                        help="limit to this contract secret (repeatable)")
    p_push.add_argument("--repo", metavar="NAME", help="limit the fan-out to one repo (the hub is always written)")
    p_push.add_argument("--hub-only", action="store_true",
                        help="write the hub only; the weekly rotation fans it out")
    p_push.add_argument("--apply", action="store_true", help="write (default: dry-run)")
    p_push.set_defaults(func=cmd_push)

    p_rot = sub.add_parser("rotate",
                           help="the weekly credential loop: audit ages, mint where "
                                "possible, propagate hub-first")
    p_rot.add_argument("--only", metavar="SECRET", action="append",
                       help="limit to this contract secret (repeatable); also overrides "
                            "that secret's rotation.enabled")
    p_rot.add_argument("--repo", metavar="NAME", help="limit to one repo")
    p_rot.add_argument("--source", choices=["auto", "refresh", "env", "none"],
                       default="auto",
                       help="where the value comes from: 'refresh' mints via the OAuth "
                            "grant, 'env' re-seeds the exported value, 'auto' (default) "
                            "tries refresh then falls back to env, 'none' audits only")
    p_rot.add_argument("--force", action="store_true",
                       help="write every reachable repo, not just missing/stale ones "
                            "(also runs when rotation.enabled is false)")
    p_rot.add_argument("--ledger", metavar="PATH",
                       help="override rotation.ledger (values-free record)")
    p_rot.add_argument("--attention-file", metavar="PATH",
                       help="write the markdown attention report the workflow turns "
                            "into a tracking issue")
    p_rot.add_argument("--no-variables", action="store_true",
                       help="skip the repository-variable pass (secrets only)")
    p_rot.add_argument("--json", action="store_true")
    p_rot.add_argument("--apply", action="store_true", help="write (default: dry-run)")
    p_rot.set_defaults(func=cmd_rotate)

    p_plan = sub.add_parser("rotation-plan",
                            help="read-only: per-repo secret ages and what is stale")
    p_plan.add_argument("--only", metavar="SECRET", action="append")
    p_plan.add_argument("--repo", metavar="NAME")
    p_plan.add_argument("--ledger", metavar="PATH")
    p_plan.add_argument("--no-variables", action="store_true",
                        help="accepted for symmetry with `rotate`; the plan is "
                             "read-only either way")
    p_plan.add_argument("--json", action="store_true")
    p_plan.set_defaults(func=cmd_rotation_plan)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
