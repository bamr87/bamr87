// Fleet-roster manifest parsing — how the cockpit learns WHICH repos make up the
// fleet. `parseGitmodules` mines a monorepo's .gitmodules (the bamr87 hub pattern:
// ~40 submodules, each a fleet member) into roster entries; `parseRosterText` accepts
// hand-typed owner/name lists; `mergeRoster` unions the two, preferring the richer
// gitmodules metadata. Slugs only — never tokens (golden rule #7). No I/O, never
// throws on malformed input: junk lines and non-GitHub urls are skipped silently.

import { parseRepo, repoSlug } from '../github/types.js';
import type { RosterEntry } from './types.js';

// ── url → slug ────────────────────────────────────────────────────────────────

/** `owner/name` from a github.com clone URL (https or ssh form), or null for any other host. */
function slugFromGithubUrl(url: string): string | null {
  const m =
    /^https?:\/\/github\.com\/(.+)$/i.exec(url.trim()) ??
    /^git@github\.com:(.+)$/i.exec(url.trim());
  if (!m) return null;
  const repo = parseRepo(m[1]); // strips a trailing `.git`/`/` and validates owner/name
  return repo ? repoSlug(repo) : null;
}

// ── .gitmodules ───────────────────────────────────────────────────────────────

/** Keys accumulated for one `[submodule "…"]` section during the line scan. */
interface SubmoduleSection {
  url: string | null;
  branch: string | null;
}

const SUBMODULE_HEADER = /^\s*\[submodule\s+"[^"]*"\]\s*$/;
const ANY_HEADER = /^\s*\[[^\]]*\]\s*$/;
const KEY_VALUE = /^\s*([A-Za-z][A-Za-z0-9-]*)\s*=\s*(.*?)\s*$/;

/**
 * Parse .gitmodules INI text into a fleet roster. Reads `url` (→ slug) and `branch`
 * from each `[submodule "…"]` section; other keys (`path`, `update`, …) and sections
 * are ignored. Entries whose url is not a github.com clone URL are skipped, order is
 * preserved, and duplicate slugs (case-insensitive) keep the first occurrence. PURE
 * and total: malformed lines are skipped silently, never throws.
 */
export function parseGitmodules(text: string): RosterEntry[] {
  const sections: SubmoduleSection[] = [];
  let current: SubmoduleSection | null = null;

  for (const line of text.split(/\r?\n/)) {
    if (SUBMODULE_HEADER.test(line)) {
      current = { url: null, branch: null };
      sections.push(current);
      continue;
    }
    if (ANY_HEADER.test(line)) {
      current = null; // some other section ([core] etc.) — its keys are not ours
      continue;
    }
    if (!current) continue;
    const kv = KEY_VALUE.exec(line);
    if (!kv || kv[2] === '') continue;
    if (kv[1] === 'url') current.url = kv[2];
    else if (kv[1] === 'branch') current.branch = kv[2];
  }

  const out: RosterEntry[] = [];
  const seen = new Set<string>();
  for (const s of sections) {
    const slug = s.url === null ? null : slugFromGithubUrl(s.url);
    if (!slug || seen.has(slug.toLowerCase())) continue;
    seen.add(slug.toLowerCase());
    out.push({ slug, source: 'gitmodules', branch: s.branch });
  }
  return out;
}

// ── hand-typed rosters ────────────────────────────────────────────────────────

/**
 * Parse a hand-typed repo list — newline/comma/space separated `owner/name` tokens,
 * tolerating full GitHub URLs (validated via {@link parseRepo}). Invalid tokens are
 * dropped, duplicates (case-insensitive) keep the first occurrence. PURE and total.
 */
export function parseRosterText(text: string): RosterEntry[] {
  const out: RosterEntry[] = [];
  const seen = new Set<string>();
  for (const token of text.split(/[\s,]+/)) {
    if (token === '') continue;
    const repo = parseRepo(token);
    if (!repo) continue;
    const slug = repoSlug(repo);
    if (seen.has(slug.toLowerCase())) continue;
    seen.add(slug.toLowerCase());
    out.push({ slug, source: 'manual', branch: null });
  }
  return out;
}

// ── merging ───────────────────────────────────────────────────────────────────

/**
 * Union two rosters, deduped by lowercase slug: `existing` entries first (order kept),
 * then unseen `incoming` entries. On a collision the existing entry wins, except that a
 * `branch: null` is upgraded from the incoming entry and a `source: 'gitmodules'`
 * incoming record upgrades a manual one (gitmodules metadata is richer). PURE — the
 * inputs are never mutated.
 */
export function mergeRoster(existing: RosterEntry[], incoming: RosterEntry[]): RosterEntry[] {
  const out: RosterEntry[] = [];
  const indexByKey = new Map<string, number>();

  for (const entry of existing) {
    const key = entry.slug.toLowerCase();
    if (indexByKey.has(key)) continue;
    indexByKey.set(key, out.length);
    out.push({ ...entry });
  }

  for (const entry of incoming) {
    const key = entry.slug.toLowerCase();
    const at = indexByKey.get(key);
    if (at === undefined) {
      indexByKey.set(key, out.length);
      out.push({ ...entry });
      continue;
    }
    const kept = out[at];
    if (kept.branch === null && entry.branch !== null) kept.branch = entry.branch;
    if (kept.source !== 'gitmodules' && entry.source === 'gitmodules') kept.source = 'gitmodules';
  }

  return out;
}
