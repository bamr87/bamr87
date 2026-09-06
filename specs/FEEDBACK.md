# UPS-FB — The universal feedback component

> Any page, in any stack, can file a well-formed GitHub issue against its own repo with one click — carrying the page context, environment, and captured console errors an agent needs to act on it without asking. Issues filed this way land in the fleet's three-tier issue pipeline by label.

Evidence base: the zer0-mistakes theme already implements this (`_includes/components/page-feedback.html`, `assets/js/page-feedback.js`, `_data/feedback_types.yml`, `_includes/core/console-capture.html`, `_sass/components/_page-feedback.scss`) with a proxy/AI mode on top. But `remote_theme` cannot ship `_config.yml` or `_data/`, so the widget is **dead on every one of the 7 consumer sites**; `barodybroject` has it as a literal TODO in `base.html`; no React app, Django app, or webview has any feedback path; the hub's own dash has one 404 link. Three different issue-URL builders exist inside zer0-mistakes alone (widget, 404 page, AI chat) with different escaping. This spec makes one builder the fleet's, framework-agnostic, seeded as a kit.

## Reference implementation

`templates/feedback/` — the `<fleet-feedback>` web component (vanilla JS, no dependencies, shadow DOM, token-aware). Adapters: a Jekyll include, a React wrapper, a Django/Rails/MkDocs snippet. The Jekyll theme keeps its richer widget and the theme's Liquid include becomes a thin wrapper that emits the same contract, so both produce identical issues.

## Behaviour

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-FB-01 | MUST | site, app | Every page renders the feedback trigger: a floating action button (bottom-right, on the `fab` layer, label "Improve this page") **and** an inline trigger in the page action bar (FE-14). Both open the same dialog. Webviews use an inline trigger only. | element present on every route | `templates/feedback/` |
| UPS-FB-02 | MUST | site, app | The dialog is a native `<dialog>` (or equivalent with `role="dialog" aria-modal="true"`), focus-trapped, Escape/backdrop closable, returns focus to the trigger, labelled by its heading. | a11y review | kit |
| UPS-FB-03 | MUST | site, app | The dialog offers **request types** from a taxonomy (FB-20) as a keyboard-navigable radio group, a description textarea with a type-specific placeholder, and a **context preview** listing exactly what will be attached (page, URL, environment, N log lines) so the user consents to it. | markup | kit |
| UPS-FB-04 | MUST | site, app | Console/error capture: a ring buffer (default 40 entries) of `console.warn/error`, `window.onerror`, and `unhandledrejection`, installed as early as possible; attached only when the user leaves "include logs" checked; previewable before submit. | `window.__fleetFeedback.logs` | kit (`fleet-feedback.js` installs on load) |
| UPS-FB-05 | MUST | site, app | Default mode is **`url`**: open `https://github.com/<repo>/issues/new?title=&body=&labels=&assignees=` in a new tab with no token. Optional **`proxy`** mode POSTs `{title, body, labels}` to a configured endpoint that holds the token server-side. | attribute `mode` | kit |
| UPS-FB-06 | MUST | site, app | URL budget **7000 chars**; when exceeded, sections are trimmed in order logs → directive → environment; when still over, or when the popup is blocked, the full body is copied to the clipboard and an `aria-live` status tells the user to paste it. Nothing is silently lost. | code path | kit |
| UPS-FB-07 | MUST | site, app | Works without JS for the inline trigger: it is a real `<a href="…/issues/new?template=page_feedback.yml&labels=page-feedback">`, progressively enhanced. | markup | kit + `page_feedback.yml` issue template |
| UPS-FB-08 | MUST | site, app | Privacy: no cookies, no analytics event without consent, no request until the user submits; the environment section never includes IP, user identity, or form contents; logs are shown before sending. | review | kit |
| UPS-FB-09 | SHOULD | site, app | Other components route through it: the 404 page opens it pre-typed `fix-page` with the missing URL; the error boundary opens it pre-typed `bug` with the stack attached; "Suggest an edit" opens it `improve-page`. | integrations | kit API `open({type, extra})` |
| UPS-FB-10 | MAY | site, app | An "Analyze with AI" step (proxy mode only) sends the draft to a triage endpoint that returns a suggested title, labels, and priority before filing. | config `ai.enabled` | zer0-mistakes chat proxy |

## Issue contract

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-FB-20 | MUST | site, app | Request-type taxonomy (data file `feedback_types.yml`, JSON-injected at runtime): `fix-page`, `improve-page`, `expand-page`, `update-page`, `accessibility` (scope page) · `ui-ux`, `performance`, `feature`, `question` (scope site). Each entry: `id label icon group scope description labels agent directive placeholder`. | data file | `templates/feedback/feedback_types.yml` |
| UPS-FB-21 | MUST | site, app | Labels applied = marker `page-feedback` + the type's labels, where the type labels map onto the **fleet issue-pipeline taxonomy** (`_data/fleet.yml` `issue_pipeline.labels.types`: `bug feature docs chore ci refactor test security question`) plus optional `area:*`. Every label MUST exist in the repo (GitHub silently drops unknown labels from a prefilled URL). | `gh label list` ⊇ taxonomy | `templates/community/labels.yml` (gap) |
| UPS-FB-22 | MUST | site, app | Title: `[<type label>] <page title>` (≤ 240 chars). | code | kit |
| UPS-FB-23 | MUST | site, app | Body sections, in order, each a `##` heading: **Description** (user text) · **Page context** table (Page, URL, Source link `blob/<branch>/<path>`, Collection/route, Last modified) · **Environment** table (browser, viewport@dpr, colour scheme + reduced-motion, referrer, repository, branch, build env, captured at) · **Console & error logs** in a `<details>` block · **Agent directive** (type's `directive`, only when `agent: true`) · footer `_Filed from <url> via fleet-feedback v<kit version>._` plus a hidden marker `<!-- fleet-feedback v1 type=<id> -->` for dedupe and analytics. | body | kit |
| UPS-FB-24 | MUST | site, app | Types with `agent: true` add the configured assignee (default `copilot`; `''` disables) and the directive so the issue is `agent:queued`-eligible on the next pipeline scan; `agent: false` types get neither. | config | kit |
| UPS-FB-25 | SHOULD | site, app | The repo's `page_feedback.yml` issue template mirrors the same sections so hand-filed and widget-filed issues look identical to the pipeline. | template present | `templates/community/` (gap) |

## Configuration

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-FB-30 | MUST | site, app | Configuration keys (attributes on the element, `page_feedback:` in `_config.yml`, or the React props): `repo` (required, `owner/name`), `branch` (default `main`), `source` (page source path), `labels` (marker, default `page-feedback`), `assignee`, `mode` (`url`/`proxy`), `endpoint`, `capture-logs` (default true), `log-limit` (40), `fab` (default true), `label` ("Improve this page"), `types` (URL or inline JSON). | attributes | kit README |
| UPS-FB-31 | MUST | site | Consumer Jekyll sites enable it in their own `_config.yml` (`page_feedback.enabled: true`, `repository:`); the theme falls back to the kit's built-in taxonomy when `_data/feedback_types.yml` is absent, so `remote_theme` consumers work with zero data files. | config key | theme change (gap) + kit fallback |
| UPS-FB-32 | MUST | app | React/Next apps mount `<FeedbackButton>` once in the AppShell; Django/Rails/MkDocs include the snippet in the base template; VS Code webviews mount the inline variant with `mode="proxy"` (the extension host files the issue via `vscode.env.openExternal`). | mount point | kit adapters |
| UPS-FB-33 | SHOULD | site, app | The hub dash mounts it on every surface against `bamr87/bamr87`, so a visitor can file against the control plane itself. | element present | hub change |
