# Example Workflows

This directory contains example workflows demonstrating how to use the reusable actions in this repository.

## 📋 Available Examples

- [`python-ci.yml`](python-ci.yml) - Python project CI with pytest
- [`nodejs-ci.yml`](nodejs-ci.yml) - Node.js project CI with Jest
- [`ruby-ci.yml`](ruby-ci.yml) - Ruby project CI with RSpec
- [`docker-build.yml`](docker-build.yml) - Docker image build and push
- [`multi-language.yml`](multi-language.yml) - Monorepo with multiple languages
- [`parallel-tests.yml`](parallel-tests.yml) - Parallel test execution
- [`release.yml`](release.yml) - Complete release workflow

## 🚀 Using These Examples

1. **Copy** the relevant example to your `.github/workflows/` directory
2. **Customize** inputs for your project
3. **Update** action paths if using from a different repository
4. **Add** required secrets to your repository settings

## 📝 Action Path Formats

### Same Repository
```yaml
uses: ./.github/actions/ci/run-tests
```

### Different Repository
```yaml
uses: owner/repo/.github/actions/ci/run-tests@main
```

### Specific Version
```yaml
uses: owner/repo/.github/actions/ci/run-tests@v1.0.0
```

## 🔑 Required Secrets

Depending on which actions you use, configure these secrets:

### Git Operations
- `GITHUB_TOKEN` - Automatically provided by GitHub

### Docker Registries
- `DOCKERHUB_USERNAME` - DockerHub username
- `DOCKERHUB_TOKEN` - DockerHub access token
- `AWS_ACCESS_KEY_ID` - AWS access key for ECR
- `AWS_SECRET_ACCESS_KEY` - AWS secret key for ECR
- `GCP_SA_KEY` - GCP service account JSON key
- `AZURE_CLIENT_ID` - Azure client ID
- `AZURE_CLIENT_SECRET` - Azure client secret
- `AZURE_TENANT_ID` - Azure tenant ID

## 💡 Tips

- Start with the simplest example and add complexity
- Use matrix strategies for testing multiple versions
- Enable caching to speed up workflows
- Use `pull_request` and `push` triggers appropriately
- Add status badges to your README

## 🔧 Customization

Each example is a starting point. Common customizations:

- Add linting and formatting checks
- Include security scanning
- Add deployment steps
- Configure notifications
- Set up dependent jobs
