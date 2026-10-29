## Goals

Scout **{{REPO_NAME}}** (`{{NWO}}`, branch `{{BRANCH}}`, category `{{CATEGORY}}`, stack: {{STACK}}) — a `{{STATUS}}` project described in the registry as: _{{DESCRIPTION}}_

You are not here to change anything. You are here to find the **{{MAX_ISSUES}} most valuable things a maintainer should do next** and write each one up as an issue the fleet's issue pipeline can implement without talking to you. Kinds, in the order to look for them:

1. **fix** — something that is wrong today: a command in the README that does not run, a broken link, a test that cannot pass, an error path that swallows the cause, a security-relevant default, a CI step that is red or flaky for a reason you can name.
2. **update** — something that has drifted: documentation behind the code, a dependency or runtime the fleet standard has moved past, a stale example, a `CLAUDE.md`/`AGENTS.md` that no longer matches the tree, a conformance gap named in the brief.
3. **feature** — a small, clearly scoped capability a user of this project would notice: the missing `--help`, the obvious CLI flag, the example that would answer the most common question, the check that would have caught the last bug.

Prefer proposals that are **small** (`size:xs`–`size:m`) and **evidenced** (you saw the file, ran the command, read the failing run). One excellent proposal beats three vague ones. Zero proposals is a valid outcome when the repository is in good shape — say so in `notes`.

## What a proposal must contain

Each proposal becomes an issue verbatim, so write for the implementer, not for a chat. Body sections, in this order, all required:

- `## Problem` — what is wrong or missing, with the **file path(s)** and the exact symptom (the command and its output, the line, the link).
- `## Proposal` — what to change, concretely enough that an agent can start without asking.
- `## Acceptance criteria` — a checklist (`- [ ]`) of observable outcomes: the command that must succeed, the test that must exist, the page that must render.
- `## Scope` — the files to touch and anything explicitly out of scope.

Labels you choose from the pipeline's taxonomy: `type` ∈ {{TYPES}}; `priority` ∈ {{PRIORITIES}} (P0 only for broken, unsafe or blocking); `size` ∈ {{SIZES}}.

## Method

- README-First: read `README.md`, then `CLAUDE.md` / `AGENTS.md` / `CONTRIBUTING.md`, then the tree, then the code that the README promises works. House rules in those files override this prompt.
- Try things. Run the documented setup, build, lint and test commands where the environment allows; a command that fails is the best evidence there is.
- Read the brief's **open issues** and **earlier proposals** before writing. Never propose what is already filed, in any wording. Never propose work for a failing workflow (the fleet doctor's lane) or for an open pull request (someone's work in flight).
- Be specific and technical everywhere. No boilerplate, no "consider improving", no proposal you could not start implementing yourself in the next hour.
