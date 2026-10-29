// Mantine, drawn in the bashOS palette.
//
// No hex value for a BASE role lives here. /theme.css (tools/fleetcore/theme.py —
// the palette the terminal dash registers as `bashos-dark`) defines the roles;
// this file points Mantine's own variables at them, so a colour changed in
// fleetcore changes the browser and the terminal together. The console's OWN
// roles — chart series, meter tracks, ANSI log colours — are declared here too,
// per colour scheme, through the same CSS-variables resolver, so the whole
// theme is one object and no stylesheet carries a palette.
//
// Component defaults live in `components:` (Mantine's Styles API), so a page
// never sets a table or badge class by hand.
import { createTheme, rem, type CSSVariablesResolver } from '@mantine/core';

import tableClasses from './styles/Table.module.css';

/** Layout constants the shell and pages share (theme.other, typed below). */
export const LAYOUT = {
  contentMaxWidth: rem(1480),
  proseMaxWidth: rem(860),
  headerHeight: 54,
  navbarWidth: 236,
} as const;

export const theme = createTheme({
  primaryColor: 'cyan',
  defaultRadius: 'md',
  fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
  fontFamilyMonospace: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
  headings: { fontWeight: '650' },
  cursorType: 'pointer',
  // Static twins of postcss.config.cjs — keep both in step.
  breakpoints: { xs: '36em', sm: '48em', md: '62em', lg: '75em', xl: '88em' },
  other: LAYOUT,
  components: {
    AppShell: {
      styles: {
        main: { background: 'var(--page)' },
        header: { background: 'var(--surface)' },
        navbar: { background: 'var(--surface)' },
      },
    },
    Tooltip: { defaultProps: { withArrow: true, multiline: true, maw: 360, openDelay: 150 } },
    Paper: { defaultProps: { withBorder: true, radius: 'md' } },
    Table: {
      defaultProps: { verticalSpacing: 4, horizontalSpacing: 'sm', highlightOnHover: false, striped: false },
      classNames: { table: tableClasses.table, th: tableClasses.th, td: tableClasses.td, tr: tableClasses.tr },
    },
    Badge: { defaultProps: { radius: 'xl', tt: 'none', fw: 500 } },
    Progress: { defaultProps: { size: 'sm', radius: 'xl' } },
    Kbd: { defaultProps: { size: 'xs' } },
    NavLink: { styles: { root: { borderRadius: 'var(--mantine-radius-sm)' }, label: { fontSize: rem(13.5) } } },
    Alert: { styles: { message: { color: 'var(--ink)' } } },
    Code: { styles: { root: { fontSize: rem(12.5) } } },
  },
});

// Mantine's variables, re-pointed at the fleetcore roles.
const shared = {
  '--mantine-color-body': 'var(--surface)',
  '--mantine-color-text': 'var(--ink)',
  '--mantine-color-dimmed': 'var(--ink-2)',
  '--mantine-color-placeholder': 'var(--muted)',
  '--mantine-color-anchor': 'var(--accent)',
  '--mantine-color-error': 'var(--critical)',
  '--mantine-color-default': 'var(--surface)',
  '--mantine-color-default-hover': 'var(--panel)',
  '--mantine-color-default-color': 'var(--ink)',
  '--mantine-color-default-border': 'var(--grid)',
  '--mantine-primary-color-filled': 'var(--accent)',
  '--mantine-primary-color-filled-hover': 'color-mix(in srgb, var(--accent) 86%, var(--ink))',
  '--mantine-primary-color-light': 'color-mix(in srgb, var(--accent) 14%, transparent)',
  '--mantine-primary-color-light-hover': 'color-mix(in srgb, var(--accent) 22%, transparent)',
  '--mantine-primary-color-light-color': 'var(--accent)',
  // Console roles derived from the base palette (same in both schemes).
  '--track': 'color-mix(in srgb, var(--accent) 16%, transparent)',
  '--warning-track': 'color-mix(in srgb, var(--warning) 22%, transparent)',
  '--critical-track': 'color-mix(in srgb, var(--critical) 18%, transparent)',
  '--good-track': 'color-mix(in srgb, var(--good) 18%, transparent)',
};

// Chart series — validated with the dataviz palette checker against each
// surface (lightness band, chroma, CVD and normal-vision separation) — and
// the ANSI colours job logs are decoded into.
const lightRoles = {
  '--series-1': '#0096a6', '--series-2': '#e0622e',
  '--ansi-red': '#c02b2b', '--ansi-green': '#006300', '--ansi-yellow': '#8a6100',
  '--ansi-blue': '#1f63b8', '--ansi-magenta': '#9c3f9c', '--ansi-cyan': '#0f7180',
};
const darkRoles = {
  '--series-1': '#00a9b5', '--series-2': '#d95926',
  '--ansi-red': '#f08a8a', '--ansi-green': '#5fd35f', '--ansi-yellow': '#e5b53f',
  '--ansi-blue': '#6aa9f0', '--ansi-magenta': '#d69bd6', '--ansi-cyan': '#62c6d4',
};

export const resolver: CSSVariablesResolver = () => ({
  variables: {},
  light: { ...shared, ...lightRoles, '--mantine-primary-color-contrast': '#ffffff' },
  dark: {
    ...shared,
    ...darkRoles,
    '--mantine-primary-color-contrast': 'var(--page)',
    // Mantine's dark scale, re-pointed at the bashOS dark roles.
    '--mantine-color-dark-0': 'var(--ink)',
    '--mantine-color-dark-1': 'var(--ink-2)',
    '--mantine-color-dark-2': 'var(--ink-2)',
    '--mantine-color-dark-3': 'var(--muted)',
    '--mantine-color-dark-4': 'var(--grid)',
    '--mantine-color-dark-5': 'var(--grid)',
    '--mantine-color-dark-6': 'var(--panel)',
    '--mantine-color-dark-7': 'var(--surface)',
    '--mantine-color-dark-8': 'var(--page)',
    '--mantine-color-dark-9': 'var(--page)',
  },
});

/** The role colour for a status tone — a CSS variable from the fleetcore palette. */
export type Tone = 'good' | 'warn' | 'crit' | 'info';
export const toneColor: Record<Tone, string> = {
  good: 'var(--good)',
  warn: 'var(--warning)',
  crit: 'var(--critical)',
  info: 'var(--muted)',
};

declare module '@mantine/core' {
  export interface MantineThemeOther {
    contentMaxWidth: string;
    proseMaxWidth: string;
    headerHeight: number;
    navbarWidth: number;
  }
}
