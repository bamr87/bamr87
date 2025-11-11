# Setup Ruby Action

Sets up Ruby environment with bundler caching and system dependencies for GitHub Actions workflows.

## Features

- 💎 **Ruby Installation**: Installs specified Ruby version
- 📦 **Bundler Caching**: Automatic gem dependency caching
- 🔧 **System Dependencies**: Optional installation of common tools
- 🚀 **Performance**: Faster builds with intelligent caching
- 📝 **Script Permissions**: Automatically makes scripts executable

## Usage

### Basic Usage

```yaml
- uses: ./.github/actions/setup/setup-ruby
```

### Specific Ruby Version

```yaml
- uses: ./.github/actions/setup/setup-ruby
  with:
    ruby-version: '3.3'
```

### Without System Dependencies

```yaml
- uses: ./.github/actions/setup/setup-ruby
  with:
    ruby-version: '3.2'
    install-system-deps: 'false'
```

## Inputs

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `ruby-version` | Ruby version to install | No | `3.2` |
| `install-system-deps` | Install system dependencies (jq) | No | `true` |

## What It Does

1. **Installs Ruby**: Uses `ruby/setup-ruby` with specified version
2. **Enables Bundler Cache**: Automatically caches gems for faster builds
3. **Installs System Tools**: Installs `jq` for JSON processing (optional)
4. **Installs Gems**: Runs `bundle install` with optimized settings
5. **Makes Scripts Executable**: Sets execute permissions on script files

## Supported Ruby Versions

- **3.3** (latest stable)
- **3.2** (default)
- **3.1**
- **3.0**
- **2.7**
- **jruby** (JRuby)
- **truffleruby** (TruffleRuby)

## Complete Examples

### Rails Application CI

```yaml
name: Rails CI

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    strategy:
      matrix:
        ruby-version: ['3.1', '3.2', '3.3']
    
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: postgres
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    
    steps:
      - uses: actions/checkout@v4
      
      - uses: ./.github/actions/setup/setup-ruby
        with:
          ruby-version: ${{ matrix.ruby-version }}
      
      - name: Setup database
        env:
          RAILS_ENV: test
          DATABASE_URL: postgres://postgres:postgres@localhost:5432/test
        run: |
          bundle exec rails db:create db:schema:load
      
      - name: Run tests
        run: bundle exec rspec
```

### Jekyll Site Build

```yaml
name: Build Jekyll Site

on:
  push:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v4
      
      - uses: ./.github/actions/setup/setup-ruby
        with:
          ruby-version: '3.2'
      
      - name: Build site
        run: bundle exec jekyll build
      
      - name: Deploy to GitHub Pages
        uses: peaceiris/actions-gh-pages@v3
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: ./_site
```

### Gem Release

```yaml
name: Release Gem

on:
  push:
    tags: ['v*']

jobs:
  release:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v4
      
      - uses: ./.github/actions/setup/setup-ruby
        with:
          ruby-version: '3.3'
      
      - name: Build gem
        run: gem build *.gemspec
      
      - name: Publish to RubyGems
        env:
          GEM_HOST_API_KEY: ${{ secrets.RUBYGEMS_API_KEY }}
        run: |
          mkdir -p ~/.gem
          echo ":rubygems_api_key: ${GEM_HOST_API_KEY}" > ~/.gem/credentials
          chmod 0600 ~/.gem/credentials
          gem push *.gem
```

### RSpec with Coverage

```yaml
name: Test with Coverage

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v4
      
      - uses: ./.github/actions/setup/setup-ruby
      
      - name: Run tests with SimpleCov
        run: |
          bundle exec rspec --format documentation
      
      - name: Upload coverage to Codecov
        uses: codecov/codecov-action@v4
        with:
          files: ./coverage/coverage.xml
```

### RuboCop Linting

```yaml
name: Lint

on: [push, pull_request]

jobs:
  rubocop:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v4
      
      - uses: ./.github/actions/setup/setup-ruby
      
      - name: Run RuboCop
        run: bundle exec rubocop --parallel
```

## Bundler Configuration

The action runs `bundle install` with these optimizations:

```bash
bundle install --jobs 4 --retry 3
```

- `--jobs 4`: Parallel installation for speed
- `--retry 3`: Automatic retry on network failures

## Caching

Bundler caching is enabled automatically by `ruby/setup-ruby`. This caches:
- Installed gems
- `vendor/bundle` directory (if used)
- Platform-specific native extensions

Cache key is based on:
- Ruby version
- `Gemfile.lock` content
- Operating system

## System Dependencies

When `install-system-deps: 'true'` (default), installs:
- **jq**: Command-line JSON processor

Add custom system dependencies before this action:

```yaml
- name: Install custom dependencies
  run: |
    sudo apt-get update
    sudo apt-get install -y libsqlite3-dev

- uses: ./.github/actions/setup/setup-ruby
```

## Script Permissions

The action automatically makes scripts executable in:
- `scripts/*.sh`
- `test/*.sh`

This prevents "permission denied" errors when running test or build scripts.

## Troubleshooting

### Bundler version mismatch
**Solution**: Update `Gemfile.lock` with the appropriate bundler version

### Native extension compilation fails
**Solution**: Install required system libraries before this action

```yaml
- name: Install build dependencies
  run: sudo apt-get install -y build-essential libpq-dev
```

### Cache not being used
**Solution**: Ensure `Gemfile.lock` is committed to repository

### jq installation fails
**Solution**: Set `install-system-deps: 'false'` and install manually if needed

## Best Practices

1. **Commit Gemfile.lock**: Essential for reproducible builds and caching
2. **Use matrix testing**: Test against multiple Ruby versions
3. **Pin bundler version**: Specify in Gemfile if needed
4. **Update dependencies regularly**: Use Dependabot or similar tools
5. **Run bundle update** in a separate workflow/branch

## Performance Tips

- **Bundler caching** reduces build time by ~30-60 seconds
- **Parallel gem installation** (`--jobs 4`) speeds up fresh installs
- **System dependency caching** further improves build times

## Platform Support

This action runs on:
- **ubuntu-latest** (recommended)
- **ubuntu-22.04**
- **ubuntu-20.04**
- **macos-latest**
- **windows-latest**

Note: System dependencies installation only works on Ubuntu.

## Related Actions

- [`ruby/setup-ruby`](https://github.com/ruby/setup-ruby) - Underlying Ruby setup
- [`actions/cache`](https://github.com/actions/cache) - Manual caching alternative

## Migration from setup-ruby v0

If migrating from older versions:

**Old:**
```yaml
- uses: actions/setup-ruby@v1
  with:
    ruby-version: 3.2
```

**New:**
```yaml
- uses: ./.github/actions/setup/setup-ruby
  with:
    ruby-version: '3.2'
```

The new action includes bundler caching and dependency installation automatically.
