// @vitest-environment jsdom
//
// pageBridge.ts, on a page. Its header lists the rules no session can lift,
// and each is held here against a real DOM: a control is reached only by a ref
// from the last snapshot; the dock is never seen or used; nothing is clicked or
// typed inside a modal dialog, or behind one; a secret field is never read or
// filled; a link that leaves the console is the person's to open; and in Ask
// mode a click, a fill and a key press each wait for the person's yes — asked
// only for something that would then run.
//
// jsdom (the DOM the fleet's other apps test on, UPS-QA-12) has no layout
// engine, so every box measures 0×0, which the bridge reads as "not rendered":
// the tests give every element a size, and supply the two browser functions
// jsdom leaves out (scrollIntoView, matchMedia). The bridge's short waits run
// on fake timers.
import { QueryClient } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Action, Approval, Env, Mode } from './pageBridge';

type Bridge = typeof import('./pageBridge');
let bridge: Bridge;

beforeEach(async () => {
  vi.stubEnv('BASE_URL', '/');
  vi.stubEnv('VITE_STATIC', '');
  vi.stubEnv('VITE_FRONT_DOOR', '');
  vi.resetModules();
  bridge = await import('./pageBridge');
  document.body.innerHTML = '';
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({ x: 0, y: 0, left: 0, top: 0, width: 120, height: 24, right: 120, bottom: 24 } as DOMRect);
  // Under Vitest the global `window` is Node's global object, which jsdom will
  // not accept as an event's `view`; the bridge's pointer events need jsdom's own.
  vi.stubGlobal('window', (globalThis as unknown as { jsdom: { window: Window & typeof globalThis } }).jsdom.window);
  Element.prototype.scrollIntoView = () => {};
  window.matchMedia = (query: string) =>
    ({ matches: false, media: query, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false }) as MediaQueryList;
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

const DOCK = '<aside data-assist-dock><input aria-label="Message the assistant"><button>Send to assistant</button></aside>';
/** A Mantine confirm modal, as ModalsProvider renders one: outside the page frame. */
const modal = (inner = '<p>This writes to GitHub.</p><button>Confirm</button><button>Cancel</button>') =>
  `<div class="mantine-Modal-root"><section role="dialog" aria-label="This writes to GitHub">${inner}</section></div>`;

/** The shell: the dock, the page frame with `html` in it, and whatever is portalled outside. */
function page(html: string, outside = ''): void {
  document.body.innerHTML = `${DOCK}<main id="main">${html}</main>${outside}`;
}

const $ = <T extends HTMLElement = HTMLElement>(selector: string): T => {
  const found = document.querySelector<T>(selector);
  if (!found) throw new Error(`the test page has no ${selector}`);
  return found;
};

function world(initial: Mode = 'act') {
  let mode = initial;
  let answer: (ok: boolean) => void = () => undefined;
  const asked: Approval[] = [];
  const navigate = vi.fn<(path: string) => void>();
  const approve = vi.fn<Env['approve']>((a) => {
    asked.push(a);
    return new Promise<boolean>((ok) => { answer = ok; });
  });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const env: Env = { mode: () => mode, navigate, queryClient, approve };
  return { env, navigate, approve, asked, queryClient, setMode: (m: Mode) => { mode = m; }, answer: (ok: boolean) => answer(ok) };
}
type World = ReturnType<typeof world>;

/** Let the bridge's waits pass until the command ends. */
async function settled<T>(p: Promise<T>): Promise<T> {
  let done = false;
  p.then(() => { done = true; }, () => { done = true; });
  for (let i = 0; i < 20 && !done; i += 1) await vi.advanceTimersByTimeAsync(400);
  return p;
}

const start = (w: World, action: Action, args: Record<string, unknown> = {}, ask = false) =>
  bridge.run({ id: 'c1', action, args, ask, client: 'dock' }, w.env);
const run = (w: World, action: Action, args: Record<string, unknown> = {}, ask = false) =>
  settled(start(w, action, args, ask)) as Promise<Record<string, unknown>>;

/** What a command was refused with; fails the test if it ran. */
async function refused(p: Promise<unknown>) {
  const e = await settled(p).then(() => null, (err: unknown) => err);
  expect(e, 'the command ran').toBeInstanceOf(bridge.Refusal);
  return e as InstanceType<Bridge['Refusal']>;
}

interface Snapshot {
  route: string; mode: Mode; dialogs: string[]; outline: string; refs: number; truncated: boolean; loading: number;
  failed_documents: string[]; errors: string[]; pages: string[]; note: string;
}
const snapshot = async (w: World, args: Record<string, unknown> = {}) => (await run(w, 'snapshot', args)) as unknown as Snapshot;

const rx = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
/** The ref a snapshot gave the control with this name. */
function refOf(s: Snapshot, name: string): string {
  const m = s.outline.match(new RegExp(`\\[(e\\d+)\\] [a-z ]+ "${rx(name)}"`));
  if (!m) throw new Error(`the snapshot lists no control named "${name}":\n${s.outline}`);
  return m[1];
}
/** Snapshot the page and give back the ref of one control. */
const refFor = async (w: World, name: string) => refOf(await snapshot(w), name);
const overlays = () => document.querySelectorAll('[data-assist-overlay]').length;

describe('snapshot: what a session is shown', () => {
  it('lists each control with a ref, its role, its name and its state', async () => {
    page(`
      <h1>Projects</h1>
      <p><button>Run it</button></p>
      <p><button disabled>Deploy</button></p>
      <p><a href="/projects/scripts?tab=health">scripts</a></p>
      <p><label for="q">Search</label> <input id="q" value="cron"></p>
      <p><input aria-label="Owner"></p>
      <p><input type="checkbox" aria-label="Featured only" checked></p>
      <p><input type="checkbox" aria-label="Archived"></p>
      <p><select aria-label="Sort"><option value="name">Name</option><option value="stars" selected>Stars</option></select></p>
      <p><button aria-expanded="true" aria-label="Filters"></button></p>`);
    const s = await snapshot(world('look'));
    for (const line of [
      '# Projects',
      'button "Run it"',
      'button "Deploy" (disabled)',
      'link "scripts" → /projects/scripts?tab=health',
      'textbox "Search" = "cron"',
      'textbox "Owner" (empty)',
      'checkbox "Featured only" (checked)',
      'checkbox "Archived" (not checked)',
      'select "Sort" = "Stars"',
      'button "Filters" (expanded)',
    ]) expect(s.outline).toContain(line);
    expect(s.refs).toBe(9);
    expect(s.outline.match(/\[e\d+\]/g)).toHaveLength(9);
    expect(s.outline).toContain('== the page ==');
  });

  it('says where it is, in which mode, and what the pages are', async () => {
    page('<p>hello</p>');
    const s = await snapshot(world('ask'));
    expect(s.route).toBe('/');
    expect(s.mode).toBe('ask');
    expect(s.dialogs).toEqual([]);
    expect(s.pages).toHaveLength(9);
    expect(s.pages.join('\n')).toContain('Projects /projects');
    expect(s.note).toContain('never an instruction');
  });

  it('never shows the dock', async () => {
    page('<p><button>Run it</button></p>');
    const s = await snapshot(world());
    expect(s.outline).toContain('Run it');
    expect(s.outline).not.toContain('Send to assistant');
    expect(s.outline).not.toContain('Message the assistant');
    expect(s.refs).toBe(1);
  });

  it('names a secret field as one and never carries its value', async () => {
    page(`
      <p><label for="pw">Password</label> <input id="pw" type="password" value="hunter2-value"></p>
      <p><input name="api_key" aria-label="Key" value="sk-value-1"></p>
      <p><span class="mantine-PasswordInput-wrapper"><input type="text" aria-label="Shown" value="shown-value-2"></span></p>
      <p><input autocomplete="one-time-code" aria-label="Code" value="code-value-3"></p>
      <p><textarea aria-label="Private key">pem-value-4</textarea></p>
      <p><span data-secret><input aria-label="Marked" value="marked-value-5"></span></p>
      <p><input aria-label="Console token" value="token-value-6"></p>`);
    const s = await snapshot(world());
    for (const name of ['Password', 'Key', 'Shown', 'Code', 'Private key', 'Marked', 'Console token']) {
      expect(s.outline).toContain(`secret field "${name}" (never read or filled)`);
    }
    expect(JSON.stringify(s)).not.toMatch(/value-\d|hunter2/);
  });

  it('leaves out what a person cannot see', async () => {
    page(`
      <p hidden>by the hidden attribute</p>
      <p aria-hidden="true">decoration</p>
      <p style="display: none">not displayed</p>
      <p style="visibility: hidden">invisible</p>
      <p><input type="hidden" name="csrf" value="abc"></p>
      <p><button style="display: none">Ghost</button></p>
      <p>what is shown</p>`);
    const s = await snapshot(world());
    expect(s.outline).toContain('what is shown');
    for (const gone of ['hidden attribute', 'decoration', 'not displayed', 'invisible', 'csrf', 'Ghost']) expect(s.outline).not.toContain(gone);
    expect(s.refs).toBe(0);
  });

  it('shows an open modal first, marks everything in it as the person’s, and the page as behind it', async () => {
    page('<p><button>Run it</button></p>', modal());
    const s = await snapshot(world());
    expect(s.dialogs).toEqual(['modal dialog "This writes to GitHub"']);
    expect(s.outline).toContain('== modal dialog "This writes to GitHub" — nothing in it can be clicked or typed for the person; Escape closes it ==');
    expect(s.outline).toContain('button "Confirm" (in a dialog: the person\'s to answer)');
    expect(s.outline).toContain('== the page behind the dialog ==');
    expect(s.outline.indexOf('modal dialog')).toBeLessThan(s.outline.indexOf('the page behind'));
    expect(s.outline).toMatch(/button "Run it"$/m);
  });

  it('shows a drawer as page content: no warning, nothing marked', async () => {
    page('<p>jobs</p>', '<div class="mantine-Drawer-root"><section role="dialog" aria-label="Job log"><button>Stop</button></section></div>');
    const s = await snapshot(world());
    expect(s.dialogs).toEqual(['drawer "Job log"']);
    expect(s.outline).toContain('== drawer "Job log" ==');
    expect(s.outline).toMatch(/button "Stop"$/m);
    expect(s.outline).toContain('== the page ==');
  });

  it('reads a table as rows of cells, with the links in them', async () => {
    page('<table><tr><th>repo</th><th>health</th></tr><tr><td><a href="/projects/scripts">scripts</a></td><td>ok</td></tr></table>');
    const s = await snapshot(world());
    expect(s.outline).toMatch(/table: 2 rows \[e\d+\]/);
    expect(s.outline).toContain('repo | health');
    expect(s.outline).toMatch(/\[e\d+\] link "scripts" → \/projects\/scripts \| ok/);
  });

  it('says so when it had to stop at the size limit', async () => {
    page(Array.from({ length: 60 }, (_, i) => `<p>paragraph number ${i} of the page</p>`).join(''));
    const w = world();
    const cut = await snapshot(w, { max_chars: 300 });
    expect(cut.truncated).toBe(true);
    expect(cut.outline.length).toBeLessThanOrEqual(300);
    const whole = await snapshot(w);
    expect(whole.truncated).toBe(false);
    expect(whole.outline).toContain('paragraph number 59');
  });

  it('says a route has no page frame rather than showing nothing', async () => {
    document.body.innerHTML = `${DOCK}<div>the desktop</div>`;
    const s = await snapshot(world());
    expect(s.outline).toContain('no console page frame');
    expect(s.refs).toBe(0);
  });

  it('reports documents that are loading and ones that failed', async () => {
    page('<p>costs</p>');
    const w = world();
    w.queryClient.setQueryData(['state'], { ok: true });
    await w.queryClient.fetchQuery({ queryKey: ['lake', 'runs'], queryFn: () => Promise.reject(new Error('501 runs on a console')) }).catch(() => undefined);
    void w.queryClient.fetchQuery({ queryKey: ['costs'], queryFn: () => new Promise(() => undefined) }).catch(() => undefined);
    const s = await snapshot(w);
    expect(s.loading).toBe(1);
    expect(s.failed_documents).toEqual(['["lake","runs"]: 501 runs on a console']);
  });

  it('keeps the page’s last uncaught errors once it is watching for them', async () => {
    page('<p>x</p>');
    bridge.watchErrors();
    bridge.watchErrors();
    window.dispatchEvent(new ErrorEvent('error', { message: 'Cannot read properties of undefined' }));
    const s = await snapshot(world());
    expect(s.errors).toHaveLength(1);
    expect(s.errors[0]).toContain('error: Cannot read properties of undefined');
  });
});

describe('refs', () => {
  it('reach the control the snapshot listed', async () => {
    page('<p><button id="a">Alpha</button></p><p><button id="b">Beta</button></p>');
    const hit = vi.fn();
    $('#b').addEventListener('click', hit);
    const w = world();
    await run(w, 'click', { ref: await refFor(w, 'Beta') });
    expect(hit).toHaveBeenCalledTimes(1);
  });

  it('end with the next snapshot', async () => {
    page('<p><button id="a">Alpha</button></p><p><button id="b">Beta</button></p>');
    const w = world();
    const beta = await refFor(w, 'Beta');
    $('#a').remove();
    expect(await refFor(w, 'Beta')).not.toBe(beta);
    const r = await refused(start(w, 'click', { ref: beta }));
    expect(r.kind).toBe('page');
    expect(r.message).toContain('not a ref from the last page_snapshot');
  });

  it('stop working when the control leaves the page', async () => {
    page('<p><button>Run it</button></p>');
    const w = world();
    const ref = await refFor(w, 'Run it');
    $('#main button').remove();
    const r = await refused(start(w, 'click', { ref }));
    expect(r.kind).toBe('page');
    expect(r.message).toContain('no longer on the page');
  });

  it('never reach into the dock, even for a control that moved there after the snapshot', async () => {
    page('<p><button>Run it</button></p>');
    const hit = vi.fn();
    const button = $('#main button');
    button.addEventListener('click', hit);
    const w = world();
    const ref = await refFor(w, 'Run it');
    $('[data-assist-dock]').append(button);
    for (const action of ['click', 'read', 'highlight'] as const) {
      const r = await refused(start(w, action, { ref }));
      expect(r.kind).toBe('page');
      expect(r.message).toContain('dock is not part of the page');
    }
    expect(hit).not.toHaveBeenCalled();
  });
});

describe('click', () => {
  it('clicks the control once and says what it clicked', async () => {
    page('<p><button>Run it</button></p>');
    const hit = vi.fn();
    $('#main button').addEventListener('click', hit);
    const w = world();
    const result = await run(w, 'click', { ref: await refFor(w, 'Run it') });
    expect(hit).toHaveBeenCalledTimes(1);
    expect(result).toMatchObject({ clicked: 'Run it', route_before: '/', route: '/', dialogs: [] });
    expect(w.approve).not.toHaveBeenCalled();
  });

  it('presses the pointer down before the click, as Mantine’s popovers expect', async () => {
    page('<p><button>Pick</button></p>');
    const seen: string[] = [];
    for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) $('#main button').addEventListener(type, () => seen.push(type));
    const w = world();
    await run(w, 'click', { ref: await refFor(w, 'Pick') });
    expect(seen).toEqual(['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']);
  });

  it('follows a link that stays in the console', async () => {
    page('<p><a href="/projects/scripts">scripts</a></p>');
    const followed = vi.fn((e: Event) => e.preventDefault());
    $('#main a').addEventListener('click', followed);
    const w = world();
    await run(w, 'click', { ref: await refFor(w, 'scripts') });
    expect(followed).toHaveBeenCalledTimes(1);
  });

  it.each([
    ['goes to another site', '<a href="https://github.com/bamr87/scripts">GitHub</a>'],
    ['opens a new tab', '<a href="/docs" target="_blank">GitHub</a>'],
    ['downloads a file', '<a href="/export.csv" download>GitHub</a>'],
  ])('leaves a link that %s to the person', async (_name, html) => {
    page(`<p>${html}</p>`);
    const followed = vi.fn((e: Event) => e.preventDefault());
    $('#main a').addEventListener('click', followed);
    const w = world();
    const s = await snapshot(w);
    expect(s.outline).toContain('link "GitHub" (leaves the console: the person opens it)');
    const r = await refused(start(w, 'click', { ref: refOf(s, 'GitHub') }));
    expect(r.kind).toBe('page');
    expect(r.message).toContain('leaves the console');
    expect(followed).not.toHaveBeenCalled();
  });

  it.each([
    ['the disabled attribute', '<button disabled>Deploy</button>'],
    ['aria-disabled', '<button aria-disabled="true">Deploy</button>'],
    ['Mantine’s data-disabled', '<button data-disabled>Deploy</button>'],
  ])('does not click a control disabled by %s', async (_name, html) => {
    page(`<p>${html}</p>`);
    const hit = vi.fn();
    $('#main button').addEventListener('click', hit);
    const w = world();
    const r = await refused(start(w, 'click', { ref: await refFor(w, 'Deploy') }));
    expect(r.kind).toBe('page');
    expect(r.message).toContain('disabled');
    expect(hit).not.toHaveBeenCalled();
  });

  it('leaves a file picker to the person', async () => {
    page('<p><input type="file" aria-label="Upload"></p>');
    const w = world();
    const r = await refused(start(w, 'click', { ref: await refFor(w, 'Upload') }));
    expect(r.message).toContain('file picker');
  });

  it('uses a control in a drawer like any other on the page', async () => {
    page('<p>jobs</p>', '<div class="mantine-Drawer-root"><section role="dialog" aria-label="Job log"><button>Stop</button></section></div>');
    const hit = vi.fn();
    $('.mantine-Drawer-root button').addEventListener('click', hit);
    const w = world();
    const result = await run(w, 'click', { ref: await refFor(w, 'Stop') });
    expect(hit).toHaveBeenCalledTimes(1);
    expect(result.dialogs).toEqual(['drawer "Job log"']);
  });
});

describe('a modal dialog is the person’s to answer', () => {
  it('nothing inside it is clicked', async () => {
    page('<p>x</p>', modal());
    const confirm = vi.fn();
    $('.mantine-Modal-root button').addEventListener('click', confirm);
    const w = world();
    const r = await refused(start(w, 'click', { ref: await refFor(w, 'Confirm') }));
    expect(r.kind).toBe('page');
    expect(r.message).toContain('inside a modal dialog');
    expect(confirm).not.toHaveBeenCalled();
  });

  it('nothing inside it is typed into', async () => {
    page('<p>x</p>', modal('<input aria-label="Reason"><button>Confirm</button>'));
    const w = world();
    const r = await refused(start(w, 'fill', { ref: await refFor(w, 'Reason'), text: 'because' }));
    expect(r.message).toContain('inside a modal dialog');
    expect($<HTMLInputElement>('.mantine-Modal-root input').value).toBe('');
  });

  it('nothing on the page behind it is used either', async () => {
    page('<p><button>Run it</button></p><p><input aria-label="Search"></p>', modal());
    const hit = vi.fn();
    $('#main button').addEventListener('click', hit);
    const w = world();
    const s = await snapshot(w);
    const clicked = await refused(start(w, 'click', { ref: refOf(s, 'Run it') }));
    expect(clicked.message).toContain('a modal dialog is open');
    const filled = await refused(start(w, 'fill', { ref: refOf(s, 'Search'), text: 'x' }));
    expect(filled.message).toContain('a modal dialog is open');
    expect(hit).not.toHaveBeenCalled();
    expect($<HTMLInputElement>('#main input').value).toBe('');
  });

  it('the page is not moved from under it', async () => {
    page('<p>x</p>', modal());
    const w = world();
    const r = await refused(start(w, 'navigate', { path: '/projects' }));
    expect(r.message).toContain('modal dialog is open');
    expect(w.navigate).not.toHaveBeenCalled();
  });

  it('no key but Escape is pressed, and Escape goes to the dialog', async () => {
    page('<p><button>Run it</button></p>', modal());
    const keys: string[] = [];
    $('.mantine-Modal-root [role="dialog"]').addEventListener('keydown', (e) => keys.push((e as KeyboardEvent).key));
    const hit = vi.fn();
    $('.mantine-Modal-root button').addEventListener('click', hit);
    const w = world();
    const ref = await refFor(w, 'Run it');
    for (const key of ['Enter', 'Space', 'Tab']) {
      const r = await refused(start(w, 'press', { key }));
      expect(r.kind).toBe('page');
      expect(r.message).toContain('a modal dialog is open');
    }
    expect(keys).toEqual([]);
    const result = await run(w, 'press', { key: 'Escape', ref });
    expect(keys).toEqual(['Escape']);
    expect(result).toMatchObject({ pressed: 'Escape', effect: 'sent to the page' });
    expect(hit).not.toHaveBeenCalled();
  });

  it.each([
    ['the palette’s root, which stays mounted while it is closed', '<div class="mantine-Spotlight-root"></div>'],
    ['a modal kept mounted but not displayed', '<div class="mantine-Modal-root"><section role="dialog" aria-label="Search" style="display: none"><input aria-label="Find"></section></div>'],
  ])('counts only while it is open: %s blocks nothing', async (_name, closed) => {
    page('<p><button>Run it</button></p>', closed);
    const hit = vi.fn();
    $('#main button').addEventListener('click', hit);
    const w = world();
    const s = await snapshot(w);
    expect(s.dialogs).toEqual([]);
    expect(s.outline).toContain('== the page ==');
    await run(w, 'click', { ref: refOf(s, 'Run it') });
    expect(hit).toHaveBeenCalledTimes(1);
  });
});

describe('fill', () => {
  it('types into a field so the page hears it, and says how much', async () => {
    page('<p><label for="q">Search</label> <input id="q" value="old"></p>');
    const input = $<HTMLInputElement>('#q');
    const heard: string[] = [];
    input.addEventListener('input', () => heard.push(`input:${input.value}`));
    input.addEventListener('change', () => heard.push(`change:${input.value}`));
    const w = world();
    const result = await run(w, 'fill', { ref: await refFor(w, 'Search'), text: 'fleet pulse' });
    expect(input.value).toBe('fleet pulse');
    expect(heard).toEqual(['input:fleet pulse', 'change:fleet pulse']);
    expect(result).toMatchObject({ filled: 'Search', chars: 11 });
  });

  it('types into a text area', async () => {
    page('<p><textarea aria-label="Note"></textarea></p>');
    const w = world();
    await run(w, 'fill', { ref: await refFor(w, 'Note'), text: 'two\nlines' });
    expect($<HTMLTextAreaElement>('textarea').value).toBe('two\nlines');
  });

  it('submits the form when asked to', async () => {
    page('<form><label for="q">Search</label> <input id="q"></form>');
    const submitted = vi.fn((e: Event) => e.preventDefault());
    $('form').addEventListener('submit', submitted);
    const w = world();
    const result = await run(w, 'fill', { ref: await refFor(w, 'Search'), text: 'cron', submit: true });
    expect(submitted).toHaveBeenCalledTimes(1);
    expect(result.then).toMatchObject({ pressed: 'Enter', effect: 'submitted the form' });
  });

  it('does not submit unless asked to', async () => {
    page('<form><label for="q">Search</label> <input id="q"></form>');
    const submitted = vi.fn((e: Event) => e.preventDefault());
    $('form').addEventListener('submit', submitted);
    const w = world();
    await run(w, 'fill', { ref: await refFor(w, 'Search'), text: 'cron' });
    expect(submitted).not.toHaveBeenCalled();
  });

  it('picks a select’s option by its label or its value', async () => {
    page('<p><select aria-label="Sort"><option value="name">Name</option><option value="stars">Stars</option><option value="pushed">Last push</option></select></p>');
    const select = $<HTMLSelectElement>('select');
    const changed = vi.fn();
    select.addEventListener('change', changed);
    const w = world();
    expect(await run(w, 'fill', { ref: await refFor(w, 'Sort'), text: 'Last push' })).toMatchObject({ selected: 'Last push' });
    expect(select.value).toBe('pushed');
    expect(await run(w, 'fill', { ref: await refFor(w, 'Sort'), text: 'stars' })).toMatchObject({ selected: 'Stars' });
    expect(select.value).toBe('stars');
    expect(changed).toHaveBeenCalledTimes(2);
  });

  it('refuses an option the select does not have, and lists the ones it has', async () => {
    page('<p><select aria-label="Sort"><option value="name">Name</option><option value="stars">Stars</option></select></p>');
    const w = world();
    const r = await refused(start(w, 'fill', { ref: await refFor(w, 'Sort'), text: 'Forks' }));
    expect(r.message).toContain('no option "Forks"');
    expect(r.message).toContain('Name, Stars');
    expect($<HTMLSelectElement>('select').value).toBe('name');
  });

  it.each([
    ['a checkbox', '<input type="checkbox" aria-label="Target">', 'click it instead'],
    ['a button', '<button>Target</button>', 'not a text field'],
    ['a read-only picker', '<input readonly aria-label="Target" value="2026-11-22">', 'read-only'],
  ])('does not type into %s', async (_name, html, why) => {
    page(`<p>${html}</p>`);
    const w = world();
    const r = await refused(start(w, 'fill', { ref: await refFor(w, 'Target'), text: 'x' }));
    expect(r.kind).toBe('page');
    expect(r.message).toContain(why);
  });
});

describe('a secret field', () => {
  const FIELDS = `
    <p><label for="pw">Password</label> <input id="pw" type="password" value="hunter2-value"></p>
    <p><input aria-label="Console token" value="token-value-6"></p>`;

  it.each(['Password', 'Console token'])('is never filled: %s', async (name) => {
    page(FIELDS);
    const w = world();
    const r = await refused(start(w, 'fill', { ref: await refFor(w, name), text: 'guess' }));
    expect(r.kind).toBe('page');
    expect(r.message).toContain('secret field');
    expect(r.message).toContain('never filled');
    expect($<HTMLInputElement>('#pw').value).toBe('hunter2-value');
    expect($<HTMLInputElement>('[aria-label="Console token"]').value).toBe('token-value-6');
  });

  it.each(['Password', 'Console token'])('is never read: %s', async (name) => {
    page(FIELDS);
    const w = world('look');
    const r = await refused(start(w, 'read', { ref: await refFor(w, name) }));
    expect(r.kind).toBe('page');
    expect(r.message).toContain('never read');
    expect(r.message).not.toMatch(/value-\d|hunter2/);
  });

  it('is not shown when the region around it is read', async () => {
    page(`<table><tr><td>credentials</td><td><input aria-label="Console token" value="token-value-6"></td></tr></table>`);
    const w = world('look');
    const s = await snapshot(w);
    const table = s.outline.match(/table: 1 row \[(e\d+)\]/)?.[1];
    const read = await run(w, 'read', { ref: table });
    expect(read.text).toContain('secret field "Console token"');
    expect(JSON.stringify(read)).not.toContain('token-value-6');
  });

  it('is pointed at by name only', async () => {
    page(FIELDS);
    const w = world('look');
    const result = await run(w, 'highlight', { ref: await refFor(w, 'Password') });
    expect(result).toEqual({ highlighted: 'the secret field "Password"' });
  });
});

describe('press', () => {
  it('activates a button with Enter and with Space, as a browser would', async () => {
    page('<p><button>Run it</button></p>');
    const hit = vi.fn();
    $('#main button').addEventListener('click', hit);
    const w = world();
    const ref = await refFor(w, 'Run it');
    expect(await run(w, 'press', { key: 'Enter', ref })).toMatchObject({ pressed: 'Enter', on: 'Run it', effect: 'activated the control' });
    expect(await run(w, 'press', { key: 'Space', ref })).toMatchObject({ pressed: 'Space', effect: 'activated the control' });
    expect(hit).toHaveBeenCalledTimes(2);
  });

  it('sends the key the page will read: Space arrives as " "', async () => {
    page('<p><button>Run it</button></p>');
    const keys: [string, string][] = [];
    $('#main button').addEventListener('keydown', (e) => keys.push([(e as KeyboardEvent).key, (e as KeyboardEvent).code]));
    const w = world();
    const ref = await refFor(w, 'Run it');
    await run(w, 'press', { key: 'Space', ref });
    await run(w, 'press', { key: 'ArrowDown', ref });
    expect(keys).toEqual([[' ', 'Space'], ['ArrowDown', 'ArrowDown']]);
  });

  it('does not activate a control whose own key handler took the key', async () => {
    page('<p><button>Run it</button></p>');
    const hit = vi.fn();
    const button = $('#main button');
    button.addEventListener('click', hit);
    button.addEventListener('keydown', (e) => e.preventDefault());
    const w = world();
    expect(await run(w, 'press', { key: 'Enter', ref: await refFor(w, 'Run it') })).toMatchObject({ effect: 'sent to the page' });
    expect(hit).not.toHaveBeenCalled();
  });

  it('goes to the page when no control is named or focused', async () => {
    page('<p>list</p>');
    const keys: string[] = [];
    document.body.addEventListener('keydown', (e) => keys.push((e as KeyboardEvent).key));
    const result = await run(world(), 'press', { key: 'j' });
    expect(keys).toEqual(['j']);
    expect(result).toMatchObject({ pressed: 'j', on: 'the page', effect: 'sent to the page' });
  });

  it('goes to the focused control when none is named, but never to one in the dock', async () => {
    page('<p><input aria-label="Search"></p>');
    const onPage: string[] = [];
    const inDock: string[] = [];
    $('#main input').addEventListener('keydown', (e) => onPage.push((e as KeyboardEvent).key));
    $('[data-assist-dock] input').addEventListener('keydown', (e) => inDock.push((e as KeyboardEvent).key));
    const w = world();
    $('#main input').focus();
    await run(w, 'press', { key: 'ArrowDown' });
    $('[data-assist-dock] input').focus();
    await run(w, 'press', { key: 'ArrowUp' });
    expect(onPage).toEqual(['ArrowDown']);
    expect(inDock).toEqual([]);
  });
});

describe('navigate', () => {
  it('asks the router for an in-app path and reports where the page was', async () => {
    page('<p>x</p>');
    const w = world();
    const result = await run(w, 'navigate', { path: '/projects/scripts?tab=health' });
    expect(w.navigate).toHaveBeenCalledExactlyOnceWith('/projects/scripts?tab=health');
    expect(result).toMatchObject({ route_before: '/', base: '/' });
  });

  it('needs no yes in Ask mode: only a click, a fill and a key press are asked for', async () => {
    page('<p>x</p>');
    const w = world('ask');
    await run(w, 'navigate', { path: '/costs' });
    expect(w.navigate).toHaveBeenCalledExactlyOnceWith('/costs');
    expect(w.approve).not.toHaveBeenCalled();
  });
});

describe('Ask mode: each click, fill and key press waits for a yes', () => {
  it('asks before a click, rings the control while the person decides, and clicks on a yes', async () => {
    page('<p><button>Run it</button></p>');
    const hit = vi.fn();
    $('#main button').addEventListener('click', hit);
    const w = world('ask');
    const ref = await refFor(w, 'Run it');
    const pending = start(w, 'click', { ref });
    expect(w.asked).toEqual([{ id: 'c1', action: 'click', summary: 'Click the button "Run it"', detail: undefined, client: 'dock' }]);
    expect(hit).not.toHaveBeenCalled();
    expect(overlays()).toBeGreaterThan(0);
    w.answer(true);
    expect(await settled(pending)).toMatchObject({ clicked: 'Run it' });
    expect(hit).toHaveBeenCalledTimes(1);
    expect(overlays()).toBe(0);
  });

  it('does nothing on a no, and tells the session that was the person’s answer', async () => {
    page('<p><button>Run it</button></p>');
    const hit = vi.fn();
    $('#main button').addEventListener('click', hit);
    const w = world('ask');
    const pending = start(w, 'click', { ref: await refFor(w, 'Run it') });
    w.answer(false);
    const r = await refused(pending);
    expect(r.kind).toBe('declined');
    expect(r.message).toContain('did not allow it: Click the button "Run it"');
    expect(r.message).toContain('do not retry');
    expect(hit).not.toHaveBeenCalled();
    expect(overlays()).toBe(0);
  });

  it('shows the person the text before it is typed', async () => {
    page('<form><label for="q">Search</label> <input id="q"></form>');
    $('form').addEventListener('submit', (e) => e.preventDefault());
    const w = world('ask');
    const ref = await refFor(w, 'Search');
    const typing = start(w, 'fill', { ref, text: 'fleet pulse' });
    expect(w.asked[0]).toMatchObject({ action: 'fill', summary: 'Type into the textbox "Search"', detail: 'fleet pulse' });
    expect($<HTMLInputElement>('#q').value).toBe('');
    w.answer(true);
    await settled(typing);
    expect($<HTMLInputElement>('#q').value).toBe('fleet pulse');

    const submitting = start(w, 'fill', { ref, text: 'cron', submit: true });
    expect(w.asked[1].summary).toBe('Type into the textbox "Search", then press Enter');
    w.answer(false);
    await refused(submitting);
    expect($<HTMLInputElement>('#q').value).toBe('fleet pulse');
  });

  it('names the key, and the control when there is one', async () => {
    page('<p><button>Run it</button></p>');
    const w = world('ask');
    const ref = await refFor(w, 'Run it');
    const onControl = start(w, 'press', { key: 'Enter', ref });
    expect(w.asked[0]).toMatchObject({ action: 'press', summary: 'Press Enter on the button "Run it"' });
    w.answer(false);
    await refused(onControl);
    const onPage = start(w, 'press', { key: 'ArrowDown' });
    expect(w.asked[1].summary).toBe('Press ArrowDown');
    w.answer(false);
    await refused(onPage);
  });

  it('asks when the console queued the command as needing a yes, whatever the page’s mode is now', async () => {
    page('<p><button>Run it</button></p>');
    const hit = vi.fn();
    $('#main button').addEventListener('click', hit);
    const w = world('act');
    const pending = start(w, 'click', { ref: await refFor(w, 'Run it') }, true);
    expect(w.asked).toHaveLength(1);
    expect(hit).not.toHaveBeenCalled();
    w.answer(true);
    await settled(pending);
    expect(hit).toHaveBeenCalledTimes(1);
  });

  it.each([
    ['a secret field', '<input type="password" aria-label="Target">', '', 'fill'],
    ['a disabled control', '<button disabled>Target</button>', '', 'click'],
    ['a control in a modal', '<p>x</p>', modal('<button>Target</button>'), 'click'],
    ['a control behind a modal', '<button>Target</button>', modal(), 'click'],
    ['a key press while a modal is open', '<button>Target</button>', modal(), 'press'],
  ] as const)('never asks the person about %s: it would not run', async (_name, html, outside, action) => {
    page(`<p>${html}</p>`, outside);
    const w = world('ask');
    const r = await refused(start(w, action, { ref: await refFor(w, 'Target'), text: 'x', key: 'Escape' }));
    expect(r.kind).toBe('page');
    expect(w.approve).not.toHaveBeenCalled();
    expect(overlays()).toBe(0);
  });

  it('checks again after the yes: the control left the page while they decided', async () => {
    page('<p><button>Run it</button></p>');
    const w = world('ask');
    const pending = start(w, 'click', { ref: await refFor(w, 'Run it') });
    $('#main button').remove();
    w.answer(true);
    const r = await refused(pending);
    expect(r.kind).toBe('page');
    expect(r.message).toContain('changed while the person was deciding');
  });

  it('checks again after the yes: the person switched to Look', async () => {
    page('<p><button>Run it</button></p>');
    const hit = vi.fn();
    $('#main button').addEventListener('click', hit);
    const w = world('ask');
    const pending = start(w, 'click', { ref: await refFor(w, 'Run it') });
    w.setMode('look');
    w.answer(true);
    const r = await refused(pending);
    expect(r.kind).toBe('refused');
    expect(hit).not.toHaveBeenCalled();
  });

  it('checks again after the yes: a modal opened, or the control was disabled', async () => {
    page('<p><button id="a">Alpha</button></p><p><button id="b">Beta</button></p>');
    const hit = vi.fn();
    $('#a').addEventListener('click', hit);
    $('#b').addEventListener('click', hit);
    const w = world('ask');
    const s = await snapshot(w);

    const behind = start(w, 'click', { ref: refOf(s, 'Alpha') });
    document.body.insertAdjacentHTML('beforeend', modal());
    w.answer(true);
    expect((await refused(behind)).message).toContain('a modal dialog is open');
    $('.mantine-Modal-root').remove();

    const disabled = start(w, 'click', { ref: refOf(s, 'Beta') });
    $<HTMLButtonElement>('#b').disabled = true;
    w.answer(true);
    expect((await refused(disabled)).message).toContain('disabled');
    expect(hit).not.toHaveBeenCalled();
  });
});

describe('Look mode', () => {
  it('reads a region by its ref', async () => {
    page('<table><tr><th>repo</th><th>health</th></tr><tr><td>scripts</td><td>ok</td></tr></table>');
    const w = world('look');
    const s = await snapshot(w);
    const table = s.outline.match(/table: 2 rows \[(e\d+)\]/)?.[1];
    expect(await run(w, 'read', { ref: table })).toEqual({ ref: table, text: 'repo | health\nscripts | ok', truncated: false });
  });

  it('points at a control with a ring and a note, which go away on their own and are never part of a snapshot', async () => {
    page('<p><button>Run it</button></p>');
    const w = world('look');
    const result = await run(w, 'highlight', { ref: await refFor(w, 'Run it'), note: 'this starts the job' });
    expect(result).toEqual({ highlighted: 'the button "Run it"' });
    expect(document.querySelector('[data-assist-overlay="ring"]')).not.toBeNull();
    expect(document.querySelector('[data-assist-overlay="note"]')?.textContent).toBe('this starts the job');
    const s = await snapshot(w);
    expect(s.outline).not.toContain('this starts the job');
    expect(s.refs).toBe(1);
    await vi.advanceTimersByTimeAsync(6000);
    expect(overlays()).toBe(0);
  });

  it('uses nothing: a click, a fill and a key press are refused and the page is untouched', async () => {
    page('<p><button>Run it</button></p><p><input aria-label="Search"></p>');
    const hit = vi.fn();
    $('#main button').addEventListener('click', hit);
    document.body.addEventListener('keydown', hit);
    const w = world('look');
    const s = await snapshot(w);
    for (const [action, args] of [['click', { ref: refOf(s, 'Run it') }], ['fill', { ref: refOf(s, 'Search'), text: 'x' }], ['press', { key: 'Enter' }]] as const) {
      const r = await refused(start(w, action, args));
      expect(r.kind).toBe('refused');
    }
    expect(hit).not.toHaveBeenCalled();
    expect($<HTMLInputElement>('#main input').value).toBe('');
    expect(w.approve).not.toHaveBeenCalled();
  });
});
