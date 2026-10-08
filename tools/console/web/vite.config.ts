// The Harness Console page. `npm run dev` serves it on :5173 against a running
// console (tools/dash console) on :4001; `npm run build` writes dist/, which
// app.py serves. Name the dev origin in DASH_CONSOLE_ALLOWED_ORIGINS
// (http://localhost:5173) for the Terminal page's WebSocket to be admitted.
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const CONSOLE = process.env.CONSOLE_URL ?? 'http://127.0.0.1:4001';

export default defineConfig({
  plugins: [react()],
  build: { outDir: 'dist', emptyOutDir: true, chunkSizeWarningLimit: 1500, sourcemap: false },
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
