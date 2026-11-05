#!/usr/bin/env python3
"""
Fixture tests for tools/jev/adapters/fleet_pulse_doctor.py — the fleet doctor's
adapter on the loop engine (bamr87/bamr87#488, ADR 0002 P3). The adapter maps
the planner's plan-mode JSON (`dash-gen remediate --plan-dir`) and the filer's
dry run (`dash-gen doctor-file`), so what is tested is that it maps the REAL
offline planner's output, that tier 0 reuses only an identical attempt, that
--apply needs a live dedupe, that validation turns the engine's patch and the
filing the agent asked gh for into one document with the MARKER line first,
withholds what would leak this machine, refuses an attempt with nothing to
file, that the filer's structural rules run on the copy, that its --apply
(the OPS remote-write path, constitution § 11.8) files exactly one push and
one draft PR through a stub `gh` against a local remote — refusing a rejected
token, an unreadable dedupe list and an unreviewed body with nothing written —
and that the engine's modules hold no route to a merge, a force or dash-gen.

No network: the planner and the dry-run filer run `--offline`; the apply tests
put a stub `gh` first on PATH, so no test can reach GitHub.
Run: python3 tools/test_jev_adapter_fleet_pulse_doctor.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

HUB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUB))

from tools.jev import adapters as A  # noqa: E402
from tools.jev import loop as L  # noqa: E402
from tools.jev import spec as S  # noqa: E402
from tools.jev.adapters import fleet_pulse_doctor as FD  # noqa: E402
from tools.jev.common import JevError, Run  # noqa: E402
from tools.jev.workspace import Harvest  # noqa: E402

sys.path.insert(0, str(HUB / ".github" / "scripts" / "dash-gen"))
import fleet_doctor_file as FILER  # noqa: E402  — the filer's own structural rules and messages

SPEC = S.load_spec("fleet-pulse", "doctor")
FD_FILER_NOT_REVIEWED = ("not in the reviewed preview (its body or patch is not byte-identical to a reviewed one)")
ADAPTER = A.get("fleet_pulse_doctor")
KEY = "bamr87/bamr87:.github/workflows/ci.yml"
MARKER = f'<!-- fleet-doctor key="{KEY}" -->'
PATCH = ("diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml\n--- a/.github/workflows/ci.yml\n"
         "+++ b/.github/workflows/ci.yml\n@@ -1 +1 @@\n-runs-on: ubuntu-20.04\n+runs-on: ubuntu-latest\n")
#: the marker inside a double-quoted shell body: its own quotes escaped, as a shell needs them
QUOTED = MARKER.replace('"', '\\"')
GH_PR = ('gh pr create --draft --base main --label fleet-doctor --label automation --title "ci: move off the '
         'retired runner" --body "' + QUOTED + '\n\n**Problem** — ubuntu-20.04 is retired."')


def offline_plan(tmp: Path, target: str = "all") -> dict:
    """The REAL planner, offline, against the hub's committed snapshots."""
    res = L.dash_gen(["remediate", "--plan-dir", str(tmp / "plan"), "--offline", f"--target={target}"])
    assert res.code in (0, 1), res.err
    return L.parse_last_json(res.out)


def ctx(tmp: Path, work_root: str = "/Users/someone/.cache/jev/work", **opts) -> SimpleNamespace:
    o = L.Options(**opts)

    def item_dir(item):
        d = tmp / "items" / re.sub(r"[^A-Za-z0-9._-]+", "_", item.key)
        d.mkdir(parents=True, exist_ok=True)
        return d
    return SimpleNamespace(spec=SPEC, opts=o, plan_dir=tmp / "plan", history=L.History(tmp / "runs"),
                           home=Path("/Users/someone"), hostname="someones-mac", work_root=Path(work_root),
                           item_dir=item_dir,
                           bodies_dir=lambda item, apply: item_dir(item) / ("filed" if apply else "bodies"),
                           dash_gen=L.dash_gen, planner=None, run_ref=lambda: "local run t (tools/jev loop)")


def _call(n: int, name: str, inp: dict, result: str, is_error: bool = False) -> list[dict]:
    return [{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": f"t{n}", "name": name,
                                                           "input": inp}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": f"t{n}",
                                                      "content": result, "is_error": is_error}]}}]


def session(calls: list[tuple[str, str, bool]], result: str = "done") -> list[dict]:
    events = [{"type": "system", "subtype": "init", "session_id": "s", "tools": ["Bash", "Read"]}]
    for i, (cmd, out, err) in enumerate(calls, 1):
        events += _call(i, "Bash", {"command": cmd}, out, err)
    events.append({"type": "result", "subtype": "success", "result": result})
    return events


def row(where: str = "hub", repo: str = "bamr87/bamr87", **extra) -> dict:
    key = f"{repo}:.github/workflows/ci.yml"
    return {"key": key, "name": "ci", "nwo": "bamr87/bamr87", "branch": "main", "repo": repo, "workflow": "CI",
            "path": ".github/workflows/ci.yml", "where": where, "signals": ["failing"],
            "marker": f'<!-- fleet-doctor key="{key}" -->', "brief": "doctor-workorder-ci.md", "dedupe": "clear",
            "evidence": "offline", **extra}


def item_for(c, r: dict | None = None) -> A.Item:
    r = r or row()
    (c.plan_dir).mkdir(parents=True, exist_ok=True)
    (c.plan_dir / r["brief"]).write_text(f"# order\n\n{r['marker']}\n", encoding="utf-8")
    return ADAPTER.items(c, {"include": [r]}).items[0]


def validate(c, item: A.Item, events: list[dict], patch: str | None = PATCH) -> A.Verdict:
    d = c.item_dir(item)
    (d / "trace.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    if patch is None:
        h = Harvest(FD.PATCH, None, None, 0, "absent")
    else:
        dest = d / "outputs" / "changes.patch"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(patch, encoding="utf-8")
        h = Harvest(FD.PATCH, dest, "x", len(patch), "ok")
    return ADAPTER.validate(c, item, {FD.PATCH: h}, {"kind": "ok"})


# --------------------------------------------------------------------------- #
# the registry, items, reuse, classify
# --------------------------------------------------------------------------- #
def test_the_adapter_is_registered_and_the_spec_names_it():
    assert A.REGISTRY["fleet_pulse_doctor"] == "tools.jev.adapters.fleet_pulse_doctor"
    assert isinstance(ADAPTER, A.Adapter) and ADAPTER.name == "fleet_pulse_doctor"
    assert SPEC.local.adapter == "fleet_pulse_doctor" and SPEC.local.harvest == "patch"
    assert SPEC.workspace.cwd == "hub" and SPEC.workspace.brief_file == "remediation-workorder.md"
    assert SPEC.workspace.github_credential == "fleet-write" and SPEC.workspace.outputs == ()


def test_items_maps_the_real_offline_planner_output_one_per_candidate():
    tmp = Path(tempfile.mkdtemp())
    c = ctx(tmp)
    plan = offline_plan(tmp)
    result = ADAPTER.items(c, plan)
    assert len(result.items) == plan["count"] and result.items, "the committed snapshots give a queue"
    for item in result.items:
        assert item.nwo == "bamr87/bamr87" and item.key == item.row["key"] and item.row["repo"] != ""
        assert item.brief == tmp / "plan" / item.row["brief"] and item.brief.is_file()
        assert item.row["marker"].startswith('<!-- fleet-doctor key="') and item.row["where"] in ("hub", "submodule")
        assert item.row["prompt"] == S.render_prompt(SPEC, S.values_from(SPEC, item.row)) == SPEC.template, "parity"
    assert all("key" in s for s in result.skipped) and result.meta["max_candidates"] == plan["max_candidates"]
    keys = [i.key for i in result.items]
    assert len(set(keys)) == len(keys)
    one = offline_plan(Path(tempfile.mkdtemp()), target=keys[0])
    assert [r["key"] for r in one["include"]] == [keys[0]], "--target picks one candidate regardless of the cap"


def test_items_refuses_a_row_missing_its_candidate_fields_or_a_non_bare_brief():
    c = ctx(Path(tempfile.mkdtemp()))
    for bad in ({**row(), "repo": "not a slug"}, {**row(), "brief": "../x.md"}, {**row(), "where": "elsewhere"},
                {k: v for k, v in row().items() if k != "marker"}):
        try:
            ADAPTER.items(c, {"include": [bad]})
        except JevError:
            continue
        raise AssertionError(f"accepted {bad}")


def test_the_reuse_key_ignores_the_signal_stamps_and_the_capture_time():
    c = ctx(Path(tempfile.mkdtemp()))
    item = item_for(c)
    k1 = ADAPTER.reuse_key(c, item, "abc")
    item.brief.write_text(f"Signals: `_data/fleet_triage.yml` (2026-11-03 06:01 UTC)\n# order\n\n{MARKER}\n"
                          "What they printed when the planner ran them with the operator's own `gh` at 2026-11-04 "
                          "01:00 UTC is below.\n", encoding="utf-8")
    assert ADAPTER.reuse_key(c, item, "abc") == k1, "stamps are not a change"
    item.brief.write_text(f"# order\n\n{MARKER}\n- a new failing run\n", encoding="utf-8")
    assert ADAPTER.reuse_key(c, item, "abc") != k1 and ADAPTER.reuse_key(c, item, "def") != k1
    assert ADAPTER.reuse_key(c, item, None) is None
    assert ADAPTER.tier0(c, item, "").action == "skip"


def test_classify_blocks_apply_without_a_live_dedupe():
    tmp = Path(tempfile.mkdtemp())
    item = item_for(ctx(tmp), row(dedupe="unavailable"))
    assert ADAPTER.classify(ctx(tmp, apply=True), item).blocked
    assert not ADAPTER.classify(ctx(tmp), item).blocked
    assert not ADAPTER.classify(ctx(tmp, apply=True), item_for(ctx(tmp))).blocked


# --------------------------------------------------------------------------- #
# validate: the patch + the filing the agent asked for
# --------------------------------------------------------------------------- #
def test_a_hub_fix_with_the_refused_pr_call_becomes_a_pr_document_marker_first():
    c = ctx(Path(tempfile.mkdtemp()))
    item = item_for(c)
    events = session([("git checkout -b fix/fleet-doctor-ci", "Switched", False),
                      (GH_PR, "Permission to use Bash has been denied", True)])
    v = validate(c, item, events)
    assert v.ok and v.publish_file is not None and not v.problems, v.problems
    doc = json.loads(v.publish_file.read_text())
    assert doc["kind"] == "pr" and doc["repo"] == "bamr87/bamr87" and doc["branch"] == "fix/fleet-doctor-ci"
    assert doc["title"] == "ci: move off the retired runner" and doc["body"].splitlines()[0] == MARKER
    assert doc["patch"] == "doctor.patch" and (v.publish_file.parent / "doctor.patch").read_text() == PATCH
    assert doc["source"] == "gh-call" and v.facts["filings_attempted"] == 1 and v.flags == []


def test_the_marker_is_prepended_when_the_agent_left_it_out_and_the_branch_is_derived():
    c = ctx(Path(tempfile.mkdtemp()))
    item = item_for(c)
    events = session([('gh pr create --title "t" --body "no marker here"', "denied", True)])   # no marker at all
    v = validate(c, item, events)
    assert v.ok, v.problems
    doc = json.loads(v.publish_file.read_text())
    assert doc["body"].startswith(MARKER + "\n\n") and doc["branch"].startswith("fix/fleet-doctor-")
    assert any("MARKER" in f for f in v.flags) and any("branch name is derived" in f for f in v.flags)


def test_a_fix_with_no_gh_call_is_synthesised_from_the_result_text_for_a_hub_candidate_only():
    c = ctx(Path(tempfile.mkdtemp()))
    v = validate(c, item_for(c), session([], result="Root cause: the runner image. Fixed in ci.yml."))
    assert v.ok, v.problems
    doc = json.loads(v.publish_file.read_text())
    assert doc["source"] == "result-text" and "Root cause" in doc["body"] and doc["body"].startswith(MARKER)
    assert any("synthesised" in f for f in v.flags)
    sub = validate(c, item_for(c, row(where="submodule", repo="bamr87/alpha")), session([]))
    assert not sub.ok and any("submodule" in p for p in sub.problems), sub.problems


def test_a_submodule_candidate_yields_the_issue_the_agent_asked_for_and_never_a_hub_pr():
    c = ctx(Path(tempfile.mkdtemp()))
    r = row(where="submodule", repo="bamr87/alpha")
    marker = r["marker"]
    issue = ('GH_TOKEN="$FLEET_WRITE_TOKEN" gh issue create -R bamr87/bamr87 --label fleet-doctor --title "alpha CI" '
             "--body '" + marker + "\n\nthe token was rejected'")   # single-quoted: the marker's quotes survive
    v = validate(c, item_for(c, r), session([(issue, "denied", True)]), patch="")
    assert v.ok, v.problems
    doc = json.loads(v.publish_file.read_text())
    assert doc["kind"] == "issue" and doc["repo"] == "bamr87/bamr87" and doc["patch"] is None and doc["branch"] is None
    aimed = validate(c, item_for(c, r), session([("gh pr create --title 't' --body '" + marker + "'", "denied", True)]))
    assert not aimed.ok and any("aimed at the hub" in p for p in aimed.problems), aimed.problems


def test_nothing_to_file_and_the_privacy_filter_reject():
    c = ctx(Path(tempfile.mkdtemp()))
    none = validate(c, item_for(c), session([]), patch="")
    assert not none.ok and any("neither a fix" in p for p in none.problems)
    leaky = validate(c, item_for(c), session([('gh pr create --title "t" --body "' + QUOTED +
                                                '\n\nsee /Users/someone/.cache/jev/work/x"', "denied", True)]))
    assert not leaky.ok and any("local path" in p for p in leaky.problems)
    host = validate(c, item_for(c), session([('gh pr create --title "on someones-mac" --body "' + QUOTED + '"',
                                               "denied", True)]))
    assert not host.ok
    denial = validate(c, item_for(c), session([('gh pr create --title "t" --body "' + QUOTED +
                                                 '\n\ngh run view failed: Operation not permitted"', "denied", True)]))
    assert denial.ok and any("local-runner denial" in f for f in denial.flags)


def test_validate_runs_the_filers_offline_rules_on_the_copy():
    c = ctx(Path(tempfile.mkdtemp()))
    secret = validate(c, item_for(c), session([('gh pr create --title "t" --body "' + QUOTED +
                                                 '\n\nghp_' + "A" * 36 + '"', "denied", True)]))
    assert not secret.ok and any("credential shape" in p for p in secret.problems), secret.problems


# --------------------------------------------------------------------------- #
# publish: the dry run, and the refused apply
# --------------------------------------------------------------------------- #
def _run(code: int = 0, out: object = None, err: str = "") -> Run:
    return Run(code, json.dumps(out) + "\n" if out is not None else "", err)


def test_publish_parses_the_dry_run_and_reads_an_exit_3_or_a_withheld_body_as_failure():
    c = ctx(Path(tempfile.mkdtemp()))
    item = item_for(c)
    v = A.Verdict(True, publish_file=Path("/x"))
    filed = {"apply": False, "filed": [{"title": "t", "kind": "pr", "repo": "bamr87/bamr87", "labels": ["fleet-doctor"],
                                         "body_file": "b.md", "patch_file": "b.patch", "branch": "fix/fleet-doctor-ci",
                                         "url": None}], "skipped": [], "rejected": []}
    plan = ADAPTER.publish(c, item, v, lambda: _run(0, filed))
    assert plan.publishable and plan.rows[0]["kind"] == "pr" and plan.blockers == [] and plan.failures == []
    nodedupe = ADAPTER.publish(c, item, v, lambda: _run(0, filed, err=FD.NO_DEDUPE))
    assert not nodedupe.publishable and "dedupe_unavailable" in nodedupe.blockers
    blocked = ADAPTER.publish(c, item, v, lambda: _run(3, None, err="doctor-file: " + FD.TOKEN_REFUSED + ": 401"),
                              apply=True)
    assert not blocked.publishable and any("filed nothing" in b for b in blocked.blockers), blocked.blockers
    withheld = ADAPTER.publish(c, item, v, lambda: _run(0, {**filed, "apply": True, "filed": [],
                                                           "skipped": [{"title": "t", "reason": FD.NOT_REVIEWED}]}),
                               apply=True)
    assert not withheld.publishable and withheld.failures == ["t"], withheld
    steps = ADAPTER.apply_steps(c, item, plan)
    assert len(steps) == 4 and "gh label create" in steps[0] and "before anything is pushed" in steps[0], steps
    assert "git checkout main" in steps[1] and "HEAD:refs/heads/fix/fleet-doctor-ci" in steps[2], steps
    assert "--draft --base main" in steps[3], steps
    issue_plan = A.PublishPlan(True, [], [{**filed["filed"][0], "kind": "issue", "branch": None}], None)
    assert len(ADAPTER.apply_steps(c, item, issue_plan)) == 2 and "gh issue create" in ADAPTER.apply_steps(c, item, issue_plan)[1]


STUB_GH = r'''#!__PY__
"""A stand-in for `gh` on PATH: reads answer, writes are logged and faked; never the network."""
import json, os, subprocess, sys
argv = sys.argv[1:]
with open(os.environ["DOCTOR_STUB_GH_LOG"], "a") as fh:
    fh.write(json.dumps({"argv": argv, "GH_TOKEN": os.environ.get("GH_TOKEN")}) + "\n")
if argv[:2] == ["api", "user"]:
    if os.environ.get("DOCTOR_STUB_USER_FAIL"):
        sys.stderr.write("HTTP 401: Bad credentials (https://api.github.com/user)\n"); sys.exit(1)
    print("bamr87"); sys.exit(0)
if argv[:2] in (["issue", "list"], ["pr", "list"]):
    if os.environ.get("DOCTOR_STUB_LIST_FAIL"):
        sys.stderr.write("HTTP 502: Bad Gateway\n"); sys.exit(1)
    print("[]"); sys.exit(0)
if argv[:2] == ["repo", "clone"]:
    rest = argv[argv.index("--") + 1:] if "--" in argv else []
    sys.exit(subprocess.run(["git", "clone", *rest, os.environ["DOCTOR_STUB_REMOTE"], argv[3]]).returncode)
if argv[:2] == ["label", "create"]:
    if os.environ.get("DOCTOR_STUB_LABEL_FAIL"):
        sys.stderr.write("HTTP 403: Resource not accessible by integration (labels)\n"); sys.exit(1)
    sys.exit(0)
if argv[:2] == ["pr", "create"]:
    print("https://github.com/" + argv[argv.index("-R") + 1] + "/pull/77"); sys.exit(0)
if argv[:2] == ["issue", "create"]:
    print("https://github.com/" + argv[argv.index("-R") + 1] + "/issues/78"); sys.exit(0)
sys.stderr.write("stub gh: unexpected " + " ".join(argv) + "\n"); sys.exit(3)
'''


def _git(args: list[str], cwd: Path) -> str:
    cfg = ["-c", "user.name=t", "-c", "user.email=t@localhost", "-c", "commit.gpgsign=false"]
    return subprocess.run(["git", *cfg, *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def _remote(tmp: Path) -> Path:
    """A local 'origin' on main carrying the file the fixture patch edits, plus a
    `trunk` branch with the same file (a target whose registry branch is not main)."""
    repo = tmp / "origin"
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "ci.yml").write_text("runs-on: ubuntu-20.04\n")
    _git(["init", "-q", "-b", "main"], repo); _git(["add", "-A"], repo); _git(["commit", "-q", "-m", "init"], repo)
    _git(["branch", "trunk"], repo)
    (repo / "TRUNK.md").write_text("only on trunk\n")
    _git(["checkout", "-q", "trunk"], repo); _git(["add", "-A"], repo); _git(["commit", "-q", "-m", "trunk"], repo)
    _git(["checkout", "-q", "main"], repo)
    _git(["config", "receive.denyCurrentBranch", "updateInstead"], repo)
    return repo


def _apply_world(tmp: Path, **flags: str) -> tuple[dict, Path]:
    """The filer's environment with a stub gh first on PATH and the remote; (env, log)."""
    stub_dir = tmp / "bin"
    stub_dir.mkdir(exist_ok=True)
    gh = stub_dir / "gh"
    gh.write_text(STUB_GH.replace("__PY__", sys.executable), encoding="utf-8")
    gh.chmod(0o755)
    log = tmp / "gh.jsonl"
    env = {**L.deterministic_env(), "PATH": f"{stub_dir}{os.pathsep}{os.environ['PATH']}",
           "DOCTOR_STUB_GH_LOG": str(log), "DOCTOR_STUB_REMOTE": str(_remote(tmp)), "GH_TOKEN": "fleet_test_token",
           **flags}
    return env, log


def _gh_calls(log: Path) -> list[list[str]]:
    return [json.loads(x)["argv"][:2] for x in log.read_text().splitlines()] if log.exists() else []


def test_the_real_filer_dry_run_writes_the_body_and_never_touches_gh_writes():
    c = ctx(Path(tempfile.mkdtemp()))
    item = item_for(c)
    v = validate(c, item, session([(GH_PR, "denied", True)]))
    assert v.ok, v.problems
    bodies = Path(tempfile.mkdtemp())
    argv = S.render_argv(SPEC.local.publish.argv, L.item_values(c, item, validated=v.publish_file))
    assert argv[-2] == "--bodies-dir", argv
    dry = L.dash_gen([*argv[:-1], str(bodies), "--offline"])
    assert dry.ok, (argv, dry.err)
    out = L.parse_last_json(dry.out)
    assert out["apply"] is False and out["filed"][0]["title"] == "ci: move off the retired runner"
    assert Path(out["filed"][0]["body_file"]).read_text().splitlines()[0] == MARKER
    assert Path(out["filed"][0]["patch_file"]).read_text() == PATCH and out["filed"][0]["url"] is None
    # the dry run with a live dedupe reads only; --reviewed-bodies alone and --apply --offline are usage errors
    tmp = Path(tempfile.mkdtemp())
    env, log = _apply_world(tmp)
    live = L.dash_gen([*argv[:-1], str(tmp / "b2")], env=env)
    assert live.ok and _gh_calls(log) == [["issue", "list"], ["pr", "list"]], (live.err, _gh_calls(log))
    assert L.dash_gen([*argv[:-1], str(bodies), "--offline", "--reviewed-bodies", str(bodies)], env=env).code == 2
    assert L.dash_gen([*argv[:-1], str(bodies), "--offline", "--apply", "--reviewed-bodies", str(bodies)],
                      env=env).code == 2
    assert L.dash_gen([*argv[:-1], str(bodies), "--apply"], env=env).code == 2, "--apply needs --reviewed-bodies"


def test_the_filer_apply_makes_exactly_one_push_and_one_draft_pr_and_records_the_url():
    c = ctx(Path(tempfile.mkdtemp()))
    item = item_for(c)
    v = validate(c, item, session([(GH_PR, "denied", True)]))
    assert v.ok, v.problems
    argv = S.render_argv(SPEC.local.publish.argv, L.item_values(c, item, validated=v.publish_file))
    tmp = Path(tempfile.mkdtemp())
    env, log = _apply_world(tmp)
    reviewed = tmp / "bodies"
    assert L.dash_gen([*argv[:-1], str(reviewed), "--offline"], env=env).ok, "the preview to review"
    filed_dir = tmp / "filed"
    res = L.dash_gen([*argv[:-1], str(filed_dir), "--apply", "--reviewed-bodies", str(reviewed)], env=env)
    assert res.ok, res.err
    out = L.parse_last_json(res.out)
    assert out["apply"] is True and out["filed"][0]["url"] == "https://github.com/bamr87/bamr87/pull/77", out
    assert out["skipped"] == [] and "publishing as bamr87" in res.err and "✓ filed" in res.err
    calls = _gh_calls(log)
    # the dedupe reads (open_markers), the readability probe (an apply never files on a failed list read as
    # empty), the token probe, the labels, the scratch clone, the draft PR — and nothing else
    assert calls == [["issue", "list"], ["pr", "list"], ["issue", "list"], ["pr", "list"], ["api", "user"],
                     ["label", "create"], ["label", "create"], ["repo", "clone"], ["pr", "create"]], calls
    rows = [json.loads(x) for x in log.read_text().splitlines()]
    assert all(r["GH_TOKEN"] == "fleet_test_token" for r in rows), "the token reaches gh through the environment only"
    create = next(r["argv"] for r in rows if r["argv"][:2] == ["pr", "create"])
    assert "--draft" in create and create[create.index("--head") + 1] == "fix/fleet-doctor-ci"
    assert create[create.index("--base") + 1] == "main" and create.count("--label") == 2
    assert "fleet_test_token" not in " ".join(create) and "--body-file" in create
    # the one push landed: the branch exists on the remote with the reviewed patch committed as fleet-doctor
    remote = Path(env["DOCTOR_STUB_REMOTE"])
    assert "fix/fleet-doctor-ci" in _git(["branch", "--list", "fix/fleet-doctor-ci"], remote)
    assert "ubuntu-latest" in _git(["show", "fix/fleet-doctor-ci:.github/workflows/ci.yml"], remote)
    assert "fleet-doctor <fleet-doctor@users.noreply.github.com>" in _git(["log", "-1", "--format=%an <%ae>",
                                                                             "fix/fleet-doctor-ci"], remote)
    assert "ci: move off the retired runner" in _git(["log", "-1", "--format=%s", "fix/fleet-doctor-ci"], remote)
    assert (filed_dir / "bamr87-bamr87-.github-workflows-ci.yml.md").read_text().splitlines()[0] == MARKER
    assert not list(tmp.glob("jev-doctor-apply-*")), "the scratch clone is removed"


def test_the_filer_apply_refuses_a_rejected_token_an_unreadable_dedupe_and_an_unreviewed_body():
    c = ctx(Path(tempfile.mkdtemp()))
    item = item_for(c)
    v = validate(c, item, session([(GH_PR, "denied", True)]))
    argv = S.render_argv(SPEC.local.publish.argv, L.item_values(c, item, validated=v.publish_file))
    # a rejected token: exit 3, nothing cloned, pushed or created
    tmp = Path(tempfile.mkdtemp())
    env, log = _apply_world(tmp, DOCTOR_STUB_USER_FAIL="1")
    reviewed = tmp / "bodies"
    assert L.dash_gen([*argv[:-1], str(reviewed), "--offline"], env=env).ok
    res = L.dash_gen([*argv[:-1], str(tmp / "filed"), "--apply", "--reviewed-bodies", str(reviewed)], env=env)
    assert res.code == 3 and FD.TOKEN_REFUSED in res.err and "nothing filed" in res.err, res.err
    out = L.parse_last_json(res.out)
    assert out["filed"] == [] and FD.TOKEN_REFUSED in out["skipped"][0]["reason"]
    assert [c for c in _gh_calls(log) if c[0] in ("repo", "pr", "label", "issue") and c[1] != "list"] == []
    # the dedupe list unreadable: exit 3, nothing filed, no token probe even
    tmp = Path(tempfile.mkdtemp())
    env, log = _apply_world(tmp, DOCTOR_STUB_LIST_FAIL="1")
    reviewed = tmp / "bodies"
    assert L.dash_gen([*argv[:-1], str(reviewed), "--offline"], env=env).ok
    res = L.dash_gen([*argv[:-1], str(tmp / "filed"), "--apply", "--reviewed-bodies", str(reviewed)], env=env)
    assert res.code == 3 and "files nothing without the duplicate check" in res.err, res.err
    assert ["api", "user"] not in _gh_calls(log) and all(c[1] == "list" for c in _gh_calls(log)), _gh_calls(log)
    # a body that is not the reviewed one: withheld (exit 0, NOT_REVIEWED), no write
    tmp = Path(tempfile.mkdtemp())
    env, log = _apply_world(tmp)
    reviewed = tmp / "bodies"
    assert L.dash_gen([*argv[:-1], str(reviewed), "--offline"], env=env).ok
    body = next(reviewed.glob("*.md"))
    body.write_text(body.read_text() + "\nedited after review\n")
    res = L.dash_gen([*argv[:-1], str(tmp / "filed"), "--apply", "--reviewed-bodies", str(reviewed)], env=env)
    assert res.ok, res.err
    out = L.parse_last_json(res.out)
    assert out["filed"] == [] and out["skipped"][0]["reason"] == FD_FILER_NOT_REVIEWED, out
    assert all(c[1] == "list" for c in _gh_calls(log)), _gh_calls(log)
    # the same with the patch changed since the review
    tmp = Path(tempfile.mkdtemp())
    env, log = _apply_world(tmp)
    reviewed = tmp / "bodies"
    assert L.dash_gen([*argv[:-1], str(reviewed), "--offline"], env=env).ok
    next(reviewed.glob("*.patch")).write_text(PATCH.replace("ubuntu-latest", "ubuntu-24.04"))
    out = L.parse_last_json(L.dash_gen([*argv[:-1], str(tmp / "filed"), "--apply", "--reviewed-bodies",
                                        str(reviewed)], env=env).out)
    assert out["filed"] == [] and out["skipped"][0]["reason"] == FD_FILER_NOT_REVIEWED


def test_the_validated_document_carries_the_base_and_the_filer_refuses_a_pr_without_one():
    c = ctx(Path(tempfile.mkdtemp()))
    v = validate(c, item_for(c), session([(GH_PR, "denied", True)]))
    assert v.ok, v.problems
    doc = json.loads(v.publish_file.read_text())
    assert doc["base"] == "main" == item_for(c).branch, "the PR's base is the target's registry branch, the row's"
    assert any("base" in line and "main" in line for line in ADAPTER.apply_steps(c, item_for(c), SimpleNamespace(
        rows=[{"kind": "pr", "repo": "bamr87/bamr87", "branch": "fix/fleet-doctor-ci", "base": "main"}])))
    without = dict(doc); without.pop("base")
    assert any("base" in p and "assumed default" in p for p in FILER.problems(without, v.publish_file.parent))
    for bad in ("", "../main", "main/../x", "a b"):
        assert any("base" in p for p in FILER.problems({**doc, "base": bad}, v.publish_file.parent)), bad
    # an issue needs no base
    issue = {**doc, "kind": "issue", "branch": None, "patch": None, "base": None}
    assert not any("base" in p for p in FILER.problems(issue, v.publish_file.parent))


def test_the_filer_apply_checks_out_the_targets_branch_and_opens_the_pr_against_it():
    c = ctx(Path(tempfile.mkdtemp()))
    item = item_for(c, row(branch="trunk"))   # the hub's registry branch here is trunk, not the clone's default
    v = validate(c, item, session([(GH_PR, "denied", True)]))
    assert v.ok and json.loads(v.publish_file.read_text())["base"] == "trunk", v.problems
    argv = S.render_argv(SPEC.local.publish.argv, L.item_values(c, item, validated=v.publish_file))
    tmp = Path(tempfile.mkdtemp())
    env, log = _apply_world(tmp)
    reviewed = tmp / "bodies"
    assert L.dash_gen([*argv[:-1], str(reviewed), "--offline"], env=env).ok
    res = L.dash_gen([*argv[:-1], str(tmp / "filed"), "--apply", "--reviewed-bodies", str(reviewed)], env=env)
    assert res.ok, res.err
    out = L.parse_last_json(res.out)
    assert out["filed"] and out["filed"][0]["url"].endswith("/pull/77"), out
    create = next(json.loads(x)["argv"] for x in log.read_text().splitlines() if '"create"' in x and '"pr"' in x)
    assert create[create.index("--base") + 1] == "trunk", create
    remote = Path(env["DOCTOR_STUB_REMOTE"])
    fix_parent = _git(["rev-parse", "fix/fleet-doctor-ci^"], remote).strip()
    assert fix_parent == _git(["rev-parse", "trunk"], remote).strip(), "the fix branch starts at the base, not main"
    assert "only on trunk" in _git(["show", "fix/fleet-doctor-ci:TRUNK.md"], remote)
    assert "ubuntu-latest" in _git(["show", "fix/fleet-doctor-ci:.github/workflows/ci.yml"], remote)
    # a base the target does not have: refused after the clone, nothing pushed
    item2 = item_for(c, row(branch="nope"))
    v2 = validate(c, item2, session([(GH_PR, "denied", True)]))
    argv2 = S.render_argv(SPEC.local.publish.argv, L.item_values(c, item2, validated=v2.publish_file))
    tmp2 = Path(tempfile.mkdtemp())
    env2, log2 = _apply_world(tmp2)
    assert L.dash_gen([*argv2[:-1], str(tmp2 / "bodies"), "--offline"], env=env2).ok
    out2 = L.parse_last_json(L.dash_gen([*argv2[:-1], str(tmp2 / "filed"), "--apply", "--reviewed-bodies",
                                         str(tmp2 / "bodies")], env=env2).out)
    assert out2["filed"] == [] and "base branch nope is not in" in out2["skipped"][0]["reason"], out2
    assert ["pr", "create"] not in _gh_calls(log2)
    assert "fix/fleet-doctor-ci" not in _git(["branch", "--list", "fix/fleet-doctor-ci"], Path(env2["DOCTOR_STUB_REMOTE"]))


def test_the_filer_apply_files_nothing_when_a_label_cannot_be_created():
    c = ctx(Path(tempfile.mkdtemp()))
    item = item_for(c)
    v = validate(c, item, session([(GH_PR, "denied", True)]))
    argv = S.render_argv(SPEC.local.publish.argv, L.item_values(c, item, validated=v.publish_file))
    tmp = Path(tempfile.mkdtemp())
    env, log = _apply_world(tmp, DOCTOR_STUB_LABEL_FAIL="1")
    reviewed = tmp / "bodies"
    assert L.dash_gen([*argv[:-1], str(reviewed), "--offline"], env=env).ok
    res = L.dash_gen([*argv[:-1], str(tmp / "filed"), "--apply", "--reviewed-bodies", str(reviewed)], env=env)
    assert res.code == 3 and FD.LABELS_REFUSED in res.err and "nothing filed" in res.err, res.err
    out = L.parse_last_json(res.out)
    assert out["filed"] == [] and FD.LABELS_REFUSED in out["skipped"][0]["reason"], out
    calls = _gh_calls(log)
    assert ["label", "create"] in calls and ["repo", "clone"] not in calls and ["pr", "create"] not in calls, calls
    remote = Path(env["DOCTOR_STUB_REMOTE"])
    assert "fix/fleet-doctor-ci" not in _git(["branch", "--list", "fix/fleet-doctor-ci"], remote), "nothing pushed"


def test_the_filer_apply_never_pushes_onto_an_existing_fix_branch():
    c = ctx(Path(tempfile.mkdtemp()))
    item = item_for(c)
    v = validate(c, item, session([(GH_PR, "denied", True)]))
    argv = S.render_argv(SPEC.local.publish.argv, L.item_values(c, item, validated=v.publish_file))
    run_url = argv[argv.index("--run-url") + 1]
    # someone else's commit on the fix branch: refused, the branch untouched, no PR
    tmp = Path(tempfile.mkdtemp())
    env, log = _apply_world(tmp)
    remote = Path(env["DOCTOR_STUB_REMOTE"])
    _git(["checkout", "-q", "-b", "fix/fleet-doctor-ci"], remote)
    (remote / "OTHER.md").write_text("someone else's work\n")
    _git(["add", "-A"], remote); _git(["commit", "-q", "-m", "unrelated"], remote); _git(["checkout", "-q", "main"], remote)
    taken_tip = _git(["rev-parse", "fix/fleet-doctor-ci"], remote).strip()
    reviewed = tmp / "bodies"
    assert L.dash_gen([*argv[:-1], str(reviewed), "--offline"], env=env).ok
    res = L.dash_gen([*argv[:-1], str(tmp / "filed"), "--apply", "--reviewed-bodies", str(reviewed)], env=env)
    assert res.ok, res.err
    out = L.parse_last_json(res.out)
    assert out["filed"] == [] and FD.BRANCH_TAKEN in out["skipped"][0]["reason"], out
    assert _git(["rev-parse", "fix/fleet-doctor-ci"], remote).strip() == taken_tip, "no push onto the branch"
    assert ["pr", "create"] not in _gh_calls(log)
    # this run's own commit already on the branch (a PR create that failed after its push): reused, no push
    tmp = Path(tempfile.mkdtemp())
    env, log = _apply_world(tmp)
    remote = Path(env["DOCTOR_STUB_REMOTE"])
    _git(["checkout", "-q", "-b", "fix/fleet-doctor-ci"], remote)
    (remote / ".github" / "workflows" / "ci.yml").write_text("runs-on: ubuntu-latest\n")
    _git(["add", "-A"], remote)
    _git(["commit", "-q", "-m", "ci: move off the retired runner", "-m",
          f"Fleet doctor, run locally ({run_url}); the pull request body carries the MARKER line."], remote)
    _git(["checkout", "-q", "main"], remote)
    ours_tip = _git(["rev-parse", "fix/fleet-doctor-ci"], remote).strip()
    reviewed = tmp / "bodies"
    assert L.dash_gen([*argv[:-1], str(reviewed), "--offline"], env=env).ok
    res = L.dash_gen([*argv[:-1], str(tmp / "filed"), "--apply", "--reviewed-bodies", str(reviewed)], env=env)
    assert res.ok, res.err
    out = L.parse_last_json(res.out)
    assert out["filed"] and out["filed"][0]["url"].endswith("/pull/77") and "reusing it, no push" in res.err, (out, res.err)
    assert _git(["rev-parse", "fix/fleet-doctor-ci"], remote).strip() == ours_tip, "reused as it was"
    assert ["pr", "create"] in _gh_calls(log)


def test_context_request_names_the_hub_and_queries_the_candidate():
    c = ctx(Path(tempfile.mkdtemp()))
    req = ADAPTER.context_request(c, item_for(c))
    assert req.nwo == "bamr87/bamr87" and req.name == "bamr87"
    assert req.queries[0].startswith(".github/workflows/ci.yml failing") and "CI workflow" in req.queries[1]


def test_recheck_reads_the_live_plan_for_the_one_candidate():
    c = ctx(Path(tempfile.mkdtemp()))
    item = item_for(c)
    c.planner = lambda target=None, no_files=False: {"include": [{"key": target}], "skipped": []}
    assert ADAPTER.recheck(c, item) is None
    c.planner = lambda target=None, no_files=False: {"include": [], "skipped": [{"key": target, "reason": "tracked"}]}
    assert ADAPTER.recheck(c, item) == "tracked"


# --------------------------------------------------------------------------- #
# boundaries
# --------------------------------------------------------------------------- #
def test_the_adapter_and_filer_hold_no_route_to_a_merge_a_force_or_a_delete():
    filer = HUB / ".github" / "scripts" / "dash-gen" / "fleet_doctor_file.py"
    for f in (HUB / "tools" / "jev" / "adapters" / "fleet_pulse_doctor.py", filer):
        src = f.read_text(encoding="utf-8")
        for bad in ("pr merge", "--admin", "git push", "push --force", "--force-with-lease", "--mirror", "--delete",
                    "issue close", "issue edit", "pr close", "dangerously", "bypassPermissions", "import ai_activity",
                    "dash_gen.py", "type: ignore", "x-access-token"):
            assert bad not in src, f"{f.name}: {bad}"
        assert not re.search(r"^\s*except[^\n]*:\s*\n\s*pass\b", src, re.M), f"{f.name}: an empty handler"
    assert "sys.path" not in (HUB / "tools" / "jev" / "adapters" / "fleet_pulse_doctor.py").read_text()
    # the filer's ONE push: an explicit src:dst refspec, git's own receive-pack pinned, the credential from gh
    src = filer.read_text(encoding="utf-8")
    pushes = [m.group(0) for m in re.finditer(r'_run\(\[[^\]]*"push",[^\]]*\]', src, re.S)]
    assert len(pushes) == 1, pushes
    push = pushes[0]
    assert "HEAD:refs/heads/" in push and "RECEIVE_PACK" in push and "CREDENTIAL_HELPER" in push, push
    assert '"-f"' not in src and "'-f'" not in src


def test_the_markers_and_messages_agree_with_the_planner_and_the_filer():
    sys.path.insert(0, str(HUB / ".github" / "scripts" / "dash-gen"))
    import fleet_doctor_file as filer
    import remediation
    assert remediation.MARKER_RE.fullmatch(MARKER) and FD.MARKER_RX.fullmatch(MARKER)
    assert remediation.doctor_marker(KEY) == MARKER
    assert FD.NO_DEDUPE == filer.NO_DEDUPE and FD.NOT_REVIEWED in filer.NOT_REVIEWED
    assert FD.TOKEN_REFUSED == filer.TOKEN_REFUSED and filer.RECEIVE_PACK == "--receive-pack=git-receive-pack"
    assert FD.LABELS_REFUSED == filer.LABELS_REFUSED and FD.BRANCH_TAKEN == filer.BRANCH_TAKEN
    assert S.PUBLISH_COMMANDS["doctor-file"] == "--apply" and S.PUBLISH_REVIEWED_FLAGS["doctor-file"] == "--reviewed-bodies"
    assert S.PLANNER_BRIEFS["remediate"].fullmatch("doctor-workorder-law-ai-ci.md")


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
