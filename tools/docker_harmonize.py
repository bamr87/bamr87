#!/usr/bin/env python3
# ============================================================================
# File:          tools/docker_harmonize.py
# Description:   Harmonizes a repo's Docker configuration to the fleet standard
#                — versions from _data/fleet.yml `images:`, loopback-bound
#                env-overridable ports, no container_name, working healthchecks
#                — with surgical line edits that preserve comments.
# Author:        bamr87
# Created:       2026-09-21
# Last Modified: 2026-09-21
# Version:       1.0.0
# Usage:
#   tools/docker_harmonize.py audit [DIR] [--project NAME] [--json]
#   tools/docker_harmonize.py apply [DIR] [--project NAME]
#   tools/docker_harmonize.py check [DIR] [--project NAME]   # exit 1 if apply would change anything
#   tools/docker_harmonize.py tags                           # do the registry's tags exist upstream?
#   tools/docker_harmonize.py fleet [--json|--summary]       # audit every checked-out submodule
# ============================================================================
#
# WHY LINE EDITS AND NOT A YAML ROUND-TRIP
#
# The fleet's compose files are heavily commented, and the comments are the
# valuable part — they record WHY (law-ai's "MAJOR VERSION IS PINNED ON
# PURPOSE", zer0-mistakes' platform note). A load/dump cycle would destroy
# them. PyYAML is used to READ structure; every write is a targeted edit of the
# exact line. Same posture as dash-gen `reconcile`.
#
# THE RULES (each is idempotent — a second `apply` is a no-op)
#
#   compose   V1  drop the obsolete top-level `version:` key
#             I1  bump managed images to the fleet registry, keeping the tag's
#                 variant (-alpine, -slim …); `bookworm` -> `trixie`
#             P1  postgres >= 18 moved its data directory; a volume still
#                 mounted at /var/lib/postgresql/data makes the server refuse
#                 to start, so the mount target moves to /var/lib/postgresql
#             N1  drop `container_name` (global to the daemon) unless a script
#                 or config references it — docs mentions do not block
#             T1  publish ports as "127.0.0.1:${VAR:-<same port>}:<target>"
#             T2  thread that variable through env values that hardcode the
#                 host port (a browser/peer URL that would otherwise go stale)
#             H1  healthchecks probe 127.0.0.1, not localhost (::1 trap)
#             H2  two evidenced healthcheck fixes: qdrant (no curl in image),
#                 celery inspect ping (1s default timeout is flaky)
#             E1  an env_file a fresh clone cannot have becomes required:false
#   Dockerfile
#             D1  seed a .dockerignore next to a build context that has none —
#                 additive, never overwrites, and excludes only paths an image
#                 never wants (.git, .env, caches, build output of the SOURCE)
#             I1  bump managed FROM images / the ARG that feeds them
#             L1  a COPY of a lockfile the fleet policy forbids committing is
#                 dropped from the source list; `npm ci` -> `npm install`
#
# DELIBERATE PINS ARE RESPECTED. A comment on or directly above an image line
# containing "pinned", "bump deliberately", "do not bump" or "fleet-pin" freezes
# that image's whole family in that repo (law-ai pins Postgres 16 with a
# dump/restore note; a psql sidecar on another major would be a surprise).
#
# NOT AUTO-FIXED, only reported (they need a human's judgement): running as
# root, no HEALTHCHECK, no .dockerignore, single-stage builds, the abandoned
# jekyll/jekyll image, platform pins.

import argparse
import json
import os
import re
import subprocess
import sys

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("docker_harmonize: PyYAML is required (pip install pyyaml)\n")
    raise SystemExit(2)

HUB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SKIP_DIRS = {".git", "node_modules", "_site", "vendor", ".venv", "venv", "dist",
             "build", ".next", "__pycache__", ".bundle", "site-packages",
             # other tools' git worktrees are whole copies of the repo
             "worktrees", ".kilo"}
LOCKFILES = ("Gemfile.lock", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock",
             "pnpm-lock.yaml", "poetry.lock", "Pipfile.lock", "uv.lock")
PIN_RE = re.compile(r"(?i)\bpinned\b|bump deliberately|do not bump|fleet-pin")
EXEC_EXT = {".sh", ".bash", ".py", ".js", ".ts", ".mjs", ".cjs", ".json", ".yml",
            ".yaml", ".toml", ".mk", ".cfg", ".ini", ".env", ".rb", ".go"}
DOC_EXT = {".md", ".rst", ".txt", ".adoc"}

# Deliberately conservative: every entry is something an image never needs, and
# nothing here is a path a Dockerfile plausibly COPYs into the image. `dist/` and
# `build/` are NOT excluded — several repos copy a pre-built frontend from one.
DOCKERIGNORE = """\
# Seeded by the fleet docker kit (bamr87/bamr87 docs/DOCKER.md).
# Additive and conservative: only paths an image never needs. Add your own below.

# VCS and CI
.git
.gitignore
.github

# Secrets — never let these reach a layer
.env
.env.*
!.env.example

# Dependency trees: installed inside the image, not copied in
node_modules
**/node_modules
.venv
venv
vendor/bundle

# Caches and local ephemera
__pycache__
**/__pycache__
*.pyc
.pytest_cache
.mypy_cache
.ruff_cache
.jekyll-cache
.sass-cache
_site
.DS_Store
*.log
coverage
.nyc_output
"""

OLD_PG_DATA = "/var/lib/postgresql/data"
NEW_PG_DATA = "/var/lib/postgresql"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
def load_images():
    """image -> version, from _data/fleet.yml `images:`. Scalars only."""
    with open(os.path.join(HUB, "_data", "fleet.yml")) as fh:
        fleet = yaml.safe_load(fh) or {}
    return {str(k): str(v) for k, v in (fleet.get("images") or {}).items()}


def load_overrides():
    """project -> {image: (version, reason)} — per-repo ceilings from fleet.yml."""
    with open(os.path.join(HUB, "_data", "fleet.yml")) as fh:
        fleet = yaml.safe_load(fh) or {}
    out = {}
    for proj, imgs in (fleet.get("image_overrides") or {}).items():
        out[str(proj)] = {str(k): (str((v or {}).get("version", "")), str((v or {}).get("reason", "")))
                          for k, v in (imgs or {}).items()}
    return out


def load_ports():
    path = os.path.join(HUB, "_data", "ports.yml")
    if not os.path.exists(path):
        return {}
    with open(path) as fh:
        return (yaml.safe_load(fh) or {}).get("projects") or {}


# ---------------------------------------------------------------------------
# Port parsing (shared with tools/fleet-compose.py)
# ---------------------------------------------------------------------------
def split_port(spec):
    """Split a compose short-form port on `:`, ignoring colons inside ${...}.

    The fleet's most conformant repo writes
    `${BIND_HOST:-127.0.0.1}:${POSTGRES_PORT:-5433}:5432` — three fields, five
    colons. A plain split (or a naive regex) reads that as garbage.
    """
    parts, buf, depth = [], [], 0
    for ch in spec:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
        if ch == ":" and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


def parse_port(entry):
    """Normalize a compose `ports:` entry to (published, target, proto)."""
    if isinstance(entry, dict):
        return (str(entry.get("published", "")), str(entry.get("target", "")),
                entry.get("protocol", "tcp"))
    spec = str(entry).strip()
    proto = "tcp"
    if "/" in spec:
        head, _, tail = spec.rpartition("/")
        if tail in ("tcp", "udp"):
            spec, proto = head, tail
    parts = split_port(spec)
    if len(parts) == 1:
        return (None, parts[0], proto)
    if len(parts) == 2:
        return (parts[0], parts[1], proto)
    return (parts[1], parts[2], proto)


def var_name(project, service, target=None, primary=True, prefix=None):
    """<PREFIX>_<SERVICE>[_<TARGET>]_PORT — the prefix comes from the registry
    (`prefix:`) so a repo's variables share one stem with the ones already
    allocated in _data/ports.yml (FREDGAR_API_PORT, not FREDGAR_AI_API_PORT)."""
    stem = re.sub(r"[^A-Za-z0-9]+", "_", prefix or project).strip("_")
    base = f"{stem}_" + re.sub(r"[^A-Za-z0-9]+", "_", service).strip("_")
    base = base.upper()
    if not primary and target:
        base = f"{base}_{target}"
    return f"{base}_PORT"


# ---------------------------------------------------------------------------
# Image tags
# ---------------------------------------------------------------------------
TAG_RE = re.compile(r"^(?P<ver>\d+(?:\.\d+){0,2})(?P<var>(?:-[A-Za-z0-9._]+)*)$")


def norm_image(name):
    for prefix in ("docker.io/library/", "docker.io/", "library/"):
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def ver_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v.split("-")[0]))


def bump_tag(tag, want):
    """Return the new tag, or None when it must be left alone.

    NEVER lowers a version. The registry's Ruby is 3.4 because the
    github-pages gem caps at < 4.0 — but zer0-cms and zer0-image-generator are
    Rails apps already on 4.0.5, and "harmonizing" them down to 3.4 would be a
    regression dressed as consistency. A pin moves up, or not at all.
    """
    if not tag or tag in ("latest", "alpine", "slim") or "$" in tag:
        return None                       # floating / interpolated: already latest
    m = TAG_RE.match(tag)
    if not m:
        return None                       # named release (jammy, stable …)
    cur, w = ver_tuple(m.group("ver")), ver_tuple(want)
    if cur[:len(w)] > w:
        return None                       # already newer than the fleet target
    var = m.group("var")
    var = re.sub(r"bookworm|bullseye|buster", "trixie", var)
    var = re.sub(r"-alpine\d+(?:\.\d+)*", "-alpine", var)
    new = f"{want}{var}"
    return None if new == tag else new


def split_ref(ref):
    """'registry/img:tag' -> (name, tag or None). Handles registry ports."""
    if "@" in ref:
        return (ref.split("@", 1)[0], None)          # digest-pinned: leave
    head, sep, tail = ref.rpartition(":")
    if sep and "/" not in tail:
        return (head, tail)
    return (ref, None)


# ---------------------------------------------------------------------------
# Change bookkeeping
# ---------------------------------------------------------------------------
class Change:
    __slots__ = ("file", "line", "rule", "old", "new")

    def __init__(self, file, line, rule, old, new):
        self.file, self.line, self.rule, self.old, self.new = file, line, rule, old, new

    def as_dict(self):
        return {"file": self.file, "line": self.line, "rule": self.rule,
                "old": self.old, "new": self.new}


class Finding:
    __slots__ = ("file", "line", "kind", "msg")

    def __init__(self, file, line, kind, msg):
        self.file, self.line, self.kind, self.msg = file, line, kind, msg

    def as_dict(self):
        return {"file": self.file, "line": self.line, "kind": self.kind, "msg": self.msg}


# ---------------------------------------------------------------------------
# Repo discovery
# ---------------------------------------------------------------------------
def walk(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        depth = os.path.relpath(dirpath, root).count(os.sep)
        if depth > 4:
            dirnames[:] = []
        for fn in filenames:
            yield os.path.join(dirpath, fn)


def is_compose(path):
    b = os.path.basename(path).lower()
    return bool(re.match(r"^(docker-)?compose([._-].+)?\.ya?ml$", b))


def is_dockerfile(path):
    b = os.path.basename(path)
    return b == "Dockerfile" or b.startswith("Dockerfile.") or b.endswith(".Dockerfile")


def is_template(path):
    """Seed material a kit copies into ANOTHER repo, not a build this one runs.

    Its image version still tracks the registry — zer0-mistakes'
    Dockerfile.consumer.template seeds theme consumers, so a stale FROM there
    propagates staleness — but it is not a build context, so it gets no
    .dockerignore.
    """
    b = os.path.basename(path)
    return b.endswith(".template") or ".template." in b


class Repo:
    """A checkout and the lazily-built facts the rules need about it."""

    def __init__(self, root, project):
        self.root = os.path.abspath(root)
        self.project = project
        self.images = load_images()
        # A repo whose ecosystem has not caught up gets its own ceiling, with the
        # reason on the record (fleet.yml `image_overrides:`).
        self.held = {}
        for img, (ver, why) in (load_overrides().get(project) or {}).items():
            if ver:
                self.images[img] = ver
                self.held[img] = (ver, why)
        self.ports = (load_ports().get(project) or {})
        # Fixtures and test data are INPUTS to the repo's tests, not its own
        # configuration — rewriting them would silently change what is tested.
        self.files = [f for f in walk(self.root)
                      if not re.search(r"[/\\](fixtures?|__fixtures__|testdata)[/\\]", f)]
        if self.root == HUB:
            # Pointed at the hub itself: `projects/` holds every submodule (each is
            # its own repo, harmonized by its own PR) and `compose/overrides/` is
            # GENERATED from _data/ports.yml — hand-harmonizing it would be undone
            # by the next `fleet-compose.py sync`.
            top = lambda f: os.path.relpath(f, self.root).split(os.sep)  # noqa: E731
            self.files = [f for f in self.files
                          if top(f)[0] not in ("projects", ".dash-lake", "site", "evolution-workorders")
                          and top(f)[:2] != ["compose", "overrides"]]
            # compose/shared.yml IS one of the hub's compose files, but its name
            # does not match the `docker-compose*.yml` pattern, so gate (n) was
            # blind to it — it still carried postgres:17 / redis:7 while the
            # registry said 18 / 8, and claimed conformance.
            extra = os.path.join(self.root, "compose", "shared.yml")
            if os.path.exists(extra):
                self.files.append(extra)
        self.compose = sorted(f for f in self.files
                              if is_compose(f) or os.path.basename(f) == "shared.yml")
        self.dockerfiles = sorted(f for f in self.files if is_dockerfile(f))
        self._text = None
        self.frozen = self._frozen_families()

    def rel(self, path):
        return os.path.relpath(path, self.root)

    def has_file(self, basename):
        return any(os.path.basename(f) == basename for f in self.files)

    # -- deliberate pins -----------------------------------------------------
    def _frozen_families(self):
        """Image families a human pinned on purpose, per FILE.

        Scoped to the file rather than the whole repo. A pin records a constraint
        about one stack — law-ai's Postgres pin has to cover the `langgraph-db-init`
        sidecar that talks to that same server, which is why it spans a file — but
        it must not leak across files: the hub pins its Wiki.js database (real
        content in an existing volume) and that was silently holding back
        `fleet-db` in compose/shared.yml, an empty, unrelated, brand-new service.
        """
        frozen = {}
        for path in self.compose + self.dockerfiles:
            lines = read_lines(path)
            here = set()
            for i, line in enumerate(lines):
                ref = image_ref_of(line, path)
                if not ref:
                    continue
                key = norm_image(split_ref(ref)[0])
                # Only families the registry manages can be frozen — a Dockerfile
                # stage alias (`FROM base`) under a "pinned" comment is not one.
                if is_pinned(lines, i) and (key in self.images or key == "timescale/timescaledb"):
                    here.add(key)
            frozen[path] = here
        return frozen

    def frozen_in(self, path):
        return self.frozen.get(path, set())

    @property
    def frozen_families(self):
        out = set()
        for v in self.frozen.values():
            out |= v
        return out

    # -- text index for container_name reference checks ----------------------
    def text_index(self):
        if self._text is None:
            self._text = []
            for f in self.files:
                ext = os.path.splitext(f)[1].lower()
                b = os.path.basename(f)
                if ext not in EXEC_EXT | DOC_EXT and b not in ("Makefile", "Dockerfile"):
                    continue
                try:
                    if os.path.getsize(f) > 512_000:
                        continue
                    with open(f, encoding="utf-8", errors="ignore") as fh:
                        self._text.append((f, fh.read().split("\n")))
                except OSError:
                    continue
        return self._text

    def references(self, name):
        """(config_refs, doc_refs) mentioning a container name."""
        pat = re.compile(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])")
        cfg, docs = [], []
        for f, lines in self.text_index():
            ext = os.path.splitext(f)[1].lower()
            for n, line in enumerate(lines, 1):
                if "container_name" in line or not pat.search(line):
                    continue
                # A name inside a comment documents; it does not depend. Treating
                # it as a live reference is how a comment in fleet-compose.py kept
                # `bamr87-wiki` pinned in place.
                is_comment = line.lstrip().startswith(("#", "//", "*", "<!--"))
                (docs if ext in DOC_EXT or is_comment else cfg).append((self.rel(f), n))
        return cfg, docs


def read_text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def write_text(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def read_lines(path):
    return read_text(path).split("\n")


def is_pinned(lines, i):
    if "#" in lines[i] and PIN_RE.search(lines[i].split("#", 1)[1]):
        return True
    j = i - 1
    while j >= 0 and lines[j].strip().startswith("#"):
        if PIN_RE.search(lines[j]):
            return True
        j -= 1
    return False


IMAGE_LINE = re.compile(r"^(?P<pre>\s*image:\s*)(?P<q>['\"]?)(?P<ref>[^\s'\"#]+)(?P=q)(?P<post>\s*(#.*)?)$")
FROM_LINE = re.compile(r"^(?P<pre>\s*FROM\s+(?:--\S+\s+)*)(?P<ref>\S+)(?P<post>.*)$", re.I)


def image_ref_of(line, path):
    if is_dockerfile(path):
        m = FROM_LINE.match(line)
    else:
        m = IMAGE_LINE.match(line)
    return m.group("ref") if m else None


# ---------------------------------------------------------------------------
# Compose structure
# ---------------------------------------------------------------------------
def service_spans(lines):
    """[(name, start, end, key_indent)] for every service; end is exclusive."""
    start = None
    for i, l in enumerate(lines):
        if re.match(r"^services:\s*(#.*)?$", l):
            start = i + 1
            break
    if start is None:
        return []
    starts, svc_indent, stop = [], None, len(lines)
    for j in range(start, len(lines)):
        l = lines[j]
        if not l.strip() or l.lstrip().startswith("#"):
            continue
        ind = len(l) - len(l.lstrip())
        if ind == 0:
            stop = j
            break
        if svc_indent is None:
            svc_indent = ind
        if ind == svc_indent:
            m = re.match(r"^\s+([^\s:#]+):\s*(#.*)?$", l)
            if m:
                starts.append((m.group(1), j))
    spans = []
    for k, (name, s) in enumerate(starts):
        e = starts[k + 1][1] if k + 1 < len(starts) else stop
        key_indent = svc_indent
        for j in range(s + 1, e):
            l = lines[j]
            if l.strip() and not l.lstrip().startswith("#"):
                key_indent = len(l) - len(l.lstrip())
                break
        spans.append((name, s, e, key_indent))
    return spans


def block(lines, span, key):
    """(key_line, [item line indexes]) for a `key:` block inside a service."""
    _, s, e, ki = span
    for i in range(s + 1, e):
        l = lines[i]
        if re.match(r"^\s{%d}%s:\s*(#.*)?$" % (ki, re.escape(key)), l):
            items = []
            for j in range(i + 1, e):
                lj = lines[j]
                if not lj.strip():
                    continue
                if lj.lstrip().startswith("#"):
                    items.append(j)
                    continue
                if len(lj) - len(lj.lstrip()) <= ki:
                    break
                items.append(j)
            return i, items
    return None, []


def service_key_line(lines, span, key):
    _, s, e, ki = span
    for i in range(s + 1, e):
        if re.match(r"^\s{%d}%s:\s*\S" % (ki, re.escape(key)), lines[i]):
            return i
    return None


def service_image(lines, span):
    _, s, e, ki = span
    for i in range(s + 1, e):
        m = IMAGE_LINE.match(lines[i])
        if m and (len(lines[i]) - len(lines[i].lstrip())) == ki:
            return i, m.group("ref")
    return None, None


# ---------------------------------------------------------------------------
# The transform
# ---------------------------------------------------------------------------
class Result:
    def __init__(self):
        self.changes = []
        self.findings = []

    def change(self, *a):
        self.changes.append(Change(*a))

    def find(self, *a):
        self.findings.append(Finding(*a))


def want_version(repo, name):
    return repo.images.get(norm_image(name))


def bump_ref(repo, ref, path=None):
    name, tag = split_ref(ref)
    key = norm_image(name)
    if key in (repo.frozen_in(path) if path is not None else repo.frozen_families):
        return None
    # TimescaleDB tracks the Postgres major inside its tag.
    if key == "timescale/timescaledb" and tag:
        pg = repo.images.get("postgres")
        m = re.match(r"^(?P<a>.*-pg)(?P<n>\d+)(?P<z>.*)$", tag)
        if pg and m and m.group("n") != pg.split(".")[0]:
            return f"{name}:{m.group('a')}{pg.split('.')[0]}{m.group('z')}"
        return None
    want = want_version(repo, name)
    if not want:
        return None
    new = bump_tag(tag, want)
    return f"{name}:{new}" if new else None


def _in_env_file_block(lines, idx, key_indent):
    """Is lines[idx] an item under an `env_file:` key (not `volumes:` etc.)?"""
    for j in range(idx - 1, -1, -1):
        l = lines[j]
        if not l.strip() or l.lstrip().startswith("#"):
            continue
        ind = len(l) - len(l.lstrip())
        if ind <= key_indent:
            return bool(re.match(r"^\s*env_file:\s*(#.*)?$", l))
    return False


def transform_compose(repo, path, text, res):
    rel = repo.rel(path)
    lines = text.split("\n")
    spans = service_spans(lines)

    # V1 -----------------------------------------------------------------
    for i, l in enumerate(lines):
        if re.match(r"^version:\s*['\"]?[\d.]+['\"]?\s*(#.*)?$", l):
            res.change(rel, i + 1, "V1", l.strip(), "(removed — obsolete key)")
            del lines[i]
            if i < len(lines) and not lines[i].strip() and (i == 0 or not lines[i - 1].strip()):
                del lines[i]
            spans = service_spans(lines)
            break

    # Host ports this file publishes -> the variable that will carry them.
    portmap = {}
    for name, s, e, ki in spans:
        for var_i, (published, target, _p, var) in enumerate(_ports_of(repo, lines, (name, s, e, ki))):
            if published and published.isdigit():
                portmap[published] = (var, published)

    for span in spans:
        name = span[0]

        # I1 + P1 --------------------------------------------------------
        ii, ref = service_image(lines, span)
        new_major = None
        if ii is not None:
            new = bump_ref(repo, ref, path)
            if new:
                m = IMAGE_LINE.match(lines[ii])
                res.change(rel, ii + 1, "I1", ref, new)
                lines[ii] = f"{m.group('pre')}{m.group('q')}{new}{m.group('q')}{m.group('post')}"
                ref = new
            n2, t2 = split_ref(ref)
            key = norm_image(n2)
            if key == "postgres" and t2 and re.match(r"^\d+", t2):
                new_major = int(re.match(r"^\d+", t2).group(0))
            elif key == "timescale/timescaledb" and t2:
                mm = re.search(r"-pg(\d+)", t2)
                new_major = int(mm.group(1)) if mm else None
        if new_major and new_major >= 18 and "postgres" not in repo.frozen_in(path):
            _, items = block(lines, span, "volumes")
            for j in items:
                if OLD_PG_DATA in lines[j] and not lines[j].lstrip().startswith("#"):
                    old = lines[j].strip()
                    lines[j] = re.sub(re.escape(OLD_PG_DATA) + r"(?![\w/])", NEW_PG_DATA, lines[j])
                    res.change(rel, j + 1, "P1", old, lines[j].strip())

        # N1 -------------------------------------------------------------
        ci = service_key_line(lines, span, "container_name")
        if ci is not None:
            cname = re.sub(r"^\s*container_name:\s*", "", lines[ci]).split("#")[0].strip().strip("'\"")
            cfg, docs = repo.references(cname)
            if cfg:
                res.find(rel, ci + 1, "container_name",
                         f"'{cname}' is referenced by {cfg[0][0]}:{cfg[0][1]}"
                         f"{' (+%d more)' % (len(cfg) - 1) if len(cfg) > 1 else ''} — kept")
            else:
                res.change(rel, ci + 1, "N1", lines[ci].strip(), "(removed — names are global to the daemon)")
                lines[ci] = None
                if docs:
                    res.find(rel, ci + 1, "docs",
                             f"docs mention container '{cname}' ({docs[0][0]}:{docs[0][1]}) — "
                             f"update to '<project>-{name}-1'")

    lines = [l for l in lines if l is not None]

    # E1, as its OWN pass and FIRST, because it is the only rule that changes the
    # line COUNT. It used to run inside the main loop, where the `spans` list the
    # loop was iterating went stale the moment two lines were inserted — every
    # service after the insertion point silently kept its hardcoded ports. A
    # fixpoint loop that re-derives spans after each edit is the simple fix.
    base_dir = os.path.dirname(path)
    while True:
        spans = service_spans(lines)
        edit = None
        for span in spans:
            _, s0, e0, ki = span
            for i in range(s0 + 1, e0):
                l = lines[i]
                m = re.match(r"^(?P<ind>\s*)env_file:\s*(?P<q>['\"]?)(?P<p>[^\s'\"#\[]+)(?P=q)\s*(#.*)?$", l)
                if m and (len(l) - len(l.lstrip())) == ki:
                    if not os.path.exists(os.path.join(base_dir, m.group("p"))):
                        edit = (i, 1, [f"{m.group('ind')}env_file:",
                                       f"{m.group('ind')}  - path: {m.group('p')}",
                                       f"{m.group('ind')}    required: false"], m.group("p"))
                    break
                # list form; `- path:` is ALREADY the long form — skipping it is what
                # keeps this loop from converting its own output forever.
                m2 = re.match(r"^(?P<ind>\s*)-\s*(?P<q>['\"]?)(?P<p>[^\s'\"#:]+)(?P=q)\s*(#.*)?$", l)
                if m2 and m2.group("p") != "path" and _in_env_file_block(lines, i, ki):
                    if not os.path.exists(os.path.join(base_dir, m2.group("p"))):
                        edit = (i, 1, [f"{m2.group('ind')}- path: {m2.group('p')}",
                                       f"{m2.group('ind')}  required: false"], m2.group("p"))
                        break
            if edit:
                break
        if not edit:
            break
        i, n, repl, what = edit
        res.change(rel, i + 1, "E1", lines[i].strip(), f"{what} (required: false)")
        lines[i:i + n] = repl

    spans = service_spans(lines)

    for span in spans:
        name = span[0]

        # T1 -------------------------------------------------------------
        pk, items = block(lines, span, "ports")
        primary_seen = False
        for j in items:
            l = lines[j]
            m = re.match(r"^(?P<pre>\s*-\s*)(?P<q>['\"]?)(?P<spec>[^'\"#\s]+)(?P=q)(?P<post>\s*(#.*)?)$", l)
            if not m:
                continue
            spec = m.group("spec")
            published, target, proto = parse_port(spec)
            if published is None or not target.isdigit():
                continue
            if "$" in published or not published.isdigit():
                continue                                   # already parameterized / a range
            var = portmap.get(published, (None,))[0] or var_name(
                repo.project, name, target, False, prefix=repo.ports.get("prefix"))
            head = spec.split(":")
            host_ip = head[0] if len(split_port(spec.rsplit("/", 1)[0] if "/" in spec else spec)) > 2 else None
            suffix = f"/{proto}" if proto != "tcp" and "/" in spec else ""
            new_spec = f"127.0.0.1:${{{var}:-{published}}}:{target}{suffix}"
            q = m.group("q") or '"'
            lines[j] = f"{m.group('pre')}{q}{new_spec}{q}{m.group('post')}"
            res.change(rel, j + 1, "T1", spec, new_spec)

        # T2 (environment values that hardcode a host port) ----------------
        _, env_items = block(lines, span, "environment")
        for j in env_items:
            l = lines[j]
            if l.lstrip().startswith("#"):
                continue
            new = _rewrite_port_refs(l, portmap)
            if new != l:
                res.change(rel, j + 1, "T2", l.strip(), new.strip())
                lines[j] = new

        # H1 / H2 --------------------------------------------------------
        hk, hitems = block(lines, span, "healthcheck")
        ii, ref = service_image(lines, span)
        img = norm_image(split_ref(ref)[0]) if ref else ""
        for j in hitems:
            l = lines[j]
            if l.lstrip().startswith("#"):
                continue
            if img == "qdrant/qdrant" and re.search(r"\bcurl\b", l) and l.lstrip().startswith("test:"):
                ind = l[: len(l) - len(l.lstrip())]
                new = f"{ind}test: [\"CMD-SHELL\", \"bash -c ':> /dev/tcp/127.0.0.1/6333'\"]"
                res.change(rel, j + 1, "H2", l.strip(), new.strip())
                lines[j] = new
                continue
            if re.search(r"inspect\s+ping", l) and "--timeout" not in l and " -t " not in l:
                new = re.sub(r"(inspect\s+ping)", r"\1 --timeout 8", l, count=1)
                res.change(rel, j + 1, "H2", l.strip(), new.strip())
                lines[j] = new
                l = new
            if "localhost" in l:
                new = l.replace("localhost", "127.0.0.1")
                res.change(rel, j + 1, "H1", l.strip(), new.strip())
                lines[j] = new

    # advisory ---------------------------------------------------------------
    for i, l in enumerate(lines):
        s = l.strip()
        if s.startswith("#"):
            continue
        if re.match(r"^image:\s*jekyll/jekyll", s) or re.match(r"^\s*image:\s*jekyll/jekyll", l):
            res.find(rel, i + 1, "abandoned-image",
                     "jekyll/jekyll is unmaintained (last release 2023); use ruby:<fleet> + bundle exec jekyll")
        if re.match(r"^\s*platform:\s*", l):
            res.find(rel, i + 1, "platform-pin",
                     "a platform: pin forces emulation on the other architecture")

    return "\n".join(lines)


def _ports_of(repo, lines, span):
    """[(published, target, proto, var)] for the numeric short-form ports."""
    out = []
    name = span[0]
    _, items = block(lines, span, "ports")
    reg_alloc = (repo.ports.get("services") or {}).get(name) or {}
    reg_debug = repo.ports.get("debug") or {}
    idx = 0
    for j in items:
        m = re.match(r"^\s*-\s*['\"]?(?P<spec>[^'\"#\s]+)['\"]?", lines[j])
        if not m or lines[j].lstrip().startswith("#"):
            continue
        published, target, proto = parse_port(m.group("spec"))
        if published is None or "$" in (published or "") or not (published or "").isdigit():
            idx += 1
            continue
        var = None
        for dname, d in reg_debug.items():
            if dname == name and str(d.get("container_port", 5678)) == str(target):
                var = d.get("var")
        if var is None and reg_alloc.get("var"):
            if idx == 0:
                var = reg_alloc["var"]
            elif idx == 1 and reg_alloc.get("livereload") is not None:
                var = reg_alloc["var"].replace("_PORT", "") + "_LIVERELOAD_PORT"
        if var is None:
            var = var_name(repo.project, name, target, primary=(idx == 0),
                           prefix=repo.ports.get("prefix"))
        out.append((published, target, proto, var))
        idx += 1
    return out


PORT_REF = re.compile(r"(?P<host>localhost|127\.0\.0\.1):(?P<port>\d{2,5})(?!\d)")


def _rewrite_port_refs(line, portmap):
    def sub(m):
        hit = portmap.get(m.group("port"))
        if not hit:
            return m.group(0)
        return f"{m.group('host')}:${{{hit[0]}:-{hit[1]}}}"
    return PORT_REF.sub(sub, line)


def rewrite_host_port_refs(text, portmap):
    """Public: rewrite `localhost:<port>` references using {port: (var, default)}."""
    return PORT_REF.sub(
        lambda m: (f"{m.group('host')}:${{{portmap[m.group('port')][0]}:-{portmap[m.group('port')][1]}}}"
                   if m.group("port") in portmap else m.group(0)), text)


# -- Dockerfile ---------------------------------------------------------------
ARG_LINE = re.compile(r"^(?P<pre>\s*ARG\s+)(?P<name>[A-Za-z_][A-Za-z0-9_]*)=(?P<q>['\"]?)(?P<val>[^\s'\"]*)(?P=q)\s*$")
COPY_LINE = re.compile(r"^(?P<pre>\s*COPY\s+)(?P<rest>.+)$", re.I)


def transform_dockerfile(repo, path, text, res):
    rel = repo.rel(path)
    lines = text.split("\n")
    stages, args = set(), {}

    for i, l in enumerate(lines):
        m = ARG_LINE.match(l)
        if m:
            args[m.group("name")] = i

    for i, l in enumerate(lines):
        m = FROM_LINE.match(l)
        if m:
            ref = m.group("ref")
            am = re.search(r"\s+AS\s+(\S+)", m.group("post"), re.I)
            name, tag = split_ref(ref)
            if name in stages or name.lower() == "scratch":
                if am:
                    stages.add(am.group(1))
                continue
            if tag and "$" in tag:
                # FROM ruby:$RUBY_VERSION-slim — the version lives in an ARG.
                am2 = re.match(r"^\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?(.*)$", tag)
                want = want_version(repo, name)
                if am2 and want and norm_image(name) not in repo.frozen_in(path) and am2.group(1) in args:
                    ai = args[am2.group(1)]
                    m2 = ARG_LINE.match(lines[ai])
                    if (m2 and re.match(r"^\d+(\.\d+){0,2}$", m2.group("val"))
                            and m2.group("val") != want
                            and ver_tuple(m2.group("val"))[:len(ver_tuple(want))] <= ver_tuple(want)):
                        res.change(rel, ai + 1, "I1", m2.group("val"), want)
                        lines[ai] = f"{m2.group('pre')}{m2.group('name')}={m2.group('q')}{want}{m2.group('q')}"
            else:
                pinned = is_pinned(lines, i)
                new = None if pinned else bump_ref(repo, ref, path)
                if new:
                    res.change(rel, i + 1, "I1", ref, new)
                    lines[i] = f"{m.group('pre')}{new}{m.group('post')}"
            if am:
                stages.add(am.group(1))

    # L1 — the fleet never commits lockfiles, so a COPY that requires one fails.
    for i, l in enumerate(lines):
        if l.lstrip().startswith("#"):
            continue
        m = COPY_LINE.match(l)
        if m:
            toks = m.group("rest").split()
            flags = [t for t in toks if t.startswith("--")]
            body = [t for t in toks if not t.startswith("--")]
            if len(body) >= 3:
                srcs, dest = body[:-1], body[-1]
                keep = [s for s in srcs
                        if not (os.path.basename(s) in LOCKFILES and not repo.has_file(os.path.basename(s)))]
                if keep and len(keep) != len(srcs):
                    new = f"{m.group('pre')}{' '.join(flags + keep + [dest])}"
                    res.change(rel, i + 1, "L1", l.strip(), new.strip())
                    lines[i] = new
        if re.search(r"\bnpm ci\b", l) and not repo.has_file("package-lock.json") \
                and not repo.has_file("npm-shrinkwrap.json"):
            new = re.sub(r"\bnpm ci\b", "npm install", l)
            res.change(rel, i + 1, "L1", l.strip(), new.strip())
            lines[i] = new

    # advisory ---------------------------------------------------------------
    body = "\n".join(lines)
    froms = [l for l in lines if FROM_LINE.match(l)]
    if not re.search(r"^\s*USER\s+(?!root\b)\S+", body, re.M | re.I):
        res.find(rel, 1, "root-user", "runs as root — add a non-root USER (UPS-REPO-31)")
    if len(froms) == 1:
        res.find(rel, 1, "single-stage", "single-stage build (UPS-REPO-31 asks for multi-stage)")
    dev_only = "dev" in os.path.basename(path).lower() or ".devcontainer" in rel
    if not re.search(r"^\s*HEALTHCHECK\b", body, re.M | re.I) and not dev_only:
        res.find(rel, 1, "no-healthcheck", "no HEALTHCHECK (UPS-REPO-31)")
    return "\n".join(lines)


RUNTIME_IMAGES = {"python": "python", "node": "node", "ruby": "ruby"}


def exact_pins(repo):
    """Exact dependency pins the always-latest policy would have removed.

    A runtime bump on top of a stale exact pin is how barodybroject broke:
    psycopg2-binary==2.9.10 has no Python 3.14 wheel, the newest release does.
    Reported, not auto-fixed — unpinning is the deps-latest kit's job, and it must
    run FIRST (it also deletes lockfiles, which is what lets rule L1 fire).
    """
    hits = []
    for f in repo.files:
        b = os.path.basename(f)
        try:
            if b.startswith("requirements") and b.endswith(".txt"):
                for line in read_lines(f):
                    spec = line.split("#", 1)[0].strip()
                    if spec and not spec.startswith("-") and re.search(r"(?<![<>!~])===?\s*\d", spec):
                        hits.append(f"{repo.rel(f)}: {spec}")
            elif b == "package.json" and "node_modules" not in f:
                d = json.loads(read_text(f))
                for k in ("dependencies", "devDependencies"):
                    for name, spec in (d.get(k) or {}).items():
                        if isinstance(spec, str) and re.match(r"^=?\d+\.\d+\.\d+$", spec):
                            hits.append(f"{repo.rel(f)}: {name}@{spec}")
        except (OSError, ValueError):
            continue
    return hits


def dockerignore_targets(repo):
    """Build-context directories that have a Dockerfile but no .dockerignore.

    Docker resolves .dockerignore against the BUILD CONTEXT, not the Dockerfile's
    directory, so the file belongs beside the context root. The contexts come from
    each compose service's `build:`; a Dockerfile with no compose service falls
    back to its own directory.
    """
    contexts = set()
    claimed = set()
    for path in repo.compose:
        try:
            doc = yaml.safe_load(read_text(path)) or {}
        except yaml.YAMLError:
            continue
        base = os.path.dirname(path)
        for svc in (doc.get("services") or {}).values():
            b = (svc or {}).get("build")
            if not b:
                continue
            if isinstance(b, str):
                ctx, dockerfile = b, "Dockerfile"
            else:
                ctx = b.get("context", ".")
                dockerfile = b.get("dockerfile", "Dockerfile")
            if "$" in str(ctx):
                continue
            ctx_abs = os.path.normpath(os.path.join(base, str(ctx)))
            if os.path.isdir(ctx_abs):
                contexts.add(ctx_abs)
                claimed.add(os.path.normpath(os.path.join(ctx_abs, str(dockerfile))))
    for df in repo.dockerfiles:
        if os.path.normpath(df) not in claimed and not is_template(df):
            contexts.add(os.path.dirname(df))
    return sorted(c for c in contexts
                  if not os.path.exists(os.path.join(c, ".dockerignore")))


def run(root, project=None, write=False):
    project = project or os.path.basename(os.path.abspath(root))
    repo = Repo(root, project)
    res = Result()
    for path in repo.compose:
        text = read_text(path)
        try:
            new = transform_compose(repo, path, text, res)
        except Exception as exc:                            # never let one file abort the sweep
            res.find(repo.rel(path), 0, "error", f"skipped: {exc!r}")
            continue
        if write and new != text:
            write_text(path, new)
    # D1 — additive, so it never overwrites a repo's own .dockerignore.
    for ctx in dockerignore_targets(repo):
        rel = os.path.relpath(os.path.join(ctx, ".dockerignore"), repo.root)
        res.change(rel, 1, "D1", "(absent)", "seeded — .git/.env/caches excluded from the build context")
        if write:
            write_text(os.path.join(ctx, ".dockerignore"), DOCKERIGNORE)

    for path in repo.dockerfiles:
        text = read_text(path)
        new = transform_dockerfile(repo, path, text, res)
        if write and new != text:
            write_text(path, new)
    # advisory: what held a repo back, and what a runtime bump could break
    for img, (ver, why) in sorted(repo.held.items()):
        if any(norm_image(split_ref(image_ref_of(l, f) or "")[0]) == img
               for f in repo.compose + repo.dockerfiles for l in read_lines(f)):
            res.find(project, 0, "held-back", f"{img} held at {ver} (fleet target {load_images().get(img)}): {why}")
    if any(c.rule == "I1" and re.match(r"^(python|node|ruby)[:\d]", str(c.new)) or
           (c.rule == "I1" and re.match(r"^\d", str(c.new))) for c in res.changes):
        pins_found = exact_pins(repo)
        if pins_found:
            more = f" (+{len(pins_found) - 3} more)" if len(pins_found) > 3 else ""
            res.find(project, 0, "pinned-deps",
                     f"a runtime image was bumped while {len(pins_found)} exact dependency pin(s) remain "
                     f"({'; '.join(pins_found[:3])}{more}) — a pin can predate the new runtime. "
                     f"Run the deps-latest kit FIRST, then re-run docker (it is idempotent)")
    pins = sorted(repo.frozen_families)
    return res, pins


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def print_report(res, pins, verbose=True):
    by_rule = {}
    for c in res.changes:
        by_rule.setdefault(c.rule, []).append(c)
    for rule in sorted(by_rule):
        print(f"  [{rule}] {len(by_rule[rule])} change(s)")
        if verbose:
            for c in by_rule[rule]:
                print(f"      {c.file}:{c.line}  {c.old}  ->  {c.new}")
    if pins:
        print(f"  deliberately pinned (left alone): {', '.join(pins)}")
    adv = {}
    for f in res.findings:
        adv.setdefault(f.kind, []).append(f)
    for kind in sorted(adv):
        print(f"  ! {kind}: {len(adv[kind])}")
        if verbose:
            for f in adv[kind][:6]:
                print(f"      {f.file}:{f.line}  {f.msg}")
            if len(adv[kind]) > 6:
                print(f"      … +{len(adv[kind]) - 6} more")


def cmd_audit(args):
    res, pins = run(args.dir, args.project, write=False)
    if args.json:
        print(json.dumps({"changes": [c.as_dict() for c in res.changes],
                          "findings": [f.as_dict() for f in res.findings],
                          "pinned": pins}, indent=2))
    else:
        print_report(res, pins)
        if not res.changes:
            print("  ✓ nothing to harmonize")
    return 0


def cmd_apply(args):
    res, pins = run(args.dir, args.project, write=True)
    print_report(res, pins, verbose=not args.quiet)
    if not res.changes:
        print("  ✓ already harmonized")
    return 0


def cmd_check(args):
    res, _ = run(args.dir, args.project, write=False)
    for c in res.changes:
        print(f"  ✗ {c.file}:{c.line} [{c.rule}] {c.old} -> {c.new}")
    # A file the transformer could not process is a FAILURE, not a pass. run()
    # deliberately swallows per-file exceptions so one bad file cannot abort a
    # fleet sweep; without this, that swallow reads as conformance.
    errors = [f for f in res.findings if f.kind == "error"]
    for f in errors:
        print(f"  ✗ {f.file}: {f.msg}")
    return 1 if (res.changes or errors) else 0


def cmd_tags(_args):
    """Do the registry's versions resolve upstream?

    Distinguishes "no such manifest" (the tag genuinely does not exist) from a
    registry hiccup or rate limit — an earlier cut reported python:3.14 missing
    because Docker Hub throttled the lookup, which would have sent someone
    hunting for a typo that was not there.
    """
    images = load_images()
    missing = unverified = 0
    for image, ver in sorted(images.items()):
        found, absent, errored = [], [], []
        for t in (ver, f"{ver}-alpine", f"{ver}-slim"):
            r = subprocess.run(["docker", "manifest", "inspect", f"{image}:{t}"],
                               capture_output=True, text=True)
            if r.returncode == 0:
                found.append(t)
            elif re.search(r"no such manifest|not found|manifest unknown", r.stderr, re.I):
                absent.append(t)
            else:
                errored.append(t)
        if found:
            print(f"  ✓ {image}:{ver}  ({', '.join(found)})")
        elif errored and not absent:
            print(f"  ? {image}:{ver}  could not verify (registry error) — retry")
            unverified += 1
        else:
            print(f"  ✗ {image}:{ver}  no such tag upstream")
            missing += 1
    return 1 if missing else 0


def cmd_fleet(args):
    rows = []
    total = 0
    for name in sorted(os.listdir(os.path.join(HUB, "projects"))):
        d = os.path.join(HUB, "projects", name)
        if not os.path.isdir(d):
            continue
        repo_files = [f for f in walk(d) if is_compose(f) or is_dockerfile(f)]
        if not repo_files:
            continue
        res, pins = run(d, name, write=False)
        rows.append((name, len(res.changes), len(res.findings), pins))
        total += len(res.changes)
    if args.summary:
        # "<pending changes> <repos with any>" — for the drift gate to read.
        print(f"{total} {sum(1 for _, c, _, _ in rows if c)}")
        return 0
    if args.json:
        print(json.dumps([{"project": n, "changes": c, "findings": f, "pinned": p}
                          for n, c, f, p in rows], indent=2))
        return 0
    print(f"  {'PROJECT':24} {'CHANGES':>8} {'ADVISORY':>9}  PINNED")
    for n, c, f, p in rows:
        print(f"  {n:24} {c:>8} {f:>9}  {', '.join(p)}")
    print(f"\n  {total} change(s) across {len(rows)} docker-bearing repo(s)")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Harmonize Docker configuration to the fleet standard")
    sub = ap.add_subparsers(dest="cmd")
    for name in ("audit", "apply", "check"):
        p = sub.add_parser(name)
        p.add_argument("dir", nargs="?", default=".")
        p.add_argument("--project", help="project key in _data/ports.yml (default: directory name)")
        if name == "audit":
            p.add_argument("--json", action="store_true")
        if name == "apply":
            p.add_argument("--quiet", action="store_true")
    sub.add_parser("tags")
    f = sub.add_parser("fleet")
    f.add_argument("--json", action="store_true")
    f.add_argument("--summary", action="store_true", help='print "<changes> <repos>" only')
    args = ap.parse_args()
    fn = {"audit": cmd_audit, "apply": cmd_apply, "check": cmd_check,
          "tags": cmd_tags, "fleet": cmd_fleet}.get(args.cmd)
    if not fn:
        ap.print_help()
        return 0
    return fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
