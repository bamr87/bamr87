# Harness Console UI — conventions

A compact, operator-style UI: warm off-white page, hairline-bordered surfaces, one blue accent, semantic green/amber/red. Everything is plain CSS classes + CSS variables; components carry their own `hc-*` classes. **There are no utility classes — compose with the components and style glue with the tokens below.**

## Wrap everything in `ConsoleRoot`
`ConsoleRoot` defines every colour token, base font (system-ui 14px/1.45) and light/dark palettes. Without it components render with undefined variables (transparent, unreadable). `theme="system"` (default) follows the OS, `"light"`/`"dark"` pin it.

```tsx
<ConsoleRoot theme="light">
  <AppHeader title="🛠️ Harness Console" meta={<Chip tone="ok">● connected</Chip>} actions={<Button>↻ Refresh</Button>} />
  <Tabs items={[{id:'overview',label:'Overview'},{id:'costs',label:'Costs'}]} value="costs" />
  <main style={{ padding: '18px 20px' }}>
    <CardGrid>
      <StatTile label="Spend today" value="$12.40" delta="of $25.00 cap"><Meter value={12.4} max={25} /></StatTile>
    </CardGrid>
    <Toolbar><Button variant="primary">Run daily pulse</Button></Toolbar>
  </main>
</ConsoleRoot>
```

## Tokens (use `var(--…)` for any custom glue)
Surfaces: `--page` (app background), `--surface` (cards, inputs), `--grid` (dividers), `--border` (hairline). Text: `--ink`, `--ink-2` (secondary), `--muted` (tertiary). Accent: `--accent`, `--accent-track`. Semantic: `--good`/`--good-text`, `--warning`/`--warning-track`, `--critical`/`--critical-track`. Series: `--series-2`, `--series-3`. Terminal log colours: `--ansi-red|green|yellow|blue|magenta|cyan`. Never hard-code hex; the dark palette swaps these variables.

## Layout and class vocabulary
- Pages are a stack of `Card`s / `CardGrid` / `Table`s; section titles are 15px/650 — use `<h2 className="hc-h2">`; secondary text `className="hc-sub"` or `hc-muted`.
- Right-align numeric table cells with `className="hc-num"`; tint a `<tr>` with `hc-flag` (amber), `hc-bad` (red) or `hc-sel` (selected).
- Short state words → `Status` (good/warn/crit/info, glyph included). Sentence-length notices → `Banner`, never `Status` (it is nowrap and widens the page).
- Budgets and caps → `Meter` (auto amber ≥70%, red ≥100%). Charts → `ColumnChart`, `BarList`, `PillarMeter`; no other chart styling exists.
- One `variant="primary"` button per toolbar; `variant="danger"` for destructive or credential-writing actions.

## Where the truth lives
Read `styles.css` (it imports `_ds_bundle.css`) for every token and class, and each `components/<group>/<Name>/<Name>.d.ts` and `.prompt.md` for props.
