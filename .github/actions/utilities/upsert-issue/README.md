# `upsert-issue`

One tracking issue per concern, updated in place, closed when the concern is gone.

## Why

Four loops — `api-keys`, `token-rotation`'s report, `reconcile-registry`, `schema-vendor` — each hand-rolled "find the open issue with this title, edit it or create it, make sure the labels exist first". Each copy had its own bug history: when a label did not exist, the labelled create failed, the unlabelled fallback ran, the labelled search below never matched, and one fresh duplicate appeared every night (27 by 2026-08-28). This is that logic once.

## Contract

- Dedupe is on the **exact title**. GitHub's issue search does not reliably match text inside an HTML comment, so a body marker is not a safe key.
- `state: open` (default): edit the open issue's body in place if it exists, else create it with every label (each created on demand), falling back to an unlabelled issue rather than no issue.
- `state: close`: close the open issue if it exists (with `close-comment`), else do nothing.
- Alarms are filed with `github.token` on purpose: an alarm must not ride on the credential most likely to be dead.

## Usage

```yaml
- uses: ./.github/actions/utilities/upsert-issue
  with:
    token: ${{ github.token }}
    title: "🔑 Anthropic API keys need a human"
    body-file: key-attention.md
    labels: automation,security
    state: ${{ steps.keys.outputs.attention == 'true' && 'open' || 'close' }}
    close-comment: "Every deployed key is inside its policy."
```

| Input | Default | Description |
| --- | --- | --- |
| `token` | — | `issues:write` on the target repo |
| `title` | — | Exact title; the dedupe key |
| `body-file` | `''` | Markdown body (required for `open`) |
| `labels` | `''` | Comma-separated, created on demand |
| `repo` | this repo | `owner/repo` |
| `state` | `open` | `open` or `close` |
| `close-comment` | `''` | Comment left on close |

| Output | Description |
| --- | --- |
| `number` | The issue acted on |
| `action` | `created`, `updated`, `closed` or `none` |
