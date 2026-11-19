#!/usr/bin/env python3
"""Tests for tools/fanout.sh's --upgrade matcher, `machine_seeded` (bamr87/bamr87#829).

`--upgrade` replaces a kit copy only when it is byte-identical to a shape in the
kit's `archive/`. Two gaps left the whole fleet's verify.yml "hand-modified":

- an archive that keeps the `__KIT_VERSION__` placeholder was rendered with the
  CURRENT kit version, so a v0.2.0 seed (stamped v0.2.0) never matched it;
- the 2026-11-15 OAuth-only sweep rewrote one comment in every deployed copy,
  so no copy matched its seed. The `-oauth*` archive variants record those
  shapes, and this test holds every variant to a comment-only difference from
  its base, so an archive can never absorb a behavioural edit.

Offline: sources the two functions out of fanout.sh and runs them in bash. Run:
    python3 tools/test_fanout_upgrade.py
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HUB = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash") or "/bin/bash"
KIT = HUB / "templates" / "verify"
ARCHIVE = KIT / "archive"
TEMPLATE = KIT / "verify.yml"
FUNCTIONS = r"""
eval "$(sed -n '/^render_kit_template()/,/^}/p; /^machine_seeded()/,/^}/p' "$1")"
if machine_seeded "$2" "$3" demo main "$4"; then echo "match ${MATCHED_ARCHIVE##*/}"; else echo "none"; fi
"""


def current_version() -> str:
    for line in (KIT / "VERSION").read_text(encoding="utf-8").splitlines():
        if line.startswith("version:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError("templates/verify/VERSION has no version:")


def render(text: str, version: str, name: str = "demo", branch: str = "main") -> str:
    return (text.replace("__PROJECT_NAME__", name).replace("__DEFAULT_BRANCH__", branch)
            .replace("__KIT_VERSION__", version))


def is_comment(line: str) -> bool:
    return line.lstrip().startswith("#")


class MachineSeeded(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fanout-upgrade-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.version = current_version()

    def match(self, text: str) -> str:
        copy = self.tmp / "verify.yml"
        copy.write_text(text, encoding="utf-8")
        proc = subprocess.run([BASH, "-c", FUNCTIONS, "test", str(HUB / "tools" / "fanout.sh"),
                               str(copy), str(TEMPLATE), self.version],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout.strip()

    def archives(self):
        found = sorted(ARCHIVE.glob("verify-*.yml"))
        self.assertTrue(found)
        return found

    @staticmethod
    def archive_version(path: Path) -> str:
        return path.stem[len("verify-"):].split("-", 1)[0]

    def test_placeholder_archive_matches_the_version_it_seeded(self):
        """A v0.2.0 seed reads `# kit: verify v0.2.0`, not the current version."""
        archived = (ARCHIVE / "verify-0.2.0.yml").read_text(encoding="utf-8")
        self.assertIn("__KIT_VERSION__", archived)
        seeded = render(archived, "0.2.0")
        self.assertIn("# kit: verify v0.2.0\n", seeded)
        self.assertEqual(self.match(seeded), "match verify-0.2.0.yml")

    def test_every_archived_shape_rendered_at_its_version_is_upgradeable(self):
        for path in self.archives():
            with self.subTest(archive=path.name):
                seeded = render(path.read_text(encoding="utf-8"), self.archive_version(path))
                self.assertEqual(self.match(seeded), f"match {path.name}")

    def test_rendering_at_the_current_version_still_matches(self):
        """The old behaviour stays: a placeholder archive rendered at the current version."""
        archived = (ARCHIVE / "verify-0.2.0.yml").read_text(encoding="utf-8")
        self.assertEqual(self.match(render(archived, self.version)), "match verify-0.2.0.yml")

    def test_a_behavioural_edit_is_never_upgradeable(self):
        for path in self.archives():
            with self.subTest(archive=path.name):
                seeded = render(path.read_text(encoding="utf-8"), self.archive_version(path))
                edited = seeded.replace("gate: false", "gate: true", 1)
                self.assertNotEqual(edited, seeded)
                self.assertEqual(self.match(edited), "none")

    def test_variants_differ_from_their_base_only_in_comments(self):
        variants = [p for p in self.archives() if "-" in p.stem[len("verify-"):]]
        self.assertTrue(variants, "the -oauth* variants are archived")
        for path in variants:
            base = ARCHIVE / f"verify-{self.archive_version(path)}.yml"
            with self.subTest(variant=path.name):
                ours = [line for line in path.read_text(encoding="utf-8").splitlines()
                        if not is_comment(line)]
                theirs = [line for line in base.read_text(encoding="utf-8").splitlines()
                          if not is_comment(line)]
                self.assertEqual(ours, theirs)

    def test_archive_names_carry_a_version(self):
        for path in self.archives():
            with self.subTest(archive=path.name):
                self.assertRegex(self.archive_version(path), re.compile(r"^\d+\.\d+\.\d+$"))


if __name__ == "__main__":
    unittest.main()
