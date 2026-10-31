#!/usr/bin/env python3
"""
End-to-end tests for `dash ai run` (`dash-gen ai-run`, ai_activity.run_headless)
— the capped, ledgered headless executor that humans and JEV's local loop
runner both use (docs/adr/0002, P1).

Every run here is against a STUB `claude` written into a temporary directory,
with a temporary ledger (`--ledger`, DASH_AI_LEDGER) and a temporary .env
(JEV_DOTENV): nothing reaches a model, nothing touches ~/.claude.

What is held:
  * the cap: `--call-site` takes budget.call_sites, `--max-budget-usd` may only
    lower it, and the passthrough cannot carry a cap, an output format, print
    mode or a permission bypass;
  * a run that leaves no result is still ONE ledger row — charged at the cap as
    `estimated` once the session started, `no-spend` when the CLI refused its
    own argv — keyed by the session id the wrapper chose;
  * `--stream` tees a condensed, redacted view; `--trace` is redacted;
    `--result-file` is what claude-cost's jq reads; `--outcome-file` classifies;
  * `--isolate` builds claude's environment from scratch while ai-run itself
    keeps PYTHONPATH (PyYAML imports only through it on the maintainer's Mac);
    `--auth-order` leaves exactly one credential;
  * `--timeout` is SIGINT-first and exits 124; a usage limit is a warning
    under `--usage-limit skip`;
  * record_run and merge_ledger lose no row to a concurrent writer;
  * `_headless_section` never counts an estimate as billed.

Run: python3 .github/scripts/dash-gen/test_ai_run.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ai_activity  # noqa: E402

DASH_GEN = HERE / "dash_gen.py"
OAUTH, KEY = "sk-ant-oat01-" + "o" * 40, "sk-ant-api03-" + "k" * 40
GH = "gho_" + "g" * 36
CLAUDE_COST_JQ = '[.. | objects | select(.type? == "result")] | last'

STUB = textwrap.dedent(r'''
    #!__PY__
    """A stand-in for `claude`, steered by a `scenario` file beside it."""
    import json, os, signal, sys, time
    HERE = os.path.dirname(os.path.abspath(__file__))
    argv = sys.argv[1:]
    if argv[:1] == ["--version"]:
        print("2.1.308 (Claude Code)"); sys.exit(0)
    if argv[:2] == ["auth", "status"]:
        print(json.dumps({"loggedIn": os.path.exists(os.path.join(HERE, "logged_in")), "authMethod": "claude.ai"}))
        sys.exit(0)
    with open(os.path.join(HERE, "argv.json"), "w") as fh:
        json.dump(argv, fh)
    with open(os.path.join(HERE, "env.json"), "w") as fh:
        kept = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "TMPDIR", "GH_CONFIG_DIR")
        json.dump({k: os.environ[k] for k in os.environ if k in kept} | {"_keys": sorted(os.environ)}, fh)
    try:
        scenario = open(os.path.join(HERE, "scenario")).read().strip()
    except OSError:
        scenario = "ok"
    prompt = sys.stdin.read() if not sys.stdin.isatty() else ""
    with open(os.path.join(HERE, "stdin.txt"), "w") as fh:
        fh.write(prompt)
    stream = "stream-json" in argv
    sid = argv[argv.index("--session-id") + 1] if "--session-id" in argv else "stub-session"
    cap = float(argv[argv.index("--max-budget-usd") + 1])
    def emit(o):
        sys.stdout.write(json.dumps(o) + "\n"); sys.stdout.flush()
    def init():
        if stream:
            emit({"type": "system", "subtype": "init", "session_id": sid, "model": "claude-sonnet-5-5",
                  "tools": ["Bash", "Read"], "permissionMode": "dontAsk"})
    ok = {"type": "result", "subtype": "success", "is_error": False, "num_turns": 3, "session_id": sid,
          "total_cost_usd": 0.61, "result": "proposals written",
          "modelUsage": {"claude-sonnet-5-5": {"inputTokens": 100, "outputTokens": 20},
                         "claude-haiku-5-5": {"inputTokens": 3, "outputTokens": 1}}}
    if scenario == "startup":
        sys.stderr.write("error: unknown option '--frobnicate'\n"); sys.exit(1)
    if scenario == "init_then_exit":
        init(); sys.exit(1)
    if scenario in ("int_no_result", "int_result"):
        def on_int(*_):
            if scenario == "int_result":
                emit({**ok, "subtype": "error_during_execution", "is_error": True, "total_cost_usd": 0.42})
            sys.exit(130)
        signal.signal(signal.SIGINT, on_int)
        init()
        while True:
            time.sleep(0.05)
    init()
    if scenario == "usage":
        emit({**ok, "is_error": True, "api_error_status": 429, "total_cost_usd": 0, "modelUsage": {},
              "result": "Claude AI usage limit reached"}); sys.exit(1)
    if scenario == "notloggedin":
        emit({**ok, "is_error": True, "total_cost_usd": 0, "modelUsage": {}, "num_turns": 1,
              "result": "Not logged in · Please run /login", "terminal_reason": "api_error"}); sys.exit(1)
    if scenario == "budget":
        emit({**ok, "subtype": "error_max_budget_usd", "is_error": True, "total_cost_usd": cap}); sys.exit(0)
    if stream:
        secret = os.environ.get("GH_TOKEN", "none")
        emit({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "git status"}},
            {"type": "text", "text": "saw " + secret + " and ghp_" + "Z" * 36}]}})
    emit(ok)
''').lstrip()


class Rig:
    """A stub claude, a temp ledger, a temp .env and a temp cwd for one test."""

    def __init__(self, scenario: str = "ok", *, logged_in: bool = False, dotenv: str = ""):
        self.dir = Path(tempfile.mkdtemp(prefix="ai-run-test-"))
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        self.claude = self.bin / "claude"
        self.claude.write_text(STUB.replace("__PY__", sys.executable), encoding="utf-8")
        self.claude.chmod(0o755)
        (self.bin / "scenario").write_text(scenario)
        if logged_in:
            (self.bin / "logged_in").write_text("1")
        self.ledger = self.dir / "ledger.json"
        self.dotenv = self.dir / ".env"
        self.dotenv.write_text(dotenv)
        self.cwd = self.dir / "work"
        self.cwd.mkdir()

    def run(self, *flags: str, passthrough: tuple[str, ...] = ("hello",), env: dict | None = None,
            timeout: float = 60) -> subprocess.CompletedProcess:
        scrubbed = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "CLAUDE_AUTH_ORDER", "GH_TOKEN")
        base = {k: v for k, v in os.environ.items() if k not in scrubbed}
        base.update({"DASH_AI_LEDGER": str(self.ledger), "JEV_DOTENV": str(self.dotenv)})
        base.update(env or {})
        argv = [sys.executable, str(DASH_GEN), "ai-run", "--claude-bin", str(self.claude), "--ledger",
                str(self.ledger), "--cwd", str(self.cwd), *flags, "--", *passthrough]
        return subprocess.run(argv, env=base, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=timeout, check=False)

    def rows(self) -> list[dict]:
        if not self.ledger.exists():
            return []
        return list(json.loads(self.ledger.read_text())["runs"].values())

    def argv(self) -> list[str]:
        return json.loads((self.bin / "argv.json").read_text())

    def child_env(self) -> dict:
        return json.loads((self.bin / "env.json").read_text())


def opt(argv: list[str], name: str) -> str:
    return argv[argv.index(name) + 1]


# --------------------------------------------------------------------------- #
# the cap
# --------------------------------------------------------------------------- #
def test_a_plain_run_behaves_as_before_and_records_a_reported_row():
    rig = Rig()
    out = rig.run()
    assert out.returncode == 0, out.stderr
    assert out.stdout == "proposals written\n"
    argv = rig.argv()
    assert argv[:3] == ["-p", "--output-format", "json"] and opt(argv, "--max-budget-usd") == "5"
    assert argv[-1] == "hello"
    [row] = rig.rows()
    assert set(row) == set(ai_activity.RUN_FIELDS)
    assert row["total_cost_usd"] == 0.61 and row["cost_source"] == "reported" and row["outcome"] == "ok"
    assert row["call_site"] == "local" and row["origin"] == "local" and row["cap_usd"] == 5.0
    assert row["session_id"] == opt(argv, "--session-id"), "the wrapper's session id is the row key"
    assert row["models"] == ["claude-haiku-5-5", "claude-sonnet-5-5"] and row["cli_version"] == "2.1.308"


def test_the_call_site_sets_the_cap_and_may_only_be_lowered():
    rig = Rig()
    assert rig.run("--call-site", "repo-scout.yml:scout").returncode == 0
    assert opt(rig.argv(), "--max-budget-usd") == "8"
    assert rig.rows()[0]["call_site"] == "repo-scout.yml:scout" and rig.rows()[0]["cap_usd"] == 8.0
    assert rig.run("--call-site", "repo-scout.yml:scout", "--max-budget-usd", "3").returncode == 0
    assert opt(rig.argv(), "--max-budget-usd") == "3"
    higher = rig.run("--call-site", "repo-scout.yml:scout", "--max-budget-usd", "9")
    assert higher.returncode == 2 and "may only be lowered" in higher.stderr
    unknown = rig.run("--call-site", "nope.yml:job")
    assert unknown.returncode == 2 and "budget.call_sites" in unknown.stderr


def test_the_passthrough_cannot_carry_a_cap_a_format_print_mode_or_a_bypass():
    rig = Rig()
    for bad in (("--max-budget-usd", "50"), ("--output-format", "text"), ("-p",), ("--print",),
                ("--dangerously-skip-permissions",), ("--permission-mode", "bypassPermissions"),
                ("--permission-mode=bypassPermissions",)):
        out = rig.run(passthrough=(*bad, "hello"))
        assert out.returncode == 2 and "refusing" in out.stderr, bad
    assert rig.rows() == [] and not (rig.bin / "argv.json").exists()


def test_a_dry_run_runs_and_records_nothing():
    rig = Rig()
    out = rig.run("--dry-run", "--call-site", "repo-scout.yml:scout")
    assert out.returncode == 0 and "cap: $8.00" in out.stderr
    assert rig.rows() == [] and not (rig.bin / "argv.json").exists()


def test_bad_meta_is_refused_and_good_meta_is_recorded():
    rig = Rig()
    assert rig.run("--meta", "total_cost_usd=0").returncode == 2
    assert rig.run("--meta", "loop=a", "--meta", "loop=b").returncode == 2
    assert rig.run("--meta", "loop=repo-scout", "--meta", "run_id=r1", "--meta", "tier=t1",
                   "--repo", "bamr87/SCHEMA").returncode == 0
    [row] = rig.rows()
    assert (row["loop"], row["run_id"], row["tier"], row["repo"]) == ("repo-scout", "r1", "t1", "bamr87/SCHEMA")


# --------------------------------------------------------------------------- #
# streaming, the trace, the result and outcome files
# --------------------------------------------------------------------------- #
def test_stream_tees_a_redacted_view_and_writes_the_three_files():
    rig = Rig()
    (rig.dir / "prompt.txt").write_text("the prompt\n")
    files = {k: rig.dir / f"{k}.json" for k in ("result", "outcome")}
    trace = rig.dir / "trace.jsonl"
    out = rig.run("--stream", "--prompt-file", str(rig.dir / "prompt.txt"), "--trace", str(trace),
                  "--result-file", str(files["result"]), "--outcome-file", str(files["outcome"]),
                  passthrough=(), env={"GH_TOKEN": GH})
    assert out.returncode == 0, out.stderr
    argv = rig.argv()
    assert argv[:4] == ["-p", "--output-format", "stream-json", "--verbose"]
    assert (rig.bin / "stdin.txt").read_text() == "the prompt\n" and "the prompt" not in " ".join(argv)
    assert "▸ Bash" in out.stderr and "■ success turns=3" in out.stderr
    for text in (out.stderr, trace.read_text()):
        assert GH not in text and "ghp_" not in text
    assert "[REDACTED:GH_TOKEN]" in trace.read_text()
    result = json.loads(files["result"].read_text())
    assert result["type"] == "result" and result["total_cost_usd"] == 0.61
    jq = shutil.which("jq")
    if jq:
        got = subprocess.run([jq, "-c", CLAUDE_COST_JQ, str(files["result"])], capture_output=True, text=True,
                             check=True).stdout
        assert json.loads(got)["total_cost_usd"] == 0.61
    outcome = json.loads(files["outcome"].read_text())
    assert outcome["kind"] == "ok" and outcome["cost_source"] == "reported" and outcome["exit_code"] == 0
    assert outcome["tool_uses"] == {"Bash": 1}


def test_a_run_with_no_result_after_init_is_charged_at_the_cap():
    rig = Rig("init_then_exit")
    outcome = rig.dir / "outcome.json"
    result = rig.dir / "result.json"
    result.write_text("{}")
    out = rig.run("--stream", "--call-site", "repo-scout.yml:scout", "--outcome-file", str(outcome),
                  "--result-file", str(result))
    assert out.returncode == 1 and "charged at the $8 cap" in out.stderr
    [row] = rig.rows()
    assert (row["outcome"], row["cost_source"], row["total_cost_usd"]) == ("unparseable", "estimated", 8.0)
    assert row["session_id"] == opt(rig.argv(), "--session-id")
    assert not result.exists(), "a stale result file is removed, never left for claude-cost to read"
    assert json.loads(outcome.read_text())["cost_source"] == "estimated"


def test_a_cli_that_refuses_its_argv_is_a_no_spend_row():
    rig = Rig("startup")
    out = rig.run("--stream")
    assert out.returncode == 1
    [row] = rig.rows()
    assert (row["outcome"], row["cost_source"], row["total_cost_usd"]) == ("startup_failed", "no-spend", 0.0)


def test_the_timeout_is_sigint_first_and_exits_124():
    rig = Rig("int_result")
    out = rig.run("--stream", "--timeout", "1")
    assert out.returncode == 124, out.stderr
    [row] = rig.rows()
    assert (row["outcome"], row["cost_source"], row["total_cost_usd"]) == ("timeout", "reported", 0.42)
    rig2 = Rig("int_no_result")
    assert rig2.run("--stream", "--timeout", "1", "--call-site", "repo-scout.yml:scout").returncode == 124
    [row] = rig2.rows()
    assert (row["outcome"], row["cost_source"], row["total_cost_usd"]) == ("timeout", "estimated", 8.0)


def test_a_usage_limit_is_a_warning_under_skip_and_a_failure_by_default():
    rig = Rig("usage")
    default = rig.run("--stream")
    assert default.returncode != 0 and "do NOT rotate" in default.stderr
    skip = rig.run("--stream", "--usage-limit", "skip")
    assert skip.returncode == 0 and "USAGE LIMIT" in skip.stderr
    assert {r["outcome"] for r in rig.rows()} == {"usage_limit"}


def test_a_refused_credential_and_a_budget_hit_are_loud():
    rig = Rig("notloggedin")
    out = rig.run("--stream")
    assert out.returncode == 1 and "CREDENTIAL REJECTED" in out.stderr
    assert rig.rows()[0]["cost_source"] == "no-spend"
    rig = Rig("budget")
    out = rig.run("--stream", "--call-site", "repo-scout.yml:scout")
    assert out.returncode == 2 and "BUDGET CAP HIT" in out.stderr
    assert rig.rows()[0]["outcome"] == "budget_hit" and rig.rows()[0]["total_cost_usd"] == 8.0


# --------------------------------------------------------------------------- #
# environment and auth
# --------------------------------------------------------------------------- #
def test_isolate_builds_claudes_env_from_scratch_while_ai_run_keeps_pythonpath():
    rig = Rig()
    pythonpath = os.pathsep.join(p for p in (os.environ.get("PYTHONPATH"), str(rig.dir / "site")) if p)
    tmp = rig.dir / "isotmp"
    out = rig.run("--isolate", "--isolate-tmp", str(tmp), "--auth-order", "oauth,api_key",
                  env={"GH_TOKEN": GH, "FLEET_TOKEN": "f" * 40, "PYTHONPATH": pythonpath,
                       "CLAUDE_CODE_OAUTH_TOKEN": OAUTH, "ANTHROPIC_API_KEY": KEY, "SSH_AUTH_SOCK": "/tmp/s"})
    assert out.returncode == 0, out.stderr
    env = rig.child_env()
    for gone in ("GH_TOKEN", "FLEET_TOKEN", "PYTHONPATH", "SSH_AUTH_SOCK", "ANTHROPIC_API_KEY", "DASH_AI_LEDGER"):
        assert gone not in env["_keys"], gone
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == OAUTH and env["TMPDIR"] == str(tmp)
    assert env["GH_CONFIG_DIR"] == str(tmp / "gh-none")
    assert rig.rows()[0]["auth_method"] == "oauth"
    assert OAUTH not in out.stderr and "oauth (env)" in out.stderr


def test_auth_order_alone_leaves_exactly_one_credential():
    rig = Rig()
    out = rig.run("--auth-order", "api_key,oauth", env={"CLAUDE_CODE_OAUTH_TOKEN": OAUTH, "ANTHROPIC_API_KEY": KEY})
    assert out.returncode == 0, out.stderr
    env = rig.child_env()
    assert env.get("ANTHROPIC_API_KEY") == KEY and "CLAUDE_CODE_OAUTH_TOKEN" not in env["_keys"]
    assert "DASH_AI_LEDGER" in env["_keys"], "without --isolate the rest of the environment is inherited"


def test_auth_falls_through_env_login_and_dotenv_without_fallback():
    rig = Rig(logged_in=True)
    assert rig.run("--isolate", env={"CLAUDE_AUTH_ORDER": "oauth"}).returncode == 0
    assert not any(k in rig.child_env()["_keys"] for k in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"))
    rig = Rig(dotenv=f"ANTHROPIC_API_KEY={KEY}\nGH_TOKEN={GH}\n")
    assert rig.run("--isolate", env={"CLAUDE_AUTH_ORDER": "oauth,api_key"}).returncode == 0
    env = rig.child_env()
    assert env.get("ANTHROPIC_API_KEY") == KEY and "GH_TOKEN" not in env["_keys"]
    nothing = Rig().run("--isolate", env={"CLAUDE_AUTH_ORDER": "oauth,api_key"})
    assert nothing.returncode == 3 and "no Claude credential" in nothing.stderr


# --------------------------------------------------------------------------- #
# the ledger
# --------------------------------------------------------------------------- #
WRITER = """
import sys
sys.path.insert(0, {here!r})
import ai_activity
from pathlib import Path
p = Path({ledger!r})
for i in range({n}):
    if {mode!r} == "merge":
        ai_activity.merge_ledger(p, {{f"box|2026-10-{{i % 28 + 1:02d}}|r|claude-sonnet-5-5": dict.fromkeys(
            ai_activity.USAGE_FIELDS, 1)}}, {{}})
    else:
        ai_activity.record_run(p, {{"timestamp": "t", "session_id": f"{{sys.argv[1]}}-{{i}}", "total_cost_usd": 0.1}})
"""


def test_concurrent_writers_lose_no_rows():
    d = Path(tempfile.mkdtemp())
    ledger = d / "ledger.json"
    n = 25
    procs = []
    for name, mode in (("a", "record"), ("b", "record"), ("c", "merge")):
        code = WRITER.format(here=str(HERE), ledger=str(ledger), n=n, mode=mode)
        procs.append(subprocess.Popen([sys.executable, "-c", code, name]))
    for p in procs:
        assert p.wait(timeout=120) == 0
    data = json.loads(ledger.read_text())
    assert len(data["runs"]) == 2 * n, f"{len(data['runs'])} of {2 * n} rows survived"
    assert len(data["usage"]) == min(n, 28)


def test_a_v1_ledger_without_the_new_fields_loads_and_estimates_are_never_billed():
    d = Path(tempfile.mkdtemp())
    ledger = d / "ledger.json"
    old = {"timestamp": "2026-09-01T00:00:00+00:00", "session_id": "old", "total_cost_usd": 1.5,
           "usage": {"turns": 2}}
    ledger.write_text(json.dumps({"version": 1, "usage": {}, "sessions": {}, "runs": {"old": old}}))
    ai_activity.record_run(ledger, {"timestamp": "2026-10-31T00:00:00+00:00", "session_id": "est",
                                    "total_cost_usd": 8.0, "cost_source": "estimated", "outcome": "timeout"})
    ai_activity.record_run(ledger, {"timestamp": "2026-10-31T00:00:01+00:00", "session_id": "free",
                                    "total_cost_usd": 0.0, "cost_source": "no-spend"})
    section = ai_activity._headless_section(ai_activity.load_ledger(ledger), "2026-10-01")
    assert section["count"] == 3
    assert section["billed_cost_usd"] == 1.5, "only reported rows (and legacy rows) are billed"
    assert section["estimated_cost_usd"] == 8.0 and section["window_estimated_cost_usd"] == 8.0
    assert section["window_billed_cost_usd"] == 0.0
    by_id = {r["session_id"]: r for r in section["runs"]}
    assert by_id["old"]["cost_source"] == "reported" and by_id["est"]["billed_cost_usd"] == 0.0


def test_the_lazy_import_points_one_way():
    src = (HERE / "ai_activity.py").read_text(encoding="utf-8")
    assert "sys.path.append(str(REPO_ROOT))" in src and 'import_module("tools.jev.headless")' in src
    assert "from tools.jev" not in src and "import tools.jev" not in src.replace("importlib", "")
    jev = (HERE.parents[2] / "tools" / "jev").glob("*.py")
    for p in jev:
        text = p.read_text(encoding="utf-8")
        assert "import ai_activity" not in text and "import repo_scout" not in text, p


def test_the_headless_result_reader_agrees_with_result_record():
    hl = ai_activity.headless()
    for text in ('{"type":"result","x":1}', '[{"type":"system"},{"type":"result","x":2}]',
                 '{"type":"system"}\n{"type":"result","x":3}', '', '{"type":"system"}'):
        assert hl.last_result(text) == ai_activity.result_record(text), text


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
