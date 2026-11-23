// static.ts is the snapshot router: in the public build an /api path is the
// file snapshot.py wrote for it, under the base path. What is held here: the
// mapping, the fleet view's filters (fleetcore's own predicate, applied in the
// browser), the routes that are never published and say so without a request,
// and the cache (one fetch per file; a failure is never remembered).
import { describe, expect, it, vi } from 'vitest';

type Static = typeof import('./static');

/** static.ts in the public build, under `base`. */
async function load(base = '/'): Promise<Static> {
  vi.stubEnv('BASE_URL', base);
  vi.stubEnv('VITE_STATIC', '1');
  vi.stubGlobal('window', undefined);
  vi.resetModules();
  return import('./static');
}

/** The published site: `files` by URL; anything else is a 404. Returns the URLs asked for, in order. */
function publish(files: Record<string, unknown>): string[] {
  const asked: string[] = [];
  vi.stubGlobal('fetch', vi.fn(async (input: unknown) => {
    const url = String(input);
    asked.push(url);
    if (url in files) return new Response(JSON.stringify(files[url]), { status: 200, headers: { 'Content-Type': 'application/json' } });
    return new Response('not found', { status: 404, statusText: 'Not Found' });
  }));
  return asked;
}

const row = (name: string, more: Record<string, unknown> = {}) => ({ name, haystack: name.toLowerCase(), health: null, triage_level: null, ...more });

const FLEET = {
  sorts: ['featured', 'name'],
  query: { q: '', sort: 'featured', health: null },
  inbox: [{ kind: 'pr', repo: 'scripts', ref: '#1' }],
  rows: [
    row('zer0-mistakes', { haystack: 'zer0-mistakes jekyll theme web active ruby', health: 'crit', triage_level: 'warn' }),
    row('scripts', { haystack: 'scripts shell utilities tools active bash', health: 'ok', triage_level: 'crit' }),
    row('README', { haystack: 'readme the docs site web active python', health: 'warn', triage_level: null }),
    row('cv-pro', { haystack: 'cv-pro the cv web active typescript' }),
  ],
};
const BY_NAME = { ...FLEET, query: { q: '', sort: 'name', health: null }, rows: [...FLEET.rows].sort((a, b) => a.name.localeCompare(b.name)) };

interface View { rows: { name: string }[]; inbox: unknown[]; repo: string | null; query: { q: string; sort: string; health: string | null } }
const names = (v: View) => v.rows.map((r) => r.name);

describe('staticGet: an /api path is a snapshot file', () => {
  it('reads /api/<name> from snapshot/<name>.json', async () => {
    const { staticGet } = await load();
    const asked = publish({ '/snapshot/state.json': { ok: true } });
    expect(await staticGet('/api/state')).toEqual({ ok: true });
    expect(asked).toEqual(['/snapshot/state.json']);
  });

  it('keeps the folders of a nested path', async () => {
    const { staticGet } = await load();
    const asked = publish({ '/snapshot/harness/health.json': { score: 1 }, '/snapshot/project/scripts.json': { name: 'scripts' } });
    expect(await staticGet('/api/harness/health')).toEqual({ score: 1 });
    expect(await staticGet('/api/project/scripts')).toEqual({ name: 'scripts' });
    expect(asked).toEqual(['/snapshot/harness/health.json', '/snapshot/project/scripts.json']);
  });

  it('reads from under the base path on GitHub Pages', async () => {
    const { staticGet } = await load('/bamr87/');
    const asked = publish({ '/bamr87/snapshot/state.json': { ok: true } });
    expect(await staticGet('/api/state')).toEqual({ ok: true });
    expect(asked).toEqual(['/bamr87/snapshot/state.json']);
  });

  it('ignores a trailing slash and a query the document does not take', async () => {
    const { staticGet } = await load();
    const asked = publish({ '/snapshot/roadmap.json': { items: [] } });
    await staticGet('/api/roadmap/');
    await staticGet('/api/roadmap?q=zer0');
    expect(new Set(asked)).toEqual(new Set(['/snapshot/roadmap.json']));
  });

  it('reads the build’s own record through manifest()', async () => {
    const { manifest } = await load('/bamr87/');
    const asked = publish({ '/bamr87/snapshot/manifest.json': { schema: 'console-pages/v1', commit: 'abc1234', documents: 3 } });
    expect(await manifest()).toMatchObject({ commit: 'abc1234', documents: 3 });
    expect(asked).toEqual(['/bamr87/snapshot/manifest.json']);
  });
});

describe('staticGet: what is not published', () => {
  it('says a missing document is not in the snapshot, as a 404', async () => {
    const { staticGet } = await load();
    publish({});
    await expect(staticGet('/api/nope')).rejects.toMatchObject({ status: 404, message: 'not in the published snapshot: nope' });
  });

  it('passes any other failure on with its status', async () => {
    const { staticGet } = await load();
    vi.stubGlobal('fetch', vi.fn(async () => new Response('down', { status: 503, statusText: 'Service Unavailable' })));
    await expect(staticGet('/api/state')).rejects.toMatchObject({ status: 503, message: '503 Service Unavailable' });
  });

  it.each([
    ['/api/auth', 'Credential management'],
    ['/api/gh-projects', 'GitHub Projects'],
    ['/api/gh-projects/PVT_1/items', 'GitHub Projects'],
    ['/api/index/search?q=cron', 'The code index'],
    ['/api/index/harmonize', 'The code index'],
    ['/api/content/lifehacker/brief', 'The content brief'],
    ['/api/jobs/j-1', 'A console job'],
    ['/api/refine/evidence/run-7/plan.json', 'An evidence tree'],
    ['/api/refine/review/run-7', 'An evidence tree'],
  ])('answers %s as local-only (501) without asking the network', async (path, what) => {
    const { staticGet } = await load();
    const asked = publish({});
    const failure = await staticGet(path).then(() => null, (e: unknown) => e as { status: number; message: string });
    expect(failure?.status).toBe(501);
    expect(failure?.message).toContain(what);
    expect(failure?.message).toContain('connect a console');
    expect(asked).toEqual([]);
  });

  it('answers a repo’s README as absent, with the reason, without asking the network', async () => {
    const { staticGet } = await load();
    const asked = publish({});
    const doc = await staticGet<{ present: boolean; reason: string }>('/api/project/scripts/readme');
    expect(doc.present).toBe(false);
    expect(doc.reason).not.toBe('');
    expect(asked).toEqual([]);
  });

  it('answers a content site’s docs as an empty list without asking the network', async () => {
    const { staticGet } = await load();
    const asked = publish({});
    expect(await staticGet('/api/content/lifehacker/docs')).toEqual([]);
    expect(asked).toEqual([]);
  });

  it('still serves the published documents beside the local-only ones', async () => {
    const { staticGet } = await load();
    publish({ '/snapshot/jobs.json': [], '/snapshot/content/lifehacker.json': { name: 'lifehacker' }, '/snapshot/refine/library.json': { entries: [] } });
    expect(await staticGet('/api/jobs')).toEqual([]);
    expect(await staticGet('/api/content/lifehacker')).toEqual({ name: 'lifehacker' });
    expect(await staticGet('/api/refine/library')).toEqual({ entries: [] });
  });
});

describe('staticGet: the fleet view', () => {
  const site = { '/snapshot/fleet/featured.json': FLEET, '/snapshot/fleet/name.json': BY_NAME, '/snapshot/project/scripts.json': { inbox: [{ kind: 'issue', repo: 'scripts', ref: '#9' }] } };

  it('is the featured order with every row when nothing is asked', async () => {
    const { staticGet } = await load();
    const asked = publish(site);
    const view = await staticGet<View>('/api/fleet');
    expect(names(view)).toEqual(['zer0-mistakes', 'scripts', 'README', 'cv-pro']);
    expect(view.query).toEqual({ q: '', sort: 'featured', health: null });
    expect(view.inbox).toEqual(FLEET.inbox);
    expect(view.repo).toBeNull();
    expect(asked).toEqual(['/snapshot/fleet/featured.json']);
  });

  it('reads the file written for the asked sort', async () => {
    const { staticGet } = await load();
    const asked = publish(site);
    const view = await staticGet<View>('/api/fleet?sort=name');
    expect(names(view)).toEqual(['cv-pro', 'README', 'scripts', 'zer0-mistakes']);
    expect(view.query.sort).toBe('name');
    expect(asked).toEqual(['/snapshot/fleet/name.json']);
  });

  it('falls back to the featured order for a sort the snapshot has no file for', async () => {
    const { staticGet } = await load();
    publish(site);
    const view = await staticGet<View>('/api/fleet?sort=stars');
    expect(names(view)).toEqual(['zer0-mistakes', 'scripts', 'README', 'cv-pro']);
    expect(view.query.sort).toBe('featured');
  });

  it('filters by a substring of the row’s haystack, whatever the case and spacing of the search', async () => {
    const { staticGet } = await load();
    publish(site);
    expect(names(await staticGet<View>('/api/fleet?q=jekyll'))).toEqual(['zer0-mistakes']);
    expect(names(await staticGet<View>('/api/fleet?q=WEB'))).toEqual(['zer0-mistakes', 'README', 'cv-pro']);
    expect(names(await staticGet<View>('/api/fleet?q=%20%20Bash%20'))).toEqual(['scripts']);
    expect(names(await staticGet<View>('/api/fleet?q=readme'))).toEqual(['README']);
    expect(names(await staticGet<View>('/api/fleet?q=no-such-thing'))).toEqual([]);
  });

  it('filters by a level on either attention signal: health or triage', async () => {
    const { staticGet } = await load();
    publish(site);
    expect(names(await staticGet<View>('/api/fleet?health=crit'))).toEqual(['zer0-mistakes', 'scripts']);
    expect(names(await staticGet<View>('/api/fleet?health=warn'))).toEqual(['zer0-mistakes', 'README']);
    expect(names(await staticGet<View>('/api/fleet?health=ok'))).toEqual(['scripts']);
  });

  it('applies the search and the level together', async () => {
    const { staticGet } = await load();
    publish(site);
    expect(names(await staticGet<View>('/api/fleet?q=web&health=warn'))).toEqual(['zer0-mistakes', 'README']);
    expect(names(await staticGet<View>('/api/fleet?q=bash&health=warn'))).toEqual([]);
  });

  it('reports the filters it applied, the search as it was typed', async () => {
    const { staticGet } = await load();
    publish(site);
    const view = await staticGet<View>('/api/fleet?q=Web&health=warn&sort=name');
    expect(view.query).toEqual({ q: 'Web', sort: 'name', health: 'warn' });
  });

  it('leaves the cached document whole: a filtered view does not narrow the next one', async () => {
    const { staticGet } = await load();
    const asked = publish(site);
    await staticGet<View>('/api/fleet?q=jekyll');
    expect(names(await staticGet<View>('/api/fleet'))).toEqual(['zer0-mistakes', 'scripts', 'README', 'cv-pro']);
    expect(asked).toEqual(['/snapshot/fleet/featured.json']);
  });

  it('takes one repo’s inbox from that project’s document', async () => {
    const { staticGet } = await load();
    const asked = publish(site);
    const view = await staticGet<View>('/api/fleet?repo=scripts');
    expect(view.repo).toBe('scripts');
    expect(view.inbox).toEqual([{ kind: 'issue', repo: 'scripts', ref: '#9' }]);
    expect(names(view)).toEqual(['zer0-mistakes', 'scripts', 'README', 'cv-pro']);
    expect(asked).toEqual(['/snapshot/fleet/featured.json', '/snapshot/project/scripts.json']);
  });

  it('gives a repo with no published document an empty inbox rather than failing the view', async () => {
    const { staticGet } = await load();
    publish(site);
    const view = await staticGet<View>('/api/fleet?repo=unknown-repo');
    expect(view.repo).toBe('unknown-repo');
    expect(view.inbox).toEqual([]);
    expect(view.rows).toHaveLength(4);
  });
});

describe('the snapshot cache', () => {
  it('fetches a file once however often it is asked for', async () => {
    const { staticGet } = await load();
    const asked = publish({ '/snapshot/state.json': { n: 1 } });
    await staticGet('/api/state');
    await staticGet('/api/state');
    expect(asked).toHaveLength(1);
  });

  it('shares one fetch between requests made at the same moment', async () => {
    const { staticGet } = await load();
    const asked = publish({ '/snapshot/state.json': { n: 1 } });
    const all = await Promise.all([staticGet('/api/state'), staticGet('/api/state'), staticGet('/api/state')]);
    expect(all).toEqual([{ n: 1 }, { n: 1 }, { n: 1 }]);
    expect(asked).toHaveLength(1);
  });

  it('fetches again after clearSnapshotCache(), and shows what the build now has', async () => {
    const { staticGet, clearSnapshotCache } = await load();
    publish({ '/snapshot/state.json': { n: 1 } });
    expect(await staticGet('/api/state')).toEqual({ n: 1 });
    const asked = publish({ '/snapshot/state.json': { n: 2 } });
    expect(await staticGet('/api/state')).toEqual({ n: 1 });
    clearSnapshotCache();
    expect(await staticGet('/api/state')).toEqual({ n: 2 });
    expect(asked).toHaveLength(1);
  });

  it('does not remember a missing document: it is asked for again, and found once published', async () => {
    const { staticGet } = await load();
    const before = publish({});
    await expect(staticGet('/api/state')).rejects.toMatchObject({ status: 404 });
    await expect(staticGet('/api/state')).rejects.toMatchObject({ status: 404 });
    expect(before).toHaveLength(2);
    publish({ '/snapshot/state.json': { n: 1 } });
    expect(await staticGet('/api/state')).toEqual({ n: 1 });
  });

  it('does not remember a dropped connection: the next ask retries', async () => {
    const { staticGet } = await load();
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch'); }));
    await expect(staticGet('/api/state')).rejects.toThrow('Failed to fetch');
    const asked = publish({ '/snapshot/state.json': { n: 1 } });
    expect(await staticGet('/api/state')).toEqual({ n: 1 });
    expect(asked).toHaveLength(1);
  });
});
