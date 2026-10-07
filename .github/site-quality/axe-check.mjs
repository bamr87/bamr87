#!/usr/bin/env node
// =============================================================================
// axe-check.mjs — axe-core (via Playwright) over the configured pages, at each
// configured viewport (default 390 px + 1366 px). COLLECT ONLY: every violation
// node is written to <reports>/axe/axe-raw.json; report.mjs grades them against
// the caller's `axe.fail_on` and allowlist, so all gate logic lives in one place.
//
// Usage: node axe-check.mjs --config <resolved.json> --base <url> --reports <dir>
// Env: PW_CHANNEL (default 'chrome' = the runner's Google Chrome; set it empty
// to use Playwright's own Chromium after `npx playwright install chromium`).
// Lifted from bamr87/lifehacker.dev#683 / bamr87/it-journey#790 a11y-check.mjs.
// =============================================================================
import { chromium } from 'playwright';
import { AxeBuilder } from '@axe-core/playwright';
import { mkdirSync, writeFileSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { parseArgs } from 'node:util';

const { values: a } = parseArgs({ options: { config: { type: 'string' }, base: { type: 'string' }, reports: { type: 'string' } } });
const cfg = JSON.parse(readFileSync(a.config, 'utf8'));
const BASE = a.base.replace(/\/+$/, '');
const OUT = `${a.reports}/axe`;
mkdirSync(OUT, { recursive: true });
const axeVersion = createRequire(import.meta.url)('axe-core/package.json').version;

// Allowlist selectors are matched IN THE BROWSER (element.matches / closest),
// so `selector: a.icon-only` covers a node axe reports as plain `a`.
const allowSelectors = [...new Set(cfg.allowlist.entries.map((e) => e.selector).filter(Boolean))];
const matchedSelectors = (tab, target) => tab.evaluate(({ target: t, sels }) => {
  let el = null;
  try { el = document.querySelector(t); } catch { return []; }
  if (!el) return [];
  return sels.filter((s) => { try { return el.matches(s) || !!el.closest(s); } catch { return false; } });
}, { target, sels: allowSelectors }).catch(() => []);

const channel = process.env.PW_CHANNEL ?? 'chrome';
const browser = await chromium.launch({ channel: channel || undefined, args: ['--no-sandbox'] });
const pages = [];
for (const vp of cfg.viewports) {
  const context = await browser.newContext({
    viewport: { width: vp.width, height: vp.height },
    isMobile: !!vp.mobile,
    hasTouch: !!vp.mobile,
    deviceScaleFactor: vp.mobile ? 3 : 1,
    reducedMotion: 'reduce',
  });
  for (const page of cfg.axe.pages) {
    const tab = await context.newPage();
    const entry = { page, viewport: vp.name, url: BASE + page, violations: [] };
    try {
      const resp = await tab.goto(entry.url, { waitUntil: 'load', timeout: 60_000 });
      await tab.waitForLoadState('networkidle', { timeout: 10_000 }).catch(() => {});
      if (!resp || resp.status() >= 400) entry.error = `HTTP ${resp ? resp.status() : 'no response'}`;
      else {
        const res = await new AxeBuilder({ page: tab }).withTags(cfg.axe.tags).analyze();
        for (const v of res.violations) {
          const nodes = [];
          for (const n of v.nodes) {
            const target = [].concat(n.target).flat().join(' ');
            const node = { target, html: (n.html || '').slice(0, 300) };
            if (allowSelectors.length) node.matched = await matchedSelectors(tab, target);
            nodes.push(node);
          }
          entry.violations.push({ rule: v.id, impact: v.impact, help: v.help, helpUrl: v.helpUrl, tags: v.tags, nodes });
        }
      }
    } catch (e) {
      entry.error = `navigation failed: ${String(e.message).split('\n')[0]}`;
    }
    pages.push(entry);
    console.log(`axe ${entry.viewport} ${page}: ${entry.error || `${entry.violations.length} violated rule(s)`}`);
    await tab.close();
  }
  await context.close();
}
await browser.close();
writeFileSync(`${OUT}/axe-raw.json`, JSON.stringify({ axe: axeVersion, tags: cfg.axe.tags, pages }, null, 2));
