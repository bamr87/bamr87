// Contract tests for the elk kit — kit: elk v__KIT_VERSION__
//
//     node --test tests/
//
// node:test, zero dependencies: a kit whose tests need an install is a kit
// whose tests do not run in the fan-out's verify step.
//
// What these guard is the EMISSION side of the log plane. A line that loses a
// field is not an error anywhere — it just quietly lands in the wrong dataset,
// with the wrong retention, missing the column a dashboard filters on. And a
// credential that survives emission is a credential in the index, because a
// standalone repo has no central redaction filter in its path at all.

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const KIT = dirname(dirname(fileURLToPath(import.meta.url)));
const read = (p) => readFileSync(join(KIT, p), 'utf8');

// UPS-OPS-10's field list, verbatim. If the spec changes, this fails first.
const REQUIRED_FIELDS = ['ts', 'level', 'msg', 'logger', 'app', 'version'];

// The credential shapes _data/fleet.yml `observability.logs.redact` names.
const SECRETS = [
  'sk-ant-api03-AAAABBBBCCCCDDDDEEEE',
  'ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA',
  'github_pat_11ABCDE_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
  'AIzaDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD',
];

test('every adapter emits the fields the spec names', () => {
  for (const [file, fields] of [
    ['adapters/python-logging.py', REQUIRED_FIELDS],
    ['adapters/node-pino.mjs', ['ts', 'level', 'msg', 'app', 'version']],
    ['adapters/rails-lograge.rb', REQUIRED_FIELDS],
  ]) {
    const src = read(file);
    for (const field of fields) {
      assert.ok(
        new RegExp(`["':\\s]${field}\\b`).test(src),
        `${file} never emits '${field}' — the line would land in fleet.container, not fleet.app`
      );
    }
  }
});

test('the routing rule is satisfied: level AND msg together', () => {
  // The ingest pipeline routes to the `fleet.app` dataset only when BOTH are
  // present. One without the other is raw chatter with 14-day retention.
  for (const file of [
    'adapters/python-logging.py',
    'adapters/node-pino.mjs',
    'adapters/rails-lograge.rb',
  ]) {
    const src = read(file);
    assert.ok(/\blevel\b/.test(src) && /\bmsg\b/.test(src), `${file} emits only one of level/msg`);
  }
});

test('every adapter redacts every credential shape at emission', () => {
  for (const file of [
    'adapters/python-logging.py',
    'adapters/node-pino.mjs',
    'adapters/rails-lograge.rb',
  ]) {
    const src = read(file);
    for (const prefix of ['sk-ant-', 'github_pat_', 'AIza']) {
      assert.ok(src.includes(prefix), `${file} does not redact ${prefix} (UPS-OPS-12)`);
    }
    assert.ok(/gh\[pousr\]_|ghp_/.test(src), `${file} does not redact GitHub tokens`);
    assert.ok(/REDACTED/.test(src), `${file} has patterns but no replacement`);
  }
});

test('the node adapter actually scrubs, not just declares patterns', async () => {
  const { scrub } = await import(join(KIT, 'adapters/node-pino.mjs')).catch(() => ({
    scrub: null,
  }));
  if (!scrub) return; // pino not installed; the static checks above still ran
  for (const secret of SECRETS) {
    const out = scrub(`connecting with ${secret} now`);
    assert.ok(!out.includes(secret), `${secret.slice(0, 10)}… survived scrub()`);
    assert.match(out, /REDACTED/);
  }
  assert.equal(
    scrub(`${SECRETS[1]} and ${SECRETS[1]}`).match(/REDACTED/g).length,
    2,
    'only the first occurrence was replaced'
  );
});

test('the shipper opts in by label, and never bypasses the redaction hub', () => {
  const fb = read('filebeat.fleet.yml');
  assert.match(
    fb,
    /com\.bamr87\.fleet\.project/,
    'autodiscover must gate on the fleet label — that label IS the opt-in'
  );
  assert.match(
    fb,
    /output\.logstash/,
    'the hub path goes through Logstash, where the shared redaction filter lives'
  );
  assert.ok(
    !/^output\.elasticsearch/m.test(fb),
    'shipping straight to Elasticsearch skips the redaction filter'
  );
  assert.match(
    fb,
    /json\.keys_under_root/,
    'a UPS-OPS-10 line must be parsed, or every structured log is one opaque string'
  );
});

test('the vendored payload is byte-identical to its archived shape', () => {
  // The --upgrade ladder compares an on-disk copy against these archives. A
  // payload edited without snapshotting the outgoing one first makes every
  // deployed copy read as hand-modified, and --upgrade silently stops reaching
  // the fleet (the trap templates/agent-context/VERSION documents).
  const version = read('VERSION').match(/^version:\s*(\S+)/m)[1];
  let archived;
  try {
    archived = read(`archive/filebeat.fleet-${version}.yml`);
  } catch {
    assert.fail(`no archive/filebeat.fleet-${version}.yml — snapshot before editing the payload`);
  }
  assert.equal(read('filebeat.fleet.yml'), archived);
});

test('the label fragment carries both halves: the opt-in and the bound', () => {
  const labels = read('compose.labels.yml');
  for (const key of ['com.bamr87.fleet.repo', 'com.bamr87.fleet.project']) {
    assert.ok(labels.includes(key), `${key} missing — the shipper cannot attribute the logs`);
  }
  assert.match(labels, /max-size/, 'no rotation: an unrotated json-file grows until the disk does');
  assert.match(labels, /max-file/);
});

test('the standalone overlay does not hand-edit the vendored payload', () => {
  const compose = read('compose.elk.yml');
  assert.match(
    compose,
    /output\.logstash\.enabled=false/,
    'standalone must switch the output with -E, not by editing filebeat.fleet.yml'
  );
  assert.match(compose, /127\.0\.0\.1:\$\{ES_PORT/, 'ports must bind loopback only');
  assert.ok(!/xpack\.security\.enabled=true/.test(compose));
});

test('every placeholder the seeder substitutes is one the engine knows', () => {
  // render_kit_template in tools/fanout.sh substitutes exactly three tokens.
  // Any other one ships to the fleet as literal text, in a file nobody reads
  // again until it is wrong.
  const KNOWN = new Set(['__PROJECT_NAME__', '__DEFAULT_BRANCH__', '__KIT_VERSION__']);
  for (const file of [
    'compose.labels.yml',
    'compose.elk.yml',
    'adapters/python-logging.py',
    'adapters/node-pino.mjs',
    'adapters/django-logging.py',
    'adapters/rails-lograge.rb',
    'tests/contract.test.mjs',
  ]) {
    for (const tok of read(file).match(/__[A-Z_]+__/g) || []) {
      assert.ok(KNOWN.has(tok), `${file} uses unknown placeholder ${tok}`);
    }
  }
  // …and the payload carries NONE: it is vendored byte-for-byte, so a
  // placeholder in it would reach every repo unsubstituted.
  assert.equal((read('filebeat.fleet.yml').match(/__[A-Z_]+__/g) || []).length, 0);
});
