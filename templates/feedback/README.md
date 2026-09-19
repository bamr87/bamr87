# templates/feedback — the universal feedback widget kit

> `<fleet-feedback>`: one component that gives any page, in any stack, an "Improve this page" button which files a prefilled GitHub issue carrying page context, environment, and the console errors that led up to the report. Spec: [`specs/FEEDBACK.md`](../../specs/FEEDBACK.md) (UPS-FB).

| File | Purpose |
| --- | --- |
| `fleet-feedback.js` | The component, in three layers: the capture buffer, `FleetFeedbackCore` (the issue contract as pure functions), and `<fleet-feedback>` (the default dialog). Zero dependencies, shadow DOM, native `<dialog>`, token-aware (`--fleet-*` with `--zer0-*`/`--bs-*` fallbacks). |
| `capture.js` | The buffer alone, for `<head>`. Byte-identical to the block inside `fleet-feedback.js`. |
| `feedback_types.yml` | The request-type taxonomy (also embedded in the JS as the fallback). Type labels map onto the fleet issue-pipeline label set. |
| `page_feedback.yml` | The no-JS twin: a GitHub issue form the inline anchor points at, with the same sections. Copy to `.github/ISSUE_TEMPLATE/`. |
| `adapters/jekyll.html` | Include for Jekyll sites not on the zer0-mistakes theme (and MkDocs overrides). |
| `adapters/FeedbackButton.tsx` | React/Next wrapper, plus `openFeedback()` and `breadcrumb()` for the error boundary, 404 route, and fetch wrapper. |
| `adapters/nextjs.tsx` | `FeedbackCapture` — installs the buffer `beforeInteractive` from the App Router root layout. |
| `adapters/django.html` | Django template snippet (translate 1:1 to ERB for Rails). |
| `tests/contract.test.mjs` | 25 contract tests. `npm test` — `node:test`, no dependencies. |
| `VERSION` · `archive/` | Kit provenance, changelog, and the shapes `--upgrade` recognises as machine-seeded. |

## Install

The fan-out does all of this for a fleet repo:

```bash
tools/fanout.sh --kit feedback --target <name> --apply
```

By hand, in any stack:

1. Vendor `capture.js` and `fleet-feedback.js` into the repo's static assets (`assets/js/`, `public/`, `static/js/`). Never hot-link the hub.
2. Load `capture.js` **first, in `<head>`**, and `fleet-feedback.js` before `</body>`. The split is the point: a buffer installed after hydration reports a clean console for exactly the failures worth reporting.
3. Mount the element once in the shell with at least `repo="owner/name"`. Use the adapter for your stack.
4. Create the labels — `page-feedback`, `bug`, `feature`, `docs`, `question`, `area:a11y`, `area:perf` (`gh label create …`). **GitHub silently drops unknown labels** from a prefilled URL: no error, no warning, the label is simply gone.
5. Copy `page_feedback.yml` to `.github/ISSUE_TEMPLATE/` so the no-JS anchor works.
6. Wire the integrations: 404 page → `FleetFeedback.open({type:'fix-page', extra:'Missing URL: …'})`; error boundary → `open({type:'fix-page', extra: stack})`; "Suggest an edit" → `data-fleet-feedback-open data-type="improve-page"`.

## Contract (what an issue looks like)

Title `[<type label>] <page title>`. Body, in this order, each under a `##` heading: **Description** · **Page context** table · **Environment** table · **Console & error logs** (`<details>`) · **Agent directive** (agent types only) · footer with `<!-- fleet-feedback v1 type=<id> -->`. Labels = marker + type labels; assignee = `copilot` for agent types. URL budget 7000 chars, trimming logs → directive → environment, with the full body copied to the clipboard whenever anything was trimmed or the pop-up was blocked. Nothing is ever silently lost.

That hidden marker is the load-bearing part: the issue pipeline's intake tier reads it and treats the report as already structured instead of re-templating it.

## Two UIs, one contract

`FleetFeedbackCore` is pure — explicit input object in, strings out, no DOM and no globals — so it runs under Node in the tests, and so a host with its own dialog can produce a byte-identical issue by calling it. The zer0-mistakes theme does exactly that: it vendors this file for the buffer and the core, keeps its Bootstrap modal and its AI triage step, and never writes the `<fleet-feedback>` tag. Change the contract here and both widgets move together.

```js
FleetFeedbackCore.buildIssue({ type, description, extra, page, environment, logs, config })
  // -> { title, body, sections, labels, assignees, marker, type }
FleetFeedbackCore.buildUrl(issue, { repo })
  // -> { url, trimmed, overBudget, fullBody }
```

## Attributes

`repo` (required) · `branch` · `source` · `route` · `page-title` · `labels` (csv markers) · `assignee` (`''` disables) · `mode` (`url` | `proxy` | `postmessage`) · `endpoint` · `capture-logs` · `log-limit` · `fab` · `label` · `env` · `app-version` · `types` (URL of a JSON array; or an inline `<script type="application/json">` child).

`url` mode needs no token — the reader submits the prefilled form under their own account. `proxy` mode POSTs `{title, body, labels, assignees, type}` to an endpoint that holds the token server-side, falling back to the URL path rather than losing the report. `postmessage` mode hands the issue to a sandboxed host (a VS Code extension) that has no `window.open` of its own.

## JS API

```js
FleetFeedback.open({ type: 'fix-page', extra: `Missing route: ${pathname}` });
FleetFeedback.breadcrumb('net', `POST /api/analysis → 502 (1243ms) req=${id}`);
window.__fleetFeedback.snapshot();   // the buffer, newest last
```

Any element with `[data-fleet-feedback-open]` (plus optional `data-type`) opens the dialog. Make it a real `issues/new` link and it keeps working when the script does not.

## Privacy

No cookies, no analytics, no request of any kind until the reader submits. The environment section carries no identity, IP, or form contents. Every captured line is redacted before it enters the ring buffer — bearer tokens, API keys, JWTs, GitHub tokens, email addresses — and the reader previews the logs and can untick them before filing.

## Theming

Reads `--fleet-color-{ink,bg-elevated,ink-muted,border,primary}`, `--fleet-radius-lg`, `--fleet-shadow-{lg,focus}`, `--fleet-layer-{fab-feedback,feedback-modal}`, `--fleet-space-fab-{offset,size,gap}`, `--fleet-font-sans`, `--fleet-motion-base`; each falls back to the zer0-mistakes / Bootstrap variable, then to a literal. Respects `prefers-reduced-motion`.

## Changing the kit

- The capture block lives in `capture.js` and is spliced into `fleet-feedback.js`. Edit it in **one** place; the parity test fails when the copies diverge.
- Snapshot the outgoing `fleet-feedback.js` into `archive/` **before** editing it, or every deployed copy reads as hand-modified and `--upgrade` silently stops reaching the fleet.
- `npm test` before committing. The contract these tests lock is what ~25 repositories file issues against.
