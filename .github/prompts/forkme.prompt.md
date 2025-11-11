---
mode: agent
---

Prompt instructions file:
-

## Purpose
Fork or analyze a GitHub repository URL to generate comprehensive `.github/copilot-instructions.md` that enables AI coding agents to be immediately productive in the codebase.

## Primary Focus Areas

### Architecture Discovery
- **System Overview**: Identify major components, service boundaries, and data flows
- **Design Decisions**: Document the "why" behind structural choices that require reading multiple files
- **Module Relationships**: Map dependencies and communication patterns between components
- **Technology Stack**: List frameworks, libraries, and their specific versions used

### Developer Workflows
- **Build System**: Document exact commands (Make targets, npm scripts, custom shell scripts)
- **Testing Framework**: Specify test runner commands, suite organization, and coverage requirements
- **Development Environment**: Docker setup, local vs containerized workflows, required tools
- **CI/CD Pipeline**: Automation workflows, versioning strategy, deployment procedures

### Project-Specific Conventions
- **File Organization**: Directory structure patterns and component placement rules
- **Naming Conventions**: Files, functions, variables - especially non-standard patterns
- **Code Patterns**: Template systems (Liquid, Jinja), configuration management, error handling approaches
- **Documentation Standards**: Front matter requirements, inline documentation format, README structure

### Integration & Dependencies
- **External Services**: APIs, CDNs, third-party integrations
- **Configuration Management**: Multi-environment setup, secrets handling
- **Cross-Component Patterns**: How modules communicate, shared utilities, common interfaces

## Information Gathering Strategy

### Search Existing AI Conventions
Use semantic search for:
```
**/{.github/copilot-instructions.md,AGENT.md,AGENTS.md,CLAUDE.md,.cursorrules,.windsurfrules,.clinerules,.cursor/rules/**,.windsurf/rules/**,.clinerules/**}
```

### Mine Repository Documentation
Prioritize searching:
- README.md, CONTRIBUTING.md, docs/
- Test directories (reveals implementation patterns)
- Build scripts (scripts/, Makefile, package.json)
- CI/CD configurations (.github/workflows/)
- Example code, quickstart guides
- Configuration files (_config.yml, tsconfig.json, etc.)

### Query for Key Patterns
Use targeted GitHub repo searches for:
- "architecture", "structure", "setup", "development workflow"
- "build", "test", "deploy", "CI/CD"
- "convention", "pattern", "guideline", "best practice"
- Framework-specific terms (Jekyll, React, Django, etc.)

## Output Guidelines

### Structure (Markdown format)
1. **Project Overview** (2-3 sentences)
2. **Architecture & Key Components** (file tree, hierarchy diagrams)
3. **Development Workflows** (exact commands with explanations)
4. **Critical Patterns & Conventions** (with code examples)
5. **Configuration Management** (environment-specific setups)
6. **Project-Specific Conventions** (what makes THIS codebase unique)
7. **Common Development Patterns** (how to add features, fix bugs, etc.)
8. **AI-Specific Guidance** (prompt writing tips, code generation rules)
9. **Quick Reference Links** (key documentation files)

### Content Principles
- **Specificity**: "Use `make test-core` for unit tests" NOT "run tests"
- **Actionability**: Include actual file paths, command examples, code snippets
- **Discoverability**: Focus on patterns you learned FROM the codebase
- **Context**: Explain WHY patterns exist, not just WHAT they are
- **Completeness**: ~200-500 lines for complex projects (not 20-50)
- **Examples**: Pull real examples from the repository

### Intelligent Merging (if file exists)
- Preserve project-specific content and examples
- Update outdated framework versions or deprecated commands
- Add missing critical sections
- Remove generic platitudes
- Maintain author's voice and organization if effective

## Prompt Writing Section (CRITICAL)

Include a section on "AI-Specific Guidance" with:

### Prompt Best Practices
- How to request code that follows project patterns
- Required context to include (files, principles, dependencies)
- Testing expectations for generated code

### Code Generation Rules
- ALWAYS/NEVER patterns specific to this project
- Required documentation format
- Error handling expectations
- Testing requirements

Example template:
```markdown
## AI-Specific Guidance

### Prompt Writing Best Practices
When requesting AI assistance for this project:
1. **Context**: Specify which [framework components] are affected
2. **Patterns**: Reference existing [pattern examples]
3. **Principles**: Mention which [project principles] apply
4. **Testing**: Request test code alongside implementation

### Code Generation Guidelines
ALWAYS:
- Include [required metadata format]
- Use [framework] classes/patterns
- Add error handling for [common failure modes]
- Include inline documentation

NEVER:
- Hardcode values that belong in [config location]
- Create duplicate functionality without checking [location]
```

## Post-Generation Steps

After creating `.github/copilot-instructions.md`:

### 1. Ask User for Direction
Present two clear options:

**Option A: Plant the Seed (MVP Roadmap)**
- Generate minimal viable project structure
- Create foundational files (README, basic config)
- Establish core directory structure
- Set up initial build/test scaffolding

**Option B: Build Upon It (Validate & Enhance)**
- Deploy development environment (Docker/local)
- Run existing test suites to validate understanding
- Identify gaps in documentation
- Create integration examples

### 2. Create Deployment Prompt
Generate `.github/prompts/deploy.prompt.md` with:
- Full context from this task
- Repository URL and analysis summary
- Devcontainer/Docker setup instructions
- Step-by-step deployment workflow
- Validation test commands
- Common troubleshooting scenarios

### 3. Update This Prompt (Meta-Improvement)
Before asking next steps, enhance `forkme.prompt.md` with:
- Specific insights from analyzing this repository
- Patterns that were hard to discover (document search strategies)
- Effective vs ineffective approaches
- Additional sections that would have helped
- Better examples or templates

## Improvements from Practice

### Lessons Learned (Update after each use)
- **Jekyll Projects**: Search for Liquid template patterns, _includes organization, front matter standards
- **Automated Projects**: Look for scripts/ directory, Makefile targets, GitHub Actions
- **Testing Complexity**: Check test/README.md for consolidated framework info
- **Multi-environment**: Always document _config.yml variations and Docker setup
- **Version Management**: Document semantic versioning strategy and CI/CD automation
- **Docker-First Projects**: Prioritize docker-compose.yml and _config_dev.yml for development setup
- **Layout Hierarchies**: Document template inheritance patterns (root → default → specialized)
- **Conventional Commits**: Capture commit message patterns that drive automation (feat:, fix:, BREAKING CHANGE)
- **Multi-Stage Automation**: Map entire CI/CD pipeline from commit to deployment
- **Statistics Systems**: Look for data generation scripts and dashboard components

### Search Strategy Refinements
- Use multiple targeted queries rather than one broad search
- Look for "comprehensive", "guide", "automation", "workflow" in docs
- Check CHANGELOG.md for historical context on architecture decisions
- Mine test files for implied patterns and usage examples
- **Progressive Discovery**: Start with structure → configuration → automation → templates
- **Four-Phase Search**: (1) Repository structure, (2) Build system, (3) CI/CD workflows, (4) Template patterns
- **Documentation Hierarchy**: /docs/ for deep dives, pages/_about/ for features, README.md for quick start
- **Script Analysis**: Read scripts/README.md and individual script headers for automation understanding
- **Workflow Mining**: .github/workflows/ reveals complete automation strategy
- **Layout Documentation**: Check _layouts/README.md for template architecture
- **Include Organization**: Examine _includes/ directory structure for component patterns
- **Data Files**: _data/ directory reveals navigation, statistics, and configuration patterns

### Output Quality Checks
- ✅ Includes actual command examples with flags
- ✅ Shows real file paths and code snippets from repo
- ✅ Explains WHY patterns exist (not just WHAT)
- ✅ Has framework-specific setup (not generic boilerplate)
- ✅ Includes troubleshooting common issues
- ✅ Provides AI prompt writing guidance
- ✅ References key documentation locations
- ✅ Documents layout hierarchy with inheritance patterns
- ✅ Explains automation workflows with trigger conditions
- ✅ Includes Docker setup with platform specifications
- ✅ Maps complete CI/CD pipeline stages
- ✅ Shows semantic versioning strategy with commit conventions
- ✅ Provides quick reference tables for commands and configurations

### Jekyll Theme Specific Insights (2025-01-28)
**Discovery Process**:
1. **Initial Structure**: Start with file tree to understand organization (_layouts/, _includes/, pages/, docs/, scripts/)
2. **Configuration Layer**: Examine _config.yml and _config_dev.yml to understand production vs development setup
3. **Docker Setup**: Review docker-compose.yml for platform requirements (linux/amd64), volume mounts, and livereload
4. **Build System**: Check Makefile and Gemfile for command interface and dependencies
5. **Automation Scripts**: Read scripts/README.md first, then individual scripts for version management, building, testing
6. **CI/CD Workflows**: Analyze .github/workflows/ for automated versioning, testing, and publishing
7. **Template System**: Study _layouts/README.md for inheritance patterns, then examine includes organization
8. **Testing Framework**: Review test/ directory structure and test_runner.sh for suite organization

**Key Patterns Found**:
- **Docker-First Philosophy**: All development via docker-compose, not optional
- **Layered Configs**: _config.yml (production) + _config_dev.yml (dev overrides)
- **Conventional Commits Drive Automation**: feat: → minor, fix: → patch, BREAKING CHANGE → major
- **Three-Tier Docs**: README (quick start) → pages/_about/ (features) → docs/ (deep dive)
- **Layout Inheritance**: root.html → default.html → specialized layouts (journals, collection, stats)
- **Organized Includes**: core/, navigation/, components/, content/, stats/, analytics/
- **Automated Everything**: Version bumping, changelog generation, testing, gem publication, GitHub releases
- **Multi-Ruby Testing**: CI tests on Ruby 2.7, 3.0, 3.1, 3.2 for broad compatibility
- **Keep a Changelog**: Auto-generated from conventional commits in standard format

**Search Queries That Worked Well**:
1. "repository structure architecture README documentation" - Revealed organizational patterns
2. "Jekyll configuration build test development workflow Makefile docker gemspec" - Exposed build system
3. "CI/CD GitHub Actions workflows automation conventional commits" - Uncovered automation details
4. "Liquid templates includes layouts front matter collections" - Documented template patterns

**What Would Have Helped Earlier**:
- Initial check for docker-compose.yml to identify Docker-first projects
- Look for scripts/README.md as entry point to automation documentation
- Search for _layouts/README.md and _includes/ to understand template organization early
- Check for test/ directory structure to understand testing philosophy upfront
- Examine package.json as version source of truth before diving into other files

**Effective Content Structure Discovered**:
1. Project Overview (mission, tech stack, philosophy)
2. Repository Structure (directory tree with annotations)
3. Development Workflows (exact commands, Docker primary)
4. Architecture & Patterns (layout hierarchy, includes organization)
5. Automation Systems (semantic versioning, CI/CD, testing)
6. Content Creation Patterns (front matter, conventions)
7. Styling & Theming (Bootstrap integration, customization)
8. Key Features & Usage (sitemap, statistics, Mermaid, comments)
9. Deployment Strategies (GitHub Pages, Azure, Docker, Netlify)
10. Troubleshooting & Debugging (common issues, diagnostics)
11. Documentation Standards (organization, templates, guidelines)
12. Contributing & Collaboration (Git workflow, commits, releases)
13. Testing Strategies (coverage, writing tests, CI integration)
14. Learning Resources (official docs, project-specific)
15. Security & Best Practices (secrets, dependencies, performance)
16. AI-Assisted Development Guidelines (prompting, code generation, review checklist)
17. Quick Reference (URLs, configs, paths, ports)
18. Getting Help (resources, issue templates)

---

**Execution**: Analyze [repository URL], generate comprehensive instructions, ask for next steps, create deployment prompt, update this file.

Focus on discovering the essential knowledge that would help an AI agents be immediately productive in this codebase. Consider aspects like:
- The "big picture" architecture that requires reading multiple files to understand - major components, service boundaries, data flows, and the "why" behind structural decisions
- Critical developer workflows (builds, tests, debugging) especially commands that aren't obvious from file inspection alone
- Project-specific conventions and patterns that differ from common practices
- Integration points, external dependencies, and cross-component communication patterns

Source existing AI conventions from `**/{.github/copilot-instructions.md,AGENT.md,AGENTS.md,CLAUDE.md,.cursorrules,.windsurfrules,.clinerules,.cursor/rules/**,.windsurf/rules/**,.clinerules/**,README.md}` (do one glob search).

Guidelines (read more at https://aka.ms/vscode-instructions-docs):
- If `.github/copilot-instructions.md` exists, merge intelligently - preserve valuable content while updating outdated sections
- Write concise, actionable instructions (~20-50 lines) using markdown structure
- Include specific examples from the codebase when describing patterns
- Avoid generic advice ("write tests", "handle errors") - focus on THIS project's specific approaches
- Document only discoverable patterns, not aspirational practices
- Reference key files/directories that exemplify important patterns

Update `.github/copilot-instructions.md` for the user. Make sure to include instructions on how to write prompts. Then ask for the next steps to either plant the seed or build upon it.

If to plant the seed, build the MVP (minimal viable product) roadmap.

If to build upon it, then deploy a development environment and run tests to validate the instructions.

Regardless of selection, after building the initial version, create a new prompt file at `.github/prompts/deploy.prompt.md` with the full context of this task for future reference. the deployment prompt should include the deployment instructions to launch the application in a devcontainer.

Before asking for next steps, update the forkme.prompt.md file with improvements to this prompt based on what you learned while completing this task, and write a seed.md file that contains any useful information discovered about the repository that would help future agents.