---
mode: agent
summary: File System Structure Overlay - Systematic repository filesystem analysis that maps directories and files onto stack layers
description: |
  Analyze a repository's filesystem and produce a layered overlay that maps directories, configuration files, and source code to the project's technology stacks and responsibilities. The analysis should be structured, searchable, and saved as a markdown record.
---

# 🗂️ File System Structure Overlay

This prompt guides the agent to analyze repository file system structure and overlay stack responsibilities across directories and files. It mirrors the Stack Attack protocol but focuses on the *file-system-first* view — where each folder and file are annotated with stack and architecture responsibilities, ownership, and integration points.

## Mission

- Map the repository's filesystem to stack layers (Frontend, Backend, Data, Infra, DevTools)
- Identify structural responsibilities and key configuration points
- Provide tactical recommendations for maintenance, onboarding, and modernization
- Save the analysis to the `stacks` collection

## PDCA Framework — Filesystem-Aligned

a. PLAN — Scan and scope

- Read `README.md` and any directory-level READMEs
- Identify top-level folders and language-specific config files (e.g., `package.json`, `pyproject.toml`, `Cargo.toml`)
- Define the analysis depth: Quick / Standard / Deep

- b. DO — Directory-by-directory review

- For each folder, collect:
  - Role: (e.g., frontend app, backend, infra, docs, scripts, tests)
  - Primary languages
  - Key config files found inside
  - Stack overlay (frontend/backend/data/infra/devtools)
  - Important file-level artifacts (e.g., Dockerfiles, test harnesses, entrypoints)
- Identify cross-folder integrations (shared libs, mono-repo packages)
- Look for patterns: multiple `package.json` files, `apps/`, `services/`, `lib/`

c. CHECK — Validate findings

- Confirm that stack mapping matches config files and imports
- Look for repeated patterns representing cross-cutting responsibilities (e.g., `scripts/setup`, `lib/shared`)
- Identify mismatches: e.g., a `Dockerfile` in a `scripts` folder or `frontend` in `backend` folder

d. ACT — Recommendations and output

- Provide immediate fixes, maintenance steps, and modernization suggestions
- Save analysis into an organized markdown file in `it-journey/pages/_quests/lvl_001/stacks/`

---

## Analysis phases & details

### 1. Quick Mode (15 min)

- Plan: Top-level scan of repository root + `README.md`
- Do: List top-level directories and one-line description each
- Check: Confirm languages and main configuration files
- Act: Provide 3-5 short actionable recommendations

### 2. Standard Mode (30–45 min)

- Plan: Full root and selected subdirectory analysis
- Do:
  - Produce `Directory -> Stack` mapping table
  - Check all top-level config files for versions and roles
  - Produce a high-level mermaid directory diagram
- Act: Provide recommendations (file placement, monorepo partitioning, clarity)

### 3. Deep Mode (1–2 hrs)

- Plan: Expand Standard mode into full service-level overlay
- Do:
  - Inspect each `package.json`, `pyproject.toml`, `Dockerfile`, and pipeline
  - Generate a service dependency graph (imports, packages referencing each other)
  - Overlay stack responsibilities with ownership tags (e.g., `data team`, `frontend team`)
- Act: Provide planning items (refactor suggestions, tests re-org, package consolidation)

---

## Directory Analysis Template

For each directory, produce:

- Directory path: `path/to/dir`
- Role: `role` (frontend, backend, plugin-server, docs, infra, tests)
- Primary language(s): `JS, TS, Python, Ruby, Go` etc.
- Key files: `package.json`, `requirements.txt`, `Dockerfile`, `README.md` etc.
- Stack overlay: `Frontend | Backend | Data | Infra | DevTools` (one or more)
- Integration notes: e.g., APIs or event flows, links to other directories
- Risk / Opportunity: e.g., stale scripts, unclear interface boundaries

Example:

### Directory: `frontend/`

- Role: Frontend SPA
- Languages: TypeScript, React
- Key files: `package.json`, `vite.config.ts`, `tsconfig.json`, `README.md`
- Stack overlay: Frontend (UI), DevTools (build), Infra (Dockerfile for static assets)
- Integration: Calls `api/` for server endpoints; shared `lib/` for types
- Opportunity: Split out shared `types/` into independent package for multi-repo reuse

---

## Tools, Patterns & Checklists

- Search for: `package.json`, `pyproject.toml`, `requirements.txt`, `Dockerfile`, `docker-compose.yml`, `helm/`, `.github/workflows`.
- Identify entrypoints: `manage.py`, `server.js`, `main.py`, `index.tsx`
- Look for repeatable patterns: `apps/`, `services/`, `packages/`
- Check for legacy areas: `vendor/`, `bin/`, `legacy/` and determine migration suggestions

### Merits of overlay mapping

- Bridging code ownership and deployment: maps code to deployment targets
- Onboarding acceleration: new contributors learn what is in each directory and why
- Dependency detection: spot where shared code should be isolated into a library

---

## Output format & file management

- File path and name:
  - `/Users/bamr87/github/it-journey/pages/_quests/lvl_001/stacks/[repository-name]-filesystem-overlay.md`
- Frontmatter (same style as Stack Attack) must be included: title, description, repository, primary_language, project_type, analysis_date, categories, tags.
- Sections required in output:
  - Executive Summary (2-3 paragraphs)
  - Key Metrics (loc estimate, languages, dependencies counts)
  - Directory Analysis (table + per-directory entries)
  - Overlay Diagram (Mermaid) showing stack overlay on directory tree
  - Recommendations (Immediate, Short-term, Long-term)
  - Action Items for maintainers

---

## Output generation checklist (QA)

- [ ] All top-level directories analyzed
- [ ] Stack overlay created and validated against config files
- [ ] Architecture diagram included
- [ ] Actionable recommendations provided
- [ ] File saved to stacks collection and index updated (if present)

---

## Special cases

- Monorepo: When `packages/` or `services/` found, create per-package overlays and high-level platform overlay
- Microservices: Map each service folder to a stack node and produce service dependency graph
- Legacy repo: Identify cross-cutting `vendor/` or `legacy/` and recommend extraction into `archived/`

---

## Suggested output code snippet (to be included in analysis)

```bash
# create overlay analysis
mkdir -p /Users/bamr87/github/it-journey/pages/_quests/lvl_001/stacks
cat > /Users/bamr87/github/it-journey/pages/_quests/lvl_001/stacks/myrepo-filesystem-overlay.md <<EOF
---
title: "Filesystem Stack Overlay: myrepo"
# ... rest frontmatter ...
---
<<analysis content>>
EOF
```

---

## Quality & Continuous Improvement

- After each analysis, add a short retrospective (what was hard to find, what is missing in the repo docs)
- Update prompt if new directory patterns appear in the organization's repos

---

**Ready to run**: Use `/stackstructure` to start a file system overlay analysis for any repository.

End of prompt
