"""keys v1 — one keymap for the terminal dash and the browser console.

The table is the contract from docs/TERMINAL-FRAMEWORK.md §6.1: single keys
every popular terminal app shares (q ? : / j k g G ] [ y), measured against
what chui's Zellij, VS Code's terminal and tmux take first. Each surface maps
the semantic `action` onto its own handler:

  TUI      tools/tui/app.py builds Textual Bindings from bindings_for("tui")
  browser  tools/console serves the table at /api/keys; index.html binds the
           same keys and renders the same `?` help sheet from it

A key that one surface cannot honour (the browser has no "quit") is limited
with `surfaces`; nothing else differs. Change a key here and both follow.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

SURFACES = ("tui", "web")


@dataclass(frozen=True)
class Key:
    key: str                 # Textual key name
    dom: str                 # KeyboardEvent.key in the browser
    action: str              # semantic action id each surface maps
    label: str
    group: str = "universal"  # universal | dash
    show: bool = True        # in the TUI footer / first in the help sheet
    surfaces: tuple[str, ...] = SURFACES


KEYS: tuple[Key, ...] = (
    # universal — the same in every bashOS app
    Key("q", "q", "quit", "Quit", surfaces=("tui",)),
    Key("question_mark", "?", "help", "Keys"),
    Key("colon", ":", "palette", "Commands"),
    Key("slash", "/", "search", "Search"),
    Key("escape", "Escape", "back", "Back / clear", show=False),
    Key("j", "j", "down", "Down", show=False),
    Key("k", "k", "up", "Up", show=False),
    Key("g", "g", "top", "Top", show=False),
    Key("G", "G", "bottom", "Bottom", show=False),
    Key("right_square_bracket", "]", "next_tab", "Next tab", show=False),
    Key("left_square_bracket", "[", "prev_tab", "Previous tab", show=False),
    *(Key(str(n), str(n), f"tab:{n}", f"Tab {n}", show=False) for n in range(1, 10)),
    Key("r", "r", "refresh", "Refresh"),
    Key("R", "R", "refresh_full", "Full refresh"),
    Key("y", "y", "copy", "Copy link"),
    Key("o", "o", "open", "Open"),
    # dash — the fleet views both surfaces share
    Key("l", "l", "open_live", "Live site", group="dash"),
    Key("s", "s", "sort", "Sort", group="dash"),
)


def bindings_for(surface: str) -> list[Key]:
    if surface not in SURFACES:
        raise ValueError(f"unknown surface {surface!r}")
    return [k for k in KEYS if surface in k.surfaces]


def as_json(surface: str = "web") -> list[dict]:
    return [{**asdict(k), "surfaces": list(k.surfaces)} for k in bindings_for(surface)]
