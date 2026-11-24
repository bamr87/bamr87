// nav.ts is the information architecture: nine sections (keys 1–9), the pages
// in the order ] and [ step through, and which item a path lights up. The base
// path and the front door are build settings, so each is tried both ways.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { NavItem } from './nav';

type Nav = typeof import('./nav');

/** nav.ts as one build sees it: the base path and the front door are build settings. */
async function load(base = '/', frontDoor = ''): Promise<Nav> {
  vi.stubEnv('BASE_URL', base);
  vi.stubEnv('VITE_FRONT_DOOR', frontDoor);
  vi.resetModules();
  return import('./nav');
}

let nav: Nav;
beforeEach(async () => {
  nav = await load();
});

const label = (index: number) => (index < 0 ? null : nav.FLAT[index].label);
const item = (to: string, more: Partial<NavItem> = {}): NavItem => ({ label: 'x', to, icon: nav.FLAT[0].icon, ...more });

describe('appPath', () => {
  it('is the path itself when the app is served at the root', () => {
    expect(nav.appPath('/')).toBe('/');
    expect(nav.appPath('/projects/scripts')).toBe('/projects/scripts');
  });

  it('drops the base path where the app is served under one', async () => {
    const pages = await load('/bamr87/');
    expect(pages.appPath('/bamr87/projects/scripts')).toBe('/projects/scripts');
    expect(pages.appPath('/bamr87/harnesses/health')).toBe('/harnesses/health');
  });

  it('reads the base itself, with or without its slash, as the front door', async () => {
    const pages = await load('/bamr87/');
    expect(pages.appPath('/bamr87/')).toBe('/');
    expect(pages.appPath('/bamr87')).toBe('/');
  });

  it('leaves a path outside the base alone', async () => {
    const pages = await load('/bamr87/');
    expect(pages.appPath('/zer0-mistakes/docs')).toBe('/zer0-mistakes/docs');
    expect(pages.appPath('/')).toBe('/');
  });
});

describe('the map', () => {
  it('has nine sections, one per number key, the profile first', () => {
    expect(nav.NAV).toHaveLength(9);
    expect(nav.NAV[0].label).toBe('Profile');
    expect(new Set(nav.NAV.map((s) => s.label)).size).toBe(9);
    for (const section of nav.NAV) expect(section.items.length, section.label).toBeGreaterThan(0);
  });

  it('lists every page once, in section order', () => {
    expect(nav.FLAT).toEqual(nav.NAV.flatMap((s) => s.items));
    const paths = nav.FLAT.map((i) => i.to);
    expect(new Set(paths).size).toBe(paths.length);
  });

  it('gives every page a label, an icon and a router path (one leading slash, no base, no query)', () => {
    for (const entry of nav.FLAT) {
      expect(entry.label, entry.to).not.toBe('');
      expect(entry.icon, entry.to).toBeTruthy();
      expect(entry.to, entry.label).toMatch(/^\/(?!\/)[^?#]*$/);
    }
  });

  it('has each long-form profile page at /<slug>, in the Profile section', () => {
    const profile = nav.NAV[0].items.map((i) => i.to);
    for (const slug of nav.PROFILE_PAGES) expect(profile).toContain(`/${slug}`);
  });
});

describe('isActive', () => {
  it('lights an item on its own path and on the drill-downs under it', () => {
    const projects = item('/projects');
    expect(nav.isActive(projects, '/projects')).toBe(true);
    expect(nav.isActive(projects, '/projects/scripts')).toBe(true);
    expect(nav.isActive(projects, '/projects/scripts/health')).toBe(true);
  });

  it('does not light an item for a sibling whose path only starts the same', () => {
    expect(nav.isActive(item('/work'), '/workflows')).toBe(false);
    expect(nav.isActive(item('/projects'), '/projects-archive')).toBe(false);
    expect(nav.isActive(item('/projects'), '/')).toBe(false);
  });

  it('lights an exact item on its own path only, with or without a trailing slash', () => {
    const inventory = item('/harnesses', { exact: true });
    expect(nav.isActive(inventory, '/harnesses')).toBe(true);
    expect(nav.isActive(inventory, '/harnesses/')).toBe(true);
    expect(nav.isActive(inventory, '/harnesses/health')).toBe(false);
  });

  it('lights an item for the extra prefixes it names', () => {
    const loops = item('/loops', { match: ['/runs/'] });
    expect(nav.isActive(loops, '/runs/42')).toBe(true);
    expect(nav.isActive(loops, '/jobs/42')).toBe(false);
  });
});

describe('activeIndex', () => {
  it('finds every page from its own path', () => {
    nav.FLAT.forEach((entry, index) => {
      expect(nav.activeIndex(entry.to), entry.to).toBe(index);
    });
  });

  it('prefers the longest match, so a page under another is itself', () => {
    expect(label(nav.activeIndex('/harnesses'))).toBe('Inventory');
    expect(label(nav.activeIndex('/harnesses/health'))).toBe('Health');
    expect(label(nav.activeIndex('/observe/logs'))).toBe('Logs');
  });

  it('prefers the longest match whichever of the two pages is listed first', () => {
    // Two pairs the real map does not have: a page that also lights for everything under it, and a page under it.
    const at = nav.FLAT.length;
    nav.FLAT.push(item('/zz'), item('/zz/deep'), item('/yy/deep'), item('/yy'));
    expect(nav.activeIndex('/zz/deep/x')).toBe(at + 1);
    expect(nav.activeIndex('/zz/other')).toBe(at);
    expect(nav.activeIndex('/yy/deep/x')).toBe(at + 2);
    expect(nav.activeIndex('/yy/other')).toBe(at + 3);
  });

  it('gives a drill-down to the page it belongs to', () => {
    expect(label(nav.activeIndex('/projects/scripts'))).toBe('Projects');
    expect(label(nav.activeIndex('/loops/issue_pipeline'))).toBe('Loops');
    expect(label(nav.activeIndex('/workflows/fleet-pulse'))).toBe('Workflows');
    expect(label(nav.activeIndex('/blog/hello-world'))).toBe('Writing');
    expect(label(nav.activeIndex('/config/budget'))).toBe('Config');
  });

  it('keeps /work and /workflows apart', () => {
    expect(label(nav.activeIndex('/work'))).toBe('Work board');
    expect(label(nav.activeIndex('/workflows'))).toBe('Workflows');
  });

  it('is -1 for a path no page owns', () => {
    expect(nav.activeIndex('/nowhere')).toBe(-1);
    expect(nav.activeIndex('/harness')).toBe(-1);
  });

  it('lights Home on /, and nothing else there', () => {
    expect(label(nav.activeIndex('/'))).toBe('Home');
    expect(nav.FLAT.filter((entry) => nav.isActive(entry, '/')).map((entry) => entry.label)).toEqual(['Home']);
  });
});

describe('a desktop-first build', () => {
  it('puts the Desktop at / and Home at /home, each lit on its own path only', async () => {
    const site = await load('/', 'desktop');
    const name = (path: string) => site.FLAT[site.activeIndex(path)]?.label ?? null;
    expect(name('/')).toBe('Desktop');
    expect(name('/home')).toBe('Home');
    expect(site.FLAT.filter((entry) => site.isActive(entry, '/')).map((entry) => entry.label)).toEqual(['Desktop']);
    expect(name('/projects/scripts')).toBe('Projects');
  });

  it('still lists every page once and finds each from its own path', async () => {
    const site = await load('/', 'desktop');
    const paths = site.FLAT.map((i) => i.to);
    expect(new Set(paths).size).toBe(paths.length);
    site.FLAT.forEach((entry, index) => expect(site.activeIndex(entry.to), entry.to).toBe(index));
  });
});
