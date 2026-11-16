#!/usr/bin/env python3
"""
Fixture tests for hub_refs.py — do the fleet's pins of the hub's reusable
workflows and actions resolve (FF-0037, bamr87/bamr87#610)?

Guards what makes the answer trustworthy:

  * extraction reads job- and step-level `uses:`, quoted refs and trailing
    comments, and ignores `./` refs, other owners, comment lines and the body
    of a block scalar (`run: |`);
  * each distinct target@ref costs ONE lookup per run, however many callers
    pin it;
  * the four states are told apart: ok, ref-missing, file-missing-at-ref, and
    unverified for anything that is not an authoritative answer — a 401, a
    5xx, no network, or a tag the local clone does not hold (CI checks out
    without tags, so a missing tag must never read as ref-missing);
  * the law-ai failure of 2026-10-30 (ci.yml:83 → spec-gate.yml@v2 while v2
    predated the file, which main listed under [Unreleased]) yields exactly
    one hub-ref-broken finding whose first fix is "cut v2.1.0 and move v2";
  * the offline check of a fixture hub with the old pin names
    templates/spec-driven/workflows/spec-gate.yml:29 without any API call.

No network, no gh, no pytest. The law-ai attention half needs PyYAML (it goes
through harness_registry):

    python3 .github/scripts/dash-gen/test_hub_refs.py
"""
from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
HUB_ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))

import hub_refs  # noqa: E402

SPEC_GATE_TEMPLATE = HUB_ROOT / "templates" / "spec-driven" / "workflows" / "spec-gate.yml"

CALLER = """\
name: CI
on: [push]
jobs:
  gate:
    uses: bamr87/bamr87/.github/workflows/spec-gate.yml@v2
  quoted:
    uses: "bamr87/bamr87/.github/workflows/standard-ci.yml@v2"   # the kit's caller
  single:
    uses: 'bamr87/bamr87/.github/workflows/standard-ci.yml@v2'
  local:
    uses: ./.github/workflows/standard-ci.yml
  other-owner:
    uses: bamr87/.github/.github/workflows/release.yml@v1
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - name: auth
        uses: bamr87/bamr87/.github/actions/claude-auth@v2 # step level, trailing comment
      - uses: BAMR87/bamr87/.github/actions/utilities/publish-data@main
      # - uses: bamr87/bamr87/.github/actions/claude-run@v9
      - uses: ./.github/actions/claude-run
      - run: |
          cat > caller.yml <<'EOF'
          uses: bamr87/bamr87/.github/workflows/never-read.yml@v9
          EOF
      - uses: docker://alpine:3
"""


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
def git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@example.com",
                        "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", *args],
                       capture_output=True, text=True, check=True)
    return r.stdout.strip()


def write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def old_hub(tmp: Path, *, tag_v2: bool = True) -> Path:
    """The hub as law-ai met it on 2026-10-30: v2.0.0/v2 cut before
    spec-gate.yml existed; main carries it, listed under [Unreleased], and the
    spec-driven kit's caller already pins it @v2 (the real template, so its
    `uses:` is on line 29)."""
    root = tmp / "hub"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    write(root, ".github/workflows/standard-ci.yml", "on: workflow_call\n")
    write(root, ".github/actions/claude-auth/action.yml", "name: auth\nruns: {using: composite, steps: []}\n")
    write(root, "CHANGELOG.md", "# Changelog\n\n## [Unreleased]\n\n## [2.0.0] - 2026-10-14\n\n- standard-ci\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "v2.0.0")
    if tag_v2:
        git(root, "tag", "v1.0.0")
        git(root, "tag", "v1")
        git(root, "tag", "-a", "v2.0.0", "-m", "v2.0.0")
        git(root, "tag", "-a", "v2", "-m", "v2 -> v2.0.0")
    write(root, ".github/workflows/spec-gate.yml", "on: workflow_call\n")
    write(root, "CHANGELOG.md", "# Changelog\n\n## [Unreleased]\n\n### Added\n\n"
                                "- `spec-gate.yml`: a reusable spec gate.\n\n"
                                "## [2.0.0] - 2026-10-14\n\n- standard-ci\n")
    write(root, "templates/spec-driven/workflows/spec-gate.yml", SPEC_GATE_TEMPLATE.read_text(encoding="utf-8"))
    write(root, "templates/spec-driven/archive/spec-gate-0.1.0.yml",
          "jobs:\n  g:\n    uses: bamr87/bamr87/.github/workflows/spec-gate.yml@v7\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "spec-gate.yml on main")
    return root


class FakeApi:
    """GitHub as a dict: `refs` maps a ref to the set of paths it carries
    (a directory listing is derived for actions); `codes` forces an answer."""

    def __init__(self, refs: dict[str, set[str]], codes: dict[str, int | None] | None = None,
                 tags: list[str] | None = None):
        self.refs, self.codes, self.tag_list = refs, codes or {}, tags
        self.calls: list[str] = []

    def __call__(self, path: str, accept: str | None = None):
        self.calls.append(path)
        for prefix, code in self.codes.items():
            if path.startswith(prefix):
                return code, None
        if "/git/matching-refs/tags/" in path:
            if self.tag_list is None:
                return 403, None
            return 200, [{"ref": f"refs/tags/{t}"} for t in self.tag_list]
        if "/commits/" in path:
            ref = path.rsplit("/commits/", 1)[1]
            return (200, "0" * 40) if ref in self.refs else (422, None)
        if "/contents/" in path:
            target, ref = path.split("/contents/", 1)[1].split("?ref=")
            have = self.refs.get(ref, set())
            if target in have:
                return 200, {"name": target.rsplit("/", 1)[-1]}
            listing = [{"name": p[len(target) + 1:]} for p in have if p.startswith(target + "/")]
            return (200, listing) if listing else (404, None)
        return 404, None


def run_cli(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = hub_refs.main(argv)
    return rc, buf.getvalue()


# --------------------------------------------------------------------------- #
# extract
# --------------------------------------------------------------------------- #
def test_extract_reads_job_and_step_pins_and_ignores_the_rest():
    refs = hub_refs.extract(CALLER, ".github/workflows/ci.yml")
    got = [(r["line"], r["kind"], r["target"], r["ref"]) for r in refs]
    assert got == [
        (5, "workflow", ".github/workflows/spec-gate.yml", "v2"),       # job level
        (7, "workflow", ".github/workflows/standard-ci.yml", "v2"),     # double quotes + comment
        (9, "workflow", ".github/workflows/standard-ci.yml", "v2"),     # single quotes
        (19, "action", ".github/actions/claude-auth", "v2"),            # step level + comment
        (20, "action", ".github/actions/utilities/publish-data", "main"),  # nested, owner case
    ], got
    assert all(r["path"] == ".github/workflows/ci.yml" for r in refs)
    # ./ refs, another owner's repo, actions/checkout, a commented-out pin, a
    # `uses:` inside a run block and a docker ref are not hub pins
    assert not any(r["ref"] in ("v1", "v7", "v9") for r in refs)


def test_mismatched_quotes_and_expressions_are_not_pins():
    text = ("jobs:\n  a:\n    uses: \"bamr87/bamr87/.github/workflows/x.yml@v2'\n"
            "  b:\n    uses: bamr87/bamr87/.github/workflows/${{ inputs.w }}@v2\n")
    assert hub_refs.extract(text, "w.yml") == []


def test_a_block_scalar_ends_at_its_parent_indentation():
    text = ("steps:\n  - run: >-\n      uses: bamr87/bamr87/.github/workflows/a.yml@v1\n\n"
            "  - uses: bamr87/bamr87/.github/workflows/b.yml@v2\n")
    refs = hub_refs.extract(text, "w.yml")
    assert [(r["line"], r["target"]) for r in refs] == [(5, ".github/workflows/b.yml")], refs


# --------------------------------------------------------------------------- #
# resolve: one lookup per distinct target@ref, four states
# --------------------------------------------------------------------------- #
def test_each_distinct_target_and_ref_costs_one_lookup():
    api = FakeApi({"v2": {".github/workflows/spec-gate.yml", ".github/workflows/standard-ci.yml",
                          ".github/actions/claude-auth/action.yml"},
                   "main": {".github/actions/utilities/publish-data/action.yml"}})
    resolver = hub_refs.Resolver(hub_refs.ApiBackend(api))
    refs = hub_refs.extract(CALLER, "ci.yml") + hub_refs.extract(CALLER, "ci-copy.yml")
    hub_refs.annotate(refs, resolver, None)
    assert len(refs) == 10 and all(r["status"] == "ok" for r in refs), refs
    assert resolver.lookups == 4  # spec-gate@v2, standard-ci@v2, claude-auth@v2, publish-data@main
    assert len(api.calls) == 8    # two requests (commit, contents) per lookup, never per caller


def test_the_api_backend_tells_the_four_states_apart():
    api = FakeApi({"v2": {".github/workflows/standard-ci.yml", ".github/actions/claude-auth/action.yml",
                          ".github/actions/empty/README.md"}},
                  codes={"repos/bamr87/bamr87/commits/v5": 403,
                         "repos/bamr87/bamr87/contents/.github/workflows/flaky.yml": 502,
                         "repos/bamr87/bamr87/commits/v6": None})
    b = hub_refs.ApiBackend(api)
    st = lambda kind, target, ref: b.resolve(kind, target, ref)["status"]  # noqa: E731
    assert st("workflow", ".github/workflows/standard-ci.yml", "v2") == "ok"
    assert st("action", ".github/actions/claude-auth", "v2") == "ok"
    assert st("workflow", ".github/workflows/standard-ci.yml", "v9") == "ref-missing"    # 422
    assert st("workflow", ".github/workflows/spec-gate.yml", "v2") == "file-missing-at-ref"
    assert st("action", ".github/actions/empty", "v2") == "file-missing-at-ref"          # no action.yml
    assert st("workflow", ".github/workflows/standard-ci.yml", "v5") == "unverified"     # 403
    assert st("workflow", ".github/workflows/flaky.yml", "v2") == "unverified"           # 5xx
    assert st("workflow", ".github/workflows/standard-ci.yml", "v6") == "unverified"     # no network
    api404 = FakeApi({}, codes={"repos/bamr87/bamr87/commits/": 404})
    assert hub_refs.ApiBackend(api404).resolve("workflow", ".github/workflows/x.yml", "v3")["status"] == "ref-missing"


def test_the_git_backend_reads_local_tags_and_never_calls_a_missing_tag_missing():
    with tempfile.TemporaryDirectory() as d:
        root = old_hub(Path(d))
        b = hub_refs.GitBackend(root)
        sha = git(root, "rev-parse", "HEAD")
        assert b.resolve("workflow", ".github/workflows/standard-ci.yml", "v2")["status"] == "ok"
        assert b.resolve("action", ".github/actions/claude-auth", "v2")["status"] == "ok"
        assert b.resolve("workflow", ".github/workflows/spec-gate.yml", "v2")["status"] == "file-missing-at-ref"
        assert b.resolve("workflow", ".github/workflows/spec-gate.yml", sha)["status"] == "ok"
        assert b.resolve("workflow", ".github/workflows/spec-gate.yml", "main")["status"] == "ok"  # the tree
        assert b.resolve("workflow", ".github/workflows/gone.yml", "main")["status"] == "file-missing-at-ref"
        missing = b.resolve("workflow", ".github/workflows/spec-gate.yml", "v3")
        assert missing["status"] == "unverified" and "git fetch" in missing["detail"], missing
        assert b.resolve("workflow", ".github/workflows/x.yml", "f" * 40)["status"] == "unverified"
        assert sorted(b.tags()) == ["v1", "v1.0.0", "v2", "v2.0.0"]
        # not a git repository at all: every tag reads unverified
        assert hub_refs.GitBackend(Path(d) / "nowhere").resolve(
            "workflow", ".github/workflows/x.yml", "v2")["status"] == "unverified"


def test_an_unverified_answer_falls_through_to_the_next_backend_once():
    with tempfile.TemporaryDirectory() as d:
        root = old_hub(Path(d))
        api = FakeApi({}, codes={"repos/": None})  # no network
        resolver = hub_refs.Resolver(hub_refs.ApiBackend(api), hub_refs.GitBackend(root))
        res = resolver.resolve("workflow", ".github/workflows/spec-gate.yml", "v2")
        assert res["status"] == "file-missing-at-ref" and res["via"] == "git"
        resolver.resolve("workflow", ".github/workflows/spec-gate.yml", "v2")
        assert resolver.lookups == 1 and len(api.calls) == 1


# --------------------------------------------------------------------------- #
# the computed fix
# --------------------------------------------------------------------------- #
def test_the_fix_follows_the_hubs_own_state():
    with tempfile.TemporaryDirectory() as d:
        root = old_hub(Path(d))
        facts = hub_refs.TreeFacts(root, tags=["v1", "v1.0.0", "v2", "v2.0.0"])
        fix = hub_refs.compute_fix("workflow", ".github/workflows/spec-gate.yml", "v2",
                                   "file-missing-at-ref", facts)
        assert fix[0] == "cut v2.1.0 and move v2" and "[Unreleased]" in fix[1], fix
        # on main but not in the changelog: same release, and say what it lacks
        fix = hub_refs.compute_fix("workflow", ".github/workflows/standard-ci.yml", "v2",
                                   "file-missing-at-ref", facts)
        assert fix[0] == "cut v2.1.0 and move v2" and "changelog.d" in fix[1], fix
        # a changelog.d fragment waiting to be compiled counts as [Unreleased]
        write(root, "changelog.d/new-gate.md", "- `new-gate.yml`: added\n")
        write(root, ".github/workflows/new-gate.yml", "on: workflow_call\n")
        facts2 = hub_refs.TreeFacts(root, tags=facts.tags)
        assert "[Unreleased]" in hub_refs.compute_fix("workflow", ".github/workflows/new-gate.yml", "v2",
                                                      "file-missing-at-ref", facts2)[1]
        # never cut: a new major
        assert hub_refs.compute_fix("workflow", ".github/workflows/spec-gate.yml", "v3", "ref-missing",
                                    facts)[0].startswith("cut v3.0.0 and create v3")
        # an immutable release never gains the file
        fix = hub_refs.compute_fix("workflow", ".github/workflows/spec-gate.yml", "v2.0.0",
                                   "file-missing-at-ref", facts)
        assert fix[0].startswith("repin to v2 once v2.1.0 carries spec-gate.yml"), fix
        # gone from main too: repin to its replacement
        assert hub_refs.compute_fix("workflow", ".github/workflows/retired.yml", "v2",
                                    "file-missing-at-ref", facts)[0].startswith("repin to the replacement")
        # unknown tags: the version is described, not invented
        assert hub_refs.compute_fix("workflow", ".github/workflows/spec-gate.yml", "v2", "file-missing-at-ref",
                                    hub_refs.TreeFacts(root))[0] == "cut the next v2.Y.0 and move v2"
        assert hub_refs.compute_fix("workflow", ".github/workflows/spec-gate.yml", "v2", "ok", facts) == []
        assert hub_refs.compute_fix("workflow", ".github/workflows/spec-gate.yml", "v2", "unverified", facts) == []


def test_law_ai_2026_10_30_is_one_finding_whose_first_fix_is_the_release():
    """law-ai's ci.yml:83 called spec-gate.yml@v2; v2 (v2.0.0, 2fc1099)
    predated the file; main had it under [Unreleased]."""
    ci = "\n".join(["# law-ai ci.yml"] + [f"# line {n}" for n in range(2, 80)] +
                   ["jobs:", "  spec-gate:", "    name: Spec Drift Gate",
                    "    uses: bamr87/bamr87/.github/workflows/spec-gate.yml@v2",
                    "    with:", "      strict: true"]) + "\n"
    pins = hub_refs.extract(ci, ".github/workflows/ci.yml")
    assert [(p["line"], p["ref"]) for p in pins] == [(83, "v2")], pins
    api = FakeApi({"v2": {".github/workflows/standard-ci.yml"}, "main": {".github/workflows/spec-gate.yml"}},
                  tags=["v1", "v1.0.0", "v2", "v2.0.0"])
    with tempfile.TemporaryDirectory() as d:
        root = old_hub(Path(d))
        resolver = hub_refs.Resolver(hub_refs.ApiBackend(api))
        facts = hub_refs.TreeFacts(root, tags=resolver.tags())
        hub_refs.annotate(pins, resolver, facts)
    broken = [p for p in pins if p["status"] in hub_refs.BROKEN]
    assert len(broken) == 1 and broken[0]["status"] == "file-missing-at-ref", pins
    assert broken[0]["fix"][0] == "cut v2.1.0 and move v2", broken[0]

    # …and through the daily scan's attention queue: exactly one item, ranked
    # above a failing harness, carrying the same fix.
    try:
        import harness_registry as hr
    except SystemExit:  # PyYAML missing: harness_registry exits at import
        print("    (skipped the attention half: PyYAML unavailable)")
        return
    cfg = hr.load_config(Path("/nonexistent/fleet.yml"))
    row = {"repo": "law-ai", "nwo": "bamr87/law-ai", "status": "active", "external": False,
           "archived": False, "scanned": True, "harnesses": [], "scheduled": [],
           "hub_refs": pins, "hub_refs_unread_files": 0}
    import datetime as dt
    out = hr.finalize([row], cfg, "0.6.0", {}, {}, "live", "now",
                      dt.datetime(2026, 10, 30, tzinfo=dt.timezone.utc))
    items = [i for i in out["attention"] if i["kind"] == "hub-ref-broken"]
    assert len(items) == 1, out["attention"]
    assert items[0]["repo"] == "law-ai" and items[0]["severity"] >= 85
    assert items[0]["action"].startswith("cut v2.1.0 and move v2"), items[0]
    assert ".github/workflows/ci.yml:83" in items[0]["summary"]
    assert out["schema"] == "harness-registry/v1"
    assert out["totals"]["hub_refs"] == 1 and out["totals"]["hub_refs_broken"] == 1


# --------------------------------------------------------------------------- #
# the CLI: drift check (q)'s offline half and its fleet listing
# --------------------------------------------------------------------------- #
def test_check_names_the_old_kit_pin_offline_with_no_api_call():
    def no_network(*_a, **_k):
        raise AssertionError("check without --online must not reach GitHub")
    saved = hub_refs.default_getter
    hub_refs.default_getter = no_network
    try:
        with tempfile.TemporaryDirectory() as d:
            root = old_hub(Path(d))
            rc, out = run_cli(["check", "--root", str(root), "templates"])
            assert rc == 1, out
            assert "templates/spec-driven/workflows/spec-gate.yml:29" in out, out
            assert "file-missing-at-ref" in out and "fix: cut v2.1.0 and move v2" in out, out
            assert "@v7" not in out  # archive/ shapes are history, not pins
            # a clone without the tags: unverified (rc 3), never ref-missing
            for t in ("v1", "v1.0.0", "v2", "v2.0.0"):
                git(root, "tag", "-d", t)
            rc, out = run_cli(["check", "--root", str(root), "templates"])
            assert rc == 3 and "unverified" in out and "ref-missing" not in out, out
            # once the release is cut and v2 moved, it resolves
            git(root, "tag", "-a", "v2.1.0", "-m", "v2.1.0")
            git(root, "tag", "-a", "v2", "-m", "v2 -> v2.1.0")
            rc, out = run_cli(["check", "--root", str(root), "templates"])
            assert rc == 0 and "1 of 1 hub pin(s)" in out, out
    finally:
        hub_refs.default_getter = saved


def test_the_real_templates_resolve_against_this_checkout_when_its_tags_are_present():
    """Today's tree: every templated pin resolves (drift check (q)). Skipped,
    not passed, when this checkout holds no v* tags (a fresh CI checkout)."""
    if not hub_refs.GitBackend(HUB_ROOT).tags():
        print("    (skipped: no v* tags in this checkout)")
        return
    rc, out = run_cli(["check", "--root", str(HUB_ROOT), "--quiet", "templates"])
    assert rc == 0 and out == "", out


def test_fleet_lists_broken_callers_and_counts_unread_ones():
    import yaml  # noqa: F401  (the fleet listing reads the committed YAML)
    with tempfile.TemporaryDirectory() as d:
        reg = Path(d) / "harness_registry.yml"
        reg.write_text("schema: harness-registry/v1\nscan: {scanned_at: 2026-10-31 06:00 UTC}\nrepos:\n"
                       "- {repo: law-ai, scanned: true, hub_refs_unread_files: 2,"
                       " hub_refs: [{path: .github/workflows/ci.yml,"
                       " line: 83, kind: workflow, target: .github/workflows/spec-gate.yml, ref: v2,"
                       " uses: bamr87/bamr87/.github/workflows/spec-gate.yml@v2, status: file-missing-at-ref,"
                       " fix: [cut v2.1.0 and move v2]}]}\n"
                       "- {repo: private-one, scanned: false, external: false}\n"
                       "- {repo: upstream, scanned: false, external: true}\n", encoding="utf-8")
        rc, out = run_cli(["fleet", "--registry", str(reg)])
        assert rc == 1, out
        assert "law-ai: .github/workflows/ci.yml:83" in out and "cut v2.1.0 and move v2" in out, out
        assert "1 repo(s) unread (private-one)" in out and "2 workflow file(s) unread" in out, out
        reg.write_text("repos:\n- {repo: a, scanned: true}\n", encoding="utf-8")
        rc, out = run_cli(["fleet", "--registry", str(reg)])
        assert rc == 0 and "predates hub_refs" in out, out


# --------------------------------------------------------------------------- #
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
    print(f"{'FAIL' if failures else 'OK'} — hub_refs fixture tests")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
