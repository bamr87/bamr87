# templates/site-quality — site quality kit

> The fleet standard for scanning a Jekyll site's quality the same way everywhere: Lighthouse CI, axe-core at 390 px and 1366 px, and pa11y contrast (WCAG 1.4.3), run by ONE reusable workflow and graded by each repo's own config. Lifted from the two green implementations, bamr87/lifehacker.dev#683 and bamr87/it-journey#790. Spec: [`specs/QUALITY.md`](../../specs/QUALITY.md) "Site quality" (UPS-QA-60..63, draft, `rollout: warn`); checker contract [`specs/QUALITY.contract.yml`](../../specs/QUALITY.contract.yml).

| Template | Seeds | Purpose |
| --- | --- | --- |
| `site-quality.yml` | `.github/workflows/site-quality.yml` | Thin caller of the hub's reusable [`site-quality.yml`](../../.github/workflows/site-quality.yml), pinned `@v1`, `mode: build`, on every PR and push to the default branch. |
| `site-quality.template.yml` | `.github/site-quality.yml` (only when absent) | The repo's config: pages, viewports, Lighthouse budgets, axe `fail_on`, contrast `max`, and the known-issue allowlist. Seeded report-only: nothing in it fails a run. |
| `site-quality.schema.json` | (stays in the hub) | JSON Schema 2020-12 for the config. The workflow validates the caller's file against it before anything runs. |
| `fixtures/` | (stays in the hub) | `pass-site/` and `fail-site/` (tiny Jekyll sites the self-test scans), `configs/valid/` and `configs/invalid/` (schema fixtures). |
| `test_site_quality_kit.py` | — | Kit test: schema vs fixtures, caller pin, tokens, lenient template, exact runtime pins. `--target <repo>` validates a repo's config. |
| `VERSION` | — | Kit provenance + changelog. |

## Seed it

```bash
tools/fanout.sh --kit site-quality --target <name>            # dry run: branch + diffstat
tools/fanout.sh --kit site-quality --target <name> --apply    # push + PR (ci/site-quality)
```

Jekyll repos only (a root `_config.yml`). Additive-only: an existing `.github/site-quality.yml` is never overwritten. A repo with its own site-quality workflow (lifehacker.dev, it-journey) migrates by hand: move its thresholds into `.github/site-quality.yml`, then replace the workflow with the caller.

## What a run does

| Step | build mode | url mode |
| --- | --- | --- |
| Config | validated against `site-quality.schema.json`; invalid = the job fails naming the key | same |
| Site | `remote_theme` resolved to a commit SHA (`git ls-remote`), the build pinned to it (`remote_theme: owner/repo@<sha>`), `_site` served on 127.0.0.1:4000. No theme cache unless `theme-cache: true`, and then keyed to the SHA with no restore-keys. | the live base URL (`base-url` input or `site.base_url`) |
| Scans | `lhci collect` (+ `assert` when the config has budgets), axe-core per page per viewport, pa11y contrast | same |
| Report | `report.json` (`site-quality-report/v1`) + `summary.md` + Lighthouse HTML/JSON + raw axe/pa11y results in the artifact (`site-quality-report` by default); the job summary carries the same tables and the resolved theme ref | same |
| Gate | fails for findings the config marks `error`, and for a collector that crashed while its check is gated (`gate: false` reports only). An invalid config or a failed build fails the job regardless. | same |

The runtime (`.github/site-quality/`) is pinned exactly (`@lhci/cli`, `axe-core`, `@axe-core/playwright`, `pa11y`, `playwright`, `ajv`, `yaml`) with a committed `package-lock.json`, and installed with `npm ci --ignore-scripts`. Dependabot moves it, except minor/major bumps of axe-core, @axe-core/playwright and @lhci/cli, which add rules or move Lighthouse and are reviewed and released by hand. `lighthouse.public_upload` only takes effect in a public repo; a private or internal repo's Lighthouse reports stay in the run artifact. The runner always comes from the same hub commit as the workflow the caller pinned.

## Config in one screen

```yaml
schema: site-quality/v1         # required const; quoted dates, like .github/sdlc.yml
pages: [/, /about/]
lighthouse:
  categories: { accessibility: { min: 0.9, level: error } }
  metrics: { largest-contentful-paint: { max: 4000, level: warn } }
axe:
  fail_on: { tags: [wcag2a, wcag2aa, wcag21a, wcag21aa], impacts: [critical, serious] }
contrast:
  pages: [{ path: /, max: 0 }]
allowlist:
  on_expired: warn              # error once the rollout ends
  entries:
    - rule: color-contrast      # axe rule id, `contrast`, or a Lighthouse id like categories:performance
      selector: ".site-footer .muted"   # a CSS selector, matched in the browser (the node or an ancestor)
      page: /
      reason: Footer palette is replaced in the theme refresh.
      issue: https://github.com/OWNER/REPO/issues/123
      until: "2026-12-31"
```

Allowlist matching: `rule` must equal the finding's rule; `page` is an exact path, `*`, or a prefix ending in `*`, and `*` or a prefix requires a `selector`; `selector` is a CSS selector matched in the browser against the failing node and its ancestors (`element.matches` / `closest`), never a text or HTML substring. Lighthouse findings have no nodes, so a Lighthouse entry uses an exact `page`. A crashed collector (`collector-crashed`) cannot be allowlisted.

Levels are `warn` (reported) and `error` (fails the job). An allowlisted finding is reported as a known issue and never fails. An entry past `until` is reported at `allowlist.on_expired` (the `expired-allowlist-level` input overrides it fleet-wide). An entry that matched nothing is listed for deletion.

## Versioning

Callers pin `@v1`. Under [`docs/WORKFLOW-VERSIONING.md`](../../docs/WORKFLOW-VERSIONING.md), anything that could turn a green caller red (a stricter default, a new required config key, a runtime bump that adds failing axe rules to a gated caller) needs a new major. Never pin a custom tag such as `site-quality-v1`: conformance accepts `@vN`, `@vX.Y.Z` or a full SHA only.
