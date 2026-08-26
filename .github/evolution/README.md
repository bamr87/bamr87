# `.github/evolution/` — the repo-evolution brief

Version-controlled prompt material for the weekly **per-repo evolution loop** ([`repo-evolution.yml`](../workflows/repo-evolution.yml), documented in [`docs/EVOLUTION.md`](../../docs/EVOLUTION.md)). These files are the *tunable* half of what the agent reads; the *hard rules* (draft-only, surgical, the lane boundaries with the other loops) live in the workflow's prompt so that a prompt edit here can never loosen them.

| File | Purpose |
| --- | --- |
| `evolve-prompt.md` | Goals in priority order (documentation → clarity → functionality) and the working method. Contains `{{PLACEHOLDER}}` tokens filled per repository. |
| `categories/docs.md` | Emphasis appended for `category: docs` repositories. |
| `categories/full-stack-ai.md` | Emphasis for `category: full-stack-ai`. |
| `categories/dev-tools.md` | Emphasis for `category: dev-tools`. |

## How the brief is assembled

[`dash-gen targets`](../scripts/dash-gen/evolution.py) — the deterministic `plan` job — writes one `evolution-workorders/evolution-workorder-<name>.md` per selected repository:

```text
<!-- repo-evolution key="owner/repo" -->      ← hidden dedupe marker (first line; copied into the PR body)
# Evolution brief — <name>
## Repository        ← registry facts (upstream, branch, category, stack, status, description)
## Signals           ← the fleet's current view from _data/fleet_triage.yml:
                       attention, failing workflows, open issues, open PRs
## Focus for this run← the dispatch `focus` input, if any
<evolve-prompt.md>   ← rendered goals + method
<categories/<category>.md>
```

The workflow uploads the briefs as the `evolution-workorders` artifact, and each matrix job downloads its own into `.evolution/` inside the target checkout (git-excluded, so it can never be committed there). The agent is told to read it first.

Placeholders rendered into `evolve-prompt.md` and the category file:

| Token | Source |
| --- | --- |
| `{{REPO_NAME}}` | registry `name` |
| `{{NWO}}` | `owner/repo` derived from `repo_url` |
| `{{BRANCH}}` | registry `branch` |
| `{{CATEGORY}}` | registry `category` |
| `{{STACK}}` | registry `stack`, comma-joined |
| `{{DESCRIPTION}}` | registry `description` |
| `{{STATUS}}` | registry `status` |

A missing category file is not an error — the brief says so and the general goals apply.

## Changing behaviour

- **What every pass does** → edit `evolve-prompt.md`. Preview the result with `tools/dash gen targets --no-dedupe` and read `evolution-workorders/`.
- **One category** → edit the matching `categories/*.md`.
- **Which repos, how many, how often** → `_data/projects.yml` (`auto_evolve: true`) and `_data/fleet.yml` (`schedule.repo_evolution`, `evolution:`), **not** here.
- **The rules** → the `prompt:` in `repo-evolution.yml`, guarded by `test_evolution.py`.

The manual [`/evolve-project`](../../.claude/skills/evolve-project/SKILL.md) skill reads the same goals file, so a local pass and the scheduled one aim at the same things.
