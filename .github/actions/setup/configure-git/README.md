# Configure Git Action

Configures Git with user information and authentication for automated commits and operations in GitHub Actions workflows.

## Features

- 🔐 **Automatic Authentication**: Sets up Git credentials using GitHub token
- 👤 **User Configuration**: Configures Git user name and email
- 🛡️ **Safe Directory**: Marks workspace as safe for Git operations
- ✅ **Verification**: Validates authentication setup

## Usage

### Basic Usage

```yaml
- uses: ./.github/actions/setup/configure-git
  with:
    github-token: ${{ secrets.GITHUB_TOKEN }}
```

### Custom Git User

```yaml
- uses: ./.github/actions/setup/configure-git
  with:
    user-name: 'Custom Bot'
    user-email: 'bot@example.com'
    github-token: ${{ secrets.GITHUB_TOKEN }}
```

### In Automated PR Workflows

```yaml
name: Auto Update
on:
  schedule:
    - cron: '0 0 * * 0'

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - uses: ./.github/actions/setup/configure-git
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
      
      - name: Make changes
        run: |
          # Your update logic
          echo "Updated at $(date)" >> UPDATED.txt
      
      - name: Commit and push
        run: |
          git add .
          git commit -m "chore: automated update"
          git push
```

## Inputs

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `user-name` | Git user name | No | `github-actions[bot]` |
| `user-email` | Git user email | No | `github-actions[bot]@users.noreply.github.com` |
| `github-token` | GitHub token for authentication | Yes | - |

## What It Does

1. **Configures Git User**: Sets `user.name` and `user.email` globally
2. **Sets Up Authentication**: Configures Git to use the GitHub token for HTTPS operations
3. **Marks Safe Directory**: Adds the workspace and all subdirectories as safe
4. **Verifies Setup**: Attempts to verify authentication (with graceful failure)

## Common Use Cases

### Automated Dependency Updates

```yaml
- uses: ./.github/actions/setup/configure-git
  with:
    github-token: ${{ secrets.GITHUB_TOKEN }}

- name: Update dependencies
  run: |
    npm update
    git add package*.json
    git commit -m "chore: update dependencies"
    git push
```

### Auto-Generated Documentation

```yaml
- uses: ./.github/actions/setup/configure-git
  with:
    github-token: ${{ secrets.GITHUB_TOKEN }}

- name: Generate docs
  run: npm run docs

- name: Commit docs
  run: |
    git add docs/
    git commit -m "docs: regenerate documentation"
    git push
```

### Version Bumping

```yaml
- uses: ./.github/actions/setup/configure-git
  with:
    github-token: ${{ secrets.GITHUB_TOKEN }}

- name: Bump version
  run: npm version patch

- name: Push version
  run: git push --follow-tags
```

### Creating Pull Requests

```yaml
- uses: ./.github/actions/setup/configure-git
  with:
    github-token: ${{ secrets.GITHUB_TOKEN }}

- name: Create feature branch
  run: |
    git checkout -b automated-update
    # Make changes
    git add .
    git commit -m "feat: automated feature"
    git push origin automated-update

- name: Create PR
  uses: peter-evans/create-pull-request@v5
```

## Authentication Methods

The action configures Git to use HTTPS with token authentication:

```bash
git config --global url."https://x-access-token:${TOKEN}@github.com/".insteadOf "https://github.com/"
```

This allows Git operations to authenticate automatically without manual credential entry.

## Permissions Required

The workflow must have appropriate permissions for the token:

```yaml
permissions:
  contents: write  # Required for pushing commits
```

## Troubleshooting

### Push fails with permission denied
**Solution**: Ensure the workflow has `contents: write` permission

### Commits appear as different user
**Solution**: Verify `user-name` and `user-email` inputs are set correctly

### Safe directory warnings
**Solution**: Action automatically handles this, but ensure workspace is checked out first

### Authentication verification fails
**Solution**: This is non-fatal; Git operations will still work if the token is valid

## Best Practices

1. **Always use `${{ secrets.GITHUB_TOKEN }}`** - Don't use PATs unless necessary
2. **Set permissions explicitly** in workflow
3. **Use the default bot user** unless you need custom attribution
4. **Run after `actions/checkout@v4`** in your workflow
5. **Combine with branch protection rules** for safety

## Security Notes

- The action uses GitHub's built-in `GITHUB_TOKEN` by default
- Tokens are masked in logs automatically
- Git credentials are configured per-workflow, not persisted
- Safe directory configuration prevents security warnings

## Example: Complete Auto-Update Workflow

```yaml
name: Weekly Dependency Update

on:
  schedule:
    - cron: '0 0 * * 0'  # Every Sunday
  workflow_dispatch:

permissions:
  contents: write
  pull-requests: write

jobs:
  update:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      
      - uses: ./.github/actions/setup/configure-git
        with:
          user-name: 'Dependency Bot'
          user-email: 'deps@example.com'
          github-token: ${{ secrets.GITHUB_TOKEN }}
      
      - name: Update dependencies
        run: |
          npm update
          npm audit fix || true
      
      - name: Check for changes
        id: check
        run: |
          if [[ -n $(git status -s) ]]; then
            echo "has-changes=true" >> $GITHUB_OUTPUT
          fi
      
      - name: Commit and push
        if: steps.check.outputs.has-changes == 'true'
        run: |
          git add .
          git commit -m "chore: update dependencies [skip ci]"
          git push
```

## Related Actions

- [`actions/checkout`](https://github.com/actions/checkout) - Check out repository
- [`peter-evans/create-pull-request`](https://github.com/peter-evans/create-pull-request) - Create PRs
- [`stefanzweifel/git-auto-commit-action`](https://github.com/stefanzweifel/git-auto-commit-action) - Alternative commit action
