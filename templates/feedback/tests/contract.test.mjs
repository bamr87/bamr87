/**
 * Contract tests for the feedback kit — spec: bamr87/bamr87 specs/FEEDBACK.md.
 *
 * These lock the ISSUE CONTRACT (UPS-FB-20..25), not the UI. Two widgets ship
 * this contract — the web component here and the zer0-mistakes theme's own
 * Bootstrap modal, which vendors this file and calls FleetFeedbackCore — so a
 * change that breaks these tests breaks issues filed from ~25 repositories.
 *
 *   node --test tests/            (or: npm test)
 *
 * No dependencies and no DOM: the core is pure by construction, and the custom
 * element bails out when `document` is undefined, so require() is safe here.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { createRequire } from 'node:module';

const KIT = dirname(dirname(fileURLToPath(import.meta.url)));
const read = (rel) => readFileSync(join(KIT, rel), 'utf8');
const Core = createRequire(import.meta.url)(join(KIT, 'fleet-feedback.js'));

const TYPE = Core.typeById(Core.TYPES, 'fix-page');
const QUESTION = Core.typeById(Core.TYPES, 'question');

const INPUT = {
  type: TYPE,
  description: 'The sidebar link 404s.',
  page: {
    title: 'Getting started',
    url: 'https://example.com/docs/start/',
    source: 'pages/_docs/start.md',
    sourceUrl: 'https://github.com/o/r/blob/main/pages/_docs/start.md',
    route: '/docs/start/',
    lastmod: '2026-09-01',
  },
  environment: {
    browser: 'Mozilla/5.0', viewport: '1440×900', dpr: 2, colorScheme: 'dark',
    reducedMotion: true, referrer: 'https://example.com/', repository: 'o/r',
    branch: 'main', buildEnv: 'production', capturedAt: '2026-09-04T00:00:00.000Z',
  },
  logs: [{ t: '2026-09-04T00:00:00.000Z', level: 'error', msg: 'Boom' }],
  config: { labels: ['page-feedback'], assignee: 'copilot', repo: 'o/r' },
};

// --- the two capture copies are one implementation ------------------------

test('capture.js and fleet-feedback.js carry a byte-identical capture block', () => {
  const BEGIN = '/* fleet-feedback:capture:begin';
  const END = '/* fleet-feedback:capture:end */';
  const slice = (src) => {
    const a = src.indexOf(BEGIN);
    const b = src.indexOf(END);
    assert.ok(a >= 0 && b > a, 'capture sentinels missing');
    return src.slice(a, b + END.length);
  };
  assert.equal(
    slice(read('capture.js')),
    slice(read('fleet-feedback.js')),
    'the capture block drifted — edit it in capture.js and re-splice, never in one copy alone',
  );
});

// --- UPS-FB-22/23: title and body ----------------------------------------

test('title is [<type label>] <page title>, capped at 240', () => {
  assert.equal(Core.buildIssue(INPUT).title, '[Report a problem] Getting started');
  const long = Core.buildIssue({ ...INPUT, page: { ...INPUT.page, title: 'x'.repeat(400) } });
  assert.equal(long.title.length, 240);
});

test('body sections appear in the contract order, each under a ## heading', () => {
  const { body } = Core.buildIssue(INPUT);
  const order = ['## 📝 Description', '## 📄 Page context', '## 🔧 Environment',
    '## 🧾 Console & error logs', '## 🤖 Agent directive'];
  let at = -1;
  for (const heading of order) {
    const found = body.indexOf(heading);
    assert.ok(found > at, `${heading} is missing or out of order`);
    at = found;
  }
  assert.match(body, /\n---\n_Filed from https:\/\/example\.com\/docs\/start\/ via fleet-feedback v[\d.]+\._/);
});

test('page context carries the source link, route, and last modified', () => {
  const { sections } = Core.buildIssue(INPUT);
  assert.match(sections.context, /\| \*\*Source\*\* \| \[`pages\/_docs\/start\.md`\]\(https:\/\/github\.com\/o\/r\/blob\/main\/pages\/_docs\/start\.md\) \|/);
  assert.match(sections.context, /\| \*\*Collection\/route\*\* \| \/docs\/start\/ \|/);
  assert.match(sections.context, /\| \*\*Last modified\*\* \| 2026-09-01 \|/);
});

test('environment reports viewport@dpr, reduced motion, repo, branch and build env', () => {
  const { sections } = Core.buildIssue(INPUT);
  assert.match(sections.environment, /\| \*\*Viewport\*\* \| 1440×900 @2x \|/);
  assert.match(sections.environment, /\| \*\*Colour scheme\*\* \| dark, reduced motion \|/);
  assert.match(sections.environment, /\| \*\*Repository\*\* \| o\/r \|/);
  assert.match(sections.environment, /\| \*\*Branch\*\* \| main \|/);
  assert.match(sections.environment, /\| \*\*Build env\*\* \| production \|/);
});

test('empty fields drop their row rather than emitting a blank cell', () => {
  const { sections } = Core.buildIssue({ ...INPUT, page: { title: 'T', url: 'U' } });
  assert.doesNotMatch(sections.context, /Source|Last modified/);
  assert.match(sections.context, /\| \*\*Page\*\* \| T \|/);
});

test('a missing description says so instead of filing an empty report', () => {
  assert.match(Core.buildIssue({ ...INPUT, description: '   ' }).body, /_\(no description provided\)_/);
});

test('extra text is appended to the description (404 route, error stack)', () => {
  const issue = Core.buildIssue({ ...INPUT, extra: 'Missing route: /nope' });
  assert.match(issue.sections.description, /The sidebar link 404s\.\n\nMissing route: \/nope/);
});

// --- UPS-FB-23: the marker is what makes a report machine-readable --------

test('the body ends with the dedupe/analytics marker and it parses', () => {
  const issue = Core.buildIssue(INPUT);
  assert.ok(issue.body.trimEnd().endsWith('<!-- fleet-feedback v1 type=fix-page -->'));
  assert.equal(issue.body.match(Core.MARKER_RE)[1], 'fix-page');
});

// --- UPS-FB-21/24: labels and assignment ---------------------------------

test('labels are the marker plus the type labels, deduplicated', () => {
  const a11y = Core.buildIssue({ ...INPUT, type: Core.typeById(Core.TYPES, 'accessibility') });
  assert.deepEqual(a11y.labels, ['page-feedback', 'bug', 'area:a11y']);
  const dupe = Core.buildIssue({ ...INPUT, config: { ...INPUT.config, labels: ['page-feedback', 'bug'] } });
  assert.deepEqual(dupe.labels, ['page-feedback', 'bug']);
});

test('only agent types get the assignee and the directive', () => {
  assert.deepEqual(Core.buildIssue(INPUT).assignees, ['copilot']);
  const q = Core.buildIssue({ ...INPUT, type: QUESTION });
  assert.deepEqual(q.assignees, []);
  assert.equal(q.sections.directive, '');
});

test('an empty assignee disables assignment entirely', () => {
  const issue = Core.buildIssue({ ...INPUT, config: { ...INPUT.config, assignee: '' } });
  assert.deepEqual(issue.assignees, []);
});

// --- escaping: the class of bug that corrupts every row downstream --------

test('table cells escape backslashes before pipes and flatten newlines', () => {
  // Escaping "|" first would re-escape the backslash it just added.
  assert.equal(Core.cell('a\\b|c\nd'), 'a\\\\b\\|c d');
});

test('a title containing a pipe cannot break the context table', () => {
  const { sections } = Core.buildIssue({ ...INPUT, page: { ...INPUT.page, title: 'A|B' } });
  const row = sections.context.split('\n').find((l) => l.includes('**Page**'));
  assert.ok(row.includes('A\\|B'), 'the pipe was not escaped');
  // Structure is what matters: with the escaped pipes removed, the row still
  // has exactly the leading, separating and trailing delimiters.
  assert.equal(row.replace(/\\\|/g, '').split('|').length, 4, 'the pipe leaked into the row structure');
});

test('a code fence inside a captured log cannot close the log fence early', () => {
  const issue = Core.buildIssue({ ...INPUT, logs: [{ t: 'T', level: 'error', msg: 'x ``` y' }] });
  assert.equal(issue.sections.logs.match(/```/g).length, 2);
});

// --- UPS-FB-06: the URL budget -------------------------------------------

test('a short report fits with nothing trimmed', () => {
  const built = Core.buildUrl(Core.buildIssue(INPUT), { repo: 'o/r' });
  assert.deepEqual(built.trimmed, []);
  assert.ok(built.url.startsWith('https://github.com/o/r/issues/new?'));
  const q = new URL(built.url).searchParams;
  assert.equal(q.get('labels'), 'page-feedback,bug');
  assert.equal(q.get('assignees'), 'copilot');
});

test('over budget, sections are dropped as logs → directive → environment', () => {
  const noisy = Array.from({ length: 40 }, (_, i) => ({ t: 'T', level: 'error', msg: 'x'.repeat(500) + i }));
  const issue = Core.buildIssue({ ...INPUT, logs: noisy });
  assert.deepEqual(Core.buildUrl(issue, { repo: 'o/r' }).trimmed, ['logs']);

  const huge = { ...issue, sections: { ...issue.sections, environment: 'E'.repeat(9000) } };
  assert.deepEqual(Core.buildUrl(huge, { repo: 'o/r' }).trimmed, ['logs', 'directive', 'environment']);
});

test('a body that cannot fit even trimmed is reported, never silently truncated', () => {
  const issue = Core.buildIssue({ ...INPUT, description: 'y'.repeat(20000) });
  const built = Core.buildUrl(issue, { repo: 'o/r' });
  assert.equal(built.overBudget, true);
  assert.ok(built.fullBody.includes('y'.repeat(20000)), 'the full body must survive for the clipboard');
});

test('trimming never drops the description or the page context', () => {
  const issue = Core.buildIssue({ ...INPUT, description: 'z'.repeat(9000) });
  const built = Core.buildUrl(issue, { repo: 'o/r' });
  const body = new URL(built.url).searchParams.get('body');
  assert.match(body, /## 📝 Description/);
  assert.match(body, /## 📄 Page context/);
});

// --- UPS-FB-08: privacy ---------------------------------------------------

test('captured lines are redacted before they can be previewed or filed', () => {
  const { redact } = globalThis.__fleetFeedback;
  assert.doesNotMatch(redact('Authorization: Bearer abc123def456'), /abc123def456/);
  assert.doesNotMatch(redact('?api_key=SUPERSECRETVALUE&x=1'), /SUPERSECRETVALUE/);
  assert.doesNotMatch(redact('token ghp_0123456789abcdefghij'), /ghp_0123456789abcdefghij/);
  assert.doesNotMatch(redact('mail to someone@example.com now'), /someone@example\.com/);
  assert.match(redact('plain log line'), /plain log line/);
});

test('the buffer is a bounded ring so a log storm cannot grow without limit', () => {
  const g = globalThis.__fleetFeedback;
  g.clear();
  g.limit = 5;
  for (let i = 0; i < 20; i += 1) g.breadcrumb('net', `req ${i}`);
  assert.equal(g.logs.length, 5);
  assert.match(g.logs.at(-1).msg, /req 19/);
  g.clear();
  g.limit = 40;
});

// --- taxonomy parity: the JS fallback vs the data file vs the no-JS form --

test('the embedded taxonomy matches feedback_types.yml, id for id', () => {
  const yml = read('feedback_types.yml');
  const ids = [...yml.matchAll(/^- id:\s*(\S+)/gm)].map((m) => m[1]);
  assert.deepEqual(Core.TYPES.map((t) => t.id), ids);
});

test('every type in the data file declares the same labels as the fallback', () => {
  const yml = read('feedback_types.yml');
  const blocks = yml.split(/^- id:\s*/m).slice(1);
  for (const block of blocks) {
    const id = block.split(/\s/)[0];
    const labels = (block.match(/^\s*labels:\s*\[(.*?)\]/m)?.[1] ?? '')
      .split(',').map((s) => s.trim().replace(/^["']|["']$/g, '')).filter(Boolean);
    assert.deepEqual(Core.typeById(Core.TYPES, id).labels, labels, `labels drifted for ${id}`);
  }
});

test('the no-JS issue form offers every request type', () => {
  const form = read('page_feedback.yml');
  for (const t of Core.TYPES) {
    assert.ok(form.includes(`(${t.id})`), `page_feedback.yml has no option for ${t.id}`);
  }
  assert.match(form, /labels:\s*\[page-feedback\]/);
});

// --- adapters stay in step with the element's attribute surface ----------

test('every adapter mounts the element with a repo', () => {
  for (const rel of ['adapters/jekyll.html', 'adapters/django.html', 'adapters/FeedbackButton.tsx']) {
    const src = read(rel);
    assert.match(src, /fleet-feedback/, `${rel} does not reference the component`);
    assert.match(src, /repo=/, `${rel} does not pass the required repo attribute`);
  }
});
