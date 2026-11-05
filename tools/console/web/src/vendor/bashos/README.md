# vendor/bashos — the bashOS shell, vendored

> The layout reducer of the bashOS desktop, copied byte-identical from `bamr87/bashos`, so the console's Desktop page is the bashOS OS shell and not a look-alike.

| File | What it is |
| --- | --- |
| `shell.js` | `src/bashos/gui/web/shell.js` from [bamr87/bashos](https://github.com/bamr87/bashos): pure functions over a plain object (windows, focus, snap, minimize, arrange, the shareable layout v1). No DOM, no fetch, no dependency. **Never edited here.** |
| `shell.d.ts` | The TypeScript shapes of that module, written in the hub because the upstream file is plain JavaScript by rule (the bashOS GUI has no build step). |

**Provenance.** Copied from bashos at `7bf95a5` (the file last changed in `d918f5d`, 2026-09-15). Its SHA-256 is recorded in `tools/console/test_bashos_shell.py`, which fails if the copy is edited and, where the `projects/bashos` submodule is checked out, if it has fallen behind upstream.

**Changing it.** Improve it in bashos first (its own gate is `node --test tests/shell.test.mjs`), then copy the file here and update the recorded hash in the same PR. When bashos publishes its JavaScript runtime as `@bamr87/bashos` (docs/TERMINAL-FRAMEWORK.md § 3.5), this directory becomes an import.

What the console adds around it (`../../pages/Desktop.tsx`): the scenes it opens (`app`, a fleet frontend from the launcher; `welcome`), the React components that draw the state, and the check that a shared layout names only apps the registry declares.
