import type { HTMLAttributes } from 'react';
import { cx } from './cx';

export interface ToolbarProps extends HTMLAttributes<HTMLDivElement> {}

/** Wrapping row of buttons, selects, inputs and inline labels placed above a table or panel. */
export function Toolbar({ className, ...rest }: ToolbarProps) {
  return <div {...rest} className={cx('hc-toolbar', className)} />;
}
