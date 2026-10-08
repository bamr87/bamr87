#!/usr/bin/env python3
"""Headless UI tests for tools/tui/app.py, driven through Textual's Pilot.

tools/test_tui_fleet.py proves the data; this proves the screen: layout,
navigation, the drill-down, markup safety, and the background refresh. Every
case runs against a fixture root (never the live `_data/`) with Docker polling
off and `webbrowser.open` captured, so nothing leaves the process.

    .venv-tui/bin/python tools/tui/test_app.py      # run-all-tests picks the venv

Skips (exit 0, says so) when Textual is not importable.
"""
from __future__ import annotations

import asyncio
import os
import stat
import sys
import tempfile
import time
import webbrowser
from pathlib import Path

import yaml

try:
    import textual  # noqa: F401
except ImportError:
    print("SKIP tools/tui/test_app.py: Textual not installed (tools/dash tui bootstraps .venv-tui)")
    sys.exit(0)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app as A  # noqa: E402
from fleetcore import host as dh  # noqa: E402  (app.py puts tools/ on the path)

SIZE = (150, 40)

PROJECTS = [
    {"name": "alpha", "description": "first [/b] project", "category": "docs", "status": "active",
     "featured": True, "stack": ["jekyll"], "repo_url": "https://github.com/bamr87/alpha",
     "live_url": "https://alpha.example", "submodule_path": "projects/alpha"},
    {"name": "beta", "description": "second", "category": "dev-tools", "status": "experiment",
     "stack": ["python"], "repo_url": "https://github.com/bamr87/beta", "submodule_path": "projects/beta"},
    *[
        {"name": f"p{n:02d}", "description": "filler", "category": "docs", "status": "active",
         "stack": [], "repo_url": f"https://github.com/bamr87/p{n:02d}"}
        for n in range(30)
    ],
]
TRIAGE = {
    "generated_at": "2026-09-30 06:03 UTC",
    "by_repo": [
        {"name": "beta", "repo_url": "https://github.com/bamr87/beta",
         "issues": {"open": 1, "items": [
             {"number": 3, "title": "[bug] beta breaks", "labels": ["bug"], "age_days": 5, "idle_days": 5,
              "url": "https://github.com/bamr87/beta/issues/3"}]},
         "prs": {"open": 0, "items": []},
         "workflows": {"failing": [{"workflow": "CI [/x]", "path": ".github/workflows/ci.yml",
                                    "conclusion": "failure", "run_url": "https://github.com/bamr87/beta/actions/runs/9"}]},
         "attention": {"score": 99, "level": "red", "reasons": ["1 failing workflow(s)"]}},
    ],
    "inbox": [
        {"kind": "workflow", "repo": "beta", "ref": ".github/workflows/ci.yml", "title": "CI [/x]",
         "why": "latest run failure", "age_days": None, "url": "https://github.com/bamr87/beta/actions/runs/9",
         "priority": 90},
        {"kind": "issue", "repo": "beta", "ref": "#3", "title": "[bug] beta breaks", "why": "bug label",
         "age_days": 5, "url": "https://github.com/bamr87/beta/issues/3", "priority": 60},
    ],
}
HARNESS = {
    "generated_at": "2026-09-30 06:03 UTC",
    "trip_wires": [{"id": "pass-rate-floor", "tripped": True, "summary": "71% vs floor 75%"}],
    "scorecard": {"completion_rate_pct": {"value": 71.5, "direction": "up", "threshold": 80, "status": "warn"}},
}
# A stand-in for tools/dash-gen: progress lines on stderr, then the file.
DASH_GEN = """#!/usr/bin/env python3
import sys, time, pathlib
root = pathlib.Path(__file__).resolve().parents[1]
for name in ("alpha", "beta"):
    sys.stderr.write(f"  · {name}\\n"); sys.stderr.flush(); time.sleep(0.05)
(root / "_data" / "project_health.yml").write_text(
    "- name: alpha\\n  attention: {level: amber, reasons: [slow CI]}\\n", encoding="utf-8")
(root / "_data" / "project_health_meta.yml").write_text("generated_at: 2026-09-30 07:00 UTC\\n", encoding="utf-8")
"""


def make_root(td: str, *, triage=True, harness=True) -> Path:
    root = Path(td)
    data = root / "_data"
    data.mkdir()
    (data / "projects.yml").write_text(yaml.safe_dump(PROJECTS), encoding="utf-8")
    if triage:
        (data / "fleet_triage.yml").write_text(yaml.safe_dump(TRIAGE), encoding="utf-8")
    if harness:
        (data / "harness_health.yml").write_text(yaml.safe_dump(HARNESS), encoding="utf-8")
    for p in ("alpha", "beta"):
        (root / "projects" / p).mkdir(parents=True)
        (root / "projects" / p / "README.md").write_text("x", encoding="utf-8")
    gen = root / "tools" / "dash-gen"
    gen.parent.mkdir()
    gen.write_text(DASH_GEN, encoding="utf-8")
    gen.chmod(gen.stat().st_mode | stat.S_IXUSR)
    return root


class Browser:
    """Captures webbrowser.open so a test can assert on it without a browser.
    found=False answers as a machine with none does (a container): False."""

    def __init__(self, found: bool = True) -> None:
        self.opened: list[str] = []
        self.found = found

    def __enter__(self) -> "Browser":
        self._real = webbrowser.open
        webbrowser.open = lambda url, *a, **k: self.opened.append(url) or self.found
        return self

    def __exit__(self, *exc) -> None:
        webbrowser.open = self._real


def cell(app, table_id: str, row: int, col: int) -> str:
    return str(app.query_one(f"#{table_id}").get_cell_at((row, col)))


async def until(pilot, cond, timeout: float = 5.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        await pilot.pause(0.05)
    return cond()


async def t_layout_header_visible(root: Path) -> None:
    """The KPI line, status line and search box sit above the tabs. They were
    scrolled off-screen: TabbedContent had no height, so the pane overflowed."""
    app = A.DashTui(root=root, hosts=[])
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        for wid in ("#kpis", "#status", "#search", "#apps"):
            region = app.query_one(wid).region
            assert region.height > 0 and region.y >= 0, (wid, region)
            assert region.y + region.height <= SIZE[1], (wid, region)
        assert app.query_one("#kpis").region.y < app.query_one("#apps").region.y
        assert app.screen.scroll_y == 0


async def t_cursor_survives_repaint(root: Path) -> None:
    """A Docker poll (and any reload/filter) used to snap the cursor to row 0."""
    app = A.DashTui(root=root, hosts=[])
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("down", "down", "down")
        apps = app.query_one("#apps")
        before = (apps.cursor_row, app._selected)
        app._host_done([], {})  # exactly what the 15 s poll does on completion
        await pilot.pause()
        assert (apps.cursor_row, app._selected) == before, ((apps.cursor_row, app._selected), before)
        app.action_reload()
        await pilot.pause()
        assert app._selected == before[1]
        await pilot.press("s")  # re-sort by name: same project stays selected, at its new index
        await pilot.pause()
        assert app._selected == before[1]
        assert apps.coordinate_to_cell_key((apps.cursor_row, 0)).row_key.value == before[1]


async def t_hidden_tables_do_not_steal_selection(root: Path) -> None:
    """A repaint re-highlights every table; a hidden tab's cursor must not
    become what `o` opens on the visible one."""
    app = A.DashTui(root=root, hosts=[])
    with Browser() as b:
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await pilot.press("down")  # Apps cursor → beta (alpha is featured, first)
            await pilot.pause()
            assert app._selected == "beta", app._selected
            app._paint()  # Attention's cursor sits on beta too, Monitor is empty …
            await pilot.pause()
            await pilot.press("o")
            await pilot.pause()
            assert b.opened == ["https://github.com/bamr87/beta"], b.opened


async def t_query_not_shadowed(root: Path) -> None:
    app = A.DashTui(root=root, hosts=[])
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert len(app.query("DataTable")) == 7  # six fleet tabs + Jobs


async def t_markup_is_literal(root: Path) -> None:
    """GitHub text containing [tags] must render verbatim and never crash."""
    app = A.DashTui(root=root, hosts=[])
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("2")
        await pilot.pause()
        assert cell(app, "inbox", 0, 3) == "CI [/x]"
        assert cell(app, "inbox", 1, 3) == "#3 [bug] beta breaks"
        await pilot.press("1")
        await pilot.pause()
        assert "first [/b] project" in str(app.query_one("#meta").render())


async def t_drill_and_open(root: Path) -> None:
    """enter on a project → that repo's items; enter on an item → its URL, once."""
    app = A.DashTui(root=root, hosts=[])
    with Browser() as b:
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await pilot.press("down", "enter")  # beta
            await pilot.pause()
            assert app.query_one("#tabs").active == "tab-inbox"
            assert app.repo_filter == "beta"
            assert b.opened == [], b.opened  # the drill did not also open a browser
            inbox = app.query_one("#inbox")
            assert inbox.row_count == 2 and app.focused is inbox
            await pilot.press("down", "enter")
            await pilot.pause()
            assert b.opened == ["https://github.com/bamr87/beta/issues/3"], b.opened
            await pilot.press("x")
            await pilot.pause()
            assert app.repo_filter is None and inbox.row_count == 2


async def t_no_browser_shows_the_link(root: Path) -> None:
    """In a container webbrowser.open finds nothing and returns False: o and l
    must then show the URL rather than do nothing."""
    app = A.DashTui(root=root, hosts=[])
    with Browser(found=False) as b:
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await pilot.press("o", "l")  # alpha: repo, then live_url
            await pilot.pause()
            shown = [n.message for n in app._notifications]
            assert b.opened == ["https://github.com/bamr87/alpha", "https://alpha.example"], b.opened
            assert shown == b.opened, shown


class FakeConsole:
    """Stands in for fleetcore.client.ConsoleClient: an in-memory job API with
    the console's confirm gate, so the Jobs tab is tested without a server."""

    enabled = True
    url = "unix:///fake.sock"

    def __init__(self) -> None:
        self.submitted: list[tuple[str, bool]] = []
        self._jobs: list[dict] = []

    def ops(self) -> list[dict]:
        return [{"id": "harness", "title": "Harness scorecard", "group": "observe", "desc": "", "remote_write": False},
                {"id": "deploy", "title": "Deploy the kit", "group": "deploy", "desc": "", "remote_write": True}]

    def jobs(self) -> list[dict]:
        return list(self._jobs)

    def submit(self, op: str, params=None, confirm: bool = False) -> dict:
        if op == "deploy" and not confirm:
            raise A.ConsoleError("'deploy' writes to GitHub — resubmit with confirm=true")
        self.submitted.append((op, confirm))
        job = {"id": f"{len(self._jobs):012x}", "op": op, "title": op, "status": "succeeded",
               "created": "2026-10-07T12:00:00+00:00", "started": "2026-10-07T12:00:01+00:00", "exit_code": 0}
        self._jobs.insert(0, job)
        return job

    def tail(self, job_id: str, offset: int = 0) -> dict:
        job = next(j for j in self._jobs if j["id"] == job_id)
        text = "$ dash-gen harness\n\x1b[1m== Harness ==\x1b[0m\nok\n"
        return {"job": job, "text": text[offset:], "offset": len(text), "done": True}

    def cancel(self, job_id: str) -> dict:
        return {}


async def t_keys_v1(root: Path) -> None:
    """The shared keymap (fleetcore.keys): ] [ tabs, j k g G rows, esc back, y copy."""
    app = A.DashTui(root=root, hosts=[])
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        tabs, apps = app.query_one("#tabs"), app.query_one("#apps")
        await pilot.press("right_square_bracket")
        assert tabs.active == "tab-inbox", tabs.active
        await pilot.press("left_square_bracket", "left_square_bracket")
        assert tabs.active == "tab-jobs", tabs.active   # wraps
        await pilot.press("1", "j")
        await pilot.pause()
        assert apps.cursor_row == 1
        await pilot.press("G")
        assert apps.cursor_row == apps.row_count - 1
        await pilot.press("g", "k")
        assert apps.cursor_row == 0
        await pilot.press("enter")  # drill into alpha's inbox …
        await pilot.pause()
        assert app.repo_filter == "alpha"
        await pilot.press("escape")  # … and esc leaves it
        await pilot.pause()
        assert app.repo_filter is None
        await pilot.press("1", "y")
        await pilot.pause()
        assert [n.message for n in app._notifications][-1] == "https://github.com/bamr87/alpha"


async def t_jobs_through_the_console(root: Path) -> None:
    """A job is SUBMITTED to the console runtime, its log tails in the Jobs tab,
    and a write the console refuses without confirm asks first."""
    fake = FakeConsole()
    app = A.DashTui(root=root, hosts=[], console=fake)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert any(op["id"] == "deploy" for op in app.ops)
        app.run_op("harness")
        assert await until(pilot, lambda: "ok" in "\n".join(app.query_one("#joblog").lines))
        shown = "\n".join(app.query_one("#joblog").lines)
        assert "== Harness ==" in shown and "\x1b" not in shown, shown  # colour codes never reach the frame
        assert app.query_one("#tabs").active == "tab-jobs"
        assert app.query_one("#jobs").row_count == 1
        app.run_op("deploy")
        assert await until(pilot, lambda: isinstance(app.screen, A.Confirm))
        await pilot.press("y")
        assert await until(pilot, lambda: ("deploy", True) in fake.submitted)
        assert fake.submitted == [("harness", False), ("deploy", True)], fake.submitted


async def t_strip_ansi_holds_a_split_sequence(root: Path) -> None:
    text, keep = A.strip_ansi("ok \x1b[1mbold\x1b[0m done \x1b[3")
    assert (text, keep) == ("ok bold done ", "\x1b[3")
    text, keep = A.strip_ansi(keep + "2mred\x1b]8;;http://x\x07link\x1b]8;;\x07\r\n")
    assert (text, keep) == ("redlink\n", ""), (text, keep)


async def t_without_a_console_jobs_explains(root: Path) -> None:
    app = A.DashTui(root=root, hosts=[])
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("7")
        await pilot.pause()
        assert "No console runtime" in str(app.query_one("#jobs-note").render())
        app.run_op("harness")  # refused politely, nothing raised
        await pilot.pause()


async def t_search_and_escape(root: Path) -> None:
    app = A.DashTui(root=root, hosts=[])
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("slash", *"beta")
        await pilot.pause()
        assert app.query_one("#apps").row_count == 1
        assert app.focused.id == "search"
        await pilot.press("s")  # typed into the box, not a sort
        await pilot.pause()
        assert app.search == "betas" and app.sort_key == "featured"
        await pilot.press("backspace", "escape")
        await pilot.pause()
        assert app.focused.id == "apps"
        await pilot.press("c", "t", "f", "h", "x")
        await pilot.pause()
        assert (app.search, app.category, app.status, app.featured_only, app.health_filter) == ("", None, None, False, None)
        assert app.query_one("#apps").row_count == len(PROJECTS)


async def t_empty_states_explain_themselves(root: Path) -> None:
    app = A.DashTui(root=root, hosts=[])
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        for tab, note in (("4", "#monitor-note"), ("2", "#inbox-note"), ("6", "#docker-note")):
            await pilot.press(tab)
            await pilot.pause()
            n = app.query_one(note)
            assert n.has_class("-show"), note
        assert "dash-gen health" in str(app.query_one("#monitor-note").render())
        assert "fleet_triage.yml" in str(app.query_one("#inbox-note").render())
        assert "DASH_DOCKER_HOST" in str(app.query_one("#docker-note").render())


async def t_docker_join_and_tab(root: Path) -> None:
    app = A.DashTui(root=root, hosts=["local", "ssh://forge"])
    app.action_poll_host = lambda: None  # no real docker in tests
    with Browser() as b:
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            boxes = [
                dh.Container(name="beta-web-1", state="running", status="Up 1h", host="local"),
                dh.Container(name="beta-db-1", state="exited", status="Exited (0)", host="local"),
                dh.Container(name="console-1", state="running", status="Up", host="local",
                             labels={"com.bamr87.fleet.project": "bamr87"}),
            ]
            app._host_done(boxes, {"forge": "ssh: Host is down"})
            await pilot.pause()
            assert cell(app, "apps", 1, 12) == "1/2 up"
            status = str(app.query_one("#status").render())
            assert "local 2/3" in status and "forge ✗" in status, status
            await pilot.press("6")
            await pilot.pause()
            assert app.query_one("#docker").row_count == 3
            assert "forge: ssh: Host is down" in str(app.query_one("#docker-note").render())
            await pilot.press("o")  # first row is beta-db-1? sorted running-first: beta-web-1
            await pilot.pause()
            assert b.opened == ["https://github.com/bamr87/beta"], b.opened


async def t_harness_tab(root: Path) -> None:
    app = A.DashTui(root=root, hosts=[])
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("5")
        await pilot.pause()
        assert cell(app, "harness", 0, 2) == "TRIPPED"
        assert cell(app, "harness", 1, 3) == "want ↑  threshold 80"


async def t_reload_on_disk_change(root: Path) -> None:
    app = A.DashTui(root=root, hosts=[])
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        n = app.query_one("#apps").row_count
        reg = root / "_data" / "projects.yml"
        reg.write_text(yaml.safe_dump(PROJECTS[:3]), encoding="utf-8")
        os.utime(reg, (time.time() + 5, time.time() + 5))  # mtime granularity
        app._tick()
        await pilot.pause()
        assert app.query_one("#apps").row_count == 3 != n


async def t_refresh_health_streams_progress(root: Path) -> None:
    app = A.DashTui(root=root, hosts=[])
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert not app.snapshot.health_present
        seen: list[str] = []
        real = app._health_progress
        app._health_progress = lambda text: (seen.append(text), real(text))
        await pilot.press("R")
        assert await until(pilot, lambda: not app._refreshing and app.snapshot.health_present)
        assert seen == ["1/32 alpha", "2/32 beta"], seen
        assert app.query_one("#apps").get_cell_at((0, 0)) == "🟠"


CASES = [
    t_layout_header_visible,
    t_cursor_survives_repaint,
    t_hidden_tables_do_not_steal_selection,
    t_query_not_shadowed,
    t_markup_is_literal,
    t_drill_and_open,
    t_no_browser_shows_the_link,
    t_keys_v1,
    t_jobs_through_the_console,
    t_without_a_console_jobs_explains,
    t_strip_ansi_holds_a_split_sequence,
    t_search_and_escape,
    t_docker_join_and_tab,
    t_harness_tab,
    t_reload_on_disk_change,
    t_refresh_health_streams_progress,
]


def main() -> int:
    failed = 0
    total = len(CASES) + 1
    for case in CASES:
        with tempfile.TemporaryDirectory() as td:
            try:
                asyncio.run(case(make_root(td)))
                print(f"PASS {case.__name__}")
            except Exception as exc:  # noqa: BLE001 — report and continue
                failed += 1
                print(f"FAIL {case.__name__}: {type(exc).__name__}: {exc}")
    with tempfile.TemporaryDirectory() as td:
        try:
            asyncio.run(t_empty_states_explain_themselves(make_root(td, triage=False, harness=False)))
            print("PASS t_empty_states_explain_themselves")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL t_empty_states_explain_themselves: {type(exc).__name__}: {exc}")
    print(f"{total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
