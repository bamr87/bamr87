# Run Tests Action

A generic, framework-agnostic test runner that supports multiple programming languages and testing frameworks.

## Features

- 🌐 **Multi-language Support**: Python, Node.js, Ruby, Go, Rust
- 🔀 **Test Parallelization**: Built-in support for test splitting
- 🐳 **Service Management**: Docker Compose integration
- 📊 **Coverage Reports**: Automatic coverage generation
- 🎯 **Flexible Configuration**: Customizable for any test framework
- 💾 **Caching**: Dependency caching for faster runs

## Usage

### Basic Example

```yaml
- uses: ./.github/actions/ci/run-tests
  with:
    language: 'python'
    language-version: '3.11'
    test-command: 'pytest tests/'
```

### Python with pytest

```yaml
- uses: ./.github/actions/ci/run-tests
  with:
    language: 'python'
    language-version: '3.11'
    package-manager: 'pip'
    test-command: 'pytest'
    test-directory: 'tests/'
    test-args: '--verbose --maxfail=1'
    coverage-enabled: 'true'
    coverage-format: 'xml'
```

### Node.js with Jest

```yaml
- uses: ./.github/actions/ci/run-tests
  with:
    language: 'node'
    language-version: '20'
    package-manager: 'npm'
    test-command: 'npm test'
    coverage-enabled: 'true'
```

### Ruby with RSpec

```yaml
- uses: ./.github/actions/ci/run-tests
  with:
    language: 'ruby'
    language-version: '3.2'
    test-command: 'bundle exec rspec'
    test-args: '--format documentation'
```

### With Docker Compose Services

```yaml
- uses: ./.github/actions/ci/run-tests
  with:
    language: 'python'
    test-command: 'pytest'
    services-enabled: 'true'
    services-compose-file: 'docker-compose.test.yml'
    services-wait-script: './scripts/wait-for-services.sh'
```

### Parallel Test Execution

```yaml
jobs:
  test:
    strategy:
      matrix:
        job-index: [1, 2, 3, 4]
    steps:
      - uses: ./.github/actions/ci/run-tests
        with:
          language: 'python'
          test-command: 'pytest'
          parallel-jobs: 4
          job-index: ${{ matrix.job-index }}
```

### With Setup Script

```yaml
- uses: ./.github/actions/ci/run-tests
  with:
    language: 'python'
    test-command: 'pytest'
    setup-script: './scripts/setup-test-env.sh'
```

## Inputs

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `language` | Programming language | Yes | - |
| `language-version` | Language version | No | Language default |
| `package-manager` | Package manager | No | Auto-detect |
| `install-dependencies` | Install dependencies | No | `true` |
| `dependency-cache` | Enable caching | No | `true` |
| `setup-script` | Setup script path | No | - |
| `test-command` | Test command | Yes | - |
| `test-directory` | Test directory | No | - |
| `test-pattern` | Test file pattern | No | - |
| `test-args` | Additional test args | No | - |
| `parallel-jobs` | Parallel job count | No | `1` |
| `job-index` | Current job index | No | `1` |
| `services-enabled` | Use Docker Compose | No | `false` |
| `services-compose-file` | Compose file path | No | `docker-compose.yml` |
| `services-wait-script` | Service wait script | No | - |
| `coverage-enabled` | Enable coverage | No | `false` |
| `coverage-format` | Coverage format | No | `xml` |
| `artifact-name` | Artifact name | No | `test-results` |
| `github-token` | GitHub token | No | - |

## Outputs

| Output | Description |
|--------|-------------|
| `test-result` | Test execution result (success/failure) |
| `coverage-report` | Path to coverage report |

## Supported Languages

### Python
- **Package Managers**: pip, poetry, uv
- **Default Version**: 3.11
- **Parallelization**: pytest-split

### Node.js
- **Package Managers**: npm, yarn, pnpm
- **Default Version**: 20
- **Parallelization**: Jest sharding

### Ruby
- **Package Manager**: bundler
- **Default Version**: 3.2

### Go
- **Package Manager**: go mod
- **Default Version**: stable

### Rust
- **Package Manager**: cargo
- **Default Version**: stable

## Examples

### Complete CI Workflow

```yaml
name: Test
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.10', '3.11', '3.12']
    
    steps:
      - uses: actions/checkout@v4
      
      - uses: ./.github/actions/ci/run-tests
        with:
          language: 'python'
          language-version: ${{ matrix.python-version }}
          test-command: 'pytest'
          coverage-enabled: 'true'
          artifact-name: 'coverage-py${{ matrix.python-version }}'
```

### Multi-language Repository

```yaml
jobs:
  test-python:
    steps:
      - uses: ./.github/actions/ci/run-tests
        with:
          language: 'python'
          test-command: 'pytest backend/'
  
  test-node:
    steps:
      - uses: ./.github/actions/ci/run-tests
        with:
          language: 'node'
          test-command: 'npm test'
```

## Migration from run-backend-tests

If migrating from the Django-specific `run-backend-tests` action:

**Before:**
```yaml
- uses: ./.github/actions/run-backend-tests
  with:
    python-version: '3.11.9'
    segment: 'Core'
```

**After:**
```yaml
- uses: ./.github/actions/ci/run-tests
  with:
    language: 'python'
    language-version: '3.11.9'
    test-command: 'pytest'
    test-directory: 'posthog/ ee/'
    services-enabled: 'true'
    services-compose-file: 'docker-compose.dev.yml'
```

## Troubleshooting

### Tests fail to find dependencies
- Ensure `install-dependencies` is `true`
- Check `package-manager` is correctly specified
- Verify dependency files exist (requirements.txt, package.json, etc.)

### Services not ready
- Add a `services-wait-script` that polls service health
- Increase timeout in wait script
- Check Docker Compose file configuration

### Coverage not generated
- Ensure `coverage-enabled` is `true`
- Install coverage tools in dependencies (coverage.py, jest --coverage, etc.)
- Check coverage format is supported for your language

### Parallel tests fail
- Ensure test framework supports parallelization
- Install required plugins (pytest-split, etc.)
- Use unique test databases/resources per job

## Contributing

Contributions welcome! Please test changes across multiple languages before submitting.
