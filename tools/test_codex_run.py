#!/usr/bin/env python3
"""
Tests for .github/actions/codex-run — the fleet's OpenAI step on the ChatGPT
OAuth login (openai_auth: in _data/fleet.yml, docs/OPENAI-AUTH.md).

run.sh is driven end to end against a FAKE `codex` on PATH, so nothing here
needs the network, an OpenAI account or npm: the fake records the arguments
and environment it was called with and does what the case asks (answer, paint
a PNG, rotate the refresh token, report a spent usage window, refuse a model).

What is held:
  - no credential, a stale bundle, a lapsing access token or an API-key login
    is a clean no-op (exit 0, outcome skipped) that names the fix;
  - the call is read-only for review, forced to the ChatGPT login, and never
    sees OPENAI_API_KEY;
  - what the reviewer writes is redacted before it reaches a file;
  - an image is found where Codex left it and carries a provenance sidecar;
    no image is RED, never a silent success;
  - a refresh inside the job is reported, a spent usage window is a warning,
    a retired model is named;
  - run.sh's defaults equal openai_auth: in _data/fleet.yml.

    python3 tools/test_codex_run.py
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

HUB = Path(__file__).resolve().parent.parent
ACTION = HUB / ".github" / "actions" / "codex-run"
RUN = ACTION / "run.sh"
sys.path.insert(0, str(ACTION))
import codex_auth  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

FAKE_CODEX = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
if sys.argv[1:2] == ["--version"]:
    print("codex-cli 0.0.0-test"); sys.exit(0)
args = sys.argv[1:]
prompt = sys.stdin.read()
rec = Path(os.environ["FAKE_RECORD"])
rec.write_text(json.dumps({"args": args, "prompt": prompt,
                           "openai_key": os.environ.get("OPENAI_API_KEY"),
                           "codex_home": os.environ.get("CODEX_HOME"),
                           "config": Path(os.environ["CODEX_HOME"], "config.toml").read_text()
                           if Path(os.environ["CODEX_HOME"], "config.toml").exists() else ""}))
case = os.environ.get("FAKE_CASE", "ok")
def opt(name):
    return args[args.index(name) + 1] if name in args else None
if case == "limit":
    print("ERROR: You've hit your usage limit. Try again later."); sys.exit(1)
if case == "model":
    print("ERROR: The 'gpt-x' model is not supported when using Codex with a ChatGPT account."); sys.exit(1)
if case == "fail":
    print("boom"); sys.exit(3)
if case == "rotate":
    auth = Path(os.environ["CODEX_HOME"], "auth.json")
    data = json.loads(auth.read_text()); data["tokens"]["refresh_token"] = "rt-rotated-by-codex"
    auth.write_text(json.dumps(data))
if case in ("image", "image-home", "no-image"):
    if case == "image":
        name = prompt.split("Save it as ./", 1)[1].split(" ", 1)[0]
        Path(opt("--cd"), name).write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    elif case == "image-home":
        d = Path(os.environ["CODEX_HOME"], "generated_images", "sess")
        d.mkdir(parents=True); (d / "ig_1.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    print("done"); sys.exit(0)
last = opt("--output-last-message")
leak = os.environ.get("FAKE_LEAK", "")
Path(last).write_text(json.dumps({"verdict": "clean", "summary": "fine " + leak}))
sys.exit(0)
'''


def _jwt(exp: int) -> str:
    def b64(obj) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    return f"{b64({'alg': 'none'})}.{b64({'exp': exp, 'sub': 'x'})}.{'s' * 16}"


def bundle(age_days: float = 1, ttl_hours: float = 48, refresh: str = "rt-fleet-0001", **extra) -> str:
    last = time.strftime("%Y-%m-%dT%H:%M:%S.000000Z", time.gmtime(time.time() - age_days * 86400))
    tokens = {"id_token": _jwt(int(time.time() + ttl_hours * 3600)),
              "access_token": _jwt(int(time.time() + ttl_hours * 3600)),
              "refresh_token": refresh, "account_id": "acct"}
    return json.dumps({"OPENAI_API_KEY": None, "tokens": tokens, "last_refresh": last, **extra})


def run(mode: str, *argv: str, auth: str | None = None, case: str = "ok", env: dict | None = None):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        bindir = tmp / "bin"
        bindir.mkdir()
        fake = bindir / "codex"
        fake.write_text(FAKE_CODEX)
        fake.chmod(0o755)
        out_file = tmp / "gh_output"
        e = {k: v for k, v in os.environ.items()
             if not k.startswith(("CODEX_", "GITHUB_")) and k != "OPENAI_API_KEY"}
        e.update({"PATH": f"{bindir}:{os.environ['PATH']}", "FAKE_RECORD": str(tmp / "rec.json"),
                  "FAKE_CASE": case, "GITHUB_OUTPUT": str(out_file), "RUNNER_TEMP": str(tmp),
                  "OPENAI_API_KEY": "sk-should-never-reach-codex-000000"})
        if auth is not None:
            e["CODEX_AUTH_JSON"] = auth
        e.update(env or {})
        argv = [a.replace("@TMP@", str(tmp)) for a in argv]
        proc = subprocess.run(["bash", str(RUN), mode, *argv], env=e, capture_output=True, text=True)
        outputs = {}
        if out_file.exists():
            for line in out_file.read_text().splitlines():
                k, _, v = line.partition("=")
                outputs[k] = v
        rec = json.loads((tmp / "rec.json").read_text()) if (tmp / "rec.json").exists() else None
        files = {p.relative_to(tmp).as_posix(): p.read_bytes()
                 for p in tmp.rglob("*") if p.is_file() and "result" in p.parts}
        homes = [p for p in tmp.iterdir() if p.name.startswith("codex-home.")]
        return proc, outputs, rec, files, homes


def test_no_credential_is_a_clean_no_op_that_names_the_fix():
    proc, out, rec, _, _ = run("review", "--prompt", "hi")
    assert proc.returncode == 0, proc.stderr
    assert out["ready"] == "false" and out["outcome"] == "skipped", out
    assert "seed" in out["reason"] and rec is None, out


def test_a_stale_bundle_is_refused_before_codex_could_refresh_it():
    proc, out, rec, _, _ = run("review", "--prompt", "hi", auth=bundle(age_days=7.6))
    assert proc.returncode == 0 and out["outcome"] == "skipped", (proc.stderr, out)
    assert "re-mint" in out["reason"] and rec is None, out
    proc, out, rec, _, _ = run("review", "--prompt", "hi", auth=bundle(ttl_hours=0.2))
    assert out["outcome"] == "skipped" and "expires" in out["reason"] and rec is None, out


def test_an_api_key_login_never_runs():
    api = json.dumps({"OPENAI_API_KEY": "sk-proj-abcdefghijklmnop", "tokens": None})
    proc, out, rec, _, _ = run("review", "--prompt", "hi", auth=api)
    assert proc.returncode == 0 and out["outcome"] == "skipped" and rec is None, out
    assert "OPENAI_API_KEY" in out["reason"] and "abcdefghijklmnop" not in out["reason"]


def test_review_is_read_only_forced_to_chatgpt_and_never_sees_an_api_key():
    proc, out, rec, files, homes = run(
        "review", "--prompt", "Review it.", "--out", "@TMP@/result/review.json",
        "--schema", "/dev/null", auth=bundle())
    assert proc.returncode == 0, proc.stderr
    assert out["outcome"] == "success" and out["refreshed"] == "false", out
    args = rec["args"]
    assert args[0] == "exec" and args[-1] == "-", args
    assert args[args.index("--sandbox") + 1] == "read-only", args
    assert args[args.index("--model") + 1] == codex_auth_defaults()["review"], args
    assert "--output-schema" in args and "--skip-git-repo-check" in args, args
    assert rec["openai_key"] is None, "the metered key must never reach codex"
    assert 'forced_login_method = "chatgpt"' in rec["config"], rec["config"]
    assert rec["prompt"] == "Review it."
    assert json.loads(files["result/review.json"])["verdict"] == "clean"
    assert not homes, "the restored CODEX_HOME must be deleted after the call"


def test_what_the_reviewer_writes_is_redacted():
    auth = bundle()
    access = json.loads(auth)["tokens"]["access_token"]
    leak = f"{access} ghp_{'A' * 36} sk-proj-{'b' * 24}"
    proc, _, _, files, _ = run("review", "--prompt", "x", "--out", "@TMP@/result/r.json",
                               auth=auth, env={"FAKE_LEAK": leak})
    assert proc.returncode == 0, proc.stderr
    text = files["result/r.json"].decode()
    assert access not in text and "ghp_" not in text and "sk-proj" not in text, text
    assert text.count(codex_auth.REDACTED) >= 3, text


def test_an_image_lands_with_its_provenance_and_none_is_red():
    for case in ("image", "image-home"):
        proc, out, rec, files, _ = run("image", "--prompt", "a lighthouse", "--out",
                                       "@TMP@/result/hero.png", auth=bundle(), case=case)
        assert proc.returncode == 0, (case, proc.stderr)
        assert out["outcome"] == "success" and out["image"].endswith("result/hero.png"), out
        assert files["result/hero.png"].startswith(b"\x89PNG"), case
        side = json.loads(files["result/hero.png.prompt.json"])
        assert side["prompt"] == "a lighthouse" and side["model"] == codex_auth_defaults()["image"]
        assert "ChatGPT" in side["source"] and len(side["sha256"]) == 64
        assert "$imagegen" in rec["prompt"], rec["prompt"]
        assert rec["args"][rec["args"].index("--sandbox") + 1] == "workspace-write"
    proc, out, _, files, _ = run("image", "--prompt", "x", "--out", "@TMP@/result/h.png",
                                 auth=bundle(), case="no-image")
    assert proc.returncode == 1 and out["outcome"] == "failure", out
    assert "no PNG" in out["reason"] and "result/h.png" not in files


def test_a_refresh_inside_the_job_is_reported():
    proc, out, _, _, _ = run("review", "--prompt", "x", "--out", "@TMP@/result/r.json",
                             auth=bundle(), case="rotate",
                             env={"GITHUB_ACTIONS": "true", "CODEX_SKIP_INSTALL": "1"})
    assert proc.returncode == 0 and out["refreshed"] == "true", out
    assert "::warning::" in proc.stdout and "Re-seed" in proc.stdout, proc.stdout
    refresh = json.loads(bundle())["tokens"]["refresh_token"]
    assert f"::add-mask::{refresh}" in proc.stdout, "token masks must reach the runner's stdout"


def test_a_spent_usage_window_is_capacity_and_a_retired_model_is_named():
    proc, out, _, _, _ = run("review", "--prompt", "x", auth=bundle(), case="limit")
    assert proc.returncode == 0 and out["outcome"] == "limited", (proc.stderr, out)
    proc, out, _, _, _ = run("review", "--prompt", "x", auth=bundle(), case="limit",
                             env={"CODEX_USAGE_LIMIT": "fail"})
    assert proc.returncode == 1 and out["outcome"] == "failure", out
    proc, out, _, _, _ = run("review", "--prompt", "x", auth=bundle(), case="model")
    assert proc.returncode == 1 and "openai_auth.models" in out["reason"], out
    proc, out, _, _, _ = run("review", "--prompt", "x", auth=bundle(), case="fail")
    assert proc.returncode == 1 and "exited 3" in out["reason"], out


def test_setup_exports_a_home_the_image_helper_reuses():
    with tempfile.TemporaryDirectory() as tmp:
        env_file = Path(tmp) / "gh_env"
        proc, out, _, _, homes = run("setup", auth=bundle(), env={"GITHUB_ENV": str(env_file)})
        assert proc.returncode == 0 and out["outcome"] == "success", proc.stderr
        exported = dict(line.split("=", 1) for line in env_file.read_text().splitlines())
        assert exported["CODEX_HOME_READY"] == "1" and exported["FLEET_IMAGEGEN"].endswith("imagegen.sh")
        assert Path(exported["CODEX_HOME"]).name.startswith("codex-home."), exported


def test_usage_errors_exit_2():
    proc, _, _, _, _ = run("paint", auth=bundle())
    assert proc.returncode == 2
    proc, _, _, _, _ = run("image", "--prompt", "x", auth=bundle())
    assert proc.returncode == 2, "image needs --out"


def codex_auth_defaults() -> dict:
    text = RUN.read_text()
    get = lambda k: re.search(rf'^{k}="([^"]+)"', text, re.M).group(1)  # noqa: E731
    return {"review": get("DEFAULT_MODEL_REVIEW"), "image_driver": get("DEFAULT_MODEL_IMAGE_DRIVER"),
            "image": get("DEFAULT_MODEL_IMAGE"), "max_age": get("DEFAULT_MAX_SEED_AGE_DAYS"),
            "min_ttl": get("DEFAULT_MIN_TTL_MINUTES")}


def test_the_runner_defaults_equal_the_fleet_contract():
    fleet = yaml.safe_load((HUB / "_data" / "fleet.yml").read_text())
    oa = fleet["openai_auth"]
    d = codex_auth_defaults()
    assert d["review"] == oa["models"]["review"], d
    assert d["image_driver"] == oa["models"]["image_driver"], d
    assert d["image"] == oa["models"]["image"], d
    assert float(d["max_age"]) == float(oa["max_seed_age_days"]), d
    assert float(d["min_ttl"]) == float(oa["min_access_ttl_minutes"]), d
    manifest = yaml.safe_load((ACTION / "action.yml").read_text())
    assert float(manifest["inputs"]["max-seed-age-days"]["default"]) == float(oa["max_seed_age_days"])
    assert float(manifest["inputs"]["min-ttl-minutes"]["default"]) == float(oa["min_access_ttl_minutes"])
    for role, model in oa["models"].items():
        assert model in fleet["ai_models"]["allowed"]["openai"], (role, model)
    assert "${{" not in json.dumps({k: v.get("description", "") for k, v in manifest["inputs"].items()}), \
        "no expression in an action description (drift check l)"


def test_the_verdict_reads_codex_timestamps_and_the_jwt_clock():
    now = time.time()
    v = codex_auth.verdict(bundle(age_days=2, ttl_hours=10), 7.5, 30)
    assert v["ok"] and 1.9 < v["age_days"] < 2.1 and 590 < v["access_ttl_minutes"] < 610, v
    b = json.loads(bundle())
    b["last_refresh"] = "2026-11-20T10:00:00.123456789Z"  # nanoseconds, as Codex writes
    assert codex_auth.parse_ts(b["last_refresh"]) is not None
    del b["last_refresh"]
    assert not codex_auth.verdict(json.dumps(b), 7.5, 30)["ok"], "unknown age is not fresh"
    assert codex_auth.jwt_exp("not-a-jwt") is None and codex_auth.jwt_exp(_jwt(int(now))) == int(now)


def main() -> int:
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ✓ {name}")
            except AssertionError as exc:
                failures += 1
                print(f"  ✗ {name}: {exc}")
    print(f"{'FAIL' if failures else 'OK'} — codex-run (OpenAI on the ChatGPT OAuth login)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
