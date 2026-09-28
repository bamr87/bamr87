#!/usr/bin/env python3
"""Terminal twin of the Jekyll command center (index.md + /monitor/).

Reads `_data/projects.yml` + `_data/project_health.yml`. Does not invent a roster.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Header, Input, Static, TabbedContent, TabPane

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fleet as fl  # noqa: E402
import host as dh  # noqa: E402

CAT_CYCLE = (None, *fl.CATEGORIES)
STATUS_CYCLE = (None, *fl.STATUSES)
HEALTH_CYCLE = (None, *fl.LEVELS)


def _fmt(v, empty="—"):
    return empty if v is None else str(v)


class DashTui(App):
    TITLE = "bamr87 · command center"
    CSS = """
    Screen { background: #101418; }
    #kpis { height: 3; color: #e8e4df; padding: 0 1; }
    #banner { height: 1; color: #f59e0b; padding: 0 1; }
    #search { width: 1fr; }
    #meta { width: 36; height: 1fr; border: solid #2a333c; padding: 0 1; }
    DataTable { height: 1fr; }
    .red { color: #ef4444; }
    .amber { color: #f59e0b; }
    .green { color: #22c55e; }
    """
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("slash", "focus_search", "Search", key_display="/"),
        Binding("s", "cycle_sort", "Sort"),
        Binding("c", "cycle_cat", "Category"),
        Binding("t", "cycle_status", "Status"),
        Binding("h", "cycle_health", "Health"),
        Binding("f", "toggle_featured", "Featured"),
        Binding("r", "reload", "Reload YAML"),
        Binding("d", "poll_host", "Docker"),
        Binding("R", "refresh_health", "dash-gen health"),
        Binding("o", "open_repo", "Open repo"),
        Binding("l", "open_live", "Open live"),
    ]

    query: reactive[str] = reactive("")
    category: reactive[str | None] = reactive(None)
    status: reactive[str | None] = reactive(None)
    featured_only: reactive[bool] = reactive(False)
    health_filter: reactive[str | None] = reactive(None)
    sort_key: reactive[str] = reactive("featured")

    def __init__(self, root: Path | None = None) -> None:
        super().__init__()
        self.root = root or ROOT
        self.rows: list[fl.AppRow] = []
        self.health_present = False
        self._selected: str | None = None
        self._refreshing = False
        self.containers: list[dh.Container] = []
        self.host_error: str | None = None
        self._host = dh.docker_host()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="kpis")
        yield Static(id="banner")
        yield Input(placeholder="Search projects, stacks, descriptions…  (/)", id="search")
        with TabbedContent(id="tabs"):
            with TabPane("Apps", id="tab-apps"):
                with Horizontal():
                    yield DataTable(id="apps", cursor_type="row", zebra_stripes=True)
                    yield Static(id="meta")
            with TabPane("Monitor", id="tab-monitor"):
                yield DataTable(id="monitor", cursor_type="row", zebra_stripes=True)
            with TabPane("Attention", id="tab-attn"):
                yield DataTable(id="attn", cursor_type="row", zebra_stripes=True)
            with TabPane("Forge", id="tab-forge"):
                yield DataTable(id="forge", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        apps = self.query_one("#apps", DataTable)
        apps.add_columns(" ", "Name", "Status", "Category", "CI", "Age", "Sec", "Disk", "Forge")
        mon = self.query_one("#monitor", DataTable)
        mon.add_columns(" ", "Repo", "CI", "Activity", "Issues", "PRs", "Sec", "Why")
        attn = self.query_one("#attn", DataTable)
        attn.add_columns(" ", "Repo", "Why")
        forge = self.query_one("#forge", DataTable)
        forge.add_columns("State", "Name", "Project", "Ports")
        self.reload()
        self.set_interval(15, self.action_poll_host)
        self.action_poll_host()
        self.query_one("#apps", DataTable).focus()

    def reload(self) -> None:
        self.rows, self.health_present = fl.join_fleet(self.root)
        dh.attach(self.rows, self.containers)
        self._paint()

    def _visible(self) -> list[fl.AppRow]:
        filtered = fl.filter_rows(
            self.rows,
            q=self.query,
            category=self.category,
            status=self.status,
            featured=True if self.featured_only else None,
            health=self.health_filter,
        )
        return fl.sort_rows(filtered, self.sort_key)

    def _paint(self) -> None:
        k = fl.kpis(self.rows)
        chips = []
        if self.category:
            chips.append(fl.CAT_LABEL.get(self.category, self.category))
        if self.status:
            chips.append(self.status)
        if self.featured_only:
            chips.append("★ featured")
        if self.health_filter:
            chips.append(fl.DOT[self.health_filter])
        chip = ("  [" + " · ".join(chips) + "]") if chips else ""
        self.query_one("#kpis", Static).update(
            f"⛵  {k['projects']} projects  ·  {k['active']} active  ·  "
            f"{k['submodules']} submodules  ·  {k['featured']} featured  ·  "
            f"{k['checked_out']} on disk    "
            f"🔴 {k['red']}  🟠 {k['amber']}  🟢 {k['green']}"
            f"    docker:{sum(1 for r in self.rows if r.docker_running)} up"
            f"    sort:{self.sort_key}{chip}"
        )
        banner = self.query_one("#banner", Static)
        if self.host_error:
            banner.update(f"Forge docker: {self.host_error[:120]}")
        elif not self.health_present:
            banner.update("Health snapshot missing — run dash-gen health  (shift+R). Registry still listed.")
        elif self._refreshing:
            banner.update("Refreshing health from GitHub…")
        elif self._host:
            banner.update(f"Container host {self._host}  ·  {len(self.containers)} containers  ·  d to refresh")
        else:
            banner.update("")

        visible = self._visible()
        apps = self.query_one("#apps", DataTable)
        apps.clear()
        for r in visible:
            ci = "—"
            if r.ci_last == "success":
                ci = f"✅ {_fmt(r.ci_pass)}%"
            elif r.ci_last:
                ci = f"❌ {_fmt(r.ci_pass)}%"
            age = "—" if r.last_commit_days is None else f"{r.last_commit_days}d"
            sec = "—" if not r.security_alerts else str(r.security_alerts)
            disk = "✓" if r.checked_out else ("·" if r.submodule_path else "ext")
            dock = "—"
            if r.docker_running:
                dock = "up"
            elif r.docker_name:
                dock = "down"
            apps.add_row(
                r.dot,
                r.name,
                r.status,
                fl.CAT_LABEL.get(r.category, r.category),
                ci,
                age,
                sec,
                disk,
                dock,
                key=r.name,
            )
        if visible:
            apps.cursor_coordinate = (0, 0)
            self._show_meta(visible[0])
        else:
            self.query_one("#meta", Static).update("No projects match.")

        mon = self.query_one("#monitor", DataTable)
        mon.clear()
        ranked = fl.sort_rows(self.rows, "health")
        for r in ranked:
            if r.health is None:
                continue
            act = "—"
            if r.last_commit_days is not None:
                act = f"{r.last_commit_days}d · {_fmt(r.commits_30d)}/30d"
            ci = f"{'✅' if r.ci_last == 'success' else '❌' if r.ci_last else '—'} {_fmt(r.ci_pass)}%"
            mon.add_row(
                r.dot,
                r.name,
                ci,
                act,
                _fmt(r.issues_open),
                _fmt(r.prs_open),
                "—" if not r.security_alerts else str(r.security_alerts),
                "; ".join(r.reasons) or "—",
                key=f"m:{r.name}",
            )

        attn = self.query_one("#attn", DataTable)
        attn.clear()
        for r in fl.flagged(self.rows):
            attn.add_row(r.dot, r.name, "; ".join(r.reasons), key=f"a:{r.name}")

        forge = self.query_one("#forge", DataTable)
        forge.clear()
        for c in sorted(self.containers, key=lambda x: (not x.running, x.name)):
            forge.add_row(
                "up" if c.running else c.state or "—",
                c.name,
                c.project or "—",
                c.ports or "—",
                key=f"f:{c.name}",
            )

    def _row(self, name: str | None) -> fl.AppRow | None:
        if not name:
            return None
        return next((r for r in self.rows if r.name == name), None)

    def _show_meta(self, r: fl.AppRow) -> None:
        self._selected = r.name
        lines = [
            f"[b]{r.dot} {r.name}[/b]",
            r.description,
            "",
            f"status    {r.status}" + ("  ★" if r.featured else ""),
            f"category  {fl.CAT_LABEL.get(r.category, r.category)}",
            f"stack     {', '.join(r.stack) or '—'}",
            f"disk      {'checked out' if r.checked_out else ('not mounted' if r.submodule_path else 'external')}",
            f"health    {r.health or '—'}",
            f"CI        {_fmt(r.ci_last)}  {_fmt(r.ci_pass)}%",
            f"activity  {_fmt(r.last_commit_days)}d  {_fmt(r.commits_30d)}/30d",
            f"issues    {_fmt(r.issues_open)}    PRs {_fmt(r.prs_open)}",
            f"security  {r.security_alerts}",
            f"stars     {r.stars}",
            f"forge     {r.docker_name or '—'}  {r.docker_status or ''}".rstrip(),
        ]
        if r.reasons:
            lines += ["", "why", *[f"  · {x}" for x in r.reasons]]
        if r.repo_url:
            lines += ["", r.repo_url]
        if r.live_url:
            lines.append(f"live  {r.live_url}")
        self.query_one("#meta", Static).update("\n".join(lines))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            self.query = event.value
            self._paint()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is None:
            return
        name = str(event.row_key.value)
        if name.startswith("f:"):
            return
        if name.startswith(("m:", "a:")):
            name = name.split(":", 1)[1]
        row = self._row(name)
        if row:
            self._show_meta(row)

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_cycle_sort(self) -> None:
        i = fl.SORTS.index(self.sort_key) if self.sort_key in fl.SORTS else 0
        self.sort_key = fl.SORTS[(i + 1) % len(fl.SORTS)]
        self._paint()

    def action_cycle_cat(self) -> None:
        i = CAT_CYCLE.index(self.category) if self.category in CAT_CYCLE else 0
        self.category = CAT_CYCLE[(i + 1) % len(CAT_CYCLE)]
        self._paint()

    def action_cycle_status(self) -> None:
        i = STATUS_CYCLE.index(self.status) if self.status in STATUS_CYCLE else 0
        self.status = STATUS_CYCLE[(i + 1) % len(STATUS_CYCLE)]
        self._paint()

    def action_cycle_health(self) -> None:
        i = HEALTH_CYCLE.index(self.health_filter) if self.health_filter in HEALTH_CYCLE else 0
        self.health_filter = HEALTH_CYCLE[(i + 1) % len(HEALTH_CYCLE)]
        self._paint()

    def action_toggle_featured(self) -> None:
        self.featured_only = not self.featured_only
        self._paint()

    def action_reload(self) -> None:
        self.reload()
        self.notify("Reloaded YAML")

    def action_poll_host(self) -> None:
        host = self._host
        if not host:
            return

        def work() -> None:
            boxes, err = dh.list_containers(host)
            self.call_from_thread(self._host_done, boxes, err)

        threading.Thread(target=work, daemon=True).start()

    def _host_done(self, boxes: list, err: str | None) -> None:
        self.containers = boxes
        self.host_error = err
        dh.attach(self.rows, boxes)
        self._paint()

    def action_refresh_health(self) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        self._paint()
        gen = self.root / "tools" / "dash-gen"

        def work() -> None:
            try:
                r = subprocess.run(
                    [str(gen), "health"],
                    cwd=self.root,
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                ok = r.returncode == 0
                err = (r.stderr or r.stdout or "").strip()[-400:]
            except Exception as exc:  # noqa: BLE001
                ok, err = False, str(exc)
            self.call_from_thread(self._health_done, ok, err)

        threading.Thread(target=work, daemon=True).start()

    def _health_done(self, ok: bool, err: str) -> None:
        self._refreshing = False
        self.reload()
        if ok:
            self.notify("Health refreshed")
        else:
            self.notify(err or "dash-gen health failed", severity="error")

    def action_open_repo(self) -> None:
        row = self._row(self._selected)
        if row and row.repo_url:
            webbrowser.open(row.repo_url)

    def action_open_live(self) -> None:
        row = self._row(self._selected)
        if row and row.live_url:
            webbrowser.open(row.live_url)
        else:
            self.notify("No live_url")


def main() -> None:
    DashTui().run()


if __name__ == "__main__":
    main()
