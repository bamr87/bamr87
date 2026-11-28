#!/usr/bin/env python3
"""Fleet clouds: WHERE each repo's deliverable runs (ADR 0018, docs/CLOUDS.md).

A provider is a platform the fleet deploys to and does not operate. The model
is `_data/fleet.yml` `clouds:`: for each provider, how a deployment to it is
recognised in a repo's own files, how the fleet is expected to sign in, and
whether the hub may read it. Which repo deploys where is never declared: this
module reads it from each owned repo's checkout,

  workflows   `.github/workflows/*.yml`: a step that uses a provider's action or
              runs its command line is a deployment, and the sign-in step beside
              it says whether the job federates or holds a stored credential
  addresses   a registry `live_url` on a provider's own host, or a marker file
              at the repo root, when no workflow deploys it (a branch build)
  iac         the files that declare a provider's resources as code

so the map cannot disagree with what the repos do. It is the one implementation
the CLI uses now and the console, the MCP server and the published site read
next:

  load_model()    the `clouds:` block, the framework's laid under the
                  instance's (ADR 0011), checked for shape
  scan_repo()     one checkout -> its deployments and infrastructure files
  status_doc()    THE document (`fleet-clouds/v1`): every provider with its
                  switch and its counts, every deployment with its evidence and
                  how it signs in, the infrastructure files, the findings, and
                  the repos that were and were not read

The code names no provider. Every vendor fact (an action, a command, a host, a
file name) is data in `clouds:`, so a new provider or service is an entry and
no code; tools/test_fleetcore_clouds.py holds that.

Read-only (constitution § 10.6): it reads files in checkouts that are already
on disk. No network, no subprocess, no credential, and nothing is written. What
it reports is what a repo CAN deploy, from its files; whether a deployment ran,
answers, or costs anything is a later phase's read.

    python3 -m fleetcore.clouds [status|map|check|json] [--instance DIR]
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from . import identity, yamlio

HUB = Path(__file__).resolve().parents[2]
SCHEMA = "fleet-clouds/v1"

IDENTITIES = ("oidc", "platform", "secret")
KINDS = ("static", "container", "function", "stack", "cluster")
# How a deployment that could not be classified is shown. Never a guess.
UNKNOWN = "unknown"
# An environment name the workflow works out when it runs.
COMPUTED = "(computed)"
# Worst first: one job with a stored credential decides how the deployment reads.
IDENTITY_RANK = ("secret", UNKNOWN, "oidc", "platform")
# The CI system's own token is the platform's, not a stored credential.
PLATFORM_OWN = {"GITHUB_TOKEN"}
# The two fields a deployment's named values land in. What is kept is the NAME a
# workflow file writes (`secrets.X` keeps `X`), never a value: a checkout holds
# none, and the pattern below admits only an identifier. The fields are called
# what they hold, credential and variable NAMES. A field called `secrets` reads as
# secret values, to a person and to CodeQL's sensitive-data heuristic
# (py/clear-text-logging-sensitive-data), which follows it into every print.
STORED, VARIABLES = "credential_names", "variable_names"
WORKFLOW_DIR = Path(".github") / "workflows"
MAX_WORKFLOW_BYTES = 512 * 1024
MAX_IAC_BYTES = 256 * 1024
SCAN_DEFAULTS = {"skip_dirs": [], "max_depth": 6, "max_files": 400}

_NAME = re.compile(r"\b(secrets|vars)\.([A-Za-z_][A-Za-z0-9_]*)")
_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class ModelError(ValueError):
    """`clouds:` is not the shape this module reads; the message lists every problem."""


# --------------------------------------------------------------------------- #
# The model
# --------------------------------------------------------------------------- #
def _load(path: Path):
    try:
        return yamlio.load(path)
    except (OSError, yaml.YAMLError):
        return None


def _strs(value) -> list[str]:
    if value is None:
        return []
    return [str(v) for v in (value if isinstance(value, list) else [value]) if str(v).strip()]


def _merge(base, over):
    """`over` laid over `base`: mappings merge key by key, anything else is replaced."""
    if isinstance(base, dict) and isinstance(over, dict):
        out = dict(base)
        for key, value in over.items():
            out[key] = _merge(base.get(key), value) if key in base else value
        return out
    return base if over is None else over


def model_problems(block) -> list[str]:
    """Every reason `clouds:` cannot be read, as sentences. Empty means it can."""
    if not isinstance(block, dict):
        return ["`clouds:` must be a mapping"]
    providers = block.get("providers")
    if not isinstance(providers, dict) or not providers:
        return ["`clouds.providers` must be a mapping with at least one provider"]
    out: list[str] = []
    for pid, prov in providers.items():
        where = f"clouds.providers.{pid}"
        if not _ID.match(str(pid)):
            out.append(f"{where}: an id is lowercase letters, digits and hyphens")
        if not isinstance(prov, dict):
            out.append(f"{where} must be a mapping")
            continue
        if not isinstance(prov.get("enabled"), bool):
            out.append(f"{where}.enabled must be true or false (the read switch)")
        if prov.get("identity") not in IDENTITIES:
            out.append(f"{where}.identity must be one of {', '.join(IDENTITIES)}")
        for i, login in enumerate(prov.get("login") or []):
            if not isinstance(login, dict) or not str(login.get("uses") or "").strip():
                out.append(f"{where}.login[{i}] needs `uses`")
        services = prov.get("services")
        if not isinstance(services, dict) or not services:
            out.append(f"{where}.services must name at least one service")
            continue
        for sid, svc in services.items():
            at = f"{where}.services.{sid}"
            if not _ID.match(str(sid)):
                out.append(f"{at}: an id is lowercase letters, digits and hyphens")
            if not isinstance(svc, dict):
                out.append(f"{at} must be a mapping")
                continue
            if svc.get("kind") not in KINDS:
                out.append(f"{at}.kind must be one of {', '.join(KINDS)}")
            if not any(_strs(svc.get(k)) for k in ("uses", "run", "hosts", "files")):
                out.append(f"{at} has nothing to recognise it by (uses, run, hosts or files)")
        for i, rule in enumerate(prov.get("iac") or []):
            if not isinstance(rule, dict) or not str(rule.get("name") or "").strip():
                out.append(f"{where}.iac[{i}] needs `name`")
    scan = block.get("scan")
    if scan is not None and not isinstance(scan, dict):
        out.append("`clouds.scan` must be a mapping")
    return out


def normalize(block: dict) -> dict:
    """The block as the scanner reads it: every list a list, every id a string."""
    providers = {}
    for pid, prov in block["providers"].items():
        services = {}
        for sid, svc in prov["services"].items():
            services[str(sid)] = {
                "kind": svc["kind"], "uses": [u.lower() for u in _strs(svc.get("uses"))],
                "run": _strs(svc.get("run")), "hosts": [h.lower() for h in _strs(svc.get("hosts"))],
                "files": _strs(svc.get("files")), "oidc": [k.lower() for k in _strs(svc.get("oidc"))],
                "secret": [k.lower() for k in _strs(svc.get("secret"))]}
        providers[str(pid)] = {
            "title": str(prov.get("title") or pid), "enabled": prov["enabled"], "identity": prov["identity"],
            "login": [{"uses": str(l["uses"]).lower(), "oidc": [k.lower() for k in _strs(l.get("oidc"))],
                       "secret": [k.lower() for k in _strs(l.get("secret"))]} for l in prov.get("login") or []],
            "services": services,
            "iac": [{"name": str(r["name"]), "contains": str(r.get("contains") or "")} for r in prov.get("iac") or []]}
    scan = {**SCAN_DEFAULTS, **(block.get("scan") or {})}
    return {"providers": providers,
            "scan": {"skip_dirs": set(_strs(scan.get("skip_dirs"))), "max_depth": int(scan["max_depth"]),
                     "max_files": int(scan["max_files"])}}


def load_model(instance: Path = HUB, framework: Path = HUB) -> dict:
    """`clouds:` as the scanner reads it. The framework's block supplies how each
    provider is recognised; the instance's is laid over it, so an instance that
    declares nothing still gets the map and one that declares a switch keeps it."""
    base = (_load(framework / "_data" / "fleet.yml") or {}).get("clouds")
    over = None
    if instance.resolve() != framework.resolve():
        over = (_load(instance / "_data" / "fleet.yml") or {}).get("clouds")
    block = _merge(base, over) if base is not None else over
    problems = model_problems(block)
    if problems:
        raise ModelError("; ".join(problems))
    return normalize(block)


# --------------------------------------------------------------------------- #
# One checkout
# --------------------------------------------------------------------------- #
def _text(value) -> str:
    """A scalar as text, anything nested as ''. A mapping or a list is never
    printed: a workflow's alias chain is small on disk and huge once expanded."""
    if isinstance(value, str):
        return value
    return str(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else ""


def _action(uses) -> str:
    """`Owner/Action/sub@ref` -> `owner/action/sub`; a local or container action -> ''."""
    text = _text(uses).strip().lower()
    if not text or text.startswith((".", "docker:")):
        return ""
    return text.split("@", 1)[0]


def _uses(action: str, wanted: list[str]) -> bool:
    return any(action == w or action.startswith(w + "/") for w in wanted)


def _script(run) -> str:
    """A step's script without its comment lines: a command named in a comment deploys nothing."""
    return "\n".join(ln for ln in _text(run).splitlines() if not ln.lstrip().startswith("#"))


def _names(*mappings) -> dict[str, set[str]]:
    """The secret and variable NAMES a step's inputs and environment refer to."""
    found: dict[str, set[str]] = {STORED: set(), VARIABLES: set()}
    for mapping in mappings:
        for value in (mapping or {}).values():
            for context, name in _NAME.findall(_text(value)):
                found[STORED if context == "secrets" else VARIABLES].add(name)
    return found


def _steps(job: dict) -> list[dict]:
    """A job's steps as {action, inputs, env, script}; a job that calls a workflow is one step."""
    rows = []
    if job.get("uses"):
        rows.append({"action": _action(job["uses"]), "inputs": job.get("with") if isinstance(job.get("with"), dict) else {},
                     "env": {}, "script": ""})
    for step in job.get("steps") if isinstance(job.get("steps"), list) else []:
        if not isinstance(step, dict):
            continue
        rows.append({"action": _action(step.get("uses")),
                     "inputs": step.get("with") if isinstance(step.get("with"), dict) else {},
                     "env": step.get("env") if isinstance(step.get("env"), dict) else {},
                     "script": _script(step.get("run"))})
    return rows


def _method(inputs: dict, rule: dict) -> str | None:
    keys = {str(k).lower() for k in inputs}
    if keys & set(rule["secret"]):
        return "secret"
    if keys & set(rule["oidc"]):
        return "oidc"
    return None


def _environment(job: dict) -> tuple[str | None, str | None]:
    """(the job's deployment environment, its address). A name the workflow works
    out at run time reads `(computed)`, and only an address written out in full is kept."""
    env = job.get("environment")
    name, url = (env.get("name"), _text(env.get("url"))) if isinstance(env, dict) else (env, "")
    name = _text(name) or None
    if name and "${{" in name:
        name = COMPUTED
    return name, (url if url.startswith(("http://", "https://")) and "${{" not in url else None)


def scan_job(job: dict, model: dict) -> list[dict]:
    """The deployments one job makes: [{provider, service, identity, credential_names, variable_names}]."""
    steps = _steps(job)
    out = []
    for pid, prov in model["providers"].items():
        methods: list[str] = []
        names = {STORED: set(), VARIABLES: set()}
        for step in steps:
            for login in prov["login"]:
                if step["action"] and _uses(step["action"], [login["uses"]]):
                    got = _method(step["inputs"], login)
                    if got:
                        methods.append(got)
                    for kind, vals in _names(step["inputs"], step["env"]).items():
                        names[kind] |= vals
        for sid, svc in prov["services"].items():
            hits = [s for s in steps
                    if (s["action"] and _uses(s["action"], svc["uses"])) or any(n in s["script"] for n in svc["run"])]
            if not hits:
                continue
            own = list(methods)
            got_names = {k: set(v) for k, v in names.items()}
            for step in hits:
                got = _method(step["inputs"], svc)
                if got:
                    own.append(got)
                refs = _names(step["inputs"], step["env"])
                # A step that is handed a stored credential and signs in no other way holds one.
                if not own and refs[STORED] - PLATFORM_OWN:
                    own.append("secret")
                for kind, vals in refs.items():
                    got_names[kind] |= vals
            if not own:
                own.append("platform" if prov["identity"] == "platform" else UNKNOWN)
            out.append({"provider": pid, "service": sid,
                        "identity": min(own, key=IDENTITY_RANK.index),
                        STORED: got_names[STORED] - PLATFORM_OWN, VARIABLES: got_names[VARIABLES]})
    return out


def scan_workflows(path: Path, model: dict) -> tuple[list[dict], int, list[str]]:
    """(deployments, workflow files read, files that could not be read) for one checkout."""
    found: dict[tuple, dict] = {}
    unreadable: list[str] = []
    files = sorted(p for p in (path / WORKFLOW_DIR).glob("*") if p.suffix in (".yml", ".yaml") and p.is_file()) \
        if (path / WORKFLOW_DIR).is_dir() else []
    for wf in files:
        rel = str(wf.relative_to(path))
        try:
            too_big = wf.stat().st_size > MAX_WORKFLOW_BYTES
            # Parsed and dropped, not kept: a fleet has several hundred workflow files, and
            # the shared reader's cache is sized for the few documents every request reads.
            data = None if too_big else yamlio.parse(wf.read_bytes())
        except (OSError, yaml.YAMLError, RecursionError):
            unreadable.append(rel)
            continue
        if too_big or not isinstance(data, dict) or not isinstance(data.get("jobs"), dict):
            unreadable.append(rel)
            continue
        for jid, job in data["jobs"].items():
            if not isinstance(job, dict):
                continue
            env_name, env_url = _environment(job)
            for hit in scan_job(job, model):
                row = found.setdefault((hit["provider"], hit["service"], rel), {
                    "provider": hit["provider"], "service": hit["service"], "workflow": rel, "jobs": [],
                    "environments": [], "urls": [], "identity": hit["identity"], STORED: set(), VARIABLES: set(),
                    "evidence": "workflow"})
                row["jobs"].append(str(jid))
                if env_name and env_name not in row["environments"]:
                    row["environments"].append(env_name)
                if env_url and env_url not in row["urls"]:
                    row["urls"].append(env_url)
                row["identity"] = min((row["identity"], hit["identity"]), key=IDENTITY_RANK.index)
                row[STORED] |= hit[STORED]
                row[VARIABLES] |= hit[VARIABLES]
    return list(found.values()), len(files), unreadable


def scan_addresses(path: Path, model: dict, live_url: str | None, have: set[tuple]) -> list[dict]:
    """Deployments no workflow makes: an address on a provider's host, or its marker file at the root."""
    host = (urlsplit(live_url).hostname or "").lower() if live_url else ""
    out = []
    for pid, prov in model["providers"].items():
        for sid, svc in prov["services"].items():
            if (pid, sid) in have:
                continue
            evidence = None
            if host and any(fnmatch.fnmatchcase(host, pat) for pat in svc["hosts"]):
                evidence = "live_url"
            else:
                marker = next((f for f in svc["files"] if (path / f).is_file()), None)
                evidence = f"file:{marker}" if marker else None
            if evidence:
                out.append({"provider": pid, "service": sid, "workflow": None, "jobs": [], "environments": [],
                            "urls": [], "identity": "platform" if prov["identity"] == "platform" else UNKNOWN,
                            STORED: set(), VARIABLES: set(), "evidence": evidence})
    return out


def scan_iac(path: Path, model: dict) -> tuple[dict[str, list[str]], bool]:
    """({provider: [files that declare its resources]}, whether the walk was cut short)."""
    scan = model["scan"]
    rules = [(pid, r) for pid, prov in model["providers"].items() for r in prov["iac"]]
    found: dict[str, list[str]] = {}
    if not rules:
        return found, False
    seen = 0
    for base, dirs, files in os.walk(path):
        rel = Path(base).relative_to(path)
        depth = len(rel.parts)
        # A hidden directory holds tooling, a skipped one holds generated or borrowed
        # files, and a nested checkout is another repo's: none is this repo's infrastructure.
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in scan["skip_dirs"]
                         and depth < scan["max_depth"] and not (Path(base) / d / ".git").exists())
        for name in sorted(files):
            for pid, rule in rules:
                if not fnmatch.fnmatchcase(name, rule["name"]):
                    continue
                seen += 1
                if seen > scan["max_files"]:
                    return found, True
                if rule["contains"]:
                    try:
                        with open(Path(base) / name, "rb") as fh:
                            text = fh.read(MAX_IAC_BYTES).decode("utf-8", "replace")
                    except OSError:
                        continue
                    if rule["contains"] not in text:
                        continue
                item = str(rel / name)
                if item not in found.setdefault(pid, []):
                    found[pid].append(item)
    return found, False


def place_address(deployments: list[dict], model: dict, live_url: str | None) -> None:
    """Give the registry's `live_url` to the ONE deployment it can belong to: the
    service whose own host it is on, else the repo's only static deployment. A
    repo that deploys twice does not get one address printed beside both."""
    if not live_url:
        return
    host = (urlsplit(live_url).hostname or "").lower()
    owner = [d for d in deployments
             if any(fnmatch.fnmatchcase(host, pat) for pat in model["providers"][d["provider"]]["services"][d["service"]]["hosts"])]
    if not owner:
        static = [d for d in deployments if model["providers"][d["provider"]]["services"][d["service"]]["kind"] == "static"]
        owner = static if len(static) == 1 else (deployments if len(deployments) == 1 else [])
    for d in owner[:1]:
        if live_url not in d["urls"]:
            d["urls"].append(live_url)


def scan_repo(path: Path, model: dict, live_url: str | None = None) -> dict:
    """One checkout: its deployments, its infrastructure files and what could not be read."""
    deployments, workflows, unreadable = scan_workflows(path, model)
    deployments += scan_addresses(path, model, live_url, {(d["provider"], d["service"]) for d in deployments})
    place_address(deployments, model, live_url)
    iac, cut = scan_iac(path, model)
    return {"deployments": deployments, "iac": iac, "workflows": workflows, "unreadable": unreadable, "iac_cut": cut}


# --------------------------------------------------------------------------- #
# The fleet
# --------------------------------------------------------------------------- #
def _slug(repo_url) -> str:
    """`https://<host>/Owner/Name(.git)` -> `Owner/Name`; anything else -> ''."""
    parts = [p for p in urlsplit(str(repo_url or "")).path.split("/") if p]
    return f"{parts[0]}/{parts[1].removesuffix('.git')}" if len(parts) >= 2 else ""


def targets(instance: Path) -> tuple[list[dict], list[dict], int, str]:
    """(repos to read, repos that cannot be read, repos under another owner, the hub's slug)."""
    # The settings alone, never the environment: the map is the same on every host.
    who = identity.from_settings(_load(instance / "_data" / "fleet.yml"))
    slug, owners = who.repo, set(who.owners)
    registry = _load(instance / "_data" / "projects.yml") or []
    read, unread, external = [], [], 0
    if slug:
        read.append({"name": slug.split("/")[-1], "repo": slug, "path": instance, "live_url": None, "status": "hub"})
    for entry in registry if isinstance(registry, list) else []:
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        repo = _slug(entry.get("repo_url"))
        if owners and repo.split("/")[0].lower() not in owners:
            external += 1  # another owner's repo is mirrored here, never managed
            continue
        row = {"name": str(entry["name"]), "repo": repo, "live_url": entry.get("live_url") or None,
               "status": str(entry.get("status") or "")}
        sub = entry.get("submodule_path")
        path = instance / str(sub) if sub else None
        if path is None:
            unread.append({**row, "why": "not a submodule of this instance"})
        elif not (path / ".git").exists():
            unread.append({**row, "why": "not checked out"})
        else:
            read.append({**row, "path": path})
    return read, unread, external, slug


def _contract_names(instance: Path) -> set[str]:
    """The names the token contract declares (`tokens:`): what something audits and rotates."""
    tokens = (_load(instance / "_data" / "fleet.yml") or {}).get("tokens")
    return {str(t["name"]) for t in tokens if isinstance(t, dict) and t.get("name")} if isinstance(tokens, list) else set()


def findings(deployments: list[dict], iac: list[dict], model: dict, declared: set[str]) -> list[dict]:
    """What the map shows that someone should look at. Advisory: nothing here fails a build."""
    out = []
    providers = model["providers"]

    def add(rule, level, row, message):
        out.append({"rule": rule, "level": level, "repo": row["repo"], "provider": row["provider"], "message": message})

    has_iac = {(i["repo"], i["provider"]) for i in iac}
    deploys = {(d["repo"], d["provider"]) for d in deployments if d["evidence"] == "workflow"}
    told: set[tuple] = set()
    for d in deployments:
        prov = providers[d["provider"]]
        where = f"{d['repo']} → {prov['title']} {d['service']}"
        if d["identity"] == "secret" and prov["identity"] == "oidc":
            add("stored-credential", "warn", d,
                f"{where} signs in with a stored credential ({', '.join(d[STORED]) or 'unnamed'}); "
                f"the rule for {prov['title']} is a federated login, which stores none")
        if d["identity"] == "secret":
            loose = [n for n in d[STORED] if n not in declared]
            if loose:
                add("unmanaged-credential", "note", d,
                    f"{where} holds {', '.join(loose)}, which the token contract does not name, "
                    f"so nothing audits or rotates it")
        if d["identity"] == UNKNOWN and d["evidence"] == "workflow":
            add("identity-unknown", "note", d, f"{where}: how {d['workflow']} signs in could not be read from its steps")
        if d["evidence"] == "workflow" and prov["iac"] and (d["repo"], d["provider"]) not in has_iac | told:
            told.add((d["repo"], d["provider"]))  # once per repo and provider, however many services it deploys
            add("no-iac", "note", d,
                f"{d['repo']} deploys to {prov['title']} from {d['workflow']}, and no file in the repo declares the resources it deploys to")
    for i in iac:
        if (i["repo"], i["provider"]) not in deploys:
            add("iac-without-deploy", "note", i,
                f"{i['repo']} declares {providers[i['provider']]['title']} resources ({i['paths'][0]}) "
                f"that no workflow deploys: applied by hand, or not yet")
    order = {"warn": 0, "note": 1}
    return sorted(out, key=lambda f: (order[f["level"]], f["rule"], f["repo"], f["provider"]))


def status_doc(instance: Path = HUB, framework: Path = HUB, now: dt.datetime | None = None) -> dict:
    """THE document every surface reads (`fleet-clouds/v1`)."""
    model = load_model(instance, framework)
    read, unread, external, hub = targets(instance)
    deployments: list[dict] = []
    iac: list[dict] = []
    repos: list[dict] = []
    for t in read:
        got = scan_repo(t["path"], model, t["live_url"])
        for d in got["deployments"]:
            svc = model["providers"][d["provider"]]["services"][d["service"]]
            deployments.append({
                "repo": t["repo"] or t["name"], "name": t["name"], "provider": d["provider"], "service": d["service"],
                "kind": svc["kind"], "evidence": d["evidence"], "workflow": d["workflow"], "jobs": d["jobs"],
                "environments": d["environments"], "urls": d["urls"],
                "identity": d["identity"], "expected": model["providers"][d["provider"]]["identity"],
                STORED: sorted(d[STORED]), VARIABLES: sorted(d[VARIABLES])})
        for pid, paths in sorted(got["iac"].items()):
            iac.append({"repo": t["repo"] or t["name"], "name": t["name"], "provider": pid, "paths": paths[:5], "count": len(paths)})
        repos.append({"name": t["name"], "repo": t["repo"], "status": t["status"], "live_url": t["live_url"],
                      "workflows": got["workflows"], "unreadable": got["unreadable"], "iac_cut": got["iac_cut"],
                      "providers": sorted({d["provider"] for d in got["deployments"]})})
    deployments.sort(key=lambda d: (d["provider"], d["service"], d["repo"].lower(), d["workflow"] or ""))
    iac.sort(key=lambda i: (i["provider"], i["repo"].lower()))
    found = findings(deployments, iac, model, _contract_names(instance))
    providers = []
    for pid, prov in model["providers"].items():
        mine = [d for d in deployments if d["provider"] == pid]
        providers.append({
            "id": pid, "title": prov["title"], "enabled": prov["enabled"], "state": "on" if prov["enabled"] else "off",
            "identity": prov["identity"], "services": [{"id": sid, "kind": s["kind"]} for sid, s in prov["services"].items()],
            "deployments": len(mine), "repos": len({d["repo"] for d in mine}),
            "iac": sum(i["count"] for i in iac if i["provider"] == pid),
            "by_identity": {m: sum(1 for d in mine if d["identity"] == m) for m in IDENTITY_RANK if any(d["identity"] == m for d in mine)}})
    kinds = {k: sum(1 for d in deployments if d["kind"] == k) for k in KINDS}
    return {
        "schema": SCHEMA,
        "generated_at": (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hub": hub,
        "providers": providers,
        "deployments": deployments,
        "iac": iac,
        "repos": repos,
        "read": {"repos": len(read), "unread": [{"name": u["name"], "repo": u["repo"], "why": u["why"]} for u in unread],
                 "external": external},
        "findings": found,
        "summary": {
            "providers": len(providers), "in_use": sum(1 for p in providers if p["deployments"]),
            "deployments": len(deployments), "repos": len({d["repo"] for d in deployments}),
            # Deployments on a provider whose read switch is off: mapped from the repos, watched by nothing.
            "unwatched": sum(p["deployments"] for p in providers if not p["enabled"]),
            "kinds": {k: n for k, n in kinds.items() if n},
            "findings": {lvl: sum(1 for f in found if f["level"] == lvl) for lvl in ("warn", "note")}},
    }


# --------------------------------------------------------------------------- #
# The CLI
# --------------------------------------------------------------------------- #
def _table(rows: list[list[str]], head: list[str]) -> str:
    widths = [max(len(str(r[i])) for r in [head] + rows) for i in range(len(head))]
    line = lambda r: "  ".join(str(c).ljust(w) for c, w in zip(r, widths)).rstrip()  # noqa: E731
    return "\n".join([line(head), line(["-" * w for w in widths])] + [line(r) for r in rows])


def providers_table(doc: dict) -> str:
    rows = [[p["id"], p["state"], p["identity"], str(p["deployments"]), str(p["repos"]), str(p["iac"]),
             ", ".join(f"{n} {m}" for m, n in p["by_identity"].items()) or "—"] for p in doc["providers"]]
    return _table(rows, ["PROVIDER", "READ", "RULE", "DEPLOYS", "REPOS", "IAC FILES", "SIGNS IN WITH"])


def deployments_table(rows: list[dict]) -> str:
    if not rows:
        return "no deployment found"
    body = [[d["repo"], f"{d['provider']}/{d['service']}", d["kind"], d["identity"],
             d["workflow"].rsplit("/", 1)[-1] if d["workflow"] else d["evidence"],
             ", ".join(d["environments"]) or "—", (d["urls"] or ["—"])[0]] for d in rows]
    return _table(body, ["REPO", "RUNS ON", "KIND", "SIGNS IN", "EVIDENCE", "ENVIRONMENTS", "ADDRESS"])


def read_line(doc: dict) -> str:
    r = doc["read"]
    text = f"read {r['repos']} checkout(s)"
    if r["unread"]:
        text += f" · NOT read: {len(r['unread'])} ({', '.join(u['name'] for u in r['unread'][:6])}{'…' if len(r['unread']) > 6 else ''})"
    if r["external"]:
        text += f" · {r['external']} under another owner, never read"
    return text


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dash cloud", description="Where each fleet repo's deliverable runs, read from the repos.")
    ap.add_argument("cmd", nargs="?", default="status", choices=("status", "map", "check", "json"),
                    help="status: providers, deployments and findings (the default) · map: the deployments · "
                         "check: the findings · json: the document (fleet-clouds/v1)")
    ap.add_argument("--instance", default=os.environ.get("FLEET_HOME") or str(HUB),
                    help="the control plane whose registry and checkouts are read (default: FLEET_HOME, else this checkout)")
    ap.add_argument("--provider", help="map: only this provider")
    ap.add_argument("--repo", help="map: only this repo (its name or owner/name)")
    ap.add_argument("--strict", action="store_true", help="check: exit 1 when a finding is a warning")
    a = ap.parse_args(argv)
    try:
        doc = status_doc(Path(a.instance).expanduser(), HUB)
    except ModelError as exc:
        print(f"dash cloud: {exc}", file=sys.stderr)
        return 2
    if a.cmd == "json":
        print(json.dumps(doc, indent=2))
        return 0
    rows = [d for d in doc["deployments"]
            if (not a.provider or d["provider"] == a.provider) and (not a.repo or a.repo in (d["repo"], d["name"]))]
    s = doc["summary"]
    if a.cmd == "map":
        print(deployments_table(rows))
        print(f"\n{len(rows)} deployment(s) · {read_line(doc)}")
        return 0
    if a.cmd == "check":
        for f in doc["findings"]:
            print(f"{f['level']:<4}  {f['rule']:<20}  {f['message']}")
        print(f"\n{s['findings']['warn']} warning(s) · {s['findings']['note']} note(s) · {read_line(doc)}")
        return 1 if a.strict and s["findings"]["warn"] else 0
    print(providers_table(doc))
    print()
    print(deployments_table(doc["deployments"]))
    print(f"\n{s['deployments']} deployment(s) in {s['repos']} repo(s) on {s['in_use']} of {s['providers']} provider(s)"
          f" · {s['unwatched']} on a provider the hub does not read"
          f" · {s['findings']['warn']} warning(s), {s['findings']['note']} note(s) (dash cloud check)")
    print(read_line(doc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
