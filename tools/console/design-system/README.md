# @bamr87/harness-console-ui

The Harness Console's earlier design language as React components: tokens, 25 components and one stylesheet, ported from the CSS of the hand-written page the console used until 2026-10. The live console page is now [`../web/`](../web/README.md) (React on Mantine, drawn from the same fleetcore palette); this package stays as the documented form of the earlier look and the source for the **Claude Design** sync.

```bash
npm install && npm run build   # dist/index.js, dist/*.d.ts, dist/styles.css
```

## Syncing to Claude Design

Config and authored previews live in `.design-sync/` (committed); `ds-bundle/`, `.ds-sync/` and `dist/` are gitignored build output. Run the `/design-sync` skill from this directory. Conventions the design agent reads are in `.design-sync/conventions.md`.

When the console's CSS changes, update `src/styles.css` to match, rebuild, and re-sync.
