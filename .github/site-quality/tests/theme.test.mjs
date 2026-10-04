import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseRemoteTheme, pickSha } from '../resolve-theme.mjs';

test('parseRemoteTheme: owner/repo, @ref, github URL', () => {
  assert.deepEqual(parseRemoteTheme('bamr87/zer0-mistakes'), { repo: 'bamr87/zer0-mistakes', ref: '' });
  assert.deepEqual(parseRemoteTheme('bamr87/zer0-mistakes@v0.22.0'), { repo: 'bamr87/zer0-mistakes', ref: 'v0.22.0' });
  assert.deepEqual(parseRemoteTheme('https://github.com/bamr87/zer0-mistakes'), { repo: 'bamr87/zer0-mistakes', ref: '' });
});

test('pickSha prefers the peeled tag', () => {
  const out = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\trefs/tags/v1\nbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\trefs/tags/v1^{}\n';
  assert.equal(pickSha(out, 'v1'), 'b'.repeat(40));
  assert.equal(pickSha('cccccccccccccccccccccccccccccccccccccccc\tHEAD\n'), 'c'.repeat(40));
  assert.equal(pickSha(''), '');
});
