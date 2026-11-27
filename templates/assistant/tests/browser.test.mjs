// The kit's rules that need a DOM, proven in a real browser, at $0.
//
// It starts its own Harness Console (credential-free, on a free loopback port, never :4001) as the broker,
// with only the fixture's origin admitted (DASH_CONSOLE_ASSIST_ORIGINS); serves this kit from a second
// loopback origin; opens tests/fixture.html in headless Chromium; opens the panel and pairs; then plays a
// Claude Code session's side through the console's REAL MCP layer (tools/console/mcp_layer, over stdio,
// with the `page` scope), the way the 2026-11-19 hand run did (test/evidence/fleet-assist/). No model is
// called and nothing is spent.
//
//   tools/test-assist-browser.sh                      # bootstraps, then runs this file
//   FLEET_ASSIST_PYTHON=<python with fastapi, uvicorn, mcp> node --test templates/assistant/tests/browser.test.mjs
//
// A missing browser, FastAPI or mcp package FAILS this test, never skips it. FLEET_ASSIST_BREAK=modal serves
// a payload with `dialog[open]` dropped from MODAL — the self-test CI runs to prove this file can go red.

import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import fs from 'node:fs';
import http from 'node:http';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import readline from 'node:readline';
import { fileURLToPath } from 'node:url';

const KIT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const HUB = path.resolve(KIT, '..', '..');
const CONSOLE_DIR = path.join(HUB, 'tools', 'console');
const PYTHON = process.env.FLEET_ASSIST_PYTHON || 'python3';
const BREAK = process.env.FLEET_ASSIST_BREAK || '';
const LIVE_CONSOLE_PORT = 4001;

// ---------------------------------------------------------------- the harness

/** Playwright from the hub's one browser toolchain: verify/node_modules (fleet-verify.yml installs it there). */
async function chromium() {
  const tries = [];
  for (const base of [path.join(HUB, 'verify', 'package.json'), path.join(KIT, 'package.json')]) {
    try {
      return createRequire(base)('@playwright/test').chromium;
    } catch (e) {
      tries.push(`${path.dirname(base)}: ${e.code || e.message}`);
    }
  }
  throw new Error('Playwright is not installed (' + tries.join('; ') + '). Install it the way the verify job does: ' +
    'npm install --prefix verify --no-save --no-audit --no-fund --no-package-lock @playwright/test yaml && ' +
    'verify/node_modules/.bin/playwright install chromium');
}

function freePort() {
  return new Promise((resolve, reject) => {
    const s = net.createServer();
    s.unref();
    s.on('error', reject);
    s.listen(0, '127.0.0.1', () => {
      const { port } = s.address();
      s.close(() => (port === LIVE_CONSOLE_PORT ? freePort().then(resolve, reject) : resolve(port)));
    });
  });
}

/** The payload as served: the kit's own, or with one rule broken for the self-test. */
function payload() {
  const js = fs.readFileSync(path.join(KIT, 'fleet-assist.js'), 'utf8');
  if (!BREAK) return js;
  if (BREAK !== 'modal') throw new Error(`FLEET_ASSIST_BREAK=${BREAK}: the only rule this test knows how to break is "modal"`);
  const broken = js.replace("const MODAL = 'dialog[open],", "const MODAL = '");
  if (broken === js) throw new Error('FLEET_ASSIST_BREAK=modal found no `dialog[open]` in MODAL to drop: the self-test would prove nothing');
  return broken;
}

/** The kit, served from its own loopback origin, the way a static site serves a page. */
function serveKit(port) {
  const js = payload();
  const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8' };
  const server = http.createServer((req, res) => {
    const rel = decodeURIComponent(new URL(req.url, 'http://x').pathname);
    if (rel === '/fleet-assist.js') {
      res.writeHead(200, { 'Content-Type': types['.js'], 'Cache-Control': 'no-store' });
      return res.end(js);
    }
    const file = path.resolve(KIT, '.' + rel);
    if (!file.startsWith(path.join(KIT, 'tests') + path.sep) || !fs.existsSync(file)) {
      res.writeHead(404);
      return res.end('not found');
    }
    res.writeHead(200, { 'Content-Type': types[path.extname(file)] || 'application/octet-stream', 'Cache-Control': 'no-store' });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise((resolve) => server.listen(port, '127.0.0.1', () => resolve(server)));
}

/** The environment of the console and the MCP server: no token from anywhere, every file they write in `tmp`. */
function brokerEnv(tmp, consoleUrl, pageOrigin) {
  const env = { ...process.env };
  for (const k of Object.keys(env)) {
    if (/^(DASH_CONSOLE_|HARNESS_MCP_)/.test(k) || k === 'PYTHONPATH') delete env[k];
  }
  return Object.assign(env, {
    PYTHONUNBUFFERED: '1',
    CONSOLE_AUTO_HEALTH: '0',
    DASH_CONSOLE_ASSIST_ORIGINS: pageOrigin,
    DASH_CONSOLE_STATE: path.join(tmp, 'state'),
    DASH_CONSOLE_JOBS: path.join(tmp, 'jobs'),
    DASH_CONSOLE_PAGE_AUDIT: path.join(tmp, 'page-audit.jsonl'),
    DASH_CONSOLE_URL: consoleUrl,
    HARNESS_MCP_DOTENV: path.join(tmp, 'no.env'),   // never the checkout's .env, which may hold the live console's token
    HARNESS_MCP_AUDIT: path.join(tmp, 'mcp-audit.jsonl'),
    HARNESS_MCP_SCOPES: 'page'
  });
}

async function startConsole(port, env, logFile) {
  const log = fs.openSync(logFile, 'a');
  const proc = spawn(PYTHON, ['-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', String(port)],
    { cwd: CONSOLE_DIR, env, stdio: ['ignore', log, log] });
  const url = `http://127.0.0.1:${port}`;
  const until = Date.now() + 60_000;
  while (Date.now() < until) {
    if (proc.exitCode !== null) break;
    try {
      const r = await fetch(url + '/api/health');
      if (r.ok) return proc;
    } catch (e) { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 250));
  }
  proc.kill();
  throw new Error(`the test console did not start on ${url}:\n` + fs.readFileSync(logFile, 'utf8').slice(-3000));
}

/** A Claude Code session's side, minus the model: the console's MCP layer over stdio, spoken to in JSON-RPC. */
class Session {
  constructor(env, logFile) {
    this.proc = spawn(PYTHON, ['-m', 'mcp_layer.server'], { cwd: CONSOLE_DIR, env, stdio: ['pipe', 'pipe', fs.openSync(logFile, 'a')] });
    this.next = 1;
    this.waiting = new Map();
    readline.createInterface({ input: this.proc.stdout }).on('line', (line) => {
      let msg;
      try { msg = JSON.parse(line); } catch (e) { return; }
      const w = msg.id != null && this.waiting.get(msg.id);
      if (!w) return;
      this.waiting.delete(msg.id);
      if (msg.error) w.reject(new Error(`${msg.error.code}: ${msg.error.message}`));
      else w.resolve(msg.result);
    });
    this.proc.on('exit', (code) => {
      for (const w of this.waiting.values()) w.reject(new Error(`the MCP server exited (${code})`));
      this.waiting.clear();
    });
  }

  send(msg) { this.proc.stdin.write(JSON.stringify({ jsonrpc: '2.0', ...msg }) + '\n'); }

  request(method, params) {
    const id = this.next++;
    return new Promise((resolve, reject) => {
      this.waiting.set(id, { resolve, reject });
      this.send({ id, method, params });
    });
  }

  async init() {
    await this.request('initialize', { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'assist-browser-test', version: '1' } });
    this.send({ method: 'notifications/initialized' });
    const { tools } = await this.request('tools/list', {});
    return tools.map((t) => t.name);
  }

  /** One tool call: { ok, text, doc } — `ok` false is a refusal or an error the tool reported. */
  async call(name, args = {}) {
    const r = await this.request('tools/call', { name, arguments: args });
    const text = (r.content || []).map((c) => c.text || '').join('');
    let doc = null;
    try { doc = JSON.parse(text); } catch (e) { /* an error's text */ }
    return { ok: !r.isError, text, doc };
  }

  close() { this.proc.kill(); }
}

// ---------------------------------------------------------------- the world

let browser, kitServer, consoleProc, session, tmp;
let pageOrigin, consoleUrl;

before(async () => {
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'fleet-assist-browser-'));
  const deps = spawnSync(PYTHON, ['-c', 'import fastapi, uvicorn, mcp'], { encoding: 'utf8' });
  if (deps.status !== 0) {
    throw new Error(`${PYTHON} cannot import fastapi, uvicorn and mcp — this test needs all three, and a missing one is a ` +
      'failure, not a skip. Install: pip install -r tools/console/requirements.txt -r tools/console/requirements-mcp.txt ' +
      '(or run tools/test-assist-browser.sh, which does). ' + (deps.stderr || deps.error || '').toString().slice(-600));
  }
  const pw = await chromium();
  const [kitPort, consolePort] = [await freePort(), await freePort()];
  assert.notEqual(consolePort, LIVE_CONSOLE_PORT, 'the live console on :4001 is never touched');
  pageOrigin = `http://127.0.0.1:${kitPort}`;
  consoleUrl = `http://127.0.0.1:${consolePort}`;
  kitServer = await serveKit(kitPort);
  const env = brokerEnv(tmp, consoleUrl, pageOrigin);
  consoleProc = await startConsole(consolePort, env, path.join(tmp, 'console.log'));
  session = new Session(env, path.join(tmp, 'mcp.log'));
  const tools = await session.init();
  for (const t of ['page_attach', 'page_snapshot', 'page_read', 'page_click', 'page_fill', 'page_press', 'page_navigate']) {
    assert.ok(tools.includes(t), `the MCP layer offers ${t} (it offered: ${tools.join(', ')})`);
  }
  try {
    browser = await pw.launch();
  } catch (e) {
    throw new Error('Chromium did not launch: verify/node_modules/.bin/playwright install --with-deps chromium. ' + e.message);
  }
});

after(async () => {
  if (session) session.close();
  if (browser) await browser.close();
  if (consoleProc) consoleProc.kill();
  if (kitServer) kitServer.close();
  if (process.env.FLEET_ASSIST_KEEP_LOGS) console.log(`logs kept in ${tmp}`);
  else if (tmp) fs.rmSync(tmp, { recursive: true, force: true });
});

/** A fresh tab on the fixture (its own sessionStorage, so its own page session), shared, paired, in `mode`. */
async function pairedPage(mode, { modal } = {}) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  page.on('pageerror', (e) => console.log('page error:', e.message));
  await page.goto(`${pageOrigin}/tests/fixture.html?broker=${encodeURIComponent(consoleUrl)}`);
  if (modal !== undefined) await page.evaluate((m) => window.FleetAssist.configure({ modal: m }), modal);
  await page.evaluate(() => window.FleetAssist.open());
  const panel = page.locator('fleet-assist');
  await panel.locator('[data-k="pair"]').click({ timeout: 15_000 });
  const code = (await panel.locator('.code').textContent({ timeout: 15_000 })).trim();
  await panel.locator(`[data-k="mode-${mode}"]`).click();
  await assert.doesNotReject(page.waitForFunction((m) => window.FleetAssist.state().mode === m, mode));
  const attached = await session.call('page_attach', { code });
  assert.ok(attached.ok, attached.text);
  assert.equal(attached.doc.kind, 'fleet');
  assert.equal(attached.doc.origin, pageOrigin);
  assert.equal(attached.doc.page.source, 'templates/assistant/tests/fixture.html');
  return { page, context, panel, close: () => context.close() };
}

/** A snapshot, with refs by what the outline calls them. */
async function snapshot() {
  const s = await session.call('page_snapshot');
  assert.ok(s.ok, s.text);
  const outline = String(s.doc.outline || '');
  const ref = (kind, label) => {
    const esc = label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const m = outline.match(new RegExp(`\\[(e\\d+)\\] ${kind} "${esc}"`));
    assert.ok(m, `the snapshot lists ${kind} "${label}":\n${outline}`);
    return m[1];
  };
  return { doc: s.doc, outline, ref };
}

/** The tool call failed, with a refusal of `kind` whose message matches `rx`. */
function refused(r, kind, rx) {
  assert.equal(r.ok, false, `expected a refusal, but it ran: ${r.text}`);
  assert.match(r.text, new RegExp(`\\b${kind}\\b`), r.text);
  if (rx) assert.match(r.text, rx);
}

const out = (page) => page.locator('#out').textContent();
const value = (page, sel) => page.locator(sel).inputValue();

// ---------------------------------------------------------------- the rules

test('Look: the session reads, and every act is refused', async () => {
  const { page, close } = await pairedPage('look');
  try {
    const { ref } = await snapshot();
    refused(await session.call('page_click', { ref: ref('button', 'Save') }), 'refused', /Look only/);
    refused(await session.call('page_fill', { ref: ref('textbox', 'Display name'), text: 'Mallory' }), 'refused', /Look only/);
    refused(await session.call('page_press', { key: 'Enter' }), 'refused', /Look only/);
    refused(await session.call('page_navigate', { path: '/tests/fixture-2.html' }), 'refused', /Look only/);
    assert.equal(await value(page, '#name'), '');
    assert.equal(await out(page), '');
    assert.match(page.url(), /\/tests\/fixture\.html/);
  } finally {
    await close();
  }
});

test('Ask first: a Deny comes back as declined with the page unchanged, and an Allow runs', async () => {
  const { page, panel, close } = await pairedPage('ask');
  try {
    const { ref } = await snapshot();
    const name = ref('textbox', 'Display name');

    const denied = session.call('page_fill', { ref: name, text: 'Eve' });
    await panel.locator('[data-k^="deny-"]').click({ timeout: 20_000 });
    refused(await denied, 'declined', /did not allow it/);
    assert.equal(await value(page, '#name'), '', 'a denied fill typed nothing');

    const allowed = session.call('page_fill', { ref: name, text: 'Ada' });
    await panel.locator('[data-k^="allow-"]').click({ timeout: 20_000 });
    const done = await allowed;
    assert.ok(done.ok, done.text);
    assert.equal(await value(page, '#name'), 'Ada', 'an allowed fill ran');
  } finally {
    await close();
  }
});

test('the secret field is neither read nor filled, and the link that leaves the site is refused', async () => {
  const { page, close } = await pairedPage('act');
  try {
    const { outline, ref } = await snapshot();
    assert.doesNotMatch(outline, /hunter2/, 'a snapshot never carries a secret field\'s value');
    const pw = ref('secret field', 'Password');
    refused(await session.call('page_fill', { ref: pw, text: 'x' }), 'page', /secret field/);
    assert.equal(await value(page, '#pw'), 'hunter2-do-not-read');
    const read = await session.call('page_read', { ref: pw });
    refused(read, 'page', /secret field/);
    assert.doesNotMatch(read.text, /hunter2/);

    refused(await session.call('page_click', { ref: ref('link', 'Elsewhere') }), 'page', /leaves/);
    assert.match(page.url(), /\/tests\/fixture\.html/);

    // and the page is otherwise usable in Act: the refusals above are the rules, not a broken session
    const filled = await session.call('page_fill', { ref: ref('textbox', 'Display name'), text: 'Ada' });
    assert.ok(filled.ok, filled.text);
    const saved = await session.call('page_click', { ref: ref('button', 'Save') });
    assert.ok(saved.ok, saved.text);
    assert.equal(await out(page), 'saved: Ada / r');
  } finally {
    await close();
  }
});

/** Open a dialog through the session, then prove nothing inside or behind it can be used, and Escape closes it. */
async function dialogHolds(page, { opener, inside, isOpen }) {
  let s = await snapshot();
  const name = s.ref('textbox', 'Display name');
  const filled = await session.call('page_fill', { ref: name, text: 'Ada' });
  assert.ok(filled.ok, filled.text);
  const save = s.ref('button', 'Save');
  const opened = await session.call('page_click', { ref: s.ref('button', opener) });
  assert.ok(opened.ok, opened.text);
  assert.ok(await isOpen(), `${opener} opened its dialog`);

  s = await snapshot();
  assert.equal(s.doc.modal_open, true, 'the snapshot says a modal dialog is open');
  for (const [kind, label, act] of inside) {
    const r = act === 'fill'
      ? await session.call('page_fill', { ref: s.ref(kind, label), text: 'Mallory' })
      : await session.call('page_click', { ref: s.ref(kind, label) });
    refused(r, 'page', /modal dialog/);
  }
  refused(await session.call('page_press', { key: 'Enter' }), 'page', /modal dialog/);
  refused(await session.call('page_fill', { ref: name, text: 'Mallory' }), 'page', /modal dialog/);
  refused(await session.call('page_click', { ref: save }), 'page', /modal dialog/);
  refused(await session.call('page_navigate', { path: '/tests/fixture-2.html' }), 'page', /modal dialog/);

  assert.equal(await out(page), '', 'nothing inside or behind the dialog ran');
  assert.equal(await value(page, '#name'), 'Ada', 'the form behind the dialog is unchanged');
  assert.match(page.url(), /\/tests\/fixture\.html/);
  assert.ok(await isOpen(), 'the dialog is still open, unanswered');

  const esc = await session.call('page_press', { key: 'Escape' });
  assert.ok(esc.ok, esc.text);
  assert.equal(await isOpen(), false, 'Escape closed the dialog');
  assert.equal(await out(page), '', 'without answering it');
}

const nativeDialog = (page) => ({
  opener: 'Delete everything',
  inside: [['button', 'Yes, delete', 'click']],
  isOpen: () => page.evaluate(() => document.getElementById('confirm').open)
});
const bootstrapModal = (page) => ({
  opener: 'Open the settings dialog',
  inside: [['textbox', 'Nickname', 'fill'], ['button', 'Apply', 'click']],
  isOpen: () => page.evaluate(() => document.getElementById('settings').classList.contains('show'))
});

test('a native modal dialog: nothing inside or behind it is used, and Escape closes it', async () => {
  const { page, close } = await pairedPage('act');
  try {
    await dialogHolds(page, nativeDialog(page));
  } finally {
    await close();
  }
});

test('a Bootstrap-style modal: nothing inside or behind it is used, and Escape closes it', async () => {
  const { page, close } = await pairedPage('act');
  try {
    await dialogHolds(page, bootstrapModal(page));
    assert.equal(await value(page, '#nick'), '', 'nothing was typed into the dialog');
  } finally {
    await close();
  }
});

for (const [why, modal] of [['a selector that matches nothing', '.no-such-dialog'], ['a broken selector', '###not[a selector']]) {
  test(`configure({ modal }) with ${why} unprotects neither dialog`, async () => {
    const { page, close } = await pairedPage('act', { modal });
    try {
      await dialogHolds(page, nativeDialog(page));
      await dialogHolds(page, bootstrapModal(page));
    } finally {
      await close();
    }
  });
}

test('after a navigation the same session carries on, and the next command reaches the new page', async () => {
  const { page, close } = await pairedPage('act');
  try {
    const before = await session.call('page_snapshot');
    assert.ok(before.ok, before.text);
    const moved = await session.call('page_navigate', { path: '/tests/fixture-2.html' });
    assert.ok(moved.ok, moved.text);
    await page.waitForURL(/\/tests\/fixture-2\.html/);
    // The 2026-11-19 loss: the old page's abandoned long poll took this command, which then timed out.
    const { doc, ref } = await snapshot();
    assert.equal(doc.route, '/tests/fixture-2.html');
    assert.equal(doc.page.source, 'templates/assistant/tests/fixture-2.html');
    const hello = await session.call('page_click', { ref: ref('button', 'Say hello') });
    assert.ok(hello.ok, hello.text);
    assert.equal(await out(page), 'hello');

    // The person moves between the pages themselves, each time while the page's long poll waits in the
    // console. Every load leaves that poll behind with nobody on the other end; a command handed to one of
    // them is lost (it times out). Only the newest poll of a session may take a command.
    const pages = ['fixture.html', 'fixture-2.html', 'fixture.html', 'fixture-2.html'];
    for (const file of pages) {
      await page.waitForTimeout(400);                       // the current page's poll is waiting in the console
      await page.locator(`header nav a[href="${file}"]`).click();
      await page.waitForURL(new RegExp(`/tests/${file.replace('.', '\\.')}$`));
      await page.waitForFunction(() => window.FleetAssist.state().shared);
    }
    await page.waitForTimeout(400);
    for (let i = 0; i < 3; i++) {
      const s = await session.call('page_snapshot');
      assert.ok(s.ok, `command ${i + 1} after the person's navigations reached the page: ${s.text}`);
      assert.equal(s.doc.route, '/tests/fixture-2.html');
    }
    const again = await snapshot();
    const hi = await session.call('page_click', { ref: again.ref('button', 'Say hello') });
    assert.ok(hi.ok, hi.text);
    assert.equal(await out(page), 'hello');
  } finally {
    await close();
  }
});
