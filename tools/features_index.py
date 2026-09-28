#!/usr/bin/env python3
"""
File: tools/features_index.py
Description: The FLEET FEATURES INDEX — validate one repo's feature index
             (features/features.yml, schema features/v1), grade its
             verification coverage (which features have tests, user scenarios,
             evidence bundles, screenshots, and a verified stamp), and
             aggregate every checked-out submodule's index into the committed
             _data/features_index.yml that the dash renders at /features/.

             This is the "index of everything" an agent reads before touching
             an area of a codebase: what the product does, where it lives,
             where it is documented, what proves it works, and what has never
             been verified. Coverage is graded from FILES ON DISK, not from
             claims: a `tests:` entry that names a file that does not exist is
             a dangling link and counts for nothing.

             Kit: templates/verify/ · spec: specs/QUALITY.md "Verification"
             (UPS-QA-50..53) · doc: docs/VERIFICATION.md
Author: bamr87
Created: 2026-09-04
Last Modified: 2026-09-04
Version: 0.1.0
Usage:
  python3 tools/features_index.py check <repo> [--json]        validate the index
  python3 tools/features_index.py coverage <repo> [--json]     per-feature coverage
  python3 tools/features_index.py fleet [--write] [--check] [--json] [--hub PATH]
                                                                aggregate → _data/features_index.yml
Dependencies: PyYAML only (no network, no GitHub).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

import yaml

HUB = Path(__file__).resolve().parent.parent
OUT = HUB / "_data" / "features_index.yml"
SCHEMA = "features-index/v1"

INDEX_CANDIDATES = ("features/features.yml", "_data/features.yml", "features.yml")
PROSE_CANDIDATES = ("FEATURES.md", "docs/FEATURES.md", "features.md")
SURFACES = ("ui", "api", "cli", "docs", "content", "infra")
VERIFIED_BY = ("agent", "human", "ci")
ID_RE = re.compile(r"^[A-Z][A-Z0-9-]*-\d+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_ITEMS = 300


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _list(v) -> list[str]:
    """String items only — `{na: reason}` waivers are handled by _waivers()."""
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v if x is not None and not isinstance(x, dict) and str(x).strip()]
    if isinstance(v, dict):
        return []
    return [str(v)] if str(v).strip() else []


def _waivers(v) -> list[str]:
    """zer0-mistakes precedent: `tests: [{na: "docs-only feature; no runtime test"}]`
    declares that coverage is NOT APPLICABLE, with a reason. A waiver counts as
    covered (the decision was made and written down) but never as evidenced."""
    if isinstance(v, dict) and "na" in v:
        return [str(v["na"])]
    if isinstance(v, (list, tuple)):
        return [str(x["na"]) for x in v if isinstance(x, dict) and "na" in x]
    return []


UI_TAGS = {"ui", "ux", "navigation", "nav", "layout", "theme", "responsive", "accessibility", "a11y", "seo", "search",
           "component", "components", "frontend", "page", "pages", "mobile", "sidebar", "menu", "form", "forms", "editor",
           "dashboard", "widget", "modal", "dialog", "css", "design", "dark-mode", "i18n", "analytics", "comments", "feedback"}
NON_UI_TAGS = {"ci", "cd", "workflow", "workflows", "automation", "devops", "docker", "release", "testing", "tests", "scripts",
               "script", "documentation", "docs", "security", "infrastructure", "infra", "build", "tooling", "installer",
               "installation", "plugin", "plugins", "backend", "api", "cli", "config", "configuration", "deployment"}


# Registry `stack:` tags that mean "this repo has a UI a person uses" when the
# entry declares no `kinds:` — so an app with no index is flagged, not excused.
UI_STACK_TAGS = {"react", "jekyll", "vite", "next", "nextjs", "next.js", "django", "vue", "svelte", "tailwind",
                 "bootstrap", "html", "css", "flask", "rails", "streamlit", "gradio", "electron", "mkdocs", "vscode"}


def infer_surface(link: str, tags: list[str], fmt: str) -> str:
    """Fallback when `surface` is absent. Fleet-format files are expected to
    declare it; legacy files link nearly everything to `/`, so tags decide
    first and the route only when it is a real sub-route."""
    t = {x.lower() for x in tags}
    if t & UI_TAGS and not (t & NON_UI_TAGS - {"analytics"}):
        return "ui"
    if t & NON_UI_TAGS:
        return "docs" if t & {"documentation", "docs"} and not (t & UI_TAGS) else "infra"
    if link.startswith("/") and (link != "/" or fmt == "fleet"):
        return "ui"
    return "infra"


def _exists(repo: Path, rel: str) -> bool:
    """A linked path counts when it exists as a file, or as a non-empty dir."""
    if not rel or rel.startswith(("http://", "https://")):
        return False
    p = repo / rel.lstrip("/")
    if p.is_file():
        return True
    if p.is_dir():
        return any(c.is_file() for c in p.rglob("*"))
    return False


def _pngs(repo: Path, rel: str) -> list[str]:
    p = repo / rel.lstrip("/")
    if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        return [rel.lstrip("/")]
    if p.is_dir():
        return sorted(str(c.relative_to(repo)) for c in p.rglob("*") if c.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif"))
    return []


def find_index(repo: Path) -> tuple[Path | None, str]:
    """→ (path, format) where format is fleet | legacy | prose | none."""
    for rel in INDEX_CANDIDATES:
        p = repo / rel
        if p.is_file():
            try:
                data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                return p, "legacy"
            fmt = "fleet" if isinstance(data, dict) and str(data.get("schema", "")).startswith("features/") else "legacy"
            return p, fmt
    for rel in PROSE_CANDIDATES:
        if (repo / rel).is_file():
            return repo / rel, "prose"
    return None, "none"


def load_scenarios(repo: Path, cfg: dict) -> list[dict]:
    d = repo / str(cfg.get("scenarios") or "verify/scenarios")
    out = []
    if not d.is_dir():
        return out
    for f in sorted(d.iterdir()):
        if f.suffix not in (".yml", ".yaml"):
            continue
        try:
            s = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            s = {"parse_error": str(e).splitlines()[0]}
        if not isinstance(s, dict):
            s = {}
        feats = s.get("feature", s.get("features"))
        out.append({"id": str(s.get("id") or f.stem), "path": str(f.relative_to(repo)),
                    "title": str(s.get("title") or ""), "features": _list(feats),
                    "steps": len(s.get("steps") or []) if isinstance(s.get("steps"), list) else 0,
                    "error": s.get("parse_error")})
    return out


def load_verify_cfg(repo: Path) -> dict:
    p = repo / "verify" / "verify.yml"
    if not p.is_file():
        return {}
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}


def kit_presence(repo: Path, cfg: dict, scenarios: list[dict]) -> dict:
    wf = repo / ".github" / "workflows" / "verify.yml"
    wf_text = wf.read_text(encoding="utf-8") if wf.is_file() else ""
    return {
        "config": (repo / "verify" / "verify.yml").is_file(),
        "runner": (repo / "verify" / "runner.mjs").is_file(),
        "scenarios": len(scenarios),
        "workflow": wf.is_file(),
        "workflow_fleet_caller": "fleet-verify.yml" in wf_text,
        "workflow_gate": bool(re.search(r"gate:\s*true", wf_text)),
        "skill": (repo / ".claude" / "skills" / "verify-feature" / "SKILL.md").is_file(),
        "agent": (repo / ".claude" / "agents" / "verifier.md").is_file(),
        "mcp": (repo / "verify" / "mcp.json").is_file(),
        # Precedents that satisfy the spirit of the standard without the kit:
        # zer0-mistakes' evidence-kit + visual-evidence skill.
        "legacy_evidence_kit": (repo / "test" / "visual" / "evidence-kit.mjs").is_file(),
        "legacy_visual_evidence_skill": (repo / ".github" / "skills" / "visual-evidence" / "SKILL.md").is_file(),
    }


def last_run(repo: Path, cfg: dict) -> dict | None:
    rep = repo / str(cfg.get("evidence_dir") or "test/evidence") / "report.json"
    if not rep.is_file():
        return None
    try:
        r = json.loads(rep.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return {"generated": r.get("generated"), "by": r.get("by"), "passed": r.get("passed"), "failed": r.get("failed"),
            "total": r.get("total"), "run": r.get("run")}


# --------------------------------------------------------------------------- #
# validation + coverage for ONE repo
# --------------------------------------------------------------------------- #
def analyze(repo: Path) -> dict:
    repo = repo.resolve()
    path, fmt = find_index(repo)
    cfg = load_verify_cfg(repo)
    scenarios = load_scenarios(repo, cfg)
    kit = kit_presence(repo, cfg, scenarios)
    res = {
        "path": str(repo), "index": str(path.relative_to(repo)) if path else None, "format": fmt,
        "ok": True, "errors": [], "warnings": [], "features": [], "kit": kit,
        "scenarios": scenarios, "last_run": last_run(repo, cfg),
        "counts": {"features": 0, "implemented": 0, "covered": 0, "evidenced": 0, "verified": 0, "ui": 0, "ui_covered": 0, "ui_verified": 0, "dangling": 0},
    }
    if fmt in ("none", "prose"):
        if fmt == "prose":
            res["warnings"].append(f"{res['index']} is prose only — convert to features/features.yml (features/v1) so coverage can be graded")
        return res

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        res["ok"] = False
        res["errors"].append(f"{res['index']}: YAML parse error: {str(e).splitlines()[0]}")
        return res
    if not isinstance(data, dict) or not isinstance(data.get("features"), list):
        res["ok"] = False
        res["errors"].append(f"{res['index']}: top level must be a mapping with a `features:` list")
        return res

    # Scenario → feature back-references (a scenario that names a feature
    # covers it even when the feature entry forgot to link the scenario).
    by_feature: dict[str, list[str]] = {}
    for s in scenarios:
        if s.get("error"):
            res["warnings"].append(f"{s['path']}: {s['error']}")
        for fid in s["features"]:
            by_feature.setdefault(fid, []).append(s["path"])

    seen: set[str] = set()
    for i, f in enumerate(data["features"]):
        where = f"{res['index']} features[{i}]"
        if not isinstance(f, dict):
            res["errors"].append(f"{where}: entry must be a mapping")
            continue
        fid = str(f.get("id") or "").strip()
        if not fid:
            res["errors"].append(f"{where}: missing id")
            continue
        where = f"{res['index']} {fid}"
        if not ID_RE.match(fid):
            res["errors"].append(f"{where}: id must match ^[A-Z][A-Z0-9-]*-<n>$ (e.g. ZER0-001)")
        if fid in seen:
            res["errors"].append(f"{where}: duplicate id")
        seen.add(fid)
        for key in ("title", "description"):
            v = f.get(key)
            if not isinstance(v, str) or not v.strip():
                res["errors"].append(f"{where}: missing {key}")
            elif "<" in v or ">" in v:
                res["warnings"].append(f"{where}: {key} contains '<' or '>' — renders as markup on the features page")
        implemented = f.get("implemented")
        if implemented is None and f.get("status"):
            implemented = str(f["status"]).lower() in ("implemented", "done", "active", "shipped")
        if not isinstance(implemented, bool):
            res["warnings"].append(f"{where}: `implemented` should be true|false (treated as false)")
            implemented = False
        link = str(f.get("link") or "")
        surface = str(f.get("surface") or "").lower()
        if surface and surface not in SURFACES:
            res["errors"].append(f"{where}: surface must be one of {', '.join(SURFACES)}")
        if not surface:
            surface = infer_surface(link, _list(f.get("tags")), fmt)
        waived = _waivers(f.get("tests"))

        def check_paths(key: str) -> tuple[list[str], list[str]]:
            ok, gone = [], []
            for rel in _list(f.get(key)):
                (ok if _exists(repo, rel) else gone).append(rel)
            for rel in gone:
                res["warnings"].append(f"{where}: {key} path not found: {rel}")
            return ok, gone

        tests, t_gone = check_paths("tests")
        scen, s_gone = check_paths("scenarios")
        evid, e_gone = check_paths("evidence")
        shots, sh_gone = check_paths("screenshots")
        docs = str(f.get("docs") or "")
        docs_ok = None
        if docs and not docs.startswith(("http://", "https://", "/")):
            docs_ok = _exists(repo, docs)
            if not docs_ok:
                res["warnings"].append(f"{where}: docs path not found: {docs}")
        backrefs = [p for p in by_feature.get(fid, []) if p not in scen]
        scen_all = scen + backrefs
        images = []
        for rel in evid + shots:
            images.extend(_pngs(repo, rel))
        images = sorted(set(images))

        verified = f.get("verified")
        v_ok = False
        if isinstance(verified, dict) and verified.get("date"):
            v_date = str(verified.get("date"))
            v_by = str(verified.get("by") or "")
            if not DATE_RE.match(v_date):
                res["warnings"].append(f"{where}: verified.date should be YYYY-MM-DD")
            elif v_by and v_by not in VERIFIED_BY:
                res["warnings"].append(f"{where}: verified.by should be one of {', '.join(VERIFIED_BY)}")
            else:
                v_ok = True
        elif verified not in (None, {}, ""):
            res["warnings"].append(f"{where}: verified must be a mapping {{date, by, run}}")

        dangling = t_gone + s_gone + e_gone + sh_gone
        covered = bool(tests or scen_all or waived)
        evidenced = bool(evid or shots)
        item = {
            "id": fid, "title": str(f.get("title") or ""), "description": str(f.get("description") or ""),
            "surface": surface, "implemented": implemented, "link": link or None, "docs": docs or None,
            "tags": _list(f.get("tags")), "date": str(f.get("date")) if f.get("date") else None,
            "provenance": f.get("provenance") if isinstance(f.get("provenance"), dict) else None,
            "tests": tests, "waived": waived, "scenarios": scen_all, "evidence": evid, "screenshots": images[:12],
            "verified": {"date": str(verified.get("date")), "by": str(verified.get("by") or ""), "run": verified.get("run")} if v_ok else None,
            "covered": covered, "evidenced": evidenced, "dangling": dangling,
        }
        res["features"].append(item)
        c = res["counts"]
        c["features"] += 1
        c["implemented"] += int(implemented)
        c["covered"] += int(covered)
        c["evidenced"] += int(evidenced)
        c["verified"] += int(v_ok)
        c["dangling"] += len(dangling)
        if surface == "ui" and implemented:
            c["ui"] += 1
            c["ui_covered"] += int(covered)
            c["ui_verified"] += int(v_ok)

    for s in scenarios:
        for fid in s["features"]:
            if fid not in seen:
                res["warnings"].append(f"{s['path']}: references unknown feature id {fid}")

    res["ok"] = not res["errors"]
    n = max(res["counts"]["implemented"], 1)
    res["pct"] = {
        "coverage": round(100 * sum(1 for x in res["features"] if x["implemented"] and x["covered"]) / n),
        "evidence": round(100 * sum(1 for x in res["features"] if x["implemented"] and x["evidenced"]) / n),
        "verified": round(100 * sum(1 for x in res["features"] if x["implemented"] and x["verified"]) / n),
    }
    return res


def gaps_for(res: dict) -> list[str]:
    """Human-readable, lever-naming gaps for one repo."""
    g = []
    kit = res["kit"]
    if res["format"] == "none":
        g.append("no feature index — seed with `tools/fanout.sh --kit verify` (features/features.yml)")
        return g
    if res["format"] == "prose":
        g.append("feature doc is prose only — convert to features/features.yml (features/v1)")
        return g
    if not res["ok"]:
        g.append(f"index invalid ({len(res['errors'])} error(s)) — `features_index.py check`")
    if res["format"] == "legacy":
        g.append("legacy index (no `schema: features/v1`) — add the marker; entries validate as-is")
    if not kit["config"] and not kit["legacy_evidence_kit"]:
        g.append("no verify/verify.yml — the agent has no instructions for running the app")
    if kit["scenarios"] == 0 and not kit["legacy_evidence_kit"]:
        g.append("no user scenarios (verify/scenarios/*.yml)")
    if not kit["workflow"] and not kit["legacy_visual_evidence_skill"]:
        g.append("no verify.yml CI caller (fleet-verify.yml)")
    if not kit["skill"] and not kit["legacy_visual_evidence_skill"]:
        g.append("no verify-feature skill — a Claude session here has no verification playbook")
    c = res["counts"]
    if c["ui"] and c["ui_covered"] < c["ui"]:
        g.append(f"{c['ui'] - c['ui_covered']} of {c['ui']} implemented UI features have no test or scenario")
    if c["ui"] and c["ui_verified"] == 0:
        g.append("no UI feature carries a `verified:` stamp — run the scenarios with --stamp or the agent pass")
    if c["dangling"]:
        g.append(f"{c['dangling']} dangling test/scenario/evidence link(s)")
    return g


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
def render_check(res: dict) -> str:
    lines = [f"features index: {res['index'] or '—'} ({res['format']}) — {'OK' if res['ok'] else 'INVALID'}"]
    for e in res["errors"]:
        lines.append(f"  ✗ {e}")
    for w in res["warnings"]:
        lines.append(f"  ! {w}")
    c = res["counts"]
    lines.append(f"  features {c['features']} · implemented {c['implemented']} · covered {c['covered']} · evidenced {c['evidenced']} · verified {c['verified']} · UI {c['ui_covered']}/{c['ui']} covered")
    for g in gaps_for(res):
        lines.append(f"  → {g}")
    return "\n".join(lines)


def render_coverage(res: dict) -> str:
    c = res["counts"]
    pct = res.get("pct") or {}
    lines = [
        f"coverage: {pct.get('coverage', 0)}% covered · {pct.get('evidence', 0)}% evidenced · {pct.get('verified', 0)}% verified "
        f"({c['implemented']} implemented of {c['features']}; UI {c['ui_covered']}/{c['ui']} covered)",
        "",
        f"{'id':<14} {'srf':<7} {'impl':<5} {'tests':<5} {'scen':<5} {'evid':<5} {'verified':<12} title",
    ]
    for f in res["features"]:
        v = f["verified"]["date"] if f["verified"] else ("-" if f["implemented"] else "n/a")
        tcol = f"{len(f['tests'])}" + ("w" if f["waived"] else "")
        lines.append(f"{f['id']:<14} {f['surface']:<7} {'yes' if f['implemented'] else 'no':<5} "
                     f"{tcol:<5} {len(f['scenarios']):<5} {len(f['evidence']):<5} {v:<12} {f['title'][:60]}"
                     + (f"   [dangling: {', '.join(f['dangling'])}]" if f["dangling"] else ""))
    kit = res["kit"]
    lines.append("")
    lines.append("kit: " + ", ".join(f"{k}={'yes' if v is True else 'no' if v is False else v}" for k, v in kit.items() if not k.startswith("legacy")))
    if res["last_run"]:
        r = res["last_run"]
        lines.append(f"last run: {r.get('generated')} by {r.get('by')} — {r.get('passed')}/{r.get('total')} passed")
    for g in gaps_for(res):
        lines.append(f"→ {g}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# fleet aggregation
# --------------------------------------------------------------------------- #
def kit_version(hub: Path) -> str:
    v = hub / "templates" / "verify" / "VERSION"
    if v.is_file():
        for line in v.read_text(encoding="utf-8").splitlines():
            if line.startswith("version:"):
                return line.split(":", 1)[1].strip()
    return "0.0.0"


def _gh_urls(entry: dict, item: dict) -> dict:
    """Absolute links the dash can render: live route, docs blob, evidence tree, raw images."""
    repo_url = str(entry.get("repo_url") or "").rstrip("/")
    branch = str(entry.get("branch") or "main")
    live = str(entry.get("live_url") or "").rstrip("/")
    u: dict = {}
    if item.get("link"):
        link = item["link"]
        if link.startswith(("http://", "https://")):
            u["link"] = link
        elif link.startswith("/") and live and item["surface"] == "ui":
            u["link"] = live + link
        elif repo_url:
            u["link"] = f"{repo_url}/blob/{branch}/{link.lstrip('/')}"
    if item.get("docs"):
        d = item["docs"]
        if d.startswith(("http://", "https://")):
            u["docs"] = d
        elif d.startswith("/") and live:
            u["docs"] = live + d
        elif repo_url:
            u["docs"] = f"{repo_url}/blob/{branch}/{d.lstrip('/')}"
    if repo_url:
        u["evidence"] = [f"{repo_url}/tree/{branch}/{e.lstrip('/')}" for e in item.get("evidence", [])]
        u["tests"] = [f"{repo_url}/blob/{branch}/{t.lstrip('/')}" for t in item.get("tests", [])]
        u["scenarios"] = [f"{repo_url}/blob/{branch}/{s.lstrip('/')}" for s in item.get("scenarios", [])]
        m = re.match(r"https?://github\.com/([^/]+)/([^/]+)$", repo_url)
        if m:
            u["screenshots"] = [f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{branch}/{p}" for p in item.get("screenshots", [])]
    return u


def fleet(hub: Path) -> dict:
    registry = yaml.safe_load((hub / "_data" / "projects.yml").read_text(encoding="utf-8")) or []
    entries = [e for e in registry if isinstance(e, dict)]
    # The hub itself is a repo with features (the dash surfaces and loops).
    hub_entry = {"name": "bamr87", "slug": "bamr87", "submodule_path": None, "branch": "main",
                 "repo_url": "https://github.com/bamr87/bamr87", "live_url": "https://bamr87.github.io/bamr87",
                 "status": "active", "category": "dash", "_path": hub}
    repos: list[dict] = []
    attention: list[dict] = []
    totals = {"repos_scanned": 0, "repos_with_index": 0, "repos_with_kit": 0, "repos_prose_only": 0, "repos_no_index": 0,
              "features": 0, "implemented": 0, "covered": 0, "evidenced": 0, "verified": 0, "ui": 0, "ui_covered": 0,
              "ui_verified": 0, "scenarios": 0, "screenshots": 0, "dangling": 0}
    for e in [hub_entry] + entries:
        path = e.get("_path") or (hub / e["submodule_path"] if e.get("submodule_path") else None)
        if not path or not Path(path).is_dir() or (not (Path(path) / ".git").exists() and e.get("name") != "bamr87"):
            continue
        if e.get("status") == "archived":
            continue
        res = analyze(Path(path))
        totals["repos_scanned"] += 1
        if res["format"] in ("fleet", "legacy"):
            totals["repos_with_index"] += 1
        elif res["format"] == "prose":
            totals["repos_prose_only"] += 1
        else:
            totals["repos_no_index"] += 1
        k = res["kit"]
        has_kit = k["config"] or k["legacy_evidence_kit"]
        totals["repos_with_kit"] += int(has_kit)
        c = res["counts"]
        for key in ("features", "implemented", "covered", "evidenced", "verified", "ui", "ui_covered", "ui_verified", "dangling"):
            totals[key] += c[key]
        totals["scenarios"] += k["scenarios"]
        totals["screenshots"] += sum(len(f["screenshots"]) for f in res["features"])
        gaps = gaps_for(res)
        items = []
        for f in res["features"][:MAX_ITEMS]:
            it = {kk: vv for kk, vv in f.items() if kk != "description"}
            it["summary"] = f["description"][:240]
            it["urls"] = _gh_urls(e, f)
            items.append(it)
        repos.append({
            "name": e.get("name"), "slug": e.get("slug") or e.get("name"), "repo_url": e.get("repo_url"),
            "live_url": e.get("live_url"), "branch": e.get("branch") or "main", "status": e.get("status"),
            "category": e.get("category"), "kinds": e.get("kinds"),
            "index": {"path": res["index"], "format": res["format"], "valid": res["ok"],
                      "errors": res["errors"][:20], "warnings": res["warnings"][:40]},
            "kit": k, "counts": c, "pct": res.get("pct") or {"coverage": 0, "evidence": 0, "verified": 0},
            "last_run": res["last_run"], "gaps": gaps, "items": items, "truncated": len(res["features"]) > MAX_ITEMS,
        })
        # Attention: strongest first — an app/site with UI features nobody has
        # ever verified outranks a missing kit file.
        kinds = set(e.get("kinds") or [])
        stack = {str(s).lower() for s in (e.get("stack") or [])}
        ui_stack = (bool(kinds & {"site", "app"}) or c["ui"] > 0 or bool(e.get("live_url"))
                    or bool(stack & UI_STACK_TAGS))
        if res["format"] in ("none", "prose") and ui_stack and e.get("status") in ("active", "maintenance"):
            attention.append({"repo": e["name"], "severity": 70, "kind": "no-index",
                              "detail": ("feature doc is prose only" if res["format"] == "prose" else "user-facing repo with no feature index")
                              + " — agents have no machine-readable map of what it does",
                              "lever": "tools/fanout.sh --kit verify --target " + str(e["name"])})
        if c["ui"] and c["ui_covered"] < c["ui"]:
            attention.append({"repo": e["name"], "severity": 60 + min(30, c["ui"] - c["ui_covered"]), "kind": "ui-uncovered",
                              "detail": f"{c['ui'] - c['ui_covered']} of {c['ui']} implemented UI features have no test or scenario",
                              "lever": "verify-feature skill / `node verify/runner.mjs`"})
        if c["ui"] and c["ui_verified"] == 0 and c["ui_covered"]:
            attention.append({"repo": e["name"], "severity": 50, "kind": "never-verified",
                              "detail": "scenarios exist but no UI feature carries a verified stamp",
                              "lever": "`node verify/runner.mjs --stamp` or label a PR `verify`"})
        if not res["ok"]:
            attention.append({"repo": e["name"], "severity": 80, "kind": "index-invalid",
                              "detail": f"{len(res['errors'])} error(s): {res['errors'][0]}",
                              "lever": "features_index.py check"})
        if c["dangling"]:
            attention.append({"repo": e["name"], "severity": 40, "kind": "dangling-links",
                              "detail": f"{c['dangling']} test/scenario/evidence path(s) in the index do not exist",
                              "lever": "fix the paths in features/features.yml"})
        if res["last_run"] and (res["last_run"].get("failed") or 0) > 0:
            attention.append({"repo": e["name"], "severity": 85, "kind": "scenarios-failing",
                              "detail": f"last runner report: {res['last_run']['failed']} of {res['last_run']['total']} scenario(s) failed",
                              "lever": "open test/evidence/<id>/report.json"})
    attention.sort(key=lambda a: (-a["severity"], a["repo"], a["kind"]))
    repos.sort(key=lambda r: (-(r["counts"]["ui"] - r["counts"]["ui_covered"]), -r["counts"]["features"], r["name"]))
    impl = max(totals["implemented"], 1)
    return {
        "schema": SCHEMA,
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "kit_version": kit_version(hub),
        "totals": totals,
        "pct": {"coverage": round(100 * totals["covered"] / impl), "evidence": round(100 * totals["evidenced"] / impl),
                "verified": round(100 * totals["verified"] / impl),
                "ui_coverage": round(100 * totals["ui_covered"] / max(totals["ui"], 1))},
        "attention": attention[:40],
        "repos": repos,
    }


def _strip_generated(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.startswith("generated_at:"))


def dump(data: dict) -> str:
    header = (
        "# =============================================================================\n"
        "# _data/features_index.yml — THE FLEET FEATURES INDEX (generated)\n"
        "# =============================================================================\n"
        "# GENERATED by tools/features_index.py fleet --write (`dash features fleet --write`).\n"
        "# Do not hand-edit. Every checked-out registry repo's features/features.yml\n"
        "# (schema features/v1, or the legacy shape) aggregated with its verification\n"
        "# coverage — which features have tests, user scenarios, evidence bundles,\n"
        "# screenshots, and a `verified:` stamp — graded from files on disk.\n"
        "# Rendered at /features/ on the dash. Kit: templates/verify/ · doc: docs/VERIFICATION.md\n"
        "# =============================================================================\n"
    )
    return header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="features_index.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check", help="validate one repo's feature index")
    p.add_argument("repo", nargs="?", default=".")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("coverage", help="per-feature coverage table for one repo")
    p.add_argument("repo", nargs="?", default=".")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("fleet", help="aggregate every checked-out submodule → _data/features_index.yml")
    p.add_argument("--hub", default=str(HUB))
    p.add_argument("--write", action="store_true", help="write _data/features_index.yml")
    p.add_argument("--check", action="store_true", help="exit 1 when the committed file is stale")
    p.add_argument("--json", action="store_true")
    p.add_argument("--out", default=None)
    a = ap.parse_args(argv)

    if a.cmd in ("check", "coverage"):
        res = analyze(Path(a.repo))
        if a.json:
            print(json.dumps(res, indent=2, default=str))
        else:
            print(render_check(res) if a.cmd == "check" else render_coverage(res))
        return 0 if res["ok"] else 1

    hub = Path(a.hub).resolve()
    data = fleet(hub)
    out = Path(a.out) if a.out else hub / "_data" / "features_index.yml"
    if a.json:
        print(json.dumps(data, indent=2, default=str))
    else:
        t, pc = data["totals"], data["pct"]
        print(f"fleet features index: {t['repos_with_index']} indexed / {t['repos_prose_only']} prose-only / {t['repos_no_index']} none "
              f"of {t['repos_scanned']} repos · {t['features']} features ({t['implemented']} implemented) · "
              f"{pc['coverage']}% covered · {pc['evidence']}% evidenced · {pc['verified']}% verified · UI {t['ui_covered']}/{t['ui']}")
        for r in data["repos"]:
            c = r["counts"]
            flag = "✓" if r["kit"]["config"] or r["kit"]["legacy_evidence_kit"] else " "
            print(f"  {flag} {r['name']:<22} {r['index']['format']:<7} {c['features']:>3} feat  UI {c['ui_covered']:>2}/{c['ui']:<3} "
                  f"cov {r['pct']['coverage']:>3}%  ver {r['pct']['verified']:>3}%  {('· ' + r['gaps'][0]) if r['gaps'] else ''}")
        if data["attention"]:
            print("attention:")
            for x in data["attention"][:15]:
                print(f"  [{x['severity']}] {x['repo']}: {x['detail']}  → {x['lever']}")
    text = dump(data)
    if a.check:
        if not out.is_file() or _strip_generated(out.read_text(encoding="utf-8")) != _strip_generated(text):
            print(f"STALE: {out} — run tools/features_index.py fleet --write", file=sys.stderr)
            return 1
        print(f"{out} is current")
        return 0
    if a.write:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
