---
file: frontmatter.standards.md
description: Unified frontmatter standards and metadata structures for instruction files across all repositories
author: Barodybroject Team
created: 2025-10-28
lastModified: 2025-10-28
version: 1.0.0
applyTo: "**/*.md"
dependencies:
  - copilot-instructions.md: Core principles and VS Code Copilot integration
relatedEvolutions:
  - "Harmonized frontmatter standards across IT-Journey ecosystem"
  - "VS Code Copilot optimization for instruction file metadata"
  - "Unified documentation structure and cross-referencing"
---

# Unified Frontmatter Standards

This document defines the standardized frontmatter structure and metadata requirements for instruction files across all repositories in the ecosystem (IT-Journey, Barodybroject, Zer0-Mistakes).

## 🎯 Frontmatter Philosophy

Frontmatter serves as structured metadata that enables:
- **AI Understanding**: VS Code Copilot and other AI tools can better understand file context
- **Cross-Repository Consistency**: Unified standards across all projects
- **Automated Processing**: Scripts can parse and validate instruction files
- **Dependency Management**: Clear relationships between instruction files
- **Evolution Tracking**: Version control and change management

## 📋 Universal Frontmatter Template

### Required Fields (All Instruction Files)

```yaml
---
file: filename.instructions.md
description: "Brief description of the instruction file's purpose and scope"
author: "Team Name or Individual Author"
created: YYYY-MM-DD
lastModified: YYYY-MM-DD
version: X.Y.Z
---
```

### Extended Template (Comprehensive)

```yaml
---
file: filename.instructions.md
description: "Brief description of the instruction file's purpose and scope"
author: "Team Name or Individual Author"
created: YYYY-MM-DD
lastModified: YYYY-MM-DD
version: X.Y.Z
applyTo: "file patterns or scope"  # Optional: what files this applies to
dependencies:
  - other-file.md: "Relationship description"
  - another-file.md: "How this file depends on the other"
relatedEvolutions:
  - "Description of related changes or improvements"
  - "Evolution or enhancement that this file supports"
containerRequirements:  # Optional: for containerized development
  baseImage: "image:tag"
  description: "Purpose of the container environment"
  exposedPorts:
    - port_number
  portDescription: "Description of what ports are used for"
  volumes:
    - "/path:permission"
  environment:
    VARIABLE_NAME: "description or value"
  resources:
    cpu: "resource_range"
    memory: "memory_range"
  healthCheck: "health check endpoint or command"
paths:  # Optional: for workflow or process documentation
  workflow_name_path:
    - step_1
    - step_2
    - step_3
changelog:
  - date: "YYYY-MM-DD"
    description: "Description of changes made"
    author: "Author of changes"
usage: "Brief description of how to use this instruction file"
notes: "Additional notes or important considerations"
---
```

## 📚 Repository-Specific Adaptations

### IT-Journey Instruction Files

**Focus**: Educational content creation, quest development, gamified learning
**Key Extensions**:
```yaml
educational_context:
  target_audience: "skill level and background"
  learning_objectives:
    - "specific learning goal"
  assessment_criteria:
    - "how success is measured"
quest_integration:  # For quest-related instructions
  binary_levels: "applicable binary levels"
  fantasy_theme: "RPG integration requirements"
  gamification_elements:
    - "achievement systems"
    - "progression tracking"
```

### Barodybroject Instruction Files

**Focus**: Django/OpenAI development, container-first architecture, Azure deployment
**Key Extensions**:
```yaml
django_context:
  apps_affected:
    - "django_app_name"
  models_involved:
    - "model_name"
  api_endpoints:
    - "endpoint pattern"
openai_integration:
  service_patterns:
    - "service integration type"
  error_handling:
    - "error handling pattern"
azure_deployment:
  infrastructure_components:
    - "Azure service or component"
  deployment_patterns:
    - "deployment strategy"
```

### Zer0-Mistakes Instruction Files

**Focus**: Jekyll theme development, Bootstrap integration, Docker optimization
**Key Extensions**:
```yaml
jekyll_context:
  layouts_affected:
    - "layout_name"
  includes_involved:
    - "include_name"
  theme_components:
    - "component_type"
bootstrap_integration:
  components_used:
    - "Bootstrap component"
  utilities_applied:
    - "utility class pattern"
docker_optimization:
  container_features:
    - "Docker feature or optimization"
  development_workflow:
    - "workflow enhancement"
```

## 🔄 Version Management Standards

### Semantic Versioning for Instruction Files

**MAJOR (X.0.0)**: Breaking changes to instruction structure or fundamental approach
- Complete rewrite of instruction methodology
- Incompatible changes to frontmatter structure
- Major architectural shifts in development approach

**MINOR (0.X.0)**: New features or significant enhancements
- Addition of new instruction sections
- New VS Code Copilot integration patterns
- Enhanced workflow or process documentation

**PATCH (0.0.X)**: Bug fixes, clarifications, and minor improvements
- Typo corrections and clarity improvements
- Updated examples or code snippets
- Minor formatting or organizational changes

### Change Documentation Requirements

Every version update MUST include:
```yaml
changelog:
  - date: "YYYY-MM-DD"
    description: "Specific description of what changed"
    author: "Person who made the changes"
    type: "major | minor | patch"
    breaking_changes: "Description if applicable"
```

## 🔗 Dependency Management

### Dependency Types

**Direct Dependencies**: Files that this instruction file directly references or builds upon
```yaml
dependencies:
  - copilot-instructions.md: "Core principles and foundation"
  - space.instructions.md: "Project organization standards"
```

**Related Files**: Files that complement or work alongside this instruction file
```yaml
related_files:
  - features.instructions.md: "Feature development patterns"
  - test.instructions.md: "Testing standards and validation"
```

**Cross-Repository References**: References to instruction files in other repositories
```yaml
cross_repo_references:
  - repo: "it-journey"
    file: "quest.instructions.md"
    relationship: "Educational content creation patterns"
  - repo: "zer0-mistakes"
    file: "layouts.instructions.md"
    relationship: "Jekyll theme development standards"
```

## 🤖 VS Code Copilot Integration Metadata

### AI-Specific Frontmatter Extensions

```yaml
ai_integration:
  copilot_optimization: true
  prompt_patterns:
    - "Common VS Code Copilot prompts for this instruction type"
  context_requirements:
    - "Information AI needs to provide effective assistance"
  quality_criteria:
    - "Standards for evaluating AI-generated content"
automation_support:
  validation_scripts:
    - "script_name.py: validation purpose"
  generation_tools:
    - "tool_name: what it generates"
  maintenance_workflows:
    - "workflow_name: maintenance task"
```

## 📊 Quality Assurance Standards

### Frontmatter Validation Requirements

Every instruction file frontmatter MUST:
- [ ] Include all required fields with appropriate values
- [ ] Use consistent date formats (YYYY-MM-DD for dates, ISO 8601 for timestamps)
- [ ] Have valid YAML syntax and structure
- [ ] Include accurate dependency references
- [ ] Maintain version consistency with content changes
- [ ] Include appropriate container requirements if applicable

### Cross-Reference Integrity

- [ ] All dependency references point to existing files
- [ ] Version numbers follow semantic versioning standards
- [ ] Container requirements are accurate and testable
- [ ] Path definitions are logical and implementable
- [ ] Changelog entries are complete and descriptive

## 🛠️ Implementation Guidelines

### Creating New Instruction Files

1. **Start with Template**: Use the appropriate frontmatter template
2. **Define Dependencies**: Identify and document all dependencies
3. **Specify Container Requirements**: If applicable, define container needs
4. **Document Workflows**: Include relevant path definitions
5. **Validate Structure**: Ensure frontmatter is valid YAML

### Updating Existing Instruction Files

1. **Update Version**: Increment version number appropriately
2. **Update lastModified**: Set to current date
3. **Add Changelog Entry**: Document what changed
4. **Review Dependencies**: Ensure dependencies are still accurate
5. **Validate Changes**: Test that examples and references still work

### Cross-Repository Harmonization

1. **Identify Common Patterns**: Find shared instruction patterns
2. **Standardize Frontmatter**: Apply unified frontmatter structure
3. **Update Cross-References**: Ensure accurate cross-repository links
4. **Validate Consistency**: Check for consistent terminology and approach
5. **Document Relationships**: Clearly define how repositories relate

---

*These frontmatter standards ensure consistency, maintainability, and AI-optimization across all instruction files in the ecosystem while supporting the unique needs of each repository.*
