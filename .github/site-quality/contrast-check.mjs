#!/usr/bin/env node
// =============================================================================
// contrast-check.mjs — pa11y (HTML_CodeSniffer, WCAG2AA) colour contrast.
// -----------------------------------------------------------------------------
// axe returns "incomplete" for most text on layered/gradient backgrounds, so it
// can't gate contrast on themes like zer0-mistakes. HTML_CodeSniffer does compute
// it; this keeps ONLY its WCAG 1.4.3 results (G18 / G145) for `contrast.pages`,
// after hiding `contrast.hide_elements`. COLLECT ONLY: report.mjs applies each
// page's `max` and the allowlist. Writes <reports>/contrast/contrast-raw.json.
//
// Allowlist selectors are matched IN THE BROWSER, as in axe-check.mjs: after
// pa11y, each failing node's selector is resolved on the same page with
// Playwright and checked against every allowlist selector (element.matches /
// closest); the result is the node's `matched` list. No text matching.
//
// Usage: node contrast-check.mjs --config <resolved.json> --base <url> --reports <dir>
// Env: CHROME_PATH (default: the runner's Google Chrome); PW_CHANNEL as in
// axe-check.mjs (only used when the config has allowlist selectors).
// Lifted from bamr87/lifehacker.dev#683 / bamr87/it-journey#790 contrast-check.mjs.
// =============================================================================
import pa11y from 'pa11y';
import { chromium } from 'playwright';
import { mkdirSync, writeFileSync, readFileSync, existsSync } from 'node:fs';
import { parseArgs } from 'node:util';

const { values: a } = parseArgs({ options: { config: { type: 'string' }, base: { type: 'string' }, reports: { type: 'string' } } });
const cfg = JSON.parse(readFileSync(a.config, 'utf8'));
const BASE = a.base.replace(/\/+$/, '');
const OUT = `${a.reports}/contrast`;
mkdirSync(OUT, { recursive: true });
const executablePath = process.env.CHROME_PATH || ['/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium']
  .find((p) => existsSync(p));
const CONTRAST = /Guideline1_4\.1_4_3\.(G18|G145)/;
const { pages, hide_elements: hideElements, viewport } = cfg.contrast;

const allowSelectors = [...new Set(cfg.allowlist.entries.map((e) => e.selector).filter(Boolean))];
let browser = null;
const matchAll = async (url, selectors) => {
  if (!allowSelectors.length || !selectors.length) return selectors.map(() => []);
  const channel = process.env.PW_CHANNEL ?? 'chrome';
  browser ||= await chromium.launch({ channel: channel || undefined, args: ['--no-sandbox'] });
  const tab = await browser.newPage({ viewport });
  try {
    await tab.goto(url, { waitUntil: 'load', timeout: 60_000 });
    return await tab.evaluate(({ targets, sels }) => targets.map((t) => {
      let el = null;
      try { el = document.querySelector(t); } catch { return []; }
      if (!el) return [];
      return sels.filter((s) => { try { return el.matches(s) || !!el.closest(s); } catch { return false; } });
    }), { targets: selectors, sels: allowSelectors });
  } catch { return selectors.map(() => []); } finally { await tab.close(); }
};

const results = [];
for (const { path, max } of pages) {
  const entry = { path, max: max ?? null, issues: [] };
  try {
    const r = await pa11y(BASE + path, {
      standard: 'WCAG2AA',
      runners: ['htmlcs'],
      includeWarnings: false,
      includeNotices: false,
      ...(hideElements ? { hideElements } : {}),
      viewport,
      timeout: 120_000,
      chromeLaunchConfig: { executablePath, args: ['--no-sandbox'] },
    });
    entry.issues = r.issues.filter((i) => CONTRAST.test(i.code)).map((i) => {
      const tag = (i.context || '').match(/^<([a-z0-9-]+)/i)?.[1] || i.selector.split(' > ').pop().replace(/:nth-child\(\d+\)/g, '');
      const cls = ((i.context || '').match(/class="([^"]*)"/)?.[1] || '').trim().split(/\s+/).filter(Boolean).slice(0, 3).map((c) => '.' + c).join('');
      const ratio = i.message.match(/contrast ratio of ([\d.]+:1)\./)?.[1] || '?';
      return { selector: i.selector, context: (i.context || '').slice(0, 300), ratio, shape: `${tag}${cls} @ ${ratio}` };
    });
    const matched = await matchAll(BASE + path, entry.issues.map((i) => i.selector));
    entry.issues.forEach((i, n) => { i.matched = matched[n] || []; });
  } catch (e) {
    entry.error = String(e.message).split('\n')[0];
  }
  results.push(entry);
  console.log(`contrast ${path}: ${entry.error || `${entry.issues.length} failure(s)`}`);
}
if (browser) await browser.close();
writeFileSync(`${OUT}/contrast-raw.json`, JSON.stringify({ hide_elements: hideElements, pages: results }, null, 2));
