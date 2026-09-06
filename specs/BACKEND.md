# UPS-BE — HTTP API conventions and the client contract

> Every service in the fleet answers the same shape of request the same way, so one client module, one error type, and one health probe work against all of them.

Evidence base: FastAPI (aieo, wtd), Django + DRF (djangoerp, barodybroject, edgar/fredgar), Rails (zer0-image-generator), a Cloudflare Worker (githubai), and a stdlib server (books). Three frontend fetch wrappers carry three different `ApiError` shapes (`{status,detail,body,isAuth,isRateLimit}` · `{code,status,retryAfter}` · bare `Response`). No repo publishes an OpenAPI document in CI; no shared health contract exists; the hub monitors repos from GitHub metadata only. The `.github/instructions/development` "RESTful API Design" section is advice with no gate.

## Surface

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-BE-01 | MUST | api | Base path `/api/v<N>/`; resources plural kebab-case nouns; ids in the path; filters/sort/pagination in the query string; verbs only for RPC-style actions under `/api/v<N>/<resource>/<id>/<action>`. | route table | — |
| UPS-BE-02 | MUST | api | JSON only (`application/json; charset=utf-8`) for request and response bodies; `snake_case` keys; ISO-8601 UTC timestamps with `Z`; ids as strings. | review | — |
| UPS-BE-03 | MUST | api | Pagination is cursor-based for lists (`?limit=&cursor=`, response `{items, next_cursor}`); offset pagination only for admin tables with a documented reason. | review | — |
| UPS-BE-04 | MUST | api | Every response carries `X-Request-Id` (echoing the inbound one if present) and the app's `X-App-Version`. | headers | middleware (gap: `templates/api/`) |
| UPS-BE-05 | SHOULD | api | Rate limiting returns `429` with `Retry-After`; auth failures return `401` (missing) or `403` (insufficient) and never leak whether a resource exists. | tests | — |
| UPS-BE-06 | MUST | api | CORS is explicit: an allowlist from config (OPS-01), never `*` with credentials. | config | — |

## Health and version endpoints

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-BE-10 | MUST | api, app (server-rendered) | `GET /healthz` → `200 {"status":"ok"}` with no dependencies touched (liveness); `GET /readyz` → `200/503 {"status":"ok"\|"degraded","checks":{"db":"ok","cache":"ok",…}}` (readiness). Both unauthenticated, uncached, excluded from analytics and rate limits. The Dockerfile `HEALTHCHECK` and the frontend `ReadyDot` (fredgar) consume `/readyz`. | endpoints | `templates/api/` (gap) |
| UPS-BE-11 | MUST | api, app (server-rendered) | `GET /version` → `{"name","version","commit","built_at"}` from release-please's version and the build's `GIT_SHA`. | endpoint | same |
| UPS-BE-12 | SHOULD | api | `GET /api/v<N>/openapi.json` serves the generated OpenAPI 3.1 document; docs UI at `/api/v<N>/docs` in non-production. | route | framework default (FastAPI/DRF spectacular) |

## Errors

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-BE-20 | MUST | api | One error envelope for every non-2xx: `{"error":{"code":"<domain>.<reason>","message":"<human>","status":<int>,"details":[…],"request_id":"…","retry_after":<seconds\|null>}}`. `code` is a stable, documented string (`auth.invalid_token`, `validation.failed`, `resource.not_found`, `rate.limited`, `upstream.unavailable`); `details` for field errors is `[{"field","code","message"}]`. | envelope | `templates/api/` (gap) |
| UPS-BE-21 | MUST | api | Unhandled exceptions return the envelope with `code: "internal.error"` and a `request_id`, never a stack trace; the trace goes to the log (OPS-10) with the same request id. | handler | same |
| UPS-BE-22 | MUST | api | Validation errors are `422` with per-field details (FastAPI/DRF native shapes are adapted into the envelope, not exposed raw). | handler | same |
| UPS-BE-23 | SHOULD | api | Error codes are enumerated in `docs/API-ERRORS.md` (or generated from the enum) and referenced by the frontend's `ApiError` mapping. | doc | — |

## Versioning and contracts

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-BE-30 | MUST | api | Breaking changes bump `v<N>`; the previous version keeps serving for one release cycle with a `Deprecation` header and a `Sunset` date. Additive changes never bump. | changelog + headers | — |
| UPS-BE-31 | MUST | api | The OpenAPI document is committed (`openapi.json` at the surface root) and CI regenerates and diffs it (QA-17); the frontend's types are generated from it (`openapi-typescript`) rather than hand-written. | CI step + generated types | — |
| UPS-BE-32 | SHOULD | api + app | Cross-repo contracts (e.g. the `CVData` schema shared by `cv` and `cv-builder-pro`) are vendored as a JSON Schema under `contract/` with a `contract-check` test on both sides. | `contract/*.schema.json` | cv-builder-pro `scripts/contract-check.mjs` |

## Client contract (what the frontend HTTP client MUST do)

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-BE-40 | MUST | app | One module (`lib/http.ts` / `services/api.ts`) exports `request<T>()`, `get/post/put/patch/del`, and `class ApiError { status; code; message; details; requestId; retryAfter; get isAuth(); get isRateLimit(); get isNetwork() }` parsed from the envelope (BE-20). Feature code never calls `fetch`. | module + lint rule (`no-restricted-globals: fetch` outside it) | `templates/api/client.ts` (gap; merge fredgar + aieo) |
| UPS-BE-41 | MUST | app | Base URL from one env var (`VITE_API_BASE` / `NEXT_PUBLIC_API_BASE`); credentials from one storage key; `AbortController` timeout (default 30 s, overridable); `X-Request-Id` generated per call and surfaced in error toasts and the feedback widget. | code | same |
| UPS-BE-42 | SHOULD | app | Server state via TanStack Query (React) with the `Query<T>` state wrapper (FE-17); retries only for `isNetwork` or `5xx`, never for `4xx`. | code | fredgar |
| UPS-BE-43 | SHOULD | app | A `ReadyDot`-style indicator polls `/readyz` and shows degraded state in the shell. | component | fredgar `AppShell.tsx` |

## Auth

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-BE-50 | MUST | api | Bearer tokens in `Authorization: Bearer …` or an `X-API-Key` header; never in query strings; tokens never logged (OPS-12). | review | — |
| UPS-BE-51 | SHOULD | app | Browser apps needing user identity use Firebase Auth (the fleet's one proven provider, cv-builder-pro) behind a `Protected` route wrapper and an `AuthContext`; server apps use the framework's session auth. New providers need a documented reason. | code | cv-builder-pro `context/AuthContext.tsx` |
