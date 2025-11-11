# Instructions Directory

## Purpose

This directory contains comprehensive coding instructions and guidelines for AI-assisted development within the barodybroject ecosystem. These instruction files define standards, patterns, and best practices for Django/OpenAI development, ensuring consistent code quality across the project.

## Contents

### Core Instructions

- **`languages.instructions.md`**: Language-specific standards for Python/Django, JavaScript, and Bash development including naming conventions, code structure, error handling, and practical examples

- **`workflows.instructions.md`**: GitHub Actions workflow patterns, CI/CD pipeline standards, container builds, Azure deployments, and automation guidelines

- **`documentation.instructions.md`**: Markdown formatting standards, README requirements, code documentation patterns (docstrings, JSDoc), and API documentation practices

- **`test.instructions.md`**: Testing standards for Django applications including pytest patterns, API testing, UI testing with Playwright, and coverage requirements

- **`features.instructions.md`**: Feature development pipeline for Django/OpenAI applications with comprehensive CI/CD integration and VS Code Copilot optimization

- **`space.instructions.md`**: Workspace organization and project structure guidelines optimized for Django development and VS Code Copilot assistance

- **`posts.instructions.md`**: Technical content creation standards for documenting Django/OpenAI development experiences and sharing knowledge

### Harmonization and Standards

- **`frontmatter.standards.md`**: Unified frontmatter structure and metadata standards for cross-repository consistency and AI optimization

- **`HARMONIZATION_SUMMARY.md`**: Comprehensive summary of instruction file harmonization across IT-Journey ecosystem repositories

- **`ECOSYSTEM_INTEGRATION.md`**: Cross-repository integration guide and shared development patterns for the IT-Journey ecosystem

## Usage

These instruction files guide AI-assisted development and code generation:

```yaml
# AI development context
coding_standards:
  apply_instructions:
    - ../copilot-instructions.md     # Foundation principles and VS Code Copilot optimization
    - languages.instructions.md      # Language-specific patterns
    - workflows.instructions.md      # CI/CD standards
    - documentation.instructions.md  # Documentation practices
    - test.instructions.md           # Testing standards
    - features.instructions.md       # Feature development pipeline
    - space.instructions.md          # Workspace organization
    - posts.instructions.md          # Technical content creation
    - frontmatter.standards.md       # Unified metadata standards
    - ECOSYSTEM_INTEGRATION.md       # Cross-repository integration patterns

development_workflow:
  1. README-FIRST: Review relevant README files for context
  2. Review applicable instruction files for standards
  3. Follow container-first development principles
  4. Apply language-specific coding standards
  5. Implement comprehensive testing strategies
  6. Maintain thorough documentation
  7. README-LAST: Update documentation after changes
```

## Key Features

- **Comprehensive Standards**: Complete development guidelines covering all aspects of the Django/OpenAI project
- **AI Integration**: Designed for AI-assisted development workflows and code generation
- **Container-First**: Emphasis on containerized development and deployment patterns
- **Practical Examples**: Real-world code examples demonstrating best practices
- **Quality Assurance**: Testing, linting, and documentation standards for maintainable code

## Technology Focus

Instructions are optimized for:
- **Django 4.x**: Web framework best practices and conventions
- **OpenAI API**: AI integration patterns with error handling and retry logic
- **PostgreSQL**: Database design and ORM usage
- **Docker**: Containerized development and deployment
- **Azure**: Cloud deployment with Container Apps and Bicep
- **GitHub Actions**: CI/CD automation workflows

## Instruction File Structure

Each instruction file follows this structure:

```yaml
---
file: filename.instructions.md
description: Brief description of content
author: Team name
created: YYYY-MM-DD
lastModified: YYYY-MM-DD
version: X.Y.Z
applyTo: "file patterns"  # Optional
dependencies:
  - other-file.md: Relationship description
containerRequirements:  # If applicable
  baseImage: image:tag
  exposedPorts: ports
  volumes: volume mounts
  environment: required env vars
---

# Content sections with examples
```

## Container Configuration

Instructions are applied within containerized development environments:
- Development container configurations follow instruction file guidelines
- CI/CD pipelines implement standards defined in instruction files
- Code generation and AI assistance follow documented patterns
- Container orchestration scripts adhere to scripting standards

## Related Files

- **`../.github/copilot-instructions.md`**: Main Copilot instructions with project overview, core principles, and general standards
- **`../.github/README.md`**: Overview of the .github directory and its contents

## Contributing

When updating instructions:

1. Ensure changes align with project goals and tech stack
2. Test examples before including them
3. Update version numbers and lastModified dates
4. Keep content concise but comprehensive
5. Focus on practical, actionable guidance
6. Remove outdated or unused patterns

## Version History

- **v1.0.0** (2025-10-11): Consolidated from 11 separate files into 4 focused instruction files, removed AI evolution concepts, added Django/OpenAI specific patterns
