---
applyTo: '**/*.py,**/*.js,**/*.ts,**/*.jsx,**/*.tsx,**/*.mjs,**/*.cjs,**/*.sh,**/*.bash,.github/workflows/*.yml,.github/workflows/*.yaml'
---

# Development Standards

Development standards for languages, workflows, testing, and features. This guide provides universal patterns adaptable to web applications, CLI tools, libraries, enterprise systems, and educational platforms.

## Language-Specific Standards

### Python

**Naming Conventions:**

- Variables/functions: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_CASE`
- Private methods: `_leading_underscore`

**Code Quality:**

- Follow PEP 8
- Use type hints
- Write docstrings (Google style)
- Keep functions under 50 lines when possible

**Testing:**

```python
import pytest

@pytest.fixture
def test_data():
    return {"key": "value"}

def test_function(test_data):
    assert test_data["key"] == "value"
```

### JavaScript/TypeScript

**Modern Standards:**

- Use ES6+ features (const/let, arrow functions, destructuring)
- Prefer `const`/`let` over `var`
- Use async/await over promise chains
- Use template literals for string interpolation
- Prefer TypeScript for type safety
- Use ES modules (`import`/`export`)

**Naming Conventions:**

```javascript
// Variables and functions: camelCase
const userData = {};
function getUserData() {}

// Classes: PascalCase
class UserManager {}

// Constants: UPPER_CASE
const MAX_RETRIES = 3;
const API_TIMEOUT = 30;

// Private members: #prefix (ES2022+) or _prefix (convention)
class MyClass {
    #privateField;
    _conventionalPrivate;
    
    publicMethod() {
        return this.#privateField;
    }
}
```

**Error Handling:**

```javascript
async function fetchData(url) {
    try {
        const response = await fetch(url);
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        return await response.json();
        
    } catch (error) {
        // Log with context
        console.error('Failed to fetch data:', { url, error: error.message });
        
        // Re-throw or handle appropriately
        throw new Error(`Data fetch failed: ${error.message}`);
    }
}

// Advanced error handling with custom errors
class ValidationError extends Error {
    constructor(message, field) {
        super(message);
        this.name = 'ValidationError';
        this.field = field;
    }
}

async function processRequest(data) {
    try {
        // Validation
        if (!data.email) {
            throw new ValidationError('Email is required', 'email');
        }
        
        // Processing
        const result = await process(data);
        return { success: true, data: result };
        
    } catch (error) {
        if (error instanceof ValidationError) {
            return { success: false, error: error.message, field: error.field };
        }
        
        // Log unexpected errors
        console.error('Unexpected error:', error);
        return { success: false, error: 'Internal error occurred' };
    }
}
```

**TypeScript Patterns:**

```typescript
// Use interfaces for object shapes
interface User {
    id: string;
    email: string;
    role: 'admin' | 'user';
    createdAt: Date;
}

// Use type for unions and primitives
type Status = 'pending' | 'active' | 'inactive';
type ID = string | number;

// Generic functions with constraints
function processItems<T extends { id: string }>(items: T[]): T[] {
    return items.filter(item => item.id !== '');
}

// Async function with proper typing
async function fetchUser(id: string): Promise<User> {
    const response = await fetch(`/api/users/${id}`);
    
    if (!response.ok) {
        throw new Error(`Failed to fetch user: ${response.statusText}`);
    }
    
    return response.json() as Promise<User>;
}
```

### Bash/Shell

**Script Structure:**

```bash
#!/bin/bash
#
# File: script-name.sh
# Description: What this script does
# Usage: ./script-name.sh [options] [arguments]
#

# Exit on error, undefined variables, and pipe failures
set -euo pipefail

# Script metadata
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../" && pwd)"
readonly SCRIPT_NAME="$(basename "$0")"

# Configuration
readonly LOG_FILE="${PROJECT_ROOT}/logs/$(date +%Y%m%d-%H%M%S).log"

# Colors for output (optional)
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly NC='\033[0m'  # No Color

# Logging functions
log_info() {
    local message="$1"
    echo -e "${GREEN}[INFO]${NC} $(date '+%Y-%m-%d %H:%M:%S') - ${message}" | tee -a "$LOG_FILE"
}

log_error() {
    local message="$1"
    echo -e "${RED}[ERROR]${NC} $(date '+%Y-%m-%d %H:%M:%S') - ${message}" | tee -a "$LOG_FILE" >&2
}

log_warning() {
    local message="$1"
    echo -e "${YELLOW}[WARN]${NC} $(date '+%Y-%m-%d %H:%M:%S') - ${message}" | tee -a "$LOG_FILE"
}

# Error handler
error_handler() {
    local line_number=$1
    log_error "Script failed at line ${line_number}"
    cleanup_on_error
    exit 1
}

trap 'error_handler ${LINENO}' ERR

# Cleanup function
cleanup_on_error() {
    log_warning "Performing cleanup after error..."
    # Add cleanup logic here
}

# Usage information
usage() {
    cat <<EOF
Usage: ${SCRIPT_NAME} [OPTIONS] [ARGUMENTS]

Description of what the script does.

OPTIONS:
    -h, --help          Show this help message
    -v, --verbose       Enable verbose output
    -d, --dry-run       Run without making changes

EXAMPLES:
    ${SCRIPT_NAME} --verbose
    ${SCRIPT_NAME} --dry-run argument

EOF
    exit 0
}

# Validate prerequisites
validate_prerequisites() {
    log_info "Validating prerequisites..."
    
    # Check required tools
    local required_tools=("git" "docker")
    for tool in "${required_tools[@]}"; do
        if ! command -v "$tool" &> /dev/null; then
            log_error "Required tool not found: ${tool}"
            return 1
        fi
    done
    
    log_info "Prerequisites validated"
}

# Main function
main() {
    log_info "Starting ${SCRIPT_NAME}"
    
    # Create logs directory if needed
    mkdir -p "${PROJECT_ROOT}/logs"
    
    # Validate prerequisites
    validate_prerequisites || exit 1
    
    # Implementation
    log_info "Process completed successfully"
}

# Parse command-line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            usage
            ;;
        -v|--verbose)
            set -x  # Enable verbose mode
            shift
            ;;
        -d|--dry-run)
            DRY_RUN=true
            shift
            ;;
        *)
            log_error "Unknown option: $1"
            usage
            ;;
    esac
done

# Run main function if script is executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
```

**Best Practices:**

- Always use `set -euo pipefail` at the start
- Quote all variable expansions: `"$variable"`
- Use `readonly` for constants
- Use `local` for function-scoped variables
- Provide meaningful error messages with context
- Check command existence before using
- Use functions for reusability
- Include usage/help documentation
- Implement cleanup handlers for error cases
- Log important operations

## CI/CD Workflows

### Basic Workflow Structure

```yaml
name: CI

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up environment
        run: # Setup commands
      - name: Run tests
        run: # Test commands
```

### Common Patterns

**Matrix Testing:**

```yaml
strategy:
  matrix:
    python-version: ['3.8', '3.9', '3.10', '3.11']
```

**Caching:**

```yaml
- uses: actions/setup-python@v4
  with:
    cache: 'pip'
```

**Conditional Execution:**

```yaml
- name: Deploy
  if: github.ref == 'refs/heads/main'
  run: ./scripts/deploy.sh
```

## Testing Standards

### Test Organization

```text
tests/
├── unit/          # Unit tests
├── integration/   # Integration tests
└── e2e/          # End-to-end tests
```

### Test Best Practices

- Test isolation: Tests should not depend on each other
- Use fixtures for test data
- Mock external dependencies
- Test edge cases and error conditions
- Aim for >80% coverage on critical components

### Example Test Structure

```python
import pytest
from unittest.mock import Mock, patch

class TestFeature:
    def test_success_case(self):
        # Arrange
        input_data = {"key": "value"}
        
        # Act
        result = process_data(input_data)
        
        # Assert
        assert result["processed"] == True
    
    @patch('external_service.call')
    def test_with_mock(self, mock_call):
        mock_call.return_value = {"status": "ok"}
        result = use_external_service()
        assert result["status"] == "ok"
```

## Feature Development

### Development Workflow

1. **Plan**: Document feature requirements
2. **Design**: Create architecture and interfaces
3. **Implement**: Write code following standards
4. **Test**: Create comprehensive tests
5. **Document**: Update documentation
6. **Review**: Code review and feedback
7. **Deploy**: Release through CI/CD

### Code Review Checklist

- [ ] Follows coding standards
- [ ] Includes tests
- [ ] Documentation updated
- [ ] Error handling implemented
- [ ] Performance considered
- [ ] Security reviewed

## Error Handling

### Python Error Handling

```python
def process_data(data):
    try:
        result = validate(data)
        return transform(result)
    except ValidationError as e:
        logger.error(f"Validation failed: {e}")
        raise
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        raise ProcessingError("Failed to process data") from e
```

### JavaScript Error Handling

```javascript
async function handleRequest(req) {
    try {
        const validated = await validate(req);
        return await process(validated);
    } catch (error) {
        if (error instanceof ValidationError) {
            return { error: error.message, code: 400 };
        }
        logger.error('Unexpected error:', error);
        return { error: 'Internal server error', code: 500 };
    }
}
```

## Service Layer Architecture

### Service Layer Pattern

For applications with complex business logic, implement a service layer:

```python
# Python service layer example
class UserService:
    """Service for user management operations"""
    
    def __init__(self, database, cache):
        self.db = database
        self.cache = cache
        self.max_retries = 3
    
    def create_user(self, email: str, password: str) -> User:
        """
        Create new user with validation and error handling
        
        Args:
            email: User email address
            password: User password (will be hashed)
        
        Returns:
            Created user object
        
        Raises:
            ValidationError: If email/password invalid
            DuplicateError: If user already exists
        """
        # Validation
        if not self._is_valid_email(email):
            raise ValidationError("Invalid email format")
        
        # Check for duplicates
        if self.db.users.find_by_email(email):
            raise DuplicateError("User already exists")
        
        # Hash password
        hashed_password = self._hash_password(password)
        
        # Create user
        user = self.db.users.create(
            email=email,
            password=hashed_password
        )
        
        # Cache user data
        self.cache.set(f"user:{user.id}", user, timeout=3600)
        
        return user
```

```javascript
// JavaScript/TypeScript service layer example
class ArticleService {
    constructor(database, apiClient, cache) {
        this.db = database;
        this.api = apiClient;
        this.cache = cache;
    }
    
    async generateArticle(prompt, options = {}) {
        // Check cache first
        const cacheKey = `article:${prompt}`;
        const cached = await this.cache.get(cacheKey);
        if (cached) return cached;
        
        // Generate with external API
        try {
            const result = await this.api.generate({
                prompt,
                max_tokens: options.maxTokens || 1000,
                temperature: options.temperature || 0.7
            });
            
            // Cache result
            await this.cache.set(cacheKey, result, { ttl: 3600 });
            
            return result;
            
        } catch (error) {
            if (error instanceof RateLimitError) {
                throw new Error('Rate limit exceeded, try again later');
            }
            throw error;
        }
    }
}
```

## API Development Patterns

### RESTful API Design

```python
# Python Flask/FastAPI example
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, EmailStr

app = FastAPI()

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    
class UserResponse(BaseModel):
    id: str
    email: str
    created_at: str

@app.post("/api/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(user: UserCreate):
    """Create a new user"""
    try:
        result = await user_service.create_user(user.email, user.password)
        return UserResponse(**result)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except DuplicateError as e:
        raise HTTPException(status_code=409, detail=str(e))
```

```javascript
// JavaScript Express example
const express = require('express');
const router = express.Router();

// POST /api/articles
router.post('/api/articles', async (req, res) => {
    try {
        const { title, content } = req.body;
        
        // Validation
        if (!title || !content) {
            return res.status(400).json({
                error: 'Title and content are required'
            });
        }
        
        // Create article
        const article = await articleService.create({
            title,
            content,
            author: req.user.id
        });
        
        // Return created resource
        res.status(201).json({
            success: true,
            data: article
        });
        
    } catch (error) {
        console.error('Article creation failed:', error);
        res.status(500).json({
            error: 'Failed to create article'
        });
    }
});

module.exports = router;
```

## Security Best Practices

### Input Validation

```python
# Python validation example
from typing import Any
import re

def validate_email(email: str) -> tuple[bool, str | None]:
    """Validate email address format"""
    if not email or len(email) > 254:
        return False, "Invalid email length"
    
    # Basic RFC 5322 pattern
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(pattern, email):
        return False, "Invalid email format"
    
    return True, None

def sanitize_input(data: dict[str, Any]) -> dict[str, Any]:
    """Sanitize user input to prevent injection"""
    sanitized = {}
    for key, value in data.items():
        if isinstance(value, str):
            # Remove potentially dangerous characters
            sanitized[key] = re.sub(r'[<>\'";]', '', value)
        else:
            sanitized[key] = value
    return sanitized
```

### Environment-Based Configuration

```python
# Python configuration management
import os
from pathlib import Path

class Config:
    """Application configuration"""
    
    # Environment
    ENV = os.getenv('APP_ENV', 'development')
    DEBUG = ENV == 'development'
    
    # Security
    SECRET_KEY = os.getenv('SECRET_KEY')
    if not SECRET_KEY and ENV == 'production':
        raise ValueError("SECRET_KEY must be set in production")
    
    # Database
    DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///dev.db')
    
    # API Keys (never hardcode!)
    API_KEY = os.getenv('API_KEY')
    
    # Paths
    BASE_DIR = Path(__file__).parent
    UPLOAD_DIR = BASE_DIR / 'uploads'
    
    @classmethod
    def validate(cls):
        """Validate required configuration"""
        required = ['SECRET_KEY'] if cls.ENV == 'production' else []
        missing = [key for key in required if not getattr(cls, key)]
        if missing:
            raise ValueError(f"Missing required config: {missing}")
```

### Security Checklist

- [ ] Never commit secrets, API keys, or credentials
- [ ] Use environment variables for sensitive configuration
- [ ] Validate and sanitize all user inputs
- [ ] Use parameterized queries (prevent SQL injection)
- [ ] Implement proper authentication and authorization
- [ ] Use HTTPS for all external communication
- [ ] Keep dependencies updated and scan for vulnerabilities
- [ ] Implement rate limiting for APIs
- [ ] Log security-relevant events
- [ ] Handle errors without exposing sensitive information

## Framework-Specific Patterns

### Web Framework Patterns (Django, Flask, Express, Rails)

**Model/ORM Pattern:**

- Define clear data models with validation
- Use migrations for schema changes
- Implement proper relationships (foreign keys, many-to-many)
- Add indexes for frequently queried fields
- Use select_related/prefetch_related to avoid N+1 queries

**View/Controller Pattern:**

- Keep views/controllers thin; business logic in services
- Validate inputs before processing
- Return consistent response formats
- Use appropriate HTTP status codes
- Implement proper error handling

**Template/Frontend Pattern:**

- Escape output to prevent XSS
- Use CSRF protection for forms
- Implement progressive enhancement
- Optimize asset loading
- Follow accessibility guidelines

### Testing Framework Patterns

**Pytest (Python):**

```python
import pytest
from unittest.mock import Mock, patch

@pytest.fixture
def mock_service():
    """Fixture providing mocked service"""
    service = Mock()
    service.process.return_value = {"status": "success"}
    return service

@pytest.mark.parametrize("input,expected", [
    ("valid", "processed"),
    ("", "error"),
    (None, "error"),
])
def test_process_various_inputs(input, expected):
    """Test processing various input types"""
    result = process_function(input)
    assert result == expected

@patch('external_api.call')
def test_with_external_api(mock_call, mock_service):
    """Test integration with external API"""
    mock_call.return_value = {"data": "test"}
    result = service_function(mock_service)
    assert result["data"] == "test"
    mock_call.assert_called_once()
```

**Jest (JavaScript):**

```javascript
describe('ArticleService', () => {
    let service;
    
    beforeEach(() => {
        service = new ArticleService(mockDb, mockApi);
    });
    
    afterEach(() => {
        jest.clearAllMocks();
    });
    
    test('should create article successfully', async () => {
        // Arrange
        const articleData = { title: 'Test', content: 'Content' };
        mockDb.create.mockResolvedValue({ id: '123', ...articleData });
        
        // Act
        const result = await service.createArticle(articleData);
        
        // Assert
        expect(result.id).toBe('123');
        expect(mockDb.create).toHaveBeenCalledWith(articleData);
    });
    
    test('should handle creation failure', async () => {
        // Arrange
        mockDb.create.mockRejectedValue(new Error('DB error'));
        
        // Act & Assert
        await expect(service.createArticle({})).rejects.toThrow('DB error');
    });
});
```

## Container Development

### Dockerfile Best Practices

```dockerfile
# Multi-stage build for optimal image size
FROM python:3.11-slim AS base

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Development stage
FROM base AS development

COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY . .

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

# Production stage
FROM base AS production

# Copy only necessary files
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY config/ ./config/

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=40s \
  CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000"]
```

### Docker Compose Development

```yaml
# docker-compose.yml
version: '3.8'

services:
  app:
    build:
      context: .
      target: development
    volumes:
      - ./src:/app/src:ro
      - ./tests:/app/tests:ro
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:pass@db:5432/app_db
      - REDIS_URL=redis://cache:6379/0
    depends_on:
      db:
        condition: service_healthy
      cache:
        condition: service_started
    command: ["python", "manage.py", "runserver", "0.0.0.0:8000"]

  db:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: app_db
      POSTGRES_USER: user
      POSTGRES_PASSWORD: pass
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U user"]
      interval: 10s
      timeout: 5s
      retries: 5
    ports:
      - "5432:5432"

  cache:
    image: redis:7-alpine
    ports:
      - "6379:6379"

volumes:
  postgres_data:
```

---

**Version:** 3.0.0 | **Last Modified:** 2025-11-14 | **Author:** Amr Abdel-Motaleb

**Purpose:** Universal development standards template applicable to various project types, languages, and frameworks.
