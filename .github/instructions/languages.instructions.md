---
file: languages.instructions.md
description: VS Code Copilot-optimized language-specific coding standards for Python/Django, JavaScript, and Bash development
author: Barodybroject Team
created: 2025-10-11
lastModified: 2025-10-28
version: 1.1.0
applyTo: "**/*.py,**/*.js,**/*.sh,**/*.bash"
dependencies:
  - copilot-instructions.md: Core principles and VS Code Copilot integration
  - space.instructions.md: Project organization and workspace standards
  - features.instructions.md: Feature development patterns
containerRequirements:
  baseImage: python:3.8-slim, node:18-alpine
  description: "Multi-language development environment for Django/OpenAI applications"
  exposedPorts:
    - 8000
    - 4002
  portDescription: "Django development server and Jekyll static site server"
  volumes:
    - "/app/src:rw"
    - "/app/static:rw"
    - "/app/templates:rw"
  environment:
    DJANGO_SETTINGS_MODULE: barodybroject.settings
    PYTHONUNBUFFERED: 1
    OPENAI_API_KEY: required
  resources:
    cpu: "0.5-1.0"
    memory: "512MiB-1GiB"
  healthCheck: "/health endpoint on Django development server"
paths:
  language_development_path:
    - python_django_patterns
    - javascript_frontend_integration
    - bash_automation_scripts
    - openai_service_integration
    - testing_and_validation
    - deployment_automation
changelog:
  - date: "2025-10-28"
    description: "Enhanced with VS Code Copilot optimization and Django/OpenAI specific patterns"
    author: "Barodybroject Team"
  - date: "2025-10-11"
    description: "Initial creation with core language standards"
    author: "Barodybroject Team"
---

# Language-Specific Coding Standards

Apply the [general coding guidelines](../copilot-instructions.md) to all code.

## Python/Django Development

### Naming Conventions

```python
# Variables and functions: snake_case
user_count = 10
article_list = []

def get_published_articles():
    pass

def generate_parody_content(prompt):
    pass

# Classes: PascalCase
class ArticleManager:
    pass

class OpenAIService:
    pass

# Constants: UPPER_CASE
MAX_RETRIES = 3
DEFAULT_CATEGORY = 'general'
API_TIMEOUT = 30

# Private methods: _leading_underscore
class MyClass:
    def _internal_helper(self):
        pass
    
    def public_method(self):
        return self._internal_helper()
```

### Django Project Structure

```python
# Django app organization
parodynews/
├── __init__.py
├── models.py              # Database models
├── views.py               # View logic
├── forms.py               # Form definitions
├── urls.py                # URL routing
├── admin.py               # Admin interface configuration
├── apps.py                # App configuration
├── serializers.py         # DRF serializers
├── services/              # Business logic layer
│   ├── __init__.py
│   ├── openai_service.py
│   └── content_service.py
├── utils/                 # Utility functions
│   ├── __init__.py
│   └── validators.py
├── templates/             # HTML templates
│   └── parodynews/
│       ├── article_list.html
│       └── article_detail.html
├── tests/                 # Test suite
│   ├── __init__.py
│   ├── test_models.py
│   ├── test_views.py
│   └── test_services.py
└── migrations/            # Database migrations
    └── 0001_initial.py
```

### Django Models Best Practices

```python
from django.db import models
from django.contrib.auth.models import User
from django.urls import reverse
from django.core.validators import MinLengthValidator

class Article(models.Model):
    """
    Parody news article with OpenAI-generated content
    
    Fields:
        title: Article headline (max 200 chars)
        slug: URL-friendly version of title
        content: Main article body
        author: Article author (ForeignKey to User)
        category: Article category
        ai_prompt: Original prompt used for generation
        is_published: Publication status
        published_at: Publication timestamp
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """
    
    CATEGORY_CHOICES = [
        ('politics', 'Politics'),
        ('tech', 'Technology'),
        ('sports', 'Sports'),
        ('entertainment', 'Entertainment'),
    ]
    
    title = models.CharField(
        max_length=200,
        validators=[MinLengthValidator(10)],
        help_text="Article headline (minimum 10 characters)"
    )
    slug = models.SlugField(unique=True, max_length=200)
    content = models.TextField(
        validators=[MinLengthValidator(100)],
        help_text="Main article content"
    )
    author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='articles'
    )
    category = models.CharField(
        max_length=50,
        choices=CATEGORY_CHOICES,
        default='politics'
    )
    ai_prompt = models.TextField(
        blank=True,
        help_text="Original prompt for AI generation"
    )
    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-published_at', '-created_at']
        indexes = [
            models.Index(fields=['-published_at']),
            models.Index(fields=['category', '-published_at']),
            models.Index(fields=['author', '-created_at']),
        ]
        verbose_name = 'Article'
        verbose_name_plural = 'Articles'
    
    def __str__(self):
        return self.title
    
    def get_absolute_url(self):
        return reverse('article-detail', kwargs={'slug': self.slug})
    
    def save(self, *args, **kwargs):
        # Auto-generate slug if not provided
        if not self.slug:
            from django.utils.text import slugify
            self.slug = slugify(self.title)
        
        # Set published_at when first published
        if self.is_published and not self.published_at:
            from django.utils import timezone
            self.published_at = timezone.now()
        
        super().save(*args, **kwargs)
```

### Django Views and Forms

```python
# views.py
from django.views.generic import CreateView, UpdateView
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from .models import Article
from .forms import ArticleForm
from .services.openai_service import OpenAIService

class ArticleGenerateView(LoginRequiredMixin, CreateView):
    """Generate article using OpenAI API"""
    model = Article
    form_class = ArticleForm
    template_name = 'parodynews/article_generate.html'
    
    def form_valid(self, form):
        """Generate content with OpenAI before saving"""
        article = form.save(commit=False)
        article.author = self.request.user
        
        # Generate content if prompt provided
        if form.cleaned_data.get('prompt'):
            try:
                openai_service = OpenAIService()
                generated_content = openai_service.generate_parody_content(
                    prompt=form.cleaned_data['prompt']
                )
                article.content = generated_content
                article.ai_prompt = form.cleaned_data['prompt']
                
                messages.success(
                    self.request,
                    'Article generated successfully!'
                )
            except Exception as e:
                messages.error(
                    self.request,
                    f'Failed to generate content: {str(e)}'
                )
                return self.form_invalid(form)
        
        return super().form_valid(form)

# forms.py
from django import forms
from .models import Article

class ArticleForm(forms.ModelForm):
    """Article creation/edit form with AI prompt field"""
    
    prompt = forms.CharField(
        widget=forms.Textarea(attrs={
            'rows': 3,
            'placeholder': 'Enter a prompt for AI content generation (optional)'
        }),
        required=False,
        help_text='Describe the parody article you want to generate'
    )
    
    class Meta:
        model = Article
        fields = ['title', 'category', 'content', 'is_published']
        widgets = {
            'content': forms.Textarea(attrs={'rows': 10}),
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
        }
    
    def clean_title(self):
        """Validate title doesn't already exist"""
        title = self.cleaned_data.get('title')
        
        # Check for duplicate titles (excluding current instance in updates)
        qs = Article.objects.filter(title__iexact=title)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        
        if qs.exists():
            raise forms.ValidationError('An article with this title already exists')
        
        return title
```

### Django REST Framework APIs

```python
# serializers.py
from rest_framework import serializers
from .models import Article

class ArticleSerializer(serializers.ModelSerializer):
    """Serializer for Article API"""
    
    author_name = serializers.CharField(source='author.username', read_only=True)
    url = serializers.SerializerMethodField()
    
    class Meta:
        model = Article
        fields = [
            'id', 'title', 'slug', 'content', 'author', 'author_name',
            'category', 'is_published', 'published_at', 'created_at',
            'updated_at', 'url'
        ]
        read_only_fields = ['slug', 'created_at', 'updated_at']
    
    def get_url(self, obj):
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(obj.get_absolute_url())
        return obj.get_absolute_url()

# views.py (API views)
from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response

class ArticleViewSet(viewsets.ModelViewSet):
    """API viewset for articles"""
    
    queryset = Article.objects.all()
    serializer_class = ArticleSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    lookup_field = 'slug'
    
    def get_queryset(self):
        """Filter published articles for non-staff users"""
        qs = super().get_queryset()
        if not self.request.user.is_staff:
            qs = qs.filter(is_published=True)
        return qs
    
    @action(detail=False, methods=['post'])
    def generate(self, request):
        """Custom action to generate article via API"""
        prompt = request.data.get('prompt')
        if not prompt:
            return Response(
                {'error': 'Prompt is required'},
                status=400
            )
        
        try:
            openai_service = OpenAIService()
            content = openai_service.generate_parody_content(prompt)
            
            return Response({
                'content': content,
                'prompt': prompt
            })
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=500
            )
```

### Python Testing with Pytest

```python
# tests/test_services.py
import pytest
from unittest.mock import Mock, patch
from parodynews.services.openai_service import OpenAIService

@pytest.fixture
def openai_service():
    """Fixture providing OpenAI service instance"""
    return OpenAIService()

@pytest.fixture
def mock_openai_response():
    """Mock OpenAI API response"""
    return {
        'choices': [{
            'message': {
                'content': 'Generated parody content here...'
            }
        }]
    }

class TestOpenAIService:
    """Test suite for OpenAI service"""
    
    @patch('openai.ChatCompletion.create')
    def test_generate_content_success(self, mock_create, openai_service, mock_openai_response):
        """Test successful content generation"""
        mock_create.return_value = mock_openai_response
        
        result = openai_service.generate_parody_content('Test prompt')
        
        assert result == 'Generated parody content here...'
        mock_create.assert_called_once()
    
    @patch('openai.ChatCompletion.create')
    def test_generate_content_retry_on_rate_limit(self, mock_create, openai_service):
        """Test retry logic on rate limit error"""
        import openai
        
        # First call raises RateLimitError, second succeeds
        mock_create.side_effect = [
            openai.RateLimitError('Rate limit exceeded'),
            {'choices': [{'message': {'content': 'Success after retry'}}]}
        ]
        
        result = openai_service.generate_parody_content('Test prompt')
        
        assert result == 'Success after retry'
        assert mock_create.call_count == 2
```

## JavaScript Development

### Modern JavaScript Standards

```javascript
// Use ES6+ features
const articleManager = {
    /**
     * Fetch articles from API
     * @param {Object} filters - Query filters
     * @returns {Promise<Array>} Array of articles
     */
    async fetchArticles(filters = {}) {
        try {
            const params = new URLSearchParams(filters);
            const response = await fetch(`/api/articles/?${params}`);
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const data = await response.json();
            return data.results || data;
            
        } catch (error) {
            console.error('Failed to fetch articles:', error);
            throw error;
        }
    },
    
    /**
     * Generate article using AI
     * @param {string} prompt - Generation prompt
     * @returns {Promise<Object>} Generated article data
     */
    async generateArticle(prompt) {
        try {
            const response = await fetch('/api/articles/generate/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCsrfToken(),
                },
                body: JSON.stringify({ prompt })
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.message || 'Generation failed');
            }
            
            return await response.json();
            
        } catch (error) {
            console.error('Failed to generate article:', error);
            throw error;
        }
    },
    
    /**
     * Get CSRF token from cookie
     * @returns {string} CSRF token
     */
    getCsrfToken() {
        const name = 'csrftoken';
        const cookies = document.cookie.split(';');
        
        for (let cookie of cookies) {
            const [key, value] = cookie.trim().split('=');
            if (key === name) {
                return decodeURIComponent(value);
            }
        }
        
        return '';
    }
};
```

### DOM Manipulation and Event Handling

```javascript
/**
 * Dynamic form field updates with AJAX
 */
class DynamicFormHandler {
    constructor(formSelector) {
        this.form = document.querySelector(formSelector);
        this.init();
    }
    
    init() {
        if (!this.form) {
            console.error('Form not found');
            return;
        }
        
        this.setupEventListeners();
    }
    
    setupEventListeners() {
        // Listen for category changes to update field options
        const categoryField = this.form.querySelector('#id_category');
        if (categoryField) {
            categoryField.addEventListener('change', (e) => {
                this.updateFieldOptions(e.target.value);
            });
        }
        
        // Handle form submission
        this.form.addEventListener('submit', (e) => {
            this.handleSubmit(e);
        });
    }
    
    async updateFieldOptions(category) {
        try {
            const response = await fetch(`/api/field-options/?category=${category}`);
            const options = await response.json();
            
            // Update dependent fields
            this.updateSelectField('#id_subcategory', options.subcategories);
            
        } catch (error) {
            console.error('Failed to update field options:', error);
        }
    }
    
    updateSelectField(selector, options) {
        const field = this.form.querySelector(selector);
        if (!field) return;
        
        // Clear existing options
        field.innerHTML = '<option value="">---------</option>';
        
        // Add new options
        options.forEach(option => {
            const optionElement = document.createElement('option');
            optionElement.value = option.value;
            optionElement.textContent = option.label;
            field.appendChild(optionElement);
        });
    }
    
    async handleSubmit(event) {
        event.preventDefault();
        
        const submitButton = this.form.querySelector('button[type="submit"]');
        const originalText = submitButton.textContent;
        
        try {
            // Disable submit button
            submitButton.disabled = true;
            submitButton.textContent = 'Processing...';
            
            const formData = new FormData(this.form);
            const response = await fetch(this.form.action, {
                method: 'POST',
                body: formData,
                headers: {
                    'X-CSRFToken': articleManager.getCsrfToken(),
                }
            });
            
            if (response.ok) {
                window.location.href = response.url;
            } else {
                const error = await response.json();
                this.showError(error.message || 'Form submission failed');
            }
            
        } catch (error) {
            console.error('Form submission error:', error);
            this.showError('An unexpected error occurred');
            
        } finally {
            submitButton.disabled = false;
            submitButton.textContent = originalText;
        }
    }
    
    showError(message) {
        // Display error message to user
        const alertDiv = document.createElement('div');
        alertDiv.className = 'alert alert-danger alert-dismissible fade show';
        alertDiv.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        
        this.form.insertBefore(alertDiv, this.form.firstChild);
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    new DynamicFormHandler('#article-form');
});
```

### Error Handling Patterns

```javascript
/**
 * Centralized error handler for API calls
 */
class APIErrorHandler {
    static handle(error, context = '') {
        console.error(`API Error ${context}:`, error);
        
        // User-friendly error messages
        const errorMessages = {
            401: 'Please log in to continue',
            403: 'You do not have permission to perform this action',
            404: 'The requested resource was not found',
            429: 'Too many requests. Please try again later',
            500: 'Server error. Please try again',
            502: 'Service temporarily unavailable',
            503: 'Service temporarily unavailable',
        };
        
        const statusCode = error.response?.status;
        const message = errorMessages[statusCode] || 'An unexpected error occurred';
        
        this.showNotification(message, 'error');
        
        return message;
    }
    
    static showNotification(message, type = 'info') {
        // Implement notification display logic
        const notification = document.createElement('div');
        notification.className = `alert alert-${type === 'error' ? 'danger' : 'info'}`;
        notification.textContent = message;
        
        document.body.appendChild(notification);
        
        setTimeout(() => notification.remove(), 5000);
    }
}
```

## Bash/Shell Scripting

### Script Structure and Standards

```bash
#!/bin/bash
#
# File: deploy.sh
# Description: Deploy Django application to Azure Container Apps
# Author: Barodybroject Team
# Created: 2025-10-11
# Version: 1.0.0
#
# Usage: ./scripts/deploy.sh [environment]
#   environment: development, staging, or production

# Exit on error, undefined variables, and pipe failures
set -euo pipefail

# Script directory and project root
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../" && pwd)"

# Configuration
readonly LOG_FILE="${PROJECT_ROOT}/logs/deploy-$(date +%Y%m%d-%H%M%S).log"
readonly ENVIRONMENT="${1:-development}"

# Colors for output
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly NC='\033[0m' # No Color

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

# Validate environment
validate_environment() {
    log_info "Validating environment: ${ENVIRONMENT}"
    
    # Check required tools
    local required_tools=("docker" "az" "git")
    for tool in "${required_tools[@]}"; do
        if ! command -v "$tool" &> /dev/null; then
            log_error "Required tool not found: ${tool}"
            return 1
        fi
    done
    
    # Validate environment parameter
    if [[ ! "$ENVIRONMENT" =~ ^(development|staging|production)$ ]]; then
        log_error "Invalid environment: ${ENVIRONMENT}"
        log_error "Must be one of: development, staging, production"
        return 1
    fi
    
    log_info "Environment validation passed"
}

# Build Docker image
build_image() {
    log_info "Building Docker image for ${ENVIRONMENT}"
    
    local image_tag="barodybroject:${ENVIRONMENT}-$(git rev-parse --short HEAD)"
    
    docker build \
        --target production \
        --tag "$image_tag" \
        --build-arg ENVIRONMENT="$ENVIRONMENT" \
        "${PROJECT_ROOT}" || {
        log_error "Docker build failed"
        return 1
    }
    
    log_info "Successfully built image: ${image_tag}"
    echo "$image_tag"
}

# Deploy to Azure
deploy_to_azure() {
    local image_tag="$1"
    
    log_info "Deploying to Azure Container Apps (${ENVIRONMENT})"
    
    cd "$PROJECT_ROOT" || return 1
    
    # Deploy using Azure Developer CLI
    azd deploy \
        --environment "$ENVIRONMENT" \
        --no-prompt || {
        log_error "Azure deployment failed"
        return 1
    }
    
    log_info "Deployment completed successfully"
}

# Main execution
main() {
    log_info "Starting deployment process"
    
    # Create logs directory
    mkdir -p "${PROJECT_ROOT}/logs"
    
    # Validate environment
    validate_environment || exit 1
    
    # Build image
    local image_tag
    image_tag=$(build_image) || exit 1
    
    # Deploy to Azure
    deploy_to_azure "$image_tag" || exit 1
    
    log_info "Deployment completed successfully"
}

# Run main function if script is executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
```

### Docker Utility Scripts

```bash
#!/bin/bash
#
# File: docker-utils.sh
# Description: Docker container management utilities
# Author: Barodybroject Team
# Version: 1.0.0

set -euo pipefail

# Build development container
build_dev_container() {
    local tag="${1:-latest}"
    
    docker build \
        --file Dockerfile \
        --target development \
        --tag "barodybroject:dev-${tag}" \
        . || {
        echo "Failed to build development container"
        return 1
    }
    
    echo "Development container built: barodybroject:dev-${tag}"
}

# Run Django management commands in container
docker_manage() {
    local command="$*"
    
    docker-compose exec web python manage.py $command
}

# Run tests in container
docker_test() {
    docker-compose exec web pytest tests/ -v --cov=parodynews
}

# Check container health
check_container_health() {
    local container_name="${1:-web}"
    
    if docker-compose ps "$container_name" | grep -q "Up (healthy)"; then
        echo "Container ${container_name} is healthy"
        return 0
    else
        echo "Container ${container_name} is not healthy"
        return 1
    fi
}

# Clean up containers and volumes
cleanup_containers() {
    echo "Stopping containers..."
    docker-compose down
    
    echo "Removing volumes..."
    docker-compose down -v
    
    echo "Pruning unused images..."
    docker image prune -f
}

# Export functions for sourcing
if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
    export -f build_dev_container
    export -f docker_manage
    export -f docker_test
    export -f check_container_health
    export -f cleanup_containers
fi
```

## Code Quality Guidelines

### Python/Django
- Follow PEP 8 style guide (use `black` for formatting)
- Use type hints for function signatures
- Write docstrings for all public classes and functions (Google or NumPy style)
- Keep functions under 50 lines when possible
- Use Django's built-in features before custom implementations
- Validate all user inputs
- Use Django ORM instead of raw SQL

### JavaScript
- Use ES6+ features (const/let, arrow functions, async/await)
- Prefer async/await over promises `.then()` chains
- Use template literals for string interpolation
- Implement proper error handling for all async operations
- Use descriptive variable names
- Avoid global variables
- Use strict mode (`'use strict'`)

### Bash
- Always use `set -euo pipefail` at the start
- Quote all variable expansions: `"$variable"`
- Use `readonly` for constants
- Use `local` for function-scoped variables
- Provide meaningful error messages
- Check command existence before using: `command -v tool &> /dev/null`
- Use functions for reusability

## Integration Patterns

### Django + OpenAI Integration

```python
# parodynews/services/content_generator.py
from typing import Dict, Any, Optional
import openai
import logging
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

class ContentGenerator:
    """
    Service for generating parody content with caching and error handling
    """
    
    def __init__(self):
        openai.api_key = settings.OPENAI_API_KEY
        self.cache_timeout = 3600  # 1 hour
    
    def generate(
        self,
        topic: str,
        category: str,
        style: str = 'satirical',
        max_length: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Generate parody article content
        
        Args:
            topic: Main topic for the article
            category: Article category (politics, tech, etc.)
            style: Writing style (satirical, absurd, etc.)
            max_length: Maximum content length in tokens
        
        Returns:
            Dict containing title and content
        
        Raises:
            openai.OpenAIError: If generation fails
        """
        # Check cache first
        cache_key = f"parody_{topic}_{category}_{style}"
        cached_result = cache.get(cache_key)
        if cached_result:
            logger.info(f"Returning cached content for: {topic}")
            return cached_result
        
        # Build prompt
        prompt = self._build_prompt(topic, category, style)
        
        # Generate content
        try:
            response = openai.ChatCompletion.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a satirical news writer creating humorous parody articles."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_tokens=max_length or settings.OPENAI_MAX_TOKENS,
                temperature=settings.OPENAI_TEMPERATURE
            )
            
            content = response.choices[0].message.content
            
            # Parse title and content from response
            result = self._parse_response(content)
            
            # Cache the result
            cache.set(cache_key, result, self.cache_timeout)
            
            logger.info(f"Generated new content for: {topic}")
            return result
            
        except Exception as e:
            logger.exception(f"Content generation failed: {e}")
            raise
    
    def _build_prompt(self, topic: str, category: str, style: str) -> str:
        """Build generation prompt"""
        return f"""
Write a {style} parody news article about: {topic}

Category: {category}

Format:
TITLE: [Humorous headline]
CONTENT: [Article body, 3-5 paragraphs]

Make it funny, absurd, and clearly satirical.
"""
    
    def _parse_response(self, response: str) -> Dict[str, str]:
        """Parse OpenAI response into title and content"""
        lines = response.strip().split('\n')
        
        title = ""
        content_lines = []
        in_content = False
        
        for line in lines:
            if line.startswith('TITLE:'):
                title = line.replace('TITLE:', '').strip()
            elif line.startswith('CONTENT:'):
                in_content = True
                content_lines.append(line.replace('CONTENT:', '').strip())
            elif in_content and line.strip():
                content_lines.append(line)
        
        return {
            'title': title or 'Untitled Article',
            'content': '\n\n'.join(content_lines)
        }
```

### Frontend API Consumption

```javascript
/**
 * Article generation UI handler
 */
class ArticleGenerator {
    constructor() {
        this.form = document.getElementById('generation-form');
        this.resultContainer = document.getElementById('generation-result');
        this.init();
    }
    
    init() {
        if (!this.form) return;
        
        this.form.addEventListener('submit', (e) => {
            e.preventDefault();
            this.generate();
        });
    }
    
    async generate() {
        const topic = document.getElementById('id_topic').value;
        const category = document.getElementById('id_category').value;
        
        if (!topic) {
            this.showError('Please enter a topic');
            return;
        }
        
        this.setLoading(true);
        
        try {
            const result = await articleManager.generateArticle(
                `Generate a ${category} parody article about: ${topic}`
            );
            
            this.displayResult(result);
            
        } catch (error) {
            this.showError(error.message);
            
        } finally {
            this.setLoading(false);
        }
    }
    
    displayResult(result) {
        this.resultContainer.innerHTML = `
            <div class="card">
                <div class="card-header">
                    <h3>${result.title || 'Generated Article'}</h3>
                </div>
                <div class="card-body">
                    <p>${result.content}</p>
                </div>
                <div class="card-footer">
                    <button class="btn btn-primary" onclick="this.saveArticle(${JSON.stringify(result)})">
                        Save Article
                    </button>
                </div>
            </div>
        `;
    }
    
    setLoading(isLoading) {
        const button = this.form.querySelector('button[type="submit"]');
        button.disabled = isLoading;
        button.textContent = isLoading ? 'Generating...' : 'Generate';
    }
    
    showError(message) {
        this.resultContainer.innerHTML = `
            <div class="alert alert-danger">${message}</div>
        `;
    }
}
```

## Best Practices Summary

### Python/Django
1. Use Django's generic views when possible
2. Implement service layer for complex business logic
3. Use Django forms for validation
4. Leverage Django ORM features (select_related, prefetch_related)
5. Write comprehensive docstrings
6. Use Django's built-in authentication
7. Implement proper error handling and logging
8. Use Django migrations for all schema changes

### JavaScript
1. Use modern ES6+ syntax
2. Prefer async/await for asynchronous code
3. Implement proper error handling
4. Use const/let instead of var
5. Validate data before sending to server
6. Handle CSRF tokens correctly for Django
7. Provide user feedback for all async operations
8. Keep functions focused and small

### Bash
1. Always start with shebang and `set -euo pipefail`
2. Use functions for reusable logic
3. Provide comprehensive logging
4. Validate inputs and prerequisites
5. Use meaningful variable names with readonly for constants
6. Quote all variable expansions
7. Implement error handlers and cleanup
8. Document all scripts with headers

### General
1. Never commit secrets or API keys
2. Use environment variables for configuration
3. Document all public interfaces
4. Write tests for critical functionality
5. Keep functions focused on single responsibilities
6. Use descriptive names for clarity
7. Follow project conventions consistently
8. Review security implications of all changes

