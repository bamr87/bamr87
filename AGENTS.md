<!-- Adapted from: skills/Agents.md (microsoft/skills submodule) -->

# Agent Principles

Guidelines for AI coding agents working in the bamr87 monorepo — a multi-project workspace spanning a CV Builder (React/TypeScript), documentation hub (MkDocs/Jekyll), automation scripts (Bash/Python), and shared tooling.

## ⚠️ Fresh Information First

**Dependencies and APIs change constantly. Never work with stale knowledge.**

Before implementing anything:

1. **Check existing patterns first** — Read the relevant README.md and instruction files in `.github/instructions/`
2. **Verify package versions** — Check `package.json`, `requirements*.txt`, or `Gemfile` for installed versions
3. **Don't trust cached knowledge** — Your training data may be outdated. Verify against what's actually in the repo.

```
# Always do this first
1. Read the README.md in the working directory
2. Check .github/instructions/ for applicable guidelines
3. Verify against actual installed package versions
```

**If you skip this step and use outdated patterns, you will produce broken code.**

---

## Core Principles

These principles reduce common LLM coding mistakes. Apply them to every task.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

- State assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

**The test:** Would a senior engineer say this is overcomplicated? If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

**The test:** Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution (TDD)

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:

| Instead of... | Transform to... |
|---------------|-----------------|
| "Add validation" | "Write tests for invalid inputs, then make them pass" |
| "Fix the bug" | "Write a test that reproduces it, then make it pass" |
| "Refactor X" | "Ensure tests pass before and after" |

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

## Clean Architecture

Follow these layered boundaries when building features:

```
┌─────────────────────────────────────┐
│           Presentation              │  ← UI components, API endpoints
├─────────────────────────────────────┤
│           Application               │  ← Use cases, orchestration
├─────────────────────────────────────┤
│             Domain                  │  ← Entities, business rules
├─────────────────────────────────────┤
│          Infrastructure             │  ← Database, external APIs
└─────────────────────────────────────┘
```

**Rules:**
- Dependencies point inward (outer layers depend on inner layers)
- Domain layer has no external dependencies
- Infrastructure implements interfaces defined in inner layers
- Each layer should be testable in isolation

---

## Repository Structure

This is a monorepo using Git submodules:

```
bamr87/
├── AGENTS.md                   # This file — agent principles
├── CONTRIBUTING.md             # Contribution guidelines
├── docker-compose.yml          # Container-first development
├── cv/                         # Submodule: CV Builder (React/TypeScript/Vite)
├── README/                     # Submodule: Documentation hub (MkDocs/Wiki)
├── scripts/                    # Submodule: Automation scripts (Bash/Python)
├── skills/                     # Submodule: Microsoft Agent Skills (microsoft/skills)
├── tools/                      # Dev environment setup, Brewfile
├── docs/                       # Architecture and development docs
├── .github/
│   ├── agents/                 # Agent persona definitions
│   ├── prompts/                # Reusable prompt templates
│   ├── instructions/           # Copilot instruction files (applyTo patterns)
│   ├── docs/                   # Pattern enforcement, workflow patterns
│   ├── workflows/              # CI/CD GitHub Actions
│   └── copilot-instructions.md # Global Copilot config
```

### Submodule Quick Reference

| Submodule | Repo | Branch | Tech Stack |
|-----------|------|--------|------------|
| `cv/` | `bamr87/cv-builder-pro` | `main` | React, TypeScript, Vite, Tailwind |
| `README/` | `bamr87/README` | `main` | MkDocs, Python, Markdown |
| `scripts/` | `bamr87/scripts` | `master` | Bash, Python |
| `skills/` | `microsoft/skills` | `main` | Skills, prompts, MCP configs |

### Container Development

All development runs in Docker. The `docker-compose.yml` provides:

| Service | Port | Purpose |
|---------|------|---------|
| `devenv` | `5000` | CV Builder (Vite) |
| `devenv` | `5173` | Vite HMR |
| `devenv` | `8000` | MkDocs |
| `devenv` | `4000` | Jekyll |

```bash
# Start development
docker-compose up -d

# Run commands inside container
docker-compose exec devenv bash
```

---

## Conventions

### Code Style

- **Python**: Follow PEP 8. Use type hints. Format with `black`, lint with `ruff` or `flake8`.
- **TypeScript/JavaScript**: Use ESLint + Prettier. Prefer TypeScript. Use ES Modules.
- **Bash**: Use `set -euo pipefail`. Quote all variables. Use `shellcheck`.
- Use context managers and proper resource cleanup
- Use type hints/annotations on all function signatures

### Git & GitHub

- Follow Conventional Commits: `type(scope): description`
- Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `perf`, `ci`
- Use `gh` CLI for GitHub operations (PRs, issues)
- Always commit submodule changes before updating the parent pointer

### Clean Code Checklist

Before completing any code change:

- [ ] Functions do one thing
- [ ] Names are descriptive and intention-revealing
- [ ] No magic numbers or strings (use constants)
- [ ] Error handling is explicit (no empty catch blocks)
- [ ] No commented-out code
- [ ] Tests cover the change

### Testing Patterns

```python
# Arrange
service = DataService()
expected = {"id": "123", "name": "test"}

# Act
result = service.get_item("123")

# Assert
assert result == expected
```

- Use `pytest` for Python, `vitest` or `cypress` for TypeScript
- Mock external dependencies at the service boundary
- Test both success and error paths
- Follow Arrange-Act-Assert (AAA) pattern

---

## README-First, README-Last

This is a **critical workflow rule**. Before and after every task:

1. **README-FIRST**: Read the relevant `README.md` to understand context
2. Do the work
3. **README-LAST**: Update `README.md` to reflect changes

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow.

---

## Workflow: Adding a Feature

1. **Clarify** — Understand the requirement. Ask if unclear.
2. **Read README** — Understand context and existing patterns.
3. **Test First** — Write a failing test that defines success.
4. **Implement** — Write minimum code to pass the test.
5. **Refactor** — Clean up while tests stay green.
6. **Verify** — Run full test suite, check types, lint.
7. **Update README** — Document what changed.

```bash
# Example workflow
pytest tests/test_feature.py -v     # Run specific tests
mypy src/                           # Type check (Python)
ruff check src/                     # Lint (Python)
npx eslint src/                     # Lint (TypeScript)
```

---

## Do's and Don'ts

### Do

- ✅ Read README.md before and after every task
- ✅ Use container-first development (`docker-compose`)
- ✅ Write tests before or alongside implementation
- ✅ Keep functions small and focused
- ✅ Match existing patterns in the codebase
- ✅ Use `gh` CLI for all GitHub operations
- ✅ Follow Conventional Commits format
- ✅ Commit submodule changes before updating parent

### Don't

- ❌ Hardcode credentials or endpoints
- ❌ Suppress type errors (`as any`, `@ts-ignore`, `# type: ignore`)
- ❌ Leave empty exception handlers
- ❌ Refactor unrelated code while fixing bugs
- ❌ Add dependencies without justification
- ❌ Skip README updates after making changes
- ❌ Make unrelated changes across multiple submodules in one PR

---

## Success Indicators

These principles are working if you see:

- Fewer unnecessary changes in diffs
- Fewer rewrites due to overcomplication
- Clarifying questions come before implementation (not after mistakes)
- Clean, minimal PRs without drive-by refactoring
- Tests that document expected behavior
- READMEs that stay current with code changes
