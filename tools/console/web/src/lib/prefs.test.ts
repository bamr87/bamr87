// prefs.ts is what one browser remembers. The rule it keeps: storage that is
// missing, refuses or holds something unreadable costs the preference, never
// the page.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { readPref, recentPages, rememberPage, writePref, type RecentPage } from './prefs';

/** localStorage, as much of it as the module uses. */
function fakeStorage(seed: Record<string, string> = {}) {
  const data = new Map(Object.entries(seed));
  return {
    data,
    getItem: (k: string) => (data.has(k) ? (data.get(k) as string) : null),
    setItem: (k: string, v: string) => void data.set(k, String(v)),
    removeItem: (k: string) => void data.delete(k),
  };
}

/** A private window: every call throws. */
const refusing = {
  getItem: () => { throw new Error('SecurityError'); },
  setItem: () => { throw new Error('QuotaExceededError'); },
  removeItem: () => { throw new Error('SecurityError'); },
};

const page = (n: number): RecentPage => ({ path: `/p${n}`, label: `Page ${n}` });

describe('readPref / writePref', () => {
  let store: ReturnType<typeof fakeStorage>;
  beforeEach(() => {
    store = fakeStorage();
    vi.stubGlobal('window', { localStorage: store });
  });

  it('gives the fallback for a key never written', () => {
    expect(readPref('nav_open', ['Fleet'])).toEqual(['Fleet']);
    expect(readPref('count', 0)).toBe(0);
  });

  it('reads back what was written, whatever its shape', () => {
    writePref('nav_open', ['Fleet', 'Spend']);
    writePref('dense', true);
    writePref('last', { path: '/costs', at: 3 });
    expect(readPref('nav_open', [])).toEqual(['Fleet', 'Spend']);
    expect(readPref('dense', false)).toBe(true);
    expect(readPref('last', null)).toEqual({ path: '/costs', at: 3 });
  });

  it('keeps a stored false, 0 and empty list instead of falling back', () => {
    writePref('dense', false);
    writePref('count', 0);
    writePref('nav_open', []);
    expect(readPref('dense', true)).toBe(false);
    expect(readPref('count', 7)).toBe(0);
    expect(readPref('nav_open', ['Fleet'])).toEqual([]);
  });

  it('keeps each key apart', () => {
    writePref('a', 1);
    writePref('b', 2);
    expect(readPref('a', 0)).toBe(1);
    expect(readPref('b', 0)).toBe(2);
  });

  it('gives the fallback when what is stored is not JSON', () => {
    store.data.set('nav_open', '{not json');
    expect(readPref('nav_open', ['Fleet'])).toEqual(['Fleet']);
  });
});

describe('readPref / writePref without usable storage', () => {
  it('fall back, and do not throw, in a window that refuses storage', () => {
    vi.stubGlobal('window', { localStorage: refusing });
    expect(() => writePref('nav_open', ['Fleet'])).not.toThrow();
    expect(readPref('nav_open', ['Overview'])).toEqual(['Overview']);
  });

  it('fall back, and do not throw, where there is no window at all', () => {
    vi.stubGlobal('window', undefined);
    expect(() => writePref('nav_open', ['Fleet'])).not.toThrow();
    expect(readPref('nav_open', ['Overview'])).toEqual(['Overview']);
  });
});

describe('recent pages', () => {
  beforeEach(() => {
    vi.stubGlobal('window', { localStorage: fakeStorage() });
  });

  it('start empty', () => {
    expect(recentPages()).toEqual([]);
  });

  it('list the newest visit first', () => {
    rememberPage(page(1));
    rememberPage(page(2));
    rememberPage(page(3));
    expect(recentPages()).toEqual([page(3), page(2), page(1)]);
  });

  it('move a page visited again to the top rather than listing it twice', () => {
    rememberPage(page(1));
    rememberPage(page(2));
    rememberPage(page(3));
    rememberPage(page(1));
    expect(recentPages()).toEqual([page(1), page(3), page(2)]);
  });

  it('take the newer label when a path is visited again', () => {
    rememberPage({ path: '/projects/x', label: 'x' });
    rememberPage({ path: '/projects/x', label: 'x — the project' });
    expect(recentPages()).toEqual([{ path: '/projects/x', label: 'x — the project' }]);
  });

  it('keep the six newest and drop the oldest', () => {
    for (let n = 1; n <= 8; n += 1) rememberPage(page(n));
    expect(recentPages()).toEqual([page(8), page(7), page(6), page(5), page(4), page(3)]);
  });

  it('survive a reload: another reader of the same storage sees them', () => {
    const shared = fakeStorage();
    vi.stubGlobal('window', { localStorage: shared });
    rememberPage(page(1));
    vi.stubGlobal('window', { localStorage: fakeStorage(Object.fromEntries(shared.data)) });
    expect(recentPages()).toEqual([page(1)]);
  });

  it('are an empty list when what is stored is not a list', () => {
    const anything = { getItem: () => '{"path":"/costs"}', setItem: () => undefined, removeItem: () => undefined };
    vi.stubGlobal('window', { localStorage: anything });
    expect(recentPages()).toEqual([]);
  });

  it('are an empty list, and remembering is harmless, in a window that refuses storage', () => {
    vi.stubGlobal('window', { localStorage: refusing });
    expect(() => rememberPage(page(1))).not.toThrow();
    expect(recentPages()).toEqual([]);
  });
});
