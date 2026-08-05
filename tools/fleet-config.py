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
import subprocess
import sys
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


def repo_secret_names(nwo: str) -> set[str] | None:
    data = gh_json(["api", f"repos/{nwo}/actions/secrets", "--jq", "[.secrets[].name]"])
    return set(data) if isinstance(data, list) else None


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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
