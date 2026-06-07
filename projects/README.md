# projects/ — submodule container

Every independent project in this monorepo is a **git submodule** under this
directory. Each is a separate repository with its own stack, branch, and release
cycle. This container keeps the repo root navigable as the portfolio grows
(toward ~42 projects).

## Convention

- One submodule per project at `projects/<name>/` — **flat**, no category
  subfolders. Logical grouping (docs / full-stack-ai / dev-tools / hub) lives in
  the registry's `category` field, not the filesystem, so a project can be
  re-categorized without moving files.
- The single source of truth is [`../dash/_data/projects.yml`](../dash/_data/projects.yml).
  Each submodule entry's `submodule_path` is `projects/<name>` and **must** equal
  the `.gitmodules` path — the drift gate (`tools/check-drift.sh`) enforces this.

## Current submodules

| Path | Upstream | Branch | Stack |
|------|----------|--------|-------|
| `projects/cv` | `bamr87/cv-builder-pro` | `main` | React, TypeScript, Vite |
| `projects/README` | `bamr87/README` | `main` | Python, MkDocs, Wiki.js |
| `projects/scripts` | `bamr87/scripts` | `master` | Bash, Python |
| `projects/skills` | `microsoft/skills` (external) | `main` (`update = merge`) | Markdown skills, MCP |

## Adding a project

```bash
git submodule add <url> projects/<name>
# add a matching entry to dash/_data/projects.yml
tools/dash-gen readme        # refresh the profile README list
tools/check-drift.sh         # verify .gitmodules ↔ registry parity
```

(The `/register-project` and `new-project` Claude skills automate this.)

## Working with submodules

A change inside a submodule is committed in **its own repo first**, then the
pointer is recorded here. See the root [`CLAUDE.md`](../CLAUDE.md) and
[`SUBMODULES.md`](../SUBMODULES.md) for the full workflow. At scale, check out
only what you need: `tools/dash sync` supports a per-project/category subset
rather than cloning all submodules.
