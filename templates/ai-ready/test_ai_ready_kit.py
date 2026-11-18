#!/usr/bin/env python3
"""Tests for the AI-ready foundation kit (templates/ai-ready/).

The kit README's `## Files` table is the kit's contract: every row is either
`present` (the file is in the tree) or `planned` with a link to the issue that
builds it. These checks keep that table true to the tree, keep VERSION's
`files:` list in step with it, and hold the A2A Agent Card template to the
shape of the A2A v1.0 AgentCard (the REQUIRED fields of `a2a.proto` and the
field names the generated JSON Schema allows).

    python3 templates/ai-ready/test_ai_ready_kit.py

Stdlib + PyYAML only (CI has no jsonschema); exits non-zero when a check fails.
The full JSON Schema validation against the published A2A schema is a one-off
command recorded in the PR that added the card.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

KIT = Path(__file__).resolve().parent
CARD = "agent-card.template.json"
FAILS: list[str] = []

ISSUE_LINK_RE = re.compile(r"\[#(\d+)\]\(https://github\.com/bamr87/bamr87/(?:issues|pull)/(\d+)\)")
TOKEN_RE = re.compile(r"__[A-Z][A-Z0-9_]*__")

# A2A v1.0 (a2a.proto, `lf.a2a.v1`): the REQUIRED fields of each message and
# every field the JSON Schema accepts (its objects are additionalProperties:
# false). camelCase is the canonical JSON name; the schema also accepts the
# snake_case spelling, which the template does not use.
CARD_REQUIRED = {"name", "description", "supportedInterfaces", "version", "capabilities",
                 "defaultInputModes", "defaultOutputModes", "skills"}
CARD_ALLOWED = CARD_REQUIRED | {"provider", "documentationUrl", "securitySchemes",
                                "securityRequirements", "signatures", "iconUrl"}
INTERFACE_REQUIRED = {"url", "protocolBinding", "protocolVersion"}
INTERFACE_ALLOWED = INTERFACE_REQUIRED | {"tenant"}
BINDINGS = {"JSONRPC", "GRPC", "HTTP+JSON"}
SKILL_REQUIRED = {"id", "name", "description", "tags"}
SKILL_ALLOWED = SKILL_REQUIRED | {"examples", "inputModes", "outputModes", "securityRequirements"}
CAPABILITIES_ALLOWED = {"streaming", "pushNotifications", "extensions", "extendedAgentCard"}
PROVIDER_REQUIRED = {"organization", "url"}
SCHEME_KINDS = {"apiKeySecurityScheme", "httpAuthSecurityScheme", "oauth2SecurityScheme",
                "openIdConnectSecurityScheme", "mtlsSecurityScheme"}
HTTP_AUTH_ALLOWED = {"scheme", "description", "bearerFormat"}


def check(cond: bool, msg: str) -> None:
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        FAILS.append(msg)


def files_table(readme: str) -> list[dict]:
    """The rows of the README's `## Files` table, keyed by its header cells."""
    m = re.search(r"^## Files\s*$(.*?)(?=^## |\Z)", readme, re.M | re.S)
    if not m:
        return []
    lines = [ln.strip() for ln in m.group(1).splitlines() if ln.strip().startswith("|")]
    if len(lines) < 2:
        return []
    split = lambda ln: [c.strip() for c in ln.strip("|").split("|")]  # noqa: E731
    header = [h.lower() for h in split(lines[0])]
    return [dict(zip(header, split(ln))) for ln in lines[2:]]


def row_path(row: dict) -> str:
    m = re.match(r"`([^`]+)`", row.get("file", ""))
    return m.group(1) if m else ""


def table_problems(kit: Path) -> list[str]:
    """Every way the Files table disagrees with the kit directory `kit`."""
    readme = (kit / "README.md").read_text(encoding="utf-8")
    rows = files_table(readme)
    if not rows:
        return ["README.md has no `## Files` table"]
    problems = []
    if "status" not in rows[0]:
        problems.append("the Files table has no Status column")
    listed = set()
    for row in rows:
        path = row_path(row)
        if not path:
            problems.append(f"row without a `file` cell: {row}")
            continue
        listed.add(path.rstrip("/"))
        status = row.get("status", "")
        target = kit / path.rstrip("/")
        exists = target.is_dir() if path.endswith("/") else target.is_file()
        if status == "present":
            if not exists:
                problems.append(f"{path}: marked present but missing from the tree")
        elif status.startswith("planned"):
            links = ISSUE_LINK_RE.findall(status)
            if not links:
                problems.append(f"{path}: planned without an issue link")
            for text_n, url_n in links:
                if text_n != url_n:
                    problems.append(f"{path}: link text #{text_n} points at {url_n}")
            if exists:
                problems.append(f"{path}: marked planned but present in the tree (mark it present)")
        else:
            problems.append(f"{path}: status {status!r} is neither `present` nor `planned …`")
    on_disk = {p.name for p in kit.iterdir() if p.name not in {"README.md", "__pycache__"}}
    for name in sorted(on_disk - listed):
        problems.append(f"{name}: in the tree but not in the Files table")
    return problems


def present_rows() -> set[str]:
    rows = files_table((KIT / "README.md").read_text(encoding="utf-8"))
    return {row_path(r).rstrip("/") for r in rows if r.get("status") == "present"}


def load_card() -> dict:
    return json.loads((KIT / CARD).read_text(encoding="utf-8"))


def documented_tokens() -> set[str]:
    readme = (KIT / "README.md").read_text(encoding="utf-8")
    m = re.search(r"^## Agent Card template\s*$(.*?)(?=^## |\Z)", readme, re.M | re.S)
    return set(TOKEN_RE.findall(m.group(1))) if m else set()


def t_files_table_matches_tree() -> None:
    print("README Files table: every row is present or planned with an issue link")
    problems = table_problems(KIT)
    check(not problems, "table == tree" + ("" if not problems else f" ({'; '.join(problems)})"))


def t_detects_a_missing_file() -> None:
    print("the table check fails when a present row's file is removed")
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "ai-ready"
        shutil.copytree(KIT, copy, ignore=shutil.ignore_patterns("__pycache__"))
        check(not table_problems(copy), "a faithful copy is clean")
        (copy / CARD).unlink(missing_ok=True)
        problems = table_problems(copy)
        check(any(CARD in p and "missing" in p for p in problems), f"removing {CARD} is reported")
        readme = copy / "README.md"
        text = readme.read_text(encoding="utf-8")
        readme.write_text(ISSUE_LINK_RE.sub("an issue", text), encoding="utf-8")
        check(any("planned without an issue link" in p for p in table_problems(copy)),
              "a planned row that loses its issue link is reported")


def t_version() -> None:
    print("VERSION: semver, `files:` lists every present payload row")
    meta = yaml.safe_load((KIT / "VERSION").read_text(encoding="utf-8"))
    check(meta.get("kit") == "ai-ready", "kit: ai-ready")
    check(re.fullmatch(r"\d+\.\d+\.\d+", str(meta.get("version"))) is not None, "version is semver")
    listed = {f.strip() for f in str(meta.get("files", "")).split(",") if f.strip()}
    want = present_rows() - {"VERSION", Path(__file__).name}
    check(listed == want, f"files == present rows but VERSION and the tests (missing: {sorted(want - listed)}, "
                          f"stale: {sorted(listed - want)})")
    check(f"{meta.get('version')} —" in str(meta.get("changelog", "")), "the changelog has an entry for this version")


def t_json_templates_parse() -> None:
    print("every *.json in the kit parses, without duplicate keys")

    def no_dupes(pairs):
        keys = [k for k, _ in pairs]
        if len(keys) != len(set(keys)):
            raise ValueError(f"duplicate keys: {sorted(k for k in keys if keys.count(k) > 1)}")
        return dict(pairs)

    found = sorted(KIT.rglob("*.json"))
    check(bool(found), "at least one JSON template")
    for path in found:
        try:
            json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=no_dupes)
            ok, why = True, ""
        except ValueError as exc:
            ok, why = False, f": {exc}"
        check(ok, f"{path.relative_to(KIT)} parses{why}")


def t_agent_card_shape() -> None:
    print("agent card: the A2A v1.0 AgentCard shape")
    card = load_card()
    check(CARD_REQUIRED <= card.keys(), f"required keys (missing: {sorted(CARD_REQUIRED - card.keys())})")
    check(card.keys() <= CARD_ALLOWED, f"only AgentCard fields (unknown: {sorted(card.keys() - CARD_ALLOWED)})")
    for key in ("name", "description", "version"):
        check(isinstance(card.get(key), str) and card.get(key), f"{key} is a non-empty string")
    for key in ("defaultInputModes", "defaultOutputModes"):
        modes = card.get(key)
        check(isinstance(modes, list) and modes and all(isinstance(m, str) and "/" in m for m in modes),
              f"{key} is a non-empty list of media types")

    interfaces = card.get("supportedInterfaces")
    check(isinstance(interfaces, list) and len(interfaces) >= 1, "supportedInterfaces has an entry")
    for i, iface in enumerate(interfaces or []):
        check(INTERFACE_REQUIRED <= iface.keys() <= INTERFACE_ALLOWED,
              f"supportedInterfaces[{i}]: url, protocolBinding, protocolVersion only")
        check(iface.get("protocolBinding") in BINDINGS, f"supportedInterfaces[{i}]: binding is one of {sorted(BINDINGS)}")
        check(re.fullmatch(r"\d+\.\d+", str(iface.get("protocolVersion"))) is not None,
              f"supportedInterfaces[{i}]: protocolVersion is major.minor")

    caps = card.get("capabilities")
    check(isinstance(caps, dict) and caps.keys() <= CAPABILITIES_ALLOWED,
          f"capabilities uses AgentCapabilities fields only ({sorted(caps or {})})")
    for key in ("streaming", "pushNotifications", "extendedAgentCard"):
        if key in (caps or {}):
            check(isinstance(caps[key], bool), f"capabilities.{key} is a boolean")

    provider = card.get("provider")
    if provider is not None:
        check(provider.keys() == PROVIDER_REQUIRED, "provider has exactly organization and url")

    skills = card.get("skills")
    check(isinstance(skills, list) and len(skills) >= 1, "skills has an entry")
    ids = []
    for i, skill in enumerate(skills or []):
        check(SKILL_REQUIRED <= skill.keys() <= SKILL_ALLOWED,
              f"skills[{i}]: id, name, description, tags (+ optional AgentSkill fields)")
        tags = skill.get("tags")
        check(isinstance(tags, list) and tags and all(isinstance(t, str) for t in tags),
              f"skills[{i}]: tags is a non-empty list of strings")
        ids.append(skill.get("id"))
    check(len(ids) == len(set(ids)), "skill ids are unique")


def t_agent_card_security() -> None:
    print("agent card: a bearer scheme example, declared before it is required, holding no values")
    card = load_card()
    schemes = card.get("securitySchemes") or {}
    check("bearer" in schemes, "a `bearer` security scheme is declared")
    for name, scheme in schemes.items():
        kinds = set(scheme) & SCHEME_KINDS
        check(len(kinds) == 1 and set(scheme) == kinds, f"securitySchemes.{name}: exactly one scheme kind")
    http = (schemes.get("bearer") or {}).get("httpAuthSecurityScheme") or {}
    check(str(http.get("scheme", "")).lower() == "bearer", "bearer: HTTP auth with scheme Bearer")
    check(http.keys() <= HTTP_AUTH_ALLOWED, "bearer: HTTPAuthSecurityScheme fields only")
    for i, req in enumerate(card.get("securityRequirements") or []):
        check(set(req) == {"schemes"}, f"securityRequirements[{i}]: a `schemes` map")
        for ref, scopes in (req.get("schemes") or {}).items():
            check(ref in schemes, f"securityRequirements[{i}]: {ref!r} is a declared scheme")
            check(set(scopes) == {"list"} and isinstance(scopes["list"], list),
                  f"securityRequirements[{i}].{ref}: a StringList of scopes")
    text = (KIT / CARD).read_text(encoding="utf-8")
    secretish = re.findall(r"(?i)\b(?:eyJ[\w-]{10,}|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9-]{20,})", text)
    check(not secretish, "no token-shaped values in the template")


def t_agent_card_tokens() -> None:
    print("agent card: placeholders are the documented tokens, and a filled card is well formed")
    used = set(TOKEN_RE.findall((KIT / CARD).read_text(encoding="utf-8")))
    documented = documented_tokens()
    check(bool(documented), "README documents the card's tokens under `## Agent Card template`")
    check(used == documented, f"tokens used == tokens documented (undocumented: {sorted(used - documented)}, "
                              f"unused: {sorted(documented - used)})")
    sample = {"__PROJECT_NAME__": "example-agent", "__OWNER__": "bamr87",
              "__AGENT_URL__": "https://agent.example.com/a2a/v1", "__AGENT_VERSION__": "1.0.0",
              "__AGENT_DESCRIPTION__": "An example agent.", "__SKILL_ID__": "example-skill",
              "__SKILL_NAME__": "Example skill", "__SKILL_DESCRIPTION__": "Does one example thing.",
              "__SKILL_EXAMPLE__": "Do the example thing."}
    text = (KIT / CARD).read_text(encoding="utf-8")
    for token, value in sample.items():
        text = text.replace(token, value)
    check(not TOKEN_RE.search(text), "the sample fills every token")
    filled = json.loads(text)
    for i, iface in enumerate(filled["supportedInterfaces"]):
        check(str(iface["url"]).startswith("https://"), f"filled supportedInterfaces[{i}].url is absolute https")
    check(filled["provider"]["url"].startswith("https://"), "filled provider.url is absolute https")
    check(filled["documentationUrl"].startswith("https://"), "filled documentationUrl is absolute https")


def card_loads() -> bool:
    """The card's own checks need a card that exists and parses; say so once when it does not."""
    try:
        return isinstance(load_card(), dict)
    except (OSError, ValueError) as exc:
        print("agent card")
        check(False, f"{CARD} exists and parses, so its shape checks can run ({exc.__class__.__name__})")
        return False


def main() -> int:
    for t in (t_files_table_matches_tree, t_detects_a_missing_file, t_version, t_json_templates_parse):
        t()
    if card_loads():
        for t in (t_agent_card_shape, t_agent_card_security, t_agent_card_tokens):
            t()
    if FAILS:
        print(f"\nFAILED ({len(FAILS)})")
        return 1
    print("\nOK — ai-ready kit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
