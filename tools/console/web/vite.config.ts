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
import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';

const CONSOLE = process.env.CONSOLE_URL ?? 'http://127.0.0.1:4001';
const STATIC = process.env.VITE_STATIC === '1';

const PAGES_CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: https://avatars.githubusercontent.com https://github.com",
  "font-src 'self' data:",
  // api.github.com: the GitHub-direct mode. Loopback and https:/wss: hosts: a
  // console the visitor connects on the Connect page (it must send CORS).
  "connect-src 'self' https://api.github.com http://127.0.0.1:* http://localhost:* ws://127.0.0.1:* ws://localhost:* https: wss:",
  // Same-origin frames only: the archify diagrams, sandboxed (HealthPage).
  "frame-src 'self'",
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

export default defineConfig({
  base: process.env.CONSOLE_BASE ?? '/',
  plugins: [react(), pagesPolicy()],
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
