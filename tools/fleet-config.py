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
  sync-secrets
          Project the declared token contract onto the fleet. Values are read
          ONLY from the environment (export the secret under its own name);
          they are never stored in, or read from, any file. Dry-run by
          default; `--apply` writes; already-set secrets are left alone unless
          `--rotate`.
  rotate  The weekly credential loop: audit every fleet repo's secret AGE from
          GitHub's own `updated_at`, mint a fresh value where the contract says
          one can be minted unattended, and propagate it hub-first. Dry-run by
          default; `--apply` writes. Values are never read from, or written to,
          any file — see `rotation:` in _data/fleet.yml.
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
                line += f" {cell(r['secrets'], c):>4}"
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

    print(f"\n  {OK} set   {MISSING} missing   ≠ differs from canonical   "
          f"{UNKNOWN} unreachable\n")

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

    for r in repos:
        current = repo_variables(r["nwo"])
        if current is None:
            print(f"  {UNKNOWN} {r['nwo']:30} unreachable (needs admin) — skipped")
            skipped += 1
            continue
        diffs = {k: v for k, v in canonical.items()
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
    tokens = [t for t in (cfg.get("tokens") or []) if not t.get("deprecated")]
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

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"\n\033[1mSync token contract\033[0m [{mode}]\n")
    changed = skipped = failed = 0

    for t in tokens:
        name = t["name"]
        value = os.environ.get(name)
        targets = repos if t.get("scope") == "fleet" else \
            [r for r in repos if r["nwo"] == hub_nwo]
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
        if t.get("deprecated"):
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
    if repo_filter:
        repos = [r for r in repos if repo_filter in (r["name"], r["nwo"])]
    return repos


def survey(token: dict, repos: list[dict],
           cache: dict[str, dict[str, str] | None]) -> list[dict]:
    """Per-repo state of one secret. `cache` is shared so a repo whose secrets
    were already listed for another token is not fetched twice."""
    pol = token["_rotation"]
    max_age = int(pol.get("max_age_days") or 0)
    rows = []
    for r in repos:
        if r["nwo"] not in cache:
            cache[r["nwo"]] = repo_secret_meta(r["nwo"])
        meta = cache[r["nwo"]]
        if meta is None:
            rows.append({**r, "state": S_UNREACHABLE, "age_days": None, "updated_at": None})
            continue
        if token["name"] not in meta:
            rows.append({**r, "state": S_MISSING, "age_days": None, "updated_at": None})
            continue
        updated = meta[token["name"]]
        age = age_days(updated)
        stale = max_age > 0 and age is not None and age >= max_age
        rows.append({**r, "state": S_STALE if stale else S_OK,
                     "age_days": age, "updated_at": updated})
    return rows


def hub_row(rows: list[dict], hub_nwo: str) -> dict | None:
    return next((r for r in rows if r["nwo"] == hub_nwo), None)


def needs_human_mint(rows: list[dict], pol: dict, hub_nwo: str) -> bool:
    """True when the credential itself is approaching the end of its life.

    The hub's `updated_at` is the best available proxy for when the credential
    was minted — nothing else in the system records it, and the secrets API
    offers no expiry field.
    """
    lifetime = int(pol.get("lifetime_days") or 0)
    renew_before = int(pol.get("renew_before_days") or 0)
    if lifetime <= 0:
        return False
    row = hub_row(rows, hub_nwo)
    if row is None or row["age_days"] is None:
        return row is not None and row["state"] == S_MISSING
    return row["age_days"] >= max(0, lifetime - renew_before)


# --------------------------------------------------------------------------- #
# ledger
# --------------------------------------------------------------------------- #
def write_ledger(path: Path, mode: str, entries: list[dict]) -> None:
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
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write("# GENERATED by tools/fleet-config.py (rotate) — refreshed weekly by "
                 "token-rotation.yml.\n")
        fh.write("# Secret NAMES, AGES, and outcomes only; never a credential value.\n")
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
            "action": ("failed" if r["nwo"] in failed
                       else "written" if r["nwo"] in written else "none"),
        } for r in rows],
    }


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
        rows = survey(t, repos, cache)
        attention = []
        if needs_human_mint(rows, t["_rotation"], hub_nwo):
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
        rows = survey(t, repos, cache)
        print(f"\n\033[1m{name}\033[0m — {len(rows)} target repo(s)")

        # --- where does this run's value come from? -------------------------
        value, source, minted, note = resolve_value(t, pol, args.source)
        if note:
            print(f"  \033[2m{note}\033[0m")
        minted_any = minted_any or minted

        attention = []
        if needs_human_mint(rows, pol, hub_nwo) and not minted:
            attention.append("needs-mint")
        if value is None and any(r["state"] in (S_STALE, S_MISSING) for r in rows):
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

    ledger = args.ledger or rot.get("ledger")
    if ledger:
        write_ledger(REPO_ROOT / ledger, "apply" if args.apply else "dry-run", entries)
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
    p_rot.add_argument("--json", action="store_true")
    p_rot.add_argument("--apply", action="store_true", help="write (default: dry-run)")
    p_rot.set_defaults(func=cmd_rotate)

    p_plan = sub.add_parser("rotation-plan",
                            help="read-only: per-repo secret ages and what is stale")
    p_plan.add_argument("--only", metavar="SECRET", action="append")
    p_plan.add_argument("--repo", metavar="NAME")
    p_plan.add_argument("--ledger", metavar="PATH")
    p_plan.add_argument("--json", action="store_true")
    p_plan.set_defaults(func=cmd_rotation_plan)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
