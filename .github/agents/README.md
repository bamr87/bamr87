# Agents

This directory contains reusable agent role definitions. Agent files should describe responsibilities, inputs, outputs, and constraints without hardcoded local paths or repository-specific identities.

## Agent Catalog

| Agent | Purpose |
| --- | --- |
| `code-reviewer.md` | Review changes for correctness, security, maintainability, and tests. |
| `test-writer.md` | Propose or write focused tests for changed behavior. |
| `systematic-debugger.md` | Investigate failures with evidence-driven debugging. |
| `workflow-reviewer.md` | Review GitHub Actions workflows and automation. |
| `prompt-engineer.md` | Improve prompts and AI instructions. |

## Rules

- Keep each agent definition generic enough to copy into another repository.
- Put concrete repository paths and project names in the invoking prompt, not in the agent file.
- Keep examples small and placeholder-based.
- Update this catalog when adding or removing agent definitions.
