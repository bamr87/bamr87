import { describe, expect, it } from 'vitest';
import { mergeRoster, parseGitmodules, parseRosterText } from './manifest.js';
import type { RosterEntry } from './types.js';

// ── fixtures: a slice of the real bamr87 hub .gitmodules ─────────────────────

/** Verbatim entries from bamr87/bamr87 — tab-indented, incl. the master-branch scripts
 *  repo and the external microsoft/skills mirror with its extra `update = merge` key. */
const HUB_GITMODULES = `[submodule "README"]
\tpath = projects/README
\turl = https://github.com/bamr87/README.git
\tbranch = main
[submodule "scripts"]
\tpath = projects/scripts
\turl = https://github.com/bamr87/scripts.git
\tbranch = master
[submodule "skills"]
\tpath = projects/skills
\turl = https://github.com/microsoft/skills.git
\tbranch = main
\tupdate = merge
[submodule "projects/ai-seed"]
\tpath = projects/ai-seed
\turl = https://github.com/bamr87/ai-seed.git
\tbranch = main
`;

// ── parseGitmodules ───────────────────────────────────────────────────────────

describe('parseGitmodules — real hub shape', () => {
  const roster = parseGitmodules(HUB_GITMODULES);

  it('yields one gitmodules entry per section, in file order', () => {
    expect(roster.map((r) => r.slug)).toEqual([
      'bamr87/README',
      'bamr87/scripts',
      'microsoft/skills',
      'bamr87/ai-seed',
    ]);
    expect(roster.every((r) => r.source === 'gitmodules')).toBe(true);
  });

  it('reads the branch key (scripts tracks master, not main)', () => {
    const scripts = roster.find((r) => r.slug === 'bamr87/scripts');
    expect(scripts?.branch).toBe('master');
  });

  it('keeps external repos and ignores unknown keys like update', () => {
    const skills = roster.find((r) => r.slug === 'microsoft/skills');
    expect(skills).toEqual({ slug: 'microsoft/skills', source: 'gitmodules', branch: 'main' });
  });
});

describe('parseGitmodules — url shapes and skips', () => {
  it('derives the slug from a git@ ssh url, with or without .git', () => {
    const roster = parseGitmodules(
      '[submodule "a"]\n  url = git@github.com:bamr87/zer0-mistakes.git\n' +
        '[submodule "b"]\n  url = git@github.com:bamr87/it-journey\n',
    );
    expect(roster.map((r) => r.slug)).toEqual(['bamr87/zer0-mistakes', 'bamr87/it-journey']);
  });

  it('skips entries whose url is not github.com', () => {
    const roster = parseGitmodules(
      '[submodule "gl"]\n\turl = https://gitlab.com/x/y.git\n\tbranch = main\n' +
        '[submodule "ssh-gl"]\n\turl = git@gitlab.com:x/y.git\n' +
        '[submodule "ok"]\n\turl = https://github.com/bamr87/scripts.git\n',
    );
    expect(roster.map((r) => r.slug)).toEqual(['bamr87/scripts']);
  });

  it('defaults branch to null and skips sections with no url', () => {
    const roster = parseGitmodules(
      '[submodule "nobranch"]\n\turl = https://github.com/o/r.git\n' +
        '[submodule "nourl"]\n\tpath = projects/ghost\n\tbranch = main\n',
    );
    expect(roster).toEqual([{ slug: 'o/r', source: 'gitmodules', branch: null }]);
  });

  it('dedupes case-insensitively, keeping the first entry', () => {
    const roster = parseGitmodules(
      '[submodule "a"]\n\turl = https://github.com/Bamr87/Scripts.git\n\tbranch = master\n' +
        '[submodule "b"]\n\turl = https://github.com/bamr87/scripts.git\n\tbranch = main\n',
    );
    expect(roster).toEqual([{ slug: 'Bamr87/Scripts', source: 'gitmodules', branch: 'master' }]);
  });

  it('ignores keys under non-submodule sections', () => {
    const roster = parseGitmodules(
      '[core]\n\turl = https://github.com/not/counted.git\n' +
        '[submodule "s"]\n\turl = https://github.com/o/r\n',
    );
    expect(roster.map((r) => r.slug)).toEqual(['o/r']);
  });

  it('never throws on junk — malformed lines are skipped silently', () => {
    expect(parseGitmodules('')).toEqual([]);
    expect(parseGitmodules('not ini at all\n===\n[unclosed\n\turl no equals sign')).toEqual([]);
    const roster = parseGitmodules(
      '[submodule "ok"]\ngarbage line here\n  url = https://github.com/o/r.git\n\t= dangling\n',
    );
    expect(roster.map((r) => r.slug)).toEqual(['o/r']);
  });
});

// ── parseRosterText ───────────────────────────────────────────────────────────

describe('parseRosterText', () => {
  it('splits on newlines, commas, and spaces; tolerates full github URLs', () => {
    const roster = parseRosterText(
      'bamr87/it-journey, bamr87/zer0-mistakes\nhttps://github.com/microsoft/skills.git owner/repo',
    );
    expect(roster.map((r) => r.slug)).toEqual([
      'bamr87/it-journey',
      'bamr87/zer0-mistakes',
      'microsoft/skills',
      'owner/repo',
    ]);
    expect(roster[0]).toEqual({ slug: 'bamr87/it-journey', source: 'manual', branch: null });
  });

  it('drops invalid tokens and dedupes case-insensitively', () => {
    const roster = parseRosterText('bamr87/scripts not-a-slug Bamr87/SCRIPTS ///');
    expect(roster).toEqual([{ slug: 'bamr87/scripts', source: 'manual', branch: null }]);
  });

  it('returns [] for empty or junk-only input', () => {
    expect(parseRosterText('')).toEqual([]);
    expect(parseRosterText('  \n , , \n just words here ')).toEqual([]);
  });
});

// ── mergeRoster ───────────────────────────────────────────────────────────────

/** Terse RosterEntry factory. */
function entry(slug: string, extra: Partial<RosterEntry> = {}): RosterEntry {
  return { slug, source: 'manual', branch: null, ...extra };
}

describe('mergeRoster', () => {
  it('unions disjoint rosters, existing first then incoming, without mutating inputs', () => {
    const existing = [entry('a/one')];
    const incoming = [entry('b/two', { source: 'gitmodules', branch: 'main' })];
    const merged = mergeRoster(existing, incoming);

    expect(merged.map((r) => r.slug)).toEqual(['a/one', 'b/two']);
    expect(existing).toEqual([entry('a/one')]);
    expect(merged[0]).not.toBe(existing[0]);
  });

  it('on collision keeps the existing entry but upgrades branch:null and manual→gitmodules', () => {
    const merged = mergeRoster(
      [entry('Bamr87/Scripts')],
      [entry('bamr87/scripts', { source: 'gitmodules', branch: 'master' })],
    );
    // Existing slug casing survives; the richer gitmodules metadata is folded in.
    expect(merged).toEqual([{ slug: 'Bamr87/Scripts', source: 'gitmodules', branch: 'master' }]);
  });

  it('never downgrades: a manual incoming record cannot overwrite gitmodules metadata', () => {
    const merged = mergeRoster(
      [entry('o/r', { source: 'gitmodules', branch: 'dev' })],
      [entry('o/r')],
    );
    expect(merged).toEqual([{ slug: 'o/r', source: 'gitmodules', branch: 'dev' }]);
  });

  it('keeps an existing non-null branch over a differing incoming one', () => {
    const merged = mergeRoster(
      [entry('o/r', { source: 'gitmodules', branch: 'master' })],
      [entry('o/r', { source: 'gitmodules', branch: 'main' })],
    );
    expect(merged[0].branch).toBe('master');
  });
});
