#!/usr/bin/env python3
"""
File: tools/gen-catalog.py
Description: Generate CATALOG.md — the master index of everything the hub
             provides as the fleet's central repository: specs, kits,
             reference implementations, registries, tools, workflows/loops,
             the AI layer (skills/commands/agents/hooks), Copilot-format
             personas/instructions/prompts, docs, dash surfaces, diagrams.
             Built from what is on disk plus the one-line purposes already
             kept in each directory's README/SCHEMA table, so it cannot drift.
Author: bamr87
Created: 2026-09-01
Last Modified: 2026-09-01
Version: 0.1.0
Usage: python3 tools/gen-catalog.py [--check]
       --check  exit 1 when CATALOG.md is stale
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "CATALOG.md"
MAX = 170  # purpose cells are trimmed to the first sentence, then to this many chars


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def frontmatter(p: Path) -> dict:
    text = read(p)
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    block = text[3:end]
    try:
        data = yaml.safe_load(block) or {}
        if isinstance(data, dict):
            return data
    except yaml.YAMLError:
        pass
    # Fallback for frontmatter that is not strict YAML (unquoted colons in a
    # description): take top-level `key: value` lines verbatim.
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"^([A-Za-z_-]+):\s*(.+)$", block, re.M)}


def key_of(cell: str) -> str:
    """Normalise a table's first cell to a bare filename/identifier."""
    c = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cell)  # [text](link) -> text
    c = c.replace("**", "").replace("`", "").strip()
    return c.split(" ")[0].strip("/")


def table_map(p: Path, col: int = -1) -> dict[str, str]:
    """First-cell -> chosen-column map for every markdown table in a file."""
    out: dict[str, str] = {}
    for line in read(p).splitlines():
        if not line.startswith("|") or re.match(r"^\|\s*-", line):
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
        if len(cells) < 2:
            continue
        k = key_of(cells[0])
        if k and k.lower() not in ("file", "script", "workflow", "agent", "diagram", "entry", "prompt", "template", "doc", "document", "name"):
            out.setdefault(k, cells[col].replace("\\|", "|"))
            out.setdefault(Path(k).name, cells[col].replace("\\|", "|"))
    return out


def self_purpose(p: Path) -> str:
    """Fallback one-liner from the file itself: a `Description:` header line,
    the first blockquote, the first top-of-file comment sentence, or the H1."""
    text = read(p)
    fm = frontmatter(p) if p.suffix == ".md" else {}
    if fm.get("description"):
        return str(fm["description"])
    m = re.search(r"^\s*#?\s*Description:\s*(.+)$", text, re.M)
    if m:
        return m.group(1)
    m = re.search(r"^>\s*(?!\*\*Status|\*\*Note|\[!)(.+)$", text, re.M)
    if m:
        return m.group(1)
    if p.suffix in (".yml", ".yaml"):
        cm = [l.lstrip("# ").rstrip() for l in text.splitlines() if l.startswith("#")]
        if cm:
            return " ".join(cm[:3])
    if p.suffix == ".py":
        m = re.search(r'"""\s*(?:File:.*?\n)?\s*(?:Description:\s*)?(.+?)(?:\n\s*\n|Author:|Usage:)', text, re.S)
        if m:
            return re.sub(r"\s+", " ", m.group(1))
    m = re.search(r"^#\s+(.+)$", text, re.M)
    return m.group(1) if m else ""


def short(s: str, n: int = MAX) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    s = re.sub(r"_\(summary unverified\)_", "", s).strip()
    m = re.match(r"^(.{20,}?[.!?])(\s|$)", s)
    if m and len(m.group(1)) <= n:
        s = m.group(1)
    if len(s) > n:
        s = s[: n - 1].rstrip() + "…"
    return s.replace("|", "\\|")


def row(*cells: str) -> str:
    return "| " + " | ".join(cells) + " |"


def header(*cols: str) -> list[str]:
    return [row(*cols), "| " + " | ".join("---" for _ in cols) + " |"]


# --------------------------------------------------------------------------- #
# sections
# --------------------------------------------------------------------------- #
def sec_specs() -> list[str]:
    data = yaml.safe_load(read(ROOT / "_data" / "specs.yml")) or {}
    reqs = data.get("requirements", [])
    out = ["## 1. Specs — the Universal Project Standard", "",
           f"[`specs/README.md`](specs/README.md) is the spec index (UPS {data.get('version')}, {data.get('status')}); [`_data/specs.yml`](_data/specs.yml) is its generated twin. "
           f"{len(reqs)} requirements: {sum(r['level']=='MUST' for r in reqs)} MUST, {sum(r['level']=='SHOULD' for r in reqs)} SHOULD, {sum(r['level']=='MAY' for r in reqs)} MAY; {sum(bool(r.get('gap')) for r in reqs)} still lack a seed kit.", ""]
    out += header("Area", "Spec", "Ids", "MUST / SHOULD / MAY", "Gaps", "Governs")
    for a in data.get("areas", []):
        rs = [r for r in reqs if r["area"] == a["id"]]
        nums = sorted(int(r["id"].rsplit("-", 1)[1]) for r in rs)
        out.append(row(a["id"], f"[`{Path(a['file']).name}`]({a['file']})",
                       f"UPS-{a['id']}-{nums[0]:02d}…{nums[-1]:02d}",
                       f"{sum(r['level']=='MUST' for r in rs)} / {sum(r['level']=='SHOULD' for r in rs)} / {sum(r['level']=='MAY' for r in rs)}",
                       str(sum(bool(r.get('gap')) for r in rs)), short(a["title"])))
    out.append(row("—", "[`STACKS.md`](specs/STACKS.md)", "—", "—", "—", "Stack-family profiles and the applicability matrix"))
    out.append(row("—", "[`CONFORMANCE.md`](specs/CONFORMANCE.md)", "—", "—", "—", "Declaring, auditing, adoption order, the fleet gap list"))
    return out + [""]


def sec_kits() -> list[str]:
    out = ["## 2. Kits — seedable artifacts", "",
           "Versioned file sets copied into repos by [`tools/fanout.sh`](tools/fanout.sh) and the fan-out workflows; index and placeholders in [`templates/README.md`](templates/README.md).", ""]
    out += header("Kit", "Version", "Updated", "Seeded by", "Files")
    for d in sorted(p for p in (ROOT / "templates").iterdir() if p.is_dir()):
        v = yaml.safe_load(read(d / "VERSION")) if (d / "VERSION").exists() else {}
        if not isinstance(v, dict):
            v = {}
        files = ", ".join(f"`{f.relative_to(d)}`" for f in sorted(d.rglob("*")) if f.is_file() and f.name not in ("VERSION",) and "archive" not in f.parts)
        version = v.get("version") or (f"spec {v['spec']}" if v.get("spec") else "unversioned")
        updated = v.get("updated") or v.get("vendored") or "—"
        out.append(row(f"[`{d.name}/`](templates/{d.name}/)", str(version), str(updated),
                       short(str(v.get("seeded-by") or ("tools/seed-schema.sh / schema-fanout.yml" if d.name == "schema" else "tools/adopt-release.sh" if d.name == "release-pipeline" else "—")), 90), short(files, 200)))
    return out + [""]


def sec_refs() -> list[str]:
    refs = yaml.safe_load(read(ROOT / "_data" / "references.yml")) or []
    out = ["## 3. Reference implementations", "",
           "Where each spec row was lifted from — go here for a proven implementation, not a blank page. Source: [`_data/references.yml`](_data/references.yml).", ""]
    out += header("Reference", "Repo · path", "Reference for", "Note")
    for r in refs:
        out.append(row(r["name"], f"`{r['repo']}` · `{r['path']}`", ", ".join(r.get("reference_for", [])), short(r.get("note", ""))))
    return out + [""]


def sec_data() -> list[str]:
    purposes = table_map(ROOT / "_data" / "SCHEMA.md", 2)
    rules = table_map(ROOT / "_data" / "SCHEMA.md", 3)
    proj = yaml.safe_load(read(ROOT / "_data" / "projects.yml")) or []
    by_status: dict[str, int] = {}
    for p in proj:
        by_status[p.get("status", "?")] = by_status.get(p.get("status", "?"), 0) + 1
    out = ["## 4. Registries and data", "",
           f"[`_data/projects.yml`](_data/projects.yml) is THE project registry ({len(proj)} projects: " + ", ".join(f"{v} {k}" for k, v in sorted(by_status.items())) + "); "
           "[`_data/fleet.yml`](_data/fleet.yml) is the control plane's own config. Contract: [`_data/SCHEMA.md`](_data/SCHEMA.md).", ""]
    out += header("File", "Purpose", "Rules")
    for f in sorted((ROOT / "_data").glob("*.*")):
        if f.name == "SCHEMA.md":
            continue
        out.append(row(f"[`{f.name}`](_data/{f.name})", short(purposes.get(f.name, "—")), rules.get(f.name, "") or "—"))
    return out + [""]


def sec_tools() -> list[str]:
    purposes = table_map(ROOT / "tools" / "README.md", 1)
    out = ["## 5. Tools and the `dash` CLI", "",
           "Operator scripts, gates, and generators; index in [`tools/README.md`](tools/README.md). `tools/dash <subcommand>` is the unified CLI.", ""]
    out += header("Script", "Purpose")
    for f in sorted((ROOT / "tools").iterdir()):
        if f.is_dir() or f.name in ("README.md", "SCHEMA.md"):
            continue
        out.append(row(f"[`{f.name}`](tools/{f.name})", short(purposes.get(f.name) or self_purpose(f) or "—")))
    return out + [""]


def sec_workflows() -> list[str]:
    readme = ROOT / ".github" / "workflows" / "README.md"
    triggers = table_map(readme, 1)
    purposes = table_map(readme, 2)
    out = ["## 6. Workflows and loops", "",
           "The control-plane automation; standards and the full table in [`.github/workflows/README.md`](.github/workflows/README.md). Reusable workflows are marked.", ""]
    out += header("Workflow", "Name", "Triggers", "Purpose")
    for f in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        doc = yaml.safe_load(read(f)) or {}
        name = str(doc.get("name", f.stem))
        on = doc.get(True, doc.get("on", {}))
        reusable = isinstance(on, dict) and "workflow_call" in on
        out.append(row(f"[`{f.name}`](.github/workflows/{f.name})", name + (" (reusable)" if reusable else ""),
                       short(triggers.get(f.name, "—"), 60), short(purposes.get(f.name) or self_purpose(f) or "—")))
    return out + [""]


def sec_ai() -> list[str]:
    out = ["## 7. AI layer (`.claude/`)", "",
           "Indexed by [`.claude/README.md`](.claude/README.md). Skills and commands are Claude Code entrypoints; `feature-scout` is the one Task-launchable agent; hooks drive the Future-Features pipeline. Only the `settings.json` baseline fans out to the fleet (see UPS-AGENT-11).", ""]
    out += ["### Skills", ""] + header("Skill", "Description")
    for d in sorted(p for p in (ROOT / ".claude" / "skills").iterdir() if p.is_dir()):
        fm = frontmatter(d / "SKILL.md")
        out.append(row(f"[`{d.name}`](.claude/skills/{d.name}/SKILL.md)", short(str(fm.get("description", "—")))))
    out += ["", "### Commands", ""] + header("Command", "Description")
    for f in sorted((ROOT / ".claude" / "commands").glob("*.md")):
        fm = frontmatter(f)
        out.append(row(f"[`/{f.stem}`](.claude/commands/{f.name})", short(str(fm.get("description", "—")))))
    out += ["", "### Agents and hooks", ""] + header("Entry", "Description")
    for f in sorted((ROOT / ".claude" / "agents").glob("*.md")):
        fm = frontmatter(f)
        out.append(row(f"[`agents/{f.name}`](.claude/agents/{f.name})", short(str(fm.get("description", "—")))))
    for f in sorted((ROOT / ".claude" / "hooks").glob("*.py")):
        first = next((l.strip("# ").strip() for l in read(f).splitlines()[1:12] if l.strip().startswith(("#", '"""')) and len(l.strip()) > 8), "")
        out.append(row(f"[`hooks/{f.name}`](.claude/hooks/{f.name})", short(first.strip('"'))))
    out.append(row("[`settings.json`](.claude/settings.json)", "Permissions allowlist + hook registration; the fleet `.claude/` baseline is seeded from `templates/agent-context/settings.template.json`"))
    out.append(row("[`.mcp.json`](.mcp.json)", "MCP servers the hub's agents rely on"))
    return out + [""]


def sec_copilot() -> list[str]:
    out = ["## 8. Copilot-format personas, instructions, prompts (`.github/`)", "",
           "Reference templates consumed in place by hub skills (e.g. `evolve-project` reads the personas); nothing seeds them into submodules.", ""]
    for sub, label in (("agents", "Persona"), ("instructions", "Instruction set"), ("prompts", "Prompt")):
        purposes = table_map(ROOT / ".github" / sub / "README.md", 1)
        out += [f"### {sub}", ""] + header(label, "Purpose")
        for f in sorted((ROOT / ".github" / sub).glob("*.md")):
            if f.name == "README.md":
                continue
            fm = frontmatter(f)
            purpose = purposes.get(f.name) or str(fm.get("description", "")) or "—"
            extra = f" (applies to `{fm['applyTo']}`)" if fm.get("applyTo") else ""
            out.append(row(f"[`{f.name}`](.github/{sub}/{f.name})", short(purpose + extra)))
        out.append("")
    out += ["### evolution", "", "[`.github/evolution/`](.github/evolution/) — the repo-evolution brief material (`evolve-prompt.md`, per-category prompts) consumed by `dash-gen targets`.", ""]
    return out


def sec_docs() -> list[str]:
    purposes = table_map(ROOT / "docs" / "README.md", 1)
    out = ["## 9. Operator docs", "", "Index in [`docs/README.md`](docs/README.md). UPPERCASE files are topic docs of record; lowercase are guides.", ""]
    out += header("Doc", "Purpose")
    for f in sorted((ROOT / "docs").glob("*.md")):
        if f.name in ("README.md", "SCHEMA.md"):
            continue
        out.append(row(f"[`{f.name}`](docs/{f.name})", short(purposes.get(f.name) or self_purpose(f) or "—")))
    for f in ("AGENTS.md", "CLAUDE.md", "SUBMODULES.md", "CONTRIBUTING.md", "SCHEMA.md"):
        if (ROOT / f).exists():
            out.append(row(f"[`{f}`]({f})", short(purposes.get(f) or self_purpose(ROOT / f) or "—")))
    return out + [""]


def sec_dash() -> list[str]:
    out = ["## 10. Dash surfaces", "", "The Jekyll site's collections under [`pages/_dash/`](pages/_dash/), published at `bamr87.github.io/bamr87/`.", ""]
    out += header("Surface", "Path", "Description")
    for f in sorted((ROOT / "pages" / "_dash").glob("*.md")):
        fm = frontmatter(f)
        out.append(row(str(fm.get("title", f.stem)), f"`{fm.get('permalink', '/' + f.stem + '/')}`", short(str(fm.get("description", "—")))))
    return out + [""]


def sec_diagrams() -> list[str]:
    shows = table_map(ROOT / "diagrams" / "README.md", 1)
    out = ["## 11. Diagrams", "", "archify JSON IR + delivered HTML under [`diagrams/`](diagrams/); rendered by `tools/render-diagrams.sh`.", ""]
    out += header("Diagram", "Shows")
    for f in sorted((ROOT / "diagrams").glob("*.json")):
        out.append(row(f"[`{f.stem}`](diagrams/{f.stem}.html)", short(shows.get(f.stem, "—"))))
    return out + [""]


def render() -> str:
    lines = [
        "<!-- GENERATED by tools/gen-catalog.py — do not hand-edit; regenerate after adding a spec, kit, tool, skill, workflow, doc, or data file. -->",
        "# Index — the bamr87 hub as the fleet's central repository",
        "",
        "> Everything the hub provides to the ~40 fleet repos and to any AI agent working in them, in one place: the **specs** repos are built to, the **kits** that seed them, the **reference implementations** they lift from, the **registries** that drive every surface, the **tools**, the **loops**, the **AI layer**, and the **docs**.",
        "",
        "**Start here.** Orientation is a chain: [`SCHEMA.md`](SCHEMA.md) (what lives where) → [`CLAUDE.md`](CLAUDE.md) / [`AGENTS.md`](AGENTS.md) (how to work) → [`specs/README.md`](specs/README.md) (what every repo must be) → [`docs/DASH.md`](docs/DASH.md) (how the control plane runs). Creating or restructuring a project: read [`specs/STACKS.md`](specs/STACKS.md) first, then [`specs/CONFORMANCE.md`](specs/CONFORMANCE.md) for the adoption order. Adding to the hub: place per the nearest `SCHEMA.md`, then run `python3 tools/gen-catalog.py`.",
        "",
        "| # | Section | What it indexes |",
        "| --- | --- | --- |",
        "| 1 | [Specs](#1-specs--the-universal-project-standard) | `specs/*.md`, `_data/specs.yml` |",
        "| 2 | [Kits](#2-kits--seedable-artifacts) | `templates/*/` |",
        "| 3 | [Reference implementations](#3-reference-implementations) | `_data/references.yml` |",
        "| 4 | [Registries and data](#4-registries-and-data) | `_data/*` |",
        "| 5 | [Tools and the dash CLI](#5-tools-and-the-dash-cli) | `tools/*` |",
        "| 6 | [Workflows and loops](#6-workflows-and-loops) | `.github/workflows/*.yml` |",
        "| 7 | [AI layer](#7-ai-layer-claude) | `.claude/{skills,commands,agents,hooks}` |",
        "| 8 | [Copilot-format templates](#8-copilot-format-personas-instructions-prompts-github) | `.github/{agents,instructions,prompts,evolution}` |",
        "| 9 | [Operator docs](#9-operator-docs) | `docs/*.md` + root docs of record |",
        "| 10 | [Dash surfaces](#10-dash-surfaces) | `pages/_dash/*.md` |",
        "| 11 | [Diagrams](#11-diagrams) | `diagrams/*.json` |",
        "",
    ]
    for sec in (sec_specs, sec_kits, sec_refs, sec_data, sec_tools, sec_workflows, sec_ai, sec_copilot, sec_docs, sec_dash, sec_diagrams):
        lines += sec()
    lines += ["## Fleet", "",
              "The projects themselves are submodules under [`projects/`](projects/) — the registry [`_data/projects.yml`](_data/projects.yml) is authoritative and [`projects/SCHEMA.md`](projects/SCHEMA.md) is generated from it. Each is a separate repo with its own pyramid; commit there first, then bump the pointer here ([`SUBMODULES.md`](SUBMODULES.md)).", ""]
    return "\n".join(lines)


def main() -> int:
    text = render()
    if "--check" in sys.argv:
        if not OUT.exists() or read(OUT) != text:
            print("STALE: CATALOG.md — run tools/gen-catalog.py", file=sys.stderr)
            return 1
        print("fresh: CATALOG.md")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote CATALOG.md ({text.count(chr(10))} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
