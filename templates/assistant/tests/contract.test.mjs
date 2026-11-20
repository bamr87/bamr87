/**
 * Contract tests for the assistant kit — spec: bamr87/bamr87 specs/ASSIST.md.
 *
 * These lock what a session may ask of a page and what the page will never do
 * on a session's word, as far as that can be said without a browser: the
 * action allowlist and its argument checks, the rule that the broker is this
 * machine, and that the kit's files agree with each other. The rules that need
 * a DOM (a modal dialog, a secret field, a link that leaves the site) are
 * proven in a browser against tests/fixture.html — the evidence bundle
 * test/evidence/fleet-assist/ holds the transcript — and the lists this file
 * shares with the console's broker are held equal by
 * tools/console/test_page_bridge.py.
 *
 *   node --test tests/            (or: npm test)
 *
 * No dependencies and no DOM: the core's pure half loads under Node, and the
 * custom element bails out when `document` is undefined, so require() is safe.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { createRequire } from 'node:module';

const KIT = dirname(dirname(fileURLToPath(import.meta.url)));
const read = (rel) => readFileSync(join(KIT, rel), 'utf8');
const Core = createRequire(import.meta.url)(join(KIT, 'fleet-assist.js'));
const refused = (fn, pattern) => assert.throws(fn, (e) => e instanceof Core.Refusal && e.kind === 'page' && pattern.test(e.message));

test('eight actions, in two tiers, and nothing else', () => {
  assert.deepEqual(Core.LOOK, ['snapshot', 'read', 'data', 'highlight']);
  assert.deepEqual(Core.ACT, ['navigate', 'click', 'fill', 'press']);
  assert.deepEqual(Core.ASKS, ['click', 'fill', 'press'], 'navigating only changes which page is read: it does not wait for a yes');
  assert.deepEqual(Core.MODES, ['look', 'ask', 'act']);
  for (const action of ['eval', 'script', 'screenshot', 'upload', 'drag', '']) {
    refused(() => Core.checkCommand({ action, args: {} }), /action must be one of/);
  }
});

test('an element is a ref from a snapshot, never a selector, a script or a coordinate', () => {
  assert.deepEqual(Core.checkCommand({ action: 'click', args: { ref: 'e12' } }), { ref: 'e12' });
  for (const args of [{ selector: '#save' }, { ref: 'e1', script: 'x()' }, { ref: 'e1', x: 10, y: 20 }]) {
    refused(() => Core.checkCommand({ action: 'click', args }), /takes ref only/);
  }
  for (const ref of ['#save', 'button', 'e', 'E1', 'e1;drop', 'e123456', 7, null]) {
    refused(() => Core.checkCommand({ action: 'click', args: { ref } }), /never a selector/);
  }
});

test('a path is inside the site: one leading slash, never a host', () => {
  for (const path of ['/', '/about/', '/posts/2026/x.html?y=1#top', '/a%20b']) assert.equal(Core.inAppPath(path), true, path);
  for (const path of ['//evil.example/x', 'https://evil.example', 'about', '', '/a b', '/a\\b', 'javascript:alert(1)', `/${'x'.repeat(400)}`, null]) {
    assert.equal(Core.inAppPath(path), false, String(path));
  }
  refused(() => Core.checkCommand({ action: 'navigate', args: { path: '//evil.example' } }), /in-app path/);
});

test('a key is one of the listed keys, and text is bounded', () => {
  assert.deepEqual(Core.checkCommand({ action: 'press', args: { key: 'Escape' } }), { key: 'Escape' });
  for (const key of ['a', 'Meta', 'F12', 'Control+A', 'Delete', '']) {
    refused(() => Core.checkCommand({ action: 'press', args: { key } }), /key must be one of/);
  }
  assert.deepEqual(Core.checkCommand({ action: 'fill', args: { ref: 'e1', text: 'Ada', submit: true } }), { ref: 'e1', text: 'Ada', submit: true });
  refused(() => Core.checkCommand({ action: 'fill', args: { ref: 'e1', text: 'x'.repeat(4001) } }), /at most 4000/);
  refused(() => Core.checkCommand({ action: 'fill', args: { ref: 'e1', text: 'a\0b' } }), /text must be/);
  assert.equal(Core.checkCommand({ action: 'snapshot', args: { max_chars: 9e9 } }).max_chars, 24000);
  assert.equal(Core.checkCommand({ action: 'snapshot', args: { max_chars: 1 } }).max_chars, 500);
});

test('the broker is the console on this machine, whatever the tag says', () => {
  assert.equal(Core.brokerUrl(''), 'http://127.0.0.1:4001');
  assert.equal(Core.brokerUrl('http://localhost:4010/'), 'http://localhost:4010');
  assert.equal(Core.brokerUrl('http://[::1]:4001'), 'http://[::1]:4001');
  for (const url of ['https://console.example.com', 'http://192.168.1.10:4001', 'http://127.0.0.1.evil.example', 'http://localhost.evil.example', '//127.0.0.1']) {
    refused(() => Core.brokerUrl(url), /this machine|not a URL/);
  }
  refused(() => Core.brokerUrl('http://user:pw@127.0.0.1:4001'), /credentials/);
  refused(() => Core.brokerUrl('file:///etc/passwd'), /http/);
});

test('a secret field is named the way the console names one', () => {
  for (const name of ['password', 'api_key', 'api-key', 'GH_TOKEN', 'client_secret', 'Credential', 'private key']) assert.match(name, Core.SECRET_NAME);
  for (const name of ['display_name', 'email', 'search', 'colour']) assert.doesNotMatch(name, Core.SECRET_NAME);
});

test('a pairing code reads the way the panel shows it', () => {
  assert.equal(Core.pairingCode('abcdefgh'), 'ABCD-EFGH');
  assert.equal(Core.pairingCode('ABCD-EFGH'), 'ABCD-EFGH');
  assert.equal(Core.trimBase('bamr87/'), '/bamr87');
  assert.equal(Core.trimBase('/'), '');
});

test('the payload sends nothing until the panel is opened, and only to the broker', () => {
  const js = read('fleet-assist.js');
  assert.equal((js.match(/root\.fetch\(/g) || []).length, 1, 'one place talks to the network');
  assert.match(js, /root\.fetch\(opts\.broker \+ '\/api\/assist\/fleet\/' \+ verb/);
  for (const banned of ['XMLHttpRequest', 'sendBeacon', 'WebSocket', 'EventSource', 'document.cookie', 'localStorage', 'eval(', 'new Function']) {
    assert.equal(js.includes(banned), false, `${banned} has no place in the payload`);
  }
  assert.match(js, /'Content-Type': 'text\/plain;charset=UTF-8'/, 'a simple request: no preflight to lose while a page unloads');
  assert.equal(/\/api\/assist\/fleet\/[^']*sid/.test(js), false, 'a session id rides in the body, never in an address');
});

test('the kit agrees with itself: one version, every file listed, every adapter mounts the tag', () => {
  const version = /^version: (\S+)$/m.exec(read('VERSION'))[1];
  assert.equal(Core.version, version);
  assert.equal(JSON.parse(read('package.json')).version, version);
  assert.match(read('fleet-assist.js'), new RegExp(`fleet-assist v${version.replace(/\./g, '\\.')} `));
  const listed = read('VERSION');
  for (const file of readdirSync(join(KIT, 'adapters'))) {
    assert.ok(listed.includes(`adapters/${file}`), `VERSION lists adapters/${file}`);
    const text = read(`adapters/${file}`);
    assert.match(text, /fleet-assist|AssistBridge/, `${file} mounts the tag`);
    assert.match(text, /UPS-AST/, `${file} names its spec`);
  }
});

test('every adapter that knows its build is off outside development unless the repo says so', () => {
  assert.match(read('adapters/jekyll.html'), /jekyll\.environment != "production" or fa\.deployed/);
  assert.match(read('adapters/django.html'), /\{% if FLEET_ASSIST %\}/);
  assert.match(read('adapters/mkdocs.html'), /fa and fa\.enabled/);
  assert.match(read('adapters/AssistBridge.tsx'), /if \(!enabled\) return null;/);
  assert.equal(/enabled = /.test(read('adapters/AssistBridge.tsx')), false, 'the React adapter has no default for `enabled`: the app decides');
});
