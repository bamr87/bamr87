# Design-sync notes

- The package is authored here (it ported the CSS of the console's old hand-written page, removed 2026-10; the live page is `../web/`, on Mantine). `src/styles.css` keeps that look with an `hc-` prefix.
- Build before sync: `npm run build`, then stage `.ds-sync/` and run `resync.mjs` with `--entry ./dist/index.js --node-modules ./node_modules`.
- playwright 1.56 in `.ds-sync` matches the preinstalled `chromium-1194`.

## Re-sync risks
- Upload never happened in the first run (design authorization missing); no `projectId` is pinned and no `_ds_sync.json` anchor exists remotely, so the first upload re-verifies everything.
- Previews use realistic console data inline; nothing is inlined into config.
