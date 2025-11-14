---
applyTo: 'CHANGELOG.md,CHANGES.md,**/version.*,VERSION,**/package.json,**/*.gemspec,**/Cargo.toml,**/go.mod'
---

# Version Control Guidelines

Version control, releases, and Git workflow guidelines. Universal patterns for managing versions, releases, and Git workflows across all project types.

## Git Workflow

### Branch Strategy

**Main Branch:**

- `main` or `master`: Stable production code
- Only merged releases and hotfixes
- Tags created here for versions

**Development Branches:**

- `develop`: Integration branch for next release
- `feature/*`: New features
- `bugfix/*`: Bug fixes
- `hotfix/*`: Urgent production fixes
- `release/*`: Preparing a new version

### Branch Naming

- `feature/add-authentication`
- `bugfix/fix-memory-leak`
- `hotfix/security-patch`
- `release/v2.0.0`

### Commit Messages

Use conventional commits format:

```text
<type>(<scope>): <description>

[optional body]

[optional footer]
```

**Types:**

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Formatting changes
- `refactor`: Code restructuring
- `test`: Adding/updating tests
- `chore`: Maintenance tasks

**Examples:**

```text
feat(auth): add user authentication
fix(api): resolve rate limiting issue
docs(readme): update installation instructions
```

## Semantic Versioning

Follow SemVer: `MAJOR.MINOR.PATCH`

- **PATCH (0.0.x)**: Backward-compatible bug fixes
- **MINOR (0.x.0)**: Backward-compatible new features
- **MAJOR (x.0.0)**: Breaking changes

### Version Management

- Update version in appropriate file (e.g., `version.rb`, `package.json`)
- Bump versions only on release branches
- Use prerelease versions for testing: `1.0.0.rc1`, `1.0.0.beta.1`

## Release Process

### Pre-Release Checklist

- [ ] All tests pass
- [ ] Version bumped
- [ ] Changelog updated
- [ ] Documentation updated
- [ ] Dependencies reviewed

### Release Steps

1. **Create release branch:**

   ```bash
   git checkout develop
   git checkout -b release/v2.0.0
   ```

2. **Bump version and update changelog**

3. **Test and validate:**

   ```bash
   ./scripts/test.sh
   ```

4. **Commit and tag:**

   ```bash
   git commit -m "chore: bump version to 2.0.0"
   git tag v2.0.0
   ```

5. **Merge to main:**

   ```bash
   git checkout main
   git merge release/v2.0.0
   git push origin main --tags
   ```

6. **Merge back to develop:**

   ```bash
   git checkout develop
   git merge main
   git push origin develop
   ```

## Changelog Management

### Format

```markdown
# Changelog

## [Unreleased]

### Added
- New features

### Changed
- Changes to existing functionality

### Fixed
- Bug fixes

## [2.0.0] - 2025-01-27

### Added
- Feature description

### Changed
- Change description
```

### Best Practices

- Update during development (in PRs)
- Group by type (Added, Changed, Fixed, etc.)
- Reverse chronological order
- Meaningful summaries (not raw git logs)
- Update before each release

## Hotfix Process

For critical bugs in production:

1. **Create hotfix branch from affected tag:**

   ```bash
   git checkout v2.0.1
   git checkout -b hotfix/v2.0.2-critical-fix
   ```

2. **Apply minimal fix and test**

3. **Release hotfix:**

   ```bash
   git commit -m "Hotfix: critical security vulnerability"
   git tag v2.0.2
   git push origin main --tags
   ```

4. **Merge forward to develop**

## GitHub Actions Automation

### Version Bump Workflow

```yaml
# .github/workflows/version-bump.yml
name: Version Bump

on:
  workflow_dispatch:
    inputs:
      version_type:
        description: 'Version bump type'
        required: true
        type: choice
        options:
          - patch
          - minor
          - major

jobs:
  bump-version:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
        with:
          fetch-depth: 0
      
      - name: Set up environment
        uses: actions/setup-python@v4  # or setup-node, setup-ruby
        with:
          python-version: '3.11'
      
      - name: Bump version
        id: bump
        run: |
          # Your version bump script
          ./scripts/version-bump.sh ${{ inputs.version_type }}
          
          # Get new version
          NEW_VERSION=$(cat VERSION)
          echo "new_version=$NEW_VERSION" >> $GITHUB_OUTPUT
      
      - name: Commit and tag
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          
          git add .
          git commit -m "chore: bump version to ${{ steps.bump.outputs.new_version }}"
          git tag "v${{ steps.bump.outputs.new_version }}"
          git push origin main --tags
```

### Release Automation

```yaml
# .github/workflows/release.yml
name: Release

on:
  push:
    tags:
      - 'v*'

jobs:
  release:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
        with:
          fetch-depth: 0
      
      - name: Extract version from tag
        id: version
        run: echo "version=${GITHUB_REF#refs/tags/v}" >> $GITHUB_OUTPUT
      
      - name: Extract changelog
        id: changelog
        run: |
          # Extract changelog for this version
          ./scripts/extract-changelog.sh ${{ steps.version.outputs.version }} > release-notes.md
      
      - name: Create GitHub Release
        uses: softprops/action-gh-release@v1
        with:
          body_path: release-notes.md
          draft: false
          prerelease: ${{ contains(steps.version.outputs.version, 'rc') || contains(steps.version.outputs.version, 'beta') || contains(steps.version.outputs.version, 'alpha') }}
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

## Package Publishing

### Python Package (PyPI)

```bash
# Build and publish Python package
python -m build
python -m twine upload dist/*
```

```yaml
# GitHub Actions for PyPI publishing
- name: Build package
  run: python -m build

- name: Publish to PyPI
  uses: pypa/gh-action-pypi-publish@release/v1
  with:
    password: ${{ secrets.PYPI_API_TOKEN }}
```

### NPM Package

```bash
# Update version and publish
npm version patch  # or minor, major
npm publish
```

```yaml
# GitHub Actions for NPM publishing
- name: Setup Node
  uses: actions/setup-node@v4
  with:
    node-version: '18'
    registry-url: 'https://registry.npmjs.org'

- name: Publish to NPM
  run: npm publish
  env:
    NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}
```

### Ruby Gem

```bash
# Build and publish Ruby gem
gem build gem_name.gemspec
gem push gem_name-X.Y.Z.gem
```

```yaml
# GitHub Actions for RubyGems publishing
- name: Setup Ruby
  uses: ruby/setup-ruby@v1
  with:
    ruby-version: '3.2'

- name: Build and publish gem
  run: |
    gem build *.gemspec
    gem push *.gem
  env:
    GEM_HOST_API_KEY: ${{ secrets.RUBYGEMS_API_KEY }}
```

## Multi-Repository Version Management

### Monorepo Versioning

For projects with multiple packages:

```json
// package.json with workspaces
{
  "private": true,
  "workspaces": [
    "packages/*"
  ],
  "scripts": {
    "version:patch": "lerna version patch",
    "version:minor": "lerna version minor",
    "version:major": "lerna version major"
  }
}
```

### Independent Repository Versioning

For related repositories:

- Maintain separate version numbers
- Document inter-repository dependencies
- Use dependency version constraints
- Coordinate breaking changes
- Update cross-repository documentation

## Security Considerations

### Secure Version Control

- Sign commits and tags when possible (GPG signing)
- Use GitHub security advisories for vulnerability disclosure
- Follow responsible disclosure practices
- Never commit secrets in any branch (including historical commits)
- Rotate keys/secrets after accidental commits

### Access Control

- Limit access to release branches and tags
- Enable branch protection rules for main/master
- Require review approvals before merges
- Use CODEOWNERS for sensitive areas
- Implement security scanning in CI/CD

### Dependency Security

- Regularly audit dependencies for vulnerabilities
- Use automated security scanning (Dependabot, Snyk)
- Keep dependencies updated with security patches
- Use lockfiles for reproducible builds
- Document security-related dependency constraints

---

**Version:** 3.0.0 | **Last Modified:** 2025-11-14 | **Author:** Amr Abdel-Motaleb

**Purpose:** Universal version control and release management template for various project types, package managers, and deployment strategies.
