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
