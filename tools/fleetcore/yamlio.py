#!/usr/bin/env python3
"""yamlio — one YAML reader for every surface: libyaml's parser when PyYAML
was built with it, and one parse per version of a file, not one per request.

Every surface used to read the committed signals with `yaml.safe_load`, the
pure-Python loader, each time it was asked. The console's `/api/state` parsed
ten files (1.4 MB) per request, 1.3 s of it, and held the interpreter while it
did, so every request beside it waited too.

    load(path)                  the file parsed, from the cache when this
                                version of it was parsed before
    parse(text)                 yaml.safe_load, with the C parser when present
    stamp(path)                 what "this version" means: (mtime_ns, size,
                                inode), or None when the file is absent
    cached(key, paths, build)   a value derived from files, rebuilt only when
                                one of them changed

A hit hands back its own copy (the parse is kept pickled), so a caller may
change what it gets, as it could with `yaml.safe_load`.

A file modified in the last RACY_NS is parsed and not kept. A filesystem's
timestamps are coarser than two writes in a row can be (Linux stamps a file
from the tick clock), and a second write of the same size inside one tick
would otherwise be served stale for good. This is git's rule for its index.

Standard library + PyYAML, no writes, no subprocess.
"""
from __future__ import annotations

import os
import pickle
import threading
import time
from typing import Any, Callable, Hashable, Iterable

import yaml

# The C parser builds the same objects through the same resolver and
# constructor; only the scanner and parser are libyaml's.
LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
RACY_NS = 2_000_000_000
MAX_ENTRIES = 512

Stamp = tuple[int, int, int]

_LOCK = threading.Lock()
_DOCS: dict[str, tuple[Stamp, bytes]] = {}
_DERIVED: dict[Hashable, tuple[tuple, Any]] = {}


def stamp(path) -> Stamp | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size, st.st_ino)


def _settled(s: Stamp | None) -> bool:
    """Old enough that a later write must move the stamp. An absent file is settled."""
    return s is None or time.time_ns() - s[0] > RACY_NS


def _keep(table: dict, key, entry) -> None:
    with _LOCK:
        if key not in table and len(table) >= MAX_ENTRIES:
            table.pop(next(iter(table)))
        table[key] = entry


def parse(text) -> Any:
    """`yaml.safe_load(text)`. Raises yaml.YAMLError as it does."""
    return yaml.load(text, Loader=LOADER)


def load(path) -> Any:
    """The file as `yaml.safe_load` reads it. Raises OSError when it cannot be
    read and yaml.YAMLError when it does not parse; callers keep their own
    answer to either."""
    key = os.fspath(path)
    before = stamp(key)
    hit = _DOCS.get(key)
    if hit and hit[0] == before:
        return pickle.loads(hit[1])  # our own bytes, never a file's
    with open(key, "rb") as fh:
        doc = parse(fh.read())
    # Kept only when the bytes just parsed are the version the stamp names.
    if before is not None and _settled(before) and stamp(key) == before:
        _keep(_DOCS, key, (before, pickle.dumps(doc, pickle.HIGHEST_PROTOCOL)))
    return doc


def cached(key: Hashable, paths: Iterable, build: Callable[[], Any]) -> Any:
    """`build()`, run again only when one of `paths` changed. The value is
    shared between callers: treat it as read-only, or copy it."""
    files = tuple(os.fspath(p) for p in paths)
    seen = (files, tuple(stamp(f) for f in files))
    hit = _DERIVED.get(key)
    if hit and hit[0] == seen:
        return hit[1]
    value = build()
    if all(_settled(s) for s in seen[1]) and tuple(stamp(f) for f in files) == seen[1]:
        _keep(_DERIVED, key, (seen, value))
    return value


def forget() -> None:
    """Drop everything kept (tests, and a caller that must re-read now)."""
    with _LOCK:
        _DOCS.clear()
        _DERIVED.clear()
