---
applyTo: '**/*.md,**/*.rst,docs/**/*.md,docs/**/*.rst'
---

# Documentation Standards

Documentation standards for README files, code comments, and technical writing. Universal patterns for documentation across web applications, libraries, educational content, and enterprise systems.

## README Requirements

Every directory should have a `README.md` that includes:

### Basic Structure

```markdown
# Directory Name

## Purpose
Brief description of what this directory contains and its role.

## Contents
- `file1.ext`: Description
- `file2.ext`: Description
- `subdirectory/`: Description

## Usage
Examples of how to use or interact with the contents.

## Related Resources
Links to related documentation or resources.
```

## Markdown Formatting

### Headings

- Use only ONE H1 per document (the title)
- Don't skip heading levels (H2 → H4 is invalid)
- Keep headings concise and descriptive

### Code Blocks

Always specify the language:

```markdown
\`\`\`python
def example():
    pass
\`\`\`

\`\`\`bash
echo "Hello, World!"
\`\`\`
```

### Links

```markdown
[Internal Link](./relative/path.md)
[External Link](https://example.com)
[Anchor Link](#section-name)
```

### Tables

```markdown
| Feature | Status | Notes |
|---------|--------|-------|
| Feature 1 | ✅ | Working |
| Feature 2 | 🔄 | In progress |
```

## Code Documentation

### Python Docstrings

Use Google-style docstrings:

```python
def process_data(data: dict, options: dict = None) -> dict:
    """
    Process input data with optional configuration.
    
    Args:
        data: Input data dictionary
        options: Optional processing configuration
    
    Returns:
        Processed data dictionary
    
    Raises:
        ValueError: If data is invalid
    
    Example:
        >>> result = process_data({"key": "value"})
        >>> print(result["processed"])
        True
    """
    pass
```

### JavaScript Documentation (JSDoc)

```javascript
/**
 * Process data with optional configuration
 * 
 * @param {Object} data - Input data object
 * @param {Object} [options] - Optional configuration
 * @returns {Promise<Object>} Processed data
 * @throws {Error} If data is invalid
 * 
 * @example
 * const result = await processData({key: 'value'});
 */
async function processData(data, options = {}) {
    // Implementation
}
```

## API Documentation

### Endpoint Documentation

```markdown
## POST /api/endpoint

Description of what this endpoint does.

### Request
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

**Body:**
\`\`\`json
{
  "key": "value"
}
\`\`\`

### Response
**Success (200):**
\`\`\`json
{
  "status": "success",
  "data": {}
}
\`\`\`

**Error (400):**
\`\`\`json
{
  "error": "Invalid input",
  "code": "INVALID_INPUT"
}
\`\`\`
```

## Changelog Format

```markdown
# Changelog

All notable changes will be documented in this file.

## [Unreleased]

### Added
- New features

### Changed
- Changes to existing functionality

### Fixed
- Bug fixes

## [1.0.0] - 2025-01-27

### Added
- Initial release
```

## Documentation Philosophy

Good documentation should be:

- **Clear and Concise**: Easy to understand for the target audience
- **Accurate**: Reflects current implementation
- **Maintainable**: Updated alongside code changes
- **Accessible**: Works with screen readers and assistive technologies
- **Discoverable**: Well-organized with good navigation
- **Practical**: Includes working examples and use cases

## Documentation Types

### README Files

**Project-Level README Template:**

```markdown
# Project Name

Brief one-sentence description of what the project does.

## Features

- Feature 1: Description
- Feature 2: Description
- Feature 3: Description

## Installation

### Prerequisites
- Requirement 1
- Requirement 2

### Quick Start

\`\`\`bash
# Clone and setup
git clone https://github.com/user/repo.git
cd repo
npm install  # or pip install -r requirements.txt

# Run
npm start    # or python app.py
\`\`\`

## Usage

### Basic Usage

\`\`\`language
# Example usage
example_code_here
\`\`\`

### Configuration

[Configuration options and examples]

## Documentation

[Links to comprehensive docs]

## Contributing

[How to contribute]

## License

[License information]
```

**Directory-Level README Template:**

```markdown
# Directory Name

## Purpose
What this directory contains and its role in the project.

## Contents

### Files
- `file1.ext`: Description of what this file does
- `file2.ext`: Description of what this file does

### Subdirectories
- `subdirectory/`: Description of subdirectory contents

## Usage

[Examples of how to use or interact with the directory contents]

## Related Resources
- [Link to related documentation]
- [Link to related directories]
```

### Inline Code Comments

**Python Comment Guidelines:**

```python
# Good: Explain WHY, not WHAT
user_count = User.objects.filter(is_active=True).count()
# Cache count to avoid repeated DB queries in loop
cache.set('active_user_count', user_count, 300)

# Bad: Obvious comments
user_count = User.objects.count()  # Get user count

# Good: Document non-obvious design decisions
# Using exponential backoff for API retries to handle rate limits
for attempt in range(max_retries):
    try:
        response = api_call()
        break
    except RateLimitError:
        time.sleep(2 ** attempt)

# Good: Explain complex algorithms
# Boyer-Moore string search for O(n/m) average performance
def boyer_moore_search(text, pattern):
    # Preprocessing: build bad character table
    # This allows skipping multiple characters on mismatch
    ...
```

### Educational Content Documentation

For tutorials, guides, and learning resources:

```markdown
## Tutorial: [Topic Name]

### Learning Objectives

By the end of this tutorial, you will:
- [ ] Understand [concept 1]
- [ ] Be able to [skill 1]
- [ ] Know how to [task 1]

### Prerequisites

**Knowledge:**
- Understanding of [prerequisite topic]

**System Setup:**
- [Tool] installed and configured
- Access to [resource]

### Step-by-Step Guide

#### Step 1: [Action Name]

**Objective**: What this step accomplishes

**Implementation**:
\`\`\`language
# Code with educational comments
code_example_here  # Explain what this line does and why
\`\`\`

**Expected Result**: What you should see/experience

**Troubleshooting**: Common issues and solutions

### Validation

Test your understanding:
1. Can you explain [concept] in your own words?
2. What would happen if you changed [parameter]?
3. How does this relate to [other concept]?

### Next Steps

- [Advanced topic to explore]
- [Related skill to learn]
```

## Documentation Best Practices

### When to Document

- Public APIs and interfaces
- Complex algorithms or business logic
- Configuration options and environment variables
- Error conditions and handling approaches
- Setup and installation procedures
- Architectural decisions and trade-offs
- Security considerations
- Performance optimizations

### What to Document

- **Purpose**: What it does and why it exists
- **Usage**: How to use it with examples
- **Parameters**: Inputs, outputs, and types
- **Examples**: Practical, working code examples
- **Errors**: Possible errors and solutions
- **Context**: When to use and when not to use
- **Alternatives**: Other approaches and trade-offs

### Documentation Maintenance

- Update docs in the same commit as code changes
- Remove outdated information promptly
- Keep examples current and working
- Validate links regularly (automated checks)
- Review for clarity and completeness
- Update version numbers and dates
- Archive deprecated documentation

## Accessibility Standards

### Image Alt Text

```markdown
# Good: Descriptive alt text
![Architecture diagram showing the flow from client through API gateway to microservices](./arch.png)

# Bad: Generic alt text
![diagram](./arch.png)

# Decorative images: Empty alt text
![](./decorative-border.png)
```

### Document Structure

- Use proper heading hierarchy (H1 → H2 → H3)
- Don't skip heading levels
- Use descriptive link text (avoid "click here")
- Provide text alternatives for visual information
- Structure content logically with clear sections
- Use lists for scannable content
- Include table of contents for long documents

### Code Accessibility

```markdown
# Include descriptive comments in code examples
\`\`\`python
def calculate_total(items):
    """Calculate total price with tax"""
    subtotal = sum(item.price for item in items)
    tax = subtotal * 0.08  # 8% sales tax
    return subtotal + tax
\`\`\`

# Provide alternative text descriptions for complex code
*This function iterates through all items, sums their prices, 
applies 8% sales tax, and returns the final total.*
```

## Documentation Tools

### Automated Validation

```bash
# Markdown linting
markdownlint README.md docs/**/*.md

# Link checking
markdown-link-check README.md
find . -name "*.md" -exec markdown-link-check {} \;

# Spell checking
cspell "**/*.md"

# YAML frontmatter validation
python scripts/validate_frontmatter.py
```

### Documentation Generation

**Python (Sphinx):**

```bash
# Generate Sphinx documentation
cd docs
sphinx-build -b html source/ build/html/
open build/html/index.html
```

**JavaScript (JSDoc):**

```bash
# Generate JSDoc documentation
jsdoc src/ -r -d docs/
open docs/index.html
```

**TypeScript (TypeDoc):**

```bash
# Generate TypeDoc documentation
typedoc --out docs src/
open docs/index.html
```

### Quality Assurance

```bash
# Run all documentation checks
./scripts/docs-quality-check.sh

# Which might include:
# - Markdown linting
# - Link validation
# - Spell checking
# - Frontmatter validation
# - Example code testing
# - Accessibility checks
```

## Project-Specific Documentation Patterns

### Web Applications

Include documentation for:

- API endpoints with request/response examples
- Database schema and migrations
- Environment configuration
- Deployment procedures
- Monitoring and logging

### Libraries/Packages

Include documentation for:

- Installation across different environments
- API reference for all public interfaces
- Usage examples for common scenarios
- Migration guides for version upgrades
- Contribution guidelines

### Educational/Learning Platforms

Include documentation for:

- Learning objectives and prerequisites
- Step-by-step tutorials with validation
- Multiple platform implementations
- Troubleshooting common issues
- Resources for further learning

---

**Version:** 3.0.0 | **Last Modified:** 2025-11-14 | **Author:** Amr Abdel-Motaleb

**Purpose:** Universal documentation standards template for comprehensive, accessible, and maintainable documentation across all project types.
