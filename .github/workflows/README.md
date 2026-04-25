# Workflows

This directory contains active GitHub Actions workflows for the monorepo. Keep workflow files here only when they are enabled for this repository or intentionally reusable as a workflow template.

## Active Workflows

| Workflow | Purpose |
| --- | --- |
| `unified-cicd.yml` | Detects project types and runs CI/build/deploy jobs based on trigger mode. |
| `unified-release.yml` | Provides manual and tag-driven release automation. |
| `unified-maintenance.yml` | Runs scheduled or manual maintenance checks. |
| `unified-evolution.yml` | Optional manual AI-assisted repository evolution workflow. |
| `workflow-dispatcher.yml` | Dispatches selected workflows based on repository events. |
| `build-docs.yml` | Builds documentation for the monorepo docs stack. |
| `update-submodules.yml` | Updates one or all Git submodules and opens a pull request. |

## Standards

- Prefer one workflow per durable responsibility.
- Use `workflow_dispatch` inputs for reusable behavior instead of copying near-duplicate workflows.
- Keep repository-specific paths, secrets, and service names documented in the workflow itself.
- Avoid scheduled write-capable workflows unless the repository owner has confirmed the required permissions and secrets.
- Update this README when adding, removing, or renaming workflows.

## Validation

After editing workflow files, run YAML validation and `actionlint` when available. At minimum, check that referenced local actions and scripts exist.
