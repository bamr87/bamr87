// backend.ts answers two questions for the whole app: where it is served from
// (`/` by a console, `/bamr87/` on GitHub Pages: every file URL goes through
// asset()) and which backend answers (a console, the published snapshot, or a
// console the visitor connected). Both are decided when the module loads, from
// the build's settings and this browser's storage, so each test loads it fresh
// as one build in one browser.
import { describe, expect, it, vi } from 'vitest';

type Backend = typeof import('./backend');

function fakeStorage(seed: Record<string, string> = {}) {
  const data = new Map(Object.entries(seed));
  return {
    data,
    getItem: (k: string) => (data.has(k) ? (data.get(k) as string) : null),
    setItem: (k: string, v: string) => void data.set(k, String(v)),
    removeItem: (k: string) => void data.delete(k),
  };
}
type FakeStorage = ReturnType<typeof fakeStorage>;

/** A private window: every call throws. */
const refusing = {
  getItem: () => { throw new Error('SecurityError'); },
  setItem: () => { throw new Error('QuotaExceededError'); },
  removeItem: () => { throw new Error('SecurityError'); },
};

interface Build {
  base?: string;
  /** VITE_STATIC, as build-pages.sh sets it. */
  isStatic?: string;
  frontDoor?: string;
  mark?: string;
  local?: Pick<FakeStorage, 'getItem' | 'setItem' | 'removeItem'>;
  session?: Pick<FakeStorage, 'getItem' | 'setItem' | 'removeItem'>;
  framed?: boolean;
  noWindow?: boolean;
}

async function load(build: Build = {}): Promise<Backend> {
  vi.stubEnv('BASE_URL', build.base ?? '/');
  vi.stubEnv('VITE_STATIC', build.isStatic ?? '');
  vi.stubEnv('VITE_FRONT_DOOR', build.frontDoor ?? '');
  vi.stubEnv('VITE_SITE_MARK', build.mark ?? '');
  if (build.noWindow) {
    vi.stubGlobal('window', undefined);
  } else {
    const win: Record<string, unknown> = { localStorage: build.local ?? fakeStorage(), sessionStorage: build.session ?? fakeStorage() };
    win.self = win;
    win.top = build.framed ? {} : win;
    vi.stubGlobal('window', win);
  }
  vi.resetModules();
  return import('./backend');
}

const PAGES = { base: '/bamr87/', isStatic: '1' } as const;
const holds = (store: FakeStorage, value: string) => [...store.data.values()].includes(value);

describe('the base path', () => {
  it('is / when a console serves the app', async () => {
    const b = await load();
    expect(b.BASE).toBe('/');
    expect(b.BASENAME).toBe('');
  });

  it('is the project subpath on GitHub Pages, and the router gets it without its trailing slash', async () => {
    const b = await load(PAGES);
    expect(b.BASE).toBe('/bamr87/');
    expect(b.BASENAME).toBe('/bamr87');
  });
});

describe('asset', () => {
  it('points at a shipped file from the root when served at /', async () => {
    const { asset } = await load();
    expect(asset('favicon.svg')).toBe('/favicon.svg');
    expect(asset('snapshot/state.json')).toBe('/snapshot/state.json');
  });

  it('puts the file under the base on GitHub Pages', async () => {
    const { asset } = await load(PAGES);
    expect(asset('favicon.svg')).toBe('/bamr87/favicon.svg');
    expect(asset('snapshot/fleet/featured.json')).toBe('/bamr87/snapshot/fleet/featured.json');
  });

  it('takes a path written with a leading slash without doubling it or escaping the base', async () => {
    expect((await load()).asset('/favicon.svg')).toBe('/favicon.svg');
    const { asset } = await load(PAGES);
    expect(asset('/favicon.svg')).toBe('/bamr87/favicon.svg');
    expect(asset('//diagrams/harness.html')).toBe('/bamr87/diagrams/harness.html');
  });

  it('keeps a query and a fragment', async () => {
    const { asset } = await load(PAGES);
    expect(asset('diagrams/harness.html?theme=dark#loops')).toBe('/bamr87/diagrams/harness.html?theme=dark#loops');
  });

  it('never returns a path outside the base', async () => {
    const { asset, BASE } = await load(PAGES);
    for (const path of ['a.json', '/a.json', 'snapshot/a/b.json', '']) {
      expect(asset(path).startsWith(BASE), path).toBe(true);
    }
  });
});

describe('build settings', () => {
  it('reads the static build from VITE_STATIC=1 and nothing else', async () => {
    expect((await load({ isStatic: '1' })).STATIC).toBe(true);
    expect((await load({ isStatic: '' })).STATIC).toBe(false);
    expect((await load({ isStatic: '0' })).STATIC).toBe(false);
    expect((await load({ isStatic: 'true' })).STATIC).toBe(false);
  });

  it('makes the profile Home the front door unless the build says desktop', async () => {
    expect((await load()).FRONT_DOOR).toBe('home');
    expect((await load({ frontDoor: 'home' })).FRONT_DOOR).toBe('home');
    expect((await load({ frontDoor: 'anything' })).FRONT_DOOR).toBe('home');
    expect((await load({ frontDoor: 'desktop' })).FRONT_DOOR).toBe('desktop');
  });

  it('uses the console’s own mark unless the build names one', async () => {
    expect((await load()).MARK).toBe('favicon.svg');
    expect((await load({ mark: 'other-mark.svg' })).MARK).toBe('other-mark.svg');
  });
});

describe('which backend answers', () => {
  it('is the console when a console serves the app', async () => {
    const b = await load();
    expect(b.mode()).toBe('console');
    expect(b.hasConsole()).toBe(true);
    expect(b.consoleOrigin()).toBe('');
    expect(b.githubDirect()).toBe(false);
  });

  it('is the snapshot in the public build, where the page talks to GitHub itself', async () => {
    const b = await load(PAGES);
    expect(b.mode()).toBe('snapshot');
    expect(b.hasConsole()).toBe(false);
    expect(b.consoleOrigin()).toBe('');
    expect(b.githubDirect()).toBe(true);
  });

  it('is the connected console once the public build has one', async () => {
    const b = await load(PAGES);
    b.setRemoteConsole('http://127.0.0.1:4001');
    expect(b.mode()).toBe('remote');
    expect(b.hasConsole()).toBe(true);
    expect(b.consoleOrigin()).toBe('http://127.0.0.1:4001');
    expect(b.githubDirect()).toBe(false);
  });

  it('stays the console in a console build whatever this browser stored or is told', async () => {
    const local = fakeStorage();
    const pages = await load({ ...PAGES, local });
    pages.setRemoteConsole('https://console.example.test');
    pages.setGithubToken('ghp_test', true);

    const b = await load({ local });
    expect(b.mode()).toBe('console');
    expect(b.consoleOrigin()).toBe('');
    expect(b.githubToken()).toBe('');
    b.setRemoteConsole('https://elsewhere.example.test');
    expect(b.mode()).toBe('console');
    expect(b.consoleOrigin()).toBe('');
  });
});

describe('the connected console', () => {
  it('is kept as an origin: trimmed, with no trailing slash', async () => {
    const b = await load(PAGES);
    b.setRemoteConsole('  https://console.example.test///  ');
    expect(b.consoleOrigin()).toBe('https://console.example.test');
    b.setRemoteConsole('http://localhost:4001/');
    expect(b.consoleOrigin()).toBe('http://localhost:4001');
  });

  it('is remembered by this browser across loads', async () => {
    const local = fakeStorage();
    (await load({ ...PAGES, local })).setRemoteConsole('https://console.example.test/');
    const again = await load({ ...PAGES, local });
    expect(again.mode()).toBe('remote');
    expect(again.consoleOrigin()).toBe('https://console.example.test');
  });

  it('is forgotten on disconnect, now and on the next load', async () => {
    const local = fakeStorage();
    const b = await load({ ...PAGES, local });
    b.setRemoteConsole('https://console.example.test');
    b.setRemoteConsole(null);
    expect(b.mode()).toBe('snapshot');
    expect(b.consoleOrigin()).toBe('');
    expect(holds(local, 'https://console.example.test')).toBe(false);
    expect((await load({ ...PAGES, local })).mode()).toBe('snapshot');
  });

  it('reads an empty or blank address as a disconnect', async () => {
    const b = await load(PAGES);
    b.setRemoteConsole('https://console.example.test');
    b.setRemoteConsole('   ');
    expect(b.mode()).toBe('snapshot');
    b.setRemoteConsole('https://console.example.test');
    b.setRemoteConsole('');
    expect(b.mode()).toBe('snapshot');
  });
});

describe('the browser-held GitHub token', () => {
  it('is absent until one is set', async () => {
    const b = await load(PAGES);
    expect(b.githubToken()).toBe('');
    expect(b.githubRemembered()).toBe(false);
  });

  it('is kept trimmed', async () => {
    const b = await load(PAGES);
    b.setGithubToken('  ghp_test \n');
    expect(b.githubToken()).toBe('ghp_test');
  });

  it('stays in this tab by default: session storage only, gone in a new tab', async () => {
    const local = fakeStorage();
    const session = fakeStorage();
    const b = await load({ ...PAGES, local, session });
    b.setGithubToken('ghp_test');
    expect(holds(session, 'ghp_test')).toBe(true);
    expect(holds(local, 'ghp_test')).toBe(false);
    expect(b.githubRemembered()).toBe(false);

    expect((await load({ ...PAGES, local, session })).githubToken()).toBe('ghp_test');
    expect((await load({ ...PAGES, local, session: fakeStorage() })).githubToken()).toBe('');
  });

  it('is kept on this device when asked to remember: local storage only, there in a new tab', async () => {
    const local = fakeStorage();
    const session = fakeStorage();
    const b = await load({ ...PAGES, local, session });
    b.setGithubToken('ghp_test', true);
    expect(holds(local, 'ghp_test')).toBe(true);
    expect(holds(session, 'ghp_test')).toBe(false);
    expect(b.githubRemembered()).toBe(true);

    const newTab = await load({ ...PAGES, local, session: fakeStorage() });
    expect(newTab.githubToken()).toBe('ghp_test');
    expect(newTab.githubRemembered()).toBe(true);
  });

  it('leaves the device when the same token is set again without remember', async () => {
    const local = fakeStorage();
    const session = fakeStorage();
    const b = await load({ ...PAGES, local, session });
    b.setGithubToken('ghp_test', true);
    b.setGithubToken('ghp_test', false);
    expect(holds(local, 'ghp_test')).toBe(false);
    expect(holds(session, 'ghp_test')).toBe(true);
    expect(b.githubRemembered()).toBe(false);
  });

  it('prefers this tab’s token over the remembered one', async () => {
    const local = fakeStorage();
    (await load({ ...PAGES, local })).setGithubToken('ghp_remembered', true);
    const session = fakeStorage();
    const tab = await load({ ...PAGES, local: fakeStorage(), session });
    tab.setGithubToken('ghp_this_tab');
    const both = await load({ ...PAGES, local, session });
    expect(both.githubToken()).toBe('ghp_this_tab');
  });

  it('is removed from both stores on disconnect', async () => {
    const local = fakeStorage();
    const session = fakeStorage();
    const b = await load({ ...PAGES, local, session });
    b.setGithubToken('ghp_test', true);
    b.setGithubToken(null);
    expect(b.githubToken()).toBe('');
    expect(b.githubRemembered()).toBe(false);
    expect(local.data.size).toBe(0);
    expect(session.data.size).toBe(0);

    b.setGithubToken('ghp_test');
    b.setGithubToken('   ');
    expect(b.githubToken()).toBe('');
    expect(session.data.size).toBe(0);
  });
});

describe('storage that cannot be used', () => {
  it('costs the memory, not the page: a private window still loads and connects for this load', async () => {
    const b = await load({ ...PAGES, local: refusing, session: refusing });
    expect(b.mode()).toBe('snapshot');
    expect(b.githubToken()).toBe('');
    expect(b.githubRemembered()).toBe(false);

    expect(() => b.setRemoteConsole('https://console.example.test')).not.toThrow();
    expect(b.mode()).toBe('remote');
    expect(() => b.setGithubToken('ghp_test', true)).not.toThrow();
    expect(b.githubToken()).toBe('ghp_test');
  });

  it('loads where there is no window at all', async () => {
    const b = await load({ ...PAGES, noWindow: true });
    expect(b.mode()).toBe('snapshot');
    expect(b.EMBEDDED).toBe(false);
    expect(b.asset('favicon.svg')).toBe('/bamr87/favicon.svg');
    expect(() => b.setGithubToken('ghp_test')).not.toThrow();
    expect(b.githubToken()).toBe('ghp_test');
  });
});

describe('EMBEDDED', () => {
  it('is false for a page that is the top window', async () => {
    expect((await load()).EMBEDDED).toBe(false);
  });

  it('is true for a page framed in a Desktop window', async () => {
    expect((await load({ framed: true })).EMBEDDED).toBe(true);
  });
});
