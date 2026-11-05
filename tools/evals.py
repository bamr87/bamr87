#!/usr/bin/env python3
"""
File: tools/evals.py
Description: The eval runner (constitution § 13.1–13.2). Each agent role keeps
             a versioned eval set at evals/<role>/cases.yml: real past tasks,
             each with an input, the expected output, a pass criterion and an
             optional LLM-judge rubric. This runner loads a set, hands every
             case to the role's ADAPTER and reports pass / fail per case. Any
             failed case makes the exit status non-zero, which is what turns an
             eval regression into a failing CI check (.github/workflows/evals.yml).

             Two kinds of role:
               deterministic  the adapter calls the code under test directly —
                              no network, no `claude` CLI (jev-classify).
               model          the adapter asks a pinned model; `--dry-run`
                              validates the set's schema without calling one
                              (t1-intake). A model run uses only ids from
                              _data/fleet.yml `ai_models.allowed` and is capped
                              by `budget.local_usd` (`--max-budget-usd`).
Author: bamr87
Created: 2026-11-04
Version: 0.1.0
Usage: python3 tools/evals.py list
       python3 tools/evals.py run <role> [--json] [--dry-run] [--model ID]
       python3 tools/evals.py run --all [--json] [--dry-run]
       python3 tools/evals.py run <role> --cases <path>   # an alternate cases file
Exit:  0 every case passed (or validated, under --dry-run); 1 a case failed or
       the set is malformed; 2 usage error.
Dependencies: PyYAML; the `claude` CLI only for a model run.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
EVALS_DIR = ROOT / "evals"
FLEET_YML = ROOT / "_data" / "fleet.yml"
SCHEMA = "evals/v1"

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
            "model": self.model, "cost_usd": round(self.cost_usd, 4),
            "passed": self.passed, "failed": self.failed, "errors": self.errors,
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


ADAPTERS = {"jev-classify": run_jev_classify, "t1-intake": run_t1_intake}


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #
def roles() -> list[str]:
    return sorted(p.parent.name for p in EVALS_DIR.glob("*/cases.yml"))


def run_role(role: str, *, cases_path: Path | None = None, dry_run: bool = False,
             model: str | None = None, cfg: dict | None = None) -> RoleResult:
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
    adapter(data, res, cfg=cfg, dry_run=dry_run, model=model)
    return res


def render_text(res: RoleResult) -> str:
    head = f"{res.role} ({res.mode}{', dry run' if res.dry_run else ''}"
    head += f", model {res.model}, ${res.cost_usd:.2f} API-equivalent (estimate)" if res.model else ""
    lines = [f"{head}): {res.passed} passed, {res.failed} failed"]
    lines += [f"  ERROR {e}" for e in res.errors]
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
    args = ap.parse_args(argv)

    if args.cmd == "list":
        print("\n".join(roles()))
        return 0
    if bool(args.role) == bool(args.all):
        ap.error("name one role, or pass --all")
    if args.all and args.cases:
        ap.error("--cases needs a single role")
    targets = roles() if args.all else [args.role]
    cfg = fleet_config()
    results = [run_role(r, cases_path=args.cases, dry_run=args.dry_run, model=args.model, cfg=cfg)
               for r in targets]
    if args.json:
        payload = [r.to_json() for r in results]
        print(json.dumps(payload[0] if len(payload) == 1 and not args.all else payload, indent=2))
    else:
        print("\n".join(render_text(r) for r in results))
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
