# UPS-FE — Frontend: design system, core components, UX standards

> Every user-facing surface in the fleet — Jekyll site, React/Next app, Django/Rails template, VS Code webview — ships the same token vocabulary, the same core component set, and passes the same UX gate. Visual identity may differ per skin; structure and behaviour do not.

Evidence base: the fleet has **four incompatible token vocabularies** for the same concepts (`--zer0-*`/`--bs-*`, `--c-*`/`--sp-*`, Tailwind `@theme --color-*`, `--z-*`), three toast systems, three error boundaries, three fetch wrappers. Skip links exist in 3 surfaces; OG meta outside Jekyll in 1; analytics outside Jekyll in 0; a feedback widget in 1 (and disabled on all 7 sites that inherit it). zer0-mistakes already holds a formal, CI-checked design system (`_design-system/`, `SYNC.md`, `scripts/design-system-check.rb`) and a component contract (`_includes/components/README.md`). law-ai holds a 13-rule machine-checked UX audit (`scripts/ux_audit.py`). Those are the reference implementations.

## Design tokens

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-FE-01 | MUST | site, app, ext | One token file defines every design value as CSS custom properties under the fleet prefix **`--fleet-*`** (Jekyll keeps `--zer0-*` as an alias layer): `color`, `space`, `type`, `radius`, `shadow`, `motion`, `layer`, `breakpoint`. Colour literals appear **nowhere else** — enforced by a test (lift `gitorio/app/src/theme.test.ts`) or a CI grep (lift zer0-cms `tokens.css` rule). | token file + test | `templates/design-tokens/` (gap; source `zer0-mistakes/_design-system/tokens/*.css`) |
| UPS-FE-02 | MUST | site, app, ext | Semantic colour roles, not palette names: `primary secondary accent success info warning danger bg bg-elevated bg-muted ink ink-muted border link link-hover code-bg code-ink`. Skins re-map roles; components consume roles. | token names | same |
| UPS-FE-03 | MUST | site, app, ext | Spacing scale `--fleet-space-0..5` = 0/.25/.5/1/1.5/3 rem plus `section` and `container-x` fluid tokens; radius `sm base lg xl pill circle`; shadow `xs sm md lg focus`; motion `fast 120ms / base 200ms / slow 320ms` with `cubic-bezier(0.2,0,0,1)`, collapsing to `0.01ms` under `prefers-reduced-motion`. | token values | same |
| UPS-FE-04 | MUST | site, app, ext | A **named z-index scale** (`--fleet-layer-sticky 1020 · header 1030 · backdrop 1040 · offcanvas 1045 · fab 1050–1060 · modal 1055 · popover 1070 · tooltip 1080 · toast 1090 · consent 1095 · feedback-modal 1096 · skip-link 1100`). Hand-written `z-index` numbers fail the UX gate. | tokens + gate rule R4 | same |
| UPS-FE-05 | MUST | site, app, ext | Typography: system font stacks by default (`system-ui` sans, `ui-monospace, SFMono-Regular, Menlo` mono); no webfont without a documented reason; fluid `clamp()` headings; weights 400/500/600/700; line heights 1.2/1.55/1.75. | tokens | same |
| UPS-FE-06 | MUST | site, app | Colour modes `light`, `dark`, `auto` via `data-theme` (Bootstrap sites: `data-bs-theme`) on `<html>`, persisted in `localStorage`, defaulting to `prefers-color-scheme`, set by an inline pre-paint script so there is no flash. Brand-locked surfaces may set `color_mode_lock`. VS Code webviews derive from `--vscode-*` through the token file only. | init script + toggle | `templates/design-tokens/color-mode-init.js` (gap) |
| UPS-FE-07 | SHOULD | site, app | Skins are a token re-map only (`[data-theme-skin]`), each shipping WCAG-AA link colours for both modes; the fleet skin set is the zer0-mistakes seven (`air aqua dirt neon mint plum sunrise`). | skin file | zer0-mistakes `_sass/theme/_skins.scss` |
| UPS-FE-08 | MUST | site, app | Bootstrap 5.3 (Jekyll) or Tailwind 4 (React/Next) are the two sanctioned utility frameworks; either consumes the token file (`@theme` maps to `--fleet-*`). A repo does not load two frameworks. | one framework | — |
| UPS-FE-09 | MUST | site, app, ext | The token file has a portable plain-CSS twin checked for drift in CI when the source is SCSS/Tailwind (lift `_design-system/SYNC.md` + `design-system-check.rb`). | sync check | zer0-mistakes |

## Core component set

Every UI surface ships these. Each is already proven in the fleet; the seed column names where it is lifted from. Components follow the **component contract** (FE-30).

| id | level | applies | component | requirement | seed / source |
| --- | --- | --- | --- | --- | --- |
| UPS-FE-10 | MUST | site, app | **AppShell** | Header/topbar with branding and primary nav, exactly one `<main id="main-content">`, footer, mobile drawer; labelled landmarks (`<nav aria-label>`, `<aside aria-label>`); optional left nav / right TOC columns. | zer0 `_layouts/root.html`; law-ai `components/shell/AppShell.tsx`; fredgar `layout/AppShell.tsx` |
| UPS-FE-11 | MUST | site, app | **Skip link** | First focusable element, `href="#main-content"`, visible on focus, on the skip-link layer. | zer0 `core/header.html`; law-ai AppShell |
| UPS-FE-12 | MUST | site, app | **Theme toggle** | Light/dark/auto segmented control in the header or settings panel; keyboard operable; announces state. | zer0 `components/halfmoon.html`; fredgar ThemeToggle |
| UPS-FE-13 | MUST | site, app | **Feedback widget** | The universal "Improve this page / Report a problem" FAB + dialog that files a prefilled GitHub issue (full contract in [FEEDBACK.md](FEEDBACK.md)). | `templates/feedback/` |
| UPS-FE-14 | MUST | site, app | **Edit / source links** | On every content page: **Edit on GitHub** (`blob/<branch>/<path>`), **Copy link**, and the feedback trigger, as real anchors that work without JS. | zer0 `content/intro.html`; cv `builder/html.ts` `editUrl` |
| UPS-FE-15 | MUST | site, app | **404 page** | A real not-found route/page with search or nav suggestions and a "report this URL" link that opens the feedback widget pre-typed as `fix-page`. No `*`→`/` redirects. | zer0 `_layouts/404.html`; law-ai `not-found.tsx`; fredgar `NotFound.tsx` |
| UPS-FE-16 | MUST | app | **Error boundary + route states** | Recover-in-place fallback (Try again · Go home · Report via feedback widget with the error attached); `loading`/`error`/`not-found` states per route. | fredgar `ErrorBoundary.tsx`; law-ai `app/(app)/{loading,error}.tsx` |
| UPS-FE-17 | MUST | app | **State set** | `Loading`, `Skeleton`, `EmptyState`, `ErrorState`, and a `Query<T>` wrapper that maps one request to all four. | fredgar `components/ui/states.tsx` |
| UPS-FE-18 | MUST | site, app | **Toast / announcer** | One toast system: `role="status" aria-live="polite"`, variants success/error/info, keyboard-dismissable, timeout respects reduced motion. Replaces `alert()`. | fredgar `lib/toast.tsx`; zer0 `ui-helpers.js`; cv-builder-pro `sonner` (acceptable) |
| UPS-FE-19 | MUST | app | **Form field** | `Field(label, hint, error, required)` primitive with `aria-describedby` wiring; validation via `react-hook-form` + `zod` in React, the framework's forms in Django/Rails. Errors are inline and announced. | aieo `ui/Field.tsx` + cv-builder-pro `ui/form.tsx` |
| UPS-FE-20 | MUST | app | **HTTP client** | One client module with one `ApiError` shape (BE-40); feature code never calls `fetch` directly. | fredgar `lib/http.ts` + aieo `services/api.ts` merged |
| UPS-FE-21 | SHOULD | site, app | **Search** | `⌘/Ctrl-K` and `/` open a search modal over a static index (`/search.json`) or the app's search API; results keyboard navigable. | zer0 `components/search-modal.html`; fredgar ⌘K |
| UPS-FE-22 | SHOULD | site, app | **Keyboard shortcuts + help** | `?` opens a shortcuts modal; shortcuts documented in one place; never override browser defaults. | zer0 `modules/navigation/keyboard.js` |
| UPS-FE-23 | SHOULD | site | **TOC, breadcrumbs, back-to-top** | Right-column TOC with scroll-spy on long pages; `BreadcrumbList` microdata breadcrumbs; back-to-top FAB. | zer0 `content/toc.html`, `navigation/breadcrumbs.html`, `back-to-top.js` |
| UPS-FE-24 | MUST | site, app | **Consent + analytics wrapper** | No tracker fires before consent; categories essential/analytics/marketing; 365-day persistence; DNT/GPC honoured; production-only gate. Fleet default analytics is **PostHog** (privacy config) with GA4 optional. | zer0 `components/cookie-consent.html`, `analytics/posthog.html` |
| UPS-FE-25 | MUST | site, app | **Head/meta block** | `<title>`, `description`, canonical, `og:title/description/image/url/type`, `twitter:card`, favicon set + `theme-color`, `manifest` for apps. Jekyll via `jekyll-seo-tag` + `content/seo.html`; React/Next via a `Head`/`Metadata` helper; Django via `{% block meta %}`. | zer0 `core/head.html`; barodybroject `base.html` |
| UPS-FE-26 | SHOULD | site, app | **Comments** | giscus (GitHub Discussions) on article-type pages, theme-following, opt-in per page (`comments: true`). | zer0 `content/giscus.html` |
| UPS-FE-27 | SHOULD | site, app | **Copy affordances** | Copy button on every code block and table (CSV), with the toast announcer. | zer0 `code-copy.js`, `table-copy.js` |
| UPS-FE-28 | MAY | site, app | **Settings panel** | An offcanvas with Appearance (mode, primary colour), Site, Developer tabs; runtime overrides persisted to `localStorage`. | zer0 `components/info-section.html` |
| UPS-FE-29 | MAY | app | **PWA** | `manifest.webmanifest` + minimal service worker for installable apps. | zer0-image-generator `app/views/pwa/` |

## Component contract

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-FE-30 | MUST | site, app, ext | Every component has a doc header (purpose, path, parameters with types and defaults, returns, example); parameter defaults are assigned at the top; filenames kebab-case (`PascalCase.tsx` in React); params snake_case (Liquid) / camelCase (TS); theme-owned classes prefixed `fleet-<component>` (`zer0-` alias in the theme). | header present | zer0 `_includes/components/README.md` |
| UPS-FE-31 | MUST | site, app, ext | Every component satisfies at least one of: renders a semantic landmark; exposes `aria-label`/`aria-labelledby`/`aria-describedby`; inherits from a documented parent landmark. Icon-only buttons have a visible label or `aria-label`; decorative icons `aria-hidden="true"`. | review + gate | same |
| UPS-FE-32 | MUST | site, app, ext | Components consume tokens, never raw values; a missing token is proposed in the token file, not hardcoded. | grep | same |
| UPS-FE-33 | SHOULD | site, app | A component catalog page renders every component with its variants (`component-showcase` / `_design-system/**/*.card.html` pattern; Storybook is acceptable in React apps but not required). | catalog route | zer0 `components/component-showcase.html` |
| UPS-FE-34 | SHOULD | site, app | A feature registry (`features/features.yml`: id → layouts/includes/styles/tests) and `Feature: <ID>` markers in component files give traceability from component to test to doc. | registry present | zer0 `features/features.yml` |
| UPS-FE-35 | MUST | site | Consumer sites override the theme only through the four extension hooks (`custom/head.html`, `custom/body-start.html`, `custom/footer.html`, `custom/body-end.html`) and `user-overrides.css/js`; copying theme includes into a consumer is a deviation. | no shadowed theme files | zer0 `_includes/custom/` |

## Content and front matter (sites)

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-FE-40 | MUST | site | Every page carries `title`, `description`, `permalink` (or a collection default), `lastmod`; posts add `date`, `categories`, `tags`, `author`; drafts use `draft:`. Sidebar resolution is page → collection → site. | `--strict_front_matter` build | zer0 `frontmatter.json` |
| UPS-FE-41 | SHOULD | site | Each post has a 4:3 preview image under `assets/images/previews/<slug>.png` used as `og:image`. | file present | zer0 preview generator |
| UPS-FE-42 | MUST | site | `jekyll-seo-tag`, `jekyll-sitemap`, `jekyll-feed`, `jekyll-redirect-from`, `jekyll-include-cache` are enabled; `/feed.xml` and `/sitemap.xml` exist; `aliases:` handles moved URLs. | `_config.yml` | — |
| UPS-FE-43 | SHOULD | site | English under `pages/**` is the only human-maintained language; alternates are generated (`translate.yml`) with `hreflang` alternates and a translation notice. | config | zer0 `translate.yml` |

## Accessibility and performance

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-FE-50 | MUST | site, app, ext | WCAG 2.1 AA: one `:focus-visible` ring token used everywhere; visible focus never removed; contrast ≥ 4.5:1 for text in every mode and skin; `maximumScale` ≥ 5 in the viewport meta; all interactive controls keyboard reachable; modals trap focus and close on Escape. | gate rules R5/R11 + axe | law-ai `ui/base.css`; zer0 `utilities/_focus.scss` |
| UPS-FE-51 | MUST | site, app | `prefers-reduced-motion` disables non-essential motion (token collapse, FE-03). | tokens | — |
| UPS-FE-52 | MUST | site, app | Exactly one scroll container owns the viewport; sticky offsets come from tokens; no horizontal page scroll — wide content scrolls inside its own container. | gate rules R1/R2/R9 | law-ai `ux_audit.py` |
| UPS-FE-53 | SHOULD | site, app | Lighthouse budgets in CI: performance ≥ 90 on the home route, accessibility ≥ 95, no layout shift > 0.1; JS budget 200 KB gzipped for sites, documented per app. | CI step | `templates/ux-audit/` (gap) |
| UPS-FE-54 | SHOULD | site, app | Images lazy-load with intrinsic dimensions; vendored CSS/JS pinned by a manifest (`vendor-manifest.json`), never two copies of one framework. | review | zer0 `vendor-manifest.json` |

## The UX audit gate

| id | level | applies | requirement | satisfied by | seed |
| --- | --- | --- | --- | --- | --- |
| UPS-FE-60 | SHOULD | site, app | A machine-checked UX audit runs in CI with the fleet rule set: **R1** one scroller · **R2** viewport ownership · **R3** single `<main>` · **R4** z-scale only · **R5** focus indicator · **R6** landmark labels · **R7** page layout primitive · **R8** route states · **R9** sticky offsets · **R10** composite widget names · **R11** control names · **R12** shared-CSS drift · **R13** token literal leak. An `ux-audit: exempt — <reason>` marker is the escape hatch. | script + CI step | `templates/ux-audit/` (gap; source `law-ai/scripts/ux_audit.py`) |
| UPS-FE-61 | SHOULD | site, app | Playwright visual specs cover the AppShell, both colour modes, the feedback dialog, and the 404 page. | specs present | zer0 `test/visual/features/` |
