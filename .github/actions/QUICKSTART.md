# Quick Start Guide

Get started with the refactored GitHub Actions in 5 minutes.

## 🚀 Choose Your Use Case

### I want to test my Python project

```yaml
name: Python CI
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - uses: ./.github/actions/ci/run-tests
        with:
          language: 'python'
          language-version: '3.11'
          test-command: 'pytest'
          coverage-enabled: 'true'
```

### I want to test my Node.js project

```yaml
name: Node.js CI
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - uses: ./.github/actions/ci/run-tests
        with:
          language: 'node'
          language-version: '20'
          test-command: 'npm test'
```

### I want to build and push Docker images

```yaml
name: Build Docker Image
on: [push]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - uses: ./.github/actions/deployment/build-push-image
        with:
          image-name: 'myapp'
          registry-type: 'ghcr'
          ghcr-token: ${{ secrets.GITHUB_TOKEN }}
          push-image: 'true'
```

### I want to automate commits

```yaml
name: Auto Update
on:
  schedule:
    - cron: '0 0 * * 0'

jobs:
  update:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
      
      - uses: ./.github/actions/setup/configure-git
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
      
      - name: Make changes
        run: |
          # Your update script
          npm update
      
      - name: Commit
        run: |
          git add .
          git commit -m "chore: auto update"
          git push
```

### I want to run custom test scripts

```yaml
name: Custom CI
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - uses: ./.github/actions/ci/run-checks
        with:
          setup-script: './scripts/setup.sh'
          test-script: './scripts/test.sh'
          quality-script: './scripts/lint.sh'
```

## 📚 Action Reference

| Action | Purpose | When to Use |
|--------|---------|-------------|
| [ci/run-tests](ci/run-tests/README.md) | Run tests for any language | Standard testing workflow |
| [ci/run-checks](ci/run-checks/README.md) | Run custom scripts | Custom CI pipelines |
| [deployment/build-push-image](deployment/build-push-image/README.md) | Build Docker images | Container deployment |
| [setup/configure-git](setup/configure-git/README.md) | Setup Git credentials | Automated commits/PRs |
| [setup/setup-ruby](setup/setup-ruby/README.md) | Setup Ruby environment | Ruby projects |
| [utilities/get-pr-labels](utilities/get-pr-labels/README.md) | Get PR labels | Conditional workflows |

## 🎯 Common Workflows

### Multi-Version Testing

```yaml
strategy:
  matrix:
    version: ['3.9', '3.10', '3.11', '3.12']

steps:
  - uses: ./.github/actions/ci/run-tests
    with:
      language: 'python'
      language-version: ${{ matrix.version }}
      test-command: 'pytest'
```

### Parallel Tests

```yaml
strategy:
  matrix:
    shard: [1, 2, 3, 4]

steps:
  - uses: ./.github/actions/ci/run-tests
    with:
      language: 'python'
      test-command: 'pytest'
      parallel-jobs: 4
      job-index: ${{ matrix.shard }}
```

### Multi-Platform Docker

```yaml
- uses: ./.github/actions/deployment/build-push-image
  with:
    image-name: 'myapp'
    platforms: 'linux/amd64,linux/arm64'
    push-image: 'true'
```

## 💡 Pro Tips

1. **Use caching**: Most actions enable caching by default
2. **Set permissions**: Some actions need explicit permissions
3. **Use secrets**: Never hardcode credentials
4. **Test in branches**: Test workflow changes before merging
5. **Read the READMEs**: Each action has comprehensive docs

## 📖 Next Steps

- Browse [example workflows](examples/)
- Read the [main README](README.md)
- Check [troubleshooting guides](README.md#🐛-troubleshooting) in each action's README
- See the [refactoring summary](REFACTORING_SUMMARY.md) for migration

## ❓ Need Help?

- Check the action's README for detailed documentation
- Look at [examples/](examples/) for real-world usage
- Review [troubleshooting sections](#) in each README
- Open an issue for questions

## 🔄 Migrating from Old Actions?

See deprecation notices:
- [run-backend-tests](run-backend-tests/README.md) → Use [ci/run-tests](ci/run-tests/README.md)
- [build-n-cache-image](deployment/build-n-cache-image/README.md) → Use [deployment/build-push-image](deployment/build-push-image/README.md)

---

**Ready to go?** Copy one of the examples above and customize it for your project!
