# ⚠️ DEPRECATED: run-backend-tests

This action has been **deprecated** and replaced with the more general [`ci/run-tests`](../ci/run-tests/README.md) action.

## Migration Required

**Old (deprecated):**
```yaml
- uses: ./.github/actions/run-backend-tests
  with:
    python-version: '3.11.9'
    clickhouse-server-image: 'clickhouse/clickhouse-server:latest'
    segment: 'Core'
```

**New (recommended):**
```yaml
- uses: ./.github/actions/ci/run-tests
  with:
    language: 'python'
    language-version: '3.11.9'
    test-command: 'pytest'
    test-directory: 'posthog/ ee/'
    services-enabled: 'true'
    services-compose-file: 'docker-compose.dev.yml'
```

## Why Deprecated?

This action was tightly coupled to PostHog's specific Django setup with ClickHouse, Kafka, and Temporal. The new `ci/run-tests` action is:

- **Framework-agnostic**: Works with any Python project, not just Django
- **Multi-language**: Supports Python, Node.js, Ruby, Go, Rust
- **Simpler**: Less opinionated about services and configuration
- **Reusable**: Can be used across different repositories

## Migration Guide

See the [Refactoring Summary](../REFACTORING_SUMMARY.md#from-run-backend-tests) for detailed migration instructions.

For PostHog-specific needs, you can:
1. Use `ci/run-tests` with appropriate service configuration
2. Keep this action temporarily while migrating
3. Create a PostHog-specific composite action that uses `ci/run-tests` internally

## Timeline

- **November 9, 2025**: Deprecated
- **Future**: Will be removed after all workflows are migrated

## Questions?

See the [main actions README](../README.md) or open an issue.
