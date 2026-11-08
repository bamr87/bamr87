// What this browser remembers about how it uses the console: the open sidebar
// sections and the recently visited pages. Nothing here is fleet state, so a
// private window that refuses storage simply starts fresh each load.
export function readPref<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    return raw === null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}

export function writePref(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* private window: the preference lives for this page load only */
  }
}

export interface RecentPage { path: string; label: string }

const RECENT_KEY = 'console_recent';
const RECENT_MAX = 6;

export const recentPages = (): RecentPage[] => {
  const list = readPref<RecentPage[]>(RECENT_KEY, []);
  return Array.isArray(list) ? list : [];
};

/** The newest visit first; a page visited again moves up rather than repeating. */
export function rememberPage(page: RecentPage): void {
  writePref(RECENT_KEY, [page, ...recentPages().filter((r) => r.path !== page.path)].slice(0, RECENT_MAX));
}
