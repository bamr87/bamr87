#!/usr/bin/env python3
"""
site_docs — the public site's own documents: who the site is about, its
long-form pages, its posts, and the committed registries its portfolio pages
render.

One module, two consumers, so the two can never disagree: app.py serves these
documents live under /api/site and /api/data (the console's page shows the same
Home, Portfolio and Writing pages locally), and snapshot.py writes them as
static JSON for GitHub Pages.

Inputs, all committed:
  _data/profile.yml        identity (name, title, links, avatar)
  pages/profile/*.md       long-form pages — front matter: title, description,
                           order, icon; the body is Markdown, rendered by the page
  pages/posts/*.md         dated writing, YYYY-MM-DD-slug.md; `draft: true` is
                           left out of the public build
  _data/<name>.yml|json    the registries named in PUBLIC_DATA, nothing else
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA = REPO_ROOT / "_data"
PAGES = REPO_ROOT / "pages"

SLUG_RX = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}$")
POST_RX = re.compile(r"^(\d{4}-\d{2}-\d{2})-([a-z0-9][a-z0-9-]{0,80})\.md$")
_FRONT_RX = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.S)

# The committed registries a page may read through /api/data/<name>. A name not
# listed here is refused: _data/ is public, but a page should depend on a
# registry on purpose, and the list is what the static build exports.
PUBLIC_DATA = {
    "projects": "projects.yml",
    "project_health": "project_health.yml",
    "roadmap": "roadmap.yml",
    "engagements": "engagements.yml",
    "features_index": "features_index.yml",
    "scripts": "scripts.yml",
    "skills": "skills.yml",
    "templates": "templates.yml",
    "docker": "docker.yml",
    "cv_portfolio": "cv_portfolio.json",
    "issue_pipeline": "issue_pipeline.yml",
    "deep_dive": "deep_dive.json",
    "actions_usage": "actions_usage.yml",
    "ai_usage": "ai_usage.yml",
    "conformance": "conformance.yml",
}


def _load(path: Path):
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    return json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)


def _plain(value):
    """YAML dates → ISO strings, so every document is JSON as-is."""
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _split(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    m = _FRONT_RX.match(text)
    if not m:
        return {}, text
    front = yaml.safe_load(m.group(1)) or {}
    return (front if isinstance(front, dict) else {}), m.group(2).lstrip("\n")


def profile() -> dict:
    return _plain(_load(DATA / "profile.yml") or {})


def _page_meta(path: Path, front: dict) -> dict:
    return {"slug": path.stem, "title": str(front.get("title") or path.stem.title()),
            "description": str(front.get("description") or ""), "order": int(front.get("order") or 99),
            "icon": str(front.get("icon") or "file-text")}


def pages() -> list[dict]:
    out = []
    for path in sorted((PAGES / "profile").glob("*.md")):
        if SLUG_RX.match(path.stem):
            out.append(_page_meta(path, _split(path)[0]))
    return sorted(out, key=lambda p: (p["order"], p["slug"]))


def page(slug: str) -> dict:
    if not SLUG_RX.match(slug or ""):
        raise ValueError("invalid page slug")
    path = PAGES / "profile" / f"{slug}.md"
    if not path.is_file():
        raise KeyError(slug)
    front, body = _split(path)
    return _page_meta(path, front) | {"markdown": body}


def _post_meta(path: Path, front: dict, body: str) -> dict:
    m = POST_RX.match(path.name)
    date = str(_plain(front.get("date")) or m.group(1))[:10]
    excerpt = str(front.get("excerpt") or "").strip()
    if not excerpt:
        para = next((p for p in body.split("\n\n") if p.strip() and not p.lstrip().startswith(("#", "```", "<"))), "")
        excerpt = re.sub(r"\s+", " ", re.sub(r"[*_`\[\]]|\(http[^)]*\)", "", para)).strip()[:280]
    return {"slug": m.group(2), "date": date, "title": str(front.get("title") or m.group(2)),
            "excerpt": excerpt, "categories": [str(c) for c in front.get("categories") or []],
            "tags": [str(t) for t in front.get("tags") or []], "draft": bool(front.get("draft")),
            "words": len(body.split())}


def _post_files():
    for path in sorted((PAGES / "posts").glob("*.md"), reverse=True):
        if POST_RX.match(path.name):
            yield path


def posts(include_drafts: bool = False) -> list[dict]:
    out = []
    for path in _post_files():
        front, body = _split(path)
        meta = _post_meta(path, front, body)
        if include_drafts or not meta["draft"]:
            out.append(meta)
    return out


def post(slug: str, include_drafts: bool = False) -> dict:
    if not SLUG_RX.match(slug or ""):
        raise ValueError("invalid post slug")
    for path in _post_files():
        if POST_RX.match(path.name).group(2) == slug:
            front, body = _split(path)
            meta = _post_meta(path, front, body)
            if meta["draft"] and not include_drafts:
                break
            return meta | {"markdown": body}
    raise KeyError(slug)


def site_index(include_drafts: bool = False) -> dict:
    """Everything the shell needs to draw the Profile section and the Home page."""
    return {"profile": profile(), "pages": pages(), "posts": posts(include_drafts)}


def data(name: str):
    if name not in PUBLIC_DATA:
        raise KeyError(name)
    return _plain(_load(DATA / PUBLIC_DATA[name]))
