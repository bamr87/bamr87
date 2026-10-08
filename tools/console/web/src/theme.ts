// Mantine, drawn in the bashOS palette.
//
// No hex value lives here. /theme.css (tools/fleetcore/theme.py — the palette
// the terminal dash registers as `bashos-dark`) defines the roles; this file
// only points Mantine's own variables at them, so a colour changed in
// fleetcore changes the browser and the terminal together.
import { createTheme, type CSSVariablesResolver } from '@mantine/core';

export const theme = createTheme({
  primaryColor: 'cyan',
  defaultRadius: 'md',
  fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
  fontFamilyMonospace: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
  headings: { fontWeight: '650' },
  cursorType: 'pointer',
  components: {
    Tooltip: { defaultProps: { withArrow: true, multiline: true, maw: 360, openDelay: 150 } },
    Paper: { defaultProps: { withBorder: true, radius: 'md' } },
  },
});

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
};

export const resolver: CSSVariablesResolver = () => ({
  variables: {},
  light: { ...shared, '--mantine-primary-color-contrast': '#ffffff' },
  dark: {
    ...shared,
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
