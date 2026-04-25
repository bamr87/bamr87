# Instructions

This directory contains reusable GitHub Copilot instruction files. Each `*.instructions.md` file should include an `applyTo` frontmatter pattern and focused guidance for that file type or task area.

## Files

| File | Purpose |
| --- | --- |
| `core.instructions.md` | Repository-wide development principles and workflow expectations. |
| `bash.instructions.md` | Bash scripting standards and reusable shell patterns. |
| `development.instructions.md` | General coding, testing, architecture, and container guidance. |
| `documentation.instructions.md` | Markdown, README, tutorial, and API documentation standards. |
| `tools.instructions.md` | Tooling, automation, linting, and development environment guidance. |
| `version-control.instructions.md` | Git, release, changelog, and package publishing guidance. |

## Rules

- Keep this README as the only index for instruction files.
- Keep instruction content reusable across repositories.
- Put repo-specific details in the target repository's root docs, not in shared instruction templates.
- Prefer concise, scoped instructions over broad repeated policy.
