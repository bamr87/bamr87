// Mantine's standard PostCSS setup (mantine.dev/getting-started): the preset
// gives CSS modules `rem()`, `light-dark()` and the `@mixin hover` family;
// postcss-simple-vars makes the theme breakpoints usable inside media queries,
// where CSS variables cannot reach. Keep these values equal to theme.breakpoints
// in src/theme.ts — they are static by design.
module.exports = {
  plugins: {
    'postcss-preset-mantine': {},
    'postcss-simple-vars': {
      variables: {
        'mantine-breakpoint-xs': '36em',
        'mantine-breakpoint-sm': '48em',
        'mantine-breakpoint-md': '62em',
        'mantine-breakpoint-lg': '75em',
        'mantine-breakpoint-xl': '88em',
      },
    },
  },
};
