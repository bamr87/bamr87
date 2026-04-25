# GitHub Toolkit

This directory contains the GitHub configuration, reusable automation, templates, and AI guidance used by this monorepo. Keep it focused on assets that are active for this repository or portable to other repositories.

## Contents

| Path | Purpose |
| --- | --- |
| `CODEOWNERS` | Active review ownership for this repository. |
| `CONTRIBUTING.md` | GitHub community-health pointer to the root contribution guide. |
| `dependabot.yml` | Dependency update configuration for GitHub Actions. |
| `workflows/` | Active GitHub Actions workflows. |
| `actions/` | Reusable composite actions and copyable workflow examples. |
| `ISSUE_TEMPLATE/` | GitHub issue forms and markdown issue templates. |
| `pull_request_template.md` | Default GitHub pull request template. |
| `instructions/` | Reusable AI instruction files for development tasks. |
| `prompts/` | Generic task prompts for AI-assisted workflows. |
| `agents/` | Generic agent role definitions and examples. |
| `scripts/` | Helper scripts used by active workflows or reusable examples. |
| `config/` | Parameterized configuration for workflows and tooling. |
| `docs/` | Short reference docs for reusable GitHub patterns. |

## Maintenance Rules

- Keep active GitHub files in GitHub-native locations: `.github/workflows/`, `.github/ISSUE_TEMPLATE/`, `.github/pull_request_template.md`, and `.github/CODEOWNERS`.
- Keep reusable actions framework-agnostic and parameterized through inputs.
- Keep repo-specific ownership, secrets, local paths, and project names out of reusable templates.
- Move historical migration notes and product-specific examples outside the active toolkit unless they are still used.
- Update this README and the relevant subdirectory README when adding, removing, or moving toolkit files.

## Reuse Guidance

When copying this toolkit into another repository, start with `actions/`, `instructions/`, `prompts/`, `templates/`, and selected workflows. Review `CODEOWNERS`, workflow secrets, script environment variables, and content config before enabling automation in the target repository.
