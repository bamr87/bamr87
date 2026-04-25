# CODEOWNERS Guide

This repository uses a compact CODEOWNERS file for a personal monorepo.

GitHub only requests reviews from valid users or teams. Keep owner entries tied to real GitHub usernames or real organization teams; do not leave template placeholders in the active CODEOWNERS file.

## Current Ownership Model

- `@bamr87` is the default owner for all paths.
- Root documentation, GitHub metadata, setup tooling, and submodule pointers are listed explicitly for readability.
- Changes inside submodules should be reviewed in the submodule repositories before updating the parent repository pointer.

## Updating Owners

If this repository moves to an organization or adds collaborators:

1. Add real GitHub users or organization teams to `.github/CODEOWNERS`.
2. Keep broad fallback ownership with `*`.
3. Add path-specific owners only where they change review behavior.
4. Test the file in a pull request to confirm GitHub requests the intended reviewers.

## Example

```text
* @bamr87
/docs/ @bamr87
/.github/workflows/ @bamr87
/tools/ @bamr87
```

Use organization teams only when they exist in GitHub:

```text
/.github/workflows/ @your-org/platform
/docs/ @your-org/docs
```
