"""
core_adapters — the documents a console page reads: sections of core's logic,
in their own file.

Each is a thin adapter over a module the CLI already runs (dash-gen's
fleet_lake, fleet_observe, fleet_index, content_atlas, workflow_atlas and
work_board; tools/fleetcore; tools/voices.py; tools/sprint_record.py), and
each degrades to a document that says why rather than a 500:

  CAPABILITIES   what this console can reach (names and booleans only)
  LAKE           the local data lake and the trace export
  OBSERVABILITY  the three local planes, the code index, the lake's runs
  PROJECT        one registry project, and its README
  CONTENT        the content atlas and the editorial plan
  NODES          where hub workloads run
  WORKFLOWS      the hub's own GitHub Actions as one model
  WORK           the board of every open item, its preview and its apply
  SPRINTS        the live expedite-sprint records (read-only)
  STARS          the open-source radar: _data/stars.json (read-only; stars-refresh writes it)
  VOICES         the editor for the fleet voice model

The argv builders these sections had (`_content_sync`, `_content_file`,
`_voices_pr`) stay in core.py beside the OPS table that names them.

core.py loads this module at its end and re-exports every name in it, so callers
keep writing `core.<name>`. What core owns (its paths, constants and helpers, the
OPS table, and every name a test or tools/evals.py rebinds) is read here as
`core.<name>` at the moment of the call, never copied, so rebinding one on core
reaches this code as it did when this was a section of core.py. To replace a
name DEFINED here, patch it on this module: this file calls its own names directly.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import os
import re
import shutil
import sys
import threading
import time
from pathlib import Path

if "core" not in sys.modules:  # the order is a rule, not luck: core loads this module at its end
    raise ImportError("core_adapters is a section of core: import core, which loads it and re-exports its names")
import core  # noqa: E402
from fleetcore import yamlio  # noqa: E402  (core put tools/ on sys.path)


# --------------------------------------------------------------------------- #
# CAPABILITIES — what this console can reach (names and booleans only)
# --------------------------------------------------------------------------- #
def _has_module(name: str) -> bool:
    """Is this optional dependency importable?

    find_spec, not a bare import: `import ruamel.yaml` would rebind the local
    name to the module object and leak it into the JSON response. But find_spec
    on a DOTTED name imports the parent first and RAISES ModuleNotFoundError
    when the parent is absent — the exact case this probe exists to report — so
    the miss has to be caught rather than compared against None.
    """
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def capabilities() -> dict:
    tools = {name: shutil.which(name) is not None
             for name in ("git", "gh", "python3", "docker", "actionlint", "shellcheck", "bundle")}
    gh_auth = None
    if tools["gh"]:
        rc, _ = core.run_quiet(["gh", "auth", "status"], timeout=20)
        gh_auth = rc == 0
    has_ruamel = _has_module("ruamel.yaml")
    has_otel = all(_has_module(m)
                   for m in ("opentelemetry.sdk", "opentelemetry.exporter.otlp.proto.http"))
    return {
        "tools": tools,
        "gh_authenticated": gh_auth,
        "env_tokens": {name: bool(os.environ.get(name)) for name in core.CREDENTIALS},
        "contract_editing": has_ruamel,
        "config_editing": has_ruamel,
        "auth_writes": core.AUTH_WRITES,
        "console_token_required": bool(os.environ.get("DASH_CONSOLE_TOKEN")),
        "python": sys.version.split()[0],
        "job_dir": str(core.JOB_DIR),
        "lake_dir": str(core.LAKE_DIR),
        "lake_present": (core.LAKE_DIR / "fleet.sqlite").exists(),
        "otel_exporter": has_otel,
        "phoenix": {"collector": core.PHOENIX_COLLECTOR, "ui": core.PHOENIX_UI},
        # All three local planes in one key, so the Observe tab can render a
        # pane per plane without three round trips. Kept BESIDE the legacy
        # `phoenix` key rather than replacing it: anything already reading that
        # key keeps working, which is cheaper than finding every reader.
        "observability": observability_planes(probe=False),
    }


# --------------------------------------------------------------------------- #
# LAKE — the local data lake + trace export, read through dash-gen's module
# --------------------------------------------------------------------------- #
def _lake_module():
    core._dash_gen_on_path()
    import fleet_lake  # noqa: WPS433
    return fleet_lake


def lake_status(probe: bool = True) -> dict:
    """The /api/lake document: what the lake holds and whether Phoenix answers.
    Degrades to a 'not present' document rather than a 500."""
    try:
        return _lake_module().status_dict(core.LAKE_DIR, probe=probe, collector=core.PHOENIX_COLLECTOR, ui=core.PHOENIX_UI)
    except Exception as exc:  # the module is optional at import time
        return {"present": False, "lake_dir": str(core.LAKE_DIR), "error": f"{exc.__class__.__name__}: {exc}",
                "tables": {}, "repos": [], "agent_runs": {"count": 0}, "exports": {"count": 0},
                "phoenix": {"collector": core.PHOENIX_COLLECTOR, "ui": core.PHOENIX_UI, "reachable": None}}


# --------------------------------------------------------------------------- #
# OBSERVABILITY — the three local planes, read through dash-gen's module
# --------------------------------------------------------------------------- #
def _observe_module():
    core._dash_gen_on_path()
    import fleet_observe  # noqa: WPS433
    return fleet_observe


def _index_module():
    core._dash_gen_on_path()
    import fleet_index  # noqa: WPS433
    return fleet_index


def index_query(kind: str, query: str) -> dict:
    """Search or harmonize the code index. Never raises: a down store is a document."""
    query = (query or "").strip()
    if not query:
        return {"present": False, "error": "query is empty", "query": ""}
    if len(query) > 500:
        return {"present": False, "error": "query is longer than 500 characters", "query": query[:80]}
    try:
        mod = _index_module()
        fn = mod.harmonize if kind == "harmonize" else mod.search
        return fn(query)
    except Exception as exc:
        return {"present": False, "error": f"{exc.__class__.__name__}: {exc}", "query": query}


def index_coverage() -> dict:
    try:
        return _index_module().coverage()
    except Exception as exc:
        return {"present": False, "error": f"{exc.__class__.__name__}: {exc}", "projects": [], "missing": [],
                "blind_spots": [], "hub_chunks": 0}


def observability_planes(probe: bool = True) -> dict:
    """Per-plane identity and (optionally) reachability.

    Never raises. A plane that is down has to render as a pane with a Start
    button, not as a 500 that takes the whole tab with it — the same
    degrade-don't-explode contract lake_status() keeps.

    probe=False skips the network entirely, which is what /api/capabilities
    wants: that document is fetched on every page load.
    """
    try:
        fo = _observe_module()
        contract = fo.load_contract()
    except Exception as exc:
        return {"present": False, "error": f"{exc.__class__.__name__}: {exc}",
                "logs": {}, "metrics": {}, "traces": {}, "indexing": {}, "portal": {}}
    if probe:
        planes = fo.plane_status(contract)
    else:
        logs, metrics, traces = contract["logs"], contract["metrics"], contract["traces"]
        indexing = contract.get("indexing") or {}
        planes = {
            "logs": {"engine": logs.get("engine"), "url": logs.get("kibana"),
                     "elasticsearch": logs.get("elasticsearch"), "reachable": None},
            "metrics": {"engine": metrics.get("engine"), "url": metrics.get("grafana"),
                        "reachable": None, "datasources": metrics.get("datasources") or []},
            "traces": {"engine": traces.get("engine"), "url": traces.get("endpoint"),
                       "reachable": None},
            "indexing": {"engine": indexing.get("engine"), "url": indexing.get("qdrant"),
                         "embedder": indexing.get("embedder"), "model": indexing.get("model"),
                         "reachable": None, "embedder_reachable": None},
            "telemetry": {"engine": "otel-collector", "url": fo.claude_contract(contract)["endpoint"],
                          "prometheus": metrics.get("prometheus"), "reachable": None,
                          "prometheus_reachable": None},
        }
    planes["present"] = True
    planes["portal"] = contract.get("portal") or {}
    return planes


def observe_status() -> dict:
    """The /api/observability document: planes, dataset sizes, ship lag.

    This is the probing one — it is fetched when the Observe tab opens, not on
    every page load.
    """
    try:
        fo = _observe_module()
        contract = fo.load_contract()
        planes = fo.plane_status(contract)
        doc = {
            "present": True,
            "planes": planes,
            "portal": contract.get("portal") or {},
            "disk_budget_gb": contract["logs"]["disk_budget_gb"],
            "retention_days": contract["logs"]["retention_days"],
            "datasets": fo.dataset_stats(contract) if planes["logs"]["reachable"] else [],
            "embeds": observe_embeds(contract),
        }
        doc["bytes_total"] = sum(d.get("bytes") or 0 for d in doc["datasets"])
        doc["over_budget"] = doc["bytes_total"] > doc["disk_budget_gb"] * 1024 ** 3
        try:
            conn = _lake_module().connect(core.LAKE_DIR, create=False)
            row = conn.execute("SELECT COUNT(*) c, MAX(shipped_at) last FROM shipments "
                               "WHERE sink = ?", (fo.SINK,)).fetchone()
            doc["shipments"] = {"count": row[0], "last": row[1]}
            # Ship replays the lake, so an empty lake ships nothing — and a
            # zero ledger beside indexed documents means they came from an
            # earlier lake, not that shipping is broken.
            doc["lake_runs"] = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        except Exception:
            doc["shipments"] = {"count": 0, "last": None}
            doc["lake_runs"] = None
        return doc
    except Exception as exc:
        return {"present": False, "error": f"{exc.__class__.__name__}: {exc}",
                "planes": {}, "datasets": [], "embeds": {}, "shipments": {"count": 0, "last": None},
                "lake_runs": None}


def observe_embeds(contract: dict) -> dict:
    """The iframe URLs for the Observe tab.

    Built here rather than in the browser so the PINNED ids stay in one place —
    the contract — instead of being half in fleet.yml and half in a template
    string in index.html, which is how an embed ends up pointing at a dashboard
    that was renamed six months ago.
    """
    portal = contract.get("portal") or {}
    dash = portal.get("dashboards") or {}
    kibana = (contract.get("logs") or {}).get("kibana") or ""
    grafana = (contract.get("metrics") or {}).get("grafana") or ""
    logs_id = (dash.get("logs") or {}).get("id")
    metrics_uid = (dash.get("metrics") or {}).get("uid")
    out = {"enabled": bool(portal.get("embed"))}
    if kibana and logs_id:
        # embed=true strips Kibana's own chrome; the time range comes from the
        # dashboard's saved timeRestore rather than a _g we would have to keep
        # in step with it.
        out["logs"] = f"{kibana}/app/dashboards#/view/{logs_id}?embed=true&show-top-menu=false"
    if grafana and metrics_uid:
        out["metrics"] = f"{grafana}/d/{metrics_uid}/{metrics_uid}?kiosk&theme=dark"
        out["metrics_panel"] = f"{grafana}/d-solo/{metrics_uid}/{metrics_uid}?panelId=%s&theme=dark"
    out["traces"] = (contract.get("traces") or {}).get("endpoint") or ""
    return out


def frame_src() -> list[str]:
    """The CSP frame-src allowlist, stated once in _data/fleet.yml.

    A missing origin here is not an error anyone sees: the browser refuses the
    frame and writes one line to a console nobody has open.

    The console asks on every response (its Content-Security-Policy names
    these), so fleet.yml is re-read only when it changed, as
    fleetcore.apps.target_origins re-reads the two registries.
    """
    def build() -> list[str]:
        contract = observe.load_contract()
        portal = contract.get("portal") or {}
        urls = list(portal.get("frame_src") or [])
        for url in ((contract.get("logs") or {}).get("kibana"),
                    (contract.get("metrics") or {}).get("grafana"),
                    (contract.get("traces") or {}).get("endpoint")):
            if url and url not in urls:
                urls.append(url)
        return urls

    try:
        observe = _observe_module()
        return list(yamlio.cached("console.frame_src", (observe.FLEET_DEFAULT,), build))
    except Exception:
        return []


def lake_runs(limit: int = 50) -> list[dict]:
    try:
        return _lake_module().recent_runs(core.LAKE_DIR, limit=limit)
    except Exception:
        return []


def lake_lines() -> list[dict]:
    try:
        return _lake_module().lines(core.LAKE_DIR)
    except Exception:
        return []


def lake_review(days: int = 30, repo: str | None = None, limit: int = 10) -> dict:
    """The /api/lake/review document: local Claude Code sessions and CI agent
    runs unified — cost, turns, tools, failures, and the ranked findings."""
    try:
        return _lake_module().review(core.LAKE_DIR, days=days, repo=repo, limit=limit)
    except Exception as exc:
        return {"present": False, "error": f"{exc.__class__.__name__}: {exc}",
                "local": {}, "ci": {}, "totals": {}, "findings": []}


def lake_recall(query: str, days: int = 30, repo: str | None = None, limit: int = 10) -> dict:
    """The /api/lake/recall document (`lake recall --json`): the stored local
    sessions whose first prompt or one assistant turn holds every word of the
    query, best match first, each with a redacted excerpt. The lake is opened
    read-only. A query with no words raises ValueError (the route's 422); any
    other failure is a document that says why, never a 500."""
    try:
        mod = _lake_module()
    except Exception as exc:  # the module is optional at import time
        return {"present": False, "error": f"{exc.__class__.__name__}: {exc}", "results": []}
    try:
        return mod.recall(core.LAKE_DIR, query, days=days, repo=repo, limit=limit)
    except ValueError:
        raise
    except Exception as exc:
        return {"present": False, "error": f"{exc.__class__.__name__}: {exc}", "results": []}


# --------------------------------------------------------------------------- #
# PROJECT — one registry project, every signal the console holds about it
# --------------------------------------------------------------------------- #
def project_detail(name: str) -> dict:
    """The drill-down document for one registry project: its registry entry,
    its harness deployment and crons, the attention findings that name it, and
    its runs + workflows in the local lake. Every piece already exists in a
    committed file or the lake; this only joins them on the project name, so
    the page never has to fetch five whole documents to show one repo.

    Raises KeyError for a name the registry does not carry.
    """
    if not core.NAME_RX.match(name or ""):
        raise ValueError("invalid project name")
    registry = core.load_yaml(core.DATA / "projects.yml") or []
    entry = next((p for p in registry if isinstance(p, dict) and p.get("name") == name), None)
    if entry is None:
        raise KeyError(name)
    hr = core.load_yaml(core.DATA / core.SOURCES["harness_registry"])
    hr = hr if isinstance(hr, dict) else {}
    # A run belongs to the project when its owner/name ends in /<name> — the
    # lake keys on GitHub's nwo, the registry on the bare name.
    owned = (lambda nwo: str(nwo or "").lower().endswith("/" + name.lower()))
    return {
        "name": name,
        "registry": {k: v for k, v in entry.items() if not str(k).startswith("_")},
        "harness": next((r for r in hr.get("repos") or [] if r.get("repo") == name), None),
        "schedule": [s for s in hr.get("schedule") or [] if s.get("repo") == name],
        "attention": [a for a in hr.get("attention") or [] if a.get("repo") == name],
        "lake_runs": [r for r in lake_runs(500) if owned(r.get("nwo"))][:60],
        "lake_lines": [w for w in lake_lines() if owned(w.get("nwo"))],
    }


README_NAMES = ("README.md", "readme.md", "README.markdown", "README.rst", "README")
README_CAP = 200_000  # characters; a README longer than this is cut and says so


def project_readme(name: str) -> dict:
    """A registry project's README, read from its submodule checkout on this
    machine — the first page of the repo app the console generates for a repo
    that has no frontend of its own (ADR 0005, phase F1).

    Local only. The public snapshot never calls this: a private repo's README
    checked out on the build machine must not reach the public site. The path
    comes from the registry's `submodule_path`, never from the request, and
    must sit under projects/.

    Raises KeyError for a name the registry does not carry.
    """
    if not core.NAME_RX.match(name or ""):
        raise ValueError("invalid project name")
    registry = core.load_yaml(core.DATA / "projects.yml") or []
    entry = next((p for p in registry if isinstance(p, dict) and p.get("name") == name), None)
    if entry is None:
        raise KeyError(name)
    sub = entry.get("submodule_path")
    if not sub:
        return {"present": False, "reason": "not a submodule of the hub"}
    projects = (core.REPO_ROOT / "projects").resolve()
    base = (core.REPO_ROOT / str(sub)).resolve()
    if projects != base.parent:
        return {"present": False, "reason": "its registry path is not directly under projects/"}
    for candidate in README_NAMES:
        path = base / candidate
        try:
            if not path.is_file() or path.is_symlink():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        return {"present": True, "path": f"{sub}/{candidate}", "markdown": text[:README_CAP],
                "truncated": len(text) > README_CAP}
    checked_out = base.is_dir() and any(base.iterdir())
    return {"present": False, "reason": "it has no README file" if checked_out else "not checked out on this machine"}


# --------------------------------------------------------------------------- #
# CONTENT — the content atlas + the editorial plan (docs/CONTENT-ATLAS.md)
# --------------------------------------------------------------------------- #
EDITORIAL = Path(os.environ.get("DASH_EDITORIAL_PLAN") or (core.DATA / "editorial.yml"))
CONTENT_VIEWS = ("all", "stale", "issues", "thin", "recent", "drafts", "unmapped")


# `_rel`, used below as core._rel, is REFINE documents' (core_refine.py): the definition this
# section's callers always resolved to. CONTENT's own, shadowed one stayed in core.py.


def _content_module():
    core._dash_gen_on_path()
    import content_atlas  # noqa: WPS433
    return content_atlas


def _content_inputs():
    ca = _content_module()
    return ca, ca.load_contract(core.DATA / "fleet.yml", core.DATA / "projects.yml"), ca.load_plan(EDITORIAL)


def content_report(site: str | None = None) -> dict:
    """The /api/content document: every declared site analyzed from the lake,
    plus the editorial plan's view of it. Degrades to a 'not present' document
    (with the declared sites, so the tab can offer the sync) rather than a 500."""
    try:
        ca, contract, plan = _content_inputs()
        declared = [{"name": s["name"], "repo": s.get("repo"), "live_url": s.get("live_url")}
                    for s in contract["sites"]]
    except Exception as exc:
        return {"present": False, "error": f"{exc.__class__.__name__}: {exc}", "declared": [], "sites": [],
                "overlap": [], "unsynced": [], "fleet": {}}
    if site is not None and site not in {s["name"] for s in declared}:
        raise ValueError(f"unknown site '{site}'")
    try:
        try:
            conn = ca.connect(core.LAKE_DIR, create=False)
        except FileNotFoundError:
            return {"present": False, "declared": declared, "sites": [], "overlap": [],
                    "unsynced": [s["name"] for s in declared], "fleet": {}}
        doc = ca.report(conn, contract, plan, site=site)
        doc.update(present=True, declared=declared, plan_path=core._rel(EDITORIAL))
        return doc
    except Exception as exc:
        return {"present": False, "error": f"{exc.__class__.__name__}: {exc}", "declared": [], "sites": [],
                "overlap": [], "unsynced": [], "fleet": {}}


def content_documents(site: str, view: str = "all", q: str = "", limit: int = 200) -> list[dict]:
    if not core.NAME_RX.match(site or ""):
        raise ValueError("site must be a plain name")
    if view not in CONTENT_VIEWS and not re.match(r"^pillar:[a-z0-9][a-z0-9._-]{0,63}$", view or ""):
        raise ValueError(f"view must be one of {CONTENT_VIEWS} or pillar:<id>")
    ca, contract, plan = _content_inputs()
    try:
        conn = ca.connect(core.LAKE_DIR, create=False)
    except FileNotFoundError:
        return []
    return ca.documents(conn, site, view=view, q=str(q or "")[:120], limit=max(1, min(int(limit), 1000)),
                        contract=contract, plan=plan)


def _plan_diff() -> str:
    rc, diff = core.run_quiet(["git", "diff", "--no-color", "--", str(EDITORIAL)])
    if rc == 0 and not diff:
        # an untracked plan has no diff against HEAD; say so rather than show nothing
        rc2, out = core.run_quiet(["git", "ls-files", "--error-unmatch", str(EDITORIAL)])
        if rc2 != 0:
            return f"(new file: {core._rel(EDITORIAL)} — not yet tracked)"
    return diff if rc == 0 else ""


def editorial_decide(site: str, action: str, key: str, fields: dict | None = None) -> dict:
    """Approve / reject a suggestion, add a directive, or move one — written to
    _data/editorial.yml in the working tree (comments preserved). The commit is
    the approval of record, and it stays with the human, as everywhere else."""
    ca, contract, plan = _content_inputs()
    suggestion = None
    if action in ("approve", "reject"):
        doc = content_report(site)
        a = (doc.get("sites") or [None])[0]
        suggestion = next((s for s in (a or {}).get("suggestions") or [] if s["key"] == key), None)
    result = ca.decide(EDITORIAL, site, action, key, contract, suggestion=suggestion, fields=fields or {})
    result["diff"] = _plan_diff()
    return result


def editorial_update(site: str, fields: dict) -> dict:
    ca, contract, _plan = _content_inputs()
    result = ca.update_site(EDITORIAL, site, contract, fields or {})
    result["diff"] = _plan_diff()
    return result


def content_brief(site: str) -> dict:
    doc = content_report(site)
    if not doc.get("sites"):
        raise ValueError(f"'{site}' is not in the atlas yet — run 'Content: sync' first")
    return {"site": site, "markdown": _content_module().render_brief(doc["sites"][0])}


# --------------------------------------------------------------------------- #
# NODES — where hub workloads run (tools/fleetcore/nodes.py, docs/PLATFORM.md):
# the document `tools/dash node status --json` prints and the MCP's fleet_nodes
# returns. A node that is not enabled is never probed; an enabled one is probed
# with a short time limit, and the page's polls share one answer for a few
# seconds, so an unreachable node costs one probe per window, never one per tab.
# --------------------------------------------------------------------------- #
NODES_TTL = 15.0
NODES_PROBE_TIMEOUT = 5
_NODES: dict = {}
_NODES_LOCK = threading.Lock()


def _fleet_nodes():
    if str(core.TOOLS) not in sys.path:
        sys.path.insert(0, str(core.TOOLS))
    from fleetcore import nodes
    return nodes


def nodes_doc(*, probe: bool = True) -> dict:
    """The Nodes page's document. `probe=False` is the public snapshot's: the
    committed placement model, nothing read from any machine."""
    nodes = _fleet_nodes()
    if not probe:
        return nodes.status_doc(probe=False)
    with _NODES_LOCK:
        if _NODES and time.monotonic() - _NODES["at"] < NODES_TTL:
            return _NODES["doc"]
        doc = nodes.status_doc(timeout=NODES_PROBE_TIMEOUT)
        _NODES.update(at=time.monotonic(), doc=doc)
        return doc


# --------------------------------------------------------------------------- #
# WORKFLOWS — the hub's own GitHub Actions as one model (dash-gen
# workflow_atlas.py; docs/WORKFLOW-ATLAS.md): structure + lint from the
# checkout (also in the public snapshot), run health from the lake (local).
# --------------------------------------------------------------------------- #
def _atlas_module():
    core._dash_gen_on_path()
    import workflow_atlas  # noqa: WPS433
    return workflow_atlas


def _default_branch_text(rel: str) -> str | None:
    """A file as the hub's default branch holds it — what `gh workflow run`
    runs — from the last fetch; None when git cannot say."""
    branch = str(((core.load_yaml(core.DATA / "fleet.yml") or {}).get("hub") or {}).get("default_branch") or "main")
    rc, out = core.run_quiet(["git", "show", f"origin/{branch}:{rel}"], timeout=10)
    return out if rc == 0 and out.strip() else None


def dispatch_inputs() -> dict[str, list[dict]]:
    """Each allowlisted workflow → the inputs its file declares (name, type,
    default, options), so the console's form and its validation follow the
    file. Read from the default branch, which is the file GitHub runs, else
    from the working tree; a file that cannot be read offers no inputs rather
    than breaking every other dispatch."""
    atlas = _atlas_module()
    out: dict[str, list[dict]] = {}
    for wf in core.DISPATCH_WORKFLOWS:
        path = core.REPO_ROOT / ".github" / "workflows" / f"{wf}.yml"
        text = _default_branch_text(core._rel(path)) or (path.read_text(encoding="utf-8") if path.is_file() else None)
        if text is None:
            continue
        try:
            out[wf] = atlas.parse_workflow(core._rel(path), text)["dispatch_inputs"]
        except Exception:  # one unreadable file must not take dispatch down for the other eight
            out[wf] = []
    return out


def dispatchable() -> dict[str, list[str]]:
    return {wf: sorted(i["name"] for i in inputs) for wf, inputs in dispatch_inputs().items()}


def workflow_atlas() -> dict:
    """The /api/workflows document: the atlas, joined with what only the
    console knows — which loop a workflow is, and whether it may dispatch it."""
    doc = _atlas_module().scan(core.REPO_ROOT)
    loops = {loop["workflow"]: loop["id"] for loop in core.LOOPS}
    for wf in doc["workflows"]:
        wf["loop"] = loops.get(wf["id"])
        wf["dispatchable"] = wf["id"] in core.DISPATCH_WORKFLOWS and "workflow_dispatch" in wf["triggers"]
    doc["kinds"] = _atlas_module().KINDS
    return doc


def workflow_health(days: int = 30) -> dict:
    """The /api/workflows/health document: the lake's runs of the hub per
    workflow, with each failure's cause and class. Local only."""
    atlas = _atlas_module()
    hub = str(((core.load_yaml(core.DATA / "fleet.yml") or {}).get("hub") or {}).get("repo") or atlas.HUB_DEFAULT)
    try:
        return atlas.lake_health(core.LAKE_DIR, hub, days, core.REPO_ROOT)
    except Exception as exc:
        return {"present": False, "error": f"{exc.__class__.__name__}: {exc}", "nwo": hub, "days": days,
                "workflows": [], "totals": {}, "classes": {}, "ghosts": [], "class_hints": atlas.CLASSES}


def workflow_lint(text: str, wid: str = "draft") -> dict:
    """Lint a draft workflow against the hub's fleet.yml (nothing is written).
    `wid` is the file stem it would have — its schedule key and call sites."""
    atlas = _atlas_module()
    if len(text) > 200_000:
        raise ValueError("a workflow draft is limited to 200 KB")
    if not atlas.ID_RX.match(wid or ""):
        raise ValueError("id must be lowercase letters, digits and dashes, starting with a letter")
    return atlas.lint_text(text, core.load_yaml(core.DATA / "fleet.yml") or {}, f".github/workflows/{wid}.yml")


def workflow_scaffold(params: dict) -> dict:
    """Preview a new workflow (the designer); `workflow-new` writes it."""
    atlas = _atlas_module()
    return atlas.scaffold(str(params.get("kind") or ""), str(params.get("id") or "").strip(),
                          str(params.get("name") or "").strip() or None, str(params.get("cron") or "").strip() or None,
                          str(params.get("purpose") or ""), core.REPO_ROOT)


# --------------------------------------------------------------------------- #
# WORK — the board of every open item and the order the loops take them in
# (dash-gen's work_board.py + work_queue.py; docs/WORK-BOARD.md)
# --------------------------------------------------------------------------- #
# WORK_QUEUE and ROADMAP stay in core.py (tests rebind them there): read here as core.WORK_QUEUE
# and core.ROADMAP at each call.
# Label moves this process made, newest per issue, overlaid on the board until
# the issue-pipeline snapshot is newer than the move — otherwise a card would
# snap back to its old lane the moment the move succeeds.
WORK_MOVES: dict[str, dict] = {}
_WORK_LOCK = threading.Lock()


def _work_module():
    core._dash_gen_on_path()
    import work_board  # noqa: WPS433
    return work_board


def work_inputs(local: bool = True) -> dict:
    return _work_module().load_inputs(core.REPO_ROOT, local=local, queue_path=core.WORK_QUEUE, roadmap_path=core.ROADMAP,
                                      moves=dict(WORK_MOVES))


def work_board(plan: dict | None = None, local: bool = True) -> dict:
    """The /api/work document; with a plan, the board as it would be (nothing written)."""
    doc = _work_module().build(work_inputs(local), plan)
    doc["queue_path"] = core._rel(core.WORK_QUEUE)
    return doc


def work_item(key: str) -> dict:
    return _work_module().item_detail(work_inputs(), key)


def _work_diff() -> str:
    paths = [str(core.WORK_QUEUE), str(core.ROADMAP)]
    rc, diff = core.run_quiet(["git", "diff", "--no-color", "--", *paths])
    out = diff if rc == 0 else ""
    rc2, _ = core.run_quiet(["git", "ls-files", "--error-unmatch", str(core.WORK_QUEUE)])
    if rc2 != 0 and core.WORK_QUEUE.exists():
        out = f"(new file: {core._rel(core.WORK_QUEUE)} — not yet tracked)\n" + core.WORK_QUEUE.read_text(encoding="utf-8") + out
    return out


def work_apply(plan: dict, confirm: bool = False, label_writer=None) -> dict:
    """Apply a board plan: issue label moves on GitHub (each through
    `label_writer`, i.e. github_link.act — fleet-scoped, logged), then the
    roadmap.yml edits and the work_queue.yml entries in the working tree.

    Nothing is committed: the diff comes back for the human to review and
    commit, as with every other console write. A plan that moves labels needs
    confirm=true. Keys for items that no longer exist are pruned."""
    wb = _work_module()
    with _WORK_LOCK:
        inp = work_inputs()
        board = wb.build(inp)
        resolved = wb.resolve_plan(board["items"], plan or {}, inp["queue"], inp["cfg"]["labels"]["state"])
        if not resolved["changes"]:
            raise ValueError("the plan changes nothing")
        if resolved["labels"] and not confirm:
            raise PermissionError("moving an issue changes its labels on GitHub — it needs confirm=true")
        if resolved["labels"] and label_writer is None:
            raise RuntimeError("no GitHub writer is available to this console")

        results: list[dict] = []
        for mv in resolved["labels"]:
            what = next(c["what"] for c in resolved["changes"] if c["key"] == mv["key"])
            try:
                entry = label_writer(mv["nwo"], mv["number"], mv["add"], mv["remove"])
                WORK_MOVES[mv["key"]] = {"lane": mv["to"], "at": entry.get("at")}
                results.append({"key": mv["key"], "target": "github", "what": what, "ok": True, "error": None})
            except Exception as exc:  # report it; the file half of the plan still applies
                results.append({"key": mv["key"], "target": "github", "what": what, "ok": False,
                                "error": core._scrub(str(exc))})

        if resolved["roadmap"]:
            text = core.ROADMAP.read_text(encoding="utf-8")
            for ff, fields in resolved["roadmap"].items():
                text = wb.edit_roadmap(text, ff, status=fields.get("status"), priority=fields.get("priority"),
                                       reason=fields.get("reason"))
            core.ROADMAP.write_text(text, encoding="utf-8")
        q = resolved["queue"]
        stale = set(board["sources"]["work_queue"]["stale_keys"])
        pruned: list[str] = []
        if q["pins"] or q["unpin"] or q["priority"] or q["notes"] or stale:
            new = wb.preview_queue(inp["queue"], resolved)
            keys = {*new["order"], *new["priority"], *new["notes"]}
            new, pruned = wb.wq.prune(new, keys - stale)
            wb.wq.save(core.WORK_QUEUE, {**new, "updated_at": dt.date.today().isoformat()})
        for c in resolved["changes"]:
            if c["target"] != "github":
                results.append({**c, "ok": True, "error": None})
    return {"results": results, "pruned": pruned, "diff": _work_diff(), "board": work_board()}


# --------------------------------------------------------------------------- #
# SPRINTS — the live expedite-sprint records (tools/sprint_record.py,
# constitution § 27.7). Read-only: a record changes only by a pull request,
# so there is no write path here and no route that writes one.
# --------------------------------------------------------------------------- #
def _sprint_module():
    if str(core.TOOLS) not in sys.path:
        sys.path.insert(0, str(core.TOOLS))
    import sprint_record  # noqa: WPS433
    return sprint_record


def sprints_doc() -> dict:
    """The /api/sprints document: every `_data/sprints/<slug>.yml` record, linted —
    gates with who and when, phase, items, spend against the cap, trip wires, the
    DORA placeholder and the retro. DASH_SPRINTS_DIR points it at another directory
    (the page's evidence build reads the test fixture through it)."""
    folder = Path(os.environ.get("DASH_SPRINTS_DIR") or (core.DATA / "sprints"))
    return _sprint_module().document(folder, fleet_path=core.DATA / "fleet.yml", queue_path=core.WORK_QUEUE)


# --------------------------------------------------------------------------- #
# STARS — the open-source radar (fleetcore/stars.py, tools/stargazer.py; docs/STARGAZER.md)
# --------------------------------------------------------------------------- #
STARS_FILE = core.DATA / "stars.json"


def stars_doc() -> dict:
    """The /api/stars document: `_data/stars.json` as committed (schema stars/v1) — the account's stars, the
    repos rising in the fleet's topics, each fleet project's closest repos, what to review, the AI reviews and
    themes, and the feed — with `present` and its age, or `present: false` and how to make one. Public data
    (GitHub shows stars to anyone), so the published build carries it whole; the `stars-refresh` operation
    rewrites it."""
    from fleetcore import stars as fstars  # noqa: PLC0415
    doc = yamlio.cached(("stars", str(STARS_FILE)), [STARS_FILE], lambda: fstars.load(STARS_FILE))
    if not doc:
        return {"schema": fstars.SCHEMA, "present": False, "generated_at": None, "age_days": None,
                "error": "no radar yet: run `tools/dash stars refresh` (the stars-refresh operation)",
                "totals": {}, "categories": [], "languages": [], "timeline": [], "health": {}, "starred": [],
                "lists": [], "trending": [], "gaining": [], "fleet": [], "incorporate": [], "feed": [],
                "errors": [], "repos": {}}
    return {**doc, "present": True, "age_days": fstars.age_days(doc)}


# --------------------------------------------------------------------------- #
# VOICES — the editor for the fleet voice model (constitution § 23 rule 7)
# --------------------------------------------------------------------------- #
# `_data/voices/voices.yml` is the only copy: the page loads it (with its check
# errors and its drift from origin/main), previews an edit as the exact bytes
# and diff a PR would carry (writing nothing), stages those bytes OUTSIDE the
# repo under the job dir, and the `voices-pr` op files them — a dry run, then,
# behind confirm, one branch and one draft PR that change that file alone
# (tools/voices.py `pr`, the OPS remote-write path of § 11.8).
VOICES_PLAN_RX = re.compile(r"^[0-9a-f]{16}$")


def _voices():
    if str(core.TOOLS) not in sys.path:
        sys.path.insert(0, str(core.TOOLS))
    import voices  # noqa: PLC0415 - tools/voices.py, shared with the CLI
    return voices


def voices_stage_dir() -> Path:
    return core.JOB_DIR / "voices"


def voices_doc() -> dict:
    """The Voices page's document: the file, its check errors, its drift from
    origin/main, the form's vocabularies. Reads only."""
    return _voices().editor_doc(core.REPO_ROOT)


def voices_preview(data) -> dict:
    """An edit validated, rendered and diffed against main, with its plan id. Writes nothing."""
    return _voices().preview(data, core.REPO_ROOT)


def voices_stage(data, plan_id: str) -> dict:
    """Stage a previewed edit for `voices-pr`: the bytes the preview showed, under
    the console's job dir (never the working tree). Refused when the edit fails
    the check, changes nothing, or no longer matches the plan id it was previewed as."""
    if not VOICES_PLAN_RX.fullmatch(str(plan_id or "")):
        raise ValueError("plan_id must be the 16-hex id of a preview")
    p = voices_preview(data)
    if not p["ok"]:
        raise ValueError(f"the edit fails tools/voices.py check: {'; '.join(p['errors'][:5])}")
    if not p["changed"]:
        raise ValueError(f"nothing to file: the edit equals voices.yml on {p['base']}")
    if p["plan_id"] != plan_id:
        raise PermissionError(f"the edit or main moved since plan {plan_id} was previewed (now {p['plan_id']}) "
                              "— preview again")
    # Named from the server's own sha256 prefix of base + bytes (equal to the
    # request's plan_id by the check above), never from the request's string.
    staged_id = p["plan_id"]
    folder = voices_stage_dir()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{staged_id}.yml").write_text(p["text"], encoding="utf-8")
    return {"plan_id": plan_id, "staged": True, "base": p["base"], "changes": p["changes"], "diff": p["diff"]}
