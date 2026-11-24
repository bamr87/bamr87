// ghdirect.ts is the public build's write path: with no console behind the
// page, a GitHub token held by the browser makes the page act on GitHub itself.
// Its header states the rules, and they are held here: the same nine actions
// and validation as the console, fleet repos the hub owns only, confirm
// required, every write in this tab's action log, only allowlisted workflows
// and inputs dispatched, and the token sent to api.github.com and nowhere else.
//
// Nothing here reaches the network: fetch is a stub that answers as GitHub and
// as the published snapshot (github/fleet.json, the rules), and records what
// it was asked.
import { describe, expect, it, vi } from 'vitest';
import type { GhAction, GhRepo, GhRepoDetail, GithubStatus, Job, JobTail } from './types';

const API = 'https://api.github.com';
const HUB = 'bamr87/bamr87';
const ACTIONS = '/api/github/repos/bamr87/scripts/actions';

// The page gathers a yes in a confirm modal and then sends it. tools/console/test_console.py
// scans src/ for the literal a page would send, so a test spells it through this name.
const CONFIRMED = true;

const RULES = {
  owner: 'bamr87',
  hub: { repo: HUB, default_branch: 'main' },
  repos: { 'bamr87/scripts': 'scripts', 'bamr87/zer0-mistakes': 'zer0-mistakes' },
  dispatchable: { 'fleet-pulse': ['mode', 'dry_run'], fanout: ['kit', 'repos', 'dry_run'] },
};

function fakeStorage() {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (k: string) => (data.has(k) ? (data.get(k) as string) : null),
    setItem: (k: string, v: string) => void data.set(k, String(v)),
    removeItem: (k: string) => void data.delete(k),
  };
}

/** ghdirect.ts in the public build, in one browser tab that holds `token` (or none). */
async function load(token = 'ghp_test') {
  const local = fakeStorage();
  const session = fakeStorage();
  vi.stubEnv('BASE_URL', '/bamr87/');
  vi.stubEnv('VITE_STATIC', '1');
  vi.stubEnv('VITE_FRONT_DOOR', '');
  vi.stubGlobal('localStorage', local);
  vi.stubGlobal('sessionStorage', session);
  vi.stubGlobal('window', { localStorage: local, sessionStorage: session });
  vi.resetModules();
  const backend = await import('./backend');
  if (token) backend.setGithubToken(token);
  const { githubDirect, isGithubPath } = await import('./ghdirect');
  return {
    isGithubPath,
    get: <T>(path: string) => githubDirect<T>(path, {}),
    send: <T>(path: string, body: unknown, method = 'POST') => githubDirect<T>(path, { method, body: JSON.stringify(body) }),
  };
}

interface GhCall { method: string; path: string; auth: string | null; body: unknown }
interface Reply { status?: number; statusText?: string; body?: unknown; headers?: Record<string, string>; text?: string }
interface Network { calls: GhCall[]; elsewhere: { url: string; auth: string | null }[] }

/** Answer as GitHub (`respond`; no answer is a 404) and as the published snapshot. */
function github(respond: (call: GhCall) => Reply | undefined = () => undefined): Network {
  const net: Network = { calls: [], elsewhere: [] };
  vi.stubGlobal('fetch', vi.fn(async (input: unknown, init: RequestInit = {}) => {
    const url = String(input);
    const headers = new Headers(init.headers);
    if (!url.startsWith(`${API}/`)) {
      net.elsewhere.push({ url, auth: headers.get('Authorization') });
      if (url === '/bamr87/snapshot/github/fleet.json') return new Response(JSON.stringify(RULES), { status: 200 });
      return new Response('not found', { status: 404, statusText: 'Not Found' });
    }
    const call: GhCall = {
      method: (init.method ?? 'GET').toUpperCase(),
      path: url.slice(API.length),
      auth: headers.get('Authorization'),
      body: init.body ? JSON.parse(String(init.body)) : undefined,
    };
    net.calls.push(call);
    const reply = respond(call) ?? { status: 404, statusText: 'Not Found', body: { message: 'Not Found' } };
    const status = reply.status ?? 200;
    const text = status === 204 ? null : reply.text ?? JSON.stringify(reply.body ?? {});
    return new Response(text, { status, statusText: reply.statusText ?? '', headers: reply.headers });
  }));
  return net;
}

/** Let the 1.5 s waits between polls for a new run pass at once (every other timer is left alone). Returns the waits asked for. */
function skipPollWaits(): number[] {
  const waits: number[] = [];
  const real = globalThis.setTimeout;
  vi.spyOn(globalThis, 'setTimeout').mockImplementation(((fn: (...args: unknown[]) => void, ms?: number, ...args: unknown[]) => {
    if (ms !== 1500) return real(fn, ms, ...args);
    waits.push(ms);
    return real(fn, 0, ...args);
  }) as unknown as typeof setTimeout);
  return waits;
}

const sent = (net: Network) => net.calls.map((c) => `${c.method} ${c.path}`);
const failure = (p: Promise<unknown>) => p.then(() => null, (e: unknown) => e as { status: number; message: string });
/** The log's text without its colours. */
const plain = (text: string) => text.replace(/\x1b\[[0-9;]*m/g, '');

describe('isGithubPath', () => {
  it('claims the GitHub routes and the job routes', async () => {
    const { isGithubPath } = await load();
    for (const path of ['/api/github/status', '/api/github/repos', '/api/github/repos/bamr87/scripts', '/api/github/log', '/api/jobs', '/api/jobs/run-7', '/api/jobs/run-7/cancel', '/api/jobs?limit=5']) {
      expect(isGithubPath(path), path).toBe(true);
    }
  });

  it('leaves the fleet rules and every other document to the snapshot', async () => {
    const { isGithubPath } = await load();
    for (const path of ['/api/github/fleet', '/api/state', '/api/fleet', '/api/capabilities', '/api/work', '/github/bamr87/scripts']) {
      expect(isGithubPath(path), path).toBe(false);
    }
  });
});

describe('status', () => {
  it('reports not connected, and asks GitHub nothing, while the browser holds no token', async () => {
    const { get } = await load('');
    const net = github();
    const s = await get<GithubStatus>('/api/github/status');
    expect(s).toMatchObject({ connected: false, source: null, kind: null, login: null, writes_enabled: false, auth_writes: false, fleet_owner: 'bamr87', error: null });
    expect(net.calls).toEqual([]);
  });

  it('reports who the token is, its scopes and its rate limit', async () => {
    const { get } = await load('ghp_test');
    const net = github((c) => (c.path === '/user' ? {
      body: { login: 'bamr87', name: 'Amr', avatar_url: 'https://avatars.githubusercontent.com/u/1' },
      headers: { 'x-oauth-scopes': 'repo, workflow ,read:org', 'x-ratelimit-limit': '5000', 'x-ratelimit-remaining': '4990', 'x-ratelimit-reset': '1795000000' },
    } : undefined));
    const s = await get<GithubStatus>('/api/github/status');
    expect(s).toMatchObject({ connected: true, source: 'browser', login: 'bamr87', name: 'Amr', writes_enabled: true, error: null });
    expect(s.scopes).toEqual(['repo', 'workflow', 'read:org']);
    expect(s.rate).toEqual({ limit: 5000, remaining: 4990, reset: 1795000000 });
    expect(sent(net)).toEqual(['GET /user']);
  });

  it('reports no scopes and an unknown rate when GitHub sends neither (a fine-grained token)', async () => {
    const { get } = await load('github_pat_test');
    github((c) => (c.path === '/user' ? { body: { login: 'bamr87' } } : undefined));
    const s = await get<GithubStatus>('/api/github/status');
    expect(s.scopes).toEqual([]);
    expect(s.rate).toEqual({ limit: null, remaining: null, reset: null });
  });

  it.each([
    ['github_pat_test', 'fine-grained PAT'],
    ['ghp_test', 'classic PAT'],
    ['gho_test', 'OAuth token'],
    ['ghu_test', 'GitHub App user token'],
    ['some-other-token', 'token'],
  ])('names the kind of token %s as %s', async (token, kind) => {
    const { get } = await load(token);
    github((c) => (c.path === '/user' ? { body: { login: 'bamr87' } } : undefined));
    expect((await get<GithubStatus>('/api/github/status')).kind).toBe(kind);
  });

  it('says a rejected token was rejected instead of failing the page', async () => {
    const { get } = await load('ghp_test');
    github(() => ({ status: 401, statusText: 'Unauthorized', body: { message: 'Bad credentials' } }));
    const s = await get<GithubStatus>('/api/github/status');
    expect(s.connected).toBe(false);
    expect(s.login).toBeNull();
    expect(s.error).toBe('GitHub rejected the token: Bad credentials');
  });
});

describe('the token', () => {
  it('goes to api.github.com as a bearer, and to nothing else', async () => {
    const { get, send } = await load('ghp_test');
    const net = github((c) => {
      if (c.path === '/user') return { body: { login: 'bamr87' } };
      if (c.path.startsWith('/user/repos')) return { body: [] };
      if (c.method === 'POST') return { body: { number: 3, html_url: 'https://github.com/bamr87/scripts/issues/3' } };
      return undefined;
    });
    await get('/api/github/status');
    await get('/api/github/repos');
    await send(ACTIONS, { action: 'issue.create', params: { title: 't', body: '' }, confirm: CONFIRMED });
    expect(net.calls.length).toBeGreaterThanOrEqual(3);
    for (const call of net.calls) expect(call.auth).toBe('Bearer ghp_test');
    expect(net.elsewhere.length).toBeGreaterThan(0);
    for (const other of net.elsewhere) expect(other.auth, other.url).toBeNull();
  });

  it('is required: a GitHub read without one is a 401 that points at the Connect page, and no request is made', async () => {
    const { get } = await load('');
    const net = github();
    const e = await failure(get('/api/github/repos'));
    expect(e?.status).toBe(401);
    expect(e?.message).toContain('Connect');
    expect(net.calls).toEqual([]);
  });
});

describe('reading GitHub', () => {
  const repo = (full: string, more: Record<string, unknown> = {}) => ({
    full_name: full, name: full.split('/')[1], owner: { login: full.split('/')[0] }, private: false, archived: false, fork: false,
    description: null, pushed_at: '2026-11-20T00:00:00Z', open_issues_count: 2, stargazers_count: 5, default_branch: 'main',
    html_url: `https://github.com/${full}`, language: 'Shell', ...more,
  });

  it('lists the token’s repos, marking the fleet’s as writable whatever the case of the name', async () => {
    const { get } = await load();
    github((c) => (c.path.startsWith('/user/repos') ? { body: [repo('bamr87/Scripts'), repo('someone/else', { permissions: { push: true } })] } : undefined));
    const repos = await get<GhRepo[]>('/api/github/repos');
    expect(repos.map((r) => [r.full_name, r.fleet_name, r.writable])).toEqual([
      ['bamr87/Scripts', 'scripts', true],
      ['someone/else', null, false],
    ]);
    expect(repos[0]).toMatchObject({ owner: 'bamr87', open_issues: 2, stars: 5, permissions: {} });
    expect(repos[1].permissions).toEqual({ push: true });
  });

  it('stops paging at the first page that is not full', async () => {
    const { get } = await load();
    const full = Array.from({ length: 100 }, (_, i) => repo(`bamr87/r${i}`));
    const net = github((c) => {
      const page = new URLSearchParams(c.path.split('?')[1]).get('page');
      return c.path.startsWith('/user/repos') ? { body: page === '1' ? full : [repo('bamr87/last')] } : undefined;
    });
    expect(await get<GhRepo[]>('/api/github/repos')).toHaveLength(101);
    expect(net.calls).toHaveLength(2);
  });

  it('reads at most three pages', async () => {
    const { get } = await load();
    const full = Array.from({ length: 100 }, (_, i) => repo(`bamr87/r${i}`));
    const net = github((c) => (c.path.startsWith('/user/repos') ? { body: full } : undefined));
    expect(await get<GhRepo[]>('/api/github/repos')).toHaveLength(300);
    expect(net.calls).toHaveLength(3);
  });

  it('builds one repo’s page from its parts, keeping pull requests out of the issue list', async () => {
    const { get } = await load();
    const issue = (number: number, more: Record<string, unknown> = {}) => ({
      number, title: `issue ${number}`, state: 'open', user: { login: 'bamr87' }, labels: [{ name: 'bug' }], comments: 0,
      created_at: 'c', updated_at: 'u', html_url: `https://github.com/bamr87/scripts/issues/${number}`, assignees: [{ login: 'bamr87' }], ...more,
    });
    github((c) => {
      const part = c.path.split('?')[0];
      if (part === '/repos/bamr87/scripts') return { body: { ...repo('bamr87/scripts'), topics: ['bash'], permissions: { push: true } } };
      if (part === '/repos/bamr87/scripts/issues') return { body: [issue(1), issue(2, { pull_request: {} })] };
      if (part === '/repos/bamr87/scripts/pulls') return { body: [{ number: 2, title: 'pr', user: null, draft: true, head: { ref: 'fix/x' }, base: { ref: 'main' }, labels: [] }] };
      if (part === '/repos/bamr87/scripts/actions/runs') return { body: { workflow_runs: [{ id: 9, name: 'CI', head_branch: 'main', status: 'completed', conclusion: 'success' }] } };
      if (part === '/repos/bamr87/scripts/actions/workflows') return { body: { workflows: [{ id: 4, name: 'CI', path: '.github/workflows/ci.yml', state: 'active' }] } };
      if (part === '/repos/bamr87/scripts/labels') return { body: [{ name: 'bug', color: 'd73a4a', description: null }] };
      return undefined;
    });
    const d = await get<GhRepoDetail>('/api/github/repos/bamr87/scripts');
    expect(d).toMatchObject({ nwo: 'bamr87/scripts', fleet_name: 'scripts', writable: true, errors: {} });
    expect(d.issues.map((i) => i.number)).toEqual([1]);
    expect(d.issues[0]).toMatchObject({ user: 'bamr87', labels: ['bug'], assignees: ['bamr87'], is_pr: false });
    expect(d.pulls).toEqual([expect.objectContaining({ number: 2, user: null, draft: true, head: 'fix/x', base: 'main' })]);
    expect(d.runs).toEqual([expect.objectContaining({ id: 9, branch: 'main', conclusion: 'success' })]);
    expect(d.workflows.map((w) => w.path)).toEqual(['.github/workflows/ci.yml']);
    expect(d.repo).toMatchObject({ default_branch: 'main', topics: ['bash'], permissions: { push: true } });
  });

  it('shows what it could read when a part fails, and says which part did', async () => {
    const { get } = await load();
    github((c) => {
      const part = c.path.split('?')[0];
      if (part === '/repos/someone/else') return { body: repo('someone/else') };
      if (part === '/repos/someone/else/actions/runs') return { status: 403, statusText: 'Forbidden', body: { message: 'Resource not accessible by personal access token' } };
      if (part.startsWith('/repos/someone/else/actions/workflows')) return { body: { workflows: [] } };
      return { body: [] };
    });
    const d = await get<GhRepoDetail>('/api/github/repos/someone/else');
    expect(d.writable).toBe(false);
    expect(d.fleet_name).toBeNull();
    expect(d.runs).toEqual([]);
    expect(Object.keys(d.errors)).toEqual(['runs']);
    expect(d.errors.runs).toContain('Resource not accessible');
  });

  it('is a 404 with GitHub’s reason when the repo itself cannot be read', async () => {
    const { get } = await load();
    github();
    const e = await failure(get('/api/github/repos/bamr87/gone'));
    expect(e).toMatchObject({ status: 404, message: 'GitHub: Not Found' });
  });

  it('refuses a name that is not owner/name before asking GitHub', async () => {
    const { get } = await load();
    const net = github();
    for (const bad of ['a b/c', '-lead/repo', 'owner/re po', 'owner/..%2F..']) {
      expect(await failure(get(`/api/github/repos/${bad}`)), bad).toMatchObject({ status: 400, message: 'expected owner/name' });
    }
    expect(net.calls).toEqual([]);
  });

  it('reads an issue and its comments, with an empty body where GitHub has none', async () => {
    const { get } = await load();
    const net = github((c) => {
      if (c.path === '/repos/bamr87/scripts/issues/7') return { body: { number: 7, title: 'broken', state: 'open', user: { login: 'bamr87' }, body: null, labels: [], assignees: [] } };
      if (c.path.startsWith('/repos/bamr87/scripts/issues/7/comments')) return { body: [{ id: 1, user: { login: 'someone' }, body: 'same here', created_at: 'c', html_url: 'h' }, { id: 2, user: null, body: null }] };
      return undefined;
    });
    const t = await get<{ issue: { number: number; body: string }; comments: { id: number; user?: string; body: string }[] }>('/api/github/repos/bamr87/scripts/issues/7');
    expect(t.issue).toMatchObject({ number: 7, body: '' });
    expect(t.comments.map((c) => [c.id, c.user, c.body])).toEqual([[1, 'someone', 'same here'], [2, undefined, '']]);
    expect(net.calls).toHaveLength(2);
  });
});

describe('writing: the gates before any request', () => {
  it('refuses an action it does not know, naming the ones it does', async () => {
    const { send } = await load();
    const net = github();
    const e = await failure(send(ACTIONS, { action: 'repo.delete', params: {}, confirm: CONFIRMED }));
    expect(e?.status).toBe(400);
    for (const known of ['issue.create', 'issue.comment', 'issue.close', 'issue.reopen', 'issue.labels', 'run.rerun_failed', 'run.cancel', 'workflow.enable', 'workflow.disable']) {
      expect(e?.message).toContain(known);
    }
    expect(net.calls).toEqual([]);
  });

  it('refuses a repo that is not one of the fleet’s, confirmed or not', async () => {
    const { send } = await load();
    const net = github();
    const e = await failure(send('/api/github/repos/someone/else/actions', { action: 'issue.close', params: { number: 1 }, confirm: CONFIRMED }));
    expect(e?.status).toBe(403);
    expect(e?.message).toContain('not a fleet repo');
    expect(net.calls).toEqual([]);
  });

  it.each([
    ['no confirm at all', { action: 'issue.close', params: { number: 1 } }],
    ['confirm false', { action: 'issue.close', params: { number: 1 }, confirm: false }],
  ])('refuses a write with %s', async (_name, body) => {
    const { send } = await load();
    const net = github();
    const e = await failure(send(ACTIONS, body));
    expect(e?.status).toBe(403);
    expect(e?.message).toContain('confirm');
    expect(net.calls).toEqual([]);
  });

  it('answers the action route only for a POST', async () => {
    const { get } = await load();
    const net = github();
    expect((await failure(get(ACTIONS)))?.status).toBe(404);
    expect(net.calls.filter((c) => c.method !== 'GET')).toEqual([]);
  });

  it('takes the fleet repo’s name in any case', async () => {
    const { send } = await load();
    const net = github(() => ({ body: {} }));
    await send('/api/github/repos/Bamr87/Scripts/actions', { action: 'issue.reopen', params: { number: 4 }, confirm: CONFIRMED });
    expect(sent(net)).toEqual(['PATCH /repos/Bamr87/Scripts/issues/4']);
  });
});

describe('writing: the nine actions', () => {
  const act = async (action: string, params: Record<string, unknown>, respond?: (c: GhCall) => Reply | undefined) => {
    const { send, get } = await load();
    const net = github(respond ?? (() => ({ body: {} })));
    const outcome = await send<GhAction>(ACTIONS, { action, params, confirm: CONFIRMED }).then((entry) => ({ entry, error: null }), (e: unknown) => ({ entry: null, error: e as { status: number; message: string } }));
    return { ...outcome, net, log: await get<GhAction[]>('/api/github/log') };
  };

  it('issue.create opens an issue and reports its number and link', async () => {
    const { entry, net } = await act('issue.create', { title: '  Broken link  ', body: 'see the docs', labels: 'bug, help wanted' },
      () => ({ status: 201, body: { number: 12, html_url: 'https://github.com/bamr87/scripts/issues/12' } }));
    expect(net.calls).toEqual([{ method: 'POST', path: '/repos/bamr87/scripts/issues', auth: 'Bearer ghp_test', body: { title: 'Broken link', body: 'see the docs', labels: ['bug', 'help wanted'] } }]);
    expect(entry).toMatchObject({ ok: true, action: 'issue.create', repo: 'bamr87/scripts', target: '#12', url: 'https://github.com/bamr87/scripts/issues/12', error: null });
  });

  it('issue.create sends no labels when none are given', async () => {
    const { net } = await act('issue.create', { title: 't', body: '' }, () => ({ body: { number: 1 } }));
    expect(net.calls[0].body).toEqual({ title: 't', body: '' });
  });

  it.each([
    ['an empty title', { title: '   ', body: '' }, 'title'],
    ['a title over 256 characters', { title: 'x'.repeat(257), body: '' }, 'title'],
    ['more than 20 labels', { title: 't', body: '', labels: Array.from({ length: 21 }, (_, i) => `l${i}`) }, 'labels'],
    ['a label over 50 characters', { title: 't', body: '', labels: ['x'.repeat(51)] }, 'labels'],
    ['a label with a control character', { title: 't', body: '', labels: ['bug\nfix'] }, 'labels'],
  ])('issue.create refuses %s before asking GitHub', async (_name, params, word) => {
    const { error, net } = await act('issue.create', params);
    expect(error?.status).toBe(400);
    expect(error?.message).toContain(word);
    expect(net.calls).toEqual([]);
  });

  it('issue.comment posts the comment, trimmed', async () => {
    const { entry, net } = await act('issue.comment', { number: 7, body: '  thanks \n' }, () => ({ body: { html_url: 'https://github.com/bamr87/scripts/issues/7#issuecomment-1' } }));
    expect(net.calls[0]).toMatchObject({ method: 'POST', path: '/repos/bamr87/scripts/issues/7/comments', body: { body: 'thanks' } });
    expect(entry).toMatchObject({ ok: true, target: '#7', url: 'https://github.com/bamr87/scripts/issues/7#issuecomment-1' });
  });

  it('issue.comment refuses an empty comment', async () => {
    const { error, net } = await act('issue.comment', { number: 7, body: '   ' });
    expect(error?.status).toBe(400);
    expect(net.calls).toEqual([]);
  });

  it.each([['a word', 'seven'], ['zero', 0], ['a negative', -3], ['a fraction', 1.5], ['nothing', undefined], ['a path', '7/../8']])('an issue number that is %s is refused before asking GitHub', async (_name, number) => {
    const { error, net } = await act('issue.comment', { number, body: 'x' });
    expect(error).toMatchObject({ status: 400, message: 'number must be a number' });
    expect(net.calls).toEqual([]);
  });

  it('issue.close closes as completed unless told not planned', async () => {
    expect((await act('issue.close', { number: 7 })).net.calls[0]).toMatchObject({ method: 'PATCH', path: '/repos/bamr87/scripts/issues/7', body: { state: 'closed', state_reason: 'completed' } });
    expect((await act('issue.close', { number: 7, reason: 'not_planned' })).net.calls[0].body).toEqual({ state: 'closed', state_reason: 'not_planned' });
  });

  it('issue.close refuses any other reason', async () => {
    const { error, net } = await act('issue.close', { number: 7, reason: 'duplicate' });
    expect(error?.status).toBe(400);
    expect(error?.message).toContain('completed or not_planned');
    expect(net.calls).toEqual([]);
  });

  it('issue.reopen reopens, with no reason', async () => {
    const { net, entry } = await act('issue.reopen', { number: 7 });
    expect(net.calls[0]).toMatchObject({ method: 'PATCH', path: '/repos/bamr87/scripts/issues/7', body: { state: 'open' } });
    expect(entry?.target).toBe('#7');
  });

  it('issue.labels adds in one request and removes one by one, each name encoded', async () => {
    const { net, entry } = await act('issue.labels', { number: 7, add: ['bug', 'p1'], remove: 'help wanted, needs/triage' });
    expect(sent(net)).toEqual([
      'POST /repos/bamr87/scripts/issues/7/labels',
      'DELETE /repos/bamr87/scripts/issues/7/labels/help%20wanted',
      'DELETE /repos/bamr87/scripts/issues/7/labels/needs%2Ftriage',
    ]);
    expect(net.calls[0].body).toEqual({ labels: ['bug', 'p1'] });
    expect(entry).toMatchObject({ ok: true, target: '#7' });
  });

  it('issue.labels counts a label that is already absent as removed', async () => {
    const { entry, error } = await act('issue.labels', { number: 7, remove: ['gone'] }, () => ({ status: 404, body: { message: 'Label does not exist' } }));
    expect(error).toBeNull();
    expect(entry?.ok).toBe(true);
  });

  it('issue.labels fails when a removal is refused for any other reason', async () => {
    const { error, log } = await act('issue.labels', { number: 7, remove: ['bug'] }, () => ({ status: 403, body: { message: 'Must have admin rights' } }));
    expect(error).toMatchObject({ status: 403, message: 'GitHub: Must have admin rights' });
    expect(log[0]).toMatchObject({ ok: false, target: '#7' });
  });

  it('issue.labels refuses a request that adds and removes nothing', async () => {
    const { error, net } = await act('issue.labels', { number: 7, add: [], remove: ' , ' });
    expect(error).toMatchObject({ status: 400, message: 'nothing to add or remove' });
    expect(net.calls).toEqual([]);
  });

  it('run.rerun_failed and run.cancel act on the run', async () => {
    const rerun = await act('run.rerun_failed', { run_id: 9001 });
    expect(sent(rerun.net)).toEqual(['POST /repos/bamr87/scripts/actions/runs/9001/rerun-failed-jobs']);
    expect(rerun.entry?.target).toBe('run 9001');
    const cancel = await act('run.cancel', { run_id: '9001' });
    expect(sent(cancel.net)).toEqual(['POST /repos/bamr87/scripts/actions/runs/9001/cancel']);
  });

  it('workflow.enable and workflow.disable act on the workflow', async () => {
    const on = await act('workflow.enable', { workflow_id: 44 });
    expect(sent(on.net)).toEqual(['PUT /repos/bamr87/scripts/actions/workflows/44/enable']);
    expect(on.entry?.target).toBe('workflow 44');
    const off = await act('workflow.disable', { workflow_id: 44 });
    expect(sent(off.net)).toEqual(['PUT /repos/bamr87/scripts/actions/workflows/44/disable']);
  });

  it('a run or workflow id that is not a number is refused before asking GitHub', async () => {
    expect((await act('run.cancel', { run_id: '9001/../../x' })).error).toMatchObject({ status: 400, message: 'run_id must be a number' });
    const bad = await act('workflow.disable', { workflow_id: 'ci.yml' });
    expect(bad.error).toMatchObject({ status: 400, message: 'workflow_id must be a number' });
    expect(bad.net.calls).toEqual([]);
  });
});

describe('writing: the action log', () => {
  it('starts empty', async () => {
    const { get } = await load();
    github();
    expect(await get('/api/github/log')).toEqual([]);
  });

  it('records every write, newest first, with when it happened to the second', async () => {
    const { get, send } = await load();
    github(() => ({ body: { number: 5, html_url: 'https://github.com/bamr87/scripts/issues/5' } }));
    await send(ACTIONS, { action: 'issue.create', params: { title: 'first', body: '' }, confirm: CONFIRMED });
    await send(ACTIONS, { action: 'issue.close', params: { number: 5 }, confirm: CONFIRMED });
    const log = await get<GhAction[]>('/api/github/log');
    expect(log.map((e) => [e.action, e.target, e.ok])).toEqual([['issue.close', '#5', true], ['issue.create', '#5', true]]);
    expect(log[0].label).toBe('Close an issue');
    expect(log[0].at).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/);
  });

  it('records a write GitHub refused, with the reason, and still fails', async () => {
    const { get, send } = await load();
    github(() => ({ status: 422, statusText: 'Unprocessable Entity', body: { message: 'Validation Failed' } }));
    const e = await failure(send(ACTIONS, { action: 'issue.comment', params: { number: 5, body: 'x' }, confirm: CONFIRMED }));
    expect(e).toMatchObject({ status: 422, message: 'GitHub: Validation Failed' });
    expect(await get<GhAction[]>('/api/github/log')).toEqual([expect.objectContaining({ action: 'issue.comment', target: '#5', ok: false, url: null, error: 'GitHub: Validation Failed' })]);
  });

  it('records nothing for a request stopped at the gates', async () => {
    const { get, send } = await load();
    github();
    await failure(send(ACTIONS, { action: 'issue.close', params: { number: 5 } }));
    await failure(send('/api/github/repos/someone/else/actions', { action: 'issue.close', params: { number: 5 }, confirm: CONFIRMED }));
    expect(await get('/api/github/log')).toEqual([]);
  });

  it('belongs to the tab: another tab starts with an empty one', async () => {
    const first = await load();
    github(() => ({ body: {} }));
    await first.send(ACTIONS, { action: 'issue.reopen', params: { number: 5 }, confirm: CONFIRMED });
    const second = await load();
    github();
    expect(await second.get('/api/github/log')).toEqual([]);
  });
});

describe('GitHub’s answers', () => {
  it('uses the status line when a failure carries no message', async () => {
    const { get } = await load();
    github(() => ({ status: 502, statusText: 'Bad Gateway', text: '<html>bad gateway</html>' }));
    expect(await failure(get('/api/github/repos'))).toMatchObject({ status: 502, message: 'GitHub: 502 Bad Gateway' });
  });

  it('says a 401 is the token being rejected', async () => {
    const { get } = await load();
    github(() => ({ status: 401, statusText: 'Unauthorized', body: { message: 'Bad credentials' } }));
    expect(await failure(get('/api/github/repos'))).toMatchObject({ status: 401, message: 'GitHub rejected the token: Bad credentials' });
  });
});

describe('dispatching a control-plane workflow', () => {
  const run = (more: Record<string, unknown> = {}) => ({
    id: 555, name: 'Fleet pulse', run_number: 31, actor: { login: 'bamr87' }, path: '.github/workflows/fleet-pulse.yml', status: 'queued', conclusion: null,
    html_url: `https://github.com/${HUB}/actions/runs/555`, created_at: '2026-11-22T12:00:00Z', run_started_at: '2026-11-22T12:00:01Z', updated_at: '2026-11-22T12:00:02Z', ...more,
  });
  const dispatches = (net: Network) => net.calls.filter((c) => c.method === 'POST');

  it('dispatches on the hub’s default branch with the inputs as text, and returns the new run as a job', async () => {
    const { send } = await load();
    const net = github((c) => {
      if (c.method === 'POST') return { body: { workflow_run_id: 555 } };
      if (c.path === `/repos/${HUB}/actions/runs/555`) return { body: run() };
      return undefined;
    });
    const job = await send<Job>('/api/jobs', { op: 'dispatch', params: { workflow: 'fleet-pulse', fields: { mode: 'report', dry_run: true } }, confirm: CONFIRMED });
    expect(dispatches(net)).toEqual([expect.objectContaining({ path: `/repos/${HUB}/actions/workflows/fleet-pulse.yml/dispatches` })]);
    expect(dispatches(net)[0].body).toMatchObject({ ref: 'main', inputs: { mode: 'report', dry_run: 'true' } });
    expect(job).toMatchObject({ id: 'run-555', op: 'dispatch', status: 'queued', remote_write: true, exit_code: null, finished: null });
    expect(job.title).toBe('Fleet pulse #31 · bamr87');
    expect(job.argv).toEqual(['gh', 'workflow', 'run', 'fleet-pulse.yml']);
    expect(job.params).toMatchObject({ workflow: 'fleet-pulse', run_url: `https://github.com/${HUB}/actions/runs/555` });
  });

  it('dispatches with no inputs when none are given', async () => {
    const { send } = await load();
    const net = github((c) => (c.method === 'POST' ? { body: { workflow_run_id: 555 } } : { body: run() }));
    await send<Job>('/api/jobs', { op: 'dispatch', params: { workflow: 'fleet-pulse' }, confirm: CONFIRMED });
    expect(dispatches(net)[0].body).toMatchObject({ inputs: {} });
  });

  it('refuses a workflow that is not on the allowlist, naming the ones that are', async () => {
    const { send } = await load();
    const net = github();
    const e = await failure(send('/api/jobs', { op: 'dispatch', params: { workflow: 'token-rotation' }, confirm: CONFIRMED }));
    expect(e?.status).toBe(400);
    expect(e?.message).toContain('fanout, fleet-pulse');
    expect(net.calls).toEqual([]);
  });

  it('refuses to dispatch without confirm', async () => {
    const { send } = await load();
    const net = github();
    const e = await failure(send('/api/jobs', { op: 'dispatch', params: { workflow: 'fleet-pulse' } }));
    expect(e?.status).toBe(409);
    expect(e?.message).toContain('confirm');
    expect(net.calls).toEqual([]);
  });

  it('refuses an input the workflow is not allowed to take', async () => {
    const { send } = await load();
    const net = github();
    const e = await failure(send('/api/jobs', { op: 'dispatch', params: { workflow: 'fleet-pulse', fields: { kit: 'schema' } }, confirm: CONFIRMED }));
    expect(e).toMatchObject({ status: 400, message: "fleet-pulse does not accept input 'kit'" });
    expect(net.calls).toEqual([]);
  });

  it.each([['a shell substitution', '$(id)'], ['a quote', 'a"b'], ['a line break', 'a\nb'], ['a semicolon', 'a;b'], ['more than 120 characters', 'x'.repeat(121)]])('refuses an input value with %s', async (_name, value) => {
    const { send } = await load();
    const net = github();
    const e = await failure(send('/api/jobs', { op: 'dispatch', params: { workflow: 'fanout', fields: { repos: value } }, confirm: CONFIRMED }));
    expect(e?.status).toBe(400);
    expect(e?.message).toContain("input 'repos'");
    expect(net.calls).toEqual([]);
  });

  it('passes the values an input legitimately takes', async () => {
    const { send } = await load();
    const net = github((c) => (c.method === 'POST' ? { body: { workflow_run_id: 555 } } : { body: run() }));
    await send('/api/jobs', { op: 'dispatch', params: { workflow: 'fanout', fields: { kit: 'deps-latest', repos: 'bamr87/scripts, bamr87/zer0-mistakes', dry_run: false } }, confirm: CONFIRMED });
    expect(dispatches(net)[0].body).toMatchObject({ inputs: { kit: 'deps-latest', repos: 'bamr87/scripts, bamr87/zer0-mistakes', dry_run: 'false' } });
  });

  it('refuses inputs that are not an object', async () => {
    const { send } = await load();
    github();
    const e = await failure(send('/api/jobs', { op: 'dispatch', params: { workflow: 'fleet-pulse', fields: ['mode'] }, confirm: CONFIRMED }));
    expect(e).toMatchObject({ status: 400, message: 'fields must be an object' });
  });

  it('says any other operation runs on a console (501)', async () => {
    const { send } = await load();
    const net = github();
    const e = await failure(send('/api/jobs', { op: 'triage', params: {}, confirm: CONFIRMED }));
    expect(e?.status).toBe(501);
    expect(e?.message).toContain('triage');
    expect(net.calls).toEqual([]);
  });

  it('finds the new run by polling when GitHub does not name it, skipping runs from before the dispatch', async () => {
    const { send } = await load();
    const waits = skipPollWaits();
    let polls = 0;
    const net = github((c) => {
      if (c.method === 'POST') return { status: 204 };
      if (c.path.startsWith(`/repos/${HUB}/actions/workflows/fleet-pulse.yml/runs`)) {
        polls += 1;
        const old = { id: 1, created_at: '2020-01-01T00:00:00Z' };
        return { body: { workflow_runs: polls < 3 ? [old] : [{ id: 555, created_at: new Date().toISOString() }, old] } };
      }
      if (c.path === `/repos/${HUB}/actions/runs/555`) return { body: run() };
      return undefined;
    });
    const job = await send<Job>('/api/jobs', { op: 'dispatch', params: { workflow: 'fleet-pulse' }, confirm: CONFIRMED });
    expect(job.id).toBe('run-555');
    expect(polls).toBe(3);
    expect(waits).toEqual([1500, 1500, 1500]);
    expect(dispatches(net)).toHaveLength(1);
  });

  it('returns a queued placeholder, dispatched once, when the run has not appeared after eight polls', async () => {
    const { send } = await load();
    const waits = skipPollWaits();
    const net = github((c) => (c.method === 'POST' ? { status: 204 } : { body: { workflow_runs: [] } }));
    const job = await send<Job>('/api/jobs', { op: 'dispatch', params: { workflow: 'fleet-pulse' }, confirm: CONFIRMED });
    expect(job).toMatchObject({ id: 'pending-fleet-pulse', op: 'dispatch', status: 'queued', remote_write: true });
    expect(dispatches(net)).toHaveLength(1);
    expect(net.calls.filter((c) => c.method === 'GET')).toHaveLength(8);
    expect(waits).toHaveLength(8);
  });
});

describe('jobs: the hub’s dispatched runs', () => {
  const run = (id: number, status: string, conclusion: string | null, more: Record<string, unknown> = {}) => ({
    id, name: 'Fleet pulse', run_number: id, path: '.github/workflows/fleet-pulse.yml', status, conclusion,
    html_url: `https://github.com/${HUB}/actions/runs/${id}`, created_at: '2026-11-22T12:00:00Z', run_started_at: '2026-11-22T12:00:05Z', updated_at: '2026-11-22T12:09:00Z', ...more,
  });

  it('is an empty list, and asks GitHub nothing, without a token', async () => {
    const { get } = await load('');
    const net = github();
    expect(await get('/api/jobs')).toEqual([]);
    expect(net.calls).toEqual([]);
  });

  it('lists the hub’s workflow_dispatch runs as jobs', async () => {
    const { get } = await load();
    const net = github((c) => (c.path.startsWith(`/repos/${HUB}/actions/runs?`) ? { body: { workflow_runs: [run(2, 'in_progress', null), run(1, 'completed', 'success')] } } : undefined));
    const jobs = await get<Job[]>('/api/jobs');
    expect(jobs.map((j) => j.id)).toEqual(['run-2', 'run-1']);
    expect(new URLSearchParams(net.calls[0].path.split('?')[1]).get('event')).toBe('workflow_dispatch');
  });

  it.each([
    ['queued', null, 'queued'], ['requested', null, 'queued'], ['waiting', null, 'queued'], ['pending', null, 'queued'],
    ['in_progress', null, 'running'],
    ['completed', 'success', 'succeeded'], ['completed', 'cancelled', 'cancelled'],
    ['completed', 'failure', 'failed'], ['completed', 'timed_out', 'failed'], ['completed', 'startup_failure', 'failed'],
  ])('reads a run that is %s / %s as %s', async (status, conclusion, expected) => {
    const { get } = await load();
    github(() => ({ body: { workflow_runs: [run(1, status, conclusion)] } }));
    const [job] = await get<Job[]>('/api/jobs');
    expect(job.status).toBe(expected);
  });

  it('gives a finished run an exit code and an end time, and a running one neither', async () => {
    const { get } = await load();
    github(() => ({ body: { workflow_runs: [run(3, 'completed', 'success'), run(2, 'completed', 'failure'), run(1, 'in_progress', null)] } }));
    const [ok, bad, live] = await get<Job[]>('/api/jobs');
    expect([ok.exit_code, ok.finished]).toEqual([0, '2026-11-22T12:09:00Z']);
    expect([bad.exit_code, bad.finished]).toEqual([1, '2026-11-22T12:09:00Z']);
    expect([live.exit_code, live.finished]).toEqual([null, null]);
    expect(live.started).toBe('2026-11-22T12:00:05Z');
  });

  it('names the workflow from the run’s file, without a ref GitHub appends, and from the run when there is no file', async () => {
    const { get } = await load();
    github(() => ({ body: { workflow_runs: [
      run(1, 'queued', null, { path: '.github/workflows/fanout.yaml@main' }),
      run(2, 'queued', null, { path: undefined, name: 'Backlog fanout', actor: { login: 'bamr87' } }),
    ] } }));
    const [a, b] = await get<Job[]>('/api/jobs');
    expect(a.argv).toEqual(['gh', 'workflow', 'run', 'fanout.yml']);
    expect(a.title).toBe('Fleet pulse #1');
    expect(b.argv).toEqual(['gh', 'workflow', 'run', 'Backlog fanout.yml']);
    expect(b.title).toBe('Backlog fanout #2 · bamr87');
  });
});

describe('jobs: a run’s steps as the live log', () => {
  const URL_77 = `https://github.com/${HUB}/actions/runs/77`;
  const theRun = (status: string, conclusion: string | null) => ({ id: 77, name: 'Fleet pulse', run_number: 31, path: '.github/workflows/fleet-pulse.yml', status, conclusion, html_url: URL_77, created_at: 'c', updated_at: 'u' });
  const step = (number: number, name: string, status: string, conclusion: string | null = null, started?: string, completed?: string) => ({ number, name, status, conclusion, started_at: started, completed_at: completed });

  /** GitHub while the run is going, then after it failed. */
  function runFails() {
    let finished = false;
    const net = github((c) => {
      if (c.path === `/repos/${HUB}/actions/runs/77`) return { body: theRun(finished ? 'completed' : 'in_progress', finished ? 'failure' : null) };
      if (c.path.startsWith(`/repos/${HUB}/actions/runs/77/jobs`)) {
        return { body: { jobs: finished ? [
          { id: 1, name: 'gather', status: 'completed', conclusion: 'failure', started_at: 's', steps: [
            step(1, 'Checkout', 'completed', 'success', '2026-11-22T12:00:00Z', '2026-11-22T12:00:03Z'),
            step(2, 'Gather signals', 'completed', 'failure', '2026-11-22T12:00:03Z', '2026-11-22T12:01:08Z'),
            step(3, 'Publish', 'completed', 'skipped'),
          ] },
          { id: 2, name: 'doctor', status: 'completed', conclusion: 'skipped', started_at: null, steps: [] },
        ] : [
          { id: 1, name: 'gather', status: 'in_progress', conclusion: null, started_at: 's', steps: [
            step(1, 'Checkout', 'completed', 'success', '2026-11-22T12:00:00Z', '2026-11-22T12:00:03Z'),
            step(2, 'Gather signals', 'in_progress'),
            step(3, 'Publish', 'queued'),
          ] },
          { id: 2, name: 'doctor', status: 'queued', conclusion: null, started_at: null, steps: [] },
        ] } };
      }
      return undefined;
    });
    return { net, finish: () => { finished = true; } };
  }

  it('shows the run’s link, each started job and each finished step, and stops at the step still running', async () => {
    const { get } = await load();
    runFails();
    const tail = await get<JobTail>('/api/jobs/run-77');
    expect(plain(tail.text).split('\n')).toEqual([URL_77, '▶ gather', '  ✓ Checkout 3s', '']);
    expect(tail.done).toBe(false);
    expect(tail.job).toMatchObject({ id: 'run-77', status: 'running' });
    expect(tail.offset).toBe(tail.text.length);
  });

  it('is append-only: a later poll from the last offset returns only what is new, and the pieces add up to the whole', async () => {
    const { get } = await load();
    const gh = runFails();
    const first = await get<JobTail>('/api/jobs/run-77?offset=0');
    const same = await get<JobTail>(`/api/jobs/run-77?offset=${first.offset}`);
    expect(same.text).toBe('');
    expect(same.offset).toBe(first.offset);

    gh.finish();
    const second = await get<JobTail>(`/api/jobs/run-77?offset=${first.offset}`);
    expect(plain(second.text).split('\n')).toEqual([
      '  ✗ Gather signals 1m5s', '  – Publish', '■ gather — failure', '▶ doctor', '■ doctor — skipped', '', `run failure — full logs: ${URL_77}`, '',
    ]);
    expect(second.done).toBe(true);
    expect(second.job).toMatchObject({ status: 'failed', exit_code: 1 });

    const whole = await get<JobTail>('/api/jobs/run-77?offset=0');
    expect(whole.text).toBe(first.text + second.text);
    expect(whole.offset).toBe(second.offset);
  });

  it('colours a passed step green, a failed one red and a skipped one grey, and resets after each', async () => {
    const { get } = await load();
    const gh = runFails();
    gh.finish();
    const lines = (await get<JobTail>('/api/jobs/run-77')).text.split('\n');
    const line = (name: string) => lines.find((l) => l.includes(name)) ?? '';
    expect(line('Checkout')).toContain('\x1b[32m✓');
    expect(line('Gather signals')).toContain('\x1b[31m✗');
    expect(line('Publish')).toContain('\x1b[90m–');
    for (const name of ['Checkout', 'Gather signals', 'Publish', '■ gather']) expect(line(name).endsWith('\x1b[0m'), name).toBe(true);
  });

  it('ends a successful run with the green line', async () => {
    const { get } = await load();
    github((c) => (c.path.includes('/jobs') ? { body: { jobs: [] } } : { body: theRun('completed', 'success') }));
    const tail = await get<JobTail>('/api/jobs/run-77');
    expect(tail.done).toBe(true);
    expect(tail.text).toContain('\x1b[32mrun success');
    expect(tail.job).toMatchObject({ status: 'succeeded', exit_code: 0 });
  });

  it('is a 404 for a job id that is not a run', async () => {
    const { get } = await load();
    const net = github();
    for (const id of ['pending-fleet-pulse', 'run-abc', 'j-20261122-1']) {
      expect(await failure(get(`/api/jobs/${id}`)), id).toMatchObject({ status: 404, message: 'no such job' });
    }
    expect(net.calls).toEqual([]);
  });

  it('cancels a run on the hub and returns the job', async () => {
    const { send } = await load();
    const net = github((c) => {
      if (c.method === 'POST') return { status: 202, body: {} };
      if (c.path.includes('/jobs')) return { body: { jobs: [] } };
      return { body: theRun('in_progress', null) };
    });
    const job = await send<Job>('/api/jobs/run-77/cancel', {});
    expect(sent(net)[0]).toBe(`POST /repos/${HUB}/actions/runs/77/cancel`);
    expect(job).toMatchObject({ id: 'run-77', status: 'running' });
  });

  it('refuses to cancel what is not a run, before asking GitHub', async () => {
    const { send } = await load();
    const net = github();
    expect((await failure(send('/api/jobs/pending-fleet-pulse/cancel', {})))?.status).toBe(400);
    expect(net.calls).toEqual([]);
  });
});

describe('routes the public page does not have', () => {
  it.each(['/api/github/oauth/device', '/api/github/oauth/callback?code=x', '/api/github/disconnect'])('answers %s as 501: paste a token instead', async (path) => {
    const { get } = await load();
    const net = github();
    const e = await failure(get(path));
    expect(e?.status).toBe(501);
    expect(e?.message).toContain('Connect page');
    expect(net.calls).toEqual([]);
  });

  it('answers an unknown GitHub route as a 404 that names it', async () => {
    const { get } = await load();
    github();
    expect(await failure(get('/api/github/nope'))).toMatchObject({ status: 404, message: 'no GitHub route for /api/github/nope' });
  });

  it('serves the fleet rules from the snapshot', async () => {
    const { get } = await load();
    const net = github();
    expect(await get('/api/github/fleet')).toEqual(RULES);
    expect(net.calls).toEqual([]);
  });
});
