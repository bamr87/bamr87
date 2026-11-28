#!/usr/bin/env python3
"""Fleet identity: WHO an instance is, read once (ADR 0011 decision 2).

An instance is a control plane that owns a set of repos (ADR 0011 decision 1).
Its identity is `_data/fleet.yml` `hub:`. A module asks this one for it and
does not read `hub:` itself, so a missing key means the same thing everywhere:

  repo            the instance's own repository, `owner/name` (`hub.repo`)
  owner, name     its two halves
  owners          the GitHub owners whose repos ARE the fleet (`hub.owners`,
                  lower-cased); when the settings declare none, the owner of
                  `repo`. A repo under any other owner is an external mirror.
  shared          the repository of shared workflows and health files
  default_branch  `hub.default_branch`, else `main`
  bot_name        the name automation commits with (`hub.bot_name`)
  bot_email       the address it commits with (`hub.bot_email`)
  site            the published site's address, when `hub.site` gives one
  source          where `repo` came from: `settings`, `environment` or `none`

  from_settings(fleet)   what an already loaded settings mapping declares, and
                         nothing else: no file is read, no environment asked
  resolve(root, env)     the identity of the instance at `root`: its settings,
                         then `GITHUB_REPOSITORY` when they name no repository
  Identity.owned(x)      whether a repo slug or a GitHub address is the fleet's

When the settings name no repository and the environment has none, the
identity is empty and says so (`source: none`). No owner is invented here: a
module that has a default of its own keeps it in its own code, where it shows.

`GITHUB_REPOSITORY` is the repository a workflow runs IN. That is the instance
inside the instance's own workflows, and a fleet repo's own name inside a
reusable workflow the hub lends it. The fallback is for the first case, and
`source` tells a caller which answer it was given.

The shell twin is this file, not a second implementation (`tools/dash identity`):

    python3 -m fleetcore.identity [show]                every key, as key=value
    python3 -m fleetcore.identity get <key>             one value; exit 1 when it has none
    python3 -m fleetcore.identity owned <repo-or-url>   exit 0 when owned, 1 when not
    python3 -m fleetcore.identity json                  the document (fleet-identity/v1)
    … --instance DIR      another instance (default: FLEET_HOME, else this checkout)

`show` and `json` exit 1 when there is no identity at all, after printing it.

Standard library only at import, and light: PyYAML is imported only to read a
settings file and `argparse` only by the CLI, so a module that must load on a
bare interpreter (stars.py, which the SessionStart hook loads) can still ask
`from_settings()`. Read-only (constitution § 10.6): no write, no subprocess, no
network.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Mapping, NamedTuple

HUB = Path(__file__).resolve().parents[2]
SCHEMA = "fleet-identity/v1"
SETTINGS = Path("_data") / "fleet.yml"
ENV_HOME = "FLEET_HOME"            # the instance root (ADR 0011 decision 1)
ENV_REPO = "GITHUB_REPOSITORY"     # the fallback for `repo` (decision 2)
DEFAULT_BRANCH = "main"
FROM_SETTINGS, FROM_ENVIRONMENT, FROM_NOTHING = "settings", "environment", "none"
# Every key `get` answers and `show` prints, in the order they are printed.
KEYS = ("repo", "owner", "name", "owners", "shared", "default_branch", "bot_name", "bot_email", "site", "source")

# The `hub:` keys that are read as they are written: one line of text each.
_TEXT_KEYS = ("shared", "bot_name", "bot_email", "site")

_GITHUB = re.compile(r"^(?:[a-z][a-z0-9+.-]*://)?(?:[^@/\s]+@)?(?:www\.)?github\.com[:/]+(?P<path>.*)$", re.I)


def _text(value) -> str:
    """A scalar as stripped text; nothing, a mapping or a list as ''."""
    if value is None or isinstance(value, (dict, list, tuple, set, bool)):
        return ""
    return str(value).strip()


def _declared(value) -> tuple[str, ...]:
    """`hub.owners` as the settings write it, in order. One name is a list of one."""
    items = value if isinstance(value, (list, tuple)) else [value]
    return tuple(name for name in (_text(item) for item in items) if name)


def owner_of(repo_or_url) -> str:
    """The owner a slug (`owner/name`) or a GitHub address names, lower-cased:
    the first of its parts. '' when it names none: one word, or an address on
    another host."""
    text = _text(repo_or_url)
    hit = _GITHUB.match(text)
    if hit:
        text = hit.group("path")
    elif "://" in text or "@" in text.split("/", 1)[0]:
        return ""  # an address, and not GitHub's
    parts = [p for p in text.split("/") if p]
    return parts[0].lower() if len(parts) >= 2 else ""


class Identity(NamedTuple):
    """One instance's identity. Every field is text; '' means the settings do not say."""

    repo: str = ""
    owners: tuple[str, ...] = ()            # lower-cased; what `owned()` asks
    declared_owners: tuple[str, ...] = ()   # `hub.owners` as written; empty when the settings declare none
    shared: str = ""
    default_branch: str = DEFAULT_BRANCH
    bot_name: str = ""
    bot_email: str = ""
    site: str = ""
    source: str = FROM_NOTHING

    @property
    def owner(self) -> str:
        return self.repo.split("/")[0] if self.repo else ""

    @property
    def name(self) -> str:
        return self.repo.split("/")[-1] if self.repo else ""

    def owned(self, repo_or_url) -> bool:
        """Whether a repo slug or a GitHub address belongs to one of the owners.
        Never true when no owner is known: nothing is the fleet's by default."""
        owner = owner_of(repo_or_url)
        return bool(owner) and owner in self.owners

    def as_dict(self) -> dict:
        """The identity as plain data, under the names the settings and the CLI use."""
        return {"repo": self.repo, "owner": self.owner, "name": self.name, "owners": list(self.owners),
                "shared": self.shared, "default_branch": self.default_branch, "bot_name": self.bot_name,
                "bot_email": self.bot_email, "site": self.site, "source": self.source}

    def get(self, key: str) -> str:
        """One key as the text a shell reads; the owners on one line, a space between them."""
        value = self.as_dict()[key]
        return " ".join(value) if isinstance(value, list) else value


def from_settings(fleet) -> Identity:
    """The identity a loaded `_data/fleet.yml` declares, and nothing else. A
    module that must give the same answer on every host asks this."""
    hub = fleet.get("hub") if isinstance(fleet, dict) else None
    hub = hub if isinstance(hub, dict) else {}
    repo = _text(hub.get("repo"))
    declared = _declared(hub.get("owners"))
    owners = tuple(dict.fromkeys(o.lower() for o in declared)) or ((repo.split("/")[0].lower(),) if repo else ())
    return Identity(repo=repo, owners=owners, declared_owners=declared,
                    default_branch=_text(hub.get("default_branch")) or DEFAULT_BRANCH,
                    source=FROM_SETTINGS if repo else FROM_NOTHING,
                    **{key: _text(hub.get(key)) for key in _TEXT_KEYS})


def load_settings(root: Path | str) -> dict:
    """An instance's `_data/fleet.yml` as a mapping; {} when it is absent, unreadable or not a mapping."""
    import yaml  # noqa: PLC0415 - only a read needs PyYAML: see the module docstring

    from . import yamlio  # noqa: PLC0415

    try:
        doc = yamlio.load(Path(root) / SETTINGS)
    except (OSError, yaml.YAMLError):
        return {}
    return doc if isinstance(doc, dict) else {}


def home(env: Mapping[str, str] | None = None) -> Path:
    """The instance root when nobody names one: `FLEET_HOME`, else this checkout."""
    env = os.environ if env is None else env
    named = _text(env.get(ENV_HOME))
    return Path(named).expanduser() if named else HUB


def resolve(root: Path | str | None = None, env: Mapping[str, str] | None = None) -> Identity:
    """The identity of the instance at `root` (default: `home()`): what its
    settings declare, then `GITHUB_REPOSITORY` for a repository they do not
    name. `env` is where both variables are read (default: the process's own);
    pass {} for the settings alone."""
    env = os.environ if env is None else env
    found = from_settings(load_settings(Path(root).expanduser() if root is not None else home(env)))
    if found.repo:
        return found
    slug = _text(env.get(ENV_REPO))
    if not slug:
        return found
    return found._replace(repo=slug, owners=found.owners or (slug.split("/")[0].lower(),), source=FROM_ENVIRONMENT)


def owned(repo_or_url, root: Path | str | None = None, env: Mapping[str, str] | None = None) -> bool:
    """`resolve(root, env).owned(repo_or_url)`, for a caller that asks once."""
    return resolve(root, env).owned(repo_or_url)


# --------------------------------------------------------------------------- #
# The CLI: what a shell script calls
# --------------------------------------------------------------------------- #
def _why_none(root: Path) -> str:
    return f"{root / SETTINGS} names no `hub.repo` and {ENV_REPO} is not set"


def main(argv: list[str] | None = None) -> int:
    import argparse  # noqa: PLC0415 - the CLI's alone: see the module docstring

    ap = argparse.ArgumentParser(prog="dash identity", description="Who this instance is, from its settings (ADR 0011).")
    ap.add_argument("cmd", nargs="?", default="show", choices=("show", "get", "owned", "json"),
                    help="show: every key as key=value (the default) · get KEY: one value · "
                         "owned REPO: is a repo slug or a GitHub address the fleet's · json: the document (fleet-identity/v1)")
    ap.add_argument("arg", nargs="?", help=f"get: one of {', '.join(KEYS)} · owned: owner/name or a GitHub address")
    ap.add_argument("--instance", default=None,
                    help=f"the control plane whose settings are read (default: {ENV_HOME}, else this checkout)")
    a = ap.parse_args(argv)
    root = Path(a.instance).expanduser() if a.instance else home()
    who = resolve(root)
    if a.cmd == "json":
        print(json.dumps({"schema": SCHEMA, "instance": str(root), **who.as_dict()}, indent=2))
        return 0 if who.repo else 1
    if a.cmd == "get":
        if a.arg not in KEYS:
            print(f"dash identity: get needs one of: {', '.join(KEYS)}", file=sys.stderr)
            return 2
        value = who.get(a.arg)
        if not value:
            why = _why_none(root) if a.arg in ("repo", "owner", "name", "owners") else f"{root / SETTINGS} sets no `hub.{a.arg}`"
            print(f"dash identity: no {a.arg}: {why}", file=sys.stderr)
            return 1
        print(value)
        return 0
    if a.cmd == "owned":
        if not a.arg:
            print("dash identity: owned needs a repo: owner/name or a GitHub address", file=sys.stderr)
            return 2
        owner = owner_of(a.arg)
        if who.owned(a.arg):
            print(f"owned: {owner} is one of the fleet's owners")
            return 0
        if not owner:
            print(f"not owned: {a.arg!r} names no GitHub owner")
        elif not who.owners:
            print(f"not owned: no owner is known ({_why_none(root)})")
        else:
            print(f"not owned: {owner} is not one of {', '.join(who.owners)}")
        return 1
    for key in KEYS:
        print(f"{key}={who.get(key)}")
    if not who.repo:
        print(f"dash identity: no identity: {_why_none(root)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
