# Get PR Labels Action

Retrieves labels from the pull request that was merged to trigger a push event. Useful for conditional workflows based on PR metadata.

## Features

- 🏷️ **Auto-Detection**: Finds the PR associated with a commit
- 📋 **Label Extraction**: Returns all labels as JSON array
- 🔄 **Merge-Aware**: Works specifically for merged PRs
- 🚦 **Conditional Logic**: Enable workflow steps based on labels

## Usage

### Basic Usage

```yaml
- uses: ./.github/actions/utilities/get-pr-labels
  id: labels
  with:
    token: ${{ secrets.GITHUB_TOKEN }}

- name: Check labels
  run: |
    echo "PR Labels: ${{ steps.labels.outputs.labels }}"
```

### Conditional Deployment

```yaml
name: Deploy on Label

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - uses: ./.github/actions/utilities/get-pr-labels
        id: pr-labels
        with:
          token: ${{ secrets.GITHUB_TOKEN }}
      
      - name: Deploy to production
        if: contains(steps.pr-labels.outputs.labels, 'deploy:prod')
        run: |
          echo "Deploying to production..."
          # Your deployment logic
      
      - name: Deploy to staging
        if: contains(steps.pr-labels.outputs.labels, 'deploy:staging')
        run: |
          echo "Deploying to staging..."
          # Your deployment logic
```

## Inputs

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `token` | GitHub token | Yes | - |

## Outputs

| Output | Description |
|--------|-------------|
| `labels` | JSON array of label names from the merged PR (e.g., `["bug", "enhancement"]`). Empty array `[]` if no PR found. |

## How It Works

1. **Find Associated PR**: Queries GitHub API for PRs associated with the commit
2. **Extract PR Number**: Parses the PR number from the response
3. **Fetch Labels**: Retrieves all labels from that PR
4. **Return as JSON**: Outputs labels as a JSON array for easy parsing

## Complete Examples

### Conditional CI Steps

```yaml
name: CI with PR Labels

on:
  push:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - uses: ./.github/actions/utilities/get-pr-labels
        id: labels
        with:
          token: ${{ secrets.GITHUB_TOKEN }}
      
      - name: Run expensive tests
        if: contains(steps.labels.outputs.labels, 'test:full')
        run: npm run test:all
      
      - name: Run quick tests
        if: "!contains(steps.labels.outputs.labels, 'test:full')"
        run: npm run test:unit
      
      - name: Build documentation
        if: contains(steps.labels.outputs.labels, 'docs')
        run: npm run docs:build
```

### Environment-Specific Deployments

```yaml
name: Smart Deploy

on:
  push:
    branches: [main]

jobs:
  check-labels:
    runs-on: ubuntu-latest
    outputs:
      labels: ${{ steps.get-labels.outputs.labels }}
    steps:
      - uses: ./.github/actions/utilities/get-pr-labels
        id: get-labels
        with:
          token: ${{ secrets.GITHUB_TOKEN }}
  
  deploy-dev:
    needs: check-labels
    if: contains(needs.check-labels.outputs.labels, 'env:dev')
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to dev
        run: echo "Deploying to dev..."
  
  deploy-staging:
    needs: check-labels
    if: contains(needs.check-labels.outputs.labels, 'env:staging')
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to staging
        run: echo "Deploying to staging..."
  
  deploy-prod:
    needs: check-labels
    if: contains(needs.check-labels.outputs.labels, 'env:prod')
    runs-on: ubuntu-latest
    environment: production
    steps:
      - name: Deploy to production
        run: echo "Deploying to production..."
```

### Version Bump Based on Labels

```yaml
name: Version Bump

on:
  push:
    branches: [main]

jobs:
  bump:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - uses: ./.github/actions/utilities/get-pr-labels
        id: labels
        with:
          token: ${{ secrets.GITHUB_TOKEN }}
      
      - name: Bump major version
        if: contains(steps.labels.outputs.labels, 'version:major')
        run: npm version major
      
      - name: Bump minor version
        if: contains(steps.labels.outputs.labels, 'version:minor')
        run: npm version minor
      
      - name: Bump patch version
        if: contains(steps.labels.outputs.labels, 'version:patch')
        run: npm version patch
      
      - uses: ./.github/actions/setup/configure-git
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
      
      - name: Push version bump
        run: git push --follow-tags
```

### Changelog Generation

```yaml
name: Update Changelog

on:
  push:
    branches: [main]

jobs:
  changelog:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - uses: ./.github/actions/utilities/get-pr-labels
        id: labels
        with:
          token: ${{ secrets.GITHUB_TOKEN }}
      
      - name: Add to changelog
        run: |
          LABELS='${{ steps.labels.outputs.labels }}'
          if echo "$LABELS" | jq -e 'contains(["feature"])' > /dev/null; then
            SECTION="Features"
          elif echo "$LABELS" | jq -e 'contains(["bug"])' > /dev/null; then
            SECTION="Bug Fixes"
          elif echo "$LABELS" | jq -e 'contains(["breaking"])' > /dev/null; then
            SECTION="Breaking Changes"
          else
            SECTION="Other"
          fi
          
          echo "## $SECTION" >> CHANGELOG.md
          echo "- ${{ github.event.head_commit.message }}" >> CHANGELOG.md
```

### Skip CI Based on Labels

```yaml
name: CI

on:
  push:
    branches: [main]

jobs:
  check-labels:
    runs-on: ubuntu-latest
    outputs:
      should-skip: ${{ steps.check.outputs.skip }}
    steps:
      - uses: ./.github/actions/utilities/get-pr-labels
        id: labels
        with:
          token: ${{ secrets.GITHUB_TOKEN }}
      
      - name: Check skip label
        id: check
        run: |
          if echo '${{ steps.labels.outputs.labels }}' | jq -e 'contains(["skip-ci"])' > /dev/null; then
            echo "skip=true" >> $GITHUB_OUTPUT
          else
            echo "skip=false" >> $GITHUB_OUTPUT
          fi
  
  build:
    needs: check-labels
    if: needs.check-labels.outputs.should-skip != 'true'
    runs-on: ubuntu-latest
    steps:
      - name: Build
        run: echo "Building..."
```

## Label Naming Conventions

Suggested label naming patterns:

### Deployment
- `deploy:prod`, `deploy:staging`, `deploy:dev`
- `env:production`, `env:staging`

### Testing
- `test:full`, `test:quick`, `skip-tests`

### Versioning
- `version:major`, `version:minor`, `version:patch`

### Change Type
- `feature`, `bug`, `hotfix`, `breaking`

### Documentation
- `docs`, `docs:api`, `docs:readme`

### Priority
- `priority:high`, `priority:low`

## JSON Processing

The labels are returned as a JSON array, making them easy to process:

```yaml
- name: Process labels
  run: |
    LABELS='${{ steps.labels.outputs.labels }}'
    
    # Check if specific label exists
    if echo "$LABELS" | jq -e 'contains(["feature"])' > /dev/null; then
      echo "This is a feature"
    fi
    
    # Get label count
    COUNT=$(echo "$LABELS" | jq 'length')
    echo "PR had $COUNT labels"
    
    # Iterate over labels
    echo "$LABELS" | jq -r '.[]' | while read label; do
      echo "Processing label: $label"
    done
```

## Troubleshooting

### No labels returned for merged PR
**Cause**: The commit may not be associated with a PR
**Solution**: Ensure workflow triggers on push after PR merge, not direct commits

### Labels output is empty array
**Cause**: PR exists but has no labels, or PR wasn't found
**Solution**: Check that PRs are properly labeled before merging

### Permission denied error
**Cause**: Token lacks necessary permissions
**Solution**: Ensure `GITHUB_TOKEN` has `pull-requests: read` permission

```yaml
permissions:
  pull-requests: read
```

### Wrong PR detected
**Cause**: Multiple PRs may reference the same commit
**Solution**: Action uses the most recent PR; ensure clean merge workflow

## Limitations

- Only works on `push` events triggered by merged PRs
- Does not work on direct commits to branches
- Returns empty array if no PR is associated with the commit
- Label fetch continues on error (graceful degradation)

## Best Practices

1. **Establish label conventions** across your team
2. **Document expected labels** in CONTRIBUTING.md
3. **Use label validation** in PR workflows
4. **Combine with branch protection** for required labels
5. **Fail gracefully** when labels are missing

## Permissions Required

```yaml
permissions:
  pull-requests: read  # Required to fetch PR labels
```

## Related Actions

- [`actions/labeler`](https://github.com/actions/labeler) - Auto-label PRs
- [`actions-ecosystem/action-add-labels`](https://github.com/actions-ecosystem/action-add-labels) - Add labels
- [`agilepathway/label-checker`](https://github.com/agilepathway/label-checker) - Validate required labels

## Alternative Approaches

If you don't need merged PR labels specifically, consider:

- **Workflow dispatch inputs**: Manual trigger with parameters
- **Branch naming**: Parse environment from branch name
- **Commit messages**: Parse deployment info from commit messages
- **GitHub Environments**: Use environment-specific secrets

This action is specifically useful when you want PR labels to influence post-merge workflows.
