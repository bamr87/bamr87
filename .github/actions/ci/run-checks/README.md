# Run Checks Action

A flexible composite action for running tests, quality checks, and validations with customizable scripts.

## Features

- 🧪 **Test Execution**: Run your test suite with any framework
- ✅ **Quality Checks**: Linting, formatting, type checking
- 🔧 **Custom Setup**: Optional setup script for environment preparation
- 📦 **Release Preparation**: Optional script for building release assets
- 🎯 **Framework Agnostic**: Works with any language or tooling

## Usage

### Basic Usage

```yaml
- uses: ./.github/actions/ci/run-checks
  with:
    test-script: './scripts/test.sh'
```

### Full Pipeline

```yaml
- uses: ./.github/actions/ci/run-checks
  with:
    setup-script: './scripts/setup.sh'
    test-script: './scripts/test.sh'
    quality-script: './scripts/lint.sh'
    release-script: './scripts/build.sh'
```

### With Inline Scripts

```yaml
- uses: ./.github/actions/ci/run-checks
  with:
    test-script: |
      #!/bin/bash
      set -e
      pytest tests/ --verbose
    quality-script: |
      #!/bin/bash
      set -e
      ruff check .
      black --check .
      mypy src/
```

## Inputs

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `runner-os` | OS for the runner (unused in composite) | No | `ubuntu-latest` |
| `setup-script` | Setup script path or content | No | - |
| `test-script` | Test script path or content | Yes | - |
| `quality-script` | Quality check script path or content | No | - |
| `release-script` | Release preparation script path or content | No | - |

## Script Execution Order

1. **Setup** (if provided) - Environment preparation
2. **Tests** (required) - Test suite execution
3. **Quality** (if provided) - Code quality checks
4. **Release** (if provided) - Release asset preparation

Each script is automatically made executable before running.

## Complete Examples

### Python Project

```yaml
name: Python CI

on: [push, pull_request]

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - uses: ./.github/actions/ci/run-checks
        with:
          setup-script: |
            #!/bin/bash
            pip install -e ".[dev]"
          test-script: |
            #!/bin/bash
            pytest tests/ --cov=src --cov-report=xml
          quality-script: |
            #!/bin/bash
            ruff check src/ tests/
            black --check src/ tests/
            mypy src/
```

### Node.js Project

```yaml
name: Node.js CI

on: [push, pull_request]

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'
      
      - uses: ./.github/actions/ci/run-checks
        with:
          setup-script: 'npm ci'
          test-script: 'npm test'
          quality-script: |
            #!/bin/bash
            npm run lint
            npm run format:check
            npm run type-check
```

### Go Project

```yaml
name: Go CI

on: [push, pull_request]

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - uses: actions/setup-go@v5
        with:
          go-version: '1.21'
      
      - uses: ./.github/actions/ci/run-checks
        with:
          test-script: 'go test -v -race -coverprofile=coverage.out ./...'
          quality-script: |
            #!/bin/bash
            go vet ./...
            golangci-lint run
```

### Rust Project

```yaml
name: Rust CI

on: [push, pull_request]

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - uses: actions-rust-lang/setup-rust-toolchain@v1
      
      - uses: ./.github/actions/ci/run-checks
        with:
          test-script: 'cargo test --all-features'
          quality-script: |
            #!/bin/bash
            cargo fmt -- --check
            cargo clippy -- -D warnings
          release-script: 'cargo build --release'
```

### Multi-Step Setup

```yaml
- uses: ./.github/actions/ci/run-checks
  with:
    setup-script: |
      #!/bin/bash
      set -e
      
      # Install system dependencies
      sudo apt-get update
      sudo apt-get install -y libsqlite3-dev
      
      # Setup database
      createdb test_db
      psql test_db < schema.sql
      
      # Install app dependencies
      bundle install
    test-script: 'bundle exec rspec'
    quality-script: 'bundle exec rubocop'
```

### With Release Build

```yaml
name: Release

on:
  push:
    tags: ['v*']

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - uses: ./.github/actions/ci/run-checks
        with:
          test-script: 'npm test'
          quality-script: 'npm run lint'
          release-script: |
            #!/bin/bash
            npm run build
            tar -czf release.tar.gz dist/
      
      - name: Upload release asset
        uses: actions/upload-artifact@v4
        with:
          name: release-build
          path: release.tar.gz
```

### Using External Scripts

Create scripts in your repository:

```bash
# scripts/setup.sh
#!/bin/bash
set -euo pipefail
pip install -r requirements.txt
pip install -r requirements-dev.txt

# scripts/test.sh
#!/bin/bash
set -euo pipefail
pytest tests/ --cov=src --cov-report=term-missing

# scripts/quality.sh
#!/bin/bash
set -euo pipefail
ruff check .
black --check .
mypy src/
```

Then reference them:

```yaml
- uses: ./.github/actions/ci/run-checks
  with:
    setup-script: './scripts/setup.sh'
    test-script: './scripts/test.sh'
    quality-script: './scripts/quality.sh'
```

## Script Best Practices

### Error Handling

Always include error handling in scripts:

```bash
#!/bin/bash
set -e  # Exit on error
set -u  # Exit on undefined variable
set -o pipefail  # Exit on pipe failure

# Your commands here
```

### Verbose Output

Add verbosity for debugging:

```bash
#!/bin/bash
set -ex  # -x prints commands before execution

pytest tests/ --verbose
```

### Exit Codes

Ensure proper exit codes:

```bash
#!/bin/bash
pytest tests/ || exit 1
ruff check . || exit 1
echo "All checks passed"
```

## Conditional Execution

Scripts only run if provided:

```yaml
# Only runs tests (setup, quality, release skipped)
- uses: ./.github/actions/ci/run-checks
  with:
    test-script: 'npm test'
```

## Script Permissions

The action automatically runs `chmod +x` on each script before execution, so you don't need to commit scripts with execute permissions.

## Common Patterns

### Python: pytest + ruff + black + mypy

```yaml
setup-script: 'pip install -e ".[dev]"'
test-script: 'pytest tests/ --cov=src'
quality-script: |
  ruff check .
  black --check .
  mypy src/
```

### Node.js: Jest + ESLint + Prettier

```yaml
setup-script: 'npm ci'
test-script: 'npm test -- --coverage'
quality-script: |
  npm run lint
  npm run format:check
```

### Ruby: RSpec + RuboCop

```yaml
setup-script: 'bundle install'
test-script: 'bundle exec rspec'
quality-script: 'bundle exec rubocop'
```

### Go: go test + golangci-lint

```yaml
test-script: 'go test -v ./...'
quality-script: |
  go vet ./...
  golangci-lint run
```

## Troubleshooting

### Script not found
**Solution**: Ensure script path is relative to repository root, or use inline script

### Permission denied
**Solution**: Action automatically handles this, but ensure script content is valid

### Setup script fails
**Solution**: Add error handling and check dependencies are available

### Quality checks too strict
**Solution**: Configure linters to match your project's standards

## Integration with Other Actions

### With Test Coverage

```yaml
- uses: ./.github/actions/ci/run-checks
  with:
    test-script: 'pytest --cov=src --cov-report=xml'

- uses: codecov/codecov-action@v4
  with:
    files: ./coverage.xml
```

### With Caching

```yaml
- uses: actions/cache@v4
  with:
    path: ~/.cache/pip
    key: ${{ runner.os }}-pip-${{ hashFiles('requirements.txt') }}

- uses: ./.github/actions/ci/run-checks
  with:
    test-script: 'pytest tests/'
```

### In Matrix Builds

```yaml
strategy:
  matrix:
    os: [ubuntu-latest, macos-latest, windows-latest]

steps:
  - uses: ./.github/actions/ci/run-checks
    with:
      test-script: './scripts/test.sh'
```

## Comparison with run-tests

| Feature | run-checks | run-tests |
|---------|-----------|-----------|
| **Purpose** | Custom scripts | Language-specific testing |
| **Setup** | Manual | Automatic language setup |
| **Flexibility** | High | Medium |
| **Simplicity** | Low | High |

Use **run-checks** when:
- You have custom build/test scripts
- Multiple tools need to run in sequence
- You need fine-grained control

Use **run-tests** when:
- Standard language testing workflow
- Want automatic setup and caching
- Need parallelization support

## Best Practices

1. **Keep scripts in version control** (`scripts/` directory)
2. **Use inline scripts** for simple commands
3. **Add error handling** to all scripts
4. **Make scripts idempotent** (safe to run multiple times)
5. **Document script dependencies** in README
6. **Use descriptive script names** (setup-db.sh, not s1.sh)

## Related Actions

- [`ci/run-tests`](../run-tests/README.md) - Language-specific test runner
- [`setup/configure-git`](../../setup/configure-git/README.md) - Git configuration

This action provides maximum flexibility for custom CI pipelines while maintaining a consistent workflow structure.
