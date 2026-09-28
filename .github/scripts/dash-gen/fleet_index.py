#!/usr/bin/env python3
"""Code-index analysis for the harness.

Kilo writes this worktree, including checked-out submodules, into Qdrant.
Native Ollama on the Mac embeds the query. This module does not start either
service and does not copy chunks into Elasticsearch — the vector store stays
the source of truth. What it adds is the question the store cannot answer by
itself: which projects share a pattern, and which do not.

`dash index harmonize` is the method. A pattern that scores above
`observability.indexing.analysis.min_score` in one submodule and not another
is a harmonization gap the harness can act on. Coverage is the other half:
a declared submodule with no chunks, or a dot-directory the scanner skips,
is code the harness cannot see.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

import fleet_observe as fo

REPO_ROOT = fo.REPO_ROOT
_GITMODULES_PATH = re.compile(r"^\s*path\s*=\s*(\S+)\s*$", re.M)
HUB = "_hub"
# The scanner walks with dot:false, so `.github` never enters the collection.
# The control plane lives there. Coverage reports the blind spot every time.
BLIND_SPOTS = (".github",)


def analysis_config(contract: dict | None = None) -> dict:
    indexing = (contract if contract is not None else fo.load_contract()).get("indexing") or {}
    analysis = indexing.get("analysis") or {}
    try:
        min_score = float(analysis.get("min_score", 0.66))
    except (TypeError, ValueError):
        min_score = 0.66
    try:
        limit = int(analysis.get("limit", 40))
    except (TypeError, ValueError):
        limit = 40
    return {
        "min_score": min(1.0, max(0.0, min_score)),
        "limit": min(100, max(1, limit)),
        "qdrant": indexing.get("qdrant") or "",
        "embedder": indexing.get("embedder") or "",
        "model": indexing.get("model") or "nomic-embed-text",
    }


def project_of(file_path: str) -> str:
    """`projects/<name>/...` is a submodule. Everything else is the hub."""
    parts = Path(file_path).parts
    if len(parts) >= 2 and parts[0] == "projects":
        return parts[1]
    return HUB


def declared_projects(root: Path | str | None = None) -> list[str]:
    root = Path(root or REPO_ROOT)
    try:
        text = (root / ".gitmodules").read_text()
    except OSError:
        return []
    names = []
    for rel in _GITMODULES_PATH.findall(text):
        parts = Path(rel).parts
        if len(parts) >= 2 and parts[0] == "projects":
            names.append(parts[1])
        elif parts:
            names.append(parts[-1])
    return names


def group_hits(hits: list[dict]) -> dict[str, dict]:
    """Best hit per project. A later weaker hit must not replace a stronger one."""
    best: dict[str, dict] = {}
    for hit in hits:
        project = hit.get("project") or project_of(hit.get("filePath") or "")
        score = float(hit.get("score") or 0)
        current = best.get(project)
        if current is None or score > float(current.get("score") or 0):
            best[project] = {**hit, "project": project, "score": score}
    return best


def harmonize_report(projects: list[str], hits: list[dict], min_score: float) -> dict:
    """Projects above the floor have the pattern. The rest are the gap list."""
    grouped = group_hits(hits)
    present = []
    gaps = []
    for name in projects:
        hit = grouped.get(name)
        if hit and float(hit["score"]) >= min_score:
            present.append(hit)
        else:
            gaps.append(name)
    present.sort(key=lambda h: -float(h["score"]))
    hub = grouped.get(HUB)
    return {
        "min_score": min_score,
        "matched": present,
        "gaps": gaps,
        "hub": hub if hub and float(hub["score"]) >= min_score else None,
        "projects": len(projects),
    }


def coverage_report(counts: dict[str, int], projects: list[str], blind: dict[str, int] | None = None) -> dict:
    """Declared projects against chunk counts. Zero chunks means the harness cannot see that tree."""
    rows = []
    missing = []
    for name in projects:
        n = int(counts.get(name) or 0)
        rows.append({"project": name, "chunks": n})
        if n == 0:
            missing.append(name)
    rows.sort(key=lambda r: -r["chunks"])
    blind = blind or {}
    return {
        "projects": rows,
        "missing": missing,
        "hub_chunks": int(counts.get(HUB) or 0),
        "blind_spots": [{"path": path, "chunks": int(blind.get(path) or 0)} for path in BLIND_SPOTS],
    }


def _get(url: str, timeout: int = 15) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as fh:
            return json.loads(fh.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def _post(url: str, payload: dict, timeout: int = 60) -> dict | None:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as fh:
            return json.loads(fh.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def collection_name(qdrant: str) -> str | None:
    listed = _get(f"{qdrant.rstrip('/')}/collections")
    if not listed:
        return None
    names = [c.get("name") for c in ((listed.get("result") or {}).get("collections") or []) if c.get("name")]
    if not names:
        return None
    if len(names) == 1:
        return names[0]
    best, best_n = names[0], -1
    for name in names:
        detail = _get(f"{qdrant.rstrip('/')}/collections/{name}") or {}
        n = int(((detail.get("result") or {}).get("points_count") or 0))
        if n > best_n:
            best, best_n = name, n
    return best


def embed(text: str, embedder: str, model: str) -> list[float] | None:
    doc = _post(f"{embedder.rstrip('/')}/api/embed", {"model": model, "input": text}, timeout=90)
    if not doc:
        return None
    vectors = doc.get("embeddings") or ([doc["embedding"]] if doc.get("embedding") else [])
    if not vectors or not isinstance(vectors[0], list):
        return None
    return vectors[0]


def _hits_from(found: dict | None) -> list[dict] | None:
    if not found:
        return None
    hits = []
    for row in found.get("result") or []:
        payload = row.get("payload") or {}
        path = payload.get("filePath") or ""
        hits.append({
            "score": float(row.get("score") or 0),
            "filePath": path,
            "startLine": payload.get("startLine"),
            "endLine": payload.get("endLine"),
            "codeChunk": (payload.get("codeChunk") or "")[:240],
            "project": project_of(path),
        })
    return hits


def _search_vector(qdrant: str, name: str, vector: list[float], limit: int, filt: dict | None = None) -> list[dict] | None:
    body: dict = {
        "vector": vector,
        "limit": limit,
        "with_payload": ["filePath", "startLine", "endLine", "codeChunk"],
    }
    if filt:
        body["filter"] = filt
    return _hits_from(_post(f"{qdrant}/collections/{name}/points/search", body))


def _ready(cfg: dict) -> tuple[str, str, list[float]] | str:
    """Embed the query once. A string return is the error."""
    qdrant = (cfg.get("qdrant") or "").rstrip("/")
    embedder = cfg.get("embedder") or ""
    if not qdrant or not embedder:
        return "indexing contract has no qdrant or embedder URL"
    name = collection_name(qdrant)
    if not name:
        return "Qdrant has no collection — the scan has not written one yet"
    vector = embed(cfg["_query"], embedder, cfg.get("model") or "nomic-embed-text")
    if not vector:
        return "Ollama did not return an embedding — is native Ollama running on the Mac?"
    return qdrant, name, vector


def search_hits(query: str, cfg: dict, limit: int | None = None) -> tuple[list[dict], str | None]:
    """Embed once, search the workspace collection, tag each hit with its project."""
    ready = _ready({**cfg, "_query": query})
    if isinstance(ready, str):
        return [], ready
    qdrant, name, vector = ready
    hits = _search_vector(qdrant, name, vector, limit or cfg["limit"])
    if hits is None:
        return [], "Qdrant search did not answer"
    return hits, None


def _count(qdrant: str, name: str, key: str, value: str) -> int | None:
    doc = _post(
        f"{qdrant.rstrip('/')}/collections/{name}/points/count",
        {"filter": {"must": [{"key": key, "match": {"value": value}}]}, "exact": False},
    )
    if not doc:
        return None
    return int((doc.get("result") or {}).get("count") or 0)


def coverage(cfg: dict | None = None, root: Path | str | None = None) -> dict:
    cfg = cfg or analysis_config()
    projects = declared_projects(root)
    qdrant = (cfg.get("qdrant") or "").rstrip("/")
    name = collection_name(qdrant) if qdrant else None
    counts: dict[str, int] = {}
    blind: dict[str, int] = {}
    error = None
    if not name:
        error = "Qdrant has no collection"
    else:
        for project in projects:
            n = _count(qdrant, name, "pathSegments.1", project)
            if n is None:
                error = "Qdrant count did not answer"
                break
            counts[project] = n
        if error is None:
            hub = 0
            for top in ("tools", "docs", "pages", "_data"):
                n = _count(qdrant, name, "pathSegments.0", top)
                hub += n or 0
            counts[HUB] = hub
            for path in BLIND_SPOTS:
                blind[path] = _count(qdrant, name, "pathSegments.0", path) or 0
    report = coverage_report(counts, projects, blind)
    report["collection"] = name
    report["error"] = error
    report["present"] = error is None
    return report


def search(query: str, cfg: dict | None = None, limit: int | None = None) -> dict:
    cfg = cfg or analysis_config()
    hits, error = search_hits(query, cfg, limit)
    return {
        "present": error is None,
        "error": error,
        "query": query,
        "min_score": cfg["min_score"],
        "hits": [h for h in hits if h["score"] >= cfg["min_score"]],
        "below_floor": sum(1 for h in hits if h["score"] < cfg["min_score"]),
    }


def harmonize(query: str, cfg: dict | None = None, root: Path | str | None = None) -> dict:
    """One embedding, then the best hit inside each submodule.

    A global top-k would let one noisy project fill the window and mark every
    other project a gap. Filtering on pathSegments.1 is what makes the gap
    list mean "this repo does not have the pattern."
    """
    cfg = cfg or analysis_config()
    projects = declared_projects(root)
    ready = _ready({**cfg, "_query": query})
    if isinstance(ready, str):
        report = harmonize_report(projects, [], cfg["min_score"])
        report.update({"present": False, "error": ready, "query": query})
        return report
    qdrant, name, vector = ready
    hits = []
    error = None
    for project in projects:
        found = _search_vector(
            qdrant, name, vector, 1,
            {"must": [{"key": "pathSegments.1", "match": {"value": project}}]},
        )
        if found is None:
            error = "Qdrant search did not answer"
            break
        hits.extend(found)
    hub_hits = _search_vector(
        qdrant, name, vector, 1,
        {"must_not": [{"key": "pathSegments.0", "match": {"value": "projects"}}]},
    ) or []
    hits.extend(hub_hits)
    report = harmonize_report(projects, hits, cfg["min_score"])
    report.update({"present": error is None, "error": error, "query": query})
    return report


def _print_hits(hits: list[dict]) -> None:
    for hit in hits:
        line = hit.get("startLine")
        where = f"{hit.get('filePath')}:{line}" if line else hit.get("filePath")
        print(f"  {float(hit.get('score') or 0):.3f}  {hit.get('project'):<16} {where}")


def cmd_status(_args) -> int:
    cfg = analysis_config()
    report = coverage(cfg)
    print(f"collection  {report.get('collection') or 'none'}")
    print(f"embedder    {cfg['model']}  {cfg['embedder']}")
    print(f"min_score   {cfg['min_score']}")
    if report.get("error"):
        print(f"coverage    DOWN  {report['error']}")
        return 1
    rows = report["projects"]
    indexed = sum(1 for r in rows if r["chunks"])
    print(f"coverage    {indexed}/{len(rows)} submodules have chunks, hub {report['hub_chunks']}")
    for spot in report["blind_spots"]:
        mark = "BLIND" if spot["chunks"] == 0 else "ok"
        print(f"  [{mark}] {spot['path']}  {spot['chunks']} chunks")
    missing = report["missing"]
    if missing:
        print("  not in the index: " + ", ".join(missing))
    return 0


def cmd_coverage(_args) -> int:
    report = coverage()
    if report.get("error"):
        print(report["error"])
        return 1
    width = max((len(r["project"]) for r in report["projects"]), default=8)
    for row in report["projects"]:
        print(f"  {row['project']:<{width}}  {row['chunks']:7d}")
    print(f"  {HUB:<{width}}  {report['hub_chunks']:7d}")
    return 0


def cmd_search(args) -> int:
    query = " ".join(args.query or []).strip()
    if not query:
        print("usage: dash index search <pattern>")
        return 2
    doc = search(query)
    if doc.get("error"):
        print(doc["error"])
        return 1
    print(f"{len(doc['hits'])} hits at or above {doc['min_score']} ({doc['below_floor']} dropped)")
    _print_hits(doc["hits"])
    return 0


def cmd_harmonize(args) -> int:
    query = " ".join(args.query or []).strip()
    if not query:
        print("usage: dash index harmonize <pattern>")
        return 2
    doc = harmonize(query)
    if doc.get("error"):
        print(doc["error"])
        return 1
    print(f"pattern    {query}")
    print(f"floor      {doc['min_score']}")
    print(f"present    {len(doc['matched'])}/{doc['projects']}")
    _print_hits(doc["matched"])
    if doc["hub"]:
        print("hub")
        _print_hits([doc["hub"]])
    if doc["gaps"]:
        print(f"gaps       {len(doc['gaps'])}")
        print("  " + ", ".join(doc["gaps"]))
    return 0


def run(args) -> int:
    return {"status": cmd_status, "coverage": cmd_coverage, "search": cmd_search,
            "harmonize": cmd_harmonize}[args.index_cmd](args)


def add_arguments(parser) -> None:
    sub = parser.add_subparsers(dest="index_cmd", required=True)
    sub.add_parser("status", help="collection, embedder, submodule coverage, scanner blind spots")
    sub.add_parser("coverage", help="chunk counts per submodule")
    p_search = sub.add_parser("search", help="semantic search, hits below the contract floor dropped")
    p_search.add_argument("query", nargs="*")
    p_harm = sub.add_parser("harmonize", help="which submodules share a pattern, and which do not")
    p_harm.add_argument("query", nargs="*")
    parser.set_defaults(func=run)
