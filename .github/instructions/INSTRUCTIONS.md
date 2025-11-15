---
applyTo: '**/.github/instructions/**'
---

# Repository Custom Instructions for GitHub Copilot

Guide to repository custom instructions for GitHub Copilot - a universal template for AI-assisted development across diverse software projects.

## Overview

This repository provides **universal AI instruction templates** designed to guide GitHub Copilot and AI assistants across various software development efforts: web applications, enterprise systems, libraries, educational platforms, CLI tools, and more. These instructions embody best practices synthesized from multiple project types and can be adapted to specific needs.

### Philosophy

These instructions represent a **comprehensive, evolving template** that:

- Provides universal patterns applicable across domains
- Adapts to different project types (web apps, libraries, educational content, etc.)
- Incorporates principles from enterprise development, educational platforms, and theme development
- Serves as a foundation that teams can customize for their specific needs
- Evolves through continuous improvement and feedback

**Reference:** [GitHub Copilot Custom Instructions Documentation](https://docs.github.com/en/copilot/how-tos/configure-custom-instructions/add-repository-instructions)

## Instruction Files Structure

All instruction files are located in `.github/instructions/` and follow the naming convention: `lowercase-name.instructions.md`

### Instruction Files Architecture

The instruction set is organized into **six focused domains** that cover the complete software development lifecycle:

#### 1. **`core.instructions.md`** - Universal Development Principles

   - **Applies to**: All files (`applyTo: '**/*'`)
   - **Core Principles**: DFF (Design for Failure), DRY (Don't Repeat Yourself), KIS (Keep It Simple), REnO (Release Early and Often), MVP, COLAB, AIPD (AI-Powered Development)
   - **AI Assistance**: Effective prompting patterns, quality gates, human oversight guidelines
   - **Workspace Organization**: Universal directory structures, project-specific adaptations
   - **Project Types**: Patterns for web apps, microservices, libraries, CLI tools, educational platforms
   - **Quality Standards**: Feature development workflow, progressive enhancement, quality checklists

#### 2. **`bash.instructions.md`** - Bash Scripting Standards

   - **Applies to**: Shell scripts (`**/*.sh`, `**/*.bash`, `scripts/**/*`)
   - **Comprehensive Template**: Full script structure with header, logging, error handling, cleanup
   - **Error Handling**: `set -euo pipefail`, traps, signal handlers, cleanup functions (DFF)
   - **Logging Framework**: Multi-level logging, colored output, file logging
   - **Utility Functions**: Retry logic, confirmations, progress indicators, file operations (DRY)
   - **Common Patterns**: Config loading, file processing, parallel execution, API calls, lock files
   - **Security**: Secrets management, input sanitization, permission checking
   - **Testing**: bats unit tests, integration testing patterns
   - **Performance**: Efficient patterns, built-in operations, optimization techniques

#### 3. **`development.instructions.md`** - Code and Workflow Standards

   - **Applies to**: Source code files and CI/CD workflows
   - **Languages**: Python (type hints, docstrings), JavaScript/TypeScript (ES6+, async/await)
   - **Error Handling**: Comprehensive patterns for each language
   - **Testing**: Pytest, Jest, RSpec patterns with fixtures and mocking
   - **Service Architecture**: Service layer patterns for complex business logic
   - **API Development**: RESTful API design, request/response patterns
   - **Security**: Input validation, environment configuration, security checklists
   - **Containers**: Docker, Docker Compose, multi-stage builds

#### 4. **`documentation.instructions.md`** - Documentation Standards

   - **Applies to**: Markdown and documentation files
   - **Documentation Types**: Project README, directory README, API docs, educational content
   - **Code Documentation**: Python docstrings (Google style), JSDoc, inline comments
   - **Accessibility**: Alt text, semantic structure, screen reader support
   - **Tools**: Markdown linting, link checking, spell checking, doc generation
   - **Educational Content**: Learning objectives, step-by-step tutorials, validation methods
   - **Maintenance**: Automated validation, continuous updates, freshness management

#### 5. **`version-control.instructions.md`** - Version Control and Release Management

   - **Applies to**: Changelogs, version files, package manifests
   - **Git Workflows**: Git Flow, GitHub Flow, branch strategies
   - **Semantic Versioning**: MAJOR.MINOR.PATCH rules, prerelease versions
   - **Commit Messages**: Conventional commits format with types and scopes
   - **Release Process**: Pre-release checklist, automated releases, hotfix procedures
   - **GitHub Actions**: Version bump workflows, release automation
   - **Package Publishing**: PyPI, NPM, RubyGems patterns
   - **Security**: Signed commits, access control, dependency security

#### 6. **`tools.instructions.md`** - Development Tools and Automation

   - **Applies to**: Tool configuration files
   - **AI Toolkit**: Agent development best practices, tracing, evaluation
   - **Code Quality**: Linters (ESLint, Flake8), formatters (Prettier, Black)
   - **Testing Tools**: pytest, Jest, RSpec, coverage tools
   - **Containers**: Docker, Docker Compose, VS Code Dev Containers
   - **Linting Configuration**: Pre-commit hooks, EditorConfig, language-specific configs
   - **CI/CD**: Reusable workflows, Makefile automation
   - **Monitoring**: Logging configuration, health checks, observability

## Instruction File Format

Per [GitHub Copilot's official documentation](https://docs.github.com/en/copilot/how-tos/configure-custom-instructions/add-repository-instructions), path-specific instruction files should use minimal frontmatter:

```yaml
---
applyTo: 'glob-patterns-for-file-matching'
---

# Instruction Title

Brief description of the instruction's purpose and scope.

## Content Sections

[Comprehensive guidance, patterns, and examples]

---

**Version:** X.Y.Z | **Last Modified:** YYYY-MM-DD | **Author:** Team/Individual

**Purpose:** Brief statement of the instruction's intended use and adaptability.
```

### Frontmatter Standards

- **`applyTo`** (required): Glob patterns (single-quoted) for file matching
- **All other metadata**: Moved to document footer for clean, standards-compliant frontmatter
- **Footer format**: Version, last modified date, author, and purpose statement

### ApplyTo Pattern Examples

The `applyTo` field uses glob patterns to match files:

- `'**'` - Applies to all files
- `'**/*.py,**/*.js'` - Applies to Python and JavaScript files
- `'**/*.md,**/README.md'` - Applies to markdown files
- `'**/.github/workflows/*.yml'` - Applies to GitHub Actions workflows

**Note:** Use single quotes for the `applyTo` field value.

## How Instructions Work

### Automatic Application

GitHub Copilot automatically applies instructions based on:

1. **File matching**: The `applyTo` glob patterns determine which files trigger each instruction
2. **Context awareness**: Instructions are applied when editing files that match the patterns
3. **Priority**: More specific patterns take precedence over general ones

### Instruction Priority

When multiple instructions could apply:

1. **Path-specific instructions** (`.github/instructions/*.instructions.md`) - Most specific
2. **Repository-wide instructions** (`.github/copilot-instructions.md`) - General fallback
3. **Organization instructions** - Broader scope
4. **Personal instructions** - User-specific

### Usage in Copilot Chat

When using Copilot Chat:

1. Attach the repository to your chat session
2. Copilot will reference relevant instruction files based on context
3. Check response references to see which instructions were used
4. Instructions apply automatically - no manual selection needed

## Creating New Instructions

### Step 1: Create the File

Create a new file in `.github/instructions/` following the naming convention:

```bash
.github/instructions/your-topic.instructions.md
```

### Step 2: Add Frontmatter

```yaml
---
description: What this instruction file covers
version: 1.0.0
lastModified: 2025-01-27
applyTo: '**/*.ext,**/pattern/**'
---
```

### Step 3: Write Content

Add clear, actionable guidance:

- Use headings for organization
- Include code examples
- Be specific and practical
- Keep content concise

### Step 4: Update README

Add the new file to `.github/instructions/README.md` in the Contents section.

## Universal Patterns from Multiple Project Types

These instructions synthesize best practices from:

### Enterprise Development (ERP, Financial Systems)

- Service layer architecture for complex business logic
- Multi-stage validation and error handling
- Database optimization patterns (N+1 prevention, indexing)
- Integration patterns for external systems
- Compliance and security frameworks

### Web Application Development (Django, Rails, Express)

- MVC/MVT architectural patterns
- ORM best practices and migration management
- API design (RESTful, GraphQL)
- Authentication and authorization
- Frontend integration patterns

### Educational and Content Platforms (Jekyll, Learning Management)

- Progressive learning and skill development
- Multi-platform compatibility (macOS, Windows, Linux)
- Accessibility-first design
- Clear learning objectives and validation
- Community engagement patterns

### Theme and UI Development (Bootstrap, React, Angular)

- Responsive design patterns
- Component-based architecture
- Accessibility standards (ARIA, semantic HTML)
- Performance optimization
- Browser compatibility

### Library and Package Development (Python, NPM, Ruby Gems)

- Clear public APIs with comprehensive documentation
- Minimal dependencies and version constraints
- Semantic versioning and release automation
- Usage examples and migration guides
- Cross-platform support

## Best Practices for Using These Instructions

### For AI Assistants

**Context Loading:**

1. Identify the file type and project context
2. Load relevant instruction files based on `applyTo` patterns
3. Apply guidelines while maintaining flexibility for project-specific needs
4. Suggest improvements aligned with universal principles
5. Validate against quality standards before proposing solutions

**Adaptation Strategy:**

- Start with universal patterns from these instructions
- Adapt to project-specific requirements when needed
- Suggest best practices from similar project types
- Maintain consistency with established project conventions
- Learn from project history and existing code

### For Human Developers

**Using Instructions Effectively:**

1. Review relevant instruction files before starting work
2. Use AI prompting patterns for better Copilot assistance
3. Apply quality gates to AI-generated code
4. Customize instructions for project-specific needs
5. Contribute improvements back to the template

**Customizing for Your Project:**

- Fork these instructions as a starting point
- Add project-specific patterns and conventions
- Remove sections not applicable to your domain
- Extend with framework-specific guidelines
- Document customizations and rationale

### Content Guidelines

- **Be Comprehensive Yet Concise**: Cover important patterns without overwhelming detail
- **Use Practical Examples**: Real, working code examples from multiple domains
- **Stay Technology-Agnostic**: Provide patterns for multiple languages/frameworks
- **Maintain Currency**: Update as tools and practices evolve
- **Avoid Redundancy**: Cross-reference instead of duplicating
- **Think Template-First**: Write for reusability across projects

### ApplyTo Pattern Best Practices

- **Be Specific**: Target exact file types that benefit from each instruction
- **Avoid Overlap**: Ensure patterns complement rather than conflict
- **Repository-Scoped**: Patterns apply within repository boundaries
- **Test Coverage**: Verify patterns match intended files
- **Use Single Quotes**: Always quote glob patterns with single quotes

**Pattern Examples:**

```yaml
applyTo: '**/*'                          # All files
applyTo: '**/*.py,**/*.js,**/*.ts'      # Multiple languages
applyTo: 'src/**/*.py'                   # Specific directory
applyTo: '.github/workflows/*.yml'       # Configuration files
applyTo: 'docs/**/*.md,**/README.md'     # Documentation
```

## Maintenance

### Regular Updates

- Review instructions quarterly for relevance
- Update examples when tools or practices change
- Remove outdated patterns or guidance
- Update `lastModified` dates when making changes

### Version Management

- Use semantic versioning (MAJOR.MINOR.PATCH)
- Increment version when making significant changes
- Document changes in commit messages

### Testing

- Verify instructions apply to intended files
- Test with Copilot Chat to ensure proper context
- Check that examples are still valid
- Validate YAML frontmatter syntax

## IDE-Specific Setup

### VS Code

1. Instructions apply automatically when repository is open
2. Enable in Settings: Search for "instruction file"
3. Verify in Copilot Chat responses

### JetBrains IDEs

1. Supports `.github/copilot-instructions.md` for repository-wide
2. Path-specific instructions in `.github/instructions/` work automatically
3. Check Settings > Tools > GitHub Copilot > Customizations

### GitHub.com (Copilot Chat)

1. Attach repository to chat session
2. Instructions apply automatically
3. Check response references to see which files were used

## Troubleshooting

### Instructions Not Applying

- Verify file naming: Must end with `.instructions.md`
- Check `applyTo` patterns: Ensure they match your files
- Validate YAML frontmatter: Check for syntax errors
- Confirm file location: Must be in `.github/instructions/`

### Pattern Matching Issues

- Test glob patterns: Use tools to verify pattern matching
- Check for typos: Single quotes, correct paths
- Review pattern specificity: More specific patterns may override

### Content Not Effective

- Simplify language: AI agents process concise content better
- Add examples: Concrete examples improve understanding
- Remove redundancy: Duplicate information adds noise
- Update regularly: Keep content current with best practices

## Related Resources

- [GitHub Copilot Custom Instructions Docs](https://docs.github.com/en/copilot/how-tos/configure-custom-instructions/add-repository-instructions)
- [`.github/instructions/README.md`](./README.md) - Overview of instruction files
- [`.github/instructions/core.instructions.md`](./core.instructions.md) - Core principles

## Adaptation Guide for Different Project Types

### Web Applications

- Use `core.instructions.md` for philosophy and AI assistance
- Apply `development.instructions.md` for backend/frontend patterns
- Reference API development and service layer sections
- Follow security and validation guidelines

### CLI Tools and Scripts

- Focus on bash patterns from `development.instructions.md`
- Use script organization from `tools.instructions.md`
- Apply error handling and logging patterns
- Follow naming conventions and documentation standards

### Libraries and Packages

- Emphasize public API design and documentation
- Apply strict semantic versioning from `version-control.instructions.md`
- Focus on testing patterns and coverage
- Use packaging and publishing automation

### Educational Platforms

- Apply progressive learning patterns
- Use educational documentation templates
- Include multiple platform implementations
- Focus on accessibility and inclusivity

### Enterprise Systems

- Apply service layer architecture patterns
- Use comprehensive error handling
- Focus on integration patterns
- Emphasize security and compliance

## Continuous Evolution

These instructions are designed to evolve:

### Contributing Improvements

If you discover better patterns or practices:

1. Test the pattern in real projects
2. Document with clear examples
3. Ensure universal applicability
4. Submit as pull request or issue
5. Include rationale and use cases

### Versioning Strategy

**MAJOR (X.0.0)**: Fundamental changes to instruction philosophy or structure
**MINOR (0.X.0)**: New sections, patterns, or significant enhancements
**PATCH (0.0.X)**: Clarifications, fixes, example improvements

### Feedback Loop

- Monitor AI assistant effectiveness with these instructions
- Collect feedback from developers using the templates
- Review emerging best practices quarterly
- Update based on new framework releases and tools
- Archive deprecated patterns with migration guides

## Version History

- **v3.0.0** (2025-11-14): Comprehensive enhancement incorporating patterns from Django/OpenAI, educational platforms, Jekyll themes, and enterprise systems. Added universal principles (DFF, DRY, KIS, REnO, MVP, COLAB, AIPD), expanded language coverage, added service layer and API patterns, enhanced testing and container sections, improved AI prompting patterns.
- **v2.0.0** (2025-01-27): Consolidated from 14 files into 5 focused instruction files, standardized naming to lowercase with `.instructions.md` suffix, added `applyTo` fields for path-specific application.

---

**Version:** 3.0.0 | **Last Modified:** 2025-11-14 | **Author:** Amr Abdel-Motaleb

**Purpose:** Universal AI instruction template providing comprehensive, adaptable guidance for GitHub Copilot across diverse software development efforts.
