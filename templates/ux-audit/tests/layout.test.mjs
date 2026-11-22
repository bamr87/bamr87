// Layout capture (L1–L6) against two local fixtures: the section-page defects found on
// lifehacker.dev/news/wire/ (section-bad.html) and the same page fixed (section-good.html).
// No network. Needs playwright + a Chromium; without them the suite skips, unless
// UX_REQUIRE_BROWSER=1 (CI sets it), where a missing browser is a failure.
import { describe, test, before } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const scripts = join(here, '..', 'scripts');
const fixture = (name) => pathToFileURL(join(here, 'fixtures', name)).toString();
const BAD = fixture('section-bad.html'), GOOD = fixture('section-good.html');

let skip = false;
try {
  await import('playwright');
} catch {
  skip = 'playwright is not installed (npm install in templates/ux-audit)';
  if (process.env.UX_REQUIRE_BROWSER === '1') throw new Error(`UX_REQUIRE_BROWSER=1 but ${skip}`);
}

const tmp = () => mkdtempSync(join(tmpdir(), 'ux-layout-'));
const node = (script, args) => spawnSync(process.execPath, [join(scripts, script), ...args], { encoding: 'utf8', timeout: 240000 });
const readJson = (f) => JSON.parse(readFileSync(f, 'utf8'));
function capture(targets, extra = []) {
  const out = tmp(), tf = join(out, 'targets.json');
  writeFileSync(tf, JSON.stringify(targets));
  const r = node('layout_capture.mjs', ['--targets', tf, '--out', out, ...extra]);
  const sf = join(out, 'summary.json');
  return { out, r, summary: existsSync(sf) ? readJson(sf) : null };
}
const prefixes = (c) => c.rules.map((id) => id.split('-')[0]).sort();
const at = (summary, viewport) => summary.captures.find((c) => c.viewport === viewport);

describe('layout capture', { skip }, () => {
  let bad, good;
  before(() => {
    bad = capture([{ id: 'section', role: 'section', url: BAD }]);
    good = capture([{ id: 'section', role: 'section', url: GOOD }]);
    assert.equal(bad.r.status, 0, bad.r.stderr);
    assert.equal(good.r.status, 0, good.r.stderr);
  });

  test('the defective section page trips L2–L6 at phone width, and the run stays warn-only', () => {
    const c = at(bad.summary, 'phone');
    assert.deepEqual(prefixes(c), ['L2', 'L3', 'L4', 'L5', 'L6']);
    assert.equal(c.errors, 1);
    assert.ok(c.score < 80, `score ${c.score}`);
  });

  test('the same page is clean at desktop width (the phone rules do not run there)', () => {
    assert.deepEqual(at(bad.summary, 'desktop').rules, []);
  });

  test('the fixed page trips nothing at any width', () => {
    for (const c of good.summary.captures) assert.deepEqual(c.rules, [], `${c.key}: ${c.rules}`);
    assert.equal(good.summary.captures.length, 3);
  });

  test('every capture writes a geometry snapshot, a wireframe and a screenshot', () => {
    for (const c of bad.summary.captures) {
      const g = readJson(join(bad.out, `${c.key}.json`));
      assert.ok(g.items.length > 10 && g.anchors.h1 && g.summary.vw === c.vw, c.key);
      const svg = readFileSync(join(bad.out, `${c.key}.svg`), 'utf8');
      assert.match(svg, /^<svg xmlns="http:\/\/www.w3.org\/2000\/svg"/);
      assert.ok(existsSync(join(bad.out, `${c.key}.png`)), `${c.key}.png`);
    }
    assert.match(readFileSync(join(bad.out, 'summary.md'), 'utf8'), /\| section--phone \| \d+ \| 1 \| 4 \|/);
  });

  test('--fail-on error turns an error into exit 1', () => {
    const r = capture([{ id: 'section', url: BAD }], ['--viewports', 'phone', '--no-png', '--fail-on', 'error']);
    assert.equal(r.r.status, 1, r.r.stdout + r.r.stderr);
    assert.ok(!existsSync(join(r.out, 'section--phone.png')), '--no-png wrote a screenshot');
  });

  test('L1 fires when the page really scrolls sideways, not when the root clips the overhang', () => {
    const OVER = fixture('overflow.html');
    const r = capture([
      { id: 'scrolls', url: OVER, css: 'html{scroll-behavior:smooth}' },
      { id: 'clipped', url: OVER, css: 'html{overflow-x:clip;scroll-behavior:smooth}' },
      { id: 'body-hidden', url: OVER, css: 'body{overflow-x:hidden}' },
    ], ['--viewports', 'phone', '--no-png']);
    assert.equal(r.r.status, 0, r.r.stderr);
    const byId = Object.fromEntries(r.summary.captures.map((c) => [c.id, c]));
    assert.deepEqual(byId.scrolls.rules, ['L1-page-overflow']);
    assert.deepEqual(byId.clipped.rules, []);
    assert.deepEqual(byId['body-hidden'].rules, []);
  });

  test('a run that captured nothing exits 2 and records why: absent is not zero', () => {
    const r = capture([{ id: 'gone', url: fixture('does-not-exist.html') }], ['--viewports', 'phone']);
    assert.equal(r.r.status, 2, r.r.stdout + r.r.stderr);
    assert.equal(r.summary.captures.length, 0);
    assert.equal(r.summary.failed.length, 1);
    assert.match(r.summary.failed[0].error, /ERR_FILE_NOT_FOUND|not found/i);
  });

  test('change: defective → fixed fixes every rule, introduces none, and names what moved', () => {
    const out = tmp();
    const r = node('layout_compare.mjs', ['--base', bad.out, '--head', good.out, '--out', out, '--fail-on', 'regression']);
    assert.equal(r.status, 0, r.stdout + r.stderr);
    const cmp = readJson(join(out, 'compare.json'));
    const phone = cmp.captures.find((c) => c.key === 'section--phone');
    assert.deepEqual(phone.fixed.map((id) => id.split('-')[0]).sort(), ['L2', 'L3', 'L4', 'L5', 'L6']);
    assert.deepEqual(phone.introduced, []);
    assert.ok(phone.structural.resized > 0);
    assert.deepEqual(phone.score, [at(bad.summary, 'phone').score, 100]);
    assert.equal(cmp.regressions, 0);
    assert.ok(existsSync(join(out, 'diff', 'section--phone.svg')) && existsSync(join(out, 'board.svg')));
  });

  test('change: fixed → defective is a regression, and --fail-on regression exits 1', () => {
    const out = tmp();
    const r = node('layout_compare.mjs', ['--base', good.out, '--head', bad.out, '--out', out, '--fail-on', 'regression']);
    assert.equal(r.status, 1, r.stdout + r.stderr);
    assert.ok(readJson(join(out, 'compare.json')).regressions >= 1);
  });

  test('consistency: one role on two sites separates layout drift from content', () => {
    const run = capture([
      { id: 'a--section', site: 'a', role: 'section', url: GOOD },
      { id: 'b--section', site: 'b', role: 'section', url: BAD },
    ], ['--viewports', 'phone', '--no-png']);
    assert.equal(run.r.status, 0, run.r.stderr);
    const r = node('layout_compare.mjs', ['--consistency', run.out]);
    assert.equal(r.status, 0, r.stdout + r.stderr);
    const [group] = readJson(join(run.out, 'consistency.json')).groups;
    assert.equal(group.group, 'section--phone');
    assert.equal(group.reference, 'a--section--phone');
    const site = group.sites[0];
    assert.ok(site.anchors.h1.dx > 32, `h1 dx ${site.anchors.h1.dx}`); // the icon column pushes the defective h1 right
    assert.ok(site.layout_drift_px > 0);
    assert.ok(existsSync(join(run.out, 'board-consistency.svg')));
  });
});
