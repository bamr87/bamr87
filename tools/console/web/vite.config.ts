// The Harness Console page. `npm run dev` serves it on :5173 against a running
// console (tools/dash console) on :4001; `npm run build` writes dist/, which
// app.py serves. Name the dev origin in DASH_CONSOLE_ALLOWED_ORIGINS
// (http://localhost:5173) for the Terminal page's WebSocket to be admitted.
//
// The same source also builds the PUBLIC site (tools/console/build-pages.sh →
// GitHub Pages): CONSOLE_BASE=/bamr87/ puts it under the project subpath and
// VITE_STATIC=1 makes it read the static snapshot (../snapshot.py) instead of
// a console's API. Pages cannot send headers, so that build carries its
// Content-Security-Policy as a <meta>: no inline script, and network access
// only to itself, api.github.com and a console on this machine.
//
// A site build (build-pages.sh with CONSOLE_SITE, docs/CONSOLE-PAGES.md) adds
// three inputs, all from _data/profile.yml and the registry, none typed here:
// VITE_FRONT_DOOR (what `/` is), VITE_SITE_MARK (the tab icon, a file of
// public/) and CONSOLE_FRAME_SRC (the launcher's origins, which that page may
// frame). Unset, the build is what it was.
import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';

const CONSOLE = process.env.CONSOLE_URL ?? 'http://127.0.0.1:4001';
const STATIC = process.env.VITE_STATIC === '1';
// Only what an origin looks like reaches the policy: scheme, plain host, port.
const ORIGIN = /^https?:\/\/[A-Za-z0-9.-]+(:\d{1,5})?$/;
const FRAME_SRC = (process.env.CONSOLE_FRAME_SRC ?? '').split(/\s+/).filter((o) => ORIGIN.test(o));
// A plain file name of public/, as site_docs.py checked it.
const MARK = /^[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.(svg|png)$/.test(process.env.VITE_SITE_MARK ?? '') ? process.env.VITE_SITE_MARK! : '';

const PAGES_CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: https://avatars.githubusercontent.com https://github.com",
  "font-src 'self' data:",
  // api.github.com: the GitHub-direct mode. Loopback and https:/wss: hosts: a
  // console the visitor connects on the Connect page (it must send CORS).
  "connect-src 'self' https://api.github.com http://127.0.0.1:* http://localhost:* ws://127.0.0.1:* ws://localhost:* https: wss:",
  // Same-origin frames only: the archify diagrams, sandboxed (HealthPage). A
  // site build also names the launcher's origins, one by one, as the console's
  // own policy does (ADR 0005, decision 4), so its desktop can frame the apps.
  ["frame-src 'self'", ...FRAME_SRC].join(' '),
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join('; ');

function pagesPolicy(): Plugin {
  return {
    name: 'pages-csp',
    transformIndexHtml: (html) =>
      STATIC ? html.replace('<meta charset="utf-8">', `<meta charset="utf-8">\n  <meta http-equiv="Content-Security-Policy" content="${PAGES_CSP}">`) : html,
  };
}

/** A site build's own tab icon, in place of the console's. */
function siteMark(): Plugin {
  const icon = `<link rel="icon" href="%BASE_URL%${MARK}" type="image/${MARK.endsWith('.png') ? 'png' : 'svg+xml'}">`;
  return {
    name: 'site-mark',
    transformIndexHtml: { order: 'pre', handler: (html) => (MARK ? html.replace(/<link rel="icon"[^>]*>/, icon) : html) },
  };
}

export default defineConfig({
  base: process.env.CONSOLE_BASE ?? '/',
  plugins: [react(), pagesPolicy(), siteMark()],
  build: { outDir: process.env.CONSOLE_OUT ?? 'dist', emptyOutDir: true, chunkSizeWarningLimit: 1500, sourcemap: false },
  server: {
    port: 5173,
    proxy: {
      '/api/tui': { target: CONSOLE.replace(/^http/, 'ws'), ws: true },
      '/api': CONSOLE,
      '/theme.css': CONSOLE,
      '/docs': CONSOLE,
      '/openapi.json': CONSOLE,
    },
  },
});
