import { test } from 'node:test';
import assert from 'node:assert/strict';
import { resolve } from '../lib/config.mjs';
import { grade, renderSummary, lhRule } from '../lib/grade.mjs';
import { assertionsFor, buildRc, urlPattern } from '../lighthouse-config.mjs';

const AS_OF = '2026-10-04';
const axePage = (violations, extra = {}) => ({ axe: '4.13.0', tags: ['wcag2a'], pages: [{ page: '/', viewport: 'mobile-390', url: 'http://x/', violations, ...extra }] });
const v = (rule, impact, nodes = [{ target: 'a', html: '<a class="icon-only"></a>', matched: [] }]) => ({ rule, impact, help: rule, helpUrl: '', tags: ['wcag2a'], nodes });

test('defaults: a violation is a warning, never an error', () => {
  const cfg = resolve({ version: 1, pages: ['/'] });
  const r = grade({ cfg, axeRaw: axePage([v('image-alt', 'critical')]), asOf: AS_OF });
  assert.equal(r.status, 'warn');
  assert.equal(r.counts.error, 0);
});

test('a clean run passes', () => {
  const cfg = resolve({ version: 1, pages: ['/'] });
  assert.equal(grade({ cfg, axeRaw: axePage([]), asOf: AS_OF }).status, 'pass');
});

test('fail_on makes matching violations errors; moderate stays info', () => {
  const cfg = resolve({ version: 1, pages: ['/'], axe: { fail_on: { tags: ['wcag2a'], impacts: ['critical', 'serious'] } } });
  const r = grade({ cfg, axeRaw: axePage([v('image-alt', 'critical'), v('region', 'moderate')]), asOf: AS_OF });
  assert.equal(r.status, 'fail');
  assert.equal(r.counts.error, 1);
  assert.equal(r.counts.info, 1);
});

test('allowlist turns an error into a known issue; a new node still fails', () => {
  const cfg = resolve({
    version: 1, pages: ['/'], axe: { fail_on: { tags: ['wcag2a'], impacts: ['serious'] } },
    allowlist: { entries: [{ rule: 'link-name', selector: 'a.icon-only', reason: 'r', issue: 'https://x/1', until: '2099-12-31' }] },
  });
  const nodes = [{ target: 'a', html: '<a class="icon-only">', matched: ['a.icon-only'] }, { target: 'nav a', html: '<a>', matched: [] }];
  const r = grade({ cfg, axeRaw: axePage([v('link-name', 'serious', nodes)]), asOf: AS_OF });
  assert.equal(r.counts.allowed, 1);
  assert.equal(r.counts.error, 1);
  assert.equal(r.status, 'fail');
});

test('expired entry: warn by default, error when on_expired is error, and still in force', () => {
  const entry = { rule: 'link-name', page: '/', reason: 'r', issue: 'https://x/1', until: '2026-01-01' };
  const base = { version: 1, pages: ['/'], axe: { fail_on: { tags: ['wcag2a'], impacts: ['serious'] } } };
  const warn = grade({ cfg: resolve({ ...base, allowlist: { entries: [entry] } }), axeRaw: axePage([v('link-name', 'serious')]), asOf: AS_OF });
  assert.equal(warn.status, 'warn');
  assert.equal(warn.counts.allowed, 1);
  assert.deepEqual(warn.allowlist.expired, [0]);
  const err = grade({ cfg: resolve({ ...base, allowlist: { on_expired: 'error', entries: [entry] } }), axeRaw: axePage([v('link-name', 'serious')]), asOf: AS_OF });
  assert.equal(err.status, 'fail');
  const viaInput = grade({ cfg: resolve({ ...base, allowlist: { on_expired: 'error', entries: [entry] } }, { expiredLevel: 'warn' }), axeRaw: axePage([v('link-name', 'serious')]), asOf: AS_OF });
  assert.equal(viaInput.status, 'warn');
});

test('unused entries are reported as stale', () => {
  const cfg = resolve({ version: 1, pages: ['/'], allowlist: { entries: [{ rule: 'label', page: '/', reason: 'r', issue: 'https://x/1', until: '2099-01-01' }] } });
  const r = grade({ cfg, axeRaw: axePage([]), asOf: AS_OF });
  assert.deepEqual(r.allowlist.stale.map((e) => e.rule), ['label']);
});

test('page load errors follow load_errors', () => {
  const raw = axePage([], { error: 'HTTP 404' });
  assert.equal(grade({ cfg: resolve({ version: 1, pages: ['/'] }), axeRaw: raw, asOf: AS_OF }).status, 'warn');
  assert.equal(grade({ cfg: resolve({ version: 1, pages: ['/'], load_errors: 'error' }), axeRaw: raw, asOf: AS_OF }).status, 'fail');
});

test('contrast: max gates, allowlisted nodes do not count', () => {
  const cfg = resolve({ version: 1, pages: ['/'], contrast: { pages: [{ path: '/', max: 0 }] },
    allowlist: { entries: [{ rule: 'contrast', selector: '.muted', reason: 'r', issue: 'https://x/1', until: '2099-01-01' }] } });
  const issue = (selector) => ({ selector, context: '<p>', shape: `${selector} @ 2:1` });
  const one = grade({ cfg, contrastRaw: { pages: [{ path: '/', max: 0, issues: [issue('p.muted')] }] }, asOf: AS_OF });
  assert.equal(one.status, 'warn');
  const two = grade({ cfg, contrastRaw: { pages: [{ path: '/', max: 0, issues: [issue('p.muted'), issue('p.faint')] }] }, asOf: AS_OF });
  assert.equal(two.status, 'fail');
  const reportOnly = grade({ cfg: resolve({ version: 1, pages: ['/'] }), contrastRaw: { pages: [{ path: '/', issues: [issue('p.faint')] }] }, asOf: AS_OF });
  assert.equal(reportOnly.status, 'warn');
});

test('lighthouse: failed assertions at their level; rule ids match the allowlist form', () => {
  const cfg = resolve({ version: 1, pages: ['/'] });
  const assertions = [
    { passed: false, level: 'error', auditId: 'categories', auditProperty: 'accessibility', url: 'http://h/', operator: '>=', expected: 0.9, actual: 0.5 },
    { passed: false, level: 'warn', auditId: 'resource-summary', auditProperty: 'total.size', url: 'http://h/', operator: '<=', expected: 1, actual: 2 },
  ];
  const r = grade({ cfg, lighthouse: { collected: true, assertions, scores: [] }, meta: { base: 'http://h' }, asOf: AS_OF });
  assert.equal(r.status, 'fail');
  assert.deepEqual(r.findings.map((f) => f.rule), ['categories:accessibility', 'resource-summary:total:size']);
  assert.equal(lhRule(assertions[1]), 'resource-summary:total:size');
  const missing = grade({ cfg, lighthouse: { collected: false, assertions: [], scores: [] }, asOf: AS_OF });
  assert.equal(missing.status, 'warn');
});

test('summary records the theme SHA', () => {
  const cfg = resolve({ version: 1, pages: ['/'] });
  const theme = { kind: 'remote', repo: 'bamr87/zer0-mistakes', ref: 'HEAD', sha: 'a'.repeat(40), source: 'remote_theme' };
  const r = grade({ cfg, theme, axeRaw: axePage([]), asOf: AS_OF });
  assert.equal(r.theme.sha, 'a'.repeat(40));
  assert.match(renderSummary(r, { artifact: 'x' }), /bamr87\/zer0-mistakes/);
  assert.match(renderSummary(r, { artifact: 'x' }), /aaaaaaa/);
});

test('lighthouse assertions: categories, metrics, audits, sizes, overrides', () => {
  const lh = resolve({ version: 1, pages: ['/', '/blog/'], lighthouse: {
    categories: { accessibility: { min: 0.9, level: 'error' } },
    metrics: { 'largest-contentful-paint': { max: 4000, level: 'warn' } },
    audits: { 'unsized-images': 'warn' },
    sizes: { total: { max_kib: 2, level: 'warn' } },
    overrides: [{ page: '/blog/', audits: { 'unsized-images': 'off' }, metrics: { 'largest-contentful-paint': { max: 6000, level: 'warn' } } }],
  } }).lighthouse;
  const home = assertionsFor(lh, '/');
  assert.deepEqual(home['categories:accessibility'], ['error', { aggregationMethod: 'median', minScore: 0.9 }]);
  assert.equal(home['largest-contentful-paint'][1].maxNumericValue, 4000);
  assert.equal(home['resource-summary:total:size'][1].maxNumericValue, 2048);
  const blog = assertionsFor(lh, '/blog/');
  assert.equal(blog['unsized-images'], 'off');
  assert.equal(blog['largest-contentful-paint'][1].maxNumericValue, 6000);
  assert.ok(new RegExp(urlPattern('http://h/base', '/blog/')).test('http://h/base/blog'));
});

test('no budgets = no assert step', () => {
  const cfg = resolve({ version: 1, pages: ['/'] });
  const { rc, hasAssertions } = buildRc(cfg, 'http://h', '/tmp/r');
  assert.equal(hasAssertions, false);
  assert.equal(rc.ci.assert, undefined);
  assert.equal(rc.ci.upload.target, 'filesystem');
});
