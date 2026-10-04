#!/usr/bin/env node
// =============================================================================
// report.mjs — grade the collected results and publish them
// -----------------------------------------------------------------------------
// Reads the resolved config, theme.json and the raw outputs of the three
// collectors, grades them (lib/grade.mjs), and writes:
//   <reports>/report.json   machine-readable (schema site-quality-report/v1)
//   <reports>/summary.md    the job summary, also used as an issue body
// plus annotations and the step outputs status / errors / warnings.
//
// Usage: node report.mjs --config <resolved.json> --theme <theme.json>
//          --reports <dir> --base <url> [--lhci-dir <dir>] [--lh-collected true|false]
//          [--config-path <caller path>] [--artifact <name>] [--hub-repo R] [--hub-sha S]
//        node report.mjs --check <report.json>   # exit 1 when status is fail
// =============================================================================
import { existsSync, readFileSync, readdirSync, writeFileSync, appendFileSync, mkdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { parseArgs } from 'node:util';
import { grade, renderSummary } from './lib/grade.mjs';

const { values: a } = parseArgs({
  options: {
    check: { type: 'string' }, config: { type: 'string' }, theme: { type: 'string' }, reports: { type: 'string' },
    base: { type: 'string', default: '' }, 'lhci-dir': { type: 'string', default: '' }, 'lh-collected': { type: 'string', default: '' },
    'config-path': { type: 'string', default: '' }, artifact: { type: 'string', default: 'site-quality-report' },
    'hub-repo': { type: 'string', default: '' }, 'hub-sha': { type: 'string', default: '' },
  },
});

if (a.check) {
  const r = JSON.parse(readFileSync(a.check, 'utf8'));
  console.log(`site-quality status: ${r.status} (${r.counts.error} error(s), ${r.counts.warn} warning(s), ${r.counts.allowed} allowlisted)`);
  process.exit(r.status === 'fail' ? 1 : 0);
}

const readJson = (p) => (p && existsSync(p) ? JSON.parse(readFileSync(p, 'utf8')) : null);
const cfg = readJson(a.config);
const theme = readJson(a.theme) || { kind: cfg.mode === 'url' ? 'live' : 'none' };
// A collector that crashed left no raw file: report it (rule collector-crashed)
// instead of silently treating the check as clean. It grades at load_errors,
// or as an error whenever the caller's config gates that check (grade.mjs gated()).
const crashed = (what) => `${what} produced no results (it crashed; see its step in the job log)`;
let axeRaw = cfg.axe.enabled ? readJson(`${a.reports}/axe/axe-raw.json`) : null;
if (cfg.axe.enabled && !axeRaw) axeRaw = { axe: '', tags: cfg.axe.tags, pages: [{ page: '*', viewport: '', crashed: true, error: crashed('axe') }] };
let contrastRaw = cfg.contrast.enabled ? readJson(`${a.reports}/contrast/contrast-raw.json`) : null;
if (cfg.contrast.enabled && !contrastRaw) contrastRaw = { pages: [{ path: '*', crashed: true, error: crashed('pa11y'), issues: [] }] };

let lighthouse = null;
if (cfg.lighthouse.enabled) {
  const dir = a['lhci-dir'];
  const lhrs = dir && existsSync(dir) ? readdirSync(dir).filter((f) => /^lhr-.*\.json$/.test(f)).sort().map((f) => readJson(`${dir}/${f}`)) : [];
  const byUrl = {};
  for (const l of lhrs) (byUrl[l.requestedUrl || l.finalDisplayedUrl] ||= []).push(l);
  let median = (runs) => runs[0];
  try {
    const { computeRepresentativeRuns } = createRequire(import.meta.url)('@lhci/utils/src/representative-runs.js');
    median = (runs) => computeRepresentativeRuns([runs.map((l) => [l, l])])[0];
  } catch { /* fall back to the first run */ }
  const pct = (c) => (c?.score == null ? '—' : Math.round(c.score * 100));
  const sec = (x) => (x?.numericValue == null ? '—' : `${(x.numericValue / 1000).toFixed(2)} s`);
  const base = a.base.replace(/\/+$/, '');
  const scores = Object.entries(byUrl).map(([url, runs]) => {
    const l = median(runs);
    const total = (l.audits['resource-summary']?.details?.items || []).find((i) => i.resourceType === 'total');
    return {
      url, page: url.startsWith(base) ? url.slice(base.length) || '/' : url, runs: runs.length,
      performance: pct(l.categories?.performance), accessibility: pct(l.categories?.accessibility),
      'best-practices': pct(l.categories?.['best-practices']), seo: pct(l.categories?.seo),
      lcp: sec(l.audits['largest-contentful-paint']), cls: l.audits['cumulative-layout-shift']?.numericValue?.toFixed(3) ?? '—',
      tbt: `${Math.round(l.audits['total-blocking-time']?.numericValue ?? 0)} ms`, total_kib: total ? Math.round(total.transferSize / 1024) : '—',
    };
  });
  lighthouse = {
    collected: a['lh-collected'] === 'true' && lhrs.length > 0,
    assertions: readJson(dir && `${dir}/assertion-results.json`) || [],
    links: readJson(dir && `${dir}/links.json`) || {},
    scores,
  };
}

const report = grade({
  cfg, theme, axeRaw, contrastRaw, lighthouse,
  meta: { base: a.base, configPath: a['config-path'], hub: { repo: a['hub-repo'], sha: a['hub-sha'] } },
});
mkdirSync(a.reports, { recursive: true });
writeFileSync(`${a.reports}/report.json`, JSON.stringify(report, null, 2));
const md = renderSummary(report, { artifact: a.artifact });
writeFileSync(`${a.reports}/summary.md`, md);
if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, md + '\n');
console.log(md);

// Annotations: one per grouped finding, capped so a noisy page can't bury the log.
const ann = (level, title, msg) => console.log(`::${level} title=${title.replace(/[:,\n]/g, ' ')}::${String(msg).replace(/\r?\n/g, '%0A')}`);
const seen = new Set();
let n = 0;
for (const f of report.findings) {
  if (!['error', 'warn', 'allowed'].includes(f.level)) continue;
  const key = `${f.level}|${f.check}|${f.rule}|${f.page}|${f.viewport || ''}`;
  if (seen.has(key) || n >= 40) continue;
  seen.add(key); n += 1;
  const where = `${f.page}${f.viewport ? ` @ ${f.viewport}` : ''}`;
  if (f.level === 'error') ann('error', `site-quality ${f.check} ${f.rule}`, `${where}: ${f.message}`);
  else if (f.level === 'warn') ann('warning', `site-quality ${f.check} ${f.rule}`, `${where}: ${f.message}`);
  else ann('notice', `site-quality ${f.check} ${f.rule} (allowlisted)`, `${where}: ${f.message} — ${f.allowed.issue} until ${f.allowed.until}`);
}
for (const e of report.allowlist.stale) ann('notice', `site-quality allowlist #${e.index + 1} unused`, `\`${e.rule}\` matched nothing this run — delete it once its fix has landed`);

if (process.env.GITHUB_OUTPUT) {
  appendFileSync(process.env.GITHUB_OUTPUT, `status=${report.status}\nerrors=${report.counts.error}\nwarnings=${report.counts.warn + report.counts.allowed}\n`);
}
