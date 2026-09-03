"""schema_vendor — keep the hub's vendored Pyramid Schema kit in step with upstream.

The hub does not depend on bamr87/SCHEMA, it COPIES from it: the linter into
`tools/schema_lint.py`, the seed template and the protocol snippet into
`templates/schema/`. `templates/schema/VERSION` records which upstream commit
those copies came from — by hand, updated by whoever remembered.

That is the half of the reinvest rule nothing enforced. `tools/check-drift.sh`
check (i) compares the fleet's copies against the HUB's copy, so a submodule
that forks the linter is caught; nothing compared the hub's copy against
UPSTREAM, so the whole fleet could sit a year behind the package it vendors
and every gate would still read green.

This closes it, deterministically and offline-testable:

  1. Fetch upstream's `DISTRIBUTION.yml` — the content-addressed manifest of
     the vendored surface (see bamr87/SCHEMA tools/schema_dist.py).
  2. Compare each payload file against the hub's copy at its mapped path,
     honouring the manifest's parity tier: `strict` files must be
     byte-identical, `text` files may be reflowed/requoted here (they are —
     deliberately, per the kit's VERSION notes) but must not differ in
     substance.
  3. With --apply, re-vendor what can be re-vendored mechanically (the strict
     files) and restamp `templates/schema/VERSION`. Text-parity drift is
     REPORTED, never auto-written: those copies carry local adaptation, and
     silently overwriting them would throw away the reflow the fleet's own
     prose gate expects.

The workflow turns a non-zero exit into one PR. No auto-merge, no push to a
protected branch.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - environment guard
    yaml = None

UPSTREAM_NWO = "bamr87/SCHEMA"
UPSTREAM_REF = "main"
MANIFEST_PATH = "DISTRIBUTION.yml"
VERSION_FILE = "templates/schema/VERSION"

# upstream payload path -> where the hub keeps its copy. The hub re-homes what
# it vendors (the snippet lives with the kit, not in a protocol/ dir), so the
# mapping is explicit rather than path-preserving.
VENDORED: dict[str, str] = {
    "tools/schema_lint.py": "tools/schema_lint.py",
    "templates/SCHEMA.template.md": "templates/schema/SCHEMA.template.md",
    "protocol/CLAUDE.snippet.md": "templates/schema/CLAUDE.snippet.md",
}

# Severity order for the summary line and the PR body.
ACTIONABLE = {"drift-strict", "drift-text", "missing-local", "unmapped"}


@dataclass
class Finding:
    kind: str
    upstream: str
    local: str = ""
    parity: str = ""
    detail: str = ""

    def as_dict(self) -> dict:
        return {"kind": self.kind, "upstream": self.upstream, "local": self.local,
                "parity": self.parity, "detail": self.detail}


@dataclass
class Plan:
    findings: list[Finding] = field(default_factory=list)
    spec: str = ""
    commit: str = ""

    @property
    def actionable(self) -> list[Finding]:
        return [f for f in self.findings if f.kind in ACTIONABLE]


# --------------------------------------------------------------------------- #
# hashing — must match bamr87/SCHEMA tools/schema_dist.py exactly
# --------------------------------------------------------------------------- #
def normalize_text(text: str) -> str:
    """Layout-blind substance of a document.

    The recipe is stated in the manifest's own header: all whitespace removed,
    ASCII apostrophes mapped to double quotes. Whitespace is removed rather
    than collapsed because a downstream restyle can INSERT it (`|---|` ->
    `| --- |`) as easily as collapse it.
    """
    return re.sub(r"\s+", "", text.replace("'", '"'))


def digests(blob: bytes) -> tuple[str, str]:
    """(raw sha256, layout-blind text sha256)."""
    raw = hashlib.sha256(blob).hexdigest()
    text = hashlib.sha256(
        normalize_text(blob.decode("utf-8", errors="replace")).encode("utf-8")
    ).hexdigest()
    return raw, text


# --------------------------------------------------------------------------- #
# upstream access
# --------------------------------------------------------------------------- #
def _authorize(req: urllib.request.Request) -> urllib.request.Request:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    return req


def content_request(nwo: str, ref: str, path: str) -> urllib.request.Request:
    """A request for one file's bytes, through the Contents API.

    NOT raw.githubusercontent.com, and the reason is a trap worth naming:
    that host 404s — not 401s — when handed an `Authorization: Bearer` header
    it does not accept, which the Actions `GITHUB_TOKEN` is. The workflow always
    sets GH_TOKEN, so the first live run of this loop reported a PUBLIC file as
    "upstream unreachable", warned, and stopped. A weekly job that can never
    run is exactly the failure this loop exists to catch, so it must not be the
    shape of the loop itself.

    `api.github.com/.../contents` with the raw media type accepts a Bearer
    token and works without one, which also makes a private upstream readable
    rather than indistinguishable from a deleted one.
    """
    url = (f"https://api.github.com/repos/{nwo}/contents/"
           f"{urllib.parse.quote(path)}?ref={urllib.parse.quote(ref)}")
    return _authorize(urllib.request.Request(url, headers={
        "Accept": "application/vnd.github.raw",
        "User-Agent": "bamr87-dash/schema-vendor",
    }))


def http_fetcher(nwo: str = UPSTREAM_NWO, ref: str = UPSTREAM_REF, timeout: int = 20):
    """Return fetch(path) -> bytes, reading file contents from GitHub."""

    def fetch(path: str) -> bytes:
        with urllib.request.urlopen(content_request(nwo, ref, path),
                                    timeout=timeout) as resp:
            return resp.read()

    return fetch


def head_commit(nwo: str = UPSTREAM_NWO, ref: str = UPSTREAM_REF,
                timeout: int = 20) -> str:
    """Short sha of upstream's ref, or '' when the API is unreachable.

    Provenance only: a missing sha degrades the VERSION stamp, never the
    comparison, which is content-addressed and needs no commit at all.
    """
    req = _authorize(urllib.request.Request(
        f"https://api.github.com/repos/{nwo}/commits/{ref}",
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": "bamr87-dash/schema-vendor"}))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return (json.load(resp).get("sha") or "")[:7]
    except (urllib.error.URLError, OSError, ValueError):
        return ""


def pinned_commit(root: Path) -> str:
    """`upstream-commit:` as recorded in the kit's VERSION file."""
    path = root / VERSION_FILE
    if not path.is_file():
        return ""
    m = re.search(r"^upstream-commit:\s*(\S+)", path.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else ""


# --------------------------------------------------------------------------- #
# comparison
# --------------------------------------------------------------------------- #
def build_plan(root: Path, manifest: dict, fetch, commit: str = "") -> Plan:
    """Compare every manifest payload entry against the hub's copy."""
    plan = Plan(spec=str(manifest.get("spec") or ""), commit=commit)

    for entry in manifest.get("payload") or []:
        up = entry.get("path") or ""
        parity = entry.get("parity") or "strict"
        local_rel = VENDORED.get(up)
        if not local_rel:
            plan.findings.append(Finding(
                "unmapped", up, parity=parity,
                detail="upstream vendors this file; the hub has no copy mapped "
                       "for it — widen VENDORED or decide not to carry it"))
            continue

        local = root / local_rel
        if not local.is_file():
            plan.findings.append(Finding(
                "missing-local", up, local_rel, parity,
                detail="the hub declares this kit file but does not have it"))
            continue

        raw, text = digests(local.read_bytes())
        if raw == entry.get("sha256"):
            plan.findings.append(Finding("current", up, local_rel, parity,
                                         detail="byte-identical"))
        elif parity == "text" and text == entry.get("sha256_text"):
            plan.findings.append(Finding(
                "current", up, local_rel, parity,
                detail="adapted (layout/quotes only), substance matches"))
        elif parity == "text":
            plan.findings.append(Finding(
                "drift-text", up, local_rel, parity,
                detail="substance differs from upstream — this copy carries "
                       "local adaptation, so re-vendoring it is a judgement "
                       "call, not a copy"))
        else:
            plan.findings.append(Finding(
                "drift-strict", up, local_rel, parity,
                detail="not byte-identical to upstream; strict parity means "
                       "the fleet is running a different gate"))

    if commit and (pin := pinned_commit(root)) and pin != commit:
        stale = any(f.kind in ACTIONABLE for f in plan.findings)
        plan.findings.append(Finding(
            "pin-stale", MANIFEST_PATH, VERSION_FILE,
            detail=f"VERSION pins {pin}, upstream is at {commit}"
                   + ("" if stale else " (content already matches — the stamp "
                                       "is just behind)")))
    return plan


def load_manifest(fetch) -> dict:
    """Fetch and parse upstream's DISTRIBUTION.yml."""
    if yaml is None:
        raise RuntimeError("PyYAML required (pip install pyyaml)")
    data = yaml.safe_load(fetch(MANIFEST_PATH).decode("utf-8"))
    if not isinstance(data, dict) or "payload" not in data:
        raise RuntimeError(f"{MANIFEST_PATH} is not a distribution manifest")
    return data


# --------------------------------------------------------------------------- #
# apply
# --------------------------------------------------------------------------- #
def restamp_version(root: Path, commit: str, today: str) -> bool:
    """Surgically update the kit VERSION's provenance lines, comments intact."""
    path = root / VERSION_FILE
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    out = text
    if commit:
        out = re.sub(r"^upstream-commit:.*$", f"upstream-commit: {commit}",
                     out, count=1, flags=re.M)
    out = re.sub(r"^vendored:.*$", f"vendored: {today}", out, count=1, flags=re.M)
    out = re.sub(r"^verified:.*$", f"verified: {today}", out, count=1, flags=re.M)
    if out != text:
        path.write_text(out, encoding="utf-8")
        return True
    return False


def apply_plan(root: Path, plan: Plan, fetch, today: str | None = None) -> list[str]:
    """Re-vendor what is mechanical. Returns the repo-relative paths written."""
    today = today or dt.date.today().isoformat()
    written: list[str] = []
    for f in plan.findings:
        # drift-text is deliberately absent: a copy the hub adapted on purpose
        # is re-vendored by a human reading the diff, not by an overwrite.
        # missing-local IS written whatever its parity — there is no local
        # adaptation to lose in a file that does not exist.
        if f.kind not in ("drift-strict", "missing-local"):
            continue
        dest = root / f.local
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(fetch(f.upstream))
        written.append(f.local)
    if written and restamp_version(root, plan.commit, today):
        written.append(VERSION_FILE)
    return written


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
SYMBOL = {"current": "ok      ", "drift-strict": "DRIFT   ", "drift-text": "DRIFT   ",
          "missing-local": "MISSING ", "unmapped": "NEW     ", "pin-stale": "stamp   "}


def render(plan: Plan) -> str:
    lines = [f"upstream: {UPSTREAM_NWO}@{plan.commit or 'unknown'}  spec {plan.spec or '?'}"]
    for f in plan.findings:
        where = f.local or f.upstream
        lines.append(f"{SYMBOL.get(f.kind, '?       ')} {where}: {f.detail}")
    n = len(plan.actionable)
    lines.append("")
    lines.append(f"{'DRIFT' if n else 'CURRENT'}: {n} actionable finding(s)")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# cli
# --------------------------------------------------------------------------- #
def cmd_vendor(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    fetch = http_fetcher(args.nwo, args.ref)
    try:
        manifest = load_manifest(fetch)
    except (urllib.error.URLError, OSError, RuntimeError, ValueError) as exc:
        # Upstream being unreachable is not drift. Say so and exit 2 so the
        # workflow can tell "cannot check" apart from "out of date".
        print(f"unreachable: {UPSTREAM_NWO} {MANIFEST_PATH}: {exc}", file=sys.stderr)
        return 2

    plan = build_plan(root, manifest, fetch, head_commit(args.nwo, args.ref))

    if args.json:
        print(json.dumps({
            "upstream": f"{args.nwo}@{args.ref}",
            "commit": plan.commit,
            "spec": plan.spec,
            "actionable": len(plan.actionable),
            "findings": [f.as_dict() for f in plan.findings],
        }, indent=2))
    else:
        print(render(plan))

    if args.apply and plan.actionable:
        written = apply_plan(root, plan, fetch)
        if written:
            print("\nre-vendored:")
            for w in written:
                print(f"  {w}")
        left = [f for f in plan.actionable if f.kind in ("drift-text", "unmapped")]
        if left:
            print("\nleft for a human (local adaptation / interface change):")
            for f in left:
                print(f"  {f.local or f.upstream}: {f.detail}")

    return 1 if plan.actionable else 0


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default=".", help="hub checkout (default: .)")
    parser.add_argument("--nwo", default=UPSTREAM_NWO, help="upstream owner/repo")
    parser.add_argument("--ref", default=UPSTREAM_REF, help="upstream ref")
    parser.add_argument("--apply", action="store_true",
                        help="re-vendor strict-parity files and restamp VERSION")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.set_defaults(func=cmd_vendor)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="schema_vendor",
                                     description=__doc__.splitlines()[0])
    add_arguments(parser)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
