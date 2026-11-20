'use client';
/**
 * AssistBridge — React adapter for the fleet's page bridge (<fleet-assist>).
 * Spec: bamr87/bamr87 specs/ASSIST.md (UPS-AST). Kit: templates/assistant.
 *
 * Mount ONCE in the AppShell, inside the router, and say when it is on:
 *
 *   // Vite + React Router
 *   const navigate = useNavigate();
 *   <AssistBridge enabled={import.meta.env.DEV} repo="bamr87/gitorio" navigate={navigate}
 *                 base={import.meta.env.BASE_URL} route={pathname} />
 *
 * `enabled` has no default on purpose: this is a tool for whoever runs the app,
 * so the app decides, and a production build that passes false ships no tag and
 * loads no script. `navigate` hands the app's router over, so an assistant
 * session moves between routes the way a click on a link does instead of
 * loading the address; without it navigating reloads the page (and the shared
 * session carries on after the load).
 *
 * `provideDocument('cart', () => store.getState().cart)` lets a session read a
 * document the page holds (page_data). Never hand over a credential.
 *
 * Works under React 18 and 19, Vite and Next (client components): it touches
 * neither the removed global JSX namespace nor `import.meta.env`.
 * Next.js App Router: use adapters/nextjs.tsx, which wires its router in.
 */
import { useEffect } from 'react';

/* React 19 removed the global JSX namespace; augmenting `react` itself is the
   form that compiles on both 18 and 19. */
declare module 'react' {
  namespace JSX {
    interface IntrinsicElements {
      'fleet-assist': React.DetailedHTMLProps<React.HTMLAttributes<HTMLElement>, HTMLElement> &
        Record<string, string | undefined>;
    }
  }
}

interface FleetAssistApi {
  open: () => void;
  close: () => void;
  state?: () => { open: boolean; mode: string; shared: boolean; paired: number };
  configure: (options: { navigate?: ((path: string) => void) | null; base?: string | null; root?: string | null; pages?: (() => string[]) | null }) => void;
  provide: (key: string, read: () => unknown) => void;
  version: string;
}

function api(): FleetAssistApi | undefined {
  return typeof window === 'undefined'
    ? undefined
    : (window as unknown as { FleetAssist?: FleetAssistApi }).FleetAssist;
}

/** Open the panel from the app's own menu or shortcut. */
export function openAssist(): void {
  api()?.open();
}

/** A document a session may read with page_data: provideDocument('filters', () => filters). */
export function provideDocument(key: string, read: () => unknown): void {
  const set = () => api()?.provide(key, read);
  if (api()) set();
  else if (typeof window !== 'undefined') window.addEventListener('fleet-assist:ready', set, { once: true });
}

export interface AssistBridgeProps {
  /** Required: pass your build's development flag. False renders nothing and loads nothing. */
  enabled: boolean;
  /** `owner/name` — tells a session which repo this app is. */
  repo: string;
  branch?: string;
  /** Route or pathname of the current view: what a session looks for in the router. */
  route?: string;
  /** Repo-relative source file of the current view, when the route maps to one. */
  source?: string;
  /** The app's path prefix (Vite `import.meta.env.BASE_URL`, Next `basePath`). */
  base?: string;
  /** The router's navigate: `useNavigate()` or `router.push`. */
  navigate?: (path: string) => void;
  /** Site-map lines a snapshot carries, e.g. ['Home /', 'Reports /reports']. */
  pages?: () => string[];
  /** CSS selector of the page frame, when it is not the <main> element. */
  root?: string;
  framework?: string;
  env?: string;
  appVersion?: string;
  /** The Harness Console on this machine; only a loopback address is accepted. */
  broker?: string;
  position?: 'left' | 'right';
  /** Where the payload is served from (vendor it into public/; never hot-link the hub). */
  scriptSrc?: string;
}

const DEFAULT_SRC = '/fleet-assist.js';

export function AssistBridge({
  enabled,
  repo,
  branch = 'main',
  route,
  source,
  base,
  navigate,
  pages,
  root,
  framework = 'react',
  env,
  appVersion,
  broker,
  position = 'left',
  scriptSrc = DEFAULT_SRC,
}: AssistBridgeProps) {
  useEffect(() => {
    if (!enabled) return;
    const configure = () => {
      api()?.configure({ navigate: navigate ?? null, base: base ?? null, root: root ?? null, pages: pages ?? null });
      window.dispatchEvent(new Event('fleet-assist:ready'));
    };
    if (api()) {
      configure();
      return;
    }
    let s = document.querySelector<HTMLScriptElement>(`script[src="${scriptSrc}"]`);
    if (!s) {
      s = document.createElement('script');
      s.src = scriptSrc;
      s.async = true;
      document.head.appendChild(s);
    }
    s.addEventListener('load', configure, { once: true });
    return () => s?.removeEventListener('load', configure);
  }, [enabled, navigate, base, root, pages, scriptSrc]);

  if (!enabled) return null;
  return (
    <fleet-assist
      repo={repo}
      branch={branch}
      route={route}
      source={source}
      base={base}
      root={root}
      framework={framework}
      env={env}
      app-version={appVersion}
      broker={broker}
      position={position}
    />
  );
}

export default AssistBridge;
