---
applyTo: '**/*'
---

# Core Development Principles

Core development principles and AI assistance guidelines for software development and DevOps.

## Overview

This repository serves as a home directory for software development and DevOps resources. These instructions provide universal principles and patterns that can be adapted to various software development efforts, from web applications to enterprise systems, from educational platforms to theme development.

## Core Development Philosophy

### Universal Principles

- **DFF (Design for Failure)**: Anticipate and handle errors gracefully; build robust error handling into every component
- **DRY (Don't Repeat Yourself)**: Avoid code and configuration duplication; create reusable components and shared libraries
- **KIS (Keep It Simple)**: Favor simplicity over complexity; choose the straightforward solution unless complexity is justified
- **REnO (Release Early and Often)**: Iterate rapidly with small, incremental releases; gather feedback continuously
- **MVP (Minimum Viable Product)**: Start with essential features and expand based on actual needs and usage
- **COLAB (Collaboration)**: Build for team collaboration; welcome contributions and make processes transparent
- **AIPD (AI-Powered Development)**: Leverage AI as an augmentation partner, not a replacement for human judgment

### AI Assistance Philosophy

- **AI as Partner**: Use AI to augment human developers, enhance productivity, and accelerate learning
- **Human Oversight**: Always review and validate AI-generated content, code, and suggestions
- **Continuous Learning**: AI and humans learn together; feedback loops improve both
- **Context Awareness**: Provide rich context to AI for better assistance
- **Quality Gates**: Establish verification criteria before accepting AI suggestions
- **Ethical Use**: Use AI responsibly, respecting privacy, security, and intellectual property

### Development Values

- **Consistency**: Maintain uniform coding standards, naming conventions, and patterns across projects
- **Documentation First**: Document features, APIs, and architecture before or alongside implementation
- **Test-Driven**: Write tests as you develop; aim for comprehensive coverage of critical paths
- **Container-First**: Prefer containerized development and deployment for reproducibility and portability
- **Security by Design**: Build security into every layer; never treat it as an afterthought
- **Accessibility**: Design for all users; ensure content and interfaces are universally accessible

## Workspace Organization

### Universal Directory Structure

Every project should maintain clear organization:

- **`src/` or `app/`**: Application source code
- **`tests/` or `spec/`**: Test suites and test data
- **`docs/`**: Documentation, guides, and architecture diagrams
- **`scripts/`**: Automation scripts, build tools, and utilities
- **`.github/`**: GitHub workflows, issue templates, and AI instructions
- **`config/`**: Configuration files and environment settings
- **`assets/` or `static/`**: Static resources (images, CSS, JavaScript)

### Project-Specific Adaptations

**Web Applications:**
```
project/
├── src/              # Application code
│   ├── backend/      # Server-side code
│   ├── frontend/     # Client-side code
│   └── shared/       # Shared utilities
├── tests/            # Test suites
├── docs/             # Documentation
└── .github/          # CI/CD and instructions
```

**Microservices:**
```
project/
├── services/         # Individual microservices
│   ├── service-a/
│   ├── service-b/
│   └── shared/
├── infra/            # Infrastructure as code
├── tests/            # Integration tests
└── docs/             # Architecture docs
```

**Libraries/Packages:**
```
project/
├── lib/              # Library source code
├── tests/            # Test suite
├── examples/         # Usage examples
├── docs/             # API documentation
└── scripts/          # Build and release scripts
```

## Language Guidelines

### General

- Use automated formatters (Prettier, Black, RuboCop)
- Use clear, descriptive names
- Implement robust error handling
- Don't suppress errors silently

### Python

- Follow PEP 8
- Use type hints for function signatures
- Write Google-style docstrings for public APIs
- Use `black` for formatting, `flake8` for linting

### JavaScript/TypeScript

- Use `prettier` for formatting, `eslint` for linting
- Prefer TypeScript over plain JavaScript
- Use ES Modules (`import`/`export`)

### Bash/Shell

- Use `set -euo pipefail` at script start
- Quote all variable expansions
- Use `readonly` for constants
- Provide meaningful error messages

## Documentation Standards

- Every directory should have a `README.md` explaining purpose and usage
- Use comments to explain *why*, not *what*
- Generate API documentation from source code comments
- Keep documentation current with code changes

## Testing Standards

- **Unit Tests**: Test individual functions and classes
- **Integration Tests**: Test component interactions
- **End-to-End Tests**: Test complete workflows
- **Coverage**: Aim for high coverage without sacrificing quality

## CI/CD Workflows

- **On Pull Request**: Run linters, formatters, and tests
- **On Merge to Main**: Deploy to staging
- **On Release**: Publish packages or deploy to production

## AI-Assisted Development Workflows

### Effective AI Prompting Patterns

**Code Generation Pattern:**
```markdown
Generate a [language] [component type] for [specific purpose] that:
- Follows [framework/style guide] conventions
- Includes comprehensive error handling (DFF)
- Implements [specific functionality] with [constraints]
- Uses [design pattern] if applicable
- Includes type hints/annotations
- Has docstrings/JSDoc with examples
- Follows DRY and KIS principles
```

**Test Generation Pattern:**
```markdown
Generate comprehensive tests for [component] that:
- Cover happy path scenarios
- Test edge cases: [list specific edges]
- Test error conditions: [list specific errors]
- Use [testing framework] with proper fixtures
- Include integration tests for [interactions]
- Aim for >80% coverage of critical paths
- Follow AAA pattern (Arrange, Act, Assert)
```

**Documentation Generation Pattern:**
```markdown
Generate documentation for [component/feature] that:
- Explains purpose and use cases
- Includes setup/installation instructions
- Provides practical code examples
- Documents API/interface specifications
- Covers common troubleshooting scenarios
- Links to related resources
- Follows project documentation standards
```

**Refactoring Pattern:**
```markdown
Refactor [code/module] to:
- Improve [specific aspect: readability/performance/maintainability]
- Apply [design pattern/principle]
- Maintain existing functionality (with tests)
- Follow DRY principle by [specific approach]
- Simplify [complex section] (KIS)
- Add error handling where missing (DFF)
- Explain trade-offs of refactoring approach
```

**Architecture Design Pattern:**
```markdown
Design [system/component] architecture that:
- Solves [specific problem/requirement]
- Follows [architectural pattern: MVC/microservices/etc]
- Considers scalability: [specific requirements]
- Includes error handling strategy (DFF)
- Plans for testing: [unit/integration/e2e]
- Supports [deployment strategy]
- Documents trade-offs and design decisions
```

### AI Assistance Best Practices

**Quality Gates Before Accepting AI Suggestions:**
- [ ] **Correctness**: Does it work as intended? Are there logical errors?
- [ ] **Security**: Any vulnerabilities, injection risks, or data leaks?
- [ ] **Performance**: Is the approach efficient? Any obvious bottlenecks?
- [ ] **Maintainability**: Is code readable and well-structured?
- [ ] **Standards**: Does it follow project conventions and style guides?
- [ ] **Completeness**: Are edge cases and error conditions handled?
- [ ] **Documentation**: Are complex parts explained?

**When to Request Human Review:**
- Security-sensitive operations (authentication, data access, encryption)
- Performance-critical code (algorithms, database queries, API calls)
- Breaking changes or major architectural decisions
- Complex business logic requiring domain expertise
- Integration with external systems or third-party APIs

## Feature Development Workflow

### README-FIRST Approach

1. **Start with README**: Review existing README files for context and architecture
2. **Plan**: Define requirements, acceptance criteria, and success metrics
3. **Design**: Create architecture diagrams and interface specifications
4. **Implement**: Follow coding standards with AI assistance
5. **Test**: Write comprehensive tests (unit, integration, e2e)
6. **Document**: Update documentation alongside code
7. **Review**: Conduct code review with peers
8. **README-LAST**: Update README with new features and changes

### Progressive Enhancement

- Start with MVP (Minimum Viable Product)
- Release early and often (REnO)
- Iterate based on feedback
- Maintain backward compatibility when possible
- Document breaking changes clearly

### Quality Assurance Checklist

Before considering any feature complete:
- [ ] Code follows project standards and conventions
- [ ] Comprehensive tests written and passing
- [ ] Documentation updated (README, API docs, inline comments)
- [ ] Error handling implemented (DFF)
- [ ] Security reviewed (no vulnerabilities, proper validation)
- [ ] Performance acceptable (no obvious bottlenecks)
- [ ] Accessibility considered (if user-facing)
- [ ] CI/CD pipeline passing
- [ ] Peer review completed

## Project Type Adaptations

### Web Applications
- Follow MVC or similar architectural patterns
- Implement service layers for business logic
- Use ORM/query builders instead of raw SQL
- Implement proper authentication and authorization
- Design RESTful or GraphQL APIs
- Consider frontend framework best practices

### CLI Tools
- Implement clear command structure and help text
- Provide verbose and quiet modes
- Use configuration files for complex settings
- Follow platform conventions (exit codes, signals)
- Include shell completion scripts

### Libraries/Packages
- Design clear, intuitive public APIs
- Minimize dependencies
- Provide comprehensive documentation
- Include usage examples
- Follow language-specific package conventions
- Maintain semantic versioning strictly

### Data Processing/Analytics
- Implement data validation and sanitization
- Use appropriate data structures for scale
- Consider memory and performance implications
- Provide data quality metrics
- Document data schemas and transformations

### Educational/Content Platforms
- Design for multiple learning styles
- Provide clear learning objectives
- Include hands-on examples and exercises
- Support progressive skill development
- Ensure accessibility for all learners

---

**Version:** 3.0.0 | **Last Modified:** 2025-11-14 | **Author:** Amr Abdel-Motaleb

**Purpose:** Universal template for core development principles applicable to any software development effort, from web applications to enterprise systems.
