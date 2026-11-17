#!/usr/bin/env python3
"""
Tests for the release-pipeline kit (templates/release-pipeline/) and the tool
that seeds it, tools/adopt-release.sh.

  * the seeded release.yml passes the hub's own UPS-WORK-10 and UPS-QA-40
    checks (no reusable workflow at a branch ref), and the archived 0.1.0 shape
    fails them, which is the bug kit 0.2.0 fixes (bamr87/bashos#97);
  * VERSION, the template's stamp and archive/ agree, and every archived shape
    differs from the template, so an upgrade always changes something;
  * `adopt-release.sh --upgrade --dry-run` refreshes a release.yml that is
    byte-identical to an archived seed, reports a current one, leaves a
    hand-edited one alone and refuses a repo that never adopted;
  * a fresh adoption renders the stamp and the default branch with no
    placeholder left over.

The script runs for real against a local clone: `gh` is a stub on PATH and git
rewrites https://github.com/ to a temporary directory, so nothing touches the
network or GitHub. Stdlib + PyYAML (conformance.py), plus bash, git and jq:

    python3 tools/test_adopt_release.py
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import conformance as c  # noqa: E402

HUB = Path(__file__).resolve().parent.parent
KIT = HUB / "templates" / "release-pipeline"
SCRIPT = HUB / "tools" / "adopt-release.sh"
VERSION_RE = re.compile(r"^version:\s*(\S+)\s*$", re.M)


def kit_version() -> str:
    m = VERSION_RE.search((KIT / "VERSION").read_text(encoding="utf-8"))
    assert m, "templates/release-pipeline/VERSION has no version: line"
    return m.group(1)


def render(path: Path, branch: str = "main", version: str | None = None) -> str:
    """What adopt-release.sh's subst() writes for a repo on `branch`."""
    text = path.read_text(encoding="utf-8")
    return text.replace("__DEFAULT_BRANCH__", branch).replace("__KIT_VERSION__", version or kit_version())


def archived() -> list[Path]:
    return sorted((KIT / "archive").glob("release-*.yml"))


def check(rid: str, release_yml: str):
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        (r / ".github" / "workflows").mkdir(parents=True)
        (r / ".github" / "workflows" / "release.yml").write_text(release_yml, encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(r)], check=True)
        subprocess.run(["git", "-C", str(r), "add", "-A"], check=True)
        return c.CHECKS[rid](c.Repo(r, HUB), ["app"])


class KitTests(unittest.TestCase):
    def test_seed_passes_the_pin_rules(self):
        seed = render(KIT / "release.yml")
        for rid in ("UPS-WORK-10", "UPS-QA-40"):
            ok, msg = check(rid, seed)[:2]
            self.assertTrue(ok, f"{rid}: {msg}")
        self.assertIn("bamr87/.github/.github/workflows/release-please.yml@v1", seed)
        self.assertIn("bamr87/.github/.github/workflows/publish.yml@v1", seed)

    def test_every_reusable_ref_in_the_kit_is_pinned(self):
        for f in sorted(KIT.glob("*.yml")):
            for uses in re.findall(r"^\s*(?:-\s+)?uses:\s*['\"]?([^\s'\"#]+)", f.read_text(encoding="utf-8"), re.M):
                self.assertIsNone(c.unpinned_ref(uses), f"{f.name}: {uses}")

    def test_the_0_1_0_shape_fails_them(self):
        old = render(KIT / "archive" / "release-0.1.0.yml")
        for rid in ("UPS-WORK-10", "UPS-QA-40"):
            ok, msg = check(rid, old)[:2]
            self.assertFalse(ok, rid)
            self.assertIn("release-please", msg)

    def test_version_stamp_and_archive_agree(self):
        v = kit_version()
        self.assertRegex(v, r"^\d+\.\d+\.\d+$")
        tpl = (KIT / "release.yml").read_text(encoding="utf-8")
        self.assertIn("# kit: release-pipeline v__KIT_VERSION__\n", tpl)
        self.assertTrue(archived(), "archive/ holds no release-*.yml snapshot")
        current = tuple(int(x) for x in v.split("."))
        for snap in archived():
            sv = snap.stem.removeprefix("release-")
            self.assertRegex(sv, r"^\d+\.\d+\.\d+$", snap.name)
            self.assertLess(tuple(int(x) for x in sv.split(".")), current, f"{snap.name} is not older than kit v{v}")
            self.assertNotEqual(render(snap, version=sv), render(KIT / "release.yml"), f"{snap.name} equals the template")
            self.assertNotIn("__KIT_VERSION__", snap.read_text(encoding="utf-8"), f"{snap.name}: write the stamp's version out")


def _tools_missing() -> str | None:
    missing = [t for t in ("bash", "git", "jq") if shutil.which(t) is None]
    return f"needs {', '.join(missing)}" if missing else None


@unittest.skipIf(_tools_missing(), _tools_missing() or "")
class ScriptTests(unittest.TestCase):
    """adopt-release.sh end to end, against local repos instead of GitHub."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="adopt-release-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.remotes = self.tmp / "remotes"
        self.work = self.tmp / "work"
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        # `gh repo view <slug>` succeeds; `gh api repos/<slug> --jq .default_branch`
        # prints the branch from the test; anything else (user, pr create) is a
        # test failure, because a dry run must never reach it.
        gh.write_text(
            "#!/usr/bin/env bash\n"
            'if [[ "$1 $2" == "repo view" ]]; then exit 0; fi\n'
            'if [[ "$1" == api && "$2" == repos/* && "$3" == --jq ]]; then echo "${STUB_DEFAULT_BRANCH:-main}"; exit 0; fi\n'
            'echo "stub gh: unexpected call: $*" >&2; exit 99\n',
            encoding="utf-8")
        gh.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "ADOPT_WORKDIR": str(self.work),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": f"url.{self.remotes.as_uri()}/.insteadOf",
            "GIT_CONFIG_VALUE_0": "https://github.com/",
        }

    def remote(self, name: str, files: dict[str, str], branch: str = "main") -> None:
        """A bare repo at what https://github.com/bamr87/<name>.git resolves to."""
        src = self.tmp / "src" / name
        src.mkdir(parents=True)
        for rel, text in files.items():
            (src / rel).parent.mkdir(parents=True, exist_ok=True)
            (src / rel).write_text(text, encoding="utf-8")
        g = ["git", "-c", "core.hooksPath=/dev/null", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
        subprocess.run([*g, "init", "-q", "-b", branch, str(src)], check=True, env=self.env)
        subprocess.run([*g, "-C", str(src), "add", "-A"], check=True, env=self.env)
        subprocess.run([*g, "-C", str(src), "commit", "-q", "-m", "seed"], check=True, env=self.env)
        dest = self.remotes / "bamr87" / f"{name}.git"
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", "--bare", str(src), str(dest)], check=True, env=self.env)

    def adopt(self, name: str, *args: str, branch: str = "main") -> subprocess.CompletedProcess:
        env = {**self.env, "STUB_DEFAULT_BRANCH": branch}
        return subprocess.run(["bash", str(SCRIPT), name, *args], capture_output=True, text=True, env=env, timeout=120)

    def released(self, name: str) -> str:
        return (self.work / name / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    def test_upgrade_refreshes_an_untouched_archived_seed(self):
        for snap in archived():
            sv = snap.stem.removeprefix("release-")
            with self.subTest(snapshot=snap.name):
                name = f"seed-{sv.replace('.', '-')}"
                self.remote(name, {".github/workflows/release.yml": render(snap, "trunk", sv), "README.md": "x\n"}, branch="trunk")
                p = self.adopt(name, "--upgrade", "--dry-run", branch="trunk")
                self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
                self.assertIn(f"upgraded machine seed v{sv} -> kit v{kit_version()}", p.stdout)
                self.assertIn("--dry-run: not pushing", p.stdout)
                self.assertEqual(self.released(name), render(KIT / "release.yml", "trunk"))
                self.assertIn("+    uses: bamr87/.github/.github/workflows/release-please.yml@v1", p.stdout)
                staged = subprocess.run(["git", "-C", str(self.work / name), "diff", "--cached", "--name-only"],
                                        capture_output=True, text=True, env=self.env, check=True).stdout.split()
                self.assertEqual(staged, [".github/workflows/release.yml"])

    def test_upgrade_reports_a_current_seed(self):
        self.remote("current", {".github/workflows/release.yml": render(KIT / "release.yml")})
        p = self.adopt("current", "--upgrade", "--dry-run")
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.assertIn(f"release.yml: current (kit v{kit_version()})", p.stdout)

    def test_upgrade_leaves_a_hand_edited_copy_alone(self):
        edited = render(KIT / "archive" / "release-0.1.0.yml") + "\n  pypi:\n    runs-on: ubuntu-latest\n    steps: [{run: echo}]\n"
        self.remote("edited", {".github/workflows/release.yml": edited})
        p = self.adopt("edited", "--upgrade", "--dry-run")
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.assertIn("hand-modified, left alone (stamp: none)", p.stdout)
        self.assertEqual(self.released("edited"), edited)

    def test_upgrade_refuses_a_repo_that_never_adopted(self):
        self.remote("bare", {"README.md": "x\n"})
        p = self.adopt("bare", "--upgrade", "--dry-run")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("nothing to upgrade", p.stderr)

    def test_adopt_points_an_adopted_repo_at_upgrade(self):
        self.remote("adopted", {".github/workflows/release.yml": render(KIT / "archive" / "release-0.1.0.yml")})
        p = self.adopt("adopted", "--dry-run")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("rerun with --upgrade", p.stderr)

    def test_fresh_adoption_renders_stamp_and_branch(self):
        self.remote("fresh", {"README.md": "x\n"}, branch="trunk")
        p = self.adopt("fresh", "--dry-run", branch="trunk")
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        seeded = self.released("fresh")
        self.assertEqual(seeded, render(KIT / "release.yml", "trunk"))
        self.assertIn(f"# kit: release-pipeline v{kit_version()}\n", seeded)
        self.assertIn("branches: [trunk]", seeded)
        for f in (".github/workflows/release.yml", ".github/workflows/ci.yml", "RELEASING.md"):
            self.assertNotIn("__", (self.work / "fresh" / f).read_text(encoding="utf-8"), f)


if __name__ == "__main__":
    unittest.main(verbosity=1)
