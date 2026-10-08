// The one fetch path to the console API.
//
// When the console runs with DASH_CONSOLE_TOKEN, every /api route wants
// `Authorization: Bearer …`. The token is asked for ONCE however many requests
// hit a 401 at the same moment (the first paint fires several in parallel): they
// all wait on one prompt, and a rejected token is SAID rather than looking like
// a failed load. The prompt itself is <TokenGate/>, which subscribes here.

const STORE_KEY = 'console_token';

function readToken(): string {
  try {
    return localStorage.getItem(STORE_KEY) ?? '';
  } catch {
    return '';
  }
}

let token = readToken();
let pending: Promise<string | null> | null = null;

type Asker = (rejected: boolean) => Promise<string | null>;
let asker: Asker | null = null;

/** <TokenGate/> registers the dialog that answers token requests. */
export function registerTokenAsker(fn: Asker | null): void {
  asker = fn;
}

export function currentToken(): string {
  return token;
}

function setToken(value: string | null): void {
  token = value ?? '';
  try {
    if (value) localStorage.setItem(STORE_KEY, value);
    else localStorage.removeItem(STORE_KEY);
  } catch {
    /* private window: the token lives for this page load only */
  }
}

/** Ask once; concurrent callers share the same answer. */
export function askToken(rejected: boolean): Promise<string | null> {
  if (!pending) {
    const run = asker ? asker(rejected) : Promise.resolve(null);
    pending = run.then((value) => {
      pending = null;
      const clean = (value ?? '').trim().replace(/^bearer\s+/i, '').trim();
      if (clean) setToken(clean);
      return clean || null;
    });
  }
  return pending;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, init: RequestInit = {}, attempt = 0): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  const sent = token;
  if (sent) headers.set('Authorization', `Bearer ${sent}`);
  const res = await fetch(path, { ...init, headers });
  if (res.status === 401) {
    // Another request already obtained a new token while this one was in flight.
    if (token && token !== sent) return api<T>(path, init, attempt);
    if (sent) setToken(null);
    if (attempt >= 3) throw new ApiError(401, 'console token rejected three times — check DASH_CONSOLE_TOKEN');
    const next = await askToken(Boolean(sent));
    if (!next) throw new ApiError(401, 'console token required');
    return api<T>(path, init, attempt + 1);
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = (body as { detail?: unknown }).detail;
    throw new ApiError(res.status, typeof detail === 'string' ? detail : `${res.status} ${res.statusText}`);
  }
  return body as T;
}

export const post = <T>(path: string, body: unknown) => api<T>(path, { method: 'POST', body: JSON.stringify(body) });
export const put = <T>(path: string, body: unknown) => api<T>(path, { method: 'PUT', body: JSON.stringify(body) });
export const del = <T>(path: string) => api<T>(path, { method: 'DELETE' });
