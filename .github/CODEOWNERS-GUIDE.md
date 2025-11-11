# CODEOWNERS Configuration Guide

This guide explains how to customize and use the generalized CODEOWNERS and CODEOWNERS-soft files for your repository.

## 📋 Overview

The CODEOWNERS system provides two levels of code ownership:

1. **CODEOWNERS** - Hard ownership (blocks PRs until approval)
2. **CODEOWNERS-soft** - Soft ownership (notifications only, doesn't block)

## 🚀 Quick Setup

### 1. Update Team Names

Replace the generic team names with your actual GitHub teams or users:

```bash
# Example replacements:
@repo-admins → @yourorg/admins
@frontend-team → @yourorg/frontend
@backend-team → @yourorg/backend
@devops-team → @yourorg/platform
@security-team → @yourorg/security
```

### 2. Customize Directory Structure

Update the file patterns to match your project structure:

```bash
# Common customizations:
/frontend/ → /web/ or /client/ or /ui/
/backend/ → /server/ or /api/ or /service/
/mobile/ → /apps/mobile/ or /native/
```

### 3. Add Project-Specific Patterns

Add patterns specific to your domain or technology:

```bash
# E-commerce example:
/**/cart/ @ecommerce-team
/**/checkout/ @payments-team
/**/inventory/ @logistics-team

# SaaS example:
/**/billing/ @billing-team
/**/subscriptions/ @revenue-team
/**/onboarding/ @growth-team
```

## 🏗️ Common Configuration Patterns

### Web Applications

```bash
# Frontend
/src/components/ @frontend-team
/src/pages/ @frontend-team
/src/hooks/ @frontend-team
/src/utils/ @frontend-team

# API
/src/api/ @backend-team
/src/controllers/ @backend-team
/src/models/ @backend-team
/src/services/ @backend-team

# Shared
/src/types/ @frontend-team @backend-team
/src/constants/ @frontend-team @backend-team
```

### Microservices

```bash
# Service-specific ownership
/services/user-service/ @user-team
/services/payment-service/ @payments-team
/services/notification-service/ @platform-team

# Shared libraries
/packages/shared/ @platform-team @all-teams
/packages/utils/ @platform-team
```

### Monorepo Structure

```bash
# Applications
/apps/web/ @frontend-team
/apps/mobile/ @mobile-team
/apps/admin/ @admin-team

# Packages
/packages/ui/ @design-system-team
/packages/api-client/ @api-team
/packages/utils/ @platform-team
```

## 🔧 Implementation Strategies

### Strategy 1: Gradual Rollout

Start with high-level ownership and gradually add specificity:

```bash
# Week 1: Basic structure
* @tech-leads
/frontend/ @frontend-team
/backend/ @backend-team

# Week 2: Add specific patterns
/**/*.test.* @qa-team
/docs/ @docs-team

# Week 3: Fine-grained ownership
/frontend/src/auth/ @security-team @frontend-team
/backend/payment/ @payments-team @backend-team
```

### Strategy 2: Team-Based Approach

Organize by team responsibilities:

```bash
# Infrastructure team
/.github/ @infra-team
/docker/ @infra-team
/k8s/ @infra-team
/scripts/ @infra-team

# Product teams
/features/dashboard/ @dashboard-team
/features/analytics/ @analytics-team
/features/billing/ @billing-team
```

### Strategy 3: Feature-Based Approach

Group by feature or domain:

```bash
# Authentication domain
/**/auth/ @security-team
/**/login/ @security-team @ux-team
/**/oauth/ @security-team @backend-team

# Analytics domain
/**/analytics/ @analytics-team
/**/tracking/ @analytics-team @privacy-team
/**/reports/ @analytics-team @business-team
```

## 🎯 Team Configurations

### Small Team (5-15 people)

```bash
# Simple structure for small teams
* @tech-leads

# Core areas
/frontend/ @frontend-devs
/backend/ @backend-devs
/mobile/ @mobile-devs

# Critical files
/.github/ @tech-leads
/package.json @tech-leads
/Dockerfile @tech-leads
```

### Medium Team (15-50 people)

```bash
# More granular for medium teams
* @tech-leads

# Platform
/.github/ @platform-team
/infra/ @platform-team
/scripts/ @platform-team

# Product teams
/web/ @web-team
/api/ @api-team
/mobile/ @mobile-team

# Cross-cutting
/docs/ @tech-writers @tech-leads
/tests/ @qa-team
/security/ @security-team @tech-leads
```

### Large Team (50+ people)

```bash
# Highly specific for large teams
* @architecture-board

# Infrastructure
/.github/ @devops-team @platform-team
/terraform/ @infrastructure-team
/k8s/ @platform-team @sre-team

# Product areas
/services/user/ @identity-team
/services/billing/ @billing-team
/services/analytics/ @analytics-team

# Frontend by domain
/web/dashboard/ @dashboard-team
/web/onboarding/ @growth-team
/web/settings/ @platform-team

# Mobile by platform
/mobile/ios/ @ios-team
/mobile/android/ @android-team
/mobile/shared/ @mobile-platform-team
```

## 🛠️ Implementing Soft Ownership

### Option 1: GitHub Action

Create `.github/workflows/soft-codeowners.yml`:

```yaml
name: Soft CODEOWNERS
on:
  pull_request:
    types: [opened, synchronize]

jobs:
  soft-owners:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Add soft reviewers
        uses: your-org/soft-codeowners-action@v1
        with:
          soft-codeowners-file: .github/CODEOWNERS-soft
          github-token: ${{ secrets.GITHUB_TOKEN }}
```

### Option 2: Bot Integration

Integrate with existing bots (Dependabot, etc.):

```javascript
// Example bot logic
const softOwners = parseSoftCodeowners('.github/CODEOWNERS-soft');
const changedFiles = await getChangedFiles(pr.number);
const relevantOwners = findMatchingOwners(changedFiles, softOwners);

for (const owner of relevantOwners) {
  await addOptionalReviewer(pr.number, owner);
}
```

### Option 3: Manual Process

Use soft ownership for team notifications:

1. Check CODEOWNERS-soft for relevant changes
2. Tag teams in PR comments
3. Update team slack channels
4. Include in weekly team reviews

## 🔒 Security Considerations

### Critical Files

Always require security team review:

```bash
# Environment and secrets
/.env* @security-team @devops-team
/secrets/ @security-team @devops-team
/**/*secret* @security-team

# Authentication
/**/auth/ @security-team @backend-team
/**/oauth/ @security-team @backend-team
/**/jwt/ @security-team @backend-team

# Infrastructure
/terraform/ @security-team @infrastructure-team
/k8s/ @security-team @devops-team
/docker/ @security-team @devops-team
```

### Compliance Requirements

For regulated industries:

```bash
# Healthcare (HIPAA)
/**/patient/ @privacy-team @legal-team @security-team
/**/health/ @privacy-team @legal-team @security-team
/**/medical/ @compliance-team @legal-team

# Financial (SOX, PCI)
/**/payment/ @security-team @compliance-team @legal-team
/**/financial/ @finance-team @compliance-team @legal-team
/**/audit/ @compliance-team @legal-team
```

## 📊 Best Practices

### 1. Start Simple

Begin with broad ownership and refine over time:

```bash
# Initial setup
* @senior-devs
/frontend/ @frontend-team
/backend/ @backend-team
```

### 2. Use Hierarchical Patterns

More specific patterns override general ones:

```bash
# General backend ownership
/backend/ @backend-team

# Specific service ownership
/backend/payment-service/ @payments-team

# Critical payment files
/backend/payment-service/src/billing.py @payments-team @finance-team @security-team
```

### 3. Consider Cross-functional Teams

Include stakeholders beyond engineering:

```bash
# User-facing features
/frontend/onboarding/ @frontend-team @ux-team @product-team
/api/user-registration/ @backend-team @legal-team @privacy-team

# Business logic
/services/pricing/ @backend-team @business-team @finance-team
/reports/revenue/ @data-team @finance-team @business-team
```

### 4. Document Exceptions

Create clear guidelines for emergency changes:

```bash
# Emergency override (document when/how to use)
# /hotfix/ @on-call-engineer @tech-lead

# Production issues
/emergency-patches/ @sre-team @tech-leads
```

### 5. Regular Maintenance

Schedule regular reviews:

- **Monthly**: Review new patterns and team changes
- **Quarterly**: Audit effectiveness and update structure
- **Annually**: Major reorganization based on team evolution

## 🚨 Troubleshooting

### Common Issues

1. **Too many reviewers**: Use more specific patterns
2. **Not enough coverage**: Add broader patterns
3. **Teams not getting notified**: Check team membership
4. **PRs blocked unexpectedly**: Review pattern specificity

### Testing CODEOWNERS

```bash
# Test specific files
gh api repos/:owner/:repo/contents/.github/CODEOWNERS

# Validate syntax
cat .github/CODEOWNERS | grep -v "^#" | grep -v "^$"

# Check team membership
gh api orgs/:org/teams/:team/members
```

## 📈 Metrics and Monitoring

Track CODEOWNERS effectiveness:

- **Review time**: Are the right people reviewing quickly?
- **Review quality**: Are reviewers catching relevant issues?
- **Coverage**: Are all important files covered?
- **Team satisfaction**: Are teams happy with the assignment?

## 🔗 Resources

- [GitHub CODEOWNERS Documentation](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners)
- [CODEOWNERS Syntax Reference](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners#codeowners-syntax)
- [Team Management](https://docs.github.com/en/organizations/organizing-members-into-teams)
- [Repository Settings](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features)

## 🤝 Contributing

To improve these templates:

1. Fork the repository
2. Test changes in your environment
3. Submit PR with examples and use cases
4. Document any new patterns or best practices

---

**Remember**: CODEOWNERS is a powerful tool but should serve your team's workflow, not constrain it. Start simple and evolve based on your team's needs and feedback.