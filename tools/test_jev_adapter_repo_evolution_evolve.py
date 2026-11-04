#!/usr/bin/env python3
"""
Fixture tests for tools/jev/adapters/repo_evolution_evolve.py — the evolution
agent's adapter on the loop engine (bamr87/bamr87#488, ADR 0002 P3, step 2).
The adapter maps the planner's JSON (`dash-gen targets`, CI's plan job) and
the filer's dry run (`dash-gen evolve-file`), so what is tested is that it
maps the REAL offline planner's output (every row carrying the spec's
render), that tier 0 reuses only an identical attempt, that --apply needs a
live dedupe, that validation turns the engine's patch and the agent's final
message into one document with the marker line first and CI's lockfile drop,
footer, PARTIAL warning and #220 remote applied, that an empty pass is valid
and files nothing, that what would leak this machine is withheld, that the
filer's structural rules run on the copy and its --apply is refused naming
#488, and that the engine's modules hold no route to a merge, a push or
dash-gen.

No network, no gh: the planner and the filer run `--offline`.
Run: python3 tools/test_jev_adapter_repo_evolution_evolve.py
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
from tools.jev.adapters import common as C  # noqa: E402
from tools.jev.adapters import repo_evolution_evolve as EV  # noqa: E402
from tools.jev.common import JevError, Run  # noqa: E402
from tools.jev.workspace import Harvest  # noqa: E402

SPEC = S.load_spec("repo-evolution", "evolve")
ADAPTER = A.get("repo_evolution_evolve")
NWO = "bamr87/alpha"
MARKER = f'<!-- repo-evolution key="{NWO}" -->'
PATCH = ("diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1 +1,2 @@\n # alpha\n"
         "+Install with `pip install alpha`.\n")
LOCK = ("diff --git a/package-lock.json b/package-lock.json\nnew file mode 100644\n--- /dev/null\n"
        "+++ b/package-lock.json\n@@ -0,0 +1 @@\n+{}\n")
SUMMARY = ("1. **What changed** — README.md: the install line names the package.\n2. **Why** — the README said "
           "`pip install`, nothing more.\n3. **Verification** — `pytest -q` (3 passed).\n4. **Not done** — nothing.")


def offline_plan(tmp: Path, target: str = "all") -> dict:
    """The REAL planner, offline, against the hub's committed registry and snapshots."""
    res = L.dash_gen(["targets", "--out-dir", str(tmp / "plan"), "--offline", f"--target={target}"])
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
                           item_dir=item_dir, fleet=S.load_fleet(), run=SimpleNamespace(run_id="20261103T000000Z-t"),
                           bodies_dir=lambda item, apply: item_dir(item) / ("filed" if apply else "bodies"),
                           dash_gen=L.dash_gen, planner=None, run_ref=lambda: "local run t (tools/jev loop)")


def _call(n: int, name: str, inp: dict, result: str, is_error: bool = False) -> list[dict]:
    return [{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": f"t{n}", "name": name,
                                                           "input": inp}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": f"t{n}",
                                                      "content": result, "is_error": is_error}]}}]


def session(calls: list[tuple[str, str, bool]] = (), result: str = SUMMARY) -> list[dict]:
    events = [{"type": "system", "subtype": "init", "session_id": "s", "tools": ["Bash", "Read", "Edit"]}]
    for i, (cmd, out, err) in enumerate(calls, 1):
        events += _call(i, "Bash", {"command": cmd}, out, err)
    events.append({"type": "result", "subtype": "success", "result": result})
    return events


def row(nwo: str = NWO, **extra) -> dict:
    name = nwo.split("/", 1)[1]
    return {"name": name, "nwo": nwo, "branch": "main", "category": "dev-tools",
            "brief": f"evolution-workorder-{name}.md", "marker": f'<!-- repo-evolution key="{nwo}" -->',
            "dedupe": "clear", **extra}


def item_for(c, r: dict | None = None, brief: str | None = None) -> A.Item:
    r = r or row()
    c.plan_dir.mkdir(parents=True, exist_ok=True)
    (c.plan_dir / r["brief"]).write_text(brief if brief is not None else
                                         f"{r['marker']}\n# Evolution brief — {r['name']}\n\nPrepared 2026-11-03 "
                                         "12:00 UTC by `dash-gen targets` for x.\n\n## Focus for this run\n\n"
                                         "_No operator focus was given — let the signals choose._\n", encoding="utf-8")
    return ADAPTER.items(c, {"include": [r]}).items[0]


def validate(c, item: A.Item, events: list[dict], patch: str | None = PATCH, kind: str = "ok") -> A.Verdict:
    d = c.item_dir(item)
    (d / "trace.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    if patch is None:
        h = Harvest(EV.PATCH, None, None, 0, "absent")
    else:
        dest = d / "outputs" / "changes.patch"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(patch, encoding="utf-8")
        h = Harvest(EV.PATCH, dest, "x", len(patch), "ok")
    return ADAPTER.validate(c, item, {EV.PATCH: h}, {"kind": kind})


# --------------------------------------------------------------------------- #
# the registry, items, reuse, classify
# --------------------------------------------------------------------------- #
def test_the_adapter_is_registered_and_the_spec_names_it():
    assert A.REGISTRY["repo_evolution_evolve"] == "tools.jev.adapters.repo_evolution_evolve"
    assert isinstance(ADAPTER, A.Adapter) and ADAPTER.name == "repo_evolution_evolve"
    assert SPEC.local.adapter == "repo_evolution_evolve" and SPEC.local.harvest == "patch"
    assert SPEC.local.on_budget_hit == "publish-flagged" and SPEC.workspace.cwd == "target"
    assert SPEC.workspace.github_credential == "fleet-read" and SPEC.workspace.outputs == ()
    assert SPEC.local.planner.argv[0] == "targets" and SPEC.local.publish.argv[0] == "evolve-file"


def test_items_maps_the_real_offline_planner_output_one_per_opted_in_repo():
    tmp = Path(tempfile.mkdtemp())
    c = ctx(tmp)
    plan = offline_plan(tmp)
    result = ADAPTER.items(c, plan)
    assert len(result.items) == plan["count"] and result.items, "the registry's auto_evolve repos give a plan"
    for item in result.items:
        assert item.key == item.nwo == item.row["nwo"] and item.row["dedupe"] == "unavailable", "offline: no dedupe"
        assert item.brief == tmp / "plan" / item.row["brief"] and item.brief.is_file()
        assert item.row["marker"] == f'<!-- repo-evolution key="{item.nwo}" -->'
        assert item.row["prompt"] == S.render_prompt(SPEC, S.values_from(SPEC, item.row)), "parity"
        assert f"`.evolution/{item.row['brief']}`" in item.row["prompt"]
    assert result.meta["model"] == "claude-opus-5-5" and result.meta["max_turns"] == 120
    keys = [i.key for i in result.items]
    assert len(set(keys)) == len(keys)
    one = offline_plan(Path(tempfile.mkdtemp()), target=result.items[0].name)
    assert [r["nwo"] for r in one["include"]] == [keys[0]], "--target picks one repository"
    none = L.dash_gen(["targets", "--out-dir", str(tmp / "p2"), "--offline", "--target=no-such-repo"])
    assert none.code == 1 and L.parse_last_json(none.out)["count"] == 0, "an explicit ask that yields nothing"


def test_items_refuses_a_row_missing_its_fields_a_non_bare_brief_or_a_foreign_marker():
    c = ctx(Path(tempfile.mkdtemp()))
    for bad in ({**row(), "nwo": "not a slug"}, {**row(), "brief": "../x.md"},
                {**row(), "marker": '<!-- repo-evolution key="bamr87/other" -->'},
                {**row(), "marker": '<!-- fleet-doctor key="bamr87/alpha" -->'},
                {k: v for k, v in row().items() if k != "branch"}):
        try:
            ADAPTER.items(c, {"include": [bad]})
        except JevError:
            continue
        raise AssertionError(f"accepted {bad}")
    skipped = ADAPTER.items(c, {"include": [], "skipped": [{"name": "beta", "reason": "open PR"}]}).skipped
    assert skipped == [{"name": "beta", "reason": "open PR", "key": "beta"}]


def test_the_reuse_key_ignores_the_prepared_stamp_and_follows_the_head_and_the_brief():
    c = ctx(Path(tempfile.mkdtemp()))
    item = item_for(c)
    k1 = ADAPTER.reuse_key(c, item, "abc")
    item.brief.write_text(item.brief.read_text().replace("2026-11-03 12:00 UTC", "2026-11-10 09:30 UTC"))
    assert ADAPTER.reuse_key(c, item, "abc") == k1, "the stamp is not a change"
    item.brief.write_text(item.brief.read_text() + "\n## Signals\n\n- a new failing workflow\n")
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
# validate: the patch + the agent's report, as CI's publish step would file them
# --------------------------------------------------------------------------- #
def test_a_pass_with_edits_becomes_a_pr_document_marker_first_with_cis_footer_branch_and_remote():
    c = ctx(Path(tempfile.mkdtemp()))
    item = item_for(c)
    v = validate(c, item, session())
    assert v.ok and v.publish_file is not None and not v.problems, v.problems
    doc = json.loads(v.publish_file.read_text())
    assert doc["kind"] == "pr" and doc["repo"] == doc["key"] == NWO and doc["base"] == "main"
    assert doc["remote"] == f"https://github.com/{NWO}", "#220: the remote is derived from the nwo"
    assert re.fullmatch(r"ai-evolution/\d{8}-local-20261103T000000Z-t", doc["branch"]), doc["branch"]
    assert doc["title"].startswith("chore(evolve): AI improvement pass — 20")
    lines = doc["body"].splitlines()
    assert lines[0] == MARKER and lines[1] == "" and "**What changed**" in doc["body"]
    assert "Draft opened by the [bamr87/bamr87 repo-evolution loop]" in doc["body"] and "local run t" in doc["body"]
    assert f"`{item.row['brief']}`" in doc["body"] and doc["flagged"] is False and doc["source"] == "result-text"
    assert doc["patch"] == "evolve.patch" and (v.publish_file.parent / "evolve.patch").read_text() == PATCH
    assert v.flags == [] and v.facts["kind"] == "pr" and v.facts["patch_bytes"] == len(PATCH)


def test_an_empty_pass_is_valid_and_files_nothing():
    c = ctx(Path(tempfile.mkdtemp()))
    v = validate(c, item_for(c), session(result="Nothing to change: the README matches the code."), patch="")
    assert v.ok, v.problems
    doc = json.loads(v.publish_file.read_text())
    assert doc["kind"] == "none" and doc["patch"] is None and doc["branch"] is None
    assert any(EV.NO_CHANGES in f for f in v.flags)
    absent = validate(c, item_for(c), session(), patch=None)
    assert absent.ok and json.loads(absent.publish_file.read_text())["kind"] == "none"


TRACKED_LOCK = ("diff --git a/Gemfile.lock b/Gemfile.lock\nindex 587be6b..d735d34 100644\n--- a/Gemfile.lock\n"
                "+++ b/Gemfile.lock\n@@ -1 +1 @@\n-x\n+x2\n")
SPACE_FILE = ("diff --git a/src/new file.txt b/src/new file.txt\nnew file mode 100644\nindex 0000000..975fbec\n"
              "--- /dev/null\n+++ b/src/new file.txt\t\n@@ -0,0 +1 @@\n+y\n")
QUOTED_FILE = ('diff --git "a/src/\\303\\274n\\303\\257code.txt" "b/src/\\303\\274n\\303\\257code.txt"\n'
               "new file mode 100644\nindex 0000000..b680253\n--- /dev/null\n+++ \"b/src/\\303\\274n\\303\\257code.txt\"\n"
               "@@ -0,0 +1 @@\n+z\n")


def test_only_an_untracked_lockfile_is_dropped_as_cis_publish_step_drops_only_those():
    c = ctx(Path(tempfile.mkdtemp()))
    v = validate(c, item_for(c), session(), patch=PATCH + LOCK)
    assert v.ok, v.problems
    doc = json.loads(v.publish_file.read_text())
    assert doc["dropped_lockfiles"] == ["package-lock.json"] and doc["kind"] == "pr"
    assert (v.publish_file.parent / "evolve.patch").read_text() == PATCH
    assert any("untracked lockfile" in f for f in v.flags)
    only = validate(c, item_for(c), session(), patch=LOCK)
    assert only.ok and json.loads(only.publish_file.read_text())["kind"] == "none", "an untracked lockfile alone is no change"
    # CI commits a TRACKED lockfile the agent modified (`git ls-files --others` lists only new ones): it stays
    kept = validate(c, item_for(c), session(), patch=TRACKED_LOCK + PATCH)
    assert kept.ok, kept.problems
    kdoc = json.loads(kept.publish_file.read_text())
    assert kdoc["dropped_lockfiles"] == [] and kdoc["kind"] == "pr"
    assert (kept.publish_file.parent / "evolve.patch").read_text() == TRACKED_LOCK + PATCH
    alone = validate(c, item_for(c), session(), patch=TRACKED_LOCK)
    assert alone.ok and json.loads(alone.publish_file.read_text())["kind"] == "pr", "a tracked lockfile edit is a change"
    kept_b, dropped = EV.drop_lockfiles(b"no diff header at all\n")
    assert kept_b == b"no diff header at all\n" and dropped == []
    # the policy comes from fleet.yml: a pattern added there reaches the drop
    extra = EV.drop_lockfiles(b"diff --git a/bun.lockb b/bun.lockb\nnew file mode 100644\n--- /dev/null\n+++ b/bun.lockb\n@@\n+x\n",
                              patterns=("bun.lockb",))
    assert extra[1] == ["bun.lockb"] and extra[0] == b""
    assert EV.drop_lockfiles(LOCK.encode(), patterns=("bun.lockb",)) == (LOCK.encode(), [])


def test_a_path_with_a_space_or_in_gits_quoted_form_is_its_own_section_and_never_rides_a_neighbour():
    # the review's case: the lockfile header followed by `src/new file.txt` — the space broke the old regex
    kept, dropped = EV.drop_lockfiles((LOCK + SPACE_FILE).encode())
    assert dropped == ["package-lock.json"] and kept.decode() == SPACE_FILE
    kept, dropped = EV.drop_lockfiles((LOCK + QUOTED_FILE).encode())
    assert dropped == ["package-lock.json"] and kept.decode() == QUOTED_FILE
    assert [p for p, _s, _n in C.diff_sections(SPACE_FILE + QUOTED_FILE)[1]] == ["src/new file.txt", "src/ünïcode.txt"]
    sys.path.insert(0, str(HUB / ".github" / "scripts" / "dash-gen"))
    import fleet_evolve_file as filer
    assert filer.diff_files(LOCK + SPACE_FILE + TRACKED_LOCK) == [("package-lock.json", True), ("src/new file.txt", True),
                                                                   ("Gemfile.lock", False)]
    assert filer.diff_header_path(QUOTED_FILE.splitlines()[0]) == "src/ünïcode.txt"


def test_the_host_name_is_matched_as_a_whole_token_and_paths_as_substrings():
    # the review's case: a Mac called `work`, `main`, `home` or `mini` must not withhold every pass
    for host, innocent in (("work", "the workflow runs"), ("main", "def main(): pass"), ("home", "the homepage"),
                           ("mini", "a minimal fix")):
        c = ctx(Path(tempfile.mkdtemp()))
        c.hostname = host
        assert not C.leaks_private(innocent, c), (host, innocent)
        assert C.leaks_private(f"built on {host} today", c) and C.leaks_private(f"ran on {host}.", c), host
        assert C.leaks_private(f"{host}:/tmp/x", c) and not C.leaks_private(f"{host}-2 is another box", c), host
        assert not C.leaks_private(f"https://github.com/x/y/blob/{host}/docs/E.md", c), "a path component is not a host"
        v = validate(c, item_for(c), session(result=innocent))
        assert v.ok, (host, v.problems)
    c = ctx(Path(tempfile.mkdtemp()))
    assert C.leaks_private("see /Users/someone/.ssh", c) and C.leaks_private("/Users/someone/.cache/jev/work/r", c)
    assert C.private_pattern(SimpleNamespace(home=Path("/"), hostname="", work_root=Path("/x"))) is None


def test_a_publishing_verb_is_seen_wherever_a_command_segment_starts():
    seen = {"cd pkg && git push origin HEAD": ["git push origin HEAD"],
            "git -C . commit -m x": ["git -C . commit -m x"],
            "env GIT_DIR=.git git push": ["git push"],
            "make build | gh pr create --fill": ["gh pr create --fill"],
            "git --git-dir=.git -c user.name=x push": ["git --git-dir=.git -c user.name=x push"],
            "ls; GIT_DIR=.git git tag v1": ["git tag v1"],
            "(cd a && git checkout -b feat)": ["git checkout -b feat"]}
    for command, want in seen.items():
        assert C.publishing_commands(command) == want, (command, C.publishing_commands(command))
    for innocent in ("echo git push", "git status && git diff", "grep 'gh pr create' README.md", "git log --oneline",
                     "python3 -c \"print('git push')\""):
        assert C.publishing_commands(innocent) == [], innocent
    c = ctx(Path(tempfile.mkdtemp()))
    v = validate(c, item_for(c), session([("cd pkg && git push origin HEAD", "denied", True),
                                          ("git status", "clean", False)]))
    assert v.ok and v.facts["publish_attempts"] == 1 and any("git push" in f for f in v.flags), (v.flags, v.facts)


def test_the_apply_steps_name_the_branch_push_and_the_draft_pr_never_an_issue():
    c = ctx(Path(tempfile.mkdtemp()))
    item = item_for(c)
    plan = A.PublishPlan(True, [], [{"title": "t", "kind": "pr", "repo": NWO, "base": "main",
                                     "branch": "ai-evolution/20261103-local-t", "remote": f"https://github.com/{NWO}",
                                     "labels": ["ai-evolution", "automation"]}], None)
    steps = ADAPTER.apply_steps(c, item, plan)
    assert len(steps) == 2 and steps[0].startswith("Push the validated patch") and "ai-evolution/20261103-local-t" in steps[0]
    assert f"https://github.com/{NWO}" in steps[0] and "gh pr create --draft" in steps[1] and "#488" in steps[1]
    assert not any("issue create" in s for s in steps)
    empty = ADAPTER.apply_steps(c, item, A.PublishPlan(False, [], [], None))
    assert len(empty) == 1 and "no branch is pushed" in empty[0]
    assert A.get("repo_scout").apply_steps(c, item, plan) is None, "scout keeps the engine's default wording"


def test_a_budget_hit_is_previewed_flagged_with_cis_partial_warning():
    c = ctx(Path(tempfile.mkdtemp()))
    v = validate(c, item_for(c), session(result="I had started on the README when"), kind="budget_hit")
    assert v.ok, v.problems
    doc = json.loads(v.publish_file.read_text())
    assert doc["flagged"] is True and doc["kind"] == "pr"
    assert doc["body"].splitlines()[0] == MARKER and "stopped MID-TASK" in doc["body"]
    assert doc["body"].index("stopped MID-TASK") < doc["body"].index("I had started"), "the warning comes first"
    assert any("PARTIAL" in f for f in v.flags) and v.facts["flagged"] is True


def test_a_missing_summary_gets_cis_placeholder_and_a_refused_publish_attempt_is_flagged():
    c = ctx(Path(tempfile.mkdtemp()))
    v = validate(c, item_for(c), session([("git push origin HEAD", "Permission to use Bash has been denied", True),
                                          ("git status", "M README.md", False)], result=""))
    assert v.ok, v.problems
    doc = json.loads(v.publish_file.read_text())
    assert EV.NO_SUMMARY in doc["body"]
    assert any("publishing command" in f and "git push" in f for f in v.flags) and v.facts["publish_attempts"] == 1


def test_the_privacy_filter_withholds_and_a_local_denial_is_only_flagged():
    c = ctx(Path(tempfile.mkdtemp()))
    leaky = validate(c, item_for(c), session(result="see /Users/someone/.cache/jev/work/x for the log"))
    assert not leaky.ok and any("local path" in p for p in leaky.problems)
    host = validate(c, item_for(c), session(result="ran on someones-mac"))
    assert not host.ok
    in_patch = validate(c, item_for(c), session(), patch=PATCH.replace("alpha", "/Users/someone/alpha"))
    assert not in_patch.ok
    denial = validate(c, item_for(c), session(result="`npm test` failed: Operation not permitted"))
    assert denial.ok and any("local-runner denial" in f for f in denial.flags)


def test_validate_runs_the_filers_offline_rules_on_the_copy():
    c = ctx(Path(tempfile.mkdtemp()))
    secret = validate(c, item_for(c), session(result="token ghp_" + "A" * 36))
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
    filed = {"apply": False, "filed": [{"title": "t", "kind": "pr", "repo": NWO, "base": "main",
                                         "branch": "ai-evolution/20261103-local-x", "remote": f"https://github.com/{NWO}",
                                         "labels": ["ai-evolution", "automation"], "flagged": False,
                                         "body_file": "b.md", "patch_file": "b.patch", "url": None}],
             "skipped": [], "rejected": []}
    plan = ADAPTER.publish(c, item, v, lambda: _run(0, filed))
    assert plan.publishable and plan.rows[0]["remote"].endswith(NWO) and plan.blockers == [] and plan.failures == []
    nodedupe = ADAPTER.publish(c, item, v, lambda: _run(0, filed, err=EV.NO_DEDUPE))
    assert not nodedupe.publishable and "dedupe_unavailable" in nodedupe.blockers
    open_pass = ADAPTER.publish(c, item, v, lambda: _run(0, {**filed, "filed": [], "skipped": [
        {"title": "t", "reason": "previous evolution PR is still open: https://github.com/bamr87/alpha/pull/9"}]}))
    assert not open_pass.publishable and any("still open" in b for b in open_pass.blockers)
    nothing = ADAPTER.publish(c, item, v, lambda: _run(0, {**filed, "filed": [], "skipped": [
        {"title": "t", "reason": EV.NO_CHANGES + " — nothing to open"}]}))
    assert not nothing.publishable and nothing.blockers == [] and nothing.rows == [], "an empty pass is no blocker"
    refused = ADAPTER.publish(c, item, v, lambda: _run(2, None, err="evolve-file: " + EV.APPLY_REFUSED + " …"),
                              apply=True)
    assert not refused.publishable and any("#488" in b for b in refused.blockers), refused.blockers


def test_the_real_filer_dry_run_writes_the_body_and_the_patch_and_its_apply_is_refused():
    c = ctx(Path(tempfile.mkdtemp()))
    item = item_for(c)
    v = validate(c, item, session())
    assert v.ok, v.problems
    bodies = Path(tempfile.mkdtemp())
    argv = S.render_argv(SPEC.local.publish.argv, L.item_values(c, item, validated=v.publish_file))
    assert argv[-2] == "--bodies-dir", argv
    dry = L.dash_gen([*argv[:-1], str(bodies), "--offline"])
    assert dry.ok, dry.err
    out = L.parse_last_json(dry.out)
    assert out["filed"][0]["kind"] == "pr" and out["filed"][0]["remote"] == f"https://github.com/{NWO}"
    assert out["filed"][0]["labels"] == ["ai-evolution", "automation"] and out["filed"][0]["url"] is None
    assert Path(out["filed"][0]["body_file"]).read_text().splitlines()[0] == MARKER
    assert Path(out["filed"][0]["patch_file"]).read_text() == PATCH
    applied = L.dash_gen([*argv[:-1], str(bodies), "--apply", "--reviewed-bodies", str(bodies)])
    assert applied.code == 2 and "#488" in applied.err and "nothing was filed" in applied.err, applied.err
    empty = validate(c, item, session(result="nothing"), patch="")
    dry2 = L.dash_gen([*S.render_argv(SPEC.local.publish.argv, L.item_values(c, item, validated=empty.publish_file))[:-1],
                       str(bodies), "--offline"])
    out2 = L.parse_last_json(dry2.out)
    assert dry2.ok and out2["filed"] == [] and EV.NO_CHANGES in out2["skipped"][0]["reason"]


def test_the_filer_refuses_a_foreign_remote_a_wrong_branch_and_a_lockfile_patch():
    sys.path.insert(0, str(HUB / ".github" / "scripts" / "dash-gen"))
    import evolution
    import fleet_evolve_file as filer
    cfg = evolution.load_config(None)
    d = Path(tempfile.mkdtemp())
    (d / "evolve.patch").write_text(PATCH, encoding="utf-8")
    good = {"kind": "pr", "repo": NWO, "key": NWO, "name": "alpha", "base": "main", "marker": MARKER,
            "title": "chore(evolve): AI improvement pass — 2026-11-03", "body": MARKER + "\n\nsummary\n",
            "branch": "ai-evolution/20261103-local-t", "remote": f"https://github.com/{NWO}", "patch": "evolve.patch",
            "flagged": False, "source": "result-text"}
    assert filer.problems(good, d, cfg) == []
    assert any("remote" in p for p in filer.problems({**good, "remote": "https://github.com/bamr87/bamr87"}, d, cfg))
    assert any("branch" in p for p in filer.problems({**good, "branch": "fix/x"}, d, cfg))
    assert any("marker" in p for p in filer.problems({**good, "marker": '<!-- repo-evolution key="bamr87/b" -->'}, d, cfg))
    assert any("first line" in p for p in filer.problems({**good, "body": "no marker"}, d, cfg))
    (d / "lock.patch").write_text(LOCK, encoding="utf-8")
    assert any("creates a lockfile" in p for p in filer.problems({**good, "patch": "lock.patch"}, d, cfg))
    (d / "tracked-lock.patch").write_text(TRACKED_LOCK, encoding="utf-8")
    assert filer.problems({**good, "patch": "tracked-lock.patch"}, d, cfg) == [], "a tracked lockfile edit is CI's own"
    assert any("no changes carries no patch" in p for p in filer.problems({**good, "kind": "none"}, d, cfg))
    assert filer.problems({**good, "kind": "none", "patch": None, "branch": None}, d, cfg) == []


def test_context_request_uses_the_focus_and_the_category_and_recheck_reads_the_live_plan():
    c = ctx(Path(tempfile.mkdtemp()))
    item = item_for(c, brief=f"{MARKER}\n# Evolution brief — alpha\n\n## Focus for this run\n\nthe README install "
                            "section\n\n## Goals\n\nx\n")
    req = ADAPTER.context_request(c, item)
    assert req.nwo == NWO and req.name == "alpha"
    assert req.queries[0] == "the README install section" and req.queries[1] == "alpha dev-tools README documentation"
    plain = ADAPTER.context_request(c, item_for(c))
    assert plain.queries == ("alpha dev-tools README documentation",), "no focus: no focus query"
    c.planner = lambda target=None, no_files=False: {"include": [{"nwo": NWO}], "skipped": []}
    assert ADAPTER.recheck(c, item) is None
    c.planner = lambda target=None, no_files=False: {"include": [], "skipped": [{"name": "alpha", "reason": "open"}]}
    assert ADAPTER.recheck(c, item) == "open"


# --------------------------------------------------------------------------- #
# boundaries
# --------------------------------------------------------------------------- #
def test_the_adapter_and_filer_hold_no_route_to_a_merge_or_a_push():
    for f in (HUB / "tools" / "jev" / "adapters" / "repo_evolution_evolve.py",
              HUB / ".github" / "scripts" / "dash-gen" / "fleet_evolve_file.py"):
        src = f.read_text(encoding="utf-8")
        for bad in ("pr merge", "--admin", "git push -", "push --force", "issue close", "issue edit", "dangerously",
                    "bypassPermissions", "import ai_activity", "dash_gen.py", "type: ignore"):
            assert bad not in src, f"{f.name}: {bad}"
        assert not re.search(r"^\s*except[^\n]*:\s*\n\s*pass\b", src, re.M), f"{f.name}: an empty handler"
    assert "sys.path" not in (HUB / "tools" / "jev" / "adapters" / "repo_evolution_evolve.py").read_text()


def test_the_markers_and_messages_agree_with_the_planner_and_the_filer():
    sys.path.insert(0, str(HUB / ".github" / "scripts" / "dash-gen"))
    import evolution
    import fleet_evolve_file as filer
    cfg = evolution.load_config(None)
    assert evolution.marker_line(cfg, NWO) == MARKER and EV.MARKER_RX.fullmatch(MARKER)
    assert EV.NO_DEDUPE == filer.NO_DEDUPE and EV.APPLY_REFUSED in filer.APPLY_REFUSED and EV.NO_CHANGES in filer.NO_CHANGES
    # one policy, read from fleet.yml by both sides (test_evolution.py holds CI's publish step to the same list)
    cfg = evolution.load_config(evolution.FLEET_DEFAULT)
    fleet = S.load_fleet()
    assert tuple(cfg["lockfile_patterns"]) == C.lockfile_patterns(fleet) == tuple(fleet["dependencies"]["lockfile_patterns"])
    assert filer.lockfile_re(cfg).pattern == C.lockfile_regex(C.lockfile_patterns(fleet)).pattern
    assert S.PUBLISH_COMMANDS["evolve-file"] == "--apply" and S.PUBLISH_REVIEWED_FLAGS["evolve-file"] == "--reviewed-bodies"
    assert S.PLANNER_BRIEFS["targets"].fullmatch("evolution-workorder-ragio-ai.md")
    assert "targets" in S.PLANNER_COMMANDS and "fleet-read" in S.GITHUB_CREDENTIALS
    assert S.CREDENTIAL_SITES["fleet-read"] == frozenset({"env GH_TOKEN"})


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
