// The snapshot router: an /api path → the file ../snapshot.py wrote for it.
//
// snapshot.py writes each document at the path the console would serve it
// from (/api/state → snapshot/state.json), so the mapping is mechanical. The
// exceptions are the parameterised views:
//
//   /api/fleet?sort=&q=&health=  one file per sort key; q and health are
//                                applied here with fleetcore's own predicate
//                                (fleet.filter_rows: a substring of the row's
//                                haystack, a level matching health OR triage)
//   /api/fleet?repo=X            that project's document carries its inbox
//   /api/lake/*, /api/content/*  the local-only planes: their "absent" shapes
import { ApiError } from './errors';
import { asset } from './backend';
import type { FleetView } from './types';

const cache = new Map<string, Promise<unknown>>();

async function file<T>(key: string): Promise<T> {
  let hit = cache.get(key);
  if (!hit) {
    hit = fetch(asset(`snapshot/${key}.json`), { cache: 'no-cache' }).then(async (res) => {
      if (!res.ok) {
        cache.delete(key);
        throw new ApiError(res.status === 404 ? 404 : res.status, res.status === 404 ? `not in the published snapshot: ${key}` : `${res.status} ${res.statusText}`);
      }
      return res.json();
    });
    // A failed fetch (offline, a dropped socket) must not stick: the next ask retries.
    hit.catch(() => cache.delete(key));
    cache.set(key, hit);
  }
  return hit as Promise<T>;
}

/** Forget every cached file (the page's refresh button: the build may have landed). */
export function clearSnapshotCache(): void {
  cache.clear();
}

function localOnly(what: string): never {
  throw new ApiError(501, `${what} runs on the operator's machine and is not part of the public snapshot — connect a console to use it`);
}

export async function staticGet<T>(path: string): Promise<T> {
  const url = new URL(path, 'http://snapshot.invalid');
  const p = url.pathname.replace(/^\/api\/?/, '').replace(/\/+$/, '');
  const qs = url.searchParams;

  if (p === 'fleet') {
    const repo = qs.get('repo');
    const view = await file<FleetView>(`fleet/${qs.get('sort') || 'featured'}`).catch(() => file<FleetView>('fleet/featured'));
    const needle = (qs.get('q') ?? '').trim().toLowerCase();
    const health = qs.get('health') ?? '';
    const rows = view.rows.filter(
      (r) => (!needle || String((r as { haystack?: string }).haystack ?? r.name).includes(needle)) && (!health || r.health === health || r.triage_level === health),
    );
    const inbox = repo ? ((await file<{ inbox: FleetView['inbox'] }>(`project/${repo}`).catch(() => ({ inbox: [] }))).inbox) : view.inbox;
    return { ...view, rows, inbox, repo, query: { q: qs.get('q') ?? '', sort: view.query?.sort ?? 'featured', health: health || null } } as T;
  }
  if (p === 'auth') localOnly('Credential management');
  if (p.startsWith('index/search') || p.startsWith('index/harmonize')) localOnly('The code index');
  if (/^content\/[^/]+\/docs$/.test(p)) return [] as T;
  if (/^content\/[^/]+\/brief$/.test(p)) localOnly('The content brief (it reads the data lake)');
  if (/^jobs\/[^/]+$/.test(p)) localOnly('A console job');
  return file<T>(p);
}

/** The build's own record: when, from which commit, by which run. */
export interface Manifest {
  schema: string;
  generated_at: string;
  base: string;
  site_url: string;
  commit: string;
  commit_date: string;
  repo: string;
  run_url: string | null;
  documents: number;
  routes: number;
}

export const manifest = () => file<Manifest>('manifest');
