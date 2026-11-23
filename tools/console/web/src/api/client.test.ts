// client.ts is the one fetch path every page uses. Against a console it adds
// the bearer token, asks for one ONCE however many requests hit a 401 together,
// and turns a failure into an ApiError a page can show. In the public build it
// never writes: reads come from the snapshot, the GitHub routes from GitHub.
// No request leaves this file: fetch is a stub that records what was asked.
import { describe, expect, it, vi } from 'vitest';

function fakeStorage(seed: Record<string, string> = {}) {
  const data = new Map(Object.entries(seed));
  return {
    data,
    getItem: (k: string) => (data.has(k) ? (data.get(k) as string) : null),
    setItem: (k: string, v: string) => void data.set(k, String(v)),
    removeItem: (k: string) => void data.delete(k),
  };
}
type Store = Pick<ReturnType<typeof fakeStorage>, 'getItem' | 'setItem' | 'removeItem'>;

const refusing: Store = {
  getItem: () => { throw new Error('SecurityError'); },
  setItem: () => { throw new Error('QuotaExceededError'); },
  removeItem: () => { throw new Error('SecurityError'); },
};

interface World {
  /** The public build (VITE_STATIC=1) rather than a page a console serves. */
  isStatic?: boolean;
  base?: string;
  local?: Store;
}

/** client.ts, freshly loaded as one build in one browser tab. */
async function load(world: World = {}) {
  const local = world.local ?? fakeStorage();
  const session = fakeStorage();
  vi.stubEnv('BASE_URL', world.base ?? '/');
  vi.stubEnv('VITE_STATIC', world.isStatic ? '1' : '');
  vi.stubEnv('VITE_FRONT_DOOR', '');
  vi.stubGlobal('localStorage', local);
  vi.stubGlobal('sessionStorage', session);
  vi.stubGlobal('window', { localStorage: local, sessionStorage: session });
  vi.resetModules();
  const backend = await import('./backend');
  const client = await import('./client');
  return { ...client, backend };
}

interface Call {
  url: string;
  method: string;
  auth: string | null;
  contentType: string | null;
  body: unknown;
}

/** Stand in for the network: `respond` answers each request; the calls come back in order. */
function serve(respond: (call: Call) => Response | Promise<Response>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal('fetch', vi.fn(async (input: unknown, init: RequestInit = {}) => {
    const headers = new Headers(init.headers);
    const call: Call = {
      url: String(input),
      method: (init.method ?? 'GET').toUpperCase(),
      auth: headers.get('Authorization'),
      contentType: headers.get('Content-Type'),
      body: init.body ?? null,
    };
    calls.push(call);
    return respond(call);
  }));
  return calls;
}

const json = (body: unknown, status = 200, statusText = '') =>
  new Response(JSON.stringify(body), { status, statusText, headers: { 'Content-Type': 'application/json' } });
const unauthorized = () => json({ detail: 'unauthorized' }, 401, 'Unauthorized');
/** A console that wants `token`. */
const wants = (token: string) => (call: Call) => (call.auth === `Bearer ${token}` ? json({ ok: true, path: call.url }) : unauthorized());

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((ok) => { resolve = ok; });
  return { promise, resolve };
}

describe('api: against the console that serves the page', () => {
  it('fetches the path on the same origin and gives back the document', async () => {
    const { api } = await load();
    const calls = serve(() => json({ projects: 3 }));
    expect(await api('/api/state')).toEqual({ projects: 3 });
    expect(calls).toEqual([{ url: '/api/state', method: 'GET', auth: null, contentType: null, body: null }]);
  });

  it('keeps the query string', async () => {
    const { api } = await load();
    const calls = serve(() => json([]));
    await api('/api/fleet?sort=name&q=web');
    expect(calls[0].url).toBe('/api/fleet?sort=name&q=web');
  });

  it('sends a body as JSON with post and put, and none with del', async () => {
    const { post, put, del } = await load();
    const calls = serve(() => json({ ok: true }));
    await post('/api/jobs', { op: 'triage', params: { repo: 'scripts' } });
    await put('/api/voices', { defaults: {} });
    await del('/api/jobs/j-1');
    expect(calls.map((c) => [c.method, c.url, c.contentType])).toEqual([
      ['POST', '/api/jobs', 'application/json'],
      ['PUT', '/api/voices', 'application/json'],
      ['DELETE', '/api/jobs/j-1', null],
    ]);
    expect(JSON.parse(String(calls[0].body))).toEqual({ op: 'triage', params: { repo: 'scripts' } });
    expect(calls[2].body).toBeNull();
  });

  it('leaves a Content-Type the caller set', async () => {
    const { api } = await load();
    const calls = serve(() => json({ ok: true }));
    await api('/api/upload', { method: 'POST', body: 'a,b\n1,2\n', headers: { 'Content-Type': 'text/csv' } });
    expect(calls[0].contentType).toBe('text/csv');
  });

  it('gives an empty document for a success with no JSON body', async () => {
    const { del } = await load();
    serve(() => new Response(null, { status: 204 }));
    expect(await del('/api/jobs/j-1')).toEqual({});
  });
});

describe('api: a failure is an ApiError the page can show', () => {
  it('uses the console’s own explanation when it gives one', async () => {
    const { api, ApiError } = await load();
    serve(() => json({ detail: 'unknown operation: nope' }, 404, 'Not Found'));
    const failure = await api('/api/ops/nope').then(() => null, (e: unknown) => e);
    expect(failure).toBeInstanceOf(ApiError);
    expect(failure).toMatchObject({ status: 404, message: 'unknown operation: nope' });
  });

  it('falls back to the status line when the explanation is not text', async () => {
    const { post } = await load();
    serve(() => json({ detail: [{ loc: ['body', 'op'], msg: 'field required' }] }, 422, 'Unprocessable Entity'));
    await expect(post('/api/jobs', {})).rejects.toMatchObject({ status: 422, message: '422 Unprocessable Entity' });
  });

  it('falls back to the status line when the body is not JSON at all', async () => {
    const { api } = await load();
    serve(() => new Response('<html>Bad Gateway</html>', { status: 502, statusText: 'Bad Gateway' }));
    await expect(api('/api/state')).rejects.toMatchObject({ status: 502, message: '502 Bad Gateway' });
  });

  it('lets a network failure on the same origin through as it is', async () => {
    const { api, ApiError } = await load();
    serve(() => { throw new TypeError('Failed to fetch'); });
    const failure = await api('/api/state').then(() => null, (e: unknown) => e);
    expect(failure).toBeInstanceOf(TypeError);
    expect(failure).not.toBeInstanceOf(ApiError);
  });
});

describe('api: the console token', () => {
  it('sends no Authorization header while there is no token', async () => {
    const { api, currentToken } = await load();
    const calls = serve(() => json({}));
    await api('/api/state');
    expect(currentToken()).toBe('');
    expect(calls[0].auth).toBeNull();
  });

  it('sends the token as a bearer on every request once there is one', async () => {
    const { api, post, setConsoleToken, currentToken } = await load();
    setConsoleToken('tok-1');
    const calls = serve(() => json({}));
    await api('/api/state');
    await post('/api/jobs', { op: 'triage' });
    expect(currentToken()).toBe('tok-1');
    expect(calls.map((c) => c.auth)).toEqual(['Bearer tok-1', 'Bearer tok-1']);
  });

  it('remembers the token in this browser across loads, and forgets it when cleared', async () => {
    const local = fakeStorage();
    (await load({ local })).setConsoleToken('tok-1');
    const again = await load({ local });
    expect(again.currentToken()).toBe('tok-1');
    again.setConsoleToken(null);
    expect(again.currentToken()).toBe('');
    expect((await load({ local })).currentToken()).toBe('');
    expect(local.data.size).toBe(0);
  });

  it('keeps the token for this page load in a window that refuses storage', async () => {
    const { api, setConsoleToken } = await load({ local: refusing });
    expect(() => setConsoleToken('tok-1')).not.toThrow();
    const calls = serve(() => json({}));
    await api('/api/state');
    expect(calls[0].auth).toBe('Bearer tok-1');
  });
});

describe('api: a 401 asks for the token', () => {
  it('asks, then sends the request again with the answer', async () => {
    const { api, registerTokenAsker, currentToken } = await load();
    const asker = vi.fn(async () => 'tok-1');
    registerTokenAsker(asker);
    const calls = serve(wants('tok-1'));
    expect(await api('/api/state')).toEqual({ ok: true, path: '/api/state' });
    expect(asker).toHaveBeenCalledTimes(1);
    expect(asker).toHaveBeenCalledWith(false);
    expect(calls.map((c) => c.auth)).toEqual([null, 'Bearer tok-1']);
    expect(currentToken()).toBe('tok-1');
  });

  it('says so when a token it sent was rejected, and drops that token', async () => {
    const local = fakeStorage();
    (await load({ local })).setConsoleToken('stale');
    const { api, registerTokenAsker, currentToken } = await load({ local });
    const asker = vi.fn(async () => 'fresh');
    registerTokenAsker(asker);
    const calls = serve(wants('fresh'));
    await api('/api/state');
    expect(asker).toHaveBeenCalledWith(true);
    expect(calls.map((c) => c.auth)).toEqual(['Bearer stale', 'Bearer fresh']);
    expect(currentToken()).toBe('fresh');
    expect((await load({ local })).currentToken()).toBe('fresh');
  });

  it('takes a pasted "Bearer <token>" and stray spaces for the token itself', async () => {
    const { api, registerTokenAsker, currentToken } = await load();
    registerTokenAsker(async () => '  bearer   tok-1 \n');
    const calls = serve(wants('tok-1'));
    await api('/api/state');
    expect(currentToken()).toBe('tok-1');
    expect(calls[1].auth).toBe('Bearer tok-1');
  });

  it('asks once for requests that hit the 401 together, and all of them go through', async () => {
    const { api, registerTokenAsker } = await load();
    const answer = deferred<string | null>();
    const asker = vi.fn(() => answer.promise);
    registerTokenAsker(asker);
    const calls = serve(wants('tok-1'));
    const all = Promise.all([api('/api/state'), api('/api/fleet'), api('/api/jobs')]);
    await vi.waitFor(() => expect(asker).toHaveBeenCalled());
    answer.resolve('tok-1');
    expect(await all).toEqual([
      { ok: true, path: '/api/state' },
      { ok: true, path: '/api/fleet' },
      { ok: true, path: '/api/jobs' },
    ]);
    expect(asker).toHaveBeenCalledTimes(1);
    expect(calls).toHaveLength(6);
  });

  it('does not ask again for a request whose 401 arrives after another request got the new token', async () => {
    const local = fakeStorage();
    (await load({ local })).setConsoleToken('stale');
    const { api, registerTokenAsker } = await load({ local });
    const asker = vi.fn(async () => 'fresh');
    registerTokenAsker(asker);
    const hold = deferred<void>();
    const calls = serve(async (call) => {
      if (call.url === '/api/slow') await hold.promise;
      return wants('fresh')(call);
    });
    const slow = api('/api/slow');
    expect(await api('/api/fast')).toEqual({ ok: true, path: '/api/fast' });
    hold.resolve();
    expect(await slow).toEqual({ ok: true, path: '/api/slow' });
    expect(asker).toHaveBeenCalledTimes(1);
    expect(calls.filter((c) => c.url === '/api/slow').map((c) => c.auth)).toEqual(['Bearer stale', 'Bearer fresh']);
  });

  it('asks again after an answer was given, when a later request is refused', async () => {
    const { api, registerTokenAsker } = await load();
    const asker = vi.fn<(rejected: boolean) => Promise<string | null>>().mockResolvedValueOnce('first').mockResolvedValueOnce('second');
    registerTokenAsker(asker);
    serve(wants('first'));
    await api('/api/state');
    serve(wants('second'));
    await api('/api/state');
    expect(asker).toHaveBeenCalledTimes(2);
    expect(asker.mock.calls).toEqual([[false], [true]]);
  });

  it('fails with "token required" when the prompt is dismissed', async () => {
    const { api, registerTokenAsker, currentToken } = await load();
    registerTokenAsker(async () => null);
    const calls = serve(unauthorized);
    await expect(api('/api/state')).rejects.toMatchObject({ status: 401, message: 'console token required' });
    expect(calls).toHaveLength(1);
    expect(currentToken()).toBe('');
  });

  it('reads a blank answer as a dismissal', async () => {
    const { api, registerTokenAsker } = await load();
    registerTokenAsker(async () => '   ');
    serve(unauthorized);
    await expect(api('/api/state')).rejects.toMatchObject({ status: 401, message: 'console token required' });
  });

  it('fails with "token required" when no prompt is registered', async () => {
    const { api, registerTokenAsker } = await load();
    serve(unauthorized);
    await expect(api('/api/state')).rejects.toMatchObject({ status: 401, message: 'console token required' });
    registerTokenAsker(async () => 'tok-1');
    registerTokenAsker(null);
    await expect(api('/api/state')).rejects.toMatchObject({ status: 401, message: 'console token required' });
  });

  it('gives up after three rejected tokens rather than asking forever', async () => {
    const { api, registerTokenAsker, currentToken } = await load();
    let n = 0;
    const asker = vi.fn(async () => `wrong-${(n += 1)}`);
    registerTokenAsker(asker);
    const calls = serve(unauthorized);
    await expect(api('/api/state')).rejects.toMatchObject({ status: 401, message: expect.stringContaining('rejected three times') });
    expect(asker).toHaveBeenCalledTimes(3);
    expect(calls.map((c) => c.auth)).toEqual([null, 'Bearer wrong-1', 'Bearer wrong-2', 'Bearer wrong-3']);
    expect(currentToken()).toBe('');
  });
});

describe('askToken', () => {
  it('gives every caller waiting on the same prompt the same answer', async () => {
    const { askToken, registerTokenAsker } = await load();
    const answer = deferred<string | null>();
    const asker = vi.fn(() => answer.promise);
    registerTokenAsker(asker);
    const first = askToken(false);
    const second = askToken(false);
    answer.resolve('tok-1');
    expect(await Promise.all([first, second])).toEqual(['tok-1', 'tok-1']);
    expect(asker).toHaveBeenCalledTimes(1);
  });

  it('opens a new prompt once the last one was answered', async () => {
    const { askToken, registerTokenAsker } = await load();
    const asker = vi.fn<(rejected: boolean) => Promise<string | null>>().mockResolvedValueOnce(null).mockResolvedValueOnce('tok-2');
    registerTokenAsker(asker);
    expect(await askToken(false)).toBeNull();
    expect(await askToken(true)).toBe('tok-2');
    expect(asker.mock.calls).toEqual([[false], [true]]);
  });

  it('leaves the stored token alone when the prompt is dismissed', async () => {
    const { askToken, registerTokenAsker, setConsoleToken, currentToken } = await load();
    setConsoleToken('tok-1');
    registerTokenAsker(async () => null);
    expect(await askToken(false)).toBeNull();
    expect(currentToken()).toBe('tok-1');
  });
});

describe('api: the public build connected to a console', () => {
  it('sends /api paths to that console, with its token', async () => {
    const { api, setConsoleToken, backend } = await load({ isStatic: true, base: '/bamr87/' });
    backend.setRemoteConsole('https://console.example.test/');
    setConsoleToken('tok-1');
    const calls = serve(() => json({ ok: true }));
    await api('/api/state');
    expect(calls).toEqual([{ url: 'https://console.example.test/api/state', method: 'GET', auth: 'Bearer tok-1', contentType: null, body: null }]);
  });

  it('writes through it like a served page does', async () => {
    const { post, backend } = await load({ isStatic: true, base: '/bamr87/' });
    backend.setRemoteConsole('http://127.0.0.1:4001');
    const calls = serve(() => json({ id: 'j-1' }));
    expect(await post('/api/jobs', { op: 'triage' })).toEqual({ id: 'j-1' });
    expect(calls[0]).toMatchObject({ url: 'http://127.0.0.1:4001/api/jobs', method: 'POST' });
  });

  it('explains a console it cannot reach, naming it, as status 0', async () => {
    const { api, ApiError, backend } = await load({ isStatic: true, base: '/bamr87/' });
    backend.setRemoteConsole('http://127.0.0.1:4001');
    serve(() => { throw new TypeError('Failed to fetch'); });
    const failure = await api('/api/state').then(() => null, (e: unknown) => e as Error & { status: number });
    expect(failure).toBeInstanceOf(ApiError);
    expect(failure?.status).toBe(0);
    expect(failure?.message).toContain('cannot reach the console at http://127.0.0.1:4001');
    expect(failure?.message).toContain('Failed to fetch');
  });
});

describe('api: the public build on its own (the snapshot)', () => {
  const PAGES = { isStatic: true, base: '/bamr87/' } as const;

  it('reads a document from the published snapshot under the base path', async () => {
    const { api } = await load(PAGES);
    const calls = serve(() => json({ projects: 3 }));
    expect(await api('/api/state')).toEqual({ projects: 3 });
    expect(calls.map((c) => c.url)).toEqual(['/bamr87/snapshot/state.json']);
    expect(calls[0].auth).toBeNull();
  });

  it.each(['POST', 'PUT', 'DELETE', 'PATCH', 'post'])('refuses a %s as read-only (405) without a request', async (method) => {
    const { api } = await load(PAGES);
    const calls = serve(() => json({}));
    await expect(api('/api/work/apply', { method, body: '{}' })).rejects.toMatchObject({ status: 405, message: expect.stringContaining('read-only') });
    expect(calls).toEqual([]);
  });

  it('refuses post, put and del the same way', async () => {
    const { post, put, del } = await load(PAGES);
    const calls = serve(() => json({}));
    await expect(post('/api/work/apply', {})).rejects.toMatchObject({ status: 405 });
    await expect(put('/api/voices', {})).rejects.toMatchObject({ status: 405 });
    await expect(del('/api/refine/library/x')).rejects.toMatchObject({ status: 405 });
    expect(calls).toEqual([]);
  });

  it('never sends a console token to the static site', async () => {
    const { api, setConsoleToken } = await load(PAGES);
    setConsoleToken('tok-1');
    const calls = serve(() => json({}));
    await api('/api/state');
    expect(calls[0].auth).toBeNull();
  });

  it('says in /api/capabilities whether this browser holds a GitHub token, which the snapshot cannot know', async () => {
    const { api, backend } = await load(PAGES);
    serve(() => json({ writes: false, gh_authenticated: false }));
    expect(await api('/api/capabilities')).toEqual({ writes: false, gh_authenticated: null });
    backend.setGithubToken('ghp_test');
    expect(await api('/api/capabilities')).toEqual({ writes: false, gh_authenticated: true });
  });

  it('answers the GitHub routes itself instead of looking for a snapshot file', async () => {
    const { api } = await load(PAGES);
    const calls = serve(() => json({}));
    expect(await api('/api/github/log')).toEqual([]);
    expect(await api('/api/jobs')).toEqual([]);
    expect(calls).toEqual([]);
  });

  it('says a console operation needs a console (501) rather than calling it read-only', async () => {
    const { post } = await load(PAGES);
    const calls = serve(() => json({}));
    await expect(post('/api/jobs', { op: 'triage' })).rejects.toMatchObject({ status: 501, message: expect.stringContaining('runs on a console') });
    expect(calls).toEqual([]);
  });

  it('reads the fleet rules, which GitHub does not answer, from the snapshot', async () => {
    const { api } = await load(PAGES);
    const calls = serve(() => json({ owner: 'bamr87', repos: {} }));
    expect(await api('/api/github/fleet')).toEqual({ owner: 'bamr87', repos: {} });
    expect(calls.map((c) => c.url)).toEqual(['/bamr87/snapshot/github/fleet.json']);
  });
});
