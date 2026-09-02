# UPS-REPO — Repository layout and required files

> What every repo looks like from the root, and what each required file must contain. File *presence* per tier is already gated by [`_data/standards.yml`](../_data/standards.yml); this spec governs *content* and *layout*.

Evidence base: 33 of 35 fleet repos carry the byte-identical hub `.editorconfig`; every repo except two has a `tools/` directory; README structure varies from none (zer0-pages-remote) to raw course HTML (skills-github-pages); 12 owned repos lack a LICENSE; no repo has `SECURITY.md`.

## Layout

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-REPO-01 | MUST | all | Root holds only: docs-of-record (`README.md`, `CLAUDE.md`/`AGENTS.md`, `LICENSE`, `CHANGELOG.md`, `SECURITY.md`, `CONTRIBUTING.md`, `SCHEMA.md`), tool manifests, dotfiles, and top-level directories from the stack profile. Source never sits loose at the root. | `SCHEMA.md` Structure table lists every root entry | `templates/schema/` |
| UPS-REPO-02 | MUST | all | Source lives under the stack's canonical source dir (`src/`, `app/`, `pages/`, `lib/`, or the framework's own convention — see [STACKS.md](STACKS.md)); tests under `tests/` (Python/Node/Bash) or the framework's own (`test/` for Ruby gems and Playwright suites, `cypress/` retired in favour of Playwright). New repos use `tests/`; existing `test/` dirs are grandfathered and recorded as a deviation. | dir present, referenced from `SCHEMA.md` | `scripts/project-init.sh` |
| UPS-REPO-03 | MUST | all | `docs/` holds human docs beyond the README (`UPPERCASE-TOPIC.md` for operator docs, lowercase for guides). A repo with a docs *site* declares its generator (`mkdocs.yml` or the Jekyll site itself); a bare `docs/` with no index is a warning. | `docs/README.md` index exists | — |
| UPS-REPO-04 | SHOULD | all | `tools/` holds the repo's own operator scripts (kebab-case, `#!/usr/bin/env bash`, `set -euo pipefail`, shellcheck-clean) and nothing that ships to users. | `tools/` + `tools/README.md` | — |
| UPS-REPO-05 | MUST | all | Multi-surface repos (backend + frontend, extension + CLI) keep each surface in its own top-level dir with its own manifest and README; the root README links them. | e.g. `backend/`, `frontend/` each with `README.md` | — |
| UPS-REPO-06 | MUST | all | Every directory with more than trivial content has a `README.md` (README-First/README-Last) and, in a schema-adopted repo, a `SCHEMA.md`. | file present | `templates/schema/`, `.github/templates/README.template.md` |
| UPS-REPO-07 | MUST | all | No committed build output, `node_modules/`, lockfiles, `.env`, or secrets. `.gitignore` carries the fleet lockfile block. | `.gitignore` contains the `unpin-deps.sh` block; `git ls-files` clean | `tools/unpin-deps.sh` |
| UPS-REPO-08 | MUST | all | Exactly one checkout per upstream in the fleet. Duplicate directories tracking the same remote (2026-09: `edgar-data-parse`≡`fredgar-ai`, `vscode-front-matter`≡`zer0-cms`) are a registry defect, not two projects. | registry + `.gitmodules` have one path per `repo_url` | `dash reconcile` |

## Required files — content contracts

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-REPO-10 | MUST | all | `README.md` opens with `# <name>`, a one-sentence tagline in a blockquote, then a badge row (CI, release, license), then sections in this order: **What it is · Quick start · Usage · Development · Testing · Deployment (if any) · Contributing · License**. Content repos may collapse Usage/Development/Testing into one **Working with this repo** section. | headings present in order | `.github/templates/README.template.md` (to be extended) |
| UPS-REPO-11 | MUST | all | Quick start is copy-pasteable: one install command, one run command, one test command, each in a fenced block, and they match `CLAUDE.md` **Stack & commands** exactly. | commands identical in both files | — |
| UPS-REPO-12 | MUST | all except fork | `LICENSE` is present and its SPDX id is recorded in the registry `license:` field. Default for bamr87-owned repos is **MIT**; content repos MAY use CC-BY-4.0 and say so in the README. | `LICENSE` + registry field | `templates/license/` (gap — see CONFORMANCE) |
| UPS-REPO-13 | MUST | all except content, fork | `CHANGELOG.md` exists and is release-please managed (Keep-a-Changelog headings, newest first). Hand-edits go only above the first release heading. | file + `release-please-config.json` | `tools/adopt-release.sh` |
| UPS-REPO-14 | MUST | app, api, ext, lib, cli | `SECURITY.md` states the supported versions, how to report privately (GitHub private vulnerability reporting), and the response window (fleet default: acknowledge within 7 days). | file with those three headings | `templates/community/` (gap) |
| UPS-REPO-15 | SHOULD | all except fork | `CONTRIBUTING.md` covers: branch naming, Conventional Commits, how to run the gates locally, the PR template, and the submodule rule (commit here first, hub bumps the pointer). Repos may instead link the hub's `CONTRIBUTING.md` in one line. | file or README link | `templates/community/` (gap) |
| UPS-REPO-16 | SHOULD | all | `CODEOWNERS` exists (soft template: `* @bamr87`) so the issue pipeline's owner routing has a default. | `.github/CODEOWNERS` | `.github/templates/CODEOWNERS-soft.template` |
| UPS-REPO-17 | MUST | all | `.editorconfig` is the hub's byte-for-byte (utf-8, lf, final newline, trim trailing; 2-space yml/json/js/ts/sh, 4-space py with `max_line_length = 120`, tab Makefile, md exempt from trim). | `cmp` with hub copy | `tools/fanout.sh --kit standardize --artifacts editorconfig` |
| UPS-REPO-18 | MUST | all | Issue templates: `bug_report.yml`, `feature_request.yml`, `documentation.yml` plus the feedback-widget template `page_feedback.yml` (see [FEEDBACK.md](FEEDBACK.md)); each applies the type label from the fleet taxonomy so filed issues enter the issue pipeline. | `.github/ISSUE_TEMPLATE/*.yml` | `templates/community/` (gap) |
| UPS-REPO-19 | SHOULD | all | `.github/pull_request_template.md` with: summary, linked issue, checklist (gates green, README-Last done, SCHEMA.md updated). | file present | `templates/community/` (gap) |
| UPS-REPO-20 | MUST | all | Front matter and file headers follow the house rule: shell/python tools carry the header block (File, Description, Author, Created, Last Modified, Version, Usage); Jekyll content carries `title`, `description`, `date`/`lastmod`, `tags`, `categories`, `permalink` (see [FRONTEND.md](FRONTEND.md) FE-40). | header present | `.github/copilot-instructions.md` § File Headers |

## Containers and local environment

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-REPO-30 | SHOULD | app, api, site | A `docker-compose.yml` (or `compose.yml`) runs the whole app locally with one command; a `.devcontainer/devcontainer.json` composes it and pins the fleet VS Code extension set. Ports follow the fleet map: 4000 Jekyll, 5000 web app, 5173 Vite HMR, 8000 API/MkDocs, 5432 Postgres, 6379 Redis. | files present, ports match | hub `.devcontainer/`, `docker-compose.yml` as reference |
| UPS-REPO-31 | MUST | app, api | Dockerfiles are multi-stage, run as a non-root user, declare a `HEALTHCHECK` hitting the health endpoint (BE-10), and never copy `.env`. | Dockerfile review | `.github/copilot-instructions.md` § Container-First |
| UPS-REPO-32 | MUST | all with env config | `.env.example` lists every variable the app reads with a comment and a safe placeholder; the app fails fast on a missing required variable (OPS-01). | file present, names match code | — |
| UPS-REPO-33 | SHOULD | all | One bootstrap script (`tools/setup.sh` or the stack's `make setup`/`npm run setup`) brings a fresh clone to a passing test run; the README Quick start calls it. | script present | `scripts/project-init.sh` |
