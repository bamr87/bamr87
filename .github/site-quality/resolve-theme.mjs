#!/usr/bin/env node
// =============================================================================
// resolve-theme.mjs — find the Jekyll theme a build will use and pin it
// -----------------------------------------------------------------------------
// The fresh-theme build is the default: a remote_theme is resolved to the
// commit SHA its ref points at RIGHT NOW (`git ls-remote`), recorded in the
// report and job summary, and the build is pinned to exactly that SHA. Nothing
// restores an older copy: the workflow either clones it fresh or (theme-cache:
// true) restores a cache keyed to this SHA, so a cache can never be stale.
//
// Usage: node resolve-theme.mjs --source <dir> --out <theme.json>
//          [--override-config <file>] [--theme-repo owner/repo] [--theme-ref ref]
// Writes theme.json { kind: remote|gem|none, repo, ref, sha, gem, source } and,
// for a remote theme, a Jekyll config overlay pinning remote_theme to the SHA
// and serving from the site root (url http://127.0.0.1:4000, baseurl "").
// =============================================================================
import { existsSync, readFileSync, writeFileSync, appendFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { join } from 'node:path';
import { parseArgs } from 'node:util';
import { parse } from 'yaml';

/** Parse a remote_theme value: owner/repo[@ref], or a github.com URL. */
export function parseRemoteTheme(value) {
  if (typeof value !== 'string' || !value.trim()) return null;
  let v = value.trim().replace(/^https?:\/\/github\.com\//, '').replace(/\.git$/, '');
  let ref = '';
  const at = v.indexOf('@');
  if (at > -1) { ref = v.slice(at + 1); v = v.slice(0, at); }
  const m = v.match(/^([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+)$/);
  return m ? { repo: `${m[1]}/${m[2]}`, ref } : null;
}

/** Pick the SHA for `ref` out of `git ls-remote` output (peeled tags win). */
export function pickSha(lsRemote, ref) {
  const lines = lsRemote.trim().split('\n').filter(Boolean).map((l) => l.split(/\s+/));
  const want = ref || 'HEAD';
  const candidates = want === 'HEAD'
    ? ['HEAD']
    : [`refs/tags/${want}^{}`, `refs/tags/${want}`, `refs/heads/${want}`, want];
  for (const c of candidates) {
    const hit = lines.find(([, name]) => name === c);
    if (hit) return hit[0];
  }
  return '';
}

function lsRemote(repo, ref) {
  const args = ['ls-remote', `https://github.com/${repo}.git`];
  args.push(ref || 'HEAD');
  return execFileSync('git', args, { encoding: 'utf8', timeout: 60_000, env: { ...process.env, GIT_TERMINAL_PROMPT: '0' } });
}

function main() {
  const { values: a } = parseArgs({
    options: {
      source: { type: 'string', default: '.' }, out: { type: 'string' },
      'override-config': { type: 'string', default: '' },
      'theme-repo': { type: 'string', default: '' }, 'theme-ref': { type: 'string', default: '' },
    },
  });
  const cfgPath = join(a.source, '_config.yml');
  let cfg = {};
  if (existsSync(cfgPath)) {
    try { cfg = parse(readFileSync(cfgPath, 'utf8'), { maxAliasCount: -1 }) || {}; } catch (e) {
      console.log(`::warning title=site-quality theme::could not parse ${cfgPath}: ${e.message}`);
    }
  }
  const theme = { kind: 'none', repo: '', ref: '', sha: '', gem: '', source: '' };
  const fromInput = a['theme-repo'] ? { repo: a['theme-repo'], ref: a['theme-ref'] } : null;
  const remote = fromInput || parseRemoteTheme(cfg.remote_theme);
  if (remote) {
    Object.assign(theme, { kind: 'remote', repo: remote.repo, ref: remote.ref || 'HEAD', source: fromInput ? 'input' : '_config.yml remote_theme' });
    if (/^[0-9a-f]{40}$/.test(remote.ref)) {
      theme.sha = remote.ref;
    } else {
      try {
        theme.sha = pickSha(lsRemote(remote.repo, remote.ref), remote.ref);
      } catch (e) {
        console.log(`::warning title=site-quality theme::git ls-remote ${remote.repo} failed — building unpinned: ${String(e.message).split('\n')[0]}`);
      }
      if (!theme.sha) console.log(`::warning title=site-quality theme::could not resolve ${remote.repo}@${theme.ref} to a commit — building unpinned`);
    }
  } else if (typeof cfg.theme === 'string' && cfg.theme) {
    // A gem theme: the version comes from Gemfile.lock after `bundle install`
    // (the workflow fills it in); the fleet never commits lockfiles, so it is
    // whatever resolved fresh in this run.
    Object.assign(theme, { kind: 'gem', gem: cfg.theme, source: '_config.yml theme' });
  }

  if (a['override-config']) {
    const lines = ['# written by site-quality resolve-theme.mjs — serve from the site root', 'url: "http://127.0.0.1:4000"', 'baseurl: ""'];
    if (theme.kind === 'remote' && theme.sha && !fromInput) lines.push(`remote_theme: "${theme.repo}@${theme.sha}"`);
    writeFileSync(a['override-config'], lines.join('\n') + '\n');
  }
  writeFileSync(a.out, JSON.stringify(theme, null, 2));
  const label = theme.kind === 'remote' ? `${theme.repo}@${theme.ref} -> ${theme.sha || 'unresolved'}`
    : theme.kind === 'gem' ? `gem ${theme.gem}` : 'none (site has its own layouts)';
  console.log(`theme: ${label}`);
  if (process.env.GITHUB_OUTPUT) {
    appendFileSync(process.env.GITHUB_OUTPUT, `kind=${theme.kind}\nrepo=${theme.repo}\nref=${theme.ref}\nsha=${theme.sha}\ngem=${theme.gem}\nlabel=${label}\n`);
  }
}

if (import.meta.url === `file://${process.argv[1]}`) main();
