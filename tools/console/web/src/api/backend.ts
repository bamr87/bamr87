// Which backend this page talks to. One app, three ways to run it:
//
//   console   — served BY a console (tools/dash console): every /api path is
//               that process, same origin. The local control plane, as before.
//   snapshot  — the public build on GitHub Pages (VITE_STATIC=1): every GET is
//               a file the build wrote (../snapshot.py → static.ts), updated by
//               build-dash.yml. Read-only on its own.
//   remote    — the public build pointed at a running console (Connect page):
//               a console URL + its bearer token, kept in this browser. The
//               page then has everything the console has. The console admits
//               it only while it requires a token (app.py, remote_page).
//
// Independently of those, the public build can hold a GitHub token (Connect
// page) and act on GitHub directly from the browser — live repo views, the
// console's issue/run/workflow writes, and dispatching the control-plane
// workflows (ghdirect.ts). A console has its own GitHub link, so with a console
// connected that token is not used.

export const STATIC = import.meta.env.VITE_STATIC === '1';
/** The path the app is served under: '/' from a console, '/bamr87/' on Pages. */
export const BASE = import.meta.env.BASE_URL;
/** For React Router: BASE without its trailing slash ('' at the root). */
export const BASENAME = BASE.replace(/\/$/, '');

const REMOTE_KEY = 'console_remote_url';
const GH_KEY = 'gh_direct_token';

function read(store: Storage | undefined, key: string): string {
  try {
    return store?.getItem(key) ?? '';
  } catch {
    return '';
  }
}

function write(store: Storage | undefined, key: string, value: string | null): void {
  try {
    if (value) store?.setItem(key, value);
    else store?.removeItem(key);
  } catch {
    /* private window: the value lives for this page load only */
  }
}

const local = typeof window !== 'undefined' ? window.localStorage : undefined;
const session = typeof window !== 'undefined' ? window.sessionStorage : undefined;

let remote = STATIC ? read(local, REMOTE_KEY) : '';
let ghToken = STATIC ? read(session, GH_KEY) || read(local, GH_KEY) : '';

export type Mode = 'console' | 'snapshot' | 'remote';

export function mode(): Mode {
  if (!STATIC) return 'console';
  return remote ? 'remote' : 'snapshot';
}

/** A console answers /api (same origin, or the connected remote one). */
export const hasConsole = () => mode() !== 'snapshot';

/** Where /api/... goes when a console answers it: '' (same origin) or the remote URL. */
export const consoleOrigin = () => (mode() === 'remote' ? remote : '');

export function setRemoteConsole(url: string | null): void {
  remote = (url ?? '').trim().replace(/\/+$/, '');
  write(local, REMOTE_KEY, remote || null);
}

// --- the browser-held GitHub token (public build only) ---------------------
/** True when the page talks to api.github.com itself (public build, no console). */
export const githubDirect = () => mode() === 'snapshot';
export const githubToken = () => ghToken;
export const githubRemembered = () => Boolean(read(local, GH_KEY));

/** remember=false keeps it in this tab only (sessionStorage); true, on this device. */
export function setGithubToken(token: string | null, remember = false): void {
  ghToken = (token ?? '').trim();
  write(session, GH_KEY, ghToken && !remember ? ghToken : null);
  write(local, GH_KEY, ghToken && remember ? ghToken : null);
}

/** A URL to a file the app ships (public/ or the snapshot), under BASE. */
export const asset = (path: string) => `${BASE}${path.replace(/^\/+/, '')}`;
