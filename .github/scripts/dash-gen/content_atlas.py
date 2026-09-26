#!/usr/bin/env python3
"""
content_atlas — CONTENT OBSERVABILITY and EDITORIAL DIRECTION for the fleet's
content sites (lifehacker.dev, it-journey, bash-365.com, irony-works, …).

The other planes of the local stack watch the MACHINERY: workflow runs, agent
cost, logs, traces. None of them can answer the questions a CMS owner asks —
what does this site actually publish, about what, how fresh is it, which
topics are growing and which were abandoned, and does the mix still match the
story the site is supposed to tell? This module answers those, and then closes
the loop the other way: it turns a human-approved editorial plan into
directives the sites' own content loops consume.

  sync     Locate each site declared in `_data/fleet.yml` `content.sites`
           (a sibling checkout, a checked-out submodule, or a blob-less clone
           cached under .dash-lake/content/), walk its Markdown, parse every
           document's front matter, measure the body (words, headings, links,
           wikilinks, images), attach git history (created / last touched /
           commit count, and the commit stream itself), and store it all in
           the local lake (.dash-lake/fleet.sqlite, tables `content_*`).
  report   The analysis, pure SQL + Python over the lake: per-site totals,
           collections, sections, authors, top topics, the publishing
           timeline, the commit cadence (human vs bot), aging buckets, stale
           and thin documents, front-matter hygiene, PILLAR COVERAGE against
           the editorial plan, the cross-site topic overlap, and the ranked
           SUGGESTIONS. `--json` is the console's /api/content document.
  plan     Show or change the editorial plan (`_data/editorial.yml`):
           approve / reject a suggestion, add a directive, move a directive
           through its states, set a site's narrative or a pillar's target.
           Comments are preserved (ruamel round-trip); the COMMIT stays human.
  brief    The editorial brief for one site — narrative, pillars with their
           coverage, and the approved directives — as Markdown, for a site's
           content loop or a human writer.
  file     Deliver approved directives: one GitHub issue per directive in the
           site's own repo, labelled `editorial:directive`, deduped on a hidden
           marker. DRY RUN unless --apply; the plan records `filed` + the URL.

Design rules, same as every dash-gen module: the analysis half is pure and
fixture-tested (test_content_atlas.py); the network half (clone, gh) degrades
instead of crashing; the lake is gitignored because it is a cache of other
repos, while the editorial PLAN is committed — it is a decision, and decisions
belong in review. Nothing here writes to a content repo except `file --apply`,
and that writes an issue, never a commit: the site's own loop and a human
still decide what ships.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("content_atlas requires PyYAML: pip install pyyaml\n")
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parents[3]
FLEET_DEFAULT = REPO_ROOT / "_data" / "fleet.yml"
REGISTRY_DEFAULT = REPO_ROOT / "_data" / "projects.yml"
PLAN_DEFAULT = Path(os.environ.get("DASH_EDITORIAL_PLAN") or (REPO_ROOT / "_data" / "editorial.yml"))
LAKE_DIR_DEFAULT = Path(os.environ.get("DASH_LAKE_DIR") or (REPO_ROOT / ".dash-lake"))
DB_NAME = "fleet.sqlite"          # the ONE lake file; these tables sit beside fleet_lake's
PLAN_SCHEMA = "editorial/v1"
MARKER = "editorial-directive"    # <!-- editorial-directive key=… site=… -->

DIRECTIVE_STATES = ("proposed", "approved", "rejected", "filed", "done")
DIRECTIVE_KINDS = ("write", "refresh", "fix", "hold", "pillar", "cadence")
# Legal transitions. `rejected` and `done` are terminal but reopenable to
# `proposed`, so a decision is always reversible from the console.
TRANSITIONS = {
    "proposed": {"approved", "rejected"},
    "approved": {"proposed", "rejected", "filed", "done"},
    "filed": {"done", "approved"},
    "rejected": {"proposed"},
    "done": {"proposed"},
}

DEFAULTS = {
    "search_roots": ["..", "projects"],
    "cache_dir": ".dash-lake/content",
    "history_days": 730,
    "recent_days": 90,
    "cadence_days": 30,
    "stale_days": 365,
    "aging_buckets": [30, 90, 180, 365],
    "exclude": [".git", "node_modules", "vendor", "_site", ".jekyll-cache", ".github", ".claude",
                ".cms", ".quests", "test", "tests", "TODO", "tmp", "work", "_includes", "_layouts",
                "_sass", "_data", "assets"],
    "exclude_files": ["README.md", "CHANGELOG.md", "CLAUDE.md", "AGENTS.md", "SCHEMA.md", "LICENSE.md",
                      "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "SECURITY.md"],
    "quality": {"min_words": 250, "description": [50, 160], "require": ["title", "description", "date", "tags"]},
    "suggest": {"gap_ratio": 0.5, "over_ratio": 1.75, "unmapped_share": 0.3, "refresh_top": 3, "top_tags": 8},
    "directives": {"label": "editorial:directive", "color": "5319e7",
                   "label_description": "Editorial direction from the bamr87 content atlas"},
}

BOT_RX = re.compile(r"\[bot\]|github-actions|dependabot|^claude$|claude\[bot\]|renovate", re.I)
FM_RX = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|\Z)", re.S)
DATE_PREFIX_RX = re.compile(r"^(\d{4}-\d{2}-\d{2})-")
FENCE_RX = re.compile(r"^(```|~~~).*?^\1", re.S | re.M)
LIQUID_RX = re.compile(r"\{%.*?%\}|\{\{.*?\}\}", re.S)
HTML_RX = re.compile(r"<[^>]+>")
WORD_RX = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’-]*")
HEADING_RX = re.compile(r"^#{1,6}\s+\S", re.M)
MDLINK_RX = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)")
IMG_RX = re.compile(r"!\[[^\]]*\]\(|<img\s", re.I)
WIKILINK_RX = re.compile(r"\[\[[^\]]+\]\]")
TEXT_RX = re.compile(r"^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]*$")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS content_sites (
  site TEXT PRIMARY KEY, repo TEXT, live_url TEXT, source TEXT, path TEXT, head TEXT,
  synced_at TEXT, docs INTEGER, skipped INTEGER, error TEXT);
CREATE TABLE IF NOT EXISTS content_docs (
  site TEXT, path TEXT, collection TEXT, section TEXT, layout TEXT, title TEXT, description TEXT,
  author TEXT, date TEXT, lastmod TEXT, git_created TEXT, git_modified TEXT, commits INTEGER,
  updated TEXT, words INTEGER, headings INTEGER, links INTEGER, wikilinks INTEGER, images INTEGER,
  has_preview INTEGER, draft INTEGER, tags TEXT, categories TEXT, issues TEXT, sha TEXT,
  PRIMARY KEY (site, path));
CREATE TABLE IF NOT EXISTS content_commits (
  site TEXT, sha TEXT, date TEXT, author TEXT, bot INTEGER, files INTEGER, content_files INTEGER,
  subject TEXT, PRIMARY KEY (site, sha));
"""


# --------------------------------------------------------------------------- #
# CONTRACT + PLAN
# --------------------------------------------------------------------------- #
def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_yaml(path: Path):
    try:
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except FileNotFoundError:
        return None


def load_contract(fleet_path: Path | str = FLEET_DEFAULT, registry_path: Path | str = REGISTRY_DEFAULT) -> dict:
    """fleet.yml `content:` merged over DEFAULTS, with each site resolved
    against the registry (repo, live url) so the contract only has to name
    what the registry does not already know."""
    fleet = load_yaml(Path(fleet_path)) or {}
    block = fleet.get("content") or {}
    contract = _merge(DEFAULTS, {k: v for k, v in block.items() if k != "sites"})
    registry = {p.get("name"): p for p in (load_yaml(Path(registry_path)) or []) if isinstance(p, dict)}
    sites = []
    for raw in block.get("sites") or []:
        if isinstance(raw, str):
            raw = {"name": raw}
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        reg = registry.get(raw.get("registry") or name) or {}
        repo = raw.get("repo") or _nwo(reg.get("repo_url") or "")
        sites.append({
            "name": name,
            "repo": repo,
            "registry": raw.get("registry") or (name if reg else None),
            "submodule_path": reg.get("submodule_path"),
            "live_url": raw.get("live_url") or reg.get("live_url"),
            "branch": raw.get("branch") or reg.get("branch") or "main",
            "roots": list(raw.get("roots") or []),
            "exclude": list(raw.get("exclude") or []),
            "checkout": raw.get("checkout"),
            "description": raw.get("description") or reg.get("description"),
            "quality": _merge(contract["quality"], raw.get("quality") or {}),
            # `git`: a document's publication date is its first commit, not its
            # front-matter `date` — for knowledge bases whose `date` is the
            # SUBJECT's date (a 2005 article dated 2005-03-14).
            "dates": raw.get("dates") if raw.get("dates") in ("frontmatter", "git") else "frontmatter",
        })
    contract["sites"] = sites
    return contract


def _nwo(url: str) -> str | None:
    m = re.search(r"github\.com[:/]+([^/]+/[^/.]+(?:\.[^/]+?)?)(?:\.git)?/?$", url or "")
    return m.group(1) if m else None


def load_plan(plan_path: Path | str = PLAN_DEFAULT) -> dict:
    plan = load_yaml(Path(plan_path)) or {}
    plan.setdefault("schema", PLAN_SCHEMA)
    plan.setdefault("sites", {})
    for site in (plan["sites"] or {}).values():
        if isinstance(site, dict):
            site.setdefault("pillars", [])
            site.setdefault("directives", [])
    return plan


def site_plan(plan: dict, site: str) -> dict:
    sp = (plan.get("sites") or {}).get(site) or {}
    return {"narrative": sp.get("narrative") or "", "audience": sp.get("audience") or "",
            "voice": sp.get("voice") or "",
            "pillars": [p for p in (sp.get("pillars") or []) if isinstance(p, dict)],
            "directives": [d for d in (sp.get("directives") or []) if isinstance(d, dict)]}


# --------------------------------------------------------------------------- #
# LOCATE — sibling checkout, submodule, or a cached blob-less clone
# --------------------------------------------------------------------------- #
def _run(argv: list[str], cwd: Path | None = None, timeout: int = 300, stdin: str | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(argv, cwd=str(cwd) if cwd else None, input=stdin, capture_output=True,
                           text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, f"{exc.__class__.__name__}: {exc}"


def _is_repo(path: Path) -> bool:
    return (path / ".git").exists() and any(path.iterdir())


def locate(site: dict, contract: dict, fetch: bool = True, repo_root: Path = REPO_ROOT) -> tuple[Path | None, str]:
    """Where to read the site from, and how it got there.

    Order: an explicit `checkout:`; a sibling/extra checkout named after the
    repo under any `search_roots` entry (DASH_CONTENT_ROOTS prepends to it);
    the checked-out submodule; finally a clone cached in the lake. A local
    checkout is read AS IS — it may carry the operator's uncommitted drafts,
    which is exactly what an editor wants to see.
    """
    candidates: list[Path] = []
    if site.get("checkout"):
        candidates.append((repo_root / site["checkout"]).resolve())
    roots = [r for r in (os.environ.get("DASH_CONTENT_ROOTS") or "").split(os.pathsep) if r]
    roots += list(contract.get("search_roots") or [])
    names = [n for n in {site["name"], (site.get("repo") or "").split("/")[-1], site.get("registry")} if n]
    for root in roots:
        base = (repo_root / root).resolve() if not os.path.isabs(root) else Path(root)
        candidates += [base / n for n in names]
    if site.get("submodule_path"):
        candidates.append(repo_root / site["submodule_path"])
    for c in candidates:
        if c.is_dir() and _is_repo(c) and c.resolve() != repo_root.resolve():
            return c, "checkout"
    cache = (repo_root / contract.get("cache_dir", DEFAULTS["cache_dir"]) / site["name"]).resolve()
    if _is_repo(cache):
        if fetch:
            rc, out = _run(["git", "-C", str(cache), "fetch", "--quiet", "origin", site["branch"]])
            if rc == 0:
                _run(["git", "-C", str(cache), "reset", "--quiet", "--hard", "FETCH_HEAD"])
        return cache, "cache"
    if not fetch or not site.get("repo"):
        return None, "missing"
    cache.parent.mkdir(parents=True, exist_ok=True)
    # --filter=blob:none keeps the WHOLE history (trees + commits, which is
    # what aging needs) while fetching only the blobs of the checked-out tree.
    rc, out = _run(["git", "clone", "--quiet", "--filter=blob:none", "--branch", site["branch"],
                    f"https://github.com/{site['repo']}.git", str(cache)], timeout=900)
    if rc != 0:
        return None, "clone failed: " + out.strip().splitlines()[-1][:200] if out.strip() else "clone failed"
    return cache, "clone"


# --------------------------------------------------------------------------- #
# EXTRACT — pure functions over a tree (fixture-tested)
# --------------------------------------------------------------------------- #
def parse_front_matter(text: str) -> tuple[dict | None, str, str | None]:
    """(front matter, body, error). None front matter = not a Jekyll document."""
    m = FM_RX.match(text)
    if not m:
        return None, text, None
    body = text[m.end():]
    try:
        fm = yaml.safe_load(m.group(1))
    except yaml.YAMLError as exc:
        return {}, body, f"front matter is not valid YAML: {str(exc).splitlines()[0][:120]}"
    if fm is None:
        fm = {}
    if not isinstance(fm, dict):
        return {}, body, "front matter is not a mapping"
    return fm, body, None


def to_date(value) -> str | None:
    """Any front-matter / git date → ISO 'YYYY-MM-DD', or None."""
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    m = re.match(r"\s*['\"]?(\d{4})-(\d{1,2})-(\d{1,2})", str(value))
    if not m:
        return None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


def as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [v for v in re.split(r"[,\s]+", value) if v] if "," in value or " " in value.strip() else [value]
    if not isinstance(value, (list, tuple)):
        value = [value]
    out = []
    for v in value:
        t = re.sub(r"\s+", "-", str(v).strip().lower())
        if t and t not in out:
            out.append(t)
    return out


def measure(body: str) -> dict:
    prose = FENCE_RX.sub(" ", body)
    prose = LIQUID_RX.sub(" ", prose)
    links = MDLINK_RX.findall(prose)
    text = HTML_RX.sub(" ", prose)
    return {
        "words": len(WORD_RX.findall(re.sub(r"\]\([^)]*\)", "]", text))),
        "headings": len(HEADING_RX.findall(prose)),
        "links": len(links),
        "wikilinks": len(WIKILINK_RX.findall(prose)),
        "images": len(IMG_RX.findall(prose)),
    }


def classify(rel: Path, fm: dict) -> tuple[str, str]:
    """(collection, section) from the path, the Jekyll way.

    A `_name` segment is a collection (pages/_posts/hacks/x.md → posts, hacks);
    without one the first directory under the scan root is the collection
    (vault/forms/x.md → forms). Section is the next directory, else the first
    category, else the front matter's `section`/`type`.
    """
    parts = list(rel.parts[:-1])
    coll_idx = next((i for i, p in enumerate(parts) if p.startswith("_") and len(p) > 1), None)
    if coll_idx is not None:
        collection = parts[coll_idx][1:]
        rest = parts[coll_idx + 1:]
    else:
        collection = parts[0] if parts else "pages"
        rest = parts[1:]
    cats = as_list(fm.get("categories") or fm.get("category"))
    section = (rest[0] if rest else None) or fm.get("section") or (cats[0] if cats else None) \
        or fm.get("type") or fm.get("genus") or collection
    return str(collection).lower(), str(section).lower()


def doc_issues(fm: dict, m: dict, quality: dict, error: str | None) -> list[str]:
    issues = []
    if error:
        issues.append("frontmatter-invalid")
    require = quality.get("require") or []
    for key in require:
        v = fm.get(key)
        if key == "date" and not v:
            continue  # judged below: a filename date prefix also counts
        if v in (None, "", [], {}):
            issues.append(f"missing-{key}")
    desc = str(fm.get("description") or "")
    lo, hi = (quality.get("description") or [0, 10 ** 6])[:2]
    if desc and not lo <= len(desc) <= hi:
        issues.append("description-length")
    if m["words"] < int(quality.get("min_words") or 0):
        issues.append("thin")
    return issues


def _excluded(rel: Path, patterns: list[str], files: list[str]) -> bool:
    if rel.name in files:
        return True
    s = rel.as_posix()
    for pat in patterns:
        pat = pat.rstrip("/")
        if any(part == pat for part in rel.parts[:-1]) or fnmatch.fnmatch(s, pat) or s.startswith(pat + "/"):
            return True
    return False


def scan_roots(tree: Path, site: dict) -> list[Path]:
    """Explicit `roots:`, else the Jekyll collections_dir (plus any loose
    top-level pages), else the whole tree."""
    if site.get("roots"):
        return [tree / r for r in site["roots"] if (tree / r).exists()]
    cfg = load_yaml(tree / "_config.yml") or {}
    cdir = cfg.get("collections_dir") if isinstance(cfg, dict) else None
    if cdir and (tree / cdir).is_dir():
        return [tree / cdir]
    return [tree]


def config_excludes(tree: Path) -> list[str]:
    cfg = load_yaml(tree / "_config.yml") or {}
    ex = cfg.get("exclude") if isinstance(cfg, dict) else None
    return [str(e) for e in ex] if isinstance(ex, list) else []


def scan_tree(tree: Path, site: dict, contract: dict) -> tuple[list[dict], int]:
    """Every Jekyll document under the site's roots → rows (no git yet).
    Returns (docs, skipped): files without front matter are not documents."""
    quality = site.get("quality") or contract.get("quality") or DEFAULTS["quality"]
    # _config.yml's exclude list describes what JEKYLL builds; a site whose
    # content reaches the build another way (irony-works: vault/ → transplant
    # → _entries/) names explicit roots, and then its own exclude is moot.
    patterns = list(contract.get("exclude") or []) + ([] if site.get("roots") else config_excludes(tree)) \
        + list(site.get("exclude") or [])
    files = list(contract.get("exclude_files") or [])
    docs, skipped, seen = [], 0, set()
    for root in scan_roots(tree, site):
        for path in sorted(root.rglob("*")):
            if path.suffix.lower() not in (".md", ".markdown") or not path.is_file():
                continue
            rel = path.relative_to(tree)
            if rel in seen or _excluded(rel, patterns, files):
                continue
            seen.add(rel)
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                skipped += 1
                continue
            fm, body, error = parse_front_matter(text)
            if fm is None:
                skipped += 1
                continue
            m = measure(body)
            scan_rel = path.relative_to(root) if root != tree else rel
            collection, section = classify(scan_rel, fm)
            fdate = DATE_PREFIX_RX.match(path.name)
            date = to_date(fm.get("date") or fm.get("planted") or fm.get("created")) or (fdate.group(1) if fdate else None)
            issues = doc_issues(fm, m, quality, error)
            if "date" in (quality.get("require") or []) and not date:
                issues.append("missing-date")
            published = fm.get("published")
            docs.append({
                "path": rel.as_posix(), "collection": collection, "section": section,
                "layout": str(fm.get("layout") or ""),
                "title": str(fm.get("title") or path.stem)[:300],
                "description": str(fm.get("description") or fm.get("excerpt") or "")[:500],
                "author": str(fm.get("author") or "") if not isinstance(fm.get("author"), (list, dict)) else
                          str((fm.get("author") or [""])[0] if isinstance(fm.get("author"), list) else ""),
                "date": date,
                "lastmod": to_date(fm.get("lastmod") or fm.get("last_modified_at") or fm.get("updated")),
                "has_preview": int(bool(fm.get("preview") or fm.get("image") or fm.get("header"))),
                "draft": int(bool(fm.get("draft")) or published is False),
                "tags": as_list(fm.get("tags")),
                "categories": as_list(fm.get("categories") or fm.get("category")),
                "issues": issues,
                "sha": hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:12],
                **m,
            })
    return docs, skipped


def git_history(tree: Path, since_days: int, now: dt.date | None = None) -> tuple[dict, list[dict]]:
    """One `git log` pass → ({path: {created, modified, commits}}, commits).

    Newest first, so the first time a path is seen is its last modification
    and the last time is the oldest commit INSIDE the window — `created` is a
    floor, not a birth date, for anything older than history_days.
    """
    now = now or dt.date.today()
    since = (now - dt.timedelta(days=since_days)).isoformat()
    rc, out = _run(["git", "-C", str(tree), "log", "--no-merges", f"--since={since}",
                    "--format=%x1e%H%x1f%cI%x1f%an%x1f%s", "--name-only", "--no-renames"], timeout=600)
    files: dict[str, dict] = {}
    commits: list[dict] = []
    if rc != 0:
        return files, commits
    # A shallow clone's boundary commit "adds" every file in the tree, which
    # would date the whole site to the day of the clone. Skip those commits;
    # files they alone touched fall back to their front-matter dates.
    boundary = set()
    shallow = tree / ".git" / "shallow"
    if shallow.is_file():
        boundary = {ln.strip() for ln in shallow.read_text().splitlines() if ln.strip()}
    for chunk in out.split("\x1e"):
        if not chunk.strip():
            continue
        head, _, rest = chunk.partition("\n")
        parts = head.split("\x1f")
        if len(parts) < 4:
            continue
        sha, date, author, subject = parts[0], to_date(parts[1]), parts[2], parts[3]
        if sha in boundary:
            continue
        names = [n.strip() for n in rest.splitlines() if n.strip()]
        commits.append({"sha": sha, "date": date, "author": author, "bot": int(bool(BOT_RX.search(author))),
                        "files": len(names), "paths": names, "subject": subject[:200]})
        for n in names:
            rec = files.setdefault(n, {"modified": date, "created": date, "commits": 0})
            rec["created"] = date
            rec["commits"] += 1
    return files, commits


# --------------------------------------------------------------------------- #
# STORE
# --------------------------------------------------------------------------- #
def connect(lake_dir: Path | str | None = None, create: bool = True) -> sqlite3.Connection:
    d = Path(lake_dir) if lake_dir else LAKE_DIR_DEFAULT
    if create:
        d.mkdir(parents=True, exist_ok=True)
    elif not (d / DB_NAME).exists():
        raise FileNotFoundError(str(d / DB_NAME))
    conn = sqlite3.connect(str(d / DB_NAME))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    return conn


def store_site(conn: sqlite3.Connection, site: dict, source: str, tree: Path | None, docs: list[dict],
               history: dict, commits: list[dict], skipped: int, error: str | None = None,
               now: dt.datetime | None = None) -> None:
    """Replace the site's rows wholesale: a deleted page must disappear."""
    now = now or dt.datetime.now(dt.timezone.utc)
    head = None
    if tree is not None:
        rc, out = _run(["git", "-C", str(tree), "rev-parse", "--short", "HEAD"], timeout=10)
        head = out.strip() if rc == 0 else None
    doc_paths = {d["path"] for d in docs}
    with conn:
        conn.execute("DELETE FROM content_docs WHERE site = ?", (site["name"],))
        conn.execute("DELETE FROM content_commits WHERE site = ?", (site["name"],))
        for d in docs:
            h = history.get(d["path"]) or {}
            if site.get("dates") == "git" and h.get("created"):
                d = {**d, "date": h["created"]}
            updated = max([x for x in (d["date"], d["lastmod"], h.get("modified")) if x] or [None],
                          key=lambda x: x or "")
            conn.execute(
                "INSERT INTO content_docs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (site["name"], d["path"], d["collection"], d["section"], d["layout"], d["title"],
                 d["description"], d["author"], d["date"], d["lastmod"], h.get("created"), h.get("modified"),
                 h.get("commits", 0), updated, d["words"], d["headings"], d["links"], d["wikilinks"],
                 d["images"], d["has_preview"], d["draft"], json.dumps(d["tags"]), json.dumps(d["categories"]),
                 json.dumps(d["issues"]), d["sha"]))
        for c in commits:
            conn.execute("INSERT OR REPLACE INTO content_commits VALUES (?,?,?,?,?,?,?,?)",
                         (site["name"], c["sha"], c["date"], c["author"], c["bot"], c["files"],
                          sum(1 for p in c["paths"] if p in doc_paths), c["subject"]))
        conn.execute("INSERT OR REPLACE INTO content_sites VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (site["name"], site.get("repo"), site.get("live_url"), source,
                      str(tree) if tree else None, head, now.isoformat(timespec="seconds"),
                      len(docs), skipped, error))


def sync(contract: dict, lake_dir: Path | str | None = None, only: list[str] | None = None,
         fetch: bool = True, log=print) -> list[dict]:
    conn = connect(lake_dir)
    results = []
    for site in contract["sites"]:
        if only and site["name"] not in only and (site.get("repo") or "") not in only:
            continue
        tree, source = locate(site, contract, fetch=fetch)
        if tree is None:
            log(f"  ✖ {site['name']}: {source}")
            store_site(conn, site, source, None, [], {}, [], 0, error=source)
            results.append({"site": site["name"], "docs": 0, "source": source, "error": source})
            continue
        docs, skipped = scan_tree(tree, site, contract)
        history, commits = git_history(tree, int(contract.get("history_days") or 730))
        store_site(conn, site, source, tree, docs, history, commits, skipped)
        log(f"  ✓ {site['name']:<26} {len(docs):>5} docs  {len(commits):>5} commits  ({source}: {tree})")
        results.append({"site": site["name"], "docs": len(docs), "commits": len(commits), "source": source})
    return results


# --------------------------------------------------------------------------- #
# ANALYZE — pure over rows (fixture-tested)
# --------------------------------------------------------------------------- #
def _age(iso: str | None, today: dt.date) -> int | None:
    if not iso:
        return None
    try:
        return (today - dt.date.fromisoformat(iso[:10])).days
    except ValueError:
        return None


def _row(r: sqlite3.Row | dict) -> dict:
    d = dict(r)
    for k in ("tags", "categories", "issues"):
        if isinstance(d.get(k), str):
            try:
                d[k] = json.loads(d[k])
            except ValueError:
                d[k] = []
    return d


def load_rows(conn: sqlite3.Connection, site: str | None = None) -> tuple[list[dict], list[dict], list[dict]]:
    q = " WHERE site = ?" if site else ""
    args = (site,) if site else ()
    sites = [dict(r) for r in conn.execute("SELECT * FROM content_sites" + q + " ORDER BY site", args)]
    docs = [_row(r) for r in conn.execute("SELECT * FROM content_docs" + q, args)]
    commits = [dict(r) for r in conn.execute("SELECT * FROM content_commits" + q, args)]
    return sites, docs, commits


def pillar_matches(doc: dict, pillar: dict) -> bool:
    match = pillar.get("match") or {}
    topics = set(doc.get("tags") or []) | set(doc.get("categories") or [])
    if topics & set(as_list(match.get("tags"))) or set(doc.get("categories") or []) & set(as_list(match.get("categories"))):
        return True
    if doc.get("section") in as_list(match.get("sections")) or doc.get("collection") in as_list(match.get("collections")):
        return True
    if any(doc.get("path", "").startswith(str(p)) for p in (match.get("paths") or [])):
        return True
    hay = f"{doc.get('title', '')} {doc.get('description', '')}".lower()
    return any(str(k).lower() in hay for k in (match.get("keywords") or []))


def month_key(iso: str) -> str:
    return iso[:7]


def week_start(iso: str) -> str:
    d = dt.date.fromisoformat(iso[:10])
    return (d - dt.timedelta(days=d.weekday())).isoformat()


def analyze_site(site_row: dict, docs: list[dict], commits: list[dict], plan: dict, contract: dict,
                 today: dt.date) -> dict:
    """Everything the Content tab shows for one site, from its rows."""
    recent_days = int(contract.get("recent_days") or 90)
    stale_days = int(contract.get("stale_days") or 365)
    buckets = list(contract.get("aging_buckets") or DEFAULTS["aging_buckets"])
    live = [d for d in docs if not d.get("draft")]
    n = len(live)

    ages = [a for a in (_age(d.get("updated"), today) for d in live) if a is not None]
    labels = [f"≤{buckets[0]}d"] + [f"{buckets[i - 1] + 1}–{buckets[i]}d" for i in range(1, len(buckets))] + [f">{buckets[-1]}d"]
    aging = [0] * (len(buckets) + 1)
    for a in ages:
        aging[next((i for i, b in enumerate(buckets) if a <= b), len(buckets))] += 1

    published = [d for d in live if d.get("date")]
    recent = [d for d in published if (_age(d["date"], today) or 10 ** 6) <= recent_days]
    last_pub = max((d["date"] for d in published if d["date"] <= today.isoformat()), default=None)

    # Publishing timeline: the last 24 months by front-matter date.
    months = []
    y, m = today.year, today.month
    for _ in range(24):
        months.append(f"{y:04d}-{m:02d}")
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    months.reverse()
    by_month = Counter(month_key(d["date"]) for d in published)
    timeline = [{"month": k, "published": by_month.get(k, 0)} for k in months]

    # Commit cadence: the last 26 weeks, human vs bot, content-touching only.
    wk0 = dt.date.fromisoformat(week_start(today.isoformat()))
    weeks = [(wk0 - dt.timedelta(weeks=i)).isoformat() for i in range(25, -1, -1)]
    human, bot = Counter(), Counter()
    for c in commits:
        if not c.get("date") or not c.get("content_files"):
            continue
        (bot if c.get("bot") else human)[week_start(c["date"])] += 1
    cadence = [{"week": w, "human": human.get(w, 0), "bot": bot.get(w, 0)} for w in weeks]

    tag_count = Counter(t for d in live for t in (d.get("tags") or []))
    recent_tags = Counter(t for d in recent for t in (d.get("tags") or []))
    prior = [d for d in published if recent_days < (_age(d["date"], today) or 0) <= 2 * recent_days]
    prior_tags = Counter(t for d in prior for t in (d.get("tags") or []))
    topics = [{"tag": t, "docs": c, "recent": recent_tags.get(t, 0), "prior": prior_tags.get(t, 0),
               "trend": recent_tags.get(t, 0) - prior_tags.get(t, 0)} for t, c in tag_count.most_common(40)]
    rising = sorted((t for t in topics if t["trend"] > 0), key=lambda t: -t["trend"])[:8]
    fading = sorted((t for t in topics if t["trend"] < 0), key=lambda t: t["trend"])[:8]

    def group(key):
        out = defaultdict(lambda: {"docs": 0, "words": 0, "recent": 0, "stale": 0, "newest": None})
        for d in live:
            g = out[d.get(key) or "—"]
            g["docs"] += 1
            g["words"] += d.get("words") or 0
            g["recent"] += int(d in recent)
            a = _age(d.get("updated"), today)
            g["stale"] += int(a is not None and a > stale_days)
            if d.get("date") and (g["newest"] is None or d["date"] > g["newest"]):
                g["newest"] = d["date"]
        return sorted(({"name": k, **v} for k, v in out.items()), key=lambda r: -r["docs"])

    issue_count = Counter(i for d in live for i in (d.get("issues") or []))
    stale = sorted((d for d in live if (_age(d.get("updated"), today) or 0) > stale_days),
                   key=lambda d: d.get("updated") or "")
    authors = Counter((d.get("author") or "—") for d in live).most_common(12)

    sp = site_plan(plan, site_row["site"])
    pillars = []
    matched = set()
    for p in sp["pillars"]:
        if p.get("status", "active") == "retired":
            continue
        members = [d for d in live if pillar_matches(d, p)]
        matched |= {d["path"] for d in members}
        rec = [d for d in members if d in recent]
        newest = max((d["date"] for d in members if d.get("date")), default=None)
        share = len(members) / n if n else 0.0
        rshare = len(rec) / len(recent) if recent else 0.0
        target = p.get("target_share")
        pillars.append({
            "id": p.get("id"), "title": p.get("title") or p.get("id"), "status": p.get("status", "active"),
            "target_share": target, "docs": len(members), "share": round(share, 3),
            "recent": len(rec), "recent_share": round(rshare, 3), "newest": newest,
            "newest_age": _age(newest, today),
            "gap": round((target or 0) - rshare, 3) if target is not None else None,
        })
    unmapped = [d for d in live if d["path"] not in matched]
    unmapped_tags = Counter(t for d in unmapped for t in (d.get("tags") or [])).most_common(12)

    return {
        "site": site_row["site"], "repo": site_row.get("repo"), "live_url": site_row.get("live_url"),
        "source": site_row.get("source"), "head": site_row.get("head"), "synced_at": site_row.get("synced_at"),
        "error": site_row.get("error"), "skipped": site_row.get("skipped"),
        "totals": {
            "docs": n, "drafts": len(docs) - n, "words": sum(d.get("words") or 0 for d in live),
            "recent": len(recent), "recent_days": recent_days, "last_published": last_pub,
            "days_since_publish": _age(last_pub, today),
            "median_age": sorted(ages)[len(ages) // 2] if ages else None,
            "stale": len(stale), "stale_share": round(len(stale) / n, 3) if n else 0.0,
            "with_issues": sum(1 for d in live if d.get("issues")),
            "commits": sum(1 for c in commits if c.get("content_files")),
            "bot_share": round(sum(1 for c in commits if c.get("content_files") and c.get("bot"))
                               / max(1, sum(1 for c in commits if c.get("content_files"))), 3),
            "tags": len(tag_count),
        },
        "aging": [{"bucket": labels[i], "docs": aging[i]} for i in range(len(aging))],
        "timeline": timeline, "cadence": cadence,
        "collections": group("collection"), "sections": group("section"),
        "authors": [{"author": a, "docs": c} for a, c in authors],
        "topics": topics, "rising": rising, "fading": fading,
        "issues": [{"issue": k, "docs": v} for k, v in issue_count.most_common()],
        "stale_docs": [_brief_doc(d, today) for d in stale[:25]],
        "narrative": sp["narrative"], "audience": sp["audience"], "voice": sp["voice"],
        "pillars": pillars,
        "unmapped": {"docs": len(unmapped), "share": round(len(unmapped) / n, 3) if n else 0.0,
                     "top_tags": [{"tag": t, "docs": c} for t, c in unmapped_tags]},
        "directives": sp["directives"],
    }


def _brief_doc(d: dict, today: dt.date) -> dict:
    return {"path": d["path"], "title": d.get("title"), "collection": d.get("collection"),
            "section": d.get("section"), "date": d.get("date"), "updated": d.get("updated"),
            "age": _age(d.get("updated"), today), "words": d.get("words"), "issues": d.get("issues") or []}


def suggestions(a: dict, contract: dict, today: dt.date) -> list[dict]:
    """Deterministic editorial suggestions for one analyzed site, each with a
    STABLE key so a human's approve/reject sticks across re-syncs. Keys the
    plan already carries (any state) are not re-suggested."""
    cfg = _merge(DEFAULTS["suggest"], contract.get("suggest") or {})
    stale_days = int(contract.get("stale_days") or 365)
    cadence_days = int(contract.get("cadence_days") or 30)
    t = a["totals"]
    out: list[dict] = []

    def add(key, kind, priority, title, brief, **extra):
        out.append({"key": key, "kind": kind, "priority": priority, "title": title, "brief": brief, **extra})

    if t["docs"] and (t["days_since_publish"] is None or t["days_since_publish"] > cadence_days):
        add("cadence", "cadence", "P1", "Resume publishing",
            f"Nothing new has been published for {t['days_since_publish'] or 'an unknown number of'} days "
            f"(cadence target: {cadence_days}). Queue the next piece from the highest-gap pillar.")
    for p in a["pillars"]:
        if p["status"] != "active":
            continue
        tgt = p.get("target_share")
        if tgt:
            if p["recent_share"] < tgt * cfg["gap_ratio"]:
                add(f"pillar-gap:{p['id']}", "write", "P1" if p["recent"] == 0 else "P2",
                    f"Publish on “{p['title']}”",
                    f"Pillar target is {round(tgt * 100)}% of new work; the last {t['recent_days']} days "
                    f"delivered {round(p['recent_share'] * 100)}% ({p['recent']} of {t['recent']}). "
                    f"At the current volume that is a gap of {max(1, round(tgt * max(t['recent'], 4)) - p['recent'])} piece(s).",
                    pillar=p["id"])
            elif p["recent"] >= 3 and p["recent_share"] > tgt * cfg["over_ratio"]:
                add(f"pillar-over:{p['id']}", "hold", "P3", f"Rest “{p['title']}” for a cycle",
                    f"{round(p['recent_share'] * 100)}% of recent work against a {round(tgt * 100)}% target — "
                    "the mix is drifting toward this pillar at the others' expense.", pillar=p["id"])
        if p["docs"] and (p["newest_age"] or 0) > stale_days:
            add(f"pillar-stale:{p['id']}", "refresh", "P2", f"Refresh “{p['title']}”",
                f"The newest piece in this pillar is {p['newest_age']} days old. Update the strongest one "
                "or publish a successor.", pillar=p["id"])
    if not a["pillars"] and t["docs"]:
        tags = ", ".join(x["tag"] for x in a["topics"][:cfg["top_tags"]])
        add("define-pillars", "pillar", "P1", "Define this site's content pillars",
            f"No editorial pillars are declared, so coverage cannot be judged. The observed top topics are: {tags}.")
    elif a["unmapped"]["share"] > cfg["unmapped_share"] and a["unmapped"]["docs"] >= 5:
        tags = ", ".join(x["tag"] for x in a["unmapped"]["top_tags"][:cfg["top_tags"]])
        add("unmapped", "pillar", "P2", "Map the orphan topics",
            f"{round(a['unmapped']['share'] * 100)}% of documents match no pillar. Their top tags: {tags}. "
            "Either extend a pillar's match or declare a new one.")
    min_words = int((a.get("quality") or contract.get("quality") or {}).get("min_words") or 0)
    for d in [d for d in a["stale_docs"] if (d.get("words") or 0) >= min_words][:cfg["refresh_top"]]:
        add(f"refresh:{d['path']}", "refresh", "P3", f"Refresh “{d['title']}”",
            f"Last updated {d['updated']} ({d['age']} days). Re-verify facts, commands and links; bump lastmod.",
            path=d["path"])
    for iss in a["issues"]:
        if iss["issue"] in ("missing-description", "missing-tags", "frontmatter-invalid", "description-length",
                            "missing-title", "missing-date"):
            add(f"hygiene:{iss['issue']}", "fix", "P2" if iss["issue"] == "frontmatter-invalid" else "P3",
                f"Fix {iss['docs']} document(s): {iss['issue'].replace('-', ' ')}",
                "Mechanical front-matter repair — the site's own normalizer or CMS lane can batch it.")
    known = {d.get("key") for d in a["directives"]}
    rank = {"P1": 0, "P2": 1, "P3": 2}
    return sorted((s for s in out if s["key"] not in known), key=lambda s: (rank[s["priority"]], s["key"]))


def overlap(docs: list[dict], min_sites: int = 2, limit: int = 30) -> list[dict]:
    """Topics several sites cover — where sister sites can cross-link, or
    where two narratives are competing for the same reader."""
    per = defaultdict(Counter)
    for d in docs:
        if d.get("draft"):
            continue
        for t in d.get("tags") or []:
            per[t][d["site"]] += 1
    rows = [{"tag": t, "sites": dict(c), "total": sum(c.values())} for t, c in per.items() if len(c) >= min_sites]
    return sorted(rows, key=lambda r: (-len(r["sites"]), -r["total"]))[:limit]


def report(conn: sqlite3.Connection, contract: dict, plan: dict, site: str | None = None,
           today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    sites, docs, commits = load_rows(conn, site)
    by_site_docs, by_site_commits = defaultdict(list), defaultdict(list)
    for d in docs:
        by_site_docs[d["site"]].append(d)
    for c in commits:
        by_site_commits[c["site"]].append(c)
    declared = [s["name"] for s in contract["sites"]]
    analyzed = []
    for s in sites:
        if site is None and s["site"] not in declared:
            continue
        a = analyze_site(s, by_site_docs[s["site"]], by_site_commits[s["site"]], plan, contract, today)
        a["quality"] = next((x.get("quality") for x in contract["sites"] if x["name"] == s["site"]), None)
        a["suggestions"] = suggestions(a, contract, today)
        analyzed.append(a)
    synced = {a["site"] for a in analyzed}
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "sites": analyzed,
        "unsynced": [n for n in declared if n not in synced] if site is None else [],
        "overlap": overlap(docs) if site is None else [],
        "fleet": {
            "sites": len(analyzed), "docs": sum(a["totals"]["docs"] for a in analyzed),
            "recent": sum(a["totals"]["recent"] for a in analyzed),
            "stale": sum(a["totals"]["stale"] for a in analyzed),
            "suggestions": sum(len(a["suggestions"]) for a in analyzed),
            "approved": sum(1 for a in analyzed for d in a["directives"] if d.get("status") == "approved"),
        },
    }


def documents(conn: sqlite3.Connection, site: str, view: str = "all", q: str = "", limit: int = 200,
              today: dt.date | None = None, contract: dict | None = None, plan: dict | None = None) -> list[dict]:
    """The document table for one site, filtered: all | stale | issues | thin |
    recent | unmapped | pillar:<id>."""
    today = today or dt.date.today()
    contract = contract or DEFAULTS
    _, docs, _ = load_rows(conn, site)
    stale_days = int(contract.get("stale_days") or 365)
    recent_days = int(contract.get("recent_days") or 90)
    pillars = site_plan(plan or {}, site)["pillars"] if plan else []
    ql = q.lower().strip()

    def keep(d):
        if ql and ql not in f"{d['path']} {d.get('title', '')} {' '.join(d.get('tags') or [])}".lower():
            return False
        age = _age(d.get("updated"), today)
        if view == "stale":
            return age is not None and age > stale_days
        if view == "issues":
            return bool(d.get("issues"))
        if view == "thin":
            return "thin" in (d.get("issues") or [])
        if view == "recent":
            return (_age(d.get("date"), today) or 10 ** 6) <= recent_days
        if view == "drafts":
            return bool(d.get("draft"))
        if view == "unmapped":
            return not any(pillar_matches(d, p) for p in pillars)
        if view.startswith("pillar:"):
            p = next((p for p in pillars if p.get("id") == view[7:]), None)
            return bool(p) and pillar_matches(d, p)
        return True

    rows = [d for d in docs if keep(d)]
    rows.sort(key=lambda d: d.get("updated") or "", reverse=view != "stale")
    out = []
    for d in rows[:limit]:
        b = _brief_doc(d, today)
        b.update({"tags": d.get("tags") or [], "author": d.get("author"), "draft": bool(d.get("draft")),
                  "commits": d.get("commits"), "links": d.get("links"), "wikilinks": d.get("wikilinks")})
        out.append(b)
    return out


# --------------------------------------------------------------------------- #
# PLAN WRITES — comment-preserving, validated, never a commit
# --------------------------------------------------------------------------- #
ID_RX = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
KEY_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/ -]{0,200}$")


def _text(value, field: str, limit: int, required: bool = False) -> str:
    v = str(value if value is not None else "").strip()
    if required and not v:
        raise ValueError(f"{field} is required")
    if len(v) > limit:
        raise ValueError(f"{field} is longer than {limit} characters")
    if not TEXT_RX.match(v):
        raise ValueError(f"{field} contains control characters")
    return v


def _yaml_rt():
    try:
        from ruamel.yaml import YAML
    except ImportError as exc:  # pragma: no cover - the console always has it
        raise RuntimeError("editing the plan needs ruamel.yaml (pip install ruamel.yaml)") from exc
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _load_rt(plan_path: Path):
    y = _yaml_rt()
    if plan_path.exists():
        with open(plan_path, encoding="utf-8") as fh:
            doc = y.load(fh)
    else:
        doc = None
    if doc is None:
        from ruamel.yaml.comments import CommentedMap
        doc = CommentedMap()
        doc["schema"] = PLAN_SCHEMA
    if "sites" not in doc or doc["sites"] is None:
        from ruamel.yaml.comments import CommentedMap
        doc["sites"] = CommentedMap()
    return y, doc


def _save_rt(y, doc, plan_path: Path) -> None:
    tmp = plan_path.with_suffix(".yml.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        y.dump(doc, fh)
    os.replace(tmp, plan_path)


def _site_node(doc, site: str):
    from ruamel.yaml.comments import CommentedMap, CommentedSeq
    if site not in doc["sites"] or doc["sites"][site] is None:
        node = CommentedMap()
        node["narrative"] = ""
        node["pillars"] = CommentedSeq()
        node["directives"] = CommentedSeq()
        doc["sites"][site] = node
    node = doc["sites"][site]
    for k in ("pillars", "directives"):
        if node.get(k) is None:
            node[k] = CommentedSeq()
    return node


def decide(plan_path: Path | str, site: str, action: str, key: str, contract: dict,
           suggestion: dict | None = None, fields: dict | None = None,
           today: dt.date | None = None, sites_known: list[str] | None = None) -> dict:
    """The one write path for directives.

    action: approve | reject — decide a SUGGESTION (its title/brief/kind are
            copied in, so the plan stays readable without the lake);
            add — a human's own directive (fields: title, brief, kind, pillar);
            status — move an existing directive (fields: status, issue);
            remove — delete a directive that is still `proposed` or `rejected`.
    """
    from ruamel.yaml.comments import CommentedMap
    plan_path = Path(plan_path)
    today = today or dt.date.today()
    fields = fields or {}
    known = sites_known if sites_known is not None else [s["name"] for s in contract.get("sites") or []]
    if site not in known:
        raise ValueError(f"unknown site '{site}' — declare it in fleet.yml content.sites first")
    key = _text(key, "key", 200, required=True)
    if not KEY_RX.match(key):
        raise ValueError("key has characters the plan refuses")
    y, doc = _load_rt(plan_path)
    node = _site_node(doc, site)
    items = node["directives"]
    existing = next((d for d in items if isinstance(d, dict) and d.get("key") == key), None)

    if action in ("approve", "reject"):
        src = dict(suggestion or {})
        if existing is None:
            if not src:
                raise ValueError(f"no suggestion '{key}' to {action} (re-run the report)")
            entry = CommentedMap()
            entry["key"] = key
            entry["kind"] = src.get("kind") if src.get("kind") in DIRECTIVE_KINDS else "write"
            entry["priority"] = src.get("priority") if src.get("priority") in ("P1", "P2", "P3") else "P2"
            entry["title"] = _text(fields.get("title") or src.get("title"), "title", 200, required=True)
            entry["brief"] = _text(fields.get("brief") or src.get("brief"), "brief", 2000)
            for extra in ("pillar", "path"):
                if src.get(extra):
                    entry[extra] = _text(src[extra], extra, 300)
            entry["source"] = "atlas"
            entry["status"] = "approved" if action == "approve" else "rejected"
            entry["decided"] = today.isoformat()
            items.append(entry)
            existing = entry
        else:
            target = "approved" if action == "approve" else "rejected"
            _transition(existing, target, today)
    elif action == "add":
        if existing is not None:
            raise ValueError(f"a directive with key '{key}' already exists")
        kind = fields.get("kind") or "write"
        if kind not in DIRECTIVE_KINDS:
            raise ValueError(f"kind must be one of {DIRECTIVE_KINDS}")
        entry = CommentedMap()
        entry["key"] = key
        entry["kind"] = kind
        entry["priority"] = fields.get("priority") if fields.get("priority") in ("P1", "P2", "P3") else "P2"
        entry["title"] = _text(fields.get("title"), "title", 200, required=True)
        entry["brief"] = _text(fields.get("brief"), "brief", 2000)
        if fields.get("pillar"):
            pid = _text(fields["pillar"], "pillar", 64)
            if not ID_RX.match(pid):
                raise ValueError("pillar must be a lowercase id")
            entry["pillar"] = pid
        entry["source"] = "human"
        entry["status"] = "approved" if fields.get("approve", True) else "proposed"
        entry["decided"] = today.isoformat()
        items.append(entry)
        existing = entry
    elif action == "status":
        if existing is None:
            raise ValueError(f"no directive '{key}'")
        target = fields.get("status")
        if target not in DIRECTIVE_STATES:
            raise ValueError(f"status must be one of {DIRECTIVE_STATES}")
        _transition(existing, target, today)
        if fields.get("issue"):
            url = _text(fields["issue"], "issue", 300)
            if not re.match(r"^https://github\.com/[\w.-]+/[\w.-]+/issues/\d+$", url):
                raise ValueError("issue must be a github.com issue URL")
            existing["issue"] = url
    elif action == "remove":
        if existing is None:
            raise ValueError(f"no directive '{key}'")
        if existing.get("status") not in ("proposed", "rejected"):
            raise ValueError("only a proposed or rejected directive can be removed — move it back first")
        items.remove(existing)
        existing = None
    else:
        raise ValueError("action must be approve | reject | add | status | remove")
    _save_rt(y, doc, plan_path)
    return {"site": site, "key": key, "action": action,
            "directive": dict(existing) if existing is not None else None}


def _transition(entry, target: str, today: dt.date) -> None:
    cur = entry.get("status") or "proposed"
    if target == cur:
        return
    if target not in TRANSITIONS.get(cur, set()):
        raise ValueError(f"cannot move a directive from {cur} to {target}")
    entry["status"] = target
    entry["decided"] = today.isoformat()


def update_site(plan_path: Path | str, site: str, contract: dict, fields: dict,
                sites_known: list[str] | None = None) -> dict:
    """Set a site's narrative / audience / voice, and upsert pillars.

    fields: {narrative?, audience?, voice?, pillar?: {id, title?, target_share?,
    status?, match?: {tags, categories, sections, collections, keywords, paths}}}
    """
    from ruamel.yaml.comments import CommentedMap, CommentedSeq
    plan_path = Path(plan_path)
    known = sites_known if sites_known is not None else [s["name"] for s in contract.get("sites") or []]
    if site not in known:
        raise ValueError(f"unknown site '{site}'")
    y, doc = _load_rt(plan_path)
    node = _site_node(doc, site)
    for k, limit in (("narrative", 2000), ("audience", 400), ("voice", 400)):
        if k in fields:
            node[k] = _text(fields[k], k, limit)
    p = fields.get("pillar")
    if p is not None:
        if not isinstance(p, dict):
            raise ValueError("pillar must be an object")
        pid = _text(p.get("id"), "pillar.id", 64, required=True)
        if not ID_RX.match(pid):
            raise ValueError("pillar.id must be a lowercase id")
        entry = next((x for x in node["pillars"] if isinstance(x, dict) and x.get("id") == pid), None)
        if entry is None:
            entry = CommentedMap()
            entry["id"] = pid
            entry["title"] = pid
            entry["target_share"] = None
            entry["status"] = "active"
            entry["match"] = CommentedMap()
            node["pillars"].append(entry)
        if "title" in p:
            entry["title"] = _text(p["title"], "pillar.title", 120, required=True)
        if "target_share" in p:
            ts = p["target_share"]
            if ts in (None, ""):
                entry["target_share"] = None
            else:
                ts = float(ts)
                if not 0 <= ts <= 1:
                    raise ValueError("target_share is a fraction between 0 and 1")
                entry["target_share"] = round(ts, 3)
        if "status" in p:
            if p["status"] not in ("active", "paused", "retired"):
                raise ValueError("pillar status must be active | paused | retired")
            entry["status"] = p["status"]
        if "match" in p:
            m = p["match"] or {}
            if not isinstance(m, dict):
                raise ValueError("pillar.match must be an object")
            out = CommentedMap()
            for mk in ("tags", "categories", "sections", "collections", "keywords", "paths"):
                vals = m.get(mk)
                if vals in (None, "", []):
                    continue
                if isinstance(vals, str):
                    vals = [v for v in vals.split(",")]
                seq = CommentedSeq([_text(v, f"match.{mk}", 80) for v in vals if str(v).strip()][:40])
                seq.fa.set_flow_style()
                out[mk] = seq
            entry["match"] = out
    _save_rt(y, doc, plan_path)
    return {"site": site, "updated": sorted(k for k in fields)}


# --------------------------------------------------------------------------- #
# BRIEF + FILE — the directives leave the hub
# --------------------------------------------------------------------------- #
def render_brief(a: dict, only_key: str | None = None) -> str:
    lines = [f"# Editorial brief — {a['site']}", ""]
    if a.get("narrative"):
        lines += ["## Narrative", "", a["narrative"].strip(), ""]
    if a.get("audience") or a.get("voice"):
        lines += [f"- **Audience:** {a.get('audience') or '—'}", f"- **Voice:** {a.get('voice') or '—'}", ""]
    if a.get("pillars"):
        lines += ["## Pillars", "", "| pillar | target | recent share | docs | newest |", "|---|---|---|---|---|"]
        for p in a["pillars"]:
            tgt = f"{round(p['target_share'] * 100)}%" if p.get("target_share") is not None else "—"
            lines.append(f"| {p['title']} ({p['status']}) | {tgt} | {round(p['recent_share'] * 100)}% "
                         f"({p['recent']}) | {p['docs']} | {p['newest'] or '—'} |")
        lines.append("")
    approved = [d for d in a.get("directives") or [] if d.get("status") in ("approved", "filed")
                and (only_key is None or d.get("key") == only_key)]
    if approved:
        lines += ["## Directives", ""]
        for d in approved:
            lines.append(f"- **{d.get('title')}** ({d.get('kind')}, {d.get('priority')}) — {d.get('brief') or ''}"
                         + (f" [{d['issue']}]({d['issue']})" if d.get("issue") else ""))
        lines.append("")
    t = a["totals"]
    lines += ["## State of the site", "",
              f"{t['docs']} published documents, {t['recent']} in the last {t['recent_days']} days; last "
              f"published {t['last_published'] or '—'}; {t['stale']} not updated in over a year; "
              f"{t['with_issues']} with front-matter issues.", ""]
    return "\n".join(lines)


def issue_body(a: dict, d: dict) -> str:
    marker = f"<!-- {MARKER} key={d['key']} site={a['site']} -->"
    body = [marker, "", f"**Editorial directive** · kind `{d.get('kind')}` · priority `{d.get('priority')}`"
            + (f" · pillar `{d['pillar']}`" if d.get("pillar") else ""), "", d.get("brief") or "", ""]
    if d.get("path"):
        body += [f"Document: `{d['path']}`", ""]
    if a.get("narrative"):
        body += ["### The narrative this serves", "", "> " + a["narrative"].strip().replace("\n", "\n> "), ""]
    body += ["---", "_Filed by the hub's content atlas from an approved entry in "
             "`bamr87/bamr87` `_data/editorial.yml`. Close it when the work ships; the atlas marks the "
             "directive done on its next `file` pass._"]
    return "\n".join(body)


def file_directives(a: dict, contract: dict, plan_path: Path | str, apply: bool = False, log=print,
                    run=_run, today: dt.date | None = None) -> list[dict]:
    """One issue per approved, unfiled directive in the site's own repo.

    Dedupe is by the hidden marker, against every issue carrying the label,
    open or closed — so a directive filed from another machine, or whose plan
    edit was never committed, is re-linked rather than re-filed. A CLOSED
    issue marks its directive done.
    """
    repo = a.get("repo")
    if not repo:
        raise ValueError(f"{a['site']} has no repo to file into")
    cfg = _merge(DEFAULTS["directives"], contract.get("directives") or {})
    label = cfg["label"]
    todo = [d for d in a.get("directives") or [] if d.get("status") in ("approved", "filed")]
    results = []
    existing: dict[str, dict] = {}
    rc, out = run(["gh", "issue", "list", "--repo", repo, "--label", label, "--state", "all",
                   "--limit", "500", "--json", "url,body,state"], timeout=60)
    if rc == 0:
        try:
            for it in json.loads(out or "[]"):
                m = re.search(rf"<!-- {MARKER} key=(.+?) site=", it.get("body") or "")
                if m:
                    existing[m.group(1)] = it
        except ValueError:
            pass
    elif apply:
        log(f"  ! could not list issues in {repo} (label may not exist yet): {out.strip()[:160]}")
    label_ready = False
    for d in todo:
        hit = existing.get(d["key"])
        if hit:
            status = "done" if hit.get("state", "").upper() == "CLOSED" else "filed"
            results.append({"key": d["key"], "action": "linked", "url": hit.get("url"), "status": status})
            if apply and (d.get("status") != status or d.get("issue") != hit.get("url")):
                _record(plan_path, a["site"], d, status, hit.get("url"), contract, today)
            continue
        if d.get("status") == "filed":
            results.append({"key": d["key"], "action": "filed-elsewhere", "url": d.get("issue")})
            continue
        title = f"[editorial] {d.get('title')}"
        if not apply:
            log(f"  would file in {repo}: {title}")
            results.append({"key": d["key"], "action": "would-file", "title": title})
            continue
        if not label_ready:
            run(["gh", "label", "create", label, "--repo", repo, "--color", cfg["color"],
                 "--description", cfg["label_description"], "--force"], timeout=60)
            label_ready = True
        rc, out = run(["gh", "issue", "create", "--repo", repo, "--title", title, "--label", label,
                       "--body-file", "-"], timeout=60, stdin=issue_body(a, d))
        url = next((ln.strip() for ln in out.splitlines() if ln.strip().startswith("https://github.com/")), None)
        if rc != 0 or not url:
            log(f"  ✖ {d['key']}: {out.strip()[:200]}")
            results.append({"key": d["key"], "action": "failed", "error": out.strip()[:200]})
            continue
        log(f"  ✓ filed {url}")
        _record(plan_path, a["site"], d, "filed", url, contract, today)
        results.append({"key": d["key"], "action": "filed", "url": url})
    return results


def _record(plan_path, site, d, status, url, contract, today):
    fields = {"status": status}
    if url:
        fields["issue"] = url
    try:
        cur = d.get("status")
        if cur == "approved" and status == "done":
            decide(plan_path, site, "status", d["key"], contract, fields={"status": "filed", "issue": url}, today=today)
            fields = {"status": "done"}
        decide(plan_path, site, "status", d["key"], contract, fields=fields, today=today)
    except ValueError:
        pass  # already there, or a human moved it meanwhile — the plan wins


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _conn_or_none(args):
    try:
        return connect(args.lake, create=False)
    except FileNotFoundError:
        return None


def cmd_sync(args) -> int:
    contract = load_contract(args.fleet)
    if not contract["sites"]:
        print("no content sites declared in fleet.yml `content.sites`", file=sys.stderr)
        return 1
    print(f"content atlas → {Path(args.lake) / DB_NAME}")
    res = sync(contract, args.lake, only=args.site, fetch=not args.no_fetch)
    return 0 if any(r.get("docs") for r in res) else 1


def cmd_report(args) -> int:
    contract, plan = load_contract(args.fleet), load_plan(args.plan)
    conn = _conn_or_none(args)
    if conn is None:
        doc = {"present": False, "sites": [], "unsynced": [s["name"] for s in contract["sites"]]}
    else:
        doc = report(conn, contract, plan, site=args.site)
        doc["present"] = True
    if args.json:
        print(json.dumps(doc, indent=2, default=str))
        return 0
    if not doc.get("sites"):
        print("the atlas is empty — run: tools/dash content sync")
        return 0
    print(f"{'site':<26} {'docs':>6} {'90d':>5} {'last pub':>11} {'med age':>8} {'stale':>6} {'issues':>7} {'sugg':>5}")
    for a in doc["sites"]:
        t = a["totals"]
        print(f"{a['site']:<26} {t['docs']:>6} {t['recent']:>5} {t['last_published'] or '—':>11} "
              f"{t['median_age'] if t['median_age'] is not None else '—':>8} {t['stale']:>6} "
              f"{t['with_issues']:>7} {len(a['suggestions']):>5}")
    for a in doc["sites"]:
        if a["suggestions"]:
            print(f"\n{a['site']}:")
            for s in a["suggestions"]:
                print(f"  [{s['priority']}] {s['key']:<34} {s['title']}")
    if doc.get("unsynced"):
        print("\nnot synced yet: " + ", ".join(doc["unsynced"]))
    return 0


def _analyzed(args, site: str) -> dict:
    contract, plan = load_contract(args.fleet), load_plan(args.plan)
    conn = _conn_or_none(args)
    if conn is None:
        raise SystemExit("the atlas is empty — run: tools/dash content sync")
    doc = report(conn, contract, plan, site=site)
    if not doc["sites"]:
        raise SystemExit(f"'{site}' is not in the atlas — run: tools/dash content sync --site {site}")
    return doc["sites"][0]


def cmd_brief(args) -> int:
    a = _analyzed(args, args.site)
    print(render_brief(a))
    return 0


def cmd_plan(args) -> int:
    contract = load_contract(args.fleet)
    if args.plan_cmd == "show":
        plan = load_plan(args.plan)
        sp = site_plan(plan, args.site) if args.site else plan
        print(yaml.safe_dump(sp, sort_keys=False, allow_unicode=True))
        return 0
    suggestion = None
    if args.plan_cmd in ("approve", "reject"):
        a = _analyzed(args, args.site)
        suggestion = next((s for s in a["suggestions"] if s["key"] == args.key), None)
    fields = {}
    if args.plan_cmd == "add":
        fields = {"title": args.title, "brief": args.brief or "", "kind": args.kind, "pillar": args.pillar}
    if args.plan_cmd == "status":
        fields = {"status": args.status}
    action = {"approve": "approve", "reject": "reject", "add": "add", "status": "status", "remove": "remove"}[args.plan_cmd]
    res = decide(args.plan, args.site, action, args.key, contract, suggestion=suggestion, fields=fields)
    print(json.dumps(res, indent=2, default=str))
    return 0


def cmd_file(args) -> int:
    contract = load_contract(args.fleet)
    a = _analyzed(args, args.site)
    print(f"{'APPLY' if args.apply else 'DRY RUN'} — approved directives for {a['site']} → {a.get('repo')}")
    res = file_directives(a, contract, args.plan, apply=args.apply)
    if not res:
        print("  nothing approved to file")
    return 1 if any(r["action"] == "failed" for r in res) else 0


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lake", default=str(LAKE_DIR_DEFAULT), help="lake directory (DASH_LAKE_DIR)")
    parser.add_argument("--fleet", default=str(FLEET_DEFAULT))
    parser.add_argument("--plan", default=str(PLAN_DEFAULT), help="the editorial plan (_data/editorial.yml)")
    sub = parser.add_subparsers(dest="content_cmd", required=True)

    p = sub.add_parser("sync", help="extract every declared content site into the lake")
    p.add_argument("--site", action="append", help="only this site (repeatable)")
    p.add_argument("--no-fetch", action="store_true", help="never clone or fetch; local checkouts/cache only")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("report", help="analyze the atlas (offline); --json is the console document")
    p.add_argument("--site", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("brief", help="the editorial brief for one site, as Markdown")
    p.add_argument("--site", required=True)
    p.set_defaults(func=cmd_brief)

    p = sub.add_parser("plan", help="show or change the editorial plan (_data/editorial.yml)")
    ps = p.add_subparsers(dest="plan_cmd", required=True)
    x = ps.add_parser("show")
    x.add_argument("--site", default=None)
    for verb in ("approve", "reject", "remove"):
        x = ps.add_parser(verb)
        x.add_argument("--site", required=True)
        x.add_argument("--key", required=True)
    x = ps.add_parser("add")
    x.add_argument("--site", required=True)
    x.add_argument("--key", required=True)
    x.add_argument("--title", required=True)
    x.add_argument("--brief", default="")
    x.add_argument("--kind", default="write", choices=DIRECTIVE_KINDS)
    x.add_argument("--pillar", default=None)
    x = ps.add_parser("status")
    x.add_argument("--site", required=True)
    x.add_argument("--key", required=True)
    x.add_argument("--status", required=True, choices=DIRECTIVE_STATES)
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("file", help="open one issue per approved directive in the site's repo (dry run unless --apply)")
    p.add_argument("--site", required=True)
    p.add_argument("--apply", action="store_true")
    p.set_defaults(func=cmd_file)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="content_atlas", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(ap)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
