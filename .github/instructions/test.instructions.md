---
file: test.instructions.md
description: VS Code Copilot-optimized testing standards and best practices for Django/OpenAI applications
author: Barodybroject Team
created: 2025-10-11
lastModified: 2025-10-28
version: 1.1.0
applyTo: "tests/**/*.py,**/*test*.py"
dependencies:
  - copilot-instructions.md: Core principles and VS Code Copilot integration
  - languages.instructions.md: Python testing patterns and standards
  - features.instructions.md: Feature development and testing integration
  - frontmatter.standards.md: Unified metadata and documentation standards
relatedEvolutions:
  - "Enhanced Django/OpenAI testing patterns"
  - "Container-based testing environments"
  - "AI service mocking and validation strategies"
containerRequirements:
  baseImage: python:3.8-slim
  description: "Django testing environment with PostgreSQL and OpenAI service mocking"
  exposedPorts:
    - 8000
  portDescription: "Django test server for integration testing"
  volumes:
    - "/app/tests:rw"
    - "/app/coverage:rw"
    - "/app/src:ro"
  environment:
    DJANGO_SETTINGS_MODULE: barodybroject.settings.testing
    DATABASE_URL: postgresql://test_user:test_password@db:5432/test_db
    OPENAI_API_KEY: mock-key-for-testing
  resources:
    cpu: "0.5-1.0"
    memory: "512MiB-1GiB"
  healthCheck: "pytest --version command validation"
paths:
  testing_workflow_path:
    - test_planning
    - unit_test_development
    - integration_test_creation
    - api_testing_validation
    - ui_testing_automation
    - coverage_analysis
    - ci_integration
changelog:
  - date: "2025-10-28"
    description: "Enhanced with VS Code Copilot optimization and comprehensive Django/OpenAI testing patterns"
    author: "Barodybroject Team"
  - date: "2025-10-11"
    description: "Initial creation with core testing standards"
    author: "Barodybroject Team"
usage: "Reference for all testing activities in Django/OpenAI applications including unit, integration, API, and UI testing"
notes: "Emphasizes Django testing best practices, OpenAI service mocking, container-based testing, and comprehensive coverage"
---

# Testing Standards

## Testing Philosophy

Testing ensures code quality, reliability, and maintainability. All new features should include appropriate tests.

### Testing Principles
- **Test Early**: Write tests as you develop features
- **Test Coverage**: Aim for >80% code coverage on critical components
- **Test Isolation**: Tests should not depend on each other
- **Test Clarity**: Tests should be self-documenting
- **Test Speed**: Keep unit tests fast; use fixtures efficiently

### Test Types

1. **Unit Tests**: Test individual functions and methods in isolation
2. **Integration Tests**: Test component interactions (views, models, forms)
3. **API Tests**: Test REST endpoints with various inputs
4. **UI Tests**: Test critical user flows with Playwright
5. **Performance Tests**: Test response times and database query efficiency

## Test Organization

```
tests/
├── __init__.py
├── conftest.py              # Shared pytest fixtures
├── unit/                    # Unit tests
│   ├── __init__.py
│   ├── test_models.py
│   ├── test_services.py
│   └── test_utils.py
├── integration/             # Integration tests
│   ├── __init__.py
│   ├── test_views.py
│   ├── test_forms.py
│   └── test_api.py
├── e2e/                     # End-to-end tests
│   ├── __init__.py
│   └── test_user_flows.py
├── fixtures/                # Test data
│   ├── articles.json
│   └── users.json
└── data/                    # Test input files
    └── sample_prompts.json
```

## Django Testing with Pytest

### Basic Test Structure

```python
# tests/unit/test_models.py
import pytest
from django.contrib.auth.models import User
from parodynews.models import Article

@pytest.mark.django_db
class TestArticleModel:
    """Test suite for Article model"""
    
    def test_article_creation(self):
        """Test creating an article"""
        user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        
        article = Article.objects.create(
            title='Test Article Title',
            content='Test article content goes here.',
            author=user,
            category='tech'
        )
        
        assert article.id is not None
        assert article.slug == 'test-article-title'
        assert str(article) == 'Test Article Title'
    
    def test_article_str_representation(self):
        """Test article string representation"""
        user = User.objects.create_user(username='author')
        article = Article.objects.create(
            title='My Article',
            content='Content',
            author=user
        )
        
        assert str(article) == 'My Article'
    
    def test_article_get_absolute_url(self):
        """Test article URL generation"""
        user = User.objects.create_user(username='author')
        article = Article.objects.create(
            title='My Article',
            slug='my-article',
            content='Content',
            author=user
        )
        
        assert article.get_absolute_url() == '/articles/my-article/'
```

### Using Fixtures

```python
# tests/conftest.py
import pytest
from django.contrib.auth.models import User
from parodynews.models import Article, Category

@pytest.fixture
def test_user():
    """Create a test user"""
    return User.objects.create_user(
        username='testuser',
        email='test@example.com',
        password='testpass123'
    )

@pytest.fixture
def test_article(test_user):
    """Create a test article"""
    return Article.objects.create(
        title='Test Article',
        content='Test content for article.',
        author=test_user,
        category='tech',
        is_published=True
    )

@pytest.fixture
def multiple_articles(test_user):
    """Create multiple test articles"""
    articles = []
    for i in range(5):
        article = Article.objects.create(
            title=f'Article {i}',
            content=f'Content for article {i}',
            author=test_user,
            category='tech' if i % 2 == 0 else 'politics',
            is_published=i % 3 != 0
        )
        articles.append(article)
    return articles

# Usage in tests
@pytest.mark.django_db
def test_published_articles_query(multiple_articles):
    """Test filtering published articles"""
    published = Article.objects.filter(is_published=True)
    
    # Should exclude articles where i % 3 == 0 (indices 0, 3)
    assert published.count() == 3
```

### Testing Views

```python
# tests/integration/test_views.py
import pytest
from django.urls import reverse
from django.test import Client
from parodynews.models import Article

@pytest.mark.django_db
class TestArticleViews:
    """Test suite for article views"""
    
    def test_article_list_view(self, client, multiple_articles):
        """Test article list displays published articles"""
        url = reverse('article-list')
        response = client.get(url)
        
        assert response.status_code == 200
        assert 'articles' in response.context
        
        # Should only show published articles
        articles = response.context['articles']
        assert all(article.is_published for article in articles)
    
    def test_article_detail_view(self, client, test_article):
        """Test article detail view"""
        url = reverse('article-detail', kwargs={'slug': test_article.slug})
        response = client.get(url)
        
        assert response.status_code == 200
        assert response.context['article'] == test_article
        assert test_article.title in response.content.decode()
    
    def test_article_create_view_requires_login(self, client):
        """Test article creation requires authentication"""
        url = reverse('article-create')
        response = client.get(url)
        
        # Should redirect to login
        assert response.status_code == 302
        assert '/accounts/login/' in response.url
    
    def test_article_create_view_authenticated(self, client, test_user):
        """Test article creation with authenticated user"""
        client.force_login(test_user)
        
        url = reverse('article-create')
        response = client.get(url)
        
        assert response.status_code == 200
        assert 'form' in response.context
```

### Testing Forms

```python
# tests/integration/test_forms.py
import pytest
from parodynews.forms import ArticleForm
from parodynews.models import Article

@pytest.mark.django_db
class TestArticleForm:
    """Test suite for article forms"""
    
    def test_valid_form(self, test_user):
        """Test form with valid data"""
        form_data = {
            'title': 'Valid Article Title',
            'content': 'This is valid article content that meets minimum length requirements.',
            'category': 'tech',
            'is_published': False
        }
        
        form = ArticleForm(data=form_data)
        assert form.is_valid()
    
    def test_form_missing_required_fields(self):
        """Test form validation with missing required fields"""
        form = ArticleForm(data={})
        
        assert not form.is_valid()
        assert 'title' in form.errors
        assert 'content' in form.errors
    
    def test_form_title_too_short(self):
        """Test form validation for minimum title length"""
        form_data = {
            'title': 'Short',  # Less than 10 characters
            'content': 'Valid content that is long enough.',
            'category': 'tech'
        }
        
        form = ArticleForm(data=form_data)
        assert not form.is_valid()
        assert 'title' in form.errors
    
    def test_form_duplicate_title(self, test_article):
        """Test form prevents duplicate titles"""
        form_data = {
            'title': test_article.title,  # Duplicate title
            'content': 'Different content',
            'category': 'tech'
        }
        
        form = ArticleForm(data=form_data)
        assert not form.is_valid()
        assert 'title' in form.errors
```

## API Testing

### REST API Tests

```python
# tests/integration/test_api.py
import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from parodynews.models import Article

@pytest.fixture
def api_client():
    """Create API client instance"""
    return APIClient()

@pytest.mark.django_db
class TestArticleAPI:
    """Test suite for Article API endpoints"""
    
    def test_list_articles(self, api_client, multiple_articles):
        """Test GET /api/articles/"""
        url = reverse('article-list')
        response = api_client.get(url)
        
        assert response.status_code == status.HTTP_200_OK
        assert 'results' in response.data or isinstance(response.data, list)
    
    def test_get_article_detail(self, api_client, test_article):
        """Test GET /api/articles/{slug}/"""
        url = reverse('article-detail', kwargs={'slug': test_article.slug})
        response = api_client.get(url)
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['title'] == test_article.title
        assert response.data['slug'] == test_article.slug
    
    def test_create_article_requires_authentication(self, api_client):
        """Test POST /api/articles/ requires auth"""
        url = reverse('article-list')
        data = {
            'title': 'New Article',
            'content': 'Article content',
            'category': 'tech'
        }
        
        response = api_client.post(url, data, format='json')
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_create_article_authenticated(self, api_client, test_user):
        """Test POST /api/articles/ with authentication"""
        api_client.force_authenticate(user=test_user)
        
        url = reverse('article-list')
        data = {
            'title': 'New Authenticated Article',
            'content': 'This article is created by authenticated user.',
            'category': 'politics'
        }
        
        response = api_client.post(url, data, format='json')
        
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['title'] == data['title']
        
        # Verify article was created in database
        assert Article.objects.filter(title=data['title']).exists()
```

### Testing OpenAI Integration

```python
# tests/unit/test_services.py
import pytest
from unittest.mock import Mock, patch, MagicMock
from parodynews.services.openai_service import OpenAIService

class TestOpenAIService:
    """Test suite for OpenAI service"""
    
    @patch('openai.ChatCompletion.create')
    def test_generate_content_success(self, mock_create):
        """Test successful content generation"""
        # Mock OpenAI response
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content='Generated parody content'))
        ]
        mock_create.return_value = mock_response
        
        service = OpenAIService()
        result = service.generate_parody_content('Test prompt')
        
        assert result == 'Generated parody content'
        mock_create.assert_called_once()
    
    @patch('openai.ChatCompletion.create')
    def test_generate_content_retry_on_rate_limit(self, mock_create):
        """Test retry logic on rate limit error"""
        import openai
        
        # First call fails with rate limit, second succeeds
        mock_success = MagicMock()
        mock_success.choices = [
            MagicMock(message=MagicMock(content='Success after retry'))
        ]
        
        mock_create.side_effect = [
            openai.RateLimitError('Rate limit exceeded'),
            mock_success
        ]
        
        service = OpenAIService()
        result = service.generate_parody_content('Test prompt')
        
        assert result == 'Success after retry'
        assert mock_create.call_count == 2
    
    @patch('openai.ChatCompletion.create')
    def test_generate_content_failure_after_retries(self, mock_create):
        """Test failure after max retries"""
        import openai
        
        # All attempts fail
        mock_create.side_effect = openai.APIError('API Error')
        
        service = OpenAIService()
        
        with pytest.raises(openai.APIError):
            service.generate_parody_content('Test prompt')
        
        assert mock_create.call_count == 3  # max_retries
```

## Container-Based Testing

### Docker Compose for Testing

```yaml
# docker-compose.test.yml
version: '3.8'

services:
  test-db:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: test_db
      POSTGRES_USER: test_user
      POSTGRES_PASSWORD: test_password
    ports:
      - "5433:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U test_user"]
      interval: 10s
      timeout: 5s
      retries: 5

  test-runner:
    build:
      context: .
      dockerfile: Dockerfile
      target: development
    environment:
      - DATABASE_URL=postgresql://test_user:test_password@test-db:5432/test_db
      - SECRET_KEY=test-secret-key-not-for-production
      - DJANGO_SETTINGS_MODULE=barodybroject.settings
    depends_on:
      test-db:
        condition: service_healthy
    volumes:
      - ./src:/app/src:ro
      - ./tests:/app/tests:ro
      - ./coverage:/app/coverage:rw
    command: pytest tests/ --cov=parodynews --cov-report=html:/app/coverage/
```

### Running Tests in Containers

```bash
#!/bin/bash
# scripts/run-tests.sh
# Run test suite in Docker container

set -euo pipefail

echo "Starting test environment..."
docker-compose -f docker-compose.test.yml up -d test-db

echo "Waiting for database to be ready..."
sleep 5

echo "Running tests..."
docker-compose -f docker-compose.test.yml run --rm test-runner

echo "Collecting coverage report..."
docker-compose -f docker-compose.test.yml down
```

## Pytest Configuration

### pytest.ini

```ini
# pytest.ini
[pytest]
DJANGO_SETTINGS_MODULE = barodybroject.settings
python_files = test_*.py
python_classes = Test*
python_functions = test_*
testpaths = tests
addopts = 
    --verbose
    --strict-markers
    --cov=parodynews
    --cov-report=html
    --cov-report=term-missing
    --cov-fail-under=80
markers =
    slow: marks tests as slow (deselect with '-m "not slow"')
    integration: marks tests as integration tests
    api: marks tests as API tests
    ui: marks tests as UI tests
```

### Conftest.py Setup

```python
# tests/conftest.py
import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

@pytest.fixture(scope='session')
def django_db_setup(django_db_setup, django_db_blocker):
    """Set up test database"""
    with django_db_blocker.unblock():
        # Run any initial database setup here
        pass

@pytest.fixture
def api_client():
    """Create DRF API client"""
    return APIClient()

@pytest.fixture
def authenticated_client(api_client, test_user):
    """Create authenticated API client"""
    api_client.force_authenticate(user=test_user)
    return api_client

@pytest.fixture
def test_user(db):
    """Create test user"""
    return User.objects.create_user(
        username='testuser',
        email='test@example.com',
        password='testpass123'
    )

@pytest.fixture
def staff_user(db):
    """Create staff user"""
    return User.objects.create_user(
        username='staffuser',
        email='staff@example.com',
        password='staffpass123',
        is_staff=True
    )
```

## Testing Django Components

### Testing Models

```python
# tests/unit/test_models.py
import pytest
from django.core.exceptions import ValidationError
from django.utils.text import slugify
from parodynews.models import Article

@pytest.mark.django_db
class TestArticleModel:
    """Test Article model functionality"""
    
    def test_slug_auto_generation(self, test_user):
        """Test slug is automatically generated from title"""
        article = Article.objects.create(
            title='My Test Article Title',
            content='Article content',
            author=test_user
        )
        
        assert article.slug == 'my-test-article-title'
    
    def test_published_at_set_on_publish(self, test_user):
        """Test published_at is set when article is published"""
        article = Article.objects.create(
            title='Unpublished Article',
            content='Content',
            author=test_user,
            is_published=False
        )
        
        assert article.published_at is None
        
        # Publish the article
        article.is_published = True
        article.save()
        
        assert article.published_at is not None
    
    def test_article_ordering(self, test_user):
        """Test articles are ordered by publication date"""
        # Create articles with different publish dates
        old_article = Article.objects.create(
            title='Old Article',
            content='Content',
            author=test_user,
            is_published=True
        )
        
        new_article = Article.objects.create(
            title='New Article',
            content='Content',
            author=test_user,
            is_published=True
        )
        
        articles = Article.objects.all()
        
        # New article should come first
        assert articles[0] == new_article
        assert articles[1] == old_article
```

### Testing Views with RequestFactory

```python
# tests/integration/test_views.py
import pytest
from django.test import RequestFactory
from django.contrib.auth.models import AnonymousUser
from parodynews.views import ArticleListView, ArticleDetailView

@pytest.mark.django_db
class TestArticleViews:
    """Test article views"""
    
    @pytest.fixture
    def factory(self):
        return RequestFactory()
    
    def test_article_list_view(self, factory, multiple_articles):
        """Test article list view"""
        request = factory.get('/articles/')
        request.user = AnonymousUser()
        
        view = ArticleListView.as_view()
        response = view(request)
        
        assert response.status_code == 200
    
    def test_article_detail_view(self, factory, test_article):
        """Test article detail view"""
        request = factory.get(f'/articles/{test_article.slug}/')
        request.user = AnonymousUser()
        
        view = ArticleDetailView.as_view()
        response = view(request, slug=test_article.slug)
        
        assert response.status_code == 200
        assert response.context_data['article'] == test_article
```

### Testing API Endpoints

```python
# tests/integration/test_api.py
import pytest
from django.urls import reverse
from rest_framework import status
from parodynews.models import Article

@pytest.mark.django_db
class TestArticleAPI:
    """Test Article API endpoints"""
    
    def test_list_articles_unauthenticated(self, api_client, multiple_articles):
        """Test listing articles without authentication"""
        url = reverse('article-list')
        response = api_client.get(url)
        
        assert response.status_code == status.HTTP_200_OK
        # Should only return published articles
        assert all(article['is_published'] for article in response.data['results'])
    
    def test_create_article_requires_auth(self, api_client):
        """Test creating article requires authentication"""
        url = reverse('article-list')
        data = {
            'title': 'New Article',
            'content': 'Article content',
            'category': 'tech'
        }
        
        response = api_client.post(url, data, format='json')
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_create_article_authenticated(self, authenticated_client):
        """Test creating article with authentication"""
        url = reverse('article-list')
        data = {
            'title': 'Authenticated User Article',
            'content': 'Content created by authenticated user.',
            'category': 'politics'
        }
        
        response = authenticated_client.post(url, data, format='json')
        
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['title'] == data['title']
        assert Article.objects.filter(title=data['title']).exists()
    
    def test_update_article_permissions(self, authenticated_client, test_user):
        """Test only article author can update"""
        # Create article by test_user
        article = Article.objects.create(
            title='Original Title',
            content='Original content',
            author=test_user,
            category='tech'
        )
        
        url = reverse('article-detail', kwargs={'slug': article.slug})
        data = {'title': 'Updated Title'}
        
        response = authenticated_client.patch(url, data, format='json')
        assert response.status_code == status.HTTP_200_OK
        
        article.refresh_from_db()
        assert article.title == 'Updated Title'
```

## UI Testing with Playwright

### Basic Playwright Tests

```python
# tests/e2e/test_user_flows.py
import pytest
from playwright.sync_api import Page, expect

@pytest.fixture(scope='session')
def browser_context_args(browser_context_args):
    """Configure browser context"""
    return {
        **browser_context_args,
        'viewport': {'width': 1280, 'height': 720},
    }

def test_homepage_loads(page: Page, live_server):
    """Test homepage loads successfully"""
    page.goto(f'{live_server.url}/')
    
    expect(page).to_have_title('Parody News')
    expect(page.locator('h1')).to_contain_text('Welcome')

def test_user_login_flow(page: Page, live_server, test_user):
    """Test user can log in"""
    page.goto(f'{live_server.url}/accounts/login/')
    
    # Fill in login form
    page.fill('input[name="username"]', 'testuser')
    page.fill('input[name="password"]', 'testpass123')
    page.click('button[type="submit"]')
    
    # Should redirect to home and show user menu
    expect(page).to_have_url(f'{live_server.url}/')
    expect(page.locator('.user-menu')).to_be_visible()

def test_create_article_flow(page: Page, live_server, test_user):
    """Test creating an article through UI"""
    # Login first
    page.goto(f'{live_server.url}/accounts/login/')
    page.fill('input[name="username"]', 'testuser')
    page.fill('input[name="password"]', 'testpass123')
    page.click('button[type="submit"]')
    
    # Navigate to create article
    page.goto(f'{live_server.url}/articles/create/')
    
    # Fill in article form
    page.fill('input[name="title"]', 'Test Article via UI')
    page.fill('textarea[name="content"]', 'This is test content created through the UI.')
    page.select_option('select[name="category"]', 'tech')
    
    # Submit form
    page.click('button[type="submit"]')
    
    # Should redirect to article detail
    expect(page.locator('h1')).to_contain_text('Test Article via UI')
```

## Test Data Management

### Using Factory Boy

```python
# tests/factories.py
import factory
from django.contrib.auth.models import User
from parodynews.models import Article

class UserFactory(factory.django.DjangoModelFactory):
    """Factory for creating test users"""
    
    class Meta:
        model = User
    
    username = factory.Sequence(lambda n: f'user{n}')
    email = factory.LazyAttribute(lambda obj: f'{obj.username}@example.com')
    first_name = factory.Faker('first_name')
    last_name = factory.Faker('last_name')

class ArticleFactory(factory.django.DjangoModelFactory):
    """Factory for creating test articles"""
    
    class Meta:
        model = Article
    
    title = factory.Faker('sentence', nb_words=6)
    slug = factory.LazyAttribute(lambda obj: slugify(obj.title))
    content = factory.Faker('paragraphs', nb=3)
    author = factory.SubFactory(UserFactory)
    category = factory.Iterator(['politics', 'tech', 'sports', 'entertainment'])
    is_published = True

# Usage in tests
@pytest.mark.django_db
def test_with_factories():
    """Test using factory-created objects"""
    # Create 5 articles with random data
    articles = ArticleFactory.create_batch(5)
    
    assert Article.objects.count() == 5
    assert all(article.is_published for article in articles)
```

### JSON Fixtures

```json
// tests/fixtures/articles.json
[
  {
    "model": "parodynews.article",
    "pk": 1,
    "fields": {
      "title": "Test Article 1",
      "slug": "test-article-1",
      "content": "Test content for article 1",
      "category": "tech",
      "is_published": true,
      "author": 1
    }
  },
  {
    "model": "parodynews.article",
    "pk": 2,
    "fields": {
      "title": "Test Article 2",
      "slug": "test-article-2",
      "content": "Test content for article 2",
      "category": "politics",
      "is_published": false,
      "author": 1
    }
  }
]
```

```python
# Load fixtures in tests
@pytest.mark.django_db
def test_with_fixtures(django_db_setup, django_db_blocker):
    """Test using JSON fixtures"""
    from django.core.management import call_command
    
    with django_db_blocker.unblock():
        call_command('loaddata', 'tests/fixtures/articles.json')
    
    assert Article.objects.count() == 2
```

## Coverage and Reporting

### Coverage Configuration

```ini
# .coveragerc
[run]
source = src/parodynews
omit =
    */tests/*
    */migrations/*
    */admin.py
    */apps.py
    */__init__.py

[report]
precision = 2
show_missing = True
skip_covered = False

[html]
directory = coverage_html
```

### Running Coverage

```bash
# Run tests with coverage
pytest --cov=parodynews --cov-report=html --cov-report=term

# Generate coverage report
coverage run -m pytest
coverage report
coverage html

# View HTML report
open htmlcov/index.html
```

## Performance Testing

### Database Query Testing

```python
# tests/integration/test_performance.py
import pytest
from django.test.utils import override_settings
from django.db import connection
from django.test.utils import CaptureQueriesContext

@pytest.mark.django_db
def test_article_list_query_count(client, multiple_articles):
    """Test article list doesn't cause N+1 queries"""
    url = reverse('article-list')
    
    with CaptureQueriesContext(connection) as queries:
        response = client.get(url)
    
    assert response.status_code == 200
    
    # Should use select_related/prefetch_related to minimize queries
    # Adjust threshold based on your implementation
    assert len(queries) <= 5, f"Too many queries: {len(queries)}"

@pytest.mark.django_db
def test_api_response_time(api_client, multiple_articles):
    """Test API response time is acceptable"""
    import time
    
    url = reverse('article-list')
    
    start = time.time()
    response = api_client.get(url)
    elapsed = time.time() - start
    
    assert response.status_code == 200
    assert elapsed < 1.0, f"Response too slow: {elapsed}s"
```

## Mocking External Services

### Mocking OpenAI API

```python
# tests/unit/test_openai_integration.py
import pytest
from unittest.mock import patch, Mock
from parodynews.services.content_generator import ContentGenerator

@pytest.fixture
def mock_openai_response():
    """Mock successful OpenAI response"""
    mock = Mock()
    mock.choices = [
        Mock(message=Mock(content='''
TITLE: AI Achieves Sentience, Immediately Files for Vacation Days
CONTENT: In an unprecedented development, the latest AI model...
        '''))
    ]
    return mock

@pytest.mark.django_db
class TestContentGenerator:
    """Test content generation service"""
    
    @patch('openai.ChatCompletion.create')
    def test_generate_with_caching(self, mock_create, mock_openai_response):
        """Test content generation uses caching"""
        from django.core.cache import cache
        
        mock_create.return_value = mock_openai_response
        
        generator = ContentGenerator()
        
        # First call should hit API
        result1 = generator.generate('AI news', 'tech')
        assert mock_create.call_count == 1
        
        # Second identical call should use cache
        result2 = generator.generate('AI news', 'tech')
        assert mock_create.call_count == 1  # Still 1, not 2
        
        assert result1 == result2
    
    @patch('openai.ChatCompletion.create')
    def test_parse_response_format(self, mock_create, mock_openai_response):
        """Test response parsing handles expected format"""
        mock_create.return_value = mock_openai_response
        
        generator = ContentGenerator()
        result = generator.generate('test topic', 'tech')
        
        assert 'title' in result
        assert 'content' in result
        assert result['title'] == 'AI Achieves Sentience, Immediately Files for Vacation Days'
        assert 'unprecedented development' in result['content']
```

### Mocking HTTP Requests

```python
# tests/unit/test_api_client.py
import pytest
from unittest.mock import Mock, patch
import requests

@patch('requests.Session.get')
def test_api_client_get_success(mock_get):
    """Test successful API GET request"""
    from utils.api_client import APIClient
    
    # Mock successful response
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {'data': 'test'}
    mock_get.return_value = mock_response
    
    client = APIClient('https://api.example.com')
    result = client.get('/endpoint')
    
    assert result == {'data': 'test'}
    mock_get.assert_called_once()

@patch('requests.Session.get')
def test_api_client_retry_logic(mock_get):
    """Test API client retries on failure"""
    from utils.api_client import APIClient
    
    # First call fails, second succeeds
    mock_fail = Mock()
    mock_fail.status_code = 500
    mock_fail.raise_for_status.side_effect = requests.exceptions.HTTPError()
    
    mock_success = Mock()
    mock_success.status_code = 200
    mock_success.json.return_value = {'data': 'success'}
    
    mock_get.side_effect = [mock_fail, mock_success]
    
    client = APIClient('https://api.example.com')
    result = client.get('/endpoint')
    
    assert result == {'data': 'success'}
    assert mock_get.call_count == 2
```

## Test Best Practices

### Test Naming
- Use descriptive names that explain what is being tested
- Format: `test_<component>_<scenario>_<expected_result>`
- Examples:
  - `test_article_creation_requires_authentication`
  - `test_api_returns_404_for_missing_article`
  - `test_form_validation_rejects_short_title`

### Test Structure (Arrange-Act-Assert)

```python
def test_example():
    # Arrange: Set up test data and conditions
    user = User.objects.create_user(username='test')
    article = Article.objects.create(
        title='Test',
        content='Content',
        author=user
    )
    
    # Act: Perform the action being tested
    result = article.get_absolute_url()
    
    # Assert: Verify expected outcome
    assert result == f'/articles/{article.slug}/'
```

### Parametrized Tests

```python
@pytest.mark.parametrize('category,expected_count', [
    ('tech', 2),
    ('politics', 3),
    ('sports', 0),
])
@pytest.mark.django_db
def test_filter_by_category(category, expected_count, multiple_articles):
    """Test filtering articles by category"""
    articles = Article.objects.filter(category=category)
    assert articles.count() == expected_count
```

### Testing Async Code

```python
import pytest
import asyncio

@pytest.mark.asyncio
async def test_async_operation():
    """Test asynchronous function"""
    async def fetch_data():
        await asyncio.sleep(0.1)
        return {'data': 'value'}
    
    result = await fetch_data()
    assert result == {'data': 'value'}
```

## Continuous Testing

### Pre-commit Hooks

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.4.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
  
  - repo: https://github.com/psf/black
    rev: 23.3.0
    hooks:
      - id: black
        language_version: python3.8
  
  - repo: https://github.com/PyCQA/flake8
    rev: 6.0.0
    hooks:
      - id: flake8
        args: ['--max-line-length=100']
```

### Running Tests Locally

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/unit/test_models.py

# Run specific test class
pytest tests/unit/test_models.py::TestArticleModel

# Run specific test
pytest tests/unit/test_models.py::TestArticleModel::test_slug_generation

# Run with coverage
pytest --cov=parodynews --cov-report=html

# Run only fast tests (skip slow ones)
pytest -m "not slow"

# Run with verbose output
pytest -v

# Run with print output
pytest -s
```

## Testing Checklist

Before submitting code, ensure:

- [ ] All new code has corresponding tests
- [ ] Tests are isolated and don't depend on each other
- [ ] Tests use appropriate fixtures and factories
- [ ] External APIs are properly mocked
- [ ] Test names are descriptive
- [ ] Coverage meets minimum threshold (80%)
- [ ] Tests pass locally before pushing
- [ ] Integration tests cover critical workflows
- [ ] Error cases are tested
- [ ] Edge cases are considered

## Common Testing Patterns

### Testing Validation

```python
@pytest.mark.django_db
def test_article_validation():
    """Test model validation"""
    article = Article(
        title='A',  # Too short
        content='Short',  # Too short
        category='invalid'  # Invalid choice
    )
    
    with pytest.raises(ValidationError):
        article.full_clean()
```

### Testing Signals

```python
from django.db.models.signals import post_save
from django.dispatch import receiver

@pytest.mark.django_db
def test_article_signal_handler(test_user):
    """Test signal is triggered on article creation"""
    signal_called = []
    
    @receiver(post_save, sender=Article)
    def test_signal(sender, instance, created, **kwargs):
        if created:
            signal_called.append(instance)
    
    article = Article.objects.create(
        title='Test',
        content='Content',
        author=test_user
    )
    
    assert len(signal_called) == 1
    assert signal_called[0] == article
```

### Testing Middleware

```python
@pytest.mark.django_db
def test_custom_middleware(client, test_user):
    """Test custom middleware behavior"""
    response = client.get('/')
    
    # Check middleware added custom header
    assert 'X-Custom-Header' in response
```
