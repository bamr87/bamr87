# ⚠️ DEPRECATED: build-n-cache-image

This action has been **deprecated** and replaced with the enhanced [`deployment/build-push-image`](../build-push-image/README.md) action.

## Migration Required

**Old (deprecated):**
```yaml
- uses: ./.github/actions/build-n-cache-image
  with:
    image-name: 'myapp'
    registry-url: '123456789.dkr.ecr.us-east-1.amazonaws.com'
    push-image: 'true'
    aws-access-key: ${{ secrets.AWS_ACCESS_KEY_ID }}
    aws-access-secret: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
```

**New (recommended):**
```yaml
- uses: ./.github/actions/deployment/build-push-image
  with:
    image-name: 'myapp'
    registry-type: 'ecr'
    aws-region: 'us-east-1'
    aws-access-key: ${{ secrets.AWS_ACCESS_KEY_ID }}
    aws-secret-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
    push-image: 'true'
```

## Why Deprecated?

The new action provides:

- **More Registries**: Support for GHCR, GCR, ACR, in addition to ECR and DockerHub
- **Better Caching**: Multiple cache strategies (GHA, registry, local)
- **Enhanced Security**: SBOM and provenance attestation support
- **Improved Tagging**: Automatic tag generation and management
- **Better Defaults**: OCI-compliant labels automatically added
- **Cleaner Interface**: More intuitive input naming

## Migration Guide

### ECR Migration

**Before:**
```yaml
registry-url: '123456789.dkr.ecr.us-east-1.amazonaws.com'
aws-access-key: ${{ secrets.AWS_ACCESS_KEY_ID }}
aws-access-secret: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
```

**After:**
```yaml
registry-type: 'ecr'
aws-region: 'us-east-1'
aws-access-key: ${{ secrets.AWS_ACCESS_KEY_ID }}
aws-secret-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
```

### DockerHub Migration

**Before:**
```yaml
dockerhub-username: ${{ secrets.DOCKERHUB_USERNAME }}
dockerhub-password: ${{ secrets.DOCKERHUB_TOKEN }}
```

**After:**
```yaml
registry-type: 'dockerhub'
dockerhub-username: ${{ secrets.DOCKERHUB_USERNAME }}
dockerhub-token: ${{ secrets.DOCKERHUB_TOKEN }}
```

### Depot.dev Users

The new action uses standard `docker/build-push-action` instead of `depot/build-push-action`. If you need Depot:

1. Keep using this action, or
2. Fork and customize `build-push-image` to use Depot

## Full Migration Example

**Before:**
```yaml
- uses: ./.github/actions/build-n-cache-image
  with:
    image-name: 'posthog'
    image-tag: ${{ github.sha }}
    registry-url: 'us-east1-docker.pkg.dev/posthog-301601/posthog'
    pr-number: ${{ github.event.pull_request.number }}
    actions-id-token-request-url: ${{ env.ACTIONS_ID_TOKEN_REQUEST_URL }}
    save: 'true'
    push-image: 'true'
    aws-access-key: ${{ secrets.AWS_ACCESS_KEY_ID }}
    aws-access-secret: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
    no-cache: 'false'
```

**After:**
```yaml
- uses: ./.github/actions/deployment/build-push-image
  with:
    image-name: 'posthog'
    image-tag: ${{ github.sha }}
    registry-type: 'custom'
    registry-url: 'us-east1-docker.pkg.dev/posthog-301601/posthog'
    pr-number: ${{ github.event.pull_request.number }}
    push-image: 'true'
    cache-enabled: 'true'
    cache-type: 'gha'
```

## Timeline

- **November 9, 2025**: Deprecated
- **Future**: Will be removed after all workflows are migrated

## Questions?

See the [build-push-image README](../build-push-image/README.md) or the [main actions README](../../README.md).
