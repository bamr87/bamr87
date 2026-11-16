#!/usr/bin/env python3
"""voices.py — the canonical fleet voice config (_data/voices/voices.yml, voices/v1): check, render, preview, file.

  python3 tools/voices.py check [--file F] [--against COPY]   schema + reference checks; --against flags drift vs a consumer copy
  python3 tools/voices.py assign SITE ACTIVITY [--repo R] [--cadence daily|weekly]   which persona an entry gets
  python3 tools/voices.py render [--file F]                   F in the canonical layout (stable key order, its header kept)
  python3 tools/voices.py diff [--file F]                     F against origin/main's voices.yml (the editor's drift banner)
  python3 tools/voices.py pr --file F [--plan-id ID] [--apply]   F as ONE draft PR that changes only voices.yml

Stdlib + PyYAML only (jsonschema is not installed in CI): `check` walks
voices.schema.json itself (types, enums, required and unknown keys, $ref and
allOf), then the references the schema cannot express. Never reads secrets.

The console's Voices editor (constitution § 23 rule 7) and this CLI share one
path: `editor_doc` is what the page loads, `preview` the validated diff and
plan id it shows (it writes nothing), and `pr` the filer of the console's
`voices-pr` operation — the OPS remote-write path (§ 11.8): a dry run unless
`--apply`, and with it the publish token probed with `gh api user`, refused
with `--scheduled`, with a dirty engine, without the reviewed plan id, or when
the open-PR dedupe cannot be read; one pushed branch, one draft PR, one file.
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REL = "_data/voices/voices.yml"
SCHEMA_REL = "_data/voices/voices.schema.json"
FILE = ROOT / REL
SCHEMA = ROOT / SCHEMA_REL
MAIN_REF = "origin/main"
#: what the filer refuses to run on when it differs from HEAD: the code and the schema that judged the bytes
ENGINE = ("tools/voices.py", SCHEMA_REL)
PR_PREFIX = "chore/voices-"
PLAN_RX = re.compile(r"^[0-9a-f]{16}$")
COMMIT_NAME, COMMIT_EMAIL = "voices-editor", "voices-editor@users.noreply.github.com"
GOVERNED_BY = "§ 23.7 (amendment 0021 `writing-chronicle`), § 11.8 (amendment 0020 `ops-remote-write-path`)"

# --------------------------------------------------------------------------- #
# check — the schema, walked
# --------------------------------------------------------------------------- #
_TYPES = {"string": str, "boolean": bool, "array": list, "object": dict}
_A = {"string": "a string", "boolean": "true or false", "array": "a list", "object": "a mapping"}


def _schema() -> dict:
    return json.loads(SCHEMA.read_text())


def _join(where: str, key) -> str:
    return f"{where}.{key}" if where else str(key)


def _resolve(s: dict, defs: dict) -> dict:
    while isinstance(s, dict) and "$ref" in s:
        s = defs[s["$ref"].rsplit("/", 1)[-1]]
    return s


def _is(value, kind: str) -> bool:
    if kind in ("integer", "number"):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and (
            kind == "number" or float(value).is_integer())
    return isinstance(value, _TYPES.get(kind, object))


def _validate(where: str, value, s: dict, defs: dict, errs: list[str]) -> None:
    s = _resolve(s, defs)
    props: dict = {}
    required: list = []
    kind = s.get("type")
    for sub in s.get("allOf") or []:
        sub = _resolve(sub, defs)
        props.update(sub.get("properties") or {})
        required += sub.get("required") or []
        kind = kind or sub.get("type")
    props.update(s.get("properties") or {})
    required += s.get("required") or []
    if "const" in s and value != s["const"]:
        errs.append(f"{where or 'the file'}: must be {s['const']!r}")
        return
    if "enum" in s and value not in s["enum"]:
        errs.append(f"{where}: {value!r} not in {s['enum']}")
        return
    if kind and not _is(value, kind):
        errs.append(f"{where or 'the file'}: must be {_A.get(kind, kind)}, not {type(value).__name__}")
        return
    if isinstance(value, dict):
        for key in required:
            if key not in value:
                errs.append(f"{where or 'the file'}: missing {key}")
        extra = s.get("additionalProperties")
        closed = extra is False or s.get("unevaluatedProperties") is False
        for key, item in value.items():
            if key in props:
                _validate(_join(where, key), item, props[key], defs, errs)
            elif isinstance(extra, dict):
                _validate(_join(where, key), item, extra, defs, errs)
            elif closed:
                errs.append(f"{where or 'the file'}: unknown key {key!r}")
    if isinstance(value, list) and isinstance(s.get("items"), dict):
        for i, item in enumerate(value):
            _validate(f"{where}[{i}]", item, s["items"], defs, errs)


def check(data) -> list[str]:
    """Every schema error, then the references the schema cannot express: an
    assignment rule names one persona that exists, and nothing follows the
    `default` rule (assign() stops there, so a later rule is never reached)."""
    schema = _schema()
    errs: list[str] = []
    _validate("", data, schema, schema.get("$defs") or {}, errs)
    if not isinstance(data, dict):
        return errs
    for site, s in (data.get("sites") or {}).items() if isinstance(data.get("sites"), dict) else ():
        if not isinstance(s, dict):
            continue
        personas = s.get("personas") if isinstance(s.get("personas"), dict) else {}
        rules = s.get("assignment") if isinstance(s.get("assignment"), list) else []
        for i, r in enumerate(rules):
            if not isinstance(r, dict):
                continue
            where = f"sites.{site}.assignment[{i}]"
            target = r.get("persona") or r.get("default")
            if not target:
                errs.append(f"{where}: names no persona (persona: or default:)")
            elif target not in personas:
                errs.append(f"{where}: unknown persona {target!r}")
            if "default" in r and i != len(rules) - 1:
                errs.append(f"{where}: the default rule must be the last — the rules after it are never reached")
    return errs


def assign(data, site, activity, repo=None, cadence=None):
    s = data["sites"][site]
    on = {k for k, p in s["personas"].items() if p.get("enabled")}
    for r in s.get("assignment", []):
        if "default" in r:
            return r["default"] if r["default"] in on else None
        if r["persona"] not in on:
            continue
        if "activity" in r and activity not in r["activity"]:
            continue
        if "repos" in r and repo not in r["repos"]:
            continue
        if "cadence" in r and cadence != r["cadence"]:
            continue
        return r["persona"]
    return None


def enums() -> dict:
    """The closed vocabularies the editor's form offers: the style enums and the rule cadences."""
    defs = _schema()["$defs"]
    return {"style": {k: list(v.get("enum") or []) for k, v in defs["style"]["properties"].items()},
            "cadence": list(defs["rule"]["properties"]["cadence"]["enum"])}


# --------------------------------------------------------------------------- #
# render — the canonical layout, so an edit's diff is the edit and nothing else
# --------------------------------------------------------------------------- #
TOP_ORDER = ("schema", "defaults", "sites")
SITE_ORDER = ("profile", "personas", "assignment")
FIELD_ORDER = ("name", "role", "enabled", "perspective", "summary", "audience", "voice", "tone", "style", "guidance",
               "avoid", "claims", "vocabulary", "bans", "lifts", "limits", "examples", "topics", "beats", "repos")
FLOW_ORDER = {"style": ("formality", "length", "humor", "reading_level"), "topics": ("cover", "exclude"),
              "rule": ("activity", "repos", "cadence", "persona", "default")}
#: free-text fields: always double-quoted, whatever they hold
QUOTED = frozenset({"name", "perspective", "summary", "audience", "voice", "tone", "guidance", "avoid", "claims"})
_PLAIN_RX = re.compile(r"^[A-Za-z_][A-Za-z0-9_./-]*$")
_RESERVED = frozenset({"true", "false", "yes", "no", "on", "off", "null", "y", "n"})
_YAML_BREAKS = frozenset("\x85  ")


def _ordered(d: dict, order) -> list[tuple]:
    return [(k, d[k]) for k in order if k in d] + [(k, v) for k, v in d.items() if k not in order]


def _printable(c: str) -> bool:
    o = ord(c)
    return c not in _YAML_BREAKS and (c in "\t\n\r" or 0x20 <= o <= 0x7E or 0xA0 <= o <= 0xD7FF
                                      or 0xE000 <= o <= 0xFFFD or 0x10000 <= o <= 0x10FFFF)


def _dq(s: str) -> str:
    """A YAML double-quoted scalar: JSON's escapes, plus \\u escapes for what YAML reads as a break or rejects."""
    return "".join(c if _printable(c) else (f"\\u{ord(c):04x}" if ord(c) <= 0xFFFF else f"\\U{ord(c):08x}")
                   for c in json.dumps(s, ensure_ascii=False))


def _scalar(value, quote: bool = False) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    s = str(value)
    if not quote and _PLAIN_RX.match(s) and s.lower() not in _RESERVED:
        return s
    return _dq(s)


def _flow(value, key: str = "") -> str:
    if isinstance(value, dict):
        order = FLOW_ORDER.get(key, ())
        return "{" + ", ".join(f"{_scalar(k)}: {_flow(v, k)}" for k, v in _ordered(value, order)) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(_flow(v, key) for v in value) + "]"
    return _scalar(value, key in QUOTED)


def _entry(key, value, indent: int) -> list[str]:
    pad = " " * indent
    if isinstance(value, list) and any(isinstance(v, dict) for v in value):
        return [f"{pad}{_scalar(key)}:"] + [f"{pad}  - {_flow(v, 'rule' if key == 'assignment' else key)}"
                                            for v in value]
    return [f"{pad}{_scalar(key)}: {_flow(value, key)}"]


def _fields(d: dict, indent: int) -> list[str]:
    out: list[str] = []
    for key, value in _ordered(d, FIELD_ORDER):
        out += _entry(key, value, indent)
    return out


def _block(key, value, indent: int, body) -> list[str]:
    """`key:` with its body below, or `key: {}` / the value inline when there is no mapping to open."""
    pad = " " * indent
    if isinstance(value, dict) and value:
        return [f"{pad}{_scalar(key)}:"] + body(value, indent + 2)
    return [f"{pad}{_scalar(key)}: {_flow(value, key)}"]


def _personas(personas: dict, indent: int) -> list[str]:
    out: list[str] = []
    for key, p in personas.items():
        out += _block(key, p, indent, _fields)
    return out


def _site(s: dict, indent: int) -> list[str]:
    out: list[str] = []
    for key, value in _ordered(s, SITE_ORDER):
        if key == "profile":
            out += _block(key, value, indent, _fields)
        elif key == "personas":
            out += _block(key, value, indent, _personas)
        elif key == "assignment" and isinstance(value, list) and value:
            out += [f"{' ' * indent}assignment:"] + [f"{' ' * indent}  - {_flow(r, 'rule')}" for r in value]
        else:
            out += _entry(key, value, indent)
    return out


def _sites(sites: dict, indent: int) -> list[str]:
    out: list[str] = []
    for i, (key, s) in enumerate(sites.items()):
        if i:
            out.append("")
        out += _block(key, s, indent, _site)
    return out


def header_of(text: str) -> str:
    """The file's leading comment block, kept verbatim through every render."""
    lines = []
    for line in (text or "").splitlines():
        if not line.startswith("#"):
            break
        lines.append(line)
    return "\n".join(lines)


def render(data: dict, header: str = "") -> str:
    """The canonical bytes for `data`: the header, then schema / defaults / sites in
    a fixed key order, short mappings and lists in flow style, one assignment rule
    per line. render(load(f), header_of(f)) == f for the canonical file, so the
    console's write-back changes exactly the lines an edit touched."""
    out = header.splitlines() if header else []
    for i, (key, value) in enumerate(_ordered(data, TOP_ORDER)):
        if i:
            out.append("")
        if key == "defaults":
            out += _block(key, value, 0, _fields)
        elif key == "sites":
            out += _block(key, value, 0, _sites)
        else:
            out += _entry(key, value, 0)
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- #
# the editor's documents: load (with drift), preview (writes nothing)
# --------------------------------------------------------------------------- #
def _git_read(root: Path, args: list[str]) -> str | None:
    try:
        proc = subprocess.run(["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", *args],
                              cwd=str(root), capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def main_text(root: Path = ROOT, ref: str = MAIN_REF) -> str | None:
    """voices.yml as `ref` has it (the local remote-tracking ref: no network), or None."""
    return _git_read(root, ["show", f"{ref}:{REL}"])


def diff(old: str | None, new: str, old_label: str = MAIN_REF) -> str:
    return "".join(difflib.unified_diff((old or "").splitlines(keepends=True), new.splitlines(keepends=True),
                                        fromfile=f"a/{REL} ({old_label})", tofile=f"b/{REL}"))


def plan_id(base: str | None, text: str) -> str:
    """Deterministic for (the file on main, the bytes to file): a preview and its
    filing agree only while neither has moved (constitution § 11.4)."""
    return hashlib.sha256(f"voices/v1\0{base or ''}\0{text}".encode()).hexdigest()[:16]


def changed_paths(old, new, where: str = "") -> list[str]:
    """The dotted paths an edit changed — what the PR body and the page summarise."""
    if isinstance(old, dict) and isinstance(new, dict):
        out: list[str] = []
        for key in list(old) + [k for k in new if k not in old]:
            if key not in new:
                out.append(f"{_join(where, key)} (removed)")
            elif key not in old:
                out.append(f"{_join(where, key)} (added)")
            else:
                out += changed_paths(old[key], new[key], _join(where, key))
        return out
    return [] if old == new else [where or "the file"]


def _load(text: str):
    try:
        return yaml.safe_load(text) if text else None, None
    except yaml.YAMLError as exc:
        return None, f"not valid YAML: {str(exc).splitlines()[0]}"


def drift(root: Path = ROOT, ref: str = MAIN_REF, text: str | None = None) -> dict:
    local = text if text is not None else ((root / REL).read_text() if (root / REL).exists() else "")
    main = main_text(root, ref)
    differs = main is not None and main != local
    return {"ref": ref, "available": main is not None, "differs": differs,
            "diff": diff(main, local) if differs else "",
            "changes": changed_paths(_load(main)[0], _load(local)[0]) if differs else []}


def editor_doc(root: Path = ROOT, ref: str = MAIN_REF) -> dict:
    """What the console's Voices page loads: the file, its check errors, its drift
    from main, and the vocabularies the form offers. Reads only."""
    path = root / REL
    text = path.read_text() if path.exists() else ""
    data, parse_error = _load(text)
    errors = [parse_error] if parse_error else check(data)
    return {"schema": "voices-editor/v1", "path": REL, "schema_path": SCHEMA_REL, "text": text,
            "data": data if isinstance(data, dict) else None, "errors": errors, "ok": not errors,
            "canonical": isinstance(data, dict) and render(data, header_of(text)) == text,
            "drift": drift(root, ref, text), "enums": enums(), "field_order": list(FIELD_ORDER),
            "quoted": sorted(QUOTED)}


def preview(data, root: Path = ROOT, ref: str = MAIN_REF) -> dict:
    """An edit as the PR would carry it: validated, rendered with the file's own
    header, diffed against main (else the working tree), with its plan id.
    Writes nothing — not the file, not git, not GitHub."""
    errors = check(data) if isinstance(data, dict) else ["the voice config must be a mapping"]
    path = root / REL
    local = path.read_text() if path.exists() else ""
    text = render(data, header_of(local)) if isinstance(data, dict) else ""
    main = main_text(root, ref)
    base, base_name = (main, ref) if main is not None else (local, "the working tree")
    return {"ok": not errors, "errors": errors, "text": text, "base": base_name, "changed": text != base,
            "diff": diff(base, text, base_name), "changes": changed_paths(_load(base)[0], data),
            "plan_id": plan_id(base, text), "drift": drift(root, ref, local)}


# --------------------------------------------------------------------------- #
# pr — the filer (the OPS remote-write path, constitution § 11.8)
# --------------------------------------------------------------------------- #
def _hub_repo(root: Path) -> str:
    try:
        cfg = yaml.safe_load((root / "_data" / "fleet.yml").read_text()) or {}
        repo = (cfg.get("hub") or {}).get("repo")
    except (OSError, yaml.YAMLError, AttributeError):
        repo = None
    return repo if isinstance(repo, str) and re.fullmatch(r"[\w.-]+/[\w.-]+", repo) else "bamr87/bamr87"


def _jev_common():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tools.jev import common  # noqa: PLC0415 - the filer's guarded git/gh, loaded only when filing
    return common


def _probe() -> tuple[dict | None, str]:
    """The publish token as the engine resolves it: FLEET_TOKEN from the
    environment, then the hub .env, else the ambient gh login — probed with
    `gh api user` before anything is written, never printed."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tools.jev.loop import probe_publish_token  # noqa: PLC0415
    return probe_publish_token()


def pr_body(changes: list[str], plan: str, base_sha: str) -> str:
    listed = "\n".join(f"- `{c}`" for c in changes[:60]) or "- (formatting only)"
    more = f"\n- … and {len(changes) - 60} more" if len(changes) > 60 else ""
    return (
        "An edit to the fleet voice model (`voices/v1`), made in the Harness Console's Voices editor and filed by "
        "`tools/voices.py pr --apply` after a reviewed dry run. It changes `_data/voices/voices.yml` and nothing "
        "else; the file is the only copy (constitution § 23 rule 7: no database copy).\n\n"
        f"## What changed\n\n{listed}{more}\n\n"
        "## Checks\n\n"
        "- `python3 tools/voices.py check` passed on these exact bytes before the push.\n"
        f"- Plan `{plan}` binds the bytes to `{REL}` as `main` had it at `{base_sha[:12]}`; the filing is "
        "refused when either moves.\n\n"
        f"Governed by: {GOVERNED_BY}\n"
    )


def file_pr(text: str, plan: str | None = None, *, apply: bool = False, scheduled: bool = False,
            root: Path = ROOT, repo: str | None = None, ref: str = MAIN_REF, today: str | None = None,
            gh=None, probe=None, say=print) -> dict:
    """File `text` as voices.yml in ONE draft PR. A dry run without `apply`.

    Returns {"status": dry-run | nothing | filed | refused | failed, ...}. Every
    refusal comes before the first write; after the push a failure is reported,
    never retried blind. `gh` and `probe` are seams for the tests."""
    repo = repo or _hub_repo(root)
    today = today or dt.date.today().isoformat()
    data, parse_error = _load(text)
    errors = [parse_error] if parse_error else check(data)

    def done(status: str, why: str = "", **extra) -> dict:
        say(f"voices pr: {status}" + (f" — {why}" if why else ""))
        return {"status": status, "reason": why, **extra}

    if errors:
        for e in errors:
            say(f"error: {e}")
        return done("refused", f"{len(errors)} check error(s): the file must pass `tools/voices.py check`")
    if not apply:
        main = main_text(root, ref)
        local = (root / REL).read_text() if (root / REL).exists() else ""
        base, base_name = (main, ref) if main is not None else (local, "the working tree")
        pid = plan_id(base, text)
        if text == base:
            return done("nothing", f"identical to {REL} on {base_name}", plan_id=pid)
        changes = changed_paths(_load(base)[0], data)
        say(f"dry run — nothing is pushed or filed. Against {REL} on {base_name}:")
        say(diff(base, text, base_name).rstrip("\n"))
        say(f"changes: {', '.join(changes) or '(formatting only)'}")
        say(f"plan id: {pid}")
        if plan and plan != pid:
            say(f"note: this is not plan {plan} (main or the bytes moved since that preview)")
        say(f"with --apply --plan-id {pid}: one branch {PR_PREFIX}{today}-{pid[:8]} and one draft PR in {repo}")
        return done("dry-run", plan_id=pid, changes=changes)
    if scheduled:
        return done("refused", "--scheduled: no unattended filing (constitution § 11.8, until § 13.7 earned autonomy)")
    if not plan or not PLAN_RX.fullmatch(plan):
        return done("refused", "--apply needs the reviewed --plan-id from the dry run or the console's preview")

    jc = _jev_common()
    gh = gh or jc.gh
    dirty = jc.git(["status", "--porcelain", "--", *ENGINE], cwd=root)
    if not dirty.ok or dirty.out.strip():
        return done("refused", f"the engine is dirty or unreadable ({', '.join(ENGINE)}): the bytes must be judged "
                               "by the committed checker")
    env, who = (probe or _probe)()
    if env is None:
        return done("refused", who)
    say(f"publish token: {who}")
    git_env = {"GH_TOKEN": env["GH_TOKEN"]} if env.get("GH_TOKEN") else None
    fetched = jc.git(["fetch", "-q", "--no-tags", "origin", "main"], cwd=root, env=git_env, timeout=600)
    if not fetched.ok:
        return done("failed", f"git fetch origin main: {fetched.err.strip()[-200:]}")
    base_sha = jc.git(["rev-parse", "FETCH_HEAD"], cwd=root).out.strip()
    shown = jc.git(["show", f"{base_sha}:{REL}"], cwd=root)
    base = shown.out if shown.ok else ""
    pid = plan_id(base, text)
    if pid != plan:
        return done("refused", f"plan {plan} no longer matches ({pid}): {REL} on main or the bytes moved since the "
                               "preview — preview again")
    if text == base:
        return done("nothing", f"identical to {REL} on main", plan_id=pid)
    listed = gh(["pr", "list", "-R", repo, "--state", "open", "--json", "number,url,headRefName", "--limit", "200"],
                env=dict(env), timeout=120)
    try:
        open_prs = json.loads(listed.out or "[]") if listed.ok else None
    except ValueError:
        open_prs = None
    if not isinstance(open_prs, list):
        return done("refused", "the open-PR list could not be read — never filed without the dedupe")
    mine = [p for p in open_prs if str(p.get("headRefName", "")).startswith(PR_PREFIX)]
    if mine:
        return done("refused", f"an open voices PR exists (#{mine[0].get('number')} {mine[0].get('url', '')}) — "
                               "review, merge or close it first")
    branch = f"{PR_PREFIX}{today}-{pid[:8]}"
    taken = gh(["api", f"repos/{repo}/git/matching-refs/heads/{branch}"], env=dict(env), timeout=60)
    try:
        refs = json.loads(taken.out or "[]") if taken.ok else None
    except ValueError:
        refs = None
    if not isinstance(refs, list):
        return done("refused", f"could not read whether {branch} exists")
    if any(r.get("ref") == f"refs/heads/{branch}" for r in refs if isinstance(r, dict)):
        return done("refused", f"{branch} already exists in {repo} — a push is never a force")

    work = Path(tempfile.mkdtemp(prefix="voices-pr-"))
    wt = work / "hub"
    added = False
    try:
        made = jc.git(["-c", "submodule.recurse=false", "worktree", "add", "-q", "--detach", str(wt), base_sha],
                      cwd=root)
        if not made.ok:
            return done("failed", f"git worktree add: {made.err.strip()[-200:]}")
        added = True
        (wt / REL).write_text(text)
        staged = jc.git(["add", "--", REL], cwd=wt)
        title = f"chore(voices): edit the voice model from the console ({today})"
        committed = staged.ok and jc.git(["-c", f"user.name={COMMIT_NAME}", "-c", f"user.email={COMMIT_EMAIL}",
                                          "-c", "commit.gpgsign=false", "commit", "-q", "-m", title, "-m",
                                          f"Plan {pid}; filed by `tools/voices.py pr --apply` from the console's "
                                          "Voices editor."], cwd=wt).ok
        if not committed:
            return done("failed", "git add/commit of the edited file failed")
        touched = jc.git(["diff", "--name-only", base_sha, "HEAD"], cwd=wt).out.split()
        if touched != [REL]:
            return done("refused", f"the commit would change {touched}, not only {REL} — nothing pushed")
        pushed = jc.git(["push", "-q", "origin", f"HEAD:refs/heads/{branch}"], cwd=wt, env=git_env, timeout=600)
        if not pushed.ok:
            return done("failed", f"git push {branch}: {pushed.err.strip()[-200:]}")
        body = work / "body.md"
        body.write_text(pr_body(changed_paths(_load(base)[0], data), pid, base_sha))
        made_pr = gh(["pr", "create", "-R", repo, "--draft", "--base", "main", "--head", branch, "--title", title,
                      "--body-file", str(body)], env=dict(env), timeout=180)
        url = (made_pr.out.strip().splitlines() or [""])[-1]
        if not made_pr.ok or not url.startswith("https://"):
            return done("failed", f"gh pr create failed after the push of {branch} (a person looks before any "
                                  f"retry): {(made_pr.err or made_pr.out).strip()[-200:]}", branch=branch, pushed=True)
        return done("filed", f"draft PR {url}", url=url, branch=branch, plan_id=pid, pushed=True)
    finally:
        if added:
            jc.git(["worktree", "remove", "--force", str(wt)], cwd=root)
        shutil.rmtree(work, ignore_errors=True)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--file", default=str(FILE))
    c.add_argument("--against")
    a = sub.add_parser("assign")
    a.add_argument("site")
    a.add_argument("activity")
    a.add_argument("--repo")
    a.add_argument("--cadence")
    a.add_argument("--file", default=str(FILE))
    r = sub.add_parser("render", help="print the file in the canonical layout")
    r.add_argument("--file", default=str(FILE))
    d = sub.add_parser("diff", help=f"the file against {MAIN_REF}'s voices.yml")
    d.add_argument("--file", default=str(FILE))
    p = sub.add_parser("pr", help="file the bytes as one draft PR (a dry run unless --apply)")
    p.add_argument("--file", required=True)
    p.add_argument("--plan-id")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--scheduled", action="store_true", help="an unattended run: --apply is refused with it")
    ns = ap.parse_args(argv)
    text = Path(ns.file).read_text()
    if ns.cmd == "pr":
        res = file_pr(text, ns.plan_id, apply=ns.apply, scheduled=ns.scheduled)
        print("result: " + json.dumps(res, sort_keys=True))
        return 0 if res["status"] in ("dry-run", "nothing", "filed") else 1
    if ns.cmd == "diff":
        print(diff(main_text(ROOT), text), end="")
        return 0
    data, parse_error = _load(text)
    if parse_error:
        print("error:", parse_error)
        return 1
    if ns.cmd == "assign":
        print(assign(data, ns.site, ns.activity, ns.repo, ns.cadence))
        return 0
    if ns.cmd == "render":
        print(render(data, header_of(text)), end="")
        return 0
    errs = check(data)
    if ns.against and yaml.safe_load(Path(ns.against).read_text()) != data:
        errs.append(f"drift: {ns.against} differs from {ns.file} (the hub file is canonical)")
    for e in errs:
        print("error:", e)
    print(f"{ns.file}: {'ok' if not errs else f'{len(errs)} error(s)'}")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
