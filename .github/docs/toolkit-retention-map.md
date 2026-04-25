# GitHub Toolkit Retention Map

Use this map when deciding whether a file belongs in `.github/`.

## Keep Active

Files GitHub reads directly for this repository:

- `CODEOWNERS`
- `CONTRIBUTING.md`
- `dependabot.yml`
- `workflows/*.yml`
- `ISSUE_TEMPLATE/*`
- `pull_request_template.md`

## Keep As Tools

Reusable automation that is portable across repositories:

- `actions/setup/*`
- `actions/ci/*`
- `actions/deployment/build-push-image`
- `actions/utilities/*`
- `actions/examples/*`
- `scripts/*` when called by a workflow or documented as a reusable helper
- `config/*` when values are parameterized rather than project-specific

## Keep As Templates

Reusable source material that is intentionally copied or adapted:

- `templates/README.template.md`
- generic issue and PR templates in GitHub-native locations
- `instructions/*.instructions.md`
- generic `prompts/*.prompt.md`
- generic `agents/*.md`
- short reference docs in `docs/`

## Move Out Or Remove

Content that should not remain in the active toolkit:

- deprecated action implementations
- historical refactoring summaries
- product-specific deployment values
- files with hardcoded local paths, personal identities, or unrelated project names
- duplicate docs that restate a canonical README
- generated output and one-time migration notes

## Review Checklist

Before adding a file to `.github/`, confirm that it is either active GitHub configuration, a reusable template, a reusable tool, or a short reference document. If a file needs secrets, team names, owner names, hostnames, or local paths, those values should be inputs, placeholders, or target-repo configuration.
