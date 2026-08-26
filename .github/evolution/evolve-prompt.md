## Goals

Improve **{{REPO_NAME}}** (`{{NWO}}`, branch `{{BRANCH}}`, category `{{CATEGORY}}`, stack: {{STACK}}) — a `{{STATUS}}` project described in the registry as: _{{DESCRIPTION}}_

Pick the highest-leverage improvements you can make **safely in one pass**, in this order:

1. **Documentation** — fix inaccuracies, broken links, and outdated instructions; make setup and usage match what the code actually does; add the missing docstring, example, or `--help` text a newcomer would need. The README must reflect reality.
2. **Clarity** — rename a confusing identifier, simplify convoluted logic, remove dead code, add a comment only where the code is genuinely non-obvious. Never a formatting sweep.
3. **Functionality** — fix a small, clear bug; add missing error handling; tighten input validation. Add or update a focused test for anything you change.

Let the **signals** above steer where you look: an area with stale PRs or repeated bug reports usually has documentation or clarity debt around it, even though the issues and workflows themselves belong to other loops.

## Method

- Read before you write. Understand the project's purpose, conventions, and test harness first.
- Prefer many small, precise fixes over one rewrite. Each change should be obviously correct to a reviewer who has five minutes.
- Verify. Run the repository's own lint and tests when it has them; if you cannot verify a change, say so in your report rather than assuming.
- Stay in scope. Anything that needs a larger change than this pass allows goes in the **Not done** section of your report, with enough detail that a human could file it.
- Nothing to change is a valid outcome. Say so plainly.
