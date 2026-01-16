# Development Setup Guide

This guide will help you set up your local development environment for working with the bamr87 monorepo.

## Prerequisites

### Required Tools

- **Git**: Version 2.13+ (for submodule support)
  ```bash
  git --version
  ```

- **GitHub CLI** (recommended): For repository management
  ```bash
  gh --version
  ```

### Project-Specific Requirements

Depending on which submodule you're working with:

#### For cv/ (CV Builder)
- **Node.js**: 18.x or higher
- **npm**: 9.x or higher

```bash
node --version
npm --version
```

#### For README/ (Documentation)
- **Python**: 3.8 or higher
- **pip**: Latest version

```bash
python3 --version
pip3 --version
```

#### For scripts/ (Automation)
- **Bash**: 4.0+ (macOS users may need to upgrade)
- **zsh**: 5.x+ (standard on macOS)

```bash
bash --version
zsh --version
```

## Initial Setup

### 1. Clone the Repository

Clone with all submodules:

```bash
git clone --recurse-submodules https://github.com/bamr87/bamr87.git
cd bamr87
```

Or clone then initialize submodules:

```bash
git clone https://github.com/bamr87/bamr87.git
cd bamr87
git submodule update --init --recursive
```

### 2. Verify Submodules

Check that all submodules are properly initialized:

```bash
git submodule status
```

You should see:
```
 366375a6e5ac66ab484157b222054ad6c233a0c1 README (heads/main)
 b93ddfa12750f79fe4a207a92c5307f1b6088731 cv (heads/main)
 fecf16b07f6f8a75a8ab52783b6ef7cc062e018c scripts (heads/master)
```

### 3. Install Dependencies

#### Quick Setup (All Projects)

Use the provided setup script:

```bash
./tools/setup-dev.sh
```

#### Manual Setup

**CV Builder:**
```bash
cd cv
npm install
cd ..
```

**Documentation System:**
```bash
cd README
pip3 install -r requirements.txt
cd ..
```

**MkDocs (Root):**
```bash
pip3 install -r requirements-docs.txt
```

**Scripts:**
```bash
cd scripts
# Scripts are standalone, but check individual script requirements
chmod +x *.sh
cd ..
```

## Running Projects Locally

### CV Builder

```bash
cd cv
npm run dev
```

Access at: http://localhost:5173

### Documentation Site

Build and serve MkDocs documentation:

```bash
mkdocs serve
```

Access at: http://localhost:8000

### Wiki.js (Optional)

If using the Wiki.js documentation system:

```bash
cd README
docker-compose up -d
```

Access at: http://localhost:3000

## Development Workflow

### Standard Workflow

1. **Create a branch**:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make changes** in the root or submodules

3. **Test your changes**:
   ```bash
   # For CV Builder
   cd cv && npm run build && npm run preview
   
   # For Documentation
   mkdocs build --strict
   
   # For Scripts
   shellcheck scripts/*.sh
   ```

4. **Commit changes**:
   ```bash
   git add .
   git commit -m "feat: your descriptive message"
   ```

5. **Push and create PR**:
   ```bash
   git push origin feature/your-feature-name
   ```

### Working with Submodules

#### Making Changes in a Submodule

1. **Navigate to submodule**:
   ```bash
   cd cv  # or README, or scripts
   ```

2. **Create branch in submodule**:
   ```bash
   git checkout -b feature/new-feature
   ```

3. **Make and commit changes**:
   ```bash
   git add .
   git commit -m "feat: add new feature"
   ```

4. **Push to submodule repo**:
   ```bash
   git push origin feature/new-feature
   ```

5. **Return to parent and update pointer**:
   ```bash
   cd ..
   git add cv
   git commit -m "chore: update cv submodule"
   git push
   ```

## Code Quality Tools

### Linting

**JavaScript/TypeScript (CV Builder):**
```bash
cd cv
npm run lint
```

**Python (Documentation):**
```bash
cd README
pylint scripts/*.py
```

**Shell Scripts:**
```bash
shellcheck scripts/*.sh
```

### Formatting

**Prettier (Markdown, JSON):**
```bash
npx prettier --write "**/*.{md,json}"
```

**Black (Python):**
```bash
black README/scripts/
```

### Pre-commit Hooks

Install pre-commit hooks:

```bash
pip install pre-commit
pre-commit install
```

Run manually:
```bash
pre-commit run --all-files
```

## Testing

### CV Builder Tests

```bash
cd cv
npm run test
```

### Documentation Tests

```bash
cd README
pytest tests/
```

### Integration Tests

Run all tests:
```bash
./tools/run-all-tests.sh
```

## Environment Variables

### CV Builder (.env.local)

Create `cv/.env.local`:

```bash
VITE_FIREBASE_API_KEY=your-api-key
VITE_FIREBASE_AUTH_DOMAIN=your-domain
VITE_FIREBASE_PROJECT_ID=your-project-id
VITE_FIREBASE_STORAGE_BUCKET=your-bucket
VITE_FIREBASE_MESSAGING_SENDER_ID=your-sender-id
VITE_FIREBASE_APP_ID=your-app-id
```

### Documentation System (.env)

Create `README/.env`:

```bash
XAI_API_KEY=your-xai-key
OPENAI_API_KEY=your-openai-key
```

## Troubleshooting

### Submodule Issues

**Problem**: Submodule not initialized
```bash
git submodule update --init --recursive
```

**Problem**: Submodule detached HEAD
```bash
cd <submodule>
git checkout main
cd ..
```

**Problem**: Submodule changes not showing
```bash
git submodule foreach git pull origin main
```

### Build Issues

**Problem**: Node modules not found
```bash
cd cv
rm -rf node_modules package-lock.json
npm install
```

**Problem**: Python dependencies conflicts
```bash
cd README
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Problem**: MkDocs build fails
```bash
pip install --upgrade -r requirements-docs.txt
mkdocs build --clean
```

### Permission Issues

**Problem**: Scripts not executable
```bash
chmod +x scripts/*.sh
chmod +x tools/*.sh
```

## IDE Setup

### VS Code

Recommended extensions:
- ESLint
- Prettier
- Python
- GitLens
- Markdown All in One
- YAML

Workspace settings are in `.vscode/settings.json`.

### IntelliJ IDEA / WebStorm

- Enable ESLint for cv/
- Enable Python plugin for README/
- Configure Prettier for code formatting

## Performance Tips

### Faster Clones

Use shallow clones for testing:
```bash
git clone --depth 1 --recurse-submodules --shallow-submodules https://github.com/bamr87/bamr87.git
```

### Parallel Submodule Operations

```bash
git submodule foreach --recursive git pull origin main
```

### Incremental Builds

For CV Builder:
```bash
npm run dev  # Uses Vite's fast HMR
```

For Documentation:
```bash
mkdocs serve --dirtyreload  # Only rebuilds changed files
```

## Getting Help

### Documentation

- [MONOREPO.md](MONOREPO.md) - Repository organization
- [ARCHITECTURE.md](ARCHITECTURE.md) - System design
- [CONTRIBUTING.md](../CONTRIBUTING.md) - Contribution guidelines

### Support Channels

- **Issues**: https://github.com/bamr87/bamr87/issues
- **Discussions**: https://github.com/bamr87/bamr87/discussions
- **Email**: amr.abdel@gmail.com

### Common Commands Reference

```bash
# Update all submodules
git submodule update --remote --merge

# Check submodule status
git submodule status

# Reset submodule to parent's version
git submodule update --init --force

# Build documentation
mkdocs build

# Run CV builder
cd cv && npm run dev

# Run all tests
./tools/run-all-tests.sh

# Format all code
npx prettier --write "**/*.{md,json,yml,yaml}"
```

## Next Steps

1. Review the [CONTRIBUTING.md](../CONTRIBUTING.md) guide
2. Check open issues for good first contributions
3. Join discussions to connect with other contributors
4. Read submodule-specific documentation in each folder

Happy coding! 🚀
