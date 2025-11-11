# GitHub Actions Library

A collection of reusable composite actions for CI/CD workflows. These actions are designed to be framework-agnostic and easily portable across repositories.

## 📁 Directory Structure

```
actions/
├── setup/              # Environment setup actions
│   ├── configure-git/
│   └── setup-ruby/
├── ci/                 # Continuous Integration actions
│   ├── run-checks/
│   └── run-tests/
├── deployment/         # Build and deployment actions
│   └── build-push-image/
└── utilities/          # Helper utilities
    └── get-pr-labels/
```

## 🎯 Quick Start

### Using Actions in Your Workflows

Reference actions using either:

**1. From the same repository:**
```yaml
- uses: ./.github/actions/setup/configure-git
  with:
    github-token: ${{ secrets.GITHUB_TOKEN }}
```

**2. From another repository:**
```yaml
- uses: owner/repo/.github/actions/setup/configure-git@main
  with:
    github-token: ${{ secrets.GITHUB_TOKEN }}
```

## 📚 Available Actions

### Setup Actions

#### configure-git
Configures Git with user information and authentication for automated commits.

```yaml
- uses: ./.github/actions/setup/configure-git
  with:
    user-name: 'github-actions[bot]'
    user-email: 'github-actions[bot]@users.noreply.github.com'
    github-token: ${{ secrets.GITHUB_TOKEN }}
```

#### setup-ruby
Sets up Ruby environment with bundler caching and dependencies.

```yaml
- uses: ./.github/actions/setup/setup-ruby
  with:
    ruby-version: '3.2'
    install-system-deps: 'true'
```

### CI Actions

#### run-checks
Run tests, quality checks, and other validations with customizable scripts.

```yaml
- uses: ./.github/actions/ci/run-checks
  with:
    setup-script: './scripts/setup.sh'
    test-script: './scripts/test.sh'
    quality-script: './scripts/lint.sh'
```

#### run-tests
Generic test runner for any language/framework with matrix support.

```yaml
- uses: ./.github/actions/ci/run-tests
  with:
    language: 'python'
    version: '3.11'
    test-command: 'pytest tests/'
```

### Deployment Actions

#### build-push-image
Build and push Docker images to multiple registries with caching.

```yaml
- uses: ./.github/actions/deployment/build-push-image
  with:
    image-name: 'my-app'
    image-tag: ${{ github.sha }}
    registry-url: 'ghcr.io/owner'
    push-image: 'true'
```

### Utility Actions

#### get-pr-labels
Retrieve labels from the merged PR that triggered the workflow.

```yaml
- uses: ./.github/actions/utilities/get-pr-labels
  with:
    token: ${{ secrets.GITHUB_TOKEN }}
```

## 🔧 Customization Guide

### Creating Custom Actions

1. **Choose the appropriate category** (setup/ci/deployment/utilities)
2. **Use the action template**:

```yaml
name: 'Your Action Name'
description: 'Brief description of what this action does'

inputs:
  input-name:
    description: 'Description of the input'
    required: true
    default: 'default-value'

outputs:
  output-name:
    description: 'Description of the output'
    value: ${{ steps.step-id.outputs.value }}

runs:
  using: 'composite'
  steps:
    - name: Step description
      shell: bash
      run: |
        echo "Your commands here"
```

3. **Add documentation** in the action's README.md
4. **Create example workflows** in `examples/`

## 📖 Best Practices

### Action Design Principles

1. **Single Responsibility**: Each action should do one thing well
2. **Parameterization**: Use inputs for customization rather than hardcoding
3. **Clear Naming**: Use descriptive names that indicate purpose
4. **Documentation**: Include comprehensive README for each action
5. **Error Handling**: Use proper exit codes and error messages
6. **Idempotency**: Actions should be safe to run multiple times

### Input Guidelines

- Use `required: true` only for essential inputs
- Provide sensible defaults when possible
- Use clear, descriptive input names
- Document all inputs with descriptions
- Use validation in steps when needed

### Output Guidelines

- Expose useful information for downstream jobs
- Use consistent naming conventions
- Document what each output contains
- Consider JSON format for complex outputs

## 🔄 Migration Guide

### Moving Actions to Another Repository

1. **Copy the action directory** to the new repo's `.github/actions/`
2. **Update any hardcoded references** to repository-specific values
3. **Test the action** in a workflow in the new repo
4. **Update documentation** with new repository path

### Converting to Reusable Workflows

If your action becomes complex, consider converting it to a reusable workflow:

```yaml
# .github/workflows/reusable-test.yml
name: Reusable Test Workflow
on:
  workflow_call:
    inputs:
      test-command:
        required: true
        type: string
```

## 🧪 Testing Actions

### Local Testing with act

```bash
# Install act
brew install act

# Run a workflow that uses your action
act -W .github/workflows/test.yml
```

### Testing in Pull Requests

Create test workflows in `.github/workflows/test-*.yml` that run on PR creation.

## 📦 Dependencies

### Common Action Dependencies

- `actions/checkout@v4` - Checkout repository
- `actions/setup-node@v4` - Setup Node.js
- `actions/setup-python@v5` - Setup Python
- `ruby/setup-ruby@v1` - Setup Ruby
- `docker/setup-buildx-action@v3` - Docker Buildx

### Managing Versions

Use specific versions or SHA for production:
```yaml
uses: actions/checkout@8f4b7f84864484a7bf31766abe9204da3cbe65b3
```

## 🤝 Contributing

1. Fork and create a feature branch
2. Make changes following best practices
3. Test thoroughly
4. Submit PR with clear description
5. Update documentation

## 📝 Examples

See the `examples/` directory for complete workflow examples using these actions.

## 🐛 Troubleshooting

### Common Issues

**Issue**: Action not found
- **Solution**: Ensure correct path and repository reference

**Issue**: Permission denied errors
- **Solution**: Check `permissions` in workflow and token scopes

**Issue**: Environment variables not available
- **Solution**: Composite actions don't inherit env - pass as inputs

## 📄 License

MIT License - See repository LICENSE file

## 🔗 Resources

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Creating Composite Actions](https://docs.github.com/en/actions/creating-actions/creating-a-composite-action)
- [Action Metadata Syntax](https://docs.github.com/en/actions/creating-actions/metadata-syntax-for-github-actions)
