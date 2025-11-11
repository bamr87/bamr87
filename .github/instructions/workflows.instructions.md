---
file: workflows.instructions.md
description: VS Code Copilot-optimized GitHub Actions workflow standards for Django/OpenAI CI/CD automation
author: Barodybroject Team
created: 2025-10-11
lastModified: 2025-10-28
version: 1.1.0
applyTo: "**/.github/workflows/*.yml,**/.github/workflows/*.yaml"
dependencies:
  - copilot-instructions.md: Core principles and VS Code Copilot integration
  - languages.instructions.md: Script execution standards and automation patterns
  - test.instructions.md: Testing automation and validation workflows
  - features.instructions.md: Feature development pipeline integration
  - frontmatter.standards.md: Unified metadata and documentation standards
relatedEvolutions:
  - "Enhanced Django/OpenAI CI/CD pipeline patterns"
  - "Azure Container Apps deployment automation"
  - "AI service testing and validation workflows"
containerRequirements:
  baseImage: ubuntu-latest
  description: "GitHub Actions runner environment for Django/OpenAI CI/CD pipelines"
  services:
    - "postgres:15 for database testing"
    - "redis:alpine for caching tests"
  environment:
    DJANGO_SETTINGS_MODULE: barodybroject.settings.testing
    DATABASE_URL: postgresql://test_user:test_password@postgres:5432/test_db
    OPENAI_API_KEY: mock-key-for-ci-testing
    AZURE_CLIENT_ID: required-for-deployment
    AZURE_TENANT_ID: required-for-deployment
    AZURE_SUBSCRIPTION_ID: required-for-deployment
paths:
  ci_cd_workflow_path:
    - code_quality_validation
    - automated_testing
    - security_scanning
    - container_building
    - azure_deployment
    - monitoring_and_alerting
changelog:
  - date: "2025-10-28"
    description: "Enhanced with VS Code Copilot optimization and comprehensive Django/OpenAI CI/CD patterns"
    author: "Barodybroject Team"
  - date: "2025-10-11"
    description: "Initial creation with core GitHub Actions workflow standards"
    author: "Barodybroject Team"
usage: "Reference for all GitHub Actions workflows, CI/CD automation, and deployment pipelines for Django/OpenAI applications"
notes: "Emphasizes Django testing automation, OpenAI service validation, Azure deployment patterns, and container-first CI/CD"
---

# GitHub Actions Workflow Standards

## Workflow Structure and Organization

### Standard Workflow Elements

Every workflow should include:

```yaml
name: Clear Descriptive Name

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]
  workflow_dispatch:  # Allow manual triggering

env:
  PYTHON_VERSION: '3.8'
  NODE_VERSION: '18'
  CONTAINER_REGISTRY: ghcr.io

permissions:
  contents: read
  pull-requests: write
  packages: write

jobs:
  job-name:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
```

### Naming Conventions

**Workflow files:**
- `ci.yml` - Continuous integration (build, test, lint)
- `deploy-[env].yml` - Environment-specific deployments
- `security.yml` - Security scanning
- `container-build.yml` - Container image building

**Job names:**
- Use lowercase with hyphens
- Be descriptive: `build-and-test`, `deploy-to-azure`

**Step names:**
- Use emojis for visual scanning (optional but helpful)
- Be concise and action-oriented
- Examples: `🔨 Build Docker image`, `🧪 Run tests`, `🚀 Deploy to Azure`

## CI/CD Pipeline Patterns

### Continuous Integration Workflow

```yaml
# .github/workflows/ci.yml
name: CI - Build and Test

on:
  push:
    branches: [ main, develop, 'feature/**' ]
  pull_request:
    branches: [ main, develop ]

env:
  PYTHON_VERSION: '3.8'

jobs:
  lint:
    name: Lint Code
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: 'pip'
      
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install black flake8 pylint
      
      - name: Run Black
        run: black --check src/
      
      - name: Run Flake8
        run: flake8 src/ --max-line-length=100
      
      - name: Run Pylint
        run: pylint src/parodynews/ --disable=all --enable=E,F

  test:
    name: Run Tests
    runs-on: ubuntu-latest
    
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_DB: test_db
          POSTGRES_USER: test_user
          POSTGRES_PASSWORD: test_password
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: 'pip'
      
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements-dev.txt
      
      - name: Run migrations
        env:
          DATABASE_URL: postgresql://test_user:test_password@localhost:5432/test_db
        run: |
          cd src
          python manage.py migrate --noinput
      
      - name: Run tests
        env:
          DATABASE_URL: postgresql://test_user:test_password@localhost:5432/test_db
          SECRET_KEY: test-secret-key-not-for-production
        run: |
          cd src
          pytest --cov=parodynews --cov-report=xml --cov-report=term
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          files: ./src/coverage.xml
          flags: unittests

  build:
    name: Build Docker Image
    runs-on: ubuntu-latest
    needs: [lint, test]
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
      
      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3
      
      - name: Build image
        uses: docker/build-push-action@v5
        with:
          context: .
          push: false
          tags: barodybroject:test
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

### Container Build and Push Workflow

```yaml
# .github/workflows/container-build.yml
name: Build and Push Container

on:
  push:
    branches: [ main ]
    tags: [ 'v*' ]
  workflow_dispatch:

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

permissions:
  contents: read
  packages: write

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
      
      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3
      
      - name: Log in to Container Registry
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      
      - name: Extract metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
          tags: |
            type=ref,event=branch
            type=ref,event=pr
            type=semver,pattern={{version}}
            type=semver,pattern={{major}}.{{minor}}
            type=sha,prefix={{branch}}-
            type=raw,value=latest,enable={{is_default_branch}}
      
      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          target: production
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
          build-args: |
            BUILDKIT_INLINE_CACHE=1
```

### Azure Deployment Workflow

```yaml
# .github/workflows/deploy-production.yml
name: Deploy to Azure Production

on:
  push:
    branches: [ main ]
    tags: [ 'v*' ]
  workflow_dispatch:
    inputs:
      environment:
        description: 'Target environment'
        required: true
        default: 'production'
        type: choice
        options:
          - staging
          - production

permissions:
  contents: read
  id-token: write

jobs:
  deploy:
    name: Deploy to Azure
    runs-on: ubuntu-latest
    environment:
      name: ${{ inputs.environment || 'production' }}
      url: ${{ steps.deploy.outputs.url }}
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
      
      - name: Install Azure CLI
        uses: azure/login@v1
        with:
          client-id: ${{ secrets.AZURE_CLIENT_ID }}
          tenant-id: ${{ secrets.AZURE_TENANT_ID }}
          subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
      
      - name: Install Azure Developer CLI
        run: |
          curl -fsSL https://aka.ms/install-azd.sh | bash
      
      - name: Azure Developer CLI login
        run: |
          azd auth login \
            --client-id ${{ secrets.AZURE_CLIENT_ID }} \
            --client-secret ${{ secrets.AZURE_CLIENT_SECRET }} \
            --tenant-id ${{ secrets.AZURE_TENANT_ID }}
      
      - name: Provision infrastructure
        id: deploy
        run: |
          azd provision --no-prompt
          azd deploy --no-prompt
          
          # Get the deployed URL
          url=$(azd env get-values | grep CONTAINER_APP_URL | cut -d'=' -f2)
          echo "url=$url" >> $GITHUB_OUTPUT
      
      - name: Run smoke tests
        run: |
          # Wait for deployment to be ready
          sleep 30
          
          # Basic health check
          curl -f ${{ steps.deploy.outputs.url }}/health || exit 1
      
      - name: Notify deployment
        if: success()
        run: |
          echo "Deployment successful: ${{ steps.deploy.outputs.url }}"
```

### Security Scanning Workflow

```yaml
# .github/workflows/security.yml
name: Security Scanning

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]
  schedule:
    - cron: '0 0 * * 0'  # Weekly on Sunday

permissions:
  contents: read
  security-events: write

jobs:
  dependency-scan:
    name: Dependency Security Scan
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.8'
      
      - name: Install Safety
        run: pip install safety
      
      - name: Run Safety check
        run: |
          safety check --file requirements.txt --json || true
      
      - name: Run Bandit security linter
        run: |
          pip install bandit
          bandit -r src/parodynews/ -f json -o bandit-report.json || true
      
      - name: Upload security reports
        uses: actions/upload-artifact@v3
        if: always()
        with:
          name: security-reports
          path: |
            bandit-report.json

  container-scan:
    name: Container Security Scan
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
      
      - name: Build image for scanning
        run: |
          docker build -t barodybroject:scan .
      
      - name: Run Trivy vulnerability scanner
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: barodybroject:scan
          format: 'sarif'
          output: 'trivy-results.sarif'
      
      - name: Upload Trivy results
        uses: github/codeql-action/upload-sarif@v2
        with:
          sarif_file: 'trivy-results.sarif'
```

## Common Workflow Patterns

### Matrix Testing

```yaml
jobs:
  test-matrix:
    name: Test Python ${{ matrix.python-version }}
    runs-on: ubuntu-latest
    
    strategy:
      matrix:
        python-version: ['3.8', '3.9', '3.10', '3.11']
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v4
        with:
          python-version: ${{ matrix.python-version }}
      
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
      
      - name: Run tests
        run: |
          cd src
          pytest tests/
```

### Caching Dependencies

```yaml
- name: Set up Python with cache
  uses: actions/setup-python@v4
  with:
    python-version: '3.8'
    cache: 'pip'
    cache-dependency-path: |
      requirements.txt
      requirements-dev.txt

- name: Install dependencies
  run: |
    pip install -r requirements-dev.txt
```

### Conditional Execution

```yaml
- name: Deploy to production
  if: github.ref == 'refs/heads/main' && github.event_name == 'push'
  run: |
    ./scripts/deploy.sh production

- name: Run integration tests
  if: github.event_name == 'pull_request'
  run: |
    pytest tests/integration/
```

### Environment Variables and Secrets

```yaml
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: production
    
    steps:
      - name: Deploy application
        env:
          AZURE_CLIENT_ID: ${{ secrets.AZURE_CLIENT_ID }}
          AZURE_TENANT_ID: ${{ secrets.AZURE_TENANT_ID }}
          AZURE_SUBSCRIPTION_ID: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          SECRET_KEY: ${{ secrets.DJANGO_SECRET_KEY }}
        run: |
          ./scripts/deploy.sh production
```

## Error Handling and Debugging

### Failure Handling

```yaml
- name: Run tests
  id: tests
  continue-on-error: true
  run: pytest tests/

- name: Report test failure
  if: steps.tests.outcome == 'failure'
  run: |
    echo "Tests failed! Check the logs above."
    exit 1

- name: Cleanup on failure
  if: failure()
  run: |
    docker-compose down -v
    rm -rf tmp/*
```

### Debug Output

```yaml
- name: Debug information
  if: runner.debug == '1'
  run: |
    echo "=== Environment Variables ==="
    env | grep -E '^(GITHUB|RUNNER|PYTHON|NODE)_' | sort
    
    echo "=== Working Directory ==="
    pwd
    ls -la
    
    echo "=== Docker Info ==="
    docker --version
    docker-compose --version
```

## Artifact Management

### Upload Artifacts

```yaml
- name: Run tests with coverage
  run: |
    pytest --cov=parodynews --cov-report=html --cov-report=xml

- name: Upload coverage reports
  uses: actions/upload-artifact@v3
  with:
    name: coverage-reports
    path: |
      htmlcov/
      coverage.xml
    retention-days: 30
```

### Download Artifacts

```yaml
- name: Download test reports
  uses: actions/download-artifact@v3
  with:
    name: coverage-reports
    path: ./reports
```

## Deployment Patterns

### Multi-Environment Deployment

```yaml
# .github/workflows/deploy.yml
name: Deploy to Environment

on:
  workflow_dispatch:
    inputs:
      environment:
        description: 'Deployment environment'
        required: true
        type: choice
        options:
          - development
          - staging
          - production

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment:
      name: ${{ inputs.environment }}
      url: ${{ steps.get-url.outputs.url }}
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
      
      - name: Deploy to ${{ inputs.environment }}
        run: |
          chmod +x ./scripts/deploy.sh
          ./scripts/deploy.sh ${{ inputs.environment }}
      
      - name: Get deployment URL
        id: get-url
        run: |
          url=$(azd env get-values | grep APP_URL | cut -d'=' -f2)
          echo "url=$url" >> $GITHUB_OUTPUT
      
      - name: Health check
        run: |
          sleep 30
          curl -f ${{ steps.get-url.outputs.url }}/health
```

### Container Registry Integration

```yaml
jobs:
  publish:
    name: Publish to Container Registry
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
      
      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3
      
      - name: Log in to GitHub Container Registry
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      
      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: |
            ghcr.io/${{ github.repository }}:latest
            ghcr.io/${{ github.repository }}:${{ github.sha }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

## Testing Automation

### Test Workflow with Reports

```yaml
# .github/workflows/test.yml
name: Test Suite

on:
  pull_request:
  push:
    branches: [ main, develop ]

jobs:
  unit-tests:
    name: Unit Tests
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.8'
          cache: 'pip'
      
      - name: Install dependencies
        run: |
          pip install -r requirements-dev.txt
      
      - name: Run unit tests
        run: |
          cd src
          pytest tests/unit/ -v --junitxml=junit.xml
      
      - name: Publish test results
        uses: EnricoMi/publish-unit-test-result-action@v2
        if: always()
        with:
          files: src/junit.xml

  integration-tests:
    name: Integration Tests
    runs-on: ubuntu-latest
    
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_DB: test_db
          POSTGRES_USER: test_user
          POSTGRES_PASSWORD: test_password
        ports:
          - 5432:5432
        options: --health-cmd pg_isready --health-interval 10s
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.8'
          cache: 'pip'
      
      - name: Install dependencies
        run: |
          pip install -r requirements-dev.txt
      
      - name: Run migrations
        env:
          DATABASE_URL: postgresql://test_user:test_password@localhost:5432/test_db
          SECRET_KEY: test-secret-key
        run: |
          cd src
          python manage.py migrate
      
      - name: Run integration tests
        env:
          DATABASE_URL: postgresql://test_user:test_password@localhost:5432/test_db
          SECRET_KEY: test-secret-key
        run: |
          cd src
          pytest tests/integration/ -v
```

## Best Practices

### Security
- Never log or expose secrets in workflow output
- Use GitHub Secrets for sensitive data
- Use environment protection rules for production deployments
- Implement approval requirements for sensitive operations
- Scan dependencies and containers regularly

### Performance
- Use caching for dependencies (pip, npm)
- Use Docker layer caching (GitHub Actions cache)
- Run jobs in parallel when possible
- Set appropriate timeout limits
- Use matrix strategies for multi-version testing

### Maintainability
- Keep workflows focused on single purposes
- Use reusable workflows for common patterns
- Document complex logic with comments
- Use descriptive names for jobs and steps
- Version workflow dependencies (actions versions)

### Reliability
- Always include health checks after deployments
- Implement retry logic for flaky operations
- Use `continue-on-error` strategically
- Include cleanup steps with `if: always()`
- Set reasonable timeout values

## Common Workflow Examples

### PR Validation Workflow

```yaml
name: PR Validation

on:
  pull_request:
    types: [ opened, synchronize, reopened ]

jobs:
  validate:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Validate PR title
        run: |
          pr_title="${{ github.event.pull_request.title }}"
          if ! echo "$pr_title" | grep -E '^(feat|fix|docs|style|refactor|test|chore):'; then
            echo "PR title must start with a type: feat|fix|docs|style|refactor|test|chore"
            exit 1
          fi
      
      - name: Check for CHANGELOG entry
        run: |
          if ! git diff --name-only origin/main... | grep -q CHANGELOG.md; then
            echo "Please update CHANGELOG.md with your changes"
            exit 1
          fi
```

### Scheduled Maintenance Workflow

```yaml
name: Weekly Maintenance

on:
  schedule:
    - cron: '0 2 * * 0'  # Sunday at 2 AM UTC
  workflow_dispatch:

jobs:
  dependency-update:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Update pip dependencies
        run: |
          pip install pip-tools
          pip-compile requirements.in > requirements.txt
          pip-compile requirements-dev.in > requirements-dev.txt
      
      - name: Create PR if changes
        run: |
          if git diff --quiet requirements*.txt; then
            echo "No dependency updates"
            exit 0
          fi
          
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          
          branch="automated/dependency-update-$(date +%Y%m%d)"
          git checkout -b "$branch"
          git add requirements*.txt
          git commit -m "chore: update dependencies"
          git push origin "$branch"
          
          gh pr create \
            --title "chore: automated dependency update" \
            --body "Automated dependency updates from weekly maintenance" \
            --label "dependencies,automated"
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

## Troubleshooting

### Common Issues

**1. Workflow not triggering:**
- Check branch names in `on` section match exactly
- Verify workflow file is in `.github/workflows/` directory
- Ensure YAML syntax is valid

**2. Secrets not accessible:**
- Verify secrets are defined in repository settings
- Check secret names match exactly (case-sensitive)
- Ensure workflow has necessary permissions

**3. Docker build failures:**
- Check Dockerfile syntax
- Verify base images are accessible
- Ensure build context is correct
- Review build logs for specific errors

**4. Azure deployment failures:**
- Verify Azure credentials are valid
- Check Azure CLI is properly authenticated
- Ensure resource group and resources exist
- Review Azure deployment logs

### Debugging Workflows

Enable debug logging by setting repository secrets:
- `ACTIONS_STEP_DEBUG` = `true` (detailed step logs)
- `ACTIONS_RUNNER_DEBUG` = `true` (runner diagnostic logs)

Add debug steps in workflows:
```yaml
- name: Debug workflow
  run: |
    echo "GitHub Event: ${{ github.event_name }}"
    echo "GitHub Ref: ${{ github.ref }}"
    echo "GitHub SHA: ${{ github.sha }}"
    echo "Working Directory: $(pwd)"
    ls -la
```

