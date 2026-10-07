#!/usr/bin/env node
// =============================================================================
// lighthouse-config.mjs — turn the resolved site-quality config into an LHCI
// config (lighthouserc.json): URLs, runs, form factor, and one assertMatrix
// entry per page. Every assertion comes from the caller's config; with none,
// the run collects and reports only (has_assertions=false skips `lhci assert`).
//
// Usage: node lighthouse-config.mjs --config <resolved.json> --base <url>
//          --out <lighthouserc.json> --reports <dir>
// =============================================================================
import { readFileSync, writeFileSync, appendFileSync } from 'node:fs';
import { parseArgs } from 'node:util';

const KiB = 1024;
const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** LHCI assertions for one page: top-level budgets with that page's override applied. */
export function assertionsFor(lh, page) {
  const pick = (key) => ({ ...(lh[key] || {}), ...((lh.overrides || []).find((o) => o.page === page)?.[key] || {}) });
  const median = { aggregationMethod: 'median' };
  const out = {};
  for (const [id, b] of Object.entries(pick('categories'))) out[`categories:${id}`] = [b.level, { ...median, minScore: b.min }];
  for (const [id, b] of Object.entries(pick('metrics'))) out[id] = [b.level, { ...median, maxNumericValue: b.max }];
  for (const [id, lvl] of Object.entries(pick('audits'))) out[id] = lvl === 'off' ? 'off' : [lvl, { ...median, minScore: 1 }];
  for (const [type, b] of Object.entries(pick('sizes'))) out[`resource-summary:${type}:size`] = [b.level, { ...median, maxNumericValue: Math.round(b.max_kib * KiB) }];
  return out;
}

/** URL for a page under base, and the pattern LHCI matches it with (trailing slash optional). */
export function pageUrl(base, page) { return base.replace(/\/+$/, '') + page; }
export function urlPattern(base, page) { return `^${escape(pageUrl(base, page).replace(/\/+$/, ''))}/?$`; }

export function buildRc(cfg, base, reports) {
  const lh = cfg.lighthouse;
  const matrix = lh.pages.map((page) => ({ matchingUrlPattern: urlPattern(base, page), assertions: assertionsFor(lh, page) }))
    .filter((m) => Object.values(m.assertions).some((v) => v !== 'off'));
  const settings = { chromeFlags: '--no-sandbox', skipAudits: lh.skip_audits };
  if (lh.form_factor === 'desktop') settings.preset = 'desktop';
  else Object.assign(settings, { formFactor: 'mobile', throttlingMethod: 'simulate' });
  return {
    rc: {
      ci: {
        collect: { url: lh.pages.map((p) => pageUrl(base, p)), numberOfRuns: lh.runs, settings },
        ...(matrix.length ? { assert: { assertMatrix: matrix } } : {}),
        upload: {
          target: 'filesystem',
          outputDir: `${reports}/lighthouse`,
          reportFilenamePattern: '%%HOSTNAME%%-%%PATHNAME%%-%%DATETIME%%.report.%%EXTENSION%%',
        },
      },
    },
    hasAssertions: matrix.length > 0,
  };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const { values: a } = parseArgs({ options: { config: { type: 'string' }, base: { type: 'string' }, out: { type: 'string' }, reports: { type: 'string' } } });
  const cfg = JSON.parse(readFileSync(a.config, 'utf8'));
  const { rc, hasAssertions } = buildRc(cfg, a.base, a.reports);
  writeFileSync(a.out, JSON.stringify(rc, null, 2));
  console.log(`lighthouserc: ${rc.ci.collect.url.length} URL(s) x ${rc.ci.collect.numberOfRuns} run(s), ${cfg.lighthouse.form_factor}, assertions: ${hasAssertions ? 'yes' : 'none (report-only)'}`);
  if (process.env.GITHUB_OUTPUT) appendFileSync(process.env.GITHUB_OUTPUT, `has_assertions=${hasAssertions}\n`);
}
