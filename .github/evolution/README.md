# `.github/evolution/` — per-repo AI evolution prompts

Shared, version-controlled prompt material for the **per-repo evolution framework**
(`.github/workflows/evolution-scheduler.yml` → `repo-evolution.yml`). The same prompt is
reused by the `/evolve-project` skill so manual and automated runs behave identically.

| File | Purpose |
|------|---------|
| `evolve-prompt.md` | Base prompt: goals (documentation, functionality, clarity) + guardrails. Contains `{{PLACEHOLDER}}` tokens filled in per run. |
| `categories/docs.md` | Extra emphasis appended for `category: docs` repos. |
| `categories/full-stack-ai.md` | Extra emphasis for `category: full-stack-ai` repos. |
| `categories/dev-tools.md` | Extra emphasis for `category: dev-tools` repos. |

## How the prompt is assembled

```
evolve-prompt.md  (with {{REPO_NAME}}, {{BRANCH}}, {{CATEGORY}}, {{STACK}} substituted)
        +
categories/<category>.md
```

`repo-evolution.yml` performs the substitution and concatenation, then passes the result to
`anthropics/claude-code-action`. Placeholders:

| Token | Source |
|-------|--------|
| `{{REPO_NAME}}` | registry `name` |
| `{{BRANCH}}` | registry `branch` |
| `{{CATEGORY}}` | registry `category` |
| `{{STACK}}` | registry `stack` (comma-joined) |

## Changing behavior

- **Tune what every run does** → edit `evolve-prompt.md`.
- **Tune a category** → edit the matching `categories/*.md`.
- **Add/remove a target repo** → set `auto_evolve: true|false` in `dash/_data/projects.yml`
  (NOT here). See [`docs/EVOLUTION.md`](../../docs/EVOLUTION.md).

All changes are surgical and draft-PR only — see the guardrails in `evolve-prompt.md`.
