# Contributing to Amr Abdel-Motaleb's Projects

First off, thank you for considering contributing! Your time and effort are greatly appreciated. This document provides guidelines for contributing to this repository and its associated projects. Following these guidelines helps maintain code quality, ensures consistency, and makes the contribution process smoother for everyone.

## 🌟 Philosophy: People Over Profits

This repository and its projects are guided by a core philosophy:

-   🌱 **Sustainable Technology**: Building systems that adapt and scale.
-   👥 **Employee Empowerment**: Transferring knowledge to make teams self-sufficient.
-   📚 **Knowledge Sharing**: Advancing our collective capabilities through open-source education.
-   🌍 **Balanced Innovation**: Integrating environmental and social impact as measurable business drivers.

Contributions should align with these values, aiming to create technology that is not only functional but also educational, sustainable, and empowering.

## 🤖 AI-Assisted Development

We embrace AI-powered development (AIPD) to enhance productivity and quality. When contributing, you are encouraged to use AI tools like GitHub Copilot. However, please adhere to the following principles:

-   **Assist, Don't Replace**: Use AI to generate drafts, suggest improvements, and automate repetitive tasks.
-   **Human Oversight**: As the contributor, you are responsible for the final code. Always review, understand, and validate AI-generated code.
-   **Maintain Quality**: Ensure that all contributions, whether human or AI-assisted, meet the standards outlined in this document.

## 📋 How to Contribute

We welcome several types of contributions:

1.  **Code Contributions**: Implementing new features, fixing bugs, or refactoring existing code.
2.  **Documentation Contributions**: Improving `README.md` files, adding examples, clarifying instructions, or fixing typos.
3.  **Content Contributions**: Writing tutorials, blog posts, or educational content for associated platforms like `it-journey.dev`.
4.  **Community Contributions**: Answering questions in discussions, reviewing pull requests, or mentoring other contributors.

### Getting Started

1.  **Find an issue** or **propose an idea**: Check the `Issues` tab to find existing tasks or open a new one to discuss your proposed changes.
2.  **Fork the repository**: Create your own copy of the repository to work on.
3.  **Create a branch**: Use a descriptive branch name (e.g., `feature/add-new-widget` or `fix/login-bug`).
4.  **Make your changes**: Follow the development principles and coding standards outlined below.
5.  **Submit a Pull Request (PR)**: Once your changes are ready, open a PR and provide a clear description of what you've done.

## 🚀 Core Development Principles

All contributions should adhere to the following principles:

-   **Design for Failure (DFF)**: Implement robust error handling, logging, and fallback mechanisms.
-   **Don't Repeat Yourself (DRY)**: Create reusable functions, modules, and components.
-   **Keep It Simple (KIS)**: Prefer clear, readable code over complex or "clever" solutions.

### 📖 README-First, README-Last

This is a **critical workflow rule**. Documentation is not an afterthought; it is an integral part of the development process.

#### 🔍 README-FIRST: Start with Documentation

Before writing any code:

1.  **Locate and read** the relevant `README.md` file(s) to understand the context, purpose, and existing structure of the module you are working on.
2.  **Assess documentation gaps**: Identify what is missing, outdated, or unclear.

#### ✅ README-LAST: Update Documentation After Changes

After completing your code changes:

1.  **Update the `README.md`** to reflect your changes. Document new files, features, or functionalities.
2.  **Ensure all documentation is accurate**, links are working, and examples are correct.
3.  **Update the `lastmod` date** in the frontmatter if the `README.md` has it.

##  Git Workflow

### Branching

Please follow these branch naming conventions:

-   `feature/<description>`: For new features.
-   `fix/<description>`: For bug fixes.
-   `docs/<description>`: For documentation-only changes.
-   `refactor/<description>`: For code refactoring without functional changes.
-   `chore/<description>`: For maintenance tasks (e.g., updating dependencies).

### Commit Messages

We follow the **Conventional Commits** specification. This makes the commit history more readable and allows for automated changelog generation.

**Format**:
```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

**Example**:
```
feat(auth): add password reset functionality

Implement the complete password reset flow, including email
notifications and a secure token-based reset mechanism.

Fixes #42
```

-   **Types**: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `perf`, `ci`.
-   **Scope**: The part of the codebase the commit affects (e.g., `auth`, `api`, `docs`).

## 🏗️ Monorepo Workflow

This repository uses **Git submodules** to manage multiple related projects. Understanding how to work with submodules is essential for contributing.

### Repository Structure

```
bamr87/
├── cv/          # Submodule: CV Builder application
├── README/      # Submodule: Documentation hub
├── scripts/     # Submodule: Automation scripts
├── skills/      # Submodule: Microsoft Agent Skills (microsoft/skills)
└── (root)       # Profile README and coordination
```

For detailed information, see [docs/MONOREPO.md](docs/MONOREPO.md).

### Contributing to Root Repository

For changes to root-level files (README.md, .gitignore, workflows, shared configs):

1. **Fork** the main repository: `https://github.com/bamr87/bamr87`
2. **Clone** with submodules:
   ```bash
   git clone --recurse-submodules https://github.com/YOUR-USERNAME/bamr87.git
   cd bamr87
   ```
3. **Create a branch**:
   ```bash
   git checkout -b feature/your-feature
   ```
4. **Make changes** to root-level files only
5. **Commit and push**:
   ```bash
   git add .
   git commit -m "feat: your descriptive message"
   git push origin feature/your-feature
   ```
6. **Open a Pull Request** to the main repository

### Contributing to Submodules

For changes to cv/, README/, or scripts/:

#### Option 1: Direct Submodule Contribution (Recommended)

1. **Fork the submodule repository** (e.g., `https://github.com/bamr87/cv-builder-pro`)
2. **Clone and work directly** in the submodule repo:
   ```bash
   git clone https://github.com/YOUR-USERNAME/cv-builder-pro.git
   cd cv-builder-pro
   git checkout -b feature/your-feature
   # Make changes
   git commit -m "feat: your feature"
   git push origin feature/your-feature
   ```
3. **Open a PR** to the submodule repository
4. **After merge**, the parent repository will be updated automatically via CI/CD

#### Option 2: Work Through Parent Repository

1. **Clone parent with submodules**:
   ```bash
   git clone --recurse-submodules https://github.com/bamr87/bamr87.git
   cd bamr87
   ```
2. **Navigate to submodule** and create branch:
   ```bash
   cd cv
   git checkout -b feature/your-feature
   ```
3. **Make changes and commit** in the submodule:
   ```bash
   git add .
   git commit -m "feat: your feature"
   git push origin feature/your-feature
   ```
4. **Return to parent and update pointer**:
   ```bash
   cd ..
   git add cv
   git commit -m "chore: update cv submodule with feature"
   git push
   ```
5. **Open PRs** for both the submodule and parent repository

### Submodule Update Process

When you see "Update submodule" PRs:

1. **Review the submodule changes** by clicking the commit hash
2. **Test the changes** locally:
   ```bash
   git checkout pr-branch
   git submodule update --init --recursive
   cd cv  # or relevant submodule
   npm install && npm run dev  # or appropriate commands
   ```
3. **Approve and merge** if tests pass

### Testing Across Submodules

Before submitting PRs that affect multiple submodules:

1. **Test each submodule independently**
2. **Test integration** by running from the root:
   ```bash
   ./tools/run-all-tests.sh
   ```
3. **Document dependencies** between submodules in your PR description

### Submodule Best Practices

-   ✅ **Always commit submodule changes first**, then update parent
-   ✅ **Test submodule changes independently** before updating parent
-   ✅ **Use descriptive commit messages** mentioning the submodule
-   ✅ **Keep submodules on stable branches** (main/master)
-   ❌ **Don't make unrelated changes** in multiple submodules in one PR
-   ❌ **Don't update parent pointer** without merging submodule changes first

## 🧠 Skills & AI Agent Resources

This repository integrates [microsoft/skills](https://github.com/microsoft/skills) as a submodule (`skills/`), providing 130+ domain-specific skills for AI coding agents. The following resources from that project have been adapted for use in this repo:

-   **Code Review Checklist**: `.github/prompts/skills-code-review.prompt.md` — Comprehensive code review checklist covering frontend, backend, security, and performance.
-   **Add Endpoint Prompt**: `.github/prompts/add-endpoint.prompt.md` — Step-by-step template for adding REST API endpoints with Pydantic models.
-   **Pattern Enforcement**: `.github/docs/pattern-enforcement.md` — How skills enforce consistent coding patterns across teams.
-   **Workflow Patterns**: `.github/docs/workflow-patterns.md` — Composing skills and prompts for multi-step workflows.
-   **Agent Principles**: `AGENTS.md` — Core principles (Think Before Coding, Simplicity First, Surgical Changes, Goal-Driven Execution) adapted for this monorepo.

These complement the existing review and development prompts in `.github/prompts/` and the agent definitions in `.github/agents/`.

## 💻 Code and Documentation Standards

### General Standards

-   **Code Style**: Follow the existing code style. Use linters and formatters where provided.
-   **File Headers**: Include a standardized header in all source files, as defined in the project's instruction files.
-   **Comments**: Explain the "why," not the "what." Code should be self-documenting.

### Language-Specific Guidelines

-   **Python**: Follow PEP 8. Use type hints and `black` for formatting.
-   **JavaScript/TypeScript**: Use Prettier for formatting and ESLint for linting. Prefer TypeScript for new projects.
-   **Bash/Shell**: Use `shellcheck` to validate scripts. Include `set -euo pipefail` for robustness.

### Documentation

-   **READMEs are essential**: Every directory should have a `README.md` explaining its purpose.
-   **Docstrings/JSDoc**: All public functions, classes, and modules must have complete documentation.
-   **Front Matter**: Use the standardized front matter for all content and instruction files to provide context for both humans and AI.

## 🧪 Testing

-   **Write tests**: All new features and bug fixes must be accompanied by tests.
-   **High Coverage**: Aim for high test coverage to ensure reliability.
-   **CI/CD**: All tests will be run automatically via GitHub Actions when you open a PR. Ensure they pass.

## 🤝 Pull Request (PR) Process

1.  **Create a Draft PR** early in the process to get feedback.
2.  **Ensure your PR is focused**: A PR should address a single issue or feature.
3.  **Provide a clear description**: Explain what the PR does and why. Use the provided PR template.
4.  **Link to the issue**: If your PR resolves an issue, link it using `Fixes #<issue-number>`.
5.  **Self-review your PR** before requesting a review from others.

Thank you for contributing to this journey of learning and building!
