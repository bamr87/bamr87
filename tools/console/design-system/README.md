# @bamr87/harness-console-ui

The Harness Console's design language as React components: tokens, 25 components and one stylesheet, ported from the CSS in `../static/index.html`. The console page itself is still vanilla JS; this package is the reusable, documented form of its visual system and the source for the **Claude Design** sync.

```bash
npm install && npm run build   # dist/index.js, dist/*.d.ts, dist/styles.css
```

## Syncing to Claude Design

Config and authored previews live in `.design-sync/` (committed); `ds-bundle/`, `.ds-sync/` and `dist/` are gitignored build output. Run the `/design-sync` skill from this directory. Conventions the design agent reads are in `.design-sync/conventions.md`.

When the console's CSS changes, update `src/styles.css` to match, rebuild, and re-sync.
