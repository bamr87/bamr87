import type { HTMLAttributes } from 'react';
import { cx } from './cx';

export interface ConsoleRootProps extends HTMLAttributes<HTMLDivElement> {
  /** `light` or `dark` pins the palette; `system` (default) follows the OS preference. */
  theme?: 'light' | 'dark' | 'system';
}

/**
 * Root wrapper for the Harness Console design language. Defines every colour
 * token (`--page`, `--surface`, `--ink`, `--accent`, …), the base typography
 * and the light/dark palettes. Wrap the whole app (or each preview) in it.
 */
export function ConsoleRoot({ theme = 'system', className, children, ...rest }: ConsoleRootProps) {
  return (
    <div {...rest} className={cx('hc-root', className)} data-theme={theme === 'system' ? undefined : theme}>
      {children}
    </div>
  );
}
