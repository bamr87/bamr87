---
applyTo: '.pre-commit-config.yaml,.pre-commit-config.yml,**/package.json,**/requirements*.txt,**/pyproject.toml,**/poetry.lock,.eslintrc.*,.prettierrc.*,.prettierrc,.rubocop.yml,.rubocop.yaml,Makefile,.editorconfig'
---

# Development Tools

AI toolkit and development tools reference. Comprehensive guide to tools, configurations, and automation for modern software development.

## AI Toolkit

Tools for AI/Agent application development:

- `aitk-get_agent_code_gen_best_practices` - Best practices for AI Agent development
- `aitk-get_tracing_code_gen_best_practices` - Best practices for tracing in AI applications
- `aitk-get_ai_model_guidance` - Guidance for using AI models
- `aitk-evaluation_planner` - Guides evaluation metrics and test dataset planning
- `aitk-get_evaluation_code_gen_best_practices` - Best practices for evaluation code generation
- `aitk-evaluation_agent_runner_best_practices` - Best practices for using agent runners

## Common Development Tools

### Code Quality

- **Linters**: ESLint, Flake8, RuboCop
- **Formatters**: Prettier, Black, RuboCop
- **Type Checkers**: TypeScript, mypy, Sorbet

### Testing

- **Python**: pytest, unittest
- **JavaScript**: Jest, Mocha, Vitest
- **Ruby**: RSpec, Minitest

### Documentation

- **Markdown**: markdownlint, markdown-link-check
- **Python**: Sphinx, mkdocs
- **JavaScript**: JSDoc, TypeDoc

### CI/CD

- **GitHub Actions**: Workflow automation
- **Docker**: Containerization
- **Scripts**: Automation and deployment

## Tool Configuration

### Pre-commit Hooks

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.4.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
```

### Editor Configuration

**VS Code Settings:**

```json
{
  "editor.formatOnSave": true,
  "editor.codeActionsOnSave": {
    "source.fixAll": true
  }
}
```

## Container Development Tools

### Docker

**Docker Compose for Development:**

```yaml
# docker-compose.yml - Development environment
version: '3.8'

services:
  app:
    build:
      context: .
      target: development
    volumes:
      - ./src:/app/src:ro
      - ./.env:/app/.env:ro
    ports:
      - "8000:8000"
    environment:
      - NODE_ENV=development
    command: npm run dev  # or python manage.py runserver
```

**Useful Docker Commands:**

```bash
# Build and run containers
docker-compose up --build

# Run commands in container
docker-compose exec app npm test
docker-compose exec app python manage.py migrate

# View logs
docker-compose logs -f app

# Clean up
docker-compose down -v
```

### VS Code Development Containers

```json
// .devcontainer/devcontainer.json
{
  "name": "Project Dev Environment",
  "dockerComposeFile": "../docker-compose.yml",
  "service": "app",
  "workspaceFolder": "/app",
  "customizations": {
    "vscode": {
      "extensions": [
        "ms-python.python",
        "dbaeumer.vscode-eslint",
        "esbenp.prettier-vscode",
        "GitHub.copilot"
      ],
      "settings": {
        "editor.formatOnSave": true,
        "python.linting.enabled": true
      }
    }
  },
  "postCreateCommand": "npm install",  // or pip install -r requirements.txt
  "remoteUser": "node"
}
```

## Linting and Formatting

### Multi-Language Configuration

**EditorConfig (.editorconfig):**

```ini
# Universal editor configuration
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space
indent_size = 2

[*.{py,rb}]
indent_size = 4

[*.{js,ts,jsx,tsx}]
indent_size = 2

[*.md]
trim_trailing_whitespace = false

[Makefile]
indent_style = tab
```

**Pre-commit Hooks (.pre-commit-config.yaml):**

```yaml
repos:
  # Universal hooks
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.4.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
      - id: check-merge-conflict
      - id: mixed-line-ending
  
  # Python
  - repo: https://github.com/psf/black
    rev: 23.3.0
    hooks:
      - id: black
  
  - repo: https://github.com/PyCQA/flake8
    rev: 6.0.0
    hooks:
      - id: flake8
  
  # JavaScript/TypeScript
  - repo: https://github.com/pre-commit/mirrors-prettier
    rev: v3.0.0
    hooks:
      - id: prettier
        types_or: [javascript, jsx, ts, tsx, json, yaml]
  
  # Markdown
  - repo: https://github.com/igorshubovych/markdownlint-cli
    rev: v0.35.0
    hooks:
      - id: markdownlint
```

### Language-Specific Tools

**Python:**

```ini
# pyproject.toml
[tool.black]
line-length = 100
target-version = ['py38', 'py39', 'py310', 'py311']

[tool.isort]
profile = "black"
line_length = 100

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = "test_*.py"
addopts = "-v --cov=src --cov-report=term-missing"
```

**JavaScript/TypeScript:**

```json
// .eslintrc.json
{
  "extends": [
    "eslint:recommended",
    "plugin:@typescript-eslint/recommended",
    "prettier"
  ],
  "rules": {
    "no-console": ["warn", { "allow": ["warn", "error"] }],
    "prefer-const": "error",
    "no-var": "error"
  }
}

// .prettierrc
{
  "semi": true,
  "singleQuote": true,
  "trailingComma": "es5",
  "printWidth": 100,
  "tabWidth": 2
}
```

## CI/CD Tools and Automation

### GitHub Actions Reusable Workflows

```yaml
# .github/workflows/reusable-test.yml
name: Reusable Test Workflow

on:
  workflow_call:
    inputs:
      language:
        required: true
        type: string

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Setup environment
        run: |
          case "${{ inputs.language }}" in
            python)
              pip install -r requirements.txt
              ;;
            node)
              npm install
              ;;
            ruby)
              bundle install
              ;;
          esac
      
      - name: Run tests
        run: |
          case "${{ inputs.language }}" in
            python)
              pytest
              ;;
            node)
              npm test
              ;;
            ruby)
              bundle exec rspec
              ;;
          esac
```

### Makefile for Common Tasks

```makefile
# Makefile - Universal task automation
# Note: In actual Makefiles, use TAB characters for indentation (not spaces)
.PHONY: help install test lint format clean

help:  ## Show this help message
    @grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:  ## Install dependencies
    @if [ -f "package.json" ]; then npm install; fi
    @if [ -f "requirements.txt" ]; then pip install -r requirements.txt; fi
    @if [ -f "Gemfile" ]; then bundle install; fi

test:  ## Run test suite
    @if [ -f "package.json" ]; then npm test; fi
    @if [ -f "pytest.ini" ]; then pytest; fi
    @if [ -f "Rakefile" ]; then bundle exec rspec; fi

lint:  ## Run linters
    @if [ -f ".eslintrc.json" ]; then npm run lint; fi
    @if [ -f ".flake8" ]; then flake8 src/; fi

format:  ## Format code
    @if [ -f "package.json" ]; then npm run format; fi
    @if [ -f "pyproject.toml" ]; then black src/; fi

clean:  ## Clean build artifacts
    @find . -type d -name "__pycache__" -exec rm -rf {} +
    @find . -type d -name "node_modules" -exec rm -rf {} +
    @find . -type f -name "*.pyc" -delete
    @rm -rf dist/ build/ *.egg-info
```

## Monitoring and Observability Tools

### Logging Configuration

**Python:**

```python
# logging_config.py
import logging
import sys

def setup_logging(level=logging.INFO):
    """Configure application logging"""
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('app.log')
        ]
    )
    
    # Suppress noisy third-party loggers
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
```

**JavaScript:**

```javascript
// logger.js
const winston = require('winston');

const logger = winston.createLogger({
  level: process.env.LOG_LEVEL || 'info',
  format: winston.format.combine(
    winston.format.timestamp(),
    winston.format.json()
  ),
  transports: [
    new winston.transports.Console(),
    new winston.transports.File({ filename: 'error.log', level: 'error' }),
    new winston.transports.File({ filename: 'combined.log' })
  ]
});

module.exports = logger;
```

### Performance Monitoring

```text
# Example health check endpoint
GET /health

Response:
{
  "status": "healthy",
  "version": "1.2.3",
  "uptime": 3600,
  "database": "connected",
  "cache": "connected"
}
```

## Script Organization and Automation

### Script Directory Structure

```text
scripts/
├── setup/           # Installation and setup scripts
│   ├── install.sh
│   └── configure.sh
├── dev/             # Development utilities
│   ├── run-tests.sh
│   └── format-code.sh
├── build/           # Build and packaging scripts
│   ├── build.sh
│   └── package.sh
├── deploy/          # Deployment scripts
│   ├── deploy-staging.sh
│   └── deploy-production.sh
└── utils/           # General utilities
    ├── clean.sh
    └── backup.sh
```

### Script Best Practices

Scripts should be:

- Located in `scripts/` directory
- Executable with proper shebang (`#!/bin/bash`)
- Self-documenting with usage information
- Idempotent (safe to run multiple times)
- Tested and validated
- Follow naming conventions (kebab-case)
- Include error handling and logging

---

**Version:** 3.0.0 | **Last Modified:** 2025-11-14 | **Author:** Amr Abdel-Motaleb

**Purpose:** Universal development tools and automation reference adaptable to various project types, languages, and development environments.
