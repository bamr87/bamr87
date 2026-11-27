#!/usr/bin/env python3
"""Versioned GitHub-hosted runner labels: the runner half of the always-latest policy.

`runs-on: ubuntu-latest` moves with GitHub's newest image; `runs-on: ubuntu-24.04`
never moves again, so a workflow pinned that way keeps testing an image the rest
of the fleet has left (docs/DEPENDENCIES.md). zer0-CMS#109 pinned one to keep a
Python 3.9 leg alive after `ubuntu-latest` became 26.04; the owner raised the
floor instead (zer0-CMS#110), and nothing in the hub would have caught the pin.

A label is a pin when it names an image version and the same runner has a
floating alias:

    ubuntu-NN.NN          -> ubuntu-latest
    macos-NN              -> macos-latest
    macos-NN-large        -> macos-latest-large
    macos-NN-xlarge       -> macos-latest-xlarge
    windows-NNNN          -> windows-latest

Labels with no floating alias (`ubuntu-24.04-arm`, `macos-15-intel`,
`windows-11-arm`) and self-hosted labels are left alone: a check that cannot
name the fix only teaches people to stop reading it.

Where it looks: the value of any YAML key or list item in a workflow that is
exactly a label, a quoted label, an inline list holding one, or a quoted label
inside a `${{ }}` default. That covers `runs-on:`, matrix values (`os:` lists,
`include:` entries) and reusable-workflow input defaults, without flagging a job
`name:` that mentions an image in prose. Block scalars (`run: |`) are skipped.

A deliberate pin carries `fleet-pin` in a comment on its line or on the line
directly above it, with the reason, e.g.
`runs-on: macos-14  # fleet-pin: the last image with Xcode 15`.

Used by tools/check-drift.sh (j) (the hub's own workflows and seed templates,
gating) and (k) (every fleet repo, advisory), and by tools/unpin-deps.sh, which
floats a scalar `runs-on:` and reports the rest as follow-ups.

CLI: python3 tools/runner_pins.py FILE...   prints `path:line: label`, exit 1 if any.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass

MARKER = "fleet-pin"

# (versioned pattern, floating alias)
_FAMILIES = (
    (re.compile(r"ubuntu-\d{2}\.\d{2}"), "ubuntu-latest"),
    (re.compile(r"macos-\d{2}"), "macos-latest"),
    (re.compile(r"macos-\d{2}-large"), "macos-latest-large"),
    (re.compile(r"macos-\d{2}-xlarge"), "macos-latest-xlarge"),
    (re.compile(r"windows-\d{4}"), "windows-latest"),
)

_KEY_VALUE = re.compile(r"^(\s*)(?:-\s+)?(?:(['\"]?)([\w.-]+)\2\s*:)?\s*(.*)$")
_BLOCK_SCALAR = re.compile(r"^(\s*)(?:-\s+)?[\w.-]+\s*:\s*[|>][-+0-9]*\s*(?:#.*)?$")
_QUOTED = re.compile(r"""['"]([^'"]+)['"]""")


@dataclass(frozen=True)
class Pin:
    line: int        # 1-based
    label: str
    key: str         # the YAML key the value sits under ('' for a bare list item)
    alias: str       # the floating label to use instead


def floating_alias(label: str) -> str | None:
    """The floating label for a versioned one, or None when `label` is not a pin."""
    for pattern, alias in _FAMILIES:
        if pattern.fullmatch(label):
            return alias
    return None


def _strip_comment(line: str) -> tuple[str, str]:
    """(code, comment): a `#` starts a comment at the line start or after whitespace."""
    m = re.search(r"(^|\s)#", line)
    if not m:
        return line, ""
    return line[: m.start()], line[m.start():]


def _candidates(value: str) -> list[str]:
    value = value.strip()
    if not value:
        return []
    if value.startswith("${{"):
        return _QUOTED.findall(value)
    if value.startswith("[") and value.endswith("]"):
        return [v.strip().strip("'\"") for v in value[1:-1].split(",")]
    return [value.strip("'\"")]


def scan(text: str) -> list[Pin]:
    """Every versioned runner label in workflow YAML `text` not marked `fleet-pin`."""
    pins: list[Pin] = []
    lines = text.splitlines()
    block_indent: int | None = None
    for i, raw in enumerate(lines):
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip())
        if block_indent is not None:
            if indent > block_indent:
                continue
            block_indent = None
        bm = _BLOCK_SCALAR.match(raw)
        if bm:
            block_indent = len(bm.group(1))
            continue
        code, comment = _strip_comment(raw)
        if not code.strip():
            continue
        m = _KEY_VALUE.match(code)
        if not m:
            continue
        key = m.group(3) or ""
        for label in _candidates(m.group(4)):
            alias = floating_alias(label)
            if not alias:
                continue
            above = lines[i - 1].strip() if i else ""
            if MARKER in comment or (above.startswith("#") and MARKER in above):
                continue
            pins.append(Pin(i + 1, label, key, alias))
    return pins


def float_runs_on(text: str) -> tuple[str, list[Pin]]:
    """Rewrite each unmarked scalar `runs-on: <versioned>` to its floating alias.

    Returns (new text, the pins it could not rewrite: matrix values, lists,
    input defaults), which a person decides, since floating a matrix that lists
    two images on purpose would collapse it."""
    lines = text.splitlines(keepends=True)
    left: list[Pin] = []
    for pin in scan(text):
        line = lines[pin.line - 1]
        code, comment = _strip_comment(line.rstrip("\n"))
        m = _KEY_VALUE.match(code)
        value = (m.group(4) if m else "").strip().strip("'\"")
        if pin.key == "runs-on" and value == pin.label:
            new = re.sub(rf"(?<![\w.-]){re.escape(pin.label)}(?![\w.-])", pin.alias, code, count=1)
            lines[pin.line - 1] = new + comment + ("\n" if line.endswith("\n") else "")
        else:
            left.append(pin)
    return "".join(lines), left


def main(argv: list[str]) -> int:
    found = 0
    for path in argv:
        try:
            text = open(path, encoding="utf-8").read()
        except (OSError, UnicodeDecodeError) as exc:
            print(f"{path}: unreadable ({exc})", file=sys.stderr)
            continue
        for pin in scan(text):
            found += 1
            print(f"{path}:{pin.line}: `{pin.label}` is a versioned runner — use {pin.alias}, or mark a deliberate pin `# {MARKER}: <reason>`")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
