#!/usr/bin/env python3
"""
Fixture tests for tools/jev/library.py — the harness experience library (JEV
capability three, docs/HARNESS-REFINEMENT.md) — and the context pack's
`library` provider that reads it. What is tested: an entry round-trips and
indexes, a malformed or leaking one is refused before anything is written,
`check` finds what a hand edit can break, the registry decides the domain,
the hub's own library is clean, and the pack shows a domain's lessons as
data under the engine's own title.

Run: python3 tools/test_jev_library.py
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys_path_root = Path(__file__).resolve().parents[1]
import sys  # noqa: E402

sys.path.insert(0, str(sys_path_root))

from tools.jev import context as C  # noqa: E402
from tools.jev import library as L  # noqa: E402
from tools.jev import spec as SP  # noqa: E402

ROOT = sys_path_root
FAKE_HOME = Path("/Users/alice")
CTX = SimpleNamespace(home=FAKE_HOME, work_root=FAKE_HOME / ".cache" / "jev" / "work", hostname="alice-mac")


def tmp() -> Path:
    return Path(tempfile.mkdtemp(prefix="jev-library-"))


def entry(**over) -> L.Entry:
    base = dict(loop="repo-scout", step="scout", domain="dev-tools", item="bamr87/SCHEMA",
                run_id="20261103T210353Z-repo-scout-scout-f6c613", adopted="inv1", date="2026-11-03", source="human",
                cue="when the brief lists no open issues and the agent cannot run the test suite",
                lesson="in the category emphasis, tell the agent to read the CI workflow files before proposing a "
                       "test change, so a proposal rests on what CI runs",
                evidence="edit row 1 (categories/dev-tools.md): base1 proposed a test gate it never saw run; inv1 "
                         "read .github/workflows first and cited the job",
                confidence="medium",
                edits=[L.Edit("categories/dev-tools.md", ["inv1"], "added a read-CI-first line",
                              "inv1 cited the workflow job at ACTION 4; base1 did not", "helped")])
    base.update(over)
    return L.Entry(**base)


def test_add_load_index_roundtrip():
    root = tmp()
    lib = L.Library(root, "repo-scout", "dev-tools")
    e = entry()
    d = lib.add(e, diff="--- a/.github/evolution/categories/dev-tools.md\n+++ b/x\n@@ -1 +1,2 @@\n+read CI first\n",
                ctx=CTX)
    assert d == root / "repo-scout" / "dev-tools" / e.id and (d / L.ENTRY_FILE).is_file() and (d / L.DIFF_FILE).is_file()
    assert L.ENTRY_ID_RX.fullmatch(e.id) and e.id.startswith("20261103-bamr87_SCHEMA-"), e.id
    back = lib.load(e.id)
    assert back == e, (back, e)
    assert lib.ids() == [e.id] and lib.entries() == [e]
    assert lib.diff_of(e.id).startswith("--- a/")
    md = lib.index_md()
    assert md.startswith("# Library — repo-scout / dev-tools") and e.cue in md and f"`{e.id}/{L.DIFF_FILE}`" in md
    # a second, newer entry sorts first
    e2 = entry(date="2026-11-04", item="bamr87/zer0-cms", cue="a different cue")
    lib.add(e2, ctx=CTX)
    assert [x.id for x in lib.entries()] == [e2.id, e.id]
    assert [lp + "/" + dm for lp, dm, _ in L.all_entries(root)] == ["repo-scout/dev-tools"] * 2
    assert "_(empty" in L.Library(root, "repo-scout", "docs").index_md()


def test_entry_problems():
    assert entry().problems() == []
    bad = {
        "confidence": ("confidence: one of", entry(confidence="certain")),
        "date": ("not YYYY-MM-DD", entry(date="yesterday")),
        "cue": ("cue: empty", entry(cue="  ")),
        "cue_line": ("cue: one line", entry(cue="a\nb")),
        "source": ("source: one of", entry(source="bot")),
        "loop": ("loop 'Repo Scout'", entry(loop="Repo Scout")),
        "domain": ("domain 'Dev Tools' is not a directory name", entry(domain="Dev Tools")),
        "verdict": ("edits[0].verdict: one of", entry(edits=[L.Edit("c", ["a"], "x", "y", "maybe")])),
        "cands": ("edits[0].candidates", entry(edits=[L.Edit("c", [], "x", "y", "helped")])),
        "long": ("lesson: over 800", entry(lesson="x" * 801)),
        "confounded": ("confidence high rests only on confounded",
                       entry(confidence="high", edits=[L.Edit("c", ["a"], "x", "y", "confounded")])),
    }
    for name, (want, e) in bad.items():
        probs = e.problems()
        assert any(want in p for p in probs), (name, probs)
        try:
            L.Library(tmp(), e.loop, e.domain).add(e, ctx=CTX)
        except L.LibraryError as exc:
            assert "refused" in str(exc), (name, exc)
        else:
            raise AssertionError(f"{name}: a malformed entry must be refused")


def test_leaks_are_refused_before_anything_is_written():
    root = tmp()
    lib = L.Library(root, "repo-scout", "dev-tools")
    leaks = {
        "home": entry(lesson="see /Users/alice/.cache/jev/work/x for the trace"),
        "host": entry(evidence="observed on alice-mac at 10:00"),
        "email": entry(notes="ask amr.abdel@gmail.com"),
        "token": entry(evidence="with ghp_" + "a" * 36 + " in the env"),
        "tmp": entry(cue="the clone under /private/tmp/claude-501/x"),
    }
    for name, e in leaks.items():
        try:
            lib.add(e, ctx=CTX)
        except L.LibraryError as exc:
            assert "carries" in str(exc), (name, exc)
        else:
            raise AssertionError(f"{name}: a leaking entry must be refused")
        assert not (root / "repo-scout" / "dev-tools" / e.id).exists(), name
    try:
        lib.add(entry(), diff="+++ /Users/alice/x\n", ctx=CTX)
    except L.LibraryError as exc:
        assert "harness.diff" in str(exc)
    else:
        raise AssertionError("a leaking diff must be refused")
    assert L.leak_problems("plain text", CTX) == []
    assert L.leak_problems("sk-ant-" + "b" * 24, None) == ["a credential shape"]


def test_duplicate_add_is_refused_and_forget_removes():
    root = tmp()
    lib = L.Library(root, "repo-scout", "dev-tools")
    e = entry()
    lib.add(e, ctx=CTX)
    try:
        lib.add(e, ctx=CTX)
    except L.LibraryError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("a duplicate must be refused")
    other = L.Library(root, "repo-evolution", "dev-tools")
    try:
        other.add(e, ctx=CTX)
    except L.LibraryError as exc:
        assert "this library is repo-evolution/dev-tools" in str(exc)
    else:
        raise AssertionError("a wrong-library entry must be refused")
    assert lib.forget(e.id) and not lib.ids() and not lib.forget(e.id)
    try:
        lib.load("not-an-id")
    except L.LibraryError:
        pass
    else:
        raise AssertionError("a bad id must refuse")


def test_check_all_finds_what_a_hand_edit_breaks():
    root = tmp()
    lib = L.Library(root, "repo-scout", "dev-tools")
    e = entry()
    d = lib.add(e, ctx=CTX)
    assert L.check_all(root, CTX) == []
    (d / "notes.txt").write_text("stray", encoding="utf-8")
    (root / "repo-scout" / "dev-tools" / "random").mkdir()
    (root / "README.md").write_text("fine\n", encoding="utf-8")
    (root / "Repo Scout").mkdir()
    probs = L.check_all(root, CTX)
    assert any("stray file(s) ['notes.txt']" in p for p in probs), probs
    assert any("random: not an entry directory" in p for p in probs), probs
    assert any("Repo Scout: not a loop directory" in p for p in probs), probs
    text = (d / L.ENTRY_FILE).read_text(encoding="utf-8").replace("loop: repo-scout", "loop: repo-evolution")
    (d / L.ENTRY_FILE).write_text(text, encoding="utf-8")
    probs = L.check_all(root, CTX)
    assert any("the entry's id" in p and "is not its directory" in p for p in probs), probs
    (d / L.DIFF_FILE).write_text("+ on alice-mac\n", encoding="utf-8")
    assert any("harness.diff: carries" in p for p in L.check_all(root, CTX)), L.check_all(root, CTX)


def test_domain_of_and_domain_dir():
    reg = tmp() / "projects.yml"
    reg.write_text("projects:\n  - name: SCHEMA\n    repo_url: https://github.com/bamr87/SCHEMA\n    category: dev-tools\n"
                   "  - name: it-journey\n    repo_url: https://github.com/bamr87/it-journey.git\n    category: Docs / Sites\n"
                   "  - name: nocat\n    repo_url: https://github.com/bamr87/nocat\n", encoding="utf-8")
    assert L.domain_of("bamr87/SCHEMA", reg) == "dev-tools"
    assert L.domain_of("BAMR87/schema", reg) == "dev-tools"
    assert L.domain_of("bamr87/it-journey", reg) == "docs__sites"
    assert L.domain_of("bamr87/nocat", reg) == L.UNKNOWN_DOMAIN
    assert L.domain_of("bamr87/missing", reg) == L.UNKNOWN_DOMAIN
    assert L.domain_of("not a slug", reg) == L.UNKNOWN_DOMAIN
    assert L.domain_of("bamr87/SCHEMA", reg.with_name("absent.yml")) == L.UNKNOWN_DOMAIN
    assert L.domain_dir("Dev Tools/") == L.UNKNOWN_DOMAIN and L.domain_dir("docs") == "docs"
    assert L.domain_of("bamr87/SCHEMA") == "dev-tools", "the hub registry lists SCHEMA as dev-tools"


def test_root_comes_from_the_env_then_fleet_then_the_default():
    old = os.environ.pop("JEV_LIBRARY_DIR", None)
    try:
        assert L.root(None) == L.HUB / L.DEFAULT_DIR
        assert L.root({"harness_refinement": {"library_dir": "_data/lib2"}}) == L.HUB / "_data/lib2"
        os.environ["JEV_LIBRARY_DIR"] = "/tmp/x"
        assert L.root({"harness_refinement": {"library_dir": "_data/lib2"}}) == Path("/tmp/x")
        for bad in ("/abs", "../up", ""):
            try:
                os.environ.pop("JEV_LIBRARY_DIR", None)
                L.root({"harness_refinement": {"library_dir": bad}})
            except L.LibraryError:
                pass
            else:
                raise AssertionError(f"{bad!r} must refuse")
    finally:
        os.environ.pop("JEV_LIBRARY_DIR", None)
        if old is not None:
            os.environ["JEV_LIBRARY_DIR"] = old


def test_the_hubs_library_is_clean():
    fleet = SP.load_fleet()
    root = L.root(fleet)
    assert root == ROOT / "_data" / "harness_library" and (root / "SCHEMA.md").is_file()
    assert L.check_all(root, None) == []


class _Ctx:
    """The RunContext surface the library provider reads."""

    def __init__(self, loop: str = "repo-scout"):
        self.spec = SimpleNamespace(loop=loop, step="scout", workspace=SimpleNamespace(brief_dir=".scout"))
        self.home, self.work_root, self.hostname = CTX.home, CTX.work_root, CTX.hostname
        self.history = SimpleNamespace(rows=lambda: iter(()), base=None)
        self.fleet = None


def test_the_context_pack_shows_a_domains_lessons_as_data():
    root = tmp()
    L.Library(root, "repo-scout", "dev-tools").add(entry(), ctx=CTX)
    req = C.ContextRequest("bamr87/SCHEMA", "SCHEMA")
    old = os.environ.get("JEV_LIBRARY_DIR")
    os.environ["JEV_LIBRARY_DIR"] = str(root)
    try:
        sec = C.library_section(_Ctx(), req)
        assert sec["status"] == "ok" and sec["source"] == C.LIBRARY_SOURCE and len(sec["rows"]) == 1, sec
        row = sec["rows"][0]
        assert row["kind"] == "lesson" and row["confidence"] == "medium" and row["cue"] == entry().cue, row
        assert "hypothesis" in sec["note"]
        empty = C.library_section(_Ctx("repo-evolution"), req)
        assert empty["status"] == "empty" and "repo-evolution" in empty["note"], empty
        doc = C.gather(_Ctx(), req, sections=["history", "library"])
        assert list(doc["sections"]) == ["history", "library"], list(doc["sections"])
        md = C.render(doc, brief_dir=".scout")
        assert f"## {C.TITLES['library']} — ok" in md and "cue: " + entry().cue in md and "lesson: " in md, md
        assert C.SOURCE_LABELS[C.LIBRARY_SOURCE] in md
        # a malformed entry costs the section, never the run
        bad = root / "repo-scout" / "dev-tools" / "20261101-x-0123abcd"
        bad.mkdir()
        (bad / L.ENTRY_FILE).write_text("schema: nope\n", encoding="utf-8")
        sec = C.library_section(_Ctx(), req)
        assert sec["status"] == "unavailable" and "schema must be" in sec["note"], sec
    finally:
        if old is None:
            os.environ.pop("JEV_LIBRARY_DIR", None)
        else:
            os.environ["JEV_LIBRARY_DIR"] = old
    assert "library" in C.PROVIDERS and C.RENDER_ORDER[1] == "library" and C.TRIM_ORDER[-2] == "library"
    assert C.LIBRARY_SOURCE in C.SCHEMA_WORDS and {"cue", "lesson", "confidence"} <= C.SCHEMA_WORDS


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
