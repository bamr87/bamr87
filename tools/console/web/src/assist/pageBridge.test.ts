// pageBridge.ts does what an assistant session asks of the page, and holds the
// rules no session can lift. This file holds the ones decided before the page
// is touched at all, so it runs without a DOM: the mode gate (Look only reads),
// the checks on a command's arguments, and the `data` action, which reads the
// documents the page loaded. The rules that need a page to stand on (dialogs,
// secret fields, links that leave) are in pageBridge.dom.test.ts.
import { QueryClient } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Action, Command, Env, Mode } from './pageBridge';

type Bridge = typeof import('./pageBridge');

let bridge: Bridge;
beforeEach(async () => {
  vi.stubEnv('BASE_URL', '/');
  vi.stubEnv('VITE_STATIC', '');
  vi.stubEnv('VITE_FRONT_DOOR', '');
  vi.resetModules();
  bridge = await import('./pageBridge');
});

function world(mode: Mode, queryClient = new QueryClient()) {
  const navigate = vi.fn<(path: string) => void>();
  const approve = vi.fn<Env['approve']>(async () => true);
  const env: Env = { mode: () => mode, navigate, queryClient, approve };
  return { env, navigate, approve, queryClient };
}

const cmd = (action: Action, args: Record<string, unknown> = {}, ask = false): Command => ({ id: 'c1', action, args, ask, client: 'dock' });

/** What a command was refused with, or null if it ran. */
async function refusal(run: Promise<unknown>) {
  const e = await run.then(() => null, (err: unknown) => err);
  if (e === null) return null;
  expect(e).toBeInstanceOf(bridge.Refusal);
  return e as InstanceType<Bridge['Refusal']>;
}

describe('Refusal', () => {
  it('is an Error that says why and of which kind', () => {
    const r = new bridge.Refusal('declined', 'the person did not allow it');
    expect(r).toBeInstanceOf(Error);
    expect(r.kind).toBe('declined');
    expect(r.message).toBe('the person did not allow it');
  });
});

describe('Look mode', () => {
  it.each<Action>(['navigate', 'click', 'fill', 'press'])('refuses %s: only reads and highlights run', async (action) => {
    const { env, navigate, approve } = world('look');
    const r = await refusal(bridge.run(cmd(action, { path: '/projects', ref: 'e1', text: 'x', key: 'Enter' }), env));
    expect(r?.kind).toBe('refused');
    expect(r?.message).toContain('Look only');
    expect(r?.message).toContain(action);
    expect(navigate).not.toHaveBeenCalled();
    expect(approve).not.toHaveBeenCalled();
  });

  it('refuses them even when the console queued the command as needing no yes', async () => {
    const { env, navigate } = world('look');
    const r = await refusal(bridge.run(cmd('navigate', { path: '/projects' }, false), env));
    expect(r?.kind).toBe('refused');
    expect(navigate).not.toHaveBeenCalled();
  });

  it('still reads the documents the page loaded', async () => {
    const { env, queryClient } = world('look');
    queryClient.setQueryData(['state'], { projects: 3 });
    expect(await bridge.run(cmd('data', { key: 'state' }), env)).toMatchObject({ document: { projects: 3 } });
  });
});

describe('navigate: the path', () => {
  it.each([
    ['nothing', ''],
    ['a relative path', 'projects'],
    ['a protocol-relative address', '//elsewhere.example.test/x'],
    ['another site', 'https://elsewhere.example.test/x'],
    ['a script', 'javascript:alert(1)'],
    ['no path given', undefined],
  ])('refuses %s: it must be an in-app path starting with one /', async (_name, path) => {
    for (const mode of ['ask', 'act'] as const) {
      const { env, navigate } = world(mode);
      const r = await refusal(bridge.run(cmd('navigate', path === undefined ? {} : { path }), env));
      expect(r?.kind).toBe('page');
      expect(r?.message).toContain('in-app path');
      expect(navigate).not.toHaveBeenCalled();
    }
  });
});

describe('a ref', () => {
  it.each<Action>(['read', 'highlight', 'click', 'fill', 'press'])('that no snapshot listed is refused for %s, and the person is not asked', async (action) => {
    const { env, approve } = world('ask');
    const r = await refusal(bridge.run(cmd(action, { ref: 'e12', text: 'x', key: 'Enter' }), env));
    expect(r?.kind).toBe('page');
    expect(r?.message).toContain('e12');
    expect(r?.message).toContain('page_snapshot');
    expect(approve).not.toHaveBeenCalled();
  });

  it.each([['a selector', '#main button'], ['a number', 12], ['an object', { selector: 'button' }]])('must be a ref: %s is refused', async (_name, ref) => {
    const { env } = world('act');
    const r = await refusal(bridge.run(cmd('click', { ref }), env));
    expect(r?.kind).toBe('page');
    expect(r?.message).toContain('page_snapshot');
  });

  it.each<Action>(['click', 'fill'])('is required for %s', async (action) => {
    const { env, approve } = world('act');
    const r = await refusal(bridge.run(cmd(action, { text: 'x' }), env));
    expect(r?.kind).toBe('page');
    expect(r?.message).toContain(`${action} needs a ref`);
    expect(approve).not.toHaveBeenCalled();
  });
});

describe('data: the documents the page loaded', () => {
  async function loaded() {
    const w = world('look', new QueryClient({ defaultOptions: { queries: { retry: false } } }));
    w.queryClient.setQueryData(['state'], { projects: 3, name: 'fleet' });
    w.queryClient.setQueryData(['project', 'scripts'], { name: 'scripts', issues: [1, 2, 3] });
    await w.queryClient.fetchQuery({ queryKey: ['lake'], queryFn: () => Promise.reject(new Error('501 runs on a console')) }).catch(() => undefined);
    return w;
  }
  interface Listing { documents: { key: string; status: string; read_at: string | null; shown: boolean; error?: string }[] }
  interface Doc { key: string; status: string; read_at: string | null; chars: number; truncated: boolean; document?: unknown; text?: string }

  it('lists every document by its key when no key is asked for', async () => {
    const { env } = await loaded();
    const list = (await bridge.run(cmd('data'), env)) as Listing;
    expect(list.documents.map((d) => [d.key, d.status])).toEqual([['["state"]', 'success'], ['["project","scripts"]', 'success'], ['["lake"]', 'error']]);
  });

  it('says when each was read, that none is on screen without a page rendering it, and why one failed', async () => {
    const { env } = await loaded();
    const { documents } = (await bridge.run(cmd('data', { key: '' }), env)) as Listing;
    const [state, , lake] = documents;
    expect(state.read_at).toMatch(/^\d{4}-\d{2}-\d{2}T/);
    expect(state.shown).toBe(false);
    expect(state.error).toBeUndefined();
    expect(lake.read_at).toBeNull();
    expect(lake.error).toBe('501 runs on a console');
  });

  it('reads one document by the key the listing gave', async () => {
    const { env } = await loaded();
    const doc = (await bridge.run(cmd('data', { key: '["project","scripts"]' }), env)) as Doc;
    expect(doc).toMatchObject({ key: '["project","scripts"]', status: 'success', truncated: false, document: { name: 'scripts', issues: [1, 2, 3] } });
    expect(doc.chars).toBe(JSON.stringify({ name: 'scripts', issues: [1, 2, 3] }).length);
    expect(doc.text).toBeUndefined();
  });

  it('reads a one-word key by the word alone', async () => {
    const { env } = await loaded();
    expect(await bridge.run(cmd('data', { key: 'state' }), env)).toMatchObject({ key: '["state"]', document: { projects: 3, name: 'fleet' } });
  });

  it('gives the start of a document over the limit as text, and says it was cut', async () => {
    const { env } = await loaded();
    const whole = JSON.stringify({ name: 'scripts', issues: [1, 2, 3] });
    const doc = (await bridge.run(cmd('data', { key: '["project","scripts"]', max_chars: 10 }), env)) as Doc;
    expect(doc.truncated).toBe(true);
    expect(doc.text).toBe(whole.slice(0, 10));
    expect(doc.chars).toBe(whole.length);
    expect(doc.document).toBeUndefined();
  });

  it('gives a failed document as null with its status', async () => {
    const { env } = await loaded();
    expect(await bridge.run(cmd('data', { key: 'lake' }), env)).toMatchObject({ status: 'error', document: null, truncated: false });
  });

  it('refuses a key the page has not loaded, pointing at the listing', async () => {
    const { env } = await loaded();
    const r = await refusal(bridge.run(cmd('data', { key: 'costs' }), env));
    expect(r?.kind).toBe('page');
    expect(r?.message).toContain('costs');
    expect(r?.message).toContain('page_data');
  });

  it('is an empty listing on a page that has loaded nothing', async () => {
    const { env } = world('act');
    expect(await bridge.run(cmd('data'), env)).toMatchObject({ documents: [] });
  });
});
