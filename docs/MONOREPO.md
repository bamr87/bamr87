# Monorepo Organization

This document explains how the bamr87 repository is organized as a monorepo using Git submodules.

## Overview

The bamr87 repository serves multiple purposes:
- **GitHub Profile**: The root README.md showcases professional experience and projects
- **Documentation Hub**: Aggregated documentation from multiple sources (README submodule)
- **CV Builder**: AI-powered CV/resume builder application (cv submodule)
- **Automation Scripts**: Collection of development and deployment utilities (scripts submodule)

## Repository Structure

```
bamr87/
├── .github/              # GitHub Actions workflows
│   └── workflows/
│       ├── update-submodules.yml  # Automated submodule updates
│       └── build-docs.yml         # Documentation deployment
├── assets/               # Shared assets (headshots, images)
├── cv/                   # Submodule: CV Builder application
├── README/               # Submodule: Documentation aggregation system
├── scripts/              # Submodule: Automation and utility scripts
├── docs/                 # Root-level monorepo documentation
│   ├── ARCHITECTURE.md   # System design decisions
│   ├── DEVELOPMENT.md    # Development setup guide
│   └── MONOREPO.md       # This file
├── .gitignore           # Comprehensive ignore patterns
├── .gitmodules          # Submodule configuration
├── CONTRIBUTING.md      # Contribution guidelines
├── README.md            # GitHub profile README
├── SUBMODULES.md        # Submodule management guide
├── mkdocs.yml           # Documentation site configuration
└── requirements-docs.txt # Documentation dependencies
```

## Why a Monorepo?

### Benefits

1. **Unified Version Control**: Single source of truth for related projects
2. **Simplified Dependency Management**: Shared configurations and tools
3. **Atomic Changes**: Cross-project changes in a single commit
4. **Centralized CI/CD**: Unified workflows for all projects
5. **Code Reuse**: Share assets and utilities across projects

### Git Submodules Approach

We use Git submodules rather than a traditional monorepo tool because:

- **Independent Development**: Each project can be developed separately
- **Selective Cloning**: Contributors can work on specific submodules
- **Independent Versioning**: Each submodule maintains its own release cycle
- **Flexible Ownership**: Different teams can own different submodules

## Working with Submodules

### Initial Setup

Clone with all submodules:

```bash
git clone --recurse-submodules https://github.com/bamr87/bamr87.git
cd bamr87
```

Or initialize submodules after cloning:

```bash
git clone https://github.com/bamr87/bamr87.git
cd bamr87
git submodule update --init --recursive
```

### Updating Submodules

Update all submodules to latest:

```bash
git submodule update --remote --merge
git add .
git commit -m "chore: update submodules"
git push
```

Update a specific submodule:

```bash
cd cv
git pull origin main
cd ..
git add cv
git commit -m "chore: update cv submodule"
git push
```

### Making Changes in Submodules

1. **Navigate to the submodule**:
   ```bash
   cd cv
   ```

2. **Create a branch and make changes**:
   ```bash
   git checkout -b feature/new-feature
   # Make your changes
   git add .
   git commit -m "feat: add new feature"
   ```

3. **Push to the submodule repository**:
   ```bash
   git push origin feature/new-feature
   ```

4. **Update parent repository**:
   ```bash
   cd ..
   git add cv
   git commit -m "chore: update cv submodule with new feature"
   git push
   ```

## Submodule Details

### cv/ - CV Builder

- **Repository**: https://github.com/bamr87/cv-builder-pro
- **Branch**: main
- **Purpose**: AI-powered CV/resume builder with LaTeX templates
- **Tech Stack**: React, TypeScript, Vite, Tailwind CSS
- **Setup**: `cd cv && npm install && npm run dev`

### README/ - Documentation Hub

- **Repository**: https://github.com/bamr87/README
- **Branch**: main
- **Purpose**: Aggregated documentation from multiple repositories
- **Tech Stack**: Python, MkDocs, Wiki.js
- **Setup**: `cd README && pip install -r requirements.txt`

### scripts/ - Automation Scripts

- **Repository**: https://github.com/bamr87/scripts
- **Branch**: master
- **Purpose**: Project initialization, GitHub utilities, deployment scripts
- **Tech Stack**: Bash, Python, Shell scripts
- **Setup**: Scripts are standalone executables

## Automated Workflows

### Submodule Updates

The `.github/workflows/update-submodules.yml` workflow:
- Runs weekly on Sundays at midnight
- Can be manually triggered via GitHub Actions UI
- Creates a pull request when updates are available
- Allows selective submodule updates

### Documentation Deployment

The `.github/workflows/build-docs.yml` workflow:
- Triggers on changes to `README/docs/**` or `mkdocs.yml`
- Builds MkDocs documentation
- Deploys to GitHub Pages automatically

## Contributing to the Monorepo

### For Root Repository Changes

Changes to root-level files (README.md, .gitignore, workflows):

1. Fork the main repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

### For Submodule Changes

Changes to cv/, README/, or scripts/:

1. Fork the **submodule repository**
2. Make changes in the submodule repo
3. Submit PR to the submodule repo
4. After merge, update the parent repo's submodule pointer

See [CONTRIBUTING.md](../CONTRIBUTING.md) for detailed guidelines.

## Troubleshooting

### Submodule Not Initialized

```bash
git submodule update --init --recursive
```

### Submodule Detached HEAD

```bash
cd <submodule>
git checkout main  # or master
cd ..
```

### Submodule Merge Conflicts

```bash
# In the submodule
cd <submodule>
git fetch origin
git merge origin/main
# Resolve conflicts
git add .
git commit
cd ..
git add <submodule>
git commit -m "fix: resolve submodule conflicts"
```

### Reset Submodule to Parent's Version

```bash
git submodule update --init --force
```

## Best Practices

1. **Always commit submodule changes first**, then update the parent
2. **Use descriptive commit messages** that mention which submodule changed
3. **Test locally** before pushing submodule updates
4. **Review submodule diffs** carefully in pull requests
5. **Keep submodules on stable branches** (main/master)
6. **Document cross-submodule dependencies** in this file

## Resources

- [Git Submodules Documentation](https://git-scm.com/book/en/v2/Git-Tools-Submodules)
- [SUBMODULES.md](../SUBMODULES.md) - Quick reference guide
- [DEVELOPMENT.md](DEVELOPMENT.md) - Development environment setup
- [GitHub: Working with submodules](https://github.blog/2016-02-01-working-with-submodules/)

## Questions?

For questions about the monorepo structure:
- Open an issue in the main repository
- Review existing issues and discussions
- Check the [CONTRIBUTING.md](../CONTRIBUTING.md) guide
