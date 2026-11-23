// Vitest's settings for the page's unit tests, in the file the fleet standard
// names (UPS-QA-12) and the fleet's other apps use. It stands apart from
// vite.config.ts on purpose: a test run takes nothing from the page build's
// inputs (CONSOLE_BASE, VITE_STATIC, …), and a build never loads Vitest.
//
// The tests sit beside the module they test (src/**/*.test.ts) and run in
// plain Node, unless a file asks for a DOM in its first line
// (`// @vitest-environment jsdom`). A test names the globals and build
// settings it needs (vi.stubGlobal, vi.stubEnv), and each is put back after
// the test. Nothing imports a test file, so none reaches the bundle.
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['src/**/*.test.ts'],
    environment: 'node',
    unstubEnvs: true,
    unstubGlobals: true,
    restoreMocks: true,
    // Several tests load a module fresh (vi.resetModules, then import), which
    // re-transforms it. On a loaded machine that took past Vitest's 5 s test
    // and 10 s hook defaults (2026-11-23, load average 10); a few seconds is
    // the normal run, so a longer ceiling hides nothing.
    testTimeout: 30_000,
    hookTimeout: 30_000,
  },
});
