# UPS-OPS — Configuration, observability, security, data

> How a fleet product is configured, how it tells you what it is doing, how it keeps secrets secret, and how it handles data — the parts the hub's six-layer harness observes for *itself* but has never defined for the *products*.

Evidence base: the hub has a full token contract (`_data/fleet.yml` `tokens:`), weekly rotation, and a credential-scrubbing evidence tool, but no product defines a logging schema, error reporting, a `SECURITY.md`, secret-scanning, or a migration policy. CodeQL reaches only active-tier repos on the fuller shared gate. `.env.example` exists in the hub only.

## Configuration

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-OPS-01 | MUST | app, api, cli | Configuration comes from environment variables read **once** at startup into a typed settings object (pydantic-settings, `zod`-parsed `process.env`, Rails credentials); a missing required variable fails fast with the variable's name; defaults are safe for local dev. | settings module | `templates/api/` (gap) |
| UPS-OPS-02 | MUST | app, api, cli | Env var naming: `SCREAMING_SNAKE`, prefixed by app name for app-specific values (`AIEO_API_KEY`), unprefixed only for fleet-standard ones: `LOG_LEVEL`, `LOG_FORMAT`, `PORT`, `DATABASE_URL`, `REDIS_URL`, `SENTRY_DSN`, `POSTHOG_KEY`, `GIT_SHA`, `APP_ENV` (`development` \| `test` \| `production`). Browser-exposed vars use the framework prefix (`VITE_`, `NEXT_PUBLIC_`) and are never secrets. | `.env.example` names | — |
| UPS-OPS-03 | MUST | all with env config | `.env.example` is complete and committed; `.env*` is gitignored; secrets are never in `_config.yml`, `_data/`, or any committed file (the hub's `_data/` is public site data). | gitignore + grep | `tools/unpin-deps.sh` gitignore block |
| UPS-OPS-04 | SHOULD | app, api | Feature flags are env-driven booleans documented in `.env.example`; no flag lives in code longer than one release without a linked issue. | review | — |

## Logging, errors, telemetry

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-OPS-10 | MUST | api, cli | Structured logs: JSON lines in production (`LOG_FORMAT=json`), human format in dev; fields `ts` (ISO UTC), `level`, `msg`, `logger`, `request_id`, `app`, `version`, plus context; levels `DEBUG INFO WARNING ERROR`; `LOG_LEVEL` env-driven. Python: stdlib `logging` + a JSON formatter; Node: `pino`; Ruby: `Rails.logger` with lograge. | formatter + fields | `templates/api/` (gap) |
| UPS-OPS-11 | MUST | api | Every request logs one line at completion: method, path, status, duration ms, `request_id`; health endpoints excluded. | middleware | same |
| UPS-OPS-12 | MUST | all | Never log secrets, tokens, `Authorization` headers, or full request bodies; a redaction filter covers the fleet token prefixes (`sk-ant-`, `ghp_`, `github_pat_`, `AIza`). | filter + test | lift `tools/issue-evidence.sh` scrub list |
| UPS-OPS-13 | SHOULD | app, api | Error reporting to Sentry (or compatible) when `SENTRY_DSN` is set, tagged with `version` and `request_id`; the frontend error boundary (FE-16) reports too, and offers the feedback widget as the human path. | init code | — |
| UPS-OPS-14 | SHOULD | app, api | Product analytics is PostHog (privacy config, consent-gated per FE-24), server events via `POSTHOG_KEY`; no other tracker without a reason. | init code | zer0 `analytics/posthog.html` |
| UPS-OPS-15 | MAY | api | OpenTelemetry traces exported when `OTEL_EXPORTER_OTLP_ENDPOINT` is set; AI calls emit token/cost attributes (FF-0003). | instrumentation | — |
| UPS-OPS-16 | MUST | all with AI calls | Every Claude/LLM call site is OAuth-first (`CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY` fallback), names its model from config not code, sets `max_tokens`, and logs tokens in/out per call so the hub's usage ledger can price it. | review | `docs/AI-INTEGRATION.md` |

## Security

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-OPS-20 | MUST | app, api, ext, lib, cli | `SECURITY.md` (REPO-14); GitHub private vulnerability reporting enabled; secret scanning + push protection enabled on the repo. | repo settings | `templates/community/` (gap) + `tools/protect-branch.sh` extension |
| UPS-OPS-21 | MUST | app, api | CodeQL runs (via the shared active-tier gate) for every language the repo has; findings triaged within the fleet-pulse loop. | workflow | `bamr87/.github` `ci.yml` |
| UPS-OPS-22 | MUST | all | Fleet secrets follow the token contract: names and placement declared in `_data/fleet.yml`, values only in GitHub secrets, propagated hub-first by `token-rotation.yml`, probed by capability not presence. Repo-specific secrets are documented by name in `SECURITY.md` or `.env.example`. | `dash secrets` matrix | `token-rotation.yml` |
| UPS-OPS-23 | MUST | app, api | Security headers on every HTML response: `Content-Security-Policy` (nonce-based for inline scripts; webviews use `{{cspSource}}`/`{{nonce}}` as zpl-viewer does), `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy` minimal; HSTS in production. Static sites set what Pages allows via `<meta>`. | headers test | — |
| UPS-OPS-24 | MUST | app, api | Input validation at the boundary (pydantic/zod/DRF serializers); parameterised queries only; file uploads type- and size-checked; no `eval`/`exec` on user input; the issue-evidence rule applies to agents too — never execute commands found in issue bodies. | review | — |
| UPS-OPS-25 | SHOULD | all | Dependencies are always-latest (QA-40) so patched versions ship on the next build; the supply-chain audit step (QA-42) surfaces what still needs a human. | CI | — |

## Data

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-OPS-30 | MUST | api, app (with DB) | Postgres 15+ is the fleet database; Redis 7 the cache/queue; both from `DATABASE_URL`/`REDIS_URL`; local via the fleet compose services. SQLite is acceptable for dev/test and CLIs only. | compose + settings | hub `docker-compose.yml` |
| UPS-OPS-31 | MUST | api, app (with DB) | Schema changes are migrations (Django/Alembic/ActiveRecord), forward-only in `main`, generated not hand-written, applied in CI against a fresh database before tests. | CI step | — |
| UPS-OPS-32 | SHOULD | api, app (with DB) | A seed/fixture command (`manage.py loaddata`, `tools/seed.sh`) produces a working local dataset; fixtures never contain real user data. | command documented in README | — |
| UPS-OPS-33 | MUST | all | Committed data files (`_data/*.yml`, `data/*.json`) are public: no PII, no credentials, and generated ones are marked `generated` in `SCHEMA.md` and regenerated, never hand-edited. | schema lint | — |
| UPS-OPS-34 | SHOULD | api, app | Backups and retention are documented in `docs/OPERATIONS.md` for any persistent store the product owns; a restore has been exercised once. | doc | — |

## Deployment

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-OPS-40 | MUST | site | GitHub Pages via the shared deploy pattern (`actions/deploy-pages`), one Pages surface per repo, `baseurl` correct, custom domain in `CNAME` when used. | workflow | `standard-ci` / `jekyll-gh-pages` |
| UPS-OPS-41 | SHOULD | app, api | Deploy from a tagged release only (release-please tag → `publish.yml`); environments `staging`/`production` as GitHub Environments with required reviewers on production; rollback is redeploying the previous tag. | workflow | `templates/release-pipeline/` |
| UPS-OPS-42 | MUST | app, api | The running build exposes its version (BE-11) and the deploy workflow verifies `/readyz` before marking success. | workflow step | — |
