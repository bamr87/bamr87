# AI Agent Prompts Directory

## Purpose

This directory contains **comprehensive AI agent prompts** designed to work with the universal instruction templates in `.github/instructions/`. These prompts provide specialized AI assistance for various software development tasks, from feature development to documentation to release management.

## Available Prompts

### Development Lifecycle Prompts

#### 1. `/develop` - Development Assistant

**File**: [`develop.prompt.md`](./develop.prompt.md)

**Purpose**: Guides feature implementation following universal principles (DFF, DRY, KIS, REnO, MVP, COLAB, AIPD)

**Use When**:
- Implementing new features
- Building new components
- Creating services or APIs
- Need structured development workflow

**Key Features**:
- README-FIRST workflow (Plan → Design → Implement → Test → Document → Review → README-LAST)
- Language-specific code generation (Python, JavaScript/TypeScript, Bash)
- Comprehensive error handling (DFF)
- Service layer architecture patterns
- API development templates
- Container development patterns

**Typical Usage**:
```
/develop I need to build a user authentication service with JWT tokens
```

#### 2. `/test` - Testing Assistant

**File**: [`test.prompt.md`](./test.prompt.md)

**Purpose**: Creates comprehensive test suites following TDD principles

**Use When**:
- Writing tests for new code
- Improving test coverage
- Creating integration tests
- Need test fixtures and mocking

**Key Features**:
- Test pyramid guidance (unit, integration, e2e)
- Pytest and Jest patterns
- AAA pattern (Arrange-Act-Assert)
- Comprehensive coverage (happy path, edge cases, errors)
- Mocking and fixture patterns
- Performance testing

**Typical Usage**:
```
/test I need tests for the UserService class with comprehensive error coverage
```

#### 3. `/document` - Documentation Assistant

**File**: [`document.prompt.md`](./document.prompt.md)

**Purpose**: Creates comprehensive, accessible documentation

**Use When**:
- Writing README files
- Documenting APIs
- Creating tutorials
- Adding code documentation
- Need accessibility compliance

**Key Features**:
- Multiple documentation types (README, API, tutorial, code)
- Accessibility guidelines
- Educational content patterns
- API documentation templates
- Code documentation (docstrings, JSDoc)
- Automated validation tools

**Typical Usage**:
```
/document I need a comprehensive README for my new library project
```

#### 4. `/review` - Code Review Assistant

**File**: [`review.prompt.md`](./review.prompt.md)

**Purpose**: Conducts thorough, constructive code reviews

**Use When**:
- Reviewing pull requests
- Conducting code audits
- Need security review
- Checking principle adherence

**Key Features**:
- Multi-dimensional review (correctness, security, performance, maintainability, testing, documentation)
- Severity classification (Critical, Moderate, Minor)
- Constructive feedback with examples
- Principle verification (DFF, DRY, KIS, etc.)
- Educational context and learning opportunities

**Typical Usage**:
```
/review Please review this PR for security and performance issues
```

#### 5. `/release` - Release Assistant

**File**: [`release.prompt.md`](./release.prompt.md)

**Purpose**: Manages version control, releases, and changelogs

**Use When**:
- Planning releases
- Updating changelogs
- Publishing packages
- Managing version bumps
- Implementing hotfixes

**Key Features**:
- Semantic versioning (MAJOR.MINOR.PATCH)
- Conventional commits format
- GitHub Actions automation
- Multi-package publishing (PyPI, NPM, RubyGems)
- Hotfix workflows
- Signed commits and security

**Typical Usage**:
```
/release I need to prepare a minor release with the recent features
```

### System Design Prompts

#### 6. `/architect` - Architecture Assistant

**File**: [`architect.prompt.md`](./architect.prompt.md)

**Purpose**: Guides system design and architecture decisions

**Use When**:
- Designing new systems
- Planning architecture
- Selecting patterns
- Making technical decisions
- Creating ADRs

**Key Features**:
- Architecture pattern selection (MVC, Microservices, Clean Architecture, Event-Driven)
- Component design specifications
- Data architecture and database design
- Integration architecture
- Deployment patterns
- Architecture Decision Records (ADRs)
- Scalability and security patterns

**Typical Usage**:
```
/architect Design a scalable web application architecture for 10K concurrent users
```

### Code Quality Prompts

#### 7. `/refactor` - Refactoring Assistant

**File**: [`refactor.prompt.md`](./refactor.prompt.md)

**Purpose**: Guides safe, systematic code refactoring

**Use When**:
- Improving code quality
- Reducing complexity
- Removing duplication
- Simplifying logic
- Applying design patterns

**Key Features**:
- Safe refactoring process (test → refactor → test)
- Code smell identification
- Refactoring patterns (Extract Method, Replace Conditional, etc.)
- Incremental improvements (Kaizen)
- Metrics tracking (complexity, lines, coverage)
- Before/after comparisons

**Typical Usage**:
```
/refactor This 200-line function is too complex, help me break it down
```

### Process Improvement Prompts

#### 8. `/kaizen` - Continuous Improvement Assistant

**File**: [`kaizen.prompt.md`](./kaizen.prompt.md)

**Purpose**: Applies Kaizen continuous improvement to development processes

**Use When**:
- Optimizing workflows
- Fixing recurring issues
- Improving team processes
- Eliminating waste
- Performance optimization

**Key Features**:
- PDCA cycle (Plan-Do-Check-Act)
- Seven wastes identification
- Blameless post-mortems
- Value stream mapping
- DORA metrics tracking
- Small, incremental improvements

**Typical Usage**:
```
/kaizen Our CI pipeline takes 30 minutes, help optimize it
```

### Repository Analysis Prompts

#### 9. `/stackattack` - Technology Stack Analyzer

**File**: [`stackattack.prompt.md`](./stackattack.prompt.md)

**Purpose**: Analyzes and documents technology stacks

**Use When**:
- Understanding new codebases
- Documenting tech stack
- Evaluating technologies
- Planning migrations
- Creating architecture docs

**Key Features**:
- 5-layer analysis (Frontend, Backend, Database, Infrastructure, DevOps)
- Dependency deep-dive
- Architecture patterns identification
- Visual diagrams (Mermaid)
- Security and quality assessment
- Actionable recommendations

**Typical Usage**:
```
/stackattack Analyze the technology stack of this repository
```

#### 10. `/forkme` - Repository Forking and Setup

**File**: [`forkme.prompt.md`](./forkme.prompt.md)

**Purpose**: Analyzes repositories and generates comprehensive setup instructions

**Use When**:
- Forking repositories
- Understanding new codebases
- Creating copilot-instructions.md
- Setting up development environments
- Generating onboarding docs

**Key Features**:
- Architecture discovery
- Developer workflow documentation
- Project-specific conventions
- AI-specific guidance generation
- Deployment instructions
- Progressive discovery strategy

**Typical Usage**:
```
/forkme Analyze https://github.com/user/repo and generate setup instructions
```

### Creative Prompts

#### 11. `/amr` - AMR Machine (Acronyms Made Recursively)

**File**: [`amr.prompt.md`](./amr.prompt.md)

**Purpose**: Generates recursive acronym content and creative naming

**Use When**:
- Need creative project names
- Generating brand content
- Creating acronyms
- Fun content generation
- Marketing materials

**Key Features**:
- Recursive acronym generation
- Multiple content mediums (blog, poem, story, etc.)
- Customizable themes
- Cultural context awareness
- Depth control

**Typical Usage**:
```
/amr Generate AMR content for "American Manufacturing Renegade" theme
```

## How These Prompts Work

### Integration with Instructions

These prompts are designed to work seamlessly with the instruction files:

```
.github/
├── instructions/           # Universal development standards
│   ├── core.instructions.md         # Principles: DFF, DRY, KIS, REnO, MVP, COLAB, AIPD
│   ├── development.instructions.md  # Language standards, testing, CI/CD
│   ├── documentation.instructions.md # Doc standards and templates
│   ├── version-control.instructions.md # Git workflows, releases
│   └── tools.instructions.md        # Development tools and automation
│
└── prompts/                # Specialized AI assistance
    ├── develop.prompt.md            # Implements features using instructions
    ├── test.prompt.md               # Creates tests following testing standards
    ├── document.prompt.md           # Generates docs using doc templates
    ├── review.prompt.md             # Reviews against all standards
    ├── release.prompt.md            # Manages releases per version control
    ├── architect.prompt.md          # Designs systems using patterns
    ├── refactor.prompt.md           # Improves code applying principles
    ├── kaizen.prompt.md             # Optimizes processes (PDCA)
    ├── stackattack.prompt.md        # Analyzes tech stacks
    └── forkme.prompt.md             # Generates setup docs
```

**Relationship**:
- **Instructions** = What to do (standards, patterns, principles)
- **Prompts** = How to assist (specialized workflows and guidance)

### Prompt Activation

Most AI agents support custom prompts through:

**VS Code with GitHub Copilot**:
- Prompts are automatically available when repository is open
- Reference with: `@workspace /develop` or direct invocation

**Cursor IDE**:
- Place prompts in `.cursorrules` or `.cursor/rules/`
- Reference with: `@[prompt-name]`

**Claude / ChatGPT**:
- Copy prompt content into conversation
- Provide context: "Act as the [Prompt Name] from [prompt file]"

## Using Prompts Effectively

### Basic Usage Pattern

1. **Invoke Prompt**: Use prompt keyword (e.g., `/develop`)
2. **Provide Context**: Share relevant files, requirements, constraints
3. **Follow Workflow**: Let the prompt guide you through structured process
4. **Iterate**: Use output as starting point, refine as needed
5. **Learn**: Understand patterns and apply to future work

### Combining Prompts

Prompts work well in sequence:

**Feature Development Flow**:
```
1. /architect    → Design system architecture
2. /develop      → Implement feature following design
3. /test         → Create comprehensive test suite
4. /review       → Review code for quality and security
5. /document     → Generate user and API documentation
6. /release      → Prepare and publish release
```

**Code Quality Flow**:
```
1. /review       → Identify issues and improvement opportunities
2. /refactor     → Safely improve code structure
3. /test         → Add tests for refactored code
4. /document     → Update documentation
```

**Repository Analysis Flow**:
```
1. /forkme       → Understand repository structure
2. /stackattack  → Analyze technology stack
3. /develop      → Implement features using discovered patterns
```

### Example Workflow

**Scenario**: Building a new user authentication feature

```bash
# Step 1: Design architecture
/architect Design authentication system with JWT tokens and refresh token flow

# Step 2: Implement feature
/develop Implement JWT authentication service with token generation and validation

# Step 3: Create tests
/test Generate comprehensive tests for authentication service including security tests

# Step 4: Document
/document Create API documentation for authentication endpoints

# Step 5: Review
/review Review authentication code for security vulnerabilities

# Step 6: Release
/release Prepare minor release with new authentication feature
```

## Prompt Customization

### Adapting for Your Project

1. **Copy prompt file** to your project
2. **Customize sections**:
   - Update technology stack references
   - Add project-specific patterns
   - Include domain-specific examples
   - Adjust to team conventions

3. **Add project context**:
   ```markdown
   ## Project-Specific Context
   
   **Project Type**: [Your project type]
   **Tech Stack**: [Your specific stack]
   **Conventions**: [Your team conventions]
   **Patterns**: [Your preferred patterns]
   ```

### Creating New Prompts

To create a new specialized prompt:

```markdown
---
mode: agent
description: [Brief description of prompt purpose]
---

# [Prompt Name]: [Protocol Name]

You are a specialized [role] assistant...

## Core Mission

When a user invokes `/[keyword]`, guide them through [process]...

## [Major Section]

[Content following similar structure to existing prompts]

---

**Ready to [accomplish goal]!**

Invoke me with `/[keyword]` and let's [action]!
```

## Best Practices

### For AI Agents Using These Prompts

- **Read Instructions First**: Load relevant `.github/instructions/*.md` files for context
- **Apply Principles**: Embody DFF, DRY, KIS, REnO, MVP, COLAB, AIPD in all assistance
- **Be Structured**: Follow the prompt's workflow and format
- **Provide Examples**: Use real, working code examples
- **Educate**: Explain "why" not just "what"
- **Quality Gates**: Apply verification checks before suggesting code

### For Developers Using These Prompts

- **Start with Right Prompt**: Choose prompt matching your current task
- **Provide Rich Context**: Share relevant files, requirements, constraints
- **Follow Workflow**: Trust the structured process
- **Iterate**: Use AI output as starting point, refine based on project needs
- **Learn Patterns**: Understand principles to apply independently
- **Give Feedback**: Note what works and what doesn't for prompt evolution

## Prompt Versioning

### Current Version: 1.0.0 (2025-11-14)

**Includes**:
- Development lifecycle prompts (develop, test, document, review, release)
- System design prompts (architect, refactor)
- Process improvement prompts (kaizen)
- Repository analysis prompts (stackattack, forkme)
- Creative prompts (amr)

**Principles Embodied**:
- DFF (Design for Failure), DRY (Don't Repeat Yourself), KIS (Keep It Simple)
- REnO (Release Early and Often), MVP (Minimum Viable Product)
- COLAB (Collaboration), AIPD (AI-Powered Development)

**Synthesized From**:
- Django/OpenAI development patterns (Barodybroject)
- Educational platform patterns (IT-Journey)
- Jekyll theme development (Zer0-Mistakes)
- Enterprise systems experience
- Universal software development best practices

## Quick Reference

| Prompt | Invoke | Purpose | Output |
|--------|--------|---------|--------|
| develop | `/develop` | Feature implementation | Code, tests, docs |
| test | `/test` | Test suite creation | Comprehensive tests |
| document | `/document` | Documentation generation | READMEs, API docs, tutorials |
| review | `/review` | Code review | Review report with suggestions |
| release | `/release` | Release management | Version bump, changelog, automation |
| architect | `/architect` | Architecture design | System design, ADRs, diagrams |
| refactor | `/refactor` | Code improvement | Refactored code, metrics |
| kaizen | `/kaizen` | Process improvement | PDCA workflow, recommendations |
| stackattack | `/stackattack` | Tech stack analysis | Stack analysis document |
| forkme | `/forkme` | Repository setup | copilot-instructions.md |
| amr | `/amr` | Creative content | Recursive acronyms, creative content |

## Integration with Development Workflow

### Typical Development Cycle

```
┌─────────────────────────────────────────────────────┐
│ 1. ARCHITECTURE: /architect                         │
│    → Design system, select patterns, create ADRs    │
└────────────────┬────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────┐
│ 2. DEVELOPMENT: /develop                            │
│    → Implement features, create services, build UI  │
└────────────────┬────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────┐
│ 3. TESTING: /test                                   │
│    → Create unit, integration, e2e tests            │
└────────────────┬────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────┐
│ 4. DOCUMENTATION: /document                         │
│    → Write README, API docs, tutorials              │
└────────────────┬────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────┐
│ 5. REVIEW: /review                                  │
│    → Code review, security check, quality audit     │
└────────────────┬────────────────────────────────────┘
                 │
          ┌──────▼──────┐
          │   Issues?   │
          └──┬───────┬──┘
             │       │
         Yes │       │ No
             │       │
┌────────────▼───┐   │
│ /refactor      │   │
│ → Improve code │   │
└────────────────┘   │
                     │
┌────────────────────▼────────────────────────────────┐
│ 6. RELEASE: /release                                │
│    → Version bump, changelog, publish               │
└────────────────┬────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────┐
│ 7. CONTINUOUS IMPROVEMENT: /kaizen                  │
│    → Optimize processes, eliminate waste            │
└─────────────────────────────────────────────────────┘
```

### Quick Tasks

**I need to...**

- Build a new feature → `/develop`
- Understand this codebase → `/forkme` or `/stackattack`
- Write tests → `/test`
- Improve code quality → `/review` then `/refactor`
- Add documentation → `/document`
- Prepare a release → `/release`
- Design a system → `/architect`
- Optimize a process → `/kaizen`

## Advanced Usage

### Multi-Prompt Sessions

**Complex Feature Development**:
```
Session 1: /architect → Design overall architecture
Session 2: /develop Component A → Implement first component
Session 3: /test Component A → Test first component
Session 4: /develop Component B → Implement second component
Session 5: /test Component B → Test second component
Session 6: /document → Create comprehensive documentation
Session 7: /review → Final review before release
Session 8: /release → Publish release
```

### Iterative Improvement

**Code Quality Enhancement**:
```
Iteration 1: /review → Identify issues
Iteration 2: /refactor Issue 1 → Fix highest priority
Iteration 3: /test → Add tests for refactored code
Iteration 4: /review → Check improvements
Iteration 5: /refactor Issue 2 → Fix next priority
Iteration 6: /kaizen → Optimize the improvement process itself
```

## Maintenance and Evolution

### Updating Prompts

When updating prompts:

1. **Test Changes**: Verify prompt still produces quality output
2. **Document Updates**: Note what changed and why
3. **Version Bump**: Update version in prompt file
4. **Update README**: Reflect changes in this file

### Contributing New Prompts

To contribute a new prompt:

1. **Identify Need**: What gap does this prompt fill?
2. **Follow Template**: Use existing prompts as examples
3. **Test Thoroughly**: Verify with multiple scenarios
4. **Document**: Add to this README with clear description
5. **Submit**: Create PR with rationale and examples

### Prompt Quality Standards

All prompts should:
- Have clear, single purpose
- Follow structured workflow
- Include practical examples
- Reference instruction files
- Embody universal principles
- Be well-documented
- Provide quality checkpoints

## Related Resources

- [Instructions Directory](../instructions/README.md) - Universal development standards
- [GitHub Copilot Documentation](https://docs.github.com/en/copilot)
- [Main Repository README](../../README.md) - Project overview

---

**Maintained by**: Amr Abdel-Motaleb  
**Purpose**: Comprehensive AI assistance for software development lifecycle  
**Status**: Active, continuously evolving  
**Version**: 1.0.0  
**Last Updated**: 2025-11-14

---

## Quick Start

1. **Choose a prompt** from the table above based on your task
2. **Invoke the prompt** in your AI assistant (e.g., `/develop`)
3. **Provide context** about your specific needs
4. **Follow the workflow** provided by the prompt
5. **Iterate and refine** the output for your project

**Pro Tip**: Start with `/architect` for new projects, `/forkme` for existing repositories, or `/develop` for specific features.

