#!/usr/bin/env python3
"""
Tests for the `setup/configure-git` composite action (issue #507).

The action used to splice `${{ inputs.github-token }}` into its `run:` script
and write the token into ~/.gitconfig as a global `insteadOf` rewrite, where
it sat for every later step of the job. These tests hold the fixed shape:

  * no `${{ inputs.* }}` expression appears inside any `run:` script — inputs
    reach the shell only through `env:` (GitHub's script-injection guidance);
  * the action never runs `git config --global url…`;
  * executing the real authentication step (in a throwaway HOME, with a fake
    GITHUB_ENV) leaves ~/.gitconfig without the token, and the exported
    GIT_CONFIG_* environment makes git resolve the insteadOf rewrite — in the
    superproject AND in a nested repository, which is what a submodule fetch
    from `git submodule update --remote` sees;
  * an existing GIT_CONFIG_COUNT is extended, not clobbered.

Needs PyYAML, bash and git; runs offline:

    python3 .github/scripts/dash-gen/test_configure_git.py
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
ACTION = REPO_ROOT / ".github" / "actions" / "setup" / "configure-git" / "action.yml"
FAKE_TOKEN = "ghs_FAKEtoken1234567890abcdef"
INPUT_EXPR = re.compile(r"\$\{\{\s*inputs\.")


def load_steps() -> list[dict]:
    return yaml.safe_load(ACTION.read_text())["runs"]["steps"]


def render(script: str, step_env: dict, inputs: dict) -> tuple[str, dict]:
    """Substitute `${{ inputs.x }}` the way the runner would — in env: values
    only (the test above guarantees run: carries none)."""
    env = {}
    for key, value in (step_env or {}).items():
        env[key] = re.sub(
            r"\$\{\{\s*inputs\.([\w-]+)\s*\}\}",
            lambda m: inputs[m.group(1)],
            str(value),
        )
    return script, env


def parse_github_env(path: Path) -> dict:
    out = {}
    for line in path.read_text().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            out[key] = value
    return out


class ConfigureGitActionTests(unittest.TestCase):
    def test_no_input_expression_inside_run(self):
        for step in load_steps():
            run = step.get("run", "")
            self.assertIsNone(
                INPUT_EXPR.search(run),
                f"step {step.get('name')!r} expands an input inside run:",
            )

    def test_no_global_url_rewrite(self):
        self.assertNotRegex(ACTION.read_text(), r"config\s+--global\s+url")

    def _auth_step(self) -> dict:
        steps = [s for s in load_steps() if "GIT_AUTH_TOKEN" in str(s.get("env", {}))]
        self.assertEqual(len(steps), 1, "expected exactly one env-fed auth step")
        return steps[0]

    def _run_auth(self, home: Path, extra_env: dict | None = None) -> dict:
        step = self._auth_step()
        script, step_env = render(
            step["run"], step.get("env"), {"github-token": FAKE_TOKEN}
        )
        github_env = home / "github_env"
        github_env.touch()
        work = home / "work"
        work.mkdir()
        subprocess.run(["git", "init", "-q", str(work)], check=True)
        env = {
            "PATH": os.environ["PATH"],
            "HOME": str(home),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GITHUB_ENV": str(github_env),
            "GIT_TERMINAL_PROMPT": "0",
            **step_env,
            **(extra_env or {}),
        }
        result = subprocess.run(
            ["bash", "-e", "-c", script],
            cwd=work, env=env, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return parse_github_env(github_env)

    def test_token_not_written_to_global_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self._run_auth(home)
            gitconfig = home / ".gitconfig"
            text = gitconfig.read_text() if gitconfig.exists() else ""
            self.assertNotIn(FAKE_TOKEN, text)
            self.assertNotIn("insteadOf", text)

    def test_exported_env_rewrites_in_superproject_and_nested_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            exported = self._run_auth(home)
            self.assertEqual(exported.get("GIT_CONFIG_COUNT"), "1")
            nested = home / "work" / "projects" / "sub"
            nested.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(nested)], check=True)
            env = {
                "PATH": os.environ["PATH"],
                "HOME": str(home),
                "GIT_CONFIG_NOSYSTEM": "1",
                **exported,
            }
            want = f"https://x-access-token:{FAKE_TOKEN}@github.com/"
            for repo in (home / "work", nested):
                got = subprocess.run(
                    ["git", "config", "--get", f"url.{want}.insteadOf"],
                    cwd=repo, env=env, capture_output=True, text=True,
                ).stdout.strip()
                self.assertEqual(got, "https://github.com/", repo)

    def test_existing_git_config_count_is_extended(self):
        with tempfile.TemporaryDirectory() as tmp:
            exported = self._run_auth(
                Path(tmp),
                {
                    "GIT_CONFIG_COUNT": "1",
                    "GIT_CONFIG_KEY_0": "core.autocrlf",
                    "GIT_CONFIG_VALUE_0": "false",
                },
            )
            self.assertEqual(exported.get("GIT_CONFIG_COUNT"), "2")
            self.assertIn("GIT_CONFIG_KEY_1", exported)
            self.assertNotIn("GIT_CONFIG_KEY_0", exported)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
