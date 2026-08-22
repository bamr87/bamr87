---
title: Pinning GitHub Actions to commit SHAs
description: How to satisfy the action-pin check when adding or updating a workflow step.
updated: 2026-08-22
---

# Pinning GitHub Actions to commit SHAs

This repository requires every third-party GitHub Action to be pinned to a **full
40-character commit SHA**, with the human-readable version kept alongside it in a
comment. An automated check (`check-action-pins`) fails CI when a workflow step
references a mutable ref such as a tag or a branch.

If you have landed here because the check failed on your pull request, jump to
[Resolving a tag to a SHA](#resolving-a-tag-to-a-sha).

## Why

A Git tag is a mutable pointer. `v4` and even `v4.1.2` can be force-moved by the
action's owner — or by anyone who compromises that account — to point at
different code, and every workflow that references the tag silently picks up the
new code on its next run. Workflows in this repository run with access to
repository contents and secrets, so that is a real supply-chain exposure.

A commit SHA is content-addressed and immutable. Pinning to one means the code
you reviewed is the code that runs, and upgrades become explicit, reviewable
commits.

## The required format

```yaml
steps:
  - uses: owner/repo@<40-char-sha>  # vX.Y.Z
```

Concretely:

```yaml
steps:
  - uses: actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11  # v4.1.1
  - uses: actions/setup-python@0a5c61591373683505ea898e09a3ea4f39ef2b9c  # v5.0.0
```

Three rules:

1. **The ref after `@` is a full 40-hex-character commit SHA.** Abbreviated SHAs
   (`@b4ffde6`) are not accepted — they are ambiguous and can become ambiguous
   later as the upstream repo grows.
2. **A trailing comment records the version the SHA corresponds to.** Without it,
   nobody — including Dependabot reviewers and future you — can tell what the
   pin actually is or whether it is stale.
3. **The comment should match the upstream tag** (`# v4.1.1`, not `# latest` or
   `# current`), so the pin can be re-derived and audited.

### Anti-patterns the check rejects

```yaml
- uses: actions/checkout@v4                 # ✗ mutable major tag
- uses: actions/checkout@v4.1.1             # ✗ mutable patch tag
- uses: actions/checkout@main               # ✗ branch ref
- uses: actions/checkout@b4ffde6            # ✗ abbreviated SHA
- uses: actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11  # ✗ SHA, but no version comment
```

## Resolving a tag to a SHA

Use the GitHub CLI's REST passthrough. Given the action reference you *wanted*
to write — say `actions/checkout@v4.1.1` — ask for the tag ref:

```bash
gh api repos/actions/checkout/git/ref/tags/v4.1.1
```

The interesting part of the response is the `object` field:

```json
{
  "ref": "refs/tags/v4.1.1",
  "object": {
    "sha": "b4ffde65f46336ab88eb53be808477a3936bae11",
    "type": "commit"
  }
}
```

When `object.type` is `"commit"`, `object.sha` **is** the SHA to pin. You are done:

```yaml
- uses: actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11  # v4.1.1
```

## The annotated-tag gotcha

Git has two kinds of tags:

- A **lightweight tag** is just a name pointing straight at a commit.
- An **annotated tag** is a first-class Git object (with a tagger, date, and
  message) that in turn points at a commit.

For an annotated tag, `git/ref/tags/<tag>` returns the **tag object's** SHA, not
the commit's:

```json
{
  "ref": "refs/tags/v5.0.0",
  "object": {
    "sha": "1111111111111111111111111111111111111111",
    "type": "tag"
  }
}
```

That SHA is 40 hex characters, so it *looks* like a valid pin and will sail past
a naive eyeball review — but GitHub Actions resolves `uses:` refs against
commits, so the workflow will fail to check out the action at runtime.

When `object.type == "tag"`, **dereference it** by fetching the tag object and
reading *its* `object.sha`:

```bash
gh api repos/actions/setup-python/git/tags/1111111111111111111111111111111111111111
```

```json
{
  "tag": "v5.0.0",
  "object": {
    "sha": "0a5c61591373683505ea898e09a3ea4f39ef2b9c",
    "type": "commit"
  }
}
```

That inner `object.sha` is the commit to pin.

> Rule of thumb: keep unwrapping until `object.type` is `"commit"`. In practice
> that is at most one hop.

### A helper that handles both cases

Drop this in your shell (it needs [`gh`](https://cli.github.com/) authenticated):

```bash
resolve-pin() {
  # usage: resolve-pin owner/repo v1.2.3
  local repo="$1" tag="$2" sha type
  read -r sha type < <(
    gh api "repos/${repo}/git/ref/tags/${tag}" \
      --jq '[.object.sha, .object.type] | @tsv'
  )
  if [ "$type" = "tag" ]; then
    sha=$(gh api "repos/${repo}/git/tags/${sha}" --jq '.object.sha')
  fi
  printf 'uses: %s@%s  # %s\n' "$repo" "$sha" "$tag"
}
```

```console
$ resolve-pin actions/checkout v4.1.1
uses: actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11  # v4.1.1
```

Copy the output straight into your workflow.

### Without the GitHub CLI

`curl` works the same way against the same endpoints:

```bash
curl -sS https://api.github.com/repos/actions/checkout/git/ref/tags/v4.1.1
```

Or, if you already have the action cloned locally, `git rev-list -n 1 <tag>`
resolves annotated tags to their commit for you:

```bash
git ls-remote https://github.com/actions/checkout refs/tags/v4.1.1^{}
```

The `^{}` suffix is Git's "dereference to a non-tag object" syntax — the
command-line equivalent of the second API call above.

## What is exempt

Not every `uses:` value is a third-party action pulled from a mutable tag. The
check skips:

| Reference kind | Example | Why it is exempt |
| --- | --- | --- |
| Local actions | `uses: ./.github/actions/setup` | The code lives in this repository at the same commit as the workflow, so there is nothing external to pin. |
| Docker images | `uses: docker://alpine:3.19` | Not a Git ref; pinning is done through the image tag or digest, which this check does not police. |

Everything else — anything of the form `owner/repo`, with or without a
subdirectory path such as `owner/repo/sub/action` — must be SHA-pinned.

> If you are referencing a Docker image, prefer a digest
> (`docker://alpine@sha256:...`) anyway. It buys you the same immutability the
> SHA pin buys for actions, even though the check will not insist on it.

## Updating a pin

Upgrading an action is a two-line change: swap the SHA and swap the version
comment. Do both. A stale comment is worse than no comment, because it makes an
old pin look current.

```diff
-  - uses: actions/checkout@a12a3943b4bdde767164f792f33f40b04645d846  # v3.5.3
+  - uses: actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11  # v4.1.1
```

When reviewing such a change, verify the new SHA independently — re-run
`resolve-pin` yourself rather than trusting the comment in the diff.

## Checking your work

Run the action-pin check locally before pushing so you do not round-trip through
CI.

<!-- TODO(maintainer): replace with the canonical local invocation, e.g. the
     Rakefile task, the pre-commit hook id, or the direct script path. -->

The same check runs in CI on pull requests. If it fails, the message names the
workflow file and the offending `uses:` line; resolve the tag with the recipe
above and re-push.

## Further reading

- GitHub Docs — [Security hardening for GitHub Actions: use third-party actions pinned to a full-length commit SHA](https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions#using-third-party-actions)
- GitHub REST API — [Git references](https://docs.github.com/en/rest/git/refs) and [Git tags](https://docs.github.com/en/rest/git/tags)
