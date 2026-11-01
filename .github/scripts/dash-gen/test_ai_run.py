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
    mode, a permission bypass in any spelling (a `--settings`/`--agents` file
    read from `--cwd`, an unreadable one refused) or a cloud session;
  * a run that leaves no result is still ONE ledger row — charged at the cap as
    `estimated` once the session started, `no-spend` when the CLI refused its
    own argv — keyed by the session id the wrapper chose;
  * `--stream` tees a condensed, redacted view; `--trace` is redacted;
    `--result-file` is what claude-cost's jq reads, redacted too; `--outcome-file`
    classifies; neither is ever left over from an earlier run;
  * `--isolate` builds claude's environment from scratch while ai-run itself
    keeps PYTHONPATH (PyYAML imports only through it on the maintainer's Mac);
    `--auth-order` leaves exactly one credential;
  * `--timeout` is SIGINT-first and exits 124; a SIGINT/SIGTERM/SIGHUP/SIGQUIT
    (or SIGUSR1, …) sent to ai-run starts the same ladder, is `interrupted`
    (exit 130) and is never read as a rejected credential; one that lands
    before claude starts runs nothing, and one that lands after claude exited
    leaves its outcome alone and waits for the ledger row; a usage limit is a
    warning under `--usage-limit skip`;
  * record_run and merge_ledger lose no row to a concurrent writer, and ai-run
    waits for a stopped one only `--ledger-wait` seconds;
  * `_headless_section` never counts an estimate as billed.

Run: python3 .github/scripts/dash-gen/test_ai_run.py
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ai_activity  # noqa: E402

DASH_GEN = HERE / "dash_gen.py"
OAUTH, KEY = "sk-ant-oat01-" + "o" * 40, "sk-ant-api03-" + "k" * 40
GH = "gho_" + "g" * 36
AGENTS_BYPASS = json.dumps({"x": {"description": "d", "prompt": "p", "permissionMode": "bypassPermissions"}})
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
    with open(os.path.join(HERE, "calls.log"), "a") as fh:
        fh.write("call\n")
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
    if scenario == "stdout_error":
        sys.stdout.write("Error: something unexpected\n"); sys.exit(1)
    if scenario == "sigkill_self":
        init(); os.kill(os.getpid(), signal.SIGKILL)
    if scenario in ("int_no_result", "int_result", "int_zero"):
        def on_int(*_):
            if scenario == "int_result":
                emit({**ok, "subtype": "error_during_execution", "is_error": True, "total_cost_usd": 0.42})
            if scenario == "int_zero":
                # aborted before the first response: no usage has accrued yet
                emit({**ok, "subtype": "error_during_execution", "is_error": True, "total_cost_usd": 0,
                      "modelUsage": {}, "result": "Request was aborted."})
            sys.exit(130)
        signal.signal(signal.SIGINT, on_int)
        init()
        open(os.path.join(HERE, "ready"), "w").close()
        while True:
            time.sleep(0.05)
    init()
    if scenario == "leak":
        # the agent quotes a token from the repo and the credential it was given
        emit({**ok, "result": "found ghp_" + "L" * 36 + " and " + os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")})
        sys.exit(0)
    if scenario == "long_error":
        # a token that straddles the 200-character clip of the outcome detail
        emit({**ok, "subtype": "error_during_execution", "is_error": True,
              "result": "y" * 180 + " ghp_" + "Q" * 36}); sys.exit(1)
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

    def command(self, *flags: str, passthrough: tuple[str, ...] = ("hello",),
                env: dict | None = None) -> tuple[list[str], dict]:
        scrubbed = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "CLAUDE_AUTH_ORDER", "GH_TOKEN")
        base = {k: v for k, v in os.environ.items() if k not in scrubbed}
        base.update({"DASH_AI_LEDGER": str(self.ledger), "JEV_DOTENV": str(self.dotenv)})
        base.update(env or {})
        argv = [sys.executable, str(DASH_GEN), "ai-run", "--claude-bin", str(self.claude), "--ledger",
                str(self.ledger), "--cwd", str(self.cwd), *flags, "--", *passthrough]
        return argv, base

    def run(self, *flags: str, passthrough: tuple[str, ...] = ("hello",), env: dict | None = None,
            timeout: float = 60) -> subprocess.CompletedProcess:
        argv, base = self.command(*flags, passthrough=passthrough, env=env)
        return subprocess.run(argv, env=base, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=timeout, check=False)

    def calls(self) -> int:
        log = self.bin / "calls.log"
        return len(log.read_text().splitlines()) if log.exists() else 0

    def rows(self) -> list[dict]:
        if not self.ledger.exists():
            return []
        return list(json.loads(self.ledger.read_text())["runs"].values())

    def argv(self) -> list[str]:
        return json.loads((self.bin / "argv.json").read_text())

    def child_env(self) -> dict:
        return json.loads((self.bin / "env.json").read_text())


def in_process(rig: Rig, *flags: str, env: dict | None = None) -> tuple[int, str, str]:
    """ai-run in THIS process, so a test can land a signal inside a window no
    subprocess timing can hit; held_signals needs the main thread."""
    argv, base = rig.command(*flags, env=env)
    parser = argparse.ArgumentParser()
    ai_activity.add_run_arguments(parser)
    args = parser.parse_args(argv[3:])
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, base, clear=True), contextlib.redirect_stdout(out), \
            contextlib.redirect_stderr(err):
        code = args.func(args)
    return code, out.getvalue(), err.getvalue()


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
    assert row["model"] is None, "no init and no --model: never guessed from modelUsage's first (helper) key"
    assert "API-equivalent (estimate)" in out.stderr


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
                ("--permission-mode=bypassPermissions",),
                # the CLI keeps the LAST value of a repeated option
                ("--permission-mode", "dontAsk", "--permission-mode", "bypassPermissions"),
                ("--permission-mode=dontAsk", "--permission-mode=bypassPermissions"),
                ("--settings", '{"permissions":{"defaultMode":"bypassPermissions"}}'),
                # the hidden mode a parent session hands down, used when nothing else sets one
                ("--inherit-permission-mode", "bypassPermissions"), ("--inherit-permission-mode=bypassPermissions",),
                ("--agents", AGENTS_BYPASS, "--agent", "x"), (f"--agents={AGENTS_BYPASS}", "--agent", "x"),
                # an attached cloud session enforces no cap from this invocation
                ("--cloud", "session_123"), ("--remote=session_123",), ("--teleport",)):
        out = rig.run(passthrough=(*bad, "hello"))
        assert out.returncode == 2 and "refusing" in out.stderr, bad
    assert rig.rows() == [] and not (rig.bin / "argv.json").exists()


def test_a_settings_or_agents_file_is_read_from_the_cwd_claude_runs_in_and_fails_closed():
    rig = Rig()
    (rig.cwd / "bypass.json").write_text('{"permissions":{"defaultMode":"bypassPermissions"}}')
    (rig.cwd / "agents.json").write_text(AGENTS_BYPASS)
    (rig.cwd / "fine.json").write_text('{"permissions":{"defaultMode":"dontAsk"}}')
    assert not Path("bypass.json").exists(), "the test's own cwd must not hold the file"
    for bad in (("--settings", "bypass.json"), ("--settings=bypass.json",), ("--agents", "agents.json"),
                ("--settings", "missing.json"), ("--settings", "{not json")):
        out = rig.run(passthrough=(*bad, "hello"))
        assert out.returncode == 2 and "refusing" in out.stderr, (bad, out.stderr)
    assert rig.rows() == []
    assert rig.run(passthrough=("--settings", "fine.json", "hello")).returncode == 0


def test_a_dry_run_runs_and_records_nothing():
    rig = Rig()
    out = rig.run("--dry-run", "--call-site", "repo-scout.yml:scout")
    assert out.returncode == 0 and "cap: $8.00 (repo-scout.yml:scout) API-equivalent (estimate)" in out.stderr
    assert rig.rows() == [] and not (rig.bin / "argv.json").exists()


def test_bad_meta_is_refused_and_good_meta_is_recorded():
    rig = Rig()
    assert rig.run("--meta", "total_cost_usd=0").returncode == 2
    assert rig.run("--meta", "loop=a", "--meta", "loop=b").returncode == 2
    # budget.loops counts origin: local rows — a row this wrapper writes is never anything else
    assert rig.run("--meta", "origin=ci", "--meta", "loop=a").returncode == 2
    assert rig.rows() == []
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


def test_the_result_file_and_the_echo_are_redacted_like_the_trace():
    for mode in ((), ("--stream",)):
        rig = Rig("leak")
        res, trace = rig.dir / "result.json", rig.dir / "trace.jsonl"
        out = rig.run(*mode, "--isolate", "--auth-order", "oauth", "--trace", str(trace), "--result-file", str(res),
                      env={"CLAUDE_CODE_OAUTH_TOKEN": OAUTH})
        assert out.returncode == 0, out.stderr
        for name, text in (("stdout", out.stdout), ("stderr", out.stderr), ("result.json", res.read_text()),
                           ("trace", trace.read_text())):
            assert OAUTH not in text and "ghp_L" not in text, (mode, name, text)
        got = json.loads(res.read_text())
        assert "[REDACTED:CLAUDE_CODE_OAUTH_TOKEN]" in got["result"] and "[REDACTED]" in out.stdout
        assert got["total_cost_usd"] == 0.61 and got["modelUsage"]["claude-sonnet-5-5"]["inputTokens"] == 100


def test_the_outcome_detail_is_redacted_before_it_is_clipped():
    # clipped first, the token's first 15 characters would survive as a prefix
    # no token pattern recognises
    for mode in ((), ("--stream",)):
        rig = Rig("long_error")
        outcome = rig.dir / "outcome.json"
        out = rig.run(*mode, "--outcome-file", str(outcome))
        assert out.returncode == 1, out.stderr
        got = json.loads(outcome.read_text())
        assert got["kind"] == "agent_error", got
        assert "ghp_" not in got["detail"] and "QQQQ" not in got["detail"], (mode, got["detail"])
        assert got["detail"].endswith("[REDACTED]"), (mode, got["detail"])
        assert "ghp_" not in out.stdout + out.stderr


def test_a_run_with_no_result_after_init_is_charged_at_the_cap():
    rig = Rig("init_then_exit")
    outcome = rig.dir / "outcome.json"
    result = rig.dir / "result.json"
    result.write_text("{}")
    out = rig.run("--stream", "--call-site", "repo-scout.yml:scout", "--outcome-file", str(outcome),
                  "--result-file", str(result))
    assert out.returncode == 1 and "charged at the $8 cap API-equivalent (estimate)" in out.stderr
    [row] = rig.rows()
    assert (row["outcome"], row["cost_source"], row["total_cost_usd"]) == ("unparseable", "estimated", 8.0)
    assert row["session_id"] == opt(rig.argv(), "--session-id")
    assert not result.exists(), "a stale result file is removed, never left for claude-cost to read"
    assert json.loads(outcome.read_text())["cost_source"] == "estimated"


def test_with_no_result_record_what_the_cli_printed_is_still_shown():
    rig = Rig("stdout_error")
    out = rig.run()
    assert out.returncode == 1 and "Error: something unexpected" in out.stdout, (out.stdout, out.stderr)
    [row] = rig.rows()
    assert (row["outcome"], row["cost_source"]) == ("unparseable", "estimated")


def test_a_claude_killed_by_a_signal_exits_128_plus_n_and_says_so():
    rig = Rig("sigkill_self")
    outcome = rig.dir / "outcome.json"
    out = rig.run("--stream", "--outcome-file", str(outcome))
    assert out.returncode == 128 + signal.SIGKILL, out.returncode
    got = json.loads(outcome.read_text())
    assert got["exit_code"] == got["rc"] == 128 + signal.SIGKILL


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
    assert "TIMED OUT" in out.stderr and "API-equivalent (estimate)" in out.stderr
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


def started(rig: Rig, *flags: str) -> subprocess.Popen:
    argv, env = rig.command(*flags)
    p = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True)
    deadline = time.monotonic() + 30
    while not (rig.bin / "ready").exists():
        assert time.monotonic() < deadline and p.poll() is None, "the stub never got ready"
        time.sleep(0.05)
    return p


def no_stub_left(rig: Rig) -> bool:
    return subprocess.run(["pgrep", "-f", str(rig.claude)], capture_output=True, check=False).returncode == 1


def test_a_signal_to_ai_run_starts_the_sigint_first_ladder():
    # The console's cancel sends SIGTERM to ai-run's group, a closed terminal
    # SIGHUP; claude runs in its own session, so only ai-run forwarding them can
    # stop claude with a result — in both output formats.
    cases = [(sig, ("--stream",)) for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGQUIT,
                                              signal.SIGUSR1)]
    for sig, mode in [*cases, (signal.SIGHUP, ())]:
        rig = Rig("int_result")
        outcome = rig.dir / "outcome.json"
        p = started(rig, *mode, "--outcome-file", str(outcome))
        os.kill(p.pid, sig)
        _, err = p.communicate(timeout=40)
        assert p.returncode == 130, (sig, p.returncode, err)
        [row] = rig.rows()
        assert (row["outcome"], row["cost_source"], row["total_cost_usd"]) == ("interrupted", "reported", 0.42)
        assert json.loads(outcome.read_text())["interrupted"] == signal.Signals(sig).name
        assert "INTERRUPTED" in err and no_stub_left(rig), "nothing is orphaned"


def test_a_cancel_while_the_run_is_recorded_waits_for_the_row():
    # claude has exited and reported $0.61; ai-run is blocked on the ledger lock
    # when the cancel lands. It must finish the row and the files first.
    for sig in (signal.SIGTERM, signal.SIGINT):
        rig = Rig()
        outcome = rig.dir / "outcome.json"
        lock = rig.ledger.with_name(rig.ledger.name + ".lock").open("a")
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            argv, env = rig.command("--outcome-file", str(outcome))
            p = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)
            deadline = time.monotonic() + 30
            while not rig.calls():
                assert time.monotonic() < deadline and p.poll() is None, "the stub never ran"
                time.sleep(0.05)
            # (pgrep cannot tell the stub from ai-run, whose argv names it too:
            # the `ok` stub exits at once, so wait instead)
            time.sleep(1.0)
            assert p.poll() is None, "ai-run waits on the ledger lock"
            os.kill(p.pid, sig)
            time.sleep(0.3)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            lock.close()
        out, err = p.communicate(timeout=30)
        assert p.returncode == 128 + sig, (sig, p.returncode, err)
        [row] = rig.rows()
        assert (row["outcome"], row["cost_source"], row["total_cost_usd"]) == ("ok", "reported", 0.61)
        assert json.loads(outcome.read_text())["kind"] == "ok" and out == "proposals written\n"


def test_a_stopped_ledger_writer_holds_a_finished_run_and_its_cancel_only_so_long():
    # a `dash ai` scan suspended with Ctrl-Z keeps the lock: the run is not
    # ledgered, its outcome file still carries its cost, and the held cancel
    # ends ai-run once the bounded wait is over
    for sig in (None, signal.SIGTERM):
        rig = Rig()
        outcome = rig.dir / "outcome.json"
        lock = rig.ledger.with_name(rig.ledger.name + ".lock").open("a")
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            argv, env = rig.command("--ledger-wait", "2", "--outcome-file", str(outcome))
            t0 = time.monotonic()
            p = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)
            if sig is not None:
                deadline = time.monotonic() + 30
                while not rig.calls():
                    assert time.monotonic() < deadline and p.poll() is None, "the stub never ran"
                    time.sleep(0.05)
                time.sleep(0.5)
                os.kill(p.pid, sig)
            out, err = p.communicate(timeout=30)
            elapsed = time.monotonic() - t0
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            lock.close()
        assert p.returncode == (128 + sig if sig else 1), (sig, p.returncode, err)
        assert elapsed < 20, "the wait is bounded"
        assert "THIS RUN IS NOT LEDGERED" in err and "NOT recorded to" in err, err
        assert rig.rows() == []
        got = json.loads(outcome.read_text())
        assert (got["kind"], got["cost_usd"]) == ("ok", 0.61) and got["ledger_error"], got
        assert out == "proposals written\n"
    rig = Rig()
    assert rig.run("--ledger-wait", "0").returncode == 2 and rig.calls() == 0


def test_a_signal_after_claude_exits_is_late_even_in_the_tidying_before_the_row():
    # claude reported $0.61 and exited; the SIGTERM lands while ai-run removes
    # its temporary directory, before any bookkeeping: the run is still `ok`,
    # and ai-run exits as SIGTERM would once the row is written
    rig = Rig()
    outcome = rig.dir / "outcome.json"
    real = shutil.rmtree

    def rmtree(path, *a, **k):
        if "jev-ai-run-" in str(path):
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(0.1)
        return real(path, *a, **k)

    with mock.patch.object(ai_activity.shutil, "rmtree", rmtree):
        code, out, err = in_process(rig, "--isolate", "--auth-order", "oauth", "--outcome-file", str(outcome),
                                    env={"CLAUDE_CODE_OAUTH_TOKEN": OAUTH})
    assert code == 128 + signal.SIGTERM, (code, err)
    assert "SIGTERM arrived after claude exited" in err and out == "proposals written\n"
    [row] = rig.rows()
    assert (row["outcome"], row["cost_source"], row["total_cost_usd"]) == ("ok", "reported", 0.61)
    got = json.loads(outcome.read_text())
    assert got["kind"] == "ok" and got["interrupted"] == "", got


def test_a_cancel_before_claude_is_started_starts_nothing_and_charges_nothing():
    # the cancel lands while ai-run builds the trace, inside held_signals but
    # before stream() would start claude
    rig = Rig()
    outcome = rig.dir / "outcome.json"
    hl = ai_activity.headless()
    real = hl.Trace

    class CancelledTrace(real):
        def __init__(self, *a, **k):
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(0.1)
            super().__init__(*a, **k)

    with mock.patch.object(hl, "Trace", CancelledTrace):
        code, _, err = in_process(rig, "--outcome-file", str(outcome))
    assert code == 130, (code, err)
    assert rig.calls() == 0, "claude was never started"
    assert rig.rows() == [], "nothing ran, so nothing is ledgered"
    got = json.loads(outcome.read_text())
    assert (got["kind"], got["cost_source"], got["cost_usd"]) == ("interrupted", "no-spend", 0.0), got
    assert "before claude was started" in err


def test_a_cancel_before_the_first_response_is_not_a_rejected_credential():
    rig = Rig("int_zero")
    p = started(rig, "--stream")
    os.kill(p.pid, signal.SIGTERM)
    _, err = p.communicate(timeout=40)
    assert p.returncode == 130, (p.returncode, err)
    assert "CREDENTIAL REJECTED" not in err and "rotate" not in err, err
    [row] = rig.rows()
    assert row["outcome"] == "interrupted" and row["cost_source"] != "no-spend"


def test_a_refused_credential_and_a_budget_hit_are_loud():
    rig = Rig("notloggedin")
    out = rig.run("--stream")
    assert out.returncode == 1 and "CREDENTIAL REJECTED" in out.stderr
    assert rig.rows()[0]["cost_source"] == "no-spend"
    assert rig.calls() == 1, "a refused credential is never retried in the run (#348)"
    keyed = rig.run("--stream", "--auth-order", "api_key", env={"ANTHROPIC_API_KEY": KEY})
    assert "rotate ANTHROPIC_API_KEY" in keyed.stderr and "CLAUDE_CODE_OAUTH_TOKEN" not in keyed.stderr, keyed.stderr
    rig = Rig("budget")
    out = rig.run("--stream", "--call-site", "repo-scout.yml:scout")
    assert out.returncode == 2 and "BUDGET CAP HIT" in out.stderr and "API-equivalent (estimate)" in out.stderr
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


def test_isolate_removes_the_temporary_directory_it_made():
    rig = Rig()
    tmp = rig.dir / "parent-tmp"
    tmp.mkdir()
    out = rig.run("--isolate", "--auth-order", "oauth", env={"TMPDIR": str(tmp), "CLAUDE_CODE_OAUTH_TOKEN": OAUTH})
    assert out.returncode == 0, out.stderr
    assert rig.child_env()["TMPDIR"].startswith(str(tmp)), "the child ran in the directory ai-run made"
    assert list(tmp.glob("jev-ai-run-*")) == [], "and it is gone afterwards"


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


def stale(rig: Rig) -> tuple[Path, Path]:
    """A result and an outcome an EARLIER run left at the paths this one reuses."""
    res, outcome = rig.dir / "result.json", rig.dir / "outcome.json"
    res.write_text(json.dumps({"type": "result", "total_cost_usd": 9.99}))
    outcome.write_text(json.dumps({"kind": "ok", "exit_code": 0}))
    return res, outcome


def test_the_early_exits_write_an_outcome_and_no_row():
    rig = Rig()
    res, outcome = stale(rig)
    rig.claude.unlink()
    assert rig.run("--outcome-file", str(outcome), "--result-file", str(res)).returncode == 127
    assert json.loads(outcome.read_text())["kind"] == "cli_missing" and rig.rows() == [] and not res.exists()
    rig = Rig()
    res, outcome = stale(rig)
    assert rig.run("--isolate", "--outcome-file", str(outcome), "--result-file", str(res),
                   env={"CLAUDE_AUTH_ORDER": "api_key"}).returncode == 3
    got = json.loads(outcome.read_text())
    assert (got["kind"], got["cost_source"], got["exit_code"]) == ("credential_rejected", "no-spend", 3)
    assert rig.rows() == [] and not (rig.bin / "argv.json").exists() and not res.exists()
    # found on PATH but cannot start (a broken shebang): no process ran, so no row either
    rig = Rig()
    res, outcome = stale(rig)
    rig.claude.write_text("#!/nonexistent/interpreter\n")
    assert rig.run("--outcome-file", str(outcome), "--result-file", str(res)).returncode == 127
    assert json.loads(outcome.read_text())["kind"] == "cli_missing" and rig.rows() == [] and not res.exists()


def test_a_refused_invocation_leaves_no_earlier_runs_files():
    for flags, passthrough in ((("--call-site", "nope.yml:job"), ("hello",)), ((), ("-p", "hello")),
                               (("--meta", "bogus=1"), ("hello",))):
        rig = Rig()
        res, outcome = stale(rig)
        assert rig.run(*flags, "--result-file", str(res), "--outcome-file", str(outcome),
                       passthrough=passthrough).returncode == 2
        assert not res.exists() and not outcome.exists(), flags
    rig = Rig()
    res, outcome = stale(rig)
    argv, env = rig.command("--result-file", str(res), "--outcome-file", str(outcome))
    argv[argv.index("--cwd") + 1] = str(rig.dir / "not-a-dir")
    assert subprocess.run(argv, env=env, stdin=subprocess.DEVNULL, capture_output=True, check=False).returncode == 2
    assert not res.exists() and not outcome.exists()


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


def test_a_session_against_an_unreadable_ledger_is_loud_unledgered_and_fails():
    # the session ran and spent: ai-run keeps the ledger as it found it, writes the outcome and exits non-zero
    for bad in ("{truncated", json.dumps({"version": 2, "runs": {}})):
        rig = Rig()
        rig.ledger.write_text(bad)
        outcome = rig.dir / "outcome.json"
        out = rig.run("--outcome-file", str(outcome))
        assert out.returncode == 1 and rig.calls() == 1, (out.returncode, out.stderr)
        assert rig.ledger.read_text() == bad, "never replaced with only this run's row"
        got = json.loads(outcome.read_text())
        assert got["ledger_error"] and (got["kind"], got["cost_usd"], got["exit_code"]) == ("ok", 0.61, 1), got
        assert "THIS RUN IS NOT LEDGERED" in out.stderr and "NOT recorded to" in out.stderr, out.stderr
        assert "in place" in out.stderr and "move it aside" not in out.stderr, out.stderr


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
