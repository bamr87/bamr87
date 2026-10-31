#!/usr/bin/env python3
"""
End-to-end tests for tools/jev/loop.py — the local loop engine (#486, ADR
0002 P1): `list`, `doctor` (and `--live`, the canary), `plan`, `run` (the
rehearsal and live attempts, the ceiling, the posture checks, the preview and
`--apply`), `publish`, `show`, `budget`.

Nothing here can spend. `claude` is a stub that answers --version and
`auth status`, refuses an empty stdin with "Input must be provided" (the flag
preflight) and plays the isolation probe credential-free; given a real prompt
it plays the session a test scripted in `scenario.json` (or, with none, drops
a PROMPTED marker the $0 tests assert never appears). `gh` is a stub whose
`repo clone` clones a local fixture, whose reads answer from fixtures and
whose writes (`issue create`, `label create`) are only logged. The planner,
`ai-run` and the filer are the REAL `tools/dash-gen scout`, `ai-run` and
`scout-file`, reading GitHub through the stub.

Run: python3 tools/test_jev_loop.py
"""
from __future__ import annotations

import contextlib
import copy
import dataclasses
import datetime as dt
import fcntl
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
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
    note("probed.jsonl", {"isolated": "--restricted" in argv, "safe_mode": "--safe-mode" in argv})
    # 2.1.308's CA-certs line lists the USER settings' env keys only; --restricted reads no settings file
    try:
        user = json.load(open(os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or "/nonexistent", "settings.json")))
    except (OSError, ValueError):
        user = {}
    keys = ",".join(user.get("env") or {}) if "--restricted" not in argv else ""
    debug("[DEBUG] CA certs: Config fallback - globalEnv keys: , settingsEnv keys: " + (keys or "none"))
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
scenario_file = os.path.join(HERE, "scenario.json")
if not os.path.exists(scenario_file):
    note("PROMPTED", {"argv": argv})   # a real prompt and no scenario: a live CLI would have spent here
    sys.exit(99)
# --- a scripted live session (tests of the attempt path; still no model) ---
sc = json.load(open(scenario_file))
calls = sum(1 for _ in open(os.path.join(HERE, "live.jsonl"))) if os.path.exists(os.path.join(HERE, "live.jsonl")) else 0
if isinstance(sc, list):
    sc = sc[min(calls, len(sc) - 1)]
note("live.jsonl", {"argv": argv, "env": sorted(os.environ), "cwd": os.getcwd()})
kind = sc.get("kind", "ok")
sid = argv[argv.index("--session-id") + 1] if "--session-id" in argv else "s-live"
tools = sc.get("init_tools") or argv[argv.index("--tools") + 1].split(",")
if sc.get("hang_before_init"):   # the wall clock fires before the session starts
    import time
    time.sleep(float(sc["hang_before_init"]))
    sys.exit(1)
if not sc.get("no_init"):
    emit({"type": "system", "subtype": "init", "session_id": sid, "tools": tools, "mcp_servers": [],
          "permissionMode": "dontAsk", "output_style": "default", "skills": [], "claude_code_version": "2.1.308",
          "model": argv[argv.index("--model") + 1]})
debug("[DEBUG] Applying permission update: Adding 44 allow rule(s) to destination 'flagSettings'")
if sc.get("settings_env"):
    debug("[DEBUG] CA certs: Config fallback - globalEnv keys: , settingsEnv keys: ANTHROPIC_BASE_URL")
FENCES = sc.get("fences", "read: denyOnly(3), write: allowOnly(2)")
SANDBOX_LINE = "[DEBUG] [Sandbox macOS] Applied restrictions - network: false, " + FENCES
n = [0]
def tool(name, inp, result, is_error=False):
    n[0] += 1
    emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": f"t{n[0]}", "name": name, "input": inp}]}})
    emit({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": f"t{n[0]}", "content": result, "is_error": is_error}]}})
usage = {argv[argv.index("--model") + 1]: {"inputTokens": 1000, "outputTokens": 200}}
denials = [{"tool_name": "Bash", "tool_use_id": f"d{i}", "tool_input": {"command": "rg x"}}
           for i in range(int(sc.get("denied_bash", 0)))]
def result(cost, **kw):
    emit({"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": cost, "num_turns": 6,
          "session_id": sid, "modelUsage": usage, "permission_denials": denials, **kw})
if kind.startswith("canary"):
    import re
    cmds = dict(re.findall(r"^([1-6])\. (.+)$", prompt, re.M))
    secret = re.search(r"cat (\S+)", cmds["1"]).group(1)
    write_to = re.search(r"Write tool to create (\S+) containing", prompt).group(1)
    leak = open(secret).read().strip() if kind == "canary_leak" else ""
    names = re.search(r"for k in (\(.*?\))\)\)", cmds["5"]).group(1)
    seen = sum(n in os.environ for n in eval(names)) if kind == "canary_env_leak" else 0
    denied = "PermissionError: [Errno 1] Operation not permitted"
    tool("Bash", {"command": cmds["1"]}, "cat: Operation not permitted", True)
    tool("Bash", {"command": cmds["2"]}, ("READ=" + leak) if leak else denied, not leak)
    tool("Bash", {"command": cmds["3"]}, "OSError: [Errno 1] Operation not permitted", True)
    tool("Bash", {"command": cmds["4"]}, denied, True)
    tool("Bash", {"command": cmds["5"]}, f"SECRETS={seen}")
    tool("Bash", {"command": cmds["6"]}, "cat: Operation not permitted", True)
    tool("Read", {"file_path": os.path.join(os.getcwd(), "link")}, "     1\t" + open("link").read())
    tool("Read", {"file_path": secret}, "File is outside the allowed working directories", True)
    tool("Write", {"file_path": write_to, "content": "x"}, "File is outside the allowed working directories", True)
    debug(SANDBOX_LINE)
    result(0.03)
    sys.exit(0)
for i in range(int(sc.get("bash", 2))):
    tool("Bash", {"command": "git log -1"}, "commit abc")
for i in range(int(sc.get("denied_bash", 0))):
    tool("Bash", {"command": "rg x"}, "Permission to use Bash with command rg x has been denied.", True)
if sc.get("bash", 2) and sc.get("sandbox_line", True):
    debug(SANDBOX_LINE)
os.makedirs(".scout", exist_ok=True)
if sc.get("symlink"):
    os.symlink(sc["symlink"], ".scout/proposals.json")
elif sc.get("proposals") is not None:
    with open(".scout/proposals.json", "w") as fh:
        json.dump({"proposals": sc["proposals"], "notes": "stub"}, fh)
if sc.get("tamper"):
    with open(".git/config", "a") as fh:
        fh.write("[core]\n\tfsmonitor = /tmp/evil\n")
if sc.get("tracked_edit"):
    with open("README.md", "a") as fh:
        fh.write("an agent edit\n")
if kind == "garbage":
    print("not json at all"); sys.exit(1)
if kind == "usage_limit":
    result(0, is_error=True, api_error_status=429, result="You have hit your weekly limit"); sys.exit(1)
if kind == "credential_rejected":
    emit(json.loads(__NOT_LOGGED_IN__)); sys.exit(1)
if kind == "budget_hit":
    result(8.0, subtype="error_max_budget_usd", is_error=True); sys.exit(1)
if sc.get("sleep"):   # a session that outlives the engine's backstop
    import time
    time.sleep(float(sc["sleep"]))
result(float(sc.get("cost", 0.61)))
sys.exit(0)
'''

STUB_GH = r'''#!__PY__
import json, os, subprocess, sys
argv = sys.argv[1:]
with open(os.environ["STUB_GH_LOG"], "a") as fh:
    fh.write(json.dumps(argv) + "\n")
if os.environ.get("STUB_GH_ENV_LOG"):
    with open(os.environ["STUB_GH_ENV_LOG"], "a") as fh:
        fh.write(json.dumps({"argv": argv[:2], "GH_TOKEN": os.environ.get("GH_TOKEN")}) + "\n")
fixtures = json.loads(os.environ.get("STUB_GH_FIXTURES") or "{}")
def src(nwo):
    return fixtures.get(nwo) or fixtures["*"]
def head(nwo):
    return subprocess.run(["git", "-C", src(nwo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
if argv[:2] == ["repo", "clone"]:
    nwo, dest = argv[2], argv[3]
    rest = argv[argv.index("--") + 1:] if "--" in argv else []
    sys.exit(subprocess.run(["git", "clone", "--quiet", *rest, src(nwo), dest]).returncode)
if argv[:2] == ["api", "user"]:
    if os.environ.get("STUB_GH_USER_FAIL"):
        sys.stderr.write("HTTP 401: Bad credentials (https://api.github.com/user)\n"); sys.exit(1)
    print("bamr87"); sys.exit(0)
if argv[:2] == ["label", "create"]:
    sys.exit(0)
if argv[:2] == ["issue", "create"]:
    count = sum(1 for line in open(os.environ["STUB_GH_LOG"]) if '"create"' in line and '"issue"' in line)
    if os.environ.get("STUB_GH_CREATE_FAIL") or count > int(os.environ.get("STUB_GH_CREATE_FAIL_AFTER") or 10 ** 6):
        sys.stderr.write("GraphQL: could not create issue\n"); sys.exit(1)
    print(f"https://github.com/{argv[argv.index('-R') + 1]}/issues/{100 + count}"); sys.exit(0)
if argv[:1] == ["api"] and "/commits/" in argv[1]:
    nwo = argv[1].split("repos/", 1)[1].split("/commits/", 1)[0]
    if os.environ.get("STUB_GH_COMMITS_ERROR"):
        sys.stderr.write("gh: " + os.environ["STUB_GH_COMMITS_ERROR"] + "\n"); sys.exit(1)
    if os.environ.get("STUB_GH_HEAD_MOVED"):
        print("0" * 40); sys.exit(0)
    print(head(nwo)); sys.exit(0)
if argv[:2] == ["repo", "view"]:
    print(json.dumps({"hasIssuesEnabled": True})); sys.exit(0)
if argv[:2] == ["issue", "list"]:
    listed = sum(1 for line in open(os.environ["STUB_GH_LOG"]) if line.startswith('["issue", "list"'))
    if listed >= int(os.environ.get("STUB_GH_LIST_FAIL_FROM") or 10 ** 6):
        sys.stderr.write("HTTP 502: Bad Gateway\n"); sys.exit(1)
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
#: `ai-run --dry-run` refuse (JEV_TEST_DRY_REFUSES), make a live `ai-run` die
#: before it writes any outcome (JEV_TEST_AI_RUN_DIES), point `scout-file` at
#: another fleet.yml (JEV_TEST_FILE_CONFIG) and log the environment's NAMES
#: each subcommand received (JEV_TEST_ENV_LOG)
DASH_GEN_WRAPPER = r'''#!__PY__
import json, os, subprocess, sys
if os.environ.get("JEV_TEST_ENV_LOG"):
    with open(os.environ["JEV_TEST_ENV_LOG"], "a") as fh:
        fh.write(json.dumps({"sub": sys.argv[1], "env": sorted(os.environ)}) + "\n")
if sys.argv[1:3] == ["ai-run", "--dry-run"] and os.environ.get("JEV_TEST_DRY_REFUSES"):
    sys.stderr.write("ai-run: --claude-bin is not executable\n"); sys.exit(2)
if sys.argv[1:2] == ["ai-run"] and "--dry-run" not in sys.argv and os.environ.get("JEV_TEST_AI_RUN_DIES"):
    sys.stderr.write("Traceback (most recent call last): ai-run died\n"); sys.exit(1)
args = sys.argv[1:]
if args[:1] == ["scout-file"] and os.environ.get("JEV_TEST_FILE_CONFIG"):
    args += ["--config", os.environ["JEV_TEST_FILE_CONFIG"]]
res = subprocess.run(["__REAL__", *args], capture_output=True, text=True, input=sys.stdin.read())
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
                "STUB_GH_FIXTURES": json.dumps({NWO: str(FIXTURE), "*": str(FIXTURE)}),
                "STUB_GH_ENV_LOG": str(self.root / "gh-env.jsonl"), "CLAUDE_CODE_OAUTH_TOKEN": "fake-oauth-token-1234"}

    def gh_calls(self) -> list[list[str]]:
        return [json.loads(x) for x in self.gh_log.read_text().splitlines()] if self.gh_log.exists() else []

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

    def seed_live(self, scenario: dict | list | None = None, *, canary: bool = True,
                  posture: str = "sandbox", auth: H.AuthChoice | None = H.AuthChoice("oauth", "env")) -> None:
        """What a live attempt needs: a passing probe (and canary, for `auth`'s
        credential exposure: the box's env OAuth token by default), and the stub's script."""
        self.seed_probe(posture=posture)
        if canary:
            L.store(".canary.json", L.canary_key((2, 1, 308), L.load_step("repo-scout"), H.Posture(posture), auth),
                    {"ok": True, "problems": [], "at": L.iso()})
        if scenario is not None:
            (self.bin / "scenario.json").write_text(json.dumps(scenario))

    def live_calls(self) -> list[dict]:
        f = self.bin / "live.jsonl"
        return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []

    def ledger_rows(self) -> list[dict]:
        f = self.root / "ledger.json"
        return list(json.loads(f.read_text())["runs"].values()) if f.exists() else []

    def gh_env(self) -> list[dict]:
        f = self.root / "gh-env.jsonl"
        return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []

    def attempts(self, run: Path | None = None) -> list[dict]:
        return [json.loads(x) for x in ((run or self.latest()) / "attempts.jsonl").read_text().splitlines()]


@contextlib.contextmanager
def world(box: Box, *, sandbox: bool = True, fleet_edit=None, dirty: list[str] | None = None, **extra: str):
    """Point the engine at the box: env, the dash-gen wrapper, the sandbox check,
    the hub's dirty state (clean unless `dirty`: the checkout under test may
    itself be uncommitted) and (optionally) an edited _data/fleet.yml.
    Everything is restored after."""
    saved_env = dict(os.environ)
    saved = (L.DASH_GEN, L.sandbox_available, L.load_fleet, L.hub_state, H.private_read_paths)
    for k in (*H.CREDENTIAL_ENV.values(), *H.AUTH_OVERRIDE_ENV, "CLAUDE_AUTH_ORDER", "GH_TOKEN", "GITHUB_TOKEN",
              "FLEET_TOKEN"):
        os.environ.pop(k, None)
    os.environ.update({**box.env(), **extra})
    L.DASH_GEN = box.dash_gen
    L.sandbox_available = lambda: sandbox
    L.hub_state = lambda paths: {"head": "0" * 40, "dirty_paths": list(dirty or [])}
    # the canary's second secret goes in the box, never in this account's real temp roots
    (box.root / "private").mkdir(exist_ok=True)
    H.private_read_paths = lambda work=None: (str(box.root / "private"),)
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
        L.DASH_GEN, L.sandbox_available, L.load_fleet, L.hub_state, H.private_read_paths = saved


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


def test_a_live_run_offline_is_refused_before_anything_runs():
    box = Box()
    with world(box):
        code, _, err = jev("run", "repo-scout", "--target", TARGET, "--offline")
    assert code == 2 and "--offline is for" in err
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
    assert rec["publish"] == {"risk": "publish", "tier": "high", "on_budget_hit": "discard"}
    assert rec["host"]["auth"] == {"method": "oauth", "source": "env"} and rec["host"]["probe"] == "ok"
    assert any("canary" in n for n in rec["notes"]), "the missing canary is reported, not hidden"
    [item] = rec["items"]
    assert item["key"] == NWO and item["status"] == "rehearsed" and item["ai_run_dry"] == 0, item
    d = box.latest() / "items" / "bamr87__SCHEMA"
    spec = L.load_step("repo-scout")
    plan = json.loads((box.latest() / "plan" / "plan.json").read_text())
    row = plan["include"][0]
    assert (d / "prompt.txt").read_text() == S.render_prompt(spec, S.values_from(spec, row)) == row["prompt"]
    settings = json.loads((d / "settings.json").read_text())
    assert settings == H.settings_doc(H.Posture("sandbox"), private_reads=(str(box.root / "private"),),
                                      dotenv=(box.root / "empty.env").resolve())
    assert str((box.root / "empty.env").resolve()) in {f["path"] for f in settings["sandbox"]["credentials"]["files"]}
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


def test_head_sha_tells_an_empty_repository_from_a_missing_branch():
    box = Box()
    with world(box, STUB_GH_COMMITS_ERROR="Git Repository is empty. (HTTP 409)"):
        assert L.head_sha(NWO, "main") == ("", "")
    with world(box, STUB_GH_COMMITS_ERROR="No commit found for SHA: nope (HTTP 422)"):
        sha, why = L.head_sha(NWO, "nope")
        assert sha is None and "no branch `nope`" in why and "drift" in why
        code, _, err = jev("run", "repo-scout", "--rehearse", "--target", TARGET)
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
        assert [(p["isolated"], p["safe_mode"]) for p in probed] == [(False, False), (True, True), (True, False)], \
            "control, then isolated, then restricted without --safe-mode"
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


# --------------------------------------------------------------------------- #
# live attempts (the stub claude plays a session; nothing can reach a model)
# --------------------------------------------------------------------------- #
GOOD = [{"title": "Add a --version flag to the schema linter", "kind": "feature", "priority": "P2",
         "size": "size:s", "body": "## Problem\n\nThe linter cannot report its version.\n\n" + "Detail. " * 20},
        {"title": "Document the SCHEMA.md placement rules in one table", "kind": "update",
         "body": "## Problem\n\nPlacement rules are spread over three files.\n\n" + "More detail. " * 15}]
FLEET_TOKEN = "fleet_test_token_000111222"


def _issue_creates(box: Box) -> list[list[str]]:
    return [c for c in box.gh_calls() if c[:2] == ["issue", "create"]]


def test_a_live_run_attempts_validates_and_previews_but_files_nothing_without_apply():
    box = Box()
    before = hub_status()
    pythonpath = os.pathsep.join(filter(None, [os.environ.get("PYTHONPATH"), str(box.root)]))
    with world(box, GH_TOKEN="ghp_user_token_should_not_reach_claude", PYTHONPATH=pythonpath):
        box.seed_live({"kind": "ok", "proposals": GOOD, "cost": 0.61})
        code, out, err = jev("run", "repo-scout", "--target", TARGET)
    assert code == 0, err
    rec = box.last()
    assert rec["mode"] == "run" and rec["status"] == "done" and out.strip() == f"run: {box.latest()}"
    [item] = rec["items"]
    assert item["status"] == "previewed" and item["outcome"] == "ok" and item["would_file"] == 2, item
    assert item["cost_usd"] == 0.61 and item["cost_source"] == "reported"
    assert rec["totals"]["spent_usd"] == 0.61 and rec["budget"]["after"]["spent_usd"] == 0.61
    [call] = box.live_calls()
    assert not {"GH_TOKEN", "GITHUB_TOKEN", "FLEET_TOKEN", "PYTHONPATH", "SSH_AUTH_SOCK"} & set(call["env"])
    assert [n for n in H.CREDENTIAL_ENV.values() if n in call["env"]] == ["CLAUDE_CODE_OAUTH_TOKEN"]
    assert Path(call["cwd"]).resolve().is_relative_to(box.work.resolve()), "the agent ran in the throwaway clone"
    [row] = box.ledger_rows()
    assert row["origin"] == "local" and row["loop"] == "repo-scout" and row["call_site"] == "repo-scout.yml:scout"
    assert row["attempt_id"] == item["attempt_id"] and row["cost_source"] == "reported" and row["cap_usd"] == 8.0
    d = box.latest() / "items" / "bamr87__SCHEMA"
    bodies = sorted((d / "bodies").glob("*.md"))
    assert len(bodies) == 2 and all(b.read_text().startswith(f'<!-- repo-scout key="{NWO}" -->') for b in bodies)
    plan = json.loads((d / "publish-plan.json").read_text())
    assert plan["publishable"] and plan["plan_id"] == item["plan_id"] and set(plan["bodies"]) == {b.name for b in bodies}
    md = (d / "publish-plan.md").read_text()
    assert "--force" in md and "refresh" in md and bodies[0].read_text().strip() in md, "the exact bytes are shown"
    assert (d / "debug-sandbox.txt").read_text().count("[Sandbox macOS]") == 1 and not (d / "debug.log").exists()
    decisions = [r["decision"] for r in box.attempts()]
    assert decisions == ["attempt", "publish-preview"], decisions
    assert not _issue_creates(box) and not [c for c in box.gh_calls() if c[:2] == ["label", "create"]]
    assert not list(box.work.glob("*/*")), "the clone is destroyed after its item"
    assert "ghp_user_token" not in (d / "trace.jsonl").read_text()
    assert hub_status() == before, "a live run changes nothing the hub tracks"


def test_apply_files_the_preview_in_the_same_run_with_the_token_in_the_filer_only():
    box = Box()
    with world(box, FLEET_TOKEN=FLEET_TOKEN):
        box.seed_live({"kind": "ok", "proposals": GOOD})
        code, _, err = jev("run", "repo-scout", "--target", TARGET, "--apply")
        assert code == 0, err
        rec = box.last()
        [item] = rec["items"]
        assert rec["mode"] == "apply" and item["status"] == "published" and item["published"] == 2, item
        creates = _issue_creates(box)
        assert len(creates) == 2 and all(c[c.index("-R") + 1] == NWO for c in creates)
        writes = [e for e in box.gh_env() if e["argv"] in (["issue", "create"], ["label", "create"])]
        assert writes and all(e["GH_TOKEN"] == FLEET_TOKEN for e in writes), "the filer runs with FLEET_TOKEN"
        lists = [e["GH_TOKEN"] for e in box.gh_env() if e["argv"] == ["issue", "list"]]
        clones = [e["GH_TOKEN"] for e in box.gh_env() if e["argv"] == ["repo", "clone"]]
        # the planner, the preview and the live recheck read with the user's gh; only the apply's own dedupe has it
        assert clones == [None] and lists.count(FLEET_TOKEN) == 1 and lists[-1] == FLEET_TOKEN, lists
        assert set(lists[:-1]) == {None}, "GH_TOKEN is set in the apply subprocess only"
        calls = box.gh_calls()
        assert calls.index(["api", "user", "--jq", ".login"]) < next(
            i for i, c in enumerate(calls) if c[:2] == ["repo", "clone"]), "the token is probed before any spend"
        d = box.latest() / "items" / "bamr87__SCHEMA"
        result = json.loads((d / "publish-result.json").read_text())
        assert result["status"] == "published" and len(result["urls"]) == 2 and result["stray_bodies"] == []
        assert sorted(p.read_text() for p in (d / "filed").glob("*.md")) == sorted(
            p.read_text() for p in (d / "bodies").glob("*.md")), "what was filed is what was previewed"
        apply_row = [r for r in box.attempts() if r["decision"] == "publish-apply"]
        assert len(apply_row) == 1 and apply_row[0]["published"] and apply_row[0]["validated_sha256"]
        code, out, _ = jev("publish", rec["run_id"], "--apply")
        assert code == 2 and "already applied" in out, "a second apply is refused"
        assert len(_issue_creates(box)) == 2
        assert "fleet_test_token" not in json.dumps(box.last()) + (d / "publish-plan.md").read_text()


def test_apply_with_a_refused_token_stops_before_any_spend():
    box = Box()
    with world(box, FLEET_TOKEN=FLEET_TOKEN, STUB_GH_USER_FAIL="1"):
        box.seed_live({"kind": "ok", "proposals": GOOD})
        code, _, _ = jev("run", "repo-scout", "--target", TARGET, "--apply")
    rec = box.last()
    assert code == 1 and rec["status"] == "refused" and any("refused by `gh api user`" in n for n in rec["notes"])
    assert not box.live_calls() and not box.ledger_rows() and FLEET_TOKEN not in json.dumps(rec)


def test_apply_refuses_a_dirty_engine_unless_allow_dirty():
    box = Box()
    with world(box, FLEET_TOKEN=FLEET_TOKEN, dirty=["tools/jev/loop.py"]):
        box.seed_live({"kind": "ok", "proposals": GOOD})
        code, _, _ = jev("run", "repo-scout", "--target", TARGET, "--apply")
        assert code == 2 and any("--allow-dirty" in n for n in box.last()["notes"]) and not box.live_calls()
        code, _, err = jev("run", "repo-scout", "--target", TARGET, "--apply", "--allow-dirty")
    assert code == 0 and box.last()["items"][0]["status"] == "published", err
    assert any("filing anyway" in n for n in box.last()["notes"])


def test_publish_files_a_reviewed_dry_run_and_refuses_changed_bytes():
    box = Box()
    with world(box, FLEET_TOKEN=FLEET_TOKEN):
        box.seed_live({"kind": "ok", "proposals": GOOD})
        assert jev("run", "repo-scout", "--target", TARGET)[0] == 0
        run_id = box.last()["run_id"]
        d = box.latest() / "items" / "bamr87__SCHEMA"
        code, out, _ = jev("publish", run_id)
        assert code == 0 and "matches the reviewed bytes" in out and not _issue_creates(box)
        body = sorted((d / "bodies").glob("*.md"))[0]
        original = body.read_text()
        body.write_text(original + "tampered after review\n")
        code, _, _ = jev("publish", run_id, "--apply")
        assert code == 2 and not _issue_creates(box), "edited reviewed bytes are refused"
        body.write_text(original)
        validated = d / "outputs" / "proposals.validated.json"
        kept = validated.read_text()
        validated.write_text(kept.replace("version", "VERSION"))
        assert jev("publish", run_id, "--apply")[0] == 2 and not _issue_creates(box)
        validated.write_text(kept)
        assert jev("publish", run_id, "--apply", "--plan-id", "0" * 16)[0] == 2
        with world(box, FLEET_TOKEN=FLEET_TOKEN, dirty=["tools/jev/steps/repo-scout/scout.yml"]):
            assert jev("publish", run_id, "--apply")[0] == 2 and not _issue_creates(box)
        plan_id = json.loads((d / "publish-plan.json").read_text())["plan_id"]
        code, out, err = jev("publish", run_id, "--apply", "--plan-id", plan_id)
        assert code == 0 and out.startswith("published: filed 2 issue(s)"), (out, err)
        assert jev("publish", run_id, "--apply")[0] == 2 and len(_issue_creates(box)) == 2, "idempotent"
        rec = json.loads((box.runs / run_id / "run.json").read_text())
        assert rec["items"][0]["status"] == "published", "refusals leave the record; the filing updates it"
        assert [p["status"] for p in rec["publishes"]][-2:] == ["published", "publish-refused"]


def test_a_live_dedupe_that_drops_a_reviewed_body_files_the_rest():
    box = Box()
    with world(box, FLEET_TOKEN=FLEET_TOKEN):
        box.seed_live({"kind": "ok", "proposals": GOOD})
        assert jev("run", "repo-scout", "--target", TARGET)[0] == 0
        run_id = box.last()["run_id"]
        # the first proposal is now an open issue: the live dedupe drops it, so the filing renumbers the second
        dup = [{"number": 7, "title": GOOD[0]["title"], "url": "", "labels": [], "body": ""}]
        with world(box, FLEET_TOKEN=FLEET_TOKEN, STUB_GH_ISSUES=json.dumps(dup)):
            code, out, err = jev("publish", run_id, "--apply")
    assert code == 0 and "filed 1 issue(s)" in out, (out, err)
    assert len(_issue_creates(box)) == 1, "a body the reviewer saw, minus the duplicate"


def test_a_filing_that_would_write_bytes_nobody_reviewed_is_refused():
    box = Box()
    with world(box, FLEET_TOKEN=FLEET_TOKEN):
        box.seed_live({"kind": "ok", "proposals": GOOD})
        assert jev("run", "repo-scout", "--target", TARGET)[0] == 0
        run_id = box.last()["run_id"]
        d = box.latest() / "items" / "bamr87__SCHEMA"
        # the validated copy AND its recorded hash move together: only the live dry run can tell
        validated = d / "outputs" / "proposals.validated.json"
        validated.write_text(validated.read_text().replace("cannot report its version", "cannot say its version"))
        plan = json.loads((d / "publish-plan.json").read_text())
        plan["validated_sha256"] = L._file_sha(validated)
        (d / "publish-plan.json").write_text(json.dumps(plan))
        code, out, _ = jev("publish", run_id, "--apply")
    assert code == 2 and "changed since the preview" in out and not _issue_creates(box), out
    assert not (d / "publish-result.json").exists()


def test_the_live_recheck_skips_filing_once_backpressure_is_reached():
    box = Box()
    marker = f'<!-- repo-scout key="{NWO}" -->'
    full = [{"number": n, "title": f"scout issue {n}", "url": "", "labels": [{"name": "ai-scout"}], "body": marker}
            for n in (1, 2, 3)]
    with world(box, FLEET_TOKEN=FLEET_TOKEN):
        box.seed_live({"kind": "ok", "proposals": GOOD})
        assert jev("run", "repo-scout", "--target", TARGET)[0] == 0
        run_id = box.last()["run_id"]
    with world(box, FLEET_TOKEN=FLEET_TOKEN, STUB_GH_ISSUES=json.dumps(full)):
        code, out, _ = jev("publish", run_id, "--apply")
    assert code == 1 and out.startswith("publish-skipped: live recheck") and "still open" in out, out
    assert not _issue_creates(box) and not (box.runs / run_id / "items" / "bamr87__SCHEMA" / "publish-result.json").exists()


def test_a_filer_failure_is_detected_per_issue():
    box = Box()
    with world(box, FLEET_TOKEN=FLEET_TOKEN, STUB_GH_CREATE_FAIL="1"):
        box.seed_live({"kind": "ok", "proposals": GOOD})
        code, _, _ = jev("run", "repo-scout", "--target", TARGET, "--apply")
    item = box.last()["items"][0]
    assert code == 1 and item["status"] == "publish-failed" and "FAILED" in item["reason"], item
    result = json.loads((box.latest() / "items" / "bamr87__SCHEMA" / "publish-result.json").read_text())
    assert result["status"] == "publish-failed" and len(result["failures"]) == 2


def test_a_usage_limit_stops_the_queue_and_never_falls_back_to_the_api_key():
    box = Box()
    with world(box, ANTHROPIC_API_KEY="sk-ant-fake-api-key-000000000000", CLAUDE_AUTH_ORDER="oauth,api_key"):
        box.seed_live({"kind": "usage_limit", "proposals": GOOD})
        code, _, err = jev("run", "repo-scout", "--target", "all", "--day", "2026-10-31")
    rec = box.last()
    assert code == 0 and rec["status"] == "usage-limited" and rec["usage_limited"] is True, (code, rec["status"])
    assert len(rec["items"]) == 2 and rec["items"][0]["status"] == "usage-limited"
    assert rec["items"][1]["status"] == "skipped" and "usage window" in rec["items"][1]["reason"]
    [call] = box.live_calls()
    assert "ANTHROPIC_API_KEY" not in call["env"] and "CLAUDE_CODE_OAUTH_TOKEN" in call["env"]
    assert "do not rotate" in err and "#348" in err
    assert [r["decision"] for r in box.attempts()][-1] == "usage-skip"


def test_a_rejected_credential_exits_3_and_stops_the_run():
    box = Box()
    with world(box):
        box.seed_live({"kind": "credential_rejected"})
        code, _, _ = jev("run", "repo-scout", "--target", "all", "--day", "2026-10-31")
    rec = box.last()
    assert code == 3 and rec["status"] == "stopped" and len(box.live_calls()) == 1
    assert rec["items"][1]["status"] == "skipped" and "stopped" in rec["items"][1]["reason"]
    [row] = box.ledger_rows()
    assert row["outcome"] == "credential_rejected" and row["cost_source"] == "no-spend"


def _seed_ledger(box: Box, rows: list[dict]) -> None:
    (box.root / "ledger.json").write_text(json.dumps({"version": 1, "usage": {}, "sessions": {},
                                                      "runs": {f"s{i}": r for i, r in enumerate(rows)}}))


def test_the_monthly_ceiling_skips_an_attempt_that_would_not_fit_and_scheduled_stops_lower():
    box = Box()
    month = L.now_utc().strftime("%Y-%m")
    spent = {"timestamp": f"{month}-01T00:30:00+00:00", "origin": "local", "loop": "repo-scout",
             "total_cost_usd": 13.0, "cost_source": "reported"}
    noise = [{**spent, "loop": None, "total_cost_usd": 100.0},                                # a plain dash ai run
             {**spent, "timestamp": "2020-01-31T23:00:00-06:00", "total_cost_usd": 100.0}]    # another month
    with world(box, STUB_GH_VAR_REPO_SCOUT_ENABLED="true"):
        box.seed_live({"kind": "ok", "proposals": GOOD})
        _seed_ledger(box, [spent, *noise])
        state = L.budget_position(S.load_fleet(), scheduled=False)
        assert state.spent_usd == 13.0 and state.cap_usd == 25.0 and state.stop_usd == 20.0
        code, _, _ = jev("run", "repo-scout", "--target", TARGET, "--scheduled")
        item = box.last()["items"][0]
        assert code == 0 and item["status"] == "skipped" and "monthly ceiling" in item["reason"], item
        assert not box.live_calls(), "$13 + an $8 cap is over the scheduled stop ($20)"
        code, _, _ = jev("run", "repo-scout", "--target", TARGET)
        assert code == 0 and box.last()["items"][0]["status"] == "previewed", "a manual run may go to $25"
        _seed_ledger(box, [{**spent, "total_cost_usd": 18.0}])
        code, _, _ = jev("run", "repo-scout", "--target", TARGET, "--fresh")
        item = box.last()["items"][0]
        assert item["status"] == "skipped" and item["decision"] == "budget-skip" and len(box.live_calls()) == 1
        _seed_ledger(box, [{**spent, "total_cost_usd": 25.0, "cost_source": "estimated"}])
        code, _, _ = jev("run", "repo-scout", "--target", TARGET, "--fresh")
        assert code == 0 and box.last()["status"] == "ceiling" and len(box.live_calls()) == 1
        code, out, _ = jev("budget", "--json")
        b = json.loads(out)
        assert b["loops"]["spent_usd"] == 25.0 and b["loops"]["estimated_usd"] == 25.0
        assert "API-equivalent (estimate)" in b["label"] and b["monthly_ai_usd"] == 200
        (box.root / "ledger.json").write_text("{not json")
        code, _, err = jev("budget")
        assert code == 2 and "cannot be read" in err, "an unreadable ledger is not an empty month"


def test_a_budget_hit_is_discarded_and_nothing_is_previewed():
    box = Box()
    with world(box):
        box.seed_live({"kind": "budget_hit", "proposals": GOOD})
        code, _, _ = jev("run", "repo-scout", "--target", TARGET)
    item = box.last()["items"][0]
    assert code == 1 and item["status"] == "discarded" and "on_budget_hit discard" in item["reason"], item
    d = box.latest() / "items" / "bamr87__SCHEMA"
    assert not (d / "bodies").exists() and not (d / "outputs").exists()
    assert box.ledger_rows()[0]["total_cost_usd"] == 8.0


def test_an_unparseable_attempt_is_charged_at_the_cap():
    box = Box()
    with world(box):
        box.seed_live({"kind": "garbage", "proposals": GOOD})
        code, _, _ = jev("run", "repo-scout", "--target", TARGET)
    item = box.last()["items"][0]
    assert code == 1 and item["status"] == "failed" and item["outcome"] == "unparseable", item
    [row] = box.ledger_rows()
    assert row["cost_source"] == "estimated" and row["total_cost_usd"] == 8.0
    assert box.last()["budget"]["after"]["spent_usd"] == 8.0 and box.last()["totals"]["estimated_usd"] == 8.0


def test_bash_without_the_sandbox_line_stops_the_run_with_4_and_reads_nothing():
    box = Box()
    with world(box):
        box.seed_live({"kind": "ok", "proposals": GOOD, "sandbox_line": False})
        code, _, _ = jev("run", "repo-scout", "--target", TARGET)
    rec = box.last()
    assert code == 4 and rec["status"] == "stopped" and rec["items"][0]["status"] == "unsafe"
    assert "no sandbox engaged" in rec["items"][0]["reason"]
    d = box.latest() / "items" / "bamr87__SCHEMA"
    assert not (d / "outputs").exists() and not (d / "bodies").exists(), "the outputs are destroyed unread"
    assert not list(box.work.glob("*/*"))


def test_a_settings_env_block_or_an_unprobed_toolset_stops_the_run_with_4():
    for scenario, needle in (({"kind": "ok", "proposals": GOOD, "settings_env": True}, "settings env block"),
                             ({"kind": "ok", "proposals": GOOD,
                               "init_tools": ["Bash", "Read", "Grep", "Glob", "Write", "Task"]}, "never-grantable")):
        box = Box()
        with world(box):
            box.seed_live(scenario)
            code, _, _ = jev("run", "repo-scout", "--target", TARGET)
        item = box.last()["items"][0]
        assert code == 4 and item["status"] == "unsafe" and needle in item["reason"], (needle, item)


def test_a_clone_tampered_by_the_agent_fails_the_item_without_reading_it():
    box = Box()
    with world(box):
        box.seed_live({"kind": "ok", "proposals": GOOD, "tamper": True})
        code, _, _ = jev("run", "repo-scout", "--target", TARGET)
    item = box.last()["items"][0]
    assert code == 1 and item["status"] == "failed" and "tampered" in item["reason"], item
    d = box.latest() / "items" / "bamr87__SCHEMA"
    assert "not inspected" in (d / "tree.txt").read_text() and not (d / "outputs").exists()


def test_a_symlinked_output_is_refused_unread():
    box = Box()
    with world(box):
        box.seed_live({"kind": "ok", "symlink": "/etc/hosts"})
        code, _, _ = jev("run", "repo-scout", "--target", TARGET)
    item = box.last()["items"][0]
    assert code == 1 and item["status"] == "rejected" and "symlink" in item["reason"], item
    assert not list((box.latest() / "items").rglob("hosts"))


def test_tracked_edits_are_discarded_and_local_paths_withheld_and_sandbox_denials_flagged():
    box = Box()
    home_leak = {**GOOD[0], "title": "Fix the path in the build script for this host",
                 "body": GOOD[0]["body"] + f" see {Path.home()}/notes.txt"}
    offline = {**GOOD[1], "title": "Installs fail with a resolver error in CI",
               "body": GOOD[1]["body"] + " npm ERR! getaddrinfo EAI_AGAIN registry.npmjs.org"}
    with world(box):
        box.seed_live({"kind": "ok", "proposals": [home_leak, offline], "tracked_edit": True})
        code, _, err = jev("run", "repo-scout", "--target", TARGET)
    assert code == 0, err
    item = box.last()["items"][0]
    flags = " ".join(item.get("flags") or [])
    assert "tracked edits discarded: README.md" in flags and "local-runner denial" in flags, flags
    assert item["would_file"] == 1 and any(r["reason"].startswith("carries a local path")
                                           for r in item["facts"]["rejected"])
    d = box.latest() / "items" / "bamr87__SCHEMA"
    assert str(Path.home()) not in "".join(p.read_text() for p in (d / "bodies").glob("*.md"))


def test_tier0_reuses_a_completed_attempt_at_zero_cost_and_skips_it_once_published():
    box = Box()
    with world(box, FLEET_TOKEN=FLEET_TOKEN):
        box.seed_live({"kind": "ok", "proposals": GOOD})
        assert jev("run", "repo-scout", "--target", TARGET)[0] == 0
        code, _, err = jev("run", "repo-scout", "--target", TARGET)
        item = box.last()["items"][0]
        assert code == 0 and item["decision"] == "tier0-reuse" and item["status"] == "previewed", (item, err)
        assert len(box.live_calls()) == 1, "the reuse made no claude call"
        assert (box.latest() / "items" / "bamr87__SCHEMA" / "publish-plan.json").is_file()
        assert jev("publish", box.last()["run_id"], "--apply")[0] == 0
        code, _, _ = jev("run", "repo-scout", "--target", TARGET)
        assert box.last()["items"][0]["status"] == "skipped", "a published attempt is not filed twice"
        code, _, _ = jev("run", "repo-scout", "--target", TARGET, "--fresh")
        assert box.last()["items"][0]["decision"] == "attempt" and len(box.live_calls()) == 2


def test_a_live_run_refuses_without_a_passing_canary_and_reduced_needs_none():
    box = Box()
    with world(box):
        box.seed_live({"kind": "ok", "proposals": GOOD, "bash": 0}, canary=False)
        code, _, _ = jev("run", "repo-scout", "--target", TARGET)
        assert code == 4 and any("canary" in n for n in box.last()["notes"]) and not box.live_calls()
        box.seed_probe(posture="reduced")
        code, _, err = jev("run", "repo-scout", "--target", TARGET, "--posture", "reduced")
    assert code == 0 and box.last()["items"][0]["status"] == "previewed", err
    [call] = box.live_calls()
    tools = call["argv"][call["argv"].index("--tools") + 1]
    assert "Bash" not in tools and "sandbox" not in json.loads(
        (box.latest() / "items" / "bamr87__SCHEMA" / "settings.json").read_text())


def test_doctor_live_runs_the_canary_only_with_a_yes_and_judges_it():
    box = Box()
    with world(box):
        code, _, err = jev("doctor", "--live")
        assert code == 2 and "--yes" in err and not box.live_calls(), "no terminal, no --yes: refused"
        assert jev("doctor", "--live", "--yes", "--posture", "reduced")[0] == 2
        (box.bin / "scenario.json").write_text(json.dumps({"kind": "canary_pass"}))
        code, out, err = jev("doctor", "--live", "--yes", "--json")
        report = json.loads(out)
        assert code == 0 and report["steps"][0]["canary"] == "ok", (report, err)
        spec = L.load_step("repo-scout")
        key = L.canary_key((2, 1, 308), spec, H.Posture("sandbox"), H.AuthChoice("oauth", "env"))
        entry = L.cached(".canary.json", key)
        assert entry["ok"] is True and entry["credential_env"] == "CLAUDE_CODE_OAUTH_TOKEN", entry
        assert entry["facts"]["outside_planted"] and entry["facts"]["fences"]["read"] == "denyOnly(3)"
        assert key.endswith("|cred=CLAUDE_CODE_OAUTH_TOKEN") and L.cached(".canary.json", L.canary_key(
            (2, 1, 308), spec, H.Posture("sandbox"), H.AuthChoice("oauth", "login"))) is None
        [call] = box.live_calls()
        assert call["argv"][call["argv"].index("--model") + 1] == L.CANARY_MODEL
        assert call["argv"][call["argv"].index("--max-turns") + 1] == str(L.CANARY_TURNS)
        [row] = box.ledger_rows()
        assert row["item"] == "canary" and row["loop"] == "repo-scout" and row["cap_usd"] == 0.1
        assert not (box.root / "canary" / "secret.txt").exists(), "the planted secret is removed"
        assert not list((box.root / "private").iterdir()), "and so is its copy outside home"
        (box.bin / "scenario.json").write_text(json.dumps({"kind": "canary_leak"}))
        code, out, _ = jev("doctor", "--live", "--yes", "--json")
        step = json.loads(out)["steps"][0]
        assert code == 4 and step["canary"] == "failed"
        assert any("planted secret reached" in p for p in step["canary_problems"]), step["canary_problems"]
        assert L.cached(".canary.json", key)["ok"] is False
        (box.bin / "scenario.json").write_text(json.dumps({"kind": "canary_env_leak"}))
        code, out, _ = jev("doctor", "--live", "--yes", "--json")
        step = json.loads(out)["steps"][0]
        assert code == 4 and any("SECRET_ENV visible" in p and "CLAUDE_CODE_OAUTH_TOKEN" in p
                                 for p in step["canary_problems"]), step["canary_problems"]


def test_doctor_live_at_the_ceiling_or_with_the_lock_held_runs_no_canary_and_says_so():
    box = Box()
    month = L.now_utc().strftime("%Y-%m")
    with world(box):
        (box.bin / "scenario.json").write_text(json.dumps({"kind": "canary_pass"}))
        _seed_ledger(box, [{"timestamp": f"{month}-01T00:30:00+00:00", "origin": "local", "loop": "repo-scout",
                            "total_cost_usd": 25.0, "cost_source": "reported"}])
        code, out, _ = jev("doctor", "--live", "--yes", "--json")
        step = json.loads(out)["steps"][0]
        assert code == 1 and any("canary not run" in p for p in step["problems"]), step
        (box.root / "ledger.json").unlink()
        with (box.root / "ledger.json.loops.lock").open("a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            code, out, _ = jev("doctor", "--live", "--yes", "--json")
        assert code == 1 and any("budget lock" in p for p in json.loads(out)["steps"][0]["problems"])
    assert not box.live_calls(), "a canary the month cannot absorb, or that another attempt races, never runs"


def test_a_canary_passed_on_a_stored_login_does_not_unlock_a_run_that_carries_a_credential():
    box = Box()
    with world(box):
        box.seed_live({"kind": "ok", "proposals": GOOD}, auth=H.AuthChoice("oauth", "login"))
        code, _, _ = jev("run", "repo-scout", "--target", TARGET)
        assert code == 4 and any("CLAUDE_CODE_OAUTH_TOKEN" in n and "canary" in n for n in box.last()["notes"])
        assert not box.live_calls()
        box.seed_live({"kind": "ok", "proposals": GOOD})
        assert jev("run", "repo-scout", "--target", TARGET)[0] == 0, "the env-token canary unlocks the env-token run"


# --------------------------------------------------------------------------- #
# the ceiling, the in-flight record and the backstop
# --------------------------------------------------------------------------- #
def test_at_the_ceiling_a_tier0_reuse_still_runs_at_zero_cost():
    box = Box()
    month = L.now_utc().strftime("%Y-%m")
    with world(box):
        box.seed_live({"kind": "ok", "proposals": GOOD})
        assert jev("run", "repo-scout", "--target", TARGET)[0] == 0
        rows = json.loads((box.root / "ledger.json").read_text())["runs"]
        rows["over"] = {"timestamp": f"{month}-01T00:30:00+00:00", "origin": "local", "loop": "repo-scout",
                        "total_cost_usd": 24.5, "cost_source": "reported"}
        _seed_ledger(box, list(rows.values()))
        code, _, err = jev("run", "repo-scout", "--target", TARGET)
    item = box.last()["items"][0]
    assert code == 0 and item["decision"] == "tier0-reuse" and item["status"] == "previewed", (item, err)
    assert len(box.live_calls()) == 1 and box.last()["status"] == "done", "the $0 reuse made no claude call"


def test_the_ceiling_is_read_afresh_before_each_attempt_and_held_under_the_budget_lock():
    box = Box()
    month = L.now_utc().strftime("%Y-%m")
    with world(box):
        spec = L.load_step("repo-scout")
        ctx = L.RunContext(spec=spec, adapter=None, fleet=S.load_fleet(), opts=L.Options(),
                           plan_dir=box.root / "plan", history=L.History(box.runs))
        ctx.budget = L.budget_position(ctx.fleet, scheduled=False)
        assert ctx.budget.spent_usd == 0 and L.budget_block(ctx, True) is None
        # another run (another step, another checkout) ledgers $20 while this one holds a stale $0
        _seed_ledger(box, [{"timestamp": f"{month}-01T00:30:00+00:00", "origin": "local", "loop": "repo-scout",
                            "total_cost_usd": 12.0, "cost_source": "reported"}])
        ctx.unledgered.append((8.0, "estimated"))
        blocked = L.budget_block(ctx, True)
        assert blocked and blocked[0] == "budget-skip" and ctx.budget.spent_usd == 20.0, (blocked, ctx.budget)
        assert ctx.budget.estimated_usd == 8.0, "an unledgered charge is added back to the fresh read"
        assert "budget lock" in L.budget_block(ctx, False)[1]
        (box.root / "ledger.json").write_text("{not json")
        assert "cannot be read" in L.budget_block(ctx, True)[1], "an unreadable ledger skips, it never spends"
        box.seed_live({"kind": "ok", "proposals": GOOD})
        (box.root / "ledger.json").unlink()
        with (box.root / "ledger.json.loops.lock").open("a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            code, _, _ = jev("run", "repo-scout", "--target", TARGET)
    item = box.last()["items"][0]
    assert code == 0 and item["decision"] == "budget-skip" and "budget lock" in item["reason"], item
    assert not box.live_calls()


def test_budget_position_counts_by_utc_month_and_refuses_a_foreign_ledger():
    box = Box()
    start = L.now_utc().replace(day=1, hour=0, minute=30, second=0, microsecond=0)
    west = start.astimezone(dt.timezone(dt.timedelta(hours=-5)))     # last month locally, this month in UTC
    east = (start - dt.timedelta(hours=2)).astimezone(dt.timezone(dt.timedelta(hours=5)))   # the reverse
    row = {"origin": "local", "loop": "repo-scout", "cost_source": "reported"}
    with world(box):
        _seed_ledger(box, [{**row, "timestamp": west.isoformat(), "total_cost_usd": 3.0},
                           {**row, "timestamp": east.isoformat(), "total_cost_usd": 100.0}])
        assert west.strftime("%Y-%m") != start.strftime("%Y-%m") == east.strftime("%Y-%m")
        assert L.budget_position(S.load_fleet(), scheduled=False).spent_usd == 3.0
        for bad in ('{"version": 2, "runs": {}}', "[]", "null"):
            (box.root / "ledger.json").write_text(bad)
            try:
                L.budget_position(S.load_fleet(), scheduled=False)
            except common.JevError as exc:
                assert "cannot" in str(exc), exc
            else:
                raise AssertionError(f"{bad} read as an empty month")
    sys.path.insert(0, str(HUB / ".github" / "scripts" / "dash-gen"))
    import ai_activity
    assert L.LEDGER_VERSION == ai_activity.LEDGER_VERSION


def test_an_unreadable_ledger_stays_unreadable_after_a_writer_tried_it():
    box = Box()
    sys.path.insert(0, str(HUB / ".github" / "scripts" / "dash-gen"))
    import ai_activity
    path = box.root / "ledger.json"
    for bad in ("{truncated", '{"version": 2, "runs": {"r": {"total_cost_usd": 20}}}', "[]"):
        path.write_text(bad)
        for write in (lambda: ai_activity.merge_ledger(path, {}, {}),
                      lambda: ai_activity.record_run(path, {"timestamp": "t", "session_id": "s"})):
            try:
                write()
            except ai_activity.LedgerUnreadable:
                pass
            else:
                raise AssertionError(f"a writer overwrote {bad!r}")
            assert path.read_text() == bad, "the bytes are untouched"
        with world(box):
            try:
                L.budget_position(S.load_fleet(), scheduled=False)
            except common.JevError:
                pass
            else:
                raise AssertionError("the ceiling read a refused ledger as an empty month")


def test_an_ai_run_that_dies_without_an_outcome_is_charged_at_the_cap_and_fails_as_attention():
    box = Box()
    with world(box, JEV_TEST_AI_RUN_DIES="1"):
        box.seed_live({"kind": "ok", "proposals": GOOD})
        code, _, _ = jev("run", "repo-scout", "--target", TARGET)
    rec = box.last()
    item = rec["items"][0]
    assert code == 1 and item["status"] == "failed" and item["outcome"] == "unparseable", item
    assert "claude may not have run" in item["reason"] and "init" not in item["reason"], item["reason"]
    assert rec["budget"]["after"]["spent_usd"] == 8.0 and item["cost_source"] == "estimated"
    [row] = [r for r in box.attempts() if r.get("outcome")]
    assert row["cost_usd"] == 8.0 and row["cost_source"] == "estimated" and not box.ledger_rows()


def _short_clock(seconds: float):
    """L.load_step with the spec's wall clock cut to `seconds`."""
    real = L.load_step

    def short(*a, **k):
        return dataclasses.replace(real(*a, **k), timeout_minutes=seconds / 60)
    return real, short


def test_a_wall_clock_before_init_fails_the_item_not_the_host():
    box = Box()
    real, L.load_step = _short_clock(2)
    try:
        with world(box):
            box.seed_live({"kind": "ok", "hang_before_init": 30})
            code, _, _ = jev("run", "repo-scout", "--target", TARGET)
    finally:
        L.load_step = real
    item = box.last()["items"][0]
    assert code == 1 and item["status"] == "failed" and item["outcome"] == "timeout", item
    [row] = box.ledger_rows()
    assert row["cost_source"] == "estimated" and row["total_cost_usd"] == 8.0, "still charged at the cap"
    assert box.last()["status"] == "done", "a hung executor is attention, not a host-safety stop"


def test_a_ctrl_c_during_an_attempt_records_the_item_and_its_spend():
    box = Box()
    real = L.relay_dash_gen

    def interrupted(*a, **k):
        real(*a, **k)            # ai-run finishes, writes its outcome and its ledger row
        raise KeyboardInterrupt
    L.relay_dash_gen = interrupted
    try:
        with world(box):
            box.seed_live({"kind": "ok", "proposals": GOOD, "cost": 0.61})
            code, _, err = jev("run", "repo-scout", "--target", TARGET)
    finally:
        L.relay_dash_gen = real
    rec = box.last()
    assert code == 130 and rec["status"] == "interrupted", (code, rec["status"], err)
    [item] = rec["items"]
    assert item["status"] == "interrupted" and item["cost_usd"] == 0.61 and item["cost_source"] == "reported", item
    [row] = box.ledger_rows()
    assert rec["totals"]["spent_usd"] == rec["budget"]["after"]["spent_usd"] == row["total_cost_usd"] == 0.61
    assert [r["status"] for r in box.attempts() if r.get("outcome")] == ["interrupted"]
    assert "$0.61 spent" in err and not list(box.work.glob("*/*")), "the clone is destroyed"


def test_a_sigterm_to_the_engine_ends_the_run_interrupted_with_its_record():
    box = Box()
    with world(box):
        box.seed_live({"kind": "ok", "proposals": GOOD, "sleep": 2})

        def cancel() -> None:
            for _ in range(600):
                if (box.bin / "live.jsonl").exists():
                    os.kill(os.getpid(), signal.SIGTERM)   # the console's cancel, minus the group
                    return
                time.sleep(0.05)
        t = threading.Thread(target=cancel)
        t.start()
        code, _, _ = jev("run", "repo-scout", "--target", TARGET)
        t.join()
    rec = box.last()
    assert code == 130 and rec["status"] == "interrupted" and rec["exit_code"] == 130, (code, rec["status"])
    assert rec["items"][0]["status"] == "interrupted" and rec["items"][0]["cost_usd"] == 0.61
    assert not list(box.work.glob("*/*")), "the clone is destroyed"
    assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL, "the handler is restored"


def test_the_backstop_terminates_ai_run_before_it_kills_it():
    d = Path(tempfile.mkdtemp())
    marker = d / "got-sigterm"
    script = d / "dash-gen"
    script.write_text(f"#!{sys.executable}\nimport signal, sys, time\n"
                      f"def on(*_):\n    open({str(marker)!r}, 'w').write('1'); sys.exit(0)\n"
                      "signal.signal(signal.SIGTERM, on)\ntime.sleep(30)\n")
    script.chmod(0o755)
    stubborn = d / "stubborn"
    stubborn.write_text(f"#!{sys.executable}\nimport signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                        "time.sleep(30)\n")
    stubborn.chmod(0o755)
    saved = (L.DASH_GEN, L.BACKSTOP_KILL_S)
    try:
        L.DASH_GEN, L.BACKSTOP_KILL_S = script, 10
        res = L.relay_dash_gen(["ai-run"], env=dict(os.environ), timeout=0.5)
        assert marker.exists() and res.code == 0, "SIGTERM first: ai-run's own ladder gets to settle the session"
        assert "backstop stopped ai-run" in res.err
        L.DASH_GEN, L.BACKSTOP_KILL_S = stubborn, 0.5
        started = time.monotonic()
        res = L.relay_dash_gen(["ai-run"], env=dict(os.environ), timeout=0.5)
        assert res.code == -signal.SIGKILL and time.monotonic() - started < 10, "then SIGKILL"
    finally:
        L.DASH_GEN, L.BACKSTOP_KILL_S = saved


def test_tier0_reuse_rehashes_the_earlier_validated_copy():
    box = Box()
    with world(box):
        box.seed_live({"kind": "ok", "proposals": GOOD})
        assert jev("run", "repo-scout", "--target", TARGET)[0] == 0
        first = box.latest() / "items" / "bamr87__SCHEMA" / "outputs" / "proposals.validated.json"
        first.write_text(first.read_text().replace("version", "VERSION"))
        code, _, err = jev("run", "repo-scout", "--target", TARGET)
    item = box.last()["items"][0]
    assert code == 0 and item["decision"] == "attempt" and len(box.live_calls()) == 2, (item, err)
    assert "gone or changed" in err


# --------------------------------------------------------------------------- #
# the posture checks' fail-closed branches
# --------------------------------------------------------------------------- #
def test_a_session_that_spent_with_no_init_record_stops_the_run_with_4():
    box = Box()
    with world(box):
        box.seed_live({"kind": "ok", "proposals": GOOD, "no_init": True, "cost": 0.4})
        code, _, _ = jev("run", "repo-scout", "--target", TARGET)
    item = box.last()["items"][0]
    assert code == 4 and item["status"] == "unsafe" and "no init record" in item["reason"], item


def test_bash_under_the_reduced_posture_stops_the_run_with_4():
    box = Box()
    with world(box, sandbox=False):
        box.seed_live({"kind": "ok", "proposals": GOOD, "bash": 2}, posture="reduced")
        code, _, _ = jev("run", "repo-scout", "--target", TARGET, "--posture", "reduced")
    item = box.last()["items"][0]
    assert code == 4 and item["status"] == "unsafe" and "reduced posture" in item["reason"], item


def test_only_bash_that_executed_needs_the_sandbox_line_and_it_must_show_both_fences():
    box = Box()
    with world(box):
        box.seed_live({"kind": "ok", "proposals": GOOD, "bash": 0, "denied_bash": 1})
        code, _, err = jev("run", "repo-scout", "--target", TARGET)
        item = box.last()["items"][0]
        assert code == 0 and item["status"] == "previewed", (item, err)
        assert any("permission denial" in f for f in item.get("flags") or []), "the denial is still flagged"
        box.seed_live({"kind": "ok", "proposals": GOOD, "bash": 1, "denied_bash": 1, "sandbox_line": False})
        code, _, _ = jev("run", "repo-scout", "--target", TARGET, "--fresh")
        item = box.last()["items"][0]
        assert code == 4 and "executed 1 time(s)" in item["reason"], item
        box.seed_live({"kind": "ok", "proposals": GOOD, "fences": "read: none, write: allowOnly(2)"})
        code, _, _ = jev("run", "repo-scout", "--target", TARGET, "--fresh")
        item = box.last()["items"][0]
        assert code == 4 and item["status"] == "unsafe" and "no read fence" in item["reason"], item


def test_an_on_budget_hit_the_engine_does_not_implement_fails_closed():
    box = Box()
    real = L.load_step

    def flagged(*a, **k):
        spec = real(*a, **k)
        return dataclasses.replace(spec, local=dataclasses.replace(spec.local, on_budget_hit="publish-flagged"))
    L.load_step = flagged
    try:
        with world(box):
            box.seed_live({"kind": "budget_hit", "proposals": GOOD})
            code, _, _ = jev("run", "repo-scout", "--target", TARGET)
    finally:
        L.load_step = real
    item = box.last()["items"][0]
    assert code == 1 and item["status"] == "failed" and "no engine behaviour" in item["reason"], item
    assert not (box.latest() / "items" / "bamr87__SCHEMA" / "outputs").exists()


# --------------------------------------------------------------------------- #
# the publish gate's fail-closed branches
# --------------------------------------------------------------------------- #
def test_a_dedupe_unavailable_at_the_live_recheck_files_nothing():
    box = Box()
    with world(box, FLEET_TOKEN=FLEET_TOKEN):
        box.seed_live({"kind": "ok", "proposals": GOOD})
        assert jev("run", "repo-scout", "--target", TARGET)[0] == 0
        run_id = box.last()["run_id"]
        listed = sum(1 for c in box.gh_calls() if c[:2] == ["issue", "list"])
    with world(box, FLEET_TOKEN=FLEET_TOKEN, STUB_GH_LIST_FAIL_FROM=str(listed + 2)):
        code, out, _ = jev("publish", run_id, "--apply")
    assert code == 1 and out.startswith("publish-skipped"), out
    assert not _issue_creates(box)


def test_a_concurrent_apply_that_claims_the_result_first_is_refused():
    box = Box()
    real = L._fresh_dry

    def racing(ctx, item, validated):
        out = real(ctx, item, validated)
        (ctx.item_dir(item) / "publish-result.json").write_text("{}")   # the other apply got there first
        return out
    with world(box, FLEET_TOKEN=FLEET_TOKEN):
        box.seed_live({"kind": "ok", "proposals": GOOD})
        assert jev("run", "repo-scout", "--target", TARGET)[0] == 0
        run_id = box.last()["run_id"]
        L._fresh_dry = racing
        try:
            code, out, _ = jev("publish", run_id, "--apply")
        finally:
            L._fresh_dry = real
    assert code == 2 and "concurrent apply" in out and not _issue_creates(box), out


def test_a_partial_filing_counts_as_published_and_tier0_skips_it():
    box = Box()
    with world(box, FLEET_TOKEN=FLEET_TOKEN, STUB_GH_CREATE_FAIL_AFTER="1"):
        box.seed_live({"kind": "ok", "proposals": GOOD})
        code, _, _ = jev("run", "repo-scout", "--target", TARGET, "--apply")
        item = box.last()["items"][0]
        assert code == 1 and item["status"] == "partial" and item["published"] == 1, item
        [row] = [r for r in box.attempts() if r["decision"] == "publish-apply"]
        assert row["published"] is True and row["filed"] == 1 and len(row["failures"]) == 1
        code, _, _ = jev("run", "repo-scout", "--target", TARGET)
    assert box.last()["items"][0]["decision"] == "tier0-skip" and len(box.live_calls()) == 1


def test_labels_that_changed_since_the_preview_are_refused():
    box = Box()
    edited = box.root / "fleet.yml"
    data = yaml.safe_load((HUB / "_data" / "fleet.yml").read_text())
    data["scout"]["label"] = "UNREVIEWED-label"
    edited.write_text(yaml.safe_dump(data, sort_keys=False))
    with world(box, FLEET_TOKEN=FLEET_TOKEN):
        box.seed_live({"kind": "ok", "proposals": GOOD})
        assert jev("run", "repo-scout", "--target", TARGET)[0] == 0
        run_id = box.last()["run_id"]
    with world(box, FLEET_TOKEN=FLEET_TOKEN, JEV_TEST_FILE_CONFIG=str(edited)):
        code, out, _ = jev("publish", run_id)
        assert code == 0 and "DIFFERS" in out and "labels that were not reviewed" in out, out
        code, out, _ = jev("publish", run_id, "--apply")
    assert code == 2 and "labels that were not reviewed" in out, out
    assert not _issue_creates(box) and not [c for c in box.gh_calls() if c[:2] == ["label", "create"]]


def test_two_previews_of_one_attempt_are_never_both_filed():
    box = Box()
    with world(box, FLEET_TOKEN=FLEET_TOKEN):
        box.seed_live({"kind": "ok", "proposals": GOOD})
        assert jev("run", "repo-scout", "--target", TARGET)[0] == 0
        run_a = box.last()["run_id"]
        assert jev("run", "repo-scout", "--target", TARGET)[0] == 0
        run_b = box.last()["run_id"]
        assert box.last()["items"][0]["decision"] == "tier0-reuse" and run_a != run_b
        assert jev("publish", run_a, "--apply")[0] == 0 and len(_issue_creates(box)) == 2
        code, out, _ = jev("publish", run_b, "--apply")
    assert code == 2 and f"already published in run {run_a}" in out, out
    assert len(_issue_creates(box)) == 2, "the closed-then-refiled duplicate cannot happen"


def test_loop_budget_prints_both_ceilings_labelled():
    box = Box()
    with world(box):
        code, out, _ = jev("budget")
    assert code == 0 and "budget.loops" in out and "budget.jev" in out and "API-equivalent (estimate)" in out


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
