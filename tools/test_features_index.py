#!/usr/bin/env python3
"""
Fixture tests for tools/features_index.py — the fleet features index.

Guards the invariants that make the index trustworthy as a CONTROL surface
(it feeds the /features/ page, the verify-fanout `gaps` target, and the
UPS-QA-50..53 conformance checks, so a wrong grade is a wrong PR or a false
alarm):

  * the three precedent shapes (zer0-mistakes, it-journey, barodybroject)
    validate unchanged — the fleet schema is a strict superset;
  * coverage is graded from FILES ON DISK: a `tests:` path that does not exist
    is a dangling link and counts for nothing, a `{na: reason}` waiver counts
    as covered but never as evidenced;
  * a scenario that names a feature covers it even when the feature entry
    forgot the back-link;
  * hard errors (bad id, duplicate id, missing title) fail `check`; warnings
    never do;
  * fleet aggregation reads the registry, skips archived + unmounted repos,
    includes the hub itself, and produces stable, `--check`-comparable output.

Deliberately dependency-light — no network, no gh, no pytest. Needs only PyYAML:

    python3 tools/test_features_index.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import features_index as fi  # noqa: E402


def write(root: Path, rel: str, text: str = "x") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def repo_with(tmp: Path, features: list[dict], schema: bool = True, extra: dict | None = None) -> Path:
    r = tmp / "repo"
    r.mkdir(exist_ok=True)
    (r / ".git").mkdir(exist_ok=True)
    data = {"features": features}
    if schema:
        data["schema"] = "features/v1"
    if extra:
        data.update(extra)
    write(r, "features/features.yml", yaml.safe_dump(data, sort_keys=False))
    return r


def test_precedents_validate():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        # it-journey / barodybroject shape: minimal legacy
        r = repo_with(tmp, [{"id": "FR-ITJ-001", "title": "Jekyll site generation", "description": "Automated",
                             "implemented": True, "link": "/", "tags": ["site", "jekyll", "build"], "date": "2024-03-12"}],
                      schema=False)
        res = fi.analyze(r)
        assert res["ok"], res["errors"]
        assert res["format"] == "legacy"
        assert res["features"][0]["surface"] == "infra", "legacy `/` + build tags must not count as UI"
        # zer0-mistakes shape: provenance + references + {na:} waiver
        write(r, "test/visual/core/styling.spec.js")
        r2 = repo_with(tmp, [
            {"id": "ZER0-001", "title": "Theme", "description": "Bootstrap theme", "implemented": True, "version": "0.1.0",
             "link": "/", "docs": "/docs/bootstrap/", "tags": ["jekyll", "theme", "ui"], "date": "2025-01-27",
             "provenance": {"introduced_in": "0.1.0", "pr": None, "commit": "a8426a5"},
             "tests": ["test/visual/core/styling.spec.js"], "references": {"layouts": ["_layouts/root.html"]}},
            {"id": "ZER0-005", "title": "Agent docs", "description": "AGENTS.md", "implemented": True, "link": "/",
             "tags": ["ai", "documentation"], "tests": [{"na": "Process/docs feature; no runtime test"}]},
        ], schema=False)
        res = fi.analyze(r2)
        assert res["ok"], res["errors"]
        f0, f1 = res["features"]
        assert f0["surface"] == "ui" and f0["covered"] and not f0["evidenced"]
        assert f1["surface"] == "docs" and f1["covered"] and f1["waived"] and not f1["evidenced"]
        assert not any("not found" in w for w in res["warnings"]), res["warnings"]
        assert res["counts"]["dangling"] == 0


def test_coverage_is_graded_from_disk():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        r = repo_with(tmp, [
            {"id": "APP-001", "title": "Login", "description": "Sign in", "implemented": True, "surface": "ui", "link": "/login",
             "tests": ["src/login.test.ts", "src/missing.test.ts"], "scenarios": ["verify/scenarios/login.yml"],
             "evidence": ["test/evidence/login"], "verified": {"date": "2026-09-04", "by": "agent", "run": "https://x"}},
            {"id": "APP-002", "title": "Export", "description": "Export CV", "implemented": True, "surface": "ui", "link": "/export"},
            {"id": "APP-003", "title": "Planned", "description": "Not yet", "implemented": False, "surface": "ui", "link": "/soon"},
        ])
        write(r, "src/login.test.ts")
        write(r, "verify/verify.yml", yaml.safe_dump({"schema": "verify/v1", "app": {"url": "http://127.0.0.1:5000"}}))
        write(r, "verify/scenarios/login.yml", yaml.safe_dump({"id": "login", "feature": "APP-001", "steps": [{"goto": "/login"}]}))
        # a scenario naming APP-002 covers it even without the back-link
        write(r, "verify/scenarios/export.yml", yaml.safe_dump({"id": "export", "feature": "APP-002", "steps": [{"goto": "/export"}]}))
        write(r, "test/evidence/login/desktop-home.png", "png")
        write(r, "test/evidence/login/report.json", "{}")
        write(r, "test/evidence/report.json", '{"schema":"verify-report/v1","passed":1,"failed":1,"total":2,"by":"ci","generated":"2026-09-04T00:00:00Z"}')
        write(r, ".github/workflows/verify.yml", "jobs:\n  verify:\n    uses: bamr87/bamr87/.github/workflows/fleet-verify.yml@main\n    with:\n      gate: true\n")
        res = fi.analyze(r)
        assert res["ok"], res["errors"]
        a, b, c = res["features"]
        assert a["tests"] == ["src/login.test.ts"] and a["dangling"] == ["src/missing.test.ts"]
        assert a["covered"] and a["evidenced"] and a["verified"]["by"] == "agent"
        assert a["screenshots"] == ["test/evidence/login/desktop-home.png"]
        assert b["covered"] and b["scenarios"] == ["verify/scenarios/export.yml"] and not b["evidenced"] and b["verified"] is None
        assert not c["covered"]
        cnt = res["counts"]
        assert (cnt["features"], cnt["implemented"], cnt["covered"], cnt["evidenced"], cnt["verified"]) == (3, 2, 2, 1, 1)
        assert (cnt["ui"], cnt["ui_covered"], cnt["ui_verified"], cnt["dangling"]) == (2, 2, 1, 1)
        assert res["pct"] == {"coverage": 100, "evidence": 50, "verified": 50}
        k = res["kit"]
        assert k["config"] and k["scenarios"] == 2 and k["workflow"] and k["workflow_fleet_caller"] and k["workflow_gate"]
        assert res["last_run"]["failed"] == 1
        assert any("dangling" in g for g in fi.gaps_for(res))
        assert any("not found: src/missing.test.ts" in w for w in res["warnings"])


def test_hard_errors_fail_check_and_warnings_do_not():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        r = repo_with(tmp, [
            {"id": "bad id", "title": "x", "description": "y", "implemented": True},
            {"id": "APP-001", "title": "x", "description": "y", "implemented": True, "surface": "ui"},
            {"id": "APP-001", "description": "dup, no title", "implemented": True},
            {"id": "APP-002", "title": "t", "description": "d", "implemented": True, "surface": "sofa"},
        ])
        res = fi.analyze(r)
        assert not res["ok"]
        msgs = " | ".join(res["errors"])
        assert "must match" in msgs and "duplicate id" in msgs and "missing title" in msgs and "surface must be" in msgs
        assert fi.main(["check", str(r)]) == 1
        r2 = repo_with(tmp, [{"id": "APP-001", "title": "t <b>", "description": "d", "implemented": "yes",
                              "verified": "yesterday", "docs": "docs/none.md"}])
        res2 = fi.analyze(r2)
        assert res2["ok"], res2["errors"]
        w = " | ".join(res2["warnings"])
        assert "'<'" in w and "implemented" in w and "verified must be a mapping" in w and "docs path not found" in w
        assert fi.main(["check", str(r2)]) == 0
        # prose-only and none
        r3 = tmp / "prose"; r3.mkdir(); write(r3, "FEATURES.md", "# Features")
        assert fi.analyze(r3)["format"] == "prose"
        r4 = tmp / "none"; r4.mkdir()
        assert fi.analyze(r4)["format"] == "none" and fi.gaps_for(fi.analyze(r4))[0].startswith("no feature index")


def test_fleet_aggregation():
    with tempfile.TemporaryDirectory() as d:
        hub = Path(d)
        write(hub, "_data/projects.yml", yaml.safe_dump([
            {"name": "app", "slug": "app", "submodule_path": "projects/app", "branch": "main", "status": "active",
             "repo_url": "https://github.com/bamr87/app", "live_url": "https://app.example", "kinds": ["app"]},
            {"name": "gone", "submodule_path": "projects/gone", "branch": "main", "status": "active", "repo_url": "https://github.com/bamr87/gone"},
            {"name": "old", "submodule_path": "projects/old", "branch": "main", "status": "archived", "repo_url": "https://github.com/bamr87/old"},
            {"name": "ext", "submodule_path": None, "branch": "main", "status": "active", "repo_url": "https://github.com/other/ext"},
        ]))
        write(hub, "templates/verify/VERSION", "kit: verify\nversion: 0.1.0\n")
        write(hub, "features/features.yml", yaml.safe_dump({"schema": "features/v1", "features": [
            {"id": "HUB-001", "title": "Dash", "description": "d", "implemented": True, "surface": "ui", "link": "/dashboard/",
             "tests": ["tools/test_x.py"]}]}))
        write(hub, "tools/test_x.py")
        app = hub / "projects" / "app"; (app / ".git").mkdir(parents=True)
        write(app, "features/features.yml", yaml.safe_dump({"schema": "features/v1", "features": [
            {"id": "APP-001", "title": "Login", "description": "d", "implemented": True, "surface": "ui", "link": "/login",
             "docs": "docs/login.md", "evidence": ["test/evidence/login"]}]}))
        write(app, "docs/login.md"); write(app, "test/evidence/login/mobile-home.png", "png")
        old = hub / "projects" / "old"; (old / ".git").mkdir(parents=True)
        write(old, "features/features.yml", yaml.safe_dump({"features": [{"id": "OLD-001", "title": "t", "description": "d", "implemented": True}]}))

        data = fi.fleet(hub)
        names = [r["name"] for r in data["repos"]]
        assert names[0] == "app" or "app" in names
        assert "bamr87" in names and "gone" not in names and "old" not in names and "ext" not in names
        assert data["kit_version"] == "0.1.0" and data["schema"] == "features-index/v1"
        appr = next(r for r in data["repos"] if r["name"] == "app")
        it = appr["items"][0]
        assert it["urls"]["link"] == "https://app.example/login"
        assert it["urls"]["docs"] == "https://github.com/bamr87/app/blob/main/docs/login.md"
        assert it["urls"]["evidence"] == ["https://github.com/bamr87/app/tree/main/test/evidence/login"]
        assert it["urls"]["screenshots"] == ["https://raw.githubusercontent.com/bamr87/app/main/test/evidence/login/mobile-home.png"]
        assert "summary" in it and "description" not in it
        t = data["totals"]
        assert t["repos_scanned"] == 2 and t["features"] == 2 and t["ui"] == 2 and t["ui_covered"] == 1
        kinds = {a["kind"] for a in data["attention"]}
        assert "ui-uncovered" in kinds
        # `--check` is stable modulo generated_at
        out = hub / "_data" / "features_index.yml"
        assert fi.main(["fleet", "--hub", str(hub), "--write"]) == 0 and out.is_file()
        assert fi.main(["fleet", "--hub", str(hub), "--check"]) == 0
        loaded = yaml.safe_load(out.read_text())
        assert loaded["totals"] == t
        write(app, "features/features.yml", yaml.safe_dump({"schema": "features/v1", "features": []}))
        assert fi.main(["fleet", "--hub", str(hub), "--check"]) == 1


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
