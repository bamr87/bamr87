---
description: "Master instructions for AI-assisted development, providing a comprehensive guide for using AI tools like GitHub Copilot to build, test, and document code according to project standards."
---

# AI-Assisted Development Instructions

## 1. Overview

These instructions guide AI assistants (e.g., GitHub Copilot) and human developers in creating, maintaining, and evolving this project. They establish standards for code, documentation, workflows, and testing to ensure consistency and quality.

**Core Principles:**
- **AI as a Partner:** Use AI to augment human developers, not replace them. AI assists with boilerplate code, tests, documentation, and analysis, while humans focus on architecture, logic, and final review.
- **Consistency is Key:** Adhering to these standards ensures the codebase is readable, maintainable, and easy for new contributors to understand.
- **README-First:** Before writing code, outline the feature and its usage in the `README.md`. This clarifies the feature's purpose and API.
- **Test-Driven Development (TDD):** Write tests before or alongside your code to ensure correctness and prevent regressions.

## 2. Workspace Setup

A clean and organized workspace is crucial for efficient development.

- **`.vscode/`**: Contains workspace-specific settings for VS Code, such as recommended extensions and debugging configurations.
- **`scripts/`**: Reusable scripts for common tasks like building, testing, and deploying.
- **`src/` or `lib/`**: Location for the main source code of the project.
- **`tests/` or `spec/`**: Contains all the tests for the project.
- **`.github/`**: Houses GitHub-specific files, including workflows, issue templates, and these instructions.

## 3. Language-Specific Guidelines

### General
- **Code Style:** Use an automated formatter (e.g., Prettier, Black, RuboCop) to maintain a consistent style.
- **Naming Conventions:** Use clear, descriptive names for variables, functions, and classes.
- **Error Handling:** Implement robust error handling. Don't suppress errors silently.

### Python
- **Style:** Follow PEP 8. Use `black` for formatting and `flake8` for linting.
- **Typing:** Use type hints for all function signatures.
- **Docstrings:** Write Google-style docstrings for all public modules, classes, and functions.

### JavaScript/TypeScript
- **Style:** Use `prettier` for formatting and `eslint` for linting.
- **Typing:** Prefer TypeScript over plain JavaScript for type safety.
- **Modules:** Use ES Modules (`import`/`export`) over CommonJS (`require`/`module.exports`).

### Ruby
- **Style:** Follow the community-driven Ruby Style Guide. Use `rubocop` for enforcement.
- **Gems:** Manage dependencies with `bundler`.

## 4. Documentation

Documentation is as important as code.

- **`README.md`:** Every directory should have a `README.md` explaining its purpose, contents, and usage. See the `README.template.md` for a good starting point.
- **Code Comments:** Use comments to explain *why* code is written a certain way, not *what* it does. The code itself should be clear enough to explain the "what".
- **API Documentation:** For libraries or services, generate API documentation from source code comments using tools like Sphinx (Python) or JSDoc (JavaScript).

## 5. Testing

- **Unit Tests:** Test individual functions and classes in isolation.
- **Integration Tests:** Test how different parts of your system work together.
- **End-to-End (E2E) Tests:** Test the entire application from the user's perspective.
- **Coverage:** Aim for high test coverage, but don't sacrifice test quality for a higher percentage.

## 6. GitHub Workflows (CI/CD)

Automated workflows ensure that every change is automatically tested and validated.

- **On Pull Request:** Run linters, formatters, and tests for all pull requests.
- **On Merge to `main`:** Deploy to a staging environment.
- **On Release:** Publish packages or deploy to production.

## 7. Prompts for AI Assistants

Use these prompts to get the most out of your AI assistant.

### Code Generation
"Generate a [language] function that [does something], including type hints, docstrings, and error handling. It should follow [specific style guide]."

### Test Generation
"Write unit tests for the following function: [paste function]. Include tests for edge cases and invalid input."

### Documentation
"Generate a `README.md` for a directory containing [description of files]. Explain the purpose, how to install dependencies, and how to run the code."

### Refactoring
"Refactor this code to be more readable and efficient. Explain the changes you made."
