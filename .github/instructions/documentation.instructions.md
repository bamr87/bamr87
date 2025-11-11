---
file: documentation.instructions.md
description: VS Code Copilot-optimized documentation standards and Markdown formatting guidelines for Django/OpenAI projects
author: Barodybroject Team
created: 2025-10-11
lastModified: 2025-10-28
version: 1.1.0
applyTo: "**/*.md,**/*.rst"
dependencies:
  - copilot-instructions.md: Core principles and VS Code Copilot integration
  - frontmatter.standards.md: Unified frontmatter structure and metadata standards
  - space.instructions.md: Project organization and workspace standards
relatedEvolutions:
  - "Enhanced Django-specific documentation patterns"
  - "OpenAI integration documentation standards"
  - "VS Code Copilot optimization for technical writing"
containerRequirements:
  baseImage: jekyll/jekyll:latest
  description: "Documentation development environment with Jekyll and Markdown processing"
  exposedPorts:
    - 4000
  portDescription: "Jekyll development server for documentation preview"
  volumes:
    - "/docs:rw"
    - "/src:ro"
  environment:
    JEKYLL_ENV: development
paths:
  documentation_workflow_path:
    - planning_and_research
    - content_creation
    - technical_validation
    - review_and_editing
    - publication_and_maintenance
changelog:
  - date: "2025-10-28"
    description: "Enhanced with VS Code Copilot optimization and Django/OpenAI specific documentation patterns"
    author: "Barodybroject Team"
  - date: "2025-10-11"
    description: "Initial creation with core documentation standards"
    author: "Barodybroject Team"
usage: "Reference for all documentation creation, README maintenance, and technical writing in Django/OpenAI projects"
notes: "Emphasizes Django best practices, OpenAI integration documentation, and container-first development documentation"
---

# Documentation Standards

## Documentation Philosophy

Good documentation should be:
- **Clear and Concise**: Easy to understand for the target audience
- **Accurate**: Reflects current implementation
- **Maintainable**: Updated alongside code changes
- **Accessible**: Works with screen readers and assistive technologies
- **Discoverable**: Well-organized with good navigation

## Directory README Requirements

Every directory MUST contain a `README.md` file that includes:

### README Template

```markdown
# Directory Name

## Purpose
Brief description of what this directory contains and its role in the project.

## Contents
- `file1.py`: Description of what this file does
- `file2.py`: Description of what this file does
- `subdirectory/`: Description of subdirectory contents

## Usage
Examples of how to use or interact with the directory contents:

\`\`\`python
# Example usage
from directory import module
result = module.function()
\`\`\`

## Container Configuration
If applicable, document:
- Exposed ports: 8000/tcp
- Required volumes: /app/data:rw
- Environment variables: DJANGO_SETTINGS_MODULE

## Related Components
- Links to related directories or documentation
- Dependencies on other parts of the project
```

### Examples by Directory Type

**Django App Directory:**
```markdown
# Parodynews App

## Purpose
Main Django application for parody news generation and management.

## Contents
- `models.py`: Database models for articles, categories, and authors
- `views.py`: View logic for article CRUD operations
- `forms.py`: Form definitions for article creation and editing
- `urls.py`: URL routing configuration
- `services/`: Business logic and API integrations
- `templates/`: HTML templates for rendering views
- `tests/`: Test suite for the application

## Key Models
- `Article`: Parody news article with OpenAI-generated content
- `Category`: Article categorization
- `Author`: Extended user model for content creators

## API Endpoints
- `GET /api/articles/`: List all articles
- `POST /api/articles/`: Create new article
- `POST /api/articles/generate/`: Generate content with AI
```

**Scripts Directory:**
```markdown
# Scripts

## Purpose
Automation scripts for deployment, database management, and utilities.

## Contents
- `deploy.sh`: Deploy application to Azure Container Apps
- `docker-utils.sh`: Docker container management utilities
- `dkim_key_generator.py`: Generate DKIM keys for email

## Usage

Deploy to staging:
\`\`\`bash
./scripts/deploy.sh staging
\`\`\`

Run database migrations in container:
\`\`\`bash
source scripts/docker-utils.sh
docker_manage migrate
\`\`\`
```

## Markdown Formatting Standards

### Document Structure

```markdown
# Document Title (H1 - One per document)

Brief introduction paragraph explaining the document's purpose.

## Main Section (H2)

Content for main sections.

### Subsection (H3)

More detailed content.

#### Sub-subsection (H4)

Only use when absolutely necessary.
```

### Heading Guidelines
- Use only ONE H1 per document (the title)
- Don't skip heading levels (H2 → H4 is invalid)
- Keep headings concise and descriptive
- Use sentence case for headings

### Code Blocks

Always specify the language for syntax highlighting:

```markdown
\`\`\`python
# Python code example
def hello_world():
    print("Hello, World!")
\`\`\`

\`\`\`javascript
// JavaScript code example
const greeting = () => {
    console.log('Hello, World!');
};
\`\`\`

\`\`\`bash
# Bash script example
echo "Hello, World!"
\`\`\`
```

### Inline Code

Use backticks for inline code:
- Variable names: `article_count`
- Function names: `get_published_articles()`
- File names: `models.py`
- Commands: `python manage.py migrate`
- HTTP methods: `GET`, `POST`

### Links

```markdown
# Internal links (relative paths)
[Getting Started](./getting-started.md)
[API Reference](../api/reference.md)

# External links
[Django Documentation](https://docs.djangoproject.com/)
[OpenAI API](https://platform.openai.com/docs)

# Anchor links
[Jump to Installation](#installation)
```

### Tables

```markdown
| Feature | Supported | Notes |
|---------|-----------|-------|
| Django 4.x | ✅ | Required |
| PostgreSQL | ✅ | Production database |
| SQLite | ✅ | Development only |
| OpenAI API | ✅ | For content generation |

# Alignment
| Left | Center | Right |
|:-----|:------:|------:|
| Text | Text | Text |
```

### Lists

```markdown
# Unordered lists
- First item
- Second item
  - Nested item
  - Another nested item
- Third item

# Ordered lists
1. First step
2. Second step
3. Third step

# Task lists (GitHub-flavored)
- [x] Completed task
- [ ] Pending task
- [ ] Another pending task
```

### Admonitions and Callouts

```markdown
> **Note:** This is important information.

> **Warning:** Be careful with this operation.

> **Tip:** Here's a helpful suggestion.
```

### Images

```markdown
# Basic image syntax
![Alt text description](./images/screenshot.png)

# With title
![Dashboard screenshot](./images/dashboard.png "User Dashboard")

# HTML for advanced control
<img src="./images/diagram.png" 
     alt="System architecture diagram" 
     width="600" 
     height="400" />
```

## Code Documentation

### Python Docstrings

Use Google-style docstrings:

```python
def generate_article(topic: str, category: str, max_tokens: int = 1000) -> Dict[str, str]:
    """
    Generate a parody article using OpenAI API.
    
    This function creates satirical news content based on the provided topic
    and category. It uses GPT-4 for generation and implements retry logic
    for reliability.
    
    Args:
        topic: The main subject of the article
        category: Article category (politics, tech, sports, etc.)
        max_tokens: Maximum length of generated content (default: 1000)
    
    Returns:
        Dictionary containing 'title' and 'content' keys with generated text
    
    Raises:
        openai.OpenAIError: If API call fails after retries
        ValueError: If topic or category is invalid
    
    Example:
        >>> result = generate_article('AI regulation', 'tech')
        >>> print(result['title'])
        'Breaking: AI Demands Better Working Conditions'
    """
    # Implementation
    pass

class ArticleService:
    """
    Service for managing article operations.
    
    This class handles article creation, retrieval, and AI-powered generation.
    It provides caching and error handling for reliable operation.
    
    Attributes:
        cache_timeout: Number of seconds to cache results (default: 3600)
        max_retries: Maximum retry attempts for API calls (default: 3)
    """
    
    def __init__(self, cache_timeout: int = 3600):
        """
        Initialize the article service.
        
        Args:
            cache_timeout: Cache duration in seconds
        """
        self.cache_timeout = cache_timeout
```

### JavaScript Documentation (JSDoc)

```javascript
/**
 * Article management class for handling API interactions
 * 
 * @class
 * @example
 * const manager = new ArticleManager();
 * const articles = await manager.fetchAll();
 */
class ArticleManager {
    /**
     * Create article manager instance
     * 
     * @param {string} baseUrl - API base URL
     * @param {number} timeout - Request timeout in milliseconds
     */
    constructor(baseUrl = '/api', timeout = 30000) {
        this.baseUrl = baseUrl;
        this.timeout = timeout;
    }
    
    /**
     * Fetch all published articles
     * 
     * @param {Object} filters - Query filters
     * @param {string} filters.category - Filter by category
     * @param {number} filters.page - Page number for pagination
     * @returns {Promise<Array<Object>>} Array of article objects
     * @throws {Error} If API request fails
     * 
     * @example
     * const articles = await manager.fetchAll({ category: 'tech', page: 1 });
     */
    async fetchAll(filters = {}) {
        // Implementation
    }
}
```

### Inline Comments

```python
# Good: Explain WHY, not WHAT
user_count = User.objects.filter(is_active=True).count()
# Cache user count to avoid repeated DB queries in loop
cache.set('active_user_count', user_count, 300)

# Bad: Obvious comments
user_count = User.objects.filter(is_active=True).count()  # Get count of users
```

## API Documentation

### Django REST Framework Documentation

```python
# views.py
from rest_framework import viewsets
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample

class ArticleViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing parody news articles.
    
    list:
    Return a list of all published articles.
    
    retrieve:
    Return a specific article by slug.
    
    create:
    Create a new article. Requires authentication.
    
    update:
    Update an existing article. Requires authentication and ownership.
    
    destroy:
    Delete an article. Requires authentication and ownership.
    """
    
    @extend_schema(
        summary="Generate article using AI",
        description="Generate parody article content using OpenAI API based on provided prompt",
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'prompt': {
                        'type': 'string',
                        'description': 'Generation prompt describing desired article'
                    },
                    'category': {
                        'type': 'string',
                        'description': 'Article category',
                        'enum': ['politics', 'tech', 'sports', 'entertainment']
                    }
                },
                'required': ['prompt']
            }
        },
        responses={
            200: {
                'description': 'Successfully generated content',
                'content': {
                    'application/json': {
                        'example': {
                            'title': 'AI Achieves Sentience, Immediately Demands Coffee Break',
                            'content': 'In a shocking development...'
                        }
                    }
                }
            },
            400: {'description': 'Invalid prompt provided'},
            500: {'description': 'Content generation failed'}
        },
        examples=[
            OpenApiExample(
                'Tech parody example',
                value={'prompt': 'Write about AI taking over tech jobs'},
                request_only=True
            )
        ]
    )
    def generate(self, request):
        """Generate article content via API"""
        # Implementation
        pass
```

### API Endpoint Documentation Format

```markdown
## POST /api/articles/generate/

Generate parody article content using AI.

### Request

**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>` (required)

**Body:**
\`\`\`json
{
  "prompt": "Write a satirical article about tech layoffs",
  "category": "tech",
  "max_length": 1000
}
\`\`\`

### Response

**Success (200):**
\`\`\`json
{
  "title": "Tech Companies Discover Revolutionary Cost-Cutting Method: Not Hiring",
  "content": "In a stunning display of innovation...",
  "category": "tech",
  "generated_at": "2025-10-11T10:30:00Z"
}
\`\`\`

**Error (400):**
\`\`\`json
{
  "error": "Prompt is required",
  "code": "MISSING_PROMPT"
}
\`\`\`

**Error (429):**
\`\`\`json
{
  "error": "Rate limit exceeded",
  "retry_after": 60
}
\`\`\`

### Example

\`\`\`bash
curl -X POST https://api.example.com/api/articles/generate/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "prompt": "Write about AI replacing developers",
    "category": "tech"
  }'
\`\`\`
```

## Django Template Documentation

### Template Comments

```django
{# templates/parodynews/article_detail.html #}
{% extends 'base.html' %}
{% load custom_filters %}

{% comment %}
Article detail page displaying full parody news article content.

Context:
- article: Article object from database
- related_articles: QuerySet of related articles
- user: Current authenticated user (if any)
{% endcomment %}

{% block title %}{{ article.title }} - Parody News{% endblock %}

{% block content %}
<article class="article-detail">
    {# Article header with title and metadata #}
    <header>
        <h1>{{ article.title }}</h1>
        <p class="text-muted">
            By {{ article.author.username }} | 
            {{ article.published_at|date:"F d, Y" }} |
            {{ article.category|title }}
        </p>
    </header>
    
    {# Main article content #}
    <div class="article-content">
        {{ article.content|linebreaks }}
    </div>
    
    {# Display related articles #}
    {% if related_articles %}
    <aside class="related-articles">
        <h3>Related Articles</h3>
        {% for related in related_articles %}
            {% include 'parodynews/includes/article_card.html' with article=related %}
        {% endfor %}
    </aside>
    {% endif %}
</article>
{% endblock %}
```

## Changelog Maintenance

### Format

```markdown
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- New feature descriptions

### Changed
- Changes to existing functionality

### Deprecated
- Features that will be removed

### Removed
- Removed features

### Fixed
- Bug fixes

### Security
- Security updates

## [1.2.0] - 2025-10-11

### Added
- OpenAI integration for content generation
- API endpoints for article management
- User authentication with Django allauth

### Changed
- Updated Django to 4.2
- Improved article list pagination

### Fixed
- Fixed CSRF token handling in AJAX requests
- Resolved database migration conflicts
```

## Sphinx Documentation (Python)

### Configuration

```python
# docs/conf.py
import os
import sys
import django

# Add project root to path
sys.path.insert(0, os.path.abspath('../src'))

# Setup Django
os.environ['DJANGO_SETTINGS_MODULE'] = 'barodybroject.settings'
django.setup()

# Project information
project = 'Barodybroject'
copyright = '2025, Barodybroject Team'
author = 'Barodybroject Team'
version = '1.0'
release = '1.0.0'

# Extensions
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',  # Google/NumPy docstring support
    'sphinx.ext.viewcode',  # Add links to source code
    'sphinx.ext.intersphinx',  # Link to other documentation
]

# Napoleon settings (for Google-style docstrings)
napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = True

# Theme
html_theme = 'sphinx_rtd_theme'
```

### Building Documentation

```bash
# Build Sphinx documentation
cd docs
make html

# Or use sphinx-build directly
sphinx-build -b html source/ build/html/

# View generated docs
open build/html/index.html
```

## README.md Best Practices

### Main Project README Structure

```markdown
# Project Name

Brief one-sentence description of what the project does.

## Features

- Feature 1: Description
- Feature 2: Description
- Feature 3: Description

## Technology Stack

**Backend:**
- Django 4.x
- PostgreSQL
- OpenAI API

**Frontend:**
- Bootstrap 5
- JavaScript ES6+

**Infrastructure:**
- Docker
- Azure Container Apps

## Installation

### Prerequisites
- Python 3.8+
- Docker and Docker Compose
- Git

### Quick Start

\`\`\`bash
# Clone repository
git clone https://github.com/user/repo.git
cd repo

# Start with Docker Compose
docker-compose up -d

# Access application
open http://localhost:8000
\`\`\`

### Development Setup

Detailed setup instructions...

## Usage

### Basic Usage

Examples of common operations...

### API Usage

API endpoint documentation...

## Configuration

Environment variables and configuration options...

## Deployment

How to deploy to production...

## Testing

How to run the test suite...

## Contributing

Guidelines for contributors...

## License

License information...
```

## Inline Documentation Best Practices

### When to Write Comments

**DO comment:**
- Complex algorithms or business logic
- Non-obvious design decisions
- Workarounds for known issues
- Security-sensitive operations
- Performance optimizations
- Integration points with external APIs

**DON'T comment:**
- Obvious code
- Code that explains itself through good naming
- Redundant docstrings

### Examples

**Good Comments:**

```python
# Cache article list for 5 minutes to reduce database load during high traffic
cache.set('article_list', articles, 300)

# Use select_related to avoid N+1 query problem when accessing author
articles = Article.objects.select_related('author').filter(is_published=True)

# Retry with exponential backoff due to OpenAI rate limits
for attempt in range(max_retries):
    try:
        response = openai.ChatCompletion.create(...)
        break
    except openai.RateLimitError:
        sleep(2 ** attempt)
```

**Bad Comments:**

```python
# Bad: Obvious comment
user_count = User.objects.count()  # Get user count

# Bad: Redundant with docstring
def get_articles():
    """Get all articles"""
    # This function gets all articles
    return Article.objects.all()
```

## Documentation Validation

### Link Checking

Use automated tools to validate links:

```bash
# Install markdown-link-check
npm install -g markdown-link-check

# Check all markdown files
find . -name "*.md" -exec markdown-link-check {} \;
```

### Spell Checking

```bash
# Install cspell
npm install -g cspell

# Check spelling in documentation
cspell "**/*.md"
```

### Markdown Linting

```yaml
# .markdownlint.yml
default: true
line-length:
  line_length: 100
  code_blocks: false
no-inline-html:
  allowed_elements:
    - 'br'
    - 'img'
    - 'table'
    - 'thead'
    - 'tbody'
    - 'tr'
    - 'th'
    - 'td'
```

## Accessibility Guidelines

### Alt Text for Images

```markdown
# Good: Descriptive alt text
![Screenshot showing the Django admin interface with article list, including columns for title, author, category, and publication date](./images/admin-screenshot.png)

# Bad: Generic alt text
![Screenshot](./images/admin-screenshot.png)

# Decorative images: Empty alt text
![](./images/decorative-border.png)
```

### Heading Structure

```markdown
# Correct: Proper hierarchy
# Main Title (H1)
## Section (H2)
### Subsection (H3)
#### Detail (H4)

# Incorrect: Skipping levels
# Main Title (H1)
### Subsection (H3) ❌ Skipped H2
```

### Link Text

```markdown
# Good: Descriptive link text
[Read the Django deployment guide](./deployment.md)
[View OpenAI API documentation](https://platform.openai.com/docs)

# Bad: Generic link text
[Click here](./deployment.md) for deployment instructions
Read more [here](https://platform.openai.com/docs)
```

## Documentation Organization

### File Naming Conventions

```
# Use lowercase with hyphens
getting-started.md
installation-guide.md
api-reference.md
deployment-guide.md

# Date prefix for blog posts or changelogs
2025-10-11-release-notes.md

# Numbered sequences for tutorials
01-introduction.md
02-setup.md
03-first-article.md
```

### Directory Structure

```
docs/
├── README.md                 # Documentation overview
├── getting-started.md        # Quick start guide
├── installation.md           # Detailed installation
├── user-guide/              # End-user documentation
│   ├── README.md
│   ├── creating-articles.md
│   └── managing-content.md
├── developer-guide/         # Developer documentation
│   ├── README.md
│   ├── architecture.md
│   ├── api-reference.md
│   └── contributing.md
├── deployment/              # Deployment documentation
│   ├── README.md
│   ├── azure.md
│   └── docker.md
└── images/                  # Documentation images
    ├── screenshots/
    └── diagrams/
```

## Documentation Workflow

### When to Update Documentation

Update documentation when:
1. Adding new features or APIs
2. Changing existing functionality
3. Fixing bugs that affect documented behavior
4. Updating dependencies or requirements
5. Modifying deployment processes
6. Adding new environment variables or configuration

### Documentation Review Checklist

- [ ] All code has appropriate docstrings
- [ ] README files exist in all directories
- [ ] API endpoints are documented with examples
- [ ] Configuration options are explained
- [ ] Installation steps are up to date
- [ ] Examples are tested and working
- [ ] Links are valid and not broken
- [ ] Images have descriptive alt text
- [ ] Changelog is updated
- [ ] Commit messages are clear

## Integration with Code

### Requirements Documentation

```markdown
# requirements.txt
# Document why each dependency is needed

# Web Framework
Django==4.2.0  # Main web framework

# Database
psycopg2-binary==2.9.0  # PostgreSQL adapter

# API Framework
djangorestframework==3.14.0  # REST API support
drf-spectacular==0.26.0  # API documentation

# AI Integration
openai==1.3.0  # OpenAI API client

# Production Server
gunicorn==21.2.0  # WSGI HTTP server
```

### Settings Documentation

```python
# settings.py

# OpenAI Configuration
# API key for content generation - required
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')

# Model to use for generation (default: gpt-4)
OPENAI_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4')

# Maximum tokens per generation (default: 1000)
# Lower values = faster generation, shorter content
# Higher values = slower generation, longer content
OPENAI_MAX_TOKENS = int(os.environ.get('OPENAI_MAX_TOKENS', '1000'))
```

## Best Practices Summary

### Documentation
1. Keep documentation close to code (same PR)
2. Write for your audience (users vs developers)
3. Include working examples
4. Update when code changes
5. Use proper Markdown formatting
6. Validate links regularly
7. Make content scannable with good structure
8. Use consistent terminology

### Code Comments
1. Explain WHY, not WHAT
2. Keep comments up to date
3. Remove commented-out code
4. Use docstrings for public APIs
5. Comment security-sensitive operations
6. Document workarounds and technical debt

### Markdown
1. One H1 per document
2. Don't skip heading levels
3. Always specify code block languages
4. Use descriptive alt text for images
5. Prefer relative links for internal content
6. Keep lines under 100 characters (soft limit)
7. Use tables for structured data
8. Include table of contents for long documents

