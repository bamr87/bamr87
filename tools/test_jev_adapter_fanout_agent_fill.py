#!/usr/bin/env python3
"""
Fixture tests for tools/jev/adapters/fanout_agent_fill.py — the fan-out agent
fill's adapter on the loop engine (bamr87/bamr87#488, ADR 0002 P3, step 3).
The adapter maps the planner's JSON (`dash-gen agent-fill --kit <kit>`) and the
filer's dry run (`dash-gen agent-fill-file`), so what is tested is that it maps
the REAL offline planner's output (one item per target, no brief), that tier 0
reuses only an identical attempt, that a target whose kit branch is missing or
already filled is blocked and --apply needs a live dedupe, that validation
holds the engine's patch to the kit's brief (only CLAUDE.md, only SCHEMA.md
files) and withholds what would leak this machine, that the filer's structural
rules run on the copy and its --apply is refused naming #488, and that the
engine's modules hold no route to a merge, a push or dash-gen.

No network, no gh: the planner and the filer run `--offline`.

Run: python3 tools/test_jev_adapter_fanout_agent_fill.py
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
from tools.jev.adapters import fanout_agent_fill as FA  # noqa: E402
from tools.jev.common import JevError, Run  # noqa: E402
from tools.jev.workspace import Harvest  # noqa: E402

SPECS = {kit: S.load_spec("fanout", f"agent-fill-{kit}") for kit in ("standardize", "schema")}
ADAPTER = A.get("fanout_agent_fill")
CLAUDE_PATCH = ("diff --git a/CLAUDE.md b/CLAUDE.md\n--- a/CLAUDE.md\n+++ b/CLAUDE.md\n@@ -1 +1 @@\n"
                "-TODO: describe this project\n+A Jekyll theme for the fleet's sites.\n")
SCHEMA_PATCH = ("diff --git a/SCHEMA.md b/SCHEMA.md\n--- a/SCHEMA.md\n+++ b/SCHEMA.md\n@@ -1 +1 @@\n-> TODO\n+> The theme\n"
                "diff --git a/_posts/SCHEMA.md b/_posts/SCHEMA.md\n--- a/_posts/SCHEMA.md\n+++ b/_posts/SCHEMA.md\n"
                "@@ -1 +1 @@\n-> TODO\n+> Dated posts\n")


def offline_plan(tmp: Path, kit: str = "standardize", target: str = "all") -> dict:
    """The REAL planner, offline, against the registry."""
    res = L.dash_gen(["agent-fill", "--kit", kit, "--plan-dir", str(tmp / "plan"), "--offline", f"--target={target}"])
    assert res.code in (0, 1), res.err
    return L.parse_last_json(res.out)


def ctx(tmp: Path, kit: str = "standardize", work_root: str = "/Users/someone/.cache/jev/work", **opts) -> SimpleNamespace:
    o = L.Options(**opts)

    def item_dir(item):
        d = tmp / "items" / re.sub(r"[^A-Za-z0-9._-]+", "_", item.key)
        d.mkdir(parents=True, exist_ok=True)
        return d
    return SimpleNamespace(spec=SPECS[kit], opts=o, plan_dir=tmp / "plan", history=L.History(tmp / "runs"),
                           home=Path("/Users/someone"), hostname="someones-mac", work_root=Path(work_root),
                           item_dir=item_dir,
                           bodies_dir=lambda item, apply: item_dir(item) / ("filed" if apply else "bodies"),
                           dash_gen=L.dash_gen, planner=None, run_ref=lambda: "local run t (tools/jev loop)")


def row(kit: str = "standardize", nwo: str = "bamr87/alpha", **extra) -> dict:
    k = FA.KITS[kit]
    return {"key": nwo, "name": nwo.split("/", 1)[1], "nwo": nwo, "branch": k["branch"], "kit": kit,
            "commit_subject": k["subject"], "branch_status": "present", "dedupe": "clear", **extra}


def item_for(c, r: dict | None = None) -> A.Item:
    r = r or row()
    c.plan_dir.mkdir(parents=True, exist_ok=True)
    return ADAPTER.items(c, {"include": [r]}).items[0]


def validate(c, item: A.Item, patch: str | None) -> A.Verdict:
    d = c.item_dir(item)
    if patch is None:
        h = Harvest(FA.PATCH, None, None, 0, "absent")
    else:
        dest = d / "outputs" / "changes.patch"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(patch, encoding="utf-8")
        h = Harvest(FA.PATCH, dest, "x", len(patch), "ok")
    return ADAPTER.validate(c, item, {FA.PATCH: h}, {"kind": "ok"})


def test_the_adapter_is_registered_and_both_specs_name_it():
    assert A.REGISTRY["fanout_agent_fill"] == "tools.jev.adapters.fanout_agent_fill"
    assert isinstance(ADAPTER, A.Adapter) and ADAPTER.name == "fanout_agent_fill"
    for kit, spec in SPECS.items():
        assert spec.local.adapter == "fanout_agent_fill" and spec.local.harvest == "patch"
        assert spec.workspace.cwd == "target" and spec.workspace.no_brief and spec.workspace.brief_file is None
        assert spec.workspace.github_credential == "none" and spec.workspace.outputs == ()
        assert set(spec.workspace.exceptions) == {"app-token", "setting-sources"}
        assert spec.local.switch is None and spec.local.context.mode == "off"
        assert spec.local.planner.argv[:3] == ("agent-fill", "--kit", kit) and spec.local.publish.argv[0] == "agent-fill-file"
        assert spec.call_site == "fanout.yml:agent-fill" and spec.step_id == f"fill-{kit}"


def test_items_maps_the_real_offline_planner_output_one_per_target_with_no_brief():
    tmp = Path(tempfile.mkdtemp())
    c = ctx(tmp)
    plan = offline_plan(tmp)
    result = ADAPTER.items(c, plan)
    assert len(result.items) == plan["count"] and result.items, "the registry gives targets"
    for item in result.items:
        assert item.key == item.nwo == item.row["key"] and item.nwo.startswith("bamr87/") and item.brief is None
        assert item.branch == "chore/standardize-baseline" and item.row["branch_status"] == "unknown"
        assert item.row["dedupe"] == "offline"
        assert item.row["prompt"] == S.render_prompt(SPECS["standardize"], S.values_from(SPECS["standardize"], item.row)) \
            == SPECS["standardize"].template, "parity"
    assert all(d.get("reason") for d in result.dropped) and result.meta["kit"] == "standardize"
    keys = [i.key for i in result.items]
    assert len(set(keys)) == len(keys)
    one = offline_plan(Path(tempfile.mkdtemp()), target="SCHEMA")
    assert [r["nwo"] for r in one["include"]] == ["bamr87/SCHEMA"], "--target picks one by registry name"
    schema = offline_plan(Path(tempfile.mkdtemp()), kit="schema", target="bamr87/SCHEMA")
    assert schema["include"][0]["branch"] == "chore/schema-adoption" and schema["branch"] == "chore/schema-adoption"


def test_items_refuses_a_row_of_another_kit_with_a_brief_or_the_wrong_branch():
    c = ctx(Path(tempfile.mkdtemp()))
    for bad in (row(kit="schema"), {**row(), "brief": "x.md"}, {**row(), "branch": "main"},
                {**row(), "commit_subject": "chore: x"}, {**row(), "key": "alpha"}, {**row(), "dedupe": "maybe"},
                {k: v for k, v in row().items() if k != "branch_status"}):
        try:
            ADAPTER.items(c, {"include": [bad]})
        except JevError:
            continue
        raise AssertionError(f"accepted {bad}")
    schema = ctx(Path(tempfile.mkdtemp()), kit="schema")
    assert ADAPTER.items(schema, {"include": [row(kit="schema")]}).items[0].branch == "chore/schema-adoption"


def test_the_reuse_key_is_the_head_and_the_kit_and_an_empty_repo_is_skipped():
    c = ctx(Path(tempfile.mkdtemp()))
    item = item_for(c)
    k1 = ADAPTER.reuse_key(c, item, "abc")
    assert k1 == ADAPTER.reuse_key(c, item, "abc") and ADAPTER.reuse_key(c, item, "def") != k1
    assert ADAPTER.reuse_key(c, item, None) is None and ADAPTER.tier0(c, item, "").action == "skip"
    other = ctx(Path(tempfile.mkdtemp()), kit="schema")
    assert ADAPTER.reuse_key(other, item_for(other, row(kit="schema")), "abc") != k1, "the kit is in the key"


def test_classify_blocks_a_missing_or_filled_branch_and_apply_without_a_live_dedupe():
    tmp = Path(tempfile.mkdtemp())
    missing = ADAPTER.classify(ctx(tmp), item_for(ctx(tmp), row(branch_status="missing")))
    assert missing.blocked and "fan-out has not pushed" in missing.reason, missing
    filled = ADAPTER.classify(ctx(tmp), item_for(ctx(tmp), row(dedupe="filled")))
    assert filled.blocked and FA.AGENT_PASS_MARK in filled.reason
    offline = item_for(ctx(tmp), row(branch_status="unknown", dedupe="offline"))
    assert not ADAPTER.classify(ctx(tmp), offline).blocked, "a dry run may go on without a live dedupe"
    assert ADAPTER.classify(ctx(tmp, apply=True), offline).blocked
    assert not ADAPTER.classify(ctx(tmp, apply=True), item_for(ctx(tmp))).blocked


# --------------------------------------------------------------------------- #
# validate: the patch, held to the kit's brief
# --------------------------------------------------------------------------- #
def test_a_claude_md_patch_becomes_the_validated_document_the_filer_accepts():
    c = ctx(Path(tempfile.mkdtemp()))
    v = validate(c, item_for(c), CLAUDE_PATCH)
    assert v.ok and v.publish_file is not None and not v.problems, v.problems
    doc = json.loads(v.publish_file.read_text())
    assert doc == {"kit": "standardize", "repo": "bamr87/alpha", "key": "bamr87/alpha",
                   "branch": "chore/standardize-baseline", "commit_subject": FA.KITS["standardize"]["subject"],
                   "patch": "agent-fill.patch", "files": ["CLAUDE.md"]}
    assert (v.publish_file.parent / "agent-fill.patch").read_text() == CLAUDE_PATCH
    assert v.facts["files"] == ["CLAUDE.md"] and v.facts["patch_bytes"] == len(CLAUDE_PATCH) and v.flags == []


def test_the_schema_kit_allows_schema_md_files_anywhere_and_nothing_else():
    c = ctx(Path(tempfile.mkdtemp()), kit="schema")
    v = validate(c, item_for(c, row(kit="schema")), SCHEMA_PATCH)
    assert v.ok, v.problems
    assert json.loads(v.publish_file.read_text())["files"] == ["SCHEMA.md", "_posts/SCHEMA.md"]
    deleted = ("diff --git a/_site/SCHEMA.md b/_site/SCHEMA.md\ndeleted file mode 100644\n--- a/_site/SCHEMA.md\n"
               "+++ /dev/null\n@@ -1 +0,0 @@\n-> TODO\n")
    assert validate(c, item_for(c, row(kit="schema")), deleted).ok, "a scaffolded SCHEMA.md inside a build dir may go"
    readme = validate(c, item_for(c, row(kit="schema")), SCHEMA_PATCH + CLAUDE_PATCH)
    assert not readme.ok and any("allows no edit to CLAUDE.md" in p for p in readme.problems), readme.problems
    std = ctx(Path(tempfile.mkdtemp()))
    other = validate(std, item_for(std), CLAUDE_PATCH + "diff --git a/README.md b/README.md\n--- a/README.md\n"
                                                       "+++ b/README.md\n@@ -1 +1 @@\n-a\n+b\n")
    assert not other.ok and any("README.md" in p and "withheld" in p for p in other.problems), other.problems
    assert FA.patch_files(SCHEMA_PATCH + CLAUDE_PATCH) == ["SCHEMA.md", "_posts/SCHEMA.md", "CLAUDE.md"]
    assert not FA.allowed_file("schema", "../SCHEMA.md") and not FA.allowed_file("docker", "CLAUDE.md")


def test_nothing_changed_no_header_and_the_privacy_filter_reject():
    c = ctx(Path(tempfile.mkdtemp()))
    empty = validate(c, item_for(c), "")
    assert not empty.ok and any("changed nothing" in p for p in empty.problems)
    absent = validate(c, item_for(c), None)
    assert not absent.ok
    headerless = validate(c, item_for(c), "+just a line\n")
    assert not headerless.ok and any("diff --git" in p for p in headerless.problems)
    leaky = validate(c, item_for(c), CLAUDE_PATCH.replace("the fleet's sites", "/Users/someone/.cache/jev/work/x"))
    assert not leaky.ok and any("local path" in p for p in leaky.problems)
    host = validate(c, item_for(c), CLAUDE_PATCH.replace("the fleet's sites", "someones-mac"))
    assert not host.ok


def test_validate_runs_the_filers_offline_rules_on_the_copy():
    c = ctx(Path(tempfile.mkdtemp()))
    secret = validate(c, item_for(c), CLAUDE_PATCH.replace("the fleet's sites", "ghp_" + "A" * 36))
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
    filed = {"apply": False, "filed": [{"title": FA.KITS["standardize"]["subject"], "kind": "push", "repo": "bamr87/alpha",
                                         "branch": "chore/standardize-baseline", "files": ["CLAUDE.md"],
                                         "body_file": "b.md", "patch_file": "b.patch", "url": None}],
             "skipped": [], "rejected": []}
    plan = ADAPTER.publish(c, item, v, lambda: _run(0, filed))
    assert plan.publishable and plan.rows[0]["kind"] == "push" and plan.blockers == [] and plan.failures == []
    nodedupe = ADAPTER.publish(c, item, v, lambda: _run(0, filed, err=FA.NO_DEDUPE))
    assert not nodedupe.publishable and "dedupe_unavailable" in nodedupe.blockers
    refused = ADAPTER.publish(c, item, v, lambda: _run(2, None, err="agent-fill-file: " + FA.APPLY_REFUSED + " …"),
                              apply=True)
    assert not refused.publishable and any("#488" in b for b in refused.blockers), refused.blockers


def test_the_real_filer_dry_run_writes_the_patch_and_message_and_its_apply_is_refused():
    c = ctx(Path(tempfile.mkdtemp()))
    item = item_for(c)
    v = validate(c, item, CLAUDE_PATCH)
    assert v.ok, v.problems
    bodies = Path(tempfile.mkdtemp())
    argv = S.render_argv(SPECS["standardize"].local.publish.argv, L.item_values(c, item, validated=v.publish_file))
    assert argv[-2] == "--bodies-dir"
    dry = L.dash_gen([*argv[:-1], str(bodies), "--offline"])
    assert dry.ok, (argv, dry.err)
    out = L.parse_last_json(dry.out)
    filed = out["filed"][0]
    assert filed["kind"] == "push" and filed["branch"] == "chore/standardize-baseline" and filed["files"] == ["CLAUDE.md"]
    assert Path(filed["patch_file"]).read_text() == CLAUDE_PATCH
    assert Path(filed["body_file"]).read_text().splitlines()[0] == FA.KITS["standardize"]["subject"]
    applied = L.dash_gen([*argv[:-1], str(bodies), "--apply", "--reviewed-bodies", str(bodies)])
    assert applied.code == 2 and "#488" in applied.err and "nothing was pushed" in applied.err, applied.err
    assert len(list(bodies.glob("*.patch"))) == 1, "the apply wrote nothing new"


def test_context_request_names_the_target_and_the_kits_queries():
    c = ctx(Path(tempfile.mkdtemp()))
    req = ADAPTER.context_request(c, item_for(c))
    assert req.nwo == "bamr87/alpha" and req.name == "alpha" and "CLAUDE.md" in req.queries[0]


def test_recheck_reads_the_live_plan_for_the_one_target():
    c = ctx(Path(tempfile.mkdtemp()))
    item = item_for(c)
    c.planner = lambda target=None, no_files=False: {"include": [{"key": target, "branch_status": "present",
                                                                  "dedupe": "clear"}], "skipped": []}
    assert ADAPTER.recheck(c, item) is None
    c.planner = lambda target=None, no_files=False: {"include": [], "skipped": [{"key": target, "reason": "filled"}]}
    assert ADAPTER.recheck(c, item) == "filled"
    c.planner = lambda target=None, no_files=False: {"include": [{"key": target, "branch_status": "present",
                                                                  "dedupe": "unavailable"}], "skipped": []}
    assert "unavailable" in ADAPTER.recheck(c, item)


# --------------------------------------------------------------------------- #
# boundaries
# --------------------------------------------------------------------------- #
def test_the_adapter_planner_and_filer_hold_no_route_to_a_merge_or_a_push():
    for f in (HUB / "tools" / "jev" / "adapters" / "fanout_agent_fill.py",
              HUB / ".github" / "scripts" / "dash-gen" / "agent_fill.py",
              HUB / ".github" / "scripts" / "dash-gen" / "agent_fill_file.py"):
        src = f.read_text(encoding="utf-8")
        for bad in ("pr merge", "--admin", "git push", "push --force", "issue close", "issue edit", "dangerously",
                    "bypassPermissions", "import ai_activity", "dash_gen.py", "type: ignore", "pr create"):
            assert bad not in src, f"{f.name}: {bad}"
        assert not re.search(r"^\s*except[^\n]*:\s*\n\s*pass\b", src, re.M), f"{f.name}: an empty handler"
    assert "sys.path" not in (HUB / "tools" / "jev" / "adapters" / "fanout_agent_fill.py").read_text()


def test_the_kits_and_messages_agree_with_the_planner_the_filer_and_the_workflow():
    sys.path.insert(0, str(HUB / ".github" / "scripts" / "dash-gen"))
    import agent_fill as planner
    import agent_fill_file as filer
    assert planner.KITS == FA.KITS and planner.AGENT_PASS_MARK == FA.AGENT_PASS_MARK
    assert FA.NO_DEDUPE == filer.NO_DEDUPE and FA.APPLY_REFUSED in filer.APPLY_REFUSED
    assert filer.patch_files(SCHEMA_PATCH) == FA.patch_files(SCHEMA_PATCH)
    for kit in FA.KITS:
        for path in ("CLAUDE.md", "SCHEMA.md", "a/SCHEMA.md", "README.md", "../SCHEMA.md"):
            assert filer.allowed_file(kit, path) == FA.allowed_file(kit, path), (kit, path)
    assert S.PUBLISH_COMMANDS["agent-fill-file"] == "--apply" and S.PUBLISH_REVIEWED_FLAGS["agent-fill-file"] == "--reviewed-bodies"
    assert "agent-fill" in S.PLANNER_COMMANDS and S.PLANNER_BRIEFS["agent-fill"].fullmatch("agent-fill-workorder-x.md")
    # the workflow's push step commits exactly the subjects the planner and the filer dedupe on, per kit
    wf = (HUB / ".github" / "workflows" / "fanout.yml").read_text(encoding="utf-8")
    for kit, k in FA.KITS.items():
        assert k["subject"] in wf and k["branch"] in wf, kit


def main() -> int:
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except Exception as exc:  # noqa: BLE001 - a test runner reports every failure
                failed += 1
                print(f"FAIL {name}: {exc}")
    total = sum(1 for n, f in globals().items() if n.startswith("test_") and callable(f))
    print(f"{total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
