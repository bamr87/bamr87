// One-shot build: ESM JS via esbuild, .d.ts via tsc, stylesheet copied verbatim.
import { build } from 'esbuild';
import { execFileSync } from 'node:child_process';
import { cpSync, rmSync } from 'node:fs';

rmSync('dist', { recursive: true, force: true });
await build({
  entryPoints: ['src/index.ts'],
  outfile: 'dist/index.js',
  bundle: true,
  format: 'esm',
  jsx: 'automatic',
  external: ['react', 'react-dom', 'react/jsx-runtime'],
});
execFileSync('npx', ['tsc', '-p', 'tsconfig.json'], { stdio: 'inherit' });
cpSync('src/styles.css', 'dist/styles.css');
