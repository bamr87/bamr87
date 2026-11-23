// legacy.ts is a table: the retired site's URLs and the page that replaced
// each. main.tsx turns every row into a redirect, so what can go wrong is a row
// that leads nowhere, shadows a live page, or lands on another redirect.
import { beforeEach, describe, expect, it, vi } from 'vitest';

type Nav = typeof import('../nav');
type Legacy = typeof import('./legacy');

let nav: Nav;
let LEGACY_ROUTES: Legacy['LEGACY_ROUTES'];

beforeEach(async () => {
  vi.stubEnv('BASE_URL', '/');
  vi.stubEnv('VITE_FRONT_DOOR', '');
  vi.resetModules();
  nav = await import('../nav');
  ({ LEGACY_ROUTES } = await import('./legacy'));
});

describe('LEGACY_ROUTES', () => {
  it('names each retired URL as one lower-case path segment', () => {
    const retired = Object.keys(LEGACY_ROUTES);
    expect(retired.length).toBeGreaterThan(0);
    for (const from of retired) expect(from, from).toMatch(/^[a-z0-9][a-z0-9-]*$/);
  });

  it('sends each to a router path (one leading slash, no base, no query)', () => {
    for (const [from, dest] of Object.entries(LEGACY_ROUTES)) {
      expect(dest, from).toMatch(/^\/(?!\/)[^?#]*$/);
    }
  });

  it('sends each to a page the navigation has', () => {
    for (const [from, dest] of Object.entries(LEGACY_ROUTES)) {
      expect(nav.activeIndex(dest), `${from} → ${dest}`).toBeGreaterThanOrEqual(0);
    }
  });

  it('never takes the address of a live page', () => {
    const live = new Set(nav.FLAT.map((entry) => entry.to.split('/')[1]));
    for (const from of Object.keys(LEGACY_ROUTES)) {
      expect(live.has(from), `${from} is a live page`).toBe(false);
    }
  });

  it('never lands on another retired URL', () => {
    const retired = Object.keys(LEGACY_ROUTES);
    for (const [from, dest] of Object.entries(LEGACY_ROUTES)) {
      expect(retired, `${from} → ${dest}`).not.toContain(dest.split('/')[1]);
    }
  });
});
