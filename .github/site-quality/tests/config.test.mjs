// Schema + config behaviour, against the kit's fixtures (templates/site-quality/fixtures).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseConfig, loadSchema, validate, resolve, expiredEntries, entryMatches } from '../lib/config.mjs';

const HUB = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
const KIT = join(HUB, 'templates', 'site-quality');
const schema = loadSchema(join(KIT, 'site-quality.schema.json'));
const load = (p) => parseConfig(readFileSync(p, 'utf8'));
// The template carries fan-out tokens only in comments, so it parses as-is.
const VALID = [
  ...readdirSync(join(KIT, 'fixtures/configs/valid')).map((f) => join(KIT, 'fixtures/configs/valid', f)),
  join(KIT, 'site-quality.template.yml'),
  join(KIT, 'fixtures/pass-site/site-quality.yml'),
  join(KIT, 'fixtures/fail-site/site-quality.yml'),
];
const INVALID_DIR = join(KIT, 'fixtures/configs/invalid');

for (const p of VALID) {
  test(`valid: ${p.slice(KIT.length + 1)}`, () => {
    assert.deepEqual(validate(load(p), schema), []);
  });
}

for (const f of readdirSync(INVALID_DIR)) {
  test(`invalid: ${f}`, () => {
    const text = readFileSync(join(INVALID_DIR, f), 'utf8');
    const expect = /^# expect: (\S+)/m.exec(text)?.[1];
    const errors = validate(parseConfig(text), schema);
    assert.ok(errors.length > 0, 'expected schema errors');
    assert.ok(expect, `${f} needs a "# expect: <word>" header`);
    assert.ok(errors.join('\n').includes(expect), `errors should mention "${expect}":\n${errors.join('\n')}`);
  });
}

test('unquoted date gets the quote hint', () => {
  const errors = validate(load(join(INVALID_DIR, 'unquoted-date.yml')), schema);
  assert.match(errors.join('\n'), /quote the date/);
});

test('defaults only report: nothing gates without caller config', () => {
  const cfg = resolve(load(join(KIT, 'fixtures/configs/valid/minimal.yml')));
  assert.equal(cfg.load_errors, 'warn');
  assert.equal(cfg.axe.fail_on, null);
  assert.deepEqual(cfg.lighthouse.categories, {});
  assert.deepEqual(cfg.lighthouse.metrics, {});
  assert.deepEqual(cfg.lighthouse.audits, {});
  assert.deepEqual(cfg.lighthouse.sizes, {});
  assert.equal(cfg.contrast.pages[0].max, undefined);
  assert.equal(cfg.allowlist.on_expired, 'warn');
  assert.equal(cfg.lighthouse.public_upload, false);
  assert.deepEqual(cfg.viewports.map((v) => v.width), [390, 1366]);
});

test('workflow inputs override the file', () => {
  const raw = load(join(KIT, 'fixtures/configs/valid/full.yml'));
  const cfg = resolve(raw, { mode: 'url', baseUrl: 'https://x.test/a/', expiredLevel: 'warn', source: 'site' });
  assert.equal(cfg.mode, 'url');
  assert.equal(cfg.site.base_url, 'https://x.test/a');
  assert.equal(cfg.site.source, 'site');
  assert.equal(cfg.allowlist.on_expired, 'warn'); // file says error; input wins
  assert.equal(resolve(raw).allowlist.on_expired, 'error');
});

test('expiredEntries compares quoted dates', () => {
  const cfg = { allowlist: { entries: [{ until: '2026-01-01' }, { until: '2026-10-04' }, { until: '2099-12-31' }] } };
  assert.deepEqual(expiredEntries(cfg, '2026-10-04').map((e) => e.index), [0]);
  assert.deepEqual(expiredEntries(cfg, '2026-10-05').map((e) => e.index), [0, 1]);
});

test('entryMatches: rule, page, wildcard, viewport, selector', () => {
  const f = { rule: 'link-name', page: '/blog/post/', viewport: 'mobile-390', nodes: ['a <a class="x">'], matched: ['a.icon-only'] };
  assert.ok(entryMatches({ rule: 'link-name', page: '/blog/post/' }, f));
  assert.ok(entryMatches({ rule: 'link-name', page: '/blog/*' }, f));
  assert.ok(entryMatches({ rule: 'link-name', page: '*' }, f));
  assert.ok(!entryMatches({ rule: 'label', page: '/blog/post/' }, f));
  assert.ok(!entryMatches({ rule: 'link-name', page: '/' }, f));
  assert.ok(!entryMatches({ rule: 'link-name', page: '/blog/post/', viewport: 'desktop-1366' }, f));
  assert.ok(entryMatches({ rule: 'link-name', selector: 'a.icon-only' }, f), 'browser-side match');
  assert.ok(entryMatches({ rule: 'link-name', selector: 'class="x"' }, f), 'substring match');
  assert.ok(!entryMatches({ rule: 'link-name', selector: '.nope' }, f));
});
