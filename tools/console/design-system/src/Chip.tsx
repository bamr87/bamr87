import type { HTMLAttributes } from 'react';
import { cx } from './cx';

export interface ChipProps extends HTMLAttributes<HTMLSpanElement> {
  /** `ok` outlines the chip green, `bad` red; `neutral` leaves the border subtle. */
  tone?: 'neutral' | 'ok' | 'bad';
}

/** Small rounded label for header metadata such as a branch, a count or a connection state. */
export function Chip({ tone = 'neutral', className, ...rest }: ChipProps) {
  return <span {...rest} className={cx('hc-chip', tone !== 'neutral' && `hc-${tone}`, className)} />;
}
