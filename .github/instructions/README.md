# Instructions Directory

## Purpose

This directory contains **universal AI instruction templates** for GitHub Copilot and AI-assisted development. These instructions synthesize best practices from multiple project types—web applications, enterprise systems, educational platforms, theme development, and libraries—to create comprehensive, adaptable guidance for diverse software development efforts.

### What Makes These Instructions Universal

These instructions are designed as **evolving templates** that:

- **Adapt Across Domains**: Applicable to web apps, CLI tools, libraries, educational content, enterprise systems
- **Synthesize Best Practices**: Incorporate patterns from Django/OpenAI development, Jekyll themes, gamified learning platforms, and enterprise ERP systems
- **Support Various Languages**: Python, JavaScript/TypeScript, Bash, Ruby, and general patterns
- **Enable AI Partnership**: Optimized prompting patterns and quality gates for effective AI assistance
- **Encourage Evolution**: Designed to grow and improve through continuous feedback

## Core Instruction Files

### 1. `core.instructions.md` - Universal Development Principles

**Applies to**: All files in the repository

**Key Content:**

- Universal principles: DFF (Design for Failure), DRY, KIS, REnO, MVP, COLAB, AIPD
- AI assistance philosophy and partnership model
- Workspace organization for various project types
- Project-specific adaptations (web apps, microservices, libraries, CLI tools, educational platforms)
- Quality assurance checklists and feature development workflows
- Effective AI prompting patterns with quality gates

**When to Reference:**

- Starting any new feature or project
- Onboarding team members or AI assistants
- Making architectural decisions
- Establishing project standards

### 2. `bash.instructions.md` - Bash Scripting Standards

**Applies to**: Shell scripts (`**/*.sh`, `**/*.bash`, `scripts/**/*`)

**Key Content:**

- Comprehensive script template with full header documentation
- Styling standards: file organization, naming conventions, indentation
- Error handling patterns: `set -euo pipefail`, traps, cleanup functions
- Logging framework: multiple log levels, colored output, file logging
- Validation and prerequisites checking
- Reusable utility functions (DRY): retry logic, confirmations, progress indicators
- Common patterns: config loading, file processing, parallel execution, API calls
- Security best practices: secrets management, input sanitization
- Testing approaches: bats unit tests, integration testing
- Performance optimization: efficient patterns, built-in operations

**When to Reference:**

- Writing automation scripts
- Creating build or deployment scripts
- Developing CLI utilities in bash
- Implementing DevOps automation
- Need robust error handling and logging

### 3. `development.instructions.md` - Code and Workflow Standards

**Applies to**: Source code files and CI/CD workflows

**Key Content:**

- Language-specific standards: Python, JavaScript/TypeScript, Bash
- Comprehensive error handling patterns for each language
- Testing frameworks: pytest, Jest, RSpec with fixtures and mocking
- Service layer architecture for complex business logic
- RESTful API development patterns
- Security best practices: input validation, environment config, security checklists
- Container development: Docker, Docker Compose, multi-stage builds
- CI/CD workflow patterns

**When to Reference:**

- Writing or reviewing code in any supported language
- Implementing new features or services
- Setting up testing infrastructure
- Designing APIs or service layers
- Configuring CI/CD pipelines

### 4. `documentation.instructions.md` - Documentation Standards

**Applies to**: Markdown and documentation files

**Key Content:**

- README templates: project-level, directory-level
- Code documentation: Python docstrings, JSDoc, inline comments
- Educational content patterns: tutorials, learning objectives, validation
- API documentation standards
- Accessibility guidelines: alt text, semantic structure, screen reader support
- Automated validation tools: linting, link checking, spell checking
- Documentation generation: Sphinx, JSDoc, TypeDoc

**When to Reference:**

- Creating or updating README files
- Writing code comments and docstrings
- Documenting APIs or public interfaces
- Creating tutorials or educational content
- Ensuring documentation accessibility

### 5. `version-control.instructions.md` - Version Control and Release Management

**Applies to**: Changelogs, version files, package manifests

**Key Content:**

- Git workflows: Git Flow, GitHub Flow, branch strategies
- Semantic versioning (SemVer) rules and prerelease versions
- Conventional commit message format
- Release process: pre-release checklist, automated releases, hotfixes
- GitHub Actions: version bump and release automation
- Package publishing: PyPI, NPM, RubyGems patterns
- Security: signed commits, access control, dependency security

**When to Reference:**

- Planning releases or version bumps
- Setting up release automation
- Managing changelogs
- Publishing packages
- Implementing hotfixes

### 6. `tools.instructions.md` - Development Tools and Automation

**Applies to**: Tool configuration files

**Key Content:**

- AI toolkit for agent development
- Code quality tools: linters, formatters, type checkers
- Testing tools across languages
- Container development: Docker, Docker Compose, Dev Containers
- Linting configuration: pre-commit hooks, EditorConfig
- CI/CD automation: reusable workflows, Makefile patterns
- Monitoring and observability: logging, health checks
- Script organization and best practices

**When to Reference:**

- Setting up development environment
- Configuring linters and formatters
- Creating automation scripts
- Implementing CI/CD workflows
- Setting up monitoring and logging

## Usage

### For AI Assistants (GitHub Copilot)

GitHub Copilot automatically applies these instructions based on file patterns. When editing files:

1. **Context Loading**: Copilot loads relevant instructions based on `applyTo` patterns
2. **Pattern Matching**: More specific patterns take precedence
3. **Adaptive Guidance**: Instructions adapt to project context
4. **Quality Validation**: AI suggestions follow established patterns

### For Human Developers

**README-FIRST Workflow:**

```yaml
development_workflow:
  1. README-FIRST: Review project README and relevant instruction files
  2. Plan: Define requirements using patterns from core.instructions.md
  3. Implement: Follow development.instructions.md standards
  4. Test: Apply testing patterns from development section
  5. Document: Use documentation.instructions.md templates
  6. Version: Follow version-control.instructions.md for releases
  7. Automate: Reference tools.instructions.md for tooling
  8. README-LAST: Update documentation with changes
```

**AI Prompting Strategy:**

```markdown
# Effective Copilot prompts reference core principles:
"Generate a [component] that follows DFF (error handling), 
DRY (reusable), and KIS (simple) principles, with comprehensive 
tests and documentation."
```

## Key Features

### Universal Applicability

- **Multi-Domain**: Web apps, enterprise systems, libraries, educational content, CLI tools
- **Multi-Language**: Python, JavaScript/TypeScript, Bash, Ruby, with extensible patterns
- **Multi-Framework**: Django, Flask, Express, Rails, Next.js, and framework-agnostic patterns

### Comprehensive Coverage

- **Architecture**: Service layers, API design, microservices, MVC patterns
- **Testing**: Unit, integration, e2e tests with pytest, Jest, RSpec patterns
- **Documentation**: README templates, API docs, educational content, accessibility
- **Automation**: CI/CD workflows, pre-commit hooks, release automation
- **Security**: Input validation, environment config, dependency scanning

### AI Optimization

- **Prompting Patterns**: Proven templates for code, tests, docs, architecture
- **Quality Gates**: Checklists before accepting AI suggestions
- **Context Awareness**: Rich context for better AI assistance
- **Human Oversight**: Clear guidelines for when to request human review

### Adaptability

- **Template-Based**: Start with universal patterns, customize for specific needs
- **Project-Specific**: Guidelines for adapting to web apps, libraries, etc.
- **Continuous Evolution**: Versioned with clear upgrade paths
- **Community-Driven**: Welcomes improvements and contributions

## Technology Coverage

### Languages

- Python (type hints, docstrings, pytest)
- JavaScript/TypeScript (ES6+, async/await, Jest)
- Bash (robust scripting, error handling)
- Ruby (conventions for gems and Rails)
- Extensible to additional languages

### Frameworks and Tools

- **Web**: Django, Flask, Express, Rails, Next.js patterns
- **Testing**: pytest, Jest, RSpec, Playwright
- **Containers**: Docker, Docker Compose, Dev Containers
- **CI/CD**: GitHub Actions, automated testing and deployment
- **Documentation**: Sphinx, JSDoc, TypeDoc, Markdown tools

## Instruction File Format

Following [GitHub Copilot documentation](https://docs.github.com/en/copilot/how-tos/configure-custom-instructions/add-repository-instructions):

```yaml
---
applyTo: 'glob-patterns'  # Required: file matching patterns (single quotes)
---

# Instruction Title

Brief description and scope.

## Content Sections

[Comprehensive patterns, examples, and best practices]

---

**Version:** X.Y.Z | **Last Modified:** YYYY-MM-DD | **Author:** Name

**Purpose:** Statement of instruction's adaptability and use cases.
```

**Key Points:**

- Only `applyTo` in frontmatter (per GitHub Copilot spec)
- All metadata in document footer
- Single quotes for glob patterns
- Version tracking for evolution management

## How to Use These Templates

### For New Projects

1. **Copy the `.github/instructions/` directory** to your project
2. **Review each instruction file** and remove sections not applicable
3. **Customize `applyTo` patterns** to match your project structure
4. **Add project-specific sections** as needed
5. **Update version and author** information
6. **Test with GitHub Copilot** to ensure effectiveness

### For Existing Projects

1. **Audit current practices** against instruction templates
2. **Identify gaps** in standards or documentation
3. **Incrementally adopt** relevant sections
4. **Customize for your stack** (add framework-specific patterns)
5. **Train team** on new standards and AI assistance patterns

### For Different Project Types

**Web Applications**: Focus on API, service layer, testing patterns
**CLI Tools**: Emphasize bash scripting, error handling, help documentation
**Libraries**: Prioritize API design, testing, version control, documentation
**Educational Content**: Use progressive learning, accessibility, multi-platform patterns
**Enterprise Systems**: Apply service layers, integration patterns, security frameworks

## Contributing to Templates

### Improvement Process

When you discover better patterns:

1. **Test thoroughly** in real projects (minimum 2-3 implementations)
2. **Ensure universality** (applicable across multiple project types)
3. **Document with examples** (real code, not pseudocode)
4. **Explain rationale** (why this pattern is better)
5. **Submit PR** with clear description of improvement
6. **Include use cases** (which project types benefit most)

### Quality Standards for Contributions

- Maintains consistency with existing instruction style
- Includes working code examples
- Documents trade-offs and alternatives
- Considers multiple languages/frameworks
- Follows DFF, DRY, KIS principles
- Enhances AI assistant effectiveness

## Versioning and Evolution

### Version Strategy

- **MAJOR (3.0.0)**: New principles, restructured approach, breaking changes
- **MINOR (3.1.0)**: New patterns, additional languages, significant enhancements
- **PATCH (3.0.1)**: Bug fixes, clarifications, example improvements

### Changelog

- **v3.0.0** (2025-11-14): Comprehensive enhancement synthesizing patterns from Django/OpenAI systems, educational platforms (IT-Journey), Jekyll theme development (Zer0-Mistakes), and enterprise ERP systems. Added universal principles (DFF, DRY, KIS, REnO, MVP, COLAB, AIPD), expanded language coverage, comprehensive service layer and API patterns, enhanced testing and container sections, improved AI prompting patterns, and template-based approach for adaptability.
- **v2.0.0** (2025-01-27): Consolidated from 14 files into 5 focused domains, standardized naming to lowercase with `.instructions.md` suffix, added `applyTo` fields for path-specific application.
- **v1.0.0** (2024): Initial instruction set for home directory tooling

## Related Resources

- [GitHub Copilot Custom Instructions Documentation](https://docs.github.com/en/copilot/how-tos/configure-custom-instructions/add-repository-instructions)
- [`instructions.md`](./instructions.md) - Comprehensive guide to using these templates
- [Main Repository README](../../README.md) - Project overview

---

**Maintained by**: Amr Abdel-Motaleb  
**Purpose**: Universal AI instruction templates for diverse software development efforts  
**Status**: Active, continuously evolving  
**License**: MIT (use freely, contribute improvements)
