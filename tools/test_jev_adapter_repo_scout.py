#!/usr/bin/env python3
"""
Fixture tests for tools/jev/adapters/ — the loop engine's adapter contract and
its first adapter, repo_scout (#486, ADR 0002 P1). The adapter maps the
planner's and the filer's JSON and holds the scout's local-only decisions, so
what is tested is that it maps the real planner's output, that tier 0 reuses
only an identical attempt, that --apply needs a live dedupe, that validation
withholds what would leak this machine and flags local-runner artefacts, that
a publish failure is seen the way CI's file job sees it, and that the engine's
modules hold no route to a merge, a push or dash-gen.

No network, no gh: the planner and the filer run `--offline`.
Run: python3 tools/test_jev_adapter_repo_scout.py
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import re
import shlex
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import yaml

HUB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUB))

from tools.jev import adapters as A  # noqa: E402
from tools.jev import loop as L  # noqa: E402
from tools.jev import spec as S  # noqa: E402
from tools.jev.adapters import repo_scout as RS  # noqa: E402
from tools.jev.common import JevError, Run  # noqa: E402

SPEC = S.load_spec("repo-scout", "scout")
ADAPTER = A.get("repo_scout")
GOOD = {"title": "Add a --help flag to the CLI entrypoint", "kind": "feature", "type": "feature",
        "priority": "P2", "size": "size:s", "body": "## Problem\n" + "The CLI prints nothing useful. " * 5}


def registry(tmp: Path) -> Path:
    p = tmp / "projects.yml"
    p.write_text(yaml.safe_dump([{"name": "alpha", "slug": "alpha", "repo_url": "https://github.com/bamr87/alpha",
                                  "branch": "main", "category": "dev-tools", "status": "active",
                                  "stack": ["python"], "description": "alpha does things"}]), encoding="utf-8")
    return p


def offline_plan(tmp: Path) -> dict:
    """The REAL planner, offline, against a one-entry fixture registry."""
    res = L.dash_gen(["scout", "--offline", "--target", "alpha", "--registry", str(registry(tmp)),
                      "--out-dir", str(tmp / "plan")])
    assert res.ok, res.err
    return L.parse_last_json(res.out)


def ctx(tmp: Path, work_root: str = "/Users/someone/.cache/jev/work", **opts) -> SimpleNamespace:
    o = L.Options(**opts)
    runs = tmp / "runs"

    def item_dir(item):
        return tmp / "items" / item.key.replace("/", "__")
    return SimpleNamespace(spec=SPEC, opts=o, plan_dir=tmp / "plan", history=L.History(runs),
                           home=Path("/Users/someone"), hostname="someones-mac", work_root=Path(work_root),
                           item_dir=item_dir,
                           bodies_dir=lambda item, apply: item_dir(item) / ("filed" if apply else "bodies"),
                           dash_gen=L.dash_gen, planner=None)


def one_item(tmp: Path, **opts):
    c = ctx(tmp, **opts)
    result = ADAPTER.items(c, offline_plan(tmp))
    return c, result, result.items[0]


def harvested(dest: Path | None, reason: str = "ok") -> dict:
    from tools.jev.workspace import Harvest
    return {RS.OUTPUT: Harvest(RS.OUTPUT, dest, None, 0, reason)}


# --------------------------------------------------------------------------- #
# the registry
# --------------------------------------------------------------------------- #
def test_the_registry_names_modules_and_get_returns_an_adapter():
    assert A.REGISTRY == {"repo_scout": "tools.jev.adapters.repo_scout"}
    assert isinstance(ADAPTER, A.Adapter) and ADAPTER.name == "repo_scout"
    try:
        A.get("os")
    except KeyError:
        pass
    else:
        raise AssertionError("a name outside REGISTRY was imported")


# --------------------------------------------------------------------------- #
# items, reuse, classify
# --------------------------------------------------------------------------- #
def test_items_maps_the_real_offline_planner_output():
    tmp = Path(tempfile.mkdtemp())
    c, result, item = one_item(tmp)
    assert [i.key for i in result.items] == ["bamr87/alpha"]
    assert (item.name, item.nwo, item.branch) == ("alpha", "bamr87/alpha", "main")
    assert item.brief == tmp / "plan" / "scout-workorder-alpha.md" and item.brief.is_file()
    assert set(SPEC.inputs.values()) <= set(item.row), "the row carries every spec input"
    assert item.row["prompt"] == S.render_prompt(SPEC, S.values_from(SPEC, item.row)), "prompt parity"
    assert result.meta["eligible"] == 1


def test_items_refuses_a_row_whose_brief_is_not_a_bare_name():
    tmp = Path(tempfile.mkdtemp())
    c = ctx(tmp)
    plan = offline_plan(tmp)
    for bad in ("briefs/x.md", "/etc/hosts", "../x.md", "..", "", None):
        row = {**plan["include"][0], "brief": bad}
        try:
            ADAPTER.items(c, {**plan, "include": [row]})
        except JevError as exc:
            assert "brief" in str(exc)
        else:
            raise AssertionError(f"brief {bad!r} was accepted")
    try:
        ADAPTER.items(c, {**plan, "include": [{**plan["include"][0], "nwo": "o/.."}]})
    except JevError:
        pass
    else:
        raise AssertionError("an nwo of '..' was accepted")


def test_planner_skipped_rows_carry_the_item_key():
    tmp = Path(tempfile.mkdtemp())
    c = ctx(tmp)
    plan = {"include": [], "skipped": [{"name": "alpha", "nwo": "bamr87/alpha", "reason": "3 open"},
                                       {"name": "beta", "reason": "no nwo known"}]}
    skipped = ADAPTER.items(c, plan).skipped
    assert skipped[0]["key"] == "bamr87/alpha" and "key" not in skipped[1]


def test_the_reuse_key_ignores_the_prepared_line_and_nothing_else():
    tmp = Path(tempfile.mkdtemp())
    c, _, item = one_item(tmp)
    head = "a" * 40
    k = ADAPTER.reuse_key(c, item, head)
    text = item.brief.read_text(encoding="utf-8")
    assert RS.PREPARED_RX.search(text), "the brief carries its per-run line"
    item.brief.write_text(RS.PREPARED_RX.sub("Prepared 1999-01-01 00:00 UTC", text), encoding="utf-8")
    assert ADAPTER.reuse_key(c, item, head) == k, "only the timestamp differs"
    assert ADAPTER.reuse_key(c, item, "b" * 40) != k, "a new HEAD is new work"
    item.brief.write_text(text + "\nA new open issue.\n", encoding="utf-8")
    assert ADAPTER.reuse_key(c, item, head) != k, "a new brief is new work"
    item.brief.write_text(text, encoding="utf-8")
    c.spec = dataclasses.replace(SPEC, template=SPEC.template + "x\n")
    assert ADAPTER.reuse_key(c, item, head) != k, "a new prompt is new work"
    assert ADAPTER.reuse_key(c, item, None) is None, "no HEAD, no reuse"


def _seed(runs: Path, run_id: str, rows: list[dict]) -> None:
    d = runs / run_id
    d.mkdir(parents=True, exist_ok=True)
    with (d / "attempts.jsonl").open("a") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def test_tier0_reuses_an_unpublished_twin_skips_a_published_one_and_fresh_bypasses():
    tmp = Path(tempfile.mkdtemp())
    c, _, item = one_item(tmp)
    head = "c" * 40
    key = ADAPTER.reuse_key(c, item, head)
    assert ADAPTER.tier0(c, item, head).action == "continue", "no history"
    assert ADAPTER.tier0(c, item, "").action == "skip", "an empty branch has nothing to read"
    now = L.iso()
    base = {"loop": "repo-scout", "step": "scout", "item": item.key, "decision": "attempt", "outcome": "ok",
            "reuse_key": key, "validated_sha256": "f" * 64, "ts": now}
    _seed(c.history.base, "r-old", [{**base, "ts": L.iso(L.now_utc() - dt.timedelta(days=A.REUSE_DAYS + 1))}])
    assert ADAPTER.tier0(c, item, head).action == "continue", "older than REUSE_DAYS"
    _seed(c.history.base, "r-1", [base])
    t0 = ADAPTER.tier0(c, item, head)
    assert t0.action == "reuse" and "r-1" in t0.reason and t0.reuse_from == c.history.base / "r-1" / "items" / \
        "bamr87__alpha", t0
    _seed(c.history.base, "r-1", [{**base, "decision": "publish-apply", "published": True}])
    assert ADAPTER.tier0(c, item, head).action == "skip", "a published twin is skipped"
    c.opts.fresh = True
    assert ADAPTER.tier0(c, item, head).action == "continue", "--fresh bypasses tier 0"
    c.opts.fresh = False
    _seed(c.history.base, "r-2", [{**base, "outcome": "budget_hit", "reuse_key": "other"}])
    assert ADAPTER.tier0(c, item, "d" * 40).action == "continue", "only an ok attempt with the same key counts"


def test_a_publish_in_a_later_run_that_reused_the_attempt_counts_as_published():
    tmp = Path(tempfile.mkdtemp())
    c, _, item = one_item(tmp)
    head = "e" * 40
    key = ADAPTER.reuse_key(c, item, head)
    base = {"loop": "repo-scout", "step": "scout", "item": item.key, "reuse_key": key, "ts": L.iso()}
    _seed(c.history.base, "run-a", [{**base, "decision": "attempt", "outcome": "ok", "validated_sha256": "1" * 64}])
    assert ADAPTER.tier0(c, item, head).action == "reuse"
    _seed(c.history.base, "run-b", [{**base, "decision": "tier0-reuse", "reuse_from": "run-a"},
                                    {**base, "decision": "publish-apply", "published": True,
                                     "validated_sha256": "1" * 64}])
    t0 = ADAPTER.tier0(c, item, head)
    assert t0.action == "skip", t0
    _seed(c.history.base, "run-c", [{**base, "decision": "publish-apply", "published": True,
                                     "validated_sha256": "2" * 64}])
    assert ADAPTER.tier0(c, item, head).action == "skip", "another file's publish changes nothing"


def test_classify_blocks_apply_without_a_live_dedupe():
    tmp = Path(tempfile.mkdtemp())
    c, _, item = one_item(tmp, apply=True)
    assert item.row["dedupe"] == "unavailable", "an offline plan has no dedupe"
    t = ADAPTER.classify(c, item)
    assert t.blocked and "dedupe" in t.reason
    item.row["dedupe"] = "clear"
    assert not ADAPTER.classify(c, item).blocked
    c.opts.apply = False
    item.row["dedupe"] = "unavailable"
    assert not ADAPTER.classify(c, item).blocked, "a dry run does not need the dedupe"


# --------------------------------------------------------------------------- #
# validate
# --------------------------------------------------------------------------- #
def _validate(tmp: Path, payload) -> A.Verdict:
    c, _, item = one_item(tmp)
    raw = tmp / "raw.json"
    raw.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
    return ADAPTER.validate(c, item, harvested(raw), None)


def test_an_absent_output_is_zero_proposals_and_valid():
    tmp = Path(tempfile.mkdtemp())
    c, _, item = one_item(tmp)
    v = ADAPTER.validate(c, item, harvested(None, "absent"), None)
    assert v.ok and v.facts["proposals"] == 0
    assert json.loads(v.publish_file.read_text()) == {"proposals": [], "notes": ""}


def test_a_refused_or_corrupt_output_is_not_valid():
    tmp = Path(tempfile.mkdtemp())
    c, _, item = one_item(tmp)
    v = ADAPTER.validate(c, item, harvested(None, "symlink"), None)
    assert not v.ok and "symlink" in v.problems[0] and v.publish_file is None
    assert not _validate(Path(tempfile.mkdtemp()), "{not json").ok
    assert not _validate(Path(tempfile.mkdtemp()), "42").ok


def test_validate_runs_the_filers_offline_rules_on_the_copy():
    v = _validate(Path(tempfile.mkdtemp()), {"proposals": [GOOD, {"title": "short", "kind": "fix", "body": "x"}],
                                             "notes": "looked at the CLI"})
    assert v.ok, v.problems
    assert v.facts["proposals"] == 2 and v.facts["would_file"] == 1 and len(v.facts["rejected"]) == 1
    assert v.facts["notes"] == "looked at the CLI"
    kept = json.loads(v.publish_file.read_text())
    assert kept["proposals"] == [GOOD, {"title": "short", "kind": "fix", "body": "x"}], "the filer decides, not this"


def test_the_privacy_filter_withholds_a_local_path_or_the_host_name():
    leaks = [dict(GOOD, body=GOOD["body"] + " see /Users/someone/.ssh"), dict(GOOD, title="Fix someones-mac build")]
    v = _validate(Path(tempfile.mkdtemp()), {"proposals": [GOOD, *leaks]})
    assert v.ok and len(json.loads(v.publish_file.read_text())["proposals"]) == 1
    withheld = [r for r in v.facts["rejected"] if r["reason"] == "carries a local path or the host name"]
    assert len(withheld) == 2 and all("someone" not in json.dumps(r) for r in withheld), "never echoed"


def test_the_privacy_filter_withholds_a_work_root_outside_home():
    tmp = Path(tempfile.mkdtemp())
    c, _, item = one_item(tmp)
    c.work_root = Path("/var/jev-work")
    raw = tmp / "raw.json"
    raw.write_text(json.dumps({"proposals": [GOOD, dict(GOOD, body=GOOD["body"] + " in /var/jev-work/r/x")]}))
    v = ADAPTER.validate(c, item, harvested(raw), None)
    assert v.ok and len(json.loads(v.publish_file.read_text())["proposals"]) == 1


def test_a_local_runner_artefact_is_flagged_not_rejected():
    art = dict(GOOD, body=GOOD["body"] + "\nnpm install fails: getaddrinfo EAI_AGAIN registry.npmjs.org")
    v = _validate(Path(tempfile.mkdtemp()), [art])
    assert v.ok and v.facts["would_file"] == 1
    assert v.flags and "local-runner denial" in v.flags[0]


# --------------------------------------------------------------------------- #
# publish and recheck
# --------------------------------------------------------------------------- #
def test_the_publish_argv_is_cis_file_step_plus_the_bodies_dir():
    values = {"nwo": "bamr87/alpha", "validated": "/r/items/x/outputs/proposals.validated.json",
              "run_ref": "local run R (tools/jev loop)", "item_dir": "/r/items/x", "bodies_dir": "/r/items/x/bodies"}
    argv = S.render_argv(SPEC.local.publish.argv, values)
    assert argv == ["scout-file", "--nwo", "bamr87/alpha", "--proposals", values["validated"], "--run-url",
                    values["run_ref"], "--bodies-dir", "/r/items/x/bodies"]
    try:
        S.render_argv(SPEC.local.publish.argv, {k: v for k, v in values.items() if k != "validated"})
    except S.StepSpecError:
        pass
    else:
        raise AssertionError("a publish without the adapter's validated file rendered")
    assert "--apply" not in argv and SPEC.local.publish.apply_flag == "--apply", "--apply is the engine's, after the gate"
    run = yaml.safe_load((HUB / ".github" / "workflows" / "repo-scout.yml").read_text())["jobs"]["file"]
    step = next(s for s in run["steps"] if s.get("name") == "File the issues")["run"]
    line = next(ln for ln in step.splitlines() if "scout-file" in ln)
    ci = shlex.split(line.strip().rstrip("\\"))
    assert ci[0] == "tools/dash-gen" and ci[1] == argv[0], ci
    assert ci[2:8:2] == argv[1:7:2] == ["--nwo", "--proposals", "--run-url"], (ci, argv)
    assert SPEC.risk[SPEC.local.publish.risk]["tier"] == "high"


def _run(code: int = 0, out: object = None, err: str = "") -> Run:
    return Run(code, json.dumps(out) + "\n" if out is not None else "", err)


def test_publish_parses_the_dry_run_and_turns_signals_into_blockers_and_failures():
    tmp = Path(tempfile.mkdtemp())
    c, _, item = one_item(tmp)
    v = A.Verdict(True)
    dry = {"nwo": item.nwo, "apply": False, "filed": [{"title": "T", "labels": ["ai-scout"], "url": None,
                                                         "body_file": "01-t.md"}], "skipped": [], "rejected": []}
    plan = ADAPTER.publish(c, item, v, lambda: _run(0, dry))
    assert plan.publishable and plan.rows == [{"title": "T", "labels": ["ai-scout"], "url": None,
                                               "body_file": "01-t.md"}]
    assert plan.bodies_dir == tmp / "items" / "bamr87__alpha" / "bodies"
    applied = ADAPTER.publish(c, item, v, lambda: _run(0, {**dry, "apply": True}), apply=True)
    assert applied.bodies_dir == tmp / "items" / "bamr87__alpha" / "filed", "the apply never writes over the preview"
    nodedupe = ADAPTER.publish(c, item, v, lambda: _run(0, dry, "could not list open issues of x — filing "
                                                                "without the duplicate check\n"))
    assert not nodedupe.publishable and nodedupe.blockers == ["dedupe_unavailable"]
    failed = ADAPTER.publish(c, item, v, lambda: _run(0, {**dry, "apply": True, "filed": [],
                                                          "skipped": [{"title": "T", "reason": RS.FILE_FAILED}]}))
    assert failed.failures == ["T"] and not failed.publishable
    assert not ADAPTER.publish(c, item, v, lambda: Run(2, "", "boom")).publishable
    assert not ADAPTER.publish(c, item, v, lambda: Run(0, "not json", "")).publishable


def test_recheck_reads_the_live_plan_for_the_one_target():
    tmp = Path(tempfile.mkdtemp())
    c, _, item = one_item(tmp)
    seen = {}

    def planner(**kw):
        seen.update(kw)
        return {"include": [{"nwo": item.nwo}]}
    c.planner = planner
    assert ADAPTER.recheck(c, item) is None and seen == {"target": "alpha", "no_files": True}
    c.planner = lambda **kw: {"include": [], "skipped": [{"name": "alpha", "reason": "3 scout issue(s) still open"}]}
    assert ADAPTER.recheck(c, item) == "3 scout issue(s) still open"
    c.planner = lambda **kw: {"include": []}
    assert ADAPTER.recheck(c, item) == "no longer in the plan"


# --------------------------------------------------------------------------- #
# boundaries
# --------------------------------------------------------------------------- #
ENGINE_FILES = [HUB / "tools" / "jev" / n for n in ("loop.py", "workspace.py")] + \
    sorted((HUB / "tools" / "jev" / "adapters").glob("*.py"))


def test_the_engine_holds_no_route_to_a_merge_a_push_or_dash_gen():
    for f in ENGINE_FILES:
        src = f.read_text(encoding="utf-8")
        for bad in ("pr merge", "--admin", "git push", "push --force", "issue close", "issue edit", "dangerously",
                    "bypassPermissions", "import ai_activity", "import repo_scout", "dash_gen.py", "type: ignore",
                    "sys.path"):
            assert bad not in src, f"{f.name}: {bad}"
        assert not re.search(r"^\s*except[^\n]*:\s*\n\s*pass\b", src, re.M), f"{f.name}: an empty handler"


def test_the_secret_pattern_and_the_filers_agree():
    sys.path.insert(0, str(HUB / ".github" / "scripts" / "dash-gen"))
    import repo_scout as filer
    from tools.jev import headless
    assert filer.SECRET_RE.pattern == headless.SECRET_RE.pattern
    assert RS.FILE_FAILED in (HUB / ".github" / "scripts" / "dash-gen" / "repo_scout.py").read_text()
    assert RS.NO_DEDUPE in (HUB / ".github" / "scripts" / "dash-gen" / "repo_scout.py").read_text()
    assert RS.FILE_FAILED in (HUB / ".github" / "workflows" / "repo-scout.yml").read_text(), "CI greps the same"


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
