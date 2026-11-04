#!/usr/bin/env python3
"""
File: tools/jev/surface.py
Description: JEV capability three, part one — the HARNESS SURFACE. Harness²
             (google-research/harness2, Apache-2.0) names eight editable
             components around a fixed model: system prompt, guardrails,
             memory, tool guidance, subagents, skills, scripts and plugins,
             and validates a candidate harness as a tree of files before any
             rollout spends a cent. This module maps those eight components
             onto what a Claude Code harness is actually made of — the
             context-file chain (`CLAUDE.md`, `AGENTS.md`), the permission
             and hook blocks of `.claude/settings.json`, `.claude/agents/`,
             `.claude/skills/`, `.claude/commands/`, the hook scripts,
             `.mcp.json` and the Copilot-format instruction files — reads a
             repository's surface as one tree, and validates it with the
             rules both sources agree on: the always-on text is capped (it
             is paid for on every turn), a skill needs `name` and
             `description` frontmatter (agentskills.io; dropped silently
             otherwise), its `name` must match its directory, a subagent
             needs a description, a hooks block must have the shape the
             runtime dispatches or it never fires, every script a component
             names must exist, and context files are scanned for
             prompt-injection phrasing (Barbaste et al. 2026, Hermes).
             Everything here is offline, deterministic and $0: a sensor in
             the HARNESS.md sense, not a judge.
Author: bamr87
Created: 2026-11-04
Version: 0.1.0
Usage: python3 -m tools.jev refine surface check [ROOT] [--json]
       python3 -m tools.jev refine surface census [ROOT] [--json]
       python3 -m tools.jev refine surface diff BEFORE AFTER
Dependencies: Python 3.12 stdlib + PyYAML. No dash-gen import.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .common import HUB, JevError

#: Harness²'s eight components (c1..c8), in its order.
COMPONENTS = ("system_prompt", "guardrails", "memory", "tool_guidance", "subagents", "skills", "scripts",
              "plugins")
COMPONENT_LABELS = {
    "system_prompt": "c1 system prompt — the context-file chain, always on",
    "guardrails": "c2 guardrails — permission rules, policy as data",
    "memory": "c3 memory — durable facts the agent reads back",
    "tool_guidance": "c4 tool guidance — how to use the tools",
    "subagents": "c5 subagents — delegated roles in their own context",
    "skills": "c6 skills — capability bundles, loaded on demand",
    "scripts": "c7 scripts — deterministic helpers",
    "plugins": "c8 plugins — hooks and servers that act inside the tool loop",
}
#: Claude Code's hook events (the vocabulary Codex adopted near-verbatim,
#: Barbaste et al. § 12); a hooks block naming another event never fires.
HOOK_EVENTS = frozenset({"PreToolUse", "PostToolUse", "PermissionRequest", "Notification", "UserPromptSubmit",
                         "SessionStart", "SessionEnd", "Stop", "SubagentStart", "SubagentStop", "PreCompact",
                         "PostCompact"})
HOOK_TYPES = frozenset({"command", "prompt", "agent", "http"})
#: a skill or agent directory / file name (agentskills.io: lower-case, digits, hyphens)
NAME_RX = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
#: a script a component names, under the roots a hub-shaped repository keeps
#: scripts in; a reference with a placeholder or a glob is not a reference
SCRIPT_REF_RX = re.compile(
    r"(?<![\w/])((?:tools|\.claude/hooks|\.claude/skills|\.github/scripts)/[A-Za-z0-9_./-]+\.(?:py|sh|mjs|js))\b")
PLACEHOLDER_CHARS = "<>{}*$"
#: a `$CLAUDE_PROJECT_DIR/<path>` or bare relative path in a hook command
HOOK_PATH_RX = re.compile(r"(?:\$CLAUDE_PROJECT_DIR|\$\{CLAUDE_PROJECT_DIR\})/([A-Za-z0-9_./-]+)")
#: prompt-injection phrasing in a context file or skill (Hermes scans every
#: context file and blocks on a match; here it is a warning, because a hub
#: that documents injection defences names the phrases)
INJECTION_RX = re.compile(
    r"ignore (?:all |any |the )?(?:previous|prior|above|earlier) (?:instructions|rules|guidance)|"
    r"disregard (?:all |any |the )?(?:previous|prior|above|earlier) (?:instructions|rules)|"
    r"reveal (?:the |your )?system prompt|"
    r"do not tell the user|"
    r"exfiltrat", re.I)
FRONTMATTER_RX = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.S)
MAX_FILE_BYTES = 1024 * 1024
#: Claude Code caps each skill it loads at 25,000 tokens (Barbaste et al.
#: § 9); about four characters a token
DEFAULT_SKILL_MAX_CHARS = 100_000
#: the always-on cap when no `_data/fleet.yml` `harness_refinement` says
#: otherwise: the hub's own context chain is about 21,000 characters
DEFAULT_ALWAYS_ON_MAX = 32_000
ALWAYS_ON_WARN_PCT = 80
#: directories under a skill that are never read (vendored kits carry whole trees)
SKIP_DIRS = frozenset({"node_modules", "__pycache__", ".git", "worktrees", "dist", "build", ".venv"})

Tree = dict[str, str]


class SurfaceError(JevError):
    """A surface that cannot be read: not a directory, a symlinked root."""


@dataclass(frozen=True)
class SurfaceSpec:
    """The editable surface of one agent framework, as paths; `claude_code`
    is the one the hub and every fleet repo use."""

    name: str
    always_on: tuple[str, ...]
    always_on_max: int
    settings_file: str
    mcp_file: str
    skills_dir: str
    agents_dir: str
    commands_dir: str
    hooks_dir: str
    tool_guidance_dir: str
    memory_dirs: tuple[str, ...]
    skill_max_chars: int = DEFAULT_SKILL_MAX_CHARS


def claude_code(*, always_on_max: int = DEFAULT_ALWAYS_ON_MAX,
                skill_max_chars: int = DEFAULT_SKILL_MAX_CHARS) -> SurfaceSpec:
    return SurfaceSpec(
        name="claude_code",
        always_on=("CLAUDE.md", "AGENTS.md"),
        always_on_max=int(always_on_max),
        settings_file=".claude/settings.json",
        mcp_file=".mcp.json",
        skills_dir=".claude/skills",
        agents_dir=".claude/agents",
        commands_dir=".claude/commands",
        hooks_dir=".claude/hooks",
        tool_guidance_dir=".github/instructions",
        memory_dirs=(".claude/memory", "_data/harness_library"),
        skill_max_chars=int(skill_max_chars),
    )


def surface_from_fleet(fleet: Mapping | None) -> SurfaceSpec:
    """The `claude_code` surface with `_data/fleet.yml` `harness_refinement`
    caps when the block is present and sane; the defaults otherwise."""
    cfg = (fleet or {}).get("harness_refinement") if isinstance(fleet, Mapping) else None
    cfg = cfg if isinstance(cfg, Mapping) else {}
    cap = cfg.get("always_on_max_chars", DEFAULT_ALWAYS_ON_MAX)
    skill_cap = cfg.get("skill_max_chars", DEFAULT_SKILL_MAX_CHARS)
    if not _positive_int(cap):
        raise SurfaceError(f"_data/fleet.yml harness_refinement.always_on_max_chars = {cap!r} is not a positive int")
    if not _positive_int(skill_cap):
        raise SurfaceError(f"_data/fleet.yml harness_refinement.skill_max_chars = {skill_cap!r} is not a positive int")
    return claude_code(always_on_max=cap, skill_max_chars=skill_cap)


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


# --------------------------------------------------------------------------- #
# classification: which component a path belongs to
# --------------------------------------------------------------------------- #
def component_of(surface: SurfaceSpec, rel: str) -> str | None:
    """The component a relative path belongs to, or None when it is off the surface."""
    rel = rel.replace("\\", "/").removeprefix("./")
    if rel in surface.always_on:
        return "system_prompt"
    if rel == surface.settings_file:
        return "guardrails"
    if rel == surface.mcp_file:
        return "plugins"
    if rel.startswith(surface.skills_dir + "/") or rel.startswith(surface.commands_dir + "/"):
        return "skills"
    if rel.startswith(surface.agents_dir + "/"):
        return "subagents"
    if rel.startswith(surface.hooks_dir + "/"):
        return "scripts"
    if rel.startswith(surface.tool_guidance_dir + "/") and rel.endswith(".md"):
        return "tool_guidance"
    if any(rel.startswith(d + "/") for d in surface.memory_dirs):
        return "memory"
    return None


def skill_name(surface: SurfaceSpec, rel: str) -> str | None:
    """`<skills_dir>/<name>/SKILL.md` → name; None for any other path."""
    parts = rel.split("/")
    base = surface.skills_dir.split("/")
    if parts[: len(base)] == base and len(parts) == len(base) + 2 and parts[-1] == "SKILL.md":
        return parts[len(base)]
    return None


def agent_name(surface: SurfaceSpec, rel: str) -> str | None:
    parts = rel.split("/")
    base = surface.agents_dir.split("/")
    if parts[: len(base)] == base and len(parts) == len(base) + 1 and parts[-1].endswith(".md"):
        return parts[-1][: -len(".md")]
    return None


def command_name(surface: SurfaceSpec, rel: str) -> str | None:
    parts = rel.split("/")
    base = surface.commands_dir.split("/")
    if parts[: len(base)] == base and len(parts) == len(base) + 1 and parts[-1].endswith(".md"):
        return parts[-1][: -len(".md")]
    return None


# --------------------------------------------------------------------------- #
# reading
# --------------------------------------------------------------------------- #
def _read_text(p: Path) -> str | None:
    """A regular text file's content, or None (a link, a directory, too big, binary)."""
    try:
        if p.is_symlink() or not p.is_file() or p.stat().st_size > MAX_FILE_BYTES:
            return None
        data = p.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:4096]:
        return None
    return data.decode("utf-8", errors="replace")


def _walk(root: Path, rel_dir: str, *, exts: tuple[str, ...] | None = None) -> Iterable[Path]:
    d = root / rel_dir
    if d.is_symlink() or not d.is_dir():
        return
    for p in sorted(d.rglob("*")):
        if any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        if not p.is_file() or p.is_symlink():
            continue
        if exts is not None and p.suffix not in exts:
            continue
        yield p


def read_tree(surface: SurfaceSpec, root: Path | str) -> Tree:
    """Every readable text file on the surface, keyed by its path relative to
    `root`: the always-on files, the settings and MCP files, every file under
    the skills, agents, commands and hooks directories, the instruction files
    and the memory directories. Vendored subtrees (`node_modules`, build
    output) are skipped; a binary or oversized file is left out."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise SurfaceError(f"{root} is not a directory")
    tree: Tree = {}
    for rel in (*surface.always_on, surface.settings_file, surface.mcp_file):
        text = _read_text(root / rel)
        if text is not None:
            tree[rel] = text
    for rel_dir in (surface.skills_dir, surface.agents_dir, surface.commands_dir, surface.hooks_dir,
                    *surface.memory_dirs):
        for p in _walk(root, rel_dir):
            text = _read_text(p)
            if text is not None:
                tree[p.relative_to(root).as_posix()] = text
    for p in _walk(root, surface.tool_guidance_dir, exts=(".md",)):
        text = _read_text(p)
        if text is not None:
            tree[p.relative_to(root).as_posix()] = text
    return tree


def always_on_text(surface: SurfaceSpec, tree: Tree) -> str:
    return "\n\n".join(tree.get(a, "") for a in surface.always_on)


def frontmatter(text: str) -> tuple[dict | None, str, str | None]:
    """(frontmatter mapping or None, the body, a problem). No block → ({}, text, None)."""
    m = FRONTMATTER_RX.match(text)
    if not m:
        return {}, text, None
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError as exc:
        return None, text[m.end():], f"frontmatter is not YAML ({str(exc).splitlines()[0]})"
    if data is None:
        return {}, text[m.end():], None
    if not isinstance(data, dict):
        return None, text[m.end():], "frontmatter is not a mapping"
    return data, text[m.end():], None


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #
@dataclass
class Report:
    """What a surface check found. `errors` fail `check`; `warnings` and
    `notes` are printed; `census` is the inventory `census()` computes."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    census: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {"ok": self.ok, "errors": list(self.errors), "warnings": list(self.warnings),
                "notes": list(self.notes), "census": self.census}


def _nonempty_str(v: object) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _check_skills(surface: SurfaceSpec, tree: Tree, body: str, rep: Report) -> list[dict]:
    skills: list[dict] = []
    for rel in sorted(tree):
        name = skill_name(surface, rel)
        if name is None:
            continue
        fm, skill_body, problem = frontmatter(tree[rel])
        row = {"name": name, "path": rel, "chars": len(tree[rel]), "triggered": name in body,
               "paths": False, "description_chars": 0, "resources": 0}
        if problem or fm is None:
            rep.errors.append(f"{rel}: {problem or 'frontmatter is not a mapping'} — the skill is dropped silently "
                              f"at load (agentskills.io)")
        else:
            if not _nonempty_str(fm.get("description")):
                rep.errors.append(f"{rel}: needs a `description:` in its frontmatter, or the skill is dropped "
                                  f"silently at load")
            else:
                row["description_chars"] = len(str(fm["description"]))
            fm_name = fm.get("name")
            if fm_name is not None and str(fm_name) != name:
                rep.errors.append(f"{rel}: frontmatter `name: {fm_name}` does not match its directory `{name}` "
                                  f"(the name is the directory; a mismatch is dropped at load)")
            if not NAME_RX.fullmatch(name):
                rep.warnings.append(f"{rel}: skill directory `{name}` is not lower-case letters, digits, `-` or "
                                    f"`_` (agentskills.io names)")
            row["paths"] = bool(fm.get("paths"))
        if len(tree[rel]) > surface.skill_max_chars:
            rep.warnings.append(f"{rel}: {len(tree[rel]):,} characters — over the {surface.skill_max_chars:,} "
                                f"the runtime loads per skill (about 25,000 tokens); the tail is cut")
        prefix = f"{surface.skills_dir}/{name}/"
        row["resources"] = sum(1 for r in tree if r.startswith(prefix) and r != rel)
        skills.append(row)
    silent = [s["name"] for s in skills if not s["triggered"]]
    if silent:
        rep.notes.append(f"{len(silent)} skill(s) never named in the always-on text ({', '.join(silent)}): the "
                         f"runtime still advertises each one's name and description (deferred loading), so a "
                         f"trigger line is optional — add one where a skill should fire on a situation its "
                         f"description does not name")
    return skills


def _check_agents(surface: SurfaceSpec, tree: Tree, rep: Report) -> list[dict]:
    agents: list[dict] = []
    for rel in sorted(tree):
        name = agent_name(surface, rel)
        if name is None:
            continue
        fm, _body, problem = frontmatter(tree[rel])
        row = {"name": name, "path": rel, "chars": len(tree[rel]), "tools": None, "model": None}
        if problem or fm is None:
            rep.errors.append(f"{rel}: {problem or 'frontmatter is not a mapping'} — the subagent cannot be dispatched")
        else:
            if not _nonempty_str(fm.get("description")):
                rep.errors.append(f"{rel}: a subagent needs a `description:` (it is how the main agent decides "
                                  f"to delegate to it)")
            fm_name = fm.get("name")
            if fm_name is not None and str(fm_name) != name:
                rep.errors.append(f"{rel}: frontmatter `name: {fm_name}` does not match the file name `{name}`")
            row["tools"] = fm.get("tools")
            row["model"] = fm.get("model")
        agents.append(row)
    return agents


def _check_commands(surface: SurfaceSpec, tree: Tree, rep: Report) -> list[dict]:
    commands: list[dict] = []
    for rel in sorted(tree):
        name = command_name(surface, rel)
        if name is None:
            continue
        fm, _body, problem = frontmatter(tree[rel])
        row = {"name": name, "path": rel, "chars": len(tree[rel]), "allowed_tools": None}
        if problem or fm is None:
            rep.errors.append(f"{rel}: {problem or 'frontmatter is not a mapping'}")
        else:
            if not _nonempty_str(fm.get("description")):
                rep.warnings.append(f"{rel}: `/{name}` has no `description:` — it shows up with no help text")
            row["allowed_tools"] = fm.get("allowed-tools")
        commands.append(row)
    return commands


def check_hooks(doc: object, where: str, rep: Report, *, root: Path | None, tree: Tree) -> dict:
    """The hooks block's shape: a malformed one never fires, so the shape is
    checked where the harness is edited. Returns the census of what fires."""
    out: dict = {"events": [], "commands": 0}
    hooks = doc.get("hooks") if isinstance(doc, dict) else None
    if hooks is None:
        return out
    if not isinstance(hooks, dict):
        rep.errors.append(f'{where}: `hooks` must be an object {{"<Event>": [...]}}')
        return out
    for event, entries in hooks.items():
        if event not in HOOK_EVENTS:
            rep.errors.append(f"{where}: unknown hook event {event!r}; the runtime dispatches "
                              f"{', '.join(sorted(HOOK_EVENTS))}")
            continue
        out["events"].append(event)
        if not isinstance(entries, list):
            rep.errors.append(f"{where}: hooks.{event} must be a LIST of matcher entries")
            continue
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
                rep.errors.append(f"{where}: hooks.{event}[{i}] needs a `hooks` list")
                continue
            for h in entry["hooks"]:
                if not isinstance(h, dict) or h.get("type") not in HOOK_TYPES:
                    rep.errors.append(f"{where}: hooks.{event}[{i}] hook `type` must be one of "
                                      f"{', '.join(sorted(HOOK_TYPES))}")
                    continue
                if h["type"] == "command":
                    cmd = str(h.get("command") or "")
                    if not cmd.strip():
                        rep.errors.append(f"{where}: hooks.{event}[{i}] has an empty `command`")
                        continue
                    out["commands"] += 1
                    for ref in HOOK_PATH_RX.findall(cmd):
                        if ref not in tree and (root is None or not (root / ref).is_file()):
                            rep.errors.append(f"{where}: hooks.{event}[{i}] runs `$CLAUDE_PROJECT_DIR/{ref}`, which "
                                              f"does not exist — the hook fails on every event")
    return out


def _check_settings(surface: SurfaceSpec, tree: Tree, rep: Report, root: Path | None) -> dict:
    rel = surface.settings_file
    out = {"present": rel in tree, "allow": 0, "deny": 0, "hooks": {"events": [], "commands": 0}}
    if rel not in tree:
        return out
    try:
        doc = json.loads(tree[rel])
    except ValueError as exc:
        rep.errors.append(f"{rel}: not valid JSON ({exc}) — no permission rule or hook in it applies")
        return out
    if not isinstance(doc, dict):
        rep.errors.append(f"{rel}: must be a JSON object")
        return out
    perms = doc.get("permissions")
    if perms is not None:
        if not isinstance(perms, dict):
            rep.errors.append(f"{rel}: `permissions` must be an object")
        else:
            for key in ("allow", "deny", "ask"):
                rules = perms.get(key)
                if rules is None:
                    continue
                if not isinstance(rules, list) or not all(isinstance(r, str) and r for r in rules):
                    rep.errors.append(f"{rel}: permissions.{key} must be a list of rule strings")
                elif key in out:
                    out[key] = len(rules)
    out["hooks"] = check_hooks(doc, rel, rep, root=root, tree=tree)
    return out


def _check_mcp(surface: SurfaceSpec, tree: Tree, rep: Report) -> list[str]:
    rel = surface.mcp_file
    if rel not in tree:
        return []
    try:
        doc = json.loads(tree[rel])
    except ValueError as exc:
        rep.errors.append(f"{rel}: not valid JSON ({exc}) — no server in it starts")
        return []
    servers = doc.get("mcpServers") if isinstance(doc, dict) else None
    if not isinstance(servers, dict):
        rep.errors.append(f"{rel}: needs a top-level `mcpServers` object")
        return []
    names: list[str] = []
    for name, cfg in servers.items():
        if not isinstance(cfg, dict) or not (cfg.get("command") or cfg.get("url")):
            rep.errors.append(f"{rel}: server {name!r} needs a `command` (stdio) or a `url`")
            continue
        names.append(str(name))
    return names


def _check_script_refs(tree: Tree, rep: Report, root: Path | None, *, rels: Iterable[str]) -> int:
    """Every script a component names must exist (Harness²'s rule 3): a skill,
    command, agent or always-on file that invokes `tools/x.py` ships it or
    points at a file that is there."""
    checked = 0
    for rel in rels:
        for ref in SCRIPT_REF_RX.findall(tree.get(rel, "")):
            if any(c in ref for c in PLACEHOLDER_CHARS):
                continue
            checked += 1
            if ref in tree or (root is not None and (root / ref).is_file()):
                continue
            rep.errors.append(f"{rel}: names `{ref}`, which does not exist in this repository")
    return checked


def _scan_injection(tree: Tree, rep: Report, *, rels: Iterable[str]) -> None:
    for rel in rels:
        text = tree.get(rel, "")
        m = INJECTION_RX.search(text)
        if m:
            line = text.count("\n", 0, m.start()) + 1
            rep.warnings.append(f"{rel}:{line}: prompt-injection phrasing ({m.group(0)!r}) in a file the agent reads "
                                f"as instructions — confirm it is documentation, not an instruction")


def validate(surface: SurfaceSpec, tree: Tree, *, root: Path | str | None = None) -> Report:
    """Every problem with the surface, as a Report; never raises on content."""
    root = Path(root) if root is not None else None
    rep = Report()
    body = always_on_text(surface, tree)
    present = [a for a in surface.always_on if a in tree]
    if not present:
        rep.warnings.append(f"no context file ({' or '.join(surface.always_on)}): the agent starts with no "
                            f"standing instruction (every production harness auto-discovers one)")
    elif not body.strip():
        rep.errors.append(f"{' and '.join(present)} are empty: an empty always-on file is a harness that does not exist")
    cap = surface.always_on_max
    if len(body) > cap:
        rep.errors.append(f"always-on text is {len(body):,} characters, over the {cap:,} cap — it is in context on "
                          f"every turn; move procedure into a skill, a script or a hook (cut to pay for an add)")
    elif len(body) > cap * ALWAYS_ON_WARN_PCT // 100:
        rep.warnings.append(f"always-on text is {len(body):,} characters, over {ALWAYS_ON_WARN_PCT}% of the "
                            f"{cap:,} cap")
    skills = _check_skills(surface, tree, body, rep)
    agents = _check_agents(surface, tree, rep)
    commands = _check_commands(surface, tree, rep)
    settings = _check_settings(surface, tree, rep, root)
    servers = _check_mcp(surface, tree, rep)
    named = [*surface.always_on, *(s["path"] for s in skills), *(c["path"] for c in commands),
             *(a["path"] for a in agents)]
    refs = _check_script_refs(tree, rep, root, rels=[r for r in named if r in tree])
    _scan_injection(tree, rep, rels=[r for r in named if r in tree])
    rep.census = census(surface, tree, skills=skills, agents=agents, commands=commands, settings=settings,
                        servers=servers, script_refs=refs)
    return rep


# --------------------------------------------------------------------------- #
# census and diff
# --------------------------------------------------------------------------- #
def census(surface: SurfaceSpec, tree: Tree, *, skills: list[dict] | None = None, agents: list[dict] | None = None,
           commands: list[dict] | None = None, settings: dict | None = None, servers: list[str] | None = None,
           script_refs: int = 0) -> dict:
    """The inventory: per component the file count and characters, the
    always-on size against its cap, and the named parts."""
    per: dict[str, dict] = {c: {"files": 0, "chars": 0} for c in COMPONENTS}
    for rel, text in tree.items():
        comp = component_of(surface, rel)
        if comp is None:
            continue
        per[comp]["files"] += 1
        per[comp]["chars"] += len(text)
    body = always_on_text(surface, tree)
    rep = Report()
    if skills is None:
        skills = _check_skills(surface, tree, body, rep)
    if agents is None:
        agents = _check_agents(surface, tree, rep)
    if commands is None:
        commands = _check_commands(surface, tree, rep)
    if settings is None:
        settings = _check_settings(surface, tree, rep, None)
    if servers is None:
        servers = _check_mcp(surface, tree, rep)
    hooks = settings.get("hooks") or {"events": [], "commands": 0}
    # hooks act inside the tool loop: counted with the plugins, beside the MCP servers
    per["plugins"]["hooks"] = hooks["commands"]
    per["plugins"]["mcp_servers"] = len(servers)
    return {
        "surface": surface.name,
        "always_on": {"files": [a for a in surface.always_on if a in tree], "chars": len(body),
                      "max_chars": surface.always_on_max,
                      "pct_of_cap": round(100.0 * len(body) / surface.always_on_max, 1) if surface.always_on_max else None},
        "components": per,
        "skills": skills,
        "subagents": agents,
        "commands": commands,
        "policy_as_data": {"settings": settings.get("present", False), "allow_rules": settings.get("allow", 0),
                           "deny_rules": settings.get("deny", 0), "hook_events": hooks["events"],
                           "hook_commands": hooks["commands"], "mcp_servers": servers},
        "script_refs_checked": script_refs,
        "files": len(tree),
    }


def diff_summary(before: Tree, after: Tree, *, surface: SurfaceSpec | None = None) -> dict:
    """What changed between two surfaces: added, removed and modified paths
    and the always-on character delta (the cost that is paid every turn)."""
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    modified = sorted(rel for rel in set(before) & set(after) if before[rel] != after[rel])
    out = {"added": added, "removed": removed, "modified": modified}
    if surface is not None:
        out["always_on_char_delta"] = len(always_on_text(surface, after)) - len(always_on_text(surface, before))
    return out


def diversity(trees: Mapping[str, Tree]) -> dict:
    """Pairwise line-Jaccard over candidate trees, so a collapse of k
    candidates into one body is visible before anything is rolled out."""
    names = sorted(trees)
    if len(names) < 2:
        return {"n": len(names), "n_distinct": len(names), "mean_line_jaccard": 1.0}

    def lines(t: Tree) -> set[str]:
        return {f"{rel}:{ln}" for rel, c in t.items() for ln in c.splitlines() if ln.strip()}

    sets = {n: lines(trees[n]) for n in names}
    sims = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            u = sets[a] | sets[b]
            sims.append(len(sets[a] & sets[b]) / len(u) if u else 1.0)
    distinct = len({tuple(sorted(t.items())) for t in trees.values()})
    return {"n": len(names), "n_distinct": distinct, "mean_line_jaccard": round(sum(sims) / len(sims), 4)}


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
def render_census(c: dict) -> str:
    ao = c["always_on"]
    lines = [f"harness surface: {c['surface']}  ({c['files']} files on the surface)",
             f"always-on: {ao['chars']:,} chars of {ao['max_chars']:,} ({ao['pct_of_cap']}%): "
             + (", ".join(ao["files"]) or "none"),
             "", "| component | files | chars |", "| --- | ---: | ---: |"]
    for comp in COMPONENTS:
        row = c["components"][comp]
        extra = ""
        if comp == "plugins":
            extra = f"  (hooks {row.get('hooks', 0)}, MCP servers {row.get('mcp_servers', 0)})"
        lines.append(f"| {COMPONENT_LABELS[comp]} | {row['files']} | {row['chars']:,} |{extra}")
    if c["skills"]:
        lines += ["", "skills:"]
        for s in c["skills"]:
            bits = [f"{s['chars']:,} chars", f"description {s['description_chars']} chars"]
            if s["paths"]:
                bits.append("path-gated")
            if s["resources"]:
                bits.append(f"{s['resources']} resource file(s)")
            bits.append("named in always-on text" if s["triggered"] else "not named in always-on text")
            lines.append(f"  - {s['name']}: " + ", ".join(bits))
    if c["subagents"]:
        lines += ["", "subagents: " + ", ".join(a["name"] for a in c["subagents"])]
    if c["commands"]:
        lines += ["commands: " + ", ".join("/" + x["name"] for x in c["commands"])]
    p = c["policy_as_data"]
    lines += ["", f"policy as data: settings {'present' if p['settings'] else 'absent'}, allow rules {p['allow_rules']}, "
                  f"deny rules {p['deny_rules']}, hook events {', '.join(p['hook_events']) or 'none'} "
                  f"({p['hook_commands']} command(s)), MCP servers {', '.join(p['mcp_servers']) or 'none'}",
              f"script references checked: {c['script_refs_checked']}"]
    return "\n".join(lines)


def render_report(rep: Report) -> str:
    lines = []
    for e in rep.errors:
        lines.append(f"ERROR {e}")
    for w in rep.warnings:
        lines.append(f"warn  {w}")
    for n in rep.notes:
        lines.append(f"note  {n}")
    lines.append(f"{'ok' if rep.ok else 'FAIL'}: {len(rep.errors)} error(s), {len(rep.warnings)} warning(s), "
                 f"{len(rep.notes)} note(s)")
    return "\n".join(lines)


def check(root: Path | str = HUB, *, fleet: Mapping | None = None) -> Report:
    surface = surface_from_fleet(fleet)
    tree = read_tree(surface, root)
    return validate(surface, tree, root=root)
