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
file, that the filer's structural rules run on the copy and its --apply is
refused naming #488, and that the engine's modules hold no route to a merge, a
push or dash-gen.

No network, no gh: the planner and the filer run `--offline`.
Run: python3 tools/test_jev_adapter_fleet_pulse_doctor.py
"""
from __future__ import annotations

import json
import re
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

SPEC = S.load_spec("fleet-pulse", "doctor")
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


def test_publish_parses_the_dry_run_and_the_apply_refusal_names_488():
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
    refused = ADAPTER.publish(c, item, v, lambda: _run(2, None, err="doctor-file: " + FD.APPLY_REFUSED + " …"),
                              apply=True)
    assert not refused.publishable and any("#488" in b for b in refused.blockers), refused.blockers


def test_the_real_filer_dry_run_writes_the_body_and_its_apply_is_refused():
    c = ctx(Path(tempfile.mkdtemp()))
    item = item_for(c)
    v = validate(c, item, session([(GH_PR, "denied", True)]))
    assert v.ok, v.problems
    bodies = Path(tempfile.mkdtemp())
    argv = S.render_argv(SPEC.local.publish.argv, L.item_values(c, item, validated=v.publish_file))
    dry = L.dash_gen([*argv[:-1], str(bodies), "--offline"]) if argv[-2] == "--bodies-dir" else None
    assert dry is not None and dry.ok, (argv, dry and dry.err)
    out = L.parse_last_json(dry.out)
    assert out["filed"][0]["title"] == "ci: move off the retired runner" and Path(out["filed"][0]["body_file"]).is_file()
    assert Path(out["filed"][0]["body_file"]).read_text().splitlines()[0] == MARKER
    assert Path(out["filed"][0]["patch_file"]).read_text() == PATCH
    applied = L.dash_gen([*argv[:-1], str(bodies), "--apply", "--reviewed-bodies", str(bodies)])
    assert applied.code == 2 and "#488" in applied.err and "nothing was filed" in applied.err, applied.err
    assert not list(bodies.glob("*")) or len(list(bodies.glob("*.md"))) == 1, "the apply wrote nothing new"


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
def test_the_adapter_and_filer_hold_no_route_to_a_merge_or_a_push():
    for f in (HUB / "tools" / "jev" / "adapters" / "fleet_pulse_doctor.py",
              HUB / ".github" / "scripts" / "dash-gen" / "fleet_doctor_file.py"):
        src = f.read_text(encoding="utf-8")
        for bad in ("pr merge", "--admin", "git push", "push --force", "issue close", "issue edit", "dangerously",
                    "bypassPermissions", "import ai_activity", "dash_gen.py", "type: ignore"):
            assert bad not in src, f"{f.name}: {bad}"
        assert not re.search(r"^\s*except[^\n]*:\s*\n\s*pass\b", src, re.M), f"{f.name}: an empty handler"
    assert "sys.path" not in (HUB / "tools" / "jev" / "adapters" / "fleet_pulse_doctor.py").read_text()


def test_the_markers_and_messages_agree_with_the_planner_and_the_filer():
    sys.path.insert(0, str(HUB / ".github" / "scripts" / "dash-gen"))
    import fleet_doctor_file as filer
    import remediation
    assert remediation.MARKER_RE.fullmatch(MARKER) and FD.MARKER_RX.fullmatch(MARKER)
    assert remediation.doctor_marker(KEY) == MARKER
    assert FD.NO_DEDUPE == filer.NO_DEDUPE and FD.APPLY_REFUSED in filer.APPLY_REFUSED
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
