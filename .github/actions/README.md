# Actions

Reusable composite actions live here. Actions should be framework-agnostic where practical, configured through inputs, and documented with local examples.

## Layout

| Path | Purpose |
| --- | --- |
| `setup/configure-git` | Configure Git identity and authentication for automation. |
| `setup/setup-ruby` | Set up Ruby and Bundler with optional system dependencies. |
| `ci/run-checks` | Run configurable setup, test, quality, and build scripts. |
| `ci/run-tests` | Run tests across Python, Node.js, Ruby, Go, and Rust projects. |
| `deployment/build-push-image` | Build and optionally push Docker images to supported registries. |
| `utilities/get-pr-labels` | Read labels from a pull request for downstream workflow logic. |
| `examples/` | Copyable workflow examples that show common action combinations. |

## Rules

- Keep each action focused on one responsibility.
- Pass project-specific values as inputs or environment variables.
- Do not hardcode registry hosts, organization names, local paths, or product-specific services.
- Include an `action.yml` and a README for every action directory.
- Keep deprecated or product-specific actions out of the active library.

## Usage

Reference local actions from workflows with:

```yaml
- uses: ./.github/actions/ci/run-tests
  with:
    language: python
    test-command: pytest
```

When copying these actions to another repository, review every input, secret, and example before enabling the workflow.
