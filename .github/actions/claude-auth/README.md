# `claude-auth`

Choose which Claude credential a `claude-code-action` step uses, in the order the repo's `CLAUDE_AUTH_ORDER` variable names.

## Why

Until 2026-09 every call site hard-coded OAuth-first:

```yaml
claude_code_oauth_token: <the OAuth secret>
anthropic_api_key: <the API key, but only when the OAuth secret is empty>
```

That made the order a fleet-wide constant, and "fallback" meant *absent*, never *rejected*. The order is now configuration: `ai_auth:` in [`_data/fleet.yml`](../../../_data/fleet.yml) sets it per repo or group, `dash config auth sync --apply` (and the weekly `token-rotation.yml` variable pass) projects it onto each repo as `CLAUDE_AUTH_ORDER`, and this action reads it.

## Contract

- **Output `method`**: `oauth`, `api_key`, or `none`. It is a name, never a credential. The calling step gates each secret on it, so no secret passes through a step output.
- **Presence decides, and for the API key so does acceptance.** The key is checked against the free `/v1/models` endpoint. A `401`/`403` moves on to the next method. A network error or `5xx` keeps the key, since it says nothing about the key itself. The OAuth token has no free check and is chosen on presence alone.
- **It never fails the job.** With nothing usable left it outputs `none` and warns. The caller's existing "is there a credential?" gate decides what happens next.
- **Empty order means the fleet default**, `oauth,api_key`. So a repo that has not received the variable yet behaves exactly as before.

## Use

```yaml
- id: claude-auth
  uses: bamr87/bamr87/.github/actions/claude-auth@main
  with:
    order: ${{ vars.CLAUDE_AUTH_ORDER }}
    has-oauth: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN != '' }}
    api-key: ${{ secrets.ANTHROPIC_API_KEY }}
- uses: anthropics/claude-code-action@v1
  with:
    claude_code_oauth_token: ${{ steps.claude-auth.outputs.method == 'oauth' && secrets.CLAUDE_CODE_OAUTH_TOKEN || '' }}
    anthropic_api_key: ${{ steps.claude-auth.outputs.method == 'api_key' && secrets.ANTHROPIC_API_KEY || '' }}
```

The action is referenced remotely, even from the hub's own workflows. Several of them check out another repository at the workspace root, where a `./.github/actions/…` path would resolve inside that repository instead of this one.

The `claude-run` lanes (`ai-lane.yml`) do not use this action. They read the same variable as `AI_AUTH_ORDER` in `run.sh`, which also retries with the next method when the first is rejected mid-call.
