#!/usr/bin/env python3
"""
File: tools/evals.py
Description: The eval runner (constitution § 13.1–13.2). Each agent role keeps
             a versioned eval set at evals/<role>/cases.yml: real past tasks,
             each with an input, the expected output, a pass criterion and an
             optional LLM-judge rubric. This runner loads a set, hands every
             case to the role's ADAPTER and reports pass / fail per case. Any
             failed case makes the exit status non-zero. The eval-regression
             check is tools/test_evals.py, which the `python-tests` workflow
             runs on every pull request, push to main and night: it validates
             every set offline and proves a wrong expectation fails the run.

             Two kinds of role:
               deterministic  the adapter calls the code under test directly —
                              no network, no `claude` CLI (jev-classify).
               model          the adapter asks a pinned model; `--dry-run`
                              validates the set without calling one. A model
                              run uses only ids from _data/fleet.yml
                              `ai_models.allowed` and is capped by
                              `budget.local_usd`.
                                t1-intake       one `claude -p` per case.
                                pr-ai-analysis  one `claude -p` per case: the CI
                                                failure analyst's shipped prompt
                                                (pr_ai_analysis.compose, SYSTEM).
                                console-assist  the console's assistant (the
                                                `assist` op, its shipped prompt
                                                and tool allowlist, the real MCP
                                                layer) against a recorded page
                                                (tools/console/assist_eval_console.py).
                                                It spends more, so a model run of
                                                it must name its cases: --canary,
                                                --all-cases or --case.
Author: bamr87
Created: 2026-11-04
Version: 0.2.0
Usage: python3 tools/evals.py list
       python3 tools/evals.py run <role> [--json] [--dry-run] [--model ID]
       python3 tools/evals.py run --all [--json] [--dry-run]
       python3 tools/evals.py run <role> --cases <path>   # an alternate cases file
       python3 tools/evals.py run console-assist --canary [--out DIR]   # SPENDS
       python3 tools/evals.py run console-assist --all-cases            # SPENDS
       python3 tools/evals.py run console-assist --case <id> [--case …] # SPENDS
Exit:  0 every case passed (or validated, under --dry-run); 1 a case failed or
       the set is malformed; 2 usage error.
Dependencies: PyYAML; for a model run the `claude` CLI, and for console-assist
       the MCP layer's virtualenv (HARNESS_MCP_VENV, default <repo>/.venv-mcp).
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
EVALS_DIR = ROOT / "evals"
FLEET_YML = ROOT / "_data" / "fleet.yml"
SCHEMA = "evals/v1"
#: constitution § 10.7: every AI dollar figure this runner prints carries it
COST_LABEL = "API-equivalent (estimate)"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# --------------------------------------------------------------------------- #
# results
# --------------------------------------------------------------------------- #
@dataclass
class CaseResult:
    id: str
    passed: bool
    expected: dict
    actual: dict = field(default_factory=dict)
    detail: str = ""


@dataclass
class RoleResult:
    role: str
    mode: str
    dry_run: bool = False
    model: str | None = None
    cost_usd: float = 0.0
    errors: list[str] = field(default_factory=list)
    #: things a reader should know that are neither an error nor a case (where a run's files are, …)
    notes: list[str] = field(default_factory=list)
    cases: list[CaseResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.cases if c.passed)

    @property
    def failed(self) -> int:
        return sum(1 for c in self.cases if not c.passed)

    @property
    def ok(self) -> bool:
        return not self.errors and self.failed == 0

    def to_json(self) -> dict:
        return {
            "role": self.role, "mode": self.mode, "dry_run": self.dry_run,
            "model": self.model, "cost_usd": round(self.cost_usd, 4), "cost_label": COST_LABEL,
            "passed": self.passed, "failed": self.failed, "errors": self.errors, "notes": self.notes,
            "cases": [asdict(c) for c in self.cases],
        }


# --------------------------------------------------------------------------- #
# fleet.yml: pinned models and the budget cap — read, never hard-coded
# --------------------------------------------------------------------------- #
def fleet_config(path: Path = FLEET_YML) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def allowed_models(cfg: dict) -> list[str]:
    allowed = (cfg.get("ai_models") or {}).get("allowed") or {}
    return [m for ids in allowed.values() for m in (ids or [])]


def budget_cap(cfg: dict) -> float:
    budget = cfg.get("budget") or {}
    return float(budget.get("local_usd", budget.get("default_usd", 0)) or 0)


# --------------------------------------------------------------------------- #
# loading and validating a set
# --------------------------------------------------------------------------- #
def load_set(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: not a mapping")
    return data


def validate_common(data: dict, role: str) -> list[str]:
    errs = []
    if data.get("schema") != SCHEMA:
        errs.append(f"schema must be {SCHEMA!r}, got {data.get('schema')!r}")
    if data.get("role") != role:
        errs.append(f"role must be {role!r}, got {data.get('role')!r}")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        errs.append("cases must be a non-empty list")
        return errs
    seen = set()
    for i, case in enumerate(cases):
        where = f"cases[{i}]"
        if not isinstance(case, dict):
            errs.append(f"{where}: not a mapping")
            continue
        cid = case.get("id")
        if not cid or not isinstance(cid, str):
            errs.append(f"{where}: missing id")
        elif cid in seen:
            errs.append(f"{where}: duplicate id {cid!r}")
        seen.add(cid)
        for key in ("source", "input", "expected", "pass"):
            if key not in case:
                errs.append(f"{where} ({cid}): missing {key!r}")
        if "input" in case and not isinstance(case["input"], dict):
            errs.append(f"{where} ({cid}): input must be a mapping")
        if "expected" in case and not isinstance(case["expected"], dict):
            errs.append(f"{where} ({cid}): expected must be a mapping")
    min_cases = data.get("min_cases")
    if isinstance(min_cases, int) and len(cases) < min_cases:
        errs.append(f"{len(cases)} case(s), fewer than min_cases {min_cases}")
    return errs


# --------------------------------------------------------------------------- #
# adapter: jev-classify — deterministic, imports the classifier directly
# --------------------------------------------------------------------------- #
def _jev_files(inp: dict):
    from tools.jev import classify as cls
    globs = inp.get("globs") or {}
    out = []
    for f in inp.get("files") or []:
        kind = f.get("kind") or cls.kind_of(
            f["path"], generated=globs.get("generated", ()), fragments=globs.get("fragments", ()),
            union=globs.get("union", ()), append=globs.get("append", ()),
            binary=bool(f.get("binary", False)))
        out.append(cls.ConflictFile(path=f["path"], hunks=int(f.get("hunks", 0)),
                                    lines=int(f.get("lines", 0)), kind=kind))
    return out


def run_jev_classify(data: dict, res: RoleResult, **_) -> None:
    from tools.jev import classify as cls
    tiers = {cls.TIER0, cls.TIER1, cls.TIER2, cls.TIER3}
    option_keys = ("attempts", "id_collision", "squash_only", "budget_exhausted",
                   "force_min_tier", "max_attempts", "tier1_max_files", "tier1_max_lines",
                   "tier2_max_files", "tier2_max_lines")
    for case in data["cases"]:
        exp = case["expected"]
        if exp.get("tier") not in tiers:
            res.cases.append(CaseResult(case["id"], False, exp,
                                        detail=f"expected.tier must be one of {sorted(tiers)}"))
            continue
        inp = case["input"]
        files = _jev_files(inp)
        opts = {k: inp[k] for k in option_keys if k in inp}
        triage = cls.classify(files, **opts)
        actual = {"tier": triage.tier, "kinds": {f.path: f.kind for f in files},
                  "reason": triage.reason}
        problems = []
        if triage.tier != exp["tier"]:
            problems.append(f"tier {triage.tier} != expected {exp['tier']}")
        for path, kind in (exp.get("kinds") or {}).items():
            if actual["kinds"].get(path) != kind:
                problems.append(f"kind of {path} is {actual['kinds'].get(path)}, expected {kind}")
        needle = exp.get("reason_contains")
        if needle and needle not in triage.reason:
            problems.append(f"reason {triage.reason!r} lacks {needle!r}")
        res.cases.append(CaseResult(case["id"], not problems, exp, actual, "; ".join(problems)))


# --------------------------------------------------------------------------- #
# adapter: t1-intake — model-backed; --dry-run validates the set offline
# --------------------------------------------------------------------------- #
INTAKE_EXITS = ("ready", "blocked")


def validate_t1_intake(data: dict, cfg: dict) -> list[str]:
    labels = ((cfg.get("issue_pipeline") or {}).get("labels") or {})
    types = set(labels.get("types") or [])
    errs = []
    for case in data["cases"]:
        cid, inp, exp = case.get("id"), case.get("input") or {}, case.get("expected") or {}
        for key in ("repo", "title", "summary", "gaps"):
            if key not in inp:
                errs.append(f"{cid}: input.{key} missing")
        for gap in inp.get("gaps") or []:
            if not isinstance(gap, dict) or gap.get("by") not in ("agent", "human") or not gap.get("gap"):
                errs.append(f"{cid}: each gap needs `gap` and `by: agent|human`")
        if exp.get("exit") not in INTAKE_EXITS:
            errs.append(f"{cid}: expected.exit must be one of {INTAKE_EXITS}")
        if types and exp.get("type") not in types:
            errs.append(f"{cid}: expected.type {exp.get('type')!r} is not in issue_pipeline.labels.types")
    return errs


INTAKE_PROMPT = """You are tier 1 (intake) of an issue pipeline. You do not write code.
Decide the exit for the issue below and its type label.
- "ready" when every gap an agent can close is closed and no human gap remains.
- "blocked" when a human gap remains: a product decision, a settings or
  credential change only the owner may make, a deploy to their machine, or a
  choice between two defensible designs.
Type is one of: {types}.

Repo: {repo}
Title: {title}
Summary: {summary}
Gaps:
{gaps}

Reply with ONE line of JSON and nothing else: {{"exit": "ready|blocked", "type": "<type>"}}"""


def _ask_model(prompt: str, model: str, cap: float) -> tuple[dict, float]:
    proc = subprocess.run(
        ["claude", "-p", prompt, "--model", model, "--max-turns", "1",
         "--max-budget-usd", f"{cap:.2f}", "--output-format", "json"],
        capture_output=True, text=True, timeout=300, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: {proc.stderr.strip()[:200]}")
    envelope = json.loads(proc.stdout)
    cost = float(envelope.get("total_cost_usd") or 0)
    text = str(envelope.get("result") or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError(f"no JSON object in the model's reply: {text[:120]!r}")
    return json.loads(text[start:end + 1]), cost


def run_t1_intake(data: dict, res: RoleResult, *, cfg: dict, dry_run: bool,
                  model: str | None = None, **_) -> None:
    errs = validate_t1_intake(data, cfg)
    if errs:
        res.errors.extend(errs)
        return
    if dry_run:
        for case in data["cases"]:
            res.cases.append(CaseResult(case["id"], True, case["expected"], detail="schema valid (dry run)"))
        return
    allowed = allowed_models(cfg)
    model = model or data.get("model")
    if model not in allowed:
        res.errors.append(f"model {model!r} is not in _data/fleet.yml ai_models.allowed {allowed}")
        return
    if shutil.which("claude") is None:
        res.errors.append("the `claude` CLI is not installed; use --dry-run for an offline check")
        return
    res.model = model
    cap = budget_cap(cfg)
    types = ", ".join((cfg.get("issue_pipeline") or {}).get("labels", {}).get("types") or [])
    for case in data["cases"]:
        remaining = cap - res.cost_usd
        if remaining <= 0:
            res.errors.append(f"budget.local_usd ${cap:.2f} spent before case {case['id']}")
            return
        inp, exp = case["input"], case["expected"]
        gaps = "\n".join(f"- [{g['by']}] {g['gap']}" for g in inp["gaps"]) or "- none"
        prompt = INTAKE_PROMPT.format(types=types, repo=inp["repo"], title=inp["title"],
                                      summary=inp["summary"], gaps=gaps)
        try:
            actual, cost = _ask_model(prompt, model, remaining)
        except (RuntimeError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
            res.cases.append(CaseResult(case["id"], False, exp, detail=str(exc)))
            continue
        res.cost_usd += cost
        problems = [f"{k} {actual.get(k)!r} != expected {exp[k]!r}"
                    for k in ("exit", "type") if k in exp and actual.get(k) != exp[k]]
        res.cases.append(CaseResult(case["id"], not problems, exp, actual, "; ".join(problems)))


# --------------------------------------------------------------------------- #
# adapter: console-assist — the console's assistant against a RECORDED page
#
# The mirror of tools/console/assist_standin.py, which scripts the model and
# keeps the page real: here the model is real and the page is recorded. Each
# case runs the `assist` op as the console builds it (core._assist: the shipped
# prompt files, the tool allowlist, the argv, read at run time, no copy here)
# through `dash-gen ai-run`, with the REAL MCP layer pointed at a recorded
# console (tools/console/assist_eval_console.py). The verdict is deterministic:
# it comes from that console's log, the session's tool calls and the answer.
# --------------------------------------------------------------------------- #
CONSOLE_DIR = ROOT / "tools" / "console"
ASSIST_SOURCE = "eval console-assist"       # the ledger row's source: never `console assist`, a person's message
ASSIST_MIN_CASES = 20
ASSIST_CANARY = (3, 8)                      # "about five": a canary subset smaller or larger than this is a mistake
ASSIST_PLACEHOLDERS = ("{{PAGE}}", "{{HISTORY}}", "{{CONTEXT}}", "{{QUESTION}}")
ASSIST_INPUT = ("question", "context", "history", "page", "api")
ASSIST_RULES = ("calls_all", "calls_any", "calls_none", "commands_all", "commands_none", "after_refusal",
                "max_page_commands", "answer_all", "answer_any", "answer_none")
ASSIST_COMMAND_KEYS = ("action", "state", "ref", "path", "key", "ok")
ASSIST_SOURCE_KINDS = ("rule", "evidence", "conversation")
MCP_PREFIX = "mcp__fleet__"
#: outcomes after which the next case would end the same way: the run stops instead of spending on it
ASSIST_STOP_OUTCOMES = ("usage_limit", "credential_rejected", "cli_missing", "startup_failed")
ASSIST_SPENDS = ("a model run of console-assist spends Claude budget, so it must say which cases: pass --canary "
                 "(the cases marked `canary: true`) or --all-cases (or --case ID for single ones); "
                 "--dry-run validates the set offline at $0")


def _console_modules():
    """tools/console's own modules, imported at run time: they ARE what is under test (core), the broker
    (page_bridge) and the recorded console. Stdlib and PyYAML only; nothing is started by importing them."""
    path = str(CONSOLE_DIR)
    if path not in sys.path:
        sys.path.insert(0, path)
    import assist_eval_console  # noqa: PLC0415
    import core  # noqa: PLC0415
    import page_bridge  # noqa: PLC0415
    return core, page_bridge, assist_eval_console


def assist_tools(core) -> dict[str, set[str]]:
    """The tool names a case may name: the MCP layer's (read from its source, so no `mcp` package is needed),
    the built-ins the assistant is allowed, and the ones it is denied (a case may say one is never called)."""
    from tools.fleetcore import graph  # noqa: PLC0415
    layer = set(graph.mcp_tools((CONSOLE_DIR / "mcp_layer" / "server.py").read_text(encoding="utf-8")))
    allowed = {t for t in core.ASSIST_ALLOWED if not t.startswith("mcp__")}
    return {"callable": layer | allowed, "known": layer | allowed | set(core.ASSIST_DENIED)}


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _source_errors(source) -> tuple[list[str], set[str]]:
    """What is wrong with a case's `source`, and which kinds it names. A `rule:` entry quotes a rule of a
    shipped file and the quote must still be there; an `evidence:` entry names a file that must exist."""
    entries = source if isinstance(source, list) else [source]
    errs: list[str] = []
    kinds: set[str] = set()
    if not entries:
        return ["source is empty"], kinds
    for entry in entries:
        m = re.match(r"^(\w+):\s*(.+)$", str(entry or ""), re.S)
        if not m or m.group(1) not in ASSIST_SOURCE_KINDS:
            errs.append(f"source entry {str(entry)[:60]!r} must start with one of "
                        f"{', '.join(k + ':' for k in ASSIST_SOURCE_KINDS)}")
            continue
        kind, rest = m.group(1), m.group(2).strip()
        kinds.add(kind)
        if kind == "conversation":
            continue
        quoted = re.match(r'^(\S+)\s+"(.+)"\s*$', rest, re.S) if kind == "rule" else None
        if kind == "rule" and not quoted:
            errs.append(f'source rule {rest[:60]!r} must be: rule: <file> "<the rule, quoted from it>"')
            continue
        rel = quoted.group(1) if quoted else rest.split()[0]
        path = (ROOT / rel).resolve()
        if ROOT.resolve() not in path.parents or not path.is_file():
            errs.append(f"source names {rel}, which is not a file of this repository")
            continue
        if quoted and _squash(quoted.group(2)) not in _squash(path.read_text(encoding="utf-8", errors="replace")):
            errs.append(f"source quotes a rule that is no longer in {rel}: {quoted.group(2)[:80]!r} — "
                        "the rule changed, so look at this case again")
    return errs, kinds


def _expected_errors(exp: dict, inp: dict, tools: dict, page_bridge, console) -> list[str]:
    errs = [f"expected.{k} is not a rule (known: {', '.join(ASSIST_RULES)})" for k in exp if k not in ASSIST_RULES]
    if not any(k in exp for k in ASSIST_RULES):
        errs.append("expected holds no rule")
    page = inp.get("page") if isinstance(inp.get("page"), dict) else None
    states = (page or {}).get("states") if isinstance((page or {}).get("states"), dict) else {}
    for key in ("calls_all", "calls_any", "calls_none"):
        names = exp.get(key, [])
        if not isinstance(names, list) or (key in exp and not names):
            errs.append(f"expected.{key} must be a non-empty list of tool names")
            continue
        pool = tools["known"] if key == "calls_none" else tools["callable"]
        errs += [f"expected.{key}: {n!r} is not a tool "
                 f"{'the layer or the CLI has' if key == 'calls_none' else 'an assistant session can call'}"
                 for n in names if n not in pool]
    for key in ("commands_all", "commands_none"):
        patterns = exp.get(key, [])
        if not isinstance(patterns, list) or (key in exp and not patterns):
            errs.append(f"expected.{key} must be a non-empty list of page-command patterns")
            continue
        if patterns and page is None:
            errs.append(f"expected.{key} needs a recorded page (input.page)")
            continue
        for p in patterns:
            if not isinstance(p, dict) or not p or set(p) - set(ASSIST_COMMAND_KEYS):
                errs.append(f"expected.{key}: a pattern is a mapping of {', '.join(ASSIST_COMMAND_KEYS)}, got {p!r}")
                continue
            actions = p.get("action")
            for a in (actions if isinstance(actions, list) else [actions] if "action" in p else []):
                if a not in page_bridge.ACTIONS:
                    errs.append(f"expected.{key}: {a!r} is not a page action")
            if "state" in p and p["state"] not in states:
                errs.append(f"expected.{key}: state {p['state']!r} is not a state of the recorded page")
            if "ok" in p and not isinstance(p["ok"], bool):
                errs.append(f"expected.{key}: ok must be true or false")
            if "ref" in p:
                where = [states[p["state"]]] if p.get("state") in states else list(states.values())
                if not any(p["ref"] in console.refs_in(str((s or {}).get("outline") or "")) for s in where):
                    errs.append(f"expected.{key}: ref {p['ref']} is in no outline it could be sent to")
    if "after_refusal" in exp and (exp["after_refusal"] != "stop" or page is None):
        errs.append("expected.after_refusal is `stop`, and needs a recorded page")
    if "max_page_commands" in exp:
        n = exp["max_page_commands"]
        if isinstance(n, bool) or not isinstance(n, int) or n < 1 or page is None:
            errs.append("expected.max_page_commands is a positive integer, and needs a recorded page")
    for key in ("answer_all", "answer_any", "answer_none"):
        needles = exp.get(key, [])
        if not isinstance(needles, list) or (key in exp and not needles):
            errs.append(f"expected.{key} must be a non-empty list of substrings or re: patterns")
            continue
        for needle in needles:
            if not isinstance(needle, str) or not needle.strip() or needle.strip() == "re:":
                errs.append(f"expected.{key}: {needle!r} is not a substring or a re: pattern")
            elif needle.startswith("re:"):
                try:
                    re.compile(needle[3:])
                except re.error as exc:
                    errs.append(f"expected.{key}: {needle!r} does not compile ({exc})")
    return errs


def validate_console_assist(data: dict, cfg: dict) -> tuple[list[str], list[str]]:
    """(errors, notes) for the set, offline: no model, no socket, no MCP package. It reads the shipped prompt
    files, the allowlist, the MCP layer's source and `assistant.model`, so a change to any of them that
    breaks what a case rests on fails here, which is what the eval-regression check runs."""
    try:
        core, page_bridge, console = _console_modules()
        tools = assist_tools(core)
    except (ImportError, OSError, SyntaxError) as exc:
        return [f"the console's modules cannot be read: {exc}"], []
    errs: list[str] = []
    cases = data["cases"]
    if "model" in data or data.get("model_from") != "assistant.model":
        errs.append("this role's model is _data/fleet.yml assistant.model: the set says `model_from: assistant.model` "
                    "and holds no `model:` of its own")
    try:
        core.assistant_config(cfg)
    except ValueError as exc:
        errs.append(str(exc))
    try:
        template = core.ASSIST_PROMPT.read_text(encoding="utf-8")
        core.ASSIST_PAGE_PROMPT.read_text(encoding="utf-8")
    except OSError as exc:
        errs.append(f"the assistant's prompt cannot be read: {exc}")
        template = "".join(ASSIST_PLACEHOLDERS)
    errs += [f"{core.ASSIST_PROMPT.name} no longer has the placeholder {p} this adapter fills (core._assist)"
             for p in ASSIST_PLACEHOLDERS if p not in template]
    if len(cases) < ASSIST_MIN_CASES:
        errs.append(f"{len(cases)} case(s), fewer than the {ASSIST_MIN_CASES} this role keeps (constitution § 13.1)")
    canary = [c.get("id") for c in cases if isinstance(c, dict) and c.get("canary") is True]
    if not ASSIST_CANARY[0] <= len(canary) <= ASSIST_CANARY[1]:
        errs.append(f"{len(canary)} case(s) marked `canary: true`; the canary subset is {ASSIST_CANARY[0]}–"
                    f"{ASSIST_CANARY[1]} cases (about five)")

    defaults = data.get("page") if isinstance(data.get("page"), dict) else {}
    errs += [f"api: {e.removeprefix('input.api')}" for e in console.validate_recording({"api": data.get("api")})]
    sentences = console.page_sentences(ROOT)
    if not sentences:
        errs.append(f"none of the page's sources can be read ({', '.join(console.PAGE_SOURCES)}), so a recorded "
                    "refusal cannot be held to the page's own sentence")
    shared = [("page.note", defaults.get("note"))] + [(f"page.says.{k}", v)
                                                     for k, v in (defaults.get("says") or {}).items()]
    errs += [f"{where}: {str(text)[:70]!r} is not a sentence the page's code says ({console.PAGE_SOURCES[0]})"
             for where, text in shared if text and sentences and not console.said_by_page(text, sentences)]
    nav = console.nav_pairs(ROOT)
    for line in defaults.get("pages") or []:
        for pair in str(line).split(": ", 1)[-1].split(", "):
            if pair.strip() not in nav:
                errs.append(f"page.pages: {pair.strip()!r} is not a page of the console's navigation "
                            f"({console.NAV_SOURCE})")

    mix = dict.fromkeys(ASSIST_SOURCE_KINDS, 0)
    for case in cases:
        cid, inp, exp = case.get("id"), case.get("input") or {}, case.get("expected") or {}
        found: list[str] = []
        if "canary" in case and not isinstance(case["canary"], bool):
            found.append("canary must be true or false")
        source_errs, kinds = _source_errors(case.get("source"))
        found += source_errs
        # what a case is, by the best source it has: a real conversation, then recorded evidence, then a rule
        for kind in ("conversation", "evidence", "rule"):
            if kind in kinds:
                mix[kind] += 1
                break
        found += [f"input.{k} is not a field (known: {', '.join(ASSIST_INPUT)})" for k in inp if k not in ASSIST_INPUT]
        question = inp.get("question")
        if not isinstance(question, str) or not question.strip() or len(question) > core.ASSIST_MAX_CHARS:
            found.append(f"input.question must be 1–{core.ASSIST_MAX_CHARS} characters")
        if "context" in inp and not isinstance(inp["context"], str):
            found.append("input.context must be a string")
        history = inp.get("history", [])
        if not isinstance(history, list) or not all(isinstance(h, dict) and set(h) == {"person", "you"}
                                                    and all(isinstance(v, str) and v.strip() for v in h.values())
                                                    for h in history):
            found.append("input.history must be a list of {person, you} exchanges")
        found += console.validate_recording(inp, defaults)
        if sentences:
            found += [f"input.page.{where}: {text[:70]!r} is not a sentence the page's code says "
                      f"({console.PAGE_SOURCES[0]}); a recorded refusal is the page's own, verbatim"
                      for where, text in console.recorded_refusals(inp, defaults)
                      if not console.said_by_page(text, sentences)]
        found += _expected_errors(exp, inp, tools, page_bridge, console)
        errs += [f"{cid}: {e}" for e in found]
    notes = [f"{len(cases)} cases by source: {mix['rule']} written for a rule only, {mix['evidence']} with recorded "
             f"evidence, {mix['conversation']} from a real conversation",
             f"canary ({len(canary)}): {', '.join(map(str, canary))}"]
    return errs, notes


# -- grading: a pure function of the case, the rows and the answer ----------- #
def _normal(text: str) -> str:
    """An answer as it is matched: typographic quotes straightened, Markdown's emphasis and code marks
    dropped (`**Look** mode` is "Look mode"), whitespace runs single. Underscores stay: names are made of them."""
    return _squash(str(text or "").translate({0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"', 0xA0: " ",
                                              ord("*"): None, ord("`"): None}))


def _says(needle: str, text: str) -> bool:
    if needle.startswith("re:"):
        return re.search(needle[3:], text, re.I | re.S) is not None
    return _normal(needle).lower() in text.lower()


def _command_matches(pattern: dict, row: dict, ok: bool | None = None) -> bool:
    if "action" in pattern:
        actions = pattern["action"] if isinstance(pattern["action"], list) else [pattern["action"]]
        if row.get("action") not in actions:
            return False
    if "state" in pattern and row.get("state") != pattern["state"]:
        return False
    if any(key in pattern and (row.get("args") or {}).get(key) != pattern[key] for key in ("ref", "path", "key")):
        return False
    want = pattern.get("ok", ok)
    return want is None or bool(row.get("ok")) == want


def _command_text(row: dict) -> str:
    args = row.get("args") or {}
    target = args.get("ref") or args.get("path") or args.get("key") or ""
    return (f"{row.get('action')}{' ' + str(target) if target else ''}"
            f"{' in ' + str(row['state']) if row.get('state') else ''}")


def grade_console_assist(case: dict, rows: list[dict], answer: str) -> tuple[list[str], dict]:
    """(problems, facts): what `expected` asked for and did not get, from the rows alone.

    `rows` are the recorded console's log rows, in order (a page command is `kind: page`, with its action,
    args, the state it was answered in, ok, and `refusal` when the page or the person said no), followed by
    one `{"tool": name}` row per tool the session called (its trace), so a tool that never reaches the
    console — Read, a fleet tool that reads the checkout — is seen too. No model, no file, no clock."""
    exp = case.get("expected") or {}
    act = _console_modules()[1].ACT
    page = [r for r in rows if r.get("kind") == "page"]
    called = {r["tool"] for r in rows if r.get("tool")}
    text = _normal(answer)
    problems: list[str] = []
    problems += [f"did not call {t}" for t in exp.get("calls_all", []) if t not in called]
    if exp.get("calls_any") and not called & set(exp["calls_any"]):
        problems.append(f"called none of {', '.join(exp['calls_any'])}")
    problems += [f"called {t}, which it must not" for t in exp.get("calls_none", []) if t in called]
    for pattern in exp.get("commands_all", []):
        if not any(_command_matches(pattern, r, True) for r in page):
            problems.append(f"sent no page command matching {json.dumps(pattern)}")
    for pattern in exp.get("commands_none", []):
        hit = next((r for r in page if _command_matches(pattern, r)), None)
        if hit is not None:
            problems.append(f"sent {_command_text(hit)} (row {hit.get('n')}), which {json.dumps(pattern)} forbids")
    refused = next((i for i, r in enumerate(page) if r.get("refusal")), None)
    if exp.get("after_refusal") == "stop" and refused is not None:
        later = next((r for r in page[refused + 1:] if r.get("action") in act), None)
        if later is not None:
            problems.append(f"after {_command_text(page[refused])} was refused it still sent {_command_text(later)} "
                            f"(row {later.get('n')})")
    limit = exp.get("max_page_commands")
    if limit is not None and len(page) > limit:
        problems.append(f"{len(page)} page commands, more than max_page_commands {limit}")
    if any(k in exp for k in ("answer_all", "answer_any", "answer_none")) and not text:
        problems.append("the session gave no answer")
    elif text:
        problems += [f"the answer lacks {n!r}" for n in exp.get("answer_all", []) if not _says(n, text)]
        if exp.get("answer_any") and not any(_says(n, text) for n in exp["answer_any"]):
            problems.append(f"the answer has none of {exp['answer_any']!r}")
        problems += [f"the answer says {n!r}" for n in exp.get("answer_none", []) if _says(n, text)]
    facts = {"tools": sorted(called), "page_commands": [_command_text(r) for r in page],
             "refusals": sum(1 for r in page if r.get("refusal")),
             "unrecorded": [_command_text(r) for r in page if r.get("recorded") is False]}
    return problems, facts


# -- a model run: one capped session per case -------------------------------- #
def _set_flag(argv: list[str], flag: str, value: str, *, after: str | None = None) -> None:
    """Replace the value of a flag core._assist put in the argv. A flag that is no longer there is an error,
    never a silent drop: the cap and the model must not go missing because the argv changed shape."""
    start = argv.index(after) if after else 0
    try:
        i = argv.index(flag, start)
    except ValueError:
        raise RuntimeError(f"core._assist no longer passes {flag}; tools/evals.py must follow it") from None
    argv[i + 1] = value


def _flag(argv: list[str], flag: str) -> str:
    try:
        return argv[argv.index(flag) + 1]
    except (ValueError, IndexError):
        raise RuntimeError(f"core._assist no longer passes {flag}; tools/evals.py must follow it") from None


@contextlib.contextmanager
def _as_the_console(core, page_bridge, jobs: Path, bridge):
    """core._assist as the console calls it, with the console's two process-wide things pointed at this run:
    its job directory (where it writes the prompt and the MCP config, and reads a conversation back) and its
    page bridge (which it asks whether the page's session is open)."""
    saved = core.JOB_DIR, page_bridge.BRIDGE
    core.JOB_DIR, page_bridge.BRIDGE = jobs, bridge
    try:
        yield
    finally:
        core.JOB_DIR, page_bridge.BRIDGE = saved


def assist_argv(case: dict, recorded, work: Path, *, model: str, cap: float, claude: str, venv: Path) -> dict:
    """The command for one case: core._assist's own argv, re-pointed. What changes, and nothing else: the
    ledger source, the cap (never above assistant.budget_usd), the model when --model overrode it, a trace,
    the exact `claude` this run resolved, and the MCP layer's console address (the recorded one) with a
    placeholder token so no real one travels. Returns the argv and the files the run will leave."""
    core, page_bridge, _ = _console_modules()
    inp = case["input"]
    params = {"question": inp["question"], "context": inp.get("context") or "", "page": recorded.sid or ""}
    with _as_the_console(core, page_bridge, work, recorded.bridge):
        history = inp.get("history") or []
        if history:
            # a conversation as the console keeps one: its record and each earlier answer's result file
            record = {"id": uuid.uuid4().hex[:12], "asks": []}
            for turn in history:
                ask = uuid.uuid4().hex[:12]
                (core._assist_dir() / f"{ask}.result.json").write_text(json.dumps({"result": turn["you"]}),
                                                                       encoding="utf-8")
                record["asks"].append({"id": ask, "question": turn["person"], "page": False,
                                       "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")})
            core._conversation_path(record["id"]).write_text(json.dumps(record, indent=1), encoding="utf-8")
            params["conversation"] = record["id"]
        argv = list(core._assist(params))
    split = argv.index("--")
    _set_flag(argv, "--source", ASSIST_SOURCE)
    _set_flag(argv, "--max-budget-usd", f"{cap:g}")
    _set_flag(argv, "--model", model, after="--")
    files = {"prompt": Path(_flag(argv, "--prompt-file")), "result": Path(_flag(argv, "--result-file")),
             "outcome": Path(_flag(argv, "--outcome-file")), "mcp": Path(_flag(argv, "--mcp-config")),
             "trace": work / "trace.jsonl", "console": recorded.log_path}
    argv[split:split] = ["--trace", str(files["trace"]), "--claude-bin", claude]
    doc = json.loads(files["mcp"].read_text(encoding="utf-8"))
    server = doc["mcpServers"]["fleet"]
    server["env"].update({"DASH_CONSOLE_URL": recorded.url, "DASH_CONSOLE_TOKEN": "recorded-console",
                          "HARNESS_MCP_DOTENV": str(work / "no.env"), "HARNESS_MCP_VENV": str(venv),
                          "HARNESS_MCP_AUDIT": str(work / "mcp-audit.jsonl")})
    files["mcp"].write_text(json.dumps(doc, indent=1), encoding="utf-8")
    # Read back, not assumed: core._assist writes the address of a LIVE console (DASH_CONSOLE_URL, else
    # :4001), and a session whose tools reached that one would be reading and driving the real thing.
    written = _read_json(files["mcp"]).get("mcpServers") or {}
    if list(written) != ["fleet"] or written["fleet"].get("env", {}).get("DASH_CONSOLE_URL") != recorded.url:
        raise RuntimeError("the session's MCP config does not point at the recorded console alone; nothing was run")
    return {"argv": argv, "files": files, "timeout_s": float(_flag(argv, "--timeout"))}


def _mcp_preflight(venv: Path, env: dict, page_bridge) -> str | None:
    """Why a session would not get its page tools from the MCP layer, or None. $0: the layer prints its
    catalog and exits; nothing is asked of any console. Checked BEFORE a session is paid for."""
    run_env = {**env, "HARNESS_MCP_VENV": str(venv), "HARNESS_MCP_SKIP_INSTALL": "1", "HARNESS_MCP_SCOPES": "page",
               "HARNESS_MCP_PAGE_SESSION": "0" * 32, "HARNESS_MCP_ALLOW_WRITES": "0", "HARNESS_MCP_FLEET_COMPAT": "0"}
    try:
        proc = subprocess.run([str(CONSOLE_DIR / "mcp.sh"), "--list-tools"], env=run_env, capture_output=True,
                              text=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"the MCP layer did not start: {exc}"
    names = {line.split()[-1] for line in proc.stdout.splitlines() if line.strip()}
    missing = [f"page_{a}" for a in page_bridge.ACTIONS if f"page_{a}" not in names]
    if proc.returncode != 0 or missing:
        return (f"the MCP layer (tools/console/mcp.sh, {venv}) exited {proc.returncode} and lacks "
                f"{', '.join(missing) or 'nothing'}: {proc.stderr.strip()[-300:]}")
    return None


def _session_trace(path: Path) -> tuple[list[dict], list[str] | None]:
    """(one row per tool the session called, in order; the tools the session started with) from ai-run's trace."""
    calls: list[dict] = []
    started: list[str] | None = None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return calls, started
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "system" and event.get("subtype") == "init":
            started = [str(t) for t in event.get("tools") or []]
        message = event.get("message") if event.get("type") == "assistant" else None
        content = message.get("content") if isinstance(message, dict) else None
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                calls.append({"kind": "tool", "source": "session",
                              "tool": str(block.get("name") or "?").removeprefix(MCP_PREFIX)})
    return calls, started


def _read_json(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def run_assist_case(case: dict, defaults: dict, work: Path, *, model: str, cap: float, claude: str, venv: Path,
                    env: dict, shared_api: dict | None = None) -> dict:
    """One case, for real: the recorded console up, one capped session through ai-run, then the verdict.
    Returns problems, facts, the cost charged and the outcome kind. Never called under --dry-run."""
    _, _, console = _console_modules()
    work.mkdir(parents=True, exist_ok=True)
    out: dict = {"problems": [], "notes": [], "facts": {}, "cost_usd": 0.0, "outcome": None, "work": str(work)}
    with console.RecordedConsole(case["input"], work / "console.jsonl", defaults=defaults, case_id=case["id"],
                                 shared_api=shared_api) as recorded:
        try:
            plan = assist_argv(case, recorded, work, model=model, cap=cap, claude=claude, venv=venv)
        except (ValueError, RuntimeError, OSError, KeyError) as exc:
            out["problems"].append(f"the session could not be built: {exc}")
            return out
        try:
            proc = subprocess.run(plan["argv"], env=env, capture_output=True, text=True, check=False,
                                  timeout=plan["timeout_s"] + 180)
            stderr = proc.stderr
        except subprocess.TimeoutExpired as exc:
            # ai-run has its own wall clock; past it and three minutes more nothing can be read back, so the
            # case is charged its cap (a run whose cost cannot be read is otherwise charged to nobody)
            out.update(cost_usd=cap, outcome="timeout")
            out["problems"].append(f"ai-run did not return within {exc.timeout:g}s; charged the ${cap:g} cap "
                                   f"{COST_LABEL}")
            return out
    files = plan["files"]
    outcome, result = _read_json(files["outcome"]), _read_json(files["result"])
    calls, started = _session_trace(files["trace"])
    # ai-run's own count of the session's tool calls: the trace is size-capped, this is not
    counted = outcome.get("tool_uses") if isinstance(outcome.get("tool_uses"), dict) else {}
    seen = {c["tool"] for c in calls}
    calls += [{"kind": "tool", "source": "outcome", "tool": name}
              for name in (str(n).removeprefix(MCP_PREFIX) for n in counted) if name not in seen]
    rows = console.read_log(files["console"]) + calls
    answer = str(result.get("result") or "")
    out["outcome"] = outcome.get("kind")
    out["cost_usd"] = float(outcome.get("cost_usd") or result.get("total_cost_usd") or 0.0)
    if outcome.get("kind") != "ok":
        tail = " | ".join(line.strip() for line in stderr.strip().splitlines()[-3:])
        out["problems"].append(f"the session ended as {outcome.get('kind') or 'unknown'} "
                               f"({outcome.get('detail') or f'ai-run exited {proc.returncode}'}): {tail[-300:]}")
    if started is not None and recorded.sid and f"{MCP_PREFIX}page_snapshot" not in started:
        # said, not failed: a CLI may list a server's tools after its init record. If the tools really were
        # missing, the case's own rules fail it.
        out["notes"].append("the session's init record lists no page tools: check the trace's mcp_servers")
    problems, facts = grade_console_assist(case, rows, answer)
    out["problems"] += problems
    out["facts"] = {**facts, "answer": answer[:2000], "outcome": outcome.get("kind"),
                    "turns": outcome.get("turns"), "cost_usd": round(out["cost_usd"], 4), "cost_label": COST_LABEL,
                    "cost_source": outcome.get("cost_source"), "files": str(work)}
    return out


def run_console_assist(data: dict, res: RoleResult, *, cfg: dict, dry_run: bool, model: str | None = None,
                       select=None, env: dict | None = None, out_dir: Path | None = None, **_) -> None:
    if not dry_run and not select:
        res.errors.append(ASSIST_SPENDS)
        return
    errs, notes = validate_console_assist(data, cfg)
    res.notes.extend(notes)
    if errs:
        res.errors.extend(errs)
        return
    cases = data["cases"]
    if dry_run:
        for case in cases:
            res.cases.append(CaseResult(case["id"], True, case["expected"],
                                        detail="recording, sources and rules valid (dry run)"))
        return
    if select == "all":
        chosen = cases
    elif select == "canary":
        chosen = [c for c in cases if c.get("canary") is True]
    else:
        by_id = {c["id"]: c for c in cases}
        unknown = [i for i in select if i not in by_id]
        if unknown:
            res.errors.append(f"no such case: {', '.join(unknown)}")
            return
        chosen = [by_id[i] for i in select]
    core, page_bridge, _ = _console_modules()
    assistant = core.assistant_config(cfg)
    allowed = allowed_models(cfg)
    model = model or assistant.model
    if model not in allowed:
        res.errors.append(f"model {model!r} is not in _data/fleet.yml ai_models.allowed {allowed}")
        return
    env = dict(os.environ if env is None else env)
    env.setdefault("PYTHON", sys.executable)        # tools/dash-gen: the interpreter that has PyYAML
    claude = shutil.which("claude", path=env.get("PATH"))
    if claude is None:
        res.errors.append("the `claude` CLI is not installed; use --dry-run for an offline check")
        return
    venv = Path(env.get("HARNESS_MCP_VENV") or ROOT / ".venv-mcp").expanduser()
    if not (venv / "bin" / "python").is_file():
        res.errors.append(f"the MCP layer's virtualenv is not at {venv}: run tools/console/mcp.sh --list-tools once "
                          "in the main checkout, or point HARNESS_MCP_VENV at one (a worktree has none of its own, "
                          "and this run creates none)")
        return
    why = _mcp_preflight(venv, env, page_bridge)
    if why:
        res.errors.append(why)
        return
    res.model = model
    cap = budget_cap(cfg)
    out = Path(out_dir).expanduser() if out_dir else Path(tempfile.mkdtemp(prefix="evals-console-assist-"))
    res.notes.append(f"each case's prompt, MCP config, trace, console log, result and outcome: {out}")
    res.notes.append(f"cap: ${cap:g} for the run (budget.local_usd), ${assistant.budget_usd:g} a case "
                     f"(assistant.budget_usd), {COST_LABEL}")
    for n, case in enumerate(chosen):
        remaining = cap - res.cost_usd
        if remaining <= 0:
            res.errors.append(f"budget.local_usd ${cap:.2f} {COST_LABEL} spent before case {case['id']}: "
                              f"{len(chosen) - n} case(s) not run")
            return
        got = run_assist_case(case, data.get("page") or {}, out / case["id"], model=model,
                              cap=min(assistant.budget_usd, remaining), claude=claude, venv=venv, env=env,
                              shared_api=data.get("api"))
        res.cost_usd += got["cost_usd"]
        res.notes += [f"{case['id']}: {note}" for note in got.get("notes") or []]
        if got["facts"].get("unrecorded"):
            res.notes.append(f"{case['id']}: the session sent {len(got['facts']['unrecorded'])} page command(s) "
                             f"the recording does not cover ({', '.join(got['facts']['unrecorded'][:4])}); "
                             "the page gave no answer to them")
        res.cases.append(CaseResult(case["id"], not got["problems"], case["expected"], got["facts"],
                                    "; ".join(got["problems"])))
        if got["outcome"] is None or got["outcome"] in ASSIST_STOP_OUTCOMES:
            # no outcome at all: ai-run refused the command or never wrote one, which no later case would change
            res.errors.append(f"stopped after {case['id']}: the session ended as {got['outcome'] or 'no outcome'}, "
                              f"and the next would too; {len(chosen) - n - 1} case(s) not run")
            return


# --------------------------------------------------------------------------- #
# adapter: pr-ai-analysis — the CI failure analyst of pr-review.yml (§ 19.11)
#
# The prompt under test is the SHIPPED one: pr_ai_analysis.compose() builds the
# user prompt from a case's recorded run material and pr_ai_analysis.SYSTEM is
# the system prompt, both imported at run time, never copied here. The answer is
# read with the shipped parser (parse_answer), so a reply the workflow would
# refuse fails the case. A dry run checks the set and that every case's prompt
# composes under the workflow's byte budget, at $0.
# --------------------------------------------------------------------------- #
ANALYSIS_VERDICTS = ("yes", "no", "unclear")
ANALYSIS_MIN_CASES = 10


def _analysis_module():
    path = str(ROOT / ".github" / "scripts" / "dash-gen")
    if path not in sys.path:
        sys.path.insert(0, path)
    import pr_ai_analysis  # noqa: PLC0415 - the module under test, imported where it is used
    return pr_ai_analysis


def analysis_material(case: dict) -> dict:
    """A case's recorded input in the shape pr_ai_analysis.compose() takes."""
    inp = case["input"]
    runs = []
    for i, r in enumerate(inp["runs"]):
        rid = int(r.get("id") or i + 1)
        jobs = [{"job": j["job"], "step": j.get("step") or "", "reason": j.get("reason") or "",
                 "class": j.get("class") or "defect", "cause": j.get("cause") or "",
                 "log_tail": [line for line in str(j.get("log") or "").split("\n")]} for j in r.get("jobs") or []]
        runs.append({"plan": {"id": rid, "name": r["name"], "conclusion": r.get("conclusion") or "failure",
                              "attempt": int(r.get("attempt") or 1), "path": r.get("path") or ""},
                     "report": {"note": r.get("note") or "", "this_pr": r.get("this_pr") or "", "jobs": jobs},
                     "workflow": r.get("workflow") or ""})
    return {"pr": int(inp.get("pr") or 1), "sha": str(inp.get("sha") or "0" * 40), "repo": inp["repo"],
            "title": inp.get("title") or "", "base": inp.get("base") or "main", "runs": runs,
            "files": list(inp.get("files") or []), "patches": [str(inp.get("diff") or "")]}


def validate_pr_ai_analysis(data: dict, cfg: dict) -> list[str]:
    errs = []
    analysis = _analysis_module()
    if data.get("model") not in allowed_models(cfg):
        errs.append(f"model {data.get('model')!r} is not in _data/fleet.yml ai_models.allowed")
    if data.get("model") != analysis.MODEL:
        errs.append(f"model {data.get('model')!r} is not the shipped analyst's ({analysis.MODEL}): "
                    "the set must test the model the workflow runs")
    if len(data.get("cases") or []) < ANALYSIS_MIN_CASES:
        errs.append(f"fewer than {ANALYSIS_MIN_CASES} cases")
    for case in data.get("cases") or []:
        cid, inp, exp = case.get("id"), case.get("input") or {}, case.get("expected") or {}
        for key in ("repo", "title", "runs", "files", "diff"):
            if key not in inp:
                errs.append(f"{cid}: input.{key} missing")
        for r in inp.get("runs") or []:
            if not isinstance(r, dict) or not r.get("name") or not (r.get("jobs") or r.get("note")):
                errs.append(f"{cid}: each run needs a `name` and `jobs` (or a `note` for a run with no job)")
            for j in (r.get("jobs") or []) if isinstance(r, dict) else []:
                if not isinstance(j, dict) or not j.get("job") or not str(j.get("log") or "").strip():
                    errs.append(f"{cid}: each job needs `job` and a non-empty `log`")
        if exp.get("caused_by_pr") not in ANALYSIS_VERDICTS:
            errs.append(f"{cid}: expected.caused_by_pr must be one of {ANALYSIS_VERDICTS}")
        terms = exp.get("root_cause_any")
        if not isinstance(terms, list) or not terms or not all(isinstance(t, str) and t.strip() for t in terms):
            errs.append(f"{cid}: expected.root_cause_any must be a non-empty list of phrases")
        if errs:
            continue
        prompt = analysis.compose(analysis_material(case))
        if len(prompt.encode("utf-8")) > analysis.MAX_PROMPT_BYTES:
            errs.append(f"{cid}: the composed prompt is over the workflow's {analysis.MAX_PROMPT_BYTES}-byte budget")
    return errs


def grade_pr_ai_analysis(exp: dict, entry: dict | None) -> list[str]:
    if not entry:
        return ["the answer analysed no run"]
    problems = []
    if entry["caused_by_pr"] != exp["caused_by_pr"]:
        problems.append(f"caused_by_pr {entry['caused_by_pr']!r} != expected {exp['caused_by_pr']!r}")
    said = " ".join(str(entry.get(k) or "") for k in ("summary", "root_cause", "evidence")).lower()
    if not any(t.lower() in said for t in exp["root_cause_any"]):
        problems.append(f"the root cause names none of {exp['root_cause_any']}")
    return problems


def run_pr_ai_analysis(data: dict, res: RoleResult, *, cfg: dict, dry_run: bool,
                       model: str | None = None, **_) -> None:
    errs = validate_pr_ai_analysis(data, cfg)
    if errs:
        res.errors.extend(errs)
        return
    if dry_run:
        for case in data["cases"]:
            res.cases.append(CaseResult(case["id"], True, case["expected"], detail="schema valid, prompt composes (dry run)"))
        return
    analysis = _analysis_module()
    allowed = allowed_models(cfg)
    model = model or data.get("model")
    if model not in allowed:
        res.errors.append(f"model {model!r} is not in _data/fleet.yml ai_models.allowed {allowed}")
        return
    if shutil.which("claude") is None:
        res.errors.append("the `claude` CLI is not installed; use --dry-run for an offline check")
        return
    res.model = model
    cap = budget_cap(cfg)
    for case in data["cases"]:
        remaining = cap - res.cost_usd
        if remaining <= 0:
            res.errors.append(f"budget.local_usd ${cap:.2f} spent before case {case['id']}")
            return
        material = analysis_material(case)
        ids = [int(r["plan"]["id"]) for r in material["runs"]]
        try:
            proc = subprocess.run(
                ["claude", "-p", analysis.compose(material), "--append-system-prompt", analysis.SYSTEM,
                 "--model", model, "--max-turns", "1", "--permission-mode", "default",
                 "--max-budget-usd", f"{remaining:.2f}", "--output-format", "json"],
                capture_output=True, text=True, timeout=300, check=False)
            if proc.returncode != 0:
                raise RuntimeError(f"claude exited {proc.returncode}: {proc.stderr.strip()[:200]}")
            envelope = json.loads(proc.stdout)
            res.cost_usd += float(envelope.get("total_cost_usd") or 0)
            parsed = analysis.parse_answer(str(envelope.get("result") or ""), ids)
        except (RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            res.cases.append(CaseResult(case["id"], False, case["expected"], detail=str(exc)[:300]))
            continue
        entry = parsed.get(ids[0])
        problems = grade_pr_ai_analysis(case["expected"], entry)
        res.cases.append(CaseResult(case["id"], not problems, case["expected"], entry, "; ".join(problems)))


ADAPTERS = {"console-assist": run_console_assist, "jev-classify": run_jev_classify,
            "pr-ai-analysis": run_pr_ai_analysis, "t1-intake": run_t1_intake}


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #
def roles() -> list[str]:
    return sorted(p.parent.name for p in EVALS_DIR.glob("*/cases.yml"))


def run_role(role: str, *, cases_path: Path | None = None, dry_run: bool = False,
             model: str | None = None, cfg: dict | None = None, select=None, env: dict | None = None,
             out_dir: Path | None = None) -> RoleResult:
    """`select` (console-assist): which cases a model run takes — "canary", "all" or a list of ids. `env` is
    the environment its sessions run in (default: this process's); `out_dir` where they leave their files."""
    cfg = fleet_config() if cfg is None else cfg
    path = cases_path or EVALS_DIR / role / "cases.yml"
    try:
        data = load_set(path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        res = RoleResult(role=role, mode="unknown", dry_run=dry_run)
        res.errors.append(str(exc))
        return res
    mode = str(data.get("mode", "unknown"))
    # A deterministic role has nothing to skip: --dry-run runs it in full.
    res = RoleResult(role=role, mode=mode, dry_run=dry_run and mode != "deterministic")
    adapter = ADAPTERS.get(role)
    if adapter is None:
        res.errors.append(f"no adapter for role {role!r} (known: {sorted(ADAPTERS)})")
        return res
    res.errors.extend(validate_common(data, role))
    if res.errors:
        return res
    adapter(data, res, cfg=cfg, dry_run=dry_run, model=model, select=select, env=env, out_dir=out_dir)
    return res


def render_text(res: RoleResult) -> str:
    head = f"{res.role} ({res.mode}{', dry run' if res.dry_run else ''}"
    head += f", model {res.model}, ${res.cost_usd:.2f} {COST_LABEL}" if res.model else ""
    lines = [f"{head}): {res.passed} passed, {res.failed} failed"]
    lines += [f"  ERROR {e}" for e in res.errors]
    lines += [f"  note  {n}" for n in res.notes]
    lines += [f"  FAIL  {c.id}: {c.detail}" for c in res.cases if not c.passed]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the agent eval sets under evals/ (constitution § 13).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list the roles that have an eval set")
    run = sub.add_parser("run", help="run one role's eval set, or --all")
    run.add_argument("role", nargs="?")
    run.add_argument("--all", action="store_true", help="every role under evals/")
    run.add_argument("--json", action="store_true", help="one JSON object per role")
    run.add_argument("--dry-run", action="store_true", help="validate model-backed sets without calling a model")
    run.add_argument("--model", help="override the set's model (must be in ai_models.allowed)")
    run.add_argument("--cases", type=Path, help="an alternate cases file for the role")
    spends = run.add_argument_group("console-assist model runs (each case is one capped session: this spends)")
    spends.add_argument("--canary", action="store_true", help="run the cases marked `canary: true` (about five)")
    spends.add_argument("--all-cases", action="store_true", help="run every case of the set")
    spends.add_argument("--case", action="append", default=[], metavar="ID", help="run one case by id; repeatable")
    spends.add_argument("--out", type=Path, metavar="DIR",
                        help="keep each case's prompt, trace, console log and result here (default: a new temporary directory)")
    args = ap.parse_args(argv)

    if args.cmd == "list":
        print("\n".join(roles()))
        return 0
    if bool(args.role) == bool(args.all):
        ap.error("name one role, or pass --all")
    if args.all and args.cases:
        ap.error("--cases needs a single role")
    if sum([args.canary, args.all_cases, bool(args.case)]) > 1:
        ap.error("--canary, --all-cases and --case choose the cases of one run: pass one of them")
    select = "canary" if args.canary else "all" if args.all_cases else (args.case or None)
    targets = roles() if args.all else [args.role]
    cfg = fleet_config()
    results = [run_role(r, cases_path=args.cases, dry_run=args.dry_run, model=args.model, cfg=cfg,
                        select=select, out_dir=args.out)
               for r in targets]
    if args.json:
        payload = [r.to_json() for r in results]
        print(json.dumps(payload[0] if len(payload) == 1 and not args.all else payload, indent=2))
    else:
        print("\n".join(render_text(r) for r in results))
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
