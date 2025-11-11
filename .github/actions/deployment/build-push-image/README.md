# Build and Push Container Image Action

A comprehensive container image builder supporting multiple registries, platforms, and build configurations.

## Features

- 🌐 **Multi-Registry Support**: ECR, GHCR, DockerHub, GCR, ACR, and custom registries
- 🏗️ **Multi-Platform Builds**: Build for multiple architectures simultaneously
- 💾 **Smart Caching**: GitHub Actions cache, registry cache, or local cache
- 🔐 **Security**: SBOM and provenance attestation support
- 🏷️ **Auto-Tagging**: Automatic tag generation based on branch/PR/commit
- 📦 **Build Arguments & Secrets**: Support for build-time configuration

## Usage

### Basic DockerHub Example

```yaml
- uses: ./.github/actions/deployment/build-push-image
  with:
    image-name: 'myapp'
    dockerhub-username: ${{ secrets.DOCKERHUB_USERNAME }}
    dockerhub-token: ${{ secrets.DOCKERHUB_TOKEN }}
    push-image: 'true'
```

### GitHub Container Registry (GHCR)

```yaml
- uses: ./.github/actions/deployment/build-push-image
  with:
    image-name: 'myapp'
    registry-type: 'ghcr'
    ghcr-token: ${{ secrets.GITHUB_TOKEN }}
    push-image: 'true'
```

### Amazon ECR

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

### Google Container Registry (GCR)

```yaml
- uses: ./.github/actions/deployment/build-push-image
  with:
    image-name: 'myapp'
    registry-type: 'gcr'
    gcp-project-id: 'my-project'
    gcp-service-account-key: ${{ secrets.GCP_SA_KEY }}
    push-image: 'true'
```

### Azure Container Registry (ACR)

```yaml
- uses: ./.github/actions/deployment/build-push-image
  with:
    image-name: 'myapp'
    registry-type: 'acr'
    registry-url: 'myregistry.azurecr.io'
    azure-client-id: ${{ secrets.AZURE_CLIENT_ID }}
    azure-client-secret: ${{ secrets.AZURE_CLIENT_SECRET }}
    azure-tenant-id: ${{ secrets.AZURE_TENANT_ID }}
    push-image: 'true'
```

### Multi-Platform Build

```yaml
- uses: ./.github/actions/deployment/build-push-image
  with:
    image-name: 'myapp'
    platforms: 'linux/amd64,linux/arm64,linux/arm/v7'
    dockerhub-username: ${{ secrets.DOCKERHUB_USERNAME }}
    dockerhub-token: ${{ secrets.DOCKERHUB_TOKEN }}
    push-image: 'true'
```

### With Build Arguments

```yaml
- uses: ./.github/actions/deployment/build-push-image
  with:
    image-name: 'myapp'
    build-args: |
      NODE_ENV=production
      API_URL=https://api.example.com
      VERSION=${{ github.ref_name }}
    push-image: 'true'
```

### With Custom Tags

```yaml
- uses: ./.github/actions/deployment/build-push-image
  with:
    image-name: 'myapp'
    image-tag: ${{ github.sha }}
    additional-tags: 'latest,v1.0.0,stable'
    pr-number: ${{ github.event.pull_request.number }}
    push-image: 'true'
```

### With SBOM and Provenance

```yaml
- uses: ./.github/actions/deployment/build-push-image
  with:
    image-name: 'myapp'
    sbom: 'true'
    provenance: 'true'
    push-image: 'true'
```

### Local Build Only

```yaml
- uses: ./.github/actions/deployment/build-push-image
  with:
    image-name: 'myapp'
    load-image: 'true'
    push-image: 'false'
```

### Multi-Stage Build

```yaml
- uses: ./.github/actions/deployment/build-push-image
  with:
    image-name: 'myapp'
    target: 'production'
    dockerfile: 'Dockerfile.prod'
    push-image: 'true'
```

## Inputs

### Image Configuration
| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `image-name` | Container image name | Yes | - |
| `image-tag` | Primary image tag | No | `${{ github.sha }}` |
| `additional-tags` | Comma-separated additional tags | No | - |

### Registry Configuration
| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `registry-type` | Registry type (ecr/ghcr/dockerhub/gcr/acr/custom) | No | `dockerhub` |
| `registry-url` | Custom registry URL | No | - |

### Registry Credentials

**AWS ECR:**
- `aws-region` - AWS region (default: us-east-1)
- `aws-access-key` - AWS access key ID
- `aws-secret-key` - AWS secret access key

**DockerHub:**
- `dockerhub-username` - DockerHub username
- `dockerhub-token` - DockerHub token/password

**GHCR:**
- `ghcr-token` - GitHub token (default: `${{ github.token }}`)

**GCR:**
- `gcp-project-id` - GCP project ID
- `gcp-service-account-key` - Service account JSON key

**ACR:**
- `azure-client-id` - Azure client ID
- `azure-client-secret` - Azure client secret
- `azure-tenant-id` - Azure tenant ID

### Build Configuration
| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `context` | Build context path | No | `.` |
| `dockerfile` | Dockerfile path | No | `Dockerfile` |
| `platforms` | Target platforms | No | `linux/amd64` |
| `build-args` | Build arguments | No | - |
| `target` | Build target stage | No | - |

### Cache Configuration
| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `cache-enabled` | Enable caching | No | `true` |
| `cache-type` | Cache backend (gha/registry/local) | No | `gha` |
| `no-cache` | Disable all caching | No | `false` |

### Push Configuration
| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `push-image` | Push to registry | No | `false` |
| `load-image` | Load to Docker daemon | No | `false` |

### Advanced Options
| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `sbom` | Generate SBOM | No | `false` |
| `provenance` | Generate provenance | No | `false` |
| `secrets` | Build secrets | No | - |
| `labels` | Image labels | No | - |
| `pr-number` | PR number for tagging | No | - |

## Outputs

| Output | Description |
|--------|-------------|
| `image-name` | Full image name with registry |
| `tags` | All applied tags |
| `digest` | Image digest (SHA256) |
| `metadata` | Build metadata |

## Registry Types

### ECR (Amazon Elastic Container Registry)
- Automatic authentication with AWS credentials
- Regional registry URLs
- Requires `aws-access-key` and `aws-secret-key`

### GHCR (GitHub Container Registry)
- Uses GitHub token for authentication
- Images at `ghcr.io/<owner>/<image>`
- Integrated with GitHub packages

### DockerHub
- Classic Docker registry
- Requires username and token
- Images at `<username>/<image>`

### GCR (Google Container Registry)
- Requires GCP service account
- Images at `gcr.io/<project>/<image>`
- JSON key authentication

### ACR (Azure Container Registry)
- Requires Azure service principal
- Custom registry URL
- Client ID/secret authentication

### Custom
- Any Docker-compatible registry
- Provide registry URL
- Username/password authentication

## Automatic Tagging

The action automatically generates tags:
- **Primary tag**: `image-tag` input (default: commit SHA)
- **Latest**: Added on main/master branch pushes
- **PR tag**: `pr-<number>` if `pr-number` provided
- **Additional**: Any tags in `additional-tags` input

Example for commit `abc123` on PR #42:
```
myimage:abc123
myimage:pr-42
myimage:latest  # if on main branch
```

## Caching Strategies

### GitHub Actions Cache (gha)
- **Best for**: Most use cases
- **Pros**: Fast, automatic, free
- **Cons**: 10GB limit per repository

### Registry Cache
- **Best for**: Large images, shared across repos
- **Pros**: Unlimited size, shareable
- **Cons**: Slower than GHA cache

### Local Cache
- **Best for**: Self-hosted runners
- **Pros**: Persistent across builds
- **Cons**: Requires storage management

## Build Arguments

Default build args automatically included:
- `COMMIT_HASH` - Current commit SHA
- `BUILD_DATE` - ISO 8601 timestamp
- `VERSION` - Image tag value

Add custom build args:
```yaml
build-args: |
  NODE_ENV=production
  API_URL=${{ secrets.API_URL }}
  FEATURE_FLAG=true
```

## Labels

OCI labels automatically added:
- `org.opencontainers.image.source` - Repository URL
- `org.opencontainers.image.revision` - Commit SHA
- `org.opencontainers.image.created` - Build timestamp

Add custom labels:
```yaml
labels: |
  com.example.team=backend
  com.example.version=${{ github.ref_name }}
```

## Complete CI/CD Example

```yaml
name: Build and Deploy
on:
  push:
    branches: [main]
  pull_request:

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Build and push
        uses: ./.github/actions/deployment/build-push-image
        with:
          image-name: 'myapp'
          registry-type: 'ghcr'
          platforms: 'linux/amd64,linux/arm64'
          build-args: |
            NODE_ENV=production
            VERSION=${{ github.ref_name }}
          cache-enabled: 'true'
          sbom: 'true'
          provenance: 'true'
          push-image: ${{ github.event_name != 'pull_request' }}
          pr-number: ${{ github.event.pull_request.number }}
          ghcr-token: ${{ secrets.GITHUB_TOKEN }}
      
      - name: Image digest
        run: echo "Built image digest ${{ steps.build.outputs.digest }}"
```

## Migration from build-n-cache-image

The action has been refactored for better generalization:

**Old:**
```yaml
- uses: ./.github/actions/build-n-cache-image
  with:
    image-name: 'myapp'
    registry-url: '123456789.dkr.ecr.us-east-1.amazonaws.com'
```

**New:**
```yaml
- uses: ./.github/actions/deployment/build-push-image
  with:
    image-name: 'myapp'
    registry-type: 'ecr'
    aws-region: 'us-east-1'
```

## Troubleshooting

### Authentication failures
- Verify credentials are correct and not expired
- Check token/key has necessary permissions
- Ensure registry URL is correct format

### Multi-platform builds fail
- Requires QEMU (automatically installed)
- Some base images don't support all platforms
- Check Dockerfile compatibility

### Cache not working
- Verify `cache-enabled` is `true`
- Check cache backend is appropriate
- GHA cache has 10GB limit

### Image too large
- Use multi-stage builds
- Minimize layers
- Use `.dockerignore`

## Security Best Practices

1. **Use secrets** for all credentials
2. **Enable SBOM** and provenance for supply chain security
3. **Scan images** with vulnerability scanners
4. **Use specific base** image versions
5. **Minimize attack surface** in final image

## Contributing

When adding new registry types:
1. Add registry-specific inputs
2. Implement login step
3. Add registry URL handling in metadata step
4. Update documentation
5. Add usage example
