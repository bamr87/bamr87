---
title: Pinning GitHub Actions to commit SHAs
description: Why third-party GitHub Actions are pinned to immutable commit SHAs in this repository, and how to pin, verify, and upgrade them.
---

# Pinning GitHub Actions to commit SHAs

When a workflow in this repository references a third-party action, it should
reference an **immutable commit SHA**, not a tag or branch:

```yaml
# Pinned - the referenced code can never change
- uses: actions/checkout@<40-char-sha>  # v4.2.2

# Not pinned - the referenced code can change under you
- uses: actions/checkout@v4
- uses: actions/checkout@main
```

This page explains why, and gives you the exact commands to fix a workflow that
fails the pinning check.

---

## TL;DR - I just want to fix the failing check

1. Find the offending `uses:` line. It will look like `owner/repo@v1` or
   `owner/repo@main`.
2. Resolve that ref to a commit SHA:

   ```bash
   gh api repos/OWNER/REPO/commits/TAG --jq .sha
   ```

3. Replace the ref with the SHA and keep the version as a trailing comment:

   ```yaml
   - uses: owner/repo@1a2b3c4d5e6f7890a1b2c3d4e5f67890abcdef12  # v1.2.3
   ```

4. Commit and push. The check looks for a full-length commit SHA after the `@`.

The rest of this page covers *why*, plus verification, upgrades, and edge cases.

---

## Why tags are not safe

A `uses:` reference tells GitHub Actions to fetch code from another repository
and run it inside your job. That code inherits your job's environment: the
`GITHUB_TOKEN`, any secrets you pass, the checked-out source tree, and the
runner itself.

The key property is that **a Git tag is a mutable pointer**. A tag is just a
ref that points at an object; the owner of the upstream repository can delete it
and recreate it pointing at a completely different commit:

```bash
git tag -f v4 <different-commit>
git push --force origin v4
```

Nothing in your workflow changes. Your YAML still says `@v4`. But the next time
the job runs, it executes different code.

This is not hypothetical bookkeeping - it is the standard shape of a supply
chain attack on CI:

- **Compromised maintainer account.** An attacker with push access repoints an
  existing tag at malicious code. Every downstream workflow using that tag picks
  it up on the next run, with no PR, no diff, and no notification.
- **Moving major-version tags.** Many actions publish a floating `v4` tag that
  the maintainer deliberately advances to each new `v4.x.y` release. That is a
  *feature* for the maintainer and a *risk* for you: `@v4` today and `@v4`
  tomorrow are, by design, different code.
- **Branch refs are worse.** `@main` re-resolves on every single run.

A commit SHA has none of these properties. It is a content-derived identifier;
you cannot repoint it at different content. `owner/repo@<sha>` today and
`owner/repo@<sha>` in two years fetch byte-identical code, or fail outright.

> Pinning does **not** make an action trustworthy. It makes it *unchanging*. You
> still need to be comfortable with the code at the commit you pinned - pinning
> just guarantees that what you reviewed is what runs.

---

## Resolving a tag to a SHA

Two ways, both fine. Use whichever tool you have.

### With the GitHub CLI

```bash
gh api repos/OWNER/REPO/commits/TAG --jq .sha
```

Concretely:

```bash
$ gh api repos/actions/checkout/commits/v4.2.2 --jq .sha
11bd71901bbe5b1630ceea73d27597364c9af683
```

This resolves through annotated tags and gives you the commit SHA directly,
which is what you want in a `uses:` line.

### With plain Git

```bash
git ls-remote https://github.com/OWNER/REPO refs/tags/TAG
```

For example:

```bash
$ git ls-remote https://github.com/actions/checkout refs/tags/v4.2.2
<sha>	refs/tags/v4.2.2
```

One wrinkle: for an **annotated** tag, `git ls-remote` shows the *tag object's*
SHA, and the commit it points to appears on a second line suffixed with `^{}`:

```bash
$ git ls-remote https://github.com/OWNER/REPO 'refs/tags/v1.2.3*'
<tag-object-sha>     refs/tags/v1.2.3
<commit-sha>         refs/tags/v1.2.3^{}
```

Use the `^{}` line - the dereferenced **commit** SHA. If only one line comes
back, the tag is lightweight and that SHA is already the commit.

GitHub Actions accepts either in practice, but standardising on the commit SHA
keeps things comparable across tools and matches what `gh api` returns.

### Sanity checks

- The SHA should be **40 hex characters**. Short SHAs (`@1a2b3c4`) are not
  acceptable - they are ambiguous and defeat the purpose.
- Resolve the SHA from the **upstream repository**, not from a fork or a mirror.
- Prefer resolving a specific release tag (`v4.2.2`) over a floating major
  (`v4`), so the version comment you write down is meaningful.

---

## The comment convention

A bare SHA is unreadable. Nobody reviewing a diff can tell whether
`11bd7190...` is a year-old release or last week's. So always preserve the
human-readable version as a trailing comment:

```yaml
steps:
  - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683  # v4.2.2
  - uses: actions/setup-node@<sha>  # v4.1.0
```

The format is:

```
uses: owner/repo@<40-char-sha>  # vX.Y.Z
```

Rules of thumb:

- Put the version in the comment, **exactly** as upstream names the release
  (keep the leading `v` if upstream uses one).
- Keep the comment on the same line as the `uses:` value. Tooling - including
  Dependabot - reads it there.
- When you change the SHA, change the comment in the same edit. A stale comment
  is worse than no comment, because it actively misleads reviewers.

This is the convention the pinning check expects, and it is what makes
`git log -p` on a workflow file readable: the diff shows both the SHA change and
the version bump it corresponds to.

---

## Upgrading a pinned action (re-pinning)

Pinning trades "silently updated" for "deliberately updated". The upgrade flow:

1. **Find the new version.** Check the upstream releases page, or:

   ```bash
   gh release list --repo OWNER/REPO --limit 5
   ```

2. **Read what changed** between your pinned version and the new one. This is
   the step that pinning exists to enable - do not skip it for actions that
   handle secrets or write to your repository. A quick diff:

   ```bash
   gh api repos/OWNER/REPO/compare/OLD_TAG...NEW_TAG --jq '.files[].filename'
   ```

3. **Resolve the new SHA:**

   ```bash
   gh api repos/OWNER/REPO/commits/NEW_TAG --jq .sha
   ```

4. **Update both the SHA and the comment:**

   ```diff
   - - uses: actions/checkout@<old-sha>  # v4.1.7
   + - uses: actions/checkout@<new-sha>  # v4.2.2
   ```

5. **Push and let CI run.** If the action's inputs or outputs changed, this is
   where you find out - on a PR, not on `main`.

### Dependabot

If this repository uses Dependabot for the `github-actions` ecosystem, it
understands SHA pins: it opens PRs that bump the SHA *and* rewrite the trailing
version comment for you. That is another reason to follow the comment
convention precisely - Dependabot uses the comment to work out which version you
are currently on.

SHA-pinned actions therefore do not mean "never updated". They mean updates
arrive as reviewable pull requests instead of as invisible changes to code you
already trust.

---

## What gets pinned, and what doesn't

**Pin these:**

- Any third-party action: `uses: some-org/some-action@...`
- Actions published by GitHub itself (`actions/checkout`, `actions/setup-*`).
  These are widely trusted but are still separate repositories with separate
  maintainers and mutable tags.

**These are different cases:**

- **Local actions** - `uses: ./.github/actions/my-action`. These live in this
  repository at the commit the workflow is already running from, so there is
  nothing to pin.
- **Reusable workflows** - `uses: owner/repo/.github/workflows/wf.yml@ref`.
  The same mutability argument applies; pin these to a SHA too.
- **Docker actions** - `uses: docker://image:tag`. Tags are mutable here as well;
  prefer a digest (`docker://image@sha256:...`) where the check allows it.

---

## Troubleshooting

**"The check fails but I already used a SHA."**
Make sure it is the full 40-character SHA, not an abbreviated one, and that
there is no stray whitespace or quoting around it.

**"The workflow now fails with a ref-not-found error."**
You may have pinned the SHA of a *tag object* rather than the commit it points
to, or copied a SHA from a fork. Re-resolve with
`gh api repos/OWNER/REPO/commits/TAG --jq .sha`.

**"The action behaves differently after pinning."**
You were previously on a floating tag that had advanced past the release you
just pinned to. Check which version you actually want, and pin the SHA for that
release.

**"I need the latest version at all times."**
You don't - that is the failure mode this guard exists to prevent. Use
Dependabot (or a scheduled manual review) to get updates as reviewable PRs.

---

## Further reading

- GitHub Docs - *Security hardening for GitHub Actions*, section "Using
  third-party actions":
  <https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions>
- GitHub Docs - *Workflow syntax: `jobs.<job_id>.steps[*].uses`*:
  <https://docs.github.com/en/actions/writing-workflows/workflow-syntax-for-github-actions#jobsjob_idstepsuses>
- GitHub Docs - *Keeping your actions up to date with Dependabot*:
  <https://docs.github.com/en/code-security/dependabot/working-with-dependabot/keeping-your-actions-up-to-date-with-dependabot>
