# Repository layout

A newcomer's map of what lives at the root of this repository and why.

> **Status of this document.** It was assembled from the repository's top-level
> file listing. Rows marked **(verified)** are things the listing itself proves
> (the file or directory exists, with that name). Rows marked **(inferred)** are
> educated guesses from conventional naming that **have not been confirmed by
> reading the file**. If you have the repo checked out and a row is wrong, please
> fix it — that is the fastest way to make this page trustworthy.

---

## The short version

This repository wears two hats at once, which is the main thing that confuses first-time readers:

1. **A site that is also a control plane.** The public site at bamr87.github.io/bamr87 is the Harness Console (`tools/console/`) built static: `_data/` (the registries) and `pages/` (`profile/*.md`, `posts/*.md`) are its content, and `tools/console/build-pages.sh` builds it ([CONSOLE-PAGES.md](CONSOLE-PAGES.md)). `README.md` is the GitHub profile README.
2. **A monorepo with automation around it.** `projects/`, `templates/`,
`tools/`, `_reports/`, `fleet.manifest.yml`, `.mcp.json`, `AGENTS.md` and `CLAUDE.md` are about building, orchestrating and agent-driven workflows — not about the site's HTML.

Everything else at the root is developer-environment plumbing: linting, formatting, hooks, containers, editor settings.

**`README.md` is a personal profile page, not a build guide.** Don't look there for setup instructions.

---

## Where to start reading

| If you want to… | Open |
| --- | --- |
| Know who maintains this and what they do | `README.md` |
| Contribute a change | `CONTRIBUTING.md` |
| Understand the data shapes / schemas used here | `SCHEMA.md` |
| Understand the git submodules and how to initialise them | `SUBMODULES.md` |
| Understand how AI agents are expected to work in this repo | `AGENTS.md`, `CLAUDE.md` |

(These files exist at the root — **verified** from the listing. Their contents are summarised here only by what their names claim; open them for the detail.)

---

## Top-level map

### Site sources

| Entry | Role | Confidence |
| --- | --- | --- |
| `tools/console/` | The Harness Console: FastAPI + a React/Mantine page; built static, it is the public site. | verified |
| `_data/` | The registries every surface reads; `profile.yml` is the site's identity. | verified |
| `pages/` | The site's long-form content: `profile/*.md` and `posts/*.md`. | verified |
| `README.md` | Profile README for github.com/bamr87. | verified |

### Monorepo content and tooling

| Entry | Role | Confidence |
| --- | --- | --- |
| `projects/` | Project directories. Given `.gitmodules` is present, some or all of these are likely git submodules. | inferred — cross-check against `.gitmodules` and `SUBMODULES.md` |
| `templates/` | Reusable templates (scaffolding for new projects, pages, or documents). | inferred — purpose and consumer unconfirmed |
| `tools/` | Scripts and utilities. The repository's primary language is reported as Shell, so this is a likely home for those scripts. | inferred |
| `_reports/` | Generated reports/output. The leading underscore suggests generated-not-hand-written. | inferred — confirm what writes here and whether it's committed |
| `tools/dash` | The dash CLI — the repository's task entry point. Run it with no arguments to list commands. | verified |
| `.gitmodules` | Git submodule definitions. See `SUBMODULES.md`. | verified |

### Agent and automation configuration

| Entry | Role | Confidence |
| --- | --- | --- |
| `AGENTS.md` | Instructions for AI coding agents working in this repo. | verified (file exists) |
| `CLAUDE.md` | Claude-specific project instructions. | verified (file exists) |
| `.claude/` | Claude configuration directory (e.g. commands, settings). | inferred |
| `.mcp.json` | Model Context Protocol server configuration. | inferred |
| `fleet.manifest.yml` | Manifest describing the automation "fleet" that operates on this repo. | inferred — see the file for the authoritative schema |
| `.github/` | GitHub configuration: workflows, issue/PR templates. | inferred |

### Development environment and code quality

| Entry | Role | Confidence |
| --- | --- | --- |
| `.devcontainer/` | VS Code / Codespaces dev container definition — likely the quickest path to a working environment. | inferred |
| `docker-compose.yml` | Container services for local development. | inferred — read the file for the actual service names |
| `.vscode/` | Shared VS Code settings for this workspace. | inferred |
| `home.code-workspace` | Consolidated VS Code multi-root workspace (dash plus related clones). | inferred |
| `.editorconfig` | Cross-editor whitespace/encoding rules. | verified (standard format) |
| `.prettierrc`, `.prettierignore` | Prettier formatting config and exclusions. | verified (standard names) |
| `.pre-commit-config.yaml` | `pre-commit` framework hook definitions. | verified (standard name) |
| `.husky/` | Husky git hooks. | verified (standard name) |
| `.env.example` | Template for a local `.env`; copy it and fill in your own values. Never commit the real `.env`. | verified (standard convention) |
| `.gitignore` | Ignored paths. | verified |

### Dotfiles at the root

| Entry | Role | Confidence |
| --- | --- | --- |
| `.zshrc`, `.zprofile`, `.gitconfig` | Shell and git dotfiles. These may be *managed by* this repository (i.e. content it distributes to a machine) rather than configuration *of* the repository. | inferred — needs confirmation, this distinction matters |

### Documentation

| Entry | Role | Confidence |
| --- | --- | --- |
| `docs/` | Long-form documentation — including this page. | verified |
| `SCHEMA.md` | Schema documentation. | verified (file exists) |
| `SUBMODULES.md` | Submodule documentation. | verified (file exists) |
| `CONTRIBUTING.md` | Contribution guide. | verified (file exists) |

---

## Getting set up — **not yet documented here**

This page deliberately contains **no install, build, serve or test commands**. The author of this page could not read `docker-compose.yml` or `.devcontainer/`, and writing commands that were never verified is worse than writing none.

Until this section is filled in, the authoritative sources are, in rough order of usefulness:

1. `.devcontainer/` — if a dev container is defined, opening the repo in it is
   usually the shortest path to a working environment.
2. `tools/dash` — run it with no arguments to list the available commands.
3. [`local-development.md`](local-development.md) — the console and the site build.
4. `docker-compose.yml` — the local service definitions.
5. `.github/` — CI workflows show the exact commands that must pass, which is
   the most reliable description of "how this project is built and tested".

### TODO for a maintainer

Replace this section with the real commands, copied verbatim from the files above:

The repository root `README.md` is a **GitHub profile README** — it renders on
<https://github.com/bamr87> and describes the author, not the codebase. That is
intentional, but it means a person who clones this repository has nowhere obvious to start.

This page is that starting point. It answers:

- What is actually in this repository?
- Which of the many existing docs should I read, and in what order?
- How do I get it running on my machine?

## Read these first

This repository already carries a fair amount of documentation. This page is a **map**, not a replacement — when a topic has a dedicated file, go there.

| Document | Read it when |
|---|---|
| [`CONTRIBUTING.md`](../CONTRIBUTING.md) | Before your first change — branch naming, commit conventions, review expectations. **This is the authoritative process doc; if it disagrees with this page, it wins.** |
| [`SUBMODULES.md`](../SUBMODULES.md) | You need to know which submodules exist, what they contain, and how to initialize/update them. |
| [`SCHEMA.md`](../SCHEMA.md) | You are adding or editing structured content — front matter fields, `_data/` files, or anything with a defined shape. |
| [`AGENTS.md`](../AGENTS.md) | You are an automated agent, or you are configuring one. Conventions for machine contributors. |
| [`CLAUDE.md`](../CLAUDE.md) | Claude-specific working instructions for this repository. |
| [`fleet.manifest.yml`](../fleet.manifest.yml) | You want to know how automated contributions to this repo are scoped and configured. |
| `docs/` | Longer-form documentation lives here (this file included). |

## What this repository is

A **monorepo** whose root is the control plane for its Git submodules — and whose public site is that control plane's own page, built static (see [CONSOLE-PAGES.md](CONSOLE-PAGES.md)) — plus the author's shell/dotfile and tooling configuration.

## Layout

### Site content and configuration

| Path | What it is |
|---|---|
| `pages/` | Site content: `profile/*.md` (About, Experience, Services, Contact) and `posts/*.md`. |
| `_data/` | The registries every surface reads. See [`SCHEMA.md`](../SCHEMA.md) for the expected shape of these files before editing them. |
| `tools/console/web/` | The site's page (React + Mantine); `public/` holds its static files. |
| `templates/` | Seedable kits fanned out to the submodules (see `templates/SCHEMA.md`). |
| `projects/` | Project content and/or submodule mount points. Cross-check against [`SUBMODULES.md`](../SUBMODULES.md). |
| `docs/` | Long-form documentation, including this page. |
| `_reports/` | ⚠️ *Verify:* generated output (reports/audits). Confirm whether this is committed deliberately or generated locally. |

### Build, run, and automation

| Path | What it is |
|---|---|
| `tools/dash` | The dash CLI — the task entry point (`tools/dash` with no arguments lists commands). |
| `docker-compose.yml` | Containerized local environment. ⚠️ *Verify:* service names and published ports. |
| `.devcontainer/` | VS Code / GitHub Codespaces dev container definition — the lowest-friction path if you use either. |
| `tools/` | Repository tooling and scripts. The repository's primary language is reported as **Shell**, so expect executable scripts here. ⚠️ *Verify:* whether these are meant to be run directly or only via `Rakefile` tasks. |
| `.github/` | GitHub Actions workflows, issue/PR templates. **The workflows here are the ground truth for what CI actually runs** — if you want to know how the project is built and checked, read them.  |

### Code quality and environment

| Path | What it is |
|---|---|
| `.editorconfig` | Editor defaults (indentation, line endings). Most editors apply this automatically. |
| `.prettierrc`, `.prettierignore` | Prettier formatting configuration and exclusions. |
| `.pre-commit-config.yaml` | [pre-commit](https://pre-commit.com/) hook definitions. |
| `.husky/` | Husky Git hooks. ⚠️ *Verify:* how these coexist with `pre-commit` — running both is possible but worth documenting so contributors know which hook fired. |
| `.env.example` | Template for local environment variables. Copy it to `.env` (which is git-ignored) and fill in real values. ⚠️ *Verify:* which keys are required vs. optional. |
| `.gitmodules` | Submodule definitions — see [`SUBMODULES.md`](../SUBMODULES.md). |
| `.gitconfig`, `.zshrc`, `.zprofile` | The author's shell and Git configuration, versioned as dotfiles. **These are not needed to build the site** — do not source them expecting the project to require it. |
| `.vscode/`, `home.code-workspace` | VS Code workspace settings and the consolidated multi-root workspace. Open `home.code-workspace` rather than the plain folder to pick up the intended layout. |
| `.mcp.json`, `.claude/` | Model Context Protocol / Claude tooling configuration for agent-assisted work. See [`AGENTS.md`](../AGENTS.md) and [`CLAUDE.md`](../CLAUDE.md). |

## Getting the site running locally

There appear to be **three** supported paths. Pick one.

### 1. Dev container (recommended if you use VS Code or Codespaces)

The repository ships a `.devcontainer/` definition, which means the toolchain is already pinned for you: open the folder in VS Code and choose *Reopen in Container*, or start a Codespace from the GitHub UI.

> ⚠️ **Needs verification:** base image, forwarded ports, and whether a
> post-create step already runs dependency installation and submodule
> initialization. Fill in below.
>
> - Base image / features:
> - Forwarded port(s):
> - Runs automatically on create:

### 2. Docker Compose

A `docker-compose.yml` exists at the root.

> ⚠️ **Needs verification:** exact invocation, service name(s), and the URL the
> site is served on.
>
> ```sh
> # fill in from docker-compose.yml
> ```

### 3. Native toolchain

Python 3 and Node (current LTS):

```sh
tools/dash console   # the live console on http://127.0.0.1:4001
tools/dash serve     # the public site, built static, on http://127.0.0.1:4000
```

### Submodules

This repository uses Git submodules (`.gitmodules`). A plain `git clone` will leave submodule directories empty, and a site build may then fail or silently omit content.

[`SUBMODULES.md`](../SUBMODULES.md) is the authoritative reference for which submodules exist and how to work with them — read it before your first clone, and consult it again when a submodule directory looks unexpectedly empty or a diff shows a bare pointer change.

## Tests and checks

> ⚠️ **Needs verification.** No dedicated test directory appears in the
> repository root listing, so it is likely that verification here means
> "the site builds cleanly" plus the configured lint/format hooks, rather than
> a unit test suite. The workflows in `.github/` are the authoritative answer
> to *what CI actually enforces* — read them and record the result here.
>
> - Test command (if any):
> - Lint / format command:
> - Link or build validation:

In the meantime, before opening a pull request:

1. Make sure the site builds locally by whichever path you used above.
2. Let the configured hooks run — `.pre-commit-config.yaml` and `.husky/` are
both present, so formatting and lint checks are expected to fire on commit. Do not bypass them without saying so in your PR description.
3. Follow the process in [`CONTRIBUTING.md`](../CONTRIBUTING.md).

## Where to put a change

| You want to… | Go to |
|---|---|
| Edit the profile page that shows on github.com/bamr87 | `README.md` (root) — note this is the *profile* README, not project docs |
| Add or edit a site page | `pages/profile/` (and `PROFILE_PAGES` in `tools/console/web/src/nav.ts`), or `pages/posts/` for writing |
| Change structured data behind the site | `_data/` — check [`SCHEMA.md`](../SCHEMA.md) first |
| Change the site's pages or styling | `tools/console/web/` |
| Add or change a build/automation task | `tools/` |
| Change CI | `.github/` |
| Add contributor documentation | `docs/` (this directory) |
| Change something inside a submodule | The submodule's own upstream repository — see [`SUBMODULES.md`](../SUBMODULES.md) |

## Improving this page

Every ⚠️ marker above is an open question. If you resolve one — by reading the file, or by running the command successfully — please replace the marker with the verified answer in the same pull request as your other work. The goal is for this page to have zero ⚠️ markers.
- [ ] Prerequisites (Ruby version, Node version, Docker — whatever is actually required)
- [ ] First-time setup, including submodule initialisation (see `SUBMODULES.md`) and `.env` creation from `.env.example`
- [ ] How to serve the site locally (`tools/dash serve`, `tools/dash console`)
- [ ] How to run linters/formatters (`pre-commit`, Prettier, Husky hooks)
- [ ] How to run tests, if any
