#!/usr/bin/env python3
"""Terminal twin of the Jekyll command center (index.md, /monitor/, /triage/, /harness/).

Reads the registry plus the dash's committed signals through fleetcore
(`tools/fleetcore/` — the same views the Harness Console serves at /api/fleet),
and live containers through fleetcore.host. Keys come from fleetcore.keys
(keys v1) and colours from fleetcore.theme (the bashOS palette), so this and the
browser console bind the same keys and draw the same levels.

It does not write. Its own subprocesses are `docker ps` and, on demand,
`dash-gen health`; anything else — the Jobs tab and the `:` palette — is a job
SUBMITTED to the console's API, where the allowlist and the confirm-before-write
gate run (fleetcore.client).
"""
from __future__ import annotations

import functools
import re
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

from rich.markup import escape
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Log, Static, TabbedContent, TabPane

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tools/, for fleetcore
from fleetcore import fleet as fl  # noqa: E402
from fleetcore import host as dh  # noqa: E402
from fleetcore import keys as fk  # noqa: E402
from fleetcore import theme as ftheme  # noqa: E402
from fleetcore.client import ConsoleClient, ConsoleError  # noqa: E402

POLL_SECONDS = 15
JOB_POLL_SECONDS = 2
_T = ftheme.TOKENS["dark"]
COLOR = {lv: ftheme.level_color(lv) for lv in fl.LEVELS}
ACCENT, INK2, DIM = _T["primary"], _T["ink2"], _T["muted"]

# keys v1 semantic action → this app's action (fleetcore.keys owns the keys).
KEY_ACTIONS = {
    "quit": "quit", "help": "toggle_help", "palette": "command_palette", "search": "focus_search",
    "back": "back", "down": "cursor(1)", "up": "cursor(-1)", "top": "cursor_edge(0)",
    "bottom": "cursor_edge(1)", "next_tab": "tab_step(1)", "prev_tab": "tab_step(-1)",
    "refresh": "reload", "refresh_full": "refresh_health", "copy": "copy_link",
    "open": "open_repo", "open_live": "open_live", "sort": "cycle_sort",
}


def _binding(k: fk.Key) -> Binding:
    action = f"tab({k.action.split(':')[1]})" if k.action.startswith("tab:") else KEY_ACTIONS[k.action]
    return Binding(k.key, action, k.label, show=k.show, key_display=k.dom if len(k.dom) == 1 else None)
# Row keys carry what the open actions need: Apps rows are the registry name;
# the other tabs prefix theirs (m:/a: name, i:<n>:<url>, h:<id>, d:<host>|<name>).


def _fmt(v, empty="—"):
    return empty if v is None else str(v)


def _plain(v) -> Text:
    """A DataTable cell that is never parsed as Rich markup.

    DataTable runs every `str` cell through Text.from_markup, so an issue
    titled "[bug] …" lost its first word and one containing "[/x]" raised
    MarkupError and took the app down. Anything sourced from GitHub goes here.
    """
    return Text(_fmt(v))


def _clip(v, width: int) -> Text:
    """A plain cell cut to `width`. DataTable columns only ever GROW, so one
    long issue title would otherwise push every column right of it off-screen
    for the rest of the session."""
    s = _fmt(v)
    return Text(s if len(s) <= width else s[: width - 1] + "…")


def _level(level: str | None, label: str | None = None) -> Text:
    dot = fl.DOT.get(level or "", "·")
    t = Text(dot)
    if label:
        t.append(f" {label}", style=COLOR.get(level or "", ""))
    return t


# CSI (colour, cursor) and OSC (titles, hyperlinks) sequences, and a trailing
# one cut off by the poll boundary, which waits for the next chunk.
_ESC = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\-_])")
_ESC_TAIL = re.compile(r"\x1b(?:\[[0-?]*[ -/]*|\][^\x07\x1b]*)?$")


def strip_ansi(buffered: str) -> tuple[str, str]:
    """(printable text, held-back tail). The tools/ scripts colour their output;
    written raw into a Log widget, an escape sequence reaches the terminal
    inside the TUI's own frame and corrupts it."""
    tail = _ESC_TAIL.search(buffered)
    keep = buffered[tail.start():] if tail else ""
    body = buffered[: tail.start()] if tail else buffered
    return _ESC.sub("", body).replace("\r\n", "\n").replace("\r", "\n"), keep


def _age(days: float | None) -> str:
    if days is None:
        return "?"
    if days < 1 / 24:
        return "now"
    if days < 1:
        return f"{round(days * 24)}h"
    return f"{days:.0f}d" if days >= 10 else f"{days:.1f}d"


def _ui(fn):
    """For methods that draw. A Docker poll, a health refresh or a highlight
    queued by the last repaint can all land after quit has started unmounting
    widgets; with nothing left to draw on they do nothing, instead of printing
    a traceback on exit. While the UI is still up, NoMatches is a real bug and
    is raised as usual."""

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        except NoMatches:
            if self.query("#tabs"):
                raise
            return None

    return wrapper


class ConsoleOps(Provider):
    """`:` (or ctrl+p) lists the console's allowlisted operations; picking one
    submits it as a job. Nothing runs here — the console decides."""

    def _hits(self):
        app = self.app
        for op in getattr(app, "ops", None) or []:
            yield op, f"Run: {op['title']}"

    async def discover(self) -> Hits:
        for op, title in self._hits():
            yield DiscoveryHit(title, functools.partial(self.app.run_op, op["id"]), help=op.get("desc") or None)

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for op, title in self._hits():
            score = matcher.match(f"{title} {op['id']} {op.get('group', '')}")
            if score > 0:
                yield Hit(score, matcher.highlight(title), functools.partial(self.app.run_op, op["id"]),
                          help=op.get("desc") or None)


class Confirm(ModalScreen[bool]):
    """Yes/no before a job the console says writes to GitHub or destroys data."""

    BINDINGS = [Binding("escape", "dismiss(False)", "Cancel"), Binding("y", "dismiss(True)", "Yes")]
    DEFAULT_CSS = """
    Confirm { align: center middle; }
    Confirm > Vertical { width: 72; height: auto; border: thick $warning; background: $surface; padding: 1 2; }
    Confirm Horizontal { height: auto; margin-top: 1; }
    Confirm Button { margin-right: 2; }
    """

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(Text(self.message))
            with Horizontal():
                yield Button("Run it (y)", id="yes", variant="warning")
                yield Button("Cancel (esc)", id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


class DashTui(App):
    TITLE = "bamr87 · command center"
    COMMANDS = App.COMMANDS | {ConsoleOps}
    # Focus the table from the first frame. Textual's default focuses the first
    # focusable widget — the search box — so keys typed while the app starts
    # (a fast `7`, a pasted command) became a search filter.
    AUTO_FOCUS = "#apps"
    CSS = """
    Screen { background: $background; }
    #kpis { height: 1; color: $foreground; padding: 0 1; }
    #status { height: 1; padding: 0 1; }
    #search { margin: 0 1; }
    TabbedContent { height: 1fr; }
    TabPane { height: 1fr; padding: 0; }
    #apps-split { height: 1fr; }
    #meta-wrap, #joblog-wrap { width: 44; height: 1fr; border: solid $panel-lighten-1; padding: 0 1; }
    #jobs-split { height: 1fr; }
    #joblog-wrap { width: 1fr; }
    #joblog { height: 1fr; }
    DataTable { height: 1fr; }
    .note { height: auto; color: $warning; padding: 0 1; display: none; }
    .note.-show { display: block; }
    """
    # keys v1 (fleetcore.keys — the same table the browser console binds), then
    # the filters only this terminal view has. `x` is kept as the old name for
    # clearing; `d` cancels a job on the Jobs tab (Docker re-polls on `r` now).
    BINDINGS = [
        *[_binding(k) for k in fk.bindings_for("tui")],
        Binding("c", "cycle_cat", "Category"),
        Binding("t", "cycle_status", "Status"),
        Binding("h", "cycle_health", "Health"),
        Binding("f", "toggle_featured", "Featured"),
        Binding("x", "clear_filters", "Clear", show=False),
        Binding("d", "cancel_job", "Cancel job", show=False),
    ]
    TABS = ("tab-apps", "tab-inbox", "tab-attn", "tab-monitor", "tab-harness", "tab-docker", "tab-jobs")

    def __init__(self, root: Path | None = None, hosts: list[str] | None = None,
                 console: ConsoleClient | None = None) -> None:
        super().__init__()
        self.root = root or ROOT
        # The console runtime the Jobs tab and the palette submit to (not
        # `console`: that is Textual's Rich console). None (the
        # default, and what the tests use) keeps the TUI purely read-only.
        self.runtime = console if console is not None and console.enabled else None
        self.ops: list[dict] = []
        self.jobs: list[dict] = []
        self.console_error: str | None = None
        self._job_id: str | None = None   # the job whose log is shown
        self._job_offset = 0
        self._job_ansi = ""                # an escape sequence split across two polls
        self._job_polling = False
        # Filter state. Plain attributes: `query` in particular must not be an
        # attribute here — it shadows DOMNode.query() and breaks every
        # `app.query(...)` call, Textual's own included.
        self.search = ""
        self.category: str | None = None
        self.status: str | None = None
        self.featured_only = False
        self.health_filter: str | None = None
        self.sort_key = "featured"
        self.repo_filter: str | None = None  # inbox drill-down
        self.snapshot = fl.Snapshot(rows=[], health_present=False, sources=[])
        self._selected: str | None = None
        self._selected_url: str | None = None
        self._refreshing = False
        self._progress = ""
        self._polling = False
        self._mtimes: dict[str, float] = {}
        self.containers: list[dh.Container] = []
        self.host_errors: dict[str, str] = {}
        self._hosts = dh.docker_hosts() if hosts is None else hosts

    @property
    def rows(self) -> list[fl.AppRow]:
        return self.snapshot.rows

    # ------------------------------------------------------------------ layout
    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="kpis")
        yield Static(id="status")
        yield Input(placeholder="Search projects, stacks, issues…  (/ to focus, esc to leave)", id="search", compact=True)
        with TabbedContent(id="tabs"):
            with TabPane("1 Apps", id="tab-apps"):
                with Horizontal(id="apps-split"):
                    yield DataTable(id="apps", cursor_type="row", zebra_stripes=True)
                    with VerticalScroll(id="meta-wrap"):
                        yield Static(id="meta")
            with TabPane("2 Inbox", id="tab-inbox"):
                yield Static(id="inbox-note", classes="note")
                yield DataTable(id="inbox", cursor_type="row", zebra_stripes=True)
            with TabPane("3 Attention", id="tab-attn"):
                yield Static(id="attn-note", classes="note")
                yield DataTable(id="attn", cursor_type="row", zebra_stripes=True)
            with TabPane("4 Monitor", id="tab-monitor"):
                yield Static(id="monitor-note", classes="note")
                yield DataTable(id="monitor", cursor_type="row", zebra_stripes=True)
            with TabPane("5 Harness", id="tab-harness"):
                yield Static(id="harness-note", classes="note")
                yield DataTable(id="harness", cursor_type="row", zebra_stripes=True)
            with TabPane("6 Docker", id="tab-docker"):
                yield Static(id="docker-note", classes="note")
                yield DataTable(id="docker", cursor_type="row", zebra_stripes=True)
            with TabPane("7 Jobs", id="tab-jobs"):
                yield Static(id="jobs-note", classes="note")
                with Horizontal(id="jobs-split"):
                    yield DataTable(id="jobs", cursor_type="row", zebra_stripes=True)
                    with Vertical(id="joblog-wrap"):
                        yield Log(id="joblog", highlight=False)
        yield Footer()

    def on_mount(self) -> None:
        cols = {
            "apps": (" ", "Name", "Status", "Category", "CI", "Age", "Triage", "Iss", "PRs", "Fail", "Sec", "Disk", "Docker"),
            "inbox": ("Pri", "Kind", "Repo", "Title", "Why", "Age"),
            "attn": ("H", "Repo", "Triage", "Why"),
            "monitor": (" ", "Repo", "CI", "Activity", "Issues", "PRs", "Sec", "Why"),
            "harness": (" ", "Signal", "Value", "Detail"),
            "docker": ("Host", "State", "Name", "Project", "Status", "Ports"),
            "jobs": ("Status", "Operation", "Started", "Exit"),
        }
        for table_id, names in cols.items():
            self.query_one(f"#{table_id}", DataTable).add_columns(*names)
        for theme in ftheme.textual_themes():
            self.register_theme(theme)
        self.theme = "bashos-dark"
        self.reload()
        self.set_interval(POLL_SECONDS, self._tick)
        self.set_interval(JOB_POLL_SECONDS, self._poll_jobs)
        self.action_poll_host()
        self._poll_jobs(force=True)
        self.query_one("#apps", DataTable).focus()

    # -------------------------------------------------------------------- data
    def reload(self) -> None:
        self.snapshot = fl.load_snapshot(self.root)
        self._mtimes = fl.data_mtimes(self.root)
        dh.attach(self.rows, self.containers)
        self._paint()

    def _tick(self) -> None:
        """Periodic: re-poll Docker, and reload if a watched file changed on disk
        (a `git pull`, the daily workspace sync, `dash-gen` in another shell)."""
        self.action_poll_host()
        if not self._refreshing and fl.data_mtimes(self.root) != self._mtimes:
            self.reload()
            self.notify("Data changed on disk — reloaded")

    def _visible(self) -> list[fl.AppRow]:
        filtered = fl.filter_rows(
            self.rows,
            q=self.search,
            category=self.category,
            status=self.status,
            featured=True if self.featured_only else None,
            health=self.health_filter,
        )
        return fl.sort_rows(filtered, self.sort_key)

    def _cycle(self, attr: str, preferred: tuple[str, ...]) -> tuple[str | None, ...]:
        return fl.cycle(preferred, {getattr(r, attr) for r in self.rows})

    # ------------------------------------------------------------------- paint
    @_ui
    def _paint(self) -> None:
        self._paint_header()
        self._paint_apps()
        self._paint_inbox()
        self._paint_attn()
        self._paint_monitor()
        self._paint_harness()
        self._paint_docker()
        self._paint_jobs()
        self._sync_selection()

    def _paint_header(self) -> None:
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
        if self.repo_filter:
            chips.append(f"inbox: {self.repo_filter}")
        if self.search:
            chips.append(f"“{self.search}”")
        line = Text(
            f"⛵ {k['projects']} projects · {k['active']} active · {k['submodules']} submodules · "
            f"{k['checked_out']} on disk   health 🔴{k['red']} 🟠{k['amber']} 🟢{k['green']}   "
            f"triage 🔴{k['triage_red']} 🟠{k['triage_amber']} · {k['failing']} failing workflows   "
            f"inbox {len(self.snapshot.inbox)}   sort:{self.sort_key}"
        )
        if chips:
            line.append("  [" + " · ".join(chips) + "]", style=f"bold {ACCENT}")
        self.query_one("#kpis", Static).update(line)
        self.query_one("#status", Static).update(self._status_line())

    def _status_line(self) -> Text:
        t = Text()
        if self._refreshing:
            t.append(f"⟳ dash-gen health {self._progress}  ", style=f"bold {ACCENT}")
        for s in self.snapshot.sources:
            if not s.present:
                style, label = COLOR["red"], f"{s.name} missing"
            elif s.name in fl.UNDATED:
                style, label = INK2, s.name
            elif s.age_days is None:
                style, label = COLOR["amber"], f"{s.name} undated"
            else:
                style = COLOR["amber"] if s.stale else INK2
                label = f"{s.name} {_age(s.age_days)}" + (" STALE" if s.stale else "")
            t.append(label, style=style)
            t.append(" · ", style=DIM)
        if not self.snapshot.health_present and not self._refreshing:
            t.append("R = live health  ", style=COLOR["amber"])
        if self._hosts:
            t.append(" docker ", style=DIM)
            for h in self._hosts:
                label = dh.host_label(h)
                if label in self.host_errors:
                    t.append(f"{label} ✗ ", style=COLOR["red"])
                    continue
                mine = [c for c in self.containers if c.host == label]
                up = sum(1 for c in mine if c.running)
                t.append(f"{label} {up}/{len(mine)} ", style=INK2)
        if self.runtime is not None:
            running = sum(1 for j in self.jobs if j.get("status") in ("queued", "running"))
            if self.console_error:
                t.append(" console ✗", style=COLOR["red"])
            else:
                t.append(f" console ✓ {running} running", style=INK2)
        return t

    def _keep_cursor(self, table: DataTable, key: str | None, fallback_row: int) -> None:
        """Re-seat the cursor after a rebuild: on the same row key if it survived
        the filter, else the same index (clamped). Rebuilding used to snap every
        table to row 0 — on each 15 s Docker poll, mid-navigation."""
        if not table.row_count:
            return
        row = fallback_row
        if key is not None:
            try:
                row = table.get_row_index(key)
            except Exception:  # noqa: BLE001 — RowDoesNotExist: key filtered out
                row = fallback_row
        table.move_cursor(row=max(0, min(row, table.row_count - 1)), animate=False, scroll=True)

    def _rebuild(self, table_id: str, rows: list[tuple], keys: list[str]) -> None:
        table = self.query_one(f"#{table_id}", DataTable)
        prior_row = table.cursor_row
        prior_key = None
        if table.row_count and 0 <= prior_row < table.row_count:
            prior_key = table.coordinate_to_cell_key((prior_row, 0)).row_key.value
        table.clear()
        for cells, key in zip(rows, keys):
            table.add_row(*cells, key=key)
        self._keep_cursor(table, prior_key, prior_row)

    def _note(self, note_id: str, text: str | None) -> None:
        note = self.query_one(f"#{note_id}", Static)
        note.update(text or "")
        note.set_class(bool(text), "-show")

    def _paint_apps(self) -> None:
        visible = self._visible()
        cells, keys = [], []
        for r in visible:
            ci = "—"
            if r.ci_last == "success":
                ci = f"✅ {_fmt(r.ci_pass)}%"
            elif r.ci_last:
                ci = f"❌ {_fmt(r.ci_pass)}%"
            age = "—" if r.last_commit_days is None else f"{r.last_commit_days}d"
            disk = "✓" if r.checked_out else ("·" if r.submodule_path else "ext")
            dock = "—"
            if r.docker_total:
                dock = f"{r.docker_up}/{r.docker_total} up" if r.docker_up else "down"
            cells.append(
                (
                    r.dot,
                    Text(r.name + (" ★" if r.featured else "")),
                    r.status,
                    fl.CAT_LABEL.get(r.category, r.category),
                    ci,
                    age,
                    _level(r.triage_level, _fmt(r.triage_score, "")) if r.triage_level else "—",
                    _fmt(r.triage_issues),
                    _fmt(r.triage_prs),
                    str(len(r.failing)) if r.failing else "—",
                    str(r.security_alerts) if r.security_alerts else "—",
                    disk,
                    dock,
                )
            )
            keys.append(r.name)
        self._rebuild("apps", cells, keys)
        if visible:
            self._show_meta(visible[self.query_one("#apps", DataTable).cursor_row])
        else:
            self.query_one("#meta", Static).update("No projects match.  (x clears filters)")

    def _paint_inbox(self) -> None:
        if self.repo_filter:
            row = self._row(self.repo_filter)
            source = fl.repo_items(self.snapshot.triage, self.repo_filter, row.repo_url if row else "")
        else:
            source = self.snapshot.inbox
        items = fl.filter_inbox(source, q=self.search)
        cells = [
            (
                str(i.priority),
                i.kind,
                _clip(i.repo, 24),
                _clip(i.label, 90),
                _clip(i.why, 32),
                "—" if i.age_days is None else f"{i.age_days}d",
            )
            for i in items
        ]
        # Inbox keys are URLs; two items can share one (a PR is also its own
        # failing check), so the index keeps keys unique.
        self._rebuild("inbox", cells, [f"i:{n}:{i.url}" for n, i in enumerate(items)])
        triage = self.snapshot.source("triage")
        if triage and not triage.present:
            self._note("inbox-note", "No _data/fleet_triage.yml — `tools/dash triage` writes it (fleet-pulse commits it daily).")
        elif self.repo_filter:
            self._note(
                "inbox-note",
                f"All open items for {self.repo_filter} ({len(items)}) — x returns to the fleet inbox · enter opens the item",
            )
        elif not items:
            self._note("inbox-note", "Nothing in the inbox matches.  (x clears filters)")
        else:
            self._note("inbox-note", None)

    def _paint_attn(self) -> None:
        rows = fl.flagged(self.rows)
        cells = [
            (
                r.dot,
                _plain(r.name),
                _level(r.triage_level, _fmt(r.triage_score, "")) if r.triage_level else "—",
                _clip("; ".join([*r.reasons, *r.triage_reasons]) or "—", 140),
            )
            for r in rows
        ]
        self._rebuild("attn", cells, [f"a:{r.name}" for r in rows])
        self._note("attn-note", None if rows else "Nothing red or amber. (Or no health/triage data — see the status line.)")

    def _paint_monitor(self) -> None:
        ranked = [r for r in fl.sort_rows(self.rows, "health") if r.health is not None]
        cells = []
        for r in ranked:
            act = "—"
            if r.last_commit_days is not None:
                act = f"{r.last_commit_days}d · {_fmt(r.commits_30d)}/30d"
            ci = f"{'✅' if r.ci_last == 'success' else '❌' if r.ci_last else '—'} {_fmt(r.ci_pass)}%"
            cells.append(
                (
                    r.dot,
                    _plain(r.name),
                    ci,
                    act,
                    _fmt(r.issues_open),
                    _fmt(r.prs_open),
                    "—" if not r.security_alerts else str(r.security_alerts),
                    _plain("; ".join(r.reasons) or "—"),
                )
            )
        self._rebuild("monitor", cells, [f"m:{r.name}" for r in ranked])
        self._note(
            "monitor-note",
            None if ranked else "No health snapshot (_data/project_health.yml is ephemeral). Press R to run `dash-gen health` (~3 min).",
        )

    def _paint_harness(self) -> None:
        cells, keys = [], []
        for w in self.snapshot.trip_wires:
            tripped = bool(w.get("tripped"))
            cells.append(
                (
                    Text("⚠" if tripped else "✓", style=COLOR["red"] if tripped else COLOR["green"]),
                    _plain(f"wire: {w.get('id', '?')}"),
                    "TRIPPED" if tripped else "ok",
                    _plain(w.get("summary") or ""),
                )
            )
            keys.append(f"h:wire:{w.get('id')}")
        for name, m in self.snapshot.scorecard.items():
            status = m.get("status")
            mark = {"warn": Text("⚠", style=COLOR["amber"]), "ok": Text("✓", style=COLOR["green"])}.get(status, Text("·"))
            # `direction` is the DESIRED direction (harness.build_scorecard),
            # not a trend: "up" means higher is better.
            want = {"up": "want ↑", "down": "want ↓", "steady": "want steady"}.get(m.get("direction"), "")
            detail = "  ".join(x for x in (want, f"threshold {m['threshold']}" if "threshold" in m else "") if x)
            cells.append((mark, _plain(name.replace("_", " ")), _plain(m.get("value")), _plain(detail)))
            keys.append(f"h:score:{name}")
        self._rebuild("harness", cells, keys)
        harness = self.snapshot.source("harness")
        self._note(
            "harness-note",
            None if harness and harness.present else "No _data/harness_health.yml — `tools/dash harness` computes it.",
        )

    def _paint_docker(self) -> None:
        boxes = sorted(self.containers, key=lambda c: (c.host, not c.running, c.name))
        cells = [
            (
                c.host,
                Text("up", style=COLOR["green"]) if c.running else _plain(c.state or "—"),
                _clip(c.name, 40),
                _clip(c.owner or c.fleet_project or c.project or "—", 24),
                _clip(c.status, 28),
                _clip(c.ports or "—", 60),
            )
            for c in boxes
        ]
        self._rebuild("docker", cells, [f"d:{c.host}|{c.name}" for c in boxes])
        if not self._hosts:
            msg = "No Docker endpoints — set DASH_DOCKER_HOST (e.g. local,ssh://forge)."
        elif self.host_errors:
            msg = "  ".join(f"{h}: {e.splitlines()[-1][:140]}" for h, e in self.host_errors.items())
        elif not boxes:
            msg = f"No containers on {', '.join(dh.host_label(h) for h in self._hosts)}.  `tools/dash up` starts the core."
        else:
            msg = None
        self._note("docker-note", msg)

    # ------------------------------------------------------------------ detail
    def _row(self, name: str | None) -> fl.AppRow | None:
        if not name:
            return None
        return next((r for r in self.rows if r.name == name), None)

    @_ui
    def _show_meta(self, r: fl.AppRow) -> None:
        """The Apps detail pane — always the row under the Apps cursor."""
        e = escape
        lines = [
            f"[b]{r.dot} {e(r.name)}[/b]",
            e(r.description),
            "",
            f"status    {e(r.status)}" + ("  ★" if r.featured else ""),
            f"category  {e(fl.CAT_LABEL.get(r.category, r.category))}",
            f"stack     {e(', '.join(r.stack) or '—')}",
            f"disk      {'checked out' if r.checked_out else ('not mounted' if r.submodule_path else 'external')}",
            "",
            f"[b]health[/b]    {r.health or '—'}",
            f"CI        {_fmt(r.ci_last)}  {_fmt(r.ci_pass)}%",
            f"activity  {_fmt(r.last_commit_days)}d  {_fmt(r.commits_30d)}/30d",
            f"issues    {_fmt(r.issues_open)}    PRs {_fmt(r.prs_open)}",
            f"security  {r.security_alerts}    stars {r.stars}",
        ]
        if r.reasons:
            lines += [f"  · {e(x)}" for x in r.reasons]
        lines += [
            "",
            f"[b]triage[/b]    {r.triage_dot} {r.triage_level or '—'}  score {_fmt(r.triage_score)}",
            f"open      {_fmt(r.triage_issues)} issues · {_fmt(r.triage_prs)} PRs",
        ]
        lines += [f"  · {e(x)}" for x in r.triage_reasons]
        if r.failing:
            lines += ["", f"[b]failing workflows[/b] ({len(r.failing)})"]
            lines += [f"  ✗ {e(w)}" for w, _ in r.failing[:8]]
            if len(r.failing) > 8:
                lines.append(f"  … {len(r.failing) - 8} more")
        mine = [c for c in self.containers if c.owner == r.name]
        if mine:
            lines += ["", f"[b]docker[/b]    {r.docker_up}/{r.docker_total} up"]
            lines += [f"  {'●' if c.running else '○'} {e(c.host)}:{e(c.name)}" for c in mine[:8]]
        lines.append("")
        if r.repo_url:
            lines.append(e(r.repo_url))
        if r.live_url:
            lines.append(f"live  {e(r.live_url)}")
        lines += ["", "[dim]o repo · l live · enter: this repo's inbox[/dim]"]
        self.query_one("#meta", Static).update("\n".join(lines))

    # ------------------------------------------------------------------ events
    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            self.search = event.value
            self._paint()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search":
            self._focus_table()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "apps" and event.row_key is not None:
            row = self._row(str(event.row_key.value))
            if row:
                self._show_meta(row)
        # A repaint re-highlights EVERY table, hidden tabs included; only the
        # visible one may move the selection that o / l / enter act on.
        if event.data_table is self._active_table():
            self._sync_selection()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        # DataTable consumes `enter` as row selection, so the drill lives here.
        if event.data_table is self._active_table():
            self._sync_selection()
            self.action_drill()

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        self._sync_selection()
        self._focus_table()

    def _sync_selection(self) -> None:
        """Point the open actions at the row under the visible tab's cursor."""
        self._selected = self._selected_url = None
        table = self._active_table()
        if table is None or not table.row_count:
            return
        key = str(table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value)
        kind, _, rest = key.partition(":") if key[:2] in ("i:", "m:", "a:", "h:", "d:", "j:") else ("", "", key)
        if kind == "i":
            self._selected_url = rest.split(":", 1)[1]
        elif kind == "d":
            host, _, name = rest.partition("|")  # a tcp:// host label has its own colon
            box = next((c for c in self.containers if c.host == host and c.name == name), None)
            self._selected = box.owner if box else None
        elif kind not in ("h", "j"):
            self._selected = rest

    # ----------------------------------------------------------------- actions
    def _active_table(self) -> DataTable | None:
        # Messages queued before shutdown (or before compose) still arrive;
        # with no tabs there is simply no active table. App-level query, not
        # self.screen: that raises ScreenStackError once the stack is empty.
        tabs = self.query("#tabs")
        pane = tabs.first(TabbedContent).active_pane if tabs else None
        return pane.query(DataTable).first() if pane else None

    def _focus_table(self) -> None:
        table = self._active_table()
        if table:
            table.focus()

    def action_tab(self, n: int) -> None:
        if 1 <= n <= len(self.TABS):
            self.query_one("#tabs", TabbedContent).active = self.TABS[n - 1]

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_back(self) -> None:
        """esc, keys v1's one way back: leave the search box, else leave an
        inbox drill-down, else clear the filters."""
        if isinstance(self.focused, Input):
            self._focus_table()
        elif self.repo_filter:
            self.repo_filter = None
            self._paint()
        else:
            self.action_clear_filters()

    def action_tab_step(self, step: int) -> None:
        tabs = self.query_one("#tabs", TabbedContent)
        i = self.TABS.index(tabs.active) if tabs.active in self.TABS else 0
        tabs.active = self.TABS[(i + step) % len(self.TABS)]

    def action_cursor(self, step: int) -> None:
        table = self._active_table()
        if table is not None and table.row_count:
            table.move_cursor(row=max(0, min(table.cursor_row + step, table.row_count - 1)))

    def action_cursor_edge(self, end: int) -> None:
        table = self._active_table()
        if table is not None and table.row_count:
            table.move_cursor(row=table.row_count - 1 if end else 0)

    def action_copy_link(self) -> None:
        """y: the selected row's link to the clipboard (OSC 52 — terminals that
        refuse it still get the link on screen to copy by hand)."""
        url = self._selected_url
        if url is None:
            row = self._row(self._selected)
            url = row.repo_url if row else None
        if not url:
            self.notify("No link on this row")
            return
        self.copy_to_clipboard(url)
        self.notify(url, title="Copied", markup=False)

    def action_toggle_help(self) -> None:
        if self.screen.query("HelpPanel"):
            self.action_hide_help_panel()
        else:
            self.action_show_help_panel()

    def action_cycle_sort(self) -> None:
        i = fl.SORTS.index(self.sort_key) if self.sort_key in fl.SORTS else 0
        self.sort_key = fl.SORTS[(i + 1) % len(fl.SORTS)]
        self._paint()

    def action_cycle_cat(self) -> None:
        values = self._cycle("category", fl.CATEGORIES)
        i = values.index(self.category) if self.category in values else 0
        self.category = values[(i + 1) % len(values)]
        self._paint()

    def action_cycle_status(self) -> None:
        values = self._cycle("status", fl.STATUSES)
        i = values.index(self.status) if self.status in values else 0
        self.status = values[(i + 1) % len(values)]
        self._paint()

    def action_cycle_health(self) -> None:
        values = (None, *fl.LEVELS)
        i = values.index(self.health_filter) if self.health_filter in values else 0
        self.health_filter = values[(i + 1) % len(values)]
        self._paint()

    def action_toggle_featured(self) -> None:
        self.featured_only = not self.featured_only
        self._paint()

    def action_clear_filters(self) -> None:
        self.category = self.status = self.health_filter = self.repo_filter = None
        self.featured_only = False
        self.search = ""
        self.query_one("#search", Input).value = ""
        self._paint()

    def action_drill(self) -> None:
        """Enter: an inbox row opens its URL; any project row opens that
        project's slice of the inbox."""
        table = self._active_table()
        if table is None:
            return
        if table.id == "inbox":
            self._open(self._selected_url)
            return
        if table.id == "jobs":
            self._show_job(self._job_under_cursor())
            return
        if table.id in ("apps", "attn", "monitor") and self._selected:
            self.repo_filter = self._selected
            self.query_one("#tabs", TabbedContent).active = "tab-inbox"
            self._paint()

    def action_reload(self) -> None:
        self.reload()
        self.action_poll_host()
        self._poll_jobs(force=True)
        self.notify("Reloaded")

    def action_poll_host(self) -> None:
        if not self._hosts or self._polling:
            return
        self._polling = True
        hosts = list(self._hosts)

        def work() -> None:
            boxes, errors = dh.list_all(hosts)
            self.call_from_thread(self._host_done, boxes, errors)

        threading.Thread(target=work, daemon=True).start()

    def _host_done(self, boxes: list[dh.Container], errors: dict[str, str]) -> None:
        self._polling = False
        self.containers = boxes
        self.host_errors = errors
        dh.attach(self.rows, boxes)
        self._paint()

    def action_refresh_health(self) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        self._progress = ""
        self._paint()
        gen = self.root / "tools" / "dash-gen"
        total = len(self.rows)

        def work() -> None:
            # dash-gen prints "  · <repo>" per project on stderr and writes the
            # file only at the end (~3 min for the fleet), so progress is read
            # line by line and there is deliberately no wall-clock cap: the old
            # 180 s timeout sat inside the normal runtime and threw away a run
            # that was about to succeed.
            tail: list[str] = []
            done = 0
            try:
                with subprocess.Popen(
                    [str(gen), "health"],
                    cwd=self.root,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                ) as proc:
                    for line in proc.stderr or ():
                        tail = (tail + [line.rstrip()])[-20:]
                        if line.lstrip().startswith("· "):
                            done += 1
                            name = line.strip()[2:]
                            self.call_from_thread(self._health_progress, f"{done}/{total} {name}")
                    ok = proc.wait() == 0
                err = "\n".join(tail)[-400:]
            except Exception as exc:  # noqa: BLE001 — surfaced in the UI
                ok, err = False, str(exc)
            self.call_from_thread(self._health_done, ok, err)

        threading.Thread(target=work, daemon=True).start()

    @_ui
    def _health_progress(self, text: str) -> None:
        self._progress = text
        self.query_one("#status", Static).update(self._status_line())

    def _health_done(self, ok: bool, err: str) -> None:
        self._refreshing = False
        self._progress = ""
        self.reload()
        if ok:
            self.notify("Health refreshed")
        else:
            self.notify(err or "dash-gen health failed", severity="error", timeout=12)

    def _open(self, url: str | None, missing: str = "No URL for this row") -> None:
        if not url:
            self.notify(missing)
        elif not webbrowser.open(url):
            # No browser to hand it to — `tools/dash tui --docker`, or an SSH
            # session. Show the link instead of swallowing the key press.
            self.notify(url, title="No browser here — open the link yourself", markup=False, timeout=20)

    def action_open_repo(self) -> None:
        table = self._active_table()
        if table is not None and table.id == "inbox":
            self._open(self._selected_url)
            return
        row = self._row(self._selected)
        self._open(row.repo_url if row else None)

    def action_open_live(self) -> None:
        row = self._row(self._selected)
        self._open(row.live_url if row else None, missing="No live_url")


    # -------------------------------------------------------------------- jobs
    @_ui
    def _paint_jobs(self) -> None:
        if self.runtime is None:
            self._note("jobs-note", "No console runtime (DASH_CONSOLE_URL is empty). Jobs run in the Harness "
                                    "Console — start it with `tools/dash console`, then reopen this.")
        elif self.console_error:
            self._note("jobs-note", f"Console unreachable at {self.runtime.url}: {self.console_error}")
        else:
            self._note("jobs-note", None if self.jobs else
                       "No jobs yet. `:` lists the console's operations; the browser's Jobs tab shows the same list.")
        cells, keys = [], []
        for j in self.jobs:
            status = j.get("status") or "?"
            style = {"succeeded": COLOR["green"], "failed": COLOR["red"], "running": ACCENT,
                     "cancelled": DIM}.get(status, INK2)
            started = (j.get("started") or j.get("created") or "")[11:19]
            cells.append((Text(status, style=style), _clip(j.get("title") or j.get("op"), 60),
                          _plain(started or "—"), _plain(j.get("exit_code"))))
            keys.append(f"j:{j['id']}")
        self._rebuild("jobs", cells, keys)

    def _job_under_cursor(self) -> str | None:
        table = self.query_one("#jobs", DataTable)
        if not table.row_count:
            return None
        key = str(table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value)
        return key[2:] if key.startswith("j:") else None

    def _show_job(self, job_id: str | None) -> None:
        if not job_id:
            return
        self._job_id, self._job_offset, self._job_ansi = job_id, 0, ""
        self.query_one("#joblog", Log).clear()
        self._poll_jobs(force=True)

    def _poll_jobs(self, force: bool = False) -> None:
        """Every 2 s while the Jobs tab is open or a shown job is still going,
        on a thread — the console is a network call."""
        if self.runtime is None or self._job_polling:
            return
        try:
            on_tab = self.query_one("#tabs", TabbedContent).active == "tab-jobs"
        except NoMatches:
            return
        live = any(j.get("id") == self._job_id and j.get("status") in ("queued", "running") for j in self.jobs)
        if not (force or on_tab or live):
            return
        self._job_polling = True
        job_id, offset, want_ops = self._job_id, self._job_offset, not self.ops

        def work() -> None:
            ops = jobs = tail = None
            err = None
            try:
                jobs = self.runtime.jobs()
                if want_ops:
                    ops = self.runtime.ops()
                if job_id:
                    tail = self.runtime.tail(job_id, offset)
            except ConsoleError as exc:
                err = str(exc)
            self.call_from_thread(self._jobs_done, jobs, ops, tail, err)

        threading.Thread(target=work, daemon=True).start()

    def _jobs_done(self, jobs, ops, tail, err) -> None:
        self._job_polling = False
        self.console_error = err
        if jobs is not None:
            self.jobs = jobs
        if ops is not None:
            self.ops = ops
        if tail and tail.get("job", {}).get("id") == self._job_id:
            text, self._job_ansi = strip_ansi(self._job_ansi + (tail.get("text") or ""))
            if text:
                self.query_one("#joblog", Log).write(text)
            self._job_offset = tail.get("offset", self._job_offset)
        self._paint()

    def run_op(self, op_id: str, confirm: bool = False) -> None:
        """Submit one allowlisted operation. The console answers 409 when the
        operation writes to GitHub (or destroys local data); that becomes a
        yes/no here, and only a yes resubmits with confirm=true."""
        if self.runtime is None:
            self.notify("No console runtime — start it with `tools/dash console`", severity="warning")
            return

        def work() -> None:
            try:
                job = self.runtime.submit(op_id, {}, confirm=confirm)
                self.call_from_thread(self._submitted, job)
            except ConsoleError as exc:
                self.call_from_thread(self._submit_failed, op_id, str(exc), confirm)

        threading.Thread(target=work, daemon=True).start()

    def _submitted(self, job: dict) -> None:
        self.notify(f"Started: {job.get('title') or job.get('op')}")
        self.query_one("#tabs", TabbedContent).active = "tab-jobs"
        self._show_job(job.get("id"))

    def _submit_failed(self, op_id: str, err: str, confirmed: bool) -> None:
        if "confirm" in err and not confirmed:
            self.push_screen(Confirm(f"{op_id}: {err}"),
                             lambda yes: self.run_op(op_id, confirm=True) if yes else None)
        else:
            self.notify(err, title=op_id, severity="error", markup=False, timeout=12)

    def action_cancel_job(self) -> None:
        table = self._active_table()
        if self.runtime is None or table is None or table.id != "jobs":
            return
        job_id = self._job_under_cursor()
        job = next((j for j in self.jobs if j.get("id") == job_id), None)
        if not job or job.get("status") != "running":
            self.notify("Only a running job can be cancelled")
            return

        def go(yes: bool | None) -> None:
            if yes:
                try:
                    self.runtime.cancel(job_id)
                except ConsoleError as exc:
                    self.notify(str(exc), severity="error", markup=False)
                self._poll_jobs(force=True)

        self.push_screen(Confirm(f"Cancel {job.get('title') or job.get('op')}?"), go)


def main() -> None:
    DashTui(console=ConsoleClient.from_env()).run()


if __name__ == "__main__":
    main()
