#!/usr/bin/env python3
"""Tests for tools/fleetcore/yamlio.py — the one YAML reader the surfaces share:
the same objects `yaml.safe_load` builds, one parse per version of a file, a
private copy per caller, and never a stale answer for a file that just changed.
Offline, no pytest:  python3 tools/test_fleetcore_yamlio.py"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fleetcore import yamlio  # noqa: E402

HUB = Path(__file__).resolve().parent.parent

DOC = """\
generated_at: 2026-11-09 03:24 UTC
day: 2026-11-09
when: 2026-11-09T03:24:00Z
defaults: &defaults {cap: 30, on: true, ratio: 0.5, none: ~}
loops:
  - {name: pulse, <<: *defaults}
  - {name: scout, <<: *defaults, cap: 4}
text: |
  two lines
  of prose — with a dash
octal_looking: 0755
"""


def write(path: Path, text: str, age: float = 60.0) -> None:
    """Write `text` and date it `age` seconds ago: a file touched within
    RACY_NS is never kept, so a test of the cache needs a settled one."""
    path.write_text(text, encoding="utf-8")
    past = time.time() - age
    os.utime(path, (past, past))


class Parses(unittest.TestCase):
    def setUp(self):
        yamlio.forget()
        self.calls = 0
        real = yamlio.parse

        def counting(text):
            self.calls += 1
            return real(text)

        yamlio.parse = counting
        self.addCleanup(setattr, yamlio, "parse", real)
        self.tmp = Path(tempfile.mkdtemp(prefix="yamlio-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)


class Load(Parses):
    def test_builds_what_safe_load_builds(self):
        f = self.tmp / "doc.yml"
        write(f, DOC)
        want = yaml.safe_load(DOC)
        self.assertEqual(yamlio.load(f), want)
        self.assertEqual(yamlio.load(f), want, "the kept copy differs from the parse")
        self.assertEqual(yamlio.load(str(f)), want, "a str path reads the same file")

    def test_one_parse_per_version_of_a_file(self):
        f = self.tmp / "doc.yml"
        write(f, DOC)
        for _ in range(5):
            yamlio.load(f)
        self.assertEqual(self.calls, 1)
        write(f, DOC + "added: 1\n", age=30)
        self.assertEqual(yamlio.load(f)["added"], 1, "a changed file must be read again")
        yamlio.load(f)
        self.assertEqual(self.calls, 2)

    def test_each_caller_gets_its_own_copy(self):
        f = self.tmp / "doc.yml"
        write(f, DOC)
        first = yamlio.load(f)
        first["loops"].clear()
        first["defaults"]["cap"] = -1
        again = yamlio.load(f)
        self.assertEqual([loop["name"] for loop in again["loops"]], ["pulse", "scout"])
        self.assertEqual(again["defaults"]["cap"], 30)

    def test_a_file_that_just_changed_is_never_kept(self):
        # Two writes of the same size inside one timestamp tick leave the stamp
        # where it was. Restoring the first write's mtime is that case exactly.
        f = self.tmp / "doc.yml"
        f.write_text("cap: 1\n", encoding="utf-8")
        st = os.stat(f)
        self.assertEqual(yamlio.load(f), {"cap": 1})
        f.write_text("cap: 2\n", encoding="utf-8")
        os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))
        self.assertEqual(yamlio.stamp(f), (st.st_mtime_ns, st.st_size, st.st_ino))
        self.assertEqual(yamlio.load(f), {"cap": 2}, "served a stale parse of a file written a moment ago")

    def test_a_replaced_file_is_read_again_even_at_the_same_time_and_size(self):
        f = self.tmp / "doc.yml"
        write(f, "cap: 1\n")
        st = os.stat(f)
        self.assertEqual(yamlio.load(f), {"cap": 1})
        new = self.tmp / "doc.yml.tmp"
        new.write_text("cap: 2\n", encoding="utf-8")
        os.utime(new, ns=(st.st_atime_ns, st.st_mtime_ns))
        os.replace(new, f)  # how the console's own writers save
        self.assertEqual(yamlio.load(f), {"cap": 2})

    def test_errors_are_the_callers_to_answer(self):
        with self.assertRaises(OSError):
            yamlio.load(self.tmp / "absent.yml")
        with self.assertRaises(OSError):
            yamlio.load(self.tmp)
        bad = self.tmp / "bad.yml"
        write(bad, "a: [1, 2\nb: }\n")
        for _ in range(2):  # a file that does not parse is not kept either
            with self.assertRaises(yaml.YAMLError):
                yamlio.load(bad)
        self.assertEqual(yamlio.load(self._empty()), None)

    def _empty(self) -> Path:
        f = self.tmp / "empty.yml"
        write(f, "")
        return f

    def test_the_table_is_bounded(self):
        saved, yamlio.MAX_ENTRIES = yamlio.MAX_ENTRIES, 3
        self.addCleanup(setattr, yamlio, "MAX_ENTRIES", saved)
        for i in range(6):
            write(self.tmp / f"{i}.yml", f"n: {i}\n")
            yamlio.load(self.tmp / f"{i}.yml")
        self.assertEqual(len(yamlio._DOCS), 3)
        self.assertEqual(yamlio.load(self.tmp / "0.yml"), {"n": 0}, "an evicted file is simply parsed again")


class Cached(Parses):
    def test_rebuilds_only_when_a_file_changed(self):
        a, b = self.tmp / "a.yml", self.tmp / "b.yml"
        write(a, "n: 1\n")
        built = []

        def build():
            built.append(1)
            return (yamlio.load(a) or {}).get("n"), b.exists()

        for _ in range(4):
            self.assertEqual(yamlio.cached("k", (a, b), build), (1, False))
        self.assertEqual(len(built), 1)
        write(b, "x: 1\n")  # a file that was absent appears
        self.assertEqual(yamlio.cached("k", (a, b), build), (1, True))
        write(a, "n: 2\n", age=30)
        self.assertEqual(yamlio.cached("k", (a, b), build), (2, True))
        self.assertEqual(len(built), 3)

    def test_the_same_key_over_other_files_is_another_value(self):
        a, b = self.tmp / "a.yml", self.tmp / "b.yml"
        write(a, "n: 1\n")
        write(b, "n: 2\n")
        self.assertEqual(yamlio.cached("k", (a,), lambda: yamlio.load(a)["n"]), 1)
        self.assertEqual(yamlio.cached("k", (b,), lambda: yamlio.load(b)["n"]), 2)

    def test_a_value_built_from_a_file_that_just_changed_is_not_kept(self):
        a = self.tmp / "a.yml"
        a.write_text("n: 1\n", encoding="utf-8")
        built = []
        for _ in range(2):
            yamlio.cached("k", (a,), lambda: built.append(1))
        self.assertEqual(len(built), 2)

    def test_a_build_that_raises_is_not_kept(self):
        a = self.tmp / "a.yml"
        write(a, "n: 1\n")

        def boom():
            raise ValueError("no")

        with self.assertRaises(ValueError):
            yamlio.cached("k", (a,), boom)
        self.assertEqual(yamlio.cached("k", (a,), lambda: 7), 7)


class Hub(unittest.TestCase):
    def test_the_hubs_own_signals_read_the_same_either_way(self):
        """The C parser and the kept copy against yaml.safe_load, on the files
        the console reads on every request."""
        yamlio.forget()
        for name in ("fleet.yml", "projects.yml", "ports.yml", "harness_health.yml", "token_rotation.yml"):
            f = HUB / "_data" / name
            if not f.is_file():
                continue
            want = yaml.safe_load(f.read_text(encoding="utf-8"))
            self.assertEqual(yamlio.load(f), want, name)
            self.assertEqual(yamlio.load(f), want, f"{name} (kept copy)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
