#!/usr/bin/env node
/**
 * layout_capture.mjs — rendered layout capture for the ux-audit kit (rules L1–L6).
 *
 * For every target × viewport it loads the page in Chromium and writes:
 *   <out>/<id>--<viewport>.json   geometry snapshot: every visible box, the rules it broke, the pattern anchors
 *   <out>/<id>--<viewport>.svg    wireframe drawn from that geometry (violations in red)
 *   <out>/<id>--<viewport>.png    screenshot (skip with --no-png)
 *   <out>/summary.json, summary.md
 *
 * Targets, first match wins:
 *   --targets FILE   JSON array of { url, id?, site?, role?, css? } (the hub writes this from the registry)
 *   --url URL        one or more, repeatable
 *   --manifest FILE  the leaf's ux.yml `surfaces:` (default ./ux.yml), joined to --base-url / preview.ready_url
 *
 * Warn-only by default: findings never change the exit code unless --fail-on asks.
 * Exit 0 ok · 1 --fail-on threshold hit · 2 usage, missing deps, or NOTHING captured
 * (a run that captured nothing is a broken harness, never a clean audit).
 *
 * Requires playwright (and js-yaml for --manifest; a minimal fallback parses the example shape):
 *   npm i -D playwright js-yaml && npx playwright install chromium
 * UX_CHROMIUM_PATH points at a Chromium build when the bundled one is not installed.
 */
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { createRequire } from 'node:module';
import { probe, RULES, VIEWPORTS, SCHEMA } from './layout_probe.mjs';

const require = createRequire(import.meta.url);
export const KIT_VERSION = '0.2.0';

// Hidden before measuring: consent banners and motion make captures unstable.
const STABILISE = '#cookieConsent,.cookie-consent-banner{display:none!important}*,*::before,*::after{animation:none!important;transition:none!important}';

function usage(msg) {
  if (msg) console.error(`layout_capture: ${msg}`);
  console.error('usage: layout_capture.mjs [--targets FILE | --url URL ... | --manifest ux.yml --base-url URL] [--out DIR] [--viewports phone,tablet,desktop] [--color-scheme light|dark] [--max-height PX] [--inject-css FILE] [--no-png] [--fail-on none|error|warn]');
  process.exit(2);
}

function parseArgs(argv) {
  const a = { urls: [], out: 'layout-capture', viewports: Object.keys(VIEWPORTS), colorScheme: 'light', maxHeight: 2400, png: true, failOn: 'none', manifest: 'ux.yml' };
  for (let i = 0; i < argv.length; i++) {
    const v = () => { if (i + 1 >= argv.length) usage(`${argv[i]} needs a value`); return argv[++i]; };
    switch (argv[i]) {
      case '--targets': a.targets = v(); break;
      case '--url': a.urls.push(v()); break;
      case '--manifest': a.manifest = v(); a.manifestGiven = true; break;
      case '--base-url': a.baseUrl = v(); break;
      case '--out': a.out = v(); break;
      case '--viewports': a.viewports = v().split(',').map((s) => s.trim()).filter(Boolean); break;
      case '--color-scheme': a.colorScheme = v(); break;
      case '--max-height': a.maxHeight = Number(v()); break;
      case '--inject-css': a.injectCss = v(); break;
      case '--no-png': a.png = false; break;
      case '--fail-on': a.failOn = v(); break;
      case '-h': case '--help': usage();
      default: usage(`unknown argument ${argv[i]}`);
    }
  }
  for (const vp of a.viewports) if (!VIEWPORTS[vp]) usage(`unknown viewport ${vp} (known: ${Object.keys(VIEWPORTS).join(', ')})`);
  if (!['none', 'error', 'warn'].includes(a.failOn)) usage(`--fail-on must be none, error or warn`);
  if (!['light', 'dark'].includes(a.colorScheme)) usage(`--color-scheme must be light or dark`);
  return a;
}

function loadYaml(path) {
  try {
    return require('js-yaml').load(readFileSync(path, 'utf8'));
  } catch (err) {
    if (err.code !== 'MODULE_NOT_FOUND') throw err;
    const text = readFileSync(path, 'utf8'), surfaces = [];
    const re = /-\s*url:\s*["']?([^"'\n]+)["']?[\s\S]*?role:\s*["']?([^"'\n]+)/g;
    let m;
    while ((m = re.exec(text))) surfaces.push({ url: m[1].trim(), role: m[2].trim() });
    return { surfaces, preview: {} };
  }
}

export function pathSlug(url) {
  const u = new URL(url);
  return `${u.pathname}${u.search}`.replace(/\.html?$/, '').replace(/[^A-Za-z0-9]+/g, '-').replace(/^-|-$/g, '').toLowerCase() || 'home';
}

export function resolveTargets(a) {
  let raw;
  if (a.targets) raw = JSON.parse(readFileSync(a.targets, 'utf8'));
  else if (a.urls.length) raw = a.urls.map((url) => ({ url }));
  else {
    if (!existsSync(a.manifest)) usage(`no targets: pass --targets, --url, or a manifest (${a.manifest} not found)`);
    const m = loadYaml(a.manifest) || {};
    const base = a.baseUrl || process.env.UX_BASE_URL || m.preview?.ready_url;
    raw = (m.surfaces || []).map((s) => {
      if (/^[a-z]+:/.test(s.url)) return s;
      if (!base) usage(`surface ${s.url} is relative: pass --base-url or set preview.ready_url`);
      return { ...s, url: new URL(s.url, base).toString() };
    });
  }
  if (!Array.isArray(raw) || !raw.length) usage('no targets resolved');
  const ids = new Set();
  return raw.map((t) => {
    if (!t.url) usage(`target without url: ${JSON.stringify(t)}`);
    const u = new URL(t.url);
    const site = t.site || u.host || 'local';
    let id = t.id || `${site}--${pathSlug(t.url)}`;
    for (let n = 2; ids.has(id); n++) id = `${t.id || `${site}--${pathSlug(t.url)}`}-${n}`;
    ids.add(id);
    return { id, site, role: t.role || null, url: t.url, css: t.css || '' };
  });
}

async function main() {
  const a = parseArgs(process.argv.slice(2));
  const targets = resolveTargets(a);
  const injected = a.injectCss ? readFileSync(a.injectCss, 'utf8') : '';
  let chromium;
  try {
    ({ chromium } = await import('playwright'));
  } catch (err) {
    console.error('layout_capture: playwright is not installed here: npm i -D playwright js-yaml && npx playwright install chromium');
    console.error(String(err));
    process.exit(2);
  }
  const out = resolve(a.out);
  mkdirSync(out, { recursive: true });
  const browser = await chromium.launch(process.env.UX_CHROMIUM_PATH ? { executablePath: process.env.UX_CHROMIUM_PATH } : {});
  const captures = [], failed = [];
  try {
    for (const t of targets) {
      for (const vpName of a.viewports) {
        const key = `${t.id}--${vpName}`;
        const ctx = await browser.newContext({ viewport: VIEWPORTS[vpName], deviceScaleFactor: 1, colorScheme: a.colorScheme, reducedMotion: 'reduce' });
        try {
          const page = await ctx.newPage();
          let resp;
          try {
            resp = await page.goto(t.url, { waitUntil: 'networkidle', timeout: 45000 });
          } catch (err) {
            if (!/timeout/i.test(String(err))) throw err;
            resp = await page.goto(t.url, { waitUntil: 'load', timeout: 45000 });
          }
          if (resp && resp.status() >= 400) throw new Error(`HTTP ${resp.status()}`);
          await page.addStyleTag({ content: STABILISE + t.css + injected });
          await page.waitForTimeout(300);
          const { geometry, svg } = await page.evaluate(probe, { maxHeight: a.maxHeight, rules: RULES.map(({ id, severity }) => ({ id, severity })) });
          geometry.summary = { key, id: t.id, site: t.site, role: t.role, viewport: vpName, patched: Boolean(t.css || injected), ...geometry.summary };
          writeFileSync(join(out, `${key}.json`), JSON.stringify(geometry, null, 1));
          writeFileSync(join(out, `${key}.svg`), svg);
          if (a.png) {
            const height = Math.min(a.maxHeight > 0 ? a.maxHeight : geometry.summary.docH, geometry.summary.docH);
            await page.screenshot({ path: join(out, `${key}.png`), fullPage: true, clip: { x: 0, y: 0, width: VIEWPORTS[vpName].width, height } });
          }
          captures.push({ ...geometry.summary, rules: geometry.rules.map((r) => r.id) });
          console.log(`${key.padEnd(48)} score ${String(geometry.summary.score).padStart(3)}  errors ${geometry.summary.errors}  warnings ${geometry.summary.warnings}`);
        } catch (err) {
          failed.push({ key, id: t.id, url: t.url, viewport: vpName, error: String(err.message || err).split('\n')[0] });
          console.error(`${key.padEnd(48)} NOT CAPTURED: ${failed.at(-1).error}`);
        } finally {
          await ctx.close();
        }
      }
    }
  } finally {
    await browser.close();
  }

  const summary = {
    schema: SCHEMA, kit: `ux-audit ${KIT_VERSION}`, captured_at: new Date().toISOString(), color_scheme: a.colorScheme,
    viewports: Object.fromEntries(a.viewports.map((v) => [v, VIEWPORTS[v]])), max_height: a.maxHeight, rules: RULES, captures, failed,
  };
  writeFileSync(join(out, 'summary.json'), JSON.stringify(summary, null, 1));
  const md = [
    '# Layout capture', '', `${captures.length} captured, ${failed.length} not captured · ${summary.captured_at} · ${summary.kit}`, '',
    '| capture | score | errors | warnings | rules |', '| --- | --- | --- | --- | --- |',
    ...captures.map((c) => `| ${c.key} | ${c.score} | ${c.errors} | ${c.warnings} | ${[...new Set(c.rules.map((r) => r.split('-')[0]))].join(' ') || '—'} |`),
    ...(failed.length ? ['', '## Not captured', '', 'Absent is not zero: these have no result, not a clean one.', '', ...failed.map((f) => `- ${f.key}: ${f.error}`)] : []),
    '', '## Rules', '', ...RULES.map((r) => `- **${r.id}** (${r.severity}${r.phone ? ', phone widths' : ''}): ${r.what}`),
  ];
  writeFileSync(join(out, 'summary.md'), `${md.join('\n')}\n`);

  const errors = captures.reduce((n, c) => n + c.errors, 0), warnings = captures.reduce((n, c) => n + c.warnings, 0);
  console.log(`\n${captures.length} captured · ${failed.length} not captured · ${errors} errors · ${warnings} warnings → ${out}`);
  if (!captures.length) {
    console.error('layout_capture: captured nothing — the harness failed, this is not a clean result');
    process.exit(2);
  }
  if ((a.failOn === 'error' && errors) || (a.failOn === 'warn' && errors + warnings)) process.exit(1);
}

if (import.meta.url === `file://${process.argv[1]}` || process.argv[1]?.endsWith('layout_capture.mjs')) {
  main().catch((err) => { console.error(err); process.exit(2); });
}
