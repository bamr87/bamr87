# Design-sync notes

- The package is authored here (the console UI is one vanilla `static/index.html`); `src/styles.css` is a port of its CSS with an `hc-` prefix. Keep them in step.
- Build before sync: `npm run build`, then stage `.ds-sync/` and run `resync.mjs` with `--entry ./dist/index.js --node-modules ./node_modules`.
- playwright 1.56 in `.ds-sync` matches the preinstalled `chromium-1194`.

## Re-sync risks
- Upload never happened in the first run (design authorization missing); no `projectId` is pinned and no `_ds_sync.json` anchor exists remotely, so the first upload re-verifies everything.
- Previews use realistic console data inline; nothing is inlined into config.
