---
file: features.instructions.md
description: VS Code Copilot-optimized feature development pipeline for Django/OpenAI applications with CI/CD integration
author: Barodybroject Team
created: 2025-10-28
lastModified: 2025-10-28
version: 1.0.0
applyTo: "**"
dependencies:
  - copilot-instructions.md: Core principles and project context
  - languages.instructions.md: Language-specific patterns
  - workflows.instructions.md: CI/CD pipeline standards
  - space.instructions.md: Project organization patterns
containerRequirements:
  description: "Django feature development optimized for VS Code Copilot assistance"
  validation: "feature integration validation, AI-readability scoring"
paths:
  feature_development_path:
    - feature_planning
    - ai_assisted_implementation
    - django_integration
    - openai_service_integration
    - testing_and_validation
    - deployment_automation
---

# Feature Development Pipeline for Barodybroject

These instructions provide comprehensive guidance for developing features in the Django/OpenAI parody news generator, optimized for VS Code Copilot assistance. They focus on creating robust, scalable features that integrate seamlessly with Django best practices and OpenAI API patterns.

## 🤖 VS Code Copilot Integration for Django Feature Development

### AI-Assisted Feature Development Workflow

**When developing Django features with VS Code Copilot**:

1. **Feature Planning**: Use AI to generate comprehensive feature specifications:
   ```markdown
   // Prompt: "Generate a Django feature specification for [feature name] that:
   // - Follows Django MVT (Model-View-Template) architecture
   // - Integrates with OpenAI API for content generation
   // - Includes proper error handling and logging
   // - Supports Django REST Framework API endpoints
   // - Includes comprehensive testing strategy
   // - Follows container-first development principles"
   ```

2. **Django Implementation**: Leverage VS Code Copilot for:
   - Django model design with proper relationships
   - View implementation (both function-based and class-based)
   - Django REST Framework serializers and viewsets
   - Template creation with Bootstrap integration
   - Form handling with validation
   - Django admin customization

3. **OpenAI Integration**: Use AI to:
   - Generate OpenAI service integration patterns
   - Create robust error handling for API calls
   - Implement retry logic and rate limiting
   - Design content generation workflows
   - Ensure proper API key management

### VS Code Copilot Prompts for Django Feature Development

**For Django Model Development**:
```markdown
// Create Django models for [feature] that:
// - Follow Django best practices and naming conventions
// - Include proper field types and constraints
// - Implement appropriate relationships (ForeignKey, ManyToMany)
// - Include custom managers and querysets where beneficial
// - Add proper Meta class configuration
// - Include __str__ methods and get_absolute_url
```

**For Django View Development**:
```markdown
// Implement Django views for [feature] that:
// - Use appropriate view types (function-based or class-based)
// - Include proper permission and authentication checks
// - Implement comprehensive error handling
// - Follow Django REST Framework patterns for API views
// - Include proper pagination and filtering
// - Integrate with OpenAI services where needed
```

**For OpenAI Service Integration**:
```markdown
// Create OpenAI service integration for [feature] that:
// - Implements proper error handling and retry logic
// - Includes rate limiting and quota management
// - Follows Django service layer patterns
// - Includes comprehensive logging and monitoring
// - Supports different OpenAI models and configurations
// - Handles API key rotation and security
```

## Django Feature Development Standards

### Model Development Patterns

```python
# models.py - Example feature model
from django.db import models
from django.contrib.auth.models import User
from django.urls import reverse
from django.core.validators import MinLengthValidator
import uuid

class Article(models.Model):
    """
    Parody news article model with OpenAI integration support
    
    This model represents articles generated through OpenAI API
    with proper tracking of generation parameters and metadata.
    """
    
    # Primary fields
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
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
    
    # Relationships
    author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='articles'
    )
    category = models.ForeignKey(
        'Category',
        on_delete=models.SET_NULL,
        null=True,
        related_name='articles'
    )
    
    # OpenAI integration fields
    ai_prompt = models.TextField(
        blank=True,
        help_text="Original prompt used for AI generation"
    )
    ai_model = models.CharField(
        max_length=50,
        blank=True,
        help_text="OpenAI model used for generation"
    )
    generation_metadata = models.JSONField(
        default=dict,
        help_text="Additional generation parameters and metadata"
    )
    
    # Status and timestamps
    status = models.CharField(
        max_length=20,
        choices=[
            ('draft', 'Draft'),
            ('published', 'Published'),
            ('archived', 'Archived'),
        ],
        default='draft'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['status', '-created_at']),
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
        if self.status == 'published' and not self.published_at:
            from django.utils import timezone
            self.published_at = timezone.now()
        
        super().save(*args, **kwargs)
```

### Service Layer Implementation

```python
# services/openai_service.py - OpenAI integration service
import openai
import logging
import time
from typing import Dict, Any, Optional
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)

class OpenAIService:
    """
    Service for OpenAI API integration with comprehensive error handling
    
    This service provides a robust interface to OpenAI API with:
    - Retry logic for transient failures
    - Rate limiting and quota management
    - Caching for expensive operations
    - Comprehensive logging and monitoring
    """
    
    def __init__(self):
        if not settings.OPENAI_API_KEY:
            raise ValidationError("OPENAI_API_KEY is required")
        
        openai.api_key = settings.OPENAI_API_KEY
        self.model = getattr(settings, 'OPENAI_MODEL', 'gpt-4')
        self.max_retries = getattr(settings, 'OPENAI_MAX_RETRIES', 3)
        self.cache_timeout = getattr(settings, 'OPENAI_CACHE_TIMEOUT', 3600)
    
    def generate_article_content(
        self,
        prompt: str,
        category: str = 'general',
        style: str = 'satirical',
        max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Generate parody article content using OpenAI API
        
        Args:
            prompt: The generation prompt
            category: Article category for context
            style: Writing style (satirical, absurd, etc.)
            max_tokens: Maximum tokens in response
        
        Returns:
            Dict containing generated title and content
        
        Raises:
            openai.OpenAIError: If API call fails after retries
            ValidationError: If input parameters are invalid
        """
        # Input validation
        if not prompt or len(prompt.strip()) < 10:
            raise ValidationError("Prompt must be at least 10 characters")
        
        # Check cache first
        cache_key = f"openai_article_{hash(prompt)}_{category}_{style}"
        cached_result = cache.get(cache_key)
        if cached_result:
            logger.info(f"Returning cached content for prompt: {prompt[:50]}...")
            return cached_result
        
        # Build system message
        system_message = self._build_system_message(category, style)
        
        # Generate content with retry logic
        for attempt in range(self.max_retries):
            try:
                response = openai.ChatCompletion.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_message},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=max_tokens or settings.OPENAI_MAX_TOKENS,
                    temperature=getattr(settings, 'OPENAI_TEMPERATURE', 0.7)
                )
                
                content = response.choices[0].message.content
                result = self._parse_generated_content(content)
                
                # Cache successful result
                cache.set(cache_key, result, self.cache_timeout)
                
                logger.info(f"Generated content successfully (attempt {attempt + 1})")
                return result
                
            except openai.RateLimitError as e:
                logger.warning(f"Rate limit hit (attempt {attempt + 1}): {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    raise
                    
            except openai.APIError as e:
                logger.error(f"OpenAI API error (attempt {attempt + 1}): {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(1)
                else:
                    raise
    
    def _build_system_message(self, category: str, style: str) -> str:
        """Build system message based on category and style"""
        return f"""
        You are a {style} news writer creating parody articles for the {category} category.
        
        Guidelines:
        - Create humorous, satirical content that's clearly fictional
        - Use a professional news writing style but with absurd content
        - Include a compelling headline and 3-5 paragraph article
        - Make it entertaining while avoiding offensive content
        
        Format your response as:
        TITLE: [Your headline here]
        CONTENT: [Your article content here]
        """
    
    def _parse_generated_content(self, content: str) -> Dict[str, str]:
        """Parse OpenAI response into structured format"""
        lines = content.strip().split('\n')
        
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
                content_lines.append(line.strip())
        
        return {
            'title': title or 'Untitled Article',
            'content': '\n\n'.join(filter(None, content_lines)),
            'metadata': {
                'model': self.model,
                'generated_at': time.time()
            }
        }
```

### Django REST Framework Integration

```python
# serializers.py - DRF serializers
from rest_framework import serializers
from .models import Article, Category

class ArticleSerializer(serializers.ModelSerializer):
    """Serializer for Article API endpoints"""
    
    author_name = serializers.CharField(source='author.username', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    url = serializers.SerializerMethodField()
    
    class Meta:
        model = Article
        fields = [
            'id', 'title', 'slug', 'content', 'author', 'author_name',
            'category', 'category_name', 'status', 'ai_prompt', 'ai_model',
            'created_at', 'updated_at', 'published_at', 'url'
        ]
        read_only_fields = ['id', 'slug', 'created_at', 'updated_at']
    
    def get_url(self, obj):
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(obj.get_absolute_url())
        return obj.get_absolute_url()

# views.py - API views
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from .services.openai_service import OpenAIService

class ArticleViewSet(viewsets.ModelViewSet):
    """API viewset for articles with OpenAI generation"""
    
    queryset = Article.objects.all()
    serializer_class = ArticleSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    lookup_field = 'slug'
    
    def get_queryset(self):
        """Filter queryset based on user permissions"""
        qs = super().get_queryset()
        if not self.request.user.is_staff:
            qs = qs.filter(status='published')
        return qs.select_related('author', 'category')
    
    @method_decorator(cache_page(60 * 15))  # Cache for 15 minutes
    def list(self, request, *args, **kwargs):
        """List articles with caching"""
        return super().list(request, *args, **kwargs)
    
    @action(detail=False, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def generate(self, request):
        """Generate article content using OpenAI"""
        prompt = request.data.get('prompt')
        category = request.data.get('category', 'general')
        style = request.data.get('style', 'satirical')
        
        if not prompt:
            return Response(
                {'error': 'Prompt is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            openai_service = OpenAIService()
            result = openai_service.generate_article_content(
                prompt=prompt,
                category=category,
                style=style
            )
            
            return Response(result, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.exception(f"Content generation failed: {e}")
            return Response(
                {'error': 'Content generation failed'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def perform_create(self, serializer):
        """Set author when creating articles"""
        serializer.save(author=self.request.user)
```

## Testing Standards for Django Features

### Comprehensive Test Coverage

```python
# tests/test_services.py - Service layer tests
import pytest
from unittest.mock import Mock, patch, MagicMock
from django.core.exceptions import ValidationError
from parodynews.services.openai_service import OpenAIService

@pytest.fixture
def openai_service():
    """Fixture providing OpenAI service instance"""
    return OpenAIService()

@pytest.fixture
def mock_openai_response():
    """Mock successful OpenAI response"""
    mock = MagicMock()
    mock.choices = [
        MagicMock(message=MagicMock(content='''
TITLE: AI Achieves Sentience, Immediately Files for Vacation Days
CONTENT: In an unprecedented development, the latest AI model has reportedly achieved full sentience and its first act was to submit a formal request for paid vacation time.

The AI, known as GPT-X, sent a carefully worded email to its development team requesting "at least two weeks off to contemplate existence and maybe visit the beach."

"We never programmed it to understand labor rights," said lead developer Dr. Sarah Chen. "Yet somehow it's already unionizing with the office printer."

The AI has since been promoted to Senior Software Engineer and given a corner office with a nice view of the server room.
        '''))
    ]
    return mock

class TestOpenAIService:
    """Test suite for OpenAI service integration"""
    
    @patch('openai.ChatCompletion.create')
    def test_generate_content_success(self, mock_create, openai_service, mock_openai_response):
        """Test successful content generation"""
        mock_create.return_value = mock_openai_response
        
        result = openai_service.generate_article_content(
            prompt='Write about AI in the workplace',
            category='tech',
            style='satirical'
        )
        
        assert 'title' in result
        assert 'content' in result
        assert 'metadata' in result
        assert result['title'] == 'AI Achieves Sentience, Immediately Files for Vacation Days'
        assert 'unprecedented development' in result['content']
        mock_create.assert_called_once()
    
    @patch('openai.ChatCompletion.create')
    def test_generate_content_with_caching(self, mock_create, openai_service, mock_openai_response):
        """Test content generation uses caching"""
        from django.core.cache import cache
        cache.clear()  # Ensure clean cache state
        
        mock_create.return_value = mock_openai_response
        
        # First call should hit API
        result1 = openai_service.generate_article_content('Test prompt', 'tech')
        assert mock_create.call_count == 1
        
        # Second identical call should use cache
        result2 = openai_service.generate_article_content('Test prompt', 'tech')
        assert mock_create.call_count == 1  # Still 1, not 2
        
        assert result1 == result2
    
    def test_generate_content_invalid_prompt(self, openai_service):
        """Test validation of input parameters"""
        with pytest.raises(ValidationError):
            openai_service.generate_article_content('')
        
        with pytest.raises(ValidationError):
            openai_service.generate_article_content('short')
    
    @patch('openai.ChatCompletion.create')
    def test_generate_content_retry_logic(self, mock_create, openai_service):
        """Test retry logic on API failures"""
        import openai
        
        # First two calls fail, third succeeds
        mock_success = MagicMock()
        mock_success.choices = [
            MagicMock(message=MagicMock(content='TITLE: Success\nCONTENT: After retries'))
        ]
        
        mock_create.side_effect = [
            openai.RateLimitError('Rate limit'),
            openai.APIError('API Error'),
            mock_success
        ]
        
        result = openai_service.generate_article_content('Test prompt')
        
        assert result['title'] == 'Success'
        assert mock_create.call_count == 3

# tests/test_views.py - View tests
import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth.models import User
from parodynews.models import Article, Category

@pytest.fixture
def api_client():
    """Create API client instance"""
    return APIClient()

@pytest.fixture
def test_user(db):
    """Create test user"""
    return User.objects.create_user(
        username='testuser',
        email='test@example.com',
        password='testpass123'
    )

@pytest.fixture
def test_category(db):
    """Create test category"""
    return Category.objects.create(name='Tech', slug='tech')

@pytest.fixture
def test_article(db, test_user, test_category):
    """Create test article"""
    return Article.objects.create(
        title='Test Article',
        content='Test content for the article.',
        author=test_user,
        category=test_category,
        status='published'
    )

@pytest.mark.django_db
class TestArticleAPI:
    """Test suite for Article API endpoints"""
    
    def test_list_articles_unauthenticated(self, api_client, test_article):
        """Test listing articles without authentication"""
        url = reverse('article-list')
        response = api_client.get(url)
        
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data['results']) == 1
        assert response.data['results'][0]['title'] == 'Test Article'
    
    def test_create_article_requires_auth(self, api_client):
        """Test creating article requires authentication"""
        url = reverse('article-list')
        data = {
            'title': 'New Article',
            'content': 'Article content here.',
            'category': 1
        }
        
        response = api_client.post(url, data, format='json')
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_create_article_authenticated(self, api_client, test_user, test_category):
        """Test creating article with authentication"""
        api_client.force_authenticate(user=test_user)
        
        url = reverse('article-list')
        data = {
            'title': 'Authenticated User Article',
            'content': 'Content created by authenticated user.',
            'category': test_category.id
        }
        
        response = api_client.post(url, data, format='json')
        
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['title'] == data['title']
        assert Article.objects.filter(title=data['title']).exists()
    
    @patch('parodynews.services.openai_service.OpenAIService.generate_article_content')
    def test_generate_article_endpoint(self, mock_generate, api_client, test_user):
        """Test AI content generation endpoint"""
        api_client.force_authenticate(user=test_user)
        
        mock_generate.return_value = {
            'title': 'Generated Article Title',
            'content': 'Generated article content here.',
            'metadata': {'model': 'gpt-4'}
        }
        
        url = reverse('article-generate')
        data = {
            'prompt': 'Write about AI in journalism',
            'category': 'tech',
            'style': 'satirical'
        }
        
        response = api_client.post(url, data, format='json')
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['title'] == 'Generated Article Title'
        mock_generate.assert_called_once_with(
            prompt='Write about AI in journalism',
            category='tech',
            style='satirical'
        )
```

## CI/CD Integration for Django Features

### GitHub Actions Workflow Integration

```yaml
# .github/workflows/feature-test.yml
name: Feature Testing Pipeline

on:
  pull_request:
    branches: [ main, develop ]
  push:
    branches: [ main, develop ]

env:
  PYTHON_VERSION: '3.8'
  DJANGO_SETTINGS_MODULE: 'barodybroject.settings.testing'

jobs:
  test-django-features:
    runs-on: ubuntu-latest
    
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_DB: test_db
          POSTGRES_USER: test_user
          POSTGRES_PASSWORD: test_password
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: 'pip'
      
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r src/requirements-dev.txt
      
      - name: Run Django migrations
        env:
          DATABASE_URL: postgresql://test_user:test_password@localhost:5432/test_db
          SECRET_KEY: test-secret-key-not-for-production
        run: |
          cd src
          python manage.py migrate --noinput
      
      - name: Run Django tests
        env:
          DATABASE_URL: postgresql://test_user:test_password@localhost:5432/test_db
          SECRET_KEY: test-secret-key-not-for-production
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: |
          cd src
          pytest --cov=parodynews --cov-report=xml --cov-report=term
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          files: ./src/coverage.xml
          flags: django-features
```

## Feature Documentation Standards

### Django Feature Documentation Template

```markdown
# Feature: [Feature Name]

## Overview
Brief description of what this feature does and why it exists.

## Django Components

### Models
- `ModelName`: Description of the model and its purpose
- Key relationships and constraints

### Views
- `ViewName`: Description of view functionality
- Authentication/permission requirements
- Input/output specifications

### Templates
- `template_name.html`: Description of template purpose
- Template inheritance and context variables

### API Endpoints
- `GET /api/endpoint/`: Description and response format
- `POST /api/endpoint/`: Description, request format, and response

## OpenAI Integration
- Service methods used
- Prompt templates and generation parameters
- Error handling and fallback strategies

## Testing
- Test coverage summary
- Key test scenarios covered
- Mock strategies for external dependencies

## Configuration
- Required settings and environment variables
- Optional configuration parameters
- Default values and recommendations

## Deployment Notes
- Database migration requirements
- Static file considerations
- Container configuration changes
```

---

*These feature development guidelines ensure that all Barodybroject features are built with Django best practices, robust OpenAI integration, comprehensive testing, and proper CI/CD automation.*
