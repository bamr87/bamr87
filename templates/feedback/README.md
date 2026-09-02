# templates/feedback — the universal feedback widget kit

> `<fleet-feedback>`: one web component that gives any page, in any stack, an "Improve this page" button that files a prefilled GitHub issue with page context, environment, and captured console errors. Spec: [`specs/FEEDBACK.md`](../../specs/FEEDBACK.md) (UPS-FB).

| File | Purpose |
| --- | --- |
| `fleet-feedback.js` | The component. Zero dependencies, shadow DOM, native `<dialog>`, token-aware (`--fleet-*` with `--zer0-*`/`--bs-*` fallbacks). Installs the console/error ring buffer as soon as it loads. |
| `feedback_types.yml` | The request-type taxonomy (also embedded in the JS as the fallback). Type labels map onto the fleet issue-pipeline label set. |
| `page_feedback.yml` | The no-JS twin: a GitHub issue form the inline anchor points at, with the same sections. Copy to `.github/ISSUE_TEMPLATE/`. |
| `adapters/jekyll.html` | Include for Jekyll sites that do not use the zer0-mistakes theme (and MkDocs overrides). |
| `adapters/FeedbackButton.tsx` | React/Next wrapper + `openFeedback()` for the error boundary, 404 route, and edit links. |
| `adapters/django.html` | Django template snippet (translate 1:1 to ERB for Rails). |
| `VERSION` | Kit provenance + changelog. |

## Install (any stack)

1. Vendor `fleet-feedback.js` into the repo's static assets. Never hot-link the hub.
2. Mount the element once in the shell with at least `repo="owner/name"`. Use the adapter for your stack.
3. Create the labels: `page-feedback`, `bug`, `feature`, `docs`, `question`, `area:a11y`, `area:perf` (`gh label create …`). GitHub drops unknown labels silently.
4. Copy `page_feedback.yml` to `.github/ISSUE_TEMPLATE/` so the no-JS anchor works.
5. Wire the integrations: 404 page → `FleetFeedback.open({type:'fix-page', extra:'Missing URL: …'})`; error boundary → `open({type:'fix-page', extra: stack})`; "Suggest an edit" → `data-fleet-feedback-open data-type="improve-page"`.

## Contract (what an issue looks like)

Title `[<type label>] <page title>`. Body: **Description** · **Page context** table · **Environment** table · **Console & error logs** (`<details>`) · **Agent directive** (agent types) · footer with `<!-- fleet-feedback v1 type=<id> -->`. Labels = marker + type labels; assignee = `copilot` for agent types. URL budget 7000 chars, trimmed logs → directive → environment, clipboard fallback when trimmed or pop-up blocked.

## Attributes

`repo` (required) · `branch` · `source` · `page-title` · `labels` · `assignee` · `mode` (`url`|`proxy`) · `endpoint` · `capture-logs` · `log-limit` · `fab` · `label` · `env` · `types` (URL to JSON array; or an inline `<script type="application/json">` child).

## Theming

Reads `--fleet-color-{ink,bg-elevated,ink-muted,border,primary}`, `--fleet-radius-lg`, `--fleet-shadow-{lg,focus}`, `--fleet-layer-{fab-feedback,feedback-modal}`, `--fleet-space-fab-{offset,size,gap}`, `--fleet-font-sans`, `--fleet-motion-base`; each falls back to the zer0-mistakes / Bootstrap variable, then to a literal. Respects `prefers-reduced-motion`.
