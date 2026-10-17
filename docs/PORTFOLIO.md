# bamr87 portfolio standard

Applies to every repository owned by [bamr87](https://github.com/bamr87). It sits alongside the hub's Universal Project Standard ([`specs/REPOSITORY.md`](https://github.com/bamr87/bamr87/blob/main/specs/REPOSITORY.md)): this file covers what a visitor sees (GitHub metadata, README, profile index), and it is written to satisfy the hub's README check (UPS-REPO-10, UPS-REPO-15).

## 1. Description

- One sentence, at most ~120 characters, in plain present tense.
- Say **what it is** first, then **for whom or for what**. Pattern: `<Name or kind>: <what it does> <for whom / where it runs>.`, or a plain sentence.
- Name the main stack only when it tells you what the project is (for example "Django + React app", "VS Code extension", "Jekyll theme").
- No emoji. No marketing words ("ultimate", "world's first"). No trailing hashtags.
- Forks start with `Fork of <upstream>` or `Personal fork of <upstream>`.
- The GitHub description and the README tagline (the blockquote under the H1) say the same thing. An existing hand-written tagline may stay if it agrees with the description.

## 2. Topics (controlled vocabulary)

5 to 10 topics per repo, lowercase and hyphenated, chosen from the lists below. Add a new term only when no existing one fits, and add it here at the same time.

**Category (pick 1 to 3)**

| Topic | Use for |
|---|---|
| `website` | A published site (personal, business or project) |
| `knowledge-base` | Content collections that grow over time |
| `education` | Learning platforms and study material |
| `jekyll-theme`, `jekyll-plugin` | Theme and plugin packages |
| `web-app` | Interactive applications with a frontend |
| `cli` | Command-line tools |
| `vscode-extension` | VS Code extensions |
| `developer-tools` | Tooling for developers that is not a CLI or extension |
| `ai-agents` | Agent frameworks, agent harnesses, agentic SDLC automation |
| `github-actions`, `automation`, `devops`, `ci-cd` | Workflow and pipeline repos |
| `game`, `retro-gaming`, `game-framework` | Games and emulation |
| `template`, `demo`, `monorepo`, `dotfiles`, `documentation`, `specification` | Repo shape |
| Domain terms: `erp`, `accounting`, `finance`, `legal-tech`, `seo`, `ocr`, `resume`, `music`, `writing`, `security`, `research` | What the project is about |

**Tech stack (pick the defining ones)**

`jekyll`, `github-pages`, `ruby`, `rails`, `python`, `django`, `fastapi`, `typescript`, `javascript`, `react`, `vite`, `tailwindcss`, `bash`, `zsh`, `docker`, `postgresql`, `sqlite`, `latex`, `godot`, `gdscript`, `obsidian`, `bootstrap5`, `mcp`, `langgraph`, `crewai`, `neo4j`, `ollama`, `openai`, `claude-code`, `ai`.

**Family**

`zer0-mistakes` marks repos built on, or built for, the zer0-mistakes Jekyll theme.

**Status (at most one; omit for active projects)**

| Topic | Meaning | Source |
|---|---|---|
| `experimental` | Prototype or research; may change or stop | registry `status: experiment` |
| `maintenance-mode` | Works, fixes only | registry `status: maintenance` |
| `unmaintained` | Registry marks it archived, but the GitHub repo is still open | registry `status: archived` |
| `fork` | A fork of someone else's project | GitHub fork flag |

GitHub-archived repos need no status topic; GitHub already shows the banner.

## 3. Homepage

- Set the homepage to the live URL when one exists, in this order: custom domain (for example `https://it-journey.dev/`), then the GitHub Pages URL, then another deployed URL.
- Use `https`, and check that the URL answers before setting it.
- Leave it empty when nothing is deployed. Never point a fork's homepage at the upstream's site.

## 4. README skeleton

Every non-fork README has, in this order (sections that do not apply may be omitted, except License):

1. `# <Project name>`. YAML front matter, when the README is also a Jekyll page, stays above it.
2. `> <tagline>`: the one-line summary from §1.
3. A badge row: **CI** (only if `.github/workflows/ci.yml` exists), **License** (only if a LICENSE file exists), **Live site** (only if a homepage is set). Existing badges stay.
4. `## Overview`: what it is and why it exists. Existing intro text moves here.
5. `## Features`: a short bullet list, written from the code and existing docs. An existing equivalent section ("What it does", "What's in the box") counts.
6. `## Quick start` (and/or `## Usage`): copy-pasteable commands that match `CLAUDE.md` / `AGENTS.md`.
7. Existing deep-dive sections (architecture, configuration, guides) stay in their original order.
8. `## Project structure`: a brief table or tree of the top-level folders.
9. `## Development`: build, test and lint commands, plus a link to `AGENTS.md` (canonical) or `CLAUDE.md`.
10. `## Contributing`: links `CONTRIBUTING.md`, or the hub's `CONTRIBUTING.md` when the repo has none, plus the agent guide.
11. `## Changelog`: links `CHANGELOG.md`, or the commit history when there is none yet, plus the releases page when releases exist.
12. `## License`: the license and a link to the LICENSE file. If there is no LICENSE file, say so.
13. The footer, after a `---` rule:

```markdown
<!-- bamr87-portfolio-footer -->
<sub>Part of the [bamr87 portfolio](https://github.com/bamr87) — browse every project on [Amr's GitHub profile](https://github.com/bamr87).</sub>
```

Rules:

- Restructure and fill gaps; do not replace accurate content. Never describe a feature the code does not have.
- Rename a heading only when nothing links to its anchor.
- Write one paragraph per line, as the fleet's `markdown-oneline` check requires.
- Forks keep the upstream README.

## 5. Profile README (bamr87/bamr87)

- A short intro, then the portfolio index grouped by the categories below, one line per repo: link, description and live site.
- The index is generated from `_data/projects.yml` (and `_data/portfolio.yml` for display-only extras) by `.github/scripts/dash-gen` between the `AUTO:projects` markers. Edit the data, not the generated block.
- Status marks: 🧪 experimental, 🛠️ maintenance mode, 💤 unmaintained, 🗄️ archived, 🍴 fork, 🔒 private (name and description only, or omitted if the description is sensitive).

Profile groups: Fleet platform & standards · zer0 Jekyll ecosystem · Websites · Knowledge bases & learning · AI applications & research · AI agents & SDLC automation · Business & career apps · Developer tools & extensions · Games & retro computing · Forks.
