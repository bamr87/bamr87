# GitHub Copilot Instructions

This file provides AI-assisted development guidelines for this repository. These instructions help AI tools like GitHub Copilot generate consistent, high-quality code.

## Core Development Principles

### Design for Failure (DFF)
- Implement comprehensive error handling with try-catch blocks
- Include meaningful error messages and logging
- Design fallback mechanisms and redundancy
- Consider edge cases and failure points
- Add monitoring capabilities where appropriate

### Don't Repeat Yourself (DRY)
- Extract reusable code into functions, modules, or utilities
- Use configuration files for repeated constants
- Create template patterns for similar structures
- Leverage inheritance, composition, and shared utilities

### Keep It Simple (KIS)
- Prefer clear, readable code over clever optimizations
- Use descriptive names for variables, functions, and classes
- Break complex functions into smaller, focused units
- Choose well-established patterns over custom solutions

### README-First, README-Last
**CRITICAL WORKFLOW RULE**: Before and after EVERY development task, interaction, or request:

#### 🔍 README-FIRST: Start with Documentation Review
Before beginning any work, **ALWAYS**:

1. **Locate the Relevant README.md**
   - Find the README.md in the current working directory
   - If none exists, check parent directories up to repository root
   - Identify all related README.md files that provide context

2. **Read and Understand Context**
   - Review the README.md to understand:
     - Purpose and scope of the directory/module
     - Existing features and capabilities
     - Current structure and organization
     - Dependencies and relationships
     - Known issues or limitations
     - Contribution guidelines

3. **Assess Documentation Gaps**
   - Identify what information is missing
   - Note what might be outdated
   - Recognize areas that need clarification
   - Detect broken links or references

#### ✅ README-LAST: Update Documentation After Changes
After completing any work, **ALWAYS**:

1. **Update the Relevant README.md**
   - Add new features, files, or capabilities
   - Update changed functionality or structure
   - Fix outdated information or broken links
   - Clarify confusing or incomplete sections
   - Update the `lastmod` date in frontmatter

2. **Document What Changed**
   - List new files or directories added
   - Explain new functionality or features
   - Update usage examples if behavior changed
   - Add troubleshooting info for issues encountered
   - Update dependency information

3. **Cross-Reference Related READMEs**
   - Update parent README if adding new subdirectories
   - Update child READMEs if parent context changed
   - Update sibling READMEs if relationships changed
   - Ensure bidirectional linking is maintained

4. **Verify Documentation Quality**
   - Check that all links work
   - Test code examples if provided
   - Ensure clarity and completeness
   - Maintain consistent style and formatting

#### 🔄 The README-First, README-Last Cycle

```
Request Received → 📋 README-FIRST
    ↓
Read relevant README.md → Understand context → Note gaps/issues
    ↓
Perform Work
    ↓
✅ README-LAST → Update README.md → Document changes
    ↓
Cross-reference related docs → Verify quality → Task Complete
```

#### 📝 Practical Examples

**Example 1: Adding a New File**
```markdown
Request: "Create a new utility script for data validation"

README-FIRST:
1. Check ./scripts/README.md
2. Note existing scripts and their purposes
3. Identify naming conventions
4. Review dependencies and patterns

Work: Create data_validator.py

README-LAST:
1. Update ./scripts/README.md:
   - Add data_validator.py to file listing
   - Document its purpose and usage
   - Show example command
   - Update lastmod date
2. If creating new category, update parent README
```

**Example 2: Fixing a Bug**
```markdown
Request: "Fix the broken link checker"

README-FIRST:
1. Read ./tools/README.md
2. Understand current functionality
3. Note existing issues or limitations
4. Review configuration options

Work: Fix link validation logic

README-LAST:
1. Update ./tools/README.md:
   - Note the bug fix in a changelog section
   - Update behavior description if changed
   - Add troubleshooting note if relevant
   - Update version number if applicable
2. Update root README if this was a critical fix
```

**Example 3: Creating New Feature**
```markdown
Request: "Add AI-powered code review feature"

README-FIRST:
1. Read root README.md and feature documentation
2. Understand existing features and structure
3. Note feature naming conventions
4. Review integration patterns

Work: Implement AI code review module

README-LAST:
1. Create ./features/ai-code-review/README.md with full documentation
2. Update ./features/README.md to list new feature
3. Update root README.md if this is a major capability
4. Add links between all related READMEs
```

#### 🎯 Why README-First, README-Last?

**Benefits**:
- 📚 **Continuous Documentation** - README always reflects current state
- 🧭 **Better Context** - Understanding before acting prevents mistakes
- 🔗 **Maintained Connections** - Cross-references stay current
- 📈 **Evolution Tracking** - Changes are documented as they happen
- 🤝 **Team Alignment** - Everyone sees the same updated information
- 🔍 **Reduced Confusion** - No orphaned or undocumented code
- ♻️ **Knowledge Preservation** - Learning and decisions are captured

**Prevents**:
- ❌ Duplicate functionality (you'd see it in README first)
- ❌ Broken documentation (updated immediately after changes)
- ❌ Lost context (README provides the "why" and "how")
- ❌ Orphaned files (README lists all files with purposes)
- ❌ Confusion for contributors (README always current)

#### ⚠️ Non-Negotiable Rules

1. **NEVER skip README review** before starting work
2. **NEVER complete a task** without updating README
3. **ALWAYS create README.md** if one doesn't exist in a directory
4. **ALWAYS update `lastmod`** date when changing README
5. **ALWAYS test links** after updating README
6. **ALWAYS maintain bidirectional links** between related READMEs

## Front Matter Standards

### Enhanced Front Matter for Educational and Project Content

Front matter serves as structured metadata that enables AI tools to understand context, learning objectives, and technical requirements. Use appropriate front matter templates based on content type.

#### Educational Content Front Matter

For tutorials, guides, and learning resources:

```yaml
---
title: "Clear, Action-Oriented Title"
description: "Complete description of what the content teaches (150-300 characters)"
date: YYYY-MM-DDTHH:MM:SS.000Z
author: "Author Name"
tags:
  - primary-technology
  - skill-level
  - learning-type
categories:
  - Main-Category
  - Skill-Category
learning_objectives:
  - "Specific skill or knowledge to be gained"
  - "Measurable learning outcome"
  - "Practical application ability"
target_audience:
  skill_level: "beginner | intermediate | advanced | expert"
  prerequisites:
    - "Required prior knowledge"
    - "Recommended background"
educational_context:
  category: "Technical Category"
  subcategory: "Specific Focus Area"
  estimated_time: "X-Y hours"
technical_requirements:
  - "Required software or tools"
  - "System requirements"
  - "Development environment"
assessment_criteria:
  - "Success measurement method"
  - "Skill demonstration requirement"
ai_teaching_notes:
  - "Focus areas for AI assistance"
  - "Common learning challenges"
  - "Recommended teaching approach"
version: "X.Y.Z"
lastmod: YYYY-MM-DDTHH:MM:SS.000Z
---
```

#### Project/Code Documentation Front Matter

For code files, projects, and technical documentation:

```yaml
---
file: filename.ext
description: "Brief description of file purpose and functionality"
author: "Name <email@domain.com>"
created: YYYY-MM-DD
lastModified: YYYY-MM-DD
version: X.Y.Z
dependencies:
  - package-name: "version or description"
  - another-package: "purpose in this project"
technical_stack:
  - "Primary technology or framework"
  - "Supporting libraries or tools"
container_requirements:
  baseImage: "image:tag"
  exposedPorts: [port_list]
  volumes: ["/path:permission"]
  environment:
    VARIABLE: "description"
usage: "Brief example of how to use this file/module"
notes: "Important considerations or limitations"
---
```

#### Instruction File Front Matter

For AI agent and development instructions:

```yaml
---
file: filename.instructions.md
description: "VS Code Copilot-optimized instructions for [purpose]"
author: "Team or Individual Name"
created: YYYY-MM-DD
lastModified: YYYY-MM-DD
version: X.Y.Z
applyTo: "file patterns where these instructions apply"
dependencies:
  - other-instructions.md: "How this relates to other instructions"
relatedEvolutions:
  - "Related improvements or changes"
containerRequirements:
  baseImage: "appropriate-image:tag"
  description: "Container environment purpose"
  exposedPorts: [port_list]
  portDescription: "What ports are used for"
  volumes: ["/path:permission"]
  environment:
    VARIABLE: "description"
  resources:
    cpu: "resource_range"
    memory: "memory_range"
  healthCheck: "health check method"
paths:
  workflow_name_path:
    - step_1
    - step_2
    - step_3
changelog:
  - date: "YYYY-MM-DD"
    description: "What changed"
    author: "Who made changes"
usage: "How to use these instructions"
notes: "Important considerations"
---
```

### Front Matter Best Practices

1. **Always Include Required Fields**
   - title/file, description, author, dates, version
   - Choose appropriate template for content type

2. **Be Specific in Descriptions**
   - Explain "what" and "why" clearly
   - Include measurable outcomes when applicable
   - Use action-oriented language

3. **Maintain Version History**
   - Follow semantic versioning (MAJOR.MINOR.PATCH)
   - Update lastmod/lastModified whenever content changes
   - Document significant changes in changelog

4. **Define Dependencies Clearly**
   - List all required packages, libraries, or files
   - Specify versions when critical
   - Explain the relationship or purpose

5. **Support AI Understanding**
   - Include ai_teaching_notes for educational content
   - Add applyTo patterns for instruction files
   - Specify technical_requirements clearly
   - Document assessment_criteria for learning content

## File Standards

### File Headers
Include standardized headers in all source files:

**Python:**
```python
"""
File: filename.py
Description: Brief one-sentence description
Author: Your Name <email@example.com>
Created: YYYY-MM-DD
Last Modified: YYYY-MM-DD
Version: X.Y.Z

Dependencies:
- package-name: description

Usage: Brief usage example
"""
```

**JavaScript/TypeScript:**
```javascript
/**
 * File: filename.js
 * Description: Brief one-sentence description
 * Author: Your Name <email@example.com>
 * Created: YYYY-MM-DD
 * Last Modified: YYYY-MM-DD
 * Version: X.Y.Z
 * 
 * Dependencies:
 * - package-name: description
 * 
 * Usage: Brief usage example
 */
```

**Bash:**
```bash
#!/bin/bash
# File: filename.sh
# Description: Brief one-sentence description
# Author: Your Name <email@example.com>
# Created: YYYY-MM-DD
# Last Modified: YYYY-MM-DD
# Version: X.Y.Z
#
# Dependencies:
# - command-name: description
#
# Usage: ./filename.sh [arguments]
```

### Documentation Requirements
- **README files**: Required in every major directory
- **Code comments**: Explain "why", not "what"
- **Docstrings/JSDoc**: For all public functions, classes, and modules
- **API documentation**: For all public endpoints and interfaces

## Language-Specific Guidelines

### Python
- Follow PEP 8 style guide
- Use type hints for all function signatures
- Write Google-style or NumPy-style docstrings
- Use snake_case for variables and functions
- Use PascalCase for classes
- Use `black` for formatting, `flake8` or `ruff` for linting

### JavaScript/TypeScript
- Use ESLint for linting, Prettier for formatting
- Prefer TypeScript over JavaScript for type safety
- Use camelCase for variables and functions
- Use PascalCase for classes and React components
- Use ES6+ features (arrow functions, destructuring, async/await)

### Bash/Shell
- Use ShellCheck for validation
- Include error handling: `set -euo pipefail`
- Add descriptive comments for complex operations
- Use functions for reusable code blocks
- Quote all variable expansions: `"${variable}"`

### Other Languages
- Follow community-standard style guides
- Use language-appropriate linters and formatters
- Maintain consistency with existing codebase patterns

## Testing Standards

### Test Coverage
- Write tests for all new features and bug fixes
- Include unit tests for individual functions/methods
- Add integration tests for component interactions
- Include end-to-end tests for critical user workflows
- Aim for 80%+ code coverage

### Test Structure
- Use descriptive test names that explain what's being tested
- Follow Arrange-Act-Assert or Given-When-Then patterns
- Include edge cases and error conditions
- Mock external dependencies appropriately

## Git Workflow

### Commit Messages
Follow Conventional Commits format:
```
type(scope): brief description (50 chars or less)

Detailed explanation if needed (wrap at 72 chars)

Fixes #issue-number
```

**Types:** `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `perf`, `ci`

### Branch Naming
- `feature/description` - New features
- `fix/description` - Bug fixes
- `docs/description` - Documentation updates
- `refactor/description` - Code refactoring
- `test/description` - Test additions or modifications

## AI-Assisted Development Best Practices

### Code Generation Guidelines
When generating code, always:
- Include comprehensive error handling
- Add clear, educational comments
- Write complete documentation and docstrings
- Provide usage examples
- Consider security implications
- Validate inputs and sanitize outputs

### Context-Aware Development
Always consider:
- **Project Architecture**: Existing patterns and structures
- **Code Style**: Follow established conventions
- **Tech Stack**: Use appropriate libraries and frameworks
- **Target Audience**: Write code appropriate for the team's skill level
- **Performance**: Consider efficiency for production code

### Quality Standards
- **Input Validation**: Validate all user inputs and external data
- **Error Handling**: Handle errors gracefully with meaningful messages
- **Logging**: Log important operations and errors
- **Security**: Never hardcode secrets; use environment variables
- **Maintainability**: Write code that's easy to understand and modify

## Security Guidelines

### Critical Security Practices
- **Never commit secrets**: No API keys, passwords, or tokens in code
- **Environment Variables**: Use `.env` files (git-ignored) for sensitive data
- **Input Validation**: Validate and sanitize all user inputs
- **Dependencies**: Keep dependencies updated; audit regularly
- **Authentication**: Use established libraries; don't roll your own
- **Encryption**: Use industry-standard encryption for sensitive data

### Code Review Checklist
- [ ] No hardcoded secrets or credentials
- [ ] All inputs validated and sanitized
- [ ] Error messages don't leak sensitive information
- [ ] Dependencies are up-to-date and from trusted sources
- [ ] Authentication and authorization properly implemented

## Container/Docker Best Practices

### Container-First Development Philosophy

All development should occur in containerized environments to ensure consistency across development, testing, and production.

#### Core Container Principles

1. **Never Install Dependencies on Host**
   - All development tools run in containers
   - Host machine only needs Docker/Podman
   - Ensures environment reproducibility

2. **Match Development to Production**
   - Development containers mirror production environment
   - Same base images, dependencies, and configurations
   - Reduces "works on my machine" issues

3. **Document All Container Requirements**
   - List all exposed ports and their purposes
   - Define required volumes and mount points
   - Specify environment variables and defaults
   - Include resource limits and health checks

### Docker Compose for Local Development

Use Docker Compose to define multi-service development environments:

```yaml
version: '3.8'

services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
      target: development
    ports:
      - "8000:8000"
    volumes:
      - ./src:/app/src:rw
      - ./static:/app/static:rw
    environment:
      - DEBUG=True
      - DATABASE_URL=postgresql://user:pass@db:5432/appdb
      - API_KEY=${API_KEY}
    depends_on:
      - db
      - redis
    command: python manage.py runserver 0.0.0.0:8000

  db:
    image: postgres:15-alpine
    environment:
      - POSTGRES_DB=appdb
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=pass
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

volumes:
  postgres_data:
  redis_data:
```

### Multi-Stage Dockerfiles

Use multi-stage builds to optimize image size and security:

```dockerfile
# Development stage - includes dev tools
FROM python:3.11-slim AS development
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt

# Development: source code mounted as volume
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

# Production stage - minimal, optimized
FROM python:3.11-slim AS production
WORKDIR /app

# Install only runtime dependencies
RUN apt-get update && apt-get install -y \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install production dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir gunicorn

# Copy application code
COPY src/ ./src/
COPY static/ ./static/

# Run as non-root user
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Run production server
EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--chdir", "src", "app.wsgi:application"]
```

### Container Security Best Practices

1. **Use Official Base Images**
   - Prefer official images from Docker Hub or trusted registries
   - Use specific version tags, never `latest`
   - Example: `python:3.11-slim`, `node:18-alpine`

2. **Run as Non-Root User**
   ```dockerfile
   # Create non-root user
   RUN useradd -m -u 1000 appuser
   USER appuser
   ```

3. **Minimize Image Size**
   - Use slim or alpine variants when possible
   - Remove package manager caches
   - Use multi-stage builds to exclude build tools
   - Combine RUN commands to reduce layers

4. **Secure Environment Variables**
   - Never hardcode secrets in Dockerfiles
   - Use Docker secrets or environment files
   - Add `.env` files to `.dockerignore`

5. **Use .dockerignore**
   ```
   # .dockerignore
   .git
   .env
   .venv
   __pycache__
   *.pyc
   *.pyo
   .DS_Store
   node_modules
   dist
   build
   ```

### Container Health Checks

Include health checks in all services:

```dockerfile
HEALTHCHECK --interval=30s --timeout=3s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1
```

```yaml
# docker-compose.yml
services:
  app:
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 3s
      retries: 3
      start_period: 40s
```

### Volume Management

1. **Named Volumes for Data Persistence**
   - Use named volumes for databases and persistent data
   - Never store persistent data in container filesystem

2. **Bind Mounts for Development**
   - Mount source code for hot reloading
   - Use read-write permissions appropriately
   - Example: `./src:/app/src:rw`

3. **Volume Permissions**
   - Ensure container user has appropriate permissions
   - Match UIDs between host and container when needed

### Container Networking

1. **Define Networks Explicitly**
   ```yaml
   networks:
     frontend:
     backend:
   
   services:
     web:
       networks:
         - frontend
     api:
       networks:
         - frontend
         - backend
     db:
       networks:
         - backend
   ```

2. **Use Service Names for DNS**
   - Services can communicate using service names
   - Example: `postgresql://user:pass@db:5432/appdb`

3. **Expose Only Necessary Ports**
   - Only publish ports that need external access
   - Internal services don't need published ports

### Development Workflow with Containers

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f app

# Run commands in container
docker-compose exec app python manage.py migrate
docker-compose exec app python manage.py createsuperuser

# Run tests in container
docker-compose exec app pytest

# Rebuild after dependency changes
docker-compose build app
docker-compose up -d app

# Stop all services
docker-compose down

# Stop and remove volumes (clean slate)
docker-compose down -v
```

### Container Documentation Requirements

Every containerized project MUST document:

```markdown
## Container Development Setup

### Prerequisites
- Docker Desktop 20.10+
- Docker Compose 2.0+

### Quick Start
```bash
# Clone repository
git clone <repo-url>
cd project-name

# Copy environment template
cp .env.example .env

# Start services
docker-compose up -d

# Run migrations
docker-compose exec app python manage.py migrate

# Access application
open http://localhost:8000
```

### Container Services
- **app**: Main application (port 8000)
- **db**: PostgreSQL database (port 5432)
- **redis**: Redis cache (port 6379)

### Common Commands
- Start: `docker-compose up -d`
- Stop: `docker-compose down`
- Logs: `docker-compose logs -f`
- Shell: `docker-compose exec app bash`
- Tests: `docker-compose exec app pytest`

### Troubleshooting
**Issue**: Permission errors with volumes
**Solution**: Ensure correct UID/GID in container matches host
```

## API Integration Best Practices

### Service Layer Pattern for API Integration

Create dedicated service classes for external API interactions:

```python
# services/api_service.py
import logging
from typing import Dict, Any, Optional
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

class BaseAPIService(ABC):
    """
    Abstract base class for API service integrations
    
    Provides common functionality for error handling, retry logic,
    and response processing that all API services should implement.
    """
    
    def __init__(self, api_key: str, base_url: str, timeout: int = 30):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.max_retries = 3
    
    @abstractmethod
    def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Subclasses must implement request logic"""
        pass
    
    def handle_error(self, error: Exception, context: str) -> None:
        """Centralized error handling with logging"""
        logger.error(f"{context}: {str(error)}")
        # Add monitoring/alerting logic here
        raise
```

### OpenAI API Integration Example

```python
# services/openai_service.py
import openai
import time
from typing import Optional
from django.conf import settings

class OpenAIService:
    """
    Service for OpenAI API interactions with error handling and retry logic
    
    Features:
    - Automatic retry with exponential backoff
    - Rate limit handling
    - Comprehensive error logging
    - Response caching support
    """
    
    def __init__(self):
        openai.api_key = settings.OPENAI_API_KEY
        self.model = settings.OPENAI_MODEL
        self.max_retries = 3
        self.timeout = 30
    
    def generate_content(
        self,
        prompt: str,
        system_message: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7
    ) -> str:
        """
        Generate content using OpenAI API
        
        Args:
            prompt: User prompt for content generation
            system_message: Optional system role message
            max_tokens: Maximum tokens in response
            temperature: Randomness in generation (0-2)
        
        Returns:
            Generated content as string
        
        Raises:
            openai.OpenAIError: If API call fails after retries
        """
        max_tokens = max_tokens or settings.OPENAI_MAX_TOKENS
        system_msg = system_message or "You are a helpful assistant."
        
        for attempt in range(self.max_retries):
            try:
                response = openai.ChatCompletion.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout=self.timeout
                )
                
                content = response.choices[0].message.content
                logger.info(f"Generated content successfully (attempt {attempt + 1})")
                
                # Log usage for monitoring
                usage = response.usage
                logger.info(f"Token usage - Prompt: {usage.prompt_tokens}, "
                          f"Completion: {usage.completion_tokens}, "
                          f"Total: {usage.total_tokens}")
                
                return content
                
            except openai.RateLimitError as e:
                logger.warning(f"Rate limit hit (attempt {attempt + 1}): {e}")
                if attempt < self.max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff
                    time.sleep(wait_time)
                else:
                    raise
                    
            except openai.APIError as e:
                logger.error(f"OpenAI API error (attempt {attempt + 1}): {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(1)
                else:
                    raise
            
            except openai.Timeout as e:
                logger.error(f"Request timeout (attempt {attempt + 1}): {e}")
                if attempt < self.max_retries - 1:
                    continue
                else:
                    raise
```

### Generic HTTP API Client

```python
# utils/api_client.py
import requests
import logging
from typing import Dict, Any, Optional
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

class APIClient:
    """
    Generic HTTP API client with retry logic and error handling
    
    Features:
    - Automatic retry with configurable strategy
    - Session management for connection pooling
    - Request/response logging
    - Timeout handling
    """
    
    def __init__(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3
    ):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.session = requests.Session()
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "PUT", "DELETE", "OPTIONS", "TRACE", "POST"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # Set default headers
        if api_key:
            self.session.headers.update({'Authorization': f'Bearer {api_key}'})
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'YourApp/1.0'
        })
    
    def get(self, endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Make GET request with error handling
        
        Args:
            endpoint: API endpoint path
            params: Query parameters
        
        Returns:
            JSON response as dictionary
        
        Raises:
            requests.exceptions.RequestException: On request failure
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        try:
            logger.debug(f"GET request to {url} with params: {params}")
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            logger.debug(f"Response received from {url}")
            return data
            
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error for GET {url}: {e}")
            logger.error(f"Response: {e.response.text if e.response else 'No response'}")
            raise
            
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error for GET {url}: {e}")
            raise
            
        except requests.exceptions.Timeout as e:
            logger.error(f"Timeout for GET {url}: {e}")
            raise
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed for GET {url}: {e}")
            raise
    
    def post(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Make POST request with error handling
        
        Args:
            endpoint: API endpoint path
            data: Request body data
        
        Returns:
            JSON response as dictionary
        
        Raises:
            requests.exceptions.RequestException: On request failure
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        try:
            logger.debug(f"POST request to {url}")
            response = self.session.post(url, json=data, timeout=self.timeout)
            response.raise_for_status()
            
            result = response.json()
            logger.debug(f"Response received from {url}")
            return result
            
        except requests.exceptions.RequestException as e:
            logger.error(f"POST request failed: {url}, Error: {e}")
            raise
    
    def close(self):
        """Close session and cleanup resources"""
        self.session.close()
```

### API Configuration Management

```python
# settings.py or config.py
import os
from django.core.exceptions import ImproperlyConfigured

# OpenAI Configuration
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
if not OPENAI_API_KEY:
    raise ImproperlyConfigured('OPENAI_API_KEY environment variable is required')

OPENAI_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4')
OPENAI_MAX_TOKENS = int(os.environ.get('OPENAI_MAX_TOKENS', '1000'))
OPENAI_TEMPERATURE = float(os.environ.get('OPENAI_TEMPERATURE', '0.7'))

# Generic API Configuration Template
API_CONFIGS = {
    'external_service': {
        'base_url': os.environ.get('EXTERNAL_SERVICE_URL'),
        'api_key': os.environ.get('EXTERNAL_SERVICE_KEY'),
        'timeout': int(os.environ.get('EXTERNAL_SERVICE_TIMEOUT', '30')),
    }
}
```

### Error Handling Best Practices

```python
from django.http import JsonResponse
import logging

logger = logging.getLogger(__name__)

def api_view_with_error_handling(request):
    """Example view with comprehensive API error handling"""
    
    try:
        # Business logic with API call
        service = ExternalAPIService()
        data = service.fetch_data()
        
        return JsonResponse({
            'status': 'success',
            'data': data
        })
        
    except requests.exceptions.Timeout:
        logger.error("API request timeout")
        return JsonResponse(
            {'status': 'error', 'message': 'Service temporarily unavailable'},
            status=504
        )
        
    except requests.exceptions.HTTPError as e:
        logger.error(f"API HTTP error: {e}")
        status_code = e.response.status_code if e.response else 500
        return JsonResponse(
            {'status': 'error', 'message': 'External service error'},
            status=status_code
        )
        
    except openai.RateLimitError:
        logger.warning("OpenAI rate limit exceeded")
        return JsonResponse(
            {'status': 'error', 'message': 'Service rate limit exceeded, please try again later'},
            status=429
        )
        
    except openai.OpenAIError as e:
        logger.error(f"OpenAI API error: {e}")
        return JsonResponse(
            {'status': 'error', 'message': 'AI service temporarily unavailable'},
            status=502
        )
        
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        return JsonResponse(
            {'status': 'error', 'message': 'Internal server error'},
            status=500
        )
```

### API Testing Best Practices

```python
# tests/test_api_service.py
import pytest
from unittest.mock import patch, Mock
from services.openai_service import OpenAIService

class TestOpenAIService:
    """Test OpenAI service with mocked API calls"""
    
    @pytest.fixture
    def service(self):
        return OpenAIService()
    
    @patch('openai.ChatCompletion.create')
    def test_generate_content_success(self, mock_create, service):
        """Test successful content generation"""
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="Generated content"))]
        mock_response.usage = Mock(
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30
        )
        mock_create.return_value = mock_response
        
        result = service.generate_content("Test prompt")
        
        assert result == "Generated content"
        mock_create.assert_called_once()
    
    @patch('openai.ChatCompletion.create')
    def test_generate_content_retry_on_rate_limit(self, mock_create, service):
        """Test retry logic on rate limit"""
        import openai
        
        # First call raises rate limit, second succeeds
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="Success"))]
        mock_response.usage = Mock(prompt_tokens=10, completion_tokens=20, total_tokens=30)
        
        mock_create.side_effect = [
            openai.RateLimitError("Rate limited"),
            mock_response
        ]
        
        result = service.generate_content("Test prompt")
        
        assert result == "Success"
        assert mock_create.call_count == 2
```

## Book and Narrative Content Creation

### Book Chapter Structure Guidelines

When creating book chapters or narrative content, follow these AI-optimized patterns:

#### Chapter Front Matter Template

```yaml
---
title: "Chapter Title"
subtitle: "Short thematic phrase"
character: "Main character(s) featured"
setting: "Primary location(s)"
era: "Time period or year(s)"
tone: "Emotional tone (Satirical, Somber, Hopeful, etc.)"
style: "Narrative style (First-Person, Observational, etc.)"
---
```

#### Chapter Content Structure

```markdown
## Outline and Contextual Alignment

### Purpose of the Chapter
- Primary narrative goal
- Character development focus
- Thematic exploration

### Setting
- Physical environment description
- Social/cultural context
- Atmosphere and mood

### Main Character(s)
- Role in this chapter
- Background relevant to events
- Character traits displayed

### Plot Progression
1. Opening scene or situation
2. Rising action or conflict
3. Key turning point
4. Resolution or cliffhanger

### Themes Introduced
- Primary thematic element
- Symbolic or metaphorical content
- Connection to overall narrative

## Chapter Body

[Narrative text written in specified style and tone]

## References & Contextual Alignment

- Emotional connection with protagonist
- Legacy and world-building details
- Foreshadowing or callbacks
- Key themes and motifs reinforced
- Plot progression within story structure

## Links and References

- [Main Outline](../README.md)
- [Previous Chapter](../chapter-XX/content.md)
- [Next Chapter](../chapter-XX/content.md)
```

### AI Instructions for Book Content

**When generating book outlines:**
1. Create README.md with three-act structure
2. Define 4-6 major themes
3. Map character arc with 4-5 phases
4. Suggest 10-15 chapter titles

**When writing/updating chapters:**
1. Review outline and existing chapters for continuity
2. Maintain consistent tone, style, and character development
3. Align with overall narrative structure and themes
4. Suggest minor updates to related chapters for coherence

**Cross-referencing requirements:**
- Link to main README outline
- Connect to previous and next chapters
- Reference character backgrounds when introduced
- Note thematic connections to other chapters

## Specialized Content Creation Guidelines

### Jekyll Article Writing for Development Sessions

**Chronicle Every AI-Powered Development Session** by creating Jekyll articles that document the learning journey:

#### Article Naming Convention
Follow Jekyll standard: `YYYY-MM-DD-descriptive-title-with-hyphens.md`

Examples:
- `2025-11-09-implementing-api-integration-patterns.md`
- `2025-11-09-debugging-docker-compose-setup.md`
- `2025-11-09-exploring-ai-assisted-development.md`

#### Required Article Frontmatter

```yaml
---
title: "Descriptive Title: What Was Accomplished"
description: Brief description explaining the learning objective and outcome
date: YYYY-MM-DDTHH:MM:SS.000Z
preview: "Short preview text for social media and search"
tags:
    - ai-assisted-development
    - specific-technology
    - learning-journey
categories:
    - Development
    - Specific-Category
sub-title: Concise explanation of the specific focus
excerpt: One-sentence summary of key learning or achievement
snippet: Memorable quote or key insight from the session
author: Team Name
layout: journals
keywords:
    primary:
        - main topic keyword
    secondary:
        - supporting concepts
lastmod: YYYY-MM-DDTHH:MM:SS.000Z
permalink: /descriptive-url-slug/
comments: true
---
```

#### Article Structure Template

```markdown
## The Challenge: [What Problem Were We Solving?]

[Clear problem statement explaining what you were trying to accomplish, why it was important, and what obstacles you faced]

## AI-Assisted Development Process

[Document the collaboration between human and AI:
- Which AI tools/agents were used
- How prompts were crafted and refined
- What reasoning approaches were taken
- How AI suggestions were evaluated and implemented]

## Step-by-Step Implementation

[Provide detailed, reproducible steps:
- Code examples with syntax highlighting
- Configuration files and settings
- Command-line instructions
- Error messages and troubleshooting steps]

## Key Learnings and Insights

[Reflect on the development process:
- What worked well in the AI collaboration
- What required human intervention or correction
- Unexpected discoveries or solutions
- Best practices that emerged]

## Code Implementations

```language
# Include all relevant code with proper formatting
# Document expected outputs and error handling
```

## Challenges and Solutions

[Document any issues encountered:
- Error messages and their solutions
- Alternative approaches considered
- Performance considerations
- Security implications]

## Next Steps and Evolution

[Connect to the broader learning journey:
- How this builds on previous work
- What future developments this enables
- Additional areas for exploration
- Links to related articles]
```

### Article Quality Checklist

Before publishing, verify:
- [ ] All code examples are tested and functional
- [ ] Frontmatter follows standards
- [ ] Article provides educational value
- [ ] Links are current and accurate
- [ ] Grammar and spelling are correct
- [ ] **README.md files are updated**
- [ ] **Cross-references added** between article and relevant READMEs

## Container/Docker Best Practices (continued)

### When Using Containers (Legacy Section)
```

- [ ] **Cross-references added** between article and relevant READMEs

---

*These instructions embody AI-assisted development principles, emphasizing consistency, quality, and continuous improvement guided by comprehensive README maintenance, containerized development, and integrated API patterns.*

**Last Modified:** 2025-11-09
