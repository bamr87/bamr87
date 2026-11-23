#!/usr/bin/env python3
"""The fleet assistant baseline — the AI agent integration each repo's platform gets.

Every repo in the registry is one of three things to the assistant (ADR 0014,
specs/ASSIST.md):

  page     it draws pages in a browser, in a framework the kit has an adapter
           for: the kit's payload (templates/assistant/fleet-assist.js) mounts
           there, and a Claude Code session paired with a page can see it and,
           as far as the person allows, use it.
  context  it has no page a browser can outline — a library, a CLI, a terminal
           UI, an extension's webview, a mobile shell, a canvas. The assistant
           reaches it as Claude Code in its checkout, on the agent-context kit
           (AGENTS.md, .claude/settings.json) and the § 16 layers for its type.
  gap      it draws pages in a framework no adapter covers yet. Reported, never
           guessed at: a new framework is a new adapter, reviewed like any other.

`plan()` is pure over the registry rows the app launcher already builds
(fleetcore.apps.repos): nothing here reads a submodule, probes a port or opens a
browser. Whether a repo has the payload installed is the fan-out's and the
conformance checker's to say (tools/fanout.sh --kit assist, UPS-AST-01).

Usage (from tools/, as `tools/dash apps assist` runs it):
    python3 -m fleetcore.assist [plan]     # the table
    python3 -m fleetcore.assist json       # the document (fleet-assist/v1)
    python3 -m fleetcore.assist family <repo>   # one word, for tools/fanout.sh --kit assist
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import apps

HUB = Path(__file__).resolve().parents[2]
SCHEMA = "fleet-assist/v1"
KIT = "templates/assistant"

#: frontend.framework → the adapter that mounts <fleet-assist> there. Matched in order as a substring of
#: the framework name, so `react-vite+django` (a React page over a Django API) is React before it is Django.
#: (family, needle, adapter in the kit, where the fan-out seeds it, how it knows it is in development)
ADAPTERS = (
    ("jekyll", "jekyll", "adapters/jekyll.html",
     "_includes/custom/fleet-assist.html (a zer0-mistakes site takes it from the theme)", "jekyll.environment"),
    ("mkdocs", "mkdocs", "adapters/mkdocs.html", "main.html in the theme's custom_dir",
     "FLEET_ASSIST=1 (an environment variable)"),
    ("nextjs", "nextjs", "adapters/nextjs.tsx", "components/AssistBridgeNext.tsx in the app's folder",
     "the app passes its NODE_ENV"),
    ("react", "react", "adapters/AssistBridge.tsx", "components/AssistBridge.tsx in the app's folder",
     "the app passes its DEV flag"),
    ("django", "django", "adapters/django.html", "templates/includes/fleet-assist.html", "settings.DEBUG"),
    ("static", "static-html", "adapters/static.html", "the page's own HTML", "a loopback address shows the button"),
)
#: a browser surface with nothing in the DOM for a snapshot to outline
NO_DOM = ("godot",)
CONTEXT = "agent-context kit (AGENTS.md, .claude/settings.json) and the § 16 layers for its type"
WHY = {
    "none": "no frontend: the assistant works in its checkout",
    "terminal": "a terminal UI has no page to outline",
    "vscode": "an extension's webview has no address the console can admit (a postMessage link is a later phase)",
    "mobile": "a native shell has no DOM",
    "desktop": "a native window has no DOM",
    "canvas": "its page is one canvas: there is nothing in the DOM to outline",
}


def adapter_for(framework: str | None) -> dict | None:
    """The kit adapter for one `frontend.framework`, or None when no adapter covers it."""
    name = str(framework or "").lower()
    for family, needle, adapter, seeded, dev in ADAPTERS:
        if needle in name:
            return {"family": family, "adapter": adapter, "seeded_to": seeded, "development": dev}
    return None


def baseline(repo: dict) -> dict:
    """One repo's baseline. `repo` is a row of fleetcore.apps.repos()."""
    surfaces = repo.get("surfaces") or []
    framework = repo.get("framework")
    out = {"id": repo["id"], "name": repo["name"], "status": repo.get("status"), "type": repo.get("type"),
           "framework": framework, "surfaces": list(surfaces), "context": CONTEXT}
    if "browser" in surfaces and not any(n in str(framework or "").lower() for n in NO_DOM):
        hit = adapter_for(framework)
        if hit:
            local = [t["url"] for t in repo.get("targets") or [] if t.get("kind") == "local"]
            live = [t["url"] for t in repo.get("targets") or [] if t.get("kind") == "live"]
            return {**out, "level": "page", **hit, "local": local[:1], "live": live[:1],
                    "why": f"draws pages in {framework}: the {hit['family']} adapter mounts the payload"}
        return {**out, "level": "gap",
                "why": f"draws pages in {framework!r}, which no adapter in {KIT}/adapters covers yet"}
    if "browser" in surfaces:
        why = WHY["canvas"]
    else:
        why = next((WHY[s] for s in ("terminal", "vscode", "mobile", "desktop") if s in surfaces), WHY["none"])
    return {**out, "level": "context", "why": why}


def plan(root: Path = HUB) -> dict:
    """The document: every non-archived repo with its baseline, and the counts."""
    rows = [baseline(r) for r in apps.apps_view(root)["repos"]]
    families: dict[str, int] = {}
    for r in rows:
        if r["level"] == "page":
            families[r["family"]] = families.get(r["family"], 0) + 1
    return {"schema": SCHEMA, "kit": KIT, "rows": rows,
            "summary": {"repos": len(rows), "page": sum(r["level"] == "page" for r in rows),
                        "context": sum(r["level"] == "context" for r in rows),
                        "gap": sum(r["level"] == "gap" for r in rows), "families": dict(sorted(families.items()))}}


def family(name: str, root: Path = HUB) -> str | None:
    """What the fan-out seeds for one repo, by its registry name: an adapter family, `none` when the repo is reached
    in its checkout, `gap` when no adapter covers its framework. None when the registry has no such repo.

    The fan-out asks this instead of reading the files at a repo's root, which do not say: an app that lives in a
    subfolder (`app/`, `arcade/`, `web/studio`) has no package.json up there to recognise."""
    want = str(name or "").lower()
    for r in plan(root)["rows"]:
        if want and want in (str(r["name"]).lower(), str(r["id"]).lower()):
            return r["family"] if r["level"] == "page" else ("gap" if r["level"] == "gap" else "none")
    return None


def table(doc: dict) -> str:
    """The plan as a Markdown table (docs/adr/0014, specs/ASSIST.md)."""
    out = ["| repo | platform | baseline | adapter | why |", "| --- | --- | --- | --- | --- |"]
    order = {"page": 0, "gap": 1, "context": 2}
    for r in sorted(doc["rows"], key=lambda r: (order[r["level"]], r.get("family", ""), r["name"].lower())):
        platform = r["framework"] if r["framework"] not in (None, "none") else "—"
        out.append(f"| {r['name']} | {platform} | {r['level']} | {r.get('adapter', '—')} | {r['why']} |")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dash apps assist",
                                 description="The assistant baseline each repo's platform gets (ADR 0014).")
    ap.add_argument("cmd", nargs="?", default="plan", choices=("plan", "json", "family"))
    ap.add_argument("repo", nargs="?", help="family: the repo's registry name")
    a = ap.parse_args(argv)
    if a.cmd == "family":
        # One word for tools/fanout.sh. Exit 3 = the registry has no such repo (the fan-out then reads the files).
        fam = family(a.repo or "", HUB)
        if fam is None:
            return 3
        print(fam)
        return 0
    doc = plan(HUB)
    if a.cmd == "json":
        print(json.dumps(doc, indent=2))
        return 0
    s = doc["summary"]
    print(table(doc))
    fam = ", ".join(f"{n} {k}" for k, n in s["families"].items())
    print(f"\n{s['repos']} repos · {s['page']} get the page bridge ({fam}) · {s['context']} are reached in their "
          f"checkout · {s['gap']} draw pages no adapter covers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
