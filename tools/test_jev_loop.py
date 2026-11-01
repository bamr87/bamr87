#!/usr/bin/env python3
"""
End-to-end tests for tools/jev/loop.py — the local loop engine's $0 slice
(#486 PR-B, ADR 0002 P1): `list`, `doctor`, `plan`, `run --rehearse`, `show`.

Nothing here can spend. `claude` is a stub that answers --version and
`auth status`, refuses an empty stdin with "Input must be provided" (the flag
preflight), plays the isolation probe credential-free, and drops a PROMPTED
marker if anything ever hands it a real prompt — every test asserts it never
appears. `gh` is a stub whose `repo clone` clones a local fixture and whose
reads answer from fixtures; it logs every call, and no write verb ever shows
up. The planner is the REAL `tools/dash-gen scout` (it reads GitHub through
the stub), and the rehearsal runs the real `dash-gen ai-run --dry-run`.

Run: python3 tools/test_jev_loop.py
"""
from __future__ import annotations

import contextlib
import copy
import dataclasses
import fcntl
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

HUB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUB))

from tools.jev import headless as H  # noqa: E402
from tools.jev import loop as L  # noqa: E402
from tools.jev import spec as S  # noqa: E402
from tools.jev.__main__ import main as jev_main  # noqa: E402
from tools.jev import common  # noqa: E402
from tools.jev import workspace as W  # noqa: E402
from tools.jev.adapters import Item, PlanResult  # noqa: E402
from tools.jev.common import git  # noqa: E402

TARGET, NWO = "SCHEMA", "bamr87/SCHEMA"   # a real registry entry; its "upstream" is a local fixture
NOT_LOGGED_IN = {"type": "result", "subtype": "success", "is_error": True, "total_cost_usd": 0, "modelUsage": {},
                 "num_turns": 1, "terminal_reason": "api_error", "result": "Not logged in · Please run /login",
                 "session_id": "s-0", "permission_denials": []}

STUB_CLAUDE = r'''#!__PY__
"""A stand-in for `claude` that can never reach a model."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
argv = sys.argv[1:]
def note(name, obj):
    with open(os.path.join(HERE, name), "a") as fh:
        fh.write(json.dumps(obj) + "\n")
if argv[:1] == ["--version"]:
    v = open(os.path.join(HERE, "version")).read().strip() if os.path.exists(os.path.join(HERE, "version")) else "2.1.308"
    print(v + " (Claude Code)"); sys.exit(0)
if argv[:2] == ["auth", "status"]:
    logged = os.environ.get("STUB_LOGGED_IN") == "1" or any(
        os.environ.get(n) for n in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"))
    print(json.dumps({"loggedIn": logged, "authMethod": "claude.ai"})); sys.exit(0)
note("argv.jsonl", argv)
note("cwd.jsonl", os.getcwd())
def debug(line):
    if "--debug-file" in argv:
        with open(argv[argv.index("--debug-file") + 1], "a") as fh:
            fh.write(line + "\n")
prompt = sys.stdin.read() if not sys.stdin.isatty() else ""
if not prompt:
    sys.stderr.write("Error: Input must be provided either through stdin or as a prompt argument when using --print\n")
    sys.exit(1)
def emit(o):
    sys.stdout.write(json.dumps(o) + "\n"); sys.stdout.flush()
if prompt == "Reply with the single word ok.\n":   # the credential-free isolation probe
    note("probed.jsonl", {"isolated": "--restricted" in argv})
    if "--restricted" in argv:
        debug("[DEBUG] Applying permission update: Adding 5 allow rule(s) to destination 'flagSettings'")
        debug("[DEBUG] $.fs.ancestors (cc-plugin-agents-md): project memory is off")
        emit({"type": "system", "subtype": "init", "tools": argv[argv.index("--tools") + 1].split(","),
              "mcp_servers": [], "permissionMode": "dontAsk", "output_style": "default", "skills": []})
    else:
        emit({"type": "system", "subtype": "hook_started", "hook_event": "SessionStart"})
        emit({"type": "system", "subtype": "init", "tools": ["Task", "Bash", "Read", "Edit"],
              "mcp_servers": [{"name": "jev-probe", "status": "failed", "source": "project"}],
              "permissionMode": "default", "output_style": "Explanatory", "skills": ["jev-probe"]})
    emit(json.loads(__NOT_LOGGED_IN__))
    sys.exit(1)
note("PROMPTED", {"argv": argv})   # a real prompt: a live CLI would have spent here
sys.exit(99)
'''

STUB_GH = r'''#!__PY__
import json, os, subprocess, sys
argv = sys.argv[1:]
with open(os.environ["STUB_GH_LOG"], "a") as fh:
    fh.write(json.dumps(argv) + "\n")
fixtures = json.loads(os.environ.get("STUB_GH_FIXTURES") or "{}")
def head(nwo):
    return subprocess.run(["git", "-C", fixtures[nwo], "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
if argv[:2] == ["repo", "clone"]:
    nwo, dest = argv[2], argv[3]
    rest = argv[argv.index("--") + 1:] if "--" in argv else []
    sys.exit(subprocess.run(["git", "clone", "--quiet", *rest, fixtures[nwo], dest]).returncode)
if argv[:1] == ["api"] and "/commits/" in argv[1]:
    nwo = argv[1].split("repos/", 1)[1].split("/commits/", 1)[0]
    if os.environ.get("STUB_GH_COMMITS_ERROR"):
        sys.stderr.write("gh: " + os.environ["STUB_GH_COMMITS_ERROR"] + "\n"); sys.exit(1)
    if os.environ.get("STUB_GH_HEAD_MOVED"):
        print("0" * 40); sys.exit(0)
    print(head(nwo)); sys.exit(0)
if argv[:1] == ["api"] and argv[1].startswith("repos/") and argv[1].count("/") == 2:
    if os.environ.get("STUB_GH_REPO_UNREADABLE"):
        sys.stderr.write("gh: Not Found (HTTP 404)\n"); sys.exit(1)
    print(argv[1][len("repos/"):]); sys.exit(0)
if argv[:2] == ["repo", "view"]:
    print(json.dumps({"hasIssuesEnabled": True})); sys.exit(0)
if argv[:2] == ["issue", "list"]:
    print(os.environ.get("STUB_GH_ISSUES") or "[]"); sys.exit(0)
if argv[:2] == ["variable", "get"]:
    if os.environ.get("STUB_GH_VAR_ERROR"):
        sys.stderr.write("HTTP 403: Resource not accessible by integration\n"); sys.exit(1)
    value = os.environ.get("STUB_GH_VAR_" + argv[2])
    if value is None:
        sys.stderr.write(f"variable {argv[2]} was not found\n"); sys.exit(1)
    print(value); sys.exit(0)
sys.stderr.write("stub gh: unexpected " + " ".join(argv) + "\n")
sys.exit(3)
'''

#: a wrapper for tools/dash-gen: the real one, except that it can corrupt the
#: planner's first prompt by one byte (JEV_TEST_MUTATE_PROMPT), make
#: `ai-run --dry-run` refuse (JEV_TEST_DRY_REFUSES) and log the environment's
#: NAMES each subcommand received (JEV_TEST_ENV_LOG)
DASH_GEN_WRAPPER = r'''#!__PY__
import json, os, subprocess, sys
if os.environ.get("JEV_TEST_ENV_LOG"):
    with open(os.environ["JEV_TEST_ENV_LOG"], "a") as fh:
        fh.write(json.dumps({"sub": sys.argv[1], "env": sorted(os.environ)}) + "\n")
if sys.argv[1:3] == ["ai-run", "--dry-run"] and os.environ.get("JEV_TEST_DRY_REFUSES"):
    sys.stderr.write("ai-run: --claude-bin is not executable\n"); sys.exit(2)
res = subprocess.run(["__REAL__", *sys.argv[1:]], capture_output=True, text=True, input=sys.stdin.read())
out = res.stdout
if sys.argv[1:2] == ["scout"] and os.environ.get("JEV_TEST_MUTATE_PROMPT") and out.strip():
    lines = out.strip().splitlines()
    plan = json.loads(lines[-1])
    plan["include"][0]["prompt"] += " "
    out = "\n".join([*lines[:-1], json.dumps(plan)]) + "\n"
sys.stdout.write(out); sys.stderr.write(res.stderr)
sys.exit(res.returncode)
'''


def _script(path: Path, body: str) -> Path:
    path.write_text(body.replace("__PY__", sys.executable).replace("__NOT_LOGGED_IN__", repr(json.dumps(NOT_LOGGED_IN)))
                    .replace("__REAL__", str(HUB / "tools" / "dash-gen")), encoding="utf-8")
    path.chmod(0o755)
    return path


def fixture_repo(extra: dict[str, str] | None = None) -> Path:
    repo = Path(tempfile.mkdtemp(prefix="jev-loop-fixture-"))
    cfg = ["-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]
    assert git(["init", "-q", "-b", "main"], cwd=repo).ok
    (repo / "README.md").write_text("# SCHEMA fixture\n", encoding="utf-8")
    for rel, body in (extra or {}).items():
        (repo / rel).write_text(body, encoding="utf-8")
    assert git(["add", "-A"], cwd=repo).ok
    assert git([*cfg, "commit", "-q", "-m", "fixture"], cwd=repo).ok
    return repo


FIXTURE = fixture_repo()


class Box:
    """One test's world: stub bin dir, run and work roots, a temp ledger."""

    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="jev-loop-test-"))
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.claude = _script(self.bin / "claude", STUB_CLAUDE)
        _script(self.bin / "gh", STUB_GH)
        self.dash_gen = _script(self.root / "dash-gen", DASH_GEN_WRAPPER)
        self.runs, self.work = self.root / "runs", self.root / "work"
        (self.root / "empty.env").write_text("", encoding="utf-8")
        self.gh_log = self.root / "gh.log"

    def env(self) -> dict[str, str]:
        return {"PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}", "JEV_RUNS_DIR": str(self.runs),
                "JEV_WORK_ROOT": str(self.work), "JEV_DOTENV": str(self.root / "empty.env"),
                "DASH_AI_LEDGER": str(self.root / "ledger.json"), "STUB_GH_LOG": str(self.gh_log),
                "STUB_GH_FIXTURES": json.dumps({NWO: str(FIXTURE)}), "CLAUDE_CODE_OAUTH_TOKEN": "fake-oauth-token-1234"}

    def gh_calls(self) -> list[list[str]]:
        return [json.loads(x) for x in self.gh_log.read_text().splitlines()] if self.gh_log.exists() else []

    def claude_cwds(self) -> list[str]:
        f = self.bin / "cwd.jsonl"
        return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []

    def claude_calls(self) -> list[list[str]]:
        f = self.bin / "argv.jsonl"
        return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []

    def prompted(self) -> bool:
        return (self.bin / "PROMPTED").exists()

    def run_dirs(self) -> list[Path]:
        return sorted(p for p in self.runs.glob("*") if (p / "run.json").is_file()) if self.runs.exists() else []

    def latest(self) -> Path:
        """The newest run (the LATEST pointer: run ids made in one second sort by their random suffix)."""
        return self.runs / (self.runs / "LATEST").read_text().strip()

    def last(self) -> dict:
        return json.loads((self.latest() / "run.json").read_text())

    def seed_probe(self, ok: bool = True, posture: str = "sandbox") -> None:
        spec = L.load_step("repo-scout")
        L.store(".probe.json", L.cache_key((2, 1, 308), spec, H.Posture(posture)),
                {"ok": ok, "problems": [] if ok else ["isolated: a project hook ran"], "at": L.iso()})


@contextlib.contextmanager
def world(box: Box, *, sandbox: bool = True, fleet_edit=None, **extra: str):
    """Point the engine at the box: env, the dash-gen wrapper, the sandbox check
    and (optionally) an edited _data/fleet.yml. Everything is restored after."""
    saved_env = dict(os.environ)
    saved = (L.DASH_GEN, L.sandbox_available, L.load_fleet)
    for k in (*H.CREDENTIAL_ENV.values(), *H.AUTH_OVERRIDE_ENV, "CLAUDE_AUTH_ORDER"):
        os.environ.pop(k, None)
    os.environ.update({**box.env(), **extra})
    L.DASH_GEN = box.dash_gen
    L.sandbox_available = lambda: sandbox
    if fleet_edit is not None:
        real = S.load_fleet()

        def edited() -> dict:
            f = copy.deepcopy(real)
            fleet_edit(f)
            return f
        L.load_fleet = edited
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved_env)
        L.DASH_GEN, L.sandbox_available, L.load_fleet = saved


def jev(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = jev_main(["loop", *argv])
    return code, out.getvalue(), err.getvalue()


def no_writes(box: Box) -> None:
    writes = [c for c in box.gh_calls() if c[:2] in (["issue", "create"], ["label", "create"], ["issue", "edit"],
                                                     ["pr", "merge"], ["variable", "set"])
              or (c[:1] == ["api"] and common._api_method(c) != "GET")]
    assert not writes, writes
    assert not box.prompted(), "a real prompt reached claude"


def hub_status() -> str:
    return git(["status", "--porcelain=v1"], cwd=HUB).out


# --------------------------------------------------------------------------- #
# refusals before anything runs
# --------------------------------------------------------------------------- #
def test_list_shows_the_scout_step():
    code, out, _ = jev("list", "--json")
    rows = json.loads(out)
    assert code == 0 and [r["step"] for r in rows] == ["repo-scout/scout"]
    assert rows[0]["publish_tier"] == "high" and rows[0]["switch"]["variable"] == "REPO_SCOUT_ENABLED"
    assert rows[0]["cap_usd"] == 8.0 and rows[0]["on_budget_hit"] == "discard"


def test_a_run_without_rehearse_refuses_until_live_attempts_land():
    box = Box()
    with world(box):
        code, _, err = jev("run", "repo-scout", "--target", TARGET)
    assert code == 2 and "next PR" in err and "--rehearse" in err
    assert not box.run_dirs() and not box.gh_calls() and not box.claude_calls()


def test_apply_with_scheduled_or_rehearse_and_reduced_with_scheduled_are_refused():
    box = Box()
    with world(box):
        for argv, needle in ((["--rehearse", "--apply", "--scheduled"], "13.7"),
                             (["--rehearse", "--apply"], "files nothing"),
                             (["--rehearse", "--posture", "reduced", "--scheduled"], "never scheduled"),
                             (["--rehearse", "--plan-file", "x.json"], "go together"),
                             (["--rehearse", "--target", "../x"], "registry name")):
            code, _, err = jev("run", "repo-scout", *argv)
            assert code == 2 and needle in err, (argv, err)
    assert not box.run_dirs() and not box.gh_calls()


def test_a_step_with_no_local_block_is_refused():
    box = Box()
    root = Path(tempfile.mkdtemp()) / "steps"
    shutil.copytree(S.SPEC_ROOT, root)
    p = root / "repo-scout" / "scout.yml"
    data = yaml.safe_load(p.read_text())
    data.pop("local")
    p.write_text(yaml.safe_dump(data, sort_keys=False))
    spec = S.load_spec("repo-scout", "scout", root=root)
    assert spec.local is None
    saved = L.load_spec
    L.load_spec = lambda loop, step, fleet=None: S.load_spec(loop, step, root=root, fleet=fleet)
    try:
        with world(box):
            code, _, err = jev("run", "repo-scout", "scout", "--rehearse")
    finally:
        L.load_spec = saved
    assert code == 2 and "no local runner" in err


def test_an_alias_model_is_refused_before_anything_runs():
    box = Box()
    with world(box, fleet_edit=lambda f: f["scout"].update(model="sonnet")):
        code, _, err = jev("run", "repo-scout", "--rehearse", "--target", TARGET)
    assert code == 2 and "13.3" in err and not box.gh_calls()


# --------------------------------------------------------------------------- #
# the rehearsal, end to end
# --------------------------------------------------------------------------- #
def test_a_rehearsal_does_everything_up_to_the_model_call_at_zero_cost():
    box = Box()
    before = hub_status()
    with world(box):
        box.seed_probe()
        code, out, err = jev("run", "repo-scout", "--rehearse", "--target", TARGET)
    assert code == 0, err
    rec = box.last()
    assert out.strip() == f"run: {box.latest()}"
    assert rec["schema"] == L.RUN_SCHEMA and rec["mode"] == "rehearse" and rec["status"] == "rehearsed"
    assert rec["posture"]["name"] == "sandbox" and rec["posture"]["network"] == []
    assert rec["tier"] == {"name": "t1", "model": "claude-sonnet-5-5", "max_turns": 40, "cap_usd": 8.0}
    assert rec["publish"] == {"risk": "publish", "tier": "high"}
    assert rec["host"]["auth"] == {"method": "oauth", "source": "env"} and rec["host"]["probe"] == "ok"
    assert any("canary" in n for n in rec["notes"]), "the missing canary is reported, not hidden"
    [item] = rec["items"]
    assert item["key"] == NWO and item["status"] == "rehearsed" and item["ai_run_dry"] == 0, item
    d = box.latest() / "items" / "bamr87__SCHEMA"
    spec = L.load_step("repo-scout")
    plan = json.loads((box.latest() / "plan" / "plan.json").read_text())
    row = plan["include"][0]
    assert (d / "prompt.txt").read_text() == S.render_prompt(spec, S.values_from(spec, row)) == row["prompt"]
    assert json.loads((d / "settings.json").read_text()) == H.settings_doc(H.Posture("sandbox"))
    argv = json.loads((d / "argv.json").read_text())
    flags = argv["claude_flags"]
    assert flags[flags.index("--session-id") + 1] == item["attempt_id"]
    assert flags[flags.index("--settings") + 1] == str(d / "settings.json")
    live = argv["ai_run"]
    for pair in (("--call-site", "repo-scout.yml:scout"), ("--repo", NWO), ("--usage-limit", "skip"),
                 ("--meta", "origin=local"), ("--meta", f"attempt_id={item['attempt_id']}")):
        assert any(live[i:i + 2] == list(pair) for i in range(len(live))), pair
    assert "--isolate" in live and "--prompt-file" in live and live[live.index("--") + 1:] == flags
    keys = json.loads((d / "env-keys.json").read_text())
    assert "CLAUDE_CODE_OAUTH_TOKEN" in keys and not {"GH_TOKEN", "GITHUB_TOKEN", "FLEET_TOKEN", "PYTHONPATH",
                                                      "SSH_AUTH_SOCK", "ANTHROPIC_API_KEY"} & set(keys)
    assert "fake-oauth-token" not in json.dumps([argv, keys, rec]), "a value never reaches the run record"
    said = (d / "ai-run-dry.txt").read_text()
    assert "cap: $8.00 (repo-scout.yml:scout)" in said and "auth: oauth (env) · isolated environment" in said, said
    assert " -p --output-format stream-json --verbose --max-budget-usd 8 " in said and "fake-oauth" not in said
    rows = [json.loads(x) for x in (box.latest() / "attempts.jsonl").read_text().splitlines()]
    assert [r["decision"] for r in rows] == ["rehearsed"] and rows[0]["cost_source"] == "no-spend"
    assert rows[0]["schema"] == L.ATTEMPT_SCHEMA and rows[0]["reuse_key"] and rows[0]["head_sha"]
    assert not list(box.work.glob("*/*")), "the workspace is destroyed after its item"
    assert not (d / "outcome.json").exists() and not (d / "result.json").exists(), "a rehearsal is no attempt"
    assert box.runs.stat().st_mode & 0o777 == 0o700 and box.latest().stat().st_mode & 0o777 == 0o700
    clones = [c for c in box.gh_calls() if c[:2] == ["repo", "clone"]]
    assert len(clones) == 1 and "core.symlinks=false" in clones[0] and "--no-upstream" in clones[0]
    preflights = [c for c in box.claude_calls() if "-p" in c]
    assert len(preflights) == 1 and "--restricted" in preflights[0], "one $0 flag preflight"
    no_writes(box)
    assert hub_status() == before, "a local run changes nothing the hub tracks"
    assert (box.runs / "LATEST").read_text().strip() == rec["run_id"]


def test_the_rehearsal_runs_ai_run_dry_without_the_prompt_or_the_attempts_artefacts():
    live = ["ai-run", "--stream", "--prompt-file", "/x/prompt.txt", "--cwd", "/c", "--trace", "/x/t.jsonl",
            "--result-file", "/x/r.json", "--outcome-file", "/x/o.json", "--", "--prompt-file", "kept"]
    assert L.rehearsal_argv(live) == ["ai-run", "--dry-run", "--stream", "--cwd", "/c", "--", "--prompt-file", "kept"]


def test_ai_run_sees_one_claude_credential_and_no_github_secret_and_the_planner_none():
    box = Box()
    log = box.root / "env.jsonl"
    with world(box, GH_TOKEN="ghp_fake_000000", FLEET_TOKEN="fleet_fake_000000", ANTHROPIC_AUTH_TOKEN="fake-auth",
               SSH_AUTH_SOCK=str(box.root / "agent.sock"), JEV_TEST_ENV_LOG=str(log)):
        code, _, err = jev("run", "repo-scout", "--rehearse", "--target", TARGET)
    assert code == 0, err
    rows = [json.loads(x) for x in log.read_text().splitlines()]
    [ai] = [r["env"] for r in rows if r["sub"] == "ai-run"]
    creds = [n for n in H.CREDENTIAL_ENV.values() if n in ai]
    assert creds == ["CLAUDE_CODE_OAUTH_TOKEN"], creds
    assert not (set(H.SECRET_ENV) - set(creds)) & set(ai), sorted((set(H.SECRET_ENV) - set(creds)) & set(ai))
    assert "SSH_AUTH_SOCK" not in ai and not set(H.AUTH_OVERRIDE_ENV) & set(ai)
    planner = [r["env"] for r in rows if r["sub"] == "scout"]
    assert planner and all(not ({*H.CREDENTIAL_ENV.values(), *H.AUTH_OVERRIDE_ENV} & set(e)) for e in planner)


def test_keep_workspace_leaves_a_hardened_clone():
    box = Box()
    with world(box):
        code, _, err = jev("run", "repo-scout", "--rehearse", "--target", TARGET, "--keep-workspace")
    assert code == 0, err
    kept = Path(box.last()["items"][0]["kept_workspace"])
    assert kept.is_dir() and kept.is_relative_to(box.work)
    assert git(["config", "--get", "remote.origin.pushurl"], cwd=kept).out.strip() == "no-push://disabled"
    assert (kept / ".scout" / "scout-workorder-SCHEMA.md").is_file(), "the brief is placed in the clone"


def test_offline_rehearsal_reads_nothing_and_clones_nothing():
    box = Box()
    with world(box):
        code, _, err = jev("run", "repo-scout", "--rehearse", "--target", TARGET, "--offline")
    assert code == 0, err
    assert box.gh_calls() == [], "offline: no gh call at all"
    item = box.last()["items"][0]
    assert item["status"] == "rehearsed" and "offline" in item["reason"]
    assert (box.latest() / "items" / "bamr87__SCHEMA" / "prompt.txt").is_file()


def test_the_reduced_posture_runs_without_a_sandbox_and_without_bash():
    box = Box()
    with world(box, sandbox=False):
        code, _, _ = jev("run", "repo-scout", "--rehearse", "--target", TARGET, "--offline")
        assert code == 4, "the sandbox posture refuses a host with no sandbox"
        code, _, err = jev("run", "repo-scout", "--rehearse", "--target", TARGET, "--offline", "--posture", "reduced")
    assert code == 0, err
    d = box.latest() / "items" / "bamr87__SCHEMA"
    flags = json.loads((d / "argv.json").read_text())["claude_flags"]
    assert "Bash" not in flags[flags.index("--tools") + 1] and "Bash(" not in flags[flags.index("--allowedTools") + 1]
    assert "sandbox" not in json.loads((d / "settings.json").read_text())


def test_a_planner_prompt_one_byte_off_is_refused():
    box = Box()
    with world(box, JEV_TEST_MUTATE_PROMPT="1"):
        code, _, _ = jev("run", "repo-scout", "--rehearse", "--target", TARGET)
    rec = box.last()
    assert code == 2 and rec["status"] == "refused" and any("nobody reviewed" in n for n in rec["notes"]), rec["notes"]
    assert not [c for c in box.gh_calls() if c[:2] == ["repo", "clone"]]


def test_an_ineligible_target_exits_one_with_the_planners_reason():
    box = Box()
    with world(box):
        code, _, _ = jev("run", "repo-scout", "--rehearse", "--target", "no-such-repo")
    rec = box.last()
    assert code == 1 and rec["status"] == "empty"
    assert any("not in the registry" in n for n in rec["notes"]), rec["notes"]
    assert not box.claude_calls() or all("-p" not in c or "--restricted" in c for c in box.claude_calls())
    no_writes(box)


def test_plan_file_rehearses_one_saved_row_with_its_brief():
    box = Box()
    saved = box.root / "saved"
    with world(box):
        res = L.dash_gen(["scout", "--offline", "--target", TARGET, "--out-dir", str(saved)])
        (saved / "plan.json").write_text(res.out.strip().splitlines()[-1])
        code, _, err = jev("run", "repo-scout", "--rehearse", "--plan-file", str(saved / "plan.json"), "--item",
                           TARGET, "--keep-workspace")
    assert code == 0, err
    item = box.last()["items"][0]
    assert item["status"] == "rehearsed", item
    assert (Path(item["kept_workspace"]) / ".scout" / "scout-workorder-SCHEMA.md").is_file()
    no_writes(box)


def test_plan_file_refuses_a_brief_that_is_not_a_bare_name_and_copies_nothing():
    box = Box()
    secret = box.root / "outside" / "host-secret.txt"
    secret.parent.mkdir()
    secret.write_text("not for the clone\n")
    saved = box.root / "saved"
    with world(box):
        res = L.dash_gen(["scout", "--offline", "--target", TARGET, "--out-dir", str(saved)])
        plan = json.loads(res.out.strip().splitlines()[-1])
        (saved / "briefs").mkdir()
        shutil.copy(saved / plan["include"][0]["brief"], saved / "briefs" / "b.md")
        for bad in ("briefs/b.md", str(secret), "../outside/host-secret.txt"):
            row = {**plan["include"][0], "brief": bad}
            row.pop("prompt")
            (saved / "plan.json").write_text(json.dumps({**plan, "include": [row]}))
            code, _, err = jev("run", "repo-scout", "--rehearse", "--plan-file", str(saved / "plan.json"),
                               "--item", TARGET, "--keep-workspace")
            assert code == 2 and "bare file name" in " ".join(box.last()["notes"]), (bad, code, box.last()["notes"])
    assert not list(box.work.rglob("host-secret.txt")) and not list(box.runs.rglob("host-secret.txt")), \
        "the host file was copied nowhere"
    assert not [c for c in box.gh_calls() if c[:2] == ["repo", "clone"]]


def test_a_malformed_or_missing_plan_file_is_refused_and_the_record_ends():
    box = Box()
    saved = box.root / "saved"
    saved.mkdir()
    with world(box):
        for body, needle in (({"include": ["SCHEMA"]}, "list of objects"), ({"include": {"a": 1}}, "list of objects"),
                             ({"include": "SCHEMA"}, "list of objects"), ([1], "not a JSON object")):
            (saved / "plan.json").write_text(json.dumps(body))
            code, _, _ = jev("run", "repo-scout", "--rehearse", "--offline", "--plan-file", str(saved / "plan.json"),
                             "--item", TARGET)
            rec = box.last()
            assert code == 2 and rec["status"] == "refused" and needle in " ".join(rec["notes"]), (body, rec)
        code, _, _ = jev("run", "repo-scout", "--rehearse", "--offline", "--plan-file", str(saved / "nope.json"),
                         "--item", TARGET)
        assert code == 2 and "no such file" in " ".join(box.last()["notes"]), box.last()["notes"]
    assert all(json.loads((d / "run.json").read_text())["status"] != "running" for d in box.run_dirs())


def test_a_relative_plan_file_is_the_callers_not_the_hubs():
    box = Box()
    saved = box.root / "saved"
    with world(box):
        res = L.dash_gen(["scout", "--offline", "--target", TARGET, "--out-dir", str(saved)])
        (saved / "plan.json").write_text(res.out.strip().splitlines()[-1])
    with world(box, JEV_CALLER_CWD=str(saved)):   # what tools/dash loop sets before its cd to the hub
        code, _, err = jev("run", "repo-scout", "--rehearse", "--offline", "--plan-file", "plan.json",
                           "--item", TARGET)
    assert code == 0 and box.last()["status"] == "rehearsed", (err, box.last()["notes"])
    assert 'JEV_CALLER_CWD="${caller}"' in (HUB / "tools" / "dash").read_text()


def test_an_unexpected_error_still_ends_the_record_and_an_oserror_fails_it():
    box = Box()
    real = L.obtain_plan
    for exc, code_want in ((PermissionError("the brief is unreadable"), 1), (ValueError("a bug"), None)):
        def boom(ctx, exc=exc):
            raise exc
        L.obtain_plan = boom
        try:
            with world(box):
                try:
                    code = jev("run", "repo-scout", "--rehearse", "--offline", "--target", TARGET)[0]
                except ValueError:
                    code = None
        finally:
            L.obtain_plan = real
        rec = box.last()
        assert code == code_want and rec["status"] == "failed" and rec["exit_code"] == 1, (exc, code, rec)
        assert type(exc).__name__ in " ".join(rec["notes"]), rec["notes"]


def test_a_target_committing_the_brief_directory_fails_the_item_not_the_run():
    box = Box()
    planted = fixture_repo({".scout": "committed by the target\n"})
    with world(box, STUB_GH_FIXTURES=json.dumps({NWO: str(planted)})):
        code, _, err = jev("run", "repo-scout", "--rehearse", "--target", TARGET)
    rec = box.last()
    assert code == 1 and rec["status"] == "rehearsed" and rec["exit_code"] == 1, (code, rec["status"], err)
    assert rec["items"][0]["status"] == "failed" and "commits .scout/" in rec["items"][0]["reason"]
    assert not list(box.work.glob("*/*")), "the refused clone is gone"


def test_backpressure_from_the_live_issue_list_skips_the_target():
    box = Box()
    marker = f'<!-- repo-scout key="{NWO}" -->'
    issues = [{"number": n, "title": f"scout issue {n}", "url": "", "labels": [{"name": "ai-scout"}],
               "body": marker} for n in (1, 2, 3)]
    with world(box, STUB_GH_ISSUES=json.dumps(issues)):
        code, _, _ = jev("run", "repo-scout", "--rehearse", "--target", TARGET)
    assert code == 1 and any("still open" in n for n in box.last()["notes"])
    rows = [json.loads(x) for x in (box.latest() / "attempts.jsonl").read_text().splitlines()]
    assert rows and rows[0]["decision"] == "planned-skip"
    assert rows[0]["item"] == NWO and rows[0]["name"] == TARGET, "one identity per repo in the attempts log"


# --------------------------------------------------------------------------- #
# the kill switch
# --------------------------------------------------------------------------- #
def test_the_fleet_switch_off_exits_zero_disabled():
    box = Box()
    with world(box, fleet_edit=lambda f: f["scout"].update(enabled=False)):
        code, _, _ = jev("run", "repo-scout", "--rehearse", "--target", TARGET)
    assert code == 0 and box.last()["status"] == "disabled" and not box.gh_calls()


def test_scheduled_reads_the_variable_and_manual_says_it_bypasses_it():
    box = Box()
    with world(box):
        code, _, _ = jev("run", "repo-scout", "--rehearse", "--scheduled", "--target", TARGET, "--offline")
        assert code == 0 and box.last()["status"] == "disabled" and "switched off" in box.last()["notes"][0]
    with world(box, STUB_GH_VAR_ERROR="1"):
        code, _, _ = jev("run", "repo-scout", "--rehearse", "--scheduled", "--target", TARGET, "--offline")
        assert code == 2 and "cannot read" in box.last()["notes"][0]
    for value in ("true", "True"):   # GitHub compares strings ignoring case
        with world(box, STUB_GH_VAR_REPO_SCOUT_ENABLED=value):
            code, _, _ = jev("run", "repo-scout", "--rehearse", "--scheduled", "--target", TARGET, "--offline")
            assert code == 0 and box.last()["status"] == "rehearsed", value
    with world(box):
        code, _, err = jev("run", "repo-scout", "--rehearse", "--target", TARGET, "--offline")
    assert code == 0 and "bypasses vars.REPO_SCOUT_ENABLED" in err
    gets = [c for c in box.gh_calls() if c[:2] == ["variable", "get"]]
    assert len(gets) == 4 and all(c[2] == "REPO_SCOUT_ENABLED" and "bamr87/bamr87" in c for c in gets)


def test_a_default_on_switch_reads_any_case_of_false_as_off():
    box = Box()
    spec = L.load_step("repo-scout")
    on = S.Switch(config=spec.local.switch.config, variable="REPO_SCOUT_ENABLED", default="on")
    spec_on = dataclasses.replace(spec, local=dataclasses.replace(spec.local, switch=on))
    with world(box):
        for value, stops in (("FALSE", True), ("False", True), ("false", True), ("anything", False)):
            os.environ["STUB_GH_VAR_REPO_SCOUT_ENABLED"] = value
            ctx = L.RunContext(spec=spec_on, adapter=None, fleet=S.load_fleet(), opts=L.Options(scheduled=True),
                               plan_dir=box.root / "plan", history=L.History(box.runs))
            stop = L.gates(ctx)
            assert (stop is not None and stop[0] == 0 and "switched off" in stop[1]) == stops, (value, stop)


def test_a_step_with_no_switch_never_runs_scheduled():
    box = Box()
    spec = L.load_step("repo-scout")
    bare = dataclasses.replace(spec, local=dataclasses.replace(spec.local, switch=None))
    with world(box):
        for scheduled, want in ((True, 2), (False, None)):
            ctx = L.RunContext(spec=bare, adapter=None, fleet=S.load_fleet(), opts=L.Options(scheduled=scheduled),
                               plan_dir=box.root / "plan", history=L.History(box.runs))
            stop = L.gates(ctx)
            assert (stop[0] if stop else None) == want, (scheduled, stop)
            assert scheduled is False or "no local.switch" in stop[1]
    assert not box.gh_calls(), "no switch to read: nothing is asked of GitHub"


def test_a_default_on_switch_reads_not_found_as_unset_only_when_the_hub_is_readable():
    box = Box()
    spec = L.load_step("repo-scout")
    on = S.Switch(config=spec.local.switch.config, variable="REPO_SCOUT_ENABLED", default="on")
    spec_on = dataclasses.replace(spec, local=dataclasses.replace(spec.local, switch=on))
    for extra, want in (({}, None), ({"STUB_GH_REPO_UNREADABLE": "1"}, 2)):
        with world(box, **extra):
            ctx = L.RunContext(spec=spec_on, adapter=None, fleet=S.load_fleet(), opts=L.Options(scheduled=True),
                               plan_dir=box.root / "plan", history=L.History(box.runs))
            stop = L.gates(ctx)
        assert (stop[0] if stop else None) == want, (extra, stop)
    assert ["api", "repos/bamr87/bamr87", "--jq", ".full_name"] in box.gh_calls()


def test_the_engine_splits_the_publish_directory_by_phase():
    box = Box()
    spec = L.load_step("repo-scout")
    rd = L.RunDir(box.root / "runs" / "r1")
    ctx = L.RunContext(spec=spec, adapter=None, fleet={}, opts=L.Options(), plan_dir=rd.path / "plan",
                       history=L.History(box.runs), run=rd)
    item = Item(key=NWO, name=TARGET, nwo=NWO, branch="main", row={}, brief=None)
    d = rd.path / "items" / "bamr87__SCHEMA"
    assert ctx.bodies_dir(item, apply=False) == d / "bodies" and ctx.bodies_dir(item, apply=True) == d / "filed"
    dry, wet = L.item_values(ctx, item), L.item_values(ctx, item, apply=True)
    assert dry["bodies_dir"] == str(d / "bodies") and wet["bodies_dir"] == str(d / "filed")
    argv = S.render_argv(spec.local.publish.argv, {**wet, "validated": str(d / "v.json")})
    assert argv[argv.index("--bodies-dir") + 1] == str(d / "filed"), "the apply never writes the reviewed bodies"


def test_the_rehearsal_preflight_runs_outside_the_hub_and_leaves_nothing():
    box = Box()
    with world(box):
        code, _, err = jev("run", "repo-scout", "--rehearse", "--target", TARGET)
    assert code == 0, err
    cwds = [Path(c) for c in box.claude_cwds()]
    assert cwds and not [c for c in cwds if c.resolve().is_relative_to(HUB.resolve())], cwds
    assert all(c.resolve().is_relative_to(box.work.resolve()) and not c.exists() for c in cwds), cwds


# --------------------------------------------------------------------------- #
# tier 0
# --------------------------------------------------------------------------- #
def _seed_completed(box: Box, *, published: bool) -> None:
    first = [json.loads(x) for x in (box.latest() / "attempts.jsonl").read_text().splitlines()][0]
    d = box.runs / "20000101T000000Z-seed"
    d.mkdir(parents=True, exist_ok=True)
    row = {**first, "decision": "attempt", "outcome": "ok", "validated_sha256": "e" * 64, "ts": L.iso(),
           "run_id": d.name}
    rows = [row] + ([{**row, "decision": "publish-apply", "published": True}] if published else [])
    (d / "attempts.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_tier0_reuses_an_identical_completed_attempt_and_skips_a_published_one():
    box = Box()
    with world(box):
        assert jev("run", "repo-scout", "--rehearse", "--target", TARGET)[0] == 0
        _seed_completed(box, published=False)
        code, _, _ = jev("run", "repo-scout", "--rehearse", "--target", TARGET)
        item = box.last()["items"][0]
        assert code == 0 and item["status"] == "reused" and "20000101T000000Z-seed" in item["reason"], item
        _seed_completed(box, published=True)
        code, _, _ = jev("run", "repo-scout", "--rehearse", "--target", TARGET)
        assert box.last()["items"][0]["status"] == "skipped"
        code, _, _ = jev("run", "repo-scout", "--rehearse", "--target", TARGET, "--fresh")
        assert box.last()["items"][0]["status"] == "rehearsed", "--fresh bypasses tier 0"
    clones = [c for c in box.gh_calls() if c[:2] == ["repo", "clone"]]
    assert len(clones) == 2, "neither the reuse nor the skip cloned"


# --------------------------------------------------------------------------- #
# the host
# --------------------------------------------------------------------------- #
def test_no_claude_exits_127_and_an_old_cli_exits_4():
    box = Box()
    with world(box):
        code, _, _ = jev("run", "repo-scout", "--rehearse", "--target", TARGET, "--claude-bin", "no-such-claude")
        assert code == 127
        (box.bin / "version").write_text("2.1.200")
        code, _, _ = jev("run", "repo-scout", "--rehearse", "--target", TARGET)
        assert code == 4 and "older than" in " ".join(box.last()["notes"])


def test_a_failed_cached_probe_exits_4_and_a_missing_one_is_a_note():
    box = Box()
    with world(box):
        code, _, _ = jev("run", "repo-scout", "--rehearse", "--target", TARGET, "--offline")
        assert code == 0 and box.last()["host"]["probe"] == "absent"
        assert any("isolation probe" in n for n in box.last()["notes"])
        box.seed_probe(ok=False)
        code, _, _ = jev("run", "repo-scout", "--rehearse", "--target", TARGET, "--offline")
    assert code == 4 and "a project hook ran" in " ".join(box.last()["notes"])


def test_no_credential_is_reported_and_the_rehearsal_still_runs():
    box = Box()
    with world(box):
        os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN")
        code, _, _ = jev("run", "repo-scout", "--rehearse", "--target", TARGET)
    rec = box.last()
    assert code == 0 and rec["host"]["auth"] is None and any("exits 3" in n for n in rec["notes"]), rec["notes"]
    assert rec["items"][0]["ai_run_dry"] == 3 and "credential" in rec["items"][0]["reason"]
    no_writes(box)


def test_a_held_lock_exits_2():
    box = Box()
    with world(box):
        locks = box.runs / ".locks"
        locks.mkdir(parents=True)
        with (locks / "repo-scout-scout.lock").open("w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            code, _, err = jev("run", "repo-scout", "--rehearse", "--target", TARGET, "--offline")
    assert code == 2 and "already running" in err and not box.run_dirs()


def test_the_branch_moving_under_the_plan_reruns_tier0_on_the_clone():
    box = Box()
    with world(box, STUB_GH_HEAD_MOVED="1"):
        code, _, err = jev("run", "repo-scout", "--rehearse", "--target", TARGET)
    assert code == 0, err
    row = [json.loads(x) for x in (box.latest() / "attempts.jsonl").read_text().splitlines()][-1]
    assert row["head_sha"] == git(["rev-parse", "HEAD"], cwd=FIXTURE).out.strip(), "the cloned HEAD wins"


def test_the_second_tier0_on_the_cloned_head_can_reuse():
    box = Box()
    with world(box):
        assert jev("run", "repo-scout", "--rehearse", "--target", TARGET)[0] == 0   # the real HEAD's reuse key
        _seed_completed(box, published=False)
    with world(box, STUB_GH_HEAD_MOVED="1"):
        code, _, err = jev("run", "repo-scout", "--rehearse", "--target", TARGET)
    assert code == 0, err
    item = box.last()["items"][0]
    assert item["status"] == "reused" and item["decision"] == "tier0-reuse", item
    d = box.latest() / "items" / "bamr87__SCHEMA"
    assert not (d / "ai-run-dry.txt").exists() and not list(box.work.glob("*/*")), "no dry run; clone destroyed"


def test_an_ai_run_dry_run_refusal_fails_the_item_and_exits_one():
    box = Box()
    with world(box, JEV_TEST_DRY_REFUSES="1"):
        code, _, _ = jev("run", "repo-scout", "--rehearse", "--target", TARGET)
    item = box.last()["items"][0]
    assert code == 1 and item["status"] == "failed" and "refused the planned argv" in item["reason"], item
    no_writes(box)


def test_a_tampered_workspace_is_failed_and_destroyed_without_git_running_in_it():
    box = Box()
    saved = (L.wsp.tampered, L.wsp.tree_report)

    def no_git(ws):
        raise AssertionError("git ran in a tampered clone")
    L.wsp.tampered, L.wsp.tree_report = (lambda ws: ["commondir"]), no_git
    try:
        with world(box):
            code, _, _ = jev("run", "repo-scout", "--rehearse", "--target", TARGET)
    finally:
        L.wsp.tampered, L.wsp.tree_report = saved
    item = box.last()["items"][0]
    assert code == 1 and item["status"] == "failed" and "tampered" in item["reason"], item
    assert "not inspected" in (box.latest() / "items" / "bamr87__SCHEMA" / "tree.txt").read_text()
    assert not list(box.work.glob("*/*")), "destroyed"
    L.wsp.tampered, L.wsp.tree_report = (lambda ws: ["commondir"]), no_git
    try:
        with world(box):
            code, _, _ = jev("run", "repo-scout", "--rehearse", "--target", TARGET, "--keep-workspace")
    finally:
        L.wsp.tampered, L.wsp.tree_report = saved
    item = box.last()["items"][0]
    assert code == 1 and "kept_workspace" not in item and not list(box.work.glob("*/*")), \
        "--keep-workspace never keeps a tampered clone"


def test_an_item_failure_after_the_clone_fails_that_item_and_the_run_goes_on():
    box = Box()
    saved = L.wsp.tree_report

    def broken(ws):
        raise common.JevError("git status failed (simulated)")
    L.wsp.tree_report = broken
    try:
        with world(box):
            code, _, _ = jev("run", "repo-scout", "--rehearse", "--target", TARGET)
    finally:
        L.wsp.tree_report = saved
    rec = box.last()
    assert code == 1 and rec["status"] == "rehearsed", (code, rec["status"], rec["notes"])
    [item] = rec["items"]
    assert item["status"] == "failed" and "simulated" in item["reason"], item
    rows = [json.loads(x) for x in (box.latest() / "attempts.jsonl").read_text().splitlines()]
    assert [(r["decision"], r["outcome"]) for r in rows] == [("rehearsed", "failed")], rows
    assert not list(box.work.glob("*/*")), "the clone is still destroyed"


def test_ctrl_c_during_the_clone_leaves_nothing_in_the_work_root():
    box = Box()
    real = L.wsp.gh

    def clone_then_interrupt(args, **kw):
        real(args, **kw)   # the clone lands on disk, then the operator's Ctrl-C
        raise KeyboardInterrupt
    L.wsp.gh = clone_then_interrupt
    try:
        with world(box):
            code, _, _ = jev("run", "repo-scout", "--rehearse", "--target", TARGET)
    finally:
        L.wsp.gh = real
    assert code == 130 and box.last()["status"] == "interrupted"
    assert [c for c in box.gh_calls() if c[:2] == ["repo", "clone"]], "the clone did run"
    assert not list(box.work.glob("*/*")), "the partial clone is removed"


def test_head_sha_tells_an_empty_repository_from_a_missing_branch():
    box = Box()
    with world(box, STUB_GH_COMMITS_ERROR="Git Repository is empty. (HTTP 409)"):
        assert L.head_sha(NWO, "main") == ("", "")
    with world(box, STUB_GH_COMMITS_ERROR="No commit found for SHA: nope (HTTP 422)"):
        sha, why = L.head_sha(NWO, "nope")
        assert sha is None and "no branch `nope`" in why and "drift" in why
        code, _, err = jev("run", "repo-scout", "--rehearse", "--target", TARGET)
        code, out, _ = jev("plan", "repo-scout", "--target", TARGET)
        assert code == 0 and "note: bamr87/SCHEMA has no branch `main`" in out and "drift" in out, out
    item = box.last()["items"][0]
    # not skipped as "nothing to read": the item goes on to the clone, which a real gh fails loudly
    assert item["status"] != "skipped" and "no branch `main`" in err and "drift" in err, (item, err)


def test_item_directories_take_any_key_and_a_plan_with_duplicate_keys_is_refused():
    assert W.item_dirname(NWO) == "bamr87__SCHEMA"
    marker = W.item_dirname("bamr87/zpl-viewer:.github/workflows/ci.yml")
    issue = W.item_dirname("bamr87/SCHEMA#12")
    assert marker != issue and all(re.fullmatch(r"[A-Za-z0-9._-]+-[0-9a-f]{8}", n) for n in (marker, issue))
    assert W.item_dirname("bamr87/SCHEMA#13") != issue, "two issues in one repo never share a directory"
    box = Box()
    ctx = L.RunContext(spec=L.load_step("repo-scout"), adapter=None, fleet={}, opts=L.Options(),
                       plan_dir=box.root / "plan", history=L.History(box.runs))
    two = [Item(key=k, name="SCHEMA", nwo=NWO, branch="main", row={}, brief=None) for k in (f"{NWO}#1", f"{NWO}#2")]
    assert {ctx.item_dir(i).name for i in two} == {W.item_dirname(i.key) for i in two} and len(
        {ctx.item_dir(i) for i in two}) == 2
    L.check_items(PlanResult(items=two))
    try:
        L.check_items(PlanResult(items=[two[0], two[0]]))
    except common.JevError as exc:
        assert "more than once" in str(exc)
    else:
        raise AssertionError("duplicate keys were accepted")


# --------------------------------------------------------------------------- #
# plan, show, doctor
# --------------------------------------------------------------------------- #
def test_plan_never_clones_and_never_runs_claude_p():
    box = Box()
    with world(box):
        code, out, _ = jev("plan", "repo-scout", "--target", TARGET, "--json")
    assert code == 0
    data = json.loads(out)
    [item] = data["items"]
    assert item["decision"] == "attempt" and item["dedupe"] == "clear"
    assert item["dry_filing"][:3] == ["scout-file", "--nwo", NWO] and "--apply" not in item["dry_filing"]
    assert "--restricted" in item["claude_flags"] and item["prompt_sha256"]
    assert not [c for c in box.gh_calls() if c[:2] == ["repo", "clone"]]
    assert not [c for c in box.claude_calls() if "-p" in c], "plan never runs claude -p"
    assert not box.run_dirs(), "plan writes no run"
    no_writes(box)


def test_refusals_exit_with_their_documented_codes():
    box = Box()
    with world(box):
        assert jev("show", "--latest")[0] == 2, "no runs yet: usage"
        assert jev("show", "not/a/run")[0] == 2 and jev("show", "20260101-nope")[0] == 2
        assert jev("run", "repo-scout", "--rehearse", "--offline", "--target", TARGET, "--run-id", "dup-1")[0] == 0
        code, _, err = jev("run", "repo-scout", "--rehearse", "--offline", "--target", TARGET, "--run-id", "dup-1")
        assert code == 2 and "already exists" in err
        assert jev("run", "repo-scout", "--apply", "--offline", "--target", TARGET)[0] == 2
    with world(box, JEV_WORK_ROOT=str(HUB / ".fleet" / "work")):
        code, _, err = jev("doctor")
    assert code == 4 and "inside the hub" in err and not (HUB / ".fleet" / "work").exists()
    for offline in ((), ("--offline",)):
        calls = len(box.claude_calls())
        with world(box, JEV_WORK_ROOT=str(HUB / ".fleet" / "work")):
            code, _, err = jev("run", "repo-scout", "--rehearse", "--target", TARGET, *offline)
        rec = box.last()
        assert code == 4 and rec["status"] == "refused" and rec["items"] == [] and "plan" not in rec, (offline, rec)
        assert any("inside the hub" in n for n in rec["notes"]) and not (HUB / ".fleet" / "work").exists()
        assert len(box.claude_calls()) == calls, "refused before any CLI runs or anything is planned"


def test_show_prints_the_latest_run():
    box = Box()
    with world(box):
        assert jev("run", "repo-scout", "--rehearse", "--target", TARGET, "--offline")[0] == 0
        code, out, _ = jev("show", "--latest")
        assert code == 0 and "rehearsed" in out and "API-equivalent" in out
        code, out, _ = jev("show", box.last()["run_id"], "--json")
        assert code == 0 and json.loads(out)["run_id"] == box.last()["run_id"]
        code, _, _ = jev("run", "repo-scout", "--rehearse", "--target", TARGET, "--offline", "--json")
        assert code == 0


def test_json_output_is_only_the_run_record():
    box = Box()
    with world(box):
        code, out, err = jev("run", "repo-scout", "--rehearse", "--target", TARGET, "--offline", "--json")
    assert code == 0 and json.loads(out)["schema"] == L.RUN_SCHEMA and "run:" in err


def test_doctor_runs_the_probe_credential_free_and_caches_it():
    box = Box()
    with world(box):
        code, out, err = jev("doctor", "--json")
        report = json.loads(out)
        assert code == 0, (report, err)
        [step] = report["steps"]
        assert step["probe"] == "ok" and step["probe_problems"] == [] and report["runs_dir_ignored"] is True
        assert step["auth"] == {"method": "oauth", "source": "env"}
        probed = [json.loads(x) for x in (box.bin / "probed.jsonl").read_text().splitlines()]
        assert [p["isolated"] for p in probed] == [False, True], "control, then isolated"
        spec = L.load_step("repo-scout")
        assert L.cached(".probe.json", L.cache_key((2, 1, 308), spec, H.Posture("sandbox")))["ok"] is True
        code, _, _ = jev("run", "repo-scout", "--rehearse", "--target", TARGET, "--offline")
        assert code == 0 and box.last()["host"]["probe"] == "ok", "a rehearsal reads the cached probe"
    assert not box.prompted() and not list(box.work.glob(".doctor-*")), "scratch removed"


def test_doctor_exits_127_without_claude_and_4_without_a_sandbox():
    box = Box()
    with world(box):
        assert jev("doctor", "--claude-bin", "no-such-claude")[0] == 127
    with world(box, sandbox=False):
        code, out, _ = jev("doctor", "--json")
        assert code == 4 and "no sandbox" in " ".join(json.loads(out)["steps"][0]["problems"])
        assert jev("doctor", "--posture", "reduced")[0] == 0


def test_the_runs_dir_is_git_ignored():
    assert git(["check-ignore", "-q", ".fleet/runs/x"], cwd=HUB).ok


def test_prune_keeps_the_newest_runs():
    box = Box()
    with world(box):
        for n in range(4):
            d = box.runs / f"r{n}"
            d.mkdir(parents=True)
            L.write_json(d / "run.json", {"schema": L.RUN_SCHEMA, "started": f"2026-10-0{n + 1}T00:00:00Z"})
        (box.runs / "other").mkdir()
        gone = L.prune(keep=2)
    assert gone == ["r0", "r1"] and sorted(p.name for p in box.runs.iterdir()) == ["other", "r2", "r3"]


def test_tools_dash_routes_loop_through_the_resolved_python():
    text = (HUB / "tools" / "dash").read_text()
    assert 'cmd_loop() {' in text and '"${PY}" -m tools.jev loop "$@"' in text and "loop)    cmd_loop" in text
    out = subprocess.run([str(HUB / "tools" / "dash"), "loop", "list"], capture_output=True, text=True,
                         check=False)
    assert out.returncode == 0 and "repo-scout/scout" in out.stdout, out.stderr


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"ok   {t.__name__}")
        except AssertionError as e:  # noqa: PERF203
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERR  {t.__name__}: {type(e).__name__}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)
